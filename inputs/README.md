# MX AI Suite — Source File Input Guide

This folder is for **reference only** — you do not manually copy files here.

When you start a run via the UI or CLI, uploaded files are automatically placed in:
```
runs/RUN-xxx/inputs/
```

---

## How to Start a Run

### Via the UI (recommended)
1. Open http://127.0.0.1:8800
2. Click **New Run**
3. Enter a title (e.g. "PM to WO CLASSSTRUCTUREID Copy — BEDFORD")
4. Upload one or more source files
5. Click **Start**

### Via the CLI
```bash
python run.py start --title "My Change Title" --file path/to/requirement.docx
# Multiple files:
python run.py start --title "My Change" --file req.docx --file notes.docx --file ado.xlsx
```

---

## What Files to Upload Per Run

Upload **all the material that describes the requirement** for that change.
The more context the AI has, the better the output.

| Source type | File format | What to include |
|---|---|---|
| ADO / Jira export | `.xlsx`, `.csv`, `.json` | User stories, acceptance criteria, tags |
| Meeting notes | `.docx`, `.txt`, `.md` | Workshop output, decisions, constraints |
| Scope document | `.docx`, `.pdf` | Change request, scope statement, charter |
| Existing specs | `.docx`, `.pdf` | Prior FDDs, TDDs, architecture docs |
| Teams chat export | `.txt`, `.html` | Key decision threads |
| Visio / process flows | `.pdf` (exported) | As-is / to-be process diagrams |

**Supported formats:** `.docx` `.xlsx` `.xlsm` `.pdf` `.pptx` `.md` `.txt` `.json` `.csv` `.html`

---

## Tips for Better AI Output

### Write a good title
The title is used for AI Brain duplicate detection and prior-art search.
Use a descriptive title that names the Maximo object and what's changing:
- ✅ "PM to WO CLASSSTRUCTUREID field copy — BEDFORD site"
- ✅ "Add Designer field to Work Order application — WOTRACK"
- ❌ "Change 1" (too vague — agents won't find prior art)

### Upload requirements, not just meeting notes
The AI extracts requirements from lines containing: "shall", "must", "should",
"need to", "require", "add", "create", "modify", "update", "enable".
Make sure your requirement statements use these verbs.

### Include acceptance criteria
Acceptance criteria become test cases in Agent 4 (Testing).
The clearer they are in the source material, the more specific the test cases.

---

## Run Output Location

All artifacts for a run are written to:
```
runs/
└── RUN-xxx/
    ├── inputs/          ← your uploaded files (read-only after upload)
    ├── 01_fdd/          ← FDD.md, FDD.docx, FDD_flag_report.md
    ├── 02_tdd/          ← TDD.md, TDD.docx, handover_tokens.json
    ├── 03a_config_build/ ← Config doc, App Designer XML, DB config XML, scripts
    ├── 03b_integration/ ← Integration doc, Field_Mapping.xlsx, MIF components
    ├── 04_test/         ← testcases.xlsx, Test_Cases_Document.md/.docx
    └── 05_deploy/       ← Deployment_Runbook.md, migration_package_RUN-xxx.zip
```

You can download any artifact from the UI after a phase completes.

---

## AI Brain — Long-Term Knowledge

When you **Approve** a phase in the UI, the document is written to the AI Brain:
```
OneDrive / SharePoint → MX-AI-Brain/store/WO/fdd/DOC-xxx/latest.md
```

Future runs will automatically search the brain for prior art — the more approved
documents are in the brain, the better agents replicate your organisation's style.

**Rule of thumb:** Approve every good document. Reject with a specific correction
comment every document that is wrong — the more specific your comment, the more
the AI learns.
