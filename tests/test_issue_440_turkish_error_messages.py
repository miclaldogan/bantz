"""Tests for Issue #440 — Turkish Error Messages.

Covers:
- All error codes have Turkish messages
- Format arguments work
- Fallback for unknown codes
- ErrorCode lookup
- Retriable error classification
- No English leakage
"""

from __future__ import annotations

import re
import pytest

from bantz.i18n.messages import (
    ErrorCode,
    tr,
    get_all_messages,
    get_error_code,
    is_retriable,
    _FALLBACK_TR,
)


# ─── Basic message lookup ───────────────────────────────────────


class TestTrFunction:
    def test_simple_lookup(self):
        msg = tr(ErrorCode.LLM_TIMEOUT)
        assert "yanıt vermedi" in msg

    def test_with_format_args(self):
        msg = tr(ErrorCode.TOOL_FAILED, tool_name="takvim")
        assert "takvim" in msg

    def test_unknown_code_returns_fallback(self):
        msg = tr("totally_unknown_code_xyz")
        assert msg == _FALLBACK_TR

    def test_string_code_lookup(self):
        msg = tr("llm_timeout")
        assert "yanıt vermedi" in msg

    def test_format_missing_arg_graceful(self):
        """If format arg is missing, return template without crashing."""
        msg = tr(ErrorCode.TOOL_FAILED)  # tool_name not provided
        assert "{tool_name}" in msg or "hata" in msg.lower()


# ─── All codes have messages ────────────────────────────────────


class TestCompleteness:
    def test_all_error_codes_have_messages(self):
        msgs = get_all_messages()
        for code in ErrorCode:
            assert code.value in msgs, f"Missing Turkish message for {code.value}"

    def test_no_empty_messages(self):
        msgs = get_all_messages()
        for code, msg in msgs.items():
            assert len(msg.strip()) > 0, f"Empty message for {code}"


# ─── No English leakage ─────────────────────────────────────────


class TestNoEnglishLeakage:
    """Verify messages are actually in Turkish, not English placeholders."""

    # Common English error words that should NOT appear
    _ENGLISH_WORDS = [
        "error occurred",
        "please try again",
        "failed to",
        "unable to",
        "connection refused",
        "timeout error",
        "internal server error",
        "something went wrong",
    ]

    def test_no_english_in_messages(self):
        msgs = get_all_messages()
        for code, msg in msgs.items():
            lower = msg.lower()
            for eng in self._ENGLISH_WORDS:
                assert eng not in lower, (
                    f"English text '{eng}' found in message for {code}: {msg}"
                )

    def test_messages_contain_turkish_chars(self):
        """At least some messages should contain Turkish-specific characters."""
        msgs = get_all_messages()
        all_text = " ".join(msgs.values())
        # Turkish chars: ç, ğ, ı, ö, ş, ü, İ
        turkish_chars = set("çğıöşüİâ")
        found = set(c for c in all_text if c in turkish_chars)
        assert len(found) >= 3, f"Too few Turkish chars found: {found}"


# ─── Error code lookup ──────────────────────────────────────────


class TestErrorCodeLookup:
    def test_valid_code(self):
        ec = get_error_code("llm_timeout")
        assert ec == ErrorCode.LLM_TIMEOUT

    def test_invalid_code(self):
        ec = get_error_code("not_a_real_code")
        assert ec == ErrorCode.UNKNOWN

    def test_all_codes_roundtrip(self):
        for code in ErrorCode:
            assert get_error_code(code.value) == code


# ─── Retriable classification ───────────────────────────────────


class TestRetriable:
    def test_timeout_is_retriable(self):
        assert is_retriable(ErrorCode.LLM_TIMEOUT)

    def test_overloaded_is_retriable(self):
        assert is_retriable(ErrorCode.LLM_OVERLOADED)

    def test_policy_blocked_not_retriable(self):
        assert not is_retriable(ErrorCode.SECURITY_POLICY_BLOCKED)

    def test_injection_not_retriable(self):
        assert not is_retriable(ErrorCode.SECURITY_INJECTION_DETECTED)

    def test_string_code_retriable(self):
        assert is_retriable("llm_timeout")

    def test_unknown_not_retriable(self):
        assert not is_retriable("totally_unknown")

    def test_voice_recognition_retriable(self):
        assert is_retriable(ErrorCode.VOICE_RECOGNITION_FAILED)


# ─── Specific message content ───────────────────────────────────


class TestSpecificMessages:
    def test_gemini_fallback_mentions_fast_model(self):
        msg = tr(ErrorCode.GEMINI_UNAVAILABLE)
        assert "hızlı model" in msg.lower() or "devam" in msg.lower()

    def test_voice_noisy_mentions_sessiz(self):
        msg = tr(ErrorCode.VOICE_TOO_NOISY)
        assert "sessiz" in msg.lower() or "gürültü" in msg.lower()

    def test_calendar_auth_mentions_giris(self):
        msg = tr(ErrorCode.CALENDAR_AUTH_EXPIRED)
        assert "giriş" in msg.lower()

    def test_security_confirmation_is_question(self):
        msg = tr(ErrorCode.SECURITY_CONFIRMATION_REQUIRED)
        assert "?" in msg

    def test_router_no_match_polite(self):
        msg = tr(ErrorCode.ROUTER_NO_MATCH)
        assert "lütfen" in msg.lower()

    def test_memory_low_warns(self):
        msg = tr(ErrorCode.SYSTEM_MEMORY_LOW)
        assert "bellek" in msg.lower() or "yavaş" in msg.lower()
