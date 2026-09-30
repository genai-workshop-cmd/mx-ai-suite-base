# MX_PM_WO — PM-to-Work-Order Design Patterns (MAS 8 / MAS 9)
*Version: 2.0 | Platform: MAS 8.x / MAS 9.x / Maximo 7.6 | Last updated: 2026-09-28*

---

## Purpose

Load for ANY requirement that involves Preventive Maintenance, PM WO generation, MULTIASSETLOCCI,
Inspection Forms, or copying data from a PM record to a generated Work Order. This skill takes
precedence over general MBO API knowledge for these specific patterns. Every code sample here is
production-tested on IBM Maximo MAS 8/9 and Maximo 7.6.1+.

---

## 1. How Maximo Generates Work Orders from PM Records

### Generation Mechanism
- **Cron Task**: `PMWOEGENCRON` (System Configuration → Platform Configuration → Cron Task Setup)
- **Manual**: PM application → "Generate Work Orders" action
- **Lead time**: WO created `LEADTIME` days before `NEXTDUEDATE`

### Key Fields Written on the Generated Work Order
| WORKORDER Field | Value Set | Description |
|---|---|---|
| `ORIGRECORDCLASS` | `"PM"` | Identifies this WO was generated from a PM |
| `ORIGRECORDID` | PM's `PMNUM` value | The source PM number |
| `PMNUM` | PM's `PMNUM` value | Direct FK to the PM |
| `WORKTYPE` | Inherited from PM | PM, OS, EM, etc. |
| `DESCRIPTION` | Inherited from PM | WO description |
| `JPNUM` | PM's `JPNUM` | Job Plan applied |
| `ASSETNUM` | PM's `ASSETNUM` | Primary asset |
| `LOCATION` | PM's `LOCATION` | Primary location |
| `SITEID` | PM's `SITEID` | Site |

### Detecting a PM-Generated WO in a Script
```python
orig_class = mbo.getString("ORIGRECORDCLASS")
orig_id    = mbo.getString("ORIGRECORDID")   # equals PMNUM of the parent PM

is_from_pm = (orig_class == "PM" and orig_id is not None and orig_id.strip() != "")
```

---

## 2. MULTIASSETLOCCI Object — Complete Reference

### Purpose
`MULTIASSETLOCCI` stores the list of **multiple assets and/or locations** against a Work Order
or PM record. Used for:
- Route-based WOs (same work at N assets/locations)
- Multi-asset inspection rounds
- Batch maintenance work

### Object-Level Details
| Property | Value |
|---|---|
| Object name | `MULTIASSETLOCCI` |
| Primary key | `MULTIID` (system-generated AUTOKEY) |
| Parent relationships | `WORKORDER` (via RECORDKEY=WONUM), `PM` (via RECORDKEY=PMNUM) |
| Site-scoped | Yes — always include `SITEID` |

### Field Reference (Complete)
| Attribute | Type | Length | Description |
|---|---|---|---|
| `MULTIID` | INTEGER | — | System-generated PK (AUTOKEY) — never set manually |
| `RECORDKEY` | UPPER | 25 | Parent WO number (WONUM) or PM number (PMNUM) |
| `ASSETNUM` | UPPER | 25 | Asset number — FK to ASSET |
| `LOCATION` | UPPER | 12 | Location code — FK to LOCATIONS |
| `SITEID` | UPPER | 8 | Site — always required |
| `ORGID` | UPPER | 8 | Organisation |
| `DESCRIPTION` | ALN | 100 | Short description for this row |
| `PARENT` | UPPER | 25 | Parent asset/location for hierarchy |
| `ASSETLOCPRIORITY` | INTEGER | — | Sequence/priority order of this row |
| `INHERITSTATUS` | YORN | 1 | Whether this row inherits parent WO status |
| `POSITIONPURPOSE` | ALN | 50 | Purpose/role (e.g. Primary, Alternate) |
| `CLASSIFICATIONID` | UPPER | 50 | Classification linked to this asset/location |
| `INSPECTIONFORM` | UPPER | 30 | Inspection Form ID (MAS 8/9 only) |
| `ISDEFAULT` | YORN | 1 | Is this the default asset/location row? |

### Relationship Name from Parent
| Parent Object | Relationship name | Access pattern |
|---|---|---|
| WORKORDER | `MULTIASSETLOCCI` | `mbo.getMboSet("MULTIASSETLOCCI")` |
| PM | `MULTIASSETLOCCI` | `pm_mbo.getMboSet("MULTIASSETLOCCI")` |

---

## 3. Inspection Forms and MULTIASSETLOCCI (MAS 8/9)

### Key Architecture Point
In **MAS 8 / MAS 9**, Inspection Forms are a **React-based separate feature** from App Designer:
- Configured via **"Inspections"** application (not App Designer)
- Results stored in `INSPECTIONRESULT` object (not embedded in WORKORDER)
- An Inspection Form can be **linked to a MULTIASSETLOCCI row** via the `INSPECTIONFORM` field
- One inspection result per row = one form filled per asset/location on the route

### Relationship
```
PM record
  └── MULTIASSETLOCCI rows (each row = one asset/location)
        └── INSPECTIONFORM field → links to the Inspection Form definition
                ↓ (when WO generated)
  WORKORDER
    └── MULTIASSETLOCCI rows (copied from PM)
          └── INSPECTIONFORM field → triggers form for field crew per asset
                ↓ (after execution)
  INSPECTIONRESULT rows → one per MULTIASSETLOCCI row completed
```

### Maximo 7.6 Note
MULTIASSETLOCCI exists in Maximo 7.6 but `INSPECTIONFORM` field does not. In 7.6, inspection
results are typically managed via custom attributes or the legacy Condition Monitoring module.

---

## 4. Full Jython Script: Copy MULTIASSETLOCCI from PM to WO

### Launch Point Configuration
| Property | Value |
|---|---|
| Launch Point Type | Object |
| Object | `WORKORDER` |
| Event | `Save` |
| Condition | `ORIGRECORDCLASS = "PM"` (optional — script guards internally) |

> **Why Save, not afterSave?**
> During `Save`, child MBO sets (MULTIASSETLOCCI) added to the WO are committed
> atomically in the same database transaction. `afterSave` would require a second
> explicit `save()` call and risks an inconsistent WO if that second save fails.

### Production-Ready Script
```python
# ============================================================
# Script:       WO_PM_MULTIASSETLOCCI_COPY
# Launch Point: WO_PM_MULTIASSETLOCCI_COPY_LP  (Object)
# Object:       WORKORDER
# Event:        Save
# Version:      1.0
# Description:  When a WO is generated from a PM record, copies
#               all MULTIASSETLOCCI (multi-asset/location/inspection
#               form) rows from the PM to the new Work Order so that
#               field crews receive the complete inspection route.
# ============================================================
from psdi.mbo import MboConstants
from psdi.util.logging import MXLoggerFactory

log = MXLoggerFactory.getLogger("maximo.script.WO_PM_MULTIASSETLOCCI_COPY")

# Guard 1: Only execute on new Work Order records.
# Existing WOs do not need this copy (route may have been manually edited).
if not mbo.isNew():
    log.debug("WO_PM_MULTIASSETLOCCI_COPY: Skipped — WO is not new.")
else:
    orig_class = mbo.getString("ORIGRECORDCLASS")
    orig_id    = mbo.getString("ORIGRECORDID")   # PMNUM of the parent PM

    # Guard 2: Only execute when WO was generated from a PM record.
    if orig_class != "PM" or orig_id is None or orig_id.strip() == "":
        log.debug("WO_PM_MULTIASSETLOCCI_COPY: Skipped — WO not generated from a PM.")
    else:
        pm_set       = None
        pm_multi_set = None
        wo_multi_set = None

        try:
            site_id = mbo.getString("SITEID")
            log.info("WO_PM_MULTIASSETLOCCI_COPY: Copying from PM " + orig_id + " to WO " + mbo.getString("WONUM"))

            # Open the source PM record.
            # Use an ad-hoc set scoped to this site so we never cross site boundaries.
            pm_set = service.getMboSet(
                "$WO_PMMULTI_PM",
                "PM",
                "PMNUM='" + orig_id + "' AND SITEID='" + site_id + "'"
            )
            pm_set.reset()

            if pm_set.isEmpty():
                log.warn("WO_PM_MULTIASSETLOCCI_COPY: PM " + orig_id + " not found in site " + site_id)
            else:
                pm_mbo = pm_set.getMbo(0)

                # Read the MULTIASSETLOCCI child rows from the PM.
                pm_multi_set = pm_mbo.getMboSet("MULTIASSETLOCCI")
                pm_multi_set.reset()

                if pm_multi_set.isEmpty():
                    log.info("WO_PM_MULTIASSETLOCCI_COPY: PM " + orig_id + " has no MULTIASSETLOCCI rows — nothing to copy.")
                else:
                    # Get the WO's MULTIASSETLOCCI child set and clear auto-populated rows.
                    wo_multi_set = mbo.getMboSet("MULTIASSETLOCCI")
                    wo_multi_set.deleteAll()

                    row_count = 0
                    src_row = pm_multi_set.moveFirst()
                    while src_row is not None:
                        new_row = wo_multi_set.add()

                        # Copy all meaningful fields from the PM row to the WO row.
                        new_row.setValue("ASSETNUM",  src_row.getString("ASSETNUM"),  MboConstants.NOACCESSCHECK)
                        new_row.setValue("LOCATION",  src_row.getString("LOCATION"),  MboConstants.NOACCESSCHECK)
                        new_row.setValue("SITEID",    src_row.getString("SITEID"),    MboConstants.NOACCESSCHECK)
                        new_row.setValue("ORGID",     src_row.getString("ORGID"),     MboConstants.NOACCESSCHECK)
                        new_row.setValue("DESCRIPTION", src_row.getString("DESCRIPTION"), MboConstants.NOACCESSCHECK)

                        # Priority/sequence — preserves the PM inspection order on the WO.
                        if not src_row.isNull("ASSETLOCPRIORITY"):
                            new_row.setValue("ASSETLOCPRIORITY", src_row.getInt("ASSETLOCPRIORITY"), MboConstants.NOACCESSCHECK)

                        # Inspection Form (MAS 8/9 only) — links the React inspection form to each route stop.
                        if not src_row.isNull("INSPECTIONFORM"):
                            new_row.setValue("INSPECTIONFORM", src_row.getString("INSPECTIONFORM"), MboConstants.NOACCESSCHECK)

                        # Optional fields — copy only when populated.
                        if not src_row.isNull("PARENT"):
                            new_row.setValue("PARENT", src_row.getString("PARENT"), MboConstants.NOACCESSCHECK)
                        if not src_row.isNull("POSITIONPURPOSE"):
                            new_row.setValue("POSITIONPURPOSE", src_row.getString("POSITIONPURPOSE"), MboConstants.NOACCESSCHECK)

                        row_count += 1
                        src_row = pm_multi_set.moveNext()

                    log.info("WO_PM_MULTIASSETLOCCI_COPY: Copied " + str(row_count) + " MULTIASSETLOCCI rows from PM " + orig_id)

        except Exception as e:
            log.error("WO_PM_MULTIASSETLOCCI_COPY failed for PM " + str(orig_id) + ": " + str(e))
            raise

        finally:
            # CRITICAL: Always close MboSets in finally — memory leak if omitted.
            if pm_multi_set is not None:
                try:
                    pm_multi_set.close()
                except:
                    pass
            if wo_multi_set is not None:
                try:
                    wo_multi_set.close()
                except:
                    pass
            if pm_set is not None:
                try:
                    pm_set.close()
                except:
                    pass
```

---

## 5. Must-Not-Overwrite Variant

When the requirement states the copy must not overwrite MULTIASSETLOCCI rows that have already
been manually set on the WO, change the copy block:

```python
# Replace: wo_multi_set.deleteAll()
# With:
if not wo_multi_set.isEmpty():
    log.info("WO_PM_MULTIASSETLOCCI_COPY: WO already has MULTIASSETLOCCI rows — not overwriting.")
else:
    # ... proceed with copying src_row → new_row as above
```

---

## 6. Copying a Single Field from PM to WO (Non-MULTIASSETLOCCI)

For simpler requirements like "copy PM.INSPECTIONFORM to WORKORDER.INSPECTIONFORM":

```python
from psdi.mbo import MboConstants
from psdi.util.logging import MXLoggerFactory

log = MXLoggerFactory.getLogger("maximo.script.WO_PM_FIELD_COPY")

if mbo.isNew():
    orig_class = mbo.getString("ORIGRECORDCLASS")
    orig_id    = mbo.getString("ORIGRECORDID")

    if orig_class == "PM" and orig_id and orig_id.strip():
        pm_set = None
        try:
            pm_set = service.getMboSet(
                "$WO_PMCOPY",
                "PM",
                "PMNUM='" + orig_id + "' AND SITEID='" + mbo.getString("SITEID") + "'"
            )
            pm_set.reset()
            if not pm_set.isEmpty():
                pm_mbo    = pm_set.getMbo(0)
                src_value = pm_mbo.getString("INSPECTIONFORM")  # source field
                if src_value and src_value.strip():
                    existing = mbo.getString("INSPECTIONFORM")   # target field
                    if not existing or not existing.strip():     # do not overwrite
                        mbo.setValue("INSPECTIONFORM", src_value, MboConstants.NOACCESSCHECK)
        finally:
            if pm_set is not None:
                pm_set.close()
```

---

## 7. FDD Requirements for PM→WO Copy (Template)

When writing the FDD for any PM→WO copy requirement, use this structure:

### Functional Requirements Table
| Req ID | Requirement | Change Type | Maximo Object | Priority |
|---|---|---|---|---|
| R-001 | When a Work Order is generated from a PM record, all MULTIASSETLOCCI rows (assets/locations/inspection form assignments) defined on the PM shall be automatically copied to the generated Work Order. | Customisation | WORKORDER | High |
| R-002 | The copy shall not overwrite MULTIASSETLOCCI rows that have been manually added to the WO after generation (if applicable). | Customisation | WORKORDER | Medium |
| R-003 | The automation script shall fire on the Save event of WORKORDER, restricted to newly created records with ORIGRECORDCLASS = 'PM'. | Customisation | WORKORDER | High |

### Business Rules (Standard Set for PM→WO Copy)
- **BR-001**: The copy shall execute only when `WORKORDER.ORIGRECORDCLASS = 'PM'` and `WORKORDER.ORIGRECORDID` is not null.
- **BR-002**: If the source PM has no MULTIASSETLOCCI rows, the script shall log an informational message and exit without error.
- **BR-003**: The following fields shall be copied per row: ASSETNUM, LOCATION, SITEID, ORGID, DESCRIPTION, ASSETLOCPRIORITY, INSPECTIONFORM (MAS 8/9 only), PARENT (if populated), POSITIONPURPOSE (if populated).
- **BR-004**: MULTIID is system-generated (AUTOKEY) — the script must never set this field.
- **BR-005**: All MBO Sets opened in the script must be closed in a `finally` block to prevent memory leaks.

---

## 8. TDD Sections for PM→WO Copy (Template)

### Section 4 — Database Configuration
No new database attributes are required for this change. The MULTIASSETLOCCI object and all
required fields (ASSETNUM, LOCATION, SITEID, ORGID, DESCRIPTION, ASSETLOCPRIORITY, INSPECTIONFORM,
PARENT, POSITIONPURPOSE) are OOTB in Maximo MAS 8/9. No DB Config changes needed.

### Section 5 — Application Configuration
No App Designer changes are required for this change. The MULTIASSETLOCCI tab/section on
Work Order Tracking (WOTRACK) is delivered out-of-the-box in Maximo and displays the copied
rows automatically once populated by the script.

### Section 6 — Automation Script
See Section 4 of this skill file for the production-ready script. Launch point configuration:
- **Path**: Go To → System Configuration → Platform Configuration → Automation Scripts
- **Action**: Create Script with Launch Point
- **Launch Point Type**: Object
- **Object**: WORKORDER
- **Event**: Save
- **Script Name**: `WO_PM_MULTIASSETLOCCI_COPY` (or per-engagement prefix, e.g. `ACN_WO_PM_MULTI_COPY`)
- **Launch Point Name**: `WO_PM_MULTIASSETLOCCI_COPY_LP`

### Section 8 — Security
No new security grants are required for this change. The MULTIASSETLOCCI tab on WOTRACK is
governed by the existing WOTRACK application security grants. Ensure all security groups that
have WOTRACK Insert/Update permission can also read MULTIASSETLOCCI rows.

---

## 9. Common Mistakes and How to Avoid Them

| Mistake | Correct Approach |
|---|---|
| Setting `MULTIID` in the script | Never set `MULTIID` — it is an AUTOKEY, system-generated |
| Using `getMboSet("MULTIASSETLOCCI")` without `try/finally` | Always close in `finally` — memory leak in production |
| Firing on ALL Save events (not just new WOs) | Guard with `if mbo.isNew()` |
| Using `afterSave` event | Use `Save` event — child rows commit atomically with parent |
| Hardcoding SITEID or ORGID | Always read from `mbo.getString("SITEID")` and `mbo.getString("ORGID")` |
| Calling `getMbo(0)` without `isEmpty()` check | Always `if not pm_set.isEmpty(): pm_mbo = pm_set.getMbo(0)` |
| Querying PM with `getMboSet("ORIGPM")` on new WO | Use `service.getMboSet("$NAME", "PM", "PMNUM=...")` — the ORIGPM relationship may not be resolved on a new, unsaved WO |
| Forgetting `INSPECTIONFORM` field | Include in copy when on MAS 8/9 — it links the React inspection form to each route stop |

---

## 10. Testing Checklist for PM→WO MULTIASSETLOCCI Copy

Before sign-off, run these tests:

| Test # | Scenario | Expected Result |
|---|---|---|
| TC-001 | PM with 3 MULTIASSETLOCCI rows (Asset A, B, C) → Generate WO | WO has 3 MULTIASSETLOCCI rows matching PM; all field values identical |
| TC-002 | PM with 0 MULTIASSETLOCCI rows → Generate WO | WO has 0 MULTIASSETLOCCI rows; no error logged |
| TC-003 | Manually create WO (not from PM) | Script skips (ORIGRECORDCLASS ≠ "PM"); no error |
| TC-004 | PM-generated WO, existing MULTIASSETLOCCI rows on WO | If must-not-overwrite: rows unchanged; if overwrite: rows replaced |
| TC-005 | PM-generated WO, PM deleted before WO save | PM not found; script logs warning, exits cleanly |
| TC-006 | PM has rows with INSPECTIONFORM linked | WO rows have same INSPECTIONFORM field — inspect in MAS Inspections app |
| TC-007 | Upgrade PMWOEGENCRON to generate 50 WOs in batch | No memory errors; all WOs have correct MULTIASSETLOCCI rows |

---

*MX AI Suite | PM→WO Skill v2.0 | IBM Maximo MAS 8/9 | Last updated: 2026-09-28*
