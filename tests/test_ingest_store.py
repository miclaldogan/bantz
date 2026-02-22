"""
Tests for bantz.data.ingest_store — IngestStore, DataClass, fingerprinting.

Issue #1288: Ingest Store + TTL Cache + Fingerprint
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from bantz.data.ingest_store import (_TTL_MAP, DataClass, IngestStore,
                                     classify_tool_result, fingerprint,
                                     start_ttl_sweeper, ttl_sweep_once)

# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def store():
    """In-memory IngestStore for tests."""
    s = IngestStore(db_path=":memory:", auto_sweep=False)
    yield s
    s.close()


@pytest.fixture
def store_with_sweep():
    """In-memory IngestStore with auto-sweep enabled (interval=0 for immediate)."""
    s = IngestStore(db_path=":memory:", auto_sweep=True, sweep_interval=0)
    yield s
    s.close()


# ── DataClass ─────────────────────────────────────────────────────

class TestDataClass:
    def test_enum_values(self):
        assert DataClass.EPHEMERAL.value == "EPHEMERAL"
        assert DataClass.SESSION.value == "SESSION"
        assert DataClass.PERSISTENT.value == "PERSISTENT"

    def test_enum_from_string(self):
        assert DataClass("EPHEMERAL") == DataClass.EPHEMERAL
        assert DataClass("SESSION") == DataClass.SESSION
        assert DataClass("PERSISTENT") == DataClass.PERSISTENT

    def test_ttl_map_values(self):
        assert _TTL_MAP[DataClass.EPHEMERAL] == 24 * 3600
        assert _TTL_MAP[DataClass.SESSION] == 7 * 24 * 3600
        assert _TTL_MAP[DataClass.PERSISTENT] is None


# ── Fingerprinting ────────────────────────────────────────────────

class TestFingerprint:
    def test_deterministic(self):
        """Same content + source always produces the same hash."""
        fp1 = fingerprint({"key": "value"}, "gmail")
        fp2 = fingerprint({"key": "value"}, "gmail")
        assert fp1 == fp2

    def test_different_content(self):
        fp1 = fingerprint({"key": "value1"}, "gmail")
        fp2 = fingerprint({"key": "value2"}, "gmail")
        assert fp1 != fp2

    def test_different_source(self):
        fp1 = fingerprint({"key": "value"}, "gmail")
        fp2 = fingerprint({"key": "value"}, "calendar")
        assert fp1 != fp2

    def test_dict_key_order_independent(self):
        """JSON sort_keys ensures key order doesn't matter."""
        fp1 = fingerprint({"b": 2, "a": 1}, "test")
        fp2 = fingerprint({"a": 1, "b": 2}, "test")
        assert fp1 == fp2

    def test_sha256_length(self):
        fp = fingerprint("test", "source")
        assert len(fp) == 64  # SHA-256 hex digest

    def test_list_content(self):
        fp1 = fingerprint([1, 2, 3], "test")
        fp2 = fingerprint([1, 2, 3], "test")
        assert fp1 == fp2

    def test_string_content(self):
        fp1 = fingerprint("hello world", "test")
        fp2 = fingerprint("hello world", "test")
        assert fp1 == fp2

    def test_unicode_content(self):
        """Turkish characters should fingerprint correctly."""
        fp1 = fingerprint({"konu": "Türkçe içerik"}, "gmail")
        fp2 = fingerprint({"konu": "Türkçe içerik"}, "gmail")
        assert fp1 == fp2


# ── IngestStore: Basic CRUD ──────────────────────────────────────

class TestIngestStoreCRUD:
    def test_ingest_returns_id(self, store):
        rid = store.ingest({"msg": "hello"}, source="test")
        assert isinstance(rid, str)
        assert len(rid) == 32  # uuid4 hex

    def test_get_by_id(self, store):
        rid = store.ingest({"msg": "hello"}, source="test")
        record = store.get(rid)
        assert record is not None
        assert record.id == rid
        assert record.content == {"msg": "hello"}
        assert record.source == "test"

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent_id") is None

    def test_default_data_class(self, store):
        rid = store.ingest({"x": 1}, source="test")
        record = store.get(rid)
        assert record.data_class == DataClass.EPHEMERAL

    def test_explicit_data_class(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.PERSISTENT)
        record = store.get(rid)
        assert record.data_class == DataClass.PERSISTENT

    def test_summary_stored(self, store):
        rid = store.ingest({"x": 1}, source="test", summary="Test summary")
        record = store.get(rid)
        assert record.summary == "Test summary"

    def test_meta_stored(self, store):
        meta = {"tool_name": "gmail.search", "elapsed_ms": 150}
        rid = store.ingest({"x": 1}, source="test", meta=meta)
        record = store.get(rid)
        assert record.meta == meta

    def test_delete(self, store):
        rid = store.ingest({"x": 1}, source="test")
        assert store.delete(rid) is True
        assert store.get(rid) is None

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent") is False

    def test_update_summary(self, store):
        rid = store.ingest({"x": 1}, source="test")
        store.update_summary(rid, "Updated summary")
        record = store.get(rid)
        assert record.summary == "Updated summary"

    def test_update_meta_merge(self, store):
        rid = store.ingest({"x": 1}, source="test", meta={"a": 1})
        store.update_meta(rid, {"b": 2})
        record = store.get(rid)
        assert record.meta == {"a": 1, "b": 2}


# ── IngestStore: Deduplication ────────────────────────────────────

class TestIngestStoreDedup:
    def test_same_content_same_source_dedup(self, store):
        """Identical content from same source → single record."""
        rid1 = store.ingest({"subject": "hello"}, source="gmail")
        rid2 = store.ingest({"subject": "hello"}, source="gmail")
        assert rid1 == rid2

    def test_same_content_different_source_no_dedup(self, store):
        """Same content from different sources → separate records."""
        rid1 = store.ingest({"subject": "hello"}, source="gmail")
        rid2 = store.ingest({"subject": "hello"}, source="calendar")
        assert rid1 != rid2

    def test_different_content_same_source_no_dedup(self, store):
        rid1 = store.ingest({"subject": "hello"}, source="gmail")
        rid2 = store.ingest({"subject": "world"}, source="gmail")
        assert rid1 != rid2

    def test_dedup_increments_access_count(self, store):
        rid = store.ingest({"x": 1}, source="test")
        record1 = store.get(rid)
        initial_count = record1.access_count

        # Ingest same content again — dedup should bump access_count
        store.ingest({"x": 1}, source="test")
        record2 = store.get(rid)
        assert record2.access_count > initial_count

    def test_dedup_updates_accessed_at(self, store):
        rid = store.ingest({"x": 1}, source="test")
        record1 = store.get(rid)
        t1 = record1.accessed_at

        time.sleep(0.01)  # Small delay
        store.ingest({"x": 1}, source="test")  # Dedup
        record2 = store.get(rid)
        assert record2.accessed_at >= t1

    def test_get_by_fingerprint(self, store):
        rid = store.ingest({"hello": "world"}, source="test")
        fp = fingerprint({"hello": "world"}, "test")
        record = store.get_by_fingerprint(fp)
        assert record is not None
        assert record.id == rid


# ── IngestStore: TTL / Expiration ─────────────────────────────────

class TestIngestStoreTTL:
    def test_ephemeral_has_expires_at(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.EPHEMERAL)
        record = store.get(rid)
        assert record.expires_at is not None
        # Expires roughly 24h from now
        expected = time.time() + 24 * 3600
        assert abs(record.expires_at - expected) < 5

    def test_session_has_expires_at(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.SESSION)
        record = store.get(rid)
        assert record.expires_at is not None
        expected = time.time() + 7 * 24 * 3600
        assert abs(record.expires_at - expected) < 5

    def test_persistent_no_expires(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.PERSISTENT)
        record = store.get(rid)
        assert record.expires_at is None

    def test_custom_ttl(self, store):
        rid = store.ingest({"x": 1}, source="test", custom_ttl=60)
        record = store.get(rid)
        expected = time.time() + 60
        assert abs(record.expires_at - expected) < 5

    def test_expired_record_not_returned_by_get(self, store):
        """Records past their TTL are invisible."""
        rid = store.ingest({"x": 1}, source="test", custom_ttl=0.001)
        time.sleep(0.01)
        record = store.get(rid)
        assert record is None

    def test_sweep_deletes_expired(self, store):
        store.ingest({"a": 1}, source="test", custom_ttl=0.001)
        store.ingest({"b": 2}, source="test", custom_ttl=0.001)
        store.ingest({"c": 3}, source="test", data_class=DataClass.PERSISTENT)
        time.sleep(0.01)

        deleted = store.sweep_expired()
        assert deleted == 2
        # Persistent record survives
        stats = store.stats()
        assert stats["total"] == 1

    def test_sweep_returns_zero_when_nothing_expired(self, store):
        store.ingest({"x": 1}, source="test", data_class=DataClass.PERSISTENT)
        assert store.sweep_expired() == 0

    def test_auto_sweep_on_ingest(self, store_with_sweep):
        """Auto-sweep triggers during ingest when interval has passed."""
        store_with_sweep.ingest({"a": 1}, source="test", custom_ttl=0.001)
        time.sleep(0.01)
        # Next ingest should trigger sweep
        store_with_sweep.ingest({"b": 2}, source="test", data_class=DataClass.PERSISTENT)
        stats = store_with_sweep.stats()
        assert stats["expired_pending_sweep"] == 0


# ── IngestStore: Query / Search ───────────────────────────────────

class TestIngestStoreQuery:
    def test_query_all(self, store):
        store.ingest({"a": 1}, source="gmail")
        store.ingest({"b": 2}, source="calendar")
        store.ingest({"c": 3}, source="web")
        results = store.query()
        assert len(results) == 3

    def test_query_by_source(self, store):
        store.ingest({"a": 1}, source="gmail")
        store.ingest({"b": 2}, source="calendar")
        results = store.query(source="gmail")
        assert len(results) == 1
        assert results[0].source == "gmail"

    def test_query_by_data_class(self, store):
        store.ingest({"a": 1}, source="test", data_class=DataClass.EPHEMERAL)
        store.ingest({"b": 2}, source="test", data_class=DataClass.PERSISTENT)
        results = store.query(data_class=DataClass.PERSISTENT)
        assert len(results) == 1
        assert results[0].data_class == DataClass.PERSISTENT

    def test_query_excludes_expired(self, store):
        store.ingest({"a": 1}, source="test", custom_ttl=0.001)
        store.ingest({"b": 2}, source="test", data_class=DataClass.PERSISTENT)
        time.sleep(0.01)
        results = store.query()
        assert len(results) == 1

    def test_query_include_expired(self, store):
        store.ingest({"a": 1}, source="test", custom_ttl=0.001)
        store.ingest({"b": 2}, source="test", data_class=DataClass.PERSISTENT)
        time.sleep(0.01)
        results = store.query(include_expired=True)
        assert len(results) == 2

    def test_query_limit(self, store):
        for i in range(10):
            store.ingest({f"item_{i}": i}, source="test")
        results = store.query(limit=3)
        assert len(results) == 3

    def test_search_keyword(self, store):
        store.ingest({"subject": "toplantı notları"}, source="gmail")
        store.ingest({"subject": "alışveriş listesi"}, source="gmail")
        results = store.search("toplantı")
        assert len(results) == 1

    def test_search_in_summary(self, store):
        store.ingest({"x": 1}, source="test", summary="Ali toplantı planı")
        results = store.search("Ali")
        assert len(results) == 1

    def test_search_by_source(self, store):
        store.ingest({"msg": "hello"}, source="gmail")
        store.ingest({"msg": "hello"}, source="calendar")
        results = store.search("hello", source="gmail")
        assert len(results) == 1

    def test_query_order_by_created_at(self, store):
        r1 = store.ingest({"a": 1}, source="test")
        r2 = store.ingest({"b": 2}, source="test")
        results = store.query(order_by="created_at")
        assert len(results) == 2
        # Most recently created record should come first (DESC order)
        assert results[0].id == r2
        assert results[1].id == r1

    def test_query_order_by_invalid_raises(self, store):
        with pytest.raises(ValueError, match="order_by"):
            store.query(order_by="injected_column; DROP TABLE")


# ── IngestStore: Tags ─────────────────────────────────────────────

class TestIngestStoreQueryTags:
    """Issue #1471 — query() tags AND filtering."""

    def test_ingest_stores_tags(self, store):
        rid = store.ingest({"x": 1}, source="gmail", tags=["unread", "important"])
        record = store.get(rid)
        assert set(record.tags) == {"unread", "important"}

    def test_ingest_no_tags_defaults_empty(self, store):
        rid = store.ingest({"x": 1}, source="test")
        record = store.get(rid)
        assert record.tags == []

    def test_query_by_single_tag(self, store):
        store.ingest({"a": 1}, source="gmail", tags=["unread"])
        store.ingest({"b": 2}, source="gmail", tags=["read"])
        store.ingest({"c": 3}, source="gmail")
        results = store.query(tags=["unread"])
        assert len(results) == 1
        assert "unread" in results[0].tags

    def test_query_tags_and_logic(self, store):
        """Both tags must be present — AND, not OR."""
        store.ingest({"a": 1}, source="gmail", tags=["unread", "important"])
        store.ingest({"b": 2}, source="gmail", tags=["unread"])
        store.ingest({"c": 3}, source="gmail", tags=["important"])
        results = store.query(tags=["unread", "important"])
        assert len(results) == 1
        assert set(results[0].tags) == {"unread", "important"}

    def test_query_empty_tags_matches_all(self, store):
        store.ingest({"a": 1}, source="gmail", tags=["unread"])
        store.ingest({"b": 2}, source="gmail")
        results = store.query(tags=[])
        assert len(results) == 2

    def test_query_tags_no_match_returns_empty(self, store):
        store.ingest({"a": 1}, source="gmail", tags=["unread"])
        results = store.query(tags=["nonexistent"])
        assert results == []

    def test_query_tags_combined_with_source(self, store):
        store.ingest({"a": 1}, source="gmail", tags=["unread"])
        store.ingest({"b": 2}, source="calendar", tags=["unread"])
        results = store.query(source="gmail", tags=["unread"])
        assert len(results) == 1
        assert results[0].source == "gmail"

    def test_query_tags_combined_with_data_class(self, store):
        store.ingest({"a": 1}, source="test", data_class=DataClass.PERSISTENT,
                     tags=["important"])
        store.ingest({"b": 2}, source="test", data_class=DataClass.EPHEMERAL,
                     tags=["important"])
        results = store.query(data_class=DataClass.PERSISTENT, tags=["important"])
        assert len(results) == 1
        assert results[0].data_class == DataClass.PERSISTENT

    def test_tags_stored_deduplicated(self, store):
        rid = store.ingest({"x": 1}, source="test", tags=["unread", "unread", "important"])
        record = store.get(rid)
        assert record.tags.count("unread") == 1

    def test_to_dict_includes_tags(self, store):
        rid = store.ingest({"x": 1}, source="test", tags=["alpha", "beta"])
        record = store.get(rid)
        d = record.to_dict()
        assert "tags" in d
        assert set(d["tags"]) == {"alpha", "beta"}

    def test_thread_safe_tag_query(self, store):
        """Concurrent tag queries under threading.Lock must not corrupt order."""
        for i in range(20):
            store.ingest({f"item_{i}": i}, source="test",
                         tags=["bulk"] if i % 2 == 0 else [])

        results_per_thread: list = []
        errors: list = []

        def worker():
            try:
                r = store.query(tags=["bulk"])
                results_per_thread.append(len(r))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Each thread should see 10 records tagged "bulk"
        for count in results_per_thread:
            assert count == 10

    def test_query_tags_limit_not_truncated_before_filter(self, store):
        """Critical: limit must be applied AFTER Python-side tag filtering.

        Ingests 10 untagged records first, then 5 tagged records.
        If LIMIT were applied in SQL before the Python tag filter, a
        limit=5 query would fetch only the first 5 (untagged) rows and
        return an empty list — incorrect behaviour.
        """
        for i in range(10):
            store.ingest({f"untagged_{i}": i}, source="test")
        for i in range(5):
            store.ingest({f"tagged_{i}": i}, source="test", tags=["needle"])

        results = store.query(tags=["needle"], limit=5)
        assert len(results) == 5, (
            "limit should apply after tag filter, not truncate before it"
        )


# ── IngestStore: Promote ──────────────────────────────────────────

class TestIngestStorePromote:
    def test_promote_ephemeral_to_persistent(self, store):
        rid = store.ingest({"contact": "Ali"}, source="test", data_class=DataClass.EPHEMERAL)
        record = store.get(rid)
        assert record.expires_at is not None

        store.promote(rid, DataClass.PERSISTENT)
        record = store.get(rid)
        assert record.data_class == DataClass.PERSISTENT
        assert record.expires_at is None

    def test_promote_session_to_persistent(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.SESSION)
        store.promote(rid, DataClass.PERSISTENT)
        record = store.get(rid)
        assert record.data_class == DataClass.PERSISTENT

    def test_promote_nonexistent(self, store):
        assert store.promote("fake_id", DataClass.PERSISTENT) is False


# ── IngestStore: Stats ────────────────────────────────────────────

class TestIngestStoreStats:
    def test_empty_stats(self, store):
        stats = store.stats()
        assert stats["total"] == 0
        assert stats["by_class"] == {}
        assert stats["by_source"] == {}
        assert stats["expired_pending_sweep"] == 0

    def test_stats_count(self, store):
        store.ingest({"a": 1}, source="gmail", data_class=DataClass.EPHEMERAL)
        store.ingest({"b": 2}, source="gmail", data_class=DataClass.PERSISTENT)
        store.ingest({"c": 3}, source="calendar", data_class=DataClass.EPHEMERAL)
        stats = store.stats()
        assert stats["total"] == 3
        assert stats["by_class"]["EPHEMERAL"] == 2
        assert stats["by_class"]["PERSISTENT"] == 1
        assert stats["by_source"]["gmail"] == 2
        assert stats["by_source"]["calendar"] == 1


# ── IngestRecord ──────────────────────────────────────────────────

class TestIngestRecord:
    def test_is_expired_false(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.EPHEMERAL)
        record = store.get(rid)
        assert record.is_expired is False

    def test_is_expired_persistent(self, store):
        rid = store.ingest({"x": 1}, source="test", data_class=DataClass.PERSISTENT)
        record = store.get(rid)
        assert record.is_expired is False  # Never expires

    def test_to_dict(self, store):
        rid = store.ingest({"x": 1}, source="test", summary="sum", meta={"m": 1})
        record = store.get(rid)
        d = record.to_dict()
        assert d["id"] == rid
        assert d["source"] == "test"
        assert d["content"] == {"x": 1}
        assert d["summary"] == "sum"
        assert d["meta"] == {"m": 1}
        assert d["data_class"] == "EPHEMERAL"

    def test_age_seconds(self, store):
        rid = store.ingest({"x": 1}, source="test")
        record = store.get(rid)
        assert record.age_seconds >= 0
        assert record.age_seconds < 5  # Should be very recent


# ── classify_tool_result ──────────────────────────────────────────

class TestClassifyToolResult:
    def test_known_ephemeral(self):
        assert classify_tool_result("gmail.search_email") == DataClass.EPHEMERAL
        assert classify_tool_result("calendar.list_events") == DataClass.EPHEMERAL

    def test_known_session(self):
        assert classify_tool_result("gmail.send_email") == DataClass.SESSION
        assert classify_tool_result("calendar.create_event") == DataClass.SESSION

    def test_known_persistent(self):
        assert classify_tool_result("contacts.search") == DataClass.PERSISTENT

    def test_unknown_defaults_ephemeral(self):
        assert classify_tool_result("unknown.tool") == DataClass.EPHEMERAL


# ── TTL Sweeper ───────────────────────────────────────────────────

class TestTTLSweeper:
    def test_sync_sweep(self, store):
        store.ingest({"a": 1}, source="test", custom_ttl=0.001)
        time.sleep(0.01)
        deleted = ttl_sweep_once(store)
        assert deleted == 1

    def test_async_sweeper_runs(self, store):
        """Verify the async sweeper can complete at least one pass."""
        store.ingest({"a": 1}, source="test", custom_ttl=0.001)
        time.sleep(0.01)

        async def run():
            task = asyncio.create_task(start_ttl_sweeper(store, interval=0))
            await asyncio.sleep(0.05)  # Let it run one pass
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run())
        stats = store.stats()
        assert stats["total"] == 0


# ── Thread Safety ─────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_ingests(self, store):
        """Multiple threads can ingest simultaneously without corruption."""
        errors = []

        def ingest_batch(batch_id):
            try:
                for i in range(20):
                    store.ingest(
                        {f"batch_{batch_id}_item_{i}": i},
                        source=f"thread_{batch_id}",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=ingest_batch, args=(b,)) for b in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        stats = store.stats()
        assert stats["total"] == 80  # 4 threads × 20 items


# ── Context Manager ───────────────────────────────────────────────

class TestContextManager:
    def test_with_statement(self):
        with IngestStore(db_path=":memory:") as store:
            rid = store.ingest({"x": 1}, source="test")
            assert store.get(rid) is not None
        # After exit, connection is closed
