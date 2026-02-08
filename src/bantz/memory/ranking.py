"""Hybrid memory-ranking engine (Issue #450).

Scores :class:`~bantz.memory.models.MemoryItem` objects against a text
query using a weighted combination of:

* **keyword score** — BM25-lite (TF-IDF-ish) with Turkish stop-word removal
* **semantic score** — cosine similarity when embeddings are available
* **recency boost** — decays over time (last 24 h → +0.20, 7 d → +0.10)
* **importance** — the ``importance`` field on each item

Default weights (configurable):

    α=0.30  keyword
    β=0.40  semantic
    γ=0.15  recency
    δ=0.15  importance
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from bantz.memory.models import MemoryItem, MemoryItemType

__all__ = [
    "RankedMemory",
    "RankingWeights",
    "HybridRanker",
    "TURKISH_STOPWORDS",
]

# ── Turkish stop-words ────────────────────────────────────────────────
TURKISH_STOPWORDS: frozenset[str] = frozenset(
    {
        "bir", "ve", "bu", "da", "de", "ile", "için", "ama",
        "ya", "ki", "ne", "mı", "mi", "mu", "mü", "var",
        "yok", "ben", "sen", "biz", "siz", "o", "şu",
        "çok", "daha", "en", "her", "gibi", "kadar",
        "ise", "olan", "olarak", "onu", "bunu", "şey",
        "hem", "veya", "ya da", "evet", "hayır", "tamam",
        "acaba", "ancak", "belki", "bile", "böyle", "çünkü",
        "diğer", "dolayı", "fakat", "hep", "henüz", "hiç",
        "nasıl", "neden", "nerede", "niye", "sadece", "sonra",
        "şimdi", "tüm", "üzere", "yani", "zaten",
    }
)


# ── Data structures ───────────────────────────────────────────────────

@dataclass
class RankingWeights:
    """Configurable weights for the hybrid scoring formula."""

    keyword: float = 0.30    # α
    semantic: float = 0.40   # β
    recency: float = 0.15    # γ
    importance: float = 0.15  # δ

    def __post_init__(self) -> None:
        total = self.keyword + self.semantic + self.recency + self.importance
        if total <= 0:
            raise ValueError("Weights must sum to a positive value")


@dataclass
class RankedMemory:
    """A memory item together with its computed score breakdown."""

    item: MemoryItem
    total_score: float = 0.0
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    recency_boost: float = 0.0
    importance_score: float = 0.0

    def __lt__(self, other: "RankedMemory") -> bool:  # for heapq / sorted
        return self.total_score < other.total_score


# ── Ranker ────────────────────────────────────────────────────────────

class HybridRanker:
    """Hybrid keyword + semantic + recency + importance ranker.

    Parameters
    ----------
    weights:
        Scoring weights (defaults to ``α=0.30, β=0.40, γ=0.15, δ=0.15``).
    stopwords:
        Stop-word set.  Defaults to :data:`TURKISH_STOPWORDS`.
    """

    def __init__(
        self,
        weights: Optional[RankingWeights] = None,
        stopwords: Optional[frozenset[str]] = None,
    ) -> None:
        self.weights = weights or RankingWeights()
        self._stopwords = stopwords if stopwords is not None else TURKISH_STOPWORDS

    # ── public API ────────────────────────────────────────────────────

    def rank(
        self,
        query: str,
        items: Sequence[MemoryItem],
        top_k: int = 5,
        type_filter: Optional[MemoryItemType] = None,
        time_window: Optional[timedelta] = None,
        now: Optional[datetime] = None,
    ) -> List[RankedMemory]:
        """Score and rank *items* against *query*.

        Parameters
        ----------
        query:
            Natural-language query.
        items:
            Candidate memory items.
        top_k:
            Maximum number of results.
        type_filter:
            If set, only items of this type are considered.
        time_window:
            If set, items older than ``now - time_window`` are excluded.
        now:
            Reference time (defaults to ``datetime.utcnow()``).
        """
        now = now or datetime.utcnow()
        query_tokens = self._tokenise(query)

        # Build IDF over the item corpus
        idf = self._build_idf(items)

        candidates: List[RankedMemory] = []
        for item in items:
            # Apply filters
            if type_filter and item.type != type_filter:
                continue
            if time_window and (now - item.created_at) > time_window:
                continue

            kw_score = self._keyword_score(query_tokens, item.content, idf)
            sem_score = self._semantic_score(query, item)
            rec_boost = self._recency_boost(item, now)
            imp_score = item.importance

            w = self.weights
            # If no embeddings available anywhere, redistribute β to keyword
            if sem_score == 0.0 and item.embedding_vector is None:
                effective_kw = w.keyword + w.semantic
                effective_sem = 0.0
            else:
                effective_kw = w.keyword
                effective_sem = w.semantic

            total = (
                effective_kw * kw_score
                + effective_sem * sem_score
                + w.recency * rec_boost
                + w.importance * imp_score
            )

            candidates.append(
                RankedMemory(
                    item=item,
                    total_score=total,
                    keyword_score=kw_score,
                    semantic_score=sem_score,
                    recency_boost=rec_boost,
                    importance_score=imp_score,
                )
            )

        candidates.sort(key=lambda r: r.total_score, reverse=True)
        return candidates[:top_k]

    # ── keyword scoring (BM25-lite) ──────────────────────────────────

    def _tokenise(self, text: str) -> List[str]:
        """Lower-case, split, strip punctuation, remove stop-words."""
        tokens: List[str] = []
        for raw in text.lower().split():
            tok = raw.strip(".,;:!?\"'()-–—…")
            if tok and tok not in self._stopwords:
                tokens.append(tok)
        return tokens

    def _build_idf(self, items: Sequence[MemoryItem]) -> Dict[str, float]:
        """Inverse Document Frequency across the item corpus."""
        n = len(items)
        if n == 0:
            return {}
        doc_freq: Dict[str, int] = {}
        for item in items:
            unique_tokens = set(self._tokenise(item.content))
            for tok in unique_tokens:
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

        idf: Dict[str, float] = {}
        for tok, df in doc_freq.items():
            idf[tok] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
        return idf

    def _keyword_score(
        self,
        query_tokens: List[str],
        content: str,
        idf: Dict[str, float],
    ) -> float:
        """BM25-lite score: TF × IDF with saturation.

        Uses *k1 = 1.5* and *b = 0.0* (no length normalisation) so the
        formula simplifies to::

            score = Σ idf(q) × (tf(q, doc) × (k1 + 1)) / (tf(q, doc) + k1)
        """
        if not query_tokens:
            return 0.0

        k1 = 1.5
        doc_tokens = self._tokenise(content)
        if not doc_tokens:
            return 0.0

        # term frequency in document
        tf: Dict[str, int] = {}
        for t in doc_tokens:
            tf[t] = tf.get(t, 0) + 1

        score = 0.0
        for qt in query_tokens:
            f = tf.get(qt, 0)
            if f == 0:
                continue
            idf_val = idf.get(qt, 1.0)
            score += idf_val * (f * (k1 + 1)) / (f + k1)

        # Normalise to 0–1 range (cap at reasonable ceiling)
        max_possible = len(query_tokens) * 3.0  # generous upper bound
        return min(score / max_possible, 1.0) if max_possible > 0 else 0.0

    # ── semantic scoring ─────────────────────────────────────────────

    @staticmethod
    def _semantic_score(query: str, item: MemoryItem) -> float:  # noqa: ARG004
        """Cosine similarity between query embedding and item embedding.

        Phase-1: always returns 0.0 (embedding support is optional).
        When an embedding provider is wired in, this will compute the
        actual cosine similarity.
        """
        # TODO(#450): integrate embedding provider (sentence-transformers / Gemini)
        return 0.0

    # ── recency boost ────────────────────────────────────────────────

    @staticmethod
    def _recency_boost(item: MemoryItem, now: datetime) -> float:
        """Recency bonus: last 24 h → 1.0, last 7 d → 0.5, older → 0.0."""
        age = now - item.created_at
        if age <= timedelta(hours=24):
            return 1.0
        if age <= timedelta(days=7):
            return 0.5
        return 0.0
