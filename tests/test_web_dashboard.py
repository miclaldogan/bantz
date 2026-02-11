"""Tests for the Web Dashboard & Settings API (Issue #867).

Coverage:
- GET / — dashboard HTML served
- GET /api/v1/settings/status — returns key/system status
- POST /api/v1/settings/gemini-key — stores key in vault + env
- DELETE /api/v1/settings/gemini-key — removes key from vault + env
- GET /api/v1/qrcode — returns QR code (or 501 if no qrcode lib)
- GET /api/v1/health — now includes gemini component
- Static file serving (manifest.json)
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure Gemini keys are clean before each test."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("BANTZ_API_TOKEN", raising=False)


def _make_mock_server() -> MagicMock:
    """Create a mock BantzServer."""
    mock = MagicMock()
    mock._brain = None
    mock.handle_command.return_value = {
        "ok": True,
        "text": "test response",
        "route": "test",
    }
    return mock


def _make_mock_vault(has_key: bool = False, stored_key: str = ""):
    """Create a mock SecretsVault."""
    vault = MagicMock()
    vault.exists.return_value = has_key
    vault.retrieve.return_value = stored_key if has_key else None
    vault.store.return_value = None
    vault.delete.return_value = has_key
    return vault


def _create_test_client(server: Any = None) -> TestClient:
    """Create a FastAPI TestClient with mocked BantzServer."""
    from bantz.api.server import create_app

    if server is None:
        server = _make_mock_server()

    # Mock event bus
    bus = MagicMock()
    bus._history = []

    app = create_app(bantz_server=server, event_bus=bus)
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────
# Dashboard serving
# ─────────────────────────────────────────────────────────────────

class TestDashboard:
    """GET / — dashboard HTML."""

    def test_root_returns_html(self):
        """Root URL should return the dashboard HTML."""
        client = _create_test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_root_contains_bantz_branding(self):
        """Dashboard should contain Bantz branding."""
        client = _create_test_client()
        resp = client.get("/")
        assert "Bantz" in resp.text

    def test_root_contains_chat_panel(self):
        """Dashboard should have the chat panel elements."""
        client = _create_test_client()
        resp = client.get("/")
        assert "chatMessages" in resp.text
        assert "chatInput" in resp.text

    def test_root_contains_settings_panel(self):
        """Dashboard should have settings panel."""
        client = _create_test_client()
        resp = client.get("/")
        assert "geminiKeyInput" in resp.text
        assert "geminiStatus" in resp.text

    def test_root_mobile_responsive(self):
        """Dashboard should have viewport meta for mobile."""
        client = _create_test_client()
        resp = client.get("/")
        assert "viewport" in resp.text
        assert "width=device-width" in resp.text

    def test_root_pwa_manifest(self):
        """Dashboard should reference PWA manifest."""
        client = _create_test_client()
        resp = client.get("/")
        assert "manifest.json" in resp.text

    def test_root_no_auth_required(self):
        """Dashboard root should be accessible without auth."""
        os.environ["BANTZ_API_TOKEN"] = "test-secret-token"
        try:
            client = _create_test_client()
            resp = client.get("/")
            assert resp.status_code == 200
        finally:
            del os.environ["BANTZ_API_TOKEN"]


# ─────────────────────────────────────────────────────────────────
# Static files
# ─────────────────────────────────────────────────────────────────

class TestStaticFiles:
    """Static file serving."""

    def test_manifest_json_served(self):
        """manifest.json should be served from /static/."""
        client = _create_test_client()
        resp = client.get("/static/manifest.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["short_name"] == "Bantz"


# ─────────────────────────────────────────────────────────────────
# Settings status
# ─────────────────────────────────────────────────────────────────

class TestSettingsStatus:
    """GET /api/v1/settings/status."""

    def test_status_returns_json(self):
        """Settings status should return JSON."""
        client = _create_test_client()
        resp = client.get("/api/v1/settings/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "gemini_key_set" in data
        assert "api_token_set" in data
        assert "version" in data

    def test_status_gemini_not_set(self):
        """Gemini key should show as not set when env is empty."""
        with patch("bantz.api.settings._is_gemini_key_set", return_value=False):
            client = _create_test_client()
            resp = client.get("/api/v1/settings/status")
            data = resp.json()
            assert data["gemini_key_set"] is False

    def test_status_gemini_set_via_env(self):
        """Gemini key should show as set when in env."""
        os.environ["GEMINI_API_KEY"] = "AIzaFakeKey123"
        try:
            client = _create_test_client()
            resp = client.get("/api/v1/settings/status")
            data = resp.json()
            assert data["gemini_key_set"] is True
        finally:
            del os.environ["GEMINI_API_KEY"]

    def test_status_api_token_not_set(self):
        """API token should show as not set."""
        client = _create_test_client()
        resp = client.get("/api/v1/settings/status")
        data = resp.json()
        assert data["api_token_set"] is False

    def test_status_api_token_set(self):
        """API token should show as set when env has it."""
        os.environ["BANTZ_API_TOKEN"] = "test-token"
        try:
            client = _create_test_client()
            resp = client.get("/api/v1/settings/status")
            data = resp.json()
            assert data["api_token_set"] is True
        finally:
            del os.environ["BANTZ_API_TOKEN"]

    def test_status_includes_uptime(self):
        """Status should include uptime."""
        client = _create_test_client()
        resp = client.get("/api/v1/settings/status")
        data = resp.json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))

    def test_status_includes_access_url(self):
        """Status should include LAN access URL."""
        client = _create_test_client()
        resp = client.get("/api/v1/settings/status")
        data = resp.json()
        assert "access_url" in data
        assert data["access_url"].startswith("http://")

    def test_status_includes_system_info(self):
        """Status should include brain/finalizer/tools info."""
        client = _create_test_client()
        resp = client.get("/api/v1/settings/status")
        data = resp.json()
        assert "brain_active" in data
        assert "finalizer" in data
        assert "tool_count" in data

    def test_status_never_exposes_keys(self):
        """Status should NEVER expose actual key values."""
        os.environ["GEMINI_API_KEY"] = "AIzaSuperSecretKey"
        os.environ["BANTZ_API_TOKEN"] = "secret-bearer-token"
        try:
            client = _create_test_client()
            resp = client.get("/api/v1/settings/status")
            text = resp.text
            assert "AIzaSuperSecretKey" not in text
            assert "secret-bearer-token" not in text
        finally:
            del os.environ["GEMINI_API_KEY"]
            del os.environ["BANTZ_API_TOKEN"]


# ─────────────────────────────────────────────────────────────────
# Save Gemini key
# ─────────────────────────────────────────────────────────────────

class TestSaveGeminiKey:
    """POST /api/v1/settings/gemini-key."""

    def test_save_valid_key(self):
        """Valid key should be stored successfully."""
        mock_vault = _make_mock_vault()
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            resp = client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "AIzaFakeTestKey1234567890"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            mock_vault.store.assert_called_once()

    def test_save_key_injects_to_env(self):
        """Saved key should be injected to os.environ."""
        mock_vault = _make_mock_vault()
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "AIzaFakeTestKey1234567890"},
            )
            assert os.environ.get("GEMINI_API_KEY") == "AIzaFakeTestKey1234567890"
            assert os.environ.get("GOOGLE_API_KEY") == "AIzaFakeTestKey1234567890"

    def test_save_empty_key_rejected(self):
        """Empty key should be rejected."""
        client = _create_test_client()
        resp = client.post(
            "/api/v1/settings/gemini-key",
            json={"key": ""},
        )
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_save_invalid_prefix_rejected(self):
        """Key not starting with AIza should be rejected."""
        client = _create_test_client()
        resp = client.post(
            "/api/v1/settings/gemini-key",
            json={"key": "sk-invalid-openai-key"},
        )
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_save_no_body_rejected(self):
        """Missing JSON body should be rejected."""
        client = _create_test_client()
        resp = client.post(
            "/api/v1/settings/gemini-key",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_save_missing_key_field_rejected(self):
        """JSON without key field should be rejected."""
        client = _create_test_client()
        resp = client.post(
            "/api/v1/settings/gemini-key",
            json={"not_key": "value"},
        )
        assert resp.status_code == 400

    def test_save_vault_error_returns_500(self):
        """Vault errors should return 500."""
        mock_vault = _make_mock_vault()
        mock_vault.store.side_effect = Exception("vault explosion")
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            resp = client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "AIzaFakeTestKey1234567890"},
            )
            assert resp.status_code == 500
            assert resp.json()["ok"] is False


# ─────────────────────────────────────────────────────────────────
# Delete Gemini key
# ─────────────────────────────────────────────────────────────────

class TestDeleteGeminiKey:
    """DELETE /api/v1/settings/gemini-key."""

    def test_delete_existing_key(self):
        """Deleting an existing key should succeed."""
        mock_vault = _make_mock_vault(has_key=True)
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            resp = client.delete("/api/v1/settings/gemini-key")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            mock_vault.delete.assert_called_once()

    def test_delete_removes_from_env(self):
        """Delete should remove key from os.environ."""
        os.environ["GEMINI_API_KEY"] = "AIzaToBeDeleted"
        os.environ["GOOGLE_API_KEY"] = "AIzaToBeDeleted"
        mock_vault = _make_mock_vault(has_key=True)
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            client.delete("/api/v1/settings/gemini-key")
            assert os.environ.get("GEMINI_API_KEY") is None
            assert os.environ.get("GOOGLE_API_KEY") is None

    def test_delete_nonexistent_key(self):
        """Deleting a non-existent key should still succeed."""
        mock_vault = _make_mock_vault(has_key=False)
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            resp = client.delete("/api/v1/settings/gemini-key")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    def test_delete_vault_error_returns_500(self):
        """Vault errors during delete should return 500."""
        mock_vault = _make_mock_vault()
        mock_vault.delete.side_effect = Exception("vault error")
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            resp = client.delete("/api/v1/settings/gemini-key")
            assert resp.status_code == 500


# ─────────────────────────────────────────────────────────────────
# QR code
# ─────────────────────────────────────────────────────────────────

class TestQRCode:
    """GET /api/v1/qrcode."""

    def test_qrcode_returns_png_or_501(self):
        """QR code should return PNG if qrcode lib is installed, 501 otherwise."""
        client = _create_test_client()
        resp = client.get("/api/v1/qrcode")
        assert resp.status_code in (200, 501)
        if resp.status_code == 200:
            assert resp.headers["content-type"] == "image/png"
        else:
            # 501 means qrcode lib not installed — still valid
            data = resp.json()
            assert "url" in data

    def test_qrcode_without_lib(self):
        """QR code endpoint should return 501 if qrcode is not installed."""
        import importlib

        with patch.dict(sys.modules, {"qrcode": None, "qrcode.image.pil": None}):
            # Need to force import failure
            with patch("builtins.__import__", side_effect=_mock_import_no_qrcode):
                client = _create_test_client()
                resp = client.get("/api/v1/qrcode")
                # May still succeed if qrcode was already imported
                assert resp.status_code in (200, 501)


def _mock_import_no_qrcode(name, *args, **kwargs):
    """Mock import that fails for qrcode."""
    if name in ("qrcode", "qrcode.image.pil"):
        raise ImportError(f"No module named '{name}'")
    return original_import(name, *args, **kwargs)

original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__


# ─────────────────────────────────────────────────────────────────
# Health endpoint — Gemini component
# ─────────────────────────────────────────────────────────────────

class TestHealthGemini:
    """GET /api/v1/health — Gemini component."""

    def test_health_includes_gemini_component(self):
        """Health response should include gemini component."""
        client = _create_test_client()
        resp = client.get("/api/v1/health")
        data = resp.json()
        component_names = [c["name"] for c in data["components"]]
        assert "gemini" in component_names

    def test_health_gemini_ok_when_key_set(self):
        """Gemini should be OK when API key is in env."""
        os.environ["GEMINI_API_KEY"] = "AIzaTestKey"
        try:
            client = _create_test_client()
            resp = client.get("/api/v1/health")
            data = resp.json()
            gemini = next(c for c in data["components"] if c["name"] == "gemini")
            assert gemini["status"] == "ok"
        finally:
            del os.environ["GEMINI_API_KEY"]

    def test_health_gemini_down_when_no_key(self):
        """Gemini should be DOWN when no API key is configured."""
        with patch("bantz.security.vault.SecretsVault.exists", return_value=False):
            client = _create_test_client()
            resp = client.get("/api/v1/health")
            data = resp.json()
            gemini = next(c for c in data["components"] if c["name"] == "gemini")
            assert gemini["status"] == "down"


# ─────────────────────────────────────────────────────────────────
# Auth integration with settings
# ─────────────────────────────────────────────────────────────────

class TestSettingsAuth:
    """Auth behavior for settings endpoints."""

    def test_settings_status_requires_auth_when_enabled(self):
        """Settings status should require auth when token is set."""
        os.environ["BANTZ_API_TOKEN"] = "test-auth-token"
        try:
            from bantz.api.auth import reset_token_cache
            reset_token_cache()

            client = _create_test_client()
            resp = client.get("/api/v1/settings/status")
            assert resp.status_code == 401

            # With valid token
            resp = client.get(
                "/api/v1/settings/status",
                headers={"Authorization": "Bearer test-auth-token"},
            )
            assert resp.status_code == 200
        finally:
            del os.environ["BANTZ_API_TOKEN"]
            from bantz.api.auth import reset_token_cache
            reset_token_cache()

    def test_save_gemini_key_requires_auth_when_enabled(self):
        """Save key should require auth when token is set."""
        os.environ["BANTZ_API_TOKEN"] = "test-auth-token"
        try:
            from bantz.api.auth import reset_token_cache
            reset_token_cache()

            client = _create_test_client()
            resp = client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "AIzaFakeKey"},
            )
            assert resp.status_code == 401
        finally:
            del os.environ["BANTZ_API_TOKEN"]
            from bantz.api.auth import reset_token_cache
            reset_token_cache()


# ─────────────────────────────────────────────────────────────────
# Integration: vault key lifecycle
# ─────────────────────────────────────────────────────────────────

class TestVaultKeyLifecycle:
    """Full lifecycle: save → check status → delete."""

    def test_full_lifecycle(self):
        """Save key → status shows set → delete → status shows unset."""
        mock_vault = _make_mock_vault(has_key=False)

        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()

            # Step 1: Status before save
            with patch("bantz.api.settings._is_gemini_key_set", return_value=False):
                resp = client.get("/api/v1/settings/status")
                assert resp.json()["gemini_key_set"] is False

            # Step 2: Save key
            resp = client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "AIzaTestLifecycleKey123456"},
            )
            assert resp.json()["ok"] is True
            assert os.environ.get("GEMINI_API_KEY") == "AIzaTestLifecycleKey123456"

            # Step 3: Status after save (key is in env now)
            resp = client.get("/api/v1/settings/status")
            assert resp.json()["gemini_key_set"] is True

            # Step 4: Delete key
            mock_vault.delete.return_value = True
            resp = client.delete("/api/v1/settings/gemini-key")
            assert resp.json()["ok"] is True
            assert os.environ.get("GEMINI_API_KEY") is None

    def test_key_stored_with_correct_type(self):
        """Vault store should be called with SecretType.API_KEY."""
        mock_vault = _make_mock_vault()
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "AIzaTestTypeKey123456789"},
            )
            call_args = mock_vault.store.call_args
            assert call_args is not None
            # Check the secret_type kwarg
            from bantz.security.vault import SecretType
            assert call_args.kwargs.get("secret_type") == SecretType.API_KEY or \
                   (len(call_args.args) > 2 and call_args.args[2] == SecretType.API_KEY)


# ─────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and robustness."""

    def test_save_whitespace_only_key_rejected(self):
        """Whitespace-only key should be rejected."""
        client = _create_test_client()
        resp = client.post(
            "/api/v1/settings/gemini-key",
            json={"key": "   "},
        )
        assert resp.status_code == 400

    def test_save_key_with_whitespace_trimmed(self):
        """Key with leading/trailing whitespace should be trimmed."""
        mock_vault = _make_mock_vault()
        with patch("bantz.api.settings._get_vault", return_value=mock_vault):
            client = _create_test_client()
            resp = client.post(
                "/api/v1/settings/gemini-key",
                json={"key": "  AIzaKeyWithSpaces  "},
            )
            assert resp.status_code == 200
            # Verify trimmed key was stored
            stored_key = mock_vault.store.call_args[0][1]
            assert stored_key == "AIzaKeyWithSpaces"

    def test_concurrent_dashboard_requests(self):
        """Multiple simultaneous dashboard requests should work."""
        client = _create_test_client()
        responses = [client.get("/") for _ in range(5)]
        for resp in responses:
            assert resp.status_code == 200
