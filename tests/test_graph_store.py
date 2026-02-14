"""
Tests for GraphStore interface, InMemoryGraphStore, and SQLiteGraphStore.

Covers:
- Node CRUD (upsert, get, search, delete)
- Edge CRUD (upsert, get_neighbors, get_edges, delete)
- Edge weight update, decay, reinforcement
- Node deletion cascades edges
- Upsert deduplication
- Multi-hop traversal
- Stats
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time

import pytest

from bantz.data.graph_store import (
    GraphEdge,
    GraphNode,
    GraphStore,
    NODE_LABELS,
    EDGE_RELATIONS,
)
from bantz.data.graph_backends.memory_backend import InMemoryGraphStore
from bantz.data.graph_backends.sqlite_backend import SQLiteGraphStore


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def memory_store():
    store = InMemoryGraphStore()
    asyncio.get_event_loop().run_until_complete(store.initialise())
    yield store
    asyncio.get_event_loop().run_until_complete(store.close())


@pytest.fixture
def sqlite_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SQLiteGraphStore(path)
    asyncio.get_event_loop().run_until_complete(store.initialise())
    yield store
    asyncio.get_event_loop().run_until_complete(store.close())
    os.unlink(path)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, memory_store, sqlite_store):
    """Parametrised fixture — tests run against both backends."""
    if request.param == "memory":
        return memory_store
    return sqlite_store


# ── Canonical labels ──────────────────────────────────────────────

class TestCanonicalLabels:
    def test_node_labels_has_8_types(self):
        assert len(NODE_LABELS) == 8
        for label in ("Person", "Org", "Event", "Email", "Task", "Topic", "Project", "Document"):
            assert label in NODE_LABELS

    def test_edge_relations_has_15_types(self):
        assert len(EDGE_RELATIONS) == 15
        for rel in ("SENT", "RECEIVED", "ATTENDS", "OWNS", "MEMBER_OF"):
            assert rel in EDGE_RELATIONS


# ── Node CRUD ─────────────────────────────────────────────────────

class TestNodeCRUD:
    @pytest.mark.asyncio
    async def test_upsert_creates_node(self, store: GraphStore):
        node = await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"})
        assert node.id
        assert node.label == "Person"
        assert node.properties["name"] == "Ali"

    @pytest.mark.asyncio
    async def test_upsert_deduplicates_by_unique_key(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"email": "ali@x.com", "name": "Ali"}, unique_key="email")
        n2 = await store.upsert_node("Person", {"email": "ali@x.com", "name": "Ali K."}, unique_key="email")
        assert n1.id == n2.id
        assert n2.properties["name"] == "Ali K."

    @pytest.mark.asyncio
    async def test_get_node_returns_none_for_missing(self, store: GraphStore):
        result = await store.get_node("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_node_returns_correct(self, store: GraphStore):
        node = await store.upsert_node("Org", {"name": "Acme"})
        fetched = await store.get_node(node.id)
        assert fetched is not None
        assert fetched.label == "Org"
        assert fetched.properties["name"] == "Acme"

    @pytest.mark.asyncio
    async def test_search_by_label(self, store: GraphStore):
        await store.upsert_node("Person", {"name": "A"})
        await store.upsert_node("Person", {"name": "B"})
        await store.upsert_node("Org", {"name": "C"})
        persons = await store.search_nodes("Person")
        assert len(persons) == 2

    @pytest.mark.asyncio
    async def test_search_with_filter(self, store: GraphStore):
        await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"}, unique_key="email")
        await store.upsert_node("Person", {"name": "Veli", "email": "veli@x.com"}, unique_key="email")
        results = await store.search_nodes("Person", name="Ali")
        assert len(results) == 1
        assert results[0].properties["name"] == "Ali"

    @pytest.mark.asyncio
    async def test_delete_node(self, store: GraphStore):
        node = await store.upsert_node("Person", {"name": "X"})
        deleted = await store.delete_node(node.id)
        assert deleted is True
        assert await store.get_node(node.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, store: GraphStore):
        assert await store.delete_node("nope") is False

    @pytest.mark.asyncio
    async def test_delete_node_cascades_edges(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "Hi"})
        await store.upsert_edge(n1.id, n2.id, "SENT")
        await store.delete_node(n1.id)
        edges = await store.get_edges(n2.id)
        assert len(edges) == 0


# ── Edge CRUD ─────────────────────────────────────────────────────

class TestEdgeCRUD:
    @pytest.mark.asyncio
    async def test_upsert_edge_creates(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "Hello"})
        edge = await store.upsert_edge(n1.id, n2.id, "SENT", {"source": "gmail"})
        assert edge.id
        assert edge.source_id == n1.id
        assert edge.target_id == n2.id
        assert edge.relation == "SENT"
        assert edge.weight == 1.0

    @pytest.mark.asyncio
    async def test_upsert_edge_deduplicates_triple(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "Hi"})
        e1 = await store.upsert_edge(n1.id, n2.id, "SENT", {"v": 1})
        e2 = await store.upsert_edge(n1.id, n2.id, "SENT", {"v": 2}, weight=0.8)
        assert e1.id == e2.id
        assert e2.weight == 0.8

    @pytest.mark.asyncio
    async def test_get_edges_outgoing(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        n3 = await store.upsert_node("Email", {"subject": "Y"})
        await store.upsert_edge(n1.id, n2.id, "SENT")
        await store.upsert_edge(n1.id, n3.id, "SENT")
        edges = await store.get_edges(n1.id, direction="out")
        assert len(edges) == 2

    @pytest.mark.asyncio
    async def test_get_edges_with_relation_filter(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        n3 = await store.upsert_node("Event", {"title": "Meeting"})
        await store.upsert_edge(n1.id, n2.id, "SENT")
        await store.upsert_edge(n1.id, n3.id, "ATTENDS")
        sent = await store.get_edges(n1.id, relation="SENT", direction="out")
        assert len(sent) == 1
        assert sent[0].relation == "SENT"

    @pytest.mark.asyncio
    async def test_delete_edge(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        edge = await store.upsert_edge(n1.id, n2.id, "SENT")
        assert await store.delete_edge(edge.id) is True
        assert await store.delete_edge(edge.id) is False

    @pytest.mark.asyncio
    async def test_update_edge_weight(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        edge = await store.upsert_edge(n1.id, n2.id, "SENT")
        assert await store.update_edge_weight(edge.id, 0.5) is True
        edges = await store.get_edges(n1.id, direction="out")
        assert edges[0].weight == 0.5


# ── Traversal ─────────────────────────────────────────────────────

class TestTraversal:
    @pytest.mark.asyncio
    async def test_get_neighbors_single_hop(self, store: GraphStore):
        a = await store.upsert_node("Person", {"name": "Ali"})
        b = await store.upsert_node("Email", {"subject": "Hi"})
        c = await store.upsert_node("Email", {"subject": "Bye"})
        await store.upsert_edge(a.id, b.id, "SENT")
        await store.upsert_edge(a.id, c.id, "SENT")
        nbs = await store.get_neighbors(a.id, direction="out")
        assert len(nbs) == 2

    @pytest.mark.asyncio
    async def test_get_neighbors_multi_hop(self, store: GraphStore):
        a = await store.upsert_node("Person", {"name": "Ali"})
        b = await store.upsert_node("Email", {"subject": "Hi"})
        c = await store.upsert_node("Person", {"name": "Veli"})
        await store.upsert_edge(a.id, b.id, "SENT")
        await store.upsert_edge(c.id, b.id, "RECEIVED")
        # From Ali, 2 hops should reach Veli (Ali→Email→Veli)
        nbs = await store.get_neighbors(a.id, max_depth=2, direction="both")
        ids = {n.id for n in nbs}
        assert b.id in ids
        assert c.id in ids

    @pytest.mark.asyncio
    async def test_get_neighbors_respects_min_weight(self, store: GraphStore):
        a = await store.upsert_node("Person", {"name": "A"})
        b = await store.upsert_node("Person", {"name": "B"})
        c = await store.upsert_node("Person", {"name": "C"})
        await store.upsert_edge(a.id, b.id, "MEMBER_OF", weight=0.9)
        await store.upsert_edge(a.id, c.id, "MEMBER_OF", weight=0.01)
        nbs = await store.get_neighbors(a.id, min_weight=0.5, direction="out")
        assert len(nbs) == 1
        assert nbs[0].id == b.id

    @pytest.mark.asyncio
    async def test_get_neighbors_with_relation_filter(self, store: GraphStore):
        a = await store.upsert_node("Person", {"name": "A"})
        b = await store.upsert_node("Email", {"subject": "X"})
        c = await store.upsert_node("Event", {"title": "Y"})
        await store.upsert_edge(a.id, b.id, "SENT")
        await store.upsert_edge(a.id, c.id, "ATTENDS")
        nbs = await store.get_neighbors(a.id, relation="SENT", direction="out")
        assert len(nbs) == 1
        assert nbs[0].label == "Email"

    @pytest.mark.asyncio
    async def test_get_neighbors_direction_in(self, store: GraphStore):
        a = await store.upsert_node("Person", {"name": "A"})
        b = await store.upsert_node("Email", {"subject": "X"})
        await store.upsert_edge(a.id, b.id, "SENT")
        # From email, direction=in should find Person
        nbs = await store.get_neighbors(b.id, direction="in")
        assert len(nbs) == 1
        assert nbs[0].id == a.id


# ── Decay & Reinforcement ────────────────────────────────────────

class TestDecayReinforcement:
    @pytest.mark.asyncio
    async def test_apply_decay_reduces_weight(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        edge = await store.upsert_edge(n1.id, n2.id, "SENT")
        # Simulate 30 days passed
        future_time = edge.created_at + (30 * 86400)
        new_weight = await store.apply_decay(edge.id, decay_rate=0.05, reference_time=future_time)
        assert new_weight < 1.0
        assert new_weight > 0.0

    @pytest.mark.asyncio
    async def test_reinforce_increases_weight(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        edge = await store.upsert_edge(n1.id, n2.id, "SENT", weight=0.5)
        new_weight = await store.reinforce(edge.id, boost=0.2)
        assert new_weight == pytest.approx(0.7, abs=0.01)

    @pytest.mark.asyncio
    async def test_reinforce_caps_at_one(self, store: GraphStore):
        n1 = await store.upsert_node("Person", {"name": "A"})
        n2 = await store.upsert_node("Email", {"subject": "X"})
        edge = await store.upsert_edge(n1.id, n2.id, "SENT", weight=0.95)
        new_weight = await store.reinforce(edge.id, boost=0.2)
        assert new_weight == 1.0


# ── Stats ─────────────────────────────────────────────────────────

class TestStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self, store: GraphStore):
        s = await store.stats()
        assert s["nodes"] == 0
        assert s["edges"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_inserts(self, store: GraphStore):
        await store.upsert_node("Person", {"name": "A"})
        await store.upsert_node("Email", {"subject": "X"})
        n1 = await store.upsert_node("Person", {"name": "A2"})
        n2 = await store.upsert_node("Email", {"subject": "X2"})
        await store.upsert_edge(n1.id, n2.id, "SENT")
        s = await store.stats()
        assert s["nodes"] == 4
        assert s["edges"] == 1
