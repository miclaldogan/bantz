"""Tests for Route-Independent Safe Tools (Issue #286).

Tests that safe tools like time.now and system.status work
regardless of route (even when route=unknown).
"""

import pytest

from bantz.brain.safety_guard import (
    SafetyGuard,
    ToolSecurityPolicy,
    ROUTE_INDEPENDENT_SAFE_TOOLS,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def guard():
    """SafetyGuard with default policy."""
    return SafetyGuard(policy=ToolSecurityPolicy())


@pytest.fixture
def guard_no_enforcement():
    """SafetyGuard with route enforcement disabled."""
    policy = ToolSecurityPolicy(enforce_route_tool_match=False)
    return SafetyGuard(policy=policy)


# ============================================================================
# Test ROUTE_INDEPENDENT_SAFE_TOOLS constant
# ============================================================================

class TestRouteIndependentSafeToolsConstant:
    """Tests for the ROUTE_INDEPENDENT_SAFE_TOOLS set."""
    
    def test_time_now_is_safe(self):
        """time.now should be in safe tools."""
        assert "time.now" in ROUTE_INDEPENDENT_SAFE_TOOLS
    
    def test_system_status_is_safe(self):
        """system.status should be in safe tools."""
        assert "system.status" in ROUTE_INDEPENDENT_SAFE_TOOLS
    
    def test_calendar_list_events_is_safe(self):
        """calendar.list_events (read-only) should be in safe tools."""
        assert "calendar.list_events" in ROUTE_INDEPENDENT_SAFE_TOOLS
    
    def test_gmail_list_messages_is_safe(self):
        """gmail.list_messages (read-only) should be in safe tools."""
        assert "gmail.list_messages" in ROUTE_INDEPENDENT_SAFE_TOOLS
    
    def test_destructive_tools_not_in_safe_list(self):
        """Destructive tools should NOT be in safe tools."""
        assert "calendar.create_event" not in ROUTE_INDEPENDENT_SAFE_TOOLS
        assert "calendar.delete_event" not in ROUTE_INDEPENDENT_SAFE_TOOLS
        assert "calendar.update_event" not in ROUTE_INDEPENDENT_SAFE_TOOLS
        assert "gmail.send" not in ROUTE_INDEPENDENT_SAFE_TOOLS


# ============================================================================
# Test filter_tool_plan with safe tools
# ============================================================================

class TestFilterToolPlanSafeTools:
    """Tests for filter_tool_plan allowing safe tools."""
    
    def test_time_now_allowed_on_route_unknown(self, guard):
        """time.now should work even when route=unknown."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["time.now"],
        )
        
        assert filtered == ["time.now"]
        assert len(violations) == 0
    
    def test_system_status_allowed_on_route_unknown(self, guard):
        """system.status should work even when route=unknown."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["system.status"],
        )
        
        assert filtered == ["system.status"]
        assert len(violations) == 0
    
    def test_calendar_list_events_allowed_on_route_unknown(self, guard):
        """calendar.list_events should work even when route=unknown."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["calendar.list_events"],
        )
        
        assert filtered == ["calendar.list_events"]
        assert len(violations) == 0
    
    def test_gmail_list_messages_allowed_on_route_unknown(self, guard):
        """gmail.list_messages should work even when route=unknown."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["gmail.list_messages"],
        )
        
        assert filtered == ["gmail.list_messages"]
        assert len(violations) == 0
    
    def test_safe_tools_allowed_on_route_smalltalk(self, guard):
        """Safe tools should work even when route=smalltalk."""
        filtered, violations = guard.filter_tool_plan(
            route="smalltalk",
            tool_plan=["time.now", "system.status"],
        )
        
        assert filtered == ["time.now", "system.status"]
        assert len(violations) == 0
    
    def test_multiple_safe_tools_all_allowed(self, guard):
        """Multiple safe tools should all be allowed."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["time.now", "calendar.list_events", "gmail.list_messages"],
        )
        
        assert filtered == ["time.now", "calendar.list_events", "gmail.list_messages"]
        assert len(violations) == 0


# ============================================================================
# Test filter_tool_plan with unsafe tools on wrong route
# ============================================================================

class TestFilterToolPlanUnsafeTools:
    """Tests for filter_tool_plan blocking unsafe tools on wrong route."""
    
    def test_calendar_create_blocked_on_route_unknown(self, guard):
        """calendar.create_event should be blocked when route=unknown."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["calendar.create_event"],
        )
        
        assert filtered == []
        assert len(violations) == 1
        assert violations[0].tool_name == "calendar.create_event"
        assert violations[0].violation_type == "route_tool_mismatch"
    
    def test_calendar_delete_blocked_on_route_smalltalk(self, guard):
        """calendar.delete_event should be blocked when route=smalltalk."""
        filtered, violations = guard.filter_tool_plan(
            route="smalltalk",
            tool_plan=["calendar.delete_event"],
        )
        
        assert filtered == []
        assert len(violations) == 1
        assert violations[0].tool_name == "calendar.delete_event"
    
    def test_gmail_send_blocked_on_route_unknown(self, guard):
        """gmail.send should be blocked when route=unknown."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["gmail.send"],
        )
        
        assert filtered == []
        assert len(violations) == 1


# ============================================================================
# Test mixed safe and unsafe tools
# ============================================================================

class TestFilterToolPlanMixed:
    """Tests for filter_tool_plan with mixed safe and unsafe tools."""
    
    def test_safe_allowed_unsafe_blocked(self, guard):
        """Safe tools should pass, unsafe should be blocked."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["time.now", "calendar.create_event", "system.status"],
        )
        
        # time.now and system.status are safe
        assert "time.now" in filtered
        assert "system.status" in filtered
        
        # calendar.create_event is blocked
        assert "calendar.create_event" not in filtered
        assert len(violations) == 1
        assert violations[0].tool_name == "calendar.create_event"
    
    def test_order_preserved_for_safe_tools(self, guard):
        """Order of safe tools should be preserved."""
        filtered, violations = guard.filter_tool_plan(
            route="unknown",
            tool_plan=["system.status", "time.now", "calendar.list_events"],
        )
        
        assert filtered == ["system.status", "time.now", "calendar.list_events"]


# ============================================================================
# Test allowed routes still work normally
# ============================================================================

class TestFilterToolPlanAllowedRoutes:
    """Tests for filter_tool_plan with allowed routes (calendar, gmail, system)."""
    
    def test_calendar_route_allows_all_calendar_tools(self, guard):
        """route=calendar should allow all calendar tools."""
        filtered, violations = guard.filter_tool_plan(
            route="calendar",
            tool_plan=["calendar.list_events", "calendar.create_event", "calendar.delete_event"],
        )
        
        assert filtered == ["calendar.list_events", "calendar.create_event", "calendar.delete_event"]
        assert len(violations) == 0
    
    def test_gmail_route_allows_all_gmail_tools(self, guard):
        """route=gmail should allow all gmail tools."""
        filtered, violations = guard.filter_tool_plan(
            route="gmail",
            tool_plan=["gmail.list_messages", "gmail.send"],
        )
        
        assert filtered == ["gmail.list_messages", "gmail.send"]
        assert len(violations) == 0
    
    def test_system_route_allows_system_tools(self, guard):
        """route=system should allow system tools."""
        filtered, violations = guard.filter_tool_plan(
            route="system",
            tool_plan=["time.now", "system.status"],
        )
        
        assert filtered == ["time.now", "system.status"]
        assert len(violations) == 0


# ============================================================================
# Test enforcement can be disabled
# ============================================================================

class TestFilterToolPlanEnforcementDisabled:
    """Tests for filter_tool_plan when enforcement is disabled."""
    
    def test_all_tools_allowed_when_enforcement_disabled(self, guard_no_enforcement):
        """All tools should be allowed when enforcement is disabled."""
        filtered, violations = guard_no_enforcement.filter_tool_plan(
            route="unknown",
            tool_plan=["calendar.create_event", "gmail.send"],
        )
        
        assert filtered == ["calendar.create_event", "gmail.send"]
        assert len(violations) == 0
