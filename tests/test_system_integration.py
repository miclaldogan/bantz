"""
Tests for System Integration Module.

Tests for:
- Notification listener
- Global shortcuts
- System tray
- Auto-start
- Desktop integration
"""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os


# =============================================================================
# Notification Tests
# =============================================================================

class TestNotification:
    """Tests for Notification dataclass."""
    
    def test_notification_creation(self):
        """Test creating a notification."""
        from bantz.system.notifications import Notification, NotificationUrgency
        
        notif = Notification(
            app_name="Discord",
            summary="New Message",
            body="Hello from John",
        )
        
        assert notif.app_name == "Discord"
        assert notif.summary == "New Message"
        assert notif.body == "Hello from John"
        assert notif.urgency == NotificationUrgency.NORMAL
    
    def test_notification_matches_app(self):
        """Test app name pattern matching."""
        from bantz.system.notifications import Notification
        
        notif = Notification(app_name="Discord", summary="Test")
        
        assert notif.matches_app("Discord") is True
        assert notif.matches_app("discord") is True
        assert notif.matches_app("Disc.*") is True
        assert notif.matches_app("Slack") is False
    
    def test_notification_matches_content(self):
        """Test content pattern matching."""
        from bantz.system.notifications import Notification
        
        notif = Notification(
            app_name="Test",
            summary="Meeting Reminder",
            body="Your meeting starts in 5 minutes",
        )
        
        assert notif.matches_content("meeting") is True
        assert notif.matches_content("Reminder") is True
        assert notif.matches_content("5 minutes") is True
        assert notif.matches_content("email") is False
    
    def test_notification_to_dict(self):
        """Test notification serialization."""
        from bantz.system.notifications import Notification, NotificationUrgency
        
        notif = Notification(
            app_name="Slack",
            summary="Channel Message",
            body="New post in #general",
            urgency=NotificationUrgency.CRITICAL,
        )
        
        data = notif.to_dict()
        
        assert data["app"] == "Slack"
        assert data["title"] == "Channel Message"
        assert data["body"] == "New post in #general"
        assert data["urgency"] == "critical"
        assert "timestamp" in data


class TestNotificationFilter:
    """Tests for NotificationFilter."""
    
    def test_filter_by_urgency(self):
        """Test filtering by urgency level."""
        from bantz.system.notifications import (
            Notification, NotificationFilter, NotificationUrgency
        )
        
        filter_ = NotificationFilter(min_urgency=NotificationUrgency.CRITICAL)
        
        critical = Notification(
            app_name="Test", summary="Critical", urgency=NotificationUrgency.CRITICAL
        )
        normal = Notification(
            app_name="Test", summary="Normal", urgency=NotificationUrgency.NORMAL
        )
        low = Notification(
            app_name="Test", summary="Low", urgency=NotificationUrgency.LOW
        )
        
        assert filter_.matches(critical) is True
        assert filter_.matches(normal) is False
        assert filter_.matches(low) is False
    
    def test_filter_exclude_apps(self):
        """Test excluding specific apps."""
        from bantz.system.notifications import Notification, NotificationFilter
        
        filter_ = NotificationFilter(exclude_apps={"chrome", "firefox"})
        
        discord = Notification(app_name="Discord", summary="Test")
        chrome = Notification(app_name="Chrome", summary="Test")
        
        assert filter_.matches(discord) is True
        assert filter_.matches(chrome) is False
    
    def test_filter_include_only_apps(self):
        """Test including only specific apps."""
        from bantz.system.notifications import Notification, NotificationFilter
        
        filter_ = NotificationFilter(include_only_apps={"discord", "slack"})
        
        discord = Notification(app_name="Discord", summary="Test")
        chrome = Notification(app_name="Chrome", summary="Test")
        
        assert filter_.matches(discord) is True
        assert filter_.matches(chrome) is False
    
    def test_filter_by_app_pattern(self):
        """Test filtering by app pattern."""
        from bantz.system.notifications import Notification, NotificationFilter
        
        filter_ = NotificationFilter(app_patterns=["^Discord$", "^Slack$"])
        
        discord = Notification(app_name="Discord", summary="Test")
        other = Notification(app_name="SomeApp", summary="Test")
        
        assert filter_.matches(discord) is True
        assert filter_.matches(other) is False
    
    def test_filter_by_content_pattern(self):
        """Test filtering by content pattern."""
        from bantz.system.notifications import Notification, NotificationFilter
        
        filter_ = NotificationFilter(content_patterns=["urgent", "important"])
        
        urgent = Notification(app_name="Test", summary="URGENT: Action needed")
        normal = Notification(app_name="Test", summary="Weekly newsletter")
        
        assert filter_.matches(urgent) is True
        assert filter_.matches(normal) is False


class TestMockNotificationListener:
    """Tests for MockNotificationListener."""
    
    @pytest.mark.asyncio
    async def test_mock_listener_start_stop(self):
        """Test starting and stopping mock listener."""
        from bantz.system.notifications import MockNotificationListener
        
        callback = Mock()
        listener = MockNotificationListener(callback)
        
        assert listener.is_running is False
        
        await listener.start()
        assert listener.is_running is True
        
        await listener.stop()
        assert listener.is_running is False
    
    @pytest.mark.asyncio
    async def test_mock_listener_emit_notification(self):
        """Test emitting mock notifications."""
        from bantz.system.notifications import MockNotificationListener, Notification
        
        received = []
        
        def callback(notif):
            received.append(notif)
        
        listener = MockNotificationListener(callback)
        await listener.start()
        
        notif = Notification(app_name="Discord", summary="Test Message")
        await listener.emit_notification(notif)
        
        assert len(received) == 1
        assert received[0].app_name == "Discord"
        assert len(listener.history) == 1
    
    @pytest.mark.asyncio
    async def test_mock_listener_emit_helper(self):
        """Test emit convenience method."""
        from bantz.system.notifications import MockNotificationListener, NotificationUrgency
        
        received = []
        listener = MockNotificationListener(lambda n: received.append(n))
        await listener.start()
        
        await listener.emit("Slack", "New DM", "From John", NotificationUrgency.CRITICAL)
        
        assert len(received) == 1
        assert received[0].app_name == "Slack"
        assert received[0].summary == "New DM"
        assert received[0].urgency == NotificationUrgency.CRITICAL
    
    @pytest.mark.asyncio
    async def test_mock_listener_filter_applied(self):
        """Test that filter is applied to mock notifications."""
        from bantz.system.notifications import (
            MockNotificationListener, NotificationFilter
        )
        
        received = []
        filter_ = NotificationFilter(include_only_apps={"discord"})
        listener = MockNotificationListener(lambda n: received.append(n), filter_)
        await listener.start()
        
        await listener.emit("Discord", "Test")
        await listener.emit("Slack", "Test")  # Should be filtered
        
        assert len(received) == 1
        assert received[0].app_name == "Discord"
    
    @pytest.mark.asyncio
    async def test_mock_listener_history(self):
        """Test notification history."""
        from bantz.system.notifications import MockNotificationListener
        
        listener = MockNotificationListener(Mock())
        await listener.start()
        
        await listener.emit("App1", "Msg1")
        await listener.emit("App2", "Msg2")
        await listener.emit("App3", "Msg3")
        
        assert len(listener.history) == 3
        
        listener.clear_history()
        assert len(listener.history) == 0
    
    @pytest.mark.asyncio
    async def test_get_notifications_from_app(self):
        """Test getting notifications from specific app."""
        from bantz.system.notifications import MockNotificationListener
        
        listener = MockNotificationListener(Mock())
        await listener.start()
        
        await listener.emit("Discord", "Msg1")
        await listener.emit("Slack", "Msg2")
        await listener.emit("Discord", "Msg3")
        
        discord_notifs = listener.get_notifications_from_app("Discord")
        assert len(discord_notifs) == 2


# =============================================================================
# Shortcuts Tests
# =============================================================================

class TestShortcutConfig:
    """Tests for ShortcutConfig."""
    
    def test_shortcut_config_creation(self):
        """Test creating shortcut config."""
        from bantz.system.shortcuts import ShortcutConfig, ShortcutAction
        
        config = ShortcutConfig(
            keys="<ctrl>+<alt>+b",
            action=ShortcutAction.ACTIVATE,
        )
        
        assert config.keys == "<ctrl>+<alt>+b"
        assert config.action == ShortcutAction.ACTIVATE
        assert config.enabled is True
        assert config.description == "Activate"
    
    def test_shortcut_config_custom_description(self):
        """Test custom description."""
        from bantz.system.shortcuts import ShortcutConfig, ShortcutAction
        
        config = ShortcutConfig(
            keys="<ctrl>+<alt>+m",
            action=ShortcutAction.TOGGLE_MUTE,
            description="Sessize Al",
        )
        
        assert config.description == "Sessize Al"
    
    def test_shortcut_config_custom_handler(self):
        """Test custom handler."""
        from bantz.system.shortcuts import ShortcutConfig, ShortcutAction
        
        handler = Mock()
        config = ShortcutConfig(
            keys="<ctrl>+<alt>+x",
            action=ShortcutAction.CUSTOM,
            custom_handler=handler,
        )
        
        assert config.custom_handler == handler


class TestShortcutParsing:
    """Tests for shortcut string parsing."""
    
    def test_parse_simple_shortcut(self):
        """Test parsing simple shortcut."""
        from bantz.system.shortcuts import parse_shortcut_string
        
        result = parse_shortcut_string("<ctrl>+<alt>+b")
        
        assert "ctrl" in result["modifiers"]
        assert "alt" in result["modifiers"]
        assert result["key"] == "b"
    
    def test_parse_with_shift(self):
        """Test parsing shortcut with shift."""
        from bantz.system.shortcuts import parse_shortcut_string
        
        result = parse_shortcut_string("<ctrl>+<shift>+s")
        
        assert "ctrl" in result["modifiers"]
        assert "shift" in result["modifiers"]
        assert result["key"] == "s"
    
    def test_parse_special_key(self):
        """Test parsing special key."""
        from bantz.system.shortcuts import parse_shortcut_string
        
        result = parse_shortcut_string("<ctrl>+<space>")
        
        assert "ctrl" in result["modifiers"]
        assert result["key"] == "space"
    
    def test_format_shortcut_display(self):
        """Test formatting shortcut for display."""
        from bantz.system.shortcuts import format_shortcut_display
        
        assert format_shortcut_display("<ctrl>+<alt>+b") == "Ctrl+Alt+B"
        assert format_shortcut_display("<ctrl>+<shift>+s") == "Ctrl+Shift+S"
        assert format_shortcut_display("<ctrl>+<space>") == "Ctrl+Space"


class TestMockGlobalShortcuts:
    """Tests for MockGlobalShortcuts."""
    
    def test_mock_shortcuts_start_stop(self):
        """Test starting and stopping mock shortcuts."""
        from bantz.system.shortcuts import MockGlobalShortcuts
        
        shortcuts = MockGlobalShortcuts()
        
        assert shortcuts.is_running is False
        
        shortcuts.start()
        assert shortcuts.is_running is True
        
        shortcuts.stop()
        assert shortcuts.is_running is False
    
    def test_mock_shortcuts_trigger(self):
        """Test triggering shortcuts."""
        from bantz.system.shortcuts import MockGlobalShortcuts, ShortcutAction
        
        activated = []
        
        shortcuts = MockGlobalShortcuts()
        shortcuts.register_handler(ShortcutAction.ACTIVATE, lambda: activated.append(True))
        shortcuts.start()
        
        # Wait a bit for debounce
        import time
        time.sleep(0.05)
        
        success = shortcuts.trigger("<ctrl>+<alt>+b")
        
        assert success is True
    
    def test_mock_shortcuts_trigger_action(self):
        """Test triggering shortcuts by action."""
        from bantz.system.shortcuts import MockGlobalShortcuts, ShortcutAction
        
        muted = []
        
        shortcuts = MockGlobalShortcuts()
        shortcuts.register_handler(ShortcutAction.TOGGLE_MUTE, lambda: muted.append(True))
        shortcuts.start()
        
        success = shortcuts.trigger_action(ShortcutAction.TOGGLE_MUTE)
        
        assert success is True
    
    def test_mock_shortcuts_add_remove(self):
        """Test adding and removing shortcuts."""
        from bantz.system.shortcuts import (
            MockGlobalShortcuts, ShortcutConfig, ShortcutAction
        )
        
        shortcuts = MockGlobalShortcuts()
        original_count = len(shortcuts.shortcuts)
        
        # Add shortcut
        new_shortcut = ShortcutConfig(
            keys="<ctrl>+<alt>+x",
            action=ShortcutAction.CUSTOM,
            custom_handler=Mock(),
        )
        shortcuts.add_shortcut(new_shortcut)
        
        assert len(shortcuts.shortcuts) == original_count + 1
        
        # Remove shortcut
        removed = shortcuts.remove_shortcut("<ctrl>+<alt>+x")
        assert removed is True
        assert len(shortcuts.shortcuts) == original_count
    
    def test_mock_shortcuts_enable_disable(self):
        """Test enabling and disabling shortcuts."""
        from bantz.system.shortcuts import MockGlobalShortcuts
        
        shortcuts = MockGlobalShortcuts()
        
        # Disable
        result = shortcuts.enable_shortcut("<ctrl>+<alt>+b", False)
        assert result is True
        
        # Check it's disabled
        shortcut_list = shortcuts.get_shortcut_list()
        activate_shortcut = next(s for s in shortcut_list if s["keys"] == "<ctrl>+<alt>+b")
        assert activate_shortcut["enabled"] is False
        
        # Enable
        shortcuts.enable_shortcut("<ctrl>+<alt>+b", True)
        shortcut_list = shortcuts.get_shortcut_list()
        activate_shortcut = next(s for s in shortcut_list if s["keys"] == "<ctrl>+<alt>+b")
        assert activate_shortcut["enabled"] is True
    
    def test_mock_shortcuts_list(self):
        """Test getting shortcut list."""
        from bantz.system.shortcuts import MockGlobalShortcuts
        
        shortcuts = MockGlobalShortcuts()
        shortcut_list = shortcuts.get_shortcut_list()
        
        assert len(shortcut_list) > 0
        
        # Check structure
        first = shortcut_list[0]
        assert "keys" in first
        assert "action" in first
        assert "enabled" in first
        assert "description" in first
        assert "has_handler" in first


# =============================================================================
# Tray Tests
# =============================================================================

class TestTrayMenuItem:
    """Tests for TrayMenuItem."""
    
    def test_menu_item_creation(self):
        """Test creating menu item."""
        from bantz.system.tray import TrayMenuItem
        
        item = TrayMenuItem(
            label="Test Action",
            action=Mock(),
            icon="🔥",
        )
        
        assert item.label == "Test Action"
        assert item.icon == "🔥"
        assert item.enabled is True
        assert item.is_separator is False
    
    def test_separator(self):
        """Test separator creation."""
        from bantz.system.tray import TrayMenuItem
        
        sep = TrayMenuItem.separator()
        
        assert sep.is_separator is True
        assert sep.label == "-"


class TestTrayStatus:
    """Tests for TrayStatus."""
    
    def test_status_values(self):
        """Test status enum values."""
        from bantz.system.tray import TrayStatus, STATUS_ICONS, STATUS_TEXTS
        
        for status in TrayStatus:
            assert status in STATUS_ICONS
            assert status in STATUS_TEXTS
    
    def test_status_icons(self):
        """Test status icons."""
        from bantz.system.tray import TrayStatus, STATUS_ICONS
        
        assert STATUS_ICONS[TrayStatus.IDLE] == "🔵"
        assert STATUS_ICONS[TrayStatus.LISTENING] == "🟢"
        assert STATUS_ICONS[TrayStatus.ERROR] == "🔴"
        assert STATUS_ICONS[TrayStatus.MUTED] == "🔇"


class TestMockSystemTray:
    """Tests for MockSystemTray."""
    
    def test_mock_tray_show_hide(self):
        """Test showing and hiding mock tray."""
        from bantz.system.tray import MockSystemTray
        
        tray = MockSystemTray()
        
        assert tray.is_visible is False
        
        tray.show()
        assert tray.is_visible is True
        
        tray.hide()
        assert tray.is_visible is False
    
    def test_mock_tray_update_status(self):
        """Test updating status."""
        from bantz.system.tray import MockSystemTray, TrayStatus
        
        tray = MockSystemTray()
        tray.show()
        
        tray.update_status(TrayStatus.LISTENING)
        assert tray.status == TrayStatus.LISTENING
        assert TrayStatus.LISTENING in tray.status_history
        
        tray.update_status(TrayStatus.PROCESSING)
        assert tray.status == TrayStatus.PROCESSING
        assert len(tray.status_history) == 2
    
    def test_mock_tray_notify(self):
        """Test notifications."""
        from bantz.system.tray import MockSystemTray
        
        tray = MockSystemTray()
        tray.show()
        
        tray.notify("Test Title", "Test Message", "info")
        
        assert len(tray.notifications) == 1
        assert tray.notifications[0]["title"] == "Test Title"
        assert tray.notifications[0]["message"] == "Test Message"
    
    def test_mock_tray_click(self):
        """Test click handling."""
        from bantz.system.tray import MockSystemTray
        
        clicked = []
        
        tray = MockSystemTray()
        tray.on_click = lambda: clicked.append(True)
        tray.show()
        
        tray.click()
        
        assert len(clicked) == 1
    
    def test_mock_tray_double_click(self):
        """Test double click handling."""
        from bantz.system.tray import MockSystemTray
        
        double_clicked = []
        
        tray = MockSystemTray()
        tray.on_double_click = lambda: double_clicked.append(True)
        tray.show()
        
        tray.double_click()
        
        assert len(double_clicked) == 1
    
    def test_mock_tray_menu_item_action(self):
        """Test menu item action."""
        from bantz.system.tray import MockSystemTray
        
        action_called = []
        
        tray = MockSystemTray()
        tray.add_menu_item("Custom Action", lambda: action_called.append(True))
        tray.show()
        
        success = tray.select_menu_item("Custom Action")
        
        assert success is True
        assert len(action_called) == 1
    
    def test_mock_tray_set_menu_action(self):
        """Test setting menu action."""
        from bantz.system.tray import MockSystemTray
        
        voice_called = []
        
        tray = MockSystemTray()
        tray.set_menu_item_action("Sesli Komut", lambda: voice_called.append(True))
        tray.show()
        
        tray.select_menu_item("Sesli Komut")
        
        assert len(voice_called) == 1
    
    def test_mock_tray_clear_history(self):
        """Test clearing history."""
        from bantz.system.tray import MockSystemTray, TrayStatus
        
        tray = MockSystemTray()
        tray.show()
        
        tray.update_status(TrayStatus.LISTENING)
        tray.notify("Test", "Message")
        
        tray.clear_history()
        
        assert len(tray.notifications) == 0
        assert len(tray.status_history) == 0


# =============================================================================
# AutoStart Tests
# =============================================================================

class TestAutoStartConfig:
    """Tests for AutoStartConfig."""
    
    def test_config_defaults(self):
        """Test default configuration."""
        from bantz.system.autostart import AutoStartConfig
        
        config = AutoStartConfig()
        
        assert config.name == "Bantz Assistant"
        assert config.executable == "bantz"
        assert config.terminal is False
        assert config.gnome_autostart_enabled is True
    
    def test_config_to_desktop_entry(self):
        """Test generating desktop entry."""
        from bantz.system.autostart import AutoStartConfig
        
        config = AutoStartConfig(
            name="Test App",
            executable="/usr/bin/test",
            icon="/path/to/icon.png",
        )
        
        content = config.to_desktop_entry()
        
        assert "[Desktop Entry]" in content
        assert "Type=Application" in content
        assert "Name=Test App" in content
        assert "Exec=/usr/bin/test" in content
        assert "Icon=/path/to/icon.png" in content
        assert "Terminal=false" in content
    
    def test_config_with_extra_args(self):
        """Test with extra arguments."""
        from bantz.system.autostart import AutoStartConfig
        
        config = AutoStartConfig(
            executable="bantz",
            extra_args="--daemon --quiet",
        )
        
        content = config.to_desktop_entry()
        
        assert "Exec=bantz --daemon --quiet" in content
    
    def test_config_with_environment(self):
        """Test with environment variables."""
        from bantz.system.autostart import AutoStartConfig
        
        config = AutoStartConfig(
            environment={"DISPLAY": ":0", "LANG": "en_US.UTF-8"},
        )
        
        content = config.to_desktop_entry()
        
        assert "X-Env-DISPLAY=:0" in content
        assert "X-Env-LANG=en_US.UTF-8" in content


class TestAutoStart:
    """Tests for AutoStart class."""
    
    def test_get_autostart_dir(self):
        """Test getting autostart directory."""
        from bantz.system.autostart import AutoStart
        
        user_dir = AutoStart.get_autostart_dir(system_wide=False)
        system_dir = AutoStart.get_autostart_dir(system_wide=True)
        
        assert "autostart" in str(user_dir)
        assert user_dir != system_dir
        assert str(system_dir).startswith("/etc")
    
    def test_enable_disable_with_temp_dir(self):
        """Test enable/disable with temporary directory."""
        from bantz.system.autostart import AutoStart
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch the autostart directory
            with patch.object(AutoStart, 'get_autostart_dir', return_value=Path(tmpdir)):
                # Enable
                success = AutoStart.enable()
                assert success is True
                
                # Check file exists
                desktop_file = Path(tmpdir) / AutoStart.DESKTOP_FILENAME
                assert desktop_file.exists()
                
                # Check is_enabled
                with patch.object(AutoStart, 'get_desktop_file_path', return_value=desktop_file):
                    assert AutoStart.is_enabled() is True
                
                # Disable
                with patch.object(AutoStart, 'get_desktop_file_path', return_value=desktop_file):
                    success = AutoStart.disable()
                    assert success is True
                    assert not desktop_file.exists()
    
    def test_parse_desktop_file(self):
        """Test parsing desktop file."""
        from bantz.system.autostart import AutoStart
        
        content = """[Desktop Entry]
Type=Application
Name=Test App
Comment=Test Description
Exec=/usr/bin/test --arg
Icon=/path/icon.png
Terminal=false
X-GNOME-Autostart-enabled=true
"""
        
        config = AutoStart._parse_desktop_file(content)
        
        assert config.name == "Test App"
        assert config.comment == "Test Description"
        assert config.executable == "/usr/bin/test"
        assert config.extra_args == "--arg"
        assert config.icon == "/path/icon.png"
        assert config.terminal is False
        assert config.gnome_autostart_enabled is True
    
    def test_toggle(self):
        """Test toggle functionality."""
        from bantz.system.autostart import AutoStart
        
        with tempfile.TemporaryDirectory() as tmpdir:
            desktop_file = Path(tmpdir) / AutoStart.DESKTOP_FILENAME
            
            with patch.object(AutoStart, 'get_autostart_dir', return_value=Path(tmpdir)):
                with patch.object(AutoStart, 'get_desktop_file_path', return_value=desktop_file):
                    # Toggle on
                    result = AutoStart.toggle()
                    assert result is True
                    assert desktop_file.exists()
                    
                    # Toggle off
                    result = AutoStart.toggle()
                    assert result is False
                    assert not desktop_file.exists()
    
    def test_verify_executable(self):
        """Test executable verification."""
        from bantz.system.autostart import AutoStart
        
        # Python executable should exist
        import sys
        assert AutoStart.verify_executable(sys.executable) is True
        
        # Non-existent should return False
        assert AutoStart.verify_executable("/nonexistent/path") is False


# =============================================================================
# Desktop Integration Tests
# =============================================================================

class TestXDGPaths:
    """Tests for XDGPaths."""
    
    def test_default_paths(self):
        """Test default XDG paths."""
        from bantz.system.desktop import XDGPaths
        
        paths = XDGPaths()
        
        assert paths.config_home.exists() or "config" in str(paths.config_home).lower()
        assert "applications" in str(paths.applications_dir)
        assert "icons" in str(paths.icons_dir)
        assert "autostart" in str(paths.autostart_dir)
    
    def test_ensure_dirs(self):
        """Test ensuring directories exist."""
        from bantz.system.desktop import XDGPaths
        
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = XDGPaths(
                config_home=Path(tmpdir) / "config",
                data_home=Path(tmpdir) / "data",
                cache_home=Path(tmpdir) / "cache",
                state_home=Path(tmpdir) / "state",
            )
            
            paths.ensure_dirs()
            
            assert paths.config_home.exists()
            assert paths.data_home.exists()
            assert paths.applications_dir.exists()


class TestMimeHandler:
    """Tests for MimeHandler."""
    
    def test_mime_handler_to_desktop(self):
        """Test MIME handler desktop entry generation."""
        from bantz.system.desktop import MimeHandler
        
        handler = MimeHandler(
            mime_type="application/x-bantz",
            name="Bantz File Handler",
            exec_command="bantz --open %f",
            icon="bantz",
        )
        
        content = handler.to_desktop_entry()
        
        assert "[Desktop Entry]" in content
        assert "MimeType=application/x-bantz" in content
        assert "Exec=bantz --open %f" in content
        assert "NoDisplay=true" in content


class TestMockDesktopIntegration:
    """Tests for MockDesktopIntegration."""
    
    def test_mock_install_desktop_file(self):
        """Test mock desktop file installation."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        
        result = integration.install_desktop_file()
        
        assert result is True
        assert integration.is_installed()["desktop_file"] is True
    
    def test_mock_uninstall_desktop_file(self):
        """Test mock desktop file uninstallation."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        integration.install_desktop_file()
        
        result = integration.uninstall_desktop_file()
        
        assert result is True
        assert integration.is_installed()["desktop_file"] is False
    
    def test_mock_register_protocol_handler(self):
        """Test mock protocol handler registration."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        
        result = integration.register_protocol_handler()
        
        assert result is True
        assert integration.is_installed()["protocol_handler"] is True
        assert "bantz" in integration._handlers
    
    def test_mock_register_mime_handler(self):
        """Test mock MIME handler registration."""
        from bantz.system.desktop import MockDesktopIntegration, MimeHandler
        
        integration = MockDesktopIntegration()
        
        handler = MimeHandler(
            mime_type="text/x-bantz",
            name="Bantz Text",
            exec_command="bantz %f",
        )
        
        result = integration.register_mime_handler(handler)
        
        assert result is True
        assert "text/x-bantz" in integration._handlers
    
    def test_mock_install_icon(self):
        """Test mock icon installation."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        
        result = integration.install_icon("/path/to/icon.png")
        
        assert result is True
        assert integration.is_installed()["icon"] is True
    
    def test_mock_desktop_shortcut(self):
        """Test mock desktop shortcut."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        
        result = integration.create_desktop_shortcut()
        
        assert result is True
        assert integration.is_installed()["desktop_shortcut"] is True
        
        integration.remove_desktop_shortcut()
        assert integration.is_installed()["desktop_shortcut"] is False
    
    def test_mock_install_all(self):
        """Test installing all components."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        
        result = integration.install_all(icon_source="/path/icon.png")
        
        assert result is True
        status = integration.is_installed()
        assert status["desktop_file"] is True
        assert status["protocol_handler"] is True
        assert status["icon"] is True
    
    def test_mock_uninstall_all(self):
        """Test uninstalling all components."""
        from bantz.system.desktop import MockDesktopIntegration
        
        integration = MockDesktopIntegration()
        integration.install_all()
        integration.create_desktop_shortcut()
        
        result = integration.uninstall_all()
        
        assert result is True
        status = integration.is_installed()
        assert status["desktop_file"] is False
        assert status["protocol_handler"] is False


class TestDesktopIntegration:
    """Tests for DesktopIntegration with temp directories."""
    
    def test_install_desktop_file_with_temp(self):
        """Test installing desktop file."""
        from bantz.system.desktop import DesktopIntegration, XDGPaths
        
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = XDGPaths(
                data_home=Path(tmpdir) / "data",
                config_home=Path(tmpdir) / "config",
            )
            
            integration = DesktopIntegration(executable="/usr/bin/bantz")
            integration.xdg = paths
            
            result = integration.install_desktop_file()
            
            assert result is True
            desktop_file = paths.applications_dir / f"{integration.APP_ID}.desktop"
            assert desktop_file.exists()
            
            content = desktop_file.read_text()
            assert "Bantz Assistant" in content
            assert "/usr/bin/bantz" in content
    
    def test_register_protocol_handler_with_temp(self):
        """Test registering protocol handler."""
        from bantz.system.desktop import DesktopIntegration, XDGPaths
        
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = XDGPaths(
                data_home=Path(tmpdir) / "data",
                config_home=Path(tmpdir) / "config",
            )
            
            integration = DesktopIntegration()
            integration.xdg = paths
            
            result = integration.register_protocol_handler()
            
            assert result is True
            handler_file = paths.applications_dir / f"{integration.APP_ID}-handler.desktop"
            assert handler_file.exists()
            
            content = handler_file.read_text()
            assert "x-scheme-handler/bantz" in content
    
    def test_is_installed(self):
        """Test installation status check."""
        from bantz.system.desktop import DesktopIntegration, XDGPaths
        
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = XDGPaths(
                data_home=Path(tmpdir) / "data",
                config_home=Path(tmpdir) / "config",
            )
            
            integration = DesktopIntegration()
            integration.xdg = paths
            
            # Initially not installed
            status = integration.is_installed()
            assert status["desktop_file"] is False
            assert status["protocol_handler"] is False
            
            # Install
            integration.install_desktop_file()
            integration.register_protocol_handler()
            
            status = integration.is_installed()
            assert status["desktop_file"] is True
            assert status["protocol_handler"] is True


# =============================================================================
# Integration Tests
# =============================================================================

class TestSystemIntegration:
    """Integration tests for system module."""
    
    def test_imports(self):
        """Test all imports work."""
        from bantz.system import (
            NotificationListener,
            Notification,
            NotificationFilter,
            GlobalShortcuts,
            ShortcutAction,
            ShortcutConfig,
            SystemTray,
            TrayStatus,
            TrayMenuItem,
            AutoStart,
            AutoStartConfig,
            DesktopIntegration,
            XDGPaths,
            MimeHandler,
        )
        
        # All imports should work
        assert NotificationListener is not None
        assert GlobalShortcuts is not None
        assert SystemTray is not None
        assert AutoStart is not None
        assert DesktopIntegration is not None
    
    @pytest.mark.asyncio
    async def test_full_mock_workflow(self):
        """Test full workflow with mock classes."""
        from bantz.system.notifications import MockNotificationListener
        from bantz.system.shortcuts import MockGlobalShortcuts, ShortcutAction
        from bantz.system.tray import MockSystemTray, TrayStatus
        
        # Setup components
        notifications_received = []
        listener = MockNotificationListener(lambda n: notifications_received.append(n))
        
        shortcuts = MockGlobalShortcuts()
        tray = MockSystemTray()
        
        # Start all
        await listener.start()
        shortcuts.start()
        tray.show()
        
        # Test notification -> tray update
        tray.update_status(TrayStatus.IDLE)
        
        await listener.emit("Discord", "New Message", "Hello!")
        assert len(notifications_received) == 1
        
        # Test shortcut handler
        activated = []
        shortcuts.register_handler(ShortcutAction.ACTIVATE, lambda: activated.append(True))
        shortcuts.trigger_action(ShortcutAction.ACTIVATE)
        
        # Test tray notification
        tray.notify("Komut Alındı", "İşleniyor...")
        tray.update_status(TrayStatus.PROCESSING)
        
        assert len(tray.notifications) == 1
        assert tray.status == TrayStatus.PROCESSING
        
        # Cleanup
        await listener.stop()
        shortcuts.stop()
        tray.hide()
        
        assert listener.is_running is False
        assert shortcuts.is_running is False
        assert tray.is_visible is False


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""
    
    def test_notification_empty_body(self):
        """Test notification with empty body."""
        from bantz.system.notifications import Notification
        
        notif = Notification(app_name="Test", summary="Title", body="")
        
        assert notif.body == ""
        assert notif.matches_content("Title") is True
        assert notif.matches_content("body") is False
    
    def test_filter_empty_patterns(self):
        """Test filter with empty patterns."""
        from bantz.system.notifications import Notification, NotificationFilter
        
        filter_ = NotificationFilter()
        notif = Notification(app_name="Any", summary="Any")
        
        # Empty filter should match everything
        assert filter_.matches(notif) is True
    
    def test_shortcut_disabled(self):
        """Test disabled shortcut doesn't trigger."""
        from bantz.system.shortcuts import MockGlobalShortcuts
        
        shortcuts = MockGlobalShortcuts()
        shortcuts.start()
        
        # Disable the activate shortcut
        shortcuts.enable_shortcut("<ctrl>+<alt>+b", False)
        
        # Should fail to trigger
        result = shortcuts.trigger("<ctrl>+<alt>+b")
        assert result is False
    
    def test_tray_menu_item_not_found(self):
        """Test selecting non-existent menu item."""
        from bantz.system.tray import MockSystemTray
        
        tray = MockSystemTray()
        tray.show()
        
        result = tray.select_menu_item("Non-existent Item")
        assert result is False
    
    def test_autostart_already_disabled(self):
        """Test disabling when already disabled."""
        from bantz.system.autostart import AutoStart
        
        with tempfile.TemporaryDirectory() as tmpdir:
            desktop_file = Path(tmpdir) / AutoStart.DESKTOP_FILENAME
            
            with patch.object(AutoStart, 'get_desktop_file_path', return_value=desktop_file):
                # Should succeed even if file doesn't exist
                result = AutoStart.disable()
                assert result is True
    
    def test_desktop_integration_no_icon(self):
        """Test desktop integration without icon."""
        from bantz.system.desktop import DesktopIntegration, XDGPaths
        
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = XDGPaths(data_home=Path(tmpdir))
            
            integration = DesktopIntegration(icon_path="")
            integration.xdg = paths
            
            result = integration.install_desktop_file()
            assert result is True
    
    @pytest.mark.asyncio
    async def test_listener_not_running(self):
        """Test emitting when listener not running."""
        from bantz.system.notifications import MockNotificationListener
        
        received = []
        listener = MockNotificationListener(lambda n: received.append(n))
        
        # Don't start, just emit
        await listener.emit("Test", "Message")
        
        # Should not receive
        assert len(received) == 0
