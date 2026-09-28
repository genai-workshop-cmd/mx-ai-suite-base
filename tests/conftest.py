"""Shared fixtures. Every test runs against a throwaway brain and runs dir,
so the suite never touches the operator's real data."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    """A SuiteConfig pointed at temporary storage."""
    c = config.load(reload_env=False)
    c.brain.store_dir = tmp_path / "store"
    c.brain.vector_dir = tmp_path / "vectors"
    c.brain.audit_log = tmp_path / "audit.jsonl"
    c.brain.collection = f"test_{tmp_path.name}"
    c.brain.dry_run_default = False
    c.runs_dir = tmp_path / "runs"
    for d in (c.brain.store_dir, c.brain.vector_dir, c.runs_dir):
        d.mkdir(parents=True, exist_ok=True)
    # Never call a real model from the test suite.
    c.llm.provider = "offline"
    c.llm.api_key = ""
    # Never call a real Maximo from the test suite.
    c.maximo.base_url = ""
    c.maximo.api_key = ""
    return c


@pytest.fixture()
def process(cfg):
    return cfg.process("CU")


@pytest.fixture()
def validator(cfg):
    from maximo.validator import MaximoValidator

    return MaximoValidator(cfg)


@pytest.fixture()
def pipeline(cfg):
    from pipeline import Pipeline

    return Pipeline(cfg)


UC1 = """# CU Comment field
- The system shall add a new CUCOMMENT attribute to the CUJP object through Database Configuration.
- The CU Comment field must be visible on the CU Header application in Application Designer.
- On Work Order generation an automation script shall copy CUJP.CUCOMMENT into WORKORDER.DESCRIPTION.
- Empty CUCOMMENT must not overwrite an existing Work Order description.
"""

UC2 = """# CU outbound to AUD
- The system shall trigger a CU outbound message to the AUD external system when the CUE Status changes to ACCEPTED.
- A Publish Channel named CUACCEPTED_PC shall be defined against the CUJP object structure.
- An External System AUD_EXTSYS shall be configured with an HTTP endpoint.
- No message shall be generated for any status change other than ACCEPTED.
"""
