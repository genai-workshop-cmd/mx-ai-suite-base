"""System endpoints: health, configuration, Maximo validation."""
from __future__ import annotations

import importlib.util as iu
import sys

from fastapi import APIRouter, HTTPException

from core.errors import SuiteError

from .deps import get_brain, get_config, get_validator, reset

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Everything the status bar shows, in one poll."""
    cfg = get_config()
    validator = get_validator()
    brain = get_brain()

    return {
        "project": cfg.project_name,
        "version": cfg.version,
        "maximo_version": cfg.maximo_version,
        "python": sys.version.split()[0],
        "model": {
            "available": cfg.llm.available,
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "label": cfg.llm.model if cfg.llm.available else "offline (deterministic)",
        },
        "maximo": {
            "configured": cfg.maximo.configured,
            "route": cfg.maximo.route,
            "base_url": cfg.maximo.base_url,
            "catalogue": validator.catalog.size,
            "label": (cfg.maximo.base_url.split("//")[-1].split("/")[0] if cfg.maximo.configured
                      else f"offline catalogue ({validator.catalog.size} OS)"),
        },
        "brain": {
            "documents": brain.store.stats()["documents"],
            "threshold": cfg.brain.duplicate_threshold,
        },
        "confidence_threshold": cfg.confidence_threshold,
    }


@router.get("/config")
def configuration() -> dict:
    """Redacted configuration. Never returns a secret."""
    cfg = get_config()
    data = cfg.redacted()
    data["templates"] = {}
    for key in cfg.templates:
        try:
            data["templates"][key] = cfg.template_path(key).name
        except SuiteError as exc:
            data["templates"][key] = f"MISSING - {exc.message}"
    data["skills"] = sorted(p.name for p in cfg.skills_dir.glob("*.md"))
    data["processes"] = cfg.known_processes()
    data["packages"] = {
        name: bool(iu.find_spec(name))
        for name in ("chromadb", "fastembed", "rank_bm25", "anthropic", "openai", "pypdf", "mammoth", "docx", "openpyxl")
    }
    return data


@router.post("/reload")
def reload_config() -> dict:
    """Re-read config/suite.yaml and .env without restarting the server."""
    reset()
    return health()


@router.get("/maximo/ping")
def maximo_ping() -> dict:
    validator = get_validator()
    if not get_config().maximo.configured:
        return {
            "reachable": False,
            "detail": "Maximo is not configured. Validation uses the bundled catalogue.",
            "catalogue": validator.catalog.size,
        }
    probe = validator.client.ping(force=True)
    out = probe.as_dict()
    out["catalogue"] = validator.catalog.size
    return out


@router.get("/maximo/validate")
def maximo_validate(name: str, process: str = "") -> dict:
    """Validate OBJECT or OBJECT.ATTRIBUTE against the environment/catalogue."""
    cfg = get_config()
    validator = get_validator()
    name = (name or "").strip().upper()
    if not name:
        raise HTTPException(status_code=400, detail={"code": "MAXIMO", "message": "Provide a name to validate."})

    results = []
    detail: dict = {}
    if "." in name:
        obj, attr = name.split(".", 1)
        results = [validator.object(obj), validator.attribute(obj, attr)]
        spec = validator.attribute_spec(obj, attr)
        if spec:
            detail["attribute"] = spec
    else:
        results = [validator.object(name)]
        info = validator.catalog.for_object(name)
        if info:
            detail["object_structure"] = {
                "os_name": info.os_name,
                "mbo": info.mbo,
                "primary_keys": [k.upper() for k in info.primary_keys],
                "unique_id": info.unique_id.upper(),
                "attribute_count": len(info.attributes),
                "children": info.child_objects[:12],
                "sample_attributes": sorted(a.upper() for a in list(info.attributes)[:24]),
            }

    return {
        "name": name,
        "source": validator.source_label(),
        "process": (process or cfg.default_process).upper(),
        "results": [r.model_dump() for r in results],
        "ok": all(r.exists for r in results),
        "detail": detail,
    }


@router.get("/maximo/search")
def maximo_search(q: str, top: int = 20) -> dict:
    validator = get_validator()
    hits = validator.catalog.search(q, limit=top)
    return {
        "query": q,
        "hits": [
            {
                "os_name": h.os_name,
                "mbo": h.mbo,
                "description": h.description,
                "attributes": len(h.attributes),
                "use_with": h.use_with,
                "primary_keys": [k.upper() for k in h.primary_keys],
            }
            for h in hits
        ],
    }
