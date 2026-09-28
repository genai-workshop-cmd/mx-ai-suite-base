"""The anti-hallucination gate.

Every Maximo name an agent wants to put in a document passes through here
first. Resolution order (blueprint section 6):

  1. live environment, when reachable
  2. bundled schema catalogue (401 real object structures)
  3. unverified -> the caller raises a Flag for human review

Nothing is silently accepted. A name that cannot be confirmed is reported as
`exists=False, source="unverified"` with close-match suggestions attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.config import SuiteConfig
from core.errors import MaximoError
from core.logging import get
from core.models import Flag, ValidationResult

from .catalog import SchemaCatalog, catalog
from .client import MaximoClient

log = get("suite.maximo.validator")


@dataclass
class ValidationReport:
    """Aggregate of every check performed while building one artifact."""

    results: list[ValidationResult] = field(default_factory=list)

    def add(self, result: ValidationResult) -> ValidationResult:
        self.results.append(result)
        return result

    @property
    def failures(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.exists]

    @property
    def unverified(self) -> list[ValidationResult]:
        return [r for r in self.results if r.source == "unverified"]

    @property
    def live_checks(self) -> int:
        return sum(1 for r in self.results if r.source == "live")

    @property
    def clean(self) -> bool:
        return not self.failures

    def to_flags(self, section: str) -> list[Flag]:
        """Turn every failed check into a reviewer-facing flag."""
        flags: list[Flag] = []
        for r in self.failures:
            suggestion = ""
            if r.suggestions:
                suggestion = "Did you mean: " + ", ".join(r.suggestions[:3]) + "?"
            flags.append(
                Flag(
                    section=section,
                    item=f"{r.kind}: {r.name}",
                    reason=r.detail or f"{r.kind} '{r.name}' could not be confirmed in Maximo.",
                    confidence=0.30 if r.source == "unverified" else 0.10,
                    severity="block" if r.source != "unverified" else "warn",
                    suggestion=suggestion,
                )
            )
        return flags

    def summary(self) -> str:
        total = len(self.results)
        if not total:
            return "No Maximo names required validation."
        ok = total - len(self.failures)
        return (
            f"{ok}/{total} Maximo references confirmed "
            f"({self.live_checks} against the live environment, "
            f"{total - self.live_checks - len(self.unverified)} against the bundled catalogue, "
            f"{len(self.unverified)} unverified)."
        )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


class MaximoValidator:
    """Validates object, attribute, application, status and script names."""

    def __init__(self, cfg: SuiteConfig, client: MaximoClient | None = None) -> None:
        self.cfg = cfg
        self.client = client or MaximoClient(cfg.maximo)
        self.catalog: SchemaCatalog = catalog(cfg.maximo.schema_dir, cfg.maximo.apimeta_path)
        self._live: bool | None = None
        self._live_schema_cache: dict[str, dict | None] = {}
        #: True when the catalogue was mirrored from the target environment by
        #: `run.py maximo sync`. Then the catalogue *is* the live environment:
        #: it is authoritative, exact and free, so we do not probe over HTTP.
        self._catalogue_is_live = bool(cfg.maximo.using_live_catalogue)

    # -- environment -------------------------------------------------------
    @property
    def live(self) -> bool:
        """Whether the live environment is usable. Probed once."""
        if self._live is None:
            self._live = self.client.ping().reachable if self.client.configured else False
            log.info("Maximo validation source: %s", "live environment" if self._live else "bundled catalogue")
        return self._live

    def source_label(self) -> str:
        if self._catalogue_is_live:
            return "schemas synced from the target environment"
        return "live environment" if self.live else "bundled catalogue"

    @property
    def _catalogue_source(self) -> str:
        """What to record on a result resolved from the catalogue."""
        return "live" if self._catalogue_is_live else "catalogue"

    @property
    def _catalogue_name(self) -> str:
        return "synced environment schemas" if self._catalogue_is_live else "bundled catalogue"

    def _should_probe_live(self) -> bool:
        """Only worth an HTTP round trip when the catalogue may be incomplete."""
        return self.live and not self._catalogue_is_live

    # -- checks ------------------------------------------------------------
    def object(self, name: str) -> ValidationResult:
        name = (name or "").strip()
        if not name:
            return ValidationResult(name="", kind="object", exists=False, detail="Empty object name.")

        # The catalogue is checked first: when it was synced from the target
        # environment it is exact, and it always ranks structures better than a
        # name-guessing HTTP probe can.
        if self.catalog.object_exists(name):
            info = self.catalog.for_object(name)
            return ValidationResult(
                name=name.upper(), kind="object", exists=True, source=self._catalogue_source,
                detail=(
                    f"Confirmed via object structure {info.os_name} ({len(info.attributes)} fields)."
                    if info else f"Confirmed in the {self._catalogue_name}."
                ),
            )

        if self._should_probe_live():
            found = self._live_schema_for_object(name)
            if found is not None:
                return ValidationResult(
                    name=name.upper(), kind="object", exists=True, source="live",
                    detail=f"Confirmed via object structure {found.get('resource', name).upper()}.",
                )

        return ValidationResult(
            name=name.upper(), kind="object", exists=False, source="unverified",
            detail=f"Object '{name.upper()}' is not in the {self._catalogue_name}.",
            suggestions=self.catalog.suggest_objects(name),
        )

    def attribute(self, mbo: str, attribute: str) -> ValidationResult:
        label = f"{mbo.upper()}.{attribute.upper()}"
        if not mbo or not attribute:
            return ValidationResult(name=label, kind="attribute", exists=False, detail="Empty object or attribute.")

        info = self.catalog.attribute(mbo, attribute)
        if info:
            length = f", max length {info.max_length}" if info.max_length else ""
            return ValidationResult(
                name=label, kind="attribute", exists=True, source=self._catalogue_source,
                detail=f"{info.title or attribute.upper()} - {info.maximo_type}{length}.",
            )

        if self._should_probe_live():
            schema = self._live_schema_for_object(mbo)
            if schema is not None:
                props = {k.lower() for k in (schema.get("properties") or {})}
                if attribute.lower() in props:
                    return ValidationResult(
                        name=label, kind="attribute", exists=True, source="live",
                        detail="Confirmed against the live object structure schema.",
                    )

        # A new attribute the project intends to create is legitimate; the caller
        # decides. We report it as unverified with the closest existing names.
        return ValidationResult(
            name=label, kind="attribute", exists=False, source="unverified",
            detail=(
                f"Attribute '{attribute.upper()}' does not exist on {mbo.upper()} today. "
                "If this change creates it, confirm the DB Config entry; otherwise the name is wrong."
            ),
            suggestions=self.catalog.suggest_attributes(mbo, attribute),
        )

    def object_structure(self, os_name: str) -> ValidationResult:
        info = self.catalog.object_structure(os_name)
        if info:
            return ValidationResult(
                name=os_name.upper(), kind="objectstructure", exists=True, source="catalogue",
                detail=f"{info.description or info.resource} ({len(info.attributes)} fields).",
            )
        if self.live and self.client.object_structure_schema(os_name):
            return ValidationResult(
                name=os_name.upper(), kind="objectstructure", exists=True, source="live",
                detail="Confirmed in the live environment.",
            )
        return ValidationResult(
            name=os_name.upper(), kind="objectstructure", exists=False, source="unverified",
            detail=f"Object structure '{os_name.upper()}' not found.",
            suggestions=[i.os_name for i in self.catalog.search(os_name, limit=3)],
        )

    def application(self, app: str, process: dict) -> ValidationResult:
        """Applications are validated against the business-process definition.

        Maximo does not expose the App Designer registry over the REST API, so
        config/processes/<p>.yaml is the authority here.
        """
        known = {a.upper() for a in (process.get("applications") or [])}
        if app.upper() in known:
            return ValidationResult(
                name=app.upper(), kind="app", exists=True, source="catalogue",
                detail=f"Declared for the {process.get('name', '?')} process.",
            )
        return ValidationResult(
            name=app.upper(), kind="app", exists=False, source="unverified",
            detail=(
                f"Application '{app.upper()}' is not declared for the {process.get('name', '?')} process."
            ),
            suggestions=sorted(known)[:5],
        )

    def status(self, value: str, process: dict, domain: str = "cu") -> ValidationResult:
        allowed = {s.upper() for s in (process.get("statuses", {}) or {}).get(domain, [])}
        if value.upper() in allowed:
            return ValidationResult(
                name=value.upper(), kind="status", exists=True, source="catalogue",
                detail=f"Valid {domain.upper()} status.",
            )
        return ValidationResult(
            name=value.upper(), kind="status", exists=False, source="unverified",
            detail=f"'{value.upper()}' is not a declared {domain.upper()} status.",
            suggestions=sorted(allowed)[:6],
        )

    def script_name_free(self, name: str) -> ValidationResult:
        """Blueprint section 6: a generated script must not clash with an existing one.

        Note the inverted polarity - `exists=True` here means "the name is free".
        """
        if self.live:
            taken = self.client.script_exists(name)
            if taken is True:
                return ValidationResult(
                    name=name.upper(), kind="script", exists=False, source="live",
                    detail=f"An automation script named '{name.upper()}' already exists in Maximo.",
                    suggestions=[f"{name.upper()}_V2", f"{name.upper()}_NEW"],
                )
            if taken is False:
                return ValidationResult(
                    name=name.upper(), kind="script", exists=True, source="live",
                    detail="Script name is free in the live environment.",
                )
        return ValidationResult(
            name=name.upper(), kind="script", exists=True, source="unverified",
            detail="Could not check for a name clash - Maximo is offline. Verify before import.",
        )

    # -- convenience -------------------------------------------------------
    def check_change_item(self, item, process: dict, report: ValidationReport) -> None:
        """Validate every Maximo reference carried by a ChangeItem."""
        if item.maximo_object:
            report.add(self.object(item.maximo_object))
            if item.maximo_attribute:
                report.add(self.attribute(item.maximo_object, item.maximo_attribute))
        if item.maximo_app:
            report.add(self.application(item.maximo_app, process))

    def attribute_spec(self, mbo: str, attribute: str) -> dict:
        """Type/length facts for an existing attribute, for build documents."""
        info = self.catalog.attribute(mbo, attribute)
        if not info:
            return {}
        return {
            "name": info.name.upper(),
            "title": info.title,
            "type": info.maximo_type,
            "length": info.max_length,
            "persistent": info.persistent,
            "remarks": info.remarks,
        }

    def _live_schema_for_object(self, mbo: str) -> dict | None:
        """Fetch the live schema for whichever object structure exposes this MBO.

        The bundled catalogue answers the common cases. When it cannot - which
        is precisely when a live environment is worth having, because the object
        belongs to an add-on like PLUSDCU - we search the environment's real
        object-structure list instead of guessing a name.
        """
        key = mbo.lower()
        if key in self._live_schema_cache:
            return self._live_schema_cache[key]

        matches: list[tuple[int, str, dict]] = []
        for candidate in self._candidate_structures(mbo):
            try:
                found = self.client.object_structure_schema(candidate)
            except MaximoError:
                continue
            if not found:
                continue
            # Confirm the structure really exposes this MBO before trusting it.
            exposed = (found.get("description") or found.get("title") or found.get("resource") or "").upper()
            if exposed == mbo.upper() or candidate == key:
                matches.append((len(found.get("properties") or {}), candidate, found))

        schema = None
        if matches:
            # Several structures can expose the same MBO - a full one and a
            # narrow sub-entity view. Validating attributes against the narrow
            # one would reject fields that genuinely exist, so take the richest.
            width, candidate, schema = max(matches, key=lambda m: m[0])
            log.debug("resolved %s via live object structure %s (%d fields)", mbo.upper(), candidate, width)

        self._live_schema_cache[key] = schema
        return schema

    def _candidate_structures(self, mbo: str) -> list[str]:
        """Object-structure names worth probing for this MBO, best first."""
        key = mbo.lower()
        candidates: list[str] = []

        info = self.catalog.for_object(mbo)
        if info:
            candidates.append(info.os_name.lower())

        available = self.client.object_structure_names()
        if not available:
            # No live listing - fall back to the naming convention.
            candidates.append(f"mxapi{key}")
            return _dedupe(candidates)

        for name in (key, f"mxapi{key}", f"mx{key}"):
            if name in available:
                candidates.append(name)

        # Add-on structures rarely follow the convention, so fall back to name
        # containment, shortest first.
        related = sorted((n for n in available if key in n or n in key), key=len)
        candidates.extend(related[:4])
        return _dedupe(candidates)[:6]
