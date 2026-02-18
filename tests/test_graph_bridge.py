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


# ── Gmail sender deduplication (Issue #1472) ─────────────────────

class TestGmailSenderDedup:
    """GraphBridge._extract_senders deduplicates Person nodes by email."""

    def _make_bridge(self, store):
        linker = AutoLinker(store)
        return GraphBridge(store, linker)

    @pytest.mark.asyncio
    async def test_single_sender_creates_person_node(self, store):
        bridge = self._make_bridge(store)
        result = {
            "message_id": "m1",
            "from": "Ali Veli <ali@example.com>",
            "to": [],
            "subject": "Hello",
        }
        edges = await bridge.on_tool_result("gmail.list_messages", {}, result)
        assert edges >= 1
        nodes = await store.search_nodes("Person", email="ali@example.com")
        assert len(nodes) == 1
        assert nodes[0].properties["email"] == "ali@example.com"
        assert nodes[0].properties["name"] == "Ali Veli"

    @pytest.mark.asyncio
    async def test_duplicate_senders_in_batch_create_one_node(self, store):
        """Two messages from the same sender → only one Person node."""
        bridge = self._make_bridge(store)
        result = {
            "messages": [
                {
                    "message_id": "m1",
                    "from": "ahmet@example.com",
                    "to": [],
                    "subject": "First",
                },
                {
                    "message_id": "m2",
                    "from": "ahmet@example.com",
                    "to": [],
                    "subject": "Second",
                },
            ]
        }
        await bridge.on_tool_result("gmail.list_messages", {}, result)
        nodes = await store.search_nodes("Person", email="ahmet@example.com")
        assert len(nodes) == 1

    @pytest.mark.asyncio
    async def test_distinct_senders_create_separate_person_nodes(self, store):
        bridge = self._make_bridge(store)
        result = {
            "messages": [
                {"message_id": "m1", "from": "ali@x.com", "to": [], "subject": "A"},
                {"message_id": "m2", "from": "veli@x.com", "to": [], "subject": "B"},
            ]
        }
        await bridge.on_tool_result("gmail.list_messages", {}, result)
        ali = await store.search_nodes("Person", email="ali@x.com")
        veli = await store.search_nodes("Person", email="veli@x.com")
        assert len(ali) == 1
        assert len(veli) == 1

    @pytest.mark.asyncio
    async def test_name_email_format_parsed_correctly(self, store):
        bridge = self._make_bridge(store)
        result = {
            "message_id": "m1",
            "from": '"Mehmet Yılmaz" <mehmet@example.com>',
            "to": [],
            "subject": "Hi",
        }
        await bridge.on_tool_result("gmail.list_messages", {}, result)
        nodes = await store.search_nodes("Person", email="mehmet@example.com")
        assert len(nodes) == 1
        assert "Mehmet" in nodes[0].properties["name"]

    def test_extract_senders_deduplication(self):
        """Unit test _extract_senders() directly."""
        items = [
            {"from": "ali@x.com", "subject": "A"},
            {"from": "veli@x.com", "subject": "B"},
            {"from": "ali@x.com", "subject": "C"},   # duplicate
            {"from": "", "subject": "D"},              # no sender — skip
        ]
        result = GraphBridge._extract_senders(items)
        assert len(result) == 2
        emails = [i["from"] for i in result]
        assert "ali@x.com" in emails
        assert "veli@x.com" in emails

    def test_extract_senders_name_angle_bracket_format(self):
        """_extract_senders handles 'Name <email>' dedup correctly."""
        items = [
            {"from": "Ali <ali@x.com>"},
            {"from": "ALI VELİ <ali@x.com>"},   # same email, different display
        ]
        result = GraphBridge._extract_senders(items)
        assert len(result) == 1

    def test_extract_senders_empty_list(self):
        assert GraphBridge._extract_senders([]) == []


# ── GmailSyncer._index_senders integration (Issue #1472) ─────────

class TestGmailSyncerIndexSenders:
    """GmailSyncer._index_senders links senders to the knowledge graph."""

    @pytest.fixture
    def store(self):
        s = InMemoryGraphStore()
        asyncio.get_event_loop().run_until_complete(s.initialise())
        yield s
        asyncio.get_event_loop().run_until_complete(s.close())

    @pytest.fixture
    def bridge(self, store):
        linker = AutoLinker(store)
        return GraphBridge(store, linker)

    @pytest.mark.asyncio
    async def test_index_senders_creates_person_nodes(self, store, bridge):
        from bantz.data.ingest_store import IngestStore
        from bantz.data.sync.gmail_sync import GmailSyncer

        ingest = IngestStore(":memory:")
        syncer = GmailSyncer(ingest, graph_bridge=bridge)

        messages = [
            {
                "id": "m1",
                "from": "Ahmet <ahmet@example.com>",
                "_sender_name": "Ahmet",
                "_sender_email": "ahmet@example.com",
                "subject": "Test",
                "to": [],
                "date": "2026-02-18",
                "snippet": "hello",
            }
        ]
        edges = await syncer._index_senders(messages)
        assert edges >= 1
        nodes = await store.search_nodes("Person", email="ahmet@example.com")
        assert len(nodes) == 1

    @pytest.mark.asyncio
    async def test_index_senders_skips_missing_email(self, store, bridge):
        from bantz.data.ingest_store import IngestStore
        from bantz.data.sync.gmail_sync import GmailSyncer

        ingest = IngestStore(":memory:")
        syncer = GmailSyncer(ingest, graph_bridge=bridge)

        messages = [
            {
                "id": "m1",
                "from": "",
                "_sender_name": "",
                "_sender_email": "",   # empty — should be skipped
                "subject": "No sender",
            }
        ]
        edges = await syncer._index_senders(messages)
        assert edges == 0
        stats = await store.stats()
        assert stats["nodes"] == 0

    @pytest.mark.asyncio
    async def test_index_senders_returns_zero_on_empty_list(self, store, bridge):
        from bantz.data.ingest_store import IngestStore
        from bantz.data.sync.gmail_sync import GmailSyncer

        ingest = IngestStore(":memory:")
        syncer = GmailSyncer(ingest, graph_bridge=bridge)
        edges = await syncer._index_senders([])
        assert edges == 0

    @pytest.mark.asyncio
    async def test_stats_includes_total_graph_edges(self, store, bridge):
        from bantz.data.ingest_store import IngestStore
        from bantz.data.sync.gmail_sync import GmailSyncer

        ingest = IngestStore(":memory:")
        syncer = GmailSyncer(ingest, graph_bridge=bridge)

        # stats key is present from construction (value 0 until a full sync)
        assert "total_graph_edges" in syncer.stats
        assert syncer.stats["total_graph_edges"] == 0

        # _index_senders returns edge count directly but stat is only
        # aggregated by sync(); validate the return value instead
        messages = [
            {
                "id": "m1",
                "from": "test@example.com",
                "_sender_name": "Test",
                "_sender_email": "test@example.com",
                "subject": "S",
                "to": [],
                "date": "",
                "snippet": "",
            }
        ]
        edges = await syncer._index_senders(messages)
        assert edges >= 1

    @pytest.mark.asyncio
    async def test_graph_bridge_disabled_returns_zero(self, store):
        from bantz.data.ingest_store import IngestStore
        from bantz.data.sync.gmail_sync import GmailSyncer

        ingest = IngestStore(":memory:")
        # Inject a disabled bridge (None store → disabled)
        disabled_bridge = await GraphBridge.create_default(db_path="/dev/null/x/y.db")
        syncer = GmailSyncer(ingest, graph_bridge=disabled_bridge)

        messages = [
            {
                "id": "m1",
                "from": "ali@x.com",
                "_sender_name": "Ali",
                "_sender_email": "ali@x.com",
                "subject": "X",
            }
        ]
        edges = await syncer._index_senders(messages)
        # Disabled bridge → 0 edges, no crash
        assert edges == 0
