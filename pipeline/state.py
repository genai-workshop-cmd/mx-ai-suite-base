"""Run persistence.

One directory per run under `runs/<run_id>/`:

    state.json        the RunState
    run.log           this run's log
    inputs/           copies of every uploaded file
    01_fdd/ ...       artifacts per phase

State is written after every phase and every gate decision, so the UI can be
closed and reopened mid-run without losing anything.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.config import SuiteConfig
from core.errors import SuiteError
from core.logging import get
from core.models import RunState

log = get("suite.pipeline.state")


class RunStore:
    """Create, load, list and save runs."""

    def __init__(self, cfg: SuiteConfig) -> None:
        self.cfg = cfg
        self.root = cfg.runs_dir
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state.json"

    def log_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.log"

    # -- lifecycle ---------------------------------------------------------
    def create(self, title: str, business_process: str, notes: str = "") -> RunState:
        state = RunState(title=title or "Untitled run", business_process=business_process.upper(), notes=notes)
        d = self.run_dir(state.run_id)
        (d / "inputs").mkdir(parents=True, exist_ok=True)
        self.save(state)
        log.info("created run %s (%s)", state.run_id, state.title)
        return state

    def save(self, state: RunState) -> Path:
        state.touch()
        path = self.state_path(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file so a crash cannot leave a truncated state.json.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def load(self, run_id: str) -> RunState:
        path = self.state_path(run_id)
        if not path.exists():
            raise SuiteError(f"Run '{run_id}' not found.", remedy="List runs with `python run.py runs`.")
        try:
            return RunState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SuiteError(f"Run '{run_id}' has an unreadable state file: {exc}") from exc

    def exists(self, run_id: str) -> bool:
        return self.state_path(run_id).exists()

    def list(self, limit: int = 50) -> list[dict]:
        """Newest first, cheap enough for the UI to poll."""
        out: list[dict] = []
        for d in self.root.iterdir():
            if not d.is_dir() or d.name.startswith("_"):
                continue
            path = d / "state.json"
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            gates = raw.get("gates", {}) or {}
            out.append(
                {
                    "run_id": raw.get("run_id", d.name),
                    "title": raw.get("title", d.name),
                    "business_process": raw.get("business_process", ""),
                    "current_phase": raw.get("current_phase", ""),
                    "created": raw.get("created", ""),
                    "updated": raw.get("updated", ""),
                    "artifacts": sum(len(r.get("artifacts", [])) for r in (raw.get("results", {}) or {}).values()),
                    "awaiting": [p for p, g in gates.items() if g.get("status") == "awaiting_review"],
                    "approved": sum(1 for g in gates.values() if g.get("status") == "approved"),
                }
            )
        out.sort(key=lambda r: r.get("updated", ""), reverse=True)
        return out[:limit]

    def delete(self, run_id: str) -> None:
        d = self.run_dir(run_id)
        if d.exists():
            shutil.rmtree(d)
            log.info("deleted run %s", run_id)

    # -- inputs ------------------------------------------------------------
    def add_input_file(self, run_id: str, source: Path) -> Path:
        """Copy an uploaded file into the run so the run is self-contained."""
        dest_dir = self.run_dir(run_id) / "inputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source.name
        if dest.exists():
            stamp = datetime.now(timezone.utc).strftime("%H%M%S")
            dest = dest_dir / f"{source.stem}_{stamp}{source.suffix}"
        shutil.copyfile(source, dest)
        return dest

    def add_input_text(self, run_id: str, text: str, name: str = "pasted_requirements.md") -> Path:
        dest_dir = self.run_dir(run_id) / "inputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        dest.write_text(text, encoding="utf-8")
        return dest

    def inputs(self, run_id: str) -> list[Path]:
        d = self.run_dir(run_id) / "inputs"
        return sorted(p for p in d.iterdir() if p.is_file()) if d.exists() else []
