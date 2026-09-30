"""Maximo environment discovery — auto-generates knowledge/client/ skill files.

Queries the live Maximo environment and writes four markdown files into
knowledge/client/ so agents have accurate, environment-specific context
without any manual editing.

Usage:
    python run.py maximo discover

What it fetches:
  - Sites and Organisations            (mxapisite, mxapiorganization)
  - Security Groups                    (mxapisecuritygroup)
  - Domains                            (mxapidomain)
  - Custom objects + custom attributes (apimeta + jsonschemas vs. bundled catalog)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get

log = get("suite.maximo.discover")

# Standard objects where we look for custom (non-catalog) attributes.
_CORE_OBJECTS = [
    "WORKORDER", "WOACTIVITY", "WPLABOR", "WPMATERIAL", "WPITEM",
    "ASSET", "LOCATIONS", "PM", "MULTIASSETLOCCI",
    "JOBPLAN", "JPTASK", "INSPECTIONFORM",
    "CUJP", "CUELIBRARY",
]

# Object-structure names that are standard IBM — not interesting as "custom".
# These are the well-known MX-prefixed structures exposed by default.
_STANDARD_OS_PREFIXES = (
    "mxapi", "mxsys", "rep_", "conv_", "oct_", "mas", "mx",
    "oslc_", "mxwo", "mxasset", "mxloc",
)


def _is_standard(os_name: str) -> bool:
    lower = os_name.lower()
    return any(lower.startswith(p) for p in _STANDARD_OS_PREFIXES)


def _members(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("member", "rdfs:member", "members"):
            if key in data:
                return data[key] or []
    return []


def _get_safe(client, path: str, params: dict | None = None) -> Any:
    try:
        return client.get(path, params=params)
    except Exception as exc:
        log.debug("fetch failed for %s: %s", path, exc)
        return {}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Individual discovery functions
# ---------------------------------------------------------------------------

def _discover_sites_orgs(client) -> tuple[list[dict], list[dict]]:
    """Fetch all sites and organisations."""
    site_params = {
        "lean": 1,
        "oslc.select": "siteid,orgid,description,active",
        "oslc.pageSize": 200,
    }
    org_params = {
        "lean": 1,
        "oslc.select": "orgid,description,basecurrency1,active",
        "oslc.pageSize": 100,
    }
    sites = _members(_get_safe(client, "os/mxapisite", site_params))
    orgs = _members(_get_safe(client, "os/mxapiorganization", org_params))
    return sites, orgs


def _discover_security_groups(client) -> list[dict]:
    """Fetch all security groups with description."""
    params = {
        "lean": 1,
        "oslc.select": "groupname,description,maxuser,maxusertype",
        "oslc.pageSize": 500,
    }
    return _members(_get_safe(client, "os/mxapisecuritygroup", params))


def _discover_domains(client) -> list[dict]:
    """Fetch ALN / SYNONYM domains (skip numeric/GL ones)."""
    params = {
        "lean": 1,
        "oslc.select": "domainid,description,domaintype",
        "oslc.pageSize": 300,
    }
    all_domains = _members(_get_safe(client, "os/mxapidomain", params))
    return [d for d in all_domains if d.get("domaintype") in ("ALN", "SYNONYM", "NUMERIC")]


def _discover_custom_objects(client, catalog) -> list[dict]:
    """Find object structures not present in the bundled offline catalog."""
    live_names = client.object_structure_names()
    bundled = {p.stem.lower() for p in catalog.schema_dir.glob("*.json")}

    custom = []
    for os_name in sorted(live_names):
        if _is_standard(os_name):
            continue
        if os_name.lower() in bundled:
            continue
        schema = client.object_structure_schema(os_name)
        if not schema:
            continue
        props = schema.get("properties") or schema.get("items", {}).get("properties") or {}
        fields = [
            {"name": k, "type": v.get("subType") or v.get("type", "ALN"), "title": v.get("title", "")}
            for k, v in props.items()
            if not k.startswith("_") and not k.startswith("href")
        ]
        custom.append({
            "os_name": os_name.upper(),
            "description": schema.get("description") or schema.get("title", ""),
            "fields": fields[:30],  # cap display at 30 fields
        })
    return custom


def _discover_custom_attributes(client, catalog) -> list[dict]:
    """For each standard core object, find attributes present in live but not in offline catalog."""
    results = []
    for obj_name in _CORE_OBJECTS:
        # Find the OS name for this MBO
        info = catalog.for_object(obj_name)
        if not info:
            continue
        os_name = info.os_name.lower()

        # Offline catalog attribute names for this object (dict keyed by lowercase name)
        offline_attrs = set(info.attributes.keys())

        # Live schema attributes
        live_schema = client.object_structure_schema(os_name)
        if not live_schema:
            continue

        props = live_schema.get("properties") or live_schema.get("items", {}).get("properties") or {}
        custom_attrs = []
        for attr_name, attr_meta in props.items():
            if attr_name.startswith("_") or attr_name.startswith("href"):
                continue
            if attr_name.lower() in offline_attrs:
                continue
            # Only report attributes that look like real DB columns (have a subType or title)
            if not (attr_meta.get("subType") or attr_meta.get("title")):
                continue
            custom_attrs.append({
                "name": attr_name.upper(),
                "type": (attr_meta.get("subType") or attr_meta.get("type", "ALN")).upper(),
                "length": attr_meta.get("maxLength"),
                "title": attr_meta.get("title", ""),
                "remarks": attr_meta.get("remarks") or attr_meta.get("description", ""),
            })

        if custom_attrs:
            results.append({"object": obj_name, "custom_fields": custom_attrs})
    return results


# ---------------------------------------------------------------------------
# Markdown writers
# ---------------------------------------------------------------------------

def _write_objects(knowledge_dir: Path, custom_objects: list[dict], custom_attrs: list[dict]) -> Path:
    path = knowledge_dir / "mx_client_objects_SKILL.md"
    ts = _timestamp()
    lines = [
        f"# Client Custom Maximo Objects & Fields",
        f"*Auto-generated by `python run.py maximo discover` on {ts}.*",
        f"*Edit this file to add notes. Re-run discover to refresh.*",
        "",
    ]

    # --- Custom objects (non-standard object structures) ---
    if custom_objects:
        lines += [
            "## Custom / Add-on Object Structures",
            "",
            "These object structures exist in the live environment but are not in the standard IBM catalog.",
            "",
            "| Object Structure | Description | Fields |",
            "|---|---|---|",
        ]
        for obj in custom_objects:
            desc = (obj["description"] or "").replace("|", "\\|")[:60]
            lines.append(f"| `{obj['os_name']}` | {desc} | {len(obj['fields'])} |")
        lines.append("")

        for obj in custom_objects:
            lines += [
                f"### `{obj['os_name']}`",
                f"",
                f"{obj['description'] or '(no description)'}",
                "",
                "| Field | Type | Title |",
                "|---|---|---|",
            ]
            for f in obj["fields"]:
                lines.append(f"| `{f['name']}` | {f['type']} | {(f['title'] or '').replace('|', chr(92)+'|')[:50]} |")
            lines.append("")
    else:
        lines += [
            "## Custom / Add-on Object Structures",
            "",
            "*(None detected — all object structures match the standard IBM catalog, or Maximo was not reachable.)*",
            "",
        ]

    # --- Custom attributes on standard objects ---
    if custom_attrs:
        lines += [
            "## Custom Attributes on Standard Objects",
            "",
            "These fields were found in the live environment but are not in the offline IBM schema catalog.",
            "They are likely custom fields added during configuration.",
            "",
        ]
        for entry in custom_attrs:
            lines += [
                f"### `{entry['object']}` — Custom Fields",
                "",
                "| Attribute | Type | Max Length | Title | Remarks |",
                "|---|---|---|---|---|",
            ]
            for attr in entry["custom_fields"]:
                length = str(attr["length"]) if attr["length"] else "—"
                title = (attr["title"] or "").replace("|", "\\|")[:40]
                remarks = (attr["remarks"] or "").replace("|", "\\|")[:60]
                lines.append(f"| `{attr['name']}` | {attr['type']} | {length} | {title} | {remarks} |")
            lines.append("")
    else:
        lines += [
            "## Custom Attributes on Standard Objects",
            "",
            "*(None detected on core objects, or Maximo was not reachable.)*",
            "",
        ]

    lines += [
        "## Notes for AI Agents",
        "",
        "- All DB Configuration changes require Admin Mode + Apply Configuration Changes",
        "- All new attributes must be added to Application Designer before testing",
        "- Scripts use MBO API only — never direct SQL",
        "",
        "*Add client-specific notes below this line:*",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_sites(knowledge_dir: Path, sites: list[dict], orgs: list[dict]) -> Path:
    path = knowledge_dir / "mx_client_sites_SKILL.md"
    ts = _timestamp()
    lines = [
        f"# Client Sites & Organisations",
        f"*Auto-generated by `python run.py maximo discover` on {ts}.*",
        "",
    ]

    if orgs:
        lines += [
            "## Organisations",
            "",
            "| ORGID | Description | Base Currency | Active |",
            "|---|---|---|---|",
        ]
        for o in sorted(orgs, key=lambda x: x.get("orgid", "")):
            orgid = o.get("orgid", "")
            desc = (o.get("description") or "").replace("|", "\\|")[:50]
            curr = o.get("basecurrency1") or "—"
            active = "Yes" if o.get("active") else "No"
            lines.append(f"| `{orgid}` | {desc} | {curr} | {active} |")
        lines.append("")
    else:
        lines += ["## Organisations", "", "*(Could not fetch from Maximo — add manually.)*", ""]

    if sites:
        lines += [
            "## Sites",
            "",
            "| SITEID | ORGID | Description | Active |",
            "|---|---|---|---|",
        ]
        for s in sorted(sites, key=lambda x: (x.get("orgid", ""), x.get("siteid", ""))):
            siteid = s.get("siteid", "")
            orgid = s.get("orgid", "")
            desc = (s.get("description") or "").replace("|", "\\|")[:50]
            active = "Yes" if s.get("active") else "No"
            lines.append(f"| `{siteid}` | `{orgid}` | {desc} | {active} |")
        lines.append("")
    else:
        lines += ["## Sites", "", "*(Could not fetch from Maximo — add manually.)*", ""]

    lines += [
        "## Site-Specific Business Rules",
        "",
        "Add rules that apply to specific sites here. Example format:",
        "",
        "**Rule:** PM-to-WO field copy for CLASSSTRUCTUREID",
        "**Applies to:** SITEID = BEDFORD, ORGID = ENGELINA",
        "**Does NOT apply to:** other sites",
        "**Implementation:** Automation script on WORKORDER OBJECT launch point, afterSave",
        "",
        "*Add your actual site-specific rules below:*",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_security(knowledge_dir: Path, groups: list[dict]) -> Path:
    path = knowledge_dir / "mx_client_security_SKILL.md"
    ts = _timestamp()
    lines = [
        f"# Client Security Groups",
        f"*Auto-generated by `python run.py maximo discover` on {ts}.*",
        "",
    ]

    if groups:
        lines += [
            "## Security Group Inventory",
            "",
            f"Found {len(groups)} security group(s) in the live environment.",
            "",
            "| Group Name | Description |",
            "|---|---|",
        ]
        for g in sorted(groups, key=lambda x: x.get("groupname", "")):
            name = g.get("groupname", "")
            desc = (g.get("description") or "").replace("|", "\\|")[:70]
            lines.append(f"| `{name}` | {desc} |")
        lines.append("")
    else:
        lines += [
            "## Security Group Inventory",
            "",
            "*(Could not fetch from Maximo — add manually.)*",
            "",
        ]

    lines += [
        "## Access Rules for This Project",
        "",
        "Edit this section to specify which groups need access to new fields/apps:",
        "",
        "| Group | Application | Access Level | Restrictions |",
        "|---|---|---|---|",
        "| (group name) | WOTRACK | Full | (none) |",
        "| (group name) | WOTRACK | Read-only | Cannot change status |",
        "",
        "## New Field Security Default",
        "",
        "When new attributes are added, grant CHANGE access to:",
        "- (list the groups here)",
        "",
        "*Add client-specific security rules below:*",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_domains(knowledge_dir: Path, domains: list[dict]) -> Path:
    path = knowledge_dir / "mx_client_domains_SKILL.md"
    ts = _timestamp()
    lines = [
        f"# Client Domains & Value Lists",
        f"*Auto-generated by `python run.py maximo discover` on {ts}.*",
        "",
    ]

    if domains:
        lines += [
            "## Domain Inventory",
            "",
            f"Found {len(domains)} ALN/SYNONYM/NUMERIC domain(s) in the live environment.",
            "",
            "| Domain ID | Type | Description |",
            "|---|---|---|",
        ]
        for d in sorted(domains, key=lambda x: x.get("domainid", "")):
            did = d.get("domainid", "")
            dtype = d.get("domaintype", "")
            desc = (d.get("description") or "").replace("|", "\\|")[:60]
            lines.append(f"| `{did}` | {dtype} | {desc} |")
        lines.append("")
    else:
        lines += [
            "## Domain Inventory",
            "",
            "*(Could not fetch from Maximo — add manually.)*",
            "",
        ]

    lines += [
        "## Notes for AI Agents",
        "",
        "- When a new attribute needs a value list, create an ALN domain in Domains application",
        "- Bind the domain to the attribute in Database Configuration (Attribute → Domain field)",
        "- SYNONYM domains translate internal codes to display values",
        "",
        "*Add domain usage notes below:*",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_discover(client, catalog, knowledge_dir: Path) -> dict[str, Any]:
    """Run all discovery queries and write knowledge/client/ files.

    Returns a stats dict with counts for each category.
    """
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {}

    log.info("discovering sites and organisations…")
    sites, orgs = _discover_sites_orgs(client)
    stats["sites"] = len(sites)
    stats["orgs"] = len(orgs)

    log.info("discovering security groups…")
    groups = _discover_security_groups(client)
    stats["security_groups"] = len(groups)

    log.info("discovering domains…")
    domains = _discover_domains(client)
    stats["domains"] = len(domains)

    log.info("discovering custom object structures…")
    custom_objects = _discover_custom_objects(client, catalog)
    stats["custom_objects"] = len(custom_objects)

    log.info("discovering custom attributes on standard objects…")
    custom_attrs = _discover_custom_attributes(client, catalog)
    stats["objects_with_custom_attrs"] = len(custom_attrs)
    stats["total_custom_attrs"] = sum(len(e["custom_fields"]) for e in custom_attrs)

    log.info("writing knowledge files…")
    stats["files"] = []

    f = _write_objects(knowledge_dir, custom_objects, custom_attrs)
    stats["files"].append(f.name)

    f = _write_sites(knowledge_dir, sites, orgs)
    stats["files"].append(f.name)

    f = _write_security(knowledge_dir, groups)
    stats["files"].append(f.name)

    f = _write_domains(knowledge_dir, domains)
    stats["files"].append(f.name)

    return stats
