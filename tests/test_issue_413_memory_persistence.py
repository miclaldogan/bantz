"""Tests for Issue #413: Memory persistence via SQLite.

Tests cover:
  - MemoryStoreConfig: defaults, from_env, env overrides
  - SQLiteMemoryStore: CRUD, session management, pruning, JSONL export/import
  - PersistentDialogSummaryManager: boot reload, add_turn, prompt_block
  - PII filtering on persist
  - Edge cases: empty DB, missing file, concurrent sessions
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from bantz.brain.memory_lite import CompactSummary, PIIFilter, DialogSummaryManager
from bantz.brain.memory_store import (
    MemoryStoreConfig,
    SQLiteMemoryStore,
    PersistentDialogSummaryManager,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite DB path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def store(tmp_db):
    """Create a temporary SQLiteMemoryStore."""
    s = SQLiteMemoryStore(db_path=tmp_db)
    yield s
    s.close()


@pytest.fixture
def sample_summary():
    """Create a sample CompactSummary."""
    return CompactSummary(
        turn_number=1,
        user_intent="asked about calendar",
        action_taken="listed events",
        pending_items=["waiting for confirmation"],
        timestamp=datetime(2025, 1, 15, 10, 30, 0),
    )


def _make_summary(turn: int, intent: str = "test", action: str = "tested") -> CompactSummary:
    return CompactSummary(
        turn_number=turn,
        user_intent=intent,
        action_taken=action,
        timestamp=datetime(2025, 1, 15, 10, 0, 0),
    )


# ======================================================================
# MemoryStoreConfig Tests
# ======================================================================


class TestMemoryStoreConfig:
    def test_defaults(self):
        c = MemoryStoreConfig()
        assert c.db_path == "~/.bantz/memory.db"
        assert c.max_sessions == 5
        assert c.max_turns_per_session == 20
        assert c.pii_filter_enabled is True

    def test_from_env_defaults(self, monkeypatch):
        for k in ["BANTZ_MEMORY_DB_PATH", "BANTZ_MEMORY_MAX_SESSIONS",
                   "BANTZ_MEMORY_MAX_TURNS", "BANTZ_MEMORY_PII_FILTER"]:
            monkeypatch.delenv(k, raising=False)
        c = MemoryStoreConfig.from_env()
        assert c.db_path == "~/.bantz/memory.db"
        assert c.max_sessions == 5

    def test_from_env_custom(self, monkeypatch):
        monkeypatch.setenv("BANTZ_MEMORY_DB_PATH", "/tmp/custom.db")
        monkeypatch.setenv("BANTZ_MEMORY_MAX_SESSIONS", "10")
        monkeypatch.setenv("BANTZ_MEMORY_MAX_TURNS", "50")
        monkeypatch.setenv("BANTZ_MEMORY_PII_FILTER", "0")
        c = MemoryStoreConfig.from_env()
        assert c.db_path == "/tmp/custom.db"
        assert c.max_sessions == 10
        assert c.max_turns_per_session == 50
        assert c.pii_filter_enabled is False

    def test_from_env_min_clamp(self, monkeypatch):
        monkeypatch.setenv("BANTZ_MEMORY_MAX_SESSIONS", "0")
        monkeypatch.setenv("BANTZ_MEMORY_MAX_TURNS", "-5")
        c = MemoryStoreConfig.from_env()
        assert c.max_sessions >= 1
        assert c.max_turns_per_session >= 1


# ======================================================================
# SQLiteMemoryStore Tests
# ======================================================================


class TestSQLiteMemoryStoreBasic:
    def test_create_store(self, tmp_db):
        store = SQLiteMemoryStore(db_path=tmp_db)
        assert Path(tmp_db).exists()
        store.close()

    def test_creates_parent_dirs(self, tmp_path):
        nested = str(tmp_path / "a" / "b" / "c" / "memory.db")
        store = SQLiteMemoryStore(db_path=nested)
        assert Path(nested).exists()
        store.close()

    def test_context_manager(self, tmp_db):
        with SQLiteMemoryStore(db_path=tmp_db) as store:
            sid = store.create_session()
            assert sid

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        store = SQLiteMemoryStore(db_path="~/test_memory.db")
        assert Path(tmp_path / "test_memory.db").exists()
        store.close()


class TestSQLiteMemoryStoreSession:
    def test_create_session(self, store):
        sid = store.create_session()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_multiple_sessions(self, store):
        s1 = store.create_session()
        s2 = store.create_session()
        assert s1 != s2
        assert store.session_count() == 2

    def test_end_session(self, store):
        sid = store.create_session()
        store.end_session(sid)
        # Should not raise


class TestSQLiteMemoryStoreTurns:
    def test_save_and_load_turn(self, store, sample_summary):
        sid = store.create_session()
        store.save_turn(sid, sample_summary)
        turns = store.load_session_turns(sid)
        assert len(turns) == 1
        assert turns[0].turn_number == 1
        assert turns[0].user_intent == "asked about calendar"
        assert turns[0].action_taken == "listed events"
        assert turns[0].pending_items == ["waiting for confirmation"]

    def test_save_multiple_turns(self, store):
        sid = store.create_session()
        for i in range(5):
            store.save_turn(sid, _make_summary(i + 1, f"intent-{i}", f"action-{i}"))
        turns = store.load_session_turns(sid)
        assert len(turns) == 5
        assert turns[0].turn_number == 1
        assert turns[4].turn_number == 5

    def test_turn_count(self, store):
        sid = store.create_session()
        assert store.turn_count(sid) == 0
        store.save_turn(sid, _make_summary(1))
        assert store.turn_count(sid) == 1
        store.save_turn(sid, _make_summary(2))
        assert store.turn_count(sid) == 2
        assert store.turn_count() >= 2  # total across all sessions

    def test_pii_filter_on_save(self, store):
        sid = store.create_session()
        summary = CompactSummary(
            turn_number=1,
            user_intent="emailed user@test.com",
            action_taken="sent to 555-123-4567",
        )
        store.save_turn(sid, summary, pii_filter=True)
        turns = store.load_session_turns(sid)
        assert "<EMAIL>" in turns[0].user_intent
        assert "<PHONE>" in turns[0].action_taken

    def test_pii_filter_disabled(self, store):
        sid = store.create_session()
        summary = CompactSummary(
            turn_number=1,
            user_intent="emailed user@test.com",
            action_taken="called 555-123-4567",
        )
        store.save_turn(sid, summary, pii_filter=False)
        turns = store.load_session_turns(sid)
        assert "user@test.com" in turns[0].user_intent

    def test_pending_items_roundtrip(self, store):
        sid = store.create_session()
        summary = CompactSummary(
            turn_number=1,
            user_intent="test",
            action_taken="test",
            pending_items=["confirmation", "review"],
        )
        store.save_turn(sid, summary, pii_filter=False)
        turns = store.load_session_turns(sid)
        assert turns[0].pending_items == ["confirmation", "review"]


class TestSQLiteMemoryStoreRecent:
    def test_load_recent_sessions(self, store):
        # Create 3 sessions with turns
        for _ in range(3):
            sid = store.create_session()
            store.save_turn(sid, _make_summary(1))
            store.save_turn(sid, _make_summary(2))

        recent = store.load_recent(max_sessions=2)
        assert len(recent) == 2
        for sid, turns in recent:
            assert len(turns) == 2

    def test_load_recent_empty_db(self, store):
        recent = store.load_recent()
        assert recent == []

    def test_load_all_turns_flat(self, store):
        s1 = store.create_session()
        store.save_turn(s1, _make_summary(1, "s1-intent"))
        store.save_turn(s1, _make_summary(2, "s1-intent2"))

        s2 = store.create_session()
        store.save_turn(s2, _make_summary(1, "s2-intent"))

        flat = store.load_all_turns_flat(max_sessions=5)
        assert len(flat) == 3
        # Oldest sessions first
        assert flat[0].user_intent == "s1-intent"
        assert flat[2].user_intent == "s2-intent"

    def test_max_turns_per_session_limit(self, store):
        sid = store.create_session()
        for i in range(10):
            store.save_turn(sid, _make_summary(i + 1))
        recent = store.load_recent(max_turns_per_session=3)
        for _, turns in recent:
            assert len(turns) <= 3


class TestSQLiteMemoryStorePrune:
    def test_prune_old_sessions(self, store):
        for _ in range(10):
            sid = store.create_session()
            store.save_turn(sid, _make_summary(1))

        deleted = store.prune_old_sessions(keep_sessions=3)
        assert deleted == 7
        assert store.session_count() == 3

    def test_prune_no_op_when_under_limit(self, store):
        store.create_session()
        deleted = store.prune_old_sessions(keep_sessions=10)
        assert deleted == 0

    def test_prune_deletes_turns(self, store):
        sids = []
        for _ in range(5):
            sid = store.create_session()
            sids.append(sid)
            store.save_turn(sid, _make_summary(1))
            store.save_turn(sid, _make_summary(2))

        assert store.turn_count() == 10
        store.prune_old_sessions(keep_sessions=2)
        # Should have only 4 turns left (2 sessions × 2 turns)
        assert store.turn_count() == 4


class TestSQLiteMemoryStoreJSONL:
    def test_export_import_roundtrip(self, store, tmp_path):
        sid = store.create_session()
        store.save_turn(sid, _make_summary(1, "hello", "greeted"))
        store.save_turn(sid, _make_summary(2, "calendar", "listed"))

        jsonl_path = str(tmp_path / "export.jsonl")
        exported = store.export_jsonl(jsonl_path)
        assert exported == 2

        # Verify JSONL content
        with open(jsonl_path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 2
        assert lines[0]["user_intent"] == "hello"
        assert lines[1]["user_intent"] == "calendar"

    def test_import_into_fresh_db(self, tmp_path):
        # First: create and export
        db1 = str(tmp_path / "db1.db")
        jsonl_path = str(tmp_path / "backup.jsonl")
        with SQLiteMemoryStore(db_path=db1) as s1:
            sid = s1.create_session()
            s1.save_turn(sid, _make_summary(1, "i1", "a1"), pii_filter=False)
            s1.save_turn(sid, _make_summary(2, "i2", "a2"), pii_filter=False)
            s1.export_jsonl(jsonl_path)

        # Second: import into fresh DB
        db2 = str(tmp_path / "db2.db")
        with SQLiteMemoryStore(db_path=db2) as s2:
            imported = s2.import_jsonl(jsonl_path)
            assert imported == 2
            flat = s2.load_all_turns_flat()
            assert len(flat) == 2

    def test_import_missing_file(self, store, tmp_path):
        with pytest.raises(FileNotFoundError):
            store.import_jsonl(str(tmp_path / "nonexistent.jsonl"))

    def test_export_empty_db(self, store, tmp_path):
        jsonl_path = str(tmp_path / "empty.jsonl")
        exported = store.export_jsonl(jsonl_path)
        assert exported == 0


# ======================================================================
# PersistentDialogSummaryManager Tests
# ======================================================================


class TestPersistentDialogSummaryManager:
    def test_create(self, tmp_path):
        config = MemoryStoreConfig(db_path=str(tmp_path / "mem.db"))
        manager = PersistentDialogSummaryManager.create(config)
        assert manager.session_id
        assert len(manager) == 0
        manager.close()

    def test_add_turn_persists(self, tmp_path):
        db = str(tmp_path / "mem.db")
        config = MemoryStoreConfig(db_path=db)

        # Session 1: add turns
        m1 = PersistentDialogSummaryManager.create(config)
        m1.add_turn(_make_summary(1, "greet", "greeted"))
        m1.add_turn(_make_summary(2, "calendar", "listed"))
        assert len(m1) == 2
        m1.close()

        # Session 2: boot reload should load past turns
        m2 = PersistentDialogSummaryManager.create(config)
        assert len(m2) >= 2
        m2.close()

    def test_prompt_block(self, tmp_path):
        config = MemoryStoreConfig(db_path=str(tmp_path / "mem.db"))
        manager = PersistentDialogSummaryManager.create(config)
        manager.add_turn(_make_summary(1, "asked about weather", "said sunny"))
        block = manager.to_prompt_block()
        assert "DIALOG_SUMMARY" in block
        assert "weather" in block
        manager.close()

    def test_clear_only_in_memory(self, tmp_path):
        db = str(tmp_path / "mem.db")
        config = MemoryStoreConfig(db_path=db)

        m1 = PersistentDialogSummaryManager.create(config)
        m1.add_turn(_make_summary(1, "test", "tested"))
        m1.clear()
        assert len(m1) == 0  # In-memory cleared
        m1.close()

        # But SQLite still has the data
        with SQLiteMemoryStore(db_path=db) as store:
            assert store.turn_count() >= 1

    def test_get_latest(self, tmp_path):
        config = MemoryStoreConfig(db_path=str(tmp_path / "mem.db"))
        manager = PersistentDialogSummaryManager.create(config)
        assert manager.get_latest() is None
        manager.add_turn(_make_summary(1, "first", "did first"))
        manager.add_turn(_make_summary(2, "second", "did second"))
        latest = manager.get_latest()
        assert latest.turn_number == 2
        assert latest.user_intent == "second"
        manager.close()

    def test_context_manager(self, tmp_path):
        config = MemoryStoreConfig(db_path=str(tmp_path / "mem.db"))
        with PersistentDialogSummaryManager.create(config) as m:
            m.add_turn(_make_summary(1))
            assert len(m) == 1

    def test_boot_reload_respects_max_turns(self, tmp_path):
        db = str(tmp_path / "mem.db")
        config = MemoryStoreConfig(db_path=db)

        # Session 1: add many turns
        m1 = PersistentDialogSummaryManager.create(config, max_turns=3)
        for i in range(10):
            m1.add_turn(_make_summary(i + 1, f"intent-{i}", f"action-{i}"))
        m1.close()

        # Session 2: boot reload, but max_turns=3 limits in-memory
        m2 = PersistentDialogSummaryManager.create(config, max_turns=3)
        assert len(m2) <= 3  # In-memory limited by max_turns
        m2.close()

    def test_pii_filter_on_persist(self, tmp_path):
        db = str(tmp_path / "mem.db")
        config = MemoryStoreConfig(db_path=db, pii_filter_enabled=True)
        m = PersistentDialogSummaryManager.create(config)
        m.add_turn(CompactSummary(
            turn_number=1,
            user_intent="sent email to user@test.com",
            action_taken="forwarded to 555-123-4567",
        ))
        m.close()

        # Check SQLite directly
        with SQLiteMemoryStore(db_path=db) as store:
            turns = store.load_all_turns_flat()
            assert "<EMAIL>" in turns[-1].user_intent
            assert "<PHONE>" in turns[-1].action_taken

    def test_str_delegation(self, tmp_path):
        config = MemoryStoreConfig(db_path=str(tmp_path / "mem.db"))
        m = PersistentDialogSummaryManager.create(config)
        m.add_turn(_make_summary(1, "test", "tested"))
        assert "DIALOG_SUMMARY" in str(m)
        m.close()

    def test_store_property(self, tmp_path):
        config = MemoryStoreConfig(db_path=str(tmp_path / "mem.db"))
        m = PersistentDialogSummaryManager.create(config)
        assert isinstance(m.store, SQLiteMemoryStore)
        m.close()


# ======================================================================
# Cross-session persistence test
# ======================================================================


class TestCrossSessionPersistence:
    def test_three_sessions_reload(self, tmp_path):
        """Simulate 3 session restarts and verify context carries over."""
        db = str(tmp_path / "mem.db")
        config = MemoryStoreConfig(db_path=db, max_sessions=5)

        # Session 1
        m1 = PersistentDialogSummaryManager.create(config)
        m1.add_turn(_make_summary(1, "greeting", "greeted back"))
        m1.add_turn(_make_summary(2, "asked about meeting", "listed 3 events"))
        m1.close()

        # Session 2
        m2 = PersistentDialogSummaryManager.create(config)
        block2 = m2.to_prompt_block()
        assert "greeting" in block2 or "meeting" in block2
        m2.add_turn(_make_summary(1, "asked about email", "showed inbox"))
        m2.close()

        # Session 3
        m3 = PersistentDialogSummaryManager.create(config)
        block3 = m3.to_prompt_block()
        # Should have context from sessions 1 and 2
        assert "DIALOG_SUMMARY" in block3
        assert len(m3) > 0
        m3.close()

    def test_session_id_changes_each_boot(self, tmp_path):
        db = str(tmp_path / "mem.db")
        config = MemoryStoreConfig(db_path=db)

        m1 = PersistentDialogSummaryManager.create(config)
        sid1 = m1.session_id
        m1.close()

        m2 = PersistentDialogSummaryManager.create(config)
        sid2 = m2.session_id
        m2.close()

        assert sid1 != sid2
