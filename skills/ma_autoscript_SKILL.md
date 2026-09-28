# RICEFW Build Acceleration Agent Skill
*Skill ID: RICEFW | EPIC-04 | MX AI Suite*

---

## Purpose

This skill governs the RICEFW Build Acceleration Agent's execution of all 7 stories in EPIC-04.
It defines coding standards, scaffolding rules, output conventions, and quality gates for all
RICEFW components: Reports (BIRT/Cognos), Interface Adapters, Conversion Scripts, Jython
Automation Scripts, App Designer XML, Workflow Design XML, and Code Quality Review.

**Always read before** starting any US-04-xxx story execution.

---

## Inputs — What Agent 4 Receives from Agents 1–3

Before producing any output, read these source documents:

| Source Document | AI-Brain Path | Key Content |
|---|---|---|
| Functional Design Document | `AI-Brain\agent-01-CUDIn\FDD_CU_Module_Content.md` | FR-001 to FR-011, §7–§9, approval matrix (§8.4) |
| Technical Design Document | `AI-Brain\agent-02-TeDCoS\TDD_CU_Module_Content.md` | Sections 5, 9, 10, 12 — object model + script specs |
| RICEFW Register | `AI-Brain\agent-02-TeDCoS\RICEFW_Register.md` | 17 items: complexity, FDD refs, build agent assignment |
| Jython Script Skeletons | `AI-Brain\agent-02-TeDCoS\Jython_Script_Skeletons.md` | Skeletons for RICE-E-001 to E-003 with TODO stubs |
| Field Config Specs | `AI-Brain\agent-02-TeDCoS\Field_Config_Specs.md` | Maximo field names, types, lengths |
| Integration Design Document | `AI-Brain\agent-03-InMap\IDD_CU_Module_Integration.md` | All 4 interface specs (RICE-I-001 to I-004) |
| GIS Field Mapping | `AI-Brain\agent-03-InMap\GIS_Field_Mapping.md` | GIS↔Maximo field-level mappings |
| ERP Field Mapping | `AI-Brain\agent-03-InMap\ERP_Field_Mapping.md` | Maximo→SAP GL posting field maps |
| MIF Configuration | `AI-Brain\agent-03-InMap\MIF_Configuration.md` | Object structures, channels, services |
| Error Handling Matrix | `AI-Brain\agent-03-InMap\Error_Handling_Matrix.md` | 27 error codes, retry policy, alert recipients |
| KBD Register | `docs\KBD_Register.md` | All closed KBDs affecting build decisions |

**Resolved decisions that unlock Agent 4 build:**
- ERP = SAP S/4HANA 2023 (KBD resolved); GL accounts: Capital 1310100–1310600, O&M 6120000–6520000
- OMS = Oracle NMS v2.4 (KBD resolved); OMS WO prefix = NMSWO-
- Contractor Portal = SAP Fieldglass (KBD resolved)
- Middleware = IBM API Connect v10
- Burden rate = 12% (confirmed); stored in MAXVARS as CU_BURDEN_PCT
- Capital/O&M output field = PLUSDCOSTCAT on WORKORDER object
- CUST_ prefix confirmed for all custom columns

---

## RICEFW Inventory Assigned to EPIC-04

| ID | Type | Name | US | Complexity | Primary Source |
|---|---|---|---|---|---|
| RICE-R-001 | Report | CU Cost Summary Report | US-04-001 | Medium | FDD §9.1–9.4 |
| RICE-R-002 | Report | CU Catalogue Listing Report | US-04-001 | Low | FDD §7 (FR-001, FR-002) |
| RICE-R-003 | Report | CU Variance Analysis Report | US-04-001 | Medium | FDD §9.1–9.2 |
| RICE-R-004 | Report | Regulatory Cost Allocation Report | US-04-001 | Medium | FDD §5 (FR-006), §9.1–9.4 |
| RICE-I-001 | Interface | GIS ↔ Maximo CU Sync Adapter | US-04-002 | High | IDD §4, GIS_Field_Mapping.md |
| RICE-I-002 | Interface | ERP Cost Posting Adapter | US-04-002 | High | IDD §5, ERP_Field_Mapping.md |
| RICE-I-003 | Interface | OMS Work Request Adapter | US-04-002 | High | IDD §6 |
| RICE-I-004 | Interface | Contractor Portal Adapter | US-04-002 | Medium | IDD §7, Contractor_Portal_API_Spec.md |
| RICE-E-001 | Enhancement | CU Rate Effectivity Engine | US-04-004 | Medium | FDD §5 (FR-005), §9.1–9.2 |
| RICE-E-002 | Enhancement | CU Overhead Calculation | US-04-004 | Medium | FDD §5 (FR-011) |
| RICE-E-003 | Enhancement | CU Capital/O&M Classification | US-04-004 | Medium | FDD §5 (FR-006), §7.2 |
| RICE-F-001 | Form | CU Estimation Summary Panel | US-04-005 | Medium | FDD §7 (FR-001, FR-004) |
| RICE-F-002 | Form | CU Set Management Screen | US-04-005 | Medium | FDD §8.1–8.3 (FR-007) |
| RICE-W-001 | Workflow | CU Approval Workflow | US-04-006 | Medium | FDD §8.4 (FR-003) |
| RICE-W-002 | Workflow | CU Estimation Sign-Off Workflow | US-04-006 | Medium | FDD §8.4 (FR-003) |

Note: RICE-C-001 and RICE-C-002 (Conversions) are scoped to EPIC-05 in the RICEFW Register but
US-04-003 covers CU-to-Job Plan migration and supplementary conversion scripts for data readiness.
Three conversion scripts are within Agent 4 scope; RICE-C-001/C-002 full loads remain in EPIC-05.

---

## US-04-001: Report Generation Rules

### BIRT Report Design Standards
- Reports are Eclipse BIRT `.rptdesign` XML files importable into Maximo BIRT Report Designer
- Every report must include: Data Source definition (Maximo DB connection), Dataset (SQL + parameters),
  Report Layout (table sections, headers, groupings, totals, page footer with report ID + date)
- Parameter naming convention: `p_` prefix (e.g. `p_orgid`, `p_siteid`, `p_from_date`, `p_to_date`)
- Always include ORGID and SITEID as mandatory parameters — never hard-code
- All currency amounts formatted as `#,##0.00` with column total row
- Report ID in page footer: `GridCo Utilities | MX CU Module | {REPORT_NAME} | v1.0`

### Report SQL Conventions
- Join WORKORDER via WONUM + SITEID + ORGID (never WONUM alone — multi-site)
- Always filter active CUs: `PLUSDCU.STATUS IN ('APPROVED', 'OBSOLETE')` — never return DRAFTs
- Capital vs O&M split: use `PLUSDCU.PLUSDCAPITAL` ('Y'/'N') or `WORKORDER.PLUSDCOSTCAT` post-classification
- Date ranges: always use `WORKORDER.REPORTDATE` for period filtering (not CHANGEDATE)

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\Report_Designs.md`
- Client: `Outputs\Agent4\Reports\MX_CU_{REPORT_CODE}_RPT-v1.0.rptdesign` (4 files)

---

## US-04-002: Interface Adapter Rules

### Adapter Architecture
- All adapters are **Python 3.8+** scripts (not Jython — run outside Maximo JVM)
- Each adapter is standalone: reads from environment variables or a `config.ini` for credentials
- Adapters call Maximo Integration Framework endpoints (MIF REST API) — never direct DB
- Standard adapter structure:
  ```
  1. Config loader (env vars / config.ini)
  2. Logger setup (rotating file handler)
  3. Connection class (with retry decorator)
  4. Message transformer (source → target schema)
  5. Dispatcher (post/get with auth header)
  6. Error handler (log + dead-letter)
  7. Main runner (argparse for CLI invocation)
  ```
- Retry: `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=30))`
- Dead-letter: on final failure, write record to `./dead-letter/{adapter}-{timestamp}.json`
- Unit test harness: `tests/{adapter}_test.py` with pytest; mock MIF and external API calls

### Adapter Naming
| RICEFW ID | Adapter File | Protocol | Direction |
|---|---|---|---|
| RICE-I-001 | `MX_CU_GIS_ADAPTER-v1.0.py` | HTTP/REST | Bidirectional |
| RICE-I-002 | `MX_CU_ERP_ADAPTER-v1.0.py` | REST (SAP OData v4) | Maximo → SAP |
| RICE-I-003 | `MX_CU_OMS_ADAPTER-v1.0.py` | REST (Oracle NMS) | OMS → Maximo |
| RICE-I-004 | `MX_CU_PORTAL_ADAPTER-v1.0.py` | REST (Fieldglass API) | Maximo → Fieldglass |

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\Interface_Adapters.md`
- Client: `Outputs\Agent4\Scripts\Adapters\` (4 Python files)

---

## US-04-003: Conversion Script Rules

### Conversion Script Standards
- All conversion scripts are SQL (DB2/Oracle compatible — use ANSI SQL where possible)
- Each script follows a 5-section structure:
  ```
  -- SECTION 1: PRE-LOAD VALIDATION (SELECT-only queries to catch issues before DML)
  -- SECTION 2: STAGING TABLE LOAD (INSERT into staging/temp table)
  -- SECTION 3: MAIN LOAD (INSERT/UPDATE target Maximo tables)
  -- SECTION 4: POST-LOAD RECONCILIATION (row count checks, orphan checks)
  -- SECTION 5: ROLLBACK PROCEDURE (DELETE/UPDATE to undo the load)
  ```
- Always include row count assertions: `SELECT COUNT(*) FROM ... -- Expected: NNN`
- Rollback must be non-destructive: restore previous state, not raw DELETE
- Transaction boundary: each script is one transaction — `BEGIN WORK ... COMMIT WORK`

### Conversion Script Inventory (US-04-003 scope)
| File | Content | Target Tables |
|---|---|---|
| `MX_CU_LEGACY_CONVERSION-v1.0.sql` | Legacy WMIS CU → PLUSDCU records (30-record pilot) | PLUSDCU, PLUSDCUITEM, PLUSDCUALABOUR, PLUSDCUATOOL |
| `MX_CU_RATE_SCHEDULE_LOAD-v1.0.sql` | Historical craft/tool/equipment rates | CRAFTRATE, ITEMCOST |
| `MX_CU_JOBPLAN_MIGRATION-v1.0.sql` | CU-to-Job Plan links | JOBTASK (via PLUSDCU cross-ref) |

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\Conversion_Scripts.md`
- Client: `Outputs\Agent4\Scripts\Conversions\` (3 SQL files)

---

## US-04-004: Jython Automation Script Rules

### Implementation Requirements (expanding from TeDCoS skeletons)
- All TODO stubs must be replaced with working code
- No skeleton headers ("IMPORTANT: Skeleton only") in v2.0 — these are production-ready scripts
- Apply confirmed KBD decisions:
  - Burden rate: read from `MAXVARS.VARVALUE WHERE VARNAME = 'CU_BURDEN_PCT'` (confirmed: 12%)
  - Overhead output: create new WOCOSTDETAIL child line (LINETYPE = 'OVERHEAD') — not a custom field
  - Capital/O&M output: write to `WORKORDER.PLUSDCOSTCAT` field (NOACCESSCHECK required)
- Every script must:
  - Guard against double-posting (check for existing OVERHEAD line before creating)
  - Use `mbo.getMboSet()` with explicit `mboSet.close()` in finally block to prevent memory leaks
  - Raise `MXApplicationException` (never `sys.exit()`) with a descriptive message key
  - Log entry + exit to `log.debug()` with script name + key field values

### Coding Standards Gate (ties to US-04-007)
- After writing each script, run checklist before marking Done:
  - [ ] No direct attribute access (all values via `getString()`, `getDouble()`, etc.)
  - [ ] All MboSets closed in finally block
  - [ ] No hardcoded org/site/rate values
  - [ ] try/except around all MboSet queries
  - [ ] NOACCESSCHECK used on all setValue() calls
  - [ ] isEmpty() checked before getMbo(0)

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\Jython_Scripts_Complete.md`
- Client (v2.0 scripts): `Outputs\Agent4\Scripts\` (3 .py files — replace v1.0 skeletons)

---

## US-04-005: App Designer XML Rules

### MAF (Mobile Application Framework) / App Designer Standards
- App Designer XML format: Maximo Presentation XML (PRESENTATION element root)
- Import via: Maximo → Go To → System Configuration → Platform Configuration → Application Designer → Import
- Never hard-code field labels — use MAXPRESENTATION message keys (`{appname}.{fieldname}`)
- Section tag: `<section id="..." label="...">`
- Conditional visibility: `<condition value="..." attribute="..." trigger="..." />`
- All custom panels must have a unique `id` attribute prefixed with `PLUSDCU`

### Screen Inventory
| RICEFW ID | Screen / Panel | Application | Section |
|---|---|---|---|
| RICE-F-001 | CU Estimation Summary Panel | WOTRACK (Work Order Tracking) | New tab: CU Estimation |
| RICE-F-002 | CU Set Management Screen | PLUSDCUSET (CU Set application) | Enhanced List + Detail |

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\App_Designer_Specs.md`
- Client: `Outputs\Agent4\App-Designer\` (2 XML files)

---

## US-04-006: Workflow Design XML Rules

### Maximo Workflow Design Standards
- WD XML format: Maximo Workflow Designer export format (WFPROCESS element root)
- Import via: Maximo → Go To → Administration → Workflows → Import
- Every workflow must define: PROCESSNAME, DESCRIPTION, OBJECTNAME, nodes, connections, roles
- Role assignment: use Security Group names (CU-ENG, CU-APR) not individual usernames
- Notification: WFNOTIFICATION element with SENDTO and TEMPLATE references
- Approval conditions: use WFCONDITION with attribute + operator + value

### Workflow Inventory
| RICEFW ID | Workflow | Object | Trigger | Roles |
|---|---|---|---|---|
| RICE-W-001 | CU Approval Workflow | PLUSDCU | STATUS → PENDING APPROVAL | CU-ENG (submitter), CU-APR (approver) |
| RICE-W-002 | CU Estimation Sign-Off Workflow | WORKORDER | Manual action — "Submit for CU Sign-Off" | CU-ENG, CU-APR |

### Approval Route Rules (from FDD §8.4 (FR-003))
- RICE-W-001: DRAFT → submit action → PENDING APPROVAL → CU-APR task → approve/reject
  - Approve → STATUS = APPROVED; Reject → STATUS = DRAFT + rejection notification to submitter
- RICE-W-002: WO in status WAPPR (waiting approval) → CU-APR task → sign-off
  - Sign-off → WO moves to APPR; Reject → WAPPR with comment

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\Workflow_Design_Specs.md`
- Client: `Outputs\Agent4\Workflows\` (2 XML files)

---

## US-04-007: Code Quality Review Rules

### Review Scope
- All Jython scripts (RICE-E-001 to E-003 v2.0)
- All interface adapters (RICE-I-001 to I-004)
- All conversion SQL scripts (US-04-003)

### Anti-Pattern Checklist (Maximo-specific)
| Anti-Pattern | Severity | Rule |
|---|---|---|
| `mbo.{field}` direct attribute access | Blocker | Use `mbo.getString("FIELD")` |
| `sys.exit()` in Jython | Blocker | Use `MXApplicationException` |
| MboSet not closed | Blocker | Always close in `finally` |
| getMbo(0) without isEmpty() check | Blocker | Guard with `if not mboSet.isEmpty()` |
| Hardcoded org/site/rate | Warning | Read from MAXVARS or parameters |
| setValue() without NOACCESSCHECK | Warning | Add `MboConstants.NOACCESSCHECK` |
| No logging | Warning | Add `log.debug()` at entry/exit |
| SQL string concatenation | Warning | Use parameterised queries |
| No retry logic in adapters | Warning | Apply tenacity `@retry` decorator |
| No dead-letter handling | Warning | Write failed records to dead-letter file |
| Missing unit tests | Info | Each adapter needs pytest harness |

### Output Files
- AI-Brain: `AI-Brain\agent-04-RICEFW\Code_Quality_Report.md`
- Client: `Outputs\Code-Review\MX_CU_CODE_QUALITY_REPORT-v1.0.docx` (pandoc render)

---

## Source Traceability Rule

Every generated artefact must cite the specific FR ID, not just a section number:

| Wrong | Right |
|---|---|
| `FDD §9` | `FDD §9.1–9.2 (FR-005)` |
| `TDD §10` | `TDD §10 — RICE-E-001, CU Rate Effectivity Engine` |
| `RICEFW §E` | `RICEFW Register — RICE-E-003 (FDD §5 (FR-006), §7.2)` |

---

## Artefact Naming Convention

| Artefact Type | Naming Pattern | Location |
|---|---|---|
| BIRT report | `MX_CU_{CODE}_RPT-v{n}.rptdesign` | `Outputs\Agent4\Reports\` |
| Jython script | `{SCRIPTNAME}-v2.0.py` | `Outputs\Agent4\Scripts\` |
| Python adapter | `MX_CU_{SYS}_ADAPTER-v{n}.py` | `Outputs\Agent4\Scripts\Adapters\` |
| Conversion SQL | `MX_CU_{TYPE}_CONVERSION-v{n}.sql` or `MX_CU_{TYPE}_LOAD-v{n}.sql` | `Outputs\Agent4\Scripts\Conversions\` |
| App Designer XML | `MX_CU_{SCREEN}-v{n}.xml` | `Outputs\Agent4\App-Designer\` |
| Workflow WD XML | `MX_CU_{WF}_WF-v{n}.xml` | `Outputs\Agent4\Workflows\` |
| Code quality report | `MX_CU_CODE_QUALITY_REPORT-v{n}.docx` | `Outputs\Code-Review\` |

---

## Handoff to Agent 6 (TestAuto)

Upon completing all US-04-xxx stories:
1. Update `agents\agent-04-RICEFW\handoff-schema.json` — all artefacts PRODUCED with file sizes
2. Update `product-backlog\epic-04-RICEFW-agent.md` — all US-04-xxx → Done
3. Update `product-backlog\backlog.md` — EPIC-04 → Done
4. Confirm handoff to EPIC-06 (TestAuto Agent)

TestAuto (EPIC-06) consumes:
- All Jython scripts (v2.0) for unit test case generation
- All adapters for integration test harness
- App Designer XML for UI regression test suite
- Workflow XML for workflow scenario test data
- Code Quality Report as a pre-test quality gate reference

---

*MX AI Suite | RICEFW Build Acceleration Agent Skill | EPIC-04*
