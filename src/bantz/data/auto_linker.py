"""
AutoLinker — Automatically creates graph relationships from tool results.

When a tool returns structured data (email, calendar event, contact, …),
the AutoLinker extracts entities and edges and upserts them into the
GraphStore.  This runs transparently after tool execution—callers don't
need to think about the graph.

Usage::

    linker = AutoLinker(graph_store)
    await linker.link("gmail", {"from": "ali@x.com", "to": ["b@x.com"], ...})
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from bantz.data.graph_store import GraphStore

logger = logging.getLogger(__name__)


class AutoLinker:
    """Extracts entities from tool results and links them in the graph."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    # ── public entry point ──

    async def link(self, source: str, data: Dict[str, Any]) -> int:
        """Route *data* to the appropriate linker based on *source*.

        Returns the number of edges created/updated.
        """
        handler = self._handlers.get(source)
        if handler:
            try:
                return await handler(self, data)
            except Exception:
                logger.warning("AutoLinker failed for source=%s", source, exc_info=True)
                return 0
        return 0

    # ── email linker ──

    async def _link_email(self, data: Dict[str, Any]) -> int:
        """Extract entities from a Gmail result.

        Expected keys: from, to, cc, subject, message_id, snippet, date
        """
        edges_created = 0
        now = time.time()

        # Upsert email node
        message_id = data.get("message_id") or data.get("id", "")
        email_node = await self._store.upsert_node("Email", {
            "message_id": message_id,
            "subject": data.get("subject", ""),
            "snippet": data.get("snippet", ""),
            "date": data.get("date", ""),
        }, unique_key="message_id")

        # Upsert sender → edge
        sender = data.get("from", "")
        if sender:
            sender_addr = self._extract_email(sender)
            sender_name = self._extract_name(sender)
            sender_node = await self._store.upsert_node("Person", {
                "email": sender_addr,
                "name": sender_name or sender_addr,
            }, unique_key="email")
            await self._store.upsert_edge(
                sender_node.id, email_node.id, "SENT",
                {"source": "gmail", "date": data.get("date", "")},
            )
            edges_created += 1

        # Upsert recipients → edges
        for field_name, relation in [("to", "RECEIVED"), ("cc", "RECEIVED")]:
            recipients = data.get(field_name, [])
            if isinstance(recipients, str):
                recipients = [r.strip() for r in recipients.split(",")]
            for recip in recipients:
                if not recip:
                    continue
                addr = self._extract_email(recip)
                name = self._extract_name(recip)
                recip_node = await self._store.upsert_node("Person", {
                    "email": addr,
                    "name": name or addr,
                }, unique_key="email")
                await self._store.upsert_edge(
                    recip_node.id, email_node.id, relation,
                    {"source": "gmail", "date": data.get("date", "")},
                )
                edges_created += 1

        # Thread REPLY_TO
        thread_id = data.get("thread_id")
        in_reply_to = data.get("in_reply_to")
        if in_reply_to:
            parent_nodes = await self._store.search_nodes(
                "Email", message_id=in_reply_to
            )
            if parent_nodes:
                await self._store.upsert_edge(
                    email_node.id, parent_nodes[0].id, "REPLY_TO",
                    {"thread_id": thread_id or ""},
                )
                edges_created += 1

        return edges_created

    # ── calendar linker ──

    async def _link_event(self, data: Dict[str, Any]) -> int:
        """Extract entities from a Calendar event.

        Expected keys: event_id, title/summary, start, end, attendees, location
        """
        edges_created = 0

        event_id = data.get("event_id") or data.get("id", "")
        event_node = await self._store.upsert_node("Event", {
            "event_id": event_id,
            "title": data.get("title") or data.get("summary", ""),
            "start": data.get("start", ""),
            "end": data.get("end", ""),
            "location": data.get("location", ""),
        }, unique_key="event_id")

        # Link attendees
        attendees = data.get("attendees", [])
        for att in attendees:
            if isinstance(att, str):
                email = self._extract_email(att)
                name = self._extract_name(att)
            elif isinstance(att, dict):
                email = att.get("email", "")
                name = att.get("displayName") or att.get("name", email)
            else:
                continue
            if not email:
                continue

            person = await self._store.upsert_node("Person", {
                "email": email,
                "name": name or email,
            }, unique_key="email")
            await self._store.upsert_edge(
                person.id, event_node.id, "ATTENDS",
                {"source": "calendar", "status": att.get("responseStatus", "")
                 if isinstance(att, dict) else ""},
            )
            edges_created += 1

        # Organiser → SCHEDULED_FOR
        organiser = data.get("organizer") or data.get("organiser")
        if isinstance(organiser, dict):
            org_email = organiser.get("email", "")
            org_name = organiser.get("displayName", org_email)
            if org_email:
                org_node = await self._store.upsert_node("Person", {
                    "email": org_email,
                    "name": org_name,
                }, unique_key="email")
                await self._store.upsert_edge(
                    event_node.id, org_node.id, "SCHEDULED_FOR",
                    {"source": "calendar"},
                )
                edges_created += 1

        return edges_created

    # ── contact linker ──

    async def _link_contact(self, data: Dict[str, Any]) -> int:
        """Extract entities from a Contacts result."""
        edges_created = 0
        email = data.get("email", "")
        name = data.get("name", email)
        org_name = data.get("organization") or data.get("company")

        if not email and not name:
            return 0

        person = await self._store.upsert_node("Person", {
            "email": email,
            "name": name,
            "phone": data.get("phone", ""),
            "role": data.get("role") or data.get("title", ""),
        }, unique_key="email" if email else "name")

        if org_name:
            org = await self._store.upsert_node("Org", {
                "name": org_name,
                "domain": data.get("domain", ""),
            }, unique_key="name")
            await self._store.upsert_edge(
                person.id, org.id, "MEMBER_OF",
                {"source": "contacts"},
            )
            edges_created += 1

        return edges_created

    # ── task linker ──

    async def _link_task(self, data: Dict[str, Any]) -> int:
        """Extract entities from a task/todo result."""
        task_id = data.get("task_id") or data.get("id", "")
        if not task_id:
            return 0

        edges_created = 0
        task_node = await self._store.upsert_node("Task", {
            "task_id": task_id,
            "title": data.get("title", ""),
            "status": data.get("status", ""),
            "priority": data.get("priority", ""),
            "due_date": data.get("due_date") or data.get("due", ""),
        }, unique_key="task_id")

        assignee = data.get("assignee") or data.get("assigned_to")
        if assignee:
            addr = self._extract_email(assignee) if isinstance(assignee, str) else assignee.get("email", "")
            if addr:
                person = await self._store.upsert_node("Person", {
                    "email": addr,
                    "name": self._extract_name(assignee) if isinstance(assignee, str) else assignee.get("name", addr),
                }, unique_key="email")
                await self._store.upsert_edge(
                    person.id, task_node.id, "ASSIGNED_TO",
                    {"source": "tasks"},
                )
                edges_created += 1

        return edges_created

    # ── handler registry ──

    _handlers: Dict[str, Any] = {
        "gmail": _link_email,
        "email": _link_email,
        "calendar": _link_event,
        "contacts": _link_contact,
        "contact": _link_contact,
        "tasks": _link_task,
        "task": _link_task,
    }

    # ── utility ──

    _EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

    @classmethod
    def _extract_email(cls, text: str) -> str:
        m = cls._EMAIL_RE.search(text)
        return m.group(0).lower() if m else text.strip().lower()

    @staticmethod
    def _extract_name(text: str) -> str:
        """Extract name from 'Name <email>' format."""
        if "<" in text:
            return text.split("<")[0].strip().strip('"').strip("'")
        return ""
