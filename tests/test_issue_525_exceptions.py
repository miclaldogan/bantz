"""Tests for Issue #525 — No silent exception policy.

Covers:
  - generate_turn_id: format, uniqueness
  - ErrorContext: structured log dict
  - BantzError: base exception with correlation + log
  - RouterParseError: raw_text truncation, phase=router
  - ToolExecutionError: tool_name, original_error
  - FinalizerError: finalizer_type
  - MemoryError_: operation tracking
  - SafetyViolationError: violation_type, tool_name
  - Exception hierarchy: all subclass BantzError
  - Structured message format: [turn:X] [phase] message
"""

from __future__ import annotations

import logging
import re

import pytest


# ═══════════════════════════════════════════════════════════════
# generate_turn_id
# ═══════════════════════════════════════════════════════════════

class TestGenerateTurnId:
    def test_format(self):
        from bantz.brain.exceptions import generate_turn_id
        tid = generate_turn_id()
        assert tid.startswith("t-")
        assert len(tid) == 10  # "t-" + 8 hex chars

    def test_uniqueness(self):
        from bantz.brain.exceptions import generate_turn_id
        ids = {generate_turn_id() for _ in range(100)}
        assert len(ids) == 100

    def test_hex_chars(self):
        from bantz.brain.exceptions import generate_turn_id
        tid = generate_turn_id()
        hex_part = tid[2:]
        assert re.match(r"^[0-9a-f]{8}$", hex_part)


# ═══════════════════════════════════════════════════════════════
# ErrorContext
# ═══════════════════════════════════════════════════════════════

class TestErrorContext:
    def test_defaults(self):
        from bantz.brain.exceptions import ErrorContext
        ctx = ErrorContext()
        assert ctx.turn_id == ""
        assert ctx.phase == ""
        assert ctx.component == ""
        assert ctx.timestamp  # non-empty

    def test_to_log_dict(self):
        from bantz.brain.exceptions import ErrorContext
        ctx = ErrorContext(
            turn_id="t-abc12345",
            phase="router",
            component="llm_router._parse_json",
            metadata={"raw_text": "bad json"},
        )
        d = ctx.to_log_dict()
        assert d["turn_id"] == "t-abc12345"
        assert d["phase"] == "router"
        assert d["component"] == "llm_router._parse_json"
        assert d["raw_text"] == "bad json"
        assert "timestamp" in d


# ═══════════════════════════════════════════════════════════════
# BantzError
# ═══════════════════════════════════════════════════════════════

class TestBantzError:
    def test_basic(self):
        from bantz.brain.exceptions import BantzError
        err = BantzError("something broke")
        assert "something broke" in str(err)
        assert err.bantz_message == "something broke"

    def test_with_turn_id(self):
        from bantz.brain.exceptions import BantzError
        err = BantzError("bad", turn_id="t-12345678", phase="router")
        msg = str(err)
        assert "[turn:t-12345678]" in msg
        assert "[router]" in msg

    def test_context_attached(self):
        from bantz.brain.exceptions import BantzError, ErrorContext
        ctx = ErrorContext(turn_id="t-aabbccdd", phase="tool")
        err = BantzError("fail", context=ctx)
        assert err.context.turn_id == "t-aabbccdd"

    def test_log_method(self, caplog):
        from bantz.brain.exceptions import BantzError
        err = BantzError("test error", turn_id="t-logtest1", phase="test")
        with caplog.at_level(logging.WARNING):
            err.log(logging.WARNING)
        assert "BantzError" in caplog.text
        assert "test error" in caplog.text

    def test_is_exception(self):
        from bantz.brain.exceptions import BantzError
        assert issubclass(BantzError, Exception)


# ═══════════════════════════════════════════════════════════════
# RouterParseError
# ═══════════════════════════════════════════════════════════════

class TestRouterParseError:
    def test_basic(self):
        from bantz.brain.exceptions import RouterParseError
        err = RouterParseError(turn_id="t-rp123456", raw_text='{"bad json')
        assert err.raw_text == '{"bad json'
        assert err.context.phase == "router"
        assert "llm_router._parse_json" in err.context.component

    def test_raw_text_truncation(self):
        from bantz.brain.exceptions import RouterParseError
        long_text = "x" * 500
        err = RouterParseError(raw_text=long_text)
        assert len(err.raw_text) == 200

    def test_subclass(self):
        from bantz.brain.exceptions import BantzError, RouterParseError
        assert issubclass(RouterParseError, BantzError)

    def test_message_format(self):
        from bantz.brain.exceptions import RouterParseError
        err = RouterParseError("custom msg", turn_id="t-fmt12345")
        assert "[turn:t-fmt12345]" in str(err)
        assert "[router]" in str(err)
        assert "custom msg" in str(err)


# ═══════════════════════════════════════════════════════════════
# ToolExecutionError
# ═══════════════════════════════════════════════════════════════

class TestToolExecutionError:
    def test_basic(self):
        from bantz.brain.exceptions import ToolExecutionError
        err = ToolExecutionError(
            "calendar API timeout",
            turn_id="t-te123456",
            tool_name="calendar.list_events",
            original_error="ReadTimeout",
        )
        assert err.tool_name == "calendar.list_events"
        assert err.original_error == "ReadTimeout"
        assert err.context.phase == "tool"
        assert "calendar.list_events" in err.context.component

    def test_subclass(self):
        from bantz.brain.exceptions import BantzError, ToolExecutionError
        assert issubclass(ToolExecutionError, BantzError)


# ═══════════════════════════════════════════════════════════════
# FinalizerError
# ═══════════════════════════════════════════════════════════════

class TestFinalizerError:
    def test_basic(self):
        from bantz.brain.exceptions import FinalizerError
        err = FinalizerError(
            "Gemini rate limited",
            turn_id="t-fe123456",
            finalizer_type="gemini",
        )
        assert err.finalizer_type == "gemini"
        assert err.context.phase == "finalizer"
        assert "gemini" in err.context.component

    def test_subclass(self):
        from bantz.brain.exceptions import BantzError, FinalizerError
        assert issubclass(FinalizerError, BantzError)


# ═══════════════════════════════════════════════════════════════
# MemoryError_
# ═══════════════════════════════════════════════════════════════

class TestMemoryError:
    def test_basic(self):
        from bantz.brain.exceptions import MemoryError_
        err = MemoryError_(
            "Token budget overflow",
            turn_id="t-me123456",
            operation="trim",
        )
        assert err.operation == "trim"
        assert err.context.phase == "memory"
        assert "trim" in err.context.component

    def test_no_shadow_builtin(self):
        """MemoryError_ does NOT shadow built-in MemoryError."""
        from bantz.brain.exceptions import MemoryError_
        assert MemoryError_ is not MemoryError

    def test_subclass(self):
        from bantz.brain.exceptions import BantzError, MemoryError_
        assert issubclass(MemoryError_, BantzError)


# ═══════════════════════════════════════════════════════════════
# SafetyViolationError
# ═══════════════════════════════════════════════════════════════

class TestSafetyViolationError:
    def test_basic(self):
        from bantz.brain.exceptions import SafetyViolationError
        err = SafetyViolationError(
            "Tool blocked by denylist",
            turn_id="t-sv123456",
            violation_type="denylist",
            tool_name="system.exec",
        )
        assert err.violation_type == "denylist"
        assert err.tool_name == "system.exec"
        assert err.context.phase == "safety"

    def test_subclass(self):
        from bantz.brain.exceptions import BantzError, SafetyViolationError
        assert issubclass(SafetyViolationError, BantzError)


# ═══════════════════════════════════════════════════════════════
# Hierarchy
# ═══════════════════════════════════════════════════════════════

class TestExceptionHierarchy:
    def test_all_subclass_bantz_error(self):
        from bantz.brain.exceptions import (
            BantzError,
            FinalizerError,
            MemoryError_,
            RouterParseError,
            SafetyViolationError,
            ToolExecutionError,
        )
        for cls in [RouterParseError, ToolExecutionError, FinalizerError, MemoryError_, SafetyViolationError]:
            assert issubclass(cls, BantzError), f"{cls.__name__} should subclass BantzError"
            assert issubclass(cls, Exception), f"{cls.__name__} should subclass Exception"

    def test_catch_all_bantz_error(self):
        """All typed exceptions can be caught with `except BantzError`."""
        from bantz.brain.exceptions import (
            BantzError,
            FinalizerError,
            MemoryError_,
            RouterParseError,
            SafetyViolationError,
            ToolExecutionError,
        )
        for cls in [RouterParseError, ToolExecutionError, FinalizerError, MemoryError_, SafetyViolationError]:
            try:
                raise cls("test")
            except BantzError:
                pass  # Expected
            except Exception:
                pytest.fail(f"{cls.__name__} not caught by BantzError")

    def test_five_typed_exceptions(self):
        """Issue #525 requires at least 5 typed exception classes."""
        from bantz.brain import exceptions
        error_classes = [
            attr for attr in dir(exceptions)
            if isinstance(getattr(exceptions, attr), type)
            and issubclass(getattr(exceptions, attr), Exception)
            and getattr(exceptions, attr) is not Exception
        ]
        # BantzError + 5 subtypes = 6+
        assert len(error_classes) >= 6, f"Expected ≥6, got {len(error_classes)}: {error_classes}"

    def test_chaining_from_json_error(self):
        """RouterParseError can chain from json.JSONDecodeError."""
        import json
        from bantz.brain.exceptions import RouterParseError
        try:
            try:
                json.loads("{bad")
            except json.JSONDecodeError as e:
                raise RouterParseError(
                    "parse failed", turn_id="t-chain123", raw_text="{bad"
                ) from e
        except RouterParseError as rpe:
            assert rpe.__cause__ is not None
            assert isinstance(rpe.__cause__, json.JSONDecodeError)
