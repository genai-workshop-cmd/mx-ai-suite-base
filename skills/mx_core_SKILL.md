# MX_Core — IBM Maximo EAM Platform Knowledge (MAS 8 / MAS 9)
*Version: 2.0 | Platform: MAS 8.x / MAS 9.x / Maximo 7.6 | Last updated: 2026-09-28*

---

## Purpose

Load before ANY Maximo task: FDD, TDD, Config, Integration, Scripting, Security, or Reporting.
Do NOT rely on general LLM knowledge for field names, statuses, object behaviour, or API patterns —
always verify against this skill first. If a field or behaviour is not listed here, FLAG it.

---

## 1. Architecture Overview

Maximo is a TPAE (Tivoli Process Automation Engine) EAM platform. Every application maps to one
or more **MBOs (Managed Business Objects)** — Java objects that enforce business rules and write
to the database. All writes must go through MBO APIs or OSLC REST — never direct SQL DML.

### Deployment Variants
| Version | Platform | Database | UI | API |
|---|---|---|---|---|
| Maximo 7.6.x | Java EE, WebSphere/WebLogic | Oracle / SQL Server / DB2 | Classic JSP | OSLC v1 |
| MAS 8.x | OpenShift containers | Oracle / DB2 (Maximo DB) + MongoDB (app data) | React (MAF) | OSLC v1 + GraphQL |
| MAS 9.x | OpenShift containers | Oracle / DB2 + MongoDB | React (MAF) | OSLC v1 + GraphQL |

### Core Object Hierarchy
```
Organization → Site → Location (hierarchy) → Asset (hierarchy)
                           ↓                        ↓
                      Work Orders ←─────────────────
                           ↓
                    Job Plans / PM Records
```

### Scoping Rules (Critical)
| Scope | Objects | Required field |
|---|---|---|
| Site-scoped | WORKORDER, ASSET, LOCATIONS, INVENTORY | SITEID |
| Org-scoped | ITEM, VENDOR, COMPANIES, CRAFTRATE | ORGID |
| System-level | Workflow, Domains, Classifications, Automation Scripts | Neither |

---

## 2. Work Order Management

### Work Order Status Lifecycle
```
WAPPR (Waiting Approval)
  ├── APPR (Approved)
  │     ├── WMATL  (Waiting on Materials)
  │     ├── WPCOND (Waiting on Plant Conditions)
  │     ├── WSCHD  (Waiting to be Scheduled)
  │     └── INPRG  (In Progress)
  │              ├── COMP  (Completed)
  │              └── CLOSE (Closed — financial close, no further cost posting)
  └── CAN (Cancelled)
```

### Key Work Order Fields
| Field | Attribute | Notes |
|---|---|---|
| WO Number | WORKORDER.WONUM | Alphanumeric, site-scoped |
| Description | WORKORDER.DESCRIPTION | 100 chars |
| Status | WORKORDER.STATUS | Domain: WOSTATUS |
| Work Type | WORKORDER.WORKTYPE | PM, CM, EM, NW, etc. |
| Asset | WORKORDER.ASSETNUM | FK → ASSET |
| Location | WORKORDER.LOCATION | FK → LOCATIONS |
| GL Account | WORKORDER.GLACCOUNT | Financial coding |
| Target Start | WORKORDER.TARGSTARTDATE | Scheduling |
| Target Finish | WORKORDER.TARGCOMPDATE | Scheduling |
| Owner | WORKORDER.OWNER | Responsible person |
| Owner Group | WORKORDER.OWNERGROUP | Responsible group |
| Job Plan | WORKORDER.JPNUM | FK → JOBPLAN |
| PM | WORKORDER.PMNUM | FK → PM |
| Parent WO | WORKORDER.PARENT | Hierarchy |
| Priority | WORKORDER.WOPRIORITY | 1–9 |
| Work Class | WORKORDER.WOCLASS | WORKORDER / ACTIVITY |

### Rules
- CLOSE = financial close; no cost posting after CLOSE
- Status changes via `changeStatus()` MBO method — never direct field update
- `INHERISTATUSCHANGES` controls child WO status inheritance
- If WO is in a workflow, direct status change may be blocked

---

## 3. Asset Management

### Asset Status Lifecycle
`NOT READY → OPERATING → DECOMMISSIONED` (client-configurable via ASSETSTATUS domain)

### Key Asset Fields
| Field | Attribute | Notes |
|---|---|---|
| Asset Number | ASSET.ASSETNUM | Unique per site |
| Status | ASSET.STATUS | Domain: ASSETSTATUS |
| Location | ASSET.LOCATION | Current operating location |
| Parent | ASSET.PARENT | Hierarchy |
| Serial Number | ASSET.SERIALNUM | |
| Failure Class | ASSET.FAILURECODE | FK → FAILURELIST |
| Manufacturer | ASSET.MANUFACTURER | |
| Replace Cost | ASSET.REPLACECOST | |

---

## 4. Job Plans

### Job Plan Status Lifecycle
`DRAFT → ACTIVE → INACTIVE` (PNDREV / REVISED for revision cycle)

**Critical rule:** Only ACTIVE job plans can be applied to WOs and PMs.

### Key Behaviour
- Revising creates a new version; old moves to REVISED
- Only one ACTIVE version at a time per JP number
- Job Plan → WO: populates Plans tab (tasks, labor, materials, tools)

---

## 5. Preventive Maintenance (PM)

### PM WO Generation
- Driven by `PMWOEGENCRON` cron task
- Lead time: WO generated X days before due date
- Blocked by: invalid asset status, DRAFT job plan, PM in DRAFT
- Key fields: `NEXTDATE`, `NEXTDUEDATE`, `LEADTIME`, `FREQUENCY`, `FREQUNIT`

### PM Frequency Types
- Calendar-based: days / weeks / months / years
- Meter-based: reading threshold on asset/location meter
- Seasonal: active months/seasons only

---

## 6. Inventory, Purchasing & Contracts

### Inventory Key Objects
| Object | Purpose |
|---|---|
| ITEM | Item master catalog |
| INVENTORY | Item-storeroom combinations (qty, cost, reorder) |
| MATRECTRANS | Material receipt transactions |
| INVTRANS | Inventory transactions (issue, transfer, return) |

### Purchasing Flow
```
PR (PURCH REQ) → PO (PURCH ORDER) → RECEIPT → INVOICE
```

### Contract Types
Purchase, Blanket, Labor, Lease/Rental, Warranty, Software, Master

---

## 7. Security Architecture

### Key Groups
| Group | Purpose |
|---|---|
| MAXADMIN | Full admin |
| MAXEVERYONE | Baseline for all users |
| MAXDEFLTREG | Default self-registration |

### Permission Model
- Independent groups: permissions NOT merged with other groups
- Non-independent groups: permissions additive across all user's groups
- Data Restrictions: row-level security via SQL WHERE on object+group

### Authentication
- Maximo native: username/password in Maximo DB
- LDAP: Active Directory integration
- SAML/SSO: standard for MAS 8/9 deployments

---

## 8. Maximo Functional Rules — Non-Negotiable

1. **MBO over SQL** — never recommend direct SQL INSERT/UPDATE on Maximo tables. Always MBO API or OSLC REST. Direct SQL bypasses business rules and audit trails.
2. **Status changes** — always use `changeStatus()` MBO method. Never set STATUS field directly.
3. **Admin Mode** — required for DB Config `Apply Configuration Changes`. Turn ON, apply, turn OFF immediately. Leaving Admin Mode on blocks most application usage.
4. **Job Plans must be ACTIVE** — DRAFT or INACTIVE job plans cannot be used on WOs or PMs.
5. **Site/Org context** — always include SITEID (site-scoped) or ORGID (org-scoped) in all queries and new records.
6. **OSLC pagination** — default page size 50, max ~1000. Always paginate for large datasets.
7. **Workflow + status** — if a WO/record is in an active workflow, direct status change may be blocked. Route through workflow instead.
8. **Custom attribute naming** — always prefix with org/client abbreviation (e.g., `CUST_`, `AWM_`). Never unprefixed. Prevents upgrade conflicts.
9. **ROWSTAMP** — read before any MBO update (optimistic locking).
10. **CHANGEBY / CHANGEDATE** — system-managed fields. Never write directly.

---

## 9. MAS 8 / MAS 9 Specific Notes

### Deployment
- OpenShift (OCP) containerised
- MongoDB for application/workspace data; Oracle/DB2 for Maximo transactional data
- Maximo pods: maxinst (core), mea (integration), report, cron, ui

### Authentication
- SAML / OIDC SSO standard; local users only for admin/emergency
- MAS licenses: Manage (EAM), Health, Predict, Visual Inspection, etc.

### API
- OSLC REST: `https://<host>/maximo/oslc/os/<ObjectStructure>`
- GraphQL available in MAS 9: `https://<host>/maximo/graphql`
- Auth headers:
  - API Key: `apikey: <key>` header
  - MAXAUTH (7.6): `MAXAUTH: base64(user:pass)` — NO "Basic " prefix
  - OAuth: standard Bearer token

### React UI (MAF)
- App Designer still used for config customisation
- Inspection Forms are separate from App Designer (React-native)
- MAS 9: some legacy JSP dialogs removed

---

## 10. Module Quick Reference

| Module | Key Applications |
|---|---|
| Work Management | Work Order Tracking, Assignment Manager, Quick Reporting, Labor Reporting, Service Requests |
| Asset Management | Assets, Locations, Meters, Failure Codes, Condition Monitoring |
| Planning | Job Plans, Routes, Safety Plans |
| Preventive Maintenance | PM, Master PM |
| Inventory | Item Master, Inventory, Storerooms, Issues and Transfers |
| Purchasing | Purchase Requisitions, Purchase Orders, Receiving, Invoices |
| Contracts | Contracts (Purchase, Blanket, Labor, Warranty, Lease, Software, Master) |
| System Configuration | DB Config, Domains, App Designer, Automation Scripts, Workflow, Cron Tasks, Escalations, Roles, Actions, Communication Templates, Migration Manager |
| Security | Security Groups, Users, Person Groups |
| Integration | Object Structures, Enterprise Services, Publish Channels, External Systems, End Points |
| Reporting | Report Administration, BIRT, Cognos (MAS) |

---

*MX AI Suite | Core Skill v2.0 | IBM Maximo MAS 8/9 | Last updated: 2026-09-28*
