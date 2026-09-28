# MX_TechConfig — Maximo Technical Configuration Skill (MAS 8 / MAS 9)
*Version: 2.0 | Platform: MAS 8.x / MAS 9.x / Maximo 7.6 | Last updated: 2026-09-28*

---

## Purpose

Load before any TDD, Config Build, or technical design task. Covers App Designer, Database
Configuration, Domains, Workflow Designer, Cron Tasks, and Escalations. Supplements mx_core_SKILL.md
— load both together. If a behaviour is not listed here, FLAG it.

---

## 1. Database Configuration (DB Config)

`System Configuration → Platform Configuration → Database Configuration`

### Process to Add a Custom Attribute
1. DB Config → search for the object (e.g., WORKORDER)
2. Attributes tab → Add New Row
3. Fill: Attribute name (use client prefix e.g., `CUST_MYFIELD`), Type, Length, Description
4. **Turn Admin Mode ON** (`Manage Admin Mode`)
5. **Apply Configuration Changes** (runs DDL — adds column to DB and regenerates MBOs)
6. **Turn Admin Mode OFF** immediately
7. Surface the field in App Designer
8. Add to Object Structure if integration exposure is needed

### Attribute Data Types
| Type | Maximo type | DB column | Use |
|---|---|---|---|
| ALN | ALN | VARCHAR | Alphanumeric free text |
| UPPER | UPPER | VARCHAR | Uppercase alphanumeric |
| INTEGER | INTEGER | INT / NUMBER | Whole numbers |
| DECIMAL | DECIMAL | DECIMAL / NUMBER | Numbers with decimals |
| YORN | YORN | CHAR(1) | Boolean — Y or N |
| DATE | DATE | DATE | Date only |
| DATETIME | DATETIME | TIMESTAMP | Date and time |
| DURATION | DURATION | DECIMAL | HH:MM format |
| LONGALN | LONGALN | CLOB | Long text (>254 chars) |
| BLOB | BLOB | BLOB | Binary data |

### Adding a New Object (Custom Table)
1. DB Config → New Object → name (e.g., `CUST_MYTABLE`)
2. Add a persistent attribute (e.g., `CUST_MYTABLENUM` as primary key)
3. Set object properties (entity name, class name if MBO extension needed)
4. Apply Configuration Changes in Admin Mode
5. Create a Maximo application via App Designer if UI is needed

### Key Rules
- Never modify OOTB object/attribute names — only ADD custom ones
- Custom prefix prevents upgrade conflicts: `CUST_`, `AWM_`, `PLUSD_` etc.
- `ROWSTAMP` is system-managed — never include in custom tables as writable
- Changes to persistent attributes require Admin Mode; changes to non-persistent (calculated) do not

---

## 2. Domains

`System Configuration → Platform Configuration → Domains`

### Domain Types
| Type | Description | Common Use |
|---|---|---|
| ALN | Free-text value list | Custom picklists |
| NUMERIC | Numeric value list | Codes, ranges |
| TABLE | Dynamic lookup from another object | Person lookup, item lookup |
| CROSSOVER | Copies value(s) to other fields when selected | Auto-populate related fields |
| SYNONYM | Extends an existing MAXVALUE list (most common for statuses) | Custom status values |

### Adding Synonym Domain Values (Status Extension)
1. Domains → Search for domain (e.g., WOSTATUS)
2. Values tab → Add synonym entry
3. Set: Value (internal), Synonyms (display), Description, Default
4. No Admin Mode needed for domain value changes

### Domain Best Practices
- Always use SYNONYM domains to extend existing status domains — never rename OOTB values
- TABLE domains: define lookup conditions (WHERE clause) to filter lookup results
- CROSSOVER domains: document the crossover mapping in the TDD — easy to misconfigure

---

## 3. Application Designer (App Designer)

`System Configuration → Platform Configuration → Application Designer`

### Key Concepts
- XML-based presentation layer — each app has a Maximo Presentation XML definition
- Import/Export: use to backup, version-control, and migrate app customisations
- Clone App: create a copy of an OOTB app to customise without touching the original

### UI Control Types
| Control | Tag | Use |
|---|---|---|
| Text box | `<textbox>` | Single-line field input |
| Multipart textbox | `<multiparttext>` | Long description (CLOB fields) |
| Checkbox | `<checkbox>` | YORN fields |
| Table | `<table>` | Multi-row child object display |
| Tab | `<tab>` | Tab panel grouping |
| Section | `<section>` | Collapsible grouping within a tab |
| Button | `<pushbutton>` | Toolbar or inline action |
| Lookup | `<lookup>` | Value lookup with search dialog |
| Image | `<image>` | Static image/icon |

### Adding a Custom Field to an Existing Application
1. App Designer → Open the application
2. Navigate to the tab/section where the field should appear
3. Click the region → Add Control → Textbox (or appropriate type)
4. Set: Attribute (field name), Label, Data Attribute (same as attribute for persistence)
5. Save and test

### Signature Options & Conditions
- **Signature Options (sigOptions):** control what actions a Security Group can perform in an app
- **Conditions:** boolean expressions evaluated at runtime to:
  - Show / Hide a control
  - Make a field readonly or required
  - Enable / Disable a button
- Conditions use object attributes and relationships
- Example condition: `STATUS = "APPR"` → make DESCRIPTION readonly

### App Designer Best Practices (IBM)
- Always export XML before modifying — store in version control
- Clone OOTB apps before customising — do not modify delivered apps in-place
- New fields added via DB Config first, then surfaced in App Designer
- Use consistent tab/section naming across all customised applications
- Label keys (MAXPRESENTATION) should follow `{appname}.{fieldname}` pattern
- Test in a lower environment before promoting to production

### MAS 9 Specifics
- React-based Inspection Forms are separate from App Designer (different tool)
- App Designer still governs all non-inspection UI customisation
- Some legacy JSP dialogs removed in MAS 9 — test after upgrade

---

## 4. Workflow Designer

`Administration → Workflows`

### Workflow Node Types
| Node | Purpose | Notes |
|---|---|---|
| Start | Entry point | One per process |
| Stop | Exit point | Multiple allowed |
| Task | Assigns work; waits for response | Linked to Role for assignment |
| Decision | Conditional branch | Evaluates condition to route |
| Subprocess | Calls another workflow | Reusable sub-process |
| Interaction | Directs user to specific app/tab | No wait — just navigation hint |
| Wait | Pauses for condition or time | Used with escalation |
| Manual Input | Collects user input via dialog | Custom fields or memo |

### Workflow-Related Objects
| Object | Purpose |
|---|---|
| Actions | Field changes, record creation, script calls triggered at routing |
| Communication Templates | Emails sent during WF routing |
| Escalations | Enforce time limits on Task nodes |
| Roles | Resolve who receives a WF task dynamically |

### Workflow Design Rules (IBM Best Practice)
- Processes operate at **System** level — multisite/multiorg
- Any MBO can have a workflow process
- Records enter WF manually (Route Workflow action) or automatically (via Object Launch Point)
- Only one active workflow instance per record at a time (unless parallel paths configured)
- Audit trail maintained automatically in WFASSIGNMENT table
- Always define a timeout escalation on Task nodes — unescalated tasks block processes indefinitely
- Use Roles (not individual users) for task assignment — supports staff changes without redesign
- Document all Decision node conditions in TDD with the exact condition expression

### Workflow Status Interaction
- Workflow can control which status transitions are available
- Use `APPACTION` with `changeStatus` action to trigger status changes via workflow
- If WO is in workflow: direct status change via API may succeed but skip workflow — always route properly

### Approval Workflow Pattern (Standard)
```
Start → Task (Submitter reviews) → Decision
                                     ├── Approve → Action (changeStatus APPR) → Stop
                                     └── Reject  → Action (changeStatus WAPPR + notification) → Stop
```

---

## 5. Cron Tasks

`System Configuration → Platform Configuration → Cron Task Setup`

### Key OOTB Cron Tasks
| Cron Task | Purpose | Key Parameters |
|---|---|---|
| PMWOEGENCRON | Generates WOs from PM records | SITEID, ORGID, lead time |
| ESCALATION | Processes escalation definitions | (runs all active escalations) |
| REORDERITEMS | Triggers inventory reorder | SITEID |
| WFESCALATION | Workflow escalation processing | (runs all WF escalations) |
| LDAPSYNC | Syncs users from LDAP/AD | LDAPURL, base DN |
| MAILROUTER | Processes inbound email | mailbox config |
| REPORTSCHEDULE | Runs scheduled BIRT reports | (per schedule definition) |

### Cron Task Configuration
- Each cron task can have **multiple instances** (e.g., one PMWOEGEN per site)
- Instance parameters override defaults for that instance
- Schedule: frequency (minutes/hours/days), active hours, active days
- Can be paused/resumed without server restart
- `ACTIVE` flag: set to 0 to disable an instance without deleting it

### Custom Cron Task Development
1. Create a Java class extending `CrontaskInstance`
2. Override `execute()` method with business logic
3. Register in `CRONTASKDEF` + `CRONTASKPARAM` tables (via DB Config, not direct SQL)
4. Deploy via EAR/pod restart in MAS; hot-deploy available in 7.6

### Cron Task Best Practices (IBM)
- Run PMWOEGEN at off-peak hours (overnight) — generates large DB transaction volumes
- Always scope PMWOEGEN instances by SITEID to avoid cross-site interference
- Monitor cron task execution in `CRONTASKHISTORY` table or Log Viewer
- Set meaningful descriptions on instances — support teams need to identify them
- Test new cron tasks in non-prod with a limited SITEID scope first

---

## 6. Escalations

`Administration → Escalations`

### Escalation Components
| Component | Description |
|---|---|
| Escalation Definition | Object, condition (SQL WHERE), schedule frequency |
| Escalation Points | Time thresholds (e.g., 24h, 48h, overdue) |
| Actions | Change field value, create record, run script, send email |
| Notifications | Communication template to role/person/group |

### Escalation Processing Flow
```
ESCALATION cron task fires
  → Evaluates all active escalation definitions
    → For each matching record (WHERE condition)
      → Checks elapsed time against escalation points
        → Triggers configured action + notification at each threshold
```

### Escalation Configuration Steps
1. Administration → Escalations → New
2. Set: Name, Description, Object (e.g., WORKORDER), Condition (SQL WHERE clause)
3. Add Escalation Points: elapsed time + action/notification at each point
4. Add Notifications: Communication Template + Role/Person
5. Activate the escalation
6. Ensure `ESCALATION` cron task is running

### Roles (for Notifications)
- Defined in `Platform Configuration → Roles`
- Types: Person, Person Group, Dataset (derived from object data), User Data, Custom, Email Address
- Dataset role: evaluates an OSLC query against the record to find the recipient dynamically

### Escalation Best Practices (IBM)
- Always test conditions with a manual SQL WHERE before saving — typos cause silent misses
- Escalation points are cumulative: 24h fires, then 48h fires (not 24h after first point)
- Use Communication Templates (not hardcoded email text) — templates support translations
- Document every escalation in the TDD with: object, condition, time points, actions, recipients
- Avoid very short intervals (< 15 min) — they cause excessive DB load
- Escalations that check many records should have indexed WHERE clause columns

---

## 7. Migration Manager

`Administration → Migration Manager`

### Purpose
Migrates configuration data (not transactional data) between environments: DEV → TEST → PROD.

### Migratable Content
Automation Scripts, Workflows, Escalations, Communication Templates, Job Plans, Classifications,
Domains, App Designer XML, Cron Task configs, Security Groups, Actions, Roles, Reports

### Migration Package Process
1. Source: create Package Definition (select objects/records to include)
2. Create Package (generates ZIP)
3. Transfer ZIP to target environment
4. Distribution Manager: import and apply package
5. Verify in target environment

### Key Rules
- Migrates **configuration only** — not WOs, assets, inventory data
- Dependencies must be included: e.g., migrating a Workflow requires its Actions and Roles too
- Always test migration in a lower environment before PROD
- Keep Migration Manager packages in version control (they are ZIP files)

---

## 8. Communication Templates

`Administration → Communication Templates`

### Template Variables
Variables use Maximo attribute syntax: `:FIELDNAME` or `:OBJECTNAME.FIELDNAME`

Example:
```
Work Order :WONUM - :DESCRIPTION has been approved.
Location: :LOCATION  Asset: :ASSETNUM
Please proceed with scheduling.
```

### Best Practices
- Never hardcode email addresses in templates — use Roles
- Support multiple languages via message keys
- Test variable substitution in a non-prod environment
- Use for: Workflow notifications, Escalation notifications, manual Communications

---

*MX AI Suite | TechConfig Skill v2.0 | IBM Maximo MAS 8/9 | Last updated: 2026-09-28*
