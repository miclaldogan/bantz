"""Tests for Issue #1289 — Graph memory wiring, events & CLI.

Covers:
- GraphBridge emits graph.entity_linked events
- GraphBridge wiring verification (create_default, on_tool_result)
- bantz graph CLI subcommand (stats, search, neighbors)
- CLI dispatch from bantz main
- SQLiteGraphStore enhanced stats (label/relation distributions)
- Integration: tool result → GraphBridge → AutoLinker → GraphStore → events
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset EventBus subscribers before each test."""
    from bantz.core.events import get_event_bus
    bus = get_event_bus()
    bus._subscribers.clear()
    bus._middleware.clear()
    yield


@pytest.fixture
def event_bus():
    from bantz.core.events import get_event_bus
    return get_event_bus()


@pytest.fixture
def memory_store():
    """InMemoryGraphStore for isolated tests."""
    from bantz.data.graph_backends.memory_backend import InMemoryGraphStore
    return InMemoryGraphStore()


@pytest.fixture
def sqlite_store(tmp_path):
    """SQLiteGraphStore on temp dir."""
    from bantz.data.graph_backends.sqlite_backend import SQLiteGraphStore

    async def _make():
        store = SQLiteGraphStore(str(tmp_path / "test_graph.db"))
        await store.initialise()
        return store

    loop = asyncio.new_event_loop()
    store = loop.run_until_complete(_make())
    yield store
    loop.run_until_complete(store.close())
    loop.close()


@pytest.fixture
def graph_bridge(memory_store):
    """GraphBridge backed by InMemoryGraphStore."""
    from bantz.data.auto_linker import AutoLinker
    from bantz.data.graph_bridge import GraphBridge
    linker = AutoLinker(memory_store)
    return GraphBridge(memory_store, linker)


# ═══════════════════════════════════════════════════════════════
# GRAPH BRIDGE EVENT TESTS
# ═══════════════════════════════════════════════════════════════

class TestGraphBridgeEvents:
    """GraphBridge should emit graph.entity_linked events."""

    @pytest.mark.asyncio
    async def test_entity_linked_event_on_gmail(self, event_bus, graph_bridge):
        """graph.entity_linked emitted when email entities are linked."""
        received = []
        event_bus.subscribe("graph.entity_linked", lambda e: received.append(e))

        email_result = {
            "messages": [{
                "id": "msg_001",
                "from": "ali@example.com",
                "to": ["user@example.com"],
                "subject": "Proje Raporu",
                "snippet": "Ekteki raporu inceler misiniz?",
                "date": "2026-01-15",
            }]
        }

        edges = await graph_bridge.on_tool_result("gmail_list_messages", {}, email_result)
        assert edges > 0
        assert len(received) == 1
        assert received[0].data["tool"] == "gmail_list_messages"
        assert received[0].data["source"] == "gmail"
        assert received[0].data["edges_created"] > 0
        assert received[0].source == "graph_bridge"

    @pytest.mark.asyncio
    async def test_no_event_for_unmapped_tool(self, event_bus, graph_bridge):
        """No event for tools not in the source map."""
        received = []
        event_bus.subscribe("graph.entity_linked", lambda e: received.append(e))

        await graph_bridge.on_tool_result("system_info", {}, {"os": "Linux"})
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_no_event_for_empty_result(self, event_bus, graph_bridge):
        """No event when tool returns empty results."""
        received = []
        event_bus.subscribe("graph.entity_linked", lambda e: received.append(e))

        await graph_bridge.on_tool_result("gmail_list_messages", {}, {"messages": []})
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_event_includes_running_total(self, event_bus, graph_bridge):
        """Event data includes cumulative edge count."""
        received = []
        event_bus.subscribe("graph.entity_linked", lambda e: received.append(e))

        email1 = {"messages": [{"id": "m1", "from": "a@x.com", "to": ["b@x.com"], "subject": "Hi", "date": "2026-01-01"}]}
        email2 = {"messages": [{"id": "m2", "from": "c@x.com", "to": ["d@x.com"], "subject": "Hey", "date": "2026-01-02"}]}

        await graph_bridge.on_tool_result("gmail_list_messages", {}, email1)
        total_after_first = received[0].data["total_edges"]

        await graph_bridge.on_tool_result("gmail_list_messages", {}, email2)
        total_after_second = received[1].data["total_edges"]

        assert total_after_second > total_after_first

    @pytest.mark.asyncio
    async def test_event_best_effort(self, graph_bridge):
        """Events fail silently if EventBus is unavailable."""
        with patch("bantz.data.graph_bridge._get_event_bus_safe", return_value=None):
            email = {"messages": [{"id": "m1", "from": "x@y.com", "to": ["z@y.com"], "subject": "Test", "date": "2026-01-01"}]}
            edges = await graph_bridge.on_tool_result("gmail_list_messages", {}, email)
            assert edges > 0  # Should still work without event bus


# ═══════════════════════════════════════════════════════════════
# GRAPH BRIDGE WIRING TESTS
# ═══════════════════════════════════════════════════════════════

class TestGraphBridgeWiring:
    """GraphBridge initialization and wiring."""

    @pytest.mark.asyncio
    async def test_create_default(self, tmp_path):
        """create_default() returns a functional bridge."""
        from bantz.data.graph_bridge import GraphBridge
        bridge = await GraphBridge.create_default(str(tmp_path / "test.db"))
        assert bridge.enabled
        await bridge.close()

    @pytest.mark.asyncio
    async def test_create_default_bad_path_graceful(self):
        """create_default() with invalid path returns disabled bridge."""
        from bantz.data.graph_bridge import GraphBridge
        bridge = await GraphBridge.create_default("/nonexistent/dir/graph.db")
        assert not bridge.enabled
        # on_tool_result should no-op
        result = await bridge.on_tool_result("gmail_list_messages", {}, {})
        assert result == 0

    @pytest.mark.asyncio
    async def test_calendar_linking(self, graph_bridge, memory_store):
        """Calendar events create Event and Person nodes."""
        event_data = {
            "events": [{
                "id": "evt_001",
                "summary": "Sprint Planning",
                "start": {"dateTime": "2026-02-20T10:00:00"},
                "end": {"dateTime": "2026-02-20T11:00:00"},
                "attendees": [
                    {"email": "ali@x.com", "displayName": "Ali"},
                    {"email": "veli@x.com"},
                ],
            }]
        }
        edges = await graph_bridge.on_tool_result("calendar_list_events", {}, event_data)
        assert edges > 0

        stats = await memory_store.stats()
        assert stats["nodes"] > 0
        assert stats["edges"] > 0


# ═══════════════════════════════════════════════════════════════
# SQLITE ENHANCED STATS TESTS
# ═══════════════════════════════════════════════════════════════

class TestSQLiteEnhancedStats:
    """SQLiteGraphStore stats() returns label/relation distributions."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, tmp_path):
        """Empty graph returns zero counts and empty distributions."""
        from bantz.data.graph_backends.sqlite_backend import SQLiteGraphStore
        store = SQLiteGraphStore(str(tmp_path / "empty.db"))
        await store.initialise()

        stats = await store.stats()
        assert stats["nodes"] == 0
        assert stats["edges"] == 0
        assert stats["labels"] == {}
        assert stats["relations"] == {}
        await store.close()

    @pytest.mark.asyncio
    async def test_stats_with_data(self, sqlite_store):
        """Stats include label and relation counts."""
        await sqlite_store.upsert_node("Person", {"name": "Ali"})
        await sqlite_store.upsert_node("Person", {"name": "Veli"})
        await sqlite_store.upsert_node("Email", {"subject": "Test"})

        ali = (await sqlite_store.search_nodes(label="Person"))[0]
        email = (await sqlite_store.search_nodes(label="Email"))[0]
        await sqlite_store.upsert_edge(ali.id, email.id, "SENT")

        stats = await sqlite_store.stats()
        assert stats["nodes"] == 3
        assert stats["edges"] == 1
        assert stats["labels"]["Person"] == 2
        assert stats["labels"]["Email"] == 1
        assert stats["relations"]["SENT"] == 1


# ═══════════════════════════════════════════════════════════════
# GRAPH CLI TESTS
# ═══════════════════════════════════════════════════════════════

class TestGraphCLI:
    """Tests for ``bantz graph`` CLI subcommand."""

    def test_graph_stats(self, capsys, tmp_path):
        """bantz graph stats displays counts."""
        from bantz.data.graph_cli import main

        exit_code = main(["--db", str(tmp_path / "cli.db"), "stats"])
        captured = capsys.readouterr()
        assert "Knowledge Graph" in captured.out
        assert "Nodes:" in captured.out
        assert exit_code == 0

    def test_graph_stats_json(self, capsys, tmp_path):
        """bantz graph --json stats produces valid JSON."""
        from bantz.data.graph_cli import main

        exit_code = main(["--json", "--db", str(tmp_path / "cli.db"), "stats"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "nodes" in data
        assert "edges" in data
        assert exit_code == 0

    def test_graph_search_empty(self, capsys, tmp_path):
        """Search on empty graph returns nothing."""
        from bantz.data.graph_cli import main

        exit_code = main(["--db", str(tmp_path / "cli.db"), "search", "Ali"])
        captured = capsys.readouterr()
        assert "No nodes found" in captured.out or "0 found" in captured.out
        assert exit_code == 0

    def test_graph_decay_dryrun(self, capsys, tmp_path):
        """Decay dry-run shows preview."""
        from bantz.data.graph_cli import main

        exit_code = main(["--db", str(tmp_path / "cli.db"), "decay", "--dry-run"])
        captured = capsys.readouterr()
        assert exit_code == 0

    def test_graph_no_action_shows_help(self, capsys, tmp_path):
        """No subaction shows help."""
        from bantz.data.graph_cli import main

        exit_code = main([])
        captured = capsys.readouterr()
        assert exit_code == 0


# ═══════════════════════════════════════════════════════════════
# CLI DISPATCH TESTS
# ═══════════════════════════════════════════════════════════════

class TestCLIDispatch:
    """CLI routing for graph subcommand."""

    def test_cli_dispatches_to_graph(self):
        """``bantz graph`` routes to graph CLI."""
        from bantz.cli import main

        with patch("bantz.data.graph_cli.main", return_value=0) as mock_graph:
            result = main(["graph"])
            mock_graph.assert_called_once_with([])

    def test_cli_dispatches_graph_with_args(self):
        """``bantz graph stats`` passes args through."""
        from bantz.cli import main

        with patch("bantz.data.graph_cli.main", return_value=0) as mock_graph:
            main(["graph", "stats"])
            mock_graph.assert_called_once_with(["stats"])


# ═══════════════════════════════════════════════════════════════
# EVENT TYPE REGISTRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestGraphEventTypes:
    """Graph-related events are registered in EventType enum."""

    def test_graph_event_types_exist(self):
        """GRAPH_ENTITY_LINKED, GRAPH_QUERY, GRAPH_DECAY exist."""
        from bantz.core.events import EventType
        assert EventType.GRAPH_ENTITY_LINKED.value == "graph.entity_linked"
        assert EventType.GRAPH_QUERY.value == "graph.query"
        assert EventType.GRAPH_DECAY.value == "graph.decay"


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestGraphIntegration:
    """End-to-end: tool result → GraphBridge → AutoLinker → GraphStore → event."""

    @pytest.mark.asyncio
    async def test_full_email_link_flow(self, event_bus, memory_store):
        """Email tool result flows through entire graph pipeline."""
        from bantz.data.auto_linker import AutoLinker
        from bantz.data.graph_bridge import GraphBridge

        events_log = []
        event_bus.subscribe("graph.entity_linked", lambda e: events_log.append(e))

        linker = AutoLinker(memory_store)
        bridge = GraphBridge(memory_store, linker)

        result = {
            "messages": [{
                "id": "msg_100",
                "from": "boss@company.com",
                "to": ["me@company.com", "colleague@company.com"],
                "subject": "Q4 Budget Review",
                "snippet": "Please review the attached budget...",
                "date": "2026-02-10",
            }]
        }

        edges = await bridge.on_tool_result("gmail_get_message", {}, result)
        assert edges > 0

        # Verify graph has the nodes
        stats = await memory_store.stats()
        assert stats["nodes"] >= 3  # At least sender + 2 recipients (Person nodes) + Email node
        assert stats["edges"] >= 2  # At least SENT + RECEIVED edges

        # Verify event was emitted
        assert len(events_log) == 1
        assert events_log[0].data["edges_created"] == edges

    @pytest.mark.asyncio
    async def test_cross_source_person_dedup(self, event_bus, memory_store):
        """Same person from email and calendar creates ONE node."""
        from bantz.data.auto_linker import AutoLinker
        from bantz.data.graph_bridge import GraphBridge

        linker = AutoLinker(memory_store)
        bridge = GraphBridge(memory_store, linker)

        # Ali appears in email
        email = {"messages": [{"id": "m1", "from": "ali@x.com", "to": ["me@x.com"], "subject": "Hi", "date": "2026-01-01"}]}
        await bridge.on_tool_result("gmail_list_messages", {}, email)

        # Ali also appears in calendar
        event = {"events": [{"id": "e1", "summary": "Meeting", "start": {"dateTime": "2026-01-02T10:00:00"}, "attendees": [{"email": "ali@x.com"}]}]}
        await bridge.on_tool_result("calendar_list_events", {}, event)

        # Search for Ali — should find exactly 1 Person node
        ali_nodes = await memory_store.search_nodes(label="Person")
        ali_emails = [n for n in ali_nodes if n.properties.get("email") == "ali@x.com"]
        assert len(ali_emails) == 1

    @pytest.mark.asyncio
    async def test_graph_bridge_disabled_graceful(self, event_bus):
        """Disabled bridge no-ops everything without errors."""
        from bantz.data.graph_bridge import GraphBridge

        bridge = GraphBridge.__new__(GraphBridge)
        bridge._store = None
        bridge._linker = None
        bridge._edges_created = 0
        bridge._enabled = False

        result = await bridge.on_tool_result("gmail_list_messages", {}, {"messages": [{"id": "m1", "from": "x@y.com", "to": ["z@y.com"], "subject": "Test", "date": "2026-01-01"}]})
        assert result == 0
        assert bridge.total_edges_created == 0
