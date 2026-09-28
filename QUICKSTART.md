# Quickstart

Five minutes from a clean checkout to a deployment package.

---

## 1. Install

```bash
cd mx-ai-suite
python -m pip install -r requirements.txt
```

## 2. Check

```bash
python run.py doctor
```

You want `READY` at the bottom. Two warnings are expected and harmless on a
fresh install:

* *No model configured* — documents use the deterministic templates.
* *MAXIMO_MANAGE_URL not set* — names are validated against the bundled
  401-schema catalogue instead of a live environment.

Both are fixed in step 5 if you want them.

## 3. Prove it works

```bash
python run.py demo
```

Runs both blueprint reference use cases end to end, unattended. You should see
two runs complete with ~16 and ~20 artifacts. Everything lands in `runs/`.

## 4. Use it

```bash
python run.py ui
```

Open **http://127.0.0.1:8800**.

1. **New run** → give it a title, drop in your requirement documents (or press
   *Load Use Case 1* to try the built-in sample) → **Create run**.
2. **Pipeline** → **Run next phase**. Agent 1 produces the FDD and stops.
3. Review the artifacts inline with **View**. Check the **Flags** tab for
   anything the system was not confident about.
4. Enter your name in the gate box and press **Approve**.
5. Repeat until Agent 5 produces the migration package.

The first run takes about 30 seconds longer than later ones — the embedding
model downloads once and is then cached.

## 5. Connect your own credentials (optional)

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# Model — either one. Anthropic wins if both are set.
ANTHROPIC_API_KEY=sk-ant-...
# or
MODEL_NAME1=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
MODEL_URL1=https://integrate.api.nvidia.com/v1/chat/completions
MODEL_API_KEY1=nvapi-...

# Maximo (read-only for Agents 1-4)
MAXIMO_MANAGE_URL=https://your-instance.manage.suite.maximo.com/maximo
MAXIMO_MANAGE_APIKEY=your-api-key
```

Then:

```bash
python run.py doctor --probe     # tests the live Maximo connection
```

No restart needed for the UI — press **Reload configuration** on the Settings page.

---

## Command reference

| Command | What it does |
|---|---|
| `python run.py doctor [--probe]` | Readiness check |
| `python run.py ui` | Web control surface on :8800 |
| `python run.py demo` | Both reference use cases, end to end |
| `python run.py start --title T --file F [--auto]` | Create a run |
| `python run.py advance RUN [--all] [--auto]` | Run the next phase |
| `python run.py status RUN` | Show the pipeline |
| `python run.py approve RUN PHASE --by NAME` | Approve a gate |
| `python run.py revise RUN PHASE -c "..."` | Send a phase back |
| `python run.py runs` | List runs |
| `python run.py brain search "text"` | Query the AI Brain |
| `python run.py brain stats \| audit` | Brain status / write log |
| `python run.py index --rebuild` | Rebuild the vector index |
| `python run.py maximo check OBJECT[.ATTR]` | Validate a Maximo name |
| `python run.py maximo search TERM` | Find object structures |
| `python run.py maximo ping` | Test the live connection |

Phase names for `approve` / `revise`: `fdd`, `tdd`, `build_config`,
`build_integration`, `test`, `deploy`.

---

## Where things land

```
runs/RUN-abc123/
├── state.json          the whole run — safe to inspect
├── run.log
├── inputs/             copies of what you uploaded
├── 01_fdd/             FDD.docx, FDD.md, FDD_flag_report.md
├── 02_tdd/             TDD.docx, handover_tokens.json
├── 03a_config_build/   build doc, app_designer_export.xml, dbconfig.xml, scripts/
├── 03b_integration/    integration doc, Field_Mapping.xlsx, mif_components.xml
├── 04_test/            testcase.xlsx, coverage summary
└── 05_deploy/          runbook, migration_package_*.zip, MANIFEST.json
```

Approved artifacts are also written into `brain/store/` as versioned markdown, so
the next run finds them.

---

## Troubleshooting

**`UnicodeEncodeError` in the console** — shouldn't happen; the CLI forces UTF-8
and falls back to ASCII glyphs. If it does, set `PYTHONIOENCODING=utf-8`.

**First run is slow** — `fastembed` downloads `BAAI/bge-small-en-v1.5` (~130 MB)
once. If the machine is offline, the suite falls back to hashed embeddings and
says so; search still works, less precisely.

**"Maximo redirected the request"** — the OSLC route is SAML-intercepted. Set
`maximo.route: api` in `config/suite.yaml`.

**A phase won't run** — a gate is open. `python run.py status RUN` shows which
one and who owns it. This is the intended behaviour.

**Search finds nothing after adding documents manually** —
`python run.py index --rebuild`.
