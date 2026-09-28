"""Shared agent scaffold.

Every specialist agent inherits the same lifecycle, which is exactly the one
the blueprint prescribes:

    search AI Brain  ->  validate against Maximo  ->  generate  ->  flag  ->  gate

Each agent supplies:
  * identity (agent_id, name, phase, doc_type)
  * `gather()`  - collect facts and validate Maximo names
  * `compose()` - build the document body (model-driven, with a deterministic
                  fallback so the suite still works with no model configured)
  * `emit()`    - write artifacts to the run directory

`BaseAgent.run()` wires those together and returns a PhaseResult.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_brain import Brain
from core.config import SuiteConfig
from core.errors import LLMError, SuiteError
from core.llm import LLMClient
from core.logging import get
from core.models import (
    Artifact,
    ChangeItem,
    DuplicateDecision,
    Flag,
    Phase,
    PhaseResult,
    RunState,
)
from maximo.validator import MaximoValidator, ValidationReport

log = get("suite.agent")

#: The FLAG line contract given to the model in the system prompt.
_FLAG_RE = re.compile(r"^\s*FLAG:\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*([01](?:\.\d+)?)\s*$", re.M)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AgentContext:
    """Everything an agent is allowed to touch."""

    cfg: SuiteConfig
    brain: Brain
    validator: MaximoValidator
    llm: LLMClient
    state: RunState
    process: dict[str, Any]
    workdir: Path
    #: text of every ingested input, prepared by the orchestrator
    source_material: str = ""
    #: set True by `demo` / `pipeline --auto` to skip interactive gates
    auto_approve: bool = False

    @property
    def process_name(self) -> str:
        return str(self.process.get("name", self.state.business_process)).upper()

    def artifact_dir(self, sub: str) -> Path:
        d = self.workdir / sub
        d.mkdir(parents=True, exist_ok=True)
        return d


@dataclass
class Composition:
    """What `compose()` returns."""

    body: str
    summary: str = ""
    flags: list[Flag] = field(default_factory=list)
    generated_by: str = "deterministic"
    handover: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    # -- identity (overridden) --------------------------------------------
    agent_id: str = "0"
    name: str = "Agent"
    phase: Phase = Phase.INTAKE
    doc_type: str = "doc"
    role: str = ""
    inputs_description: str = ""
    output_format: str = ""
    #: skill files loaded into the system prompt
    skill_files: tuple[str, ...] = ()

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self.log = get(f"suite.agent.{self.agent_id.lower()}")
        self.report = ValidationReport()
        #: populated by run() so compose() and emit() share one gather() pass
        self.facts: dict[str, Any] = {}
        #: set when the model was configured but could not be reached
        self._model_error: str = ""

    # -- lifecycle ---------------------------------------------------------
    def run(self) -> PhaseResult:
        result = PhaseResult(phase=self.phase, agent=f"Agent {self.agent_id} - {self.name}")
        try:
            self.log.info("start: %s", self.name)

            duplicate = self.check_duplicate()
            result.duplicate = duplicate
            if duplicate.found:
                self.log.info(
                    "prior art found: %s (similarity %.3f) - user will choose Update or New",
                    duplicate.best.title if duplicate.best else "?",
                    duplicate.similarity,
                )

            self.facts = self.gather()
            composition = self.compose(self.facts, duplicate)

            result.flags = list(composition.flags) + self.report.to_flags(self.name)
            result.validations = list(self.report.results)
            result.handover = composition.handover
            result.artifacts = self.emit(composition)
            result.summary = composition.summary or self.report.summary()
            result.ok = True
            self.log.info(
                "done: %d artifact(s), %d flag(s), %s",
                len(result.artifacts), len(result.flags), self.report.summary(),
            )
        except SuiteError as exc:
            result.ok = False
            result.error = exc.as_dict()
            self.log.error("%s failed: %s", self.name, exc.message)
        except Exception as exc:  # never let one agent kill the process
            result.ok = False
            result.error = {"code": "UNEXPECTED", "message": str(exc), "remedy": "See the run log."}
            self.log.exception("%s crashed", self.name)
        result.finished = _now()
        return result

    # -- steps agents override --------------------------------------------
    @abstractmethod
    def gather(self) -> dict[str, Any]:
        """Collect and validate the facts this document needs."""

    @abstractmethod
    def compose(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> Composition:
        """Produce the document body."""

    @abstractmethod
    def emit(self, composition: Composition) -> list[Artifact]:
        """Write files and return the artifact records."""

    # -- shared helpers ----------------------------------------------------
    def duplicate_query(self) -> str:
        """Text used for the search-before-create check."""
        return f"{self.ctx.state.title}\n" + "\n".join(
            f"{r.title}: {r.text[:200]}" for r in self.ctx.state.requirements[:8]
        )

    def check_duplicate(self) -> DuplicateDecision:
        return self.ctx.brain.search.find_duplicate(
            text=self.duplicate_query(),
            doc_type=self.doc_type,
            business_process=self.ctx.process_name,
        )

    def prior_art(self, limit: int = 3) -> str:
        """Brain excerpts injected into the prompt."""
        from ai_brain import SearchQuery

        outcome = self.ctx.brain.search.search(
            SearchQuery(text=self.duplicate_query(), business_process=self.ctx.process_name, top_k=limit)
        )
        if not outcome.hits:
            return "(no prior art in the AI Brain)"
        blocks = []
        for hit in outcome.hits[:limit]:
            blocks.append(
                f"- {hit.title} [{hit.doc_type} v{hit.version}, relevance {hit.score:.2f}]\n  {hit.excerpt[:300]}"
            )
        return "\n".join(blocks)

    def load_skills(self) -> str:
        """Concatenate the skill files this agent declares, plus auto-learned corrections."""
        parts = []
        for filename in (self.skill_files or []):
            path = self.ctx.cfg.skills_dir / filename
            if not path.exists():
                self.log.debug("skill file missing: %s", filename)
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Keep prompts affordable; the head of each skill carries the rules.
            parts.append(f"--- {filename} ---\n{text[:6000]}")

        # Auto-learned corrections: past reviewer feedback for this doc_type
        corrections = self.ctx.brain.feedback.corrections_skill(self.doc_type)
        if corrections:
            # Include the 10 most recent corrections (tail of file, ~3000 chars)
            parts.append(
                f"--- corrections_{self.doc_type}.md (auto-learned from reviewer feedback) ---\n"
                f"{corrections[-3000:]}"
            )
        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(
            loader=FileSystemLoader(str(self.ctx.cfg.prompts_dir)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        process = self.ctx.process
        objects = process.get("objects", {}) or {}
        statuses = process.get("statuses", {}) or {}

        return env.get_template("agent_system.md.j2").render(
            agent_name=f"Agent {self.agent_id} - {self.name}",
            project_name=self.ctx.cfg.project_name,
            role=self.role,
            maximo_version=self.ctx.cfg.maximo_version,
            process_name=self.ctx.process_name,
            process_label=process.get("label", self.ctx.process_name),
            domain=self.ctx.cfg.domain,
            validation_source=(
                "live Maximo environment" if self.ctx.validator.live else "bundled Maximo schema catalogue (offline)"
            ),
            confidence_threshold=self.ctx.cfg.confidence_threshold,
            process_objects=", ".join(
                [*(objects.get("primary") or []), *(objects.get("related") or [])]
            ),
            process_statuses="; ".join(f"{k.upper()}: {', '.join(v)}" for k, v in statuses.items()),
            inputs_description=self.inputs_description,
            output_format=self.output_format,
            skills=self.load_skills(),
        )

    def validated_facts_block(self) -> str:
        """The whitelist of Maximo names the model is permitted to use."""
        confirmed = [r for r in self.report.results if r.exists]
        rejected = [r for r in self.report.results if not r.exists]
        lines = []
        if confirmed:
            lines.append("CONFIRMED (safe to use):")
            for r in confirmed:
                lines.append(f"  - {r.kind}: {r.name} - {r.detail}")
        if rejected:
            lines.append("NOT CONFIRMED (must be flagged, never stated as fact):")
            for r in rejected:
                hint = f" Suggestions: {', '.join(r.suggestions[:3])}." if r.suggestions else ""
                lines.append(f"  - {r.kind}: {r.name} - {r.detail}{hint}")
        return "\n".join(lines) or "(no Maximo names required validation)"

    def ask_model(self, user_prompt: str, *, max_tokens: int | None = None) -> tuple[str, str]:
        """Call the model. Returns (text, generated_by). Empty text => fall back.

        A model failure - bad key, rate limit, endpoint down - must never fail
        the run. The deterministic path produces the same document structure,
        so we log the reason loudly and carry on.
        """
        if not self.ctx.llm.available:
            return "", "deterministic"
        try:
            reply = self.ctx.llm.complete(self.system_prompt(), user_prompt, max_tokens=max_tokens)
        except LLMError as exc:
            self.log.warning(
                "model unavailable (%s) - falling back to the deterministic template. "
                "Check credentials with `python run.py doctor --probe`.",
                exc.message,
            )
            self._model_error = exc.message
            return "", "deterministic"
        if not reply.ok or not reply.text.strip():
            return "", "deterministic"
        self.log.info("model produced %d chars (%s/%s)", len(reply.text), reply.provider, reply.model)
        return reply.text, f"{reply.provider}:{reply.model}"

    def parse_flags(self, text: str, default_section: str) -> tuple[str, list[Flag]]:
        """Pull FLAG: lines out of model output into structured flags."""
        flags: list[Flag] = []
        for section, item, reason, score in _FLAG_RE.findall(text):
            confidence = max(0.0, min(1.0, float(score)))
            flags.append(
                Flag(
                    section=section or default_section,
                    item=item,
                    reason=reason,
                    confidence=confidence,
                    severity="block" if confidence < 0.4 else "warn",
                )
            )
        return _FLAG_RE.sub("", text).strip(), flags

    def change_items(self) -> list[ChangeItem]:
        return self.ctx.state.change_items

    def brain_body(self, composition: Composition) -> str:
        """Markdown stored in the AI Brain for this phase."""
        return composition.body

    def register_artifact(
        self,
        path: Path,
        *,
        kind: str,
        description: str = "",
    ) -> Artifact:
        return Artifact(
            name=path.name,
            kind=kind,  # type: ignore[arg-type]
            path=str(path),
            agent=f"Agent {self.agent_id}",
            phase=self.phase.value,
            bytes=path.stat().st_size if path.exists() else 0,
            description=description,
        )
