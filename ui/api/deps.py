"""Shared singletons for the API layer.

The pipeline, brain and validator are expensive to construct (schema catalogue,
embedding model, Chroma) so the UI builds them once per process.
"""
from __future__ import annotations

from functools import lru_cache

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
