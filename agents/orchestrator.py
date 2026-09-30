"""Orchestration agent (blueprint section 3.2).

Sits between the UI and the specialist agents and decides:
  * which business process this run belongs to
  * what the requirements are, extracted from the raw material
  * the change type of each one (config / customisation / integration / ...)
  * therefore which build agent runs: 3A, 3B, or both
  * whether this is an update to an existing document (Case 1) or new (Case 2)

Classification runs a deterministic rule pass first and, when a model is
configured, refines it. The rules alone are good enough to route correctly,
which is what keeps the suite usable with no API key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.logging import get
from core.models import ChangeItem, ChangeType, Phase, Requirement
from ingest.extract import Document

from .base import AgentContext

log = get("suite.agent.orchestrator")

#: Signals for each change type, highest-signal patterns first.
_RULES: list[tuple[ChangeType, list[str]]] = [
    (
        ChangeType.INTEGRATION,
        [
            r"\b(integration|interface|inbound|outbound|publish channel|enterprise service|object structure)\b",
            r"\b(external system|endpoint|web ?service|REST|SOAP|MIF|message)\b",
            r"\b(send|receive|push|pull|sync(hronis|hroniz)e)\b.{0,30}\b(to|from|with)\b.{0,30}\b(system|erp|gis|sap|portal)\b",
        ],
    ),
    (
        ChangeType.WORKFLOW,
        [r"\b(workflow|approval (process|route)|routing|wf process|assignment node|escalation path)\b"],
    ),
    (
        ChangeType.REPORT,
        [r"\b(BIRT|report|dashboard|KPI|print(out)?|crystal)\b"],
    ),
    (
        ChangeType.SECURITY,
        [
            r"\b(security group|authorisation|authorization|signature option|conditional access|data restriction)\b",
            # "Common Actions" toolbar in Maximo == Signature Options.
            r"\b(common actions?|toolbar option|action button)\b.{0,60}\b(add|create|new|custom)\b",
            r"\b(add|create|new|custom)\b.{0,60}\b(common actions?|toolbar option|action button)\b",
            # "Select X" dialogs launched from an action button are a signature option + conditional expression.
            r"\b(select\s+\w+)\b.{0,60}\b(dialog|option|action|button)\b",
        ],
    ),
    (
        ChangeType.CUSTOMISATION,
        [
            r"\b(automation script|autoscript|jython|java class|launch ?point|MBO|mboset)\b",
            r"\b(custom (logic|code|validation)|trigger|on (save|add|init|delete)|business rule)\b",
            r"\b(calculate|derive|copy\b.{0,30}\bto\b|populate\b.{0,30}\b(from|with))\b",
            # Validation rules ("X must not overwrite Y") need code, not config.
            r"\bmust not\b.{0,40}\b(overwrite|clear|change|replace|exceed)\b",
            r"\b(prevent|reject|block|disallow)\b.{0,30}\b(save|entry|update|status change)\b",
        ],
    ),
    (
        ChangeType.DATA,
        [r"\b(data (load|migration|conversion|cleansing)|bulk (load|update)|MXLoader|import .{0,20}records)\b"],
    ),
    (
        ChangeType.CONFIG,
        [
            r"\b(app designer|application designer|db config(urator|uration)?)\b",
            # "add a CU Comment field", "create a new status attribute" - allow
            # the descriptive words that sit between the verb and the noun.
            r"\b(add|create|introduce|define)\b[\w\s,'-]{0,40}?\b(field|attribute|column|tab|section|checkbox|dialog)\b",
            r"\b(domain|alndomain|synonym|crossover|conditional (expression|ui)|table (domain|column))\b",
            r"\b(screen|tab|section|dialog|lookup)\b",
            r"\bfield\b.{0,30}\b(visible|hidden|read.?only|mandatory|required|displayed|shown)\b",
            r"\b(cron task|escalation|start ?center)\b",
            r"\b(conditional expression|sigopt|app designer|toolbar|action bar)\b",
        ],
    ),
]

_COMPILED = [(ct, [re.compile(p, re.I) for p in pats]) for ct, pats in _RULES]

#: Sentences that look like a requirement.
_REQ_MARKERS = re.compile(
    r"\b(shall|must|should|need(s)? to|require(d|s)?|as an? \w+.{0,50}i want|add|create|modify|"
    r"update|remove|enable|disable|configure|generate|trigger|propagate|display|validate)\b",
    re.I,
)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")

#: Sections that explain rather than specify. Prose under these headings is
#: context for the FDD, not a change item to be built and estimated.
_NARRATIVE_HEADING_RE = re.compile(
    r"^\s*(background|context|overview|introduction|purpose|problem statement|"
    r"current state|as.is|rationale|objective|summary|glossary|references?)\b",
    re.I,
)

#: MAXIMO objects/attributes mentioned inline, e.g. WORKORDER.DESCRIPTION or workorder.description
_QUALIFIED_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,})\.([A-Za-z][A-Za-z0-9_]{2,})\b")
#: ALL-CAPS token (legacy) — still checked first
_UPPER_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\b")
#: Any mixed/lowercase token that could be a Maximo name
_ANY_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{3,})\b")

#: Upper-case tokens that are never Maximo attribute names.
_NOT_ATTRIBUTES = {
    "HTTP", "HTTPS", "JSON", "XML", "REST", "SOAP", "SQL", "CSV", "URL", "URI", "API",
    "MIF", "OSLC", "UUID", "GUID", "ETL", "SFTP", "FTP", "TLS", "SSL", "UTC", "PDF",
    "DOCX", "XLSX", "BIRT", "SLA", "UAT", "SIT", "ADO", "TODO", "NOTE", "WARN",
    "MAXIMO", "MAS", "ERP", "GIS", "CRM", "EAM", "AND", "OR", "NOT", "THE", "FOR",
    "WHEN", "FROM", "WITH", "INTO", "THAT", "THIS", "HAVE", "BEEN", "WILL", "COPY",
    "FORM", "WORK", "ORDER", "GETTING", "CREATED",
}

#: Common informal names → canonical Maximo object names.
#: Checked against the lowercase requirement text before the regex passes.
_MAXIMO_ALIASES: list[tuple[str, str]] = [
    # Multi-word aliases must come before single-word ones.
    ("preventive maintenance", "PM"),
    ("preventative maintenance", "PM"),
    ("planned maintenance", "PM"),
    ("multi asset locci", "MULTIASSETLOCCI"),
    ("multi-asset locci", "MULTIASSETLOCCI"),
    ("inspection form", "MULTIASSETLOCCI"),  # best-effort; often on WO/PM
    ("work order", "WORKORDER"),
    ("workorder", "WORKORDER"),
    ("job plan", "JOBPLAN"),
    ("service request", "SR"),
    ("purchase order", "PO"),
    ("purchase requisition", "PR"),
    ("multiassetlocci", "MULTIASSETLOCCI"),
    ("woactivity", "WOACTIVITY"),
    ("wplabor", "WPLABOR"),
    ("matusetrans", "MATUSETRANS"),
    ("labtrans", "LABTRANS"),
    ("craftskill", "CRAFTSKILL"),
]


@dataclass
class RoutingDecision:
    business_process: str
    requirements: list[Requirement] = field(default_factory=list)
    change_items: list[ChangeItem] = field(default_factory=list)
    phases: list[Phase] = field(default_factory=list)
    skipped: list[Phase] = field(default_factory=list)
    rationale: str = ""
    classified_by: str = "rules"

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for item in self.change_items:
            counts[item.change_type.value] = counts.get(item.change_type.value, 0) + 1
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "none"
        return (
            f"{len(self.requirements)} requirement(s) -> {len(self.change_items)} change item(s) "
            f"({breakdown}). Build route: {'3A + 3B' if Phase.BUILD_INTEGRATION in self.phases and Phase.BUILD_CONFIG in self.phases else ('3B' if Phase.BUILD_INTEGRATION in self.phases else '3A')}."
        )


def classify_text(text: str) -> tuple[ChangeType, float]:
    """Score a requirement against every rule set; highest wins."""
    scores: dict[ChangeType, float] = {}
    for change_type, patterns in _COMPILED:
        hits = sum(1 for p in patterns if p.search(text))
        if hits:
            # Earlier rule sets are more specific, so they get a small edge.
            scores[change_type] = hits + (0.1 * (len(_COMPILED) - _COMPILED.index((change_type, patterns))))
    if not scores:
        return ChangeType.UNKNOWN, 0.25
    best = max(scores, key=lambda k: scores[k])
    spread = scores[best] - (sorted(scores.values(), reverse=True) + [0])[1]
    confidence = 0.55 + min(0.4, 0.12 * scores[best] + 0.1 * spread)
    return best, round(min(confidence, 0.95), 2)


def detect_process(text: str, cfg) -> tuple[str, float]:
    """Pick the business process whose vocabulary the material matches."""
    best_name, best_score = cfg.default_process, 0.0
    lowered = text.lower()
    for name in cfg.known_processes():
        try:
            process = cfg.process(name)
        except Exception:
            continue
        keywords = process.get("keywords") or []
        score = sum(lowered.count(k.lower()) for k in keywords)
        if score > best_score:
            best_name, best_score = name, float(score)
    confidence = 0.5 if best_score == 0 else min(0.95, 0.6 + 0.05 * best_score)
    return best_name, round(confidence, 2)


def extract_requirements(docs: list[Document], limit: int = 40) -> list[Requirement]:
    """Pull candidate requirement statements out of the ingested material."""
    found: list[Requirement] = []
    seen: set[str] = set()

    for doc in docs:
        if not doc.ok:
            continue
        heading = doc.name
        narrative = False
        for raw in doc.text.splitlines():
            line = raw.strip()
            if not line:
                continue
            h = _HEADING_RE.match(line)
            if h:
                heading = h.group(1).strip()
                narrative = bool(_NARRATIVE_HEADING_RE.match(heading))
                continue
            if narrative:
                # Explanatory prose. It reaches the agents as source material,
                # but it is not a change item to build, estimate and test.
                continue

            bullet = _BULLET_RE.match(raw)
            candidate = bullet.group(1).strip() if bullet else line
            if len(candidate) < 25 or len(candidate) > 600:
                continue
            if not _REQ_MARKERS.search(candidate):
                continue

            key = re.sub(r"\W+", "", candidate.lower())[:90]
            if key in seen:
                continue
            seen.add(key)

            change_type, _ = classify_text(candidate)
            found.append(
                Requirement(
                    title=_title_of(candidate),
                    text=candidate,
                    source=f"{doc.name} > {heading}" if heading != doc.name else doc.name,
                    change_type=change_type,
                )
            )
            if len(found) >= limit:
                return found

        # Table rows are a common requirement carrier in ADO exports.
        for table in doc.tables[:4]:
            for row in table[1:]:
                joined = " | ".join(c for c in row if c).strip()
                if 30 <= len(joined) <= 500 and _REQ_MARKERS.search(joined):
                    key = re.sub(r"\W+", "", joined.lower())[:90]
                    if key in seen:
                        continue
                    seen.add(key)
                    change_type, _ = classify_text(joined)
                    found.append(
                        Requirement(
                            title=_title_of(joined),
                            text=joined,
                            source=f"{doc.name} (table)",
                            change_type=change_type,
                        )
                    )
                    if len(found) >= limit:
                        return found
    return found


def _title_of(text: str, width: int = 80) -> str:
    clean = re.sub(r"\s+", " ", text).strip(" -*|")
    clean = re.sub(r"^(as an?\s+[\w\s]+?,?\s*i want\s*(to)?\s*)", "", clean, flags=re.I)
    return (clean[:width].rsplit(" ", 1)[0] + "...") if len(clean) > width else clean


def _maximo_hints(text: str, process: dict) -> tuple[str, str, str]:
    """Best-effort object / attribute / application extraction.

    Works in three passes:
    1. Alias lookup — catches informal names like "work order", "pm", "multiassetlocci".
    2. OBJECT.ATTRIBUTE qualified token (any case).
    3. Uppercase token scan against the process's known object / app lists,
       then against any token that looks like a Maximo name.
    """
    objects = process.get("objects", {}) or {}
    known_objects = {o.upper() for o in [*(objects.get("primary") or []), *(objects.get("related") or [])]}
    known_apps = {a.upper() for a in (process.get("applications") or [])}
    known_statuses = {
        s.upper() for group in (process.get("statuses", {}) or {}).values() for s in group
    }
    naming = process.get("naming", {}) or {}
    component_suffixes = tuple(
        s for s in (naming.get("publish_channel_suffix"), naming.get("external_system_suffix")) if s
    )

    obj = attr = app = ""
    lower_text = text.lower()

    # Pass 1 — alias lookup (multi-word names, common informal references).
    for alias, canonical in _MAXIMO_ALIASES:
        if alias in lower_text:
            if canonical in known_objects and not obj:
                obj = canonical
            elif canonical in known_apps and not app:
                app = canonical
            elif not obj:
                # Not in this process's known list but is a valid Maximo object name.
                obj = obj or canonical

    # Pass 2 — qualified OBJECT.ATTRIBUTE token (case-insensitive).
    qualified = _QUALIFIED_RE.search(text)
    if qualified:
        q_obj = qualified.group(1).upper()
        q_attr = qualified.group(2).upper()
        if q_attr not in _NOT_ATTRIBUTES:
            return q_obj, q_attr, app

    # Pass 3 — uppercase token scan then any-case scan.
    for token in _UPPER_TOKEN_RE.findall(text):
        upper = token.upper()
        if upper in known_objects:
            obj = obj or upper
        elif upper in known_apps:
            app = app or upper
        elif (
            upper in known_statuses
            or upper in _NOT_ATTRIBUTES
            or upper.endswith(component_suffixes or ("\0",))
        ):
            continue
        elif not attr:
            attr = upper

    # Pass 3b — case-insensitive scan for any-case Maximo tokens not caught above.
    if not obj:
        for token in _ANY_TOKEN_RE.findall(text):
            upper = token.upper()
            if upper in known_objects:
                obj = upper
                break

    return obj, attr, app


class Orchestrator:
    """Routing brain. Not a document producer."""

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    def route(self, docs: list[Document]) -> RoutingDecision:
        cfg = self.ctx.cfg
        combined = "\n".join(d.text for d in docs if d.ok)

        process_name, process_conf = detect_process(combined, cfg)
        # An explicit choice from the user wins over detection.
        if self.ctx.state.business_process:
            process_name = self.ctx.state.business_process.upper()
        process = cfg.process(process_name)

        requirements = extract_requirements(docs)
        if not requirements and combined.strip():
            # Nothing matched the requirement heuristics: treat the whole input
            # as one requirement rather than producing an empty run.
            requirements = [
                Requirement(
                    title=self.ctx.state.title or "Requirement from uploaded material",
                    text=combined[:1500],
                    source=", ".join(d.name for d in docs if d.ok) or "input",
                    change_type=classify_text(combined)[0],
                )
            ]

        change_items = self._to_change_items(requirements, process)
        phases, skipped = self._phases(change_items)

        decision = RoutingDecision(
            business_process=process_name,
            requirements=requirements,
            change_items=change_items,
            phases=phases,
            skipped=skipped,
            classified_by="rules",
        )
        decision.rationale = (
            f"Process '{process_name}' selected (confidence {process_conf}). " + decision.summary()
        )

        refined = self._refine_with_model(decision, combined)
        if refined is not None:
            decision = refined

        log.info("routing: %s", decision.rationale)
        return decision

    # -- internals ---------------------------------------------------------
    def _to_change_items(self, requirements: list[Requirement], process: dict) -> list[ChangeItem]:
        items: list[ChangeItem] = []
        for req in requirements:
            change_type, confidence = classify_text(req.text)
            obj, attr, app = _maximo_hints(req.text, process)
            items.append(
                ChangeItem(
                    title=req.title,
                    description=req.text,
                    change_type=change_type,
                    maximo_object=obj,
                    maximo_attribute=attr,
                    maximo_app=app,
                    business_process=str(process.get("name", "CU")),
                    source_requirement=req.id,
                    confidence=confidence,
                )
            )
        return items

    def _phases(self, items: list[ChangeItem]) -> tuple[list[Phase], list[Phase]]:
        """Blueprint section 3.2: route to 3A and/or 3B by handover token."""
        needs_3b = any(i.build_owner == "3B" for i in items)
        needs_3a = any(i.build_owner == "3A" for i in items)
        if not items:
            needs_3a = True

        phases = [Phase.FDD, Phase.TDD]
        skipped: list[Phase] = []
        (phases if needs_3a else skipped).append(Phase.BUILD_CONFIG)
        (phases if needs_3b else skipped).append(Phase.BUILD_INTEGRATION)
        phases.extend([Phase.TEST, Phase.DEPLOY])
        return phases, skipped

    def _refine_with_model(self, decision: RoutingDecision, material: str) -> RoutingDecision | None:
        """Let the model correct change types. Rules stand if it declines."""
        if not self.ctx.llm.available or not decision.change_items:
            return None

        listing = "\n".join(
            f"{i}. [{item.change_type.value}] {item.title}" for i, item in enumerate(decision.change_items, 1)
        )
        valid = ", ".join(t.value for t in ChangeType if t is not ChangeType.UNKNOWN)
        system = (
            "You are the orchestration agent for an IBM Maximo delivery suite. "
            "You classify Maximo change requirements. You never invent requirements."
        )
        user = (
            f"Business process: {decision.business_process}\n\n"
            f"Each line below is a requirement with its rule-based classification.\n"
            f"Return JSON: a list of objects with keys 'index' (1-based) and 'change_type'.\n"
            f"Valid change_type values: {valid}.\n"
            f"Only include an entry where the rule-based classification is WRONG. "
            f"If every classification is correct, return [].\n\n{listing}"
        )
        try:
            parsed, reply = self.ctx.llm.complete_json(system, user, max_tokens=1200)
        except Exception as exc:
            log.warning("orchestrator model refinement failed (%s) - keeping rule classification", exc)
            return None
        if not reply.ok or not isinstance(parsed, list) or not parsed:
            return None

        changed = 0
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry.get("index", 0)) - 1
                new_type = ChangeType(str(entry.get("change_type", "")).lower())
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(decision.change_items) and decision.change_items[idx].change_type is not new_type:
                decision.change_items[idx].change_type = new_type
                decision.change_items[idx].confidence = 0.85
                if idx < len(decision.requirements):
                    decision.requirements[idx].change_type = new_type
                changed += 1

        if not changed:
            return None
        decision.classified_by = f"rules+{reply.provider}"
        decision.phases, decision.skipped = self._phases(decision.change_items)
        decision.rationale = f"{decision.summary()} Model adjusted {changed} classification(s)."
        return decision
