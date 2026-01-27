"""
Bantz System Integration Module.

System-level integrations for Linux desktop environments:
- DBus notification listening
- Global keyboard shortcuts
- System tray icon
- Auto-start configuration
- XDG desktop integration
"""

from bantz.system.notifications import (
    NotificationListener,
    Notification,
    NotificationFilter,
)
from bantz.system.shortcuts import (
    GlobalShortcuts,
    ShortcutAction,
    ShortcutConfig,
)
from bantz.system.tray import (
    SystemTray,
    TrayStatus,
    TrayMenuItem,
)
from bantz.system.autostart import (
    AutoStart,
    AutoStartConfig,
)
from bantz.system.desktop import (
    DesktopIntegration,
    XDGPaths,
    MimeHandler,
)

__all__ = [
    # Notifications
    "NotificationListener",
    "Notification",
    "NotificationFilter",
    # Shortcuts
    "GlobalShortcuts",
    "ShortcutAction",
    "ShortcutConfig",
    # Tray
    "SystemTray",
    "TrayStatus",
    "TrayMenuItem",
    # Autostart
    "AutoStart",
    "AutoStartConfig",
    # Desktop
    "DesktopIntegration",
    "XDGPaths",
    "MimeHandler",
]
