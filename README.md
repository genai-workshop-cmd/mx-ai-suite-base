# Maximo Delivery AI Suite

AI-assisted IBM Maximo delivery for the **Compatible Unit (CU)** business process in
Transmission & Distribution utilities — from raw requirements to a validated,
production-ready deployment package.

Built to `MX_AI_Suite_System_Design_v1.0`. Python, FastAPI, Claude API, Git and
Maximo REST. No additional subscriptions, no cloud vector database, no npm build step.

---

## What it does

Upload the requirement material you already have — ADO exports, user stories,
meeting notes, Teams transcripts, spreadsheets, PDFs — and the suite runs it
through six agents, stopping for human approval at every phase boundary.

| Phase | Agent | Produces |
|---|---|---|
| Intake | Orchestrator | Requirement classification and build routing (3A / 3B / both) |
| Design | **Agent 1 — FDD** | `FDD.docx` + flag report |
| Design | **Agent 2 — TDD** | `TDD.docx` + estimation table + handover tokens |
| Build | **Agent 3A — Config** | Build document, App Designer XML, DB Config XML, Jython scripts |
| Build | **Agent 3B — Integration** | Integration document, field mapping workbook, MIF component spec |
| Test | **Agent 4 — Testing** | `testcase.xlsx` + coverage summary |
| Deploy | **Agent 5 — Deployment** | Migration Manager package, runbook, manifest, Git commit |

Every approved artifact is written back into the **AI Brain**, a local RAG store
that the next run searches before it creates anything.

---

## The three rules the system actually enforces

**1. No phase runs until the previous gate is approved.**
Not a convention — the phase machine refuses. Advance while a gate is open and you
get `blocked_by: fdd`, not a document.

**2. No invented Maximo names.**
Every object, attribute, application and status passes through the validator
before it can appear in a document. Resolution order: the live environment, then
a bundled catalogue of **401 real object structures** dumped from a MAS trial,
then *flagged for human review*. A name that cannot be confirmed is never
silently stated as fact.

**3. Search before create.**
Before generating anything, the agent searches the AI Brain. Cosine similarity
≥ 0.85 surfaces the existing document and asks: **Update or New?**

---

## Install

```bash
cd mx-ai-suite
python -m pip install -r requirements.txt
python run.py doctor
```

`doctor` prints a readiness table and tells you exactly what is missing. It exits
0 when the suite can run.

Optional — copy `.env.example` to `.env` and add credentials. **Everything works
without them**: documents fall back to deterministic templates and Maximo names are
validated against the bundled catalogue.

---

## Run it

```bash
python run.py demo      # both blueprint use cases, end to end
python run.py ui        # http://127.0.0.1:8800
```

### Command line

```bash
python run.py start --title "Add CU Comment field" --file requirements.docx
python run.py advance RUN-abc123                       # run the next phase, stop at its gate
python run.py status  RUN-abc123
python run.py approve RUN-abc123 fdd --by "Your Name"
python run.py revise  RUN-abc123 tdd -c "add the security section"
python run.py brain search "CU comment propagate work order"
python run.py maximo check WORKORDER.DESCRIPTION
```

Add `--auto` to run unattended; gates are recorded as `auto (unattended run)` so an
unattended run is never mistaken for a reviewed one.

---

## Configuration

Nothing is hardcoded into an agent prompt.

| What | Where |
|---|---|
| Templates, thresholds, routes | `config/suite.yaml` |
| Business processes (CU, WO, …) | `config/processes/*.yaml` |
| Client document templates | `templates/*.docx` |
| Maximo reference material | `skills/*.md` |
| Credentials | `.env` |

**Swapping templates for a new client** means dropping their `.docx` into
`templates/` and pointing `config/suite.yaml` at it. No code changes.

**Adding a business process** means one YAML file. `config/processes/wo.yaml` is
included as a worked example — the agents refuse to mix vocabulary across processes.

### Model provider

Auto-detected, in this order:

1. `ANTHROPIC_API_KEY` → Claude API
2. `MODEL_URL1` + `MODEL_API_KEY1` + `MODEL_NAME1` → any OpenAI-compatible endpoint
3. neither → **offline mode**, deterministic templates

Every agent has a deterministic path, so the pipeline produces the same document
structure with or without a model. The model improves prose and coverage; it is
never required for the system to function.

### Maximo route

The blueprint specifies OSLC with a `MAXAUTH` header. On the MAS trial and ACN IAX
environments `/maximo/oslc/` is **SAML-intercepted** — it redirects to OIDC and
ignores the API key. The default here is therefore the lowercase `/maximo/api/`
route with an `apikey` header, which works on both. Switch with
`maximo.route: oslc` in `config/suite.yaml` if your environment exposes OSLC
directly; the client detects a redirect and tells you which setting to change.

Agents are **read-only** against Maximo. Only Agent 5 may write, and only after
the final gate.

---

## Layout

```
mx-ai-suite/
├── run.py                  CLI entry point
├── config/                 suite.yaml + per-process definitions
├── core/                   config, contracts, logging, model access
├── ingest/                 docx xlsx pdf pptx md txt json csv html → text
├── maximo/                 read-only client, 401-schema catalogue, validator
├── ai_brain/               versioned store, embeddings, Chroma index, tiered search
├── agents/                 orchestrator + the six specialist agents
├── pipeline/               run persistence and the gated phase machine
├── rendering/              docx, xlsx and deployment packaging
├── prompts/                the shared agent system prompt
├── templates/              client .docx templates (swap per engagement)
├── skills/                 Maximo reference loaded into agent prompts
├── reference/              401 real object-structure schemas
├── brain/                  the AI Brain (store + vector index + audit log)
├── runs/                   one self-contained directory per run
└── tests/
```

---

## AI Brain

Markdown with YAML front matter, laid out as
`brain/store/<process>/<doc_type>/<doc_id>/v1.md`.

* **Versioned** — a write creates `v2`, never overwrites `v1`.
* **Audited** — every write appends to `brain/audit.jsonl`.
* **Dry-run by default** — the pipeline's confirmation is the user gate.

Search runs in three tiers and stops at the first confident hit: metadata filter →
BM25 keyword → semantic similarity. Embeddings are local
(`fastembed`, ONNX, no torch); the vector store is embedded Chroma. If either is
unavailable the system degrades to a pure-Python fallback rather than failing.

```bash
python run.py index --rebuild     # rebuild the vector index from the markdown store
python run.py brain stats
python run.py brain audit
```

---

## Tests

```bash
python -m pytest tests/ -q
```

Covers: the anti-hallucination validator, brain versioning and duplicate
detection, gate enforcement, both reference use cases end to end, and the
validity of every generated `.docx`, `.xlsx`, `.xml` and `.zip`.

---

## Known limits

* **CUJP / PLUSDCU is not in the bundled catalogue.** The PLUSDCU module is not
  installed on the MAS trial the schemas were dumped from, so CU-specific objects
  are correctly reported as *unverified* rather than confirmed. Point the suite at
  an environment that has the module, or accept the flags and confirm manually.
* **Agent 5 does not write to Maximo.** It produces a Migration Manager package and
  a runbook. `deploy_to_maximo()` exists, is gated, and deliberately refuses —
  shipping an untested write path against a live environment is not worth it.
* **Requirement granularity drives estimation.** Effort is computed per deliverable,
  not per requirement line, but a badly split requirement set still produces a
  lumpy estimate. Review the estimation table at the TDD gate.
* **Agent 5's Git commit needs a repository.** Run `git init` in this folder to
  enable it; without one the deploy agent reports "not a git repository" and
  skips the commit. It never pushes — that stays a human action.

`docs/TRACEABILITY.md` maps every blueprint section to its implementation and
lists the five deliberate departures with reasons.
