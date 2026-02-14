"""
Tests for bantz.data.ingest_bridge — IngestBridge orchestrator integration.

Issue #1288: Ingest Store bridge for tool result caching.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from bantz.data.ingest_store import IngestStore, DataClass, IngestRecord
from bantz.data.ingest_bridge import IngestBridge, _stable_params


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def store():
    return IngestStore(db_path=":memory:", auto_sweep=False)


@pytest.fixture
def bridge(store):
    return IngestBridge(store)


# ── IngestBridge: Basic ───────────────────────────────────────────

class TestIngestBridgeBasic:
    def test_on_tool_result_returns_id(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="gmail.search_email",
            params={"query": "from:ali"},
            result={"messages": [{"id": "1", "subject": "hello"}]},
        )
        assert isinstance(rid, str)
        assert len(rid) == 32  # uuid hex

    def test_on_tool_result_skips_failures(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="calendar.list_events",
            params={},
            result={"ok": False, "error": "auth failed"},
            success=False,
        )
        assert rid is None

    def test_on_tool_result_skips_none(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="test.tool",
            params={},
            result=None,
        )
        assert rid is None

    def test_on_tool_result_skips_empty_dict(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="test.tool",
            params={},
            result={},
        )
        assert rid is None

    def test_on_tool_result_skips_empty_list(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="test.tool",
            params={},
            result=[],
        )
        assert rid is None

    def test_summary_stored(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="gmail.search_email",
            params={"query": "test"},
            result={"messages": [{"id": "1"}]},
            summary="Found 1 email",
        )
        record = bridge.store.get(rid)
        assert record.summary == "Found 1 email"

    def test_meta_includes_tool_info(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="calendar.list_events",
            params={"date": "today"},
            result={"events": [{"title": "Meeting"}]},
            elapsed_ms=250,
        )
        record = bridge.store.get(rid)
        assert record.meta["tool_name"] == "calendar.list_events"
        assert record.meta["elapsed_ms"] == 250
        assert record.meta["params"] == {"date": "today"}


# ── IngestBridge: Classification ──────────────────────────────────

class TestIngestBridgeClassification:
    def test_read_tool_classified_ephemeral(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="gmail.search_email",
            params={"query": "test"},
            result={"messages": ["m1"]},
        )
        record = bridge.store.get(rid)
        assert record.data_class == DataClass.EPHEMERAL

    def test_write_tool_classified_session(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="gmail.send_email",
            params={"to": "ali@x.com", "body": "hi"},
            result={"ok": True, "message_id": "abc123"},
        )
        record = bridge.store.get(rid)
        assert record.data_class == DataClass.SESSION

    def test_contacts_classified_persistent(self, bridge):
        rid = bridge.on_tool_result(
            tool_name="contacts.search",
            params={"query": "Ali"},
            result={"contacts": [{"name": "Ali", "email": "ali@x.com"}]},
        )
        record = bridge.store.get(rid)
        assert record.data_class == DataClass.PERSISTENT


# ── IngestBridge: Cache Lookup ────────────────────────────────────

class TestIngestBridgeCache:
    def test_cache_hit(self, bridge):
        """After ingesting, same tool+params should produce a cache hit."""
        bridge.on_tool_result(
            tool_name="gmail.search_email",
            params={"query": "from:ali"},
            result={"messages": [{"id": "1"}]},
        )
        cached = bridge.get_cached("gmail.search_email", {"query": "from:ali"})
        assert cached is not None
        assert cached.content["result"]["messages"][0]["id"] == "1"

    def test_cache_miss(self, bridge):
        """Different params should not cache-hit."""
        bridge.on_tool_result(
            tool_name="gmail.search_email",
            params={"query": "from:ali"},
            result={"messages": [{"id": "1"}]},
        )
        cached = bridge.get_cached("gmail.search_email", {"query": "from:veli"})
        assert cached is None

    def test_cache_max_age(self, bridge):
        """Cached result older than max_age should be a miss."""
        bridge.on_tool_result(
            tool_name="gmail.search_email",
            params={"query": "from:ali"},
            result={"messages": []},
        )
        # max_age=0 means "only accept records created at this exact instant"
        time.sleep(0.01)
        cached = bridge.get_cached(
            "gmail.search_email",
            {"query": "from:ali"},
            max_age=0.001,
        )
        assert cached is None


# ── IngestBridge: Turn Stats ──────────────────────────────────────

class TestIngestBridgeTurnStats:
    def test_initial_stats_zero(self, bridge):
        stats = bridge.reset_turn_stats()
        assert stats["ingested"] == 0
        assert stats["cache_hits"] == 0

    def test_stats_track_ingests(self, bridge):
        bridge.on_tool_result("t1", {}, {"data": 1})
        bridge.on_tool_result("t2", {}, {"data": 2})
        stats = bridge.reset_turn_stats()
        assert stats["ingested"] == 2

    def test_stats_track_cache_hits(self, bridge):
        bridge.on_tool_result(
            "gmail.search_email",
            {"query": "test"},
            {"messages": [1]},
        )
        bridge.get_cached("gmail.search_email", {"query": "test"})
        stats = bridge.reset_turn_stats()
        assert stats["cache_hits"] == 1

    def test_stats_reset(self, bridge):
        bridge.on_tool_result("t1", {}, {"data": 1})
        bridge.reset_turn_stats()
        stats = bridge.reset_turn_stats()
        assert stats["ingested"] == 0

    def test_failed_ingest_not_counted(self, bridge):
        bridge.on_tool_result("t1", {}, None)  # None result → skipped
        stats = bridge.reset_turn_stats()
        assert stats["ingested"] == 0


# ── IngestBridge: create_default ──────────────────────────────────

class TestIngestBridgeCreateDefault:
    def test_creates_instance(self, tmp_path):
        db = tmp_path / "test_ingest.db"
        b = IngestBridge.create_default(db_path=str(db))
        assert b is not None
        rid = b.on_tool_result("test", {}, {"ok": True})
        assert rid is not None
        b.close()

    def test_fallback_on_error(self):
        """If DB path is invalid, falls back to in-memory."""
        b = IngestBridge.create_default(db_path="/nonexistent/path/db.sqlite")
        # Should work with in-memory fallback
        rid = b.on_tool_result("test", {}, {"ok": True})
        assert rid is not None
        b.close()


# ── _stable_params ────────────────────────────────────────────────

class TestStableParams:
    def test_removes_unstable_keys(self):
        params = {"query": "test", "page_token": "abc", "_request_id": "xyz"}
        stable = _stable_params(params)
        assert "query" in stable
        assert "page_token" not in stable
        assert "_request_id" not in stable

    def test_preserves_normal_keys(self):
        params = {"query": "from:ali", "max_results": 10}
        stable = _stable_params(params)
        assert stable == {"max_results": 10, "query": "from:ali"}

    def test_sorted_keys(self):
        params = {"z_key": 1, "a_key": 2}
        stable = _stable_params(params)
        keys = list(stable.keys())
        assert keys == ["a_key", "z_key"]

    def test_non_dict_passthrough(self):
        assert _stable_params("string") == "string"
        assert _stable_params(42) == 42
