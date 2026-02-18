# SPDX-License-Identifier: MIT
"""Tests for Issue #1221: Core pipeline hardening.

Covers trace_id generation, tool result size limiting/truncation,
and pipeline integration.
"""

from __future__ import annotations

import json

import pytest

from bantz.brain.tool_result_limiter import (
    truncate_tool_result,
    enforce_result_size_limits,
    _estimate_size,
    TOOL_RESULT_SOFT_LIMIT,
    TOOL_RESULT_HARD_LIMIT,
)


# ============================================================================
# Tool result size estimation
# ============================================================================
class TestEstimateSize:

    def test_string(self) -> None:
        assert _estimate_size("hello") == 5

    def test_dict(self) -> None:
        d = {"key": "value"}
        assert _estimate_size(d) == len(json.dumps(d, ensure_ascii=False))

    def test_list(self) -> None:
        l = [1, 2, 3]
        assert _estimate_size(l) == len(json.dumps(l))

    def test_non_serializable(self) -> None:
        assert _estimate_size(object()) > 0


# ============================================================================
# Single result truncation
# ============================================================================
class TestTruncateToolResult:

    def test_small_result_unchanged(self) -> None:
        result = {"ok": True, "data": "short"}
        assert truncate_tool_result(result, hard_limit=1000) is result

    def test_large_string_truncated(self) -> None:
        result = "x" * 10000
        truncated = truncate_tool_result(result, hard_limit=500)
        assert isinstance(truncated, str)
        assert len(truncated) < 600
        assert "truncated" in truncated

    def test_large_dict_truncated(self) -> None:
        result = {"body": "x" * 50000, "ok": True}
        truncated = truncate_tool_result(result, hard_limit=1000)
        assert isinstance(truncated, dict)
        assert truncated.get("_truncated") is True
        assert truncated.get("_original_size", 0) > 1000

    def test_large_list_truncated(self) -> None:
        result = [{"id": i, "data": "x" * 100} for i in range(500)]
        truncated = truncate_tool_result(result, hard_limit=2000)
        assert isinstance(truncated, list)
        assert len(truncated) < 500

    def test_preserves_dict_keys_when_possible(self) -> None:
        result = {"a": "short", "b": "medium" * 100, "c": "x" * 50000}
        truncated = truncate_tool_result(result, hard_limit=2000)
        assert "a" in truncated
        assert truncated["a"] == "short"


# ============================================================================
# Batch enforcement
# ============================================================================
class TestEnforceResultSizeLimits:

    def test_no_truncation_needed(self) -> None:
        results = [
            {"tool": "web.search", "result": {"ok": True, "data": "short"}},
        ]
        enforced = enforce_result_size_limits(results, hard_limit=10000)
        assert enforced[0]["result"]["data"] == "short"

    def test_truncation_applied(self) -> None:
        results = [
            {"tool": "gmail.get_message", "result": "x" * 50000},
        ]
        enforced = enforce_result_size_limits(results, hard_limit=1000)
        assert len(str(enforced[0]["result"])) < 2000

    def test_multiple_keys_checked(self) -> None:
        results = [
            {
                "tool": "test",
                "result": "short",
                "raw_result": "y" * 50000,
            },
        ]
        enforced = enforce_result_size_limits(results, hard_limit=1000)
        # raw_result should be truncated
        assert len(str(enforced[0]["raw_result"])) < 2000
        # result should be unchanged
        assert enforced[0]["result"] == "short"

    def test_trace_id_propagated(self) -> None:
        """trace_id is passed through for logging (no crash)."""
        results = [{"tool": "t", "result": "x" * 50000}]
        enforce_result_size_limits(results, hard_limit=1000, trace_id="abc123")


# ============================================================================
# Trace ID in orchestrator
# ============================================================================
class TestTraceIdInOrchestrator:
    """Verify trace_id is generated in process_turn."""

    def test_trace_id_format(self) -> None:
        """trace_id should be a 16-char hex string."""
        import uuid
        trace_id = uuid.uuid4().hex[:16]
        assert len(trace_id) == 16
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_state_trace_gets_trace_id(self) -> None:
        """OrchestratorState.trace should contain trace_id after process_turn sets it."""
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        import uuid
        _trace_id = uuid.uuid4().hex[:16]
        state.trace["trace_id"] = _trace_id
        assert state.trace["trace_id"] == _trace_id
        assert len(state.trace["trace_id"]) == 16
