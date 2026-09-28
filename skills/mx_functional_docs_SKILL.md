# MX_FuncDocs — Functional Document Authoring Skill
*Version: 1.0 | Last updated: 2026-09-20*

---

## Purpose

Load before authoring any Functional Design Document (FDD) or User Story.
Defines required structure, language rules, output conventions, and quality standards.

---

## Functional Design Document (FDD)

### Naming Convention

```
MX_[MODULE]_FDD-v[X.X].docx
```

Examples:
- `MX_CU_FDD-v1.0.docx`
- `MX_JOBPLAN_FDD-v1.1.docx`

### Output Location

```
Outputs\FDD\MX_[MODULE]_FDD-v[X.X].docx
```

### Template Location

```
templates\FDD\
```

Always write to the template file via the `word` MCP tool — never create from scratch.

---

## Required FDD Sections (in order)

| # | Section | Content |
|---|---|---|
| 1 | Document Control | Version history, author, reviewer, approver, date |
| 2 | Executive Summary | 2–3 sentence overview of the module and scope |
| 3 | Scope | In-scope and Out-of-scope items (use two-column table) |
| 4 | Business Context | Why this module exists; business driver; client context |
| 5 | Functional Requirements | Numbered list — "System shall..." format with priority |
| 6 | Process Flow | Step-by-step flow (numbered list or swimlane diagram description) |
| 7 | Data Requirements | Key data fields, sources, validation rules |
| 8 | Configuration Design | OOB config settings, domain values, status flows |
| 9 | Integration Points | References to interfaces (FIDD IDs); in/out data |
| 10 | Assumptions | Numbered list of assumptions the design rests on |
| 11 | Open Questions | Table: ID, Question, Owner, Date Raised, Status |
| 12 | Appendices | Supporting data, cross-reference tables, diagrams |

**Parent US ID Reference:** Every FDD must reference the parent User Story ID on the cover page and in Document Control.
Use `US-HOTFIX-XXX` for ad-hoc work with no formal US.

---

## Functional Requirements Language Rules

- Always use **"System shall..."** language for requirements
- Assign a priority to every requirement: **High / Medium / Low**
- Number requirements sequentially: FR-001, FR-002, ...
- Separate functional requirements from configuration notes

Examples:
- **Good:** `FR-001 [High] System shall allow users to create a CU record with a minimum of PLUSDCUNUM, DESCRIPTION, PLUSDCUTYPE, and STATUS fields.`
- **Bad:** `The system needs to create CU records.`

---

## Process Flow Format

Use numbered steps with role prefixes:

```
1. [Functional Architect] Initiates CU record creation in Maximo
2. [System] Validates mandatory fields (PLUSDCUNUM, DESCRIPTION, PLUSDCUTYPE)
3. [System] Sets STATUS = DRAFT on save
4. [Approval Authority] Reviews CU record
5. [System] Transitions STATUS from DRAFT → APPROVED on confirmation
6. [System] Makes CU available for WO estimating
```

---

## Scope Table Format

| In Scope | Out of Scope |
|---|---|
| CU Library ingestion from Excel and Maximo OSLC | CU data migration to target environment |
| Auto-generation of FDD CU sections | Workflow Designer configuration |
| Gap analysis against WO history | Integration to SAP (covered in EPIC-03) |

---

## Open Questions Table Format

| ID | Question | Owner | Date Raised | Status |
|---|---|---|---|---|
| OQ-001 | Which approval roles can transition CU from DRAFT → APPROVED? | Client PM | 2026-09-20 | Open |
| OQ-002 | Are regulatory-review CU statuses required for this engagement? | Functional Architect | 2026-09-20 | Open |

---

## SME Review Checklist (Append to every FDD)

Append this section as the last appendix of every FDD:

```
## SME Review Checklist

- [ ] All functional requirements are complete and unambiguous
- [ ] No "TBD" without an owner name and target date
- [ ] Scope table accurately reflects what is and is not covered
- [ ] All integration dependencies referenced to FIDD IDs
- [ ] Open Questions table reviewed — new questions added where needed
- [ ] Process flow matches client's confirmed business process
- [ ] Data requirements aligned to confirmed Maximo field list
- [ ] KBD references included for all engagement-specific decisions
- [ ] Document version and date updated in Document Control section
```

---

## Document Quality Rules

- No internal shorthand or acronyms without definition on first use
- No "TBD" without an owner and target date
- Client-ready language throughout — write for a non-technical client audience
- All section headings must follow the required structure above
- Version history must be maintained (do not delete prior versions)
- "System shall..." language mandatory for all Functional Requirements

---

## Create vs Update Rule

| Scenario | Action |
|---|---|
| FDD does not exist for this module | Create new using template |
| FDD already exists in `Outputs\FDD\` | Update in place — append new section or update existing rows |
| Updating an existing section | Increment minor version (1.0 → 1.1); add row to Document Control |

---

## User Story Authoring Rules

### Story Format
```
As a [persona],
I want [action/capability],
So that [outcome/benefit].
```

### Acceptance Criteria Format
```
- [ ] [Specific, testable criterion]
- [ ] [Specific, testable criterion]
```

### Story ID Convention
```
US-[EPIC]-[NNN]
```
Example: `US-01-004` (Epic 01, Story 004)

### Priority Levels
| Level | Meaning |
|---|---|
| P0 | Must-have for MVP; blocks other stories |
| P1 | Important; needed for full delivery |
| P2 | Nice-to-have; can be deferred |

---

*MX AI Suite | Skill version: 1.0*
