"""
Tests for AutoLinker — entity extraction and graph relationship creation.

Covers:
- Email linking (sender, recipients, REPLY_TO)
- Calendar event linking (attendees, organiser)
- Contact linking (person, org membership)
- Task linking (assignee)
- Unknown source gracefully returns 0
"""

from __future__ import annotations

import asyncio

import pytest

from bantz.data.auto_linker import AutoLinker
from bantz.data.graph_backends.memory_backend import InMemoryGraphStore


@pytest.fixture
def store():
    s = InMemoryGraphStore()
    asyncio.get_event_loop().run_until_complete(s.initialise())
    yield s
    asyncio.get_event_loop().run_until_complete(s.close())


@pytest.fixture
def linker(store):
    return AutoLinker(store)


# ── Email linking ─────────────────────────────────────────────────

class TestEmailLinking:
    @pytest.mark.asyncio
    async def test_simple_email_creates_nodes_and_edges(self, linker, store):
        edges = await linker.link("gmail", {
            "message_id": "msg-001",
            "from": "Ali Kaya <ali@example.com>",
            "to": ["veli@example.com"],
            "subject": "Meeting notes",
            "snippet": "Here are the notes...",
            "date": "2026-01-15",
        })
        assert edges >= 2  # SENT + RECEIVED

        # Verify email node
        emails = await store.search_nodes("Email", message_id="msg-001")
        assert len(emails) == 1
        assert emails[0].properties["subject"] == "Meeting notes"

        # Verify person nodes
        persons = await store.search_nodes("Person")
        emails_extracted = {p.properties.get("email") for p in persons}
        assert "ali@example.com" in emails_extracted
        assert "veli@example.com" in emails_extracted

    @pytest.mark.asyncio
    async def test_email_with_cc(self, linker, store):
        edges = await linker.link("gmail", {
            "message_id": "msg-002",
            "from": "a@x.com",
            "to": ["b@x.com"],
            "cc": ["c@x.com", "d@x.com"],
            "subject": "FYI",
        })
        # SENT(a→email) + RECEIVED(b→email) + RECEIVED(c→email) + RECEIVED(d→email)
        assert edges >= 4

    @pytest.mark.asyncio
    async def test_email_to_as_comma_string(self, linker, store):
        """to field can be a comma-separated string."""
        edges = await linker.link("gmail", {
            "message_id": "msg-003",
            "from": "a@x.com",
            "to": "b@x.com, c@x.com",
            "subject": "Test",
        })
        assert edges >= 3

    @pytest.mark.asyncio
    async def test_email_extracts_name_from_angle_format(self, linker, store):
        await linker.link("gmail", {
            "message_id": "msg-004",
            "from": "Ali Kaya <ali@x.com>",
            "to": [],
            "subject": "Test",
        })
        persons = await store.search_nodes("Person", email="ali@x.com")
        assert len(persons) == 1
        assert persons[0].properties["name"] == "Ali Kaya"

    @pytest.mark.asyncio
    async def test_reply_to_creates_edge(self, linker, store):
        # Create parent email first
        await linker.link("gmail", {
            "message_id": "parent-001",
            "from": "a@x.com",
            "to": [],
            "subject": "Original",
        })
        # Reply
        await linker.link("gmail", {
            "message_id": "reply-001",
            "from": "b@x.com",
            "to": ["a@x.com"],
            "subject": "Re: Original",
            "in_reply_to": "parent-001",
            "thread_id": "thread-1",
        })
        reply_nodes = await store.search_nodes("Email", message_id="reply-001")
        assert len(reply_nodes) == 1
        edges = await store.get_edges(reply_nodes[0].id, relation="REPLY_TO", direction="out")
        assert len(edges) == 1


# ── Calendar linking ──────────────────────────────────────────────

class TestCalendarLinking:
    @pytest.mark.asyncio
    async def test_event_with_attendees(self, linker, store):
        edges = await linker.link("calendar", {
            "event_id": "evt-001",
            "summary": "Sprint Review",
            "start": "2026-02-01T14:00:00",
            "end": "2026-02-01T15:00:00",
            "attendees": [
                {"email": "ali@x.com", "displayName": "Ali"},
                {"email": "veli@x.com", "displayName": "Veli"},
            ],
        })
        assert edges >= 2

        events = await store.search_nodes("Event", event_id="evt-001")
        assert len(events) == 1
        assert events[0].properties["title"] == "Sprint Review"

    @pytest.mark.asyncio
    async def test_event_with_organiser(self, linker, store):
        edges = await linker.link("calendar", {
            "event_id": "evt-002",
            "summary": "1:1",
            "start": "2026-02-01T10:00:00",
            "end": "2026-02-01T10:30:00",
            "organizer": {"email": "boss@x.com", "displayName": "Boss"},
            "attendees": [],
        })
        assert edges >= 1  # SCHEDULED_FOR

    @pytest.mark.asyncio
    async def test_event_attendees_as_strings(self, linker, store):
        edges = await linker.link("calendar", {
            "event_id": "evt-003",
            "title": "Meeting",
            "start": "",
            "end": "",
            "attendees": ["ali@x.com", "veli@x.com"],
        })
        assert edges >= 2


# ── Contact linking ───────────────────────────────────────────────

class TestContactLinking:
    @pytest.mark.asyncio
    async def test_contact_with_org(self, linker, store):
        edges = await linker.link("contacts", {
            "name": "Ali Kaya",
            "email": "ali@acme.com",
            "organization": "Acme Corp",
        })
        assert edges >= 1  # MEMBER_OF

        orgs = await store.search_nodes("Org", name="Acme Corp")
        assert len(orgs) == 1

    @pytest.mark.asyncio
    async def test_contact_without_org(self, linker, store):
        edges = await linker.link("contacts", {
            "name": "Solo Person",
            "email": "solo@x.com",
        })
        assert edges == 0

        persons = await store.search_nodes("Person", email="solo@x.com")
        assert len(persons) == 1


# ── Task linking ──────────────────────────────────────────────────

class TestTaskLinking:
    @pytest.mark.asyncio
    async def test_task_with_assignee(self, linker, store):
        edges = await linker.link("tasks", {
            "task_id": "task-001",
            "title": "Fix bug",
            "status": "open",
            "assignee": {"email": "dev@x.com", "name": "Dev"},
        })
        assert edges >= 1

        tasks = await store.search_nodes("Task", task_id="task-001")
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_task_without_assignee(self, linker, store):
        edges = await linker.link("tasks", {
            "task_id": "task-002",
            "title": "Review PR",
        })
        assert edges == 0


# ── Edge cases ────────────────────────────────────────────────────

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_unknown_source_returns_zero(self, linker):
        edges = await linker.link("unknown_tool", {"data": "stuff"})
        assert edges == 0

    @pytest.mark.asyncio
    async def test_empty_data_doesnt_crash(self, linker):
        edges = await linker.link("gmail", {})
        assert edges == 0

    @pytest.mark.asyncio
    async def test_dedup_person_across_sources(self, linker, store):
        """Same email from gmail and calendar should produce one Person node."""
        await linker.link("gmail", {
            "message_id": "m1",
            "from": "ali@x.com",
            "to": [],
            "subject": "Hi",
        })
        await linker.link("calendar", {
            "event_id": "e1",
            "summary": "Meeting",
            "start": "",
            "end": "",
            "attendees": [{"email": "ali@x.com", "displayName": "Ali"}],
        })
        persons = await store.search_nodes("Person", email="ali@x.com")
        assert len(persons) == 1
