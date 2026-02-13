"""Test suite for Safety Guard (Issue #140).

Tests:
- Tool allowlist/denylist enforcement
- Argument schema validation
- Confirmation token validation
- Route-tool match filtering
- Policy violation handling
"""

from __future__ import annotations

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.safety_guard import (
    SafetyGuard,
    ToolSecurityPolicy,
    normalize_confirmation,
)


# ============================================================================
# Confirmation Token Tests
# ============================================================================

def test_normalize_confirmation_accept():
    """Test accept tokens."""
    assert normalize_confirmation("1") == "accept"
    assert normalize_confirmation("yes") == "accept"
    assert normalize_confirmation("evet") == "accept"
    assert normalize_confirmation("tamam") == "accept"
    assert normalize_confirmation("YES") == "accept"  # Case insensitive
    assert normalize_confirmation("Evet!") == "accept"  # With punctuation


def test_normalize_confirmation_reject():
    """Test reject tokens."""
    assert normalize_confirmation("0") == "reject"
    assert normalize_confirmation("no") == "reject"
    assert normalize_confirmation("hayır") == "reject"
    assert normalize_confirmation("iptal") == "reject"
    assert normalize_confirmation("NO") == "reject"


def test_normalize_confirmation_ambiguous():
    """Test ambiguous tokens (not acceptable for destructive ops)."""
    assert normalize_confirmation("okay") == "ambiguous"
    assert normalize_confirmation("sure") == "ambiguous"
    assert normalize_confirmation("olur") == "ambiguous"


def test_normalize_confirmation_unknown():
    """Test unknown tokens."""
    assert normalize_confirmation("belki") == "unknown"
    assert normalize_confirmation("düşüneyim") == "unknown"
    assert normalize_confirmation("") == "unknown"


# ============================================================================
# Tool Allowlist/Denylist Tests
# ============================================================================

def test_tool_allowlist():
    """Test tool allowlist enforcement."""
    policy = ToolSecurityPolicy(
        allowlist={"calendar.list_events", "calendar.create_event"}
    )
    guard = SafetyGuard(policy=policy)
    
    # Allowed tools
    allowed, reason = guard.check_tool_allowed("calendar.list_events")
    assert allowed is True
    assert reason is None
    
    # Not in allowlist
    allowed, reason = guard.check_tool_allowed("calendar.delete_event")
    assert allowed is False
    assert "not in allowlist" in reason


def test_tool_denylist():
    """Test tool denylist enforcement."""
    policy = ToolSecurityPolicy(
        denylist={"calendar.delete_event"}
    )
    guard = SafetyGuard(policy=policy)
    
    # Not denied
    allowed, reason = guard.check_tool_allowed("calendar.list_events")
    assert allowed is True
    
    # Denied
    allowed, reason = guard.check_tool_allowed("calendar.delete_event")
    assert allowed is False
    assert "denied by policy" in reason


def test_denylist_precedence():
    """Test denylist takes precedence over allowlist."""
    policy = ToolSecurityPolicy(
        allowlist={"calendar.list_events", "calendar.delete_event"},
        denylist={"calendar.delete_event"},
    )
    guard = SafetyGuard(policy=policy)
    
    # In allowlist but also in denylist - should be denied
    allowed, reason = guard.check_tool_allowed("calendar.delete_event")
    assert allowed is False
    assert "denied by policy" in reason


# ============================================================================
# Argument Schema Validation Tests
# ============================================================================

def test_validate_args_required_fields():
    """Test required field validation."""
    tool = Tool(
        name="calendar.create_event",
        description="Create event",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_time": {"type": "string"},
            },
            "required": ["title", "start_time"],
        },
    )
    guard = SafetyGuard()
    
    # Valid args
    valid, error = guard.validate_tool_args(tool, {
        "title": "Meeting",
        "start_time": "2026-01-30T10:00:00",
    })
    assert valid is True
    assert error is None
    
    # Missing required field
    valid, error = guard.validate_tool_args(tool, {
        "title": "Meeting",
    })
    assert valid is False
    assert "Missing required field: start_time" in error


def test_validate_args_type_checking():
    """Test type validation."""
    tool = Tool(
        name="calendar.list_events",
        description="List events",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
                "limit": {"type": "number"},
            },
            "required": [],
        },
    )
    guard = SafetyGuard()
    
    # Valid types
    valid, error = guard.validate_tool_args(tool, {
        "time_min": "2026-01-30T00:00:00",
        "time_max": "2026-01-30T23:59:59",
        "limit": 10,
    })
    assert valid is True
    
    # Invalid type (string instead of number)
    valid, error = guard.validate_tool_args(tool, {
        "time_min": "2026-01-30T00:00:00",
        "limit": "ten",  # Should be number
    })
    assert valid is False
    assert "must be number" in error


# ============================================================================
# Confirmation Token Validation Tests
# ============================================================================

def test_confirmation_strict_accept():
    """Test strict confirmation accepts clear tokens."""
    policy = ToolSecurityPolicy(
        strict_confirmation={"calendar.delete_event"},
        reject_ambiguous_confirmation=True,
    )
    guard = SafetyGuard(policy=policy)
    
    # Clear accept
    accepted, reason = guard.check_confirmation_token(
        "calendar.delete_event",
        "yes"
    )
    assert accepted is True
    assert reason is None


def test_confirmation_strict_reject_ambiguous():
    """Test strict confirmation rejects ambiguous tokens."""
    policy = ToolSecurityPolicy(
        strict_confirmation={"calendar.delete_event"},
        reject_ambiguous_confirmation=True,
    )
    guard = SafetyGuard(policy=policy)
    
    # Ambiguous token
    accepted, reason = guard.check_confirmation_token(
        "calendar.delete_event",
        "okay"
    )
    assert accepted is False
    assert "Ambiguous confirmation" in reason
    assert "not accepted for destructive operation" in reason


def test_confirmation_non_strict_allow_ambiguous():
    """Test non-strict confirmation allows ambiguous tokens."""
    policy = ToolSecurityPolicy(
        strict_confirmation=set(),  # No strict tools
        reject_ambiguous_confirmation=True,
    )
    guard = SafetyGuard(policy=policy)
    
    # Ambiguous but tool not in strict list
    accepted, reason = guard.check_confirmation_token(
        "calendar.list_events",  # Not destructive
        "okay"
    )
    assert accepted is True


def test_confirmation_reject_unknown():
    """Test unknown confirmation tokens are rejected."""
    guard = SafetyGuard()
    
    accepted, reason = guard.check_confirmation_token(
        "calendar.delete_event",
        "belki"  # "maybe" in Turkish
    )
    assert accepted is False
    assert "Unclear confirmation" in reason


# ============================================================================
# Route-Tool Match Tests
# ============================================================================

def test_filter_tool_plan_smalltalk():
    """Test tool plan is filtered for smalltalk route.
    
    Issue #286: Safe tools (like calendar.list_events) are now allowed
    regardless of route. This test verifies UNSAFE tools are still blocked.
    """
    policy = ToolSecurityPolicy(enforce_route_tool_match=True)
    guard = SafetyGuard(policy=policy)
    
    # Smalltalk route should block unsafe tools like calendar.create_event
    # but allow safe tools like calendar.list_events (Issue #286)
    filtered, violations = guard.filter_tool_plan(
        route="smalltalk",
        tool_plan=["calendar.create_event"],  # Unsafe tool
    )
    
    assert filtered == []
    assert len(violations) == 1
    assert violations[0].violation_type == "route_tool_mismatch"
    assert "smalltalk" in violations[0].reason


def test_filter_tool_plan_calendar():
    """Test tool plan is preserved for calendar route."""
    policy = ToolSecurityPolicy(enforce_route_tool_match=True)
    guard = SafetyGuard(policy=policy)
    
    # Calendar route should allow tools
    filtered, violations = guard.filter_tool_plan(
        route="calendar",
        tool_plan=["calendar.list_events", "calendar.create_event"],
    )
    
    assert filtered == ["calendar.list_events", "calendar.create_event"]
    assert len(violations) == 0


def test_filter_tool_plan_disabled():
    """Test tool plan filtering can be disabled."""
    policy = ToolSecurityPolicy(enforce_route_tool_match=False)
    guard = SafetyGuard(policy=policy)
    
    # Even smalltalk allows tools if filtering disabled
    filtered, violations = guard.filter_tool_plan(
        route="smalltalk",
        tool_plan=["calendar.list_events"],
    )
    
    assert filtered == ["calendar.list_events"]
    assert len(violations) == 0
