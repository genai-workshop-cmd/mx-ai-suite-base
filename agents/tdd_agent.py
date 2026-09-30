"""Agent 2 - TDD Agent (blueprint section 4).

Consumes the approved FDD and produces a Technical Design Document detailed
enough for a Maximo developer to implement without asking questions, plus the
structured handover tokens that route work to Agent 3A and/or 3B.
"""
from __future__ import annotations

import json
from typing import Any

from core.models import Artifact, ChangeItem, DuplicateDecision, Phase
from rendering.docx_writer import render

from .base import BaseAgent, Composition

#: Change types that are implemented as an automation script, and the launch
#: point each uses. Integration is deliberately absent: MIF interfaces are
#: configuration (Publish Channel / Enterprise Service), not Jython, and Agent
#: 3B owns them.
_LAUNCH_POINTS = {
    "customisation": "OBJECT",
    "workflow": "ACTION",
}


class TDDAgent(BaseAgent):
    agent_id = "2"
    name = "TDD Agent"
    phase = Phase.TDD
    doc_type = "tdd"
    role = (
        "Convert an approved Functional Design Document into a step-by-step "
        "Technical Design Document that a Maximo developer can implement without "
        "ambiguity, and emit handover tokens for the build agents."
    )
    inputs_description = (
        "- The approved FDD for this run\n"
        "- The classified change items\n"
        "- Validated Maximo object and attribute facts"
    )
    output_format = (
        "Markdown following exactly these sections:\n"
        "# Technical Design Document\n"
        "## 1. Document Control\n"
        "## 2. Solution Overview\n"
        "## 3. Change Register   (table: CI ID | Change | Type | Object | Build Agent)\n"
        "## 4. Database Configuration\n"
        "## 5. Application Configuration\n"
        "## 6. Automation Scripts   (one subsection per script, with a Jython outline in a fenced block)\n"
        "## 7. Integration Design\n"
        "## 8. Security\n"
        "## 9. Estimation   (table: CI ID | Change | Effort (hrs) | Skill | Risk)\n"
        "## 10. Implementation Sequence\n"
        "Jython must use the MBO API (mbo.getString, mbo.setValue, MboConstants), never raw SQL."
    )
    skill_files = ("mx_core_SKILL.md", "mx_tech_config_SKILL.md", "ma_autoscript_SKILL.md", "mx_pm_wo_SKILL.md")

    # -- gather ------------------------------------------------------------
    def gather(self) -> dict[str, Any]:
        process = self.ctx.process
        items = self.change_items()
        for item in items:
            self.ctx.validator.check_change_item(item, process, self.report)

        self._estimate(items, process)

        scripts = self._plan_scripts(items, process)
        for script in scripts:
            self.report.add(self.ctx.validator.script_name_free(script["name"]))

        fdd = self._approved_fdd()
        return {
            "change_items": items,
            "scripts": scripts,
            "fdd_excerpt": fdd,
            "prior_art": self.prior_art(),
            "attribute_specs": {
                f"{i.maximo_object}.{i.maximo_attribute}": self.ctx.validator.attribute_spec(
                    i.maximo_object, i.maximo_attribute
                )
                for i in items
                if i.maximo_object and i.maximo_attribute
            },
        }

    def _approved_fdd(self) -> str:
        """Body of the FDD produced earlier in this run, if any."""
        result = self.ctx.state.result(Phase.FDD)
        if result:
            for artifact in result.artifacts:
                if artifact.name.endswith(".md") and "flag" not in artifact.name.lower():
                    from pathlib import Path

                    path = Path(artifact.path)
                    if path.exists():
                        return path.read_text(encoding="utf-8")[:20000]
        return "(no FDD from this run - working from the change items directly)"

    #: Effort for a requirement that refines a deliverable already being built,
    #: as a fraction of the full baseline. Several requirement lines routinely
    #: describe one interface or one script; charging each of them the full
    #: baseline would over-estimate the release several times over.
    ADDITIONAL_REQUIREMENT_FACTOR = 0.15

    def _estimate(self, items: list[ChangeItem], process: dict) -> None:
        """Effort, skill and risk per change item, from process baselines.

        Estimation is per *deliverable*, not per requirement line. Items that
        build the same thing - one interface on one object, one script on one
        object - share a baseline: the first carries it, the rest carry a
        refinement increment.
        """
        estimation = process.get("estimation", {}) or {}
        multipliers = estimation.get("risk_multiplier", {}) or {}
        skills = {
            "config": "junior",
            "security": "junior",
            "data": "mid",
            "report": "mid",
            "workflow": "senior",
            "customisation": "senior",
            "integration": "architect",
        }
        #: Change types where several requirements collapse into one build item.
        consolidating = {"integration", "customisation", "workflow"}
        seen_deliverables: set[tuple[str, str]] = set()
        # Match how the build agents resolve a missing object, so estimation
        # groups exactly as Agent 3A/3B will actually build.
        primary_objects = (process.get("objects", {}) or {}).get("primary") or ["WORKORDER"]
        default_object = primary_objects[0]

        for item in items:
            change_type = item.change_type.value
            base = float(estimation.get(change_type, 8))

            # Unconfirmed Maximo names mean discovery work, so risk rises.
            unconfirmed = any(
                not r.exists and item.maximo_object and item.maximo_object in r.name
                for r in self.report.results
            )
            if unconfirmed:
                item.risk = "high"
            elif change_type in {"integration", "workflow"}:
                item.risk = "medium"
            else:
                item.risk = "low" if item.confidence >= 0.8 else "medium"

            if change_type in consolidating:
                key = (change_type, item.maximo_object or default_object)
                if key in seen_deliverables:
                    base *= self.ADDITIONAL_REQUIREMENT_FACTOR
                else:
                    seen_deliverables.add(key)

            item.effort_hours = round(base * float(multipliers.get(item.risk, 1.0)), 1)
            item.skill_level = skills.get(change_type, "mid")

    def _plan_scripts(self, items: list[ChangeItem], process: dict) -> list[dict[str, Any]]:
        """One script per (object, launch point).

        Several requirements usually describe one piece of logic on the same
        object - "copy the value" and "do not overwrite an existing value" are
        two rules inside a single script, not two scripts. Emitting one per
        requirement would produce launch points that fight each other.
        """
        prefix = (process.get("naming", {}) or {}).get("autoscript_prefix", "MX")
        grouped: dict[tuple[str, str], dict[str, Any]] = {}

        for item in items:
            if item.change_type.value not in _LAUNCH_POINTS:
                continue
            launch_point = _LAUNCH_POINTS[item.change_type.value]
            target = item.maximo_object or "WORKORDER"
            key = (target, launch_point)

            existing = grouped.get(key)
            if existing is None:
                grouped[key] = {
                    "name": f"{prefix}_{target}_{len(grouped) + 1:02d}",
                    "launch_point": launch_point,
                    "object": target,
                    "event": "Add, Update" if item.change_type.value == "customisation" else "Action",
                    "change_items": [item.id],
                    "purpose": item.title,
                    "rules": [item.description],
                    "attribute": item.maximo_attribute or "",
                }
            else:
                existing["change_items"].append(item.id)
                existing["rules"].append(item.description)
                existing["attribute"] = existing["attribute"] or (item.maximo_attribute or "")

        scripts = list(grouped.values())
        for s in scripts:
            # Keep the single-id field the build agent and templates expect.
            s["change_item"] = ", ".join(s["change_items"])
        return scripts

    # -- compose -----------------------------------------------------------
    def compose(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> Composition:
        text, generated_by = self.ask_model(self._user_prompt(facts, duplicate), max_tokens=9000)
        if text:
            body, flags = self.parse_flags(text, "TDD")
        else:
            body = self._deterministic(facts)
            flags = []
            generated_by = "deterministic"

        handover = self._handover(facts)
        total = sum(i.effort_hours for i in facts["change_items"])
        summary = (
            f"TDD for {len(facts['change_items'])} change item(s), "
            f"{len(facts['scripts'])} automation script(s), estimated {total:.1f} hours. "
            f"Handover: {handover['summary']}."
        )
        return Composition(
            body=body, summary=summary, flags=flags, generated_by=generated_by, handover=handover
        )

    def _user_prompt(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> str:
        items = "\n".join(
            f"- {i.id} [{i.change_type.value}] {i.title}\n"
            f"  object={i.maximo_object or '?'} attribute={i.maximo_attribute or '?'} "
            f"effort={i.effort_hours}h skill={i.skill_level} risk={i.risk}\n"
            f"  {i.description[:300]}"
            for i in facts["change_items"]
        )
        scripts = "\n".join(
            f"- {s['name']}: {s['launch_point']} launch point on {s['object']} ({s['event']}) - {s['purpose']}"
            for s in facts["scripts"]
        ) or "(no automation scripts required)"
        specs = "\n".join(
            f"- {k}: {v}" for k, v in facts["attribute_specs"].items() if v
        ) or "(no existing attribute specifications retrieved)"

        return (
            f"RUN: {self.ctx.state.title}\nBUSINESS PROCESS: {self.ctx.process_name}\n\n"
            f"APPROVED FDD:\n{facts['fdd_excerpt']}\n\n"
            f"CHANGE ITEMS (with estimation already computed - reproduce these numbers exactly):\n{items}\n\n"
            f"AUTOMATION SCRIPTS TO SPECIFY (use these exact names):\n{scripts}\n\n"
            f"EXISTING ATTRIBUTE SPECIFICATIONS FROM MAXIMO:\n{specs}\n\n"
            f"VALIDATED MAXIMO FACTS:\n{self.validated_facts_block()}\n\n"
            f"Write the Technical Design Document now.{self.revision_block()}"
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        from ._extract import field_spec, jython_body, security_steps, narrate

        items: list[ChangeItem] = facts["change_items"]
        scripts = facts["scripts"]
        state = self.ctx.state
        process = self.ctx.process
        applications = process.get("applications") or [self.ctx.process_name]
        naming = process.get("naming", {}) or {}

        # Maximo-specific narrative for this requirement pattern
        nb = narrate(items, scripts, process)
        pattern = nb.get("pattern", "config")

        # --- Section 3: Change Register --------------------------------------
        register = ["| CI ID | Change | Type | Object | Attribute | Build Agent |", "|---|---|---|---|---|---|"]
        for item in items:
            register.append(
                f"| {item.id} | {_cell(item.title)} | {item.change_type.value} | "
                f"{item.maximo_object or 'TBC'} | {item.maximo_attribute or '—'} | Agent {item.build_owner} |"
            )

        # --- Section 4: DB Configuration -------------------------------------
        db_rows = [
            "| Object | Attribute | Type | Length | Mandatory | Persistent | Action |",
            "|---|---|---|---|---|---|---|",
        ]
        db_any = False
        for item in items:
            if not item.maximo_attribute:
                continue
            spec = facts["attribute_specs"].get(f"{item.maximo_object}.{item.maximo_attribute}") or {}
            parsed = field_spec(item.description or "")
            ftype = spec.get("type") or parsed.get("type") or "ALN"
            length = spec.get("length") or parsed.get("length") or 100
            mand = "Yes" if (spec.get("required") or parsed.get("mandatory")) else "No"
            action = "MODIFY — update existing" if spec else "ADD — new attribute"
            db_any = True
            db_rows.append(
                f"| `{item.maximo_object or 'TBC'}` | `{item.maximo_attribute}` | "
                f"`{ftype}` | `{length}` | {mand} | Yes | {action} |"
            )
        db_section = "\n".join(db_rows) if db_any else "No database configuration changes are required for this change set."

        # DB implementation steps
        db_steps = []
        for item in items:
            if not item.maximo_attribute:
                continue
            spec = facts["attribute_specs"].get(f"{item.maximo_object}.{item.maximo_attribute}") or {}
            parsed = field_spec(item.description or "")
            ftype = spec.get("type") or parsed.get("type") or "ALN"
            length = spec.get("length") or parsed.get("length") or 100
            mand = spec.get("required") or parsed.get("mandatory") or False
            existing = bool(spec)
            db_steps += [
                f"**{item.id} — {item.maximo_object}.{item.maximo_attribute}**",
                f"1. Go To → System Configuration → Platform Configuration → **Database Configuration**.",
                f"2. Filter Object = `{item.maximo_object or 'TBC'}`. Click the object row.",
                f"3. Click the **Attributes** tab.",
                f"4. {'Locate the existing row for' if existing else 'Click **New Row** and enter'}  attribute `{item.maximo_attribute}`.",
                f"   - Type: `{ftype}`",
                f"   - Length/Precision: `{length}`",
                f"   - Required: {'Yes' if mand else 'No'}   Persistent: Yes",
                f"   - Description: {_cell(item.title, 80)}",
                f"5. Save the record.",
                f"6. Go To → System Configuration → Platform Configuration → **Apply Configuration Changes**.",
                f"7. Select object `{item.maximo_object or 'TBC'}` and click **Apply Changes Now**.",
                "",
            ]

        # --- Section 5: Application Configuration ----------------------------
        config_items = [i for i in items if i.change_type.value == "config"]
        app_steps = []
        for item in config_items:
            app_name = item.maximo_app or applications[0]
            app_steps += [
                f"**{item.id} — {app_name}: {item.maximo_attribute or 'new field'}**",
                f"1. Go To → System Configuration → Platform Configuration → **Application Designer**.",
                f"2. Filter Application = `{app_name}`. Open the definition.",
                f"3. Click **Export Application Definition** and save as a backup.",
                f"4. Select the **Main** tab in the canvas.",
                f"5. From the Controls palette, drag a **Textbox** control into the target section.",
                f"   - Label: `{item.title[:60]}`",
                f"   - Attribute: `{item.maximo_attribute or 'TBC'}`",
                f"   - Input Mode: default",
                f"6. Click **Save**.",
                f"7. Click **Export Application Definition** — save this XML for Migration Manager.",
                "",
            ]

        app_section = "\n".join(app_steps) if app_steps else "No Application Designer changes are required."

        # --- Section 6: Automation Scripts -----------------------------------
        script_sections = []
        for idx, s in enumerate(scripts, 1):
            logic_body = jython_body(s, rules=s.get("rules", []))
            script_sections.append(
                f"### 6.{idx} {s['name']}\n\n"
                f"| Property | Value |\n|---|---|\n"
                f"| Script name | `{s['name']}` |\n"
                f"| Launch point name | `{s['name']}_LP` |\n"
                f"| Launch point type | `{s['launch_point']}` |\n"
                f"| Object | `{s['object']}` |\n"
                f"| Events | `{s['event']}` |\n"
                f"| Language | Jython 2.7 |\n"
                f"| Change item(s) | {s['change_item']} |\n\n"
                f"**Purpose:** {_cell(s['purpose'])}\n\n"
                f"**Import path:** Go To → Automation → Automation Scripts → "
                f"Create Script with Launch Point\n\n"
                f"```python\n{logic_body}\n```\n"
            )
        scripts_section = "\n".join(script_sections) if script_sections else "No automation scripts are required."

        # --- Section 7: Integration ------------------------------------------
        integration_items = [i for i in items if i.change_type.value == "integration"]
        if integration_items:
            primary = (process.get("objects", {}) or {}).get("primary") or ["WORKORDER"]
            grouped: dict[str, list[ChangeItem]] = {}
            for item in integration_items:
                grouped.setdefault(item.maximo_object or primary[0], []).append(item)

            blocks = []
            for seq, (obj, group) in enumerate(grouped.items(), 1):
                channel = f"{self.ctx.process_name}{seq:02d}{naming.get('publish_channel_suffix', '_PC')}"
                es_name = f"{self.ctx.process_name}{seq:02d}{naming.get('enterprise_service_suffix', '_ES')}"
                req_lines = "\n".join(f"  - {i.id}: {_cell(i.title, 150)}" for i in group)
                blocks.append(
                    f"**Interface {seq} — Object `{obj}`**\n\n"
                    f"| MIF Component | Name | Direction |\n|---|---|---|\n"
                    f"| Object Structure | `{obj}OS` | Inbound and Outbound |\n"
                    f"| Publish Channel | `{channel}` | Outbound |\n"
                    f"| Enterprise Service | `{es_name}` | Inbound |\n\n"
                    f"Covers {len(group)} requirement(s):\n{req_lines}\n\n"
                    f"> Detailed field mapping and transformation rules are specified by "
                    f"Agent 3B in the Integration Build Document."
                )
            integration_section = (
                f"{len(grouped)} interface(s) are handed to Agent 3B (Integration Build Agent) "
                f"for detailed MIF design.\n\n" + "\n\n".join(blocks)
            )
        else:
            integration_section = "No integration changes are in scope for this change set."

        # --- Section 8: Security ---------------------------------------------
        sec_steps = security_steps(items, applications[0])
        security_section = "\n".join(sec_steps)

        # --- Section 9: Estimation -------------------------------------------
        estimation = ["| CI ID | Change | Effort (hrs) | Skill | Risk | Justification |", "|---|---|---|---|---|---|"]
        for item in items:
            justification = (
                "High confidence, validated" if item.confidence >= 0.8
                else "Unconfirmed name(s) — discovery overhead" if item.risk == "high"
                else "Standard effort for this change type"
            )
            estimation.append(
                f"| {item.id} | {_cell(item.title, 100)} | {item.effort_hours} | "
                f"{item.skill_level} | {item.risk} | {justification} |"
            )
        total = sum(i.effort_hours for i in items)
        estimation.append(f"| **Total** | | **{total:.1f} hrs** | | | |")

        # --- Section 10: Implementation Sequence -----------------------------
        seq_steps = []
        if db_any:
            seq_steps.append("1. **Database Configuration** — add/modify attributes (section 4). "
                             "Run Apply Configuration Changes in Admin Mode. Verify in a test environment first.")
        if config_items:
            seq_steps.append(f"{len(seq_steps)+1}. **Application Designer** — import field controls for "
                             f"`{', '.join(set(i.maximo_app or applications[0] for i in config_items))}` (section 5).")
        if scripts:
            seq_steps.append(f"{len(seq_steps)+1}. **Automation Scripts** — import and activate "
                             f"{', '.join(s['name'] for s in scripts)} (section 6). "
                             f"Test with a single record in isolation before enabling in production.")
        if integration_items:
            seq_steps.append(f"{len(seq_steps)+1}. **Integration (Agent 3B)** — configure Object Structures, "
                             f"Publish Channels, External Systems and End Points (section 7). "
                             f"Test with a single outbound message.")
        seq_steps.append(f"{len(seq_steps)+1}. **Security** — grant new fields to authorised security groups (section 8).")
        seq_steps.append(f"{len(seq_steps)+1}. **Test execution** — run the test cases produced by Agent 4, "
                         f"covering happy-path, negative and regression scenarios.")
        seq_steps.append(f"{len(seq_steps)+1}. **Go / No-go review** — submit all artifacts for final gate approval "
                         f"before Agent 5 (Deployment) assembles the migration package.")

        # Build the pattern-specific notes for sections 4 and 5
        db_config_note = nb.get("db_config_note", "")
        app_config_note = nb.get("app_config_note", "")
        security_note = nb.get("security_note", "")

        # Section 4 content: note first, then table and steps (or just note for no-change patterns)
        if not db_any and db_config_note:
            db_full = db_config_note
        elif db_any:
            db_full = (
                f"### 4.1 Summary Table\n\n{db_section}\n\n"
                f"### 4.2 Step-by-step Instructions\n\n"
                f"{chr(10).join(db_steps)}\n\n"
                f"After all attribute changes: switch Maximo to **Admin Mode**, run "
                f"**Apply Configuration Changes**, then switch Admin Mode off."
            )
        else:
            db_full = "No database configuration changes are required for this change set."

        # Section 5: app config note or steps
        if not config_items and app_config_note:
            app_full = app_config_note
        elif config_items:
            app_full = app_section
        else:
            app_full = "No Application Designer changes are required for this change set."

        # Section 8: security note enriched with steps
        sec_full = f"{security_note}\n\n{security_section}" if security_note else security_section

        # Pattern-specific implementation sequence additions
        pattern_seq_note: dict[str, str] = {
            "pm_wo_multiasset": (
                "> **Testing note**: Generate a WO from a PM that has at least 3 MULTIASSETLOCCI rows. "
                "Verify all rows appear on the WO's Multi-Asset/Location tab in WOTRACK. "
                "Also test a manually created WO — the script must not fire."
            ),
            "pm_wo_field_copy": (
                "> **Testing note**: Generate a WO from a PM with the source field populated. "
                "Verify the target field on the WO matches. Also test an existing WO save — must not re-copy."
            ),
            "integration": (
                "> **Testing note**: Send a test outbound message from a non-production environment "
                "before activating the Publish Channel in production."
            ),
        }
        seq_pattern_note = pattern_seq_note.get(pattern, "")

        return f"""# Technical Design Document

## 1. Document Control

| Field | Value |
|---|---|
| Document | Technical Design Document |
| Business process | {process.get('label', self.ctx.process_name)} ({self.ctx.process_name}) |
| Platform | IBM Maximo {self.ctx.cfg.maximo_version} |
| Run ID | {state.run_id} |
| Title | {state.title} |
| Status | Draft — awaiting Technical Lead review |
| Validation source | {self.ctx.validator.source_label()} |
| Total estimated effort | {total:.1f} hrs |

## 2. Solution Overview

{nb['solution_overview']}

{self.report.summary()}

**Change set components:**

| Component | Required | Detail |
|---|---|---|
| Database Configuration | {"Yes" if db_any else "**Not required**"} | {str(sum(1 for i in items if i.maximo_attribute)) + " attribute(s)" if db_any else "No new attributes needed — all required fields exist in the OOTB schema"} |
| Application Designer | {"Yes" if config_items else "**Not required**"} | {str(len(config_items)) + " control(s)" if config_items else "OOTB UI covers this change — no additional controls needed"} |
| Automation Scripts | {"Yes" if scripts else "Not required"} | {str(len(scripts)) + " script(s): " + ", ".join(s["name"] for s in scripts) if scripts else "Not required"} |
| Integration (MIF) | {"Yes → Agent 3B" if integration_items else "Not required"} | {str(len(integration_items)) + " interface(s)" if integration_items else "Not required"} |

## 3. Change Register

{chr(10).join(register)}

## 4. Database Configuration

{db_full}

## 5. Application Configuration

{app_full}

## 6. Automation Scripts

{scripts_section}

## 7. Integration Design

{integration_section}

## 8. Security

{sec_full}

## 9. Estimation

{chr(10).join(estimation)}

> Baseline effort figures are taken from `config/processes/{self.ctx.process_name.lower()}.yaml`.
> Risk multiplier applied per item. All estimates assume senior Maximo developer familiarity.

## 10. Implementation Sequence

{chr(10).join(seq_steps)}

{seq_pattern_note}
"""

    def _handover(self, facts: dict[str, Any]) -> dict[str, Any]:
        """Structured JSON tokens for Agent 3A / 3B (blueprint section 4)."""
        items: list[ChangeItem] = facts["change_items"]
        to_3a = [i for i in items if i.build_owner == "3A"]
        to_3b = [i for i in items if i.build_owner == "3B"]

        def token(item: ChangeItem) -> dict[str, Any]:
            return {
                "change_item_id": item.id,
                "title": item.title,
                "change_type": item.change_type.value,
                "maximo_object": item.maximo_object,
                "maximo_attribute": item.maximo_attribute,
                "maximo_app": item.maximo_app,
                "effort_hours": item.effort_hours,
                "risk": item.risk,
            }

        return {
            "run_id": self.ctx.state.run_id,
            "business_process": self.ctx.process_name,
            "agent_3a": {"required": bool(to_3a), "items": [token(i) for i in to_3a]},
            "agent_3b": {"required": bool(to_3b), "items": [token(i) for i in to_3b]},
            "scripts": facts["scripts"],
            "summary": (
                f"Agent 3A: {len(to_3a)} item(s); Agent 3B: {len(to_3b)} item(s)"
            ),
        }

    # -- emit --------------------------------------------------------------
    def emit(self, composition: Composition) -> list[Artifact]:
        out = self.ctx.artifact_dir("02_tdd")
        artifacts: list[Artifact] = []

        md_path = out / "TDD.md"
        md_path.write_text(composition.body, encoding="utf-8")
        artifacts.append(self.register_artifact(md_path, kind="md", description="TDD source markdown"))

        docx_path = out / "TDD.docx"
        render(
            composition.body,
            template=self.ctx.cfg.template_path("tdd"),
            target=docx_path,
            title=f"{self.ctx.process_name} - Technical Design Document",
            subtitle=self.ctx.state.title,
        )
        artifacts.append(self.register_artifact(docx_path, kind="docx", description="Production-ready TDD"))

        token_path = out / "handover_tokens.json"
        token_path.write_text(json.dumps(composition.handover, indent=2), encoding="utf-8")
        artifacts.append(
            self.register_artifact(token_path, kind="json", description="Handover tokens for Agent 3A / 3B")
        )
        return artifacts


def _cell(text: str, width: int = 240) -> str:
    clean = " ".join((text or "").split()).replace("|", "\\|")
    return clean[:width] + ("..." if len(clean) > width else "")
