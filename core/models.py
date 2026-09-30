"""Pydantic contracts shared by agents, pipeline, brain and UI.

These are the only structures that cross a module boundary. If a field is not
here, it does not travel between phases.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# --------------------------------------------------------------------------
# Requirement classification
# --------------------------------------------------------------------------
class ChangeType(str, Enum):
    CONFIG = "config"
    CUSTOMISATION = "customisation"
    INTEGRATION = "integration"
    WORKFLOW = "workflow"
    REPORT = "report"
    SECURITY = "security"
    DATA = "data"
    UNKNOWN = "unknown"


#: Which build agent owns each change type.
BUILD_OWNER: dict[ChangeType, str] = {
    ChangeType.CONFIG: "3A",
    ChangeType.CUSTOMISATION: "3A",
    ChangeType.WORKFLOW: "3A",
    ChangeType.REPORT: "3A",
    ChangeType.SECURITY: "3A",
    ChangeType.DATA: "3A",
    ChangeType.INTEGRATION: "3B",
    ChangeType.UNKNOWN: "3A",
}


class Confidence(BaseModel):
    """A 0..1 score plus the reason it is not 1.0."""

    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""

    @property
    def tier(self) -> str:
        if self.score >= 0.80:
            return "HIGH"
        if self.score >= 0.50:
            return "MEDIUM"
        return "LOW"


class Flag(BaseModel):
    """An item the agent is not confident about; surfaced at the user gate."""

    id: str = Field(default_factory=lambda: new_id("FLG"))
    section: str
    item: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Literal["info", "warn", "block"] = "warn"
    suggestion: str = ""


class ChangeItem(BaseModel):
    """One discrete change traced from requirement through to deployment."""

    id: str = Field(default_factory=lambda: new_id("CI"))
    title: str
    description: str = ""
    change_type: ChangeType = ChangeType.UNKNOWN
    maximo_object: str = ""
    maximo_attribute: str = ""
    maximo_app: str = ""
    business_process: str = "CU"
    source_requirement: str = ""
    # populated by Agent 2
    effort_hours: float = 0.0
    skill_level: Literal["junior", "mid", "senior", "architect"] = "mid"
    risk: Literal["low", "medium", "high"] = "medium"
    confidence: float = 1.0

    @property
    def build_owner(self) -> str:
        return BUILD_OWNER.get(self.change_type, "3A")


class Requirement(BaseModel):
    id: str = Field(default_factory=lambda: new_id("REQ"))
    title: str
    text: str
    source: str = ""
    change_type: ChangeType = ChangeType.UNKNOWN
    acceptance_criteria: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Maximo validation
# --------------------------------------------------------------------------
class ValidationResult(BaseModel):
    """Outcome of checking one Maximo name against the environment/catalogue."""

    name: str
    kind: Literal["object", "attribute", "app", "status", "script", "objectstructure"]
    exists: bool
    source: Literal["live", "catalogue", "unverified"] = "unverified"
    detail: str = ""
    suggestions: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exists


# --------------------------------------------------------------------------
# AI Brain
# --------------------------------------------------------------------------
class BrainHit(BaseModel):
    doc_id: str
    path: str
    title: str
    doc_type: str
    business_process: str
    version: int
    score: float
    matched_by: Literal["metadata", "keyword", "semantic"]
    excerpt: str = ""


class BrainDocument(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    business_process: str
    version: int = 1
    created: str = Field(default_factory=_now)
    updated: str = Field(default_factory=_now)
    run_id: str = ""
    agent: str = ""
    change_items: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    body: str = ""
    path: str = ""


class DuplicateDecision(BaseModel):
    """Result of the mandatory search-before-create check."""

    found: bool = False
    best: BrainHit | None = None
    similarity: float = 0.0
    threshold: float = 0.85
    #: set by the user at the gate
    action: Literal["update", "new", "pending"] = "new"


# --------------------------------------------------------------------------
# Artifacts, gates, run state
# --------------------------------------------------------------------------
class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ART"))
    name: str
    kind: Literal["docx", "xlsx", "md", "xml", "json", "py", "zip", "txt"]
    path: str
    agent: str
    phase: str
    bytes: int = 0
    created: str = Field(default_factory=_now)
    description: str = ""


class Phase(str, Enum):
    INTAKE = "intake"
    ANALYSIS = "analysis"
    FDD = "fdd"
    TDD = "tdd"
    BUILD_CONFIG = "build_config"
    BUILD_INTEGRATION = "build_integration"
    TEST = "test"
    DEPLOY = "deploy"
    DONE = "done"


PHASE_ORDER: list[Phase] = [
    Phase.INTAKE,
    Phase.ANALYSIS,
    Phase.FDD,
    Phase.TDD,
    Phase.BUILD_CONFIG,
    Phase.BUILD_INTEGRATION,
    Phase.TEST,
    Phase.DEPLOY,
    Phase.DONE,
]

PHASE_LABEL: dict[Phase, str] = {
    Phase.INTAKE: "Intake & Routing",
    Phase.ANALYSIS: "Agent 0 - Requirements Analysis",
    Phase.FDD: "Agent 1 - FDD",
    Phase.TDD: "Agent 2 - TDD",
    Phase.BUILD_CONFIG: "Agent 3A - Config Build",
    Phase.BUILD_INTEGRATION: "Agent 3B - Integration Build",
    Phase.TEST: "Agent 4 - Testing",
    Phase.DEPLOY: "Agent 5 - Deployment",
    Phase.DONE: "Complete",
}

PHASE_GATE_ROLE: dict[Phase, str] = {
    Phase.ANALYSIS: "Business Analyst / Scrum Master",
    Phase.FDD: "Designer / Architect",
    Phase.TDD: "Technical Lead / Architect",
    Phase.BUILD_CONFIG: "Maximo Developer",
    Phase.BUILD_INTEGRATION: "Integration Architect",
    Phase.TEST: "QA Lead",
    Phase.DEPLOY: "Architect / Project Manager",
}


class GateStatus(str, Enum):
    NOT_READY = "not_ready"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"
    SKIPPED = "skipped"


class Gate(BaseModel):
    phase: Phase
    role: str = ""
    status: GateStatus = GateStatus.NOT_READY
    decided_by: str = ""
    decided_at: str = ""
    comment: str = ""


class PhaseResult(BaseModel):
    phase: Phase
    agent: str
    started: str = Field(default_factory=_now)
    finished: str = ""
    ok: bool = False
    summary: str = ""
    artifacts: list[Artifact] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    duplicate: DuplicateDecision | None = None
    handover: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, str] | None = None
    # Document-level confidence score (0.0–1.0) computed from flags, validations, and generation method.
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    generated_by: str = ""


class RunState(BaseModel):
    """Everything about one pipeline run. Persisted to runs/<id>/state.json."""

    run_id: str = Field(default_factory=lambda: new_id("RUN"))
    title: str = "Untitled run"
    business_process: str = "CU"
    created: str = Field(default_factory=_now)
    updated: str = Field(default_factory=_now)
    current_phase: Phase = Phase.INTAKE
    inputs: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    change_items: list[ChangeItem] = Field(default_factory=list)
    gates: dict[str, Gate] = Field(default_factory=dict)
    results: dict[str, PhaseResult] = Field(default_factory=dict)
    #: phases the orchestrator decided are not applicable to this run
    skipped_phases: list[Phase] = Field(default_factory=list)
    notes: str = ""

    # -- helpers -----------------------------------------------------------
    def gate(self, phase: Phase) -> Gate:
        g = self.gates.get(phase.value)
        if g is None:
            g = Gate(phase=phase, role=PHASE_GATE_ROLE.get(phase, "Reviewer"))
            self.gates[phase.value] = g
        return g

    def result(self, phase: Phase) -> PhaseResult | None:
        return self.results.get(phase.value)

    def artifacts(self) -> list[Artifact]:
        out: list[Artifact] = []
        for r in self.results.values():
            out.extend(r.artifacts)
        return out

    def all_flags(self) -> list[Flag]:
        out: list[Flag] = []
        for r in self.results.values():
            out.extend(r.flags)
        return out

    def touch(self) -> None:
        self.updated = _now()
