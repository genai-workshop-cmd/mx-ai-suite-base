"""Agent 3A - Config Build Agent (blueprint section 4).

Produces the Maximo configuration build artifacts: a step-by-step build
document, an App Designer-shaped XML export, a DB Configuration script and the
final Jython files ready for Script Manager import.
"""
from __future__ import annotations

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
    skill_files = ("mx_core_SKILL.md", "mx_tech_config_SKILL.md", "ma_autoscript_SKILL.md")

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
            "Write the Configuration Build Document now."
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        items: list[ChangeItem] = facts["items"]
        scripts = facts["scripts"]
        apps = self.ctx.process.get("applications") or ["TBC"]

        db_steps, app_steps = [], []
        for item in items:
            spec = facts["attribute_specs"].get(f"{item.maximo_object}.{item.maximo_attribute}") or {}
            if item.maximo_attribute and not spec:
                db_steps.append(
                    f"1. Open **Database Configuration** and filter for object `{item.maximo_object or 'TBC'}`.\n"
                    f"2. On the Attributes tab, select **New Row** and enter:\n"
                    f"   - Attribute: `{item.maximo_attribute}`\n"
                    f"   - Description: {_cell(item.title, 100)}\n"
                    f"   - Type: `ALN`   Length: `100`   Persistent: yes\n"
                    f"3. Save the record."
                )
            if item.change_type.value == "config":
                app_steps.append(
                    f"1. Open **Application Designer** and select `{item.maximo_app or apps[0]}`.\n"
                    f"2. Export the current definition as a backup before any change.\n"
                    f"3. Add a textbox bound to `{item.maximo_attribute or 'the new attribute'}` "
                    f"on the main tab, label \"{_cell(item.title, 60)}\".\n"
                    f"4. Save and export the updated application XML."
                )

        db_section = "\n\n".join(db_steps) or "No database configuration changes are required."
        app_section = "\n\n".join(app_steps) or "No Application Designer changes are required."

        script_steps = "\n".join(
            f"{n}. Open **Automation Scripts**, choose *Create Script with Launch Point*. "
            f"Launch point `{s['name']}_LP`, type `{s['launch_point']}`, object `{s['object']}`, "
            f"events `{s['event']}`. Paste the contents of `scripts/{s['name']}.py`. Set status to **Active**."
            for n, s in enumerate(scripts, 1)
        ) or "No automation scripts to import."

        verification = "\n".join(
            f"{n}. Confirm `{i.maximo_attribute or i.maximo_object or 'the change'}` behaves as described in "
            f"change item {i.id}."
            for n, i in enumerate(items, 1)
        ) or "1. Confirm the application opens without error."

        return f"""# Configuration Build Document

## 1. Build Summary

| Field | Value |
|---|---|
| Business process | {self.ctx.process_name} |
| Run ID | {self.ctx.state.run_id} |
| Config change items | {len(items)} |
| Automation scripts | {len(scripts)} |
| Validation source | {self.ctx.validator.source_label()} |

{self.report.summary()}

## 2. Database Configuration Steps

{db_section}

After all attribute changes: turn on **Admin Mode**, run **Apply Configuration
Changes**, then turn Admin Mode off.

## 3. Application Designer Steps

{app_section}

## 4. Domains and Lookups

No new domains are required by this change set. If a value list is added later,
define it in **Domains** as an `ALN` domain and bind it to the attribute before import.

## 5. Security Configuration

Grant the new fields to the security groups that already hold access to
{', '.join(f'`{a}`' for a in apps)}. No new signature options are introduced.

## 6. Automation Script Import

{script_steps}

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
        attribute = script.get("attribute") or "STATUS"
        return f'''# {script['name']}
# Generated by {self.ctx.cfg.project_name} - run {self.ctx.state.run_id}
# Launch point : {script['name']}_LP  ({script['launch_point']})
# Object       : {script['object']}
# Events       : {script['event']}
# Language     : Jython 2.7
#
# Purpose: {script['purpose']}
#
# Uses the MBO API only. No direct SQL - Maximo caching and field validation
# would be bypassed and the change would not be auditable.

from psdi.mbo import MboConstants

SOURCE_ATTRIBUTE = "{attribute}"
TARGET_ATTRIBUTE = "DESCRIPTION"


def _blank(value):
    return value is None or str(value).strip() == ""


source_value = mbo.getString(SOURCE_ATTRIBUTE)

if not _blank(source_value):
    current_target = mbo.getString(TARGET_ATTRIBUTE)
    # Never overwrite a value a user has already entered.
    if _blank(current_target):
        mbo.setValue(TARGET_ATTRIBUTE, source_value, MboConstants.NOACCESSCHECK)
'''


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
