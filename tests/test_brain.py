"""AI Brain: versioned writes, audit trail, and search-before-create."""
from __future__ import annotations

import pytest

from ai_brain import Brain, SearchQuery


@pytest.fixture()
def brain(cfg):
    return Brain.build(cfg)


def _write(brain, title, body, doc_type="fdd"):
    _, doc = brain.store.write(
        confirm=True, title=title, doc_type=doc_type,
        business_process="CU", body=body, agent="test",
    )
    return doc


def test_write_creates_version_one(brain):
    doc = _write(brain, "CU Comment field", "# FDD\n\nAdd CUCOMMENT to CUJP.\n")
    assert doc.version == 1
    assert doc.doc_type == "fdd"
    assert "CUCOMMENT" in doc.body


def test_second_write_versions_rather_than_overwrites(brain):
    _write(brain, "CU Comment field", "# FDD\n\nv1 body\n")
    doc2 = _write(brain, "CU Comment field", "# FDD\n\nv1 body\n\n## Extra\nmore\n")
    assert doc2.version == 2
    versions = brain.store.versions("CU", "fdd", doc2.doc_id)
    assert versions == [1, 2], "history must be preserved, not overwritten"
    v1 = brain.store.load(brain.store.doc_dir("CU", "fdd", doc2.doc_id) / "v1.md")
    assert "Extra" not in v1.body


def test_dry_run_is_the_default(cfg):
    cfg.brain.dry_run_default = True
    brain = Brain.build(cfg)
    proposal, doc = brain.store.write(
        title="Dry run doc", doc_type="fdd", business_process="CU", body="# x\n"
    )
    assert doc is None, "a write must be proposed before it is applied"
    assert not proposal.target_path.exists()


def test_every_write_is_audited(brain):
    _write(brain, "Audited doc", "# FDD\n\nbody\n")
    entries = brain.store.audit_tail(5)
    assert entries and entries[0]["action"] == "create"
    assert entries[0]["doc_id"]


def test_duplicate_detection_fires_on_a_true_duplicate(brain):
    _write(
        brain, "CU Comment Field on CU Header",
        "# FDD\n\n## Requirement\nAdd a CU Comment field to the CU Header application "
        "and propagate it to the Work Order Description.\n",
    )
    brain.search.reindex(rebuild=True)

    hit = brain.search.find_duplicate(
        text="Add CU Comment attribute to CU Header app and copy it to the work order description",
        doc_type="fdd", business_process="CU",
    )
    assert hit.found, f"a near-identical requirement must be detected (got {hit.similarity})"
    assert hit.similarity >= hit.threshold
    assert hit.action == "pending", "the user must choose Update or New"


def test_unrelated_requirement_is_not_a_duplicate(brain):
    _write(
        brain, "CU Comment Field on CU Header",
        "# FDD\n\nAdd a CU Comment field to the CU Header application.\n",
    )
    brain.search.reindex(rebuild=True)

    hit = brain.search.find_duplicate(
        text="Create a BIRT report showing meter readings by substation for the gas network",
        doc_type="fdd", business_process="CU",
    )
    assert not hit.found
    assert hit.action == "new"


def test_metadata_filter_scopes_the_search(brain):
    _write(brain, "An FDD", "# FDD\n\nCU comment field on CU header.\n", doc_type="fdd")
    _write(brain, "A TDD", "# TDD\n\nCU comment field on CU header.\n", doc_type="tdd")
    brain.search.reindex(rebuild=True)

    out = brain.search.search(SearchQuery(text="CU comment field", doc_type="tdd", business_process="CU"))
    assert out.hits
    assert all(h.doc_type == "tdd" for h in out.hits)


def test_process_isolation(brain):
    _write(brain, "CU doc", "# FDD\n\nCU comment field.\n")
    brain.search.reindex(rebuild=True)
    out = brain.search.search(SearchQuery(text="CU comment field", business_process="WO"))
    assert not out.hits, "a CU document must not surface in a WO search"
