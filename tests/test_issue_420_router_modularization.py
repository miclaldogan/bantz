"""Tests for Issue #420: Router Engine Modularization.

Tests the handler registry, individual handler modules, and the
dispatch integration in Router._dispatch().
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from bantz.router.handler_registry import (
    register_handler,
    register_handlers,
    get_handler,
    registered_intents,
    _REGISTRY,
)
from bantz.router.types import RouterResult


# ============================================================================
# Handler Registry
# ============================================================================

class TestHandlerRegistry:
    """Test the handler registry mechanism."""

    def test_register_and_get(self):
        """Register a handler and retrieve it."""
        def my_handler(*, intent, slots, ctx, router, in_queue):
            return RouterResult(ok=True, intent=intent, user_text="test")

        register_handler("test_intent_420", my_handler)
        assert get_handler("test_intent_420") is my_handler
        # Cleanup
        _REGISTRY.pop("test_intent_420", None)

    def test_register_handlers_bulk(self):
        """Register multiple intents to same handler."""
        def bulk_handler(*, intent, slots, ctx, router, in_queue):
            return RouterResult(ok=True, intent=intent, user_text="bulk")

        register_handlers(["bulk_a_420", "bulk_b_420"], bulk_handler)
        assert get_handler("bulk_a_420") is bulk_handler
        assert get_handler("bulk_b_420") is bulk_handler
        # Cleanup
        _REGISTRY.pop("bulk_a_420", None)
        _REGISTRY.pop("bulk_b_420", None)

    def test_get_unknown_returns_none(self):
        """Unknown intent returns None."""
        assert get_handler("nonexistent_intent_xyz_420") is None

    def test_registered_intents_sorted(self):
        """registered_intents() returns sorted list."""
        intents = registered_intents()
        assert intents == sorted(intents)


# ============================================================================
# Handler Module Registration
# ============================================================================

class TestHandlerModuleRegistration:
    """Test that all handler modules register correctly."""

    def test_ensure_registered_idempotent(self):
        """ensure_registered() can be called multiple times."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()
        ensure_registered()  # no error

    def test_browser_intents_registered(self):
        """Browser handler intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        browser_intents = [
            "ai_chat", "browser_open", "browser_scan", "browser_click",
            "browser_type", "browser_scroll_down", "browser_scroll_up",
            "browser_back", "browser_info", "browser_detail", "browser_wait",
            "browser_search",
        ]
        for intent in browser_intents:
            assert get_handler(intent) is not None, f"Browser intent '{intent}' not registered"

    def test_panel_intents_registered(self):
        """Panel handler intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        panel_intents = [
            "panel_move", "panel_hide", "panel_minimize", "panel_maximize",
            "panel_next_page", "panel_prev_page", "panel_select_item",
        ]
        for intent in panel_intents:
            assert get_handler(intent) is not None, f"Panel intent '{intent}' not registered"

    def test_pc_intents_registered(self):
        """PC/desktop handler intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        pc_intents = [
            "app_open", "app_close", "app_focus", "app_list", "app_type",
            "app_submit", "pc_mouse_move", "pc_mouse_click", "pc_mouse_scroll",
            "pc_hotkey", "clipboard_set", "clipboard_get", "app_session_exit",
        ]
        for intent in pc_intents:
            assert get_handler(intent) is not None, f"PC intent '{intent}' not registered"

    def test_daily_intents_registered(self):
        """Daily skills handler intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        daily_intents = [
            "open_browser", "google_search", "open_path", "open_url",
            "notify", "open_btop",
        ]
        for intent in daily_intents:
            assert get_handler(intent) is not None, f"Daily intent '{intent}' not registered"

    def test_scheduler_intents_registered(self):
        """Scheduler handler intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        scheduler_intents = [
            "reminder_add", "reminder_list", "reminder_delete", "reminder_snooze",
            "checkin_add", "checkin_list", "checkin_delete", "checkin_pause", "checkin_resume",
        ]
        for intent in scheduler_intents:
            assert get_handler(intent) is not None, f"Scheduler intent '{intent}' not registered"

    def test_coding_intents_registered(self):
        """Coding agent intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        coding_intents = [
            "file_read", "file_write", "file_edit", "file_create", "file_delete",
            "terminal_run", "code_apply_diff", "project_info", "project_tree",
        ]
        for intent in coding_intents:
            assert get_handler(intent) is not None, f"Coding intent '{intent}' not registered"

    def test_total_registered_count(self):
        """At least 60 intents should be registered."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        count = len(registered_intents())
        assert count >= 60, f"Expected ≥60 registered intents, got {count}"


# ============================================================================
# Individual Handler Behavior
# ============================================================================

class TestBrowserHandlers:
    """Test browser handler functions directly."""

    def _mock_ctx(self):
        ctx = MagicMock()
        ctx.last_intent = None
        return ctx

    @patch("bantz.browser.skills.browser_ai_chat", return_value=(True, "AI chat açıldı"))
    def test_ai_chat(self, mock_chat):
        from bantz.router.handlers.browser import handle_ai_chat
        ctx = self._mock_ctx()
        result = handle_ai_chat(intent="ai_chat", slots={"service": "duck", "prompt": "test"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "AI chat" in result.user_text

    @patch("bantz.browser.skills.browser_open", return_value=(True, "Açıldı"))
    def test_browser_open(self, mock_open):
        from bantz.router.handlers.browser import handle_browser_open
        ctx = self._mock_ctx()
        result = handle_browser_open(intent="browser_open", slots={"url": "google.com"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True

    @patch("bantz.browser.skills.browser_click_index", return_value=(True, "Tıklandı"))
    def test_browser_click_index(self, mock_click):
        from bantz.router.handlers.browser import handle_browser_click
        ctx = self._mock_ctx()
        result = handle_browser_click(intent="browser_click", slots={"index": 3}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        mock_click.assert_called_once_with(3)

    @patch("bantz.browser.skills.browser_click_text", return_value=(True, "Tıklandı"))
    def test_browser_click_text(self, mock_click):
        from bantz.router.handlers.browser import handle_browser_click
        ctx = self._mock_ctx()
        result = handle_browser_click(intent="browser_click", slots={"text": "Login"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        mock_click.assert_called_once_with("Login")

    def test_browser_click_no_target(self):
        from bantz.router.handlers.browser import handle_browser_click
        ctx = self._mock_ctx()
        result = handle_browser_click(intent="browser_click", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False
        assert "anlamadım" in result.user_text

    @patch("bantz.browser.skills.browser_search_in_page", return_value=(True, "Arandı"))
    def test_browser_search(self, mock_search):
        from bantz.router.handlers.browser import handle_browser_search
        ctx = self._mock_ctx()
        result = handle_browser_search(intent="browser_search", slots={"query": "test"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True

    def test_browser_search_empty(self):
        from bantz.router.handlers.browser import handle_browser_search
        ctx = self._mock_ctx()
        result = handle_browser_search(intent="browser_search", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False
        assert "Ne arayayım" in result.user_text


class TestPanelHandlers:
    """Test panel handler functions directly."""

    def _mock_ctx(self, has_controller=True):
        ctx = MagicMock()
        if not has_controller:
            ctx.get_panel_controller.return_value = None
        return ctx

    def test_panel_move_no_position(self):
        from bantz.router.handlers.panel import handle_panel_move
        ctx = self._mock_ctx()
        result = handle_panel_move(intent="panel_move", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False
        assert "Nereye" in result.user_text

    def test_panel_move_with_position(self):
        from bantz.router.handlers.panel import handle_panel_move
        ctx = self._mock_ctx()
        result = handle_panel_move(intent="panel_move", slots={"position": "sağ"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "sağ" in result.user_text

    def test_panel_hide_no_controller(self):
        from bantz.router.handlers.panel import handle_panel_hide
        ctx = self._mock_ctx(has_controller=False)
        result = handle_panel_hide(intent="panel_hide", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "zaten" in result.user_text.lower()

    def test_panel_select_no_index(self):
        from bantz.router.handlers.panel import handle_panel_select_item
        ctx = self._mock_ctx()
        result = handle_panel_select_item(intent="panel_select_item", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False


class TestDailyHandlers:
    """Test daily skills handler functions."""

    def _mock_ctx(self):
        ctx = MagicMock()
        ctx.last_intent = None
        ctx.awaiting = None
        return ctx

    @patch("bantz.skills.daily.google_search", return_value=(True, "Arandı"))
    def test_google_search(self, mock_search):
        from bantz.router.handlers.daily import handle_google_search
        ctx = self._mock_ctx()
        result = handle_google_search(intent="google_search", slots={"query": "python"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True

    def test_google_search_empty(self):
        from bantz.router.handlers.daily import handle_google_search
        ctx = self._mock_ctx()
        result = handle_google_search(intent="google_search", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False
        assert "Ne arayayım" in result.user_text


class TestPCHandlers:
    """Test PC control handler functions."""

    def _mock_ctx(self, has_active_app=False):
        ctx = MagicMock()
        ctx.last_intent = None
        ctx.has_active_app.return_value = has_active_app
        ctx.active_app = "test_app" if has_active_app else None
        ctx.active_window_id = "win123" if has_active_app else None
        return ctx

    def test_app_type_empty(self):
        from bantz.router.handlers.pc import handle_app_type
        ctx = self._mock_ctx()
        result = handle_app_type(intent="app_type", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False
        assert "Ne yazayım" in result.user_text

    def test_app_session_exit_no_session(self):
        from bantz.router.handlers.pc import handle_app_session_exit
        ctx = self._mock_ctx(has_active_app=False)
        result = handle_app_session_exit(intent="app_session_exit", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "Zaten" in result.user_text

    def test_app_session_exit_with_session(self):
        from bantz.router.handlers.pc import handle_app_session_exit
        ctx = self._mock_ctx(has_active_app=True)
        result = handle_app_session_exit(intent="app_session_exit", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "çıktım" in result.user_text
        ctx.clear_active_app.assert_called_once()

    def test_app_close_no_app_no_session(self):
        from bantz.router.handlers.pc import handle_app_close
        ctx = self._mock_ctx(has_active_app=False)
        result = handle_app_close(intent="app_close", slots={}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is False
        assert "Hangi" in result.user_text


class TestSchedulerHandlers:
    """Test scheduler handler functions."""

    @patch("bantz.scheduler.reminder.get_reminder_manager")
    def test_reminder_add(self, mock_mgr_fn):
        mock_mgr = MagicMock()
        mock_mgr.add_reminder.return_value = {"ok": True, "text": "Hatırlatıcı eklendi"}
        mock_mgr_fn.return_value = mock_mgr

        from bantz.router.handlers.scheduler import handle_reminder_add
        ctx = MagicMock()
        result = handle_reminder_add(intent="reminder_add", slots={"time": "17:00", "message": "test"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "eklendi" in result.user_text


# ============================================================================
# Integration: Router._dispatch() uses registry
# ============================================================================

class TestDispatchIntegration:
    """Test that Router._dispatch() delegates to the handler registry."""

    @patch("bantz.browser.skills.browser_open", return_value=(True, "Açıldı"))
    def test_dispatch_browser_open_via_registry(self, mock_open):
        """_dispatch should route browser_open through the handler registry."""
        from bantz.router.engine import Router
        from bantz.router.context import ConversationContext

        mock_logger = MagicMock()
        mock_policy = MagicMock()
        router = Router(policy=mock_policy, logger=mock_logger)

        ctx = MagicMock(spec=ConversationContext)
        ctx.last_intent = None

        result = router._dispatch(intent="browser_open", slots={"url": "test.com"}, ctx=ctx, in_queue=False)
        assert result.ok is True
        assert result.intent == "browser_open"
        mock_open.assert_called_once()

    def test_dispatch_unknown_intent(self):
        """Unknown intent should fall through to default."""
        from bantz.router.engine import Router

        mock_logger = MagicMock()
        mock_policy = MagicMock()
        router = Router(policy=mock_policy, logger=mock_logger)

        ctx = MagicMock()
        ctx.last_intent = None

        result = router._dispatch(intent="totally_unknown_xyz", slots={}, ctx=ctx, in_queue=False)
        assert result.ok is False
        assert result.intent == "unknown"

    def test_follow_up_in_queue(self):
        """When in_queue=True, follow-up text should be empty."""
        from bantz.router.handlers.browser import handle_browser_search
        ctx = MagicMock()
        result = handle_browser_search(intent="browser_search", slots={}, ctx=ctx, router=None, in_queue=True)
        assert result.ok is False
        # Should NOT have "Başka ne yapayım?"
        assert "Başka" not in result.user_text

    def test_follow_up_not_in_queue(self):
        """When in_queue=False, handler still returns clean result."""
        from bantz.router.handlers.panel import handle_panel_move
        ctx = MagicMock()
        result = handle_panel_move(intent="panel_move", slots={"position": "sol"}, ctx=ctx, router=None, in_queue=False)
        assert result.ok is True
        assert "sol" in result.user_text


# ============================================================================
# Architecture: Module counts and structure
# ============================================================================

class TestArchitecture:
    """Test the architectural properties of the modularization."""

    def test_handler_modules_exist(self):
        """All expected handler modules should be importable."""
        from bantz.router.handlers import browser, panel, pc, daily, scheduler, coding
        assert hasattr(browser, "register_all")
        assert hasattr(panel, "register_all")
        assert hasattr(pc, "register_all")
        assert hasattr(daily, "register_all")
        assert hasattr(scheduler, "register_all")
        assert hasattr(coding, "register_all")

    def test_handler_protocol_signature(self):
        """All handlers should accept the standard kwargs."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        import inspect
        for intent_name in registered_intents():
            handler = get_handler(intent_name)
            sig = inspect.signature(handler)
            params = set(sig.parameters.keys())
            required = {"intent", "slots", "ctx", "router", "in_queue"}
            assert required.issubset(params), f"Handler for '{intent_name}' missing params: {required - params}"

    def test_no_handler_returns_none_result(self):
        """All handlers should return RouterResult, not None."""
        from bantz.router.handlers import ensure_registered
        ensure_registered()

        # Spot-check a few handlers with minimal mocks
        ctx = MagicMock()
        ctx.last_intent = None
        ctx.has_active_app.return_value = False
        ctx.active_app = None

        handlers_to_check = [
            ("browser_search", {"query": ""}),
            ("panel_move", {}),
            ("app_type", {}),
        ]
        for intent_name, slots in handlers_to_check:
            handler = get_handler(intent_name)
            result = handler(intent=intent_name, slots=slots, ctx=ctx, router=None, in_queue=False)
            assert isinstance(result, RouterResult), f"Handler '{intent_name}' returned {type(result)}"

    def test_registry_is_not_empty_after_ensure(self):
        from bantz.router.handlers import ensure_registered
        ensure_registered()
        assert len(registered_intents()) > 0
