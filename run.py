#!/usr/bin/env python
"""Maximo Delivery AI Suite - command line entry point.

    python run.py doctor                       check the install and credentials
    python run.py ui                           start the web control surface
    python run.py start  --title T --file F    create a run and route it
    python run.py advance RUN_ID               run the next phase, stop at its gate
    python run.py approve RUN_ID PHASE --by N  approve a gate
    python run.py revise  RUN_ID PHASE -c "…"  send a phase back
    python run.py status  RUN_ID               show the pipeline
    python run.py runs                         list runs
    python run.py brain  search "text"         query the AI Brain
    python run.py index  [--rebuild]           (re)build the vector index
    python run.py maximo check OBJECT[.ATTR]   validate a Maximo name
    python run.py demo                         run both blueprint use cases end to end

  Claude Code bridge (no API key needed):
    python run.py prompt-export RUN_ID PHASE   export the prompt to a .txt file
    python run.py prompt-inject RUN_ID PHASE --response-file R.txt   inject response
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402
from core.errors import SuiteError  # noqa: E402
from core.logging import setup  # noqa: E402
from core.models import PHASE_LABEL, Phase  # noqa: E402

# ---------------------------------------------------------------- output ---
def _prepare_console() -> bool:
    """Force UTF-8 on the console. Returns True if box glyphs are safe.

    The default Windows console codepage is cp1252, which cannot encode the
    glyphs used below; without this the CLI dies on its first heading.
    """
    ok = True
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            ok = False
    if ok:
        try:
            "─◆↺✓·".encode(sys.stdout.encoding or "utf-8")
        except (UnicodeEncodeError, LookupError):
            ok = False
    return ok


_UNICODE_OK = _prepare_console()

_C = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[38;5;245m",
    "green": "\033[38;5;42m", "red": "\033[38;5;203m", "amber": "\033[38;5;214m",
    "blue": "\033[38;5;39m", "grey": "\033[38;5;250m",
}
_USE_COLOUR = sys.stdout.isatty()

_RULE = "─" if _UNICODE_OK else "-"
_ARROW = "→" if _UNICODE_OK else "->"
_OK = "✓" if _UNICODE_OK else "OK"
_BAD = "✗" if _UNICODE_OK else "X"
_REDO = "↺" if _UNICODE_OK else "<<"
_PEND = "◆" if _UNICODE_OK else "!"
_PLAY = "▶" if _UNICODE_OK else ">"


def c(text: str, colour: str) -> str:
    return f"{_C[colour]}{text}{_C['reset']}" if _USE_COLOUR else text


def head(text: str) -> None:
    print(f"\n{c(text, 'bold')}\n{c(_RULE * len(text), 'dim')}")


def kv(key: str, value: str, width: int = 24) -> None:
    print(f"  {c(key.ljust(width), 'grey')} {value}")


_STATUS_MARK_UNICODE = {
    "approved": ("✓", "green"),
    "awaiting_review": ("◆", "amber"),
    "revision_requested": ("↺", "amber"),
    "skipped": ("–", "dim"),
    "not_ready": ("·", "dim"),
}
_STATUS_MARK_ASCII = {
    "approved": ("[x]", "green"),
    "awaiting_review": ("[!]", "amber"),
    "revision_requested": ("[r]", "amber"),
    "skipped": ("[-]", "dim"),
    "not_ready": ("[ ]", "dim"),
}
_STATUS_MARK = _STATUS_MARK_UNICODE if _UNICODE_OK else _STATUS_MARK_ASCII


def mark(status: str) -> str:
    symbol, colour = _STATUS_MARK.get(status, ("[ ]", "dim"))
    return c(symbol, colour)


def phase_from(name: str) -> Phase:
    try:
        return Phase(name.lower())
    except ValueError:
        options = ", ".join(p.value for p in Phase if p not in (Phase.INTAKE, Phase.DONE))
        raise SuiteError(f"Unknown phase '{name}'.", remedy=f"Use one of: {options}")


# ---------------------------------------------------------------- doctor ---
def cmd_doctor(args) -> int:
    cfg = config.load()
    head(f"{cfg.project_name} v{cfg.version} — readiness check")

    problems: list[str] = []
    warnings: list[str] = []

    # Python + dependencies
    import importlib.util as iu

    print(f"\n  {c('Runtime', 'bold')}")
    kv("Python", sys.version.split()[0])
    required = ["pydantic", "yaml", "jinja2", "docx", "openpyxl", "fastapi", "uvicorn", "httpx", "dotenv"]
    optional = {"chromadb": "vector index", "fastembed": "local embeddings", "rank_bm25": "keyword ranking",
                "anthropic": "Claude API", "pypdf": "PDF ingest"}
    missing = [m for m in required if not iu.find_spec(m)]
    if missing:
        problems.append(f"Missing required packages: {', '.join(missing)}. Run: pip install -r requirements.txt")
        kv("Required packages", c(f"{len(required) - len(missing)}/{len(required)} — missing {', '.join(missing)}", "red"))
    else:
        kv("Required packages", c(f"all {len(required)} present", "green"))
    absent = [m for m in optional if not iu.find_spec(m)]
    if absent:
        warnings.append(f"Optional packages absent: {', '.join(absent)} (degraded: {', '.join(optional[m] for m in absent)})")
        kv("Optional packages", c(f"{len(optional) - len(absent)}/{len(optional)} — absent: {', '.join(absent)}", "amber"))
    else:
        kv("Optional packages", c(f"all {len(optional)} present", "green"))

    # Templates and skills
    print(f"\n  {c('Assets', 'bold')}")
    for key in cfg.templates:
        try:
            path = cfg.template_path(key)
            kv(f"template:{key}", c(path.name, "green"))
        except SuiteError as exc:
            problems.append(exc.message)
            kv(f"template:{key}", c("MISSING", "red"))
    skills = sorted(cfg.skills_dir.glob("*.md"))
    kv("skills", c(f"{len(skills)} file(s)", "green" if skills else "amber"))
    if not skills:
        warnings.append("No skill files found in /skills — agents lose their Maximo reference material.")

    # Model
    print(f"\n  {c('Model', 'bold')}")
    if cfg.llm.available:
        kv("provider", c(cfg.llm.provider, "green"))
        kv("model", cfg.llm.model)
        if cfg.llm.base_url:
            kv("endpoint", cfg.llm.base_url)
        if args.probe:
            from core import llm as _llm
            from core.errors import LLMError

            try:
                reply = _llm.client(cfg).complete("Reply with the single word: ok", "ping", max_tokens=16)
                if reply.ok:
                    kv("live check", c(f"responded ({reply.tokens} tokens)", "green"))
                else:
                    kv("live check", c(reply.reason or "no response", "amber"))
                    warnings.append(f"Model did not respond: {reply.reason}")
            except LLMError as exc:
                kv("live check", c(exc.message[:88], "red"))
                warnings.append(
                    f"Model credentials are rejected: {exc.message} "
                    "Documents will fall back to the deterministic templates."
                )
        else:
            kv("live check", c("skipped - pass --probe to test the credentials", "dim"))
    else:
        kv("provider", c("offline — deterministic templates only", "amber"))
        warnings.append(
            "No model configured. Set ANTHROPIC_API_KEY, or MODEL_URL1 + MODEL_API_KEY1 + MODEL_NAME1, in .env. "
            "The suite runs without one, but documents use the deterministic templates."
        )

    # Maximo
    print(f"\n  {c('Maximo', 'bold')}")
    from maximo.validator import MaximoValidator

    validator = MaximoValidator(cfg)
    source = "synced from your environment" if cfg.maximo.using_live_catalogue else "bundled"
    kv("catalogue", c(f"{validator.catalog.size} object structures ({source})",
                      "green" if validator.catalog.size else "red"))
    if not validator.catalog.size:
        problems.append("The offline Maximo schema catalogue is empty — validation cannot ground field names.")
    if cfg.maximo.configured:
        kv("route", f"/{cfg.maximo.route}/  ->  {cfg.maximo.base_url}")
        if args.probe:
            probe = validator.client.ping(force=True)
            if probe.reachable:
                kv("live check", c(f"connected — {probe.object_structures} object structures", "green"))
            else:
                kv("live check", c(probe.detail[:90], "amber"))
                warnings.append(f"Maximo unreachable: {probe.detail}")
        else:
            kv("live check", c("skipped — pass --probe to test the connection", "dim"))
    else:
        kv("connection", c("not configured — validation uses the bundled catalogue", "amber"))
        warnings.append("MAXIMO_MANAGE_URL / MAXIMO_MANAGE_APIKEY not set. Offline validation only.")

    # Brain
    print(f"\n  {c('AI Brain', 'bold')}")
    from ai_brain import Brain

    brain = Brain.build(cfg)
    stats = brain.store.stats()
    kv("documents", str(stats["documents"]))
    kv("by type", ", ".join(f"{k}={v}" for k, v in stats["by_type"].items()) or "(empty)")
    kv("store", str(cfg.brain.store_dir))
    kv("duplicate threshold", str(cfg.brain.duplicate_threshold))

    # Verdict
    head("Verdict")
    for w in warnings:
        print(f"  {c('warn', 'amber')}  {w}")
    for p in problems:
        print(f"  {c('FAIL', 'red')}  {p}")
    if not problems:
        print(f"\n  {c('READY', 'green')} — the suite can run. "
              f"{'Some capabilities are degraded; see warnings above.' if warnings else ''}\n")
        return 0
    print(f"\n  {c('NOT READY', 'red')} — fix the failures above.\n")
    return 1


# ----------------------------------------------------------------- runs ----
def _pipeline():
    from pipeline import Pipeline

    return Pipeline(config.load())


def cmd_start(args) -> int:
    pipe = _pipeline()
    text = ""
    if args.text:
        text = args.text
    elif args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")

    state = pipe.start(
        title=args.title,
        business_process=args.process or "",
        files=args.file or [],
        text=text,
        notes=args.notes or "",
    )
    head(f"Run created: {state.run_id}")
    kv("title", state.title)
    kv("process", state.business_process)
    kv("requirements", str(len(state.requirements)))
    kv("change items", str(len(state.change_items)))
    intake = state.result(Phase.INTAKE)
    if intake:
        kv("routing", intake.summary)
    print(f"\n  Next: {c(f'python run.py advance {state.run_id}', 'blue')}\n")

    if args.auto:
        return _run_all(pipe, state.run_id, auto=True)
    return 0


def _run_all(pipe, run_id: str, *, auto: bool) -> int:
    for step in pipe.run_all(run_id, auto_approve=auto):
        if step.ran and step.result:
            status = c("ok", "green") if step.result.ok else c("FAILED", "red")
            print(f"  {status}  {PHASE_LABEL[step.phase]} — {step.result.summary}")
            for a in step.result.artifacts:
                print(f"        {c(_ARROW, 'dim')} {a.name} ({a.bytes:,} bytes)")
            if step.result.flags:
                print(f"        {c(f'{len(step.result.flags)} flag(s) for review', 'amber')}")
            if not step.result.ok:
                print(f"        {c((step.result.error or {}).get('message', ''), 'red')}")
                return 1
        else:
            print(f"\n  {step.message}\n")
    return 0


def cmd_advance(args) -> int:
    pipe = _pipeline()
    if args.all:
        return _run_all(pipe, args.run_id, auto=args.auto)
    step = pipe.advance(args.run_id, auto_approve=args.auto)
    if not step.ran:
        print(f"\n  {step.message}\n")
        return 0
    head(f"{PHASE_LABEL[step.phase]}")
    result = step.result
    print(f"  {c('ok', 'green') if result.ok else c('FAILED', 'red')}  {result.summary}")
    for a in result.artifacts:
        print(f"    {c(_ARROW, 'dim')} {a.path}")
    if result.duplicate and result.duplicate.found:
        d = result.duplicate
        print(f"\n  {c('Prior art found', 'amber')}: {d.best.title} v{d.best.version} "
              f"(similarity {d.similarity:.3f} ≥ {d.threshold}) — choose Update or New at the gate.")
    if result.flags:
        print(f"\n  {c(f'{len(result.flags)} item(s) flagged for review:', 'amber')}")
        for f in sorted(result.flags, key=lambda x: x.confidence)[:10]:
            print(f"    [{f.confidence:.2f}] {f.item}: {f.reason[:100]}")
    print(f"\n  {step.message}\n")
    return 0 if result.ok else 1


def cmd_approve(args) -> int:
    pipe = _pipeline()
    phase = phase_from(args.phase)
    pipe.approve(args.run_id, phase, by=args.by or "", comment=args.comment or "",
                 duplicate_action=args.duplicate or "")
    print(f"\n  {c(_OK, 'green')} {PHASE_LABEL[phase]} approved by {args.by or 'unnamed reviewer'}.")
    nxt = pipe.status(args.run_id)["next_phase"]
    print(f"  Next: {c(f'python run.py advance {args.run_id}', 'blue') if nxt else 'run complete'}\n")
    return 0


def cmd_revise(args) -> int:
    pipe = _pipeline()
    phase = phase_from(args.phase)
    pipe.revise(args.run_id, phase, by=args.by or "", comment=args.comment or "")
    print(f"\n  {c(_REDO, 'amber')} {PHASE_LABEL[phase]} sent back for revision.")
    print(f"  Re-run with: {c(f'python run.py advance {args.run_id}', 'blue')}\n")
    return 0


def cmd_status(args) -> int:
    pipe = _pipeline()
    s = pipe.status(args.run_id)
    head(f"{s['title']}  ({s['run_id']})")
    kv("process", s["business_process"])
    kv("updated", s["updated"])
    kv("requirements", str(len(s["requirements"])))
    kv("change items", str(len(s["change_items"])))
    kv("artifacts", str(s["total_artifacts"]))
    kv("flags", str(s["total_flags"]))

    print(f"\n  {c('Pipeline', 'bold')}")
    for p in s["phases"]:
        line = f"   {mark(p['status'])} {p['label']:<32} {c(p['status'], 'dim')}"
        if p["artifacts"]:
            line += c(f"  {len(p['artifacts'])} artifact(s)", "dim")
        if p["flags"]:
            line += c(f"  {len(p['flags'])} flag(s)", "amber")
        print(line)
        if p["summary"]:
            print(f"        {c(p['summary'][:110], 'dim')}")

    if s["awaiting_gate"]:
        phase = s["awaiting_gate"]
        approve_cmd = f'python run.py approve {args.run_id} {phase} --by "Your Name"'
        role = next((p["role"] for p in s["phases"] if p["phase"] == phase), "reviewer")
        print(f"\n  {c('Awaiting review:', 'amber')} {PHASE_LABEL[Phase(phase)]} ({role})")
        print(f"    approve: {c(approve_cmd, 'blue')}")
        print(f"    revise:  {c(f'python run.py revise {args.run_id} {phase} -c \"what to change\"', 'blue')}")
    elif s["finished"]:
        print(f"\n  {c('Run complete.', 'green')}")
    elif s["next_phase"]:
        print(f"\n  Next: {c(f'python run.py advance {args.run_id}', 'blue')}")
    print()
    return 0


def cmd_runs(args) -> int:
    from pipeline import RunStore

    rows = RunStore(config.load()).list()
    if not rows:
        print("\n  No runs yet. Create one with `python run.py start --title \"...\" --file requirements.docx`\n")
        return 0
    head(f"{len(rows)} run(s)")
    print(f"  {'RUN ID':<18} {'PROCESS':<8} {'PHASE':<18} {'ART':>4} {'UPDATED':<22} TITLE")
    for r in rows:
        awaiting = c(f" {_PEND}", "amber") if r["awaiting"] else "  "
        print(f"  {r['run_id']:<18} {r['business_process']:<8} {r['current_phase']:<18} "
              f"{r['artifacts']:>4} {r['updated'][:19]:<22}{awaiting}{r['title'][:40]}")
    print()
    return 0


# ---------------------------------------------------------------- brain ----
def cmd_brain(args) -> int:
    from ai_brain import Brain, SearchQuery

    cfg = config.load()
    brain = Brain.build(cfg)

    if args.brain_action == "search":
        outcome = brain.search.search(
            SearchQuery(text=args.query, doc_type=args.type, business_process=args.process, top_k=args.top)
        )
        head(f"AI Brain — {len(outcome.hits)} hit(s)   [stopped at: {outcome.stopped_at}]")
        if outcome.note:
            print(f"  {c(outcome.note, 'dim')}")
        for h in outcome.hits:
            semantic = outcome.semantic_for(h.doc_id)
            print(f"\n  {c(h.title, 'bold')}  {c(f'[{h.doc_type} v{h.version}]', 'dim')}")
            print(f"    rank {h.score:.3f} | cosine {semantic:.3f} | matched by {h.matched_by}")
            print(f"    {c(h.excerpt[:220].replace(chr(10), ' '), 'grey')}")
        print()
        return 0

    if args.brain_action == "stats":
        status = brain.status()
        head("AI Brain")
        for k, v in status.items():
            kv(k, str(v))
        print()
        return 0

    if args.brain_action == "audit":
        head("AI Brain write audit (newest first)")
        for rec in brain.store.audit_tail(args.top):
            print(f"  {rec.get('timestamp', '')[:19]}  {rec.get('action', ''):<7} "
                  f"{rec.get('doc_id', '')} v{rec.get('version', '')}  by {rec.get('agent', '?')}")
        print()
        return 0
    return 1


def cmd_index(args) -> int:
    from ai_brain import Brain

    cfg = config.load()
    brain = Brain.build(cfg)
    head("Indexing the AI Brain")
    stats = brain.search.reindex(rebuild=args.rebuild)
    for k, v in stats.items():
        kv(k, str(v))
    kv("backend", brain.index.backend)
    kv("embeddings", brain.index.embedder.backend)
    print()
    return 0


# -------------------------------------------------------------- ibmdocs ----
def cmd_ibmdocs(args) -> int:
    from core import ibm_docs, config as cfg_mod

    cfg = cfg_mod.load()

    if args.ibmdocs_action == "sync":
        head("IBM Knowledge Centre — syncing documentation cache")
        delay = float(getattr(cfg, "ibm_docs_fetch_delay_seconds", 1.5))
        stats = ibm_docs.sync(cfg.skills_dir, delay_seconds=delay)
        kv("fetched (web)", str(stats["fetched_web"]))
        kv("fetched (fallback)", str(stats["fetched_fallback"]))
        kv("failed", str(stats["failed"]))
        kv("cache", str(cfg.skills_dir / ibm_docs._CACHE_FILENAME))
        print()
        return 0 if stats["failed"] == 0 else 1

    if args.ibmdocs_action == "list":
        head("IBM Knowledge Centre — configured pages")
        for label, url in ibm_docs.IBM_DOC_PAGES:
            kv(label, url)
        cache = cfg.skills_dir / ibm_docs._CACHE_FILENAME
        print()
        kv("cache file", str(cache))
        kv("cache exists", "yes" if cache.exists() else "no — run: python run.py ibmdocs sync")
        if cache.exists():
            kv("cache size", f"{cache.stat().st_size:,} bytes")
        print()
        return 0

    return 1


# --------------------------------------------------------------- maximo ----
def cmd_maximo(args) -> int:
    cfg = config.load()
    from maximo.validator import MaximoValidator

    v = MaximoValidator(cfg)

    if args.maximo_action == "check":
        head(f"Validating '{args.name}'")
        if "." in args.name:
            obj, attr = args.name.split(".", 1)
            results = [v.object(obj), v.attribute(obj, attr)]
        else:
            results = [v.object(args.name)]
            info = v.catalog.for_object(args.name)
            if info:
                kv("object structure", info.os_name)
                kv("primary keys", ", ".join(k.upper() for k in info.primary_keys))
                kv("attributes", str(len(info.attributes)))
        for r in results:
            symbol = c(_OK, "green") if r.exists else c(_BAD, "red")
            print(f"  {symbol} {r.kind}: {r.name}  [{r.source}]")
            print(f"      {r.detail}")
            if r.suggestions:
                print(f"      {c('suggestions: ' + ', '.join(r.suggestions), 'amber')}")
        print()
        return 0 if all(r.exists for r in results) else 1

    if args.maximo_action == "search":
        hits = v.catalog.search(args.name, limit=args.top)
        head(f"{len(hits)} object structure(s) matching '{args.name}'")
        for h in hits:
            print(f"  {h.os_name:<28} {h.mbo:<22} {len(h.attributes):>4} fields  {h.description[:40]}")
        print()
        return 0

    if args.maximo_action == "sync":
        head("Mirroring live object-structure schemas")
        if not cfg.maximo.configured:
            raise SuiteError(
                "Maximo is not configured.",
                remedy="Set MAXIMO_MANAGE_URL and MAXIMO_MANAGE_APIKEY in .env.",
            )
        target = cfg.maximo.live_schema_dir
        kv("source", cfg.maximo.base_url)
        kv("target", str(target))
        print()

        def show(done: int, total: int) -> None:
            pct = int(done * 100 / total)
            bar = "#" * (pct // 3)
            print(f"\r  [{bar:<33}] {done}/{total}", end="", flush=True)

        stats = v.client.sync_schemas(target, progress=show)
        print()
        kv("object structures", str(stats["total"]))
        kv("written", c(str(stats["written"]), "green"))
        if stats["unreadable"]:
            kv("unreadable", c(f"{stats['unreadable']} (security-group restricted)", "amber"))
        print(f"\n  {c('Done.', 'green')} Validation now uses your environment's real schemas.\n")
        return 0

    if args.maximo_action == "ping":
        probe = v.client.ping(force=True)
        head("Maximo connection")
        for k, val in probe.as_dict().items():
            kv(k, str(val))
        print()
        return 0 if probe.reachable else 1

    if args.maximo_action == "discover":
        head("Discovering Maximo environment → knowledge/client/")
        if not cfg.maximo.configured:
            raise SuiteError(
                "Maximo is not configured.",
                remedy="Set MAXIMO_MANAGE_URL and MAXIMO_MANAGE_APIKEY in .env, then retry.",
            )
        probe = v.client.ping(force=True)
        if not probe.reachable:
            raise SuiteError(
                f"Cannot reach Maximo: {probe.detail}",
                remedy="Fix the connection first with `python run.py maximo ping`.",
            )
        kv("source", cfg.maximo.base_url)
        from maximo.discover import run_discover
        knowledge_dir = cfg.skills_dir.parent / "knowledge" / "client"
        kv("writing to", str(knowledge_dir))
        print()
        stats = run_discover(v.client, v.catalog, knowledge_dir)
        kv("organisations",   c(str(stats["orgs"]), "green"))
        kv("sites",           c(str(stats["sites"]), "green"))
        kv("security groups", c(str(stats["security_groups"]), "green"))
        kv("domains",         c(str(stats["domains"]), "green"))
        kv("custom objects",  c(str(stats["custom_objects"]), "green"))
        kv("custom attributes found", c(str(stats["total_custom_attrs"]), "green"))
        print()
        for fname in stats["files"]:
            print(f"  {c('✓', 'green')} knowledge/client/{fname}")
        print(f"\n  {c('Done.', 'green')} All agents will now use this data automatically.\n")
        return 0

    return 1


# ------------------------------------------------------------------ ui -----
def cmd_ui(args) -> int:
    import uvicorn

    cfg = config.load()
    host = args.host or cfg.ui_host
    port = args.port or cfg.ui_port
    head(f"{cfg.project_name}")
    kv("URL", c(f"http://{host}:{port}", "blue"))
    kv("model", cfg.llm.model if cfg.llm.available else "offline (deterministic)")
    kv("maximo", cfg.maximo.base_url or "offline catalogue")
    print(f"\n  {c('Ctrl+C to stop', 'dim')}\n")
    uvicorn.run("ui.server:app", host=host, port=port, reload=args.reload, log_level="warning")
    return 0


# ----------------------------------------------------------------- demo ----
def cmd_prompt_export(args) -> int:
    """Export the full agent prompt for a phase to a .txt file."""
    pipe = _pipeline()
    phase = phase_from(args.phase)
    out_path = pipe.export_prompt(args.run_id, phase)
    head(f"Prompt exported — {PHASE_LABEL[phase]}")
    kv("file", str(out_path))
    print(f"""
  HOW TO USE (Claude Code bridge):
  1. Open the exported file above in any text editor.
  2. In Claude Code, start a NEW conversation.
  3. Paste everything under "SYSTEM PROMPT" first (as a user message asking
     Claude to act as that agent), then paste the "USER PROMPT" block.
  4. Copy Claude's entire response.
  5. Save the response to a .txt file, e.g. response_fdd.txt
  6. Run:
       {c(f'python run.py prompt-inject {args.run_id} {args.phase} --response-file response_{args.phase}.txt', 'blue')}
""")
    return 0


def cmd_prompt_inject(args) -> int:
    """Inject a Claude Code response back into the pipeline as a phase result."""
    pipe = _pipeline()
    phase = phase_from(args.phase)
    response_path = Path(args.response_file)
    if not response_path.exists():
        print(f"\n  {c('error', 'red')}  Response file not found: {response_path}\n")
        return 1
    response_text = response_path.read_text(encoding="utf-8")
    if not response_text.strip():
        print(f"\n  {c('error', 'red')}  Response file is empty.\n")
        return 1

    step = pipe.inject_response(args.run_id, phase, response_text)
    head(f"{PHASE_LABEL[phase]} — response injected")
    result = step.result
    print(f"  {c('ok', 'green')}  {result.summary}")
    for a in result.artifacts:
        print(f"    {c(_ARROW, 'dim')} {a.path}")
    if result.flags:
        print(f"\n  {c(f'{len(result.flags)} flag(s) for review:', 'amber')}")
        for f in sorted(result.flags, key=lambda x: x.confidence)[:10]:
            print(f"    [{f.confidence:.2f}] {f.item}: {f.reason[:100]}")
    print(f"\n  {step.message}")
    print(f"\n  Approve: {c(f'python run.py approve {args.run_id} {args.phase} --by \"Your Name\"', 'blue')}")
    print(f"  Revise:  {c(f'python run.py revise {args.run_id} {args.phase} -c \"what to change\"', 'blue')}\n")
    return 0


def cmd_demo(args) -> int:
    """Both blueprint reference use cases, end to end, unattended."""
    from demo_data import USE_CASES

    pipe = _pipeline()
    head("Demonstration — blueprint reference use cases")
    failures = 0
    for name, payload in USE_CASES.items():
        print(f"\n{c(_PLAY + ' ' + payload['title'], 'bold')}")
        state = pipe.start(title=payload["title"], business_process="CU", text=payload["text"])
        print(f"  run {state.run_id}: {len(state.change_items)} change item(s)")
        if _run_all(pipe, state.run_id, auto=True) != 0:
            failures += 1
            continue
        s = pipe.status(state.run_id)
        print(f"  {c('complete', 'green')}: {s['total_artifacts']} artifact(s), {s['total_flags']} flag(s)")
        print(f"  artifacts in {c(str(pipe.store.run_dir(state.run_id)), 'dim')}")
    print()
    return 1 if failures else 0


# ----------------------------------------------------------------- main ----
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="Maximo Delivery AI Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--log-level", default="", help="DEBUG, INFO, WARNING, ERROR")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check the install, credentials and assets")
    d.add_argument("--probe", action="store_true", help="also test the live Maximo connection")
    d.set_defaults(func=cmd_doctor)

    u = sub.add_parser("ui", help="start the web control surface")
    u.add_argument("--host", default="")
    u.add_argument("--port", type=int, default=0)
    u.add_argument("--reload", action="store_true")
    u.set_defaults(func=cmd_ui)

    s = sub.add_parser("start", help="create a run from requirement material")
    s.add_argument("--title", required=True)
    s.add_argument("--process", default="", help="CU, WO, ... (default: auto-detect)")
    s.add_argument("--file", action="append", help="input file (repeatable)")
    s.add_argument("--text", default="", help="paste requirement text directly")
    s.add_argument("--text-file", default="", help="read requirement text from a file")
    s.add_argument("--notes", default="")
    s.add_argument("--auto", action="store_true", help="run every phase, auto-approving gates")
    s.set_defaults(func=cmd_start)

    a = sub.add_parser("advance", help="run the next phase")
    a.add_argument("run_id")
    a.add_argument("--all", action="store_true", help="keep going until a gate blocks")
    a.add_argument("--auto", action="store_true", help="auto-approve gates (unattended)")
    a.set_defaults(func=cmd_advance)

    ap = sub.add_parser("approve", help="approve a gate")
    ap.add_argument("run_id")
    ap.add_argument("phase")
    ap.add_argument("--by", default="")
    ap.add_argument("--comment", "-c", default="")
    ap.add_argument("--duplicate", choices=["update", "new"], default="",
                    help="when prior art was found: update it or create new")
    ap.set_defaults(func=cmd_approve)

    rv = sub.add_parser("revise", help="send a phase back for revision")
    rv.add_argument("run_id")
    rv.add_argument("phase")
    rv.add_argument("--by", default="")
    rv.add_argument("--comment", "-c", default="")
    rv.set_defaults(func=cmd_revise)

    st = sub.add_parser("status", help="show a run")
    st.add_argument("run_id")
    st.set_defaults(func=cmd_status)

    sub.add_parser("runs", help="list runs").set_defaults(func=cmd_runs)

    b = sub.add_parser("brain", help="query the AI Brain")
    bsub = b.add_subparsers(dest="brain_action", required=True)
    bs = bsub.add_parser("search")
    bs.add_argument("query")
    bs.add_argument("--type", default=None)
    bs.add_argument("--process", default=None)
    bs.add_argument("--top", type=int, default=5)
    bsub.add_parser("stats")
    ba = bsub.add_parser("audit")
    ba.add_argument("--top", type=int, default=20)
    b.set_defaults(func=cmd_brain)

    ix = sub.add_parser("index", help="(re)build the vector index")
    ix.add_argument("--rebuild", action="store_true")
    ix.set_defaults(func=cmd_index)

    m = sub.add_parser("maximo", help="validate Maximo names / test the connection")
    msub = m.add_subparsers(dest="maximo_action", required=True)
    mc = msub.add_parser("check")
    mc.add_argument("name", help="OBJECT or OBJECT.ATTRIBUTE")
    ms = msub.add_parser("search")
    ms.add_argument("name")
    ms.add_argument("--top", type=int, default=15)
    msub.add_parser("ping")
    msub.add_parser("sync", help="mirror live schemas locally for exact validation")
    msub.add_parser(
        "discover",
        help="query live Maximo and auto-generate knowledge/client/ skill files (sites, orgs, security groups, custom objects)",
    )
    m.set_defaults(func=cmd_maximo)

    sub.add_parser("demo", help="run both blueprint use cases end to end").set_defaults(func=cmd_demo)

    id_ = sub.add_parser("ibmdocs", help="sync IBM Maximo Knowledge Centre documentation into the skills cache")
    idsub = id_.add_subparsers(dest="ibmdocs_action", required=True)
    idsub.add_parser("sync", help="fetch / refresh IBM docs cache (run periodically or after install)")
    idsub.add_parser("list", help="list configured IBM documentation pages")
    id_.set_defaults(func=cmd_ibmdocs)

    pe = sub.add_parser("prompt-export", help="export the agent prompt for a phase (Claude Code bridge)")
    pe.add_argument("run_id")
    pe.add_argument("phase", help="fdd, tdd, build_config, build_integration, test, deploy")
    pe.set_defaults(func=cmd_prompt_export)

    pi = sub.add_parser("prompt-inject", help="inject a Claude Code response back as a phase result")
    pi.add_argument("run_id")
    pi.add_argument("phase", help="fdd, tdd, build_config, build_integration, test, deploy")
    pi.add_argument("--response-file", required=True, help="path to .txt file containing the Claude response")
    pi.set_defaults(func=cmd_prompt_inject)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup(args.log_level or "INFO")
    try:
        return args.func(args)
    except SuiteError as exc:
        print(f"\n  {c('error', 'red')}  {exc.message}")
        print(f"  {c('fix', 'dim')}    {exc.remedy}\n")
        return 1
    except KeyboardInterrupt:
        print("\n  interrupted\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
