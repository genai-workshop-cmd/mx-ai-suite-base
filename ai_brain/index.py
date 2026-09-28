"""Chroma-backed vector index over the AI Brain store.

Documents are chunked, embedded locally and persisted to `brain/vectors/`.
Chroma runs embedded - no server, no subscription (blueprint section 7.2).

If Chroma cannot start for any reason the index degrades to an in-memory
numpy-free cosine scan over the same chunks, so search never hard-fails.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Iterable

from core.config import BrainConfig
from core.logging import get
from core.models import BrainDocument

from .embeddings import Embedder, cosine, embedder

log = get("suite.brain.index")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict[str, Any]


def chunk_document(doc: BrainDocument, size: int, overlap: int) -> list[Chunk]:
    """Split on markdown headings first, then pack to the character budget.

    Heading-aware chunking keeps "Field Mapping" and "Error Handling" in
    separate chunks, which matters a lot for retrieval precision on design docs.
    """
    body = doc.body.strip()
    if not body:
        return []

    sections: list[tuple[str, str]] = []
    current_heading = doc.title
    buffer: list[str] = []
    for line in body.splitlines():
        if re.match(r"^#{1,4}\s+\S", line):
            if buffer:
                sections.append((current_heading, "\n".join(buffer).strip()))
                buffer = []
            current_heading = line.lstrip("#").strip()
        else:
            buffer.append(line)
    if buffer:
        sections.append((current_heading, "\n".join(buffer).strip()))
    if not sections:
        sections = [(doc.title, body)]

    chunks: list[Chunk] = []
    for heading, text in sections:
        if not text:
            continue
        prefixed = f"{doc.title} > {heading}\n\n{text}"
        for i, piece in enumerate(_pack(prefixed, size, overlap)):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}::v{doc.version}::{len(chunks)}",
                    doc_id=doc.doc_id,
                    text=piece,
                    metadata={
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        "heading": heading,
                        "doc_type": doc.doc_type,
                        "business_process": doc.business_process,
                        "version": doc.version,
                        "path": doc.path,
                        "agent": doc.agent,
                        "chunk_index": i,
                    },
                )
            )
    return chunks


def _pack(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out: list[str] = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        window = text[start : start + size]
        # Prefer to break on a paragraph boundary.
        if start + size < len(text):
            cut = window.rfind("\n\n")
            if cut > size // 2:
                window = window[:cut]
        out.append(window.strip())
        start += max(step, len(window) - overlap) if len(window) > overlap else step
    return [w for w in out if w]


class VectorIndex:
    """Persisted vector store with a pure-Python fallback."""

    def __init__(self, cfg: BrainConfig, emb: Embedder | None = None) -> None:
        self.cfg = cfg
        self.embedder = emb or embedder(cfg.embed_model)
        self._lock = threading.Lock()
        self._collection = None
        self._fallback: list[tuple[Chunk, list[float]]] = []
        self.backend = "pending"

    # -- setup -------------------------------------------------------------
    def _ensure(self) -> None:
        if self.backend != "pending":
            return
        with self._lock:
            if self.backend != "pending":
                return
            try:
                import chromadb
                from chromadb.config import Settings

                self.cfg.vector_dir.mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(
                    path=str(self.cfg.vector_dir),
                    settings=Settings(anonymized_telemetry=False, allow_reset=True),
                )
                # We embed ourselves; tell Chroma not to.
                self._collection = client.get_or_create_collection(
                    name=self.cfg.collection,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=None,
                )
                self.backend = "chroma"
                log.info("vector index: chroma at %s", self.cfg.vector_dir)
            except Exception as exc:
                self.backend = "memory"
                log.warning("chroma unavailable (%s) - using in-memory index", str(exc)[:160])

    @property
    def count(self) -> int:
        self._ensure()
        if self.backend == "chroma" and self._collection is not None:
            try:
                return self._collection.count()
            except Exception:
                return 0
        return len(self._fallback)

    # -- mutation ----------------------------------------------------------
    def reset(self) -> None:
        self._ensure()
        self._fallback.clear()
        if self.backend == "chroma" and self._collection is not None:
            try:
                import chromadb
                from chromadb.config import Settings

                client = chromadb.PersistentClient(
                    path=str(self.cfg.vector_dir),
                    settings=Settings(anonymized_telemetry=False, allow_reset=True),
                )
                try:
                    client.delete_collection(self.cfg.collection)
                except Exception:
                    pass
                self._collection = client.get_or_create_collection(
                    name=self.cfg.collection,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=None,
                )
            except Exception as exc:
                log.warning("could not reset chroma collection: %s", exc)

    def remove_document(self, doc_id: str) -> None:
        self._ensure()
        if self.backend == "chroma" and self._collection is not None:
            try:
                self._collection.delete(where={"doc_id": doc_id})
                return
            except Exception as exc:
                log.debug("chroma delete failed for %s: %s", doc_id, exc)
        self._fallback = [(c, v) for c, v in self._fallback if c.doc_id != doc_id]

    def add(self, chunks: Iterable[Chunk]) -> int:
        chunks = list(chunks)
        if not chunks:
            return 0
        self._ensure()
        vectors = self.embedder.encode([c.text for c in chunks])

        if self.backend == "chroma" and self._collection is not None:
            try:
                self._collection.upsert(
                    ids=[c.chunk_id for c in chunks],
                    embeddings=vectors,
                    documents=[c.text for c in chunks],
                    metadatas=[_flatten(c.metadata) for c in chunks],
                )
                return len(chunks)
            except Exception as exc:
                log.warning("chroma upsert failed (%s) - falling back to memory index", str(exc)[:160])
                self.backend = "memory"

        ids = {c.chunk_id for c in chunks}
        self._fallback = [(c, v) for c, v in self._fallback if c.chunk_id not in ids]
        self._fallback.extend(zip(chunks, vectors))
        return len(chunks)

    def index_document(self, doc: BrainDocument) -> int:
        self.remove_document(doc.doc_id)
        return self.add(chunk_document(doc, self.cfg.chunk_chars, self.cfg.chunk_overlap))

    # -- query -------------------------------------------------------------
    def query(
        self,
        text: str,
        *,
        top_k: int = 8,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Return (chunk, cosine_similarity) best-first."""
        self._ensure()
        if self.count == 0:
            return []
        vector = self.embedder.encode_one(text)

        if self.backend == "chroma" and self._collection is not None:
            try:
                res = self._collection.query(
                    query_embeddings=[vector],
                    n_results=min(top_k, max(1, self.count)),
                    where=_chroma_where(where),
                    include=["documents", "metadatas", "distances"],
                )
                out: list[tuple[Chunk, float]] = []
                ids = (res.get("ids") or [[]])[0]
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                dists = (res.get("distances") or [[]])[0]
                for cid, doc_text, meta, dist in zip(ids, docs, metas, dists):
                    meta = dict(meta or {})
                    # cosine space: similarity = 1 - distance
                    out.append(
                        (
                            Chunk(chunk_id=cid, doc_id=str(meta.get("doc_id", "")), text=doc_text or "", metadata=meta),
                            max(0.0, min(1.0, 1.0 - float(dist))),
                        )
                    )
                return out
            except Exception as exc:
                log.warning("chroma query failed (%s) - using memory index", str(exc)[:160])

        scored = []
        for chunk, vec in self._fallback:
            if where and any(chunk.metadata.get(k) != v for k, v in where.items()):
                continue
            scored.append((chunk, cosine(vector, vec)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]


def _flatten(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma metadata values must be scalars."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif v is None:
            out[k] = ""
        else:
            out[k] = ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
    return out


def _chroma_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
    """Chroma rejects a multi-key dict unless it is wrapped in $and."""
    if not where:
        return None
    if len(where) == 1:
        return where
    return {"$and": [{k: v} for k, v in where.items()]}
