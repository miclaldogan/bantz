# SPDX-License-Identifier: MIT
"""Tests for Issue #1225: Golden Path Inbox.

Covers:
1. Display hints for gmail.list_messages, gmail.smart_search, gmail.send
2. Draft display hints
3. Extended gmail_intent_map (draft, reply, detail)
4. Empty result display hints
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Display hints — list_messages
# ============================================================================
class TestListMessagesDisplayHint:
    """gmail_list_messages_tool adds display_hint with numbered messages."""

    @patch("bantz.tools.gmail_tools.gmail_list_messages")
    def test_display_hint_with_messages(self, mock_list: MagicMock) -> None:
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        mock_list.return_value = {
            "ok": True,
            "messages": [
                {"id": "m1", "from": "ali@example.com", "subject": "Proje Güncellemesi", "unread": True},
                {"id": "m2", "from": "veli@corp.com", "subject": "Toplantı Notu", "unread": False},
            ],
        }
        result = gmail_list_messages_tool(max_results=5)
        assert result.get("display_hint") is not None
        assert "#1 ali@example.com" in result["display_hint"]
        assert "#2 veli@corp.com" in result["display_hint"]
        assert result["message_count"] == 2

    @patch("bantz.tools.gmail_tools.gmail_list_messages")
    def test_empty_messages_hint(self, mock_list: MagicMock) -> None:
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        mock_list.return_value = {"ok": True, "messages": []}
        result = gmail_list_messages_tool(max_results=5)
        assert "bulunamadı" in result.get("display_hint", "")
        assert result["message_count"] == 0

    @patch("bantz.tools.gmail_tools.gmail_list_messages")
    def test_unread_indicator(self, mock_list: MagicMock) -> None:
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        mock_list.return_value = {
            "ok": True,
            "messages": [
                {"id": "m1", "from": "a@b.com", "subject": "Test", "unread": True},
            ],
        }
        result = gmail_list_messages_tool()
        # Unread messages get ✉️ indicator
        assert "✉️" in result.get("display_hint", "")


# ============================================================================
# Display hints — smart_search
# ============================================================================
class TestSmartSearchDisplayHint:
    """gmail_smart_search_tool adds display_hint."""

    @patch("bantz.tools.gmail_tools.build_smart_query")
    @patch("bantz.tools.gmail_tools.gmail_list_messages")
    def test_search_display_hint(self, mock_list: MagicMock, mock_bsq: MagicMock) -> None:
        from bantz.tools.gmail_tools import gmail_smart_search_tool
        mock_bsq.return_value = ("from:tubitak", None)
        mock_list.return_value = {
            "ok": True,
            "messages": [
                {"id": "m1", "from": "tubitak@gov.tr", "subject": "Proje Onayı"},
            ],
        }
        result = gmail_smart_search_tool(natural_query="tübitaktan gelen mailler")
        assert result.get("display_hint") is not None
        assert "#1 tubitak@gov.tr" in result["display_hint"]
        assert result["message_count"] == 1


# ============================================================================
# Display hints — send
# ============================================================================
class TestSendDisplayHint:
    """gmail_send_tool adds display_hint on success."""

    @patch("bantz.tools.gmail_tools._gmail_check_duplicate", return_value=False)
    @patch("bantz.tools.gmail_tools.gmail_send")
    def test_send_display_hint(self, mock_send: MagicMock, mock_dup: MagicMock) -> None:
        from bantz.tools.gmail_tools import gmail_send_tool
        mock_send.return_value = {"ok": True, "id": "sent1"}
        result = gmail_send_tool(to="test@example.com", subject="Merhaba", body="Test body")
        assert result.get("display_hint") is not None
        assert "test@example.com" in result["display_hint"]
        assert "Merhaba" in result["display_hint"]


# ============================================================================
# Display hints — create_draft
# ============================================================================
class TestCreateDraftDisplayHint:
    """gmail_create_draft_tool adds display_hint."""

    @patch("bantz.tools.gmail_extended_tools._safe_call")
    def test_draft_display_hint(self, mock_call: MagicMock) -> None:
        from bantz.tools.gmail_extended_tools import gmail_create_draft_tool
        mock_call.return_value = {"ok": True, "draft_id": "d1"}
        result = gmail_create_draft_tool(to="ali@b.com", subject="Rapor", body="İçerik")
        assert result.get("display_hint") is not None
        assert "ali@b.com" in result["display_hint"]
        assert "Rapor" in result["display_hint"]
        assert "Taslak" in result["display_hint"]


# ============================================================================
# Extended Gmail intent map
# ============================================================================
class TestGmailIntentMap:
    """_gmail_intent_map includes draft and reply intents."""

    def test_draft_intent_in_map(self) -> None:
        import inspect
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        source = inspect.getsource(OrchestratorLoop.__init__)
        assert '"draft"' in source
        assert "gmail.create_draft" in source

    def test_reply_intent_in_map(self) -> None:
        import inspect
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        source = inspect.getsource(OrchestratorLoop.__init__)
        assert '"reply"' in source
        assert "gmail.generate_reply" in source

    def test_detail_intent_in_map(self) -> None:
        import inspect
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        source = inspect.getsource(OrchestratorLoop.__init__)
        assert '"detail"' in source
        assert "gmail.get_message" in source


# ============================================================================
# Regression — existing tools still work
# ============================================================================
class TestGmailRegressions:
    """Existing gmail tool behavior is not broken."""

    def test_list_tool_returns_error_on_exception(self) -> None:
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        with patch("bantz.tools.gmail_tools.gmail_list_messages", side_effect=Exception("API error")):
            result = gmail_list_messages_tool()
            assert result["ok"] is False
            assert "messages" in result

    def test_send_duplicate_guard(self) -> None:
        from bantz.tools.gmail_tools import gmail_send_tool
        with patch("bantz.tools.gmail_tools._gmail_check_duplicate", return_value=True):
            result = gmail_send_tool(to="x@y.com", subject="Test", body="Body")
            assert result["ok"] is False
            assert result.get("duplicate") is True
