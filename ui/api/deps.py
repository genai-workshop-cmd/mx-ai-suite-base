"""Shared singletons for the API layer.

The pipeline, brain and validator are expensive to construct (schema catalogue,
embedding model, Chroma) so the UI builds them once per process.
"""
from __future__ import annotations

import threading
import uuid
from functools import lru_cache
from typing import Any

from ai_brain import Brain
from core import config
from core.config import SuiteConfig
from maximo.validator import MaximoValidator
from pipeline import Pipeline, RunStore


@lru_cache(maxsize=1)
def get_config() -> SuiteConfig:
    return config.load()


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline(get_config())


@lru_cache(maxsize=1)
def get_store() -> RunStore:
    return get_pipeline().store


@lru_cache(maxsize=1)
def get_brain() -> Brain:
    return get_pipeline().brain


@lru_cache(maxsize=1)
def get_validator() -> MaximoValidator:
    return get_pipeline().validator


def reset() -> None:
    """Drop every cached singleton (used by the settings reload endpoint)."""
    for fn in (get_config, get_pipeline, get_store, get_brain, get_validator):
        fn.cache_clear()
    config.reset()


# ---------------------------------------------------------------------------
# Background job store — tracks in-flight advance() calls so the UI can poll
# instead of blocking on a long-running HTTP request.
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def job_create() -> str:
    """Create a new job entry and return its ID."""
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None}
    return job_id


def job_done(job_id: str, result: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id] = {"status": "done", "result": result, "error": None}


def job_fail(job_id: str, error: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id] = {"status": "error", "result": None, "error": error}


def job_get(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        return _jobs.get(job_id)
