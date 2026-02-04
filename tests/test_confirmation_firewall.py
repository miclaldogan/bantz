"""Tests for Confirmation Firewall (Issue #160).

Tests cover:
1. Tool risk classification
2. Destructive tools require confirmation
3. LLM cannot override firewall
4. Confirmation flow works correctly
5. Audit logging captures all events
"""

from __future__ import annotations

import pytest
import tempfile
import json
from pathlib import Path
from typing import Any

from bantz.tools.metadata import (
    ToolRisk,
    get_tool_risk,
    is_destructive,
    requires_confirmation,
    get_confirmation_prompt,
    register_tool_risk,
    get_all_tools_by_risk,
    get_registry_stats,
    TOOL_REGISTRY,
)
from bantz.agent.executor import Executor, ExecutionResult
from bantz.agent.tools import ToolRegistry, Tool
from bantz.logs.logger import JsonlLogger


# ═══════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def tool_registry():
    """Create a test tool registry with sample tools."""
    registry = ToolRegistry()
    
    # SAFE tool
    registry.register(
        Tool(
            name="web.search",
            description="Search the web",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            function=lambda query: {"results": ["result1", "result2"]},
        )
    )
    
    # MODERATE tool
    registry.register(
        Tool(
            name="calendar.create_event",
            description="Create a calendar event",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                },
            },
            function=lambda title, start: {"event_id": "evt123"},
        )
    )
    
    # DESTRUCTIVE tool
    registry.register(
        Tool(
            name="calendar.delete_event",
            description="Delete a calendar event",
            parameters={
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
            },
            function=lambda event_id: {"deleted": event_id},
        )
    )
    
    return registry


@pytest.fixture
def audit_logger():
    """Create a temporary audit logger."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
        logger = JsonlLogger(path=f.name)
        yield logger
        # Cleanup
        Path(f.name).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════
# Test Risk Classification
# ═══════════════════════════════════════════════════════════

def test_tool_risk_enum():
    """Test ToolRisk enum values."""
    assert ToolRisk.SAFE.value == "safe"
    assert ToolRisk.MODERATE.value == "moderate"
    assert ToolRisk.DESTRUCTIVE.value == "destructive"


def test_get_tool_risk_safe():
    """Test getting risk for SAFE tools."""
    assert get_tool_risk("web.search") == ToolRisk.SAFE
    assert get_tool_risk("web.open") == ToolRisk.SAFE
    assert get_tool_risk("calendar.list_events") == ToolRisk.SAFE


def test_get_tool_risk_moderate():
    """Test getting risk for MODERATE tools."""
    assert get_tool_risk("calendar.create_event") == ToolRisk.MODERATE
    assert get_tool_risk("notification.send") == ToolRisk.MODERATE
    assert get_tool_risk("browser.open") == ToolRisk.MODERATE


def test_get_tool_risk_destructive():
    """Test getting risk for DESTRUCTIVE tools."""
    assert get_tool_risk("calendar.delete_event") == ToolRisk.DESTRUCTIVE
    assert get_tool_risk("file.delete") == ToolRisk.DESTRUCTIVE
    assert get_tool_risk("system.shutdown") == ToolRisk.DESTRUCTIVE


def test_get_tool_risk_unknown_default():
    """Test default risk for unknown tools."""
    assert get_tool_risk("unknown.tool") == ToolRisk.MODERATE
    assert get_tool_risk("unknown.tool", default=ToolRisk.SAFE) == ToolRisk.SAFE


def test_is_destructive():
    """Test is_destructive helper."""
    assert is_destructive("calendar.delete_event") is True
    assert is_destructive("file.delete") is True
    assert is_destructive("web.search") is False
    assert is_destructive("calendar.create_event") is False


def test_requires_confirmation_destructive_always():
    """Test that DESTRUCTIVE tools always require confirmation."""
    # LLM says no confirmation needed - FIREWALL overrides
    assert requires_confirmation("calendar.delete_event", llm_requested=False) is True
    # LLM says confirmation needed - respect it
    assert requires_confirmation("calendar.delete_event", llm_requested=True) is True


def test_requires_confirmation_safe_respects_llm():
    """Test that SAFE tools respect LLM decision."""
    # LLM says no confirmation - respect it
    assert requires_confirmation("web.search", llm_requested=False) is False
    # LLM says confirmation needed - respect it
    assert requires_confirmation("web.search", llm_requested=True) is True


def test_get_confirmation_prompt():
    """Test confirmation prompt generation."""
    prompt = get_confirmation_prompt(
        "calendar.delete_event",
        {"event_id": "evt123"}
    )
    assert "evt123" in prompt
    assert "Delete" in prompt or "delete" in prompt
    
    prompt = get_confirmation_prompt(
        "file.delete",
        {"path": "/tmp/test.txt"}
    )
    assert "/tmp/test.txt" in prompt


def test_register_tool_risk():
    """Test dynamic tool registration."""
    register_tool_risk("custom.dangerous", ToolRisk.DESTRUCTIVE)
    assert get_tool_risk("custom.dangerous") == ToolRisk.DESTRUCTIVE
    assert is_destructive("custom.dangerous") is True


def test_get_all_tools_by_risk():
    """Test filtering tools by risk level."""
    safe_tools = get_all_tools_by_risk(ToolRisk.SAFE)
    assert "web.search" in safe_tools
    assert "web.open" in safe_tools
    
    destructive_tools = get_all_tools_by_risk(ToolRisk.DESTRUCTIVE)
    assert "calendar.delete_event" in destructive_tools
    assert "file.delete" in destructive_tools


def test_get_registry_stats():
    """Test registry statistics."""
    stats = get_registry_stats()
    assert stats["total"] > 0
    assert stats["safe"] > 0
    assert stats["moderate"] > 0
    assert stats["destructive"] > 0
    assert stats["total"] == stats["safe"] + stats["moderate"] + stats["destructive"]


# ═══════════════════════════════════════════════════════════
# Test Executor Confirmation Firewall
# ═══════════════════════════════════════════════════════════

class DummyStep:
    """Dummy step for testing."""
    def __init__(self, action: str, params: dict):
        self.action = action
        self.params = params
        self.description = f"Execute {action}"


def test_executor_safe_tool_executes_immediately(tool_registry):
    """Test that SAFE tools execute without confirmation."""
    executor = Executor(tool_registry)
    step = DummyStep("web.search", {"query": "test"})
    
    def runner(action: str, params: dict) -> ExecutionResult:
        tool = tool_registry.get(action)
        result = tool.function(**params)
        return ExecutionResult(ok=True, data=result)
    
    result = executor.execute(step, runner=runner)
    
    assert result.ok is True
    assert result.awaiting_confirmation is False
    assert result.risk_level == "safe"


def test_executor_destructive_tool_requires_confirmation(tool_registry):
    """Test that DESTRUCTIVE tools require confirmation."""
    executor = Executor(tool_registry)
    step = DummyStep("calendar.delete_event", {"event_id": "evt123"})
    
    def runner(action: str, params: dict) -> ExecutionResult:
        tool = tool_registry.get(action)
        result = tool.function(**params)
        return ExecutionResult(ok=True, data=result)
    
    # First attempt - should block
    result = executor.execute(step, runner=runner)
    
    assert result.ok is False
    assert result.awaiting_confirmation is True
    assert result.confirmation_prompt is not None
    assert "evt123" in result.confirmation_prompt
    assert result.risk_level == "destructive"


def test_executor_destructive_tool_executes_after_confirmation(tool_registry):
    """Test that DESTRUCTIVE tools execute after confirmation."""
    executor = Executor(tool_registry)
    step = DummyStep("calendar.delete_event", {"event_id": "evt123"})
    
    def runner(action: str, params: dict) -> ExecutionResult:
        tool = tool_registry.get(action)
        result = tool.function(**params)
        return ExecutionResult(ok=True, data=result)
    
    # First attempt - should block
    result1 = executor.execute(step, runner=runner)
    assert result1.awaiting_confirmation is True
    
    # Confirm the action
    executor.confirm_action(step)
    
    # Second attempt - should execute
    result2 = executor.execute(step, runner=runner)
    assert result2.ok is True
    assert result2.awaiting_confirmation is False
    assert result2.data == {"deleted": "evt123"}


def test_executor_skip_confirmation_flag(tool_registry):
    """Test skip_confirmation flag for testing."""
    executor = Executor(tool_registry)
    step = DummyStep("calendar.delete_event", {"event_id": "evt123"})
    
    def runner(action: str, params: dict) -> ExecutionResult:
        tool = tool_registry.get(action)
        result = tool.function(**params)
        return ExecutionResult(ok=True, data=result)
    
    # Execute with skip_confirmation=True
    result = executor.execute(step, runner=runner, skip_confirmation=True)
    
    assert result.ok is True
    assert result.awaiting_confirmation is False


def test_executor_different_params_need_separate_confirmation(tool_registry):
    """Test that different parameters require separate confirmations."""
    executor = Executor(tool_registry)
    
    step1 = DummyStep("calendar.delete_event", {"event_id": "evt1"})
    step2 = DummyStep("calendar.delete_event", {"event_id": "evt2"})
    
    def runner(action: str, params: dict) -> ExecutionResult:
        tool = tool_registry.get(action)
        result = tool.function(**params)
        return ExecutionResult(ok=True, data=result)
    
    # Confirm step1
    executor.confirm_action(step1)
    
    # step1 should execute
    result1 = executor.execute(step1, runner=runner)
    assert result1.ok is True
    
    # step2 should still need confirmation
    result2 = executor.execute(step2, runner=runner)
    assert result2.awaiting_confirmation is True


# ═══════════════════════════════════════════════════════════
# Test Audit Logging
# ═══════════════════════════════════════════════════════════

def test_audit_logger_tool_execution(audit_logger):
    """Test logging tool execution."""
    audit_logger.log_tool_execution(
        tool_name="web.search",
        risk_level="safe",
        success=True,
        confirmed=False,
        params={"query": "test"},
        result={"results": ["result1"]},
    )
    
    logs = audit_logger.tail(1)
    assert len(logs) == 1
    assert logs[0]["event_type"] == "tool_execution"
    assert logs[0]["tool_name"] == "web.search"
    assert logs[0]["risk_level"] == "safe"
    assert logs[0]["success"] is True
    assert logs[0]["confirmed"] is False


def test_audit_logger_destructive_tool(audit_logger):
    """Test logging destructive tool execution."""
    audit_logger.log_tool_execution(
        tool_name="calendar.delete_event",
        risk_level="destructive",
        success=True,
        confirmed=True,
        params={"event_id": "evt123"},
        result={"deleted": "evt123"},
    )
    
    logs = audit_logger.tail(1)
    assert len(logs) == 1
    assert logs[0]["tool_name"] == "calendar.delete_event"
    assert logs[0]["risk_level"] == "destructive"
    assert logs[0]["confirmed"] is True


def test_audit_logger_tool_failure(audit_logger):
    """Test logging tool failure."""
    audit_logger.log_tool_execution(
        tool_name="calendar.delete_event",
        risk_level="destructive",
        success=False,
        confirmed=False,
        error="Event not found",
        params={"event_id": "evt999"},
    )
    
    logs = audit_logger.tail(1)
    assert len(logs) == 1
    assert logs[0]["success"] is False
    assert logs[0]["error"] == "Event not found"


def test_audit_logger_result_truncation(audit_logger):
    """Test that long results are truncated."""
    long_result = "x" * 1000
    
    audit_logger.log_tool_execution(
        tool_name="web.search",
        risk_level="safe",
        success=True,
        confirmed=False,
        result=long_result,
    )
    
    logs = audit_logger.tail(1)
    assert len(logs) == 1
    # Result should be truncated to 500 chars + "..."
    assert len(logs[0]["result"]) <= 503
    assert logs[0]["result"].endswith("...")


def test_audit_logger_multiple_executions(audit_logger):
    """Test logging multiple tool executions."""
    # Log 3 different tools
    audit_logger.log_tool_execution(
        tool_name="web.search",
        risk_level="safe",
        success=True,
        confirmed=False,
    )
    
    audit_logger.log_tool_execution(
        tool_name="calendar.create_event",
        risk_level="moderate",
        success=True,
        confirmed=False,
    )
    
    audit_logger.log_tool_execution(
        tool_name="calendar.delete_event",
        risk_level="destructive",
        success=True,
        confirmed=True,
    )
    
    logs = audit_logger.tail(3)
    assert len(logs) == 3
    assert logs[0]["tool_name"] == "web.search"
    assert logs[1]["tool_name"] == "calendar.create_event"
    assert logs[2]["tool_name"] == "calendar.delete_event"
    assert logs[2]["confirmed"] is True


# ═══════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════

def test_firewall_prevents_llm_override(tool_registry):
    """Test that LLM cannot override DESTRUCTIVE tool firewall.
    
    This is the key security feature: even if LLM says
    requires_confirmation=False, the firewall enforces it.
    """
    # Simulate LLM output that forgot to request confirmation
    llm_requested_confirmation = False
    tool_name = "calendar.delete_event"
    
    # Firewall should still require confirmation
    assert requires_confirmation(tool_name, llm_requested_confirmation) is True
    assert is_destructive(tool_name) is True


def test_moderate_tools_respect_llm_decision(tool_registry):
    """Test that MODERATE tools respect LLM confirmation decision."""
    tool_name = "calendar.create_event"
    
    # LLM says no confirmation - allow it
    assert requires_confirmation(tool_name, llm_requested=False) is False
    
    # LLM says confirmation needed - respect it
    assert requires_confirmation(tool_name, llm_requested=True) is True


def test_gmail_send_requires_confirmation_even_if_llm_does_not_request_it():
    tool_name = "gmail.send"
    assert get_tool_risk(tool_name) == ToolRisk.MODERATE
    assert is_destructive(tool_name) is False
    assert requires_confirmation(tool_name, llm_requested=False) is True


def test_confirmation_flow_full_cycle(tool_registry, audit_logger):
    """Test full confirmation flow from request to execution."""
    executor = Executor(tool_registry)
    step = DummyStep("calendar.delete_event", {"event_id": "evt123"})
    
    execution_count = 0
    
    def runner(action: str, params: dict) -> ExecutionResult:
        nonlocal execution_count
        execution_count += 1
        tool = tool_registry.get(action)
        result = tool.function(**params)
        
        # Log execution
        audit_logger.log_tool_execution(
            tool_name=action,
            risk_level=get_tool_risk(action).value,
            success=True,
            confirmed=True,
            params=params,
            result=result,
        )
        
        return ExecutionResult(ok=True, data=result)
    
    # Step 1: First attempt - should block
    result1 = executor.execute(step, runner=runner)
    assert result1.awaiting_confirmation is True
    assert execution_count == 0  # Not executed yet
    
    # Step 2: User confirms
    executor.confirm_action(step)
    
    # Step 3: Second attempt - should execute
    result2 = executor.execute(step, runner=runner)
    assert result2.ok is True
    assert result2.awaiting_confirmation is False
    assert execution_count == 1  # Executed once
    
    # Step 4: Check audit log
    logs = audit_logger.tail(1)
    assert len(logs) == 1
    assert logs[0]["tool_name"] == "calendar.delete_event"
    assert logs[0]["risk_level"] == "destructive"
    assert logs[0]["confirmed"] is True
    assert logs[0]["success"] is True
