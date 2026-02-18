"""
Tests for GraphBridge — tool-result → graph pipeline.
"""

from __future__ import annotations

import asyncio

import pytest

from bantz.data.auto_linker import AutoLinker
from bantz.data.graph_backends.memory_backend import InMemoryGraphStore
from bantz.data.graph_bridge import GraphBridge


@pytest.fixture
def store():
    s = InMemoryGraphStore()
    asyncio.get_event_loop().run_until_complete(s.initialise())
    yield s
    asyncio.get_event_loop().run_until_complete(s.close())


@pytest.fixture
def bridge(store):
    linker = AutoLinker(store)
    return GraphBridge(store, linker)


# ── Tool routing ──────────────────────────────────────────────────

class TestToolRouting:
    @pytest.mark.asyncio
    async def test_gmail_tool_creates_nodes(self, store, bridge):
        result = {
            "messages": [
                {
                    "message_id": "m1",
                    "from": "ali@x.com",
                    "to": ["veli@x.com"],
                    "subject": "Test",
                }
            ]
        }
        await bridge.on_tool_result("gmail_search", {}, result)

        stats = await store.stats()
        assert stats["nodes"] >= 1

    @pytest.mark.asyncio
    async def test_calendar_tool_creates_events(self, store, bridge):
        result = {
            "events": [
                {
                    "event_id": "ev1",
                    "summary": "Standup",
                    "start": "2026-02-01T09:00",
                    "end": "2026-02-01T09:30",
                    "attendees": [{"email": "ali@x.com"}],
                }
            ]
        }
        await bridge.on_tool_result("calendar_list_events", {}, result)

        stats = await store.stats()
        assert stats["nodes"] >= 1

    @pytest.mark.asyncio
    async def test_contacts_tool_creates_people(self, store, bridge):
        result = {
            "items": [
                {
                    "email": "ali@x.com",
                    "name": "Ali",
                }
            ]
        }
        await bridge.on_tool_result("contacts_search", {}, result)

        stats = await store.stats()
        assert stats["nodes"] >= 1

    @pytest.mark.asyncio
    async def test_tasks_tool_creates_tasks(self, store, bridge):
        result = {
            "items": [
                {
                    "task_id": "t1",
                    "title": "Fix bug",
                    "assignee": "ali@x.com",
                }
            ]
        }
        await bridge.on_tool_result("tasks_list", {}, result)

        stats = await store.stats()
        assert stats["nodes"] >= 1


# ── Item extraction ───────────────────────────────────────────────

class TestItemExtraction:
    @pytest.mark.asyncio
    async def test_list_input(self, store, bridge):
        """Raw list of dicts should be extracted as items."""
        result = [
            {"message_id": "m1", "from": "ali@x.com", "to": [], "subject": "Hey"},
        ]
        await bridge.on_tool_result("gmail_search", {}, result)

        stats = await store.stats()
        assert stats["nodes"] >= 1

    @pytest.mark.asyncio
    async def test_single_dict_without_wrapper(self, store, bridge):
        """A single dict should be wrapped as one item."""
        result = {
            "message_id": "m2",
            "from": "veli@x.com",
            "to": [],
            "subject": "Solo",
        }
        await bridge.on_tool_result("gmail_search", {}, result)

        stats = await store.stats()
        assert stats["nodes"] >= 1

    @pytest.mark.asyncio
    async def test_empty_result(self, store, bridge):
        """Empty result should not fail."""
        # None result produces no items at all
        await bridge.on_tool_result("gmail_search", {}, None)
        stats = await store.stats()
        assert stats["nodes"] == 0


# ── Unknown tools ─────────────────────────────────────────────────

class TestUnknownTools:
    @pytest.mark.asyncio
    async def test_unmapped_tool_is_silently_skipped(self, store, bridge):
        await bridge.on_tool_result("weather_get", {}, {"temp": 22})
        stats = await store.stats()
        assert stats["nodes"] == 0


# ── Graceful degradation ─────────────────────────────────────────

class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_create_default_returns_bridge(self):
        bridge = await GraphBridge.create_default(db_path=":memory:")
        assert bridge is not None
        result = {"messages": [{"message_id": "m1", "from": "a@x.com", "to": [], "subject": "hi"}]}
        await bridge.on_tool_result("gmail_search", {}, result)

    @pytest.mark.asyncio
    async def test_create_default_with_bad_path_does_not_crash(self):
        """Even with an invalid path, create_default should either work or return None."""
        # /dev/null/nope is not writable — constructor should handle gracefully
        bridge = await GraphBridge.create_default(db_path="/dev/null/nope/bad.db")
        # It's acceptable to return None or raise — the key is no unhandled crash
        # given the current implementation, it should return None or raise
        # We just assert it doesn't cause an unhandled exception
        assert bridge is None or isinstance(bridge, GraphBridge)
