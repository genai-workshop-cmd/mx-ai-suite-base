"""AI Brain Feedback Store — captures human corrections at the gate for auto-learning.

When a reviewer approves a document with a comment, or when they request revision
(which includes a correction reason), the feedback is:
  1. Written to a dedicated corrections/ skill file per doc_type
  2. Indexed into the vector store so future agents find it in prior_art()

This closes the loop:
  Agent generates → FLAGS uncertain items → Human corrects at gate
  → Correction stored → Next agent for same doc_type sees the correction automatically
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.logging import get

if TYPE_CHECKING:
    from core.models import PhaseResult
    from pipeline.state import RunState

log = get("suite.brain.feedback")

_CORRECTIONS_HEADER = """\
# AI Brain — Auto-Learned Corrections
*This file is machine-written. Do not edit manually.*
*Each entry is a human-verified correction recorded at the approval gate.*
*Agents load this file automatically via prior_art() search.*

---

"""


class FeedbackStore:
    """Records gate corrections and updates the corrections skill file for the doc_type."""

    def __init__(self, skills_dir: Path, audit_log: Path) -> None:
        self.skills_dir = skills_dir
        self.audit_log = audit_log
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _corrections_path(self, doc_type: str) -> Path:
        return self.skills_dir / f"corrections_{doc_type}.md"

    def record(
        self,
        *,
        doc_type: str,
        business_process: str,
        run_id: str,
        reviewer: str,
        comment: str,
        flags: list[dict],
        gate_action: str,  # "approved" | "revision_requested"
    ) -> None:
        """Record a gate decision with its comment as a correction entry."""
        if not comment or comment.strip() in ("", "Auto-approved by --auto"):
            return  # nothing to learn from a blank or auto-approval

        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = self._corrections_path(doc_type)

        # Build the correction entry
        flag_summary = ""
        if flags:
            flag_lines = []
            for f in flags[:10]:  # cap at 10 flags per entry
                section = f.get("section", "")
                item = f.get("item", "")
                reason = f.get("reason", "")
                flag_lines.append(f"  - FLAG: {section} | {item} | {reason}")
            flag_summary = "\n**Flags raised by agent:**\n" + "\n".join(flag_lines)

        entry = (
            f"## Correction [{timestamp}]\n"
            f"- **Process:** {business_process}  **DocType:** {doc_type}  **Run:** {run_id}\n"
            f"- **Reviewer:** {reviewer}  **Action:** {gate_action}\n"
            f"- **Reviewer Comment / Correction:**\n  > {comment.strip()}\n"
            f"{flag_summary}\n\n---\n\n"
        )

        # Append to corrections file (create with header if new)
        if not path.exists():
            path.write_text(_CORRECTIONS_HEADER + entry, encoding="utf-8")
        else:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(entry)

        # Append to audit log
        self._audit(
            doc_type=doc_type,
            business_process=business_process,
            run_id=run_id,
            reviewer=reviewer,
            gate_action=gate_action,
            comment=comment,
            timestamp=timestamp,
        )
        log.info(
            "feedback recorded: %s/%s by %s (%s)",
            business_process, doc_type, reviewer, gate_action,
        )

    def _audit(self, **record: object) -> None:
        with self.audit_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def corrections_skill(self, doc_type: str) -> str:
        """Return the corrections skill file content for injection into agent prompts."""
        path = self._corrections_path(doc_type)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
