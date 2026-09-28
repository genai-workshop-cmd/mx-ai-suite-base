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
    skill_files = ("mx_core_SKILL.md", "mx_tech_config_SKILL.md", "ma_autoscript_SKILL.md")

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
            "Write the Technical Design Document now."
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        items: list[ChangeItem] = facts["change_items"]
        scripts = facts["scripts"]
        state = self.ctx.state

        register = ["| CI ID | Change | Type | Maximo Object | Build Agent |", "|---|---|---|---|---|"]
        for item in items:
            register.append(
                f"| {item.id} | {_cell(item.title)} | {item.change_type.value} | "
                f"{item.maximo_object or 'TBC'} | Agent {item.build_owner} |"
            )

        estimation = ["| CI ID | Change | Effort (hrs) | Skill | Risk |", "|---|---|---|---|---|"]
        for item in items:
            estimation.append(
                f"| {item.id} | {_cell(item.title, 120)} | {item.effort_hours} | {item.skill_level} | {item.risk} |"
            )
        total = sum(i.effort_hours for i in items)
        estimation.append(f"| **Total** | | **{total:.1f}** | | |")

        db_rows = ["| Object | Attribute | Type | Length | Action |", "|---|---|---|---|---|"]
        db_any = False
        for item in items:
            if item.change_type.value != "config" or not item.maximo_attribute:
                continue
            spec = facts["attribute_specs"].get(f"{item.maximo_object}.{item.maximo_attribute}") or {}
            db_any = True
            db_rows.append(
                f"| {item.maximo_object or 'TBC'} | {item.maximo_attribute} | "
                f"{spec.get('type', 'ALN')} | {spec.get('length', 100)} | "
                f"{'Modify existing' if spec else 'Add new attribute'} |"
            )
        db_section = "\n".join(db_rows) if db_any else "No database configuration changes are required."

        app_items = [i for i in items if i.change_type.value == "config"]
        app_section = (
            "\n".join(
                f"{n}. **{i.maximo_app or self.ctx.process.get('applications', ['TBC'])[0]}** - {_cell(i.description)}"
                for n, i in enumerate(app_items, 1)
            )
            if app_items
            else "No application configuration changes are required."
        )

        script_sections = []
        for s in scripts:
            script_sections.append(
                f"""### 6.{len(script_sections) + 1} {s['name']}

| Property | Value |
|---|---|
| Script name | {s['name']} |
| Launch point type | {s['launch_point']} |
| Object | {s['object']} |
| Event | {s['event']} |
| Language | Jython 2.7 |
| Change item | {s['change_item']} |

Purpose: {_cell(s['purpose'])}

```python
# {s['name']} - {s['launch_point']} launch point on {s['object']}
# Event: {s['event']}
from psdi.mbo import MboConstants

source = mbo.getString("{s['attribute'] or 'STATUS'}")

if source is not None and source.strip() != "":
    target = mbo.getString("DESCRIPTION")
    # Do not overwrite a value the user has already entered.
    if target is None or target.strip() == "":
        mbo.setValue("DESCRIPTION", source, MboConstants.NOACCESSCHECK)
```
"""
            )
        scripts_section = "\n".join(script_sections) or "No automation scripts are required."

        integration_items = [i for i in items if i.change_type.value == "integration"]
        naming = self.ctx.process.get("naming", {}) or {}
        if integration_items:
            # Group the way Agent 3B will: requirements sharing an object
            # describe one interface, not one interface each.
            primary = (self.ctx.process.get("objects", {}) or {}).get("primary") or ["WORKORDER"]
            grouped: dict[str, list[ChangeItem]] = {}
            for item in integration_items:
                grouped.setdefault(item.maximo_object or primary[0], []).append(item)

            blocks = []
            for seq, (obj, group) in enumerate(grouped.items(), 1):
                channel = f"{self.ctx.process_name}{seq:02d}{naming.get('publish_channel_suffix', '_PC')}"
                lines = "\n".join(f"  - {i.id}: {_cell(i.title, 150)}" for i in group)
                blocks.append(
                    f"**Interface {seq} — object `{obj}`** (proposed Publish Channel `{channel}`), "
                    f"covering {len(group)} requirement(s):\n{lines}"
                )
            integration_section = (
                f"{len(grouped)} interface(s) are handed to Agent 3B for detailed design.\n\n"
                + "\n\n".join(blocks)
            )
        else:
            integration_section = "No integration changes are in scope for this run."

        return f"""# Technical Design Document

## 1. Document Control

| Field | Value |
|---|---|
| Document | Technical Design Document |
| Business process | {self.ctx.process.get('label', self.ctx.process_name)} ({self.ctx.process_name}) |
| Platform | IBM Maximo {self.ctx.cfg.maximo_version} |
| Run ID | {state.run_id} |
| Status | Draft - awaiting technical lead review |
| Validation source | {self.ctx.validator.source_label()} |

## 2. Solution Overview

{len(items)} change item(s) are implemented across database configuration, application
configuration, automation scripting and integration. {self.report.summary()}

## 3. Change Register

{chr(10).join(register)}

## 4. Database Configuration

{db_section}

Apply through **Database Configuration**, then run Admin Mode + Apply Configuration
Changes in the target environment.

## 5. Application Configuration

{app_section}

## 6. Automation Scripts

{scripts_section}

## 7. Integration Design

{integration_section}

## 8. Security

Grant the new fields and any new application to the security groups that already
hold access to the {self.ctx.process_name} applications. No new signature options
are introduced by this change unless listed in section 3.

## 9. Estimation

{chr(10).join(estimation)}

## 10. Implementation Sequence

1. Apply database configuration changes (section 4) in admin mode.
2. Import the application definitions (section 5).
3. Import and activate the automation scripts (section 6).
4. Configure the integration components (section 7) and test with a single record.
5. Apply the security grants (section 8).
6. Execute the test cases produced by Agent 4.
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
