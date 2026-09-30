"""Agent 0 - Requirements Analysis Agent.

Acts as a senior IBM Maximo consultant in a Scrum Master role BEFORE any design
documents are created:
  - Validates every referenced Maximo object and field against the schema catalog
  - Determines whether each requirement is achievable via OOB config, customisation,
    or integration
  - Asks specific clarifying questions for anything ambiguous or missing
  - The reviewer answers the questions at the gate; those answers are passed to FDD

This phase prevents the FDD/TDD from being generated with wrong fields, empty
sections, or generic placeholder content.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.models import Artifact, DuplicateDecision, Phase
from rendering.docx_writer import render

from .base import BaseAgent, Composition

_IMPL_TYPE: dict[str, str] = {
    "config": "OOB Configuration",
    "customisation": "Customisation — Jython Automation Script",
    "integration": "Integration — MIF Object Structure / Enterprise Service",
    "workflow": "Workflow Configuration",
    "report": "BIRT Report",
    "security": "OOB Security Configuration",
    "data": "Data Load (MXLoader / Data Import)",
    "unknown": "Cannot Determine — clarification required",
}

_SECTIONS_FDD: dict[str, list[str]] = {
    "config":        ["1. Document Control", "2. Executive Summary", "4. Scope",
                      "5. Functional Requirements", "8. Assumptions", "9. Open Questions"],
    "customisation": ["1. Document Control", "2. Executive Summary", "3. Business Context",
                      "4. Scope", "5. Functional Requirements", "6. Business Rules",
                      "7. Process Flow", "8. Assumptions", "9. Open Questions"],
    "integration":   ["1. Document Control", "2. Executive Summary", "4. Scope",
                      "5. Functional Requirements", "8. Assumptions", "9. Open Questions"],
    "workflow":      ["1. Document Control", "2. Executive Summary", "3. Business Context",
                      "4. Scope", "5. Functional Requirements", "6. Business Rules",
                      "7. Process Flow", "8. Assumptions", "9. Open Questions"],
    "security":      ["1. Document Control", "2. Executive Summary", "4. Scope",
                      "5. Functional Requirements", "8. Assumptions", "9. Open Questions"],
    "data":          ["1. Document Control", "2. Executive Summary", "4. Scope",
                      "5. Functional Requirements", "8. Assumptions", "9. Open Questions"],
    "report":        ["1. Document Control", "2. Executive Summary", "4. Scope",
                      "5. Functional Requirements", "8. Assumptions", "9. Open Questions"],
    "unknown":       ["1. Document Control", "2. Executive Summary", "4. Scope",
                      "5. Functional Requirements", "9. Open Questions"],
}

_SECTIONS_TDD: dict[str, list[str]] = {
    "config":        ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "4. Database Configuration", "5. Application Configuration",
                      "9. Estimation", "10. Implementation Sequence"],
    "customisation": ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "4. Database Configuration", "6. Automation Scripts",
                      "9. Estimation", "10. Implementation Sequence"],
    "integration":   ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "7. Integration Design", "9. Estimation", "10. Implementation Sequence"],
    "workflow":      ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "5. Application Configuration", "9. Estimation", "10. Implementation Sequence"],
    "security":      ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "8. Security", "9. Estimation", "10. Implementation Sequence"],
    "data":          ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "9. Estimation", "10. Implementation Sequence"],
    "report":        ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "9. Estimation", "10. Implementation Sequence"],
    "unknown":       ["1. Document Control", "2. Solution Overview", "3. Change Register",
                      "9. Estimation"],
}


class AnalysisAgent(BaseAgent):
    agent_id = "0"
    name = "Requirements Analysis Agent"
    phase = Phase.ANALYSIS
    doc_type = "analysis"
    role = (
        "Act as a senior IBM Maximo consultant in a Scrum Master role. BEFORE any design "
        "documents are created: validate every referenced Maximo object and field against "
        "the schema catalog, determine whether each requirement is achievable via OOB "
        "configuration, Jython customisation, or MIF integration, state the recommended "
        "implementation approach for each, and raise specific clarifying questions for "
        "anything that is ambiguous or whose Maximo grounding is unknown. "
        "Do NOT produce a design — only analyse and question."
    )
    inputs_description = (
        "- Extracted requirements and change items from the uploaded material\n"
        "- Maximo object/attribute validation results from the schema catalog\n"
        "- Live Maximo environment facts (if connected)"
    )
    output_format = (
        "Markdown document:\n"
        "# Requirements Analysis\n\n"
        "## Summary\n"
        "(2-3 sentences: count, overall feasibility, any show-stoppers)\n\n"
        "## Requirement-by-Requirement Analysis\n"
        "One ### subsection per requirement. For each:\n"
        "  - **Maximo Object / Field:** confirmed name from VALIDATED MAXIMO FACTS, or 'NOT FOUND'\n"
        "  - **Implementation Type:** OOB Configuration | Customisation (Jython) | Integration | etc.\n"
        "  - **Recommended Approach:** 2-4 bullet steps — name the exact Maximo application(s)\n"
        "  - **FDD Sections:** list only the sections that will appear in the FDD\n"
        "  - **TDD Sections:** list only the sections that will appear in the TDD\n"
        "  - **Clarifying Questions:** numbered list, or 'None — requirement is clear'\n\n"
        "## Open Questions (consolidated)\n"
        "(All questions numbered — reviewer answers these in the gate comment before approving)\n\n"
        "## Recommended Implementation Plan\n"
        "(Order of Maximo applications to open, overall complexity, key risks)"
    )
    skill_files = ("mx_core_SKILL.md", "mx_tech_config_SKILL.md", "mx_functional_docs_SKILL.md")

    # -- gather ------------------------------------------------------------
    def gather(self) -> dict[str, Any]:
        process = self.ctx.process
        items = self.change_items()

        for item in items:
            self.ctx.validator.check_change_item(item, process, self.report)

        attr_specs: dict[str, str] = {}
        for item in items:
            if item.maximo_object and item.maximo_attribute:
                key = f"{item.maximo_object}.{item.maximo_attribute}"
                spec = self.ctx.validator.attribute_spec(item.maximo_object, item.maximo_attribute)
                if spec:
                    attr_specs[key] = spec

        return {
            "requirements": self.ctx.state.requirements,
            "change_items": items,
            "attr_specs": attr_specs,
            "validation_summary": self.report.summary(),
        }

    # -- compose -----------------------------------------------------------
    def compose(self, facts: dict[str, Any], duplicate: DuplicateDecision) -> Composition:
        user_prompt = self._user_prompt(facts)
        text, generated_by = self.ask_model(user_prompt, max_tokens=5000)

        if text:
            body, flags = self.parse_flags(text, "Analysis")
        else:
            body = self._deterministic(facts)
            flags = []
            generated_by = "deterministic"

        n = len(facts["change_items"])
        summary = (
            f"Requirements analysis for {n} change item(s). "
            f"{self.report.summary()} "
            "Answer the Open Questions in the gate comment before approving — "
            "your answers will guide the FDD and TDD agents."
        )
        return Composition(body=body, summary=summary, flags=flags, generated_by=generated_by)

    def _user_prompt(self, facts: dict[str, Any]) -> str:
        items_text = "\n".join(
            f"- [{i.change_type.value}] {i.title}\n"
            f"  Object: {i.maximo_object or 'NOT IDENTIFIED'} | "
            f"Field: {i.maximo_attribute or 'NOT IDENTIFIED'} | "
            f"App: {i.maximo_app or 'NOT IDENTIFIED'}\n"
            f"  Description: {i.description[:400]}"
            for i in facts["change_items"]
        )
        specs_text = (
            "\n".join(f"- {k}: {v}" for k, v in facts["attr_specs"].items())
            or "(no attribute specs retrieved — field names may need confirmation)"
        )
        return (
            f"RUN: {self.ctx.state.title}\n"
            f"BUSINESS PROCESS: {self.ctx.process_name}\n\n"
            f"CHANGE ITEMS TO ANALYSE:\n{items_text}\n\n"
            f"MAXIMO FIELD SPECS FROM SCHEMA:\n{specs_text}\n\n"
            f"VALIDATED MAXIMO FACTS:\n{self.validated_facts_block()}\n\n"
            f"SOURCE MATERIAL (first 4000 chars):\n{self.ctx.source_material[:4000]}\n\n"
            "For EACH change item above:\n"
            "1. Confirm the Maximo object/field from VALIDATED MAXIMO FACTS, or flag 'NOT FOUND'\n"
            "   - If a field name is mentioned (e.g. 'MEMO') without an object, search VALIDATED MAXIMO "
            "FACTS for it — which object does it belong to? If not found at all, raise it as a question.\n"
            "2. Determine implementation type: OOB Config / Customisation (Jython) / Integration / etc.\n"
            "3. State the recommended Maximo implementation steps (2-4 bullets, exact application names)\n"
            "4. List the FDD sections that will appear for this item (omit irrelevant ones)\n"
            "5. List the TDD sections that will appear for this item (omit irrelevant ones)\n"
            "6. Raise specific clarifying questions — what is ambiguous or missing?\n\n"
            "Then write the consolidated Open Questions list and the Recommended Implementation Plan.\n\n"
            "CRITICAL: Be specific. 'Add Domain for Memo field' needs to know: which object has MEMO? "
            "what domain type (ALN/NUM/SYN)? what values? which sites?\n\n"
            "Write the Requirements Analysis document now."
        )

    def _deterministic(self, facts: dict[str, Any]) -> str:
        items = facts["change_items"]
        req_sections: list[str] = []
        all_questions: list[str] = []
        qn = 1

        for idx, item in enumerate(items, 1):
            ct = item.change_type.value
            impl_type = _IMPL_TYPE.get(ct, "Cannot Determine")
            fdd_secs = ", ".join(_SECTIONS_FDD.get(ct, _SECTIONS_FDD["unknown"]))
            tdd_secs = ", ".join(_SECTIONS_TDD.get(ct, _SECTIONS_TDD["unknown"]))

            obj_line = (
                f"`{item.maximo_object}` — found in schema"
                if item.maximo_object
                else "**NOT IDENTIFIED** — must be confirmed before FDD"
            )
            field_line = (
                f"`{item.maximo_attribute}` on `{item.maximo_object}`"
                if item.maximo_attribute and item.maximo_object
                else "**NOT IDENTIFIED** — must be confirmed"
            )

            questions: list[str] = []
            if not item.maximo_object:
                q = f"Req {idx}: Which Maximo object/application does '{item.title}' apply to?"
                questions.append(q)
                all_questions.append(f"{qn}. {q}")
                qn += 1
            if not item.maximo_attribute and ct == "config":
                q = f"Req {idx}: What is the exact field/attribute name in Maximo for '{item.title}'?"
                questions.append(q)
                all_questions.append(f"{qn}. {q}")
                qn += 1
            if ct == "config" and "domain" in item.description.lower():
                q = f"Req {idx}: What domain values should be configured? Please provide the complete list."
                questions.append(q)
                all_questions.append(f"{qn}. {q}")
                qn += 1
                q2 = f"Req {idx}: Should this domain apply to all sites/orgs or specific ones only?"
                questions.append(q2)
                all_questions.append(f"{qn}. {q2}")
                qn += 1
            if ct == "integration":
                q = f"Req {idx}: What is the external system? What are the endpoint URL and authentication details?"
                questions.append(q)
                all_questions.append(f"{qn}. {q}")
                qn += 1
            if ct == "unknown":
                q = f"Req {idx}: Can you clarify '{item.title}' in Maximo terms — is this a field, screen, script, or report change?"
                questions.append(q)
                all_questions.append(f"{qn}. {q}")
                qn += 1

            if not questions:
                questions_text = "None — requirement is clear enough to proceed."
            else:
                questions_text = "\n".join(f"  {j+1}. {q}" for j, q in enumerate(questions))

            req_sections.append(
                f"### {idx}. {item.title}\n\n"
                f"- **Maximo Object:** {obj_line}\n"
                f"- **Maximo Field:** {field_line}\n"
                f"- **Implementation Type:** {impl_type}\n"
                f"- **Recommended Approach:** Confirm object/field, then proceed with design\n"
                f"- **FDD Sections:** {fdd_secs}\n"
                f"- **TDD Sections:** {tdd_secs}\n"
                f"- **Clarifying Questions:**\n{questions_text}\n"
            )

        if not all_questions:
            open_qs = "None — all requirements are clear. Approve this gate to proceed to FDD."
        else:
            open_qs = "\n".join(all_questions)

        has_custom = any(i.change_type.value in ("customisation", "integration", "workflow") for i in items)
        complexity = "High" if has_custom else "Low" if len(items) == 1 else "Medium"

        return f"""# Requirements Analysis

> **Agent 0 — Requirements Analysis** | Run: {self.ctx.state.run_id}
> Validation source: {self.ctx.validator.source_label()}
>
> **Action required:** Answer the Open Questions below in the gate comment box before approving.
> Your answers will be passed directly to the FDD and TDD agents.

## Summary

{len(items)} requirement(s) identified for business process **{self.ctx.process_name}**.
Overall complexity: **{complexity}**. {self.report.summary()}

## Requirement-by-Requirement Analysis

{chr(10).join(req_sections)}
## Open Questions (consolidated)

> Enter your answers in the **gate comment box** below. Number them to match.

{open_qs}

## Recommended Implementation Plan

1. Answer all open questions above before approving this gate.
2. **FDD Agent** will generate the Functional Design Document (only relevant sections) using your answers.
3. Review and approve the FDD before TDD generation.
4. **Build agents** will implement the approved design.

Overall estimated complexity: **{complexity}**
"""

    # -- emit --------------------------------------------------------------
    def emit(self, composition: Composition) -> list[Artifact]:
        out = self.ctx.artifact_dir("00_analysis")
        artifacts: list[Artifact] = []

        md_path = out / "Requirements_Analysis.md"
        md_path.write_text(composition.body, encoding="utf-8")
        artifacts.append(
            self.register_artifact(md_path, kind="md", description="Requirements analysis with open questions")
        )

        docx_path = out / "Requirements_Analysis.docx"
        render(
            composition.body,
            template=self.ctx.cfg.template_path("fdd"),
            target=docx_path,
            title=f"{self.ctx.process_name} - Requirements Analysis",
            subtitle=self.ctx.state.title,
        )
        artifacts.append(
            self.register_artifact(docx_path, kind="docx", description="Requirements analysis document")
        )

        return artifacts
