"""Tests for Issue #663 — Tool Contract'ları ürün kalitesine çıkar.

Faz 1: Schema sertleştirme
Faz 2: Type coercion & validation
Faz 3: İdempotency guards
Faz 4: Confirmation UX
"""

from __future__ import annotations

import os
import time
import threading
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.agent.registry import build_default_registry


# ═══════════════════════════════════════════════════════════════════
# Faz 1 — Schema Sertleştirme
# ═══════════════════════════════════════════════════════════════════

class TestFaz1_SchemaHardening:

    def test_list_tools_returns_all(self):
        """ToolRegistry.list_tools() returns Tool objects sorted by name."""
        reg = build_default_registry()
        tools = reg.list_tools()
        assert len(tools) >= 15  # runtime registry has ~17+ tools
        assert all(isinstance(t, Tool) for t in tools)
        # sorted
        names = [t.name for t in tools]
        assert names == sorted(names)

    def test_get_schema_returns_dict(self):
        """ToolRegistry.get_schema() returns well-formed schema dict."""
        reg = build_default_registry()
        schema = reg.get_schema("calendar.create_event")
        assert schema is not None
        assert schema["name"] == "calendar.create_event"
        assert "parameters" in schema
        assert schema["requires_confirmation"] is True

    def test_get_schema_none_for_missing(self):
        """get_schema returns None for non-existent tool."""
        reg = build_default_registry()
        assert reg.get_schema("nonexistent.tool") is None

    def test_no_empty_schemas_in_calendar_tools(self):
        """Issue #654: calendar tool schemas should NOT have empty {} property defs."""
        reg = build_default_registry()
        for name in reg.names():
            if not name.startswith("calendar."):
                continue
            tool = reg.get(name)
            assert tool is not None
            props = (tool.parameters or {}).get("properties", {})
            for field_name, field_schema in props.items():
                assert field_schema != {}, (
                    f"{name}.{field_name} has empty schema {{}}"
                )

    def test_gmail_tools_no_calendar_fields(self):
        """Issue #654: Gmail tools should NOT contain calendar-only fields."""
        calendar_only = {"window_hint", "duration"}
        reg = build_default_registry()
        for name in reg.names():
            if not name.startswith("gmail."):
                continue
            tool = reg.get(name)
            assert tool is not None
            props = set((tool.parameters or {}).get("properties", {}).keys())
            leaked = props & calendar_only
            assert not leaked, f"{name} leaks calendar fields: {leaked}"

    def test_phantom_tools_present(self):
        """Issue #663: calendar.find_event and calendar.get_event exist in runtime registry."""
        reg = build_default_registry()
        assert reg.get("calendar.find_event") is not None, "calendar.find_event missing"
        assert reg.get("calendar.get_event") is not None, "calendar.get_event missing"
        # Both should have function handlers
        assert reg.get("calendar.find_event").function is not None
        assert reg.get("calendar.get_event").function is not None


# ═══════════════════════════════════════════════════════════════════
# Faz 2 — Type Coercion & Validation
# ═══════════════════════════════════════════════════════════════════

class TestFaz2_TypeCoercion:

    def test_bool_before_int_check(self):
        """Issue #656: bool True should fail integer validation (bool ⊂ int)."""
        reg = ToolRegistry()
        reg.register(Tool(
            name="test.tool",
            description="test",
            parameters={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": [],
            },
        ))
        # bool should be rejected for integer
        ok, msg = reg.validate_call("test.tool", {"count": True})
        assert not ok
        assert "expected_int" in msg

    def test_bool_accepted_for_boolean(self):
        """bool True should pass boolean validation."""
        reg = ToolRegistry()
        reg.register(Tool(
            name="test.tool",
            description="test",
            parameters={
                "type": "object",
                "properties": {"flag": {"type": "boolean"}},
                "required": [],
            },
        ))
        ok, msg = reg.validate_call("test.tool", {"flag": True})
        assert ok

    def test_int_rejected_for_boolean(self):
        """int 1 should fail boolean validation."""
        reg = ToolRegistry()
        reg.register(Tool(
            name="test.tool",
            description="test",
            parameters={
                "type": "object",
                "properties": {"flag": {"type": "boolean"}},
                "required": [],
            },
        ))
        ok, msg = reg.validate_call("test.tool", {"flag": 1})
        assert not ok
        assert "expected_boolean" in msg

    def test_empty_string_coerced_to_none(self):
        """Issue #663: empty string '' → None during validation."""
        reg = ToolRegistry()
        reg.register(Tool(
            name="test.tool",
            description="test",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": [],
            },
        ))
        params = {"name": "  "}
        ok, msg = reg.validate_call("test.tool", params)
        assert ok
        # Issue #1174: validate_call works on a shallow copy,
        # so the caller's original dict is NOT mutated.
        assert params["name"] == "  "

    def test_enum_validation(self):
        """Issue #663: enum fields should reject invalid values."""
        reg = ToolRegistry()
        reg.register(Tool(
            name="test.tool",
            description="test",
            parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["fast", "quality"]},
                },
                "required": [],
            },
        ))
        ok, _ = reg.validate_call("test.tool", {"mode": "fast"})
        assert ok
        ok, msg = reg.validate_call("test.tool", {"mode": "invalid"})
        assert not ok
        assert "bad_enum" in msg

    def test_date_format_validation(self):
        """Issue #663: invalid date format rejected by calendar.create_event."""
        from bantz.tools.calendar_tools import _validate_date_format
        # Valid
        assert _validate_date_format("2026-02-10") is None
        assert _validate_date_format("bugün") is None
        assert _validate_date_format("yarın") is None
        # Invalid
        assert _validate_date_format("10-02-2026") is not None
        assert _validate_date_format("abc") is not None

    def test_time_format_validation(self):
        """Issue #663: invalid time format rejected."""
        from bantz.tools.calendar_tools import _validate_time_format
        # Valid
        assert _validate_time_format("14:30") is None
        assert _validate_time_format("9:00") is None
        # Invalid
        assert _validate_time_format("25:00") is not None
        assert _validate_time_format("abc") is not None
        assert _validate_time_format("14:60") is not None

    def test_past_date_detected(self):
        """Issue #663: past dates are detected by _is_past."""
        from bantz.tools.calendar_tools import _is_past
        yesterday = (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()
        assert _is_past(yesterday, "10:00") is True
        tomorrow = (datetime.now().astimezone().date() + timedelta(days=1)).isoformat()
        assert _is_past(tomorrow, "10:00") is False


# ═══════════════════════════════════════════════════════════════════
# Faz 3 — İdempotency Guards
# ═══════════════════════════════════════════════════════════════════

class TestFaz3_Idempotency:

    def test_gmail_send_duplicate_blocked(self):
        """Issue #663: gmail.send blocks duplicate within 60s window."""
        from bantz.tools.gmail_tools import (
            _gmail_check_duplicate,
            _gmail_record_send,
            _gmail_send_log,
        )
        # Clean state
        _gmail_send_log.clear()

        _gmail_record_send("test@example.com", "Test Subject")
        assert _gmail_check_duplicate("test@example.com", "Test Subject") is True
        # Different subject: OK
        assert _gmail_check_duplicate("test@example.com", "Other Subject") is False
        # Different recipient: OK
        assert _gmail_check_duplicate("other@example.com", "Test Subject") is False

    def test_gmail_send_duplicate_expires(self):
        """Duplicate guard expires after window."""
        from bantz.tools.gmail_tools import (
            _gmail_check_duplicate,
            _gmail_send_log,
            _gmail_send_dedup_key,
            _GMAIL_SEND_WINDOW,
        )
        _gmail_send_log.clear()

        key = _gmail_send_dedup_key("test@example.com", "Test")
        _gmail_send_log[key] = time.time() - _GMAIL_SEND_WINDOW - 1  # expired
        assert _gmail_check_duplicate("test@example.com", "Test") is False

    def test_calendar_idempotency_exists(self):
        """Calendar idempotency module is importable and has key functions."""
        from bantz.tools.calendar_idempotency import (
            generate_idempotency_key,
            check_duplicate,
            create_event_with_idempotency,
        )
        key = generate_idempotency_key(
            title="Toplantı",
            start="2026-02-10T14:00:00+03:00",
            end="2026-02-10T15:00:00+03:00",
        )
        assert isinstance(key, str)
        assert len(key) == 32  # SHA-256 hex digest truncated to 32 chars


# ═══════════════════════════════════════════════════════════════════
# Faz 4 — Confirmation UX
# ═══════════════════════════════════════════════════════════════════

class TestFaz4_ConfirmationUX:

    def test_all_runtime_tools_have_risk_level(self):
        """Every runtime tool must have an explicit risk level in policy.json."""
        from bantz.tools.metadata import TOOL_REGISTRY
        reg = build_default_registry()
        for name in reg.names():
            assert name in TOOL_REGISTRY, (
                f"Tool '{name}' missing from TOOL_REGISTRY (policy.json). "
                f"It will fall back to undefined_tool_policy."
            )

    def test_confirmation_timeout_constant(self):
        """CONFIRMATION_TIMEOUT_SECONDS is exported and equals 30."""
        from bantz.tools.metadata import CONFIRMATION_TIMEOUT_SECONDS
        assert CONFIRMATION_TIMEOUT_SECONDS == 30

    def test_deterministic_prompt_never_empty(self):
        """Confirmation prompts are always non-empty Turkish strings."""
        from bantz.tools.metadata import get_confirmation_prompt
        prompt = get_confirmation_prompt("calendar.create_event", {"title": "Test", "time": "14:00"})
        assert prompt  # non-empty
        assert isinstance(prompt, str)

        prompt2 = get_confirmation_prompt("unknown.tool", {})
        assert prompt2  # fallback still non-empty

    def test_undefined_tool_policy_is_deny(self):
        """undefined_tool_policy should be 'deny' by default."""
        from bantz.tools.metadata import UNDEFINED_TOOL_POLICY
        assert UNDEFINED_TOOL_POLICY == "deny"

    def test_system_screenshot_not_destructive(self):
        """system.screenshot should be SAFE, not DESTRUCTIVE."""
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        risk = get_tool_risk("system.screenshot")
        assert risk == ToolRisk.SAFE, (
            f"system.screenshot risk is {risk}, expected SAFE"
        )
