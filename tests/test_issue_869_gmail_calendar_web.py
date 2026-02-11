"""Tests for Issue #869 — Gmail & Calendar tools on Web Dashboard.

Covers:
  1. handle_command() brain path — confirmation fields pass through
  2. handle_command() — pending confirmation yes/no handling
  3. WebSocket handler — confirm_request message type
  4. WebSocket handler — confirm message type (yes/no)
  5. REST chat endpoint — requires_confirmation field in response
  6. Frontend confirmation dialog (existence check in HTML)
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────
# Fake server with confirmation support
# ─────────────────────────────────────────────────────────────


class FakeOrchestratorOutput:
    """Fake orchestrator output."""

    def __init__(
        self,
        assistant_reply: str = "Test yanıtı efendim.",
        route: str = "smalltalk",
        ask_user: bool = False,
        question: str = "",
        requires_confirmation: bool = False,
        confirmation_prompt: str = "",
    ):
        self.assistant_reply = assistant_reply
        self.route = route
        self.ask_user = ask_user
        self.question = question
        self.requires_confirmation = requires_confirmation
        self.confirmation_prompt = confirmation_prompt


class FakeOrchestratorState:
    """Minimal fake OrchestratorState with confirmation support."""

    def __init__(self):
        self.pending_confirmations: list[dict] = []
        self.confirmed_tool: Optional[str] = None

    def has_pending_confirmation(self) -> bool:
        return bool(self.pending_confirmations)

    def peek_pending_confirmation(self) -> Optional[dict]:
        if not self.pending_confirmations:
            return None
        return self.pending_confirmations[0]

    def pop_pending_confirmation(self) -> Optional[dict]:
        if not self.pending_confirmations:
            return None
        return self.pending_confirmations.pop(0)

    def clear_pending_confirmation(self) -> None:
        self.pending_confirmations.clear()
        self.confirmed_tool = None

    def add_pending_confirmation(self, action: dict) -> None:
        self.pending_confirmations.append(action)


class FakeInboxStore:
    def snapshot(self):
        return {"items": [], "unread": 0}

    def mark_read(self, target_id):
        return False

    def clear(self):
        pass


# ─────────────────────────────────────────────────────────────
# Test: server.py handle_command confirmation flow
# ─────────────────────────────────────────────────────────────


class TestHandleCommandConfirmation:
    """Test that handle_command correctly handles confirmation flow."""

    def _make_server(self, *, pending_tool=None, pending_prompt=None):
        """Create a minimal real BantzServer mock with brain + state."""
        from bantz.brain.orchestrator_state import OrchestratorState

        server = MagicMock()
        server._brain = MagicMock()
        server._brain_state = OrchestratorState()
        server._inbox = FakeInboxStore()
        server._running = True
        server.session_name = "test"
        server.ctx = MagicMock()
        server.ctx.mode = "normal"
        server.ctx.queue_active = lambda: False
        server.ctx.pending = None

        if pending_tool:
            server._brain_state.add_pending_confirmation({
                "tool": pending_tool,
                "prompt": pending_prompt or f"{pending_tool} onay bekleniyor",
                "slots": {},
                "risk_level": "med",
            })

        return server

    def test_brain_path_returns_confirmation_fields(self):
        """When brain output creates a pending confirmation, handle_command
        should return needs_confirmation=True + prompt."""
        from bantz.server import BantzServer

        server = self._make_server()
        state = server._brain_state

        # After process_turn, simulate the state having a pending confirmation
        def fake_process_turn(command, brain_state):
            brain_state.add_pending_confirmation({
                "tool": "calendar.create_event",
                "prompt": "'Toplantı' yarın 14:00'de eklensin mi?",
                "slots": {},
                "risk_level": "med",
            })
            return FakeOrchestratorOutput(
                assistant_reply="",
                route="calendar",
            ), brain_state

        server._brain.process_turn = fake_process_turn

        # Call handle_command via the real method with mocked internals
        # We need to call the actual handle_command, not the mock
        result = BantzServer.handle_command(server, "yarın 2ye toplantı koy")

        assert result["needs_confirmation"] is True
        assert result["confirmation_prompt"] is not None
        assert "Toplantı" in result["confirmation_prompt"] or "calendar" in str(result.get("confirmation_tool", ""))

    def test_confirmation_yes_clears_pending(self):
        """When user says 'evet' with pending confirmation, it should
        set confirmed_tool and re-run process_turn."""
        from bantz.server import BantzServer

        server = self._make_server(
            pending_tool="calendar.create_event",
            pending_prompt="'Toplantı' yarın 14:00'de eklensin mi?",
        )

        def fake_process_turn(command, brain_state):
            # When called after confirmation, return success
            return FakeOrchestratorOutput(
                assistant_reply="Tamamdır efendim, toplantı eklendi.",
                route="calendar",
            ), brain_state

        server._brain.process_turn = fake_process_turn

        result = BantzServer.handle_command(server, "evet")

        assert result["ok"] is True
        assert "Tamamdır" in result["text"] or "toplantı" in result["text"].lower()
        assert result["brain"] is True

    def test_confirmation_no_cancels(self):
        """When user says 'hayır' with pending confirmation, it should
        cancel and clear pending."""
        from bantz.server import BantzServer

        server = self._make_server(
            pending_tool="calendar.create_event",
            pending_prompt="'Toplantı' yarın 14:00'de eklensin mi?",
        )

        result = BantzServer.handle_command(server, "hayır")

        assert result["ok"] is True
        assert "iptal" in result["text"].lower()
        assert result["route"] == "cancelled"
        # Pending should be cleared
        assert not server._brain_state.has_pending_confirmation()

    def test_confirmation_unknown_reprompts(self):
        """When user says something unrelated with pending confirmation,
        re-show the confirmation prompt."""
        from bantz.server import BantzServer

        server = self._make_server(
            pending_tool="calendar.create_event",
            pending_prompt="'Toplantı' yarın 14:00'de eklensin mi?",
        )

        result = BantzServer.handle_command(server, "hava nasıl?")

        assert result["needs_confirmation"] is True
        assert "confirmation_prompt" in result

    def test_yes_variations_accepted(self):
        """Various Turkish confirmation words should be accepted."""
        from bantz.server import BantzServer

        yes_words = ["evet", "tamam", "ok", "olur", "ekle", "e", "kabul"]
        for word in yes_words:
            server = self._make_server(
                pending_tool="calendar.create_event",
                pending_prompt="Onay bekleniyor",
            )
            server._brain.process_turn = lambda cmd, st: (
                FakeOrchestratorOutput(assistant_reply="OK", route="calendar"), st
            )
            result = BantzServer.handle_command(server, word)
            assert result["ok"] is True, f"'{word}' should be accepted as confirmation"
            assert result.get("needs_confirmation") is not True, f"'{word}' should clear confirmation"

    def test_no_variations_accepted(self):
        """Various Turkish rejection words should be accepted."""
        from bantz.server import BantzServer

        no_words = ["hayır", "iptal", "vazgeç", "hayir", "reddet", "yok"]
        for word in no_words:
            server = self._make_server(
                pending_tool="calendar.create_event",
                pending_prompt="Onay bekleniyor",
            )
            result = BantzServer.handle_command(server, word)
            assert result["ok"] is True, f"'{word}' should be accepted as rejection"
            assert "iptal" in result["text"].lower(), f"'{word}' should cancel"


# ─────────────────────────────────────────────────────────────
# Test: WebSocket handler
# ─────────────────────────────────────────────────────────────


class TestWebSocketConfirmation:
    """Test WebSocket chat endpoint confirmation support."""

    @pytest.fixture()
    def _app(self):
        from bantz.api.server import create_app
        from bantz.core.events import EventBus

        server = MagicMock()
        server.handle_command = MagicMock()
        event_bus = EventBus(history_size=10)

        os.environ.pop("BANTZ_API_TOKEN", None)
        app = create_app(bantz_server=server, event_bus=event_bus)
        return app, server

    def test_ws_chat_normal_response(self, _app):
        """Normal chat response should be type='chat'."""
        from fastapi.testclient import TestClient

        app, server = _app
        server.handle_command.return_value = {
            "ok": True,
            "text": "Merhaba efendim!",
            "brain": True,
            "route": "smalltalk",
        }

        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "chat", "message": "merhaba"})
            response = websocket.receive_json()

        assert response["type"] == "chat"
        assert response["data"]["response"] == "Merhaba efendim!"

    def test_ws_chat_confirmation_response(self, _app):
        """When response has needs_confirmation, type should be 'confirm_request'."""
        from fastapi.testclient import TestClient

        app, server = _app
        server.handle_command.return_value = {
            "ok": True,
            "text": "'Toplantı' yarın 14:00'de eklensin mi?",
            "brain": True,
            "route": "calendar",
            "needs_confirmation": True,
            "confirmation_prompt": "'Toplantı' yarın 14:00'de eklensin mi?",
            "confirmation_tool": "calendar.create_event",
        }

        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "chat", "message": "yarın 2ye toplantı koy"})
            response = websocket.receive_json()

        assert response["type"] == "confirm_request"
        assert response["data"]["tool"] == "calendar.create_event"
        assert "Toplantı" in response["data"]["prompt"]

    def test_ws_confirm_yes(self, _app):
        """Sending confirm action=yes should call handle_command with 'evet'."""
        from fastapi.testclient import TestClient

        app, server = _app
        server.handle_command.return_value = {
            "ok": True,
            "text": "Tamamdır, toplantı eklendi.",
            "brain": True,
            "route": "calendar",
        }

        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "confirm", "action": "yes"})
            response = websocket.receive_json()

        server.handle_command.assert_called_once_with("evet")
        assert response["type"] == "chat"
        assert "toplantı" in response["data"]["response"].lower() or response["data"]["ok"]

    def test_ws_confirm_no(self, _app):
        """Sending confirm action=no should call handle_command with 'hayır'."""
        from fastapi.testclient import TestClient

        app, server = _app
        server.handle_command.return_value = {
            "ok": True,
            "text": "Anlaşıldı efendim, iptal ettim.",
            "brain": True,
            "route": "cancelled",
        }

        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "confirm", "action": "no"})
            response = websocket.receive_json()

        server.handle_command.assert_called_once_with("hayır")
        assert response["type"] == "chat"

    def test_ws_confirm_invalid_action(self, _app):
        """Invalid confirm action should return error."""
        from fastapi.testclient import TestClient

        app, server = _app
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "confirm", "action": "maybe"})
            response = websocket.receive_json()

        assert response["type"] == "error"
        assert "invalid_confirm" in response["data"]["code"]

    def test_ws_ping_still_works(self, _app):
        """Ping/pong should still work."""
        from fastapi.testclient import TestClient

        app, server = _app
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "ping"})
            response = websocket.receive_json()

        assert response["type"] == "pong"


# ─────────────────────────────────────────────────────────────
# Test: REST /api/v1/chat confirmation
# ─────────────────────────────────────────────────────────────


class TestRESTChatConfirmation:
    """Test REST chat endpoint includes confirmation fields."""

    @pytest.fixture()
    def client(self):
        from bantz.api.server import create_app
        from bantz.core.events import EventBus
        from fastapi.testclient import TestClient

        server = MagicMock()
        server.handle_command = MagicMock()
        event_bus = EventBus(history_size=10)

        os.environ.pop("BANTZ_API_TOKEN", None)
        app = create_app(bantz_server=server, event_bus=event_bus)
        with TestClient(app) as tc:
            yield tc, server

    def test_rest_chat_confirmation_fields(self, client):
        """REST chat response should include requires_confirmation."""
        tc, server = client
        server.handle_command.return_value = {
            "ok": True,
            "text": "'Toplantı' eklensin mi?",
            "brain": True,
            "route": "calendar",
            "needs_confirmation": True,
            "confirmation_prompt": "'Toplantı' eklensin mi?",
        }

        response = tc.post("/api/v1/chat", json={"message": "toplantı ekle"})
        data = response.json()

        assert response.status_code == 200
        assert data["requires_confirmation"] is True
        assert data["confirmation_prompt"] == "'Toplantı' eklensin mi?"

    def test_rest_chat_no_confirmation(self, client):
        """Normal responses should have requires_confirmation=False."""
        tc, server = client
        server.handle_command.return_value = {
            "ok": True,
            "text": "Merhaba!",
            "brain": True,
            "route": "smalltalk",
        }

        response = tc.post("/api/v1/chat", json={"message": "merhaba"})
        data = response.json()

        assert response.status_code == 200
        assert data["requires_confirmation"] is False


# ─────────────────────────────────────────────────────────────
# Test: Frontend HTML confirmation dialog
# ─────────────────────────────────────────────────────────────


class TestFrontendConfirmation:
    """Test that the frontend HTML includes confirmation UI."""

    @pytest.fixture()
    def html_content(self):
        from pathlib import Path
        html_path = Path(__file__).parent.parent / "src" / "bantz" / "api" / "static" / "index.html"
        return html_path.read_text(encoding="utf-8")

    def test_confirm_overlay_exists(self, html_content):
        """Confirmation overlay div should exist."""
        assert 'id="confirmOverlay"' in html_content

    def test_confirm_text_element_exists(self, html_content):
        """Confirmation text element should exist."""
        assert 'id="confirmText"' in html_content

    def test_confirm_tool_element_exists(self, html_content):
        """Confirmation tool element should exist."""
        assert 'id="confirmTool"' in html_content

    def test_confirm_buttons_exist(self, html_content):
        """Confirm/reject buttons should exist."""
        assert "confirmAction('yes')" in html_content
        assert "confirmAction('no')" in html_content

    def test_showConfirmDialog_function(self, html_content):
        """showConfirmDialog JS function should exist."""
        assert "function showConfirmDialog" in html_content

    def test_confirmAction_function(self, html_content):
        """confirmAction JS function should exist."""
        assert "function confirmAction" in html_content

    def test_confirm_request_handler(self, html_content):
        """WS onmessage should handle confirm_request type."""
        assert "confirm_request" in html_content

    def test_ws_sends_confirm_message(self, html_content):
        """confirmAction should send {type:'confirm'} via WS."""
        assert "type:'confirm'" in html_content

    def test_confirm_modal_css(self, html_content):
        """Confirmation modal CSS should exist."""
        assert ".confirm-overlay" in html_content
        assert ".confirm-modal" in html_content
