# MX_TechDocs — Technical Document Authoring Skill
*Version: 1.0 | Last updated: 2026-09-21*

---

## Purpose

Load before authoring any Technical Design Document (TDD), Database Design Document,
Interface Specification, or Security Design Matrix. Defines required structure, language
rules, output conventions, and quality standards for EPIC-02 (TeDCoS) deliverables.

---

## Technical Design Document (TDD)

### Naming Convention

```
MX_[MODULE]_TDD-v[X.X].docx
```

Examples:
- `MX_CU_TDD-v1.0.docx`
- `MX_JOBPLAN_TDD-v1.1.docx`

### Output Location

```
Outputs\Agent2\TDD\MX_[MODULE]_TDD-v[X.X].docx
```

### Template Location

```
templates\TDD\
```

Always render via `render_docs.py` from the AI-Brain `.md` source — never hand-author the `.docx`.

---

## Required TDD Sections (in order)

| # | Section | Content |
|---|---|---|
| 1 | Document Control | Version history, author, reviewer, approver, date, parent FDD reference |
| 2 | Executive Summary | 2–3 sentence overview of what is being technically designed |
| 3 | Scope | In-scope and Out-of-scope items (two-column table) |
| 4 | Technical Architecture | High-level diagram (text); Maximo module (PLUSD) placement; key object relationships |
| 5 | Object Structure Analysis | One subsection per Maximo object: fields, types, lengths, FKs, mandatory flags |
| 6 | Domain Definitions | All ALN/LIST domains required — name, value list, default |
| 7 | Configuration Design | MAF (Application Designer) screen specs, field additions, conditional visibility |
| 8 | Database Design | Custom columns, naming convention, new indexes, ER diagram, schema validation |
| 9 | Integration Summary | Cross-reference to EPIC-03 interface specs; data flows |
| 10 | Automation Scripts | Summary of Jython skeletons produced; launch points; business rule reference |
| 11 | Security Design | Summary; reference to Security Matrix xlsx |
| 12 | RICEFW Inventory | Reference to RICEFW Register xlsx; complexity summary |
| 13 | Assumptions & Constraints | Maximo version, target release, naming conventions, KBD dependencies |
| 14 | Open Questions | OQs inherited from FDD + new TDD-level OQs; each must have an owner |
| A | Appendix A — Field Config Specs | Reference to `Outputs\Agent2\Config-Specs\MX_CU_CONFIG_SPECS-v1.0.xlsx` |
| B | Appendix B — Security Matrix | Reference to `Outputs\Agent2\Security\MX_CU_SECURITY_MATRIX-v1.0.xlsx` |

---

## Language Rules

- **Every requirement:** "The configuration shall…" or "The system shall…" — never "should" or "could"
- **Every custom extension:** prefix `CUST_` — never extend base Maximo objects without this prefix
- **Every KBD-dependent decision:** append `[KBD-XXX — pending]` inline
- **Every Open Question:** label `OQ-xxx` — inherited OQs from FDD keep their original ID
- **Solution tier annotation:** always document tier chosen (Tier 1 OOB / Tier 2 Extension / Tier 3 Jython)

---

## Object Structure Table Format

Use this column set for every object table in Section 5:

| Field Name | Data Type | Length | Mandatory | Domain / FK | Default | Custom? | Notes |
|---|---|---|---|---|---|---|---|
| FIELDNAME | Char/Int/Date/Decimal/CLOB | 8 | Yes/No | domain or FK→OBJECT | value | No/Yes | note |

Rules:
- Custom fields = `CUST_` prefix + Custom? = Yes
- FK fields reference the target object: FK→ITEM, FK→CRAFTSKILL, etc.
- Domain references use the Maximo domain name: e.g., domain=PLUSDCUTYPE
- CLOB type has no Length entry — leave cell blank

---

## Database Design Conventions

| Convention | Rule |
|---|---|
| Custom column prefix | `CUST_` (KBD — confirm with client) |
| Custom index prefix | `CUST_IDX_` |
| Custom table prefix | `CUST_` |
| Naming: all uppercase | Yes — Maximo convention |
| Max column name length | 10 characters (Maximo DB restriction) |
| Data type mapping | Maximo Char→VARCHAR2(n), Integer→INT, Decimal→DECIMAL(15,2), Date→DATETIME |

---

## Interface Spec Document Format

```
Outputs\Agent2\Interface-Specs\MX_CU_INTERFACE_SPECS-v1.0.docx
```

Each interface section covers:
1. Interface ID and name (from RICEFW Register)
2. Direction (Maximo → External / External → Maximo / Bidirectional)
3. Trigger (batch/event/API call)
4. Data objects exchanged (Maximo object → external object mapping)
5. Error handling and retry strategy
6. Security — authentication method, data classification

---

## Markdown Authoring Rules (AI-Brain output → TDD render)

Same rules as FDD (see CUDIn.skill.md) — additionally:

| Content Type | Markdown Format |
|---|---|
| Object ER diagram | ` ``` ` code fence with `──>` arrows and `│` connectors |
| Jython launch point | ` ``` ` code fence — gets Consolas font |
| Field table | Pipe table with blank line before AND after |
| Domain value list | Bullet list `- VALUE: description` |

---

## SME Review Checklist (TDD)

Append to every TDD as Appendix C:

- [ ] All Maximo object names validated against target release data dictionary
- [ ] All custom column names use `CUST_` prefix — confirmed no base object conflicts
- [ ] All domain values approved by Functional Architect
- [ ] MAF screen specs reviewed by Application Designer configurator
- [ ] DB design reviewed by DBA / Maximo Technical Lead
- [ ] Security matrix reviewed by Security Lead
- [ ] All OQ items have an owner and target resolution date
- [ ] RICEFW Register scope confirmed with delivery manager

---

*MX AI Suite | Skill version: 1.0*
