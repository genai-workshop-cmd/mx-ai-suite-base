# Client Business Processes & Workflows
# ──────────────────────────────────────
# INSTRUCTIONS: Document your client's actual business processes.
# Standard IBM process docs don't cover client-specific status flows,
# approval chains, or custom escalation rules. Add them here.
# ──────────────────────────────────────

## Active Business Processes

Which Maximo processes are in scope for this project:

- [ ] Work Order Management (WO)
- [ ] Preventive Maintenance (PM)
- [ ] Compatible Units (CU)
- [ ] Service Requests
- [ ] Asset Management
- [ ] Inventory / Procurement
- [ ] Integration with: (list external systems)

---

## Work Order Status Workflow

Document any deviations from standard IBM WO status flow.

**Standard IBM flow:** WAPPR → APPR → INPRG → COMP → CLOSE

**Your client's flow:**
```
(e.g.)
WAPPR ──► APPR ──► INPRG ──► COMP ──► CLOSE
           │                              │
           └── Supervisor rejects ──► WAPPR
```

**Custom statuses in use (if any):**

| Status Code | Description | Can be set by | Triggers |
|---|---|---|---|
| (e.g. ONHOLD) | Work on hold pending parts | WOSUPER | Notification to planner |
| (add more) | | | |

---

## PM-to-WO Generation Rules

Rules for how Preventive Maintenance generates Work Orders:

- **Cron task:** PMWOEGENCRON runs every: (frequency, e.g. nightly at 02:00)
- **Lead time:** WOs generated (N) days before PM due date
- **Site filter:** Generates for SITEID = (list)
- **Job Plan assignment:** Auto-assigned from PM.JPNUM
- **Multi-asset:** MULTIASSETLOCCI rows are copied to generated WOs: Yes / No
  - If Yes: which fields are copied from PM's asset list? (list fields)
- **Field copy rules** (PM fields propagated to WO):
  - PM.CLASSSTRUCTUREID → WORKORDER.CLASSSTRUCTUREID (example)
  - PM.WOPRIORITY → WORKORDER.WOPRIORITY (example — add your actual mappings)

---

## Approval Workflows

| Workflow Name | Applied to | Trigger | Approver Role | Rejection goes to |
|---|---|---|---|---|
| (e.g. WOAPPROVAL) | WORKORDER | Status → WAPPR | WOSUPER | Returns to DRAFT |
| (add more) | | | | |

---

## Integration Points

List all external systems that integrate with Maximo:

| System Name | Direction | Protocol | Maximo Object | Trigger |
|---|---|---|---|---|
| (e.g. SAP Finance) | Outbound | REST/MIF | WORKORDER | On CLOSE status |
| (e.g. GIS System) | Inbound | REST | ASSET | On asset change |
| (add more) | | | | |

**Integration notes:**
- External system base URL: (confirm per environment — do not hardcode prod)
- Auth method: API Key / MAXAUTH / OAuth
- Message tracking enabled: Yes / No

---

## Escalations and Notifications

| Escalation Name | Condition | Notification to | SLA |
|---|---|---|---|
| (e.g. WOAPPR_OVERDUE) | WO in WAPPR > 48h | WOSUPER + Planner | 48h |
| (add more) | | | |

---

## Known Constraints & Gotchas

Document any non-obvious constraints discovered during previous work:

- (example: PLUSDCU.CUID must be unique across all ORGIDs, not just per site)
- (example: Automation scripts that run on PM object cannot access MULTIASSETLOCCI via mbo.getMboSet() — must use a separate MAXIMO service call)
- (example: Admin Mode must be run during off-peak hours only — agreed SLA with operations)
- (add yours)
