"""Agent 3A - Config Build Agent (blueprint section 4).

Produces the Maximo configuration build artifacts: a step-by-step build
document, an App Designer-shaped XML export, a DB Configuration script and the
final Jython files ready for Script Manager import.
"""
from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from core.models import Artifact, ChangeItem, DuplicateDecision, Phase
from rendering.docx_writer import render

from .base import BaseAgent, Composition


class ConfigBuildAgent(BaseAgent):
    agent_id = "3A"
    name = "Config Build Agent"
    phase = Phase.BUILD_CONFIG
    doc_type = "build_config"
    role = (
        "Generate every Maximo configuration build artifact - App Designer, DB "
        "Configurator, Security, Workflow, Escalations, Cron Tasks and BIRT - from "
        "the approved TDD, ready to apply in a live environment without rework."
    )
    inputs_description = (
        "- The approved TDD\n- Handover token listing the config change items\n"
        "- Validated Maximo object and attribute facts"
    )
    output_format = (
        "Markdown with exactly these sections:\n"
        "# Configuration Build Document\n"
        "## 1. Build Summary\n"
        "## 2. Database Configuration Steps\n"
        "## 3. Application Designer Steps\n"
        "## 4. Domains and Lookups\n"
        "## 5. Security Configuration\n"
        "## 6. Automation Script Import\n"
        "## 7. Post-build Verification\n"
        "Each step must be numbered, name the exact Maximo application to open, "
        "and state the exact field values to enter."
    )
    skill_files = ("mx_core_SKILL.md", "mx_tech_config_SKILL.md", "ma_autoscript_SKILL.md", "mx_pm_wo_SKILL.md")

    # -- gather ------------------------------------------------------------
    def gather(self) -> dict[str, Any]:
        handover = self._handover()
        items = self._items(handover)
        for item in items:
            self.ctx.validator.check_change_item(item, self.ctx.process, self.report)

        scripts = handover.get("scripts", [])
        specs = {}
        for item in items:
            if item.maximo_object and item.maximo_attribute:
                key = f"{item.maximo_object}.{item.maximo_attribute}"
                specs[key] = self.ctx.validator.attribute_spec(item.maximo_object, item.maximo_attribute)

        return {"items": items, "scripts": scripts, "attribute_specs": specs, "handover": handover}

    def _handover(self) -> dict[str, Any]:
        result = self.ctx.state.result(Phase.TDD)
        return (result.handover if result else {}) or {}

    def _items(self, handover: dict[str, Any]) -> list[ChangeItem]:
        """Change items this agent owns, taken from the handover token."""
        ids = {t["change_item_id"] for t in (handover.get("agent_3a", {}) or {}).get("items", [])}
        if ids:
            return [i for i in self.change_items() if i.id in ids]
        return [i for i in self.change_items() if i.build_owner == "3A"]

    # -- compose -----------------------------------------------------------
    def compose(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> Composition:
        text, generated_by = self.ask_model(self._user_prompt(facts), max_tokens=8000)
        if text:
            body, flags = self.parse_flags(text, "Config Build")
        else:
            body = self._deterministic(facts)
            flags = []
            generated_by = "deterministic"

        summary = (
            f"Config build for {len(facts['items'])} item(s): DB Config, App Designer XML "
            f"and {len(facts['scripts'])} automation script(s). {self.report.summary()}"
        )
        return Composition(body=body, summary=summary, flags=flags, generated_by=generated_by)

    def _user_prompt(self, facts: dict[str, Any]) -> str:
        items = "\n".join(
            f"- {i.id} [{i.change_type.value}] {i.title}\n  object={i.maximo_object or '?'} "
            f"attribute={i.maximo_attribute or '?'} app={i.maximo_app or '?'}\n  {i.description[:300]}"
            for i in facts["items"]
        )
        scripts = "\n".join(
            f"- {s['name']} ({s['launch_point']} on {s['object']}, {s['event']})" for s in facts["scripts"]
        ) or "(none)"
        return (
            f"RUN: {self.ctx.state.title}\nBUSINESS PROCESS: {self.ctx.process_name}\n\n"
            f"CONFIG CHANGE ITEMS FROM THE HANDOVER TOKEN:\n{items}\n\n"
            f"AUTOMATION SCRIPTS TO IMPORT:\n{scripts}\n\n"
            f"EXISTING ATTRIBUTE SPECS:\n{facts['attribute_specs']}\n\n"
            f"VALIDATED MAXIMO FACTS:\n{self.validated_facts_block()}\n\n"
            f"Write the Configuration Build Document now.{self.revision_block()}"
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        from ._extract import field_spec, db_config_steps, app_designer_steps, security_steps, jython_body

        items: list[ChangeItem] = facts["items"]
        scripts = facts["scripts"]
        apps = self.ctx.process.get("applications") or ["TBC"]
        app = apps[0]

        # --- Section 2: DB Configuration Steps -------------------------------
        all_db_steps: list[str] = []
        for item in items:
            if not item.maximo_attribute:
                continue
            spec = facts["attribute_specs"].get(f"{item.maximo_object}.{item.maximo_attribute}") or {}
            steps = db_config_steps(item, spec, existing=bool(spec))
            all_db_steps.append(f"**{item.id} — `{item.maximo_object}.{item.maximo_attribute}`**\n\n"
                                 + "\n".join(steps) + "\n")
        db_section = "\n".join(all_db_steps) or "No database configuration changes are required."

        # --- Section 3: Application Designer Steps ---------------------------
        config_items = [i for i in items if i.change_type.value == "config"]
        all_app_steps: list[str] = []
        for item in config_items:
            target_app = item.maximo_app or app
            steps = app_designer_steps(item, target_app)
            all_app_steps.append(f"**{item.id} — `{target_app}`: {_cell(item.title, 60)}**\n\n"
                                  + "\n".join(steps) + "\n")
        app_section = "\n".join(all_app_steps) or "No Application Designer changes are required."

        # --- Section 4: Domains and Lookups -----------------------------------
        domain_items = [i for i in items if re.search(r'\bdomain\b|\blookup\b|\bvalue\s+list\b', i.description or "", re.I)]
        if domain_items:
            domain_steps = []
            for item in domain_items:
                domain_steps += [
                    f"**{item.id}** — "
                    f"1. Go To → System Configuration → Platform Configuration → **Domains**.",
                    f"   2. Create a new ALN domain for `{item.maximo_attribute or 'the attribute'}`.",
                    f"   3. Add the required synonym values.",
                    f"   4. Bind the domain to `{item.maximo_object}.{item.maximo_attribute or 'ATTR'}` in Database Configuration.",
                ]
            domain_section = "\n".join(domain_steps)
        else:
            domain_section = (
                "No new domains or value lists are required. If a lookup is added later, "
                "define it in **Domains** as an `ALN` domain and bind it to the attribute "
                "in Database Configuration before applying configuration changes."
            )

        # --- Section 5: Security Configuration --------------------------------
        sec_steps = security_steps(items, app)
        security_section = "\n".join(sec_steps)

        # --- Section 6: Automation Script Import ------------------------------
        script_import_steps = []
        for n, s in enumerate(scripts, 1):
            script_import_steps += [
                f"**Script {n}: `{s['name']}`**",
                f"1. Go To → Automation → **Automation Scripts**.",
                f"2. From the **More Actions** menu, choose **Create Script with Launch Point**.",
                f"3. Select launch point type: **{s['launch_point'].title()}**.",
                f"4. In the Launch Point details:",
                f"   - Launch Point: `{s['name']}_LP`",
                f"   - Object: `{s['object']}`",
                f"   - Active: Yes",
                f"   - Events: `{s['event']}`",
                f"5. In the Script details:",
                f"   - Script: `{s['name']}`",
                f"   - Language: **Jython**",
                f"   - Status: **Active**",
                f"6. Paste the contents of `scripts/{s['name']}.py` into the Script Source field.",
                f"7. Click **Save**.",
                f"8. Test by triggering the event on a `{s['object']}` record and confirming the expected outcome.",
                "",
            ]
        script_section = "\n".join(script_import_steps) or "No automation scripts to import."

        # --- Section 7: Post-build Verification -------------------------------
        verif_steps: list[str] = []
        n = 1
        for item in items:
            if item.maximo_attribute:
                verif_steps.append(
                    f"{n}. Open the `{item.maximo_app or app}` application and confirm field "
                    f"`{item.maximo_attribute}` on `{item.maximo_object or 'the object'}` is "
                    f"visible, correct type, and behaves as per {item.id}."
                )
                n += 1
        for s in scripts:
            verif_steps.append(
                f"{n}. Create a test `{s['object']}` record and trigger the `{s['event']}` event. "
                f"Confirm script `{s['name']}` executes without error and produces the expected result."
            )
            n += 1
        verif_steps.append(
            f"{n}. Run the full test suite from Agent 4 and confirm all cases pass."
        )
        verification = "\n".join(verif_steps) or "1. Confirm the application opens without error after changes."

        return f"""# Configuration Build Document

## 1. Build Summary

| Field | Value |
|---|---|
| Business process | {self.ctx.process_name} |
| Run ID | {self.ctx.state.run_id} |
| Config change items | {len(items)} |
| Automation scripts | {len(scripts)} |
| Target application(s) | {', '.join(f'`{a}`' for a in set(i.maximo_app or app for i in items))} |
| Validation source | {self.ctx.validator.source_label()} |
| Generated | Deterministic template (offline mode) |

{self.report.summary()}

**Apply order:** Database Configuration → Apply Config Changes → Application Designer
→ Automation Scripts → Security → Verification.

## 2. Database Configuration Steps

{db_section}

> After **all** attribute changes: switch to **Admin Mode**, run **Apply Configuration Changes**,
> then switch Admin Mode off before proceeding to Application Designer.

## 3. Application Designer Steps

{app_section}

## 4. Domains and Lookups

{domain_section}

## 5. Security Configuration

{security_section}

## 6. Automation Script Import

{script_section}

## 7. Post-build Verification

{verification}
"""

    # -- emit --------------------------------------------------------------
    def emit(self, composition: Composition) -> list[Artifact]:
        out = self.ctx.artifact_dir("03a_config_build")
        artifacts: list[Artifact] = []

        md = out / "Config_Build_Document.md"
        md.write_text(composition.body, encoding="utf-8")
        artifacts.append(self.register_artifact(md, kind="md", description="Config build source"))

        docx = out / "Config_Build_Document.docx"
        render(
            composition.body,
            template=self.ctx.cfg.template_path("tdd"),
            target=docx,
            title=f"{self.ctx.process_name} - Configuration Build Document",
            subtitle=self.ctx.state.title,
        )
        artifacts.append(self.register_artifact(docx, kind="docx", description="Config build document"))

        facts = self.facts

        app_xml = out / "app_designer_export.xml"
        app_xml.write_text(self._app_designer_xml(facts["items"]), encoding="utf-8")
        artifacts.append(
            self.register_artifact(app_xml, kind="xml", description="App Designer import structure")
        )

        db_xml = out / "dbconfig.xml"
        db_xml.write_text(self._dbconfig_xml(facts), encoding="utf-8")
        artifacts.append(self.register_artifact(db_xml, kind="xml", description="DB Configuration definition"))

        script_dir = out / "scripts"
        script_dir.mkdir(exist_ok=True)
        for s in facts["scripts"]:
            path = script_dir / f"{s['name']}.py"
            path.write_text(self._jython(s), encoding="utf-8")
            artifacts.append(
                self.register_artifact(path, kind="py", description=f"Jython script {s['name']}")
            )
        return artifacts

    # -- artifact builders -------------------------------------------------
    def _app_designer_xml(self, items: list[ChangeItem]) -> str:
        """App Designer presentation fragment for the new fields.

        Maximo's App Designer import expects a <presentation> document; this
        emits the textbox controls to merge into the target application.
        """
        apps = self.ctx.process.get("applications") or ["TBC"]
        app_name = next((i.maximo_app for i in items if i.maximo_app), apps[0])
        primary = next((i.maximo_object for i in items if i.maximo_object), "")

        presentation = ET.Element(
            "presentation",
            {
                "id": app_name,
                "mboname": primary or app_name,
                "beanclass": "psdi.webclient.beans.common.AppBean",
                "resultsttable": "results",
            },
        )
        tabgroup = ET.SubElement(presentation, "tabgroup", {"id": f"{app_name}_tabgroup"})
        tab = ET.SubElement(tabgroup, "tab", {"id": f"{app_name}_main", "label": "Main"})
        section = ET.SubElement(tab, "section", {"id": f"{app_name}_section_generated", "border": "true"})

        for n, item in enumerate(items, 1):
            if not item.maximo_attribute:
                continue
            ET.SubElement(
                section,
                "textbox",
                {
                    "id": f"{app_name}_{item.maximo_attribute.lower()}",
                    "dataattribute": item.maximo_attribute,
                    "label": _cell(item.title, 40),
                    "inputmode": "default",
                },
            )
        _indent(presentation)
        header = (
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            f"<!-- Generated by {self.ctx.cfg.project_name} for run {self.ctx.state.run_id}.\n"
            f"     Merge into the {app_name} application in Application Designer. -->\n"
        )
        return header + ET.tostring(presentation, encoding="unicode")

    def _dbconfig_xml(self, facts: dict[str, Any]) -> str:
        """Attribute definitions for Database Configuration."""
        root = ET.Element("dbconfig", {"run": self.ctx.state.run_id, "process": self.ctx.process_name})
        for item in facts["items"]:
            if not (item.maximo_object and item.maximo_attribute):
                continue
            spec = facts["attribute_specs"].get(f"{item.maximo_object}.{item.maximo_attribute}") or {}
            obj = ET.SubElement(root, "object", {"name": item.maximo_object})
            ET.SubElement(
                obj,
                "attribute",
                {
                    "name": item.maximo_attribute,
                    "title": _cell(item.title, 50),
                    "maxtype": str(spec.get("type", "ALN")),
                    "length": str(spec.get("length") or 100),
                    "persistent": "true",
                    "required": "false",
                    "action": "MODIFY" if spec else "ADD",
                },
            )
        _indent(root)
        return "<?xml version='1.0' encoding='UTF-8'?>\n" + ET.tostring(root, encoding="unicode")

    def _jython(self, script: dict[str, Any]) -> str:
        """Script Manager-ready Jython using the MBO API, never raw SQL."""
        from ._extract import jython_body

        body = jython_body(script, rules=script.get("rules", []))
        return (
            f"# {script['name']}\n"
            f"# Generated by {self.ctx.cfg.project_name} — run {self.ctx.state.run_id}\n"
            f"# Uses the MBO API only — no direct SQL; Maximo caching and field\n"
            f"# validation would be bypassed and the change would not be auditable.\n\n"
            + body
        )


def _indent(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print an ElementTree in place."""
    pad = "\n" + "  " * level
    if len(elem):
        if not (elem.text or "").strip():
            elem.text = pad + "  "
        for child in elem:
            _indent(child, level + 1)
        if not (elem.tail or "").strip():
            elem.tail = pad
        if not (elem[-1].tail or "").strip():
            elem[-1].tail = pad + "  "
    elif level and not (elem.tail or "").strip():
        elem.tail = pad


def _cell(text: str, width: int = 240) -> str:
    clean = " ".join((text or "").split()).replace("|", "\\|")
    return clean[:width] + ("..." if len(clean) > width else "")
