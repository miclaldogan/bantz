"""Tests for issue #450 — Memory retrieval v0: hybrid scoring."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bantz.memory.models import MemoryItem, MemoryItemType
from bantz.memory.ranking import (
    TURKISH_STOPWORDS,
    HybridRanker,
    RankedMemory,
    RankingWeights,
)

# ── Helpers ───────────────────────────────────────────────────────────

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _item(
    content: str,
    importance: float = 0.5,
    created_at: datetime | None = None,
    item_type: MemoryItemType = MemoryItemType.EPISODIC,
    session_id: str | None = None,
) -> MemoryItem:
    return MemoryItem(
        content=content,
        importance=importance,
        created_at=created_at or NOW,
        accessed_at=created_at or NOW,
        type=item_type,
        session_id=session_id,
    )


# ── TestKeywordScoring ────────────────────────────────────────────────

class TestKeywordScoring:
    """BM25-lite keyword matching."""

    def test_exact_word_match(self):
        ranker = HybridRanker()
        items = [
            _item("Ankara'ya yarın uçak bileti al"),
            _item("Bugün hava çok güzel"),
        ]
        results = ranker.rank("Ankara uçak", items, now=NOW)
        assert results[0].item.content.startswith("Ankara")
        assert results[0].keyword_score > 0

    def test_no_match_returns_zero_keyword(self):
        ranker = HybridRanker()
        items = [_item("Bugün hava güzel")]
        results = ranker.rank("programlama python", items, now=NOW)
        assert results[0].keyword_score == 0.0

    def test_stopwords_ignored(self):
        ranker = HybridRanker()
        tokens = ranker._tokenise("bu bir çok güzel ev")
        assert "bu" not in tokens
        assert "bir" not in tokens
        assert "çok" not in tokens
        assert "güzel" in tokens
        assert "ev" in tokens

    def test_turkish_stopwords_present(self):
        assert "ve" in TURKISH_STOPWORDS
        assert "için" in TURKISH_STOPWORDS
        assert "şimdi" in TURKISH_STOPWORDS

    def test_multiple_keyword_match_beats_single(self):
        ranker = HybridRanker()
        items = [
            _item("Ankara uçak bileti"),
            _item("Ankara şehir merkezi"),
        ]
        results = ranker.rank("Ankara uçak", items, now=NOW)
        # first result should have both keywords
        assert results[0].keyword_score >= results[1].keyword_score

    def test_case_insensitive_matching(self):
        ranker = HybridRanker()
        items = [_item("ANKARA uçak BİLETİ")]
        results = ranker.rank("ankara bileti", items, now=NOW)
        assert results[0].keyword_score > 0


# ── TestRecencyBoost ──────────────────────────────────────────────────

class TestRecencyBoost:
    """Recency scoring: newer items score higher."""

    def test_recent_item_high_boost(self):
        ranker = HybridRanker()
        item = _item("test", created_at=NOW - timedelta(hours=2))
        results = ranker.rank("test", [item], now=NOW)
        assert results[0].recency_boost == 1.0

    def test_week_old_item_medium_boost(self):
        ranker = HybridRanker()
        item = _item("test", created_at=NOW - timedelta(days=3))
        results = ranker.rank("test", [item], now=NOW)
        assert results[0].recency_boost == 0.5

    def test_old_item_no_boost(self):
        ranker = HybridRanker()
        item = _item("test", created_at=NOW - timedelta(days=30))
        results = ranker.rank("test", [item], now=NOW)
        assert results[0].recency_boost == 0.0

    def test_newer_beats_older(self):
        ranker = HybridRanker()
        items = [
            _item("toplantı notu", created_at=NOW - timedelta(days=30), importance=0.5),
            _item("toplantı notu", created_at=NOW - timedelta(hours=1), importance=0.5),
        ]
        results = ranker.rank("toplantı", items, now=NOW)
        assert results[0].recency_boost > results[1].recency_boost


# ── TestImportanceBoost ───────────────────────────────────────────────

class TestImportanceBoost:
    """Importance field boosts ranking."""

    def test_high_importance_beats_low(self):
        ranker = HybridRanker()
        items = [
            _item("Python kursu", importance=0.2, created_at=NOW),
            _item("Python sertifika", importance=0.9, created_at=NOW),
        ]
        results = ranker.rank("Python", items, now=NOW)
        # Higher importance should win (both have same recency/keyword match)
        assert results[0].importance_score >= results[1].importance_score

    def test_importance_in_score(self):
        ranker = HybridRanker()
        item = _item("veri", importance=0.8, created_at=NOW)
        results = ranker.rank("veri", [item], now=NOW)
        assert results[0].importance_score == 0.8


# ── TestTopK ──────────────────────────────────────────────────────────

class TestTopK:
    """top_k parameter limits results."""

    def test_top_k_limits_output(self):
        ranker = HybridRanker()
        items = [_item(f"belge {i}") for i in range(20)]
        results = ranker.rank("belge", items, top_k=3, now=NOW)
        assert len(results) == 3

    def test_top_k_larger_than_items(self):
        ranker = HybridRanker()
        items = [_item("tek belge")]
        results = ranker.rank("belge", items, top_k=10, now=NOW)
        assert len(results) == 1


# ── TestEmptyMemory ───────────────────────────────────────────────────

class TestEmptyMemory:
    """Edge case: no items in memory."""

    def test_empty_items_returns_empty(self):
        ranker = HybridRanker()
        results = ranker.rank("herhangi sorgu", [], now=NOW)
        assert results == []

    def test_empty_query(self):
        ranker = HybridRanker()
        items = [_item("veri")]
        results = ranker.rank("", items, now=NOW)
        # Still returns items (recency + importance contribute)
        assert len(results) == 1
        assert results[0].keyword_score == 0.0


# ── TestTypeFilter ────────────────────────────────────────────────────

class TestTypeFilter:
    """type_filter parameter restricts item types."""

    def test_filter_episodic_only(self):
        ranker = HybridRanker()
        items = [
            _item("fakt", item_type=MemoryItemType.FACT),
            _item("anı", item_type=MemoryItemType.EPISODIC),
            _item("bilgi", item_type=MemoryItemType.SEMANTIC),
        ]
        results = ranker.rank(
            "test", items, type_filter=MemoryItemType.EPISODIC, now=NOW
        )
        assert all(r.item.type == MemoryItemType.EPISODIC for r in results)

    def test_filter_fact_only(self):
        ranker = HybridRanker()
        items = [
            _item("fakt bilgi", item_type=MemoryItemType.FACT),
            _item("anı bilgi", item_type=MemoryItemType.EPISODIC),
        ]
        results = ranker.rank(
            "bilgi", items, type_filter=MemoryItemType.FACT, now=NOW
        )
        assert len(results) == 1
        assert results[0].item.type == MemoryItemType.FACT


# ── TestTimeWindow ────────────────────────────────────────────────────

class TestTimeWindow:
    """time_window parameter filters old items."""

    def test_time_window_excludes_old(self):
        ranker = HybridRanker()
        items = [
            _item("yeni not", created_at=NOW - timedelta(hours=5)),
            _item("eski not", created_at=NOW - timedelta(days=10)),
        ]
        results = ranker.rank(
            "not", items, time_window=timedelta(days=7), now=NOW
        )
        assert len(results) == 1
        assert "yeni" in results[0].item.content


# ── TestWeights ───────────────────────────────────────────────────────

class TestWeights:
    """Custom weight configuration."""

    def test_custom_weights(self):
        w = RankingWeights(keyword=0.5, semantic=0.0, recency=0.25, importance=0.25)
        ranker = HybridRanker(weights=w)
        items = [_item("test veri")]
        results = ranker.rank("test", items, now=NOW)
        assert len(results) == 1

    def test_zero_weights_raises(self):
        with pytest.raises(ValueError):
            RankingWeights(keyword=0, semantic=0, recency=0, importance=0)


# ── TestRankedMemoryOrdering ──────────────────────────────────────────

class TestRankedMemoryOrdering:
    """RankedMemory comparison support."""

    def test_lt_comparison(self):
        a = RankedMemory(item=_item("a"), total_score=0.3)
        b = RankedMemory(item=_item("b"), total_score=0.7)
        assert a < b

    def test_sorted_descending(self):
        ranker = HybridRanker()
        items = [
            _item("belge A", importance=0.1),
            _item("belge B", importance=0.9),
        ]
        results = ranker.rank("belge", items, now=NOW)
        scores = [r.total_score for r in results]
        assert scores == sorted(scores, reverse=True)


# ── TestIntegrationWithPersistentStore ────────────────────────────────

class TestIntegrationWithPersistentStore:
    """Round-trip: write to PersistentMemoryStore → rank results."""

    def test_store_search_then_rank(self):
        from bantz.memory.persistent import PersistentMemoryStore

        store = PersistentMemoryStore(":memory:")
        sess = store.create_session()

        store.write(_item("Ankara'ya bilet al", session_id=sess.id))
        store.write(_item("Python öğren", session_id=sess.id))
        store.write(_item("Ankara toplantısı", session_id=sess.id))

        found = store.search("Ankara", limit=10)
        ranker = HybridRanker()
        ranked = ranker.rank("Ankara", found, now=NOW)
        assert len(ranked) == 2
        assert all("Ankara" in r.item.content for r in ranked)

    def test_access_count_updated(self):
        from bantz.memory.persistent import PersistentMemoryStore

        store = PersistentMemoryStore(":memory:")
        sess = store.create_session()
        item = _item("hatırla bunu", session_id=sess.id)
        store.write(item)

        # Simulate retrieval → update access
        found = store.search("hatırla")
        for f in found:
            store.update_access(f.id)

        updated = store.read(item.id)
        assert updated is not None
        assert updated.access_count == 1
