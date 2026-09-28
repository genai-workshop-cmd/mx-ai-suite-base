"""Deployment packaging for Agent 5.

Produces a Migration Manager-compatible bundle: the config XML, automation
scripts, integration definitions, a manifest and an ordered runbook, zipped
with a deterministic layout so two runs over the same inputs differ only by
timestamp.

Also handles the optional Git commit of approved artifacts.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get

log = get("suite.render.package")


@dataclass
class PackageEntry:
    arcname: str
    source: Path | None = None
    text: str | None = None

    def payload(self) -> bytes:
        if self.text is not None:
            return self.text.encode("utf-8")
        if self.source is not None and self.source.exists():
            return self.source.read_bytes()
        return b""


@dataclass
class PackageResult:
    path: Path
    entries: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


def build_package(
    entries: list[PackageEntry],
    target: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> PackageResult:
    """Zip the deployment bundle with a checksum manifest."""
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest or {})
    files: list[dict[str, Any]] = []

    payloads: list[tuple[str, bytes]] = []
    for entry in sorted(entries, key=lambda e: e.arcname):
        data = entry.payload()
        payloads.append((entry.arcname, data))
        files.append(
            {
                "path": entry.arcname,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    manifest["files"] = files
    manifest["file_count"] = len(files)
    manifest["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        # Fixed timestamp keeps the archive reproducible across runs.
        for arcname, data in payloads:
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
        info = zipfile.ZipInfo("MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, manifest_bytes)

    log.info("built deployment package %s (%d entries)", target.name, len(files) + 1)
    return PackageResult(path=target, entries=[f["path"] for f in files], manifest=manifest)


# --------------------------------------------------------------------------
# Git
# --------------------------------------------------------------------------
@dataclass
class GitResult:
    ok: bool
    commit: str = ""
    message: str = ""
    detail: str = ""
    tag: str = ""


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
        )
    except FileNotFoundError:
        return 127, "git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return 124, "git command timed out"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def commit_artifacts(
    repo: Path,
    paths: list[Path],
    message: str,
    *,
    tag: str = "",
) -> GitResult:
    """Commit approved artifacts. Never pushes - that stays a human action."""
    code, out = _git(["rev-parse", "--is-inside-work-tree"], repo)
    if code != 0:
        return GitResult(ok=False, detail=f"Not a git repository ({out[:120]}). Skipped commit.")

    rel: list[str] = []
    for p in paths:
        try:
            rel.append(str(p.resolve().relative_to(repo.resolve())))
        except ValueError:
            log.debug("skipping %s - outside the repository", p)
    if not rel:
        return GitResult(ok=False, detail="No artifacts inside the repository to commit.")

    code, out = _git(["add", "--", *rel], repo)
    if code != 0:
        return GitResult(ok=False, detail=f"git add failed: {out[:200]}")

    code, out = _git(["diff", "--cached", "--quiet"], repo)
    if code == 0:
        return GitResult(ok=True, detail="No changes to commit - artifacts already committed.")

    code, out = _git(["commit", "-m", message], repo)
    if code != 0:
        return GitResult(ok=False, detail=f"git commit failed: {out[:300]}")

    _, sha = _git(["rev-parse", "--short", "HEAD"], repo)
    result = GitResult(ok=True, commit=sha.strip(), message=message, detail=out[:200])

    if tag:
        code, out = _git(["tag", "-a", tag, "-m", message], repo)
        if code == 0:
            result.tag = tag
        else:
            result.detail += f" | tag failed: {out[:120]}"
    return result
