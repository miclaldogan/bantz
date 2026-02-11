"""Comprehensive tests for the Bantz REST API (Issue #834).

Tests cover:
  - POST /api/v1/chat (with/without auth)
  - GET  /api/v1/health
  - GET  /api/v1/skills
  - GET  /api/v1/notifications (SSE)
  - GET  /api/v1/inbox
  - POST /api/v1/inbox/{id}/read
  - WS   /ws/chat
  - Authentication (Bearer token)
  - CORS headers
  - Error handling
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


class FakeBrainOutput:
    """Fake orchestrator output for testing."""

    def __init__(
        self,
        assistant_reply: str = "Test yanıtı efendim.",
        route: str = "smalltalk",
        ask_user: bool = False,
        question: str = "",
    ):
        self.assistant_reply = assistant_reply
        self.route = route
        self.ask_user = ask_user
        self.question = question


class FakeRuntime:
    """Fake BantzRuntime for testing."""

    def __init__(self):
        self.tools = FakeToolRegistry()

    def process_turn(self, user_input, state):
        return FakeBrainOutput(f"Yanıt: {user_input}"), state


class FakeToolRegistry:
    """Fake tool registry."""

    def list_tools(self):
        return ["calendar_list", "gmail_read", "system_info"]

    def get_tool(self, name):
        tool = MagicMock()
        tool.description = f"Tool: {name}"
        tool.category = "builtin"
        return tool


class FakeInboxStore:
    """Fake inbox store for testing."""

    def __init__(self):
        self._items = [
            {
                "id": 1,
                "ts": datetime.now().isoformat(),
                "kind": "reminder",
                "text": "Test hatırlatma",
                "source": "test",
                "read": False,
                "timestamp": datetime.now().isoformat(),
            }
        ]

    def snapshot(self):
        unread = sum(1 for x in self._items if not x.get("read"))
        return {"items": list(self._items), "unread": unread}

    def mark_read(self, target_id: int) -> bool:
        for item in self._items:
            if item["id"] == target_id:
                item["read"] = True
                return True
        return False

    def clear(self):
        self._items.clear()


class FakeBantzServer:
    """Fake BantzServer for testing without real LLM/brain dependencies."""

    def __init__(self):
        self._brain = FakeRuntime()
        self._brain_state = {}
        self._inbox = FakeInboxStore()
        self._running = True
        self.session_name = "test"

    def handle_command(self, command: str) -> dict:
        command = command.strip()

        if command.lower() == "__inbox__":
            snap = self._inbox.snapshot()
            return {"ok": True, "text": "OK", "inbox": snap["items"], "unread": snap["unread"]}

        if command.lower().startswith("__inbox_mark__"):
            parts = command.split()
            if len(parts) < 2:
                return {"ok": False, "text": "Eksik parametre"}
            target_id = int(parts[1])
            updated = self._inbox.mark_read(target_id)
            return {"ok": updated, "text": "OK" if updated else "Bulunamadı"}

        if command.lower() == "__inbox_clear__":
            self._inbox.clear()
            return {"ok": True, "text": "OK"}

        if command.lower() == "__status__":
            return {"ok": True, "text": "Server çalışıyor", "status": {"session": "test"}}

        # Brain path
        return {
            "ok": True,
            "text": f"Yanıt: {command}",
            "brain": True,
            "route": "smalltalk",
        }


@pytest.fixture()
def fake_server():
    """Create a fake BantzServer."""
    return FakeBantzServer()


@pytest.fixture()
def event_bus():
    """Create a fresh EventBus for testing."""
    from bantz.core.events import EventBus

    return EventBus(history_size=100)


@pytest.fixture()
def app(fake_server, event_bus):
    """Create a FastAPI test app."""
    from bantz.api.server import create_app
    from bantz.api.auth import reset_token_cache

    reset_token_cache()
    application = create_app(bantz_server=fake_server, event_bus=event_bus)
    return application


@pytest.fixture()
def client(app):
    """Create a test client (no auth)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def authed_client(app):
    """Create a test client with auth token set."""
    from bantz.api.auth import reset_token_cache

    reset_token_cache()
    os.environ["BANTZ_API_TOKEN"] = "test-secret-token-834"
    # Reset cache so token is picked up
    reset_token_cache()
    with TestClient(app) as c:
        yield c
    del os.environ["BANTZ_API_TOKEN"]
    reset_token_cache()


# ─────────────────────────────────────────────────────────────
# Health endpoint tests
# ─────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    """GET /api/v1/health tests."""

    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_contains_status(self, client):
        data = client.get("/api/v1/health").json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "down")

    def test_health_contains_version(self, client):
        data = client.get("/api/v1/health").json()
        assert "version" in data
        assert data["version"] == "0.3.0"

    def test_health_contains_uptime(self, client):
        data = client.get("/api/v1/health").json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_health_contains_components(self, client):
        data = client.get("/api/v1/health").json()
        assert "components" in data
        assert isinstance(data["components"], list)

    def test_health_no_auth_required(self, authed_client):
        """Health endpoint should work without auth token."""
        resp = authed_client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_brain_component_ok(self, client):
        data = client.get("/api/v1/health").json()
        brain_comp = next(
            (c for c in data["components"] if c["name"] == "brain"), None
        )
        assert brain_comp is not None
        assert brain_comp["status"] == "ok"


# ─────────────────────────────────────────────────────────────
# Chat endpoint tests
# ─────────────────────────────────────────────────────────────


class TestChatEndpoint:
    """POST /api/v1/chat tests."""

    def test_chat_returns_200(self, client):
        resp = client.post("/api/v1/chat", json={"message": "merhaba"})
        assert resp.status_code == 200

    def test_chat_returns_response(self, client):
        data = client.post("/api/v1/chat", json={"message": "merhaba"}).json()
        assert data["ok"] is True
        assert "response" in data
        assert len(data["response"]) > 0

    def test_chat_includes_route(self, client):
        data = client.post("/api/v1/chat", json={"message": "bugün hava nasıl"}).json()
        assert "route" in data

    def test_chat_includes_brain_flag(self, client):
        data = client.post("/api/v1/chat", json={"message": "test"}).json()
        assert "brain" in data
        assert data["brain"] is True

    def test_chat_includes_session(self, client):
        data = client.post(
            "/api/v1/chat", json={"message": "test", "session": "work"}
        ).json()
        assert data["session"] == "work"

    def test_chat_empty_message_rejected(self, client):
        resp = client.post("/api/v1/chat", json={"message": ""})
        assert resp.status_code == 422  # Validation error

    def test_chat_missing_message_rejected(self, client):
        resp = client.post("/api/v1/chat", json={})
        assert resp.status_code == 422

    def test_chat_too_long_message_rejected(self, client):
        resp = client.post("/api/v1/chat", json={"message": "x" * 5000})
        assert resp.status_code == 422

    def test_chat_default_session(self, client):
        data = client.post("/api/v1/chat", json={"message": "test"}).json()
        assert data["session"] == "default"

    def test_chat_includes_timestamp(self, client):
        data = client.post("/api/v1/chat", json={"message": "test"}).json()
        assert "timestamp" in data


# ─────────────────────────────────────────────────────────────
# Skills endpoint tests
# ─────────────────────────────────────────────────────────────


class TestSkillsEndpoint:
    """GET /api/v1/skills tests."""

    def test_skills_returns_200(self, client):
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200

    def test_skills_returns_list(self, client):
        data = client.get("/api/v1/skills").json()
        assert data["ok"] is True
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_skills_count_matches(self, client):
        data = client.get("/api/v1/skills").json()
        assert data["count"] == len(data["skills"])

    def test_skills_have_required_fields(self, client):
        data = client.get("/api/v1/skills").json()
        if data["skills"]:
            skill = data["skills"][0]
            assert "name" in skill
            assert "description" in skill
            assert "source" in skill


# ─────────────────────────────────────────────────────────────
# Authentication tests
# ─────────────────────────────────────────────────────────────


class TestAuthentication:
    """Bearer token authentication tests."""

    def test_no_auth_when_token_not_set(self, client):
        """When BANTZ_API_TOKEN is not set, all requests should pass."""
        resp = client.post("/api/v1/chat", json={"message": "test"})
        assert resp.status_code == 200

    def test_auth_required_when_token_set(self, authed_client):
        """When token is set, requests without auth should fail."""
        resp = authed_client.post("/api/v1/chat", json={"message": "test"})
        assert resp.status_code == 401

    def test_valid_token_accepted(self, authed_client):
        """Valid Bearer token should be accepted."""
        resp = authed_client.post(
            "/api/v1/chat",
            json={"message": "test"},
            headers={"Authorization": "Bearer test-secret-token-834"},
        )
        assert resp.status_code == 200

    def test_invalid_token_rejected(self, authed_client):
        """Invalid Bearer token should be rejected."""
        resp = authed_client.post(
            "/api/v1/chat",
            json={"message": "test"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_health_no_auth_even_when_token_set(self, authed_client):
        """Health endpoint should always work."""
        resp = authed_client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_auth_failure_returns_json(self, authed_client):
        """Auth failure should return JSON error."""
        resp = authed_client.post("/api/v1/chat", json={"message": "test"})
        assert resp.status_code == 401
        data = resp.json()
        assert "detail" in data

    def test_skills_requires_auth_when_set(self, authed_client):
        """Skills endpoint should require auth when token is set."""
        resp = authed_client.get("/api/v1/skills")
        assert resp.status_code == 401

    def test_skills_with_valid_token(self, authed_client):
        resp = authed_client.get(
            "/api/v1/skills",
            headers={"Authorization": "Bearer test-secret-token-834"},
        )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# Inbox endpoint tests
# ─────────────────────────────────────────────────────────────


class TestInboxEndpoint:
    """GET /api/v1/inbox and POST /api/v1/inbox/{id}/read tests."""

    def test_inbox_returns_200(self, client):
        resp = client.get("/api/v1/inbox")
        assert resp.status_code == 200

    def test_inbox_has_items(self, client):
        data = client.get("/api/v1/inbox").json()
        assert data["ok"] is True
        assert "items" in data
        assert "unread" in data

    def test_inbox_has_unread_count(self, client):
        data = client.get("/api/v1/inbox").json()
        assert data["unread"] == 1  # FakeInboxStore has 1 unread item

    def test_mark_read_existing_item(self, client):
        resp = client.post("/api/v1/inbox/1/read")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_mark_read_nonexistent_item(self, client):
        resp = client.post("/api/v1/inbox/999/read")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_mark_read_then_inbox_updated(self, client):
        client.post("/api/v1/inbox/1/read")
        data = client.get("/api/v1/inbox").json()
        assert data["unread"] == 0


# ─────────────────────────────────────────────────────────────
# WebSocket tests
# ─────────────────────────────────────────────────────────────


class TestWebSocket:
    """WS /ws/chat tests."""

    def test_ws_connect(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_ws_chat_message(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "chat", "message": "merhaba"})
            data = ws.receive_json()
            assert data["type"] == "chat"
            assert data["data"]["ok"] is True
            assert "response" in data["data"]

    def test_ws_invalid_json(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_text("not json")
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["data"]["code"] == "invalid_json"

    def test_ws_empty_message(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "chat", "message": ""})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["data"]["code"] == "empty_message"

    def test_ws_unknown_type(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "unknown_xyz"})
            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["data"]["code"] == "unknown_type"

    def test_ws_auth_required_when_token_set(self, authed_client):
        """WebSocket should reject unauthenticated connections when token is set."""
        # WebSocket auth via query param
        with pytest.raises(Exception):
            with authed_client.websocket_connect("/ws/chat") as ws:
                ws.send_json({"type": "ping"})

    def test_ws_auth_with_valid_token(self, authed_client):
        """WebSocket with valid token query param should connect."""
        with authed_client.websocket_connect(
            "/ws/chat?token=test-secret-token-834"
        ) as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_ws_chat_response_has_route(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "chat", "message": "test"})
            data = ws.receive_json()
            assert "route" in data["data"]

    def test_ws_response_has_timestamp(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert "timestamp" in data


# ─────────────────────────────────────────────────────────────
# SSE notification tests
# ─────────────────────────────────────────────────────────────


class TestSSENotifications:
    """GET /api/v1/notifications SSE tests.

    Note: Full SSE streaming tests require an async test runner.
    Here we verify the endpoint is registered in the OpenAPI schema.
    """

    def test_sse_endpoint_in_openapi(self, client):
        """SSE endpoint should be registered in OpenAPI."""
        schema = client.get("/openapi.json").json()
        assert "/api/v1/notifications" in schema["paths"]

    def test_sse_inbox_endpoint_works(self, client):
        """Inbox endpoint (non-streaming) should work."""
        resp = client.get("/api/v1/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "unread" in data


# ─────────────────────────────────────────────────────────────
# CORS tests
# ─────────────────────────────────────────────────────────────


class TestCORS:
    """CORS middleware tests."""

    def test_cors_allows_localhost(self, client):
        resp = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS preflight should not be 404 or 500
        assert resp.status_code in (200, 204, 405)


# ─────────────────────────────────────────────────────────────
# OpenAPI / docs tests
# ─────────────────────────────────────────────────────────────


class TestDocs:
    """OpenAPI documentation tests."""

    def test_openapi_schema_available(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "openapi" in schema
        assert "paths" in schema

    def test_docs_page_available(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_page_available(self, client):
        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_openapi_has_chat_endpoint(self, client):
        schema = client.get("/openapi.json").json()
        assert "/api/v1/chat" in schema["paths"]

    def test_openapi_has_health_endpoint(self, client):
        schema = client.get("/openapi.json").json()
        assert "/api/v1/health" in schema["paths"]

    def test_openapi_has_skills_endpoint(self, client):
        schema = client.get("/openapi.json").json()
        assert "/api/v1/skills" in schema["paths"]


# ─────────────────────────────────────────────────────────────
# Error handling tests
# ─────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Error handling and edge case tests."""

    def test_404_for_unknown_endpoint(self, client):
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code == 404

    def test_method_not_allowed(self, client):
        resp = client.get("/api/v1/chat")  # POST endpoint, not GET
        assert resp.status_code == 405

    def test_invalid_json_body(self, client):
        resp = client.post(
            "/api/v1/chat",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────
# Models tests
# ─────────────────────────────────────────────────────────────


class TestModels:
    """Pydantic model validation tests."""

    def test_chat_request_validation(self):
        from bantz.api.models import ChatRequest

        req = ChatRequest(message="merhaba")
        assert req.message == "merhaba"
        assert req.session == "default"
        assert req.stream is False

    def test_chat_request_min_length(self):
        from bantz.api.models import ChatRequest

        with pytest.raises(Exception):
            ChatRequest(message="")

    def test_chat_request_max_length(self):
        from bantz.api.models import ChatRequest

        with pytest.raises(Exception):
            ChatRequest(message="x" * 5000)

    def test_chat_response_serialization(self):
        from bantz.api.models import ChatResponse

        resp = ChatResponse(ok=True, response="test", route="calendar", brain=True)
        data = resp.model_dump()
        assert data["ok"] is True
        assert data["response"] == "test"
        assert data["route"] == "calendar"

    def test_health_response_serialization(self):
        from bantz.api.models import HealthResponse

        resp = HealthResponse(status="ok", uptime_seconds=42.0)
        data = resp.model_dump()
        assert data["status"] == "ok"
        assert data["uptime_seconds"] == 42.0

    def test_skills_response_serialization(self):
        from bantz.api.models import SkillsResponse, SkillInfo

        resp = SkillsResponse(
            count=2,
            skills=[
                SkillInfo(name="calendar_list", description="List events"),
                SkillInfo(name="gmail_read", description="Read emails"),
            ],
        )
        data = resp.model_dump()
        assert data["count"] == 2
        assert len(data["skills"]) == 2

    def test_error_response(self):
        from bantz.api.models import ErrorResponse

        resp = ErrorResponse(error="Something broke", code="test_error")
        data = resp.model_dump()
        assert data["ok"] is False
        assert data["code"] == "test_error"

    def test_ws_message_defaults(self):
        from bantz.api.models import WSMessage

        msg = WSMessage()
        assert msg.type == "chat"
        assert msg.session == "default"


# ─────────────────────────────────────────────────────────────
# Auth module tests
# ─────────────────────────────────────────────────────────────


class TestAuthModule:
    """Direct auth module tests."""

    def test_reset_token_cache(self):
        from bantz.api.auth import reset_token_cache, _resolve_token

        reset_token_cache()
        os.environ["BANTZ_API_TOKEN"] = "test-123"
        reset_token_cache()
        assert _resolve_token() == "test-123"
        del os.environ["BANTZ_API_TOKEN"]
        reset_token_cache()

    def test_is_auth_enabled_false_by_default(self):
        from bantz.api.auth import reset_token_cache, is_auth_enabled

        reset_token_cache()
        # Make sure env var is not set
        os.environ.pop("BANTZ_API_TOKEN", None)
        reset_token_cache()
        assert is_auth_enabled() is False

    def test_is_auth_enabled_true_when_set(self):
        from bantz.api.auth import reset_token_cache, is_auth_enabled

        reset_token_cache()
        os.environ["BANTZ_API_TOKEN"] = "secret"
        reset_token_cache()
        assert is_auth_enabled() is True
        del os.environ["BANTZ_API_TOKEN"]
        reset_token_cache()


# ─────────────────────────────────────────────────────────────
# Integration test: create_app factory
# ─────────────────────────────────────────────────────────────


class TestAppFactory:
    """Test create_app factory function."""

    def test_create_app_returns_fastapi(self, fake_server, event_bus):
        from bantz.api.server import create_app

        app = create_app(bantz_server=fake_server, event_bus=event_bus)
        assert app is not None
        assert hasattr(app, "state")

    def test_create_app_state_initialized(self, fake_server, event_bus):
        from bantz.api.server import create_app

        app = create_app(bantz_server=fake_server, event_bus=event_bus)
        assert app.state.bantz_server is fake_server
        assert app.state.event_bus is event_bus

    def test_create_app_has_routes(self, fake_server, event_bus):
        from bantz.api.server import create_app

        app = create_app(bantz_server=fake_server, event_bus=event_bus)
        routes = [r.path for r in app.routes]
        assert "/api/v1/chat" in routes
        assert "/api/v1/health" in routes
        assert "/api/v1/skills" in routes
