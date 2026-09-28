# MX_AutoScript — Maximo Automation Scripts (Jython) Skill (MAS 8 / MAS 9)
*Version: 2.0 | Platform: MAS 8.x / MAS 9.x / Maximo 7.6 | Last updated: 2026-09-28*

---

## Purpose

Load before writing, reviewing, or designing any Maximo Automation Script. Covers Jython
scripting patterns, all launch point types, MBO API usage, and IBM best practices.
Jython is the preferred scripting language in Maximo — use it over JavaScript.

---

## 1. Overview

Automation Scripts extend Maximo without Java development or server restart. Introduced in
Maximo 7.5. Activated immediately on save — no EAR rebuild, no pod restart in MAS.

`System Configuration → Platform Configuration → Automation Scripts`

Supported engines: **Jython 2.7** (preferred), JavaScript (Rhino — limited, avoid for new work).

---

## 2. Launch Point Types

| Launch Point | Trigger | Object | Use |
|---|---|---|---|
| **Object** | MBO lifecycle events: Init, Add, Save, Delete, beforeSave, afterSave | Any MBO | Field defaults, validation, derived calculations on save |
| **Attribute** | Field events: validate, action, retrieve, initialize | Specific field | Field-level validation, auto-populate related fields |
| **Action** | Called explicitly from Workflow, Escalation, toolbar button, or another script | Any | Reusable business logic callable from multiple points |
| **Custom Condition** | Boolean result evaluated by Workflow/Security | Any | Conditional routing, field visibility |
| **Integration** | Inbound/outbound MIF message processing | Integration object | Transform payloads, enrich inbound data |

### Object Launch Point Events
| Event | When it fires | Notes |
|---|---|---|
| Init | Object initialised (new record) | Set default field values |
| Add | Record added to set (before save) | Validate new records |
| Save | Before the MBO save transaction commits | Most common — validate + derive |
| Delete | Before record deletion | Block invalid deletes |
| beforeSave | Before save (similar to Save — use Save unless ordering matters) | |
| afterSave | After transaction commits | Trigger downstream actions |

---

## 3. Implicit Script Variables

| Variable | Type | Description |
|---|---|---|
| `mbo` | MBO | Current business object (transactional) |
| `mboset` | MBOSet | Current set |
| `service` | MXServer | Maximo server reference |
| `app` | String | Current application name |
| `user` | String | Current Maximo username |
| `interactive` | Boolean | True if triggered from UI |
| `scriptName` | String | Name of this script |
| `errorgroup` | String | Error group for message keys |
| `errorkey` | String | Error message key |
| `implContext` | ImplContext | Integration context (Integration launch points only) |

---

## 4. Core MBO API Patterns

### Reading Field Values
```python
# String value
wonum = mbo.getString("WONUM")

# Integer
qty = mbo.getInt("QUANTITY")

# Double / Decimal
cost = mbo.getDouble("LINECOST")

# Date
eff_date = mbo.getDate("EFFECTIVEDATE")

# Boolean (YORN)
is_capital = mbo.getBoolean("PLUSDCAPITAL")

# Null check
if mbo.isNull("PARENTWO"):
    pass
```

### Writing Field Values
```python
from psdi.mbo import MboConstants

# Standard write
mbo.setValue("DESCRIPTION", "Updated by script", MboConstants.NOACCESSCHECK)

# With validation (raises exception if domain check fails)
mbo.setValue("STATUS", "APPR")

# Set to null
mbo.setValueNull("ENDDATE", MboConstants.NOACCESSCHECK)
```

### Field Flags (Attribute Launch Points)
```python
# Make field required
mbo.setFieldFlag("ASSETNUM", MboConstants.REQUIRED, True)

# Make field readonly
mbo.setFieldFlag("WONUM", MboConstants.READONLY, True)

# Hide field
mbo.setFieldFlag("INTERNALNOTES", MboConstants.HIDDEN, True)

# Remove readonly
mbo.setFieldFlag("DESCRIPTION", MboConstants.READONLY, False)
```

### Status Changes
```python
import java.util.Date

# Change status (transactional MBO — part of current save)
mbo.changeStatus("APPR", java.util.Date(), "Auto-approved by script")

# Change status on standalone MBO (requires explicit save)
standalone_mbo.changeStatus("COMP", java.util.Date(), "Completed")
standalone_mbo.getMboSet().save()
```

### Querying Related MBOs
```python
# Get child MBOSet (defined relationship)
wo_tasks = mbo.getMboSet("WOACTIVITY")

try:
    wo_tasks.setOrderBy("TASKID")
    if not wo_tasks.isEmpty():
        first_task = wo_tasks.getMbo(0)
        task_desc = first_task.getString("DESCRIPTION")
finally:
    wo_tasks.close()  # ALWAYS close MboSets — memory leak if not

# Ad-hoc query (use $ prefix for script-defined sets)
wo_set = mbo.getMboSet("$scriptWOs", "WORKORDER",
                       "SITEID=:SITEID AND STATUS='WAPPR'")
try:
    wo_set.reset()
    wo = wo_set.moveFirst()
    while wo is not None:
        # process each WO
        wo = wo_set.moveNext()
finally:
    wo_set.close()
```

### Reading MAXVARS (System Parameters)
```python
maxvar_set = service.getMboSet("MAXVARS")
try:
    maxvar_set.setWhere("VARNAME='MY_PARAM' AND ORGID='" + mbo.getString("ORGID") + "'")
    maxvar_set.reset()
    if not maxvar_set.isEmpty():
        param_value = maxvar_set.getMbo(0).getString("VARVALUE")
    else:
        param_value = "DEFAULT"
finally:
    maxvar_set.close()
```

### Creating a New MBO Record
```python
new_set = service.getMboSet("WORKORDER")
try:
    new_wo = new_set.add()
    new_wo.setValue("DESCRIPTION", "Auto-created WO", MboConstants.NOACCESSCHECK)
    new_wo.setValue("SITEID", mbo.getString("SITEID"), MboConstants.NOACCESSCHECK)
    new_wo.setValue("ORGID", mbo.getString("ORGID"), MboConstants.NOACCESSCHECK)
    new_wo.setValue("WORKTYPE", "CM", MboConstants.NOACCESSCHECK)
    new_set.save()
finally:
    new_set.close()
```

---

## 5. Error Handling

### Throwing User-Facing Errors
```python
from psdi.util.logging import MXLoggerFactory
from psdi.util import MXApplicationException

log = MXLoggerFactory.getLogger("maximo.script.MYSCRIPT")

# Raise an application exception (shows error dialog to user)
raise MXApplicationException("mxe.oslc", "BMXAA0000E",
                               ["Custom error message for the user"])

# Show a warning (non-blocking)
service.setWarning("mxe.oslc", "BMXAA0000E", "MXSERVER", ["Warning text"])
```

### Logging
```python
from psdi.util.logging import MXLoggerFactory

log = MXLoggerFactory.getLogger("maximo.script." + scriptName)

log.debug("Script start — WONUM: " + str(mbo.getString("WONUM")))
log.info("Status changed to: APPR")
log.warn("Unexpected null value for ASSETNUM — using default")
log.error("Failed to retrieve MAXVAR CU_BURDEN_PCT")
```

### Try / Finally Pattern (Mandatory for MboSets)
```python
my_set = mbo.getMboSet("SOMECHILD")
try:
    # ... process records
    pass
except Exception as e:
    log.error("Error in script " + scriptName + ": " + str(e))
    raise
finally:
    my_set.close()  # ALWAYS in finally — runs even if exception raised
```

---

## 6. Script Standard Template

Every script must follow this structure:

```python
# ============================================================
# Script:       SCRIPTNAME
# Launch Point: OBJECT | ATTRIBUTE | ACTION
# Object:       OBJECTNAME
# Event:        save | validate | action
# Version:      1.0
# Description:  One-line description of what this script does.
# ============================================================
from psdi.mbo import MboConstants
from psdi.util.logging import MXLoggerFactory
import java.util.Date

log = MXLoggerFactory.getLogger("maximo.script.SCRIPTNAME")
log.debug("START: SCRIPTNAME — " + str(mbo.getString("PRIMARYKEY")))

try:
    # ---- Guard conditions ----
    if mbo.isNew():
        pass  # handle new record logic

    # ---- Main logic ----
    # ... business logic here

except Exception as e:
    log.error("SCRIPTNAME failed: " + str(e))
    raise

finally:
    log.debug("END: SCRIPTNAME")
```

---

## 7. IBM Best Practices & Anti-Patterns

### Must-Do (Blockers)
| Rule | Why |
|---|---|
| Always close MboSets in `finally` block | Memory leak — causes OutOfMemory in production |
| Never `sys.exit()` | Kills the Maximo JVM thread |
| Check `isEmpty()` before `getMbo(0)` | IndexOutOfBoundsException |
| Use `MboConstants.NOACCESSCHECK` on `setValue()` | Prevents security check rejection on system updates |
| Use `getString()` / `getDouble()` not direct attribute access | MBO API enforces type conversion |
| Never direct SQL DML in scripts | Bypasses MBO business rules and audit |
| Catch Java exceptions explicitly | Python bare `except` catches Python exceptions only |

### Anti-Patterns to Avoid
| Anti-Pattern | Correct Approach |
|---|---|
| `mbo.WONUM` (direct attribute) | `mbo.getString("WONUM")` |
| `mboSet = mbo.getMboSet("X")` without close | Add `finally: mboSet.close()` |
| Calling `save()` inside an Object launch point | Save is called by framework — double save causes issues |
| Hardcoded SITEID / ORGID / rate values | Read from MAXVARS or pass as script parameters |
| `getMbo(0)` without isEmpty() check | Guard with `if not mboSet.isEmpty():` |
| `sys.exit()` or `exit()` | Raise `MXApplicationException` |
| Very long running queries in Save launch point | Move to Action launch point or cron task |

### Performance Tips
- Add indexes to DB columns used in `setWhere()` queries
- Avoid N+1 patterns (querying inside a loop that iterates many records)
- Use `setOrderBy()` and `setRange()` to limit result sets
- Script runs synchronously in the UI transaction — keep it fast (< 1s for interactive)

---

## 8. Integration Launch Point Patterns

### Inbound (Enriching Incoming Data)
```python
# implContext available in Integration launch points
payload = implContext.getPropertyValue("FIELDNAME")
mbo.setValue("CUSTOMFIELD", payload, MboConstants.NOACCESSCHECK)
```

### Outbound (Transforming Outgoing Data)
```python
# Filter: only send APPROVED records
status = mbo.getString("STATUS")
if status != "APPROVED":
    implContext.setAttribute("SKIP", "1")
```

---

## 9. Script Naming Convention

| Pattern | Example |
|---|---|
| `{PREFIX}_{OBJECT}_{PURPOSE}` | `CU_PLUSDCU_RATEEFFECTIVITY` |
| `{PREFIX}_{TRIGGER}_{PURPOSE}` | `WO_SAVE_CAPITALCLASSIFY` |
| All caps, underscores only | `WORKORDER_STATUS_NOTIFY` |

Prefix = client/module prefix agreed for the engagement (e.g., `CU`, `AWM`, `WO`).

---

*MX AI Suite | AutoScript Skill v2.0 | IBM Maximo MAS 8/9 | Last updated: 2026-09-28*
