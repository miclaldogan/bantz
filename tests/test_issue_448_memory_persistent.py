"""Tests for Issue #448 — Memory v0: SQLite persistent storage.

Covers:
- MemoryItem CRUD (write, read, search, delete, list, update_access)
- Session lifecycle (create, get, close, increment_turn, list)
- ToolTrace CRUD (write, get with filters)
- UserProfile CRUD (set, get, delete, list_keys, upsert)
- Migration system (fresh DB, idempotent re-run)
- Thread safety (concurrent writes)
- Stats / introspection
- Edge cases (empty search, missing IDs, type filters)
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest

from bantz.memory.models import (
    MemoryItem,
    MemoryItemType,
    Session,
    ToolTrace,
    UserProfile,
)
from bantz.memory.migrations import LATEST_VERSION, migrate, _current_version
from bantz.memory.persistent import PersistentMemoryStore


@pytest.fixture()
def store():
    """In-memory store for each test."""
    s = PersistentMemoryStore(":memory:")
    yield s
    s.close()


# ===================================================================
# 1. MemoryItem CRUD
# ===================================================================

class TestMemoryItemCRUD:
    def test_write_and_read_roundtrip(self, store):
        item = MemoryItem(content="Merhaba dünya", importance=0.8)
        item_id = store.write(item)
        got = store.read(item_id)
        assert got is not None
        assert got.content == "Merhaba dünya"
        assert got.importance == 0.8
        assert got.type == MemoryItemType.EPISODIC

    def test_read_nonexistent_returns_none(self, store):
        assert store.read("nonexistent-id") is None

    def test_write_with_all_fields(self, store):
        sess = store.create_session()
        item = MemoryItem(
            content="test content",
            session_id=sess.id,
            type=MemoryItemType.FACT,
            embedding_vector=[0.1, 0.2, 0.3],
            importance=0.9,
            tags=["tag1", "tag2"],
            metadata={"source": "calendar"},
        )
        item_id = store.write(item)
        got = store.read(item_id)
        assert got.session_id == sess.id
        assert got.type == MemoryItemType.FACT
        assert got.embedding_vector == [0.1, 0.2, 0.3]
        assert got.tags == ["tag1", "tag2"]
        assert got.metadata == {"source": "calendar"}

    def test_delete_existing(self, store):
        item = MemoryItem(content="to delete")
        item_id = store.write(item)
        assert store.delete(item_id) is True
        assert store.read(item_id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete("nope") is False

    def test_update_access(self, store):
        item = MemoryItem(content="access me")
        item_id = store.write(item)
        assert store.update_access(item_id) is True
        got = store.read(item_id)
        assert got.access_count == 1

    def test_update_access_twice(self, store):
        item = MemoryItem(content="access me twice")
        item_id = store.write(item)
        store.update_access(item_id)
        store.update_access(item_id)
        got = store.read(item_id)
        assert got.access_count == 2

    def test_write_replaces_on_same_id(self, store):
        item = MemoryItem(id="fixed-id", content="original")
        store.write(item)
        item2 = MemoryItem(id="fixed-id", content="updated")
        store.write(item2)
        got = store.read("fixed-id")
        assert got.content == "updated"

    def test_list_items_all(self, store):
        for i in range(5):
            store.write(MemoryItem(content=f"item {i}"))
        items = store.list_items(limit=10)
        assert len(items) == 5

    def test_list_items_type_filter(self, store):
        store.write(MemoryItem(content="ep", type=MemoryItemType.EPISODIC))
        store.write(MemoryItem(content="fact", type=MemoryItemType.FACT))
        items = store.list_items(type_filter="fact")
        assert len(items) == 1
        assert items[0].content == "fact"

    def test_list_items_session_filter(self, store):
        s1 = store.create_session()
        s2 = store.create_session()
        store.write(MemoryItem(content="a", session_id=s1.id))
        store.write(MemoryItem(content="b", session_id=s2.id))
        items = store.list_items(session_id=s1.id)
        assert len(items) == 1


# ===================================================================
# 2. Search
# ===================================================================

class TestSearch:
    def test_keyword_search(self, store):
        store.write(MemoryItem(content="yarın toplantı var saat 3'te"))
        store.write(MemoryItem(content="hava durumu güzel"))
        results = store.search("toplantı")
        assert len(results) == 1
        assert "toplantı" in results[0].content

    def test_multiple_keywords(self, store):
        store.write(MemoryItem(content="yarın toplantı saat 3"))
        store.write(MemoryItem(content="toplantı iptal"))
        results = store.search("toplantı saat")
        assert len(results) == 1
        assert "saat" in results[0].content

    def test_search_with_type_filter(self, store):
        store.write(MemoryItem(content="takvim etkinliği", type=MemoryItemType.EPISODIC))
        store.write(MemoryItem(content="takvim bilgisi", type=MemoryItemType.FACT))
        results = store.search("takvim", type_filter="fact")
        assert len(results) == 1
        assert results[0].type == MemoryItemType.FACT

    def test_search_empty_query(self, store):
        store.write(MemoryItem(content="something"))
        assert store.search("") == []
        assert store.search("   ") == []

    def test_search_no_match(self, store):
        store.write(MemoryItem(content="hello world"))
        assert store.search("xyznomatch") == []

    def test_search_limit(self, store):
        for i in range(10):
            store.write(MemoryItem(content=f"test item {i}"))
        results = store.search("test", limit=3)
        assert len(results) == 3

    def test_search_ordered_by_importance(self, store):
        store.write(MemoryItem(content="low test", importance=0.1))
        store.write(MemoryItem(content="high test", importance=0.9))
        results = store.search("test", limit=10)
        assert results[0].importance >= results[1].importance


# ===================================================================
# 3. Session lifecycle
# ===================================================================

class TestSession:
    def test_create_session(self, store):
        sess = store.create_session()
        assert sess.id
        assert sess.is_active is True
        assert sess.turn_count == 0

    def test_get_session(self, store):
        sess = store.create_session(metadata={"lang": "tr"})
        got = store.get_session(sess.id)
        assert got is not None
        assert got.metadata == {"lang": "tr"}

    def test_get_nonexistent_session(self, store):
        assert store.get_session("nope") is None

    def test_close_session(self, store):
        sess = store.create_session()
        assert store.close_session(sess.id, summary="güzel sohbet") is True
        got = store.get_session(sess.id)
        assert got.end_time is not None
        assert got.summary == "güzel sohbet"

    def test_increment_turn_count(self, store):
        sess = store.create_session()
        store.increment_turn_count(sess.id)
        store.increment_turn_count(sess.id)
        got = store.get_session(sess.id)
        assert got.turn_count == 2

    def test_list_sessions(self, store):
        for _ in range(3):
            store.create_session()
        sessions = store.list_sessions(limit=10)
        assert len(sessions) == 3

    def test_session_with_memory_items(self, store):
        sess = store.create_session()
        store.write(MemoryItem(content="turn 1", session_id=sess.id))
        store.write(MemoryItem(content="turn 2", session_id=sess.id))
        items = store.list_items(session_id=sess.id)
        assert len(items) == 2


# ===================================================================
# 4. ToolTrace
# ===================================================================

class TestToolTrace:
    def test_write_and_get(self, store):
        trace = ToolTrace(
            tool_name="calendar.create_event",
            args_hash="abc123",
            result_summary="Event created",
            success=True,
            latency_ms=150.5,
        )
        trace_id = store.write_tool_trace(trace)
        traces = store.get_tool_traces()
        assert len(traces) == 1
        assert traces[0].tool_name == "calendar.create_event"
        assert traces[0].latency_ms == 150.5

    def test_filter_by_session(self, store):
        s1 = store.create_session()
        s2 = store.create_session()
        store.write_tool_trace(ToolTrace(tool_name="t1", session_id=s1.id))
        store.write_tool_trace(ToolTrace(tool_name="t2", session_id=s2.id))
        traces = store.get_tool_traces(session_id=s1.id)
        assert len(traces) == 1
        assert traces[0].tool_name == "t1"

    def test_filter_by_tool_name(self, store):
        store.write_tool_trace(ToolTrace(tool_name="calendar.list"))
        store.write_tool_trace(ToolTrace(tool_name="gmail.send"))
        traces = store.get_tool_traces(tool_name="gmail.send")
        assert len(traces) == 1

    def test_failed_trace(self, store):
        store.write_tool_trace(ToolTrace(tool_name="x", success=False))
        traces = store.get_tool_traces()
        assert traces[0].success is False


# ===================================================================
# 5. UserProfile
# ===================================================================

class TestUserProfile:
    def test_set_and_get(self, store):
        store.set_profile("language", "tr")
        assert store.get_profile("language") == "tr"

    def test_upsert(self, store):
        store.set_profile("theme", "dark")
        store.set_profile("theme", "light")
        assert store.get_profile("theme") == "light"

    def test_get_nonexistent(self, store):
        assert store.get_profile("nope") is None

    def test_delete_profile(self, store):
        store.set_profile("key", "val")
        assert store.delete_profile("key") is True
        assert store.get_profile("key") is None

    def test_delete_nonexistent(self, store):
        assert store.delete_profile("nope") is False

    def test_list_keys(self, store):
        store.set_profile("a", "1")
        store.set_profile("b", "2")
        keys = store.list_profile_keys()
        assert sorted(keys) == ["a", "b"]


# ===================================================================
# 6. Migration
# ===================================================================

class TestMigration:
    def test_fresh_db_migration(self, store):
        # Store fixture already migrated — just check version
        with store._lock:
            ver = _current_version(store._conn)
        assert ver == LATEST_VERSION

    def test_idempotent_migration(self, store):
        # Running migrate again should be a no-op
        with store._lock:
            ver = migrate(store._conn)
        assert ver == LATEST_VERSION


# ===================================================================
# 7. Thread safety
# ===================================================================

class TestThreadSafety:
    def test_concurrent_writes(self, store):
        errors = []

        def writer(idx):
            try:
                for i in range(20):
                    store.write(MemoryItem(content=f"thread-{idx}-item-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        items = store.list_items(limit=200)
        assert len(items) == 80  # 4 threads × 20 items

    def test_concurrent_sessions(self, store):
        errors = []
        session_ids = []

        def session_worker(idx):
            try:
                sess = store.create_session()
                session_ids.append(sess.id)
                for _ in range(5):
                    store.increment_turn_count(sess.id)
                store.close_session(sess.id, summary=f"session {idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=session_worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        sessions = store.list_sessions(limit=10)
        assert len(sessions) == 4
        for sess in sessions:
            assert sess.turn_count == 5


# ===================================================================
# 8. Stats
# ===================================================================

class TestStats:
    def test_empty_stats(self, store):
        s = store.stats()
        assert s["memory_items"] == 0
        assert s["sessions"] == 0
        assert s["tool_traces"] == 0
        assert s["user_profiles"] == 0

    def test_stats_after_writes(self, store):
        store.write(MemoryItem(content="a"))
        store.write(MemoryItem(content="b"))
        store.create_session()
        store.write_tool_trace(ToolTrace(tool_name="x"))
        store.set_profile("k", "v")
        s = store.stats()
        assert s["memory_items"] == 2
        assert s["sessions"] == 1
        assert s["tool_traces"] == 1
        assert s["user_profiles"] == 1


# ===================================================================
# 9. Models
# ===================================================================

class TestModels:
    def test_memory_item_defaults(self):
        item = MemoryItem()
        assert item.id
        assert item.type == MemoryItemType.EPISODIC
        assert 0.0 <= item.importance <= 1.0

    def test_memory_item_clamps_importance(self):
        item = MemoryItem(importance=2.0)
        assert item.importance == 1.0
        item2 = MemoryItem(importance=-0.5)
        assert item2.importance == 0.0

    def test_memory_item_touch(self):
        item = MemoryItem()
        assert item.access_count == 0
        item.touch()
        assert item.access_count == 1

    def test_session_is_active(self):
        sess = Session()
        assert sess.is_active is True
        sess.end_time = datetime.utcnow()
        assert sess.is_active is False

    def test_memory_item_type_from_string(self):
        item = MemoryItem(type="fact")
        assert item.type == MemoryItemType.FACT
