"""
Tests for PC Skills (v0.5.3)
- NLU: app_open, app_close, app_focus, app_type, app_list, app_submit, app_session_exit
- Context: active_app, active_window_id session tracking  
- Policy: allow/confirm/deny for app intents
- PC Skills: open_app, close_app, focus_app, list_windows, type_text, send_key
"""

import pytest
from bantz.router.nlu import parse_intent
from bantz.router.context import ConversationContext
from bantz.router.policy import Policy
from bantz.skills.pc import (
    ALLOWED_APPS,
    CONFIRM_APPS,
    DENIED_APPS,
    list_windows,
)


# ─────────────────────────────────────────────────────────────
# NLU Tests
# ─────────────────────────────────────────────────────────────
class TestNLUAppIntents:
    """Test that NLU correctly parses app-related intents."""

    @pytest.mark.parametrize("text,expected_intent,expected_app", [
        ("discord aç", "app_open", "discord"),
        ("spotify aç", "app_open", "spotify"),
        ("firefox aç", "app_open", "firefox"),
        ("chrome'u aç", "app_open", "chrome"),
        ("vscode başlat", "app_open", "vscode"),
        ("terminal aç", "app_open", "terminal"),
    ])
    def test_app_open_intent(self, text, expected_intent, expected_app):
        parsed = parse_intent(text)
        assert parsed.intent == expected_intent
        assert parsed.slots.get("app") == expected_app

    @pytest.mark.parametrize("text,expected_intent,expected_app", [
        ("discord kapat", "app_close", "discord"),
        ("spotify'ı kapat", "app_close", "spotify"),
        ("firefox'u kapat", "app_close", "firefox"),
    ])
    def test_app_close_intent(self, text, expected_intent, expected_app):
        parsed = parse_intent(text)
        assert parsed.intent == expected_intent
        assert parsed.slots.get("app") == expected_app

    @pytest.mark.parametrize("text,expected_intent", [
        ("uygulamaları listele", "app_list"),
        ("pencereler", "app_list"),
    ])
    def test_app_list_intent(self, text, expected_intent):
        parsed = parse_intent(text)
        assert parsed.intent == expected_intent

    @pytest.mark.parametrize("text,expected_intent,expected_text", [
        ("yaz: merhaba dünya", "app_type", "merhaba dünya"),
        ("şunu yaz: test mesajı", "app_type", "test mesajı"),
    ])
    def test_app_type_intent(self, text, expected_intent, expected_text):
        parsed = parse_intent(text)
        assert parsed.intent == expected_intent
        assert parsed.slots.get("text") == expected_text

    @pytest.mark.parametrize("text,expected_intent", [
        ("gönder", "app_submit"),
        ("enter bas", "app_submit"),
    ])
    def test_app_submit_intent(self, text, expected_intent):
        parsed = parse_intent(text)
        assert parsed.intent == expected_intent

    @pytest.mark.parametrize("text,expected_intent", [
        ("uygulamadan çık", "app_session_exit"),
        ("tamam bitti", "app_session_exit"),
    ])
    def test_app_session_exit_intent(self, text, expected_intent):
        parsed = parse_intent(text)
        assert parsed.intent == expected_intent


class TestNLUAdvancedDesktopInput:
    """Test that NLU correctly parses advanced desktop input intents."""

    @pytest.mark.parametrize("text,x,y", [
        ("mouse 500 300 git", 500, 300),
        ("imleç 800,400 götür", 800, 400),
    ])
    def test_mouse_move(self, text, x, y):
        parsed = parse_intent(text)
        assert parsed.intent == "pc_mouse_move"
        assert parsed.slots.get("x") == x
        assert parsed.slots.get("y") == y

    @pytest.mark.parametrize("text,button,double,x,y", [
        ("mouse 500 300 sol tıkla", "left", False, 500, 300),
        ("fare sağ tıkla", "right", False, None, None),
        ("mouse 200 100 çift tıkla", "left", True, 200, 100),
    ])
    def test_mouse_click(self, text, button, double, x, y):
        parsed = parse_intent(text)
        assert parsed.intent == "pc_mouse_click"
        assert parsed.slots.get("button") == button
        assert parsed.slots.get("double") == double
        assert parsed.slots.get("x") == x
        assert parsed.slots.get("y") == y

    @pytest.mark.parametrize("text,direction,amount", [
        ("mouse aşağı 5 kaydır", "down", 5),
        ("fare yukarı kaydır", "up", 3),
    ])
    def test_mouse_scroll(self, text, direction, amount):
        parsed = parse_intent(text)
        assert parsed.intent == "pc_mouse_scroll"
        assert parsed.slots.get("direction") == direction
        assert parsed.slots.get("amount") == amount

    def test_hotkey(self):
        parsed = parse_intent("kısayol: ctrl alt t")
        assert parsed.intent == "pc_hotkey"
        assert parsed.slots.get("combo") == "ctrl+alt+t"

    def test_clipboard_set(self):
        parsed = parse_intent("panoya kopyala: merhaba")
        assert parsed.intent == "clipboard_set"
        assert parsed.slots.get("text") == "merhaba"

    def test_clipboard_get(self):
        parsed = parse_intent("panoda ne var")
        assert parsed.intent == "clipboard_get"


# ─────────────────────────────────────────────────────────────
# Context Tests
# ─────────────────────────────────────────────────────────────
class TestContextAppSession:
    """Test that context correctly tracks active app session."""

    def test_initial_state(self):
        ctx = ConversationContext()
        assert ctx.has_active_app() is False
        assert ctx.active_app is None
        assert ctx.active_window_id is None

    def test_set_active_app(self):
        ctx = ConversationContext()
        ctx.set_active_app("discord", "0x12345")
        
        assert ctx.has_active_app() is True
        assert ctx.active_app == "discord"
        assert ctx.active_window_id == "0x12345"

    def test_clear_active_app(self):
        ctx = ConversationContext()
        ctx.set_active_app("discord", "0x12345")
        ctx.clear_active_app()
        
        assert ctx.has_active_app() is False
        assert ctx.active_app is None
        assert ctx.active_window_id is None

    def test_snapshot_includes_active_app(self):
        ctx = ConversationContext()
        ctx.set_active_app("spotify", "0x67890")
        
        snap = ctx.snapshot()
        assert "active_app" in snap
        assert snap["active_app"] == "spotify"

    def test_switch_active_app(self):
        ctx = ConversationContext()
        ctx.set_active_app("discord", "0x12345")
        ctx.set_active_app("spotify", "0x67890")
        
        assert ctx.active_app == "spotify"
        assert ctx.active_window_id == "0x67890"


# ─────────────────────────────────────────────────────────────
# Policy Tests
# ─────────────────────────────────────────────────────────────
class TestPolicyAppIntents:
    """Test that policy correctly decides for app intents."""

    @pytest.fixture
    def policy(self):
        return Policy.from_json_file("config/policy.json")

    @pytest.mark.parametrize("intent,expected_decision", [
        ("app_open", "allow"),
        ("app_list", "allow"),
        ("app_focus", "allow"),
        ("app_session_exit", "allow"),
    ])
    def test_allow_intents(self, policy, intent, expected_decision):
        decision, _ = policy.decide(text="test", intent=intent, confirmed=False)
        assert decision == expected_decision

    @pytest.mark.parametrize("intent,expected_decision", [
        ("app_close", "confirm"),
        ("app_type", "confirm"),
        ("app_submit", "confirm"),
    ])
    def test_confirm_intents(self, policy, intent, expected_decision):
        decision, _ = policy.decide(text="test", intent=intent, confirmed=False)
        assert decision == expected_decision


class TestPolicyAdvancedDesktopInput:
    @pytest.fixture
    def policy(self):
        return Policy.from_json_file("config/policy.json")

    @pytest.mark.parametrize("intent,expected_decision", [
        ("pc_mouse_move", "confirm"),
        ("pc_mouse_click", "confirm"),
        ("pc_mouse_scroll", "confirm"),
        ("pc_hotkey", "confirm"),
        ("clipboard_set", "confirm"),
        ("clipboard_get", "allow"),
    ])
    def test_intent_levels(self, policy, intent, expected_decision):
        decision, _ = policy.decide(text="test", intent=intent, confirmed=False)
        assert decision == expected_decision


# ─────────────────────────────────────────────────────────────
# PC Skills Tests
# ─────────────────────────────────────────────────────────────
class TestPCSkillsConfig:
    """Test PC skills configuration."""

    def test_allowed_apps_has_common_apps(self):
        common_apps = ["discord", "firefox", "chrome", "spotify", "vscode", "terminal"]
        for app in common_apps:
            assert app in ALLOWED_APPS, f"{app} should be in ALLOWED_APPS"

    def test_confirm_apps_has_system_monitors(self):
        system_apps = ["htop", "btop"]
        for app in system_apps:
            assert app in CONFIRM_APPS, f"{app} should be in CONFIRM_APPS"

    def test_denied_apps_has_dangerous_commands(self):
        dangerous = ["sudo", "rm", "dd", "mkfs"]
        for cmd in dangerous:
            assert cmd in DENIED_APPS, f"{cmd} should be in DENIED_APPS"

    def test_list_windows_returns_tuple(self):
        """list_windows should return (ok, msg, windows_list)"""
        ok, msg, windows = list_windows()
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        assert isinstance(windows, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
