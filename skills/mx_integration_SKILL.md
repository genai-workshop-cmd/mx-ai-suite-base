# InMap Agent Skill — Integration Mapping Agent
*Skill ID: InMap | EPIC-03 | MX AI Suite*

---

## Purpose

This skill governs the InMap Agent's execution of all 7 stories in EPIC-03. It defines
field-level mapping rules, MIF configuration patterns, XSD schema conventions, test data
requirements, and error handling standards for all four CU module integration points.

**Always read before** starting any US-03-xxx story execution.

---

## Inputs — What InMap Receives from TeDCoS (Agent 2)

Before producing any output, read these source documents:

| Source Document | AI-Brain Path | Key Content |
|---|---|---|
| Interface Specifications | `AI-Brain\agent-02-TeDCoS\Interface_Specs.md` | High-level interface design for RICE-I-001 to RICE-I-004 |
| Technical Design Document | `AI-Brain\agent-02-TeDCoS\TDD_CU_Module_Content.md` | Section 9 (Integration Summary), Section 5 (Object Structure) |
| RICEFW Register | `AI-Brain\agent-02-TeDCoS\RICEFW_Register.md` | Interface complexity, direction, trigger, source FDD reference |
| Field Config Specs | `AI-Brain\agent-02-TeDCoS\Field_Config_Specs.md` | Maximo field names, data types, lengths for mapping |

**Never pre-fill field names or FDD section references.** Derive all values by reading the
source documents above. Cross-document references must include the specific FR ID
(e.g., `FDD §5 (FR-006)` not just `FDD §5`).

---

## Interface Inventory

| ID | Name | Direction | Trigger | Complexity | US |
|---|---|---|---|---|---|
| RICE-I-001 | GIS ↔ Maximo CU Sync | Bidirectional | Batch nightly + event (APPROVED status) | High | US-03-001 |
| RICE-I-002 | ERP Cost Posting Interface | Maximo → ERP | WO Close event (Status → COMP) | High | US-03-002 |
| RICE-I-003 | OMS Work Request Interface | OMS → Maximo | Event (OMS DISPATCHED) | High | US-03-003 |
| RICE-I-004 | Contractor Portal Integration | Maximo → Portal | Batch daily | Medium | US-03-004 |

**GIS system:** PLS-CADD (confirmed from Interface_Specs.md)
**ERP system:** TBD — OQ-010 outstanding (assume SAP for structural purposes; flag as assumption)
**OMS system:** TBD — OQ-011 outstanding (document as ASSUMPTION-003)
**Contractor Portal:** TBD — OQ-012 outstanding (document as ASSUMPTION-004)

---

## US-03-001: GIS Integration Mapping Rules

### Story Purpose
Produce the detailed GIS Integration Design Document (IDD) with field-level mapping,
transformation rules, key matching strategy, MBO publish channel spec, and enterprise
service spec. Input: PLS-CADD GIS feature class attribute list.

### Field Mapping Conventions

**GIS → Maximo (inbound):**
- GIS Feature Class → Maximo Object: read from `TDD_CU_Module_Content.md §5`
- Key matching: CU Number — GIS uses underscore format (e.g. `CU_UGC_004`); Maximo uses
  hyphen format (`CU-UGC-004`). Transformation rule: replace `_` with `-` on ingest.
- Geometry centroid: GIS latitude/longitude → Maximo PLUSDCU latitude/longitude custom fields
  (confirm column names from `Field_Config_Specs.md`)
- CU Type code: GIS attribute `CU_TYPE` → Maximo `PLUSDCU.PLUSDCUTYPE` domain value (OH/UG/SS/DS/GS)
- New GIS CU records → create PLUSDCU in DRAFT status; trigger CU Approval Workflow (RICE-W-001)

**Maximo → GIS (outbound, event-driven):**
- Trigger: PLUSDCU STATUS change to APPROVED
- MBO Publish Channel: `PLUSDCU_PUB_CHANNEL` on PLUSDCU object SAVE
- Processing Rule: filter on `STATUS = 'APPROVED'`
- Outbound payload: PLUSDCUNUM, PLUSDCUTYPE, STATUS, CHANGEDATE, DESCRIPTION
- GIS receiver updates feature class attribute `MAXIMO_STATUS` and `MAXIMO_APPROVED_DATE`

### XSD Requirement
Produce `MX_CU_GIS_MESSAGE.xsd` for the integration message payload covering both
inbound (GIS → Maximo) and outbound (Maximo → GIS) directions.

### Output Files
- AI-Brain: `AI-Brain\agent-03-InMap\GIS_Field_Mapping.md`
- Client (.xlsx): `Outputs\Agent3\Interface-Specs\MX_CU_GIS_FIELD_MAPPING-v1.0.xlsx`
  - Worksheets: GIS→Maximo Inbound, Maximo→GIS Outbound, Transformation Rules, Key Matching
- Client (.xsd): `Outputs\Agent3\Interface-Specs\MX_CU_GIS_MESSAGE.xsd`

---

## US-03-002: ERP Cost Posting Interface Rules

### Story Purpose
Produce the ERP Cost Posting IDD: GL account derivation logic, WBS mapping, Capital vs O&M
split, message format (IDoc/BAPI or REST — confirm OQ-010), and transformation rules.

### Field Mapping Conventions

**Maximo → ERP (outbound):**
- Source object: WOCOSTDETAIL (join to WORKORDER)
- Trigger: WORKORDER.STATUS changes to COMP
- Key cost fields from WOCOSTDETAIL:
  - WONUM, SITEID, ORGID, ITEMNUM, LINECOST, LINETYPE
- CU-specific fields (confirm from `Field_Config_Specs.md`):
  - PLUSDCUNUM — the CU code applied on this WO
  - Capital/O&M flag — derive from output of RICE-E-003 (CU_CAPITAL_OAM_CLASS-v1.0.py)
- GL account derivation logic:
  - Capital WO + Capital CU → Capital GL account (WBS element)
  - O&M WO + O&M CU → O&M GL account (cost centre)
  - If classification is mixed, split proportionally by cost component

**Cost Component → GL Mapping:**

| LINETYPE | ERP Account Type | GL Account | Notes |
|---|---|---|---|
| MATERIAL | Direct Material | Cost centre debit | Item class determines account |
| LABOUR | Direct Labour | Labour clearing account | Craft rate × hours |
| TOOL | Tool/Plant | Tool account | Internal rate recovery |
| EQUIPMENT | Equipment | Equipment clearing | Plant account |
| CONTRACTOR | Contractor Labour | Sub-contract account | PO-linked |
| OVERHEAD | Overhead/Burden | Overhead pool | RICE-E-002 output — FDD §5 (FR-011) |

### Integration Assumption (OQ-010 pending)
Document as ASSUMPTION-002 in IDD: ERP assumed to be SAP. Middleware assumed to be REST API
(IBM API Connect or MuleSoft). IDoc format documented as fallback. Update when OQ-010 resolved.

### XSD Requirement
Produce `MX_CU_ERP_POSTING.xsd` for the ERP posting message payload.

### Output Files
- AI-Brain: `AI-Brain\agent-03-InMap\ERP_Field_Mapping.md`
- Client (.xlsx): `Outputs\Agent3\Interface-Specs\MX_CU_ERP_FIELD_MAPPING-v1.0.xlsx`
  - Worksheets: Maximo→ERP Field Mapping, GL Account Derivation, Cost Component Matrix, Assumptions
- Client (.xsd): `Outputs\Agent3\Interface-Specs\MX_CU_ERP_POSTING.xsd`

---

## US-03-003: OMS Work Request Interface Rules

### Story Purpose
Produce OMS → Maximo work request IDD: message flow, XSD schema, field mappings,
OMS work code → CU type mapping table, error handling, outbound completion update spec.

### Field Mapping Conventions

**OMS → Maximo (inbound):**
- Trigger: OMS work request status reaches DISPATCHED
- OMS work request → create WORKORDER with WONUM prefix `OMS-` (e.g. OMS-000001)
- OMS work code → CU type mapping table (defined in IDD Appendix)
- WORKORDER fields to populate:
  - WONUM: generated (OMS-prefix + sequence)
  - DESCRIPTION: OMS work request description
  - WORKTYPE: derived from OMS work type (corrective, preventive, etc.)
  - SITEID: mapped from OMS location/depot code
  - LOCATION: mapped from OMS asset location reference
  - ASSETNUM: mapped from OMS asset number (1:1 if formats align)
  - CU type hint: added to WO long description if OMS work code maps to a CU type

**Maximo → OMS (outbound, completion update):**
- Trigger: WORKORDER STATUS changes to COMP
- Payload: WONUM, WOCOSTDETAIL summary (total cost, CU codes applied), ACTFINISH
- OMS updates its work request to COMPLETED with Maximo cost reference

### Integration Assumption (OQ-011 pending)
Document as ASSUMPTION-003: OMS system assumed to expose REST API at a documented endpoint.
Authentication assumed OAuth 2.0. Update when OQ-011 resolved.

### XSD Requirement
Produce `MX_CU_OMS_WORK_REQUEST.xsd` for the inbound OMS work request message.

### Output Files
- AI-Brain: contribution to `AI-Brain\agent-03-InMap\IDD_CU_Module_Integration.md` §6
- Client (.xsd): `Outputs\Agent3\Interface-Specs\MX_CU_OMS_WORK_REQUEST.xsd`

---

## US-03-004: Contractor Portal API Specification Rules

### Story Purpose
Generate REST API specification (OpenAPI 3.0) for the Maximo → Contractor Portal integration.
Four endpoints: CU rate schedule, rate approval trigger, material/labour requirements query,
CU specifications retrieval.

### API Endpoint Conventions

| Method | Path | Purpose | Maximo Source |
|---|---|---|---|
| GET | `/cu-rates` | Retrieve approved CU rate schedule | PLUSDCU (APPROVED) + PLUSDCUITEM |
| POST | `/rate-approvals` | Trigger rate approval workflow | PLUSDCU STATUS → PENDING |
| GET | `/work-orders/{wonum}/requirements` | Get material and labour requirements | WOMATL + WOTOOL + WOLABOR |
| GET | `/cu-specs/{cunum}` | Get full CU specification | PLUSDCU + cost components |

### MIF Service Configuration
- Maximo Enterprise Service: `CONTRACTOR_PORTAL_ES` — processes inbound rate submissions
- Maximo Publish Channel: `CONTRACTOR_PORTAL_PC` — pushes approved CU packages to portal nightly

### Integration Assumption (OQ-012 pending)
Document as ASSUMPTION-004: Contractor portal vendor assumed to consume OpenAPI 3.0 REST API.
Authentication assumed API key (portal side) + Maximo integration user (read-only). Update when OQ-012 resolved.

### Output Files
- AI-Brain: `AI-Brain\agent-03-InMap\Contractor_Portal_API_Spec.md` (OpenAPI 3.0 in YAML format)
- Client (.docx): included in IDD rendered document §7

---

## US-03-005: MIF Channel & Service Configuration Rules

### MIF Configuration Standards

**Object Structures:**
- Follow existing Maximo MIF naming conventions
- Prefix all custom object structures with `PLUSDCU`
- Document in TDD Appendix D (Integration Config)

**Publish Channels:**

| Channel Name | Object Structure | Trigger | Processing Rule |
|---|---|---|---|
| `PLUSDCU_GIS_PUB` | `PLUSDCUSYNC` | PLUSDCU SAVE | STATUS = 'APPROVED' |
| `CONTRACTOR_PORTAL_PC` | `PLUSDCUPKG` | Scheduled nightly | STATUS = 'APPROVED' |

**Enterprise Services:**

| Service Name | Object Structure | Protocol | Inbound Handler |
|---|---|---|---|
| `GIS_INBOUND_ES` | `PLUSDCUINB` | HTTP/REST | `plusdcu.integration.GISInboundHandler` |
| `OMS_WORKORDER_ES` | `OMSWKREQUEST` | HTTP/REST | `integration.oms.OMSWorkRequestHandler` |
| `ERP_POSTING_ES` | `ERPPOSTING` | HTTP/REST (or IDoc) | `integration.erp.ERPCostPostHandler` |

**Processing Rules:**
- Filter on STATUS for publish channels (only push APPROVED records)
- Dead-letter queue: all failed records go to MAXEXPORTLOG with retry count
- Retry: 3 attempts, exponential back-off (30s → 2min → 10min), then dead-letter

**Load File Format:** XML (Maximo Integration Framework DBC import format)
**Location:** `Outputs\Agent3\Scripts\MIF-Config\`

### Output Files
- `MX_CU_MIF_GIS_PUB_CHANNEL.xml`
- `MX_CU_MIF_GIS_ENT_SERVICE.xml`
- `MX_CU_MIF_ERP_ENT_SERVICE.xml`
- `MX_CU_MIF_OMS_ENT_SERVICE.xml`
- `MX_CU_MIF_PORTAL_PUB_CHANNEL.xml`

---

## US-03-006: Integration Test Data Rules

### Test Data Standards
- Produce one worksheet per interface in `MX_CU_INTEGRATION_TEST_DATA-v1.0.xlsx`
- Cover: happy path, boundary conditions (max field lengths, zero costs), error scenarios
- All test data must be traceable to a test case ID (TC-03-xxx) for EPIC-06 linkage
- Field values must be valid against Maximo domain values defined in `Field_Config_Specs.md`

### Test Scenario Coverage

| Interface | Happy Path Scenarios | Boundary Scenarios | Error Scenarios |
|---|---|---|---|
| GIS → Maximo | New CU ingest (OH/UG/SS/DS) | Max CU description (200 chars) | Duplicate PLUSDCUNUM |
| Maximo → GIS | APPROVED status push | Null geometry centroid | GIS API timeout |
| ERP Cost Posting | Capital WO close | Zero-cost line | Invalid GL account |
| OMS Work Request | Dispatched WR creates WO | Invalid location code | OMS auth failure |
| Contractor Portal | Nightly CU rate publish | No approved CUs | Portal API unavailable |

### Worksheet Structure (each interface sheet)
Columns: TC-ID | Scenario | Test Data (all fields) | Expected Result | Pass/Fail

### Output File
- `Outputs\Test-Data\MX_CU_INTEGRATION_TEST_DATA-v1.0.xlsx`
- Worksheets: GIS-Inbound, GIS-Outbound, ERP-Posting, OMS-Inbound, OMS-Outbound, Portal-Outbound, Summary

---

## US-03-007: Error Handling Matrix Rules

### Error Matrix Structure (per interface)
Columns: Interface | Error Code | Description | Cause | Retry Attempts | Back-off | Dead-Letter Action | Alert Recipient | BMXAA Code (if applicable)

### BMXAA Error Code Mapping

| BMXAA Code | Meaning | Applicable Interfaces |
|---|---|---|
| BMXAA4210E | Object not found | GIS → Maximo (unknown PLUSDCUNUM) |
| BMXAA6830E | Duplicate record | GIS → Maximo (CU already exists) |
| BMXAA7702E | Validation error | ERP posting (invalid cost amount) |
| BMXAA0022E | Required field missing | OMS → Maximo (no SITEID) |

### Retry Policy
- Max retries: 3
- Back-off: 30s → 2min → 10min (exponential)
- After 3 failures: insert record into MAXEXPORTLOG; send email alert

### Dead-Letter Queue
- All dead-lettered records stored in MAXEXPORTLOG with EXCEPTIONID
- Daily exception report generated by RICE-R-001 (CU Cost Summary) sub-query
- Manual re-trigger available via MIF Re-Submit function in Maximo admin console

### Output File
- `Outputs\Agent3\Interface-Specs\MX_CU_ERROR_HANDLING_MATRIX-v1.0.xlsx`
- Worksheets: GIS, ERP, OMS, Contractor Portal, Summary, BMXAA Reference

---

## Artefact Naming Convention

| Artefact | Naming Pattern | Location |
|---|---|---|
| IDD (main doc) | `MX_CU_IDD-v{n}.docx` | `Outputs\Agent3\Interface-Specs\` |
| Field mapping xlsx | `MX_CU_{SYS}_FIELD_MAPPING-v{n}.xlsx` | `Outputs\Agent3\Interface-Specs\` |
| Error handling matrix | `MX_CU_ERROR_HANDLING_MATRIX-v{n}.xlsx` | `Outputs\Agent3\Interface-Specs\` |
| Test data | `MX_CU_INTEGRATION_TEST_DATA-v{n}.xlsx` | `Outputs\Agent3\Test-Data\` |
| MIF load files | `MX_CU_MIF_{name}.xml` | `Outputs\Agent3\Scripts\MIF-Config\` |
| XSD schemas | `MX_CU_{name}.xsd` | `Outputs\Agent3\Interface-Specs\` |

---

## Source Traceability Rule

Every interface field mapping must cite the specific FR ID from the FDD and TDD:

| Wrong | Right |
|---|---|
| `FDD §6` | `FDD §6 (FR-008) — Interface Requirements` |
| `TDD §9` | `TDD §9 — Integration Summary, RICE-I-001` |
| `Interface Specs §3` | `Interface Specs §3 — RICE-I-001, GIS ↔ Maximo CU Sync` |

---

## Handoff to Agent 4 (RICEFW)

Upon completion of all US-03-xxx stories, produce `agents\agent-03-InMap\handoff-schema.json`
with status and file size for every produced artefact. Mark EPIC-03 as complete.

EPIC-04 (RICEFW Build Acceleration Agent) consumes:
- IDD for all 4 interface build specifications
- XSD schemas for interface build
- MIF configuration load files (EPIC-04 executes the load)
- Integration test data sets (EPIC-06 also consumes)
- Error handling matrix (for build and test coverage)

---

*MX AI Suite | InMap Agent Skill | EPIC-03*
