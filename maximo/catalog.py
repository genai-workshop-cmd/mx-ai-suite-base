"""Offline Maximo schema catalogue.

Backed by 401 real object-structure JSON schemas dumped read-only from a MAS
trial environment (`reference/maximo-schemas/`). This is what makes the
"no hallucinated field names" rule enforceable when Maximo is unreachable:
every object and attribute an agent emits is checked against this catalogue.

Loading is lazy and cached - the first lookup pays ~1s, the rest are O(1).
"""
from __future__ import annotations

import difflib
import json
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.logging import get

log = get("suite.maximo.catalog")


@dataclass
class AttributeInfo:
    name: str
    title: str = ""
    type: str = "string"
    sub_type: str = ""
    persistent: bool = True
    max_length: int | None = None
    remarks: str = ""
    has_list: bool = False

    @property
    def maximo_type(self) -> str:
        """Map JSON-schema type + subType onto a Maximo attribute type."""
        st = (self.sub_type or "").upper()
        if st in {"ALN", "UPPER", "LOWER"}:
            return "ALN" if st == "ALN" else "UPPER"
        if st == "DATE":
            return "DATE"
        if st == "DATETIME":
            return "DATETIME"
        if st in {"AMOUNT", "DECIMAL", "FLOAT"}:
            return "DECIMAL"
        if st in {"INTEGER", "SMALLINT", "BIGINT"}:
            return "INTEGER"
        if st in {"YORN", "BOOLEAN"}:
            return "YORN"
        mapping = {"string": "ALN", "number": "DECIMAL", "integer": "INTEGER", "boolean": "YORN"}
        return mapping.get(self.type, "ALN")


#: Prefixes Maximo puts on object-structure names. Stripping one is a weak
#: hint at the business object underneath (mxapiasset -> asset).
_OS_PREFIXES = ("mxapi", "mxsys", "rep_", "conv_", "oct_", "mas", "mx")

#: Strength of each signal used to decide which MBO a structure exposes.
_STRONG = 2
_WEAK = 1

#: Reporting, conversion and project-specific views. They expose a real object
#: but are not the canonical structure to design against, so they rank last.
_DERIVED_PREFIXES = ("rep_", "conv_", "oct_")


def _mbo_candidates(raw: dict, os_key: str) -> list[tuple[str, int]]:
    """Every plausible business-object name for this schema, with a strength.

    Environments disagree about `description`: the MAS trial puts the MBO there
    ("WORKORDER"), ACN IAX puts prose ("Maximo API for Work Orders"). The
    dependable signal is `uniqueid` - workorderid -> WORKORDER. We index under
    every plausible key and let ranking sort it out, rather than betting on one
    convention and silently failing to resolve half the environment.
    """
    out: list[tuple[str, int]] = []

    uid = (raw.get("uniqueid") or "").strip().lower()
    if uid:
        # plusdcuid is PLUSDCU + "id" or PLUSDC + "uid" - register both.
        for suffix in ("id", "uid"):
            if uid.endswith(suffix) and len(uid) > len(suffix):
                out.append((uid[: -len(suffix)], _STRONG))

    for key in ("description", "title"):
        value = (raw.get(key) or "").strip()
        # A single bare token is an MBO name; prose is a human label.
        if value and " " not in value:
            out.append((value.lower(), _STRONG))

    for prefix in _OS_PREFIXES:
        if os_key.startswith(prefix) and len(os_key) > len(prefix):
            out.append((os_key[len(prefix):], _WEAK))
            break
    out.append((os_key, _WEAK))

    return [(name, strength) for name, strength in out if len(name) > 1]


@dataclass
class ObjectStructureInfo:
    """One object structure.

    `os_name` is the structure (MXAPIWO); `mbo` is the business object it
    exposes (WORKORDER), derived from whichever signal the environment offers.
    """

    os_name: str
    mbo: str
    description: str = ""
    primary_keys: list[str] = field(default_factory=list)
    unique_id: str = ""
    attributes: dict[str, AttributeInfo] = field(default_factory=dict)
    child_objects: list[str] = field(default_factory=list)
    use_with: str = ""

    def attribute(self, name: str) -> AttributeInfo | None:
        return self.attributes.get(name.lower())


class SchemaCatalog:
    """Read-only index over the bundled object-structure schemas."""

    def __init__(self, schema_dir: Path, apimeta_path: Path | None = None) -> None:
        self.schema_dir = schema_dir
        self.apimeta_path = apimeta_path
        self._lock = threading.Lock()
        self._loaded = False
        self._by_os: dict[str, ObjectStructureInfo] = {}
        self._by_mbo: dict[str, list[tuple[int, str]]] = {}
        self._meta: dict[str, dict] = {}

    # -- loading -----------------------------------------------------------
    def _ensure(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._load()
            self._loaded = True

    def _load(self) -> None:
        if not self.schema_dir.exists():
            log.warning("schema catalogue missing at %s - offline validation disabled", self.schema_dir)
            return

        if self.apimeta_path and self.apimeta_path.exists():
            try:
                for entry in json.loads(self.apimeta_path.read_text(encoding="utf-8")):
                    name = (entry.get("osName") or "").lower()
                    if name:
                        self._meta[name] = entry
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("could not read apimeta.json: %s", exc)

        count = 0
        for path in sorted(self.schema_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.debug("skipping unreadable schema %s: %s", path.name, exc)
                continue

            os_name = path.stem.lower()
            candidates = _mbo_candidates(raw, os_name)
            best_mbo = next((n for n, s in candidates if s == _STRONG), candidates[0][0] if candidates else os_name)
            info = ObjectStructureInfo(
                os_name=(raw.get("resource") or os_name).upper(),
                mbo=best_mbo.upper(),
                description=(raw.get("description") or raw.get("title") or "").strip(),
                primary_keys=[k.lower() for k in (raw.get("pk") or [])],
                unique_id=(raw.get("uniqueid") or "").lower(),
                use_with=(self._meta.get(os_name, {}).get("useWith") or ""),
            )
            for attr_name, spec in (raw.get("properties") or {}).items():
                if not isinstance(spec, dict):
                    continue
                if spec.get("type") == "array" or "items" in spec:
                    info.child_objects.append(attr_name.upper())
                    continue
                info.attributes[attr_name.lower()] = AttributeInfo(
                    name=attr_name.lower(),
                    title=spec.get("title", ""),
                    type=spec.get("type", "string"),
                    sub_type=spec.get("subType", ""),
                    persistent=bool(spec.get("persistent", False)),
                    max_length=spec.get("maxLength"),
                    remarks=spec.get("remarks", ""),
                    has_list=bool(spec.get("hasList", False)),
                )
            self._by_os[os_name] = info
            for name, strength in candidates:
                self._by_mbo.setdefault(name, []).append((strength, os_name))
            count += 1

        log.info("schema catalogue loaded: %d object structures", count)

    # -- queries -----------------------------------------------------------
    @property
    def size(self) -> int:
        self._ensure()
        return len(self._by_os)

    def object_structure(self, name: str) -> ObjectStructureInfo | None:
        self._ensure()
        return self._by_os.get(name.lower())

    def for_object(self, mbo: str) -> ObjectStructureInfo | None:
        """Best object structure exposing a Maximo business object.

        Ranked by: signal strength, then the canonical MXAPI* integration
        structure, then field count. Field count matters because narrow views
        exist alongside full ones - MXAPIWOCHANGESTATUS exposes 12 WORKORDER
        fields where MXAPIWO exposes 604, and validating against the narrow one
        would reject fields that genuinely exist.
        """
        self._ensure()
        entries = self._by_mbo.get(mbo.lower())
        if not entries:
            return None

        def rank(entry: tuple[int, str]) -> tuple:
            strength, os_key = entry
            info = self._by_os[os_key]
            return (
                -strength,                                # strong signals first
                0 if os_key.startswith("mxapi") else 1,   # canonical API structure
                1 if os_key.startswith(_DERIVED_PREFIXES) else 0,  # not a report/conversion view
                -len(info.attributes),                    # richest field set
                len(os_key),
            )

        return self._by_os[min(entries, key=rank)[1]]

    def object_exists(self, mbo: str) -> bool:
        self._ensure()
        return mbo.lower() in self._by_mbo

    def attribute_exists(self, mbo: str, attribute: str) -> bool:
        info = self.for_object(mbo)
        return bool(info and info.attribute(attribute))

    def attribute(self, mbo: str, attribute: str) -> AttributeInfo | None:
        info = self.for_object(mbo)
        return info.attribute(attribute) if info else None

    def known_objects(self) -> list[str]:
        self._ensure()
        return sorted(m.upper() for m in self._by_mbo)

    def suggest_objects(self, name: str, limit: int = 5) -> list[str]:
        self._ensure()
        return [
            m.upper()
            for m in difflib.get_close_matches(name.lower(), self._by_mbo.keys(), n=limit, cutoff=0.6)
        ]

    def suggest_attributes(self, mbo: str, attribute: str, limit: int = 5) -> list[str]:
        info = self.for_object(mbo)
        if not info:
            return []
        return [
            a.upper()
            for a in difflib.get_close_matches(attribute.lower(), info.attributes.keys(), n=limit, cutoff=0.6)
        ]

    def search(self, term: str, limit: int = 20) -> list[ObjectStructureInfo]:
        """Substring search across object-structure name and description."""
        self._ensure()
        term = term.lower()
        hits = [
            info
            for info in self._by_os.values()
            if term in info.os_name.lower() or term in info.mbo.lower() or term in info.description.lower()
        ]
        hits.sort(key=lambda i: (0 if term in i.mbo.lower() else 1, len(i.os_name)))
        return hits[:limit]


@lru_cache(maxsize=4)
def catalog(schema_dir: Path, apimeta_path: Path | None = None) -> SchemaCatalog:
    return SchemaCatalog(schema_dir, apimeta_path)
