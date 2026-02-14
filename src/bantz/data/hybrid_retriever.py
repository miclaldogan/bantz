"""
HybridRetriever — Combines keyword search with graph traversal.

Given a user query, the retriever:

1. **Keyword search** — finds nodes whose properties contain query tokens.
2. **Graph expansion** — traverses 1–2 hops from matched nodes.
3. **Rank & merge** — scores results by relevance × edge weight.

A future version will add embedding-based similarity (semantic search)
when an embedder is provided.  The current MVP uses keyword matching
which is fast and dependency-free.

Usage::

    retriever = HybridRetriever(graph_store)
    results = await retriever.recall("Ali ile ilgili her şey")
    # [{"node": GraphNode(...), "score": 0.85, "path": ["Ali → SENT → Email"]}]
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from bantz.data.graph_store import GraphNode, GraphStore

logger = logging.getLogger(__name__)


class RetrievalResult:
    """A single retrieval hit with score and provenance."""

    __slots__ = ("node", "score", "path", "depth")

    def __init__(
        self,
        node: GraphNode,
        score: float = 1.0,
        path: Optional[List[str]] = None,
        depth: int = 0,
    ) -> None:
        self.node = node
        self.score = score
        self.path = path or []
        self.depth = depth

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node.id,
            "label": self.node.label,
            "properties": self.node.properties,
            "score": round(self.score, 4),
            "path": self.path,
            "depth": self.depth,
        }

    def __repr__(self) -> str:
        return f"RetrievalResult({self.node.label}:{self.node.id[:8]}… score={self.score:.3f})"


class HybridRetriever:
    """Keyword search + graph expansion retriever.

    Parameters
    ----------
    store:
        The graph backend to query.
    max_depth:
        How many hops to expand from seed nodes (default 2).
    expansion_decay:
        Score multiplier per hop depth (default 0.5).
        Depth-1 neighbours get ``score × 0.5``, depth-2 get ``× 0.25``.
    min_weight:
        Minimum edge weight to follow during expansion.
    """

    def __init__(
        self,
        store: GraphStore,
        max_depth: int = 2,
        expansion_decay: float = 0.5,
        min_weight: float = 0.05,
    ) -> None:
        self._store = store
        self._max_depth = max_depth
        self._expansion_decay = expansion_decay
        self._min_weight = min_weight

    async def recall(
        self,
        query: str,
        top_k: int = 10,
        label_filter: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """Retrieve relevant nodes for *query*.

        Steps:
        1. Tokenize query → keyword set
        2. Search nodes whose properties match any keyword
        3. Expand matched nodes via graph traversal
        4. Score, deduplicate, sort, return top_k
        """
        tokens = self._tokenize(query)
        if not tokens:
            return []

        # Step 1: keyword seed search
        seeds = await self._keyword_search(tokens, label_filter)
        logger.debug("HybridRetriever: %d seeds from %d tokens", len(seeds), len(tokens))

        # Step 2: graph expansion
        expanded = await self._expand(seeds)

        # Step 3: merge & rank
        merged = self._merge(seeds, expanded)

        # Step 4: sort & limit
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:top_k]

    # ── keyword search ──

    async def _keyword_search(
        self,
        tokens: List[str],
        label_filter: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """Find nodes whose properties contain any of the tokens."""
        results: Dict[str, RetrievalResult] = {}

        # Search by each token against common property names
        for token in tokens:
            # Try exact property matches first
            for prop_name in ("name", "email", "subject", "title", "task_id", "event_id"):
                nodes = await self._store.search_nodes(
                    label=label_filter, limit=20, **{prop_name: token}
                )
                for node in nodes:
                    if node.id not in results:
                        results[node.id] = RetrievalResult(
                            node=node, score=1.0, path=[f"keyword:{prop_name}={token}"],
                        )
                    else:
                        # Boost score for multiple token matches
                        results[node.id].score = min(results[node.id].score + 0.3, 2.0)

        # Also do fuzzy property matching across all nodes
        # (search all nodes of each label and check if any property value contains a token)
        if not results:
            for label in (
                [label_filter] if label_filter else ["Person", "Email", "Event", "Task", "Project", "Org"]
            ):
                all_nodes = await self._store.search_nodes(label=label, limit=100)
                for node in all_nodes:
                    score = self._property_match_score(node, tokens)
                    if score > 0 and node.id not in results:
                        results[node.id] = RetrievalResult(
                            node=node, score=score, path=["fuzzy_match"],
                        )

        return list(results.values())

    # ── graph expansion ──

    async def _expand(
        self,
        seeds: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """Expand seed nodes via graph traversal."""
        expanded: Dict[str, RetrievalResult] = {}
        seed_ids = {r.node.id for r in seeds}

        for seed in seeds:
            neighbours = await self._store.get_neighbors(
                seed.node.id,
                direction="both",
                max_depth=self._max_depth,
                min_weight=self._min_weight,
            )
            for i, nb in enumerate(neighbours):
                if nb.id in seed_ids:
                    continue
                depth = 1  # Simplified depth tracking
                decay = self._expansion_decay ** depth
                score = seed.score * decay

                if nb.id in expanded:
                    expanded[nb.id].score = max(expanded[nb.id].score, score)
                else:
                    expanded[nb.id] = RetrievalResult(
                        node=nb,
                        score=score,
                        path=[f"expand:{seed.node.label}→{nb.label}"],
                        depth=depth,
                    )

        return list(expanded.values())

    # ── merge ──

    @staticmethod
    def _merge(
        seeds: List[RetrievalResult],
        expanded: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """Merge seed and expanded results, deduplicating by node ID."""
        merged: Dict[str, RetrievalResult] = {}
        for r in seeds:
            merged[r.node.id] = r
        for r in expanded:
            if r.node.id in merged:
                merged[r.node.id].score = max(merged[r.node.id].score, r.score)
            else:
                merged[r.node.id] = r
        return list(merged.values())

    # ── utility ──

    _TOKEN_RE = re.compile(r"\w+", re.UNICODE)

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        """Split text into searchable tokens, lower-cased."""
        # Filter out common stop words
        stop = {"ile", "ve", "bir", "de", "da", "için", "her", "şey",
                "the", "and", "for", "with", "all", "from", "about"}
        tokens = cls._TOKEN_RE.findall(text.lower())
        return [t for t in tokens if t not in stop and len(t) > 1]

    @staticmethod
    def _property_match_score(node: GraphNode, tokens: List[str]) -> float:
        """Score a node based on how many tokens appear in its properties."""
        score = 0.0
        for val in node.properties.values():
            if not isinstance(val, str):
                continue
            val_lower = val.lower()
            for token in tokens:
                if token in val_lower:
                    score += 0.5
        return min(score, 2.0)
