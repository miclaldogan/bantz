"""Tests for Issue #523 — Plan→Act→Verify loop.

Covers:
  - VerifyConfig: defaults + custom
  - ToolVerification: single tool outcome tracking
  - verify_tool_results: ok / empty / error / retry scenarios
  - VerifyTrace: trace line format
  - Retry with callback
  - Mixed results (some ok, some fail)
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════
# VerifyConfig
# ═══════════════════════════════════════════════════════════════

class TestVerifyConfig:
    def test_defaults(self):
        from bantz.brain.verify_results import VerifyConfig
        cfg = VerifyConfig()
        assert cfg.max_retries == 1
        assert cfg.retry_empty is True
        assert cfg.retry_errors is True
        assert cfg.timeout_seconds is None

    def test_custom(self):
        from bantz.brain.verify_results import VerifyConfig
        cfg = VerifyConfig(max_retries=3, retry_empty=False, timeout_seconds=5.0)
        assert cfg.max_retries == 3
        assert cfg.retry_empty is False
        assert cfg.timeout_seconds == 5.0


# ═══════════════════════════════════════════════════════════════
# VerifyTrace
# ═══════════════════════════════════════════════════════════════

class TestVerifyTrace:
    def test_trace_line_no_results(self):
        from bantz.brain.verify_results import VerifyTrace
        t = VerifyTrace(turn_number=1, result=None)
        assert "skipped" in t.to_trace_line()

    def test_trace_line_with_result(self):
        from bantz.brain.verify_results import VerifyResult, VerifyTrace
        vr = VerifyResult(verified=True, tools_ok=2, tools_retry=0, tools_fail=0, elapsed_ms=5)
        t = VerifyTrace(turn_number=1, result=vr)
        line = t.to_trace_line()
        assert "[verify]" in line
        assert "verified=True" in line
        assert "tools_ok=2" in line
        assert "tools_retry=0" in line
        assert "tools_fail=0" in line

    def test_trace_line_with_failures(self):
        from bantz.brain.verify_results import VerifyResult, VerifyTrace
        vr = VerifyResult(verified=False, tools_ok=1, tools_retry=1, tools_fail=1, elapsed_ms=12)
        t = VerifyTrace(turn_number=2, result=vr)
        line = t.to_trace_line()
        assert "verified=False" in line
        assert "tools_fail=1" in line


# ═══════════════════════════════════════════════════════════════
# verify_tool_results — All OK
# ═══════════════════════════════════════════════════════════════

class TestVerifyAllOk:
    def test_all_successful(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [
            {"tool": "calendar.list_events", "success": True, "result": [{"id": 1}], "result_summary": "1 event"},
            {"tool": "time.now", "success": True, "result": "14:00", "result_summary": "14:00"},
        ]
        vr = verify_tool_results(results)
        assert vr.verified is True
        assert vr.tools_ok == 2
        assert vr.tools_retry == 0
        assert vr.tools_fail == 0
        assert len(vr.verified_results) == 2

    def test_empty_results_list(self):
        from bantz.brain.verify_results import verify_tool_results
        vr = verify_tool_results([])
        assert vr.verified is True
        assert vr.tools_ok == 0
        assert vr.tools_fail == 0


# ═══════════════════════════════════════════════════════════════
# verify_tool_results — Empty detection
# ═══════════════════════════════════════════════════════════════

class TestVerifyEmpty:
    def test_empty_result_none(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [{"tool": "calendar.list_events", "success": True, "result": None, "result_summary": ""}]
        vr = verify_tool_results(results)
        assert vr.verified is False
        assert vr.tools_fail == 1

    def test_empty_result_empty_string(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [{"tool": "test.tool", "success": True, "result": "", "result_summary": ""}]
        vr = verify_tool_results(results)
        assert vr.verified is False
        assert vr.tools_fail == 1

    def test_empty_result_empty_list(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [{"tool": "test.tool", "success": True, "result": [], "result_summary": ""}]
        vr = verify_tool_results(results)
        assert vr.verified is False

    def test_empty_result_empty_dict(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [{"tool": "test.tool", "success": True, "result": {}, "result_summary": ""}]
        vr = verify_tool_results(results)
        assert vr.verified is False


# ═══════════════════════════════════════════════════════════════
# verify_tool_results — Error detection
# ═══════════════════════════════════════════════════════════════

class TestVerifyErrors:
    def test_error_success_false(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [{"tool": "calendar.create_event", "success": False, "error": "API error"}]
        vr = verify_tool_results(results)
        assert vr.verified is False
        assert vr.tools_fail == 1

    def test_error_has_error_key(self):
        from bantz.brain.verify_results import verify_tool_results
        results = [{"tool": "test.tool", "success": True, "error": "timeout", "result": "partial"}]
        vr = verify_tool_results(results)
        assert vr.verified is False


# ═══════════════════════════════════════════════════════════════
# verify_tool_results — Retry
# ═══════════════════════════════════════════════════════════════

class TestVerifyRetry:
    def test_retry_success(self):
        from bantz.brain.verify_results import VerifyConfig, verify_tool_results

        def retry_fn(tool_name, original):
            return {"tool": tool_name, "success": True, "result": "recovered", "result_summary": "ok"}

        results = [{"tool": "calendar.list_events", "success": False, "error": "timeout"}]
        vr = verify_tool_results(results, config=VerifyConfig(max_retries=1), retry_fn=retry_fn)
        assert vr.verified is True
        assert vr.tools_retry == 1
        assert vr.tools_ok == 1
        assert vr.tools_fail == 0
        assert vr.verified_results[0].get("_retried") is True

    def test_retry_fails_again(self):
        from bantz.brain.verify_results import VerifyConfig, verify_tool_results

        def retry_fn(tool_name, original):
            return {"tool": tool_name, "success": False, "error": "still broken"}

        results = [{"tool": "test.tool", "success": False, "error": "broken"}]
        vr = verify_tool_results(results, config=VerifyConfig(max_retries=1), retry_fn=retry_fn)
        assert vr.verified is False
        assert vr.tools_retry == 1
        assert vr.tools_fail == 1

    def test_retry_raises_exception(self):
        from bantz.brain.verify_results import VerifyConfig, verify_tool_results

        def retry_fn(tool_name, original):
            raise RuntimeError("kaboom")

        results = [{"tool": "test.tool", "success": False, "error": "bad"}]
        vr = verify_tool_results(results, config=VerifyConfig(max_retries=1), retry_fn=retry_fn)
        assert vr.verified is False
        assert vr.tools_fail == 1

    def test_no_retry_when_disabled(self):
        from bantz.brain.verify_results import VerifyConfig, verify_tool_results

        called = []

        def retry_fn(tool_name, original):
            called.append(tool_name)
            return {"tool": tool_name, "success": True, "result": "ok", "result_summary": "ok"}

        results = [{"tool": "test.tool", "success": False, "error": "fail"}]
        vr = verify_tool_results(results, config=VerifyConfig(max_retries=0), retry_fn=retry_fn)
        assert len(called) == 0  # retry_fn never called
        assert vr.tools_fail == 1

    def test_no_retry_without_callback(self):
        from bantz.brain.verify_results import verify_tool_results

        results = [{"tool": "test.tool", "success": False, "error": "fail"}]
        vr = verify_tool_results(results, retry_fn=None)
        assert vr.tools_fail == 1

    def test_retry_empty_result(self):
        from bantz.brain.verify_results import VerifyConfig, verify_tool_results

        def retry_fn(tool_name, original):
            return {"tool": tool_name, "success": True, "result": "data", "result_summary": "data"}

        results = [{"tool": "test.tool", "success": True, "result": None, "result_summary": ""}]
        vr = verify_tool_results(results, config=VerifyConfig(retry_empty=True), retry_fn=retry_fn)
        assert vr.verified is True
        assert vr.tools_retry == 1
        assert vr.tools_ok == 1


# ═══════════════════════════════════════════════════════════════
# verify_tool_results — Mixed
# ═══════════════════════════════════════════════════════════════

class TestVerifyMixed:
    def test_mixed_ok_and_fail(self):
        from bantz.brain.verify_results import verify_tool_results

        results = [
            {"tool": "calendar.list_events", "success": True, "result": [{"id": 1}], "result_summary": "1 event"},
            {"tool": "gmail.send", "success": False, "error": "auth failed"},
        ]
        vr = verify_tool_results(results)
        assert vr.verified is False
        assert vr.tools_ok == 1
        assert vr.tools_fail == 1
        assert len(vr.verified_results) == 2

    def test_tool_verifications_tracked(self):
        from bantz.brain.verify_results import verify_tool_results

        results = [
            {"tool": "a", "success": True, "result": "ok", "result_summary": "ok"},
            {"tool": "b", "success": False, "error": "fail"},
        ]
        vr = verify_tool_results(results)
        assert len(vr.tool_verifications) == 2
        assert vr.tool_verifications[0].tool_name == "a"
        assert vr.tool_verifications[0].final_success is True
        assert vr.tool_verifications[1].tool_name == "b"
        assert vr.tool_verifications[1].final_success is False
