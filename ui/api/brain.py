"""AI Brain explorer endpoints: search, browse, read, reindex, audit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from ai_brain import SearchQuery
from core.errors import SuiteError

from .deps import get_brain, get_config

router = APIRouter(prefix="/api/brain", tags=["brain"])


@router.get("/status")
def status() -> dict:
    brain = get_brain()
    cfg = get_config()
    out = brain.status()
    out["duplicate_threshold"] = cfg.brain.duplicate_threshold
    return out


@router.get("/search")
def search(
    q: str,
    doc_type: str | None = None,
    process: str | None = None,
    top: int = 8,
) -> dict:
    brain = get_brain()
    outcome = brain.search.search(
        SearchQuery(text=q, doc_type=doc_type or None, business_process=process or None, top_k=top)
    )
    return {
        "query": q,
        "stopped_at": outcome.stopped_at,
        "candidates_after_metadata": outcome.candidates_after_metadata,
        "note": outcome.note,
        "hits": [
            {**h.model_dump(), "semantic": outcome.semantic_for(h.doc_id)} for h in outcome.hits
        ],
    }


@router.post("/duplicate-check")
def duplicate_check(payload: dict[str, Any] = Body(...)) -> dict:
    """The search-before-create check, exposed for the UI 'new document' flow."""
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail={"code": "BRAIN", "message": "Provide some text to check."})
    decision = get_brain().search.find_duplicate(
        text=text,
        doc_type=str(payload.get("doc_type", "fdd")),
        business_process=str(payload.get("business_process", get_config().default_process)),
    )
    return decision.model_dump()


@router.get("/documents")
def documents() -> dict:
    brain = get_brain()
    docs = []
    for doc in brain.store.iter_documents():
        docs.append(
            {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "business_process": doc.business_process,
                "version": doc.version,
                "updated": doc.updated,
                "agent": doc.agent,
                "run_id": doc.run_id,
                "path": doc.path,
                "versions": brain.store.versions(doc.business_process, doc.doc_type, doc.doc_id),
                "chars": len(doc.body),
            }
        )
    docs.sort(key=lambda d: d["updated"], reverse=True)
    return {"documents": docs, "count": len(docs)}


@router.get("/document")
def document(path: str) -> dict:
    """Read one brain document. Confined to the brain store."""
    store_root = get_config().brain.store_dir.resolve()
    resolved = Path(path).resolve()
    if store_root not in resolved.parents:
        raise HTTPException(
            status_code=403, detail={"code": "PATH", "message": "Document is outside the AI Brain store."}
        )
    try:
        doc = get_brain().store.load(resolved)
    except SuiteError as exc:
        raise HTTPException(status_code=404, detail=exc.as_dict())
    return doc.model_dump()


@router.post("/reindex")
def reindex(payload: dict[str, Any] = Body(default={})) -> dict:
    brain = get_brain()
    stats = brain.search.reindex(rebuild=bool(payload.get("rebuild")))
    stats["backend"] = brain.index.backend
    stats["embeddings"] = brain.index.embedder.backend
    return stats


@router.get("/audit")
def audit(limit: int = 50) -> dict:
    return {"entries": get_brain().store.audit_tail(limit)}
