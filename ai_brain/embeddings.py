"""Local embeddings. No API, no subscription (blueprint section 7.2).

Primary backend is fastembed (ONNX, no torch). If the model cannot be
downloaded - offline machine, blocked proxy - we fall back to a deterministic
hashed character n-gram vectoriser. The fallback is weaker but keeps the whole
suite functional, and `backend` says which one is in use so the UI can show it.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Iterable, Sequence

from core.logging import get

log = get("suite.brain.embed")

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


class Embedder:
    """Text -> unit-length float vectors."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> None:
        self.model_name = model_name
        self.dim = dim
        self.backend = "pending"
        self._model = None
        self._lock = threading.Lock()

    # -- setup -------------------------------------------------------------
    def _ensure(self) -> None:
        if self.backend != "pending":
            return
        with self._lock:
            if self.backend != "pending":
                return
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.model_name)
                # Probe once so a download failure surfaces here, not mid-run.
                probe = next(iter(self._model.embed(["probe"])))
                self.dim = len(probe)
                self.backend = "fastembed"
                log.info("embeddings: fastembed %s (dim=%d)", self.model_name, self.dim)
            except Exception as exc:
                self._model = None
                self.backend = "hashed"
                log.warning(
                    "fastembed unavailable (%s) - falling back to hashed n-gram embeddings. "
                    "Semantic search quality will be lower.",
                    str(exc)[:160],
                )

    @property
    def ready_backend(self) -> str:
        self._ensure()
        return self.backend

    # -- encoding ----------------------------------------------------------
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self._ensure()
        if not texts:
            return []
        if self._model is not None:
            try:
                return [list(map(float, v)) for v in self._model.embed(list(texts))]
            except Exception as exc:
                log.warning("fastembed failed mid-run (%s) - switching to hashed embeddings", exc)
                self._model = None
                self.backend = "hashed"
        return [self._hashed(t) for t in texts]

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]

    # -- fallback ----------------------------------------------------------
    def _hashed(self, text: str) -> list[float]:
        """Deterministic bag-of-features vector.

        Combines word tokens and 4-gram character shingles so that near-
        duplicate documents still land close together in cosine space.
        """
        vec = [0.0] * self.dim
        lowered = text.lower()
        tokens = _TOKEN_RE.findall(lowered)

        for tok in tokens:
            _accumulate(vec, tok, 1.0, self.dim)
        for a, b in zip(tokens, tokens[1:]):
            _accumulate(vec, f"{a}_{b}", 0.7, self.dim)

        compact = re.sub(r"\s+", " ", lowered)
        for i in range(0, max(0, len(compact) - 4), 2):
            _accumulate(vec, compact[i : i + 4], 0.25, self.dim)

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


def _accumulate(vec: list[float], feature: str, weight: float, dim: int) -> None:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    bucket = int.from_bytes(digest[:4], "little") % dim
    sign = 1.0 if digest[4] & 1 else -1.0
    vec[bucket] += sign * weight


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    av, bv = list(a), list(b)
    if not av or not bv or len(av) != len(bv):
        return 0.0
    dot = sum(x * y for x, y in zip(av, bv))
    na = math.sqrt(sum(x * x for x in av))
    nb = math.sqrt(sum(y * y for y in bv))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


_embedder: Embedder | None = None


def embedder(model_name: str = "BAAI/bge-small-en-v1.5") -> Embedder:
    global _embedder
    if _embedder is None or _embedder.model_name != model_name:
        _embedder = Embedder(model_name)
    return _embedder
