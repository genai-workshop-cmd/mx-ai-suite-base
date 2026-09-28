"""Tiered AI Brain search (blueprint section 7.3).

    Step 1  metadata filter   - doc type + business process + Maximo module
    Step 2  full-text keyword - BM25 over the filtered set
    Step 3  semantic          - cosine similarity over the filtered set

"Stop at first confident hit": if the metadata + keyword tiers already produce
an unambiguous match we return without paying for an embedding pass.

`find_duplicate()` is the mandatory pre-flight every generating agent runs:
similarity >= threshold means an equivalent document exists and the user must
choose Update or New.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.config import BrainConfig
from core.logging import get
from core.models import BrainDocument, BrainHit, DuplicateDecision

from .index import VectorIndex
from .store import BrainStore

log = get("suite.brain.search")

_WORD_RE = re.compile(r"[a-z0-9_]+")
#: Terms too common in Maximo design docs to carry signal.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is", "are", "be",
    "this", "that", "with", "as", "by", "from", "it", "at", "will", "shall", "must",
    "maximo", "document", "design", "system", "field", "value", "user", "data",
}


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS and len(w) > 1]


@dataclass
class SearchQuery:
    text: str
    doc_type: str | None = None
    business_process: str | None = None
    modules: list[str] = field(default_factory=list)
    top_k: int = 8

    def metadata_filter(self) -> dict[str, Any]:
        f: dict[str, Any] = {}
        if self.doc_type:
            f["doc_type"] = self.doc_type.lower()
        if self.business_process:
            f["business_process"] = self.business_process.upper()
        return f


@dataclass
class SearchOutcome:
    hits: list[BrainHit] = field(default_factory=list)
    stopped_at: str = "semantic"
    candidates_after_metadata: int = 0
    note: str = ""
    #: doc_id -> raw cosine similarity, before the keyword blend. The blueprint's
    #: 0.85 duplicate threshold is defined on this, not on the blended rank score.
    semantic_scores: dict[str, float] = field(default_factory=dict)

    def best(self) -> BrainHit | None:
        return self.hits[0] if self.hits else None

    def semantic_for(self, doc_id: str) -> float:
        return self.semantic_scores.get(doc_id, 0.0)


class BrainSearch:
    """Reads the store, ranks with BM25 + vectors."""

    def __init__(self, cfg: BrainConfig, store: BrainStore, index: VectorIndex) -> None:
        self.cfg = cfg
        self.store = store
        self.index = index

    # -- tier 1 ------------------------------------------------------------
    def _metadata_candidates(self, q: SearchQuery) -> list[BrainDocument]:
        docs: list[BrainDocument] = []
        for doc in self.store.iter_documents():
            if q.doc_type and doc.doc_type.lower() != q.doc_type.lower():
                continue
            if q.business_process and doc.business_process.upper() != q.business_process.upper():
                continue
            if q.modules:
                haystack = f"{doc.title} {doc.body} {' '.join(doc.tags)}".upper()
                if not any(m.upper() in haystack for m in q.modules):
                    continue
            docs.append(doc)
        return docs

    # -- tier 2 ------------------------------------------------------------
    def _keyword_rank(self, q: SearchQuery, docs: list[BrainDocument]) -> list[tuple[BrainDocument, float]]:
        terms = tokenize(q.text)
        if not terms or not docs:
            return [(d, 0.0) for d in docs]

        corpus = [tokenize(f"{d.title} {d.title} {d.body}") for d in docs]
        try:
            from rank_bm25 import BM25Okapi

            scores = BM25Okapi(corpus).get_scores(terms)
        except Exception:
            scores = [_overlap_score(terms, toks) for toks in corpus]

        top = max(scores) if len(scores) else 0.0
        norm = [float(s) / top if top > 0 else 0.0 for s in scores]
        ranked = list(zip(docs, norm))
        ranked.sort(key=lambda t: t[1], reverse=True)
        return ranked

    # -- tier 3 ------------------------------------------------------------
    def _semantic_rank(self, q: SearchQuery, allowed: set[str]) -> dict[str, tuple[float, str]]:
        """doc_id -> (best chunk similarity, excerpt)."""
        results = self.index.query(q.text, top_k=max(q.top_k * 4, 20), where=q.metadata_filter() or None)
        best: dict[str, tuple[float, str]] = {}
        for chunk, sim in results:
            doc_id = chunk.doc_id
            if allowed and doc_id not in allowed:
                continue
            if doc_id not in best or sim > best[doc_id][0]:
                best[doc_id] = (sim, chunk.text[:400])
        return best

    # -- public ------------------------------------------------------------
    def search(self, q: SearchQuery) -> SearchOutcome:
        docs = self._metadata_candidates(q)
        outcome = SearchOutcome(candidates_after_metadata=len(docs))
        if not docs:
            outcome.stopped_at = "metadata"
            outcome.note = "No document matches the metadata filter."
            return outcome

        keyword_ranked = self._keyword_rank(q, docs)

        # Stop-at-first-confident-hit: one document dominates on keywords and
        # nothing else comes close, so an embedding pass cannot change the answer.
        if len(keyword_ranked) > 1:
            top_score = keyword_ranked[0][1]
            runner_up = keyword_ranked[1][1]
            if top_score >= 0.95 and runner_up <= 0.45:
                doc = keyword_ranked[0][0]
                outcome.stopped_at = "keyword"
                outcome.hits = [_to_hit(doc, top_score, "keyword", _excerpt(doc, q.text))]
                outcome.note = "Unambiguous keyword match; semantic pass skipped."
                return outcome

        allowed = {d.doc_id for d in docs}
        semantic = self._semantic_rank(q, allowed)

        keyword_by_id = {d.doc_id: s for d, s in keyword_ranked}
        doc_by_id = {d.doc_id: d for d in docs}

        hits: list[BrainHit] = []
        for doc_id, doc in doc_by_id.items():
            sem, excerpt = semantic.get(doc_id, (0.0, ""))
            kw = keyword_by_id.get(doc_id, 0.0)
            # Semantic dominates; keyword breaks ties and rewards exact terminology.
            combined = (0.75 * sem) + (0.25 * kw)
            matched = "semantic" if sem >= kw else "keyword"
            hits.append(_to_hit(doc, combined, matched, excerpt or _excerpt(doc, q.text)))

        hits.sort(key=lambda h: h.score, reverse=True)
        outcome.hits = hits[: q.top_k]
        outcome.stopped_at = "semantic"
        outcome.semantic_scores = {doc_id: round(sem, 4) for doc_id, (sem, _) in semantic.items()}

        if self.index.count == 0:
            outcome.note = "Vector index is empty - ranking used keywords only. Run `python run.py index`."
            # Without an index there is no cosine score; derive one from a
            # document signature so duplicate detection still functions.
            outcome.semantic_scores = self._signature_scores(q.text, docs)
        return outcome

    def _signature_scores(self, text: str, docs: list[BrainDocument]) -> dict[str, float]:
        """Document-level cosine against title + opening body, used when the
        chunk index is unavailable."""
        from .embeddings import cosine as _cos

        emb = self.index.embedder
        query_vec = emb.encode_one(text)
        signatures = [f"{d.title}\n{d.body[:600]}" for d in docs]
        vectors = emb.encode(signatures)
        return {d.doc_id: round(_cos(query_vec, v), 4) for d, v in zip(docs, vectors)}

    def find_duplicate(
        self,
        *,
        text: str,
        doc_type: str,
        business_process: str,
        threshold: float | None = None,
    ) -> DuplicateDecision:
        """The mandatory search-before-create check.

        Compares on raw cosine similarity, per blueprint section 7.3. The
        blended rank score used for browsing would understate a true duplicate.
        """
        threshold = self.cfg.duplicate_threshold if threshold is None else threshold
        outcome = self.search(
            SearchQuery(text=text, doc_type=doc_type, business_process=business_process, top_k=5)
        )
        if not outcome.hits:
            return DuplicateDecision(found=False, similarity=0.0, threshold=threshold, action="new")

        # Pick the document with the highest *semantic* score, not the highest
        # blended score - they can disagree when terminology overlaps.
        best = max(outcome.hits, key=lambda h: outcome.semantic_for(h.doc_id))
        similarity = outcome.semantic_for(best.doc_id)
        if outcome.stopped_at == "keyword":
            # An unambiguous keyword match short-circuits the semantic pass.
            similarity = max(similarity, best.score)

        found = similarity >= threshold
        return DuplicateDecision(
            found=found,
            best=best,
            similarity=round(similarity, 4),
            threshold=threshold,
            action="pending" if found else "new",
        )

    # -- maintenance -------------------------------------------------------
    def reindex(self, *, rebuild: bool = False) -> dict[str, int]:
        """(Re)build the vector index from the markdown store."""
        if rebuild:
            self.index.reset()
        docs = chunks = 0
        for doc in self.store.iter_documents():
            added = self.index.index_document(doc)
            docs += 1
            chunks += added
        log.info("indexed %d documents into %d chunks (%s)", docs, chunks, self.index.backend)
        return {"documents": docs, "chunks": chunks, "index_size": self.index.count}


def _overlap_score(terms: list[str], tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    tokenset = set(tokens)
    return sum(1 for t in terms if t in tokenset) / max(1, len(set(terms)))


def _to_hit(doc: BrainDocument, score: float, matched_by: str, excerpt: str) -> BrainHit:
    return BrainHit(
        doc_id=doc.doc_id,
        path=doc.path,
        title=doc.title,
        doc_type=doc.doc_type,
        business_process=doc.business_process,
        version=doc.version,
        score=round(float(score), 4),
        matched_by=matched_by,  # type: ignore[arg-type]
        excerpt=excerpt,
    )


def _excerpt(doc: BrainDocument, query: str, width: int = 320) -> str:
    """A window of the body around the first query term that appears."""
    body = doc.body
    for term in tokenize(query)[:6]:
        idx = body.lower().find(term)
        if idx >= 0:
            start = max(0, idx - width // 3)
            return ("..." if start else "") + body[start : start + width].strip() + "..."
    return body[:width].strip()
