"""Agent 3B - Integration Build Agent (blueprint section 4).

Produces MIF integration design artifacts:

  inbound  -> Enterprise Service + Object Structure, external fields mapped
              onto Maximo attributes
  outbound -> Publish Channel + External System + endpoint, Maximo attributes
              mapped onto the outbound message

Every object and attribute in the mapping table is validated first, so the
mapping cannot reference a field that does not exist.
"""
from __future__ import annotations

import json
import re
from typing import Any
from xml.etree import ElementTree as ET

from core.models import Artifact, ChangeItem, DuplicateDecision, Flag, Phase
from rendering.docx_writer import render
from rendering.xlsx_writer import Sheet, write_workbook

from .base import BaseAgent, Composition

_OUTBOUND_RE = re.compile(r"\b(outbound|publish|send|export|notify|push|emit)\b", re.I)
_INBOUND_RE = re.compile(r"\b(inbound|receive|import|consume|ingest|load from)\b", re.I)

MAPPING_COLUMNS = [
    "Seq",
    "Direction",
    "Source Field",
    "Target Field",
    "Data Type",
    "Length",
    "Mandatory",
    "Transformation",
    "Validated",
    "Notes",
]


class IntegrationAgent(BaseAgent):
    agent_id = "3B"
    name = "Integration Build Agent"
    phase = Phase.BUILD_INTEGRATION
    doc_type = "build_integration"
    role = (
        "Produce the complete MIF interface specification and field mapping for "
        "every integration change item, in a form an integration architect can "
        "configure in Maximo without further analysis."
    )
    inputs_description = (
        "- The approved TDD\n- Handover token listing the integration change items\n"
        "- Validated Maximo object structure and attribute facts"
    )
    output_format = (
        "Markdown document covering the integration design:\n"
        "# Integration Build Document\n"
        "## 1. Interface Summary  (table: Interface | Direction | Trigger | Object Structure | External System)\n"
        "## 2. Interface Detail  (one ### subsection per interface)\n"
        "## 3. Field Mapping  (only include mappings that are confirmed in VALIDATED MAXIMO FACTS)\n"
        "## 4. Transformation Rules\n"
        "## 5. Error Handling\n"
        "## 6. Security and Endpoint Configuration\n"
        "## 7. Test Approach\n"
    )
    skill_files = ("mx_core_SKILL.md", "mx_integration_SKILL.md", "mx_rest_api_SKILL.md")

    # -- gather ------------------------------------------------------------
    def gather(self) -> dict[str, Any]:
        handover = self._handover()
        items = self._items(handover)
        interfaces = self._consolidate(items)

        for iface in interfaces:
            self.report.add(self.ctx.validator.object(iface["object"]))
            os_check = self.ctx.validator.object_structure(iface["object_structure"])
            self.report.add(os_check)
            iface["object_structure_exists"] = os_check.exists

        mappings = [row for iface in interfaces for row in self._mapping_rows(iface)]
        return {"items": items, "interfaces": interfaces, "mappings": mappings, "handover": handover}

    def _handover(self) -> dict[str, Any]:
        result = self.ctx.state.result(Phase.TDD)
        return (result.handover if result else {}) or {}

    def _items(self, handover: dict[str, Any]) -> list[ChangeItem]:
        ids = {t["change_item_id"] for t in (handover.get("agent_3b", {}) or {}).get("items", [])}
        if ids:
            return [i for i in self.change_items() if i.id in ids]
        return [i for i in self.change_items() if i.build_owner == "3B"]

    def _consolidate(self, items: list[ChangeItem]) -> list[dict[str, Any]]:
        """Group change items into distinct interfaces.

        A single interface is normally described by several requirement lines -
        the trigger, the publish channel, the external system, the payload, the
        error behaviour. Treating each line as its own interface would produce
        duplicate publish channels that could never be configured.

        Items are one interface when they share a direction and a Maximo
        object. The external system is resolved afterwards, because only some
        requirement lines name it.
        """
        buckets: dict[tuple[str, str], list[ChangeItem]] = {}
        for item in items:
            probe = self._interface(item, 0)
            buckets.setdefault((probe["direction"], probe["object"]), []).append(item)

        interfaces: list[dict[str, Any]] = []
        for seq, (key, group) in enumerate(buckets.items(), 1):
            # Build from the item carrying the most detail, then merge the rest.
            primary = max(group, key=lambda i: len(i.description or ""))
            iface = self._interface(primary, seq)
            iface["change_items"] = [i.id for i in group]
            iface["requirements"] = [i.description for i in group]

            # A trigger stated in any requirement in the group beats "confirm".
            if "confirm" in iface["trigger"].lower():
                for other in group:
                    trigger = self._trigger(other.description or other.title)
                    if "confirm" not in trigger.lower():
                        iface["trigger"] = trigger
                        break

            # Same for an explicitly named external system.
            if iface["external_system"].startswith("EXT"):
                naming = self.ctx.process.get("naming", {}) or {}
                for other in group:
                    named = self._external_system(other.description or other.title, naming)
                    if not named.startswith("EXT"):
                        iface["external_system"] = named
                        iface["endpoint"] = f"{named}_ENDPOINT"
                        break
            interfaces.append(iface)
        return interfaces

    def _interface(self, item: ChangeItem, seq: int) -> dict[str, Any]:
        """Derive the MIF component set for one integration change item."""
        naming = self.ctx.process.get("naming", {}) or {}
        text = item.description or item.title

        outbound = bool(_OUTBOUND_RE.search(text))
        inbound = bool(_INBOUND_RE.search(text))
        # When the wording is ambiguous, outbound is the safer default for a
        # status-change notification, which is the common CU pattern.
        direction = "Inbound" if (inbound and not outbound) else "Outbound"

        obj = item.maximo_object or (self.ctx.process.get("objects", {}).get("primary") or ["WORKORDER"])[0]
        external = self._external_system(text, naming)
        base = f"{self.ctx.process_name}{seq:02d}"

        iface = {
            "id": item.id,
            "name": f"{base}_{'IN' if direction == 'Inbound' else 'OUT'}",
            "direction": direction,
            "object": obj,
            "object_structure": self._object_structure(obj, naming),
            "external_system": external,
            "trigger": self._trigger(text),
            "title": item.title,
            "description": item.description,
        }
        if direction == "Outbound":
            iface["publish_channel"] = f"{base}{naming.get('publish_channel_suffix', '_PC')}"
            iface["endpoint"] = f"{external}_ENDPOINT"
            iface["enterprise_service"] = ""
        else:
            iface["enterprise_service"] = f"{base}_ES"
            iface["publish_channel"] = ""
            iface["endpoint"] = "MAXIMO inbound queue (JMS / REST)"
        return iface

    def _object_structure(self, obj: str, naming: dict) -> str:
        info = self.ctx.validator.catalog.for_object(obj)
        if info:
            return info.os_name
        return f"{naming.get('object_structure_prefix', 'MXAPI')}{obj.upper()}"

    def _external_system(self, text: str, naming: dict) -> str:
        """Pick up an explicitly named external system, else a sane default."""
        suffix = naming.get("external_system_suffix", "_EXTSYS")
        named = re.search(r"\b([A-Z][A-Z0-9_]{2,})" + re.escape(suffix) + r"\b", text or "")
        if named:
            return named.group(0)
        # "to the AUD external system" / "to AUD system"
        phrase = re.search(r"\bto (?:the )?([A-Z][A-Z0-9]{1,15})\b(?=[^.]{0,30}\bsystem\b)", text or "")
        if phrase:
            return f"{phrase.group(1)}{suffix}"
        return f"EXT{suffix}"

    def _trigger(self, text: str) -> str:
        status = re.search(r"\bstatus\b[^.]{0,40}?\b(?:to|is|becomes|changes to)\s+([A-Z][A-Z0-9_]{2,})", text or "", re.I)
        if status:
            return f"Status change to {status.group(1).upper()}"
        if re.search(r"\bon (save|insert|add)\b", text or "", re.I):
            return "Record save (Add/Update)"
        if re.search(r"\b(schedule|nightly|daily|cron)\b", text or "", re.I):
            return "Scheduled (Cron Task)"
        return "Record event - confirm with the integration architect"

    def _mapping_rows(self, iface: dict[str, Any]) -> list[dict[str, Any]]:
        """Build the field mapping from real object-structure metadata."""
        info = self.ctx.validator.catalog.for_object(iface["object"])
        rows: list[dict[str, Any]] = []

        if info is None:
            rows.append(
                {
                    "Seq": 1,
                    "Direction": iface["direction"],
                    "Source Field": f"{iface['object']}.<unconfirmed>",
                    "Target Field": "<unconfirmed>",
                    "Data Type": "",
                    "Length": "",
                    "Mandatory": "",
                    "Transformation": "Direct",
                    "Validated": "NO",
                    "Notes": f"Object {iface['object']} is not in the validation source; mapping cannot be generated.",
                }
            )
            return rows

        # Primary keys first, then the descriptive and status fields that an
        # interface almost always carries.
        preferred = list(info.primary_keys)
        for candidate in ("description", "status", "statusdate", "changeby", "changedate"):
            if candidate in info.attributes and candidate not in preferred:
                preferred.append(candidate)

        for seq, attr_name in enumerate(preferred, 1):
            attr = info.attributes.get(attr_name)
            if attr is None:
                continue
            maximo_field = f"{iface['object']}.{attr.name.upper()}"
            external_field = _camel(attr.name)
            source, target = (
                (maximo_field, external_field)
                if iface["direction"] == "Outbound"
                else (external_field, maximo_field)
            )
            rows.append(
                {
                    "Seq": seq,
                    "Direction": iface["direction"],
                    "Source Field": source,
                    "Target Field": target,
                    "Data Type": attr.maximo_type,
                    "Length": attr.max_length or "",
                    "Mandatory": "Yes" if attr.name in info.primary_keys else "No",
                    "Transformation": "Direct",
                    "Validated": "YES",
                    "Notes": attr.title or "",
                }
            )
        return rows

    # -- compose -----------------------------------------------------------
    def compose(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> Composition:
        text, generated_by = self.ask_model(self._user_prompt(facts), max_tokens=8000)
        if text:
            body, flags = self.parse_flags(text, "Integration Build")
        else:
            body = self._deterministic(facts)
            flags = []
            generated_by = "deterministic"

        for iface in facts["interfaces"]:
            if "confirm" in iface["trigger"].lower():
                flags.append(
                    Flag(
                        section="2. Interface Detail",
                        item=iface["name"],
                        reason="The trigger condition could not be determined from the requirement text.",
                        confidence=0.4,
                        severity="warn",
                        suggestion="Confirm the trigger event with the integration architect.",
                    )
                )

        summary = (
            f"{len(facts['interfaces'])} interface(s), {len(facts['mappings'])} mapped field(s). "
            f"{self.report.summary()}"
        )
        return Composition(body=body, summary=summary, flags=flags, generated_by=generated_by)

    def _user_prompt(self, facts: dict[str, Any]) -> str:
        ifaces = "\n".join(
            f"- {i['name']} | {i['direction']} | object={i['object']} | OS={i['object_structure']} | "
            f"external={i['external_system']} | trigger={i['trigger']}\n  {i['description'][:250]}"
            for i in facts["interfaces"]
        )
        mapping = "\n".join(
            f"  {m['Seq']}. {m['Source Field']} -> {m['Target Field']} ({m['Data Type']}"
            f"{'/' + str(m['Length']) if m['Length'] else ''}, mandatory={m['Mandatory']})"
            for m in facts["mappings"][:40]
        )
        return (
            f"RUN: {self.ctx.state.title}\nBUSINESS PROCESS: {self.ctx.process_name}\n\n"
            f"INTERFACES DERIVED FROM THE HANDOVER TOKEN:\n{ifaces}\n\n"
            f"FIELD MAPPING (already validated against Maximo - reproduce exactly):\n{mapping}\n\n"
            f"VALIDATED MAXIMO FACTS:\n{self.validated_facts_block()}\n\n"
            f"Write the Integration Build Document now.{self.revision_block()}"
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        interfaces = facts["interfaces"]
        if not interfaces:
            return "# Integration Build Document\n\nNo integration change items were routed to this agent."

        summary = [
            "| Interface | Direction | Trigger | Object Structure | External System |",
            "|---|---|---|---|---|",
        ]
        for i in interfaces:
            summary.append(
                f"| `{i['name']}` | {i['direction']} | {i['trigger']} | `{i['object_structure']}` | `{i['external_system']}` |"
            )

        details = []
        for n, i in enumerate(interfaces, 1):
            if i["direction"] == "Outbound":
                components = f"""| Component | Value |
|---|---|
| Publish Channel | `{i['publish_channel']}` |
| Object Structure | `{i['object_structure']}` |
| External System | `{i['external_system']}` |
| Endpoint | `{i['endpoint']}` |
| Processing | Asynchronous (JMS continuous queue) |

**Configuration steps**

1. **Object Structures** - confirm `{i['object_structure']}` exposes `{i['object']}` with the fields in section 3.
2. **Publish Channels** - create `{i['publish_channel']}` against `{i['object_structure']}`.
3. **External Systems** - create `{i['external_system']}`, set the outbound queue to `sqoutbd`, and enable it.
4. On the External System's Publish Channels tab, add `{i['publish_channel']}` and enable it.
5. **End Points** - create `{i['endpoint']}` with handler `HTTP`, set the URL and credentials.
6. Trigger condition: {i['trigger']}."""
            else:
                components = f"""| Component | Value |
|---|---|
| Enterprise Service | `{i['enterprise_service']}` |
| Object Structure | `{i['object_structure']}` |
| External System | `{i['external_system']}` |
| Inbound queue | `sqin` (sequential) |
| Processing | Asynchronous |

**Configuration steps**

1. **Object Structures** - confirm `{i['object_structure']}` exposes `{i['object']}` with the fields in section 3.
2. **Enterprise Services** - create `{i['enterprise_service']}` against `{i['object_structure']}`, operation `Sync`.
3. **External Systems** - create `{i['external_system']}`, set the inbound queue to `sqin`, and enable it.
4. On the External System's Enterprise Services tab, add `{i['enterprise_service']}` and enable it.
5. Trigger condition: {i['trigger']}."""

            details.append(f"### 2.{n} {i['name']} - {_cell(i['title'], 80)}\n\n{components}\n")

        mapping_rows = ["| " + " | ".join(MAPPING_COLUMNS) + " |", "|" + "---|" * len(MAPPING_COLUMNS)]
        for m in facts["mappings"]:
            mapping_rows.append("| " + " | ".join(str(m.get(c, "")) for c in MAPPING_COLUMNS) + " |")

        return f"""# Integration Build Document

## 1. Interface Summary

{chr(10).join(summary)}

{self.report.summary()}

## 2. Interface Detail

{chr(10).join(details)}

## 3. Field Mapping

{chr(10).join(mapping_rows)}

Every field marked `Validated = YES` was confirmed against the {self.ctx.validator.source_label()}.

## 4. Transformation Rules

- All mappings above are direct, one-to-one.
- Date and datetime fields are exchanged in ISO 8601 with an explicit UTC offset.
- Empty optional fields are omitted from the message rather than sent as empty strings.
- No field is truncated silently: a value longer than the target length raises an error.

## 5. Error Handling

| Condition | Behaviour | Recovery |
|---|---|---|
| Object structure unavailable | Message stays in the queue | Correct the configuration, reprocess from Message Reprocessing |
| Mandatory field missing | Message rejected to the error queue | Fix at source, resubmit |
| Endpoint unreachable | Retry with backoff, then error queue | Check the endpoint and credentials, reprocess |
| Data type mismatch | Message rejected, error logged | Correct the mapping or source value |

Monitor through **Message Reprocessing** and **Message Tracking**.

## 6. Security and Endpoint Configuration

- Credentials are held in the End Point definition, never in a script.
- The external system user needs only the object-level access required by the mapping.
- TLS is required on all HTTP endpoints.

## 7. Test Approach

1. Configure the components in a non-production environment.
2. Trigger a single record and confirm the message is generated.
3. Compare every field in the payload against section 3.
4. Confirm no message is produced for events outside the trigger condition.
5. Force each error condition in section 5 and confirm the recovery path.
"""

    # -- emit --------------------------------------------------------------
    def emit(self, composition: Composition) -> list[Artifact]:
        out = self.ctx.artifact_dir("03b_integration")
        facts = self.facts
        artifacts: list[Artifact] = []

        md = out / "Integration_Build_Document.md"
        md.write_text(composition.body, encoding="utf-8")
        artifacts.append(self.register_artifact(md, kind="md", description="Integration build source"))

        docx = out / "Integration_Build_Document.docx"
        render(
            composition.body,
            template=self.ctx.cfg.template_path("tdd"),
            target=docx,
            title=f"{self.ctx.process_name} - Integration Build Document",
            subtitle=self.ctx.state.title,
        )
        artifacts.append(self.register_artifact(docx, kind="docx", description="Integration build document"))

        if facts["mappings"]:
            xlsx = out / "Field_Mapping.xlsx"
            write_workbook(
                [
                    Sheet(
                        title="Field Mapping",
                        columns=MAPPING_COLUMNS,
                        rows=[[m.get(c, "") for c in MAPPING_COLUMNS] for m in facts["mappings"]],
                    )
                ],
                xlsx,
            )
            artifacts.append(
                self.register_artifact(xlsx, kind="xlsx", description="Source-to-target field mapping")
            )

        spec = out / "mif_components.json"
        spec.write_text(json.dumps(facts["interfaces"], indent=2), encoding="utf-8")
        artifacts.append(
            self.register_artifact(spec, kind="json", description="MIF component specification")
        )

        xml = out / "mif_components.xml"
        xml.write_text(self._mif_xml(facts["interfaces"]), encoding="utf-8")
        artifacts.append(
            self.register_artifact(xml, kind="xml", description="MIF configuration for Migration Manager")
        )
        return artifacts

    def _mif_xml(self, interfaces: list[dict[str, Any]]) -> str:
        root = ET.Element("mifconfig", {"run": self.ctx.state.run_id, "process": self.ctx.process_name})
        for i in interfaces:
            node = ET.SubElement(
                root, "interface", {"name": i["name"], "direction": i["direction"].upper()}
            )
            ET.SubElement(node, "objectstructure", {"name": i["object_structure"], "object": i["object"]})
            ET.SubElement(node, "externalsystem", {"name": i["external_system"], "enabled": "true"})
            if i["direction"] == "Outbound":
                ET.SubElement(
                    node,
                    "publishchannel",
                    {"name": i["publish_channel"], "objectstructure": i["object_structure"], "enabled": "true"},
                )
                ET.SubElement(node, "endpoint", {"name": i["endpoint"], "handler": "HTTP"})
            else:
                ET.SubElement(
                    node,
                    "enterpriseservice",
                    {"name": i["enterprise_service"], "objectstructure": i["object_structure"], "operation": "Sync"},
                )
            ET.SubElement(node, "trigger", {"condition": i["trigger"]})
        _indent(root)
        return "<?xml version='1.0' encoding='UTF-8'?>\n" + ET.tostring(root, encoding="unicode")


def _camel(name: str) -> str:
    parts = re.split(r"[_\s]+", name.lower())
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _indent(elem: ET.Element, level: int = 0) -> None:
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
