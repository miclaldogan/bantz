"""
Tests for HybridRetriever — keyword search + graph expansion.
"""

from __future__ import annotations

import asyncio

import pytest

from bantz.data.auto_linker import AutoLinker
from bantz.data.graph_backends.memory_backend import InMemoryGraphStore
from bantz.data.hybrid_retriever import HybridRetriever, RetrievalResult


@pytest.fixture
def store():
    s = InMemoryGraphStore()
    asyncio.get_event_loop().run_until_complete(s.initialise())
    yield s
    asyncio.get_event_loop().run_until_complete(s.close())


@pytest.fixture
def retriever(store):
    return HybridRetriever(store, max_depth=2)


@pytest.fixture
def linker(store):
    return AutoLinker(store)


# ── Basic retrieval ───────────────────────────────────────────────

class TestBasicRetrieval:
    @pytest.mark.asyncio
    async def test_empty_query_returns_nothing(self, retriever):
        results = await retriever.recall("")
        assert results == []

    @pytest.mark.asyncio
    async def test_stopwords_only_returns_nothing(self, retriever):
        results = await retriever.recall("ile ve de")
        assert results == []

    @pytest.mark.asyncio
    async def test_find_person_by_name(self, store, retriever):
        await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"}, unique_key="email")
        results = await retriever.recall("Ali")
        assert len(results) >= 1
        names = [r.node.properties.get("name") for r in results]
        assert "Ali" in names

    @pytest.mark.asyncio
    async def test_find_email_by_subject(self, store, retriever):
        await store.upsert_node("Email", {"message_id": "m1", "subject": "Sprint Review Notes"}, unique_key="message_id")
        results = await retriever.recall("Sprint Review")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_find_event_by_title(self, store, retriever):
        await store.upsert_node("Event", {"event_id": "e1", "title": "Team Standup"}, unique_key="event_id")
        results = await retriever.recall("Standup")
        assert len(results) >= 1


# ── Graph expansion ───────────────────────────────────────────────

class TestGraphExpansion:
    @pytest.mark.asyncio
    async def test_expansion_finds_connected_nodes(self, store, retriever):
        """Search for Ali should also find emails he sent."""
        ali = await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"}, unique_key="email")
        email = await store.upsert_node("Email", {"message_id": "m1", "subject": "Budget Report"}, unique_key="message_id")
        await store.upsert_edge(ali.id, email.id, "SENT")

        results = await retriever.recall("Ali")
        node_ids = {r.node.id for r in results}
        assert ali.id in node_ids
        assert email.id in node_ids

    @pytest.mark.asyncio
    async def test_expansion_score_decays_with_depth(self, store, retriever):
        """Expanded nodes should have lower scores than seed nodes."""
        ali = await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"}, unique_key="email")
        email = await store.upsert_node("Email", {"message_id": "m1", "subject": "Report"}, unique_key="message_id")
        await store.upsert_edge(ali.id, email.id, "SENT")

        results = await retriever.recall("Ali")
        scores = {r.node.id: r.score for r in results}
        # Seed (Ali) should have higher score than expanded (Email)
        assert scores.get(ali.id, 0) >= scores.get(email.id, 0)

    @pytest.mark.asyncio
    async def test_two_hop_expansion(self, store, retriever):
        """Ali → Email → Veli should be reachable in 2 hops."""
        ali = await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"}, unique_key="email")
        email = await store.upsert_node("Email", {"message_id": "m1", "subject": "Hello"}, unique_key="message_id")
        veli = await store.upsert_node("Person", {"name": "Veli", "email": "veli@x.com"}, unique_key="email")
        await store.upsert_edge(ali.id, email.id, "SENT")
        await store.upsert_edge(veli.id, email.id, "RECEIVED")

        results = await retriever.recall("Ali")
        node_ids = {r.node.id for r in results}
        assert veli.id in node_ids


# ── Integration with AutoLinker ───────────────────────────────────

class TestRetrieverWithAutoLinker:
    @pytest.mark.asyncio
    async def test_end_to_end_email_retrieval(self, store, linker, retriever):
        """Link an email, then retrieve via the sender's name."""
        await linker.link("gmail", {
            "message_id": "msg-100",
            "from": "Ali Kaya <ali@example.com>",
            "to": ["veli@example.com"],
            "subject": "Project Update",
            "date": "2026-02-01",
        })

        results = await retriever.recall("ali")
        assert len(results) >= 1
        labels = {r.node.label for r in results}
        # Should find Person and expanded Email
        assert "Person" in labels

    @pytest.mark.asyncio
    async def test_cross_domain_query(self, store, linker, retriever):
        """Link email + event for same person, then query."""
        await linker.link("gmail", {
            "message_id": "m1",
            "from": "ali@x.com",
            "to": [],
            "subject": "Notes",
        })
        await linker.link("calendar", {
            "event_id": "e1",
            "summary": "1:1 with Ali",
            "start": "",
            "end": "",
            "attendees": [{"email": "ali@x.com", "displayName": "Ali"}],
        })

        results = await retriever.recall("ali")
        labels = {r.node.label for r in results}
        assert "Person" in labels
        # Should find both Email and Event through expansion
        assert len(results) >= 2


# ── RetrievalResult ───────────────────────────────────────────────

class TestRetrievalResult:
    def test_to_dict(self):
        from bantz.data.graph_store import GraphNode
        node = GraphNode(id="x", label="Person", properties={"name": "Ali"})
        r = RetrievalResult(node=node, score=0.85, path=["keyword:name=Ali"])
        d = r.to_dict()
        assert d["node_id"] == "x"
        assert d["score"] == 0.85
        assert d["label"] == "Person"

    def test_repr(self):
        from bantz.data.graph_store import GraphNode
        node = GraphNode(id="abcdefgh-1234", label="Email", properties={})
        r = RetrievalResult(node=node, score=0.5)
        assert "Email" in repr(r)
