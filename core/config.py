"""Configuration: YAML file + .env, resolved once into a typed object.

Design rule from the blueprint: nothing is hardcoded into an agent prompt.
Templates, thresholds, Maximo endpoints and model choice all resolve here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .errors import ConfigError

#: Repo root = parent of this package.
ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _abs(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path)


@dataclass
class LLMConfig:
    """Which model the suite talks to.

    Auto-detection order:
      1. ANTHROPIC_API_KEY          -> Claude API (the blueprint default)
      2. MODEL_URL1 + MODEL_API_KEY1 -> any OpenAI-compatible endpoint
      3. nothing                    -> offline mode (deterministic templates only)
    """

    provider: str = "offline"          # anthropic | openai | offline
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = 8000
    temperature: float = 0.0
    timeout_seconds: float = 180.0
    max_retries: int = 3

    @property
    def available(self) -> bool:
        return self.provider != "offline"

    def redacted(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
        }


@dataclass
class MaximoConfig:
    """Maximo connection.

    `route` defaults to "api" because /maximo/oslc/ is SAML-intercepted on the
    MAS trial and ACN IAX environments and silently ignores the API key. Set
    route: oslc in config/suite.yaml if your environment exposes OSLC directly.
    """

    base_url: str = ""
    api_key: str = ""
    maxauth: str = ""
    route: str = "api"                 # api | oslc
    verify_tls: bool = True
    timeout_seconds: float = 30.0
    schema_dir: Path = field(default_factory=lambda: ROOT / "reference" / "maximo-schemas")
    apimeta_path: Path = field(default_factory=lambda: ROOT / "reference" / "apimeta.json")
    #: Schemas mirrored from your own environment by `run.py maximo sync`.
    #: When present these replace the bundled catalogue, because they describe
    #: the environment you are actually delivering into.
    live_schema_dir: Path = field(default_factory=lambda: ROOT / "reference" / "maximo-schemas-live")
    #: True when the catalogue in use came from `maximo sync`.
    using_live_catalogue: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and bool(self.api_key or self.maxauth)

    def redacted(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "route": self.route,
            "verify_tls": self.verify_tls,
            "api_key_set": bool(self.api_key),
            "maxauth_set": bool(self.maxauth),
            "schema_catalogue": str(self.schema_dir),
            "catalogue_source": "synced from your environment" if self.using_live_catalogue else "bundled",
        }


@dataclass
class BrainConfig:
    store_dir: Path = field(default_factory=lambda: ROOT / "brain" / "store")
    vector_dir: Path = field(default_factory=lambda: ROOT / "brain" / "vectors")
    audit_log: Path = field(default_factory=lambda: ROOT / "brain" / "audit.jsonl")
    feedback_log: Path = field(default_factory=lambda: ROOT / "brain" / "feedback.jsonl")
    collection: str = "mx_ai_suite"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    duplicate_threshold: float = 0.85
    top_k: int = 8
    chunk_chars: int = 1800
    chunk_overlap: int = 200
    #: write proposals are shown before they are applied
    dry_run_default: bool = True


@dataclass
class SuiteConfig:
    project_name: str = "Maximo Delivery AI Suite"
    version: str = "1.0"
    maximo_version: str = "MAS 9 / Maximo 7.6"
    domain: str = "Transmission & Distribution utilities"
    default_process: str = "CU"
    confidence_threshold: float = 0.75
    templates_dir: Path = field(default_factory=lambda: ROOT / "templates")
    skills_dir: Path = field(default_factory=lambda: ROOT / "skills")
    prompts_dir: Path = field(default_factory=lambda: ROOT / "prompts")
    runs_dir: Path = field(default_factory=lambda: ROOT / "runs")
    processes_dir: Path = field(default_factory=lambda: ROOT / "config" / "processes")
    templates: dict[str, str] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)
    maximo: MaximoConfig = field(default_factory=MaximoConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    ui_host: str = "127.0.0.1"
    ui_port: int = 8800
    log_level: str = "INFO"

    # -- lookups -----------------------------------------------------------
    def template_path(self, key: str) -> Path:
        """Resolve a template by logical key (fdd, tdd, ...). Never hardcoded."""
        name = self.templates.get(key)
        if not name:
            raise ConfigError(
                f"No template configured for '{key}'.",
                remedy=f"Add templates.{key} to config/suite.yaml.",
            )
        path = _abs(self.templates_dir / name) if not Path(name).is_absolute() else Path(name)
        if not path.exists():
            raise ConfigError(
                f"Template for '{key}' not found: {path}",
                remedy="Drop the .docx into /templates or correct config/suite.yaml.",
            )
        return path

    def process(self, name: str) -> dict[str, Any]:
        """Load a business-process definition (CU, WO, ...)."""
        path = self.processes_dir / f"{name.lower()}.yaml"
        if not path.exists():
            raise ConfigError(
                f"Unknown business process '{name}'.",
                remedy=f"Create {path.relative_to(ROOT)} or pick an existing process.",
            )
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def known_processes(self) -> list[str]:
        if not self.processes_dir.exists():
            return []
        return sorted(p.stem.upper() for p in self.processes_dir.glob("*.yaml"))

    def redacted(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "version": self.version,
            "maximo_version": self.maximo_version,
            "default_process": self.default_process,
            "confidence_threshold": self.confidence_threshold,
            "llm": self.llm.redacted(),
            "maximo": self.maximo.redacted(),
            "brain": {
                "store_dir": str(self.brain.store_dir),
                "duplicate_threshold": self.brain.duplicate_threshold,
                "embed_model": self.brain.embed_model,
            },
        }


def _detect_llm(raw: dict[str, Any]) -> LLMConfig:
    cfg = LLMConfig(
        max_tokens=int(raw.get("max_tokens", 8000)),
        temperature=float(raw.get("temperature", 0.0)),
        timeout_seconds=float(raw.get("timeout_seconds", 180)),
        max_retries=int(raw.get("max_retries", 3)),
    )
    forced = str(raw.get("provider", "auto")).lower()

    anthropic_key = _env("ANTHROPIC_API_KEY")
    compat_key = _env("MODEL_API_KEY1")
    compat_url = _env("MODEL_URL1")

    def use_anthropic() -> None:
        cfg.provider = "anthropic"
        cfg.api_key = anthropic_key
        cfg.model = _env("ANTHROPIC_MODEL") or str(raw.get("anthropic_model", "claude-sonnet-5"))
        cfg.base_url = _env("ANTHROPIC_BASE_URL")

    def use_openai() -> None:
        cfg.provider = "openai"
        cfg.api_key = compat_key
        cfg.base_url = compat_url
        cfg.model = _env("MODEL_NAME1") or str(raw.get("openai_model", "gpt-4o"))

    if forced == "anthropic" and anthropic_key:
        use_anthropic()
    elif forced == "openai" and compat_key and compat_url:
        use_openai()
    elif forced in ("auto", ""):
        if anthropic_key:
            use_anthropic()
        elif compat_key and compat_url:
            use_openai()
    # else: stays offline
    return cfg


def _detect_maximo(raw: dict[str, Any]) -> MaximoConfig:
    base = (_env("MAXIMO_MANAGE_URL") or _env("MAXIMO_URL")).rstrip("/")
    cfg = MaximoConfig(
        base_url=base,
        api_key=_env("MAXIMO_MANAGE_APIKEY") or _env("MAXIMO_APIKEY"),
        maxauth=_env("MAXAUTH"),
        route=str(raw.get("route", "api")).lower(),
        timeout_seconds=float(raw.get("timeout_seconds", 30)),
    )
    # ACN IAX ships a self-signed certificate; the public MAS trial does not.
    verify = raw.get("verify_tls", "auto")
    if verify == "auto":
        cfg.verify_tls = "acn-ix.iam.accenture.com" not in base
    else:
        cfg.verify_tls = bool(verify)

    if raw.get("schema_dir"):
        cfg.schema_dir = _abs(raw["schema_dir"])
    if raw.get("apimeta_path"):
        cfg.apimeta_path = _abs(raw["apimeta_path"])
    if raw.get("live_schema_dir"):
        cfg.live_schema_dir = _abs(raw["live_schema_dir"])

    # Prefer schemas mirrored from the operator's own environment.
    if cfg.live_schema_dir.is_dir() and any(cfg.live_schema_dir.glob("*.json")):
        cfg.schema_dir = cfg.live_schema_dir
        cfg.using_live_catalogue = True
        live_meta = cfg.live_schema_dir.parent / "apimeta-live.json"
        if live_meta.exists():
            cfg.apimeta_path = live_meta
    return cfg


def load(config_path: Path | None = None, *, reload_env: bool = True) -> SuiteConfig:
    """Read config/suite.yaml + .env into a SuiteConfig."""
    if reload_env:
        load_dotenv(ROOT / ".env", override=False)

    path = config_path or (ROOT / "config" / "suite.yaml")
    if not path.exists():
        raise ConfigError(
            f"Missing config file: {path}",
            remedy="Copy config/suite.yaml from the repo, or re-run the installer.",
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    suite = raw.get("suite", {}) or {}
    brain_raw = raw.get("brain", {}) or {}
    ui_raw = raw.get("ui", {}) or {}

    brain = BrainConfig(
        collection=brain_raw.get("collection", "mx_ai_suite"),
        embed_model=brain_raw.get("embed_model", "BAAI/bge-small-en-v1.5"),
        duplicate_threshold=float(brain_raw.get("duplicate_threshold", 0.85)),
        top_k=int(brain_raw.get("top_k", 8)),
        chunk_chars=int(brain_raw.get("chunk_chars", 1800)),
        chunk_overlap=int(brain_raw.get("chunk_overlap", 200)),
        dry_run_default=bool(brain_raw.get("dry_run_default", True)),
    )
    if brain_raw.get("store_dir"):
        brain.store_dir = _abs(brain_raw["store_dir"])
    if brain_raw.get("vector_dir"):
        brain.vector_dir = _abs(brain_raw["vector_dir"])
    if brain_raw.get("audit_log"):
        brain.audit_log = _abs(brain_raw["audit_log"])

    cfg = SuiteConfig(
        project_name=suite.get("project_name", "Maximo Delivery AI Suite"),
        version=str(suite.get("version", "1.0")),
        maximo_version=suite.get("maximo_version", "MAS 9 / Maximo 7.6"),
        domain=suite.get("domain", "Transmission & Distribution utilities"),
        default_process=suite.get("default_process", "CU"),
        confidence_threshold=float(suite.get("confidence_threshold", 0.75)),
        templates=raw.get("templates", {}) or {},
        llm=_detect_llm(raw.get("llm", {}) or {}),
        maximo=_detect_maximo(raw.get("maximo", {}) or {}),
        brain=brain,
        ui_host=ui_raw.get("host", "127.0.0.1"),
        ui_port=int(ui_raw.get("port", 8800)),
        log_level=_env("LOG_LEVEL") or suite.get("log_level", "INFO"),
    )

    for key in ("templates_dir", "skills_dir", "prompts_dir", "runs_dir"):
        if suite.get(key):
            setattr(cfg, key, _abs(suite[key]))

    # Directories the suite writes into must exist before anything runs.
    for d in (cfg.runs_dir, cfg.brain.store_dir, cfg.brain.vector_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg


@lru_cache(maxsize=1)
def get() -> SuiteConfig:
    """Process-wide singleton. Use `load()` directly in tests."""
    return load()


def reset() -> None:
    """Drop the cached config (used by tests and the UI reload endpoint)."""
    get.cache_clear()
