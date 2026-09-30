# MX AI Suite — Knowledge Directory

This folder is the **single place** where you feed domain knowledge to the AI agents.
Everything here is loaded automatically — no code changes needed.

---

## Directory Structure

```
knowledge/
├── README.md               ← this file
├── ibm_urls.txt            ← extra IBM documentation URLs to fetch and cache
│
├── client/                 ← CLIENT-SPECIFIC KNOWLEDGE (auto-loaded by all agents)
│   ├── mx_client_objects_SKILL.md     ← your custom Maximo objects & fields
│   ├── mx_client_sites_SKILL.md       ← site/org-specific rules
│   ├── mx_client_security_SKILL.md    ← security groups & access patterns
│   └── mx_client_processes_SKILL.md   ← custom workflows & business processes
│
└── training/               ← TRAINING MATERIALS (paste content into client/ .md files)
    └── (put reference docs, past FDDs/TDDs, SOPs here to copy from)
```

---

## How It Works

```
knowledge/client/*.md  ─────────────────────────────────────────────────────────►
                                                                                  │
skills/*.md (core IBM knowledge)  ──────────────────────────────────────────────► LLM System Prompt
                                                                                  │
skills/corrections_*.md (auto-learned from reviewer feedback)  ─────────────────►
                                                                                  │
skills/ibm_docs_cache.md (IBM KC fetched pages)  ───────────────────────────────►
```

Every `.md` file you drop into `knowledge/client/` is **automatically injected into every
agent's system prompt** the next time a run is processed. No restart needed.

---

## What to Put Where

### `knowledge/client/` — Your Client's Maximo Environment

These files teach the agents about *your specific Maximo installation*.
Fill in the provided templates with real values from your environment.

| File | What to put in it |
|---|---|
| `mx_client_objects_SKILL.md` | Custom objects (CUJP, PLUSDCU, ZZMYOBJ), their fields, types, and purpose |
| `mx_client_sites_SKILL.md` | Site IDs, Org IDs, which rules apply per site, inter-org rules |
| `mx_client_security_SKILL.md` | Security group names, what access level each holds, which apps |
| `mx_client_processes_SKILL.md` | Custom status workflows, escalation rules, SLAs |

**Tips for writing good knowledge files:**
- Be specific: use exact Maximo field names (`WORKORDER.SITEID`), not just descriptions
- Include examples of correct values: `SITEID = 'BEDFORD'`, `ORGID = 'ENGELINA'`
- State constraints explicitly: "This rule applies to SITEID=BEDFORD only"
- List what does NOT apply: "PLUSDCU is not used in the WO process"

### `knowledge/ibm_urls.txt` — Extra IBM Documentation Pages

One line per page:
```
Label | https://www.ibm.com/docs/en/...
```
After adding URLs, run:
```bash
python run.py ibmdocs sync
```
This fetches and caches the pages into `skills/ibm_docs_cache.md`.

### `knowledge/training/` — Reference Materials

Paste completed FDDs, TDDs, SOPs, client decision logs here.
These are **not** auto-loaded — copy the relevant sections into the `client/` skill files.

---

## AI Brain vs Knowledge Files

| | `knowledge/client/` | AI Brain (approved runs) |
|---|---|---|
| **Updated by** | You (manual) | Automatically when you Approve a gate |
| **Used for** | Client environment facts, business rules | Prior art for duplicate detection, terminology |
| **Scope** | All runs forever | Per doc_type, per business process |
| **Best for** | "This field always exists on WORKORDER" | "Here's what a good FDD looks like" |

Both are injected into the prompt. Fill both for best results.

---

## Quick Start

1. Open `knowledge/client/mx_client_objects_SKILL.md`
2. Replace the placeholder examples with your actual Maximo objects and fields
3. Do the same for sites, security, and processes
4. Run your next pipeline — the agents will immediately use the new knowledge
5. After approving 2–3 runs, the AI Brain will also have prior art to reference
