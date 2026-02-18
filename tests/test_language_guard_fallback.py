# SPDX-License-Identifier: MIT
"""Issue #1232: Language guard TR fallback tests.

When the language guard rejects non-Turkish LLM output, the system must
return a route-aware Turkish fallback instead of the generic "Efendim,
isteğiniz işlendi."
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from bantz.brain.finalization_pipeline import (
    _LANG_FALLBACK,
    _ROUTE_FALLBACK_TEMPLATES,
    _route_aware_fallback,
    _validate_reply_language,
)


# ── _route_aware_fallback tests ─────────────────────────────────────────────

class TestRouteAwareFallback:
    """Route-aware fallback must return meaningful Turkish messages."""

    def test_calendar_route(self) -> None:
        msg = _route_aware_fallback(route="calendar")
        assert "takvim" in msg.lower()
        assert msg != _LANG_FALLBACK

    def test_gmail_route(self) -> None:
        msg = _route_aware_fallback(route="gmail")
        assert "posta" in msg.lower() or "mail" in msg.lower()
        assert msg != _LANG_FALLBACK

    def test_system_route(self) -> None:
        msg = _route_aware_fallback(route="system")
        assert "sistem" in msg.lower()
        assert msg != _LANG_FALLBACK

    def test_smalltalk_route(self) -> None:
        msg = _route_aware_fallback(route="smalltalk")
        assert "efendim" in msg.lower()
        assert msg != _LANG_FALLBACK

    def test_unknown_route_uses_generic(self) -> None:
        msg = _route_aware_fallback(route="unknown")
        assert msg == _LANG_FALLBACK

    def test_none_route_uses_generic(self) -> None:
        msg = _route_aware_fallback(route=None)
        assert msg == _LANG_FALLBACK

    def test_tool_results_summary_preferred(self) -> None:
        """When tool results are available, their summary takes priority."""
        tool_results = [
            {
                "tool": "calendar.list_events",
                "success": True,
                "raw_result": {
                    "ok": True,
                    "events": [
                        {
                            "id": "e1",
                            "summary": "Standup",
                            "start": {"dateTime": "2025-01-15T09:00:00+03:00"},
                            "end": {"dateTime": "2025-01-15T09:30:00+03:00"},
                        }
                    ],
                },
            }
        ]
        msg = _route_aware_fallback(route="calendar", tool_results=tool_results)
        # Should contain event details from tool results, not generic template
        assert "standup" in msg.lower() or "etkinlik" in msg.lower() or "#1" in msg

    def test_failed_tool_results_fall_to_template(self) -> None:
        """If all tools failed, fall back to route template."""
        tool_results = [
            {"tool": "gmail.list_messages", "success": False, "error": "timeout"},
        ]
        msg = _route_aware_fallback(route="gmail", tool_results=tool_results)
        # Should use gmail template since no successes
        assert "posta" in msg.lower() or "mail" in msg.lower()


# ── _validate_reply_language tests ──────────────────────────────────────────

class TestValidateReplyLanguage:
    """Language validation must use route-aware fallback when rejecting."""

    def test_turkish_text_passes(self) -> None:
        """Turkish text should pass through unchanged."""
        text = "Merhaba efendim, takvim bilgileriniz güncellendi."
        result = _validate_reply_language(text, route="calendar")
        assert result == text

    def test_english_text_rejected_with_route(self) -> None:
        """English text on calendar route → calendar-specific fallback."""
        with patch("bantz.brain.language_guard.validate_turkish") as mock_vt:
            mock_vt.return_value = ("__LANG_GUARD_REJECTED__", False)
            result = _validate_reply_language(
                "Here are your calendar events for today.",
                route="calendar",
            )
            assert "takvim" in result.lower()
            assert result != _LANG_FALLBACK

    def test_english_text_rejected_with_gmail_route(self) -> None:
        """English text on gmail route → gmail-specific fallback."""
        with patch("bantz.brain.language_guard.validate_turkish") as mock_vt:
            mock_vt.return_value = ("__LANG_GUARD_REJECTED__", False)
            result = _validate_reply_language(
                "You have 3 new emails in your inbox.",
                route="gmail",
            )
            assert "posta" in result.lower() or "mail" in result.lower()

    def test_english_text_rejected_no_route_uses_generic(self) -> None:
        """English text with no route → generic fallback."""
        with patch("bantz.brain.language_guard.validate_turkish") as mock_vt:
            mock_vt.return_value = ("__LANG_GUARD_REJECTED__", False)
            result = _validate_reply_language(
                "This is an English response from the model.",
            )
            assert result == _LANG_FALLBACK

    def test_rejected_with_tool_results(self) -> None:
        """When rejected with tool results, prefer tool summary."""
        tool_results = [
            {
                "tool": "calendar.create_event",
                "success": True,
                "raw_result": {
                    "ok": True,
                    "event": {"summary": "Meeting", "start": {"dateTime": "2025-01-15T09:00:00+03:00"}},
                },
            }
        ]
        with patch("bantz.brain.language_guard.validate_turkish") as mock_vt:
            mock_vt.return_value = ("__LANG_GUARD_REJECTED__", False)
            result = _validate_reply_language(
                "Event created successfully.",
                route="calendar",
                tool_results=tool_results,
            )
            assert result != _LANG_FALLBACK
            # Should be a meaningful Turkish response
            assert len(result) > 10


# ── All route templates are Turkish ─────────────────────────────────────────

class TestRouteTemplateQuality:
    """All fallback templates must be proper Turkish."""

    def test_all_templates_non_empty(self) -> None:
        for route, template in _ROUTE_FALLBACK_TEMPLATES.items():
            assert template.strip(), f"Template for {route} is empty"

    def test_all_templates_contain_efendim(self) -> None:
        for route, template in _ROUTE_FALLBACK_TEMPLATES.items():
            assert "efendim" in template.lower(), f"Template for {route} missing 'efendim'"

    def test_no_english_in_templates(self) -> None:
        en_words = {"the", "your", "event", "email", "system", "hello"}
        for route, template in _ROUTE_FALLBACK_TEMPLATES.items():
            tokens = set(template.lower().split())
            overlap = tokens & en_words
            assert not overlap, f"Template for {route} has English: {overlap}"

    def test_generic_fallback_not_in_route_templates(self) -> None:
        """No route template should be identical to the generic fallback."""
        for route, template in _ROUTE_FALLBACK_TEMPLATES.items():
            assert template != _LANG_FALLBACK, f"Template for {route} is same as generic"
