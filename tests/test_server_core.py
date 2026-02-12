"""Server core tests — BantzServer, InboxStore, socket helpers (Issue #853).

Tests are unit-level; they do NOT open real sockets or start real servers.
"""
from __future__ import annotations

import json
import struct
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bantz.core.events import Event
from bantz.server import (
    DEFAULT_SESSION,
    InboxStore,
    get_socket_path,
    is_server_running,
)


# ─────────────────────────────────────────────────────────────────
# InboxStore
# ─────────────────────────────────────────────────────────────────

class TestInboxStore:

    def test_empty_snapshot(self):
        store = InboxStore()
        snap = store.snapshot()
        assert snap["items"] == []
        assert snap["unread"] == 0

    def test_push_proactive_event(self):
        store = InboxStore()
        event = Event(
            event_type="bantz_message",
            data={"proactive": True, "text": "Hello!", "kind": "system"},
            timestamp=datetime.now(),
        )
        store.push_from_event(event)
        snap = store.snapshot()
        assert len(snap["items"]) == 1
        assert snap["unread"] == 1
        assert snap["items"][0]["text"] == "Hello!"

    def test_skip_non_proactive_event(self):
        store = InboxStore()
        event = Event(
            event_type="bantz_message",
            data={"proactive": False, "text": "Ignored"},
            timestamp=datetime.now(),
        )
        store.push_from_event(event)
        assert len(store.snapshot()["items"]) == 0

    def test_skip_no_proactive_key(self):
        store = InboxStore()
        event = Event(
            event_type="bantz_message",
            data={"text": "No proactive key"},
            timestamp=datetime.now(),
        )
        store.push_from_event(event)
        assert len(store.snapshot()["items"]) == 0

    def test_mark_read(self):
        store = InboxStore()
        event = Event(
            event_type="bantz_message",
            data={"proactive": True, "text": "Read me", "kind": "reminder"},
            timestamp=datetime.now(),
        )
        store.push_from_event(event)
        snap = store.snapshot()
        item_id = snap["items"][0]["id"]
        ok = store.mark_read(item_id)
        assert ok is True
        snap2 = store.snapshot()
        assert snap2["unread"] == 0
        assert snap2["items"][0]["read"] is True

    def test_mark_read_nonexistent(self):
        store = InboxStore()
        ok = store.mark_read(999)
        assert ok is False

    def test_clear(self):
        store = InboxStore()
        for i in range(5):
            event = Event(
                event_type="bantz_message",
                data={"proactive": True, "text": f"Item {i}", "kind": "system"},
                timestamp=datetime.now(),
            )
            store.push_from_event(event)
        assert len(store.snapshot()["items"]) == 5
        store.clear()
        assert len(store.snapshot()["items"]) == 0

    def test_maxlen_enforced(self):
        store = InboxStore(maxlen=3)
        for i in range(10):
            event = Event(
                event_type="bantz_message",
                data={"proactive": True, "text": f"Item {i}", "kind": "system"},
                timestamp=datetime.now(),
            )
            store.push_from_event(event)
        snap = store.snapshot()
        assert len(snap["items"]) <= 3

    def test_auto_increment_id(self):
        store = InboxStore()
        for i in range(3):
            event = Event(
                event_type="bantz_message",
                data={"proactive": True, "text": f"Item {i}", "kind": "system"},
                timestamp=datetime.now(),
            )
            store.push_from_event(event)
        ids = [it["id"] for it in store.snapshot()["items"]]
        assert ids == [1, 2, 3]

    def test_thread_safety(self):
        store = InboxStore()
        errors = []

        def push_events(n):
            try:
                for i in range(n):
                    event = Event(
                        event_type="bantz_message",
                        data={"proactive": True, "text": f"t-{i}", "kind": "system"},
                        timestamp=datetime.now(),
                    )
                    store.push_from_event(event)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=push_events, args=(20,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(store.snapshot()["items"]) <= 200

    def test_kind_detection_checkin(self):
        store = InboxStore()
        event = Event(
            event_type="bantz_message",
            data={"proactive": True, "intent": "checkin_fired", "text": "Check-in"},
            timestamp=datetime.now(),
        )
        store.push_from_event(event)
        assert store.snapshot()["items"][0]["kind"] == "checkin"

    def test_kind_detection_reminder(self):
        store = InboxStore()
        event = Event(
            event_type="bantz_message",
            data={"proactive": True, "intent": "reminder_fired", "text": "Reminder"},
            timestamp=datetime.now(),
        )
        store.push_from_event(event)
        assert store.snapshot()["items"][0]["kind"] == "reminder"


# ─────────────────────────────────────────────────────────────────
# Socket helpers
# ─────────────────────────────────────────────────────────────────

class TestSocketHelpers:

    def test_get_socket_path_default(self):
        path = get_socket_path()
        assert path.name == f"{DEFAULT_SESSION}.sock"
        assert "bantz_sessions" in str(path)

    def test_get_socket_path_custom(self):
        path = get_socket_path("custom_session")
        assert path.name == "custom_session.sock"

    def test_is_server_running_no_socket(self):
        # Without a socket file it shouldn't be running
        assert is_server_running("nonexistent_test_session") is False


# ─────────────────────────────────────────────────────────────────
# BantzServer — framing helpers (static, no socket needed)
# ─────────────────────────────────────────────────────────────────

class TestFramingHelpers:

    def test_send_framed(self):
        """_send_framed prepends 4-byte big-endian length."""
        from bantz.server import BantzServer

        mock_sock = MagicMock()
        payload = b'{"hello": "world"}'
        BantzServer._send_framed(mock_sock, payload)
        expected_header = struct.pack("!I", len(payload))
        call_args = mock_sock.sendall.call_args[0][0]
        assert call_args[:4] == expected_header
        assert call_args[4:] == payload

    def test_recv_framed_good_frame(self):
        """_recv_framed reads length + data."""
        from bantz.server import BantzServer

        payload = b'{"test": true}'
        header = struct.pack("!I", len(payload))
        data = header + payload

        mock_sock = MagicMock()
        # First call for header, second for body
        mock_sock.recv.side_effect = [header, payload]
        result = BantzServer._recv_framed(mock_sock)
        assert result == payload

    def test_recv_framed_empty(self):
        """Empty recv returns empty bytes."""
        from bantz.server import BantzServer

        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""
        result = BantzServer._recv_framed(mock_sock)
        assert result == b""
