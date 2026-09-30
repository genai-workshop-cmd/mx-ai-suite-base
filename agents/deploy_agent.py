"""Agent 5 - Deployment Agent (blueprint section 4).

Assembles every approved artifact into a Migration Manager-compatible package,
writes the ordered deployment runbook, and optionally commits to Git.

This is the only agent permitted to write to Maximo, and only after the final
user gate. `deploy_to_maximo()` refuses to act without an explicit approval
token, so an accidental call cannot touch a live environment.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.errors import GateError
from core.models import Artifact, DuplicateDecision, GateStatus, Phase
from rendering.package import PackageEntry, build_package, commit_artifacts

from .base import BaseAgent, Composition


class DeployAgent(BaseAgent):
    agent_id = "5"
    name = "Deployment Agent"
    phase = Phase.DEPLOY
    doc_type = "deployment"
    role = (
        "Assemble every approved artifact into a deployment package for the target "
        "Maximo environment and write the ordered runbook that applies it safely."
    )
    inputs_description = "- All approved artifacts from the previous phases\n- The change item register"
    output_format = (
        "Markdown with exactly these sections:\n"
        "# Deployment Runbook\n"
        "## 1. Package Contents\n"
        "## 2. Pre-deployment Checklist\n"
        "## 3. Deployment Sequence\n"
        "## 4. Validation Steps\n"
        "## 5. Rollback Plan\n"
        "## 6. Sign-off\n"
    )
    skill_files = ("mx_core_SKILL.md",)

    # -- gather ------------------------------------------------------------
    def gather(self) -> dict[str, Any]:
        collected: list[Artifact] = []
        for phase in (Phase.FDD, Phase.TDD, Phase.BUILD_CONFIG, Phase.BUILD_INTEGRATION, Phase.TEST):
            result = self.ctx.state.result(phase)
            if not result or not result.ok:
                continue
            gate = self.ctx.state.gate(phase)
            if gate.status is not GateStatus.APPROVED:
                self.log.warning(
                    "phase %s is not approved (%s) - its artifacts are excluded from the package",
                    phase.value, gate.status.value,
                )
                continue
            collected.extend(result.artifacts)

        return {
            "artifacts": collected,
            "items": self.change_items(),
            "unapproved": [
                p.value
                for p in (Phase.FDD, Phase.TDD, Phase.BUILD_CONFIG, Phase.BUILD_INTEGRATION, Phase.TEST)
                if self.ctx.state.result(p)
                and self.ctx.state.gate(p).status is not GateStatus.APPROVED
            ],
        }

    # -- compose -----------------------------------------------------------
    def compose(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> Composition:
        text, generated_by = self.ask_model(self._user_prompt(facts), max_tokens=6000)
        if text:
            body, flags = self.parse_flags(text, "Deployment")
        else:
            body = self._deterministic(facts)
            flags = []
            generated_by = "deterministic"

        summary = (
            f"Deployment package for {len(facts['artifacts'])} approved artifact(s) "
            f"across {len(facts['items'])} change item(s)."
        )
        if facts["unapproved"]:
            summary += f" Excluded unapproved phases: {', '.join(facts['unapproved'])}."
        return Composition(body=body, summary=summary, flags=flags, generated_by=generated_by)

    def _user_prompt(self, facts: dict[str, Any]) -> str:
        arts = "\n".join(f"- {a.name} ({a.kind}) from {a.agent}: {a.description}" for a in facts["artifacts"])
        items = "\n".join(f"- {i.id} [{i.change_type.value}] {i.title}" for i in facts["items"])
        return (
            f"RUN: {self.ctx.state.title}\nBUSINESS PROCESS: {self.ctx.process_name}\n"
            f"TARGET PLATFORM: IBM Maximo {self.ctx.cfg.maximo_version}\n\n"
            f"APPROVED ARTIFACTS:\n{arts}\n\nCHANGE ITEMS:\n{items}\n\n"
            f"Write the Deployment Runbook now.{self.revision_block()}"
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        artifacts: list[Artifact] = facts["artifacts"]
        items = facts["items"]

        contents = ["| Artifact | Type | Produced by | Purpose |", "|---|---|---|---|"]
        for a in artifacts:
            contents.append(f"| `{a.name}` | {a.kind} | {a.agent} | {_cell(a.description)} |")

        has_db = any(a.name == "dbconfig.xml" for a in artifacts)
        has_app = any(a.name == "app_designer_export.xml" for a in artifacts)
        has_scripts = any(a.kind == "py" for a in artifacts)
        has_mif = any(a.name.startswith("mif_components") for a in artifacts)

        sequence: list[str] = ["1. Take a full backup of the target database and a Maximo configuration export."]
        n = 2
        if has_db:
            sequence.append(
                f"{n}. Enable **Admin Mode**. Import `dbconfig.xml` through Database Configuration, "
                f"then run **Apply Configuration Changes**. Disable Admin Mode when it completes."
            )
            n += 1
        if has_app:
            sequence.append(
                f"{n}. Import `app_designer_export.xml` in **Application Designer** and save the application."
            )
            n += 1
        if has_scripts:
            sequence.append(
                f"{n}. Import each file under `scripts/` in **Automation Scripts**, create the launch "
                f"point named in the Config Build Document, and set the status to Active."
            )
            n += 1
        if has_mif:
            sequence.append(
                f"{n}. Apply `mif_components.xml`: create the Object Structure, Publish Channel / "
                f"Enterprise Service, External System and End Point, then enable the external system."
            )
            n += 1
        sequence.append(f"{n}. Restart the Maximo application server if the DB configuration changed.")
        n += 1
        sequence.append(f"{n}. Execute the smoke tests in section 4.")

        validation = [
            f"{i}. Confirm change item {item.id} - {_cell(item.title, 90)}"
            for i, item in enumerate(items, 1)
        ] or ["1. Confirm the affected applications open without error."]
        validation.append(f"{len(validation) + 1}. Run the test cases in `testcase.xlsx` and record the results.")

        unapproved = ""
        if facts["unapproved"]:
            unapproved = (
                f"\n> **Warning** - these phases were not approved and are NOT in the package: "
                f"{', '.join(facts['unapproved'])}.\n"
            )

        return f"""# Deployment Runbook

| Field | Value |
|---|---|
| Business process | {self.ctx.process_name} |
| Run ID | {self.ctx.state.run_id} |
| Target platform | IBM Maximo {self.ctx.cfg.maximo_version} |
| Change items | {len(items)} |
| Artifacts | {len(artifacts)} |
{unapproved}
## 1. Package Contents

{chr(10).join(contents)}

## 2. Pre-deployment Checklist

- [ ] All user gates approved and recorded.
- [ ] Database backup taken and verified restorable.
- [ ] Current Maximo configuration exported as a rollback baseline.
- [ ] Target environment confirmed: not production unless this is the production window.
- [ ] Deployment window agreed and users notified.
- [ ] Rollback owner identified and available.

## 3. Deployment Sequence

{chr(10).join(sequence)}

## 4. Validation Steps

{chr(10).join(validation)}

## 5. Rollback Plan

1. Stop the Maximo application server.
2. Restore the database backup taken in step 1 of section 3.
3. Re-import the configuration baseline exported in the pre-deployment checklist.
4. Set any imported automation script to **Draft** so it cannot fire.
5. Disable the external system and publish channel created for this release.
6. Restart the application server and confirm the pre-change baseline behaviour.

## 6. Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Architect | | | |
| Project Manager | | | |
| Maximo Administrator | | | |

Deployment must not proceed until this section is complete.
"""

    # -- emit --------------------------------------------------------------
    def emit(self, composition: Composition) -> list[Artifact]:
        out = self.ctx.artifact_dir("05_deploy")
        artifacts: list[Artifact] = []

        runbook = out / "Deployment_Runbook.md"
        runbook.write_text(composition.body, encoding="utf-8")
        artifacts.append(self.register_artifact(runbook, kind="md", description="Ordered deployment runbook"))

        entries: list[PackageEntry] = [PackageEntry(arcname="RUNBOOK.md", text=composition.body)]
        for a in self.facts["artifacts"]:
            path = Path(a.path)
            if not path.exists():
                continue
            entries.append(PackageEntry(arcname=f"{_folder(a)}/{path.name}", source=path))

        manifest = {
            "run_id": self.ctx.state.run_id,
            "title": self.ctx.state.title,
            "business_process": self.ctx.process_name,
            "maximo_version": self.ctx.cfg.maximo_version,
            "generator": f"{self.ctx.cfg.project_name} v{self.ctx.cfg.version}",
            "change_items": [
                {"id": i.id, "title": i.title, "type": i.change_type.value, "object": i.maximo_object}
                for i in self.facts["items"]
            ],
            "gates": {
                phase: {"status": gate.status.value, "by": gate.decided_by, "at": gate.decided_at}
                for phase, gate in self.ctx.state.gates.items()
            },
        }
        package = build_package(entries, out / f"migration_package_{self.ctx.state.run_id}.zip", manifest=manifest)
        artifacts.append(
            self.register_artifact(
                package.path, kind="zip", description=f"Migration Manager package ({len(package.entries)} files)"
            )
        )

        manifest_path = out / "MANIFEST.json"
        manifest_path.write_text(json.dumps(package.manifest, indent=2), encoding="utf-8")
        artifacts.append(self.register_artifact(manifest_path, kind="json", description="Package manifest"))
        return artifacts

    # -- post-gate actions -------------------------------------------------
    def commit_to_git(self) -> dict[str, Any]:
        """Commit approved artifacts. Called after the final gate only."""
        gate = self.ctx.state.gate(Phase.DEPLOY)
        if gate.status is not GateStatus.APPROVED:
            raise GateError("The final deployment gate has not been approved.")

        result = self.ctx.state.result(Phase.DEPLOY)
        paths = [Path(a.path) for a in (result.artifacts if result else [])]
        paths.extend(Path(a.path) for a in self.facts.get("artifacts", []))

        outcome = commit_artifacts(
            repo=Path(self.ctx.cfg.runs_dir).parent,
            paths=[p for p in paths if p.exists()],
            message=(
                f"{self.ctx.process_name}: {self.ctx.state.title}\n\n"
                f"Run {self.ctx.state.run_id}. {len(self.facts.get('items', []))} change item(s). "
                f"Approved by {gate.decided_by or 'the deployment gate'}."
            ),
            tag=f"{self.ctx.process_name.lower()}-{self.ctx.state.run_id.lower()}",
        )
        return {"ok": outcome.ok, "commit": outcome.commit, "tag": outcome.tag, "detail": outcome.detail}

    def deploy_to_maximo(self, *, approval_token: str) -> dict[str, Any]:
        """Direct deployment. Intentionally gated and not enabled by default.

        The blueprint permits Agent 5 to write to Maximo, but only after the
        final human gate. Rather than ship an untested write path against a
        live environment, this refuses and points at the package, which is the
        supported route.
        """
        gate = self.ctx.state.gate(Phase.DEPLOY)
        if gate.status is not GateStatus.APPROVED or approval_token != self.ctx.state.run_id:
            raise GateError(
                "Direct deployment requires an approved final gate and a matching approval token."
            )
        return {
            "performed": False,
            "reason": (
                "Direct write-back to Maximo is disabled in this build. Apply the generated "
                "migration package through Migration Manager, following the runbook."
            ),
            "package": next(
                (a.path for a in (self.ctx.state.result(Phase.DEPLOY).artifacts if self.ctx.state.result(Phase.DEPLOY) else []) if a.kind == "zip"),
                "",
            ),
        }


def _folder(artifact: Artifact) -> str:
    return {
        "fdd": "01_functional_design",
        "tdd": "02_technical_design",
        "build_config": "03_configuration",
        "build_integration": "04_integration",
        "test": "05_test",
    }.get(artifact.phase, "99_other")


def _cell(text: str, width: int = 240) -> str:
    clean = " ".join((text or "").split()).replace("|", "\\|")
    return clean[:width] + ("..." if len(clean) > width else "")
