"""Tests for Issue #524 — Tool-call trace viewer.

Covers:
  - ToolCallEntry: trace line + table row format
  - ToolCallLog: ring buffer (maxlen=20), record, stats, format_table
  - format_tools_command: /tools output
  - Ring buffer eviction (maxlen overflow)
  - Turn filtering, retry tracking
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════
# ToolCallEntry
# ═══════════════════════════════════════════════════════════════

class TestToolCallEntry:
    def test_defaults(self):
        from bantz.brain.tool_trace import ToolCallEntry
        e = ToolCallEntry()
        assert e.tool_name == ""
        assert e.success is True
        assert e.elapsed_ms == 0
        assert e.retried is False

    def test_trace_line_ok(self):
        from bantz.brain.tool_trace import ToolCallEntry
        e = ToolCallEntry(
            tool_name="calendar.list_events",
            success=True,
            elapsed_ms=340,
            result_summary="3 events",
        )
        line = e.to_trace_line()
        assert "[tool]" in line
        assert "calendar.list_events" in line
        assert "ok" in line
        assert "340ms" in line
        assert "3 events" in line

    def test_trace_line_fail(self):
        from bantz.brain.tool_trace import ToolCallEntry
        e = ToolCallEntry(
            tool_name="gmail.send",
            success=False,
            elapsed_ms=50,
            error="auth error",
        )
        line = e.to_trace_line()
        assert "FAIL" in line
        assert "auth error" in line

    def test_trace_line_retry(self):
        from bantz.brain.tool_trace import ToolCallEntry
        e = ToolCallEntry(
            tool_name="test.tool",
            success=True,
            elapsed_ms=100,
            result_summary="recovered",
            retried=True,
        )
        line = e.to_trace_line()
        assert "(retry)" in line

    def test_table_row_ok(self):
        from bantz.brain.tool_trace import ToolCallEntry
        e = ToolCallEntry(tool_name="time.now", success=True, elapsed_ms=5, result_summary="14:30")
        row = e.to_table_row()
        assert "✓" in row
        assert "time.now" in row

    def test_table_row_fail(self):
        from bantz.brain.tool_trace import ToolCallEntry
        e = ToolCallEntry(tool_name="test.tool", success=False, error="timeout")
        row = e.to_table_row()
        assert "✗" in row
        assert "timeout" in row


# ═══════════════════════════════════════════════════════════════
# ToolCallLog — Basic
# ═══════════════════════════════════════════════════════════════

class TestToolCallLogBasic:
    def test_empty_log(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        assert len(log) == 0
        assert log.last is None
        assert log.entries == []

    def test_record_single(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        entry = log.record("calendar.list_events", {"date": "2025-01-15"}, "3 events", True, 340)
        assert len(log) == 1
        assert log.last.tool_name == "calendar.list_events"
        assert entry.success is True
        assert entry.elapsed_ms == 340

    def test_record_multiple(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        log.record("time.now", success=True, elapsed_ms=5, result_summary="14:30")
        log.record("calendar.list_events", success=True, elapsed_ms=340, result_summary="3 events")
        log.record("gmail.send", success=False, elapsed_ms=50, error="auth")
        assert len(log) == 3
        assert log.last.tool_name == "gmail.send"


# ═══════════════════════════════════════════════════════════════
# ToolCallLog — Ring Buffer
# ═══════════════════════════════════════════════════════════════

class TestToolCallLogRingBuffer:
    def test_maxlen_default_20(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        assert log._maxlen == 20

    def test_maxlen_custom(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog(maxlen=5)
        assert log._maxlen == 5

    def test_eviction_on_overflow(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog(maxlen=3)
        for i in range(5):
            log.record(f"tool_{i}", success=True, elapsed_ms=i * 10, result_summary=f"result_{i}")
        assert len(log) == 3
        # Oldest should be tool_2 (0, 1 evicted)
        names = [e.tool_name for e in log.entries]
        assert names == ["tool_2", "tool_3", "tool_4"]


# ═══════════════════════════════════════════════════════════════
# ToolCallLog — Stats
# ═══════════════════════════════════════════════════════════════

class TestToolCallLogStats:
    def test_stats_empty(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        s = log.stats()
        assert s["total"] == 0
        assert s["ok"] == 0
        assert s["avg_ms"] == 0

    def test_stats_mixed(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        log.record("a", success=True, elapsed_ms=100)
        log.record("b", success=False, elapsed_ms=200, error="fail")
        log.record("c", success=True, elapsed_ms=300, retried=True)
        s = log.stats()
        assert s["total"] == 3
        assert s["ok"] == 2
        assert s["fail"] == 1
        assert s["retries"] == 1
        assert s["avg_ms"] == 200  # (100+200+300)//3


# ═══════════════════════════════════════════════════════════════
# ToolCallLog — Turn Filtering
# ═══════════════════════════════════════════════════════════════

class TestToolCallLogTurnFilter:
    def test_for_turn(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        log.record("a", success=True, turn_number=1)
        log.record("b", success=True, turn_number=1)
        log.record("c", success=True, turn_number=2)
        turn1 = log.for_turn(1)
        assert len(turn1) == 2
        turn2 = log.for_turn(2)
        assert len(turn2) == 1

    def test_for_turn_empty(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        log.record("a", success=True, turn_number=1)
        assert log.for_turn(99) == []


# ═══════════════════════════════════════════════════════════════
# ToolCallLog — Format Table
# ═══════════════════════════════════════════════════════════════

class TestToolCallLogFormatTable:
    def test_empty_table(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        table = log.format_table()
        assert "no tool calls" in table

    def test_table_with_entries(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        log.record("calendar.list_events", success=True, elapsed_ms=340, result_summary="3 events")
        log.record("gmail.send", success=False, elapsed_ms=50, error="auth")
        table = log.format_table()
        assert "Tool Call Log" in table
        assert "calendar.list_events" in table
        assert "gmail.send" in table
        assert "Total:" in table
        assert "OK: 1" in table
        assert "Fail: 1" in table


# ═══════════════════════════════════════════════════════════════
# format_tools_command
# ═══════════════════════════════════════════════════════════════

class TestFormatToolsCommand:
    def test_format_empty(self):
        from bantz.brain.tool_trace import ToolCallLog, format_tools_command
        log = ToolCallLog()
        out = format_tools_command(log)
        assert "Tool Call Trace Viewer" in out
        assert "no tool calls" in out

    def test_format_with_entries(self):
        from bantz.brain.tool_trace import ToolCallLog, format_tools_command
        log = ToolCallLog()
        log.record("time.now", success=True, elapsed_ms=5, result_summary="14:30")
        out = format_tools_command(log)
        assert "🔧" in out
        assert "time.now" in out

    def test_clear(self):
        from bantz.brain.tool_trace import ToolCallLog
        log = ToolCallLog()
        log.record("a", success=True)
        log.record("b", success=True)
        assert len(log) == 2
        log.clear()
        assert len(log) == 0
