# TeDCoS — Technical Design & Configuration Specification Agent Skill
*Version: 1.0 | Last updated: 2026-09-21*

---

## Purpose

Load before performing any TeDCoS agent task: TDD generation, field-level config specs,
MAF screen specs, database design, Jython script skeletons, or security design.
This skill supplements `maximo_core.md` and `Technical-Docs.skill.md` — load all three together.

---

## Markdown Authoring Rules (AI-Brain output)

Same rules as CUDIn skill — see `skills/CUDIn.skill.md § Markdown Authoring Rules`.
Key rule: numbered process steps use plain ordered list, NOT code fences.

---

## Skill Registry for This Agent

| Skill | File | Always Load |
|---|---|---|
| MX_Functional | `skills/maximo_core.md` | Yes |
| MX_TechDocs | `skills/Technical-Docs.skill.md` | Yes |
| TeDCoS | `skills/TeDCoS.skill.md` | Yes (this file) |

---

## Input Artefacts (from CUDIn Agent 1)

| Artefact | Location | Used By Story |
|---|---|---|
| Functional Design Document | `Outputs\Agent1\FDD\MX_CU_FDD-v1.0.docx` | US-02-001 |
| CU Catalogue Blueprint | `Outputs\Agent1\CU-Catalogue\MX_CU_CATALOGUE_BLUEPRINT-v1.0.xlsx` | US-02-001, 002 |
| CU Gap Analysis Report | `Outputs\Agent1\Gap-Analysis\MX_CU_GAP_ANALYSIS-v1.0.docx` | US-02-001 |
| Agent 1 Handoff Manifest | `agents\agent-01-CUDIn\handoff-schema.json` | US-02-001 |
| AI-Brain FDD Content | `AI-Brain\agent-01-CUDIn\FDD_CU_Module_Content.md` | US-02-001 |

---

## US-02-001 — Auto-Generate TDD for CU Module

### TDD Input Read Sequence

```
1. Read handoff manifest: agents\agent-01-CUDIn\handoff-schema.json
   - Confirm handoff_status != "BLOCKED"
   - Note open_questions_outstanding and kbd_references
2. Read FDD AI-Brain content: AI-Brain\agent-01-CUDIn\FDD_CU_Module_Content.md
3. Search Brain (docs_search_brain) for existing TDD or any CU technical design docs
4. Note all KBDs in docs\KBD_Register.md relevant to technical design
```

### CU Module Object Map

The following Maximo Utilities (PLUSD) objects are in scope for technical design:

| Object | Role | Parent Object |
|---|---|---|
| PLUSDCU | CU header record (type, status, capital flag, rates) | — |
| PLUSDCUITEM | Material and contractor cost lines | PLUSDCU |
| PLUSDCUALABOUR | Labour cost lines (craft + hours + rate) | PLUSDCU |
| PLUSDCUATOOL | Tool/small equipment cost lines | PLUSDCU |
| PLUSDCUAEQUIP | Large equipment cost lines | PLUSDCU |
| PLUSDCUSET | CU Set definition header | — |
| PLUSDCUSETMEMBER | Members of a CU Set (PRIMARY / ALTERNATE / OPTIONAL) | PLUSDCUSET |

### Custom Extensions Required

| Extension | Object | Column | Type | Reason | KBD |
|---|---|---|---|---|---|
| Gas CU subtype | PLUSDCU | CUST_GASSUB | Char(10) | Gas mains sub-classification | KBD-001 |
| Retirement date | PLUSDCU | CUST_RETDTE | Date | INACTIVE CU lifecycle tracking | KBD-003 |

### Domain Definitions Required

| Domain | Type | Values | Used On |
|---|---|---|---|
| PLUSDCUTYPE | ALN | OH, UG, SS, DS, GS (KBD-001 pending) | PLUSDCU.PLUSDCUTYPE |
| PLUSDSTATUS | ALN | DRAFT, PENDING, APPROVED, OBSOLETE | PLUSDCU.STATUS |
| CULINETYPE | ALN | MATERIAL, SERVICE, STDPREM | PLUSDCUITEM.LINETYPE |
| CUSETMEMTYPE | ALN | PRIMARY, ALTERNATE, OPTIONAL | PLUSDCUSETMEMBER.MEMBERTYPE |

### TDD Generation Workflow

```
Step 1: Read all inputs (handoff manifest, FDD AI-Brain content, KBD Register)
Step 2: Generate Section 5 (Object Structure Analysis) — one sub-section per object
Step 3: Generate Section 6 (Domain Definitions) — using domain table above
Step 4: Generate Section 7 (Configuration Design) — from US-02-003 output
Step 5: Generate Section 8 (Database Design) — from US-02-004 output
Step 6: Generate Sections 9–12 (Integration, Scripts, Security, RICEFW — summary refs)
Step 7: Generate Section 13 (Assumptions) and Section 14 (Open Questions)
Step 8: Write AI-Brain content to AI-Brain\agent-02-TeDCoS\TDD_CU_Module_Content.md
Step 9: Render to Outputs\Agent2\TDD\MX_CU_TDD-v1.0.docx via render_docs.py
```

**Success criteria:** All 7 in-scope objects documented; all custom extensions flagged with KBD reference; no TBD without owner.

---

## US-02-002 — Field-Level Configuration Specifications

### Per-Object Field Table Rules

For each object, produce a field table using the standard column set from Technical-Docs.skill.md.
Include ALL fields — base Maximo fields the configuration uses AND custom extensions.
Mark custom extensions in the Custom? column as Yes and note the KBD reference.

### Objects and Key Fields

#### PLUSDCU — CU Header

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? |
|---|---|---|---|---|---|---|
| PLUSDCUNUM | Char | 25 | Yes | — | — | No |
| DESCRIPTION | Char | 100 | Yes | — | — | No |
| PLUSDCUTYPE | Char | 10 | Yes | domain=PLUSDCUTYPE | — | No |
| STATUS | Char | 10 | Yes | domain=PLUSDSTATUS | DRAFT | No |
| PLUSDCAPITAL | Char | 1 | No | domain=YORN | N | No |
| ORGID | Char | 8 | Yes | FK→ORGANIZATION | — | No |
| SITEID | Char | 8 | Yes | FK→SITE | — | No |
| EFFECTIVEDATE | Date | — | No | — | — | No |
| ENDDATE | Date | — | No | — | — | No |
| LONGDESCRIPTION | CLOB | — | No | — | — | No |
| CUST_GASSUB | Char | 10 | No | — | — | Yes |
| CUST_RETDTE | Date | — | No | — | — | Yes |

#### PLUSDCUITEM — Material / Contractor Cost Lines

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? |
|---|---|---|---|---|---|---|
| CUNUM | Char | 25 | Yes | FK→PLUSDCU | — | No |
| LINETYPE | Char | 10 | Yes | domain=CULINETYPE | MATERIAL | No |
| ITEMNUM | Char | 30 | No | FK→ITEM | — | No |
| DESCRIPTION | Char | 100 | Yes | — | — | No |
| QUANTITY | Decimal | — | Yes | — | 1 | No |
| UNITCOST | Decimal | — | No | — | — | No |
| UOM | Char | 10 | No | FK→MEASUREUNIT | — | No |

#### PLUSDCUALABOUR — Labour Cost Lines

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? |
|---|---|---|---|---|---|---|
| CUNUM | Char | 25 | Yes | FK→PLUSDCU | — | No |
| CRAFT | Char | 10 | Yes | FK→CRAFTSKILL | — | No |
| SKILLLEVEL | Char | 10 | No | — | — | No |
| HOURS | Decimal | — | Yes | — | 1.00 | No |
| RATE | Decimal | — | No | From CRAFTRATE | — | No |

#### PLUSDCUATOOL — Tool Cost Lines

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? |
|---|---|---|---|---|---|---|
| CUNUM | Char | 25 | Yes | FK→PLUSDCU | — | No |
| TOOLNUM | Char | 30 | Yes | FK→TOOL | — | No |
| DESCRIPTION | Char | 100 | No | — | — | No |
| HOURS | Decimal | — | Yes | — | 1.00 | No |
| RATE | Decimal | — | No | — | — | No |

#### PLUSDCUAEQUIP — Equipment Cost Lines

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? |
|---|---|---|---|---|---|---|
| CUNUM | Char | 25 | Yes | FK→PLUSDCU | — | No |
| ASSETNUM | Char | 25 | No | FK→ASSET | — | No |
| DESCRIPTION | Char | 100 | Yes | — | — | No |
| HOURS | Decimal | — | Yes | — | 1.00 | No |
| RATE | Decimal | — | No | — | — | No |

#### PLUSDCUSET / PLUSDCUSETMEMBER — CU Sets

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? |
|---|---|---|---|---|---|---|
| CUSETNUM | Char | 25 | Yes | — | — | No |
| DESCRIPTION | Char | 100 | Yes | — | — | No |
| STATUS | Char | 10 | Yes | domain=PLUSDSTATUS | DRAFT | No |
| ORGID | Char | 8 | Yes | FK→ORGANIZATION | — | No |
| CUNUM | Char | 25 | Yes | FK→PLUSDCU | — | No |
| MEMBERTYPE | Char | 10 | Yes | domain=CUSETMEMTYPE | PRIMARY | No |
| MEMBERSEQ | Integer | — | No | — | 10 | No |

### Output Files

- AI-Brain: `AI-Brain\agent-02-TeDCoS\Field_Config_Specs.md`
- Client artefact: `Outputs\Agent2\Config-Specs\MX_CU_CONFIG_SPECS-v1.0.xlsx`
  - One worksheet per object; columns follow the standard field table format
- Included as Appendix A in TDD (US-02-001)

---

## US-02-003 — MAF Screen Customisation Specifications

### CU Library Application Specs

Application: **PLUSDCULIB** (Compatible Unit Library)

#### Tab 1: CU Details

| Sequence | Field | Label | Length | Mandatory | Visibility Rule |
|---|---|---|---|---|---|
| 10 | PLUSDCUNUM | CU Number | 25 | Yes | Always visible |
| 20 | DESCRIPTION | Description | 100 | Yes | Always visible |
| 30 | PLUSDCUTYPE | CU Type | 10 | Yes | Always visible |
| 40 | STATUS | Status | 10 | Yes | Always visible |
| 50 | PLUSDCAPITAL | Capital? | 1 | No | Always visible |
| 60 | EFFECTIVEDATE | Effective Date | — | No | Always visible |
| 70 | ENDDATE | End Date | — | No | Always visible |
| 80 | ORGID | Org | 8 | Yes | Always visible |
| 90 | SITEID | Site | 8 | Yes | Always visible |
| 100 | CUST_GASSUB | Gas Sub-Type | 10 | No | Visible only when PLUSDCUTYPE = GS [KBD-001] |
| 110 | CUST_RETDTE | Retirement Date | — | No | Visible only when STATUS = INACTIVE [KBD-003] |

#### Tab 2: Cost Components (sub-tabs)

| Sub-tab | Object | Columns Shown |
|---|---|---|
| Material | PLUSDCUITEM (LINETYPE=MATERIAL) | ITEMNUM, DESCRIPTION, QUANTITY, UOM, UNITCOST |
| Labour | PLUSDCUALABOUR | CRAFT, SKILLLEVEL, HOURS, RATE |
| Tools | PLUSDCUATOOL | TOOLNUM, DESCRIPTION, HOURS, RATE |
| Equipment | PLUSDCUAEQUIP | ASSETNUM, DESCRIPTION, HOURS, RATE |
| Contractor | PLUSDCUITEM (LINETYPE=SERVICE) | ITEMNUM, DESCRIPTION, QUANTITY, UOM, UNITCOST |

#### Tab 3: CU Sets

Shows PLUSDCUSETMEMBER records where this CU is a member:

| Column | Description |
|---|---|
| CUSETNUM | Set number (lookup to PLUSDCUSET) |
| MEMBERTYPE | PRIMARY / ALTERNATE / OPTIONAL |
| MEMBERSEQ | Sequence within set |

### Conditional Visibility Rules

| Rule ID | Trigger Condition | Action |
|---|---|---|
| CVR-001 | PLUSDCUTYPE = GS | Show CUST_GASSUB field [KBD-001 pending] |
| CVR-002 | STATUS = INACTIVE | Show CUST_RETDTE field [KBD-003 pending] |
| CVR-003 | PLUSDCAPITAL = Y | Highlight Capital flag row in Cost Components tab |

### RICEFW Cross-Reference

| Screen Component | RICEFW Item | Type |
|---|---|---|
| CU Estimation Summary Panel | RICE-F-001 | Form (F) |
| CU Set Management Screen | RICE-F-002 | Form (F) |

### Output Files

- AI-Brain content embedded in `AI-Brain\agent-02-TeDCoS\TDD_CU_Module_Content.md` (Section 7)
- Standalone spec: `Outputs\Agent2\Config-Specs\MX_CU_SCREEN_SPECS-v1.0.xlsx`

---

## US-02-004 — Database Design Documents

### Custom Extension Specification

#### New Columns on PLUSDCU

| Column Name | Data Type | Length | Nullable | Purpose | KBD |
|---|---|---|---|---|---|
| CUST_GASSUB | VARCHAR2 | 10 | Yes | Gas CU sub-type (LPS/HPS/MED) | KBD-001 |
| CUST_RETDTE | DATETIME | — | Yes | INACTIVE CU retirement date for audit | KBD-003 |

#### New Indexes

| Index Name | Table | Columns | Purpose |
|---|---|---|---|
| CUST_IDX_CUTYPE | PLUSDCU | PLUSDCUTYPE | Filter performance for CU type lookups |
| CUST_IDX_CUSTATUS | PLUSDCU | STATUS | Lifecycle query performance |
| CUST_IDX_CUORGSITE | PLUSDCU | ORGID, SITEID | Multi-site filter performance |

### ER Diagram (Text)

```
PLUSDCU (PLUSDCUNUM PK)
  ├──> PLUSDCUITEM (CUNUM FK)
  │      └── LINETYPE: MATERIAL | SERVICE | STDPREM
  ├──> PLUSDCUALABOUR (CUNUM FK)
  │      └── CRAFT FK──> CRAFTSKILL
  ├──> PLUSDCUATOOL (CUNUM FK)
  │      └── TOOLNUM FK──> TOOL
  ├──> PLUSDCUAEQUIP (CUNUM FK)
  │      └── ASSETNUM FK──> ASSET (optional)
  └──> PLUSDCUSETMEMBER (CUNUM FK)
         └── CUSETNUM FK──> PLUSDCUSET

WOCOSTDETAIL
  └── PLUSDCUNUM FK──> PLUSDCU
```

### Schema Validation Results

| Check | Result | Notes |
|---|---|---|
| CUST_GASSUB conflicts with base object | PASS | No PLUSDCU column named CUST_GASSUB in MAS 9 schema |
| CUST_RETDTE conflicts with base object | PASS | No PLUSDCU column named CUST_RETDTE in MAS 9 schema |
| CUST_IDX_CUTYPE duplicate index | PASS | No existing index on PLUSDCUTYPE alone |
| PLUSDCUTYPE domain capacity | PASS | ALN domain supports up to 50 values |

### Output Files

- Embedded in `AI-Brain\agent-02-TeDCoS\TDD_CU_Module_Content.md` (Section 8)
- Referenced in TDD Section 8 as DB Design Document

---

## US-02-005 — Automation Script Skeletons (Jython)

### Scripts to Produce

| Script | File | Launch Point | Object | Business Rule |
|---|---|---|---|---|
| Rate Effectivity Lookup | `CURATE_EFFECTIVITY-v1.0.py` | OBJECT | PLUSDCU | Select correct rate by EFFECTIVEDATE |
| Overhead/Burden Calculation | `CU_OVERHEAD_CALC-v1.0.py` | OBJECT | WOCOSTDETAIL | Apply burden % to CU cost total |
| Capital vs O&M Classification | `CU_CAPITAL_OAM_CLASS-v1.0.py` | OBJECT | WORKORDER | Classify CU cost by asset type + WO type |

### Script Skeleton Template

Each skeleton must include:

```python
# ============================================================
# MX AI Suite — CU Module Automation Script Skeleton
# Script:      [SCRIPT_NAME]
# Launch Point: [OBJECT] — [EVENT: add/save/delete/init]
# Parent US:   [US-02-005]
# Version:     1.0
# Author:      TeDCoS Agent | MX AI Suite
# Date:        [DATE]
# ============================================================
# IMPORTANT: This is a skeleton. Business logic stubs are marked TODO.
# Review against: skills/maximo_core.md and docs/KBD_Register.md
# before implementation.
# ============================================================

# --- Variable Declarations ---
mbo = mbo  # current MBO (Maximo Business Object)
app = mbo.getApp()

# --- Helper: safe get attribute ---
def safe_get(field):
    try:
        return mbo.getString(field)
    except Exception:
        return None

# --- Main Logic ---
def main():
    pass  # TODO: implement business logic here

main()
```

### Script-Specific Stubs

#### CURATE_EFFECTIVITY-v1.0.py

Business logic stub:
```python
# TODO: Get rate lookup inputs
cu_num = safe_get("PLUSDCUNUM")
effective_date = mbo.getDate("EFFECTIVEDATE")
resource_type = safe_get("LINETYPE")  # MATERIAL / LABOUR / TOOL / EQUIP

# TODO: Query PLUSDCUITEM / PLUSDCUALABOUR for rate effective on effective_date
# Use mbo.getMboSet("PLUSDCUITEM").setWhere(...)
# Select rate where EFFECTIVEDATE <= :effective_date AND (ENDDATE IS NULL OR ENDDATE >= :effective_date)

# TODO: Return matched rate; raise MXApplicationException if no rate found
```

#### CU_OVERHEAD_CALC-v1.0.py

Business logic stub:
```python
# TODO: Get burden % from config (store in MAXVAR or ORGANZATION attribute)
BURDEN_PCT = 0.15  # TODO: replace with dynamic lookup [KBD — confirm % with client]

# TODO: Get total CU cost from WOCOSTDETAIL.PLUSDCUNUM
cu_num = safe_get("PLUSDCUNUM")
base_cost = mbo.getDouble("LINECOST")

# TODO: Calculate overhead amount
overhead = base_cost * BURDEN_PCT

# TODO: Write overhead to WOCOSTDETAIL or custom overhead line — confirm with client [KBD]
```

#### CU_CAPITAL_OAM_CLASS-v1.0.py

Business logic stub:
```python
# TODO: Get classification inputs
wo_type = safe_get("WORKTYPE")  # NW (new capital) vs CM/PM (O&M)
asset_class = safe_get("ASSETCLASS")
cu_capital_flag = safe_get("PLUSDCAPITAL")  # Y / N on the CU record

# TODO: Apply classification logic:
# IF wo_type = 'NW' AND cu_capital_flag = 'Y' → CAPITAL
# IF wo_type in ('CM','PM') → OAM
# IF conflict → raise flag for manual review

# TODO: Write result to WORKORDER.PLUSDCOSTCAT or custom attribute [KBD — field name]
```

### Output Files

- AI-Brain: `AI-Brain\agent-02-TeDCoS\Jython_Script_Skeletons.md`
- Client deliverables: `Outputs\Agent2\Scripts\CURATE_EFFECTIVITY-v1.0.py`, `CU_OVERHEAD_CALC-v1.0.py`, `CU_CAPITAL_OAM_CLASS-v1.0.py`

---

## US-02-006 — Security Design Matrix

### CU Module Roles

| Role Code | Role Name | Description |
|---|---|---|
| CU-EST | Estimator | Creates and edits DRAFT CU records; assigns cost components |
| CU-APR | Approver | Promotes CU from DRAFT/PENDING → APPROVED; cannot edit APPROVED records |
| CU-VWR | Viewer | Read-only access to all CU applications and data |
| CU-ADM | CU System Admin | Full access; manages domains, lifecycle, configuration |

### Application Access Matrix

| Application | CU-EST | CU-APR | CU-VWR | CU-ADM | Notes |
|---|---|---|---|---|---|
| PLUSDCULIB (CU Library) | Full | Read + Status | Read | Full | Estimator cannot approve |
| PLUSDCUSET (CU Sets) | Full | Read | Read | Full | |
| WOCOSTDETAIL (WO Actuals) | Read | Read | Read | Full | |
| Domain Manager | None | None | None | Full | |
| Application Designer | None | None | None | Full | |

### Field-Level Restrictions

| Field | Restriction | Role(s) Affected |
|---|---|---|
| UNITCOST | Read-only after APPROVED | CU-EST, CU-APR |
| STATUS | No direct edit (use Status Change button only) | All except CU-ADM |
| CUST_RETDTE | Read-only unless STATUS = INACTIVE | CU-EST |

### Approval Authority Matrix

| Transition | Authorized Roles | Notes |
|---|---|---|
| DRAFT → PENDING | CU-EST | Submit for approval |
| PENDING → APPROVED | CU-APR | Approver sign-off |
| APPROVED → OBSOLETE | CU-ADM | Admin only — irreversible |
| Any → INACTIVE | CU-ADM | KBD-003 pending |

### Output Files

- AI-Brain: `AI-Brain\agent-02-TeDCoS\Security_Design_Matrix.md`
- Client artefact: `Outputs\Agent2\Security\MX_CU_SECURITY_MATRIX-v1.0.xlsx`
- Included as Appendix B in TDD (US-02-001)

---

## RICEFW Source Traceability Rule

**This rule is non-negotiable. Violating it produced the RICE-E-003 defect (2026-09-21).**

Before writing any FDD section reference in the RICEFW Register, the agent MUST:

1. Open the FDD AI-Brain source file: `AI-Brain\agent-01-CUDIn\FDD_CU_Module_Content.md`
2. Locate the specific FR ID or paragraph that mandates the component
3. Write the reference as: `FDD §X (FR-YYY)` — never a bare section number alone
4. If no FR exists → the FDD has a gap. Stop. Add the missing FR to the FDD source before proceeding.

**Format rule:**

| Wrong | Right |
|---|---|
| `FDD §8` | `FDD §8.4 (FR-003)` |
| `FDD §9` | `FDD §9.2 (FR-004)` or `FDD §5 (FR-006), §7.2` |

A bare section number like `FDD §8` is always wrong because section numbers can be guessed.
An FR ID like `FR-006` can only be written correctly by reading the document.

**Root cause of RICE-E-003 defect:** the skill file pre-populated the RICEFW table without this rule,
so the agent at runtime inherited wrong values without a trigger to re-verify them.
Skill files must never contain pre-filled reference data that agents are supposed to derive from source documents.

---

## RICEFW Register — Full Inventory

| ID | Type | Component | Source FDD § | Complexity | Build Agent |
|---|---|---|---|---|---|
| RICE-R-001 | R | CU Cost Summary Report | FDD §9 | Medium | EPIC-04 |
| RICE-R-002 | R | CU Catalogue Listing Report | FDD §7 | Low | EPIC-04 |
| RICE-R-003 | R | CU Variance Analysis Report | FDD §9 | Medium | EPIC-04 |
| RICE-R-004 | R | Regulatory Cost Allocation Report | FDD §9 | Medium | EPIC-04 |
| RICE-I-001 | I | GIS ↔ Maximo CU Sync | FDD §6 | High | EPIC-03 + EPIC-04 |
| RICE-I-002 | I | ERP Cost Posting Interface | FDD §9 | High | EPIC-03 + EPIC-04 |
| RICE-I-003 | I | OMS Work Request Interface | FDD §6 | High | EPIC-03 + EPIC-04 |
| RICE-I-004 | I | Contractor Portal Integration | FDD §9 | Medium | EPIC-03 + EPIC-04 |
| RICE-C-001 | C | Legacy CU Library Conversion | FDD §7 | High | EPIC-05 |
| RICE-C-002 | C | Rate Schedule Historical Load | FDD §9 | Medium | EPIC-05 |
| RICE-E-001 | E | CU Rate Effectivity Engine | FDD §9 | Medium | EPIC-04 |
| RICE-E-002 | E | CU Overhead Calculation | FDD §5 (FR-011) | Medium | EPIC-04 |
| RICE-E-003 | E | CU Capital/O&M Classification | FDD §5 (FR-006), §7.2 | Medium | EPIC-04 |
| RICE-F-001 | F | CU Estimation Summary Panel | FDD §7 | Medium | EPIC-04 |
| RICE-F-002 | F | CU Set Management Screen | FDD §8.1–8.3 | Medium | EPIC-04 |
| RICE-W-001 | W | CU Approval Workflow | FDD §8 | Medium | EPIC-04 |
| RICE-W-002 | W | CU Estimation Sign-Off Workflow | FDD §8 | Medium | EPIC-04 |

Total: 17 items (4R, 4I, 2C, 3E, 2F, 2W)

Output file: `Outputs\Agent2\RICEFW\MX_CU_RICEFW_REGISTER-v1.0.xlsx`

---

## Agent 2 → Agent 3 Handoff Checklist

Before passing artefacts to the InMap Agent (EPIC-03), confirm:

- [ ] TDD v1.0 written to `Outputs\Agent2\TDD\MX_CU_TDD-v1.0.docx`
- [ ] Field Config Specs written to `Outputs\Agent2\Config-Specs\MX_CU_CONFIG_SPECS-v1.0.xlsx`
- [ ] Screen Specs written to `Outputs\Agent2\Config-Specs\MX_CU_SCREEN_SPECS-v1.0.xlsx`
- [ ] DB Design embedded in TDD and schema validation confirmed clean
- [ ] Jython skeletons written to `Outputs\Agent2\Scripts\` (3 files)
- [ ] Security Matrix written to `Outputs\Agent2\Security\MX_CU_SECURITY_MATRIX-v1.0.xlsx`
- [ ] RICEFW Register written to `Outputs\Agent2\RICEFW\MX_CU_RICEFW_REGISTER-v1.0.xlsx`
- [ ] Interface Specs written to `Outputs\Agent2\Interface-Specs\MX_CU_INTERFACE_SPECS-v1.0.docx`
- [ ] Handoff manifest written to `agents\agent-02-TeDCoS\handoff-schema.json`
- [ ] All Open Questions in TDD have an owner and target date

---

*MX AI Suite | Skill version: 1.0*
