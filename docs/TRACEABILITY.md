# Blueprint traceability

Maps every requirement in `MX_AI_Suite_System_Design_v1.0` to where it is
implemented and how it is verified.

Legend: **Built** = implemented and tested · **Adapted** = implemented
differently, with the reason stated · **Deferred** = deliberately not built.

---

## 2. Guiding design principles

| Principle | Status | Where | Verified by |
|---|---|---|---|
| AI Brain is the single source of truth | Built | `ai_brain/`, `pipeline/runner.py::_write_to_brain` | `test_approval_writes_into_the_brain` |
| Search before create | Built | `ai_brain/search.py::find_duplicate` | `test_duplicate_detection_fires_on_a_true_duplicate` |
| Production-ready output only | Built | every agent's `_deterministic` + `output_format` | `test_generated_documents_open_cleanly` |
| No hallucination | Built | `maximo/validator.py` | `test_maximo.py` (8 tests) |
| User gate at every phase boundary | Built | `pipeline/runner.py::next_phase` | `test_gate_blocks_the_next_phase` |
| Templates are client-agnostic | Built | `core/config.py::template_path`, `config/suite.yaml` | `test_docx_render_uses_the_template` |
| Minimal footprint | Built | `requirements.txt` — all open source, no server, no npm | `python run.py doctor` |

## 3. Architecture

| Layer | Status | Where |
|---|---|---|
| Input layer | Built | `ingest/extract.py` — 10 formats |
| AI Brain | Built | `ai_brain/{store,embeddings,index,search}.py` |
| Orchestration agent | Built | `agents/orchestrator.py` |
| Specialist agents | Built | `agents/` — 6 agents |
| Output / deployment | Built | `rendering/package.py` |

### 3.1 AI Brain

| Spec | Status | Note |
|---|---|---|
| Chroma DB, local, no subscription | Built | `ai_brain/index.py`; pure-Python fallback if Chroma fails |
| Local sentence-transformers embeddings | Adapted | Uses `fastembed` (same ONNX models, no 5 GB torch dependency). Hashed fallback if offline. |
| Metadata → full-text → semantic, stop at first confident hit | Built | `ai_brain/search.py::search` |
| Write back after gate approval | Built | `pipeline/runner.py::_write_to_brain` |
| Similarity > 0.85 → Update or New? | Built | Compared on **raw cosine**, not the blended rank score |
| IBM docs pre-loaded | Adapted | 7 Maximo skill files in `skills/` + 401 real object-structure schemas. Live IBM URL fetching not built. |

### 3.2 Orchestration agent

All six responsibilities built in `agents/orchestrator.py`: intent parsing,
classification, agent sequencing, Case 1/Case 2 detection, 3A/3B routing.
Verified by `test_routing_sends_config_work_to_3a_only` and
`test_routing_sends_integration_work_to_3b`.

## 4. Agent specifications

| Agent | Status | Outputs produced |
|---|---|---|
| 1 — FDD | Built | `FDD.docx`, `FDD.md`, `FDD_flag_report.md` |
| 2 — TDD | Built | `TDD.docx`, `TDD.md`, `handover_tokens.json` |
| 3A — Config Build | Built | build doc (md + docx), `app_designer_export.xml`, `dbconfig.xml`, `scripts/*.py` |
| 3B — Integration | Built | integration doc (md + docx), `Field_Mapping.xlsx`, `mif_components.{json,xml}` |
| 4 — Testing | Built | `testcase.xlsx` (exact column set), `Test_Coverage_Summary.md` |
| 5 — Deployment | Built | `Deployment_Runbook.md`, `migration_package_*.zip`, `MANIFEST.json`, Git commit |

All seven of Agent 1's processing steps, all nine of Agent 2's, and Agent 4's
four coverage requirements are implemented. Agent 2's estimation is computed
**per deliverable** rather than per requirement line — several requirements
describing one interface would otherwise over-estimate several-fold
(`test_estimate_is_per_deliverable_not_per_requirement`).

## 5. Data flow and gate sequence

All 15 steps built. The phase machine refuses to advance past an open gate
(`test_gate_blocks_the_next_phase`), and revision returns to the same phase
(`test_revision_reruns_the_same_phase`).

## 6. Maximo integration

| Spec | Status | Note |
|---|---|---|
| Authentication in `.env`, never hardcoded | Built | `core/config.py`; the app never prints a secret |
| OSLC base path `/maximo/oslc/` | **Adapted** | Default is the lowercase `/maximo/api/` route with an `apikey` header. `/oslc/` is SAML-intercepted on both documented environments and ignores the key. Switch via `maximo.route: oslc`. |
| Read operations | Built | `maximo/client.py` — GET only |
| DB schema check, never raw SQL | Built | `maximo/catalog.py` over 401 object-structure schemas |
| Script name collision check | Built | `validator.script_name_free` |
| Writes only via Agent 5 after final gate | Built | `deploy_agent.py::deploy_to_maximo` requires an approved gate **and** a matching token |

## 7. AI Brain technical design

| Spec | Status |
|---|---|
| UTF-8 markdown + YAML front matter, structured folders | Built |
| Chroma, local embeddings | Built |
| Three-tier search, 0.85 threshold | Built |
| Dry-run by default | Built (`test_dry_run_is_the_default`) |
| Versioned, never overwrite | Built (`test_second_write_versions_rather_than_overwrites`) |
| JSON Lines audit log | Built (`test_every_write_is_audited`) |

## 8. Folder structure

Adapted. Same components, organised as Python packages with the responsibilities
split further (`core/`, `pipeline/`, `rendering/`, `ingest/`) so each module has
one job. The blueprint's `agents/`, `ai_brain/`, `maximo_client/` (→ `maximo/`),
`templates/`, `skills/`, `ui/`, `.env`, `README.md` are all present.

## 9. Agent system prompt

Built as a Jinja template at `prompts/agent_system.md.j2`, rendered per agent by
`BaseAgent.system_prompt()`. Every section of the blueprint's pattern is present,
plus a `VALIDATED MAXIMO FACTS` whitelist the model is told it may not go outside.

## 10. UI/UX

| Screen | Status |
|---|---|
| Home / process selector | Built — Dashboard + process selector on New run |
| Upload & start | Built — drag-and-drop, paste, detected document types |
| Agent pipeline view | Built — phase rail with per-phase status |
| Document review panel | Built — inline docx/xlsx/markdown preview, flags with reason and confidence, Approve / Request revision / Skip |
| AI Brain explorer | Built — search, browse, read, download, reindex |
| Deployment console | Built — package contents and final gate in the rail |

Interface type: **Adapted**. The blueprint says Streamlit or Flask. This uses
FastAPI plus a dependency-free HTML/CSS/JS front end — no build step, no npm, and
no SPA framework, so it honours "not a full-stack SPA" while looking like a
product. Case 1 (update existing) and Case 2 (new) are both implemented.

## 12. Out of scope — respected

* No new subscriptions — every dependency is open source.
* No cloud vector DB — embedded Chroma, local embeddings.
* No React/Next.js — vanilla front end, zero build.
* No deployment without gate approval — enforced in code.
* No cross-process mixing — enforced by `config/processes/*.yaml` and the metadata filter (`test_process_isolation`).
* No hallucinated IBM documentation — only the bundled skills, the schema catalogue and the live environment.

## 13. Build sequence — all 8 sprints delivered

Each sprint's "done when" criterion is covered by a test in `tests/`.

---

## Deliberate departures, in one place

1. **Maximo route** — `/api/` + `apikey` instead of `/oslc/` + `MAXAUTH`, because
   `/oslc/` does not authenticate on the target environments. Configurable.
2. **Embeddings** — `fastembed` instead of `sentence-transformers`, same models,
   no torch.
3. **UI** — FastAPI + vanilla front end instead of Streamlit.
4. **Estimation granularity** — per deliverable, not per requirement line.
5. **Direct Maximo write-back** — gated and deliberately disabled. Agent 5 produces
   a Migration Manager package instead. Shipping an untested write path against a
   production EAM is not a reasonable default.
