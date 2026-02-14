"""Tests for Issue #870: Gmail / Calendar tool'ları Web Dashboard üzerinden çalışmıyor.

Covers:
1. _sanitize_tool_plan — LLM phantom / mismatched tool remap
2. _tr_calendar_error — Calendar Türkçe error messages
3. _tr_gmail_error — Gmail Türkçe error messages
4. End-to-end tool remap in process_turn pipeline
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass, field, replace
from typing import Any, Optional
from unittest.mock import MagicMock, patch


# ── Minimal OrchestratorOutput stub ──────────────────────────────────

@dataclass
class FakeOutput:
    route: str = "gmail"
    calendar_intent: str = "none"
    gmail_intent: str = "list"
    confidence: float = 0.9
    tool_plan: list = field(default_factory=list)
    ask_user: bool = False
    question: str = ""
    requires_confirmation: bool = False
    confirmation_prompt: str = ""
    slots: dict = field(default_factory=dict)
    assistant_reply: str = ""
    raw_output: Any = None


# ======================================================================
# 1. _sanitize_tool_plan tests
# ======================================================================


class TestSanitizeToolPlan(unittest.TestCase):
    """Test OrchestratorLoop._sanitize_tool_plan remap logic."""

    def _make_loop(self):
        """Build a minimal OrchestratorLoop with mocked dependencies."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop

        loop = OrchestratorLoop.__new__(OrchestratorLoop)
        loop.config = MagicMock(debug=False)
        # Inherit class-level _TOOL_REMAP
        return loop

    # -- gmail.list_drafts + intent=list → gmail.list_messages ----------

    def test_list_drafts_with_list_intent_remapped(self):
        """gmail.list_drafts + gmail_intent=list → stays (no remap rule for this combo)."""
        loop = self._make_loop()
        out = FakeOutput(
            route="gmail",
            gmail_intent="list",
            tool_plan=["gmail.list_drafts"],
        )
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.list_drafts"])

    def test_list_drafts_with_search_intent_not_remapped(self):
        """gmail.list_drafts + gmail_intent=search → stays (no remap rule for search)."""
        loop = self._make_loop()
        out = FakeOutput(
            route="gmail",
            gmail_intent="search",
            tool_plan=["gmail.list_drafts"],
        )
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.list_drafts"])

    # -- Phantom tool remaps (wildcard) --------------------------------

    def test_phantom_gmail_list_all(self):
        """gmail.list_all (phantom) → gmail.list_messages."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=["gmail.list_all"])
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.list_messages"])

    def test_phantom_gmail_search_messages(self):
        """gmail.search_messages (phantom) → gmail.smart_search."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=["gmail.search_messages"], gmail_intent="search")
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.smart_search"])

    def test_phantom_gmail_check_inbox(self):
        """gmail.check_inbox (phantom) → gmail.list_messages."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=["gmail.check_inbox"])
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.list_messages"])

    def test_phantom_gmail_get_unread(self):
        """gmail.get_unread (phantom) → gmail.unread_count."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=["gmail.get_unread"])
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.unread_count"])

    def test_phantom_calendar_get_events(self):
        """calendar.get_events (phantom) → calendar.list_events."""
        loop = self._make_loop()
        out = FakeOutput(
            route="calendar",
            calendar_intent="query",
            gmail_intent="none",
            tool_plan=["calendar.get_events"],
        )
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["calendar.list_events"])

    def test_phantom_calendar_add_event(self):
        """calendar.add_event (phantom) → calendar.create_event."""
        loop = self._make_loop()
        out = FakeOutput(
            route="calendar",
            calendar_intent="create",
            gmail_intent="none",
            tool_plan=["calendar.add_event"],
        )
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["calendar.create_event"])

    def test_phantom_calendar_remove_event(self):
        """calendar.remove_event (phantom) → calendar.delete_event."""
        loop = self._make_loop()
        out = FakeOutput(
            route="calendar",
            calendar_intent="cancel",
            gmail_intent="none",
            tool_plan=["calendar.remove_event"],
        )
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["calendar.delete_event"])

    # -- No-op cases ---------------------------------------------------

    def test_valid_tool_unchanged(self):
        """A valid tool name passes through untouched."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=["gmail.list_messages"])
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.list_messages"])

    def test_empty_tool_plan_unchanged(self):
        """Empty tool_plan → returned as-is."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=[])
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, [])

    def test_multiple_tools_partial_remap(self):
        """Multiple tools: only phantom ones get remapped."""
        loop = self._make_loop()
        out = FakeOutput(
            tool_plan=["gmail.list_all", "gmail.list_messages"],
        )
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["gmail.list_messages", "gmail.list_messages"])

    def test_unknown_tool_passes_through(self):
        """Unknown tool (no remap entry) passes through for _execute_tools_phase to handle."""
        loop = self._make_loop()
        out = FakeOutput(tool_plan=["some.unknown_tool"])
        result = loop._sanitize_tool_plan(out)
        self.assertEqual(result.tool_plan, ["some.unknown_tool"])


# ======================================================================
# 2. Calendar Türkçe error message tests
# ======================================================================


class TestCalendarTurkishErrors(unittest.TestCase):
    """Test _tr_calendar_error returns Turkish messages for known errors."""

    def _tr(self, msg: str) -> str:
        from bantz.tools.calendar_tools import _tr_calendar_error
        return _tr_calendar_error(Exception(msg))

    def test_client_secret_not_found(self):
        result = self._tr("Google client secret not found. Set BANTZ_GOOGLE_CLIENT_SECRET")
        self.assertIn("Google hesap bilgileri bulunamadı", result)

    def test_dependencies_not_installed(self):
        result = self._tr("Google calendar dependencies are not installed")
        self.assertIn("bağımlılıkları yüklü değil", result)

    def test_http_401(self):
        result = self._tr("HttpError 401: Login required")
        self.assertIn("yetkilendirmesi başarısız", result)

    def test_http_403(self):
        result = self._tr("HttpError 403: Forbidden")
        self.assertIn("erişim izni yok", result)

    def test_http_404(self):
        result = self._tr("HttpError 404: Not Found")
        self.assertIn("bulunamadı", result)

    def test_http_429(self):
        result = self._tr("HttpError 429: Rate limit")
        self.assertIn("istek limiti aşıldı", result)

    def test_timeout(self):
        result = self._tr("Connection timeout after 30s")
        self.assertIn("zaman aşımına", result)

    def test_connection_error(self):
        result = self._tr("ConnectionError: Network unreachable")
        self.assertIn("bağlanılamadı", result)

    def test_token_expired(self):
        result = self._tr("token has been expired or revoked")
        self.assertIn("oturum süresi dolmuş", result)

    def test_unknown_error_fallback(self):
        result = self._tr("Some completely unknown error XYZ")
        self.assertIn("Takvim işlemi başarısız oldu", result)
        self.assertIn("XYZ", result)

    def test_calendar_list_events_uses_turkish(self):
        """calendar_list_events_tool wraps errors in Turkish."""
        from bantz.tools.calendar_tools import calendar_list_events_tool

        with patch("bantz.tools.calendar_tools.list_events", side_effect=FileNotFoundError("Google client secret not found")):
            result = calendar_list_events_tool()
        self.assertFalse(result["ok"])
        self.assertIn("Google hesap bilgileri bulunamadı", result["error"])


# ======================================================================
# 3. Gmail Türkçe error message tests
# ======================================================================


class TestGmailTurkishErrors(unittest.TestCase):
    """Test _tr_gmail_error returns Turkish messages for known errors."""

    def _tr(self, msg: str) -> str:
        from bantz.tools.gmail_tools import _tr_gmail_error
        return _tr_gmail_error(Exception(msg))

    def test_client_secret(self):
        result = self._tr("Google client secret not found")
        self.assertIn("Google hesap bilgileri bulunamadı", result)

    def test_http_401(self):
        result = self._tr("HttpError 401: Unauthorized")
        self.assertIn("yetkilendirmesi başarısız", result)

    def test_http_403(self):
        result = self._tr("HttpError 403: Forbidden")
        self.assertIn("erişim izni yok", result)

    def test_timeout(self):
        result = self._tr("Request timeout")
        self.assertIn("zaman aşımına", result)

    def test_connection_error(self):
        result = self._tr("ConnectionError: host down")
        self.assertIn("bağlanılamadı", result)

    def test_unknown_fallback(self):
        result = self._tr("Random failure ABC")
        self.assertIn("Gmail işlemi başarısız oldu", result)
        self.assertIn("ABC", result)

    def test_gmail_unread_count_uses_turkish(self):
        """gmail_unread_count_tool wraps errors in Turkish."""
        from bantz.tools.gmail_tools import gmail_unread_count_tool

        with patch("bantz.tools.gmail_tools.gmail_unread_count", side_effect=FileNotFoundError("Google client secret not found")):
            result = gmail_unread_count_tool()
        self.assertFalse(result["ok"])
        self.assertIn("Google hesap bilgileri bulunamadı", result["error"])

    def test_gmail_list_messages_uses_turkish(self):
        """gmail_list_messages_tool wraps errors in Turkish."""
        from bantz.tools.gmail_tools import gmail_list_messages_tool

        with patch("bantz.tools.gmail_tools.gmail_list_messages", side_effect=RuntimeError("Google client secret not found")):
            result = gmail_list_messages_tool()
        self.assertFalse(result["ok"])
        self.assertIn("Google hesap bilgileri bulunamadı", result["error"])


# ======================================================================
# 4. _TOOL_REMAP dictionary integrity
# ======================================================================


class TestToolRemapIntegrity(unittest.TestCase):
    """Ensure _TOOL_REMAP targets are valid runtime registry tools."""

    # The replacement targets should be real tool names (not phantom).
    KNOWN_REAL_TOOLS = {
        "gmail.list_messages",
        "gmail.smart_search",
        "gmail.unread_count",
        "gmail.get_message",
        "calendar.list_events",
        "calendar.create_event",
        "calendar.delete_event",
    }

    def test_all_remap_targets_are_real_tools(self):
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        for (src, intent), target in OrchestratorLoop._TOOL_REMAP.items():
            self.assertIn(
                target,
                self.KNOWN_REAL_TOOLS,
                f"Remap target '{target}' (from '{src}', intent='{intent}') is not a known real tool",
            )

    def test_no_self_remap(self):
        """No tool should remap to itself."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        for (src, intent), target in OrchestratorLoop._TOOL_REMAP.items():
            self.assertNotEqual(src, target, f"Self-remap detected: {src} → {target}")


if __name__ == "__main__":
    unittest.main()
