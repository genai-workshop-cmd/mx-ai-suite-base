"""The phase machine (blueprint section 5).

Enforces the rule that makes this a delivery tool rather than a document
generator: **no agent triggers the next phase without explicit human approval
of the previous one.**

    advance()  runs the next phase, then stops at its gate
    approve()  records the decision, writes the artifact into the AI Brain,
               and makes the next phase runnable
    revise()   sends a phase back with reviewer comments

`auto_approve` exists for `demo` and `pipeline --auto`; it records a decision of
"auto (unattended run)" so an unattended run is never mistaken for a reviewed one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import AGENTS, AgentContext, Orchestrator
from ai_brain import Brain
from core import llm
from core.config import SuiteConfig
from core.errors import GateError, SuiteError
from core.logging import get, setup
from core.models import (
    PHASE_GATE_ROLE,
    PHASE_LABEL,
    GateStatus,
    Phase,
    PhaseResult,
    RunState,
)
from ingest.extract import Document, bundle, extract_file
from maximo.validator import MaximoValidator

from .state import RunStore

log = get("suite.pipeline")

#: Phases that produce a document and therefore have a gate.
GATED_PHASES = [
    Phase.FDD,
    Phase.TDD,
    Phase.BUILD_CONFIG,
    Phase.BUILD_INTEGRATION,
    Phase.TEST,
    Phase.DEPLOY,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AdvanceResult:
    ran: bool
    phase: Phase | None = None
    result: PhaseResult | None = None
    blocked_by: str = ""
    message: str = ""
    finished: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "phase": self.phase.value if self.phase else None,
            "phase_label": PHASE_LABEL.get(self.phase, "") if self.phase else "",
            "ok": self.result.ok if self.result else None,
            "summary": self.result.summary if self.result else "",
            "artifacts": [a.model_dump() for a in self.result.artifacts] if self.result else [],
            "flags": [f.model_dump() for f in self.result.flags] if self.result else [],
            "blocked_by": self.blocked_by,
            "message": self.message,
            "finished": self.finished,
        }


class Pipeline:
    """Owns one run from intake to deployment."""

    def __init__(self, cfg: SuiteConfig, store: RunStore | None = None) -> None:
        self.cfg = cfg
        self.store = store or RunStore(cfg)
        self.brain = Brain.build(cfg)
        self.validator = MaximoValidator(cfg)
        self.llm = llm.client(cfg)

    # -- intake ------------------------------------------------------------
    def start(
        self,
        *,
        title: str,
        business_process: str = "",
        files: list[str | Path] | None = None,
        text: str = "",
        notes: str = "",
    ) -> RunState:
        """Create a run, ingest the material and route it."""
        process = (business_process or self.cfg.default_process).upper()
        state = self.store.create(title=title, business_process=process, notes=notes)
        setup(self.cfg.log_level, self.store.log_path(state.run_id))

        for f in files or []:
            source = Path(f)
            if not source.exists():
                log.warning("input not found, skipped: %s", source)
                continue
            state.inputs.append(str(self.store.add_input_file(state.run_id, source)))
        if text.strip():
            state.inputs.append(str(self.store.add_input_text(state.run_id, text)))

        if not state.inputs:
            raise SuiteError(
                "No readable input material was provided.",
                remedy="Attach at least one file or paste requirement text.",
            )

        docs = self._ingest(state)
        ctx = self._context(state, docs)
        decision = Orchestrator(ctx).route(docs)

        state.business_process = decision.business_process
        state.requirements = decision.requirements
        state.change_items = decision.change_items
        state.skipped_phases = decision.skipped

        for phase in GATED_PHASES:
            gate = state.gate(phase)
            gate.role = PHASE_GATE_ROLE.get(phase, "Reviewer")
            if phase in decision.skipped:
                gate.status = GateStatus.SKIPPED
                gate.comment = "Not applicable to this run - no change items routed to this agent."

        intake = PhaseResult(
            phase=Phase.INTAKE,
            agent="Orchestration Agent",
            ok=True,
            finished=_now(),
            summary=decision.rationale,
            handover={
                "classified_by": decision.classified_by,
                "phases": [p.value for p in decision.phases],
                "skipped": [p.value for p in decision.skipped],
                "inputs": [d.as_dict() for d in docs],
            },
        )
        state.results[Phase.INTAKE.value] = intake
        state.current_phase = Phase.FDD
        self.store.save(state)
        log.info("run %s ready: %s", state.run_id, decision.rationale)
        return state

    # -- execution ---------------------------------------------------------
    def advance(self, run_id: str, *, auto_approve: bool = False) -> AdvanceResult:
        """Run the next runnable phase, then stop at its gate."""
        state = self.store.load(run_id)
        setup(self.cfg.log_level, self.store.log_path(run_id))

        phase = self.next_phase(state)
        if phase is None:
            blocking = self._blocking_gate(state)
            if blocking is not None:
                return AdvanceResult(
                    ran=False,
                    phase=blocking,
                    blocked_by=blocking.value,
                    message=(
                        f"{PHASE_LABEL[blocking]} is awaiting review by the "
                        f"{state.gate(blocking).role}. Approve it to continue."
                    ),
                )
            return AdvanceResult(ran=False, finished=True, message="Run complete. All phases approved.")

        agent_cls = AGENTS.get(phase)
        if agent_cls is None:
            raise SuiteError(f"No agent is registered for phase '{phase.value}'.")

        docs = self._ingest(state)
        ctx = self._context(state, docs, auto_approve=auto_approve)
        state.current_phase = phase

        log.info("--- %s ---", PHASE_LABEL[phase])
        agent = agent_cls(ctx)
        result = agent.run()
        state.results[phase.value] = result

        gate = state.gate(phase)
        if result.ok:
            gate.status = GateStatus.AWAITING_REVIEW
            message = (
                f"{PHASE_LABEL[phase]} complete. {len(result.artifacts)} artifact(s), "
                f"{len(result.flags)} flag(s). Awaiting {gate.role} approval."
            )
        else:
            gate.status = GateStatus.NOT_READY
            message = f"{PHASE_LABEL[phase]} failed: {(result.error or {}).get('message', 'unknown error')}"

        self.store.save(state)

        if auto_approve and result.ok:
            self.approve(run_id, phase, by="auto (unattended run)", comment="Auto-approved by --auto")
            message += " Auto-approved."

        return AdvanceResult(ran=True, phase=phase, result=result, message=message)

    def run_all(self, run_id: str, *, auto_approve: bool = False, max_phases: int = 12) -> list[AdvanceResult]:
        """Advance repeatedly. Without auto_approve this stops at the first gate."""
        out: list[AdvanceResult] = []
        for _ in range(max_phases):
            step = self.advance(run_id, auto_approve=auto_approve)
            out.append(step)
            if not step.ran or step.finished:
                break
            if step.result and not step.result.ok:
                break
        return out

    # -- gates -------------------------------------------------------------
    def approve(
        self,
        run_id: str,
        phase: Phase,
        *,
        by: str = "",
        comment: str = "",
        duplicate_action: str = "",
    ) -> RunState:
        """Record approval and write the artifact into the AI Brain."""
        state = self.store.load(run_id)
        result = state.result(phase)
        if result is None or not result.ok:
            raise GateError(f"{PHASE_LABEL[phase]} has not produced an approvable result.")

        gate = state.gate(phase)
        gate.status = GateStatus.APPROVED
        gate.decided_by = by or "unnamed reviewer"
        gate.decided_at = _now()
        gate.comment = comment

        if duplicate_action and result.duplicate:
            result.duplicate.action = duplicate_action  # type: ignore[assignment]

        self._write_to_brain(state, phase, result)
        self._record_feedback(state, phase, result, gate_action="approved")

        nxt = self.next_phase(state)
        state.current_phase = nxt or Phase.DONE
        self.store.save(state)
        log.info("gate approved: %s by %s", PHASE_LABEL[phase], gate.decided_by)
        return state

    def revise(self, run_id: str, phase: Phase, *, by: str = "", comment: str = "") -> RunState:
        """Send a phase back. It will re-run on the next advance()."""
        state = self.store.load(run_id)
        result = state.result(phase)
        gate = state.gate(phase)
        gate.status = GateStatus.REVISION_REQUESTED
        gate.decided_by = by or "unnamed reviewer"
        gate.decided_at = _now()
        gate.comment = comment
        if result:
            self._record_feedback(state, phase, result, gate_action="revision_requested")
        state.current_phase = phase
        self.store.save(state)
        log.info("revision requested on %s: %s", PHASE_LABEL[phase], comment or "(no comment)")
        return state

    def skip(self, run_id: str, phase: Phase, *, by: str = "", comment: str = "") -> RunState:
        state = self.store.load(run_id)
        gate = state.gate(phase)
        gate.status = GateStatus.SKIPPED
        gate.decided_by = by or "unnamed reviewer"
        gate.decided_at = _now()
        gate.comment = comment or "Skipped by reviewer."
        if phase not in state.skipped_phases:
            state.skipped_phases.append(phase)
        state.current_phase = self.next_phase(state) or Phase.DONE
        self.store.save(state)
        return state

    # -- queries -----------------------------------------------------------
    def next_phase(self, state: RunState) -> Phase | None:
        """First phase that is runnable, or None if blocked or finished."""
        for phase in GATED_PHASES:
            gate = state.gate(phase)
            if gate.status is GateStatus.SKIPPED:
                continue
            if gate.status is GateStatus.APPROVED:
                continue
            if gate.status is GateStatus.AWAITING_REVIEW:
                return None  # blocked: a human must decide first
            # NOT_READY or REVISION_REQUESTED -> this phase is the one to run
            return phase
        return None

    def _blocking_gate(self, state: RunState) -> Phase | None:
        for phase in GATED_PHASES:
            if state.gate(phase).status is GateStatus.AWAITING_REVIEW:
                return phase
        return None

    def status(self, run_id: str) -> dict[str, Any]:
        """Everything the UI pipeline view needs, in one call."""
        state = self.store.load(run_id)
        phases = []
        for phase in GATED_PHASES:
            gate = state.gate(phase)
            result = state.result(phase)
            phases.append(
                {
                    "phase": phase.value,
                    "label": PHASE_LABEL[phase],
                    "role": gate.role,
                    "status": gate.status.value,
                    "ok": result.ok if result else None,
                    "summary": result.summary if result else "",
                    "artifacts": [a.model_dump() for a in (result.artifacts if result else [])],
                    "flags": [f.model_dump() for f in (result.flags if result else [])],
                    "duplicate": result.duplicate.model_dump() if result and result.duplicate else None,
                    "decided_by": gate.decided_by,
                    "decided_at": gate.decided_at,
                    "comment": gate.comment,
                    "error": result.error if result else None,
                }
            )

        nxt = self.next_phase(state)
        blocking = self._blocking_gate(state)
        return {
            "run_id": state.run_id,
            "title": state.title,
            "business_process": state.business_process,
            "created": state.created,
            "updated": state.updated,
            "current_phase": state.current_phase.value,
            "next_phase": nxt.value if nxt else None,
            "awaiting_gate": blocking.value if blocking else None,
            "finished": nxt is None and blocking is None,
            "intake": state.results.get(Phase.INTAKE.value).model_dump() if state.result(Phase.INTAKE) else None,
            "requirements": [r.model_dump() for r in state.requirements],
            "change_items": [
                {**i.model_dump(), "build_owner": i.build_owner} for i in state.change_items
            ],
            "phases": phases,
            "total_artifacts": len(state.artifacts()),
            "total_flags": len(state.all_flags()),
        }

    # -- internals ---------------------------------------------------------
    def _ingest(self, state: RunState) -> list[Document]:
        docs = [extract_file(p) for p in state.inputs]
        failed = [d for d in docs if not d.ok]
        for d in failed:
            log.warning("input unreadable: %s - %s", d.name, d.error)
        return docs

    def _context(self, state: RunState, docs: list[Document], *, auto_approve: bool = False) -> AgentContext:
        process_name = (state.business_process or self.cfg.default_process).upper()
        return AgentContext(
            cfg=self.cfg,
            brain=self.brain,
            validator=self.validator,
            llm=self.llm,
            state=state,
            process=self.cfg.process(process_name),
            workdir=self.store.run_dir(state.run_id),
            source_material=bundle(docs),
            auto_approve=auto_approve,
        )

    def _write_to_brain(self, state: RunState, phase: Phase, result: PhaseResult) -> None:
        """Approved artifact -> AI Brain (blueprint: write back after the gate)."""
        body = ""
        for artifact in result.artifacts:
            if artifact.kind == "md" and "flag" not in artifact.name.lower():
                path = Path(artifact.path)
                if path.exists():
                    body = path.read_text(encoding="utf-8")
                    break
        if not body:
            log.debug("no markdown artifact to index for %s", phase.value)
            return

        doc_type = {
            Phase.FDD: "fdd",
            Phase.TDD: "tdd",
            Phase.BUILD_CONFIG: "build_config",
            Phase.BUILD_INTEGRATION: "build_integration",
            Phase.TEST: "testcases",
            Phase.DEPLOY: "deployment",
        }[phase]

        action = result.duplicate.action if result.duplicate else "new"
        doc_id = None
        if action == "update" and result.duplicate and result.duplicate.best:
            doc_id = result.duplicate.best.doc_id

        proposal, doc = self.brain.store.write(
            confirm=True,  # the user gate is the confirmation
            title=f"{state.business_process} - {state.title}",
            doc_type=doc_type,
            business_process=state.business_process,
            body=body,
            doc_id=doc_id,
            run_id=state.run_id,
            agent=result.agent,
            change_items=[i.id for i in state.change_items],
            tags=[state.business_process, doc_type],
        )
        if doc is not None:
            self.brain.index.index_document(doc)
            log.info("AI Brain updated: %s v%d", doc.doc_id, doc.version)
            for artifact in result.artifacts:
                if artifact.kind in ("docx", "xlsx"):
                    companion = Path(artifact.path)
                    if companion.exists():
                        self.brain.store.copy_companion(doc, companion)

    def _record_feedback(
        self, state: "RunState", phase: "Phase", result: "PhaseResult", *, gate_action: str
    ) -> None:
        """Capture gate decision + reviewer comment as a correction for auto-learning."""
        gate = state.gate(phase)
        if not gate.comment:
            return
        doc_type = {
            Phase.FDD: "fdd",
            Phase.TDD: "tdd",
            Phase.BUILD_CONFIG: "build_config",
            Phase.BUILD_INTEGRATION: "build_integration",
            Phase.TEST: "testcases",
            Phase.DEPLOY: "deployment",
        }.get(phase, "unknown")
        flags = [f.model_dump() for f in result.flags] if result.flags else []
        self.brain.feedback.record(
            doc_type=doc_type,
            business_process=state.business_process,
            run_id=state.run_id,
            reviewer=gate.decided_by or "unnamed",
            comment=gate.comment,
            flags=flags,
            gate_action=gate_action,
        )
