"""Requirement-text extraction utilities for deterministic agent templates.

These functions parse plain-English requirement text to pull out Maximo-specific
facts: field types, lengths, copy logic, trigger events, and business rules.
The goal is to make offline/deterministic templates produce genuinely useful,
requirement-specific content rather than generic placeholders.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Maximo field type detection
# ---------------------------------------------------------------------------

_KNOWN_TYPES = ("ALN", "UPPER", "INTEGER", "AMOUNT", "DECIMAL", "DATETIME", "DATE",
                "YORN", "DURATION", "LONGALN", "CRYPTO", "BLOB", "CLOB", "GL")

_TYPE_LABEL_RE = re.compile(
    r'\btype[\s:=]+(' + "|".join(_KNOWN_TYPES) + r')\b', re.I
)
_TYPE_BARE_RE = re.compile(r'\b(' + "|".join(_KNOWN_TYPES) + r')\b', re.I)
_LENGTH_RE = re.compile(r'length[\s:=,]+(\d+)|(\d+)\s*char(?:acter)?s?', re.I)
_MANDATORY_FALSE_RE = re.compile(r'not\s+mandatory|optional|not\s+required|non.?mandatory', re.I)
_MANDATORY_TRUE_RE = re.compile(r'\bmandatory\b|\brequired\b|\bcompulsory\b', re.I)
_PERSISTENT_RE = re.compile(r'\bpersist(?:ent|ed)?\b', re.I)


def field_spec(text: str) -> dict[str, Any]:
    """Extract field type, length and mandatory flag from a requirement string."""
    result: dict[str, Any] = {}

    m = _TYPE_LABEL_RE.search(text)
    if m:
        result["type"] = m.group(1).upper()
    else:
        m = _TYPE_BARE_RE.search(text)
        if m:
            result["type"] = m.group(1).upper()

    m = _LENGTH_RE.search(text)
    if m:
        result["length"] = int(m.group(1) or m.group(2))

    if _MANDATORY_FALSE_RE.search(text):
        result["mandatory"] = False
    elif _MANDATORY_TRUE_RE.search(text):
        result["mandatory"] = True

    if _PERSISTENT_RE.search(text):
        result["persistent"] = True

    return result


# ---------------------------------------------------------------------------
# Copy-value / attribute-propagation logic extraction
# ---------------------------------------------------------------------------

# Matches: "copy OBJECT.ATTR into OBJECT.ATTR" or "propagate X to Y"
_COPY_RE = re.compile(
    r'(?:copy|propagate|transfer|push)\s+'
    r'(?:(?P<src_obj>\w+)\.)?(?P<src_attr>\w+)'
    r'\s+(?:field|attribute)?\s*'
    r'(?:into|to|across\s+to)\s+'
    r'(?:(?:the|a)\s+)?(?:(?P<tgt_obj>\w+)\.)?(?P<tgt_attr>\w+)',
    re.I,
)
# Matches: "populate OBJECT.ATTR with ATTR" or "set X from Y"
_POPULATE_RE = re.compile(
    r'(?:populate|set|fill|write\s+to|store\s+in)\s+'
    r'(?:(?P<tgt_obj>\w+)\.)?(?P<tgt_attr>\w+)'
    r'\s+(?:with|from)\s+'
    r'(?:(?P<src_obj>\w+)\.)?(?P<src_attr>\w+)',
    re.I,
)
_NO_OVERWRITE_RE = re.compile(r"must\s+not|do\s+not|never|don't\s+", re.I)
_OVERWRITE_CTX_RE = re.compile(r'overwrite|overrid', re.I)
_STATUS_TRIGGER_RE = re.compile(
    r'when\s+(?:the\s+)?(?P<obj>\w+)?\s*status\s+changes?\s+to\s+(?P<status>\w+)', re.I
)
_SAVE_TRIGGER_RE = re.compile(r'\bon\s+(?:save|update|insert|add\b)', re.I)
_GENERATE_TRIGGER_RE = re.compile(r'on\s+(?:work\s+order|wo)\s+(?:creation|generation)', re.I)


def copy_logic(rules: list[str]) -> dict[str, Any]:
    """Extract copy/propagation logic from a list of requirement rule strings."""
    combined = " ".join(rules)
    result: dict[str, Any] = {"source": "", "target": "", "no_overwrite": False,
                               "trigger": "Add, Update"}

    # Try explicit copy/propagate patterns
    m = _COPY_RE.search(combined)
    if m:
        result["source_obj"] = (m.group("src_obj") or "").upper()
        result["source"] = m.group("src_attr").upper()
        result["target_obj"] = (m.group("tgt_obj") or "").upper()
        result["target"] = m.group("tgt_attr").upper()
    else:
        m = _POPULATE_RE.search(combined)
        if m:
            result["source_obj"] = (m.group("src_obj") or "").upper()
            result["source"] = m.group("src_attr").upper()
            result["target_obj"] = (m.group("tgt_obj") or "").upper()
            result["target"] = m.group("tgt_attr").upper()

    # Check for "must not overwrite" (across the combined rules)
    sentences = re.split(r'[.;]', combined)
    for sent in sentences:
        if _NO_OVERWRITE_RE.search(sent) and _OVERWRITE_CTX_RE.search(sent):
            result["no_overwrite"] = True
            break

    # Trigger event
    m = _STATUS_TRIGGER_RE.search(combined)
    if m:
        status = m.group("status").upper()
        obj = m.group("obj") or ""
        result["trigger"] = f"Save"
        result["trigger_comment"] = f"fires when {obj} status changes to {status}".strip()
        result["status_trigger"] = status
    elif _GENERATE_TRIGGER_RE.search(combined):
        result["trigger"] = "Save"
        result["trigger_comment"] = "fires on Work Order generation from this record"
    elif _SAVE_TRIGGER_RE.search(combined):
        result["trigger"] = "Save"

    return result


# ---------------------------------------------------------------------------
# Process flow generation from change items
# ---------------------------------------------------------------------------

def process_flow_steps(items: list[Any], process_name: str, applications: list[str]) -> list[str]:
    """Generate a specific, ordered process flow narrative from change items."""
    steps: list[str] = []
    app = applications[0] if applications else process_name

    has_db = any(getattr(i, "change_type", None) and i.change_type.value in ("config",) and getattr(i, "maximo_attribute", None) for i in items)
    has_appdesign = any(getattr(i, "change_type", None) and i.change_type.value == "config" for i in items)
    has_script = any(getattr(i, "change_type", None) and i.change_type.value in ("customisation", "workflow") for i in items)
    has_integration = any(getattr(i, "change_type", None) and i.change_type.value == "integration" for i in items)
    has_security = True  # always required

    step_n = 1

    if has_db:
        attrs = ", ".join(
            f"`{i.maximo_attribute}`" for i in items
            if getattr(i, "maximo_attribute", None) and i.change_type.value == "config"
        )
        step_n_label = f"{step_n}."
        steps.append(
            f"{step_n_label} A Maximo administrator opens **Database Configuration** and adds "
            f"the new attribute(s) {attrs} to the relevant object(s), then runs "
            f"**Apply Configuration Changes** in Admin Mode."
        )
        step_n += 1

    if has_appdesign:
        fields = ", ".join(
            f"`{i.maximo_attribute or i.title[:40]}`" for i in items
            if i.change_type.value == "config"
        )
        steps.append(
            f"{step_n}. The administrator opens **Application Designer**, locates the "
            f"`{app}` application and adds the field control(s) for {fields}. "
            f"The definition is exported and applied."
        )
        step_n += 1

    if has_script:
        script_items = [i for i in items if i.change_type.value in ("customisation", "workflow")]
        for item in script_items:
            steps.append(
                f"{step_n}. An automation script is imported into **Automation Scripts** to "
                f"implement: {item.title[:120]}. "
                f"The script fires on the `{item.maximo_object or process_name}` object."
            )
            step_n += 1

    steps.append(
        f"{step_n}. An end user opens the `{app}` application and creates or updates a "
        f"{process_name} record. The new field(s) and business rules take effect immediately."
    )
    step_n += 1

    if has_integration:
        int_items = [i for i in items if i.change_type.value == "integration"]
        steps.append(
            f"{step_n}. On the configured trigger, the integration layer publishes an outbound "
            f"message for {', '.join(i.title[:60] for i in int_items[:2])}. "
            f"The receiving system acknowledges receipt."
        )
        step_n += 1

    steps.append(
        f"{step_n}. The change is validated against the test cases produced by Agent 4 and "
        f"approved by the designated reviewer before promotion to production."
    )

    return steps


# ---------------------------------------------------------------------------
# Business rule extraction
# ---------------------------------------------------------------------------

_CONDITIONAL_RE = re.compile(r'(?:if|when|only if|unless|provided that)\b.+?(?:[.;]|$)', re.I)
_SHALL_NOT_RE = re.compile(r'(?:shall not|must not|cannot|should not|never)\b', re.I)
_SHALL_RE = re.compile(r'\bshall\b|\bmust\b', re.I)


def business_rules(items: list[Any]) -> list[str]:
    """Extract specific business rules from change item descriptions."""
    rules: list[str] = []
    seen: set[str] = set()

    for item in items:
        text = getattr(item, "description", "") or ""
        # Sentences with conditional or obligation language
        sentences = re.split(r'(?<=[.!?])\s+|\n', text)
        for sent in sentences:
            s = sent.strip()
            if not s or len(s) < 20:
                continue
            if (_CONDITIONAL_RE.search(s) or _SHALL_NOT_RE.search(s)) and s not in seen:
                # Trim to first 200 chars; clean up newlines
                rule = " ".join(s[:200].split())
                rules.append(f"- **{item.id}** — {rule}")
                seen.add(s)

    return rules


# ---------------------------------------------------------------------------
# Jython code generation
# ---------------------------------------------------------------------------

def jython_body(script: dict[str, Any], rules: list[str] | None = None) -> str:
    """Generate a Jython 2.7 MBO-API script from a script spec and its rules.

    Recognises several well-known Maximo relationship patterns (PM→WO,
    MULTIASSETLOCCI copy, simple field copy) and generates correct MBO API code
    for each rather than a generic SOURCE_FIELD → TARGET_FIELD placeholder.
    """
    rules = rules or script.get("rules", [])
    logic = copy_logic(rules)
    combined = " ".join(rules).lower()

    src = logic.get("source") or script.get("attribute") or ""
    tgt = logic.get("target") or ""
    no_overwrite = logic.get("no_overwrite", False)
    trigger_comment = logic.get("trigger_comment", "")
    status_trigger = logic.get("status_trigger", "")
    has_publish = any(re.search(r'publish|outbound|external\s+system|interface', r, re.I) for r in rules)

    header = [
        f'# {script["name"]}',
        f'# Launch point : {script["name"]}_LP  ({script["launch_point"]})',
        f'# Object       : {script["object"]}',
        f'# Events       : {script["event"]}',
        f'# Language     : Jython 2.7',
        '',
        f'# Purpose: {script["purpose"]}',
    ]
    if trigger_comment:
        header.append(f'# Trigger      : {trigger_comment}')
    header += [
        '',
        '# Uses the MBO API only. No direct SQL — Maximo caching and field',
        '# validation would be bypassed and the change would not be auditable.',
        '',
        'from psdi.mbo import MboConstants',
        '',
    ]

    body_lines: list[str] = []

    # -----------------------------------------------------------------------
    # Pattern A: PM → WORKORDER relationship traversal
    # Detected when the script or rules mention PM/preventive maintenance AND
    # work order, and the object is WORKORDER.
    # -----------------------------------------------------------------------
    is_pm_to_wo = (
        re.search(r'\bpm\b|preventive|preventative|planned.mainten', combined)
        and re.search(r'work.?order|workorder', combined)
    ) or (
        script.get("object", "").upper() == "WORKORDER"
        and re.search(r'\bpm\b', combined)
    )

    # Pattern B: MULTIASSETLOCCI copy (from PM or within WO)
    is_multiasset_copy = re.search(
        r'multiassetlocci|multi.?asset|inspection.?form|multiple.?asset|locci', combined
    )

    if is_pm_to_wo and is_multiasset_copy:
        # PM → WO: copy MULTIASSETLOCCI child rows
        overwrite_guard = (
            '        if wo_multi_set.isEmpty():'
            if no_overwrite else ''
        )
        copy_indent = '            ' if no_overwrite else '                '
        body_lines += [
            'from psdi.util.logging import MXLoggerFactory',
            'log = MXLoggerFactory.getLogger("maximo.script." + scriptName)',
            '',
            '# Guard: only copy on newly generated WOs — skip edits to existing records.',
            'if mbo.isNew():',
            '    orig_class = mbo.getString("ORIGRECORDCLASS")',
            '    orig_id    = mbo.getString("ORIGRECORDID")   # PMNUM of the parent PM',
            '',
            '    if orig_class == "PM" and orig_id is not None and orig_id.strip() != "":',
            '        pm_set       = None',
            '        pm_multi_set = None',
            '        wo_multi_set = None',
            '        try:',
            '            site_id = mbo.getString("SITEID")',
            '            # Open the parent PM by PMNUM + SITEID (ad-hoc set avoids relationship timing issues on new WO).',
            '            pm_set = service.getMboSet(',
            '                "$WO_PMMULTI_PM",',
            '                "PM",',
            '                "PMNUM=\'" + orig_id + "\' AND SITEID=\'" + site_id + "\'"',
            '            )',
            '            pm_set.reset()',
            '',
            '            if not pm_set.isEmpty():',
            '                pm_mbo = pm_set.getMbo(0)',
            '                pm_multi_set = pm_mbo.getMboSet("MULTIASSETLOCCI")',
            '                pm_multi_set.reset()',
            '',
            '                if not pm_multi_set.isEmpty():',
            '                    wo_multi_set = mbo.getMboSet("MULTIASSETLOCCI")',
        ]
        if no_overwrite:
            body_lines += [
                '                    # Must-not-overwrite: only copy when WO has no existing rows.',
                '                    if wo_multi_set.isEmpty():',
                '                        src_row = pm_multi_set.moveFirst()',
                '                        while src_row is not None:',
                '                            new_row = wo_multi_set.add()',
                '                            new_row.setValue("ASSETNUM",  src_row.getString("ASSETNUM"),  MboConstants.NOACCESSCHECK)',
                '                            new_row.setValue("LOCATION",  src_row.getString("LOCATION"),  MboConstants.NOACCESSCHECK)',
                '                            new_row.setValue("SITEID",    src_row.getString("SITEID"),    MboConstants.NOACCESSCHECK)',
                '                            new_row.setValue("ORGID",     src_row.getString("ORGID"),     MboConstants.NOACCESSCHECK)',
                '                            new_row.setValue("DESCRIPTION", src_row.getString("DESCRIPTION"), MboConstants.NOACCESSCHECK)',
                '                            if not src_row.isNull("ASSETLOCPRIORITY"):',
                '                                new_row.setValue("ASSETLOCPRIORITY", src_row.getInt("ASSETLOCPRIORITY"), MboConstants.NOACCESSCHECK)',
                '                            if not src_row.isNull("INSPECTIONFORM"):',
                '                                new_row.setValue("INSPECTIONFORM", src_row.getString("INSPECTIONFORM"), MboConstants.NOACCESSCHECK)',
                '                            if not src_row.isNull("PARENT"):',
                '                                new_row.setValue("PARENT", src_row.getString("PARENT"), MboConstants.NOACCESSCHECK)',
                '                            src_row = pm_multi_set.moveNext()',
                '                        log.info(scriptName + ": Copied MULTIASSETLOCCI rows from PM " + orig_id)',
            ]
        else:
            body_lines += [
                '                    wo_multi_set.deleteAll()',
                '                    src_row = pm_multi_set.moveFirst()',
                '                    while src_row is not None:',
                '                        new_row = wo_multi_set.add()',
                '                        new_row.setValue("ASSETNUM",  src_row.getString("ASSETNUM"),  MboConstants.NOACCESSCHECK)',
                '                        new_row.setValue("LOCATION",  src_row.getString("LOCATION"),  MboConstants.NOACCESSCHECK)',
                '                        new_row.setValue("SITEID",    src_row.getString("SITEID"),    MboConstants.NOACCESSCHECK)',
                '                        new_row.setValue("ORGID",     src_row.getString("ORGID"),     MboConstants.NOACCESSCHECK)',
                '                        new_row.setValue("DESCRIPTION", src_row.getString("DESCRIPTION"), MboConstants.NOACCESSCHECK)',
                '                        if not src_row.isNull("ASSETLOCPRIORITY"):',
                '                            new_row.setValue("ASSETLOCPRIORITY", src_row.getInt("ASSETLOCPRIORITY"), MboConstants.NOACCESSCHECK)',
                '                        if not src_row.isNull("INSPECTIONFORM"):',
                '                            new_row.setValue("INSPECTIONFORM", src_row.getString("INSPECTIONFORM"), MboConstants.NOACCESSCHECK)',
                '                        if not src_row.isNull("PARENT"):',
                '                            new_row.setValue("PARENT", src_row.getString("PARENT"), MboConstants.NOACCESSCHECK)',
                '                        src_row = pm_multi_set.moveNext()',
                '                    log.info(scriptName + ": Copied MULTIASSETLOCCI rows from PM " + orig_id)',
            ]
        body_lines += [
            '        except Exception as e:',
            '            log.error(scriptName + " failed for PM " + str(orig_id) + ": " + str(e))',
            '            raise',
            '        finally:',
            '            # Always close MboSets — memory leak if omitted.',
            '            if pm_multi_set is not None:',
            '                try: pm_multi_set.close()',
            '                except: pass',
            '            if wo_multi_set is not None:',
            '                try: wo_multi_set.close()',
            '                except: pass',
            '            if pm_set is not None:',
            '                try: pm_set.close()',
            '                except: pass',
        ]

    elif is_pm_to_wo:
        # PM → WO: copy a specific field
        src_field = src or "INSPECTIONFORM"
        tgt_field = tgt or src_field
        body_lines += [
            'from psdi.util.logging import MXLoggerFactory',
            'log = MXLoggerFactory.getLogger("maximo.script." + scriptName)',
            '',
            'if mbo.isNew():',
            '    orig_class = mbo.getString("ORIGRECORDCLASS")',
            '    orig_id    = mbo.getString("ORIGRECORDID")',
            '',
            '    if orig_class == "PM" and orig_id is not None and orig_id.strip() != "":',
            '        pm_set = None',
            '        try:',
            '            pm_set = service.getMboSet(',
            '                "$WO_PMFIELD",',
            '                "PM",',
            '                "PMNUM=\'" + orig_id + "\' AND SITEID=\'" + mbo.getString("SITEID") + "\'"',
            '            )',
            '            pm_set.reset()',
            '            if not pm_set.isEmpty():',
            '                pm_rec  = pm_set.getMbo(0)',
            f'                src_val = pm_rec.getString("{src_field}")',
            '                if src_val is not None and src_val.strip() != "":',
        ]
        if no_overwrite:
            body_lines += [
                f'                    existing = mbo.getString("{tgt_field}")',
                '                    if existing is None or existing.strip() == "":',
                f'                        mbo.setValue("{tgt_field}", src_val, MboConstants.NOACCESSCHECK)',
            ]
        else:
            body_lines += [
                f'                    mbo.setValue("{tgt_field}", src_val, MboConstants.NOACCESSCHECK)',
            ]
        body_lines += [
            '        except Exception as e:',
            '            log.error(scriptName + " PM field copy failed: " + str(e))',
            '            raise',
            '        finally:',
            '            if pm_set is not None:',
            '                try: pm_set.close()',
            '                except: pass',
        ]

    elif status_trigger:
        body_lines += [
            f'current_status = mbo.getString("STATUS")',
            '',
            f'if current_status == "{status_trigger}":',
        ]
        if has_publish:
            body_lines += [
                '    # Trigger outbound integration message via the Publish Channel.',
                '    # The message will be queued for the configured external system endpoint.',
                '    pass  # Publish Channel fires automatically on status change — no script action needed.',
                '    # To add pre-send enrichment, populate any required fields here before the status saves.',
            ]
        else:
            s = src or "SOURCE_FIELD"
            t = tgt or "TARGET_FIELD"
            body_lines += [
                f'    source_value = mbo.getString("{s}")',
                f'    if source_value is not None and source_value.strip() != "":',
            ]
            if no_overwrite:
                body_lines += [
                    f'        current = mbo.getString("{t}")',
                    f'        if current is None or current.strip() == "":',
                    f'            mbo.setValue("{t}", source_value, MboConstants.NOACCESSCHECK)',
                ]
            else:
                body_lines += [
                    f'        mbo.setValue("{t}", source_value, MboConstants.NOACCESSCHECK)',
                ]

    else:
        # Generic field-copy pattern
        s = src or "SOURCE_FIELD"
        t = tgt or "TARGET_FIELD"
        body_lines += [
            f'source_value = mbo.getString("{s}")',
            '',
            f'if source_value is not None and source_value.strip() != "":',
        ]
        if no_overwrite:
            body_lines += [
                '    # Requirement: must not overwrite a value the user has already entered.',
                f'    current_value = mbo.getString("{t}")',
                f'    if current_value is None or current_value.strip() == "":',
                f'        mbo.setValue("{t}", source_value, MboConstants.NOACCESSCHECK)',
            ]
        else:
            body_lines += [
                f'    mbo.setValue("{t}", source_value, MboConstants.NOACCESSCHECK)',
            ]

    all_lines = header + body_lines
    return "\n".join(line for line in all_lines if line is not None)


# ---------------------------------------------------------------------------
# DB Configuration step generator
# ---------------------------------------------------------------------------

def db_config_steps(item: Any, spec: dict[str, Any], existing: bool = False) -> list[str]:
    """Generate numbered DB Configuration steps for one change item."""
    obj = getattr(item, "maximo_object", None) or "TBC"
    attr = getattr(item, "maximo_attribute", None) or "TBC"
    desc = " ".join((getattr(item, "description", "") or "")[:80].split())

    # Extract from description if spec not available
    parsed = field_spec(desc)
    ftype = spec.get("type") or parsed.get("type") or "ALN"
    length = spec.get("length") or parsed.get("length") or 100
    mandatory = spec.get("required", parsed.get("mandatory", False))
    action = "Modify existing attribute" if existing else "Add new attribute"

    steps = [
        f"1. Open **Database Configuration** (Go To → System Configuration → Platform Configuration → Database Configuration).",
        f"2. In the Object field, type `{obj}` and press Enter.",
        f"3. Navigate to the **Attributes** tab.",
        f"4. Click **New Row** to add a new attribute.",
        f"5. Enter the following values:",
        f"   - **Attribute**: `{attr}`",
        f"   - **Description**: {desc[:80] or item.title[:80]}",
        f"   - **Type**: `{ftype}`",
        f"   - **Length / Precision**: `{length}`",
        f"   - **Persistent**: Yes",
        f"   - **Required**: {'Yes' if mandatory else 'No'}",
        f"6. Click **Save** (floppy disk icon).",
        f"7. Go to **Go To → System Configuration → Platform Configuration → Apply Configuration Changes**.",
        f"8. Tick `{obj}` and click **Apply Changes Now**. (Action: {action})",
    ]
    return steps


# ---------------------------------------------------------------------------
# Application Designer step generator
# ---------------------------------------------------------------------------

def app_designer_steps(item: Any, app: str, tab: str = "Main") -> list[str]:
    """Generate numbered App Designer steps for one field change."""
    attr = getattr(item, "maximo_attribute", None) or "the new attribute"
    label = item.title[:60] if hasattr(item, "title") else attr

    return [
        f"1. Open **Application Designer** (Go To → System Configuration → Platform Configuration → Application Designer).",
        f"2. In the Application field, type `{app}` and press Enter.",
        f"3. Click **Export Application Definition** and save as a backup.",
        f"4. Select the **{tab}** tab in the design canvas.",
        f"5. Drag a **Textbox** control from the palette onto the section where the field should appear.",
        f"6. In the control properties panel:",
        f"   - **Label**: `{label}`",
        f"   - **Attribute**: `{attr}`",
        f"   - **Input Mode**: default",
        f"   - **Required** (if applicable): {'Yes' if getattr(item, 'mandatory', False) else 'No'}",
        f"7. Click **Save** (floppy disk icon).",
        f"8. Click **Export Application Definition** to capture the final XML for migration.",
    ]


# ---------------------------------------------------------------------------
# Maximo-specific narrative generator (offline "brain" for deterministic mode)
# ---------------------------------------------------------------------------

# Pattern detection regexes
_PM_RE = re.compile(r'\bpm\b|preventive.maint|planned.maint', re.I)
_WO_RE = re.compile(r'work.?order|workorder|\bwo\b', re.I)
_MULTI_RE = re.compile(r'multiassetlocci|multi.?asset|inspection.?form|inspection.?route|locci', re.I)
_STATUS_RE = re.compile(r'status.change|when.+status|on.+status', re.I)
_FIELD_COPY_RE = re.compile(r'\bcopy\b|\bpropagate\b|\btransfer\b|\binherit\b', re.I)
_INTEGRATION_RE = re.compile(r'\bintegrat|\binterface\b|\bpublish\b|\bexternal\b|\bapi\b', re.I)
_WORKFLOW_RE = re.compile(r'\bworkflow\b|\bapproval\b|\broute\b', re.I)
_DOMAIN_RE = re.compile(r'\bdomain\b|\bpick.?list\b|\bdropdown\b|\blist.?of.?values', re.I)
_SECURITY_RE = re.compile(r'\bsecurity\b|\baccess\b|\bpermission\b|\brole\b', re.I)


def _detect_pattern(items: list[Any], scripts: list[dict]) -> str:
    """Classify the dominant requirement pattern for narrative generation."""
    combined = " ".join(
        (getattr(i, "description", "") or "") + " " + (getattr(i, "title", "") or "")
        for i in items
    ) + " ".join(s.get("purpose", "") + " " + " ".join(s.get("rules", [])) for s in scripts)

    is_pm = bool(_PM_RE.search(combined))
    is_wo = bool(_WO_RE.search(combined))
    is_multi = bool(_MULTI_RE.search(combined))
    is_status = bool(_STATUS_RE.search(combined))
    has_script = any(i.change_type.value in ("customisation", "workflow") for i in items if hasattr(i, "change_type"))
    has_integration = any(i.change_type.value == "integration" for i in items if hasattr(i, "change_type"))

    if is_pm and is_wo and is_multi:
        return "pm_wo_multiasset"
    elif is_pm and is_wo and has_script:
        return "pm_wo_field_copy"
    elif is_status and has_script:
        return "status_trigger"
    elif has_integration:
        return "integration"
    elif _WORKFLOW_RE.search(combined):
        return "workflow"
    elif has_script:
        return "field_copy"
    else:
        return "config"


_NARRATIVE: dict[str, dict[str, str]] = {
    "pm_wo_multiasset": {
        "executive_summary": (
            "This document specifies the automation of **MULTIASSETLOCCI** (Multi-Asset/Location) "
            "record propagation from **Preventive Maintenance (PM)** records to **Work Orders** "
            "generated by the `PMWOEGENCRON` cron task.\n\n"
            "When a Work Order is created from a PM record, Maximo sets `WORKORDER.ORIGRECORDCLASS = 'PM'` "
            "and `WORKORDER.ORIGRECORDID = <PMNUM>` on the generated WO. Out-of-the-box, Maximo does "
            "**not** automatically copy the PM's MULTIASSETLOCCI child rows (inspection route stops / "
            "multi-asset entries) to the generated Work Order. Field crews opening the WO in "
            "**Work Order Tracking (WOTRACK)** would find an empty Multi-Asset/Location tab, "
            "requiring manual data re-entry for every generated WO.\n\n"
            "This change implements an Object launch point automation script on `WORKORDER` (Save event) "
            "that detects PM-generated WOs and copies all MULTIASSETLOCCI rows — including asset numbers, "
            "location codes, descriptions, sequence priorities, and Inspection Form assignments (MAS 8/9) "
            "— from the parent PM to the new Work Order automatically."
        ),
        "business_context": (
            "IBM Maximo's Preventive Maintenance module schedules recurring maintenance work via the "
            "`PMWOEGENCRON` cron task (System Configuration → Platform Configuration → Cron Task Setup). "
            "When a PM record's `NEXTDUEDATE` falls within the configured `LEADTIME` window, the cron "
            "task generates a `WORKORDER` record and stamps `ORIGRECORDCLASS = 'PM'` and "
            "`ORIGRECORDID = PMNUM` on the WO to preserve the PM lineage.\n\n"
            "For inspection routes — PMs that define multiple assets or locations to be visited in a "
            "single work cycle — maintenance planners populate the **Multi-Asset/Location** tab "
            "(`MULTIASSETLOCCI`) on the PM record. Each row in this child object represents one stop "
            "on the route, carrying the asset number, location, priority sequence, description, and "
            "(in MAS 8/9) the linked Inspection Form that field crew must complete at that stop.\n\n"
            "Without this automation, every PM-generated WO requires a planner to manually re-enter "
            "the full inspection route — a repetitive, error-prone step that negates the efficiency "
            "benefit of the PM module for route-based work."
        ),
        "solution_overview": (
            "The solution is a single **Automation Script** with an Object launch point on `WORKORDER`, "
            "triggered on the `Save` event. Using the `Save` event (not `afterSave`) ensures that the "
            "MULTIASSETLOCCI child rows are committed atomically within the same database transaction "
            "as the Work Order itself — no risk of an orphaned WO with a missing route.\n\n"
            "**Why Save (not afterSave)?** During the `Save` event, child MBO sets added to the WO "
            "are committed in the same transaction. `afterSave` would require a separate `save()` "
            "call on the child set, creating a two-phase commit risk.\n\n"
            "**No Database Configuration changes are required.** `MULTIASSETLOCCI` is a standard, "
            "delivered Maximo object. All fields being copied (ASSETNUM, LOCATION, SITEID, ORGID, "
            "DESCRIPTION, ASSETLOCPRIORITY, INSPECTIONFORM, PARENT, POSITIONPURPOSE) exist in the "
            "OOTB schema. No new attributes need to be added via DB Config.\n\n"
            "**No Application Designer changes are required.** The Multi-Asset/Location tab on "
            "Work Order Tracking (WOTRACK) is delivered out-of-the-box and will display the copied "
            "rows automatically once the script populates them."
        ),
        "db_config_note": (
            "> **No Database Configuration changes are required for this change set.**\n"
            ">\n"
            "> `MULTIASSETLOCCI` is a standard delivered Maximo object. All fields involved in the "
            "copy operation — `ASSETNUM`, `LOCATION`, `SITEID`, `ORGID`, `DESCRIPTION`, "
            "`ASSETLOCPRIORITY`, `INSPECTIONFORM`, `PARENT`, `POSITIONPURPOSE` — exist in the "
            "out-of-the-box Maximo schema and require no DDL changes. Switch Maximo to **Admin Mode** "
            "only if an unrelated attribute must be added in the same release."
        ),
        "app_config_note": (
            "> **No Application Designer changes are required for this change set.**\n"
            ">\n"
            "> The **Multi-Asset/Location** tab on **Work Order Tracking (WOTRACK)** is delivered "
            "out-of-the-box and renders `MULTIASSETLOCCI` rows automatically. Once the automation "
            "script populates these rows on save, field crews will see the full inspection route "
            "immediately when opening the generated WO — no UI configuration required."
        ),
        "security_note": (
            "No new security grants are required for the MULTIASSETLOCCI copy itself. The automation "
            "script runs with system-level privileges via `MboConstants.NOACCESSCHECK` and does not "
            "expose new UI controls.\n\n"
            "Verify that all Security Groups with access to **Work Order Tracking (WOTRACK)** have "
            "`Read` and `Insert` access to the `MULTIASSETLOCCI` object on the **Object Restrictions** "
            "tab. This is typically granted by default in the OOTB MAXADMIN and MAXEVERYONE groups."
        ),
        "business_rules": [
            "- **BR-001** — The copy shall execute only when `WORKORDER.ORIGRECORDCLASS = 'PM'` and `WORKORDER.ORIGRECORDID` is not null or blank.",
            "- **BR-002** — The copy shall execute only on newly generated Work Orders (`mbo.isNew() = true`). Editing or saving an existing WO must not trigger the copy.",
            "- **BR-003** — Fields copied per MULTIASSETLOCCI row: `ASSETNUM`, `LOCATION`, `SITEID`, `ORGID`, `DESCRIPTION`, `ASSETLOCPRIORITY`, `INSPECTIONFORM` (MAS 8/9), `PARENT` (when not null), `POSITIONPURPOSE` (when not null).",
            "- **BR-004** — `MULTIID` is a system-generated AUTOKEY. The script must never set this field — Maximo assigns it automatically when the row is added.",
            "- **BR-005** — If the source PM has no MULTIASSETLOCCI rows, the script shall log an informational message and exit without error or exception.",
            "- **BR-006** — All MboSets opened within the script must be closed in a `finally` block to prevent memory leaks under batch WO generation.",
            "- **BR-007** — The script must log entry/exit and the count of rows copied using `MXLoggerFactory` at `INFO` level for operational traceability.",
        ],
        "process_flow": [
            "1. A Maximo administrator or the `PMWOEGENCRON` cron task initiates Work Order generation from a PM record.",
            "2. Maximo creates a new `WORKORDER` record with `ORIGRECORDCLASS = 'PM'` and `ORIGRECORDID = <PMNUM>` stamped automatically.",
            "3. On the Save event of the new Work Order, the automation script `WO_PM_MULTIASSETLOCCI_COPY` fires.",
            "4. The script reads `ORIGRECORDCLASS` and `ORIGRECORDID` from the WO. If `ORIGRECORDCLASS ≠ 'PM'` or `ORIGRECORDID` is null, the script exits with no action.",
            "5. The script opens the parent PM record via an ad-hoc MboSet query on `PM` filtered by `PMNUM` and `SITEID`.",
            "6. The script reads each MULTIASSETLOCCI row from the PM and adds a matching row to the WO's MULTIASSETLOCCI child set, copying all required fields.",
            "7. All MboSets are closed in the `finally` block. The WO and its MULTIASSETLOCCI rows are committed to the database in a single transaction.",
            "8. The field crew opens the Work Order in Work Order Tracking (WOTRACK). The Multi-Asset/Location tab displays the full inspection route, ready for execution.",
        ],
        "testing": [
            "| TC-001 | PM with 3 MULTIASSETLOCCI rows → Generate WO | WO Multi-Asset/Location tab shows 3 rows; ASSETNUM, LOCATION, DESCRIPTION match PM |",
            "| TC-002 | PM with 0 MULTIASSETLOCCI rows → Generate WO | WO generated successfully; no MULTIASSETLOCCI rows; no errors |",
            "| TC-003 | Manually create WO (not from PM) | Script skips; ORIGRECORDCLASS ≠ 'PM'; no change to WO |",
            "| TC-004 | PM with INSPECTIONFORM linked on rows → Generate WO | WO rows carry same INSPECTIONFORM; visible in MAS Inspections |",
            "| TC-005 | Batch PM generation (PMWOEGENCRON, 20 PMs) | All generated WOs have correct MULTIASSETLOCCI rows; no OutOfMemory |",
            "| TC-006 | Update/save existing PM-generated WO | Script does not re-copy rows (isNew() guard); no duplicate rows |",
        ],
    },
    "pm_wo_field_copy": {
        "executive_summary": (
            "This document specifies automation of field-value propagation from **Preventive Maintenance (PM)** "
            "records to **Work Orders** generated by the `PMWOEGENCRON` cron task. When a Work Order is "
            "created from a PM, Maximo stamps `ORIGRECORDCLASS = 'PM'` and `ORIGRECORDID = <PMNUM>` on the WO. "
            "An automation script on `WORKORDER` (Save event) reads the specified field from the parent PM "
            "record and copies it to the generated WO, eliminating manual re-entry by planners."
        ),
        "business_context": (
            "IBM Maximo generates Work Orders from PM records via the `PMWOEGENCRON` cron task. "
            "Certain PM-level fields (such as inspection form assignments, classification codes, or "
            "custom attributes) are not automatically propagated to the generated WO by OOTB Maximo. "
            "This creates a maintenance overhead for planners who must manually update each generated WO "
            "to carry the correct values from the source PM."
        ),
        "solution_overview": (
            "An Object launch point automation script on `WORKORDER` (Save event) detects WOs generated "
            "from PM records via `ORIGRECORDCLASS = 'PM'`, traverses the PM relationship using an ad-hoc "
            "MboSet query, reads the source field, and sets the corresponding field on the WO. "
            "The script guards against re-execution on existing WOs using `mbo.isNew()` and against "
            "overwriting values already set on the WO where required."
        ),
        "db_config_note": "> Database Configuration changes depend on whether the target field is a custom attribute. Confirm with the Maximo DBA before proceeding.",
        "app_config_note": "> Application Designer changes are required if the field must be visible in WOTRACK. Navigate to App Designer → WOTRACK and add the appropriate control.",
        "security_note": "Verify that all Security Groups with WOTRACK access can read and update the new field. Check Object Restrictions on the WORKORDER object for each group.",
        "business_rules": [],
        "process_flow": [],
        "testing": [],
    },
    "status_trigger": {
        "executive_summary": (
            "This document specifies an automation rule that fires when a Maximo record's status changes "
            "to a specified value. An Object launch point automation script on the target Maximo object "
            "guards on the `STATUS` field and executes the required business logic — field derivation, "
            "notification, or downstream record creation — at the point of status transition."
        ),
        "business_context": (
            "IBM Maximo enforces status transitions via the `changeStatus()` MBO method, which triggers "
            "all registered Object launch point scripts on the Save event. Status-driven automation "
            "is the standard Maximo pattern for triggering business logic at defined lifecycle milestones "
            "without requiring workflow configuration."
        ),
        "solution_overview": (
            "An Object launch point automation script fires on the Save event of the target object. "
            "The script checks `mbo.getString('STATUS')` against the trigger value and executes the "
            "required logic only when the condition is met. "
            "Using the Save event ensures the logic runs in the same transaction as the status change."
        ),
        "db_config_note": "> Confirm whether new attributes are required. If so, add them via Database Configuration before surfacing in App Designer.",
        "app_config_note": "> App Designer changes are required to surface any new fields in the application UI.",
        "security_note": "Update Security Groups to grant access to any new fields or actions introduced by this change.",
        "business_rules": [],
        "process_flow": [],
        "testing": [],
    },
    "field_copy": {
        "executive_summary": (
            "This document specifies an automation rule that propagates field values between Maximo "
            "objects or within the same object at a defined trigger event. An Automation Script with "
            "an Object launch point implements the copy logic using the Maximo MBO API, ensuring "
            "field values are set through the business object layer (not direct SQL) so that all "
            "Maximo validation, auditing, and domain checks are respected."
        ),
        "business_context": (
            "Field value propagation is a common Maximo configuration pattern used to auto-populate "
            "derived or inherited fields, reducing manual data entry and ensuring data consistency "
            "across related objects. The standard implementation is an Automation Script on the "
            "Object launch point, firing on the Save event."
        ),
        "solution_overview": (
            "An Object launch point automation script reads the source field value and sets the "
            "target field using `mbo.setValue(field, value, MboConstants.NOACCESSCHECK)`. "
            "Guard conditions prevent re-execution when not required (e.g., only on new records, "
            "only when the target field is blank, or only on a specific status)."
        ),
        "db_config_note": "> Confirm whether new attributes are required. Add via Database Configuration → Apply Configuration Changes (Admin Mode) before App Designer.",
        "app_config_note": "> If a new field must be visible to users, add a Textbox control in Application Designer and surface it in the appropriate tab/section.",
        "security_note": "Grant Read and Update access to new fields in Security Groups → Object Restrictions for all groups with access to the relevant application.",
        "business_rules": [],
        "process_flow": [],
        "testing": [],
    },
    "config": {
        "executive_summary": (
            "This document specifies configuration changes to the IBM Maximo platform including "
            "Database Configuration (new attributes), Application Designer (UI controls), Domain "
            "configuration (value lists), and Security Group grants."
        ),
        "business_context": (
            "IBM Maximo configuration changes are implemented without code changes, using the "
            "platform's built-in configuration tools: Database Configuration (DB Config) for new "
            "attributes, Application Designer for UI presentation, Domains for value lists, "
            "and Security Groups for access control."
        ),
        "solution_overview": (
            "The change set comprises pure Maximo configuration. New attributes are added via "
            "Database Configuration and surfaced via Application Designer. Domain values are extended "
            "via the Domains application. Security Group grants are updated via Security Groups."
        ),
        "db_config_note": "> Follow the DB Configuration steps in section 4.2 exactly. Always run Apply Configuration Changes in Admin Mode. Turn Admin Mode OFF immediately after.",
        "app_config_note": "> Export the Application Designer XML before making any changes. Store it in version control as the baseline for Migration Manager.",
        "security_note": "Update Security Groups to grant access to all new fields and signature options. Use Copy Security Groups to replicate grants across multiple groups efficiently.",
        "business_rules": [],
        "process_flow": [],
        "testing": [],
    },
    "integration": {
        "executive_summary": (
            "This document specifies an integration interface between IBM Maximo and an external system "
            "using the Maximo Integration Framework (MIF). The interface uses standard MIF components: "
            "Object Structure, Publish Channel (outbound) and/or Enterprise Service (inbound), "
            "External System, and End Point."
        ),
        "business_context": (
            "The Maximo Integration Framework (MIF) provides a standards-based messaging layer for "
            "exchanging data between Maximo and external systems. Outbound messages are triggered by "
            "Publish Channels (event-driven) or Object Structures (API pull). Inbound data is "
            "processed through Enterprise Services and optionally enriched by Integration launch point scripts."
        ),
        "solution_overview": (
            "The interface design comprises an Object Structure defining the data payload, a Publish Channel "
            "for outbound messaging, an Enterprise Service for inbound processing, an External System "
            "grouping the components, and an End Point defining the transport (HTTP, JMS, file)."
        ),
        "db_config_note": "> No Database Configuration changes are required unless the interface requires new custom attributes on the Maximo object.",
        "app_config_note": "> No Application Designer changes are required unless new fields must be visible to users.",
        "security_note": "The integration service account requires Object Structure access. Grant the account an appropriate Security Group with OSLC API access to the relevant Object Structure.",
        "business_rules": [],
        "process_flow": [],
        "testing": [],
    },
}

_DEFAULT_NARRATIVE = _NARRATIVE["config"]


def narrate(items: list[Any], scripts: list[dict] | None = None, process: dict | None = None) -> dict[str, Any]:
    """Return a dict of Maximo-specific narrative strings keyed by document section.

    Analyses the requirement items and script specs to detect the dominant
    Maximo implementation pattern, then returns pre-authored, IBM-accurate
    prose for each section. This is the offline 'Maximo brain' — it produces
    content specific to what the requirement actually asks for, not generic
    placeholders.

    Keys returned:
      executive_summary, business_context, solution_overview,
      db_config_note, app_config_note, security_note,
      business_rules (list[str]), process_flow (list[str]),
      testing (list[str]), pattern (str)
    """
    scripts = scripts or []
    process = process or {}
    pattern = _detect_pattern(items, scripts)
    data = dict(_NARRATIVE.get(pattern, _DEFAULT_NARRATIVE))
    data["pattern"] = pattern

    # Inject the primary script name into the solution overview when available.
    if scripts and "{script_name}" in data.get("solution_overview", ""):
        data["solution_overview"] = data["solution_overview"].replace(
            "{script_name}", scripts[0].get("name", "the automation script")
        )

    # If the template has empty business_rules/process_flow/testing, keep them empty
    # (callers generate fallbacks from the items themselves).
    return data


# ---------------------------------------------------------------------------
# Security step generator
# ---------------------------------------------------------------------------

def security_steps(items: list[Any], app: str) -> list[str]:
    """Generate Security Manager configuration steps."""
    attrs = [getattr(i, "maximo_attribute", None) for i in items if getattr(i, "maximo_attribute", None)]
    attr_list = ", ".join(f"`{a}`" for a in attrs[:8]) or "the new fields"

    return [
        f"1. Open **Security Groups** (Go To → Security → Security Groups).",
        f"2. Query for each security group that currently has access to the `{app}` application.",
        f"3. On the **Applications** tab, locate `{app}`.",
        f"4. Confirm that **Read**, **Insert**, **Update** access is enabled.",
        f"5. On the **Object Restrictions** tab, verify {attr_list} are not hidden or read-only "
        f"unless stated in the Functional Design Document.",
        f"6. Click **Save**.",
        f"7. Use **Copy Security Groups** if multiple groups require identical access.",
    ]
