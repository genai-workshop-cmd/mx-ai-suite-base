"""AI Brain document store (blueprint section 7.1 and 7.4).

Artifacts are UTF-8 markdown with YAML front matter, laid out as:

    brain/store/<business_process>/<doc_type>/<doc_id>/v1.md
                                                      /v2.md
                                                      /latest.md   (copy of newest)

Write safety, as specified:
  * dry-run by default - `propose()` returns a WriteProposal, nothing touches disk
  * versioned - `commit()` always creates v(N+1), never overwrites
  * logged - every commit appends a JSON Lines audit record
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from core.config import BrainConfig
from core.errors import BrainError
from core.logging import get
from core.models import BrainDocument

log = get("suite.brain.store")

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str, max_len: int = 60) -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (s[:max_len].rstrip("-")) or "untitled"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class WriteProposal:
    """What a commit would do. Shown to the user before anything is written."""

    doc_id: str
    title: str
    doc_type: str
    business_process: str
    target_path: Path
    version: int
    is_update: bool
    previous_version: int | None
    bytes: int
    diff_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type,
            "business_process": self.business_process,
            "target_path": str(self.target_path),
            "version": self.version,
            "is_update": self.is_update,
            "previous_version": self.previous_version,
            "bytes": self.bytes,
            "diff_summary": self.diff_summary,
        }


class BrainStore:
    """Versioned markdown store with an append-only audit log."""

    def __init__(self, cfg: BrainConfig) -> None:
        self.cfg = cfg
        self.root = cfg.store_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_log = cfg.audit_log
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    def doc_dir(self, business_process: str, doc_type: str, doc_id: str) -> Path:
        return self.root / business_process.upper() / doc_type.lower() / doc_id

    def make_doc_id(self, title: str, doc_type: str) -> str:
        return f"{doc_type.lower()}-{slug(title, 48)}"

    # -- read --------------------------------------------------------------
    def load(self, path: Path) -> BrainDocument:
        if not path.exists():
            raise BrainError(f"Brain document not found: {path}")
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        return BrainDocument(
            doc_id=meta.get("doc_id", path.parent.name),
            title=meta.get("title", path.stem),
            doc_type=meta.get("doc_type", "unknown"),
            business_process=meta.get("business_process", "CU"),
            version=int(meta.get("version", 1)),
            created=meta.get("created", ""),
            updated=meta.get("updated", ""),
            run_id=meta.get("run_id", ""),
            agent=meta.get("agent", ""),
            change_items=list(meta.get("change_items", []) or []),
            tags=list(meta.get("tags", []) or []),
            body=body,
            path=str(path),
        )

    def latest(self, business_process: str, doc_type: str, doc_id: str) -> BrainDocument | None:
        path = self.doc_dir(business_process, doc_type, doc_id) / "latest.md"
        return self.load(path) if path.exists() else None

    def versions(self, business_process: str, doc_type: str, doc_id: str) -> list[int]:
        d = self.doc_dir(business_process, doc_type, doc_id)
        if not d.exists():
            return []
        out = []
        for p in d.glob("v*.md"):
            try:
                out.append(int(p.stem[1:]))
            except ValueError:
                continue
        return sorted(out)

    def iter_documents(self, *, latest_only: bool = True) -> Iterator[BrainDocument]:
        """Walk every document in the store."""
        pattern = "**/latest.md" if latest_only else "**/v*.md"
        for path in sorted(self.root.glob(pattern)):
            try:
                yield self.load(path)
            except (BrainError, yaml.YAMLError) as exc:
                log.warning("skipping unreadable brain document %s: %s", path, exc)

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        by_process: dict[str, int] = {}
        total = 0
        for doc in self.iter_documents():
            total += 1
            by_type[doc.doc_type] = by_type.get(doc.doc_type, 0) + 1
            by_process[doc.business_process] = by_process.get(doc.business_process, 0) + 1
        return {
            "documents": total,
            "by_type": dict(sorted(by_type.items())),
            "by_process": dict(sorted(by_process.items())),
            "store_dir": str(self.root),
        }

    # -- write -------------------------------------------------------------
    def propose(
        self,
        *,
        title: str,
        doc_type: str,
        business_process: str,
        body: str,
        doc_id: str | None = None,
        run_id: str = "",
        agent: str = "",
        change_items: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> WriteProposal:
        """Describe the write without performing it (dry-run by default)."""
        doc_id = doc_id or self.make_doc_id(title, doc_type)
        existing = self.versions(business_process, doc_type, doc_id)
        previous = existing[-1] if existing else None
        version = (previous or 0) + 1
        target = self.doc_dir(business_process, doc_type, doc_id) / f"v{version}.md"

        diff = ""
        if previous is not None:
            old = self.load(self.doc_dir(business_process, doc_type, doc_id) / f"v{previous}.md")
            diff = summarise_diff(old.body, body)

        return WriteProposal(
            doc_id=doc_id,
            title=title,
            doc_type=doc_type,
            business_process=business_process.upper(),
            target_path=target,
            version=version,
            is_update=previous is not None,
            previous_version=previous,
            bytes=len(body.encode("utf-8")),
            diff_summary=diff,
            metadata={
                "run_id": run_id,
                "agent": agent,
                "change_items": change_items or [],
                "tags": tags or [],
            },
        )

    def commit(self, proposal: WriteProposal, body: str) -> BrainDocument:
        """Apply a proposal: write v(N+1), refresh latest.md, append audit."""
        target = proposal.target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise BrainError(
                f"Refusing to overwrite an existing version: {target}",
                remedy="Re-run propose() to get the next free version number.",
            )

        created = _now()
        if proposal.previous_version is not None:
            prev = self.load(target.parent / f"v{proposal.previous_version}.md")
            created = prev.created or created

        meta = {
            "doc_id": proposal.doc_id,
            "title": proposal.title,
            "doc_type": proposal.doc_type,
            "business_process": proposal.business_process,
            "version": proposal.version,
            "created": created,
            "updated": _now(),
            "run_id": proposal.metadata.get("run_id", ""),
            "agent": proposal.metadata.get("agent", ""),
            "change_items": proposal.metadata.get("change_items", []),
            "tags": proposal.metadata.get("tags", []),
        }
        content = render_front_matter(meta) + body.rstrip() + "\n"
        target.write_text(content, encoding="utf-8")
        shutil.copyfile(target, target.parent / "latest.md")

        self._audit(
            action="update" if proposal.is_update else "create",
            doc_id=proposal.doc_id,
            version=proposal.version,
            agent=meta["agent"],
            run_id=meta["run_id"],
            path=str(target),
            bytes=len(content.encode("utf-8")),
        )
        log.info(
            "brain %s: %s v%d (%s)",
            "updated" if proposal.is_update else "created",
            proposal.doc_id,
            proposal.version,
            proposal.doc_type,
        )
        return self.load(target)

    def write(self, *, confirm: bool = False, **kwargs: Any) -> tuple[WriteProposal, BrainDocument | None]:
        """Propose, and commit only when explicitly confirmed."""
        body = kwargs.pop("body")
        proposal = self.propose(body=body, **kwargs)
        if not confirm and self.cfg.dry_run_default:
            return proposal, None
        return proposal, self.commit(proposal, body)

    def copy_companion(self, doc: "BrainDocument", src: Path) -> None:
        """Copy a companion file (docx/xlsx/…) into the same folder as the versioned .md.

        Writes both a versioned copy (v<N>.<ext>) and refreshes latest.<ext>.
        Safe to call after commit() — version number is read from doc.
        """
        ext = src.suffix  # e.g. ".docx" or ".xlsx"
        dest_dir = Path(doc.path).parent
        versioned = dest_dir / f"v{doc.version}{ext}"
        latest = dest_dir / f"latest{ext}"
        if not versioned.exists():
            shutil.copy2(src, versioned)
        shutil.copy2(src, latest)
        log.info("brain companion: %s -> %s", src.name, versioned.name)

    # -- audit -------------------------------------------------------------
    def _audit(self, **record: Any) -> None:
        record["timestamp"] = _now()
        with self.audit_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def audit_tail(self, limit: int = 50) -> list[dict]:
        if not self.audit_log.exists():
            return []
        lines = self.audit_log.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))


# --------------------------------------------------------------------------
# front matter helpers
# --------------------------------------------------------------------------
def parse_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), raw[match.end() :]


def render_front_matter(meta: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{dumped}---\n\n"


def summarise_diff(old: str, new: str) -> str:
    """Plain-language summary of what a new version changes."""
    import difflib

    old_lines = old.splitlines()
    new_lines = new.splitlines()
    added = removed = 0
    for line in difflib.ndiff(old_lines, new_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    if not added and not removed:
        return "No textual change."

    old_heads = {ln.strip() for ln in old_lines if ln.startswith("#")}
    new_heads = {ln.strip() for ln in new_lines if ln.startswith("#")}
    sections = []
    if new_heads - old_heads:
        sections.append(f"{len(new_heads - old_heads)} new section(s)")
    if old_heads - new_heads:
        sections.append(f"{len(old_heads - new_heads)} removed section(s)")
    tail = f" ({', '.join(sections)})" if sections else ""
    return f"+{added} / -{removed} lines{tail}"
