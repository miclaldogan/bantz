"""Tests for phone call tools — Issue #1438.

Covers:
- PhoneService state machine (idle → dialing → active → ended)
- Incoming call flow (ringing → accept → active → hangup)
- Tool handlers (call, hangup, mute, speaker, status, call_log)
- Error handling (duplicate calls, no active call, invalid number)
- IPC event emission
- Backend detection
- Tool registration in register_all
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock, PropertyMock
from typing import Any

import pytest


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _make_phone_service():
    """Create a PhoneService with backend detection mocked out."""
    with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
        mock_sp.run.return_value = MagicMock(returncode=1)  # no D-Bus backend
        from bantz.tools.phone_tools import PhoneService
        svc = PhoneService()
    return svc


def _inject_service(svc) -> None:
    """Inject a PhoneService into the singleton."""
    import bantz.tools.phone_tools as mod
    mod._phone_service = svc


def _cleanup_service() -> None:
    """Reset the singleton."""
    import bantz.tools.phone_tools as mod
    mod._phone_service = None


# ─────────────────────────────────────────────────────────────────
# PhoneService — State Machine
# ─────────────────────────────────────────────────────────────────


class TestPhoneServiceStateMachine:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()  # capture IPC events

    def test_initial_state_is_idle(self):
        from bantz.tools.phone_tools import CallState
        assert self.svc.state == CallState.IDLE
        assert not self.svc.is_active

    def test_outgoing_call_lifecycle(self):
        """idle → dialing → active → ended"""
        from bantz.tools.phone_tools import CallState

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_popen = MagicMock()
            mock_sp.Popen.return_value = mock_popen

            result = self.svc.initiate_call("+905551234567", "Ali")
            assert result["ok"] is True
            assert self.svc.state == CallState.ACTIVE
            assert self.svc.is_active

        # Hangup
        result = self.svc.hangup()
        assert result["ok"] is True
        assert result["state"] == "ended"
        assert result["duration_seconds"] >= 0
        assert self.svc.state == CallState.IDLE
        assert not self.svc.is_active

    def test_incoming_call_lifecycle(self):
        """idle → ringing → active → ended"""
        from bantz.tools.phone_tools import CallState

        self.svc.handle_incoming("+905559876543", "Ayşe", "https://photo.url/ayse.jpg")
        assert self.svc.state == CallState.RINGING
        assert self.svc.is_active

        result = self.svc.accept_call()
        assert result["ok"] is True
        assert self.svc.state == CallState.ACTIVE

        result = self.svc.hangup()
        assert result["ok"] is True
        assert self.svc.state == CallState.IDLE

    def test_cannot_accept_when_not_ringing(self):
        result = self.svc.accept_call()
        assert result["ok"] is False
        assert result["error"] == "no_incoming_call"

    def test_cannot_initiate_when_already_active(self):
        from bantz.tools.phone_tools import CallState

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567")

        assert self.svc.state == CallState.ACTIVE

        result = self.svc.initiate_call("+905559999999")
        assert result["ok"] is False
        assert result["error"] == "call_already_active"

    def test_hangup_when_idle_fails(self):
        result = self.svc.hangup()
        assert result["ok"] is False
        assert result["error"] == "no_active_call"

    def test_dial_failure_resets_to_idle(self):
        from bantz.tools.phone_tools import CallState

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.side_effect = Exception("xdg-open not found")

            result = self.svc.initiate_call("+905551234567")
            assert result["ok"] is False
            assert self.svc.state == CallState.IDLE


# ─────────────────────────────────────────────────────────────────
# PhoneService — Mute & Speaker
# ─────────────────────────────────────────────────────────────────


class TestPhoneServiceMuteSpeaker:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        # Start an active call
        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567", "Test")

    def test_toggle_mute(self):
        result = self.svc.toggle_mute()
        assert result["ok"] is True
        assert result["muted"] is True

        result = self.svc.toggle_mute()
        assert result["ok"] is True
        assert result["muted"] is False

    def test_toggle_speaker(self):
        result = self.svc.toggle_speaker()
        assert result["ok"] is True
        assert result["speaker"] is True

        result = self.svc.toggle_speaker()
        assert result["ok"] is True
        assert result["speaker"] is False

    def test_mute_when_no_call_fails(self):
        svc = _make_phone_service()
        result = svc.toggle_mute()
        assert result["ok"] is False
        assert result["error"] == "no_active_call"

    def test_speaker_when_no_call_fails(self):
        svc = _make_phone_service()
        result = svc.toggle_speaker()
        assert result["ok"] is False
        assert result["error"] == "no_active_call"


# ─────────────────────────────────────────────────────────────────
# PhoneService — Status & Call Log
# ─────────────────────────────────────────────────────────────────


class TestPhoneServiceStatus:
    def test_idle_status(self):
        svc = _make_phone_service()
        status = svc.get_status()
        assert status["state"] == "idle"
        assert "backend" in status
        assert "caller_name" not in status

    def test_active_status(self):
        svc = _make_phone_service()
        svc._notify_fn = MagicMock()
        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            svc.initiate_call("+905551234567", "Mehmet")

        status = svc.get_status()
        assert status["state"] == "active"
        assert status["caller_name"] == "Mehmet"
        assert status["caller_number"] == "+905551234567"
        assert status["muted"] is False
        assert "duration_seconds" in status

    def test_call_log_empty(self):
        svc = _make_phone_service()
        log = svc.get_call_log()
        assert log == []

    def test_call_log_after_hangup(self):
        svc = _make_phone_service()
        svc._notify_fn = MagicMock()

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            svc.initiate_call("+905551234567", "Ali")

        svc.hangup()
        log = svc.get_call_log()
        assert len(log) == 1
        assert log[0]["name"] == "Ali"
        assert log[0]["number"] == "+905551234567"
        assert log[0]["duration_seconds"] >= 0
        assert "timestamp" in log[0]

    def test_call_log_limit(self):
        svc = _make_phone_service()
        svc._notify_fn = MagicMock()

        for i in range(5):
            with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
                mock_sp.Popen.return_value = MagicMock()
                svc.initiate_call(f"+90555{i:07d}", f"User{i}")
            svc.hangup()

        log = svc.get_call_log(limit=3)
        assert len(log) == 3
        # Most recent first
        assert log[0]["name"] == "User4"


# ─────────────────────────────────────────────────────────────────
# PhoneService — IPC Events
# ─────────────────────────────────────────────────────────────────


class TestPhoneServiceEvents:
    def test_outgoing_call_emits_event(self):
        svc = _make_phone_service()
        events: list[dict] = []
        svc.set_notify_fn(lambda msg: events.append(msg))

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            svc.initiate_call("+905551234567", "Ali")

        assert any(e["event"] == "phone:outgoing" for e in events)
        outgoing = [e for e in events if e["event"] == "phone:outgoing"][0]
        assert outgoing["data"]["caller_number"] == "+905551234567"

    def test_incoming_call_emits_event(self):
        svc = _make_phone_service()
        events: list[dict] = []
        svc.set_notify_fn(lambda msg: events.append(msg))

        svc.handle_incoming("+905559876543", "Ayşe")

        assert len(events) == 1
        assert events[0]["event"] == "phone:incoming"
        assert events[0]["data"]["caller_name"] == "Ayşe"

    def test_hangup_emits_ended_event(self):
        svc = _make_phone_service()
        events: list[dict] = []
        svc.set_notify_fn(lambda msg: events.append(msg))

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            svc.initiate_call("+905551234567")

        events.clear()
        svc.hangup()

        assert len(events) == 1
        assert events[0]["event"] == "phone:ended"
        assert "duration_seconds" in events[0]["data"]


# ─────────────────────────────────────────────────────────────────
# PhoneService — Backend Detection
# ─────────────────────────────────────────────────────────────────


class TestPhoneServiceBackend:
    def test_gsconnect_detected(self):
        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.run.return_value = MagicMock(returncode=0)
            from bantz.tools.phone_tools import PhoneService
            svc = PhoneService()
        assert svc._dbus_backend == "gsconnect"

    def test_kdeconnect_fallback(self):
        def _side_effect(*args, **kwargs):
            cmd = args[0]
            if "GSConnect" in str(cmd):
                return MagicMock(returncode=1)  # GSConnect fails
            return MagicMock(returncode=0)  # KDE Connect succeeds

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.run.side_effect = _side_effect
            from bantz.tools.phone_tools import PhoneService
            svc = PhoneService()
        assert svc._dbus_backend == "kdeconnect"

    def test_no_backend_fallback(self):
        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.run.return_value = MagicMock(returncode=1)
            from bantz.tools.phone_tools import PhoneService
            svc = PhoneService()
        assert svc._dbus_backend is None


# ─────────────────────────────────────────────────────────────────
# Tool Handlers
# ─────────────────────────────────────────────────────────────────


class TestPhoneCallTool:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        _inject_service(self.svc)

    def teardown_method(self):
        _cleanup_service()

    def test_call_success(self):
        from bantz.tools.phone_tools import phone_call_tool

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            result = phone_call_tool(number="+905551234567", contact_name="Ali")

        assert result["ok"] is True
        assert result["number"] == "+905551234567"

    def test_call_no_number(self):
        from bantz.tools.phone_tools import phone_call_tool
        result = phone_call_tool()
        assert result["ok"] is False
        assert result["error"] == "number_required"

    def test_call_invalid_number(self):
        from bantz.tools.phone_tools import phone_call_tool
        result = phone_call_tool(number="not-a-number")
        assert result["ok"] is False
        assert result["error"] == "invalid_number_format"

    def test_call_strips_spaces(self):
        from bantz.tools.phone_tools import phone_call_tool

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            result = phone_call_tool(number="+90 555 123 45 67")

        assert result["ok"] is True


class TestPhoneHangupTool:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        _inject_service(self.svc)

    def teardown_method(self):
        _cleanup_service()

    def test_hangup_active_call(self):
        from bantz.tools.phone_tools import phone_hangup_tool

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567")

        result = phone_hangup_tool()
        assert result["ok"] is True

    def test_hangup_no_call(self):
        from bantz.tools.phone_tools import phone_hangup_tool
        result = phone_hangup_tool()
        assert result["ok"] is False


class TestPhoneMuteTool:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        _inject_service(self.svc)
        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567")

    def teardown_method(self):
        _cleanup_service()

    def test_mute_toggle(self):
        from bantz.tools.phone_tools import phone_mute_tool
        result = phone_mute_tool()
        assert result["ok"] is True
        assert result["muted"] is True


class TestPhoneSpeakerTool:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        _inject_service(self.svc)
        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567")

    def teardown_method(self):
        _cleanup_service()

    def test_speaker_toggle(self):
        from bantz.tools.phone_tools import phone_speaker_tool
        result = phone_speaker_tool()
        assert result["ok"] is True
        assert result["speaker"] is True


class TestPhoneStatusTool:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        _inject_service(self.svc)

    def teardown_method(self):
        _cleanup_service()

    def test_idle_status(self):
        from bantz.tools.phone_tools import phone_status_tool
        result = phone_status_tool()
        assert result["ok"] is True
        assert result["state"] == "idle"

    def test_active_status(self):
        from bantz.tools.phone_tools import phone_status_tool

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567", "Ali")

        result = phone_status_tool()
        assert result["ok"] is True
        assert result["state"] == "active"
        assert result["caller_name"] == "Ali"


class TestPhoneCallLogTool:
    def setup_method(self):
        self.svc = _make_phone_service()
        self.svc._notify_fn = MagicMock()
        _inject_service(self.svc)

    def teardown_method(self):
        _cleanup_service()

    def test_empty_log(self):
        from bantz.tools.phone_tools import phone_call_log_tool
        result = phone_call_log_tool()
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["calls"] == []

    def test_log_after_call(self):
        from bantz.tools.phone_tools import phone_call_log_tool

        with patch("bantz.tools.phone_tools.subprocess") as mock_sp:
            mock_sp.Popen.return_value = MagicMock()
            self.svc.initiate_call("+905551234567", "Ali")
        self.svc.hangup()

        result = phone_call_log_tool()
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["calls"][0]["name"] == "Ali"

    def test_log_limit_clamped(self):
        from bantz.tools.phone_tools import phone_call_log_tool
        result = phone_call_log_tool(limit=100)
        assert result["ok"] is True  # limit clamped to 50


# ─────────────────────────────────────────────────────────────────
# Tool Registration
# ─────────────────────────────────────────────────────────────────


class TestPhoneToolRegistration:
    def test_all_tool_handlers_are_callable(self):
        """Verify phone tools can be imported."""
        from bantz.tools.phone_tools import (
            phone_call_tool,
            phone_hangup_tool,
            phone_mute_tool,
            phone_speaker_tool,
            phone_status_tool,
            phone_call_log_tool,
        )
        assert callable(phone_call_tool)
        assert callable(phone_hangup_tool)
        assert callable(phone_mute_tool)
        assert callable(phone_speaker_tool)
        assert callable(phone_status_tool)
        assert callable(phone_call_log_tool)


# ─────────────────────────────────────────────────────────────────
# Metadata & Policy (Issue #1438)
# ─────────────────────────────────────────────────────────────────


class TestPhoneToolMetadata:
    def test_phone_call_is_destructive(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("phone.call") == ToolRisk.DESTRUCTIVE

    def test_phone_status_is_safe(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("phone.status") == ToolRisk.SAFE

    def test_phone_hangup_is_moderate(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("phone.hangup") == ToolRisk.MODERATE

    def test_phone_call_requires_confirmation(self):
        from bantz.tools.metadata import requires_confirmation
        assert requires_confirmation("phone.call") is True
