"""AI Brain: the single source of truth every agent reads from and writes to."""
from __future__ import annotations

from dataclasses import dataclass

from core.config import SuiteConfig

from .index import VectorIndex
from .search import BrainSearch, SearchQuery
from .store import BrainStore, WriteProposal

__all__ = ["Brain", "BrainStore", "BrainSearch", "SearchQuery", "VectorIndex", "WriteProposal", "brain"]


@dataclass
class Brain:
    """Store + index + search, wired together."""

    store: BrainStore
    index: VectorIndex
    search: BrainSearch

    @classmethod
    def build(cls, cfg: SuiteConfig) -> "Brain":
        store = BrainStore(cfg.brain)
        index = VectorIndex(cfg.brain)
        return cls(store=store, index=index, search=BrainSearch(cfg.brain, store, index))

    def status(self) -> dict:
        stats = self.store.stats()
        stats.update(
            {
                "index_backend": self.index.backend if self.index.backend != "pending" else "not started",
                "index_chunks": self.index.count,
                "embed_backend": self.index.embedder.backend,
            }
        )
        return stats


_brain: Brain | None = None


def brain(cfg: SuiteConfig) -> Brain:
    global _brain
    if _brain is None:
        _brain = Brain.build(cfg)
    return _brain
