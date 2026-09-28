# MX_Functional — Core Maximo EAM Knowledge Skill
*Version: 1.0 | Last updated: 2026-09-20*

---

## Purpose

Load before any Maximo EAM question, FDD/TDD/Config task, scripting, or integration design.
Do NOT rely on training knowledge alone for field names, statuses, or object behaviour — always
check this skill first. If a field or behaviour is not listed here, flag it and look it up.

---

## Compatible Unit (CU) Module — Core Objects

### PLUSDCU — CU Header (primary object)

| Field | Type | Description |
|---|---|---|
| PLUSDCUNUM | UPPER | CU identifier — primary key |
| DESCRIPTION | ALN | Short description (60 chars) |
| DESCRIPTION_LONGDESCRIPTION | CLOB | Long description |
| STATUS | UPPER | DRAFT / APPROVED / OBSOLETE |
| ORGID | UPPER | Organisation ID |
| SITEID | UPPER | Site ID |
| PLUSDCUTYPE | UPPER | CU type code (OH / UG / SS / DS / TX) |
| PLUSDCUCLASS | UPPER | Asset class: DISTRIBUTION / TRANSMISSION / SUBSTATION |
| PLUSDCAPITAL | YORN | Capital (Y) vs O&M (N) flag |
| HASLD | YORN | Has Labour Detail |
| HASEQ | YORN | Has Equipment Detail |
| PLUSDCUSETNUM | UPPER | Parent CU Set number (if member of a set) |
| EFFECTIVEDATE | DATE | Rate effectivity start date |
| ENDDATE | DATE | Rate effectivity end date (null = open-ended) |
| CHANGEBY | UPPER | Last changed by (system-managed — do not write) |
| CHANGEDATE | DATETIME | Last changed date (system-managed — do not write) |
| ROWSTAMP | BIGINT | Optimistic lock — read before any update |

### PLUSDCUASSET — CU Asset Component

| Field | Description |
|---|---|
| PLUSDCUNUM | Parent CU |
| ITEMNUM | Material/asset item number |
| QUANTITY | Quantity required |
| UNITCOST | Unit cost |
| ASSETTYPE | Asset type code |

### PLUSDCUITEM — CU Material / Labour / Tool Item

| Field | Description |
|---|---|
| PLUSDCUNUM | Parent CU |
| LINENUM | Line sequence number |
| ITEMNUM | Item number (material or tool) |
| QUANTITY | Quantity required |
| UNITCOST | Standard unit cost |
| LINETYPE | MATERIAL / TOOL / SERVICE / STDPREM |

### PLUSDCUALABOUR — CU Labour Component

| Field | Description |
|---|---|
| PLUSDCUNUM | Parent CU |
| CRAFT | Labour craft code |
| HOURS | Standard hours |
| RATE | Labour rate per hour |

### PLUSDCUATOOL — CU Tool Component

| Field | Description |
|---|---|
| PLUSDCUNUM | Parent CU |
| ITEMNUM | Tool item number |
| HOURS | Standard hours |
| RATE | Tool rate per hour |

### PLUSDCUAEQUIP — CU Equipment Component

| Field | Description |
|---|---|
| PLUSDCUNUM | Parent CU |
| EQUIP | Equipment identifier |
| HOURS | Hours required |
| RATE | Equipment rate per hour |

### PLUSDCUACUSTOMER — CU Customer Charges

| Field | Description |
|---|---|
| PLUSDCUNUM | Parent CU |
| CUSTOMERCHARGETYPE | Charge type code |
| AMOUNT | Customer contribution amount |

### PLUSDCUSET — CU Set Header

| Field | Description |
|---|---|
| PLUSDCUSETNUM | Set identifier — primary key |
| DESCRIPTION | Set description |
| STATUS | Set status (mirrors CU lifecycle) |
| ORGID | Organisation ID |

### PLUSDCUSETMEM — CU Set Members

| Field | Description |
|---|---|
| PLUSDCUSETNUM | Parent set |
| PLUSDCUNUM | Member CU number |
| MEMBERTYPE | Type within set (PRIMARY / ALTERNATE / OPTIONAL) |

---

## CU Status Lifecycle

### Standard (3-state)
```
DRAFT → APPROVED → OBSOLETE
```

### Extended (with PENDING)
```
DRAFT → PENDING APPROVAL → APPROVED → OBSOLETE
```

### Regulatory-Review Variant
```
DRAFT → UNDER REVIEW → REGULATORY APPROVED → APPROVED → OBSOLETE
```

**Transition rules:**
- DRAFT → APPROVED: Requires approval authority (role-based security group)
- APPROVED → OBSOLETE: Irreversible. Existing WOs referencing this CU are unaffected.
- DRAFT → OBSOLETE: Fast-track decommission, bypass approval
- Never update STATUS directly via SQL — always use the `changeStatus()` MBO method

---

## CU Classification (Type Codes)

| Code | Type | Typical Components | Status |
|---|---|---|---|
| OH | Overhead Line | Poles, conductors, cross-arms, overhead transformers, guy wires | OOB |
| UG | Underground Cable | Cable, conduit, manholes, underground transformers, vaults | OOB |
| SS | Substation | Breakers, bus, protection relays, control equipment, power transformers | OOB |
| DS | Distribution | Distribution-class assets, typically < 69 kV | OOB |
| TX | Transmission | Transmission-class assets, typically ≥ 69 kV | OOB |
| GS | Gas Mains | Gas mains, service lines, valves, regulators, meters | **PENDING — KBD-001** |

**GS domain value:** Not OOB. Client is a combined electric + gas utility. `PLUSDCUTYPE` domain extension required (KBD-001 — Open). Until KBD-001 is closed, classify Gas CUs as `UNCLASSIFIED` in ingestion output with a `GS*` annotation.

Unrecognised type codes must be flagged as `UNCLASSIFIED` in ingestion output.

---

## CU Cost Component Breakdown

Every CU has up to 4 cost components:

| Component | Object | LINETYPE |
|---|---|---|
| Material | PLUSDCUITEM | MATERIAL |
| Labour | PLUSDCUALABOUR | (separate object) |
| Tool/Equipment | PLUSDCUATOOL / PLUSDCUAEQUIP | (separate objects) |
| Contractor | PLUSDCUITEM | SERVICE |
| Premium Pay | PLUSDCUITEM | STDPREM |

---

## Rate Effectivity

CU costs are time-bound:
- Active rate: where `EFFECTIVEDATE <= SYSDATE` AND (`ENDDATE IS NULL` OR `ENDDATE >= SYSDATE`)
- Multiple rate periods may exist for the same CU (different date ranges)
- When ingesting legacy data, check for rate gaps or overlaps

---

## Capital vs O&M Classification

| Value | Classification | Meaning |
|---|---|---|
| Y | Capital | Creates or extends asset life; capitalised on books |
| N | O&M | Maintenance expenditure; expensed in period |

Used for: financial reporting, project capitalisation, GL account routing.

---

## CU Set Concept

A CU Set groups related CUs installed together as a unit:
- A CU can belong to multiple sets
- Sets are estimated together; individual CU rates still apply
- Set members can be PRIMARY, ALTERNATE, or OPTIONAL
- Estimating logic: when a set is selected on a WO, all PRIMARY members are included automatically

---

## Work Order Integration (CU Usage)

| Object | Role |
|---|---|
| WORKORDER | Work order header — references PLUSDCUNUM via cost detail |
| WOCOSTDETAIL | Line-level CU usage (qty × CU rate) |
| JOBPLAN | Job Plan cross-referenced to CU (recommended installation method) |
| JPASSET | Job Plan → Asset class association |
| WOACTIVITY | Activity-level cost breakdown within a WO |

---

## Key API Objects (OSLC REST)

| OSLC Object | Purpose |
|---|---|
| `MXCUELIBRARY` | OOB OS for CU Library — read/write CU records |
| `MXAPIASSET` | Asset data via REST |
| `MXAPIWODETAIL` | Work Order data via REST |
| `MXAPIJOBPLAN` | Job Plan data via REST |

Always use OSLC REST via `mx-api-agent` for live Maximo reads/writes.
Never write directly to the database — all writes go through MBO/OSLC.

---

## Key Maximo Field Conventions

| Rule | Detail |
|---|---|
| Status changes | Use `changeStatus()` MBO method — never direct field update |
| ORGID / SITEID | Always include in all queries and new record creation |
| ROWSTAMP | Read before any update (optimistic locking) |
| DESCRIPTION_LONGDESCRIPTION | CLOB — separate from the 60-char DESCRIPTION field |
| CHANGEBY / CHANGEDATE | System-managed — never write directly |
| Custom attributes | Prefix: `CUST_` (confirm per engagement — see KBD_Register.md) |
| Maximo query syntax | MBO query language or OSLC WHERE clause — not raw SQL |

---

## Maximo Version Notes

| Version | Notes |
|---|---|
| 7.6 | Classic UI; Jython automation scripts; OSLC API v1 |
| MAS 8 | OpenShift; same data model as 7.6; upgraded UI (Maximo Application Framework) |
| MAS 9 | OpenShift; GraphQL API available alongside OSLC; React UI |

When a behaviour differs between versions, always flag it explicitly.

---

*MX AI Suite | Skill version: 1.0*
