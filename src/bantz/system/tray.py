"""
System Tray Icon.

Provides system tray integration with menu and notifications.
Uses PyQt5 or fallback to pystray for cross-platform support.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Any
import logging
import threading
import os

logger = logging.getLogger(__name__)


class TrayStatus(Enum):
    """Tray icon status states."""
    IDLE = auto()           # Waiting for command
    LISTENING = auto()      # Actively listening
    PROCESSING = auto()     # Processing command
    SPEAKING = auto()       # TTS speaking
    MUTED = auto()          # Microphone muted
    PAUSED = auto()         # Paused
    ERROR = auto()          # Error state
    DISCONNECTED = auto()   # Not connected


STATUS_ICONS = {
    TrayStatus.IDLE: "🔵",
    TrayStatus.LISTENING: "🟢",
    TrayStatus.PROCESSING: "🟡",
    TrayStatus.SPEAKING: "💬",
    TrayStatus.MUTED: "🔇",
    TrayStatus.PAUSED: "⏸️",
    TrayStatus.ERROR: "🔴",
    TrayStatus.DISCONNECTED: "⚫",
}

STATUS_TEXTS = {
    TrayStatus.IDLE: "Hazır",
    TrayStatus.LISTENING: "Dinliyorum",
    TrayStatus.PROCESSING: "İşleniyor",
    TrayStatus.SPEAKING: "Konuşuyor",
    TrayStatus.MUTED: "Sessiz",
    TrayStatus.PAUSED: "Duraklatıldı",
    TrayStatus.ERROR: "Hata",
    TrayStatus.DISCONNECTED: "Bağlantı Yok",
}


@dataclass
class TrayMenuItem:
    """Menu item configuration."""
    
    label: str
    action: Optional[Callable[[], None]] = None
    icon: str = ""
    enabled: bool = True
    checked: bool = False
    checkable: bool = False
    separator_after: bool = False
    submenu: List["TrayMenuItem"] = field(default_factory=list)
    
    @property
    def is_separator(self) -> bool:
        return self.label == "-"
    
    @staticmethod
    def separator() -> "TrayMenuItem":
        return TrayMenuItem(label="-")


class SystemTray:
    """
    System tray icon with menu.
    
    Provides:
    - Status indicator with icon
    - Context menu with actions
    - System notifications
    - Click handling
    
    Example:
        tray = SystemTray()
        tray.add_menu_item("🎤 Sesli Komut", on_voice_command)
        tray.add_menu_item("⚙️ Ayarlar", on_settings)
        tray.show()
        
        tray.update_status(TrayStatus.LISTENING)
        tray.notify("Komut alındı", "YouTube'u açıyorum")
    """
    
    DEFAULT_ICON_PATH = "icons/bantz.png"
    APP_NAME = "Bantz Assistant"
    
    def __init__(
        self,
        icon_path: Optional[str] = None,
        tooltip: str = "Bantz - Kişisel Asistan",
        use_qt: bool = True,
    ):
        """
        Initialize system tray.
        
        Args:
            icon_path: Path to tray icon
            tooltip: Tooltip text
            use_qt: Whether to use PyQt5 (vs pystray fallback)
        """
        self.icon_path = icon_path or self.DEFAULT_ICON_PATH
        self.tooltip = tooltip
        self.use_qt = use_qt
        
        self._status = TrayStatus.IDLE
        self._menu_items: List[TrayMenuItem] = []
        self._tray = None
        self._app = None
        self._running = False
        self._thread = None
        
        # Event handlers
        self.on_click: Optional[Callable[[], None]] = None
        self.on_double_click: Optional[Callable[[], None]] = None
        self.on_quit: Optional[Callable[[], None]] = None
        
        # Build default menu
        self._build_default_menu()
    
    @property
    def status(self) -> TrayStatus:
        """Get current status."""
        return self._status
    
    @property
    def is_visible(self) -> bool:
        """Check if tray is visible."""
        return self._running and self._tray is not None
    
    def _build_default_menu(self) -> None:
        """Build default menu items."""
        self._menu_items = [
            TrayMenuItem(
                label=f"{STATUS_ICONS[TrayStatus.IDLE]} {STATUS_TEXTS[TrayStatus.IDLE]}",
                enabled=False,
            ),
            TrayMenuItem.separator(),
            TrayMenuItem(
                label="🎤 Sesli Komut",
                icon="🎤",
            ),
            TrayMenuItem(
                label="⌨️ Yazılı Komut",
                icon="⌨️",
            ),
            TrayMenuItem.separator(),
            TrayMenuItem(
                label="⚙️ Ayarlar",
                icon="⚙️",
            ),
            TrayMenuItem(
                label="📊 İstatistikler",
                icon="📊",
            ),
            TrayMenuItem(
                label="📋 Komut Geçmişi",
                icon="📋",
            ),
            TrayMenuItem.separator(),
            TrayMenuItem(
                label="❌ Çıkış",
                icon="❌",
            ),
        ]
    
    def add_menu_item(
        self,
        label: str,
        action: Optional[Callable[[], None]] = None,
        icon: str = "",
        position: int = -1,
    ) -> None:
        """
        Add a menu item.
        
        Args:
            label: Menu item text
            action: Callback function
            icon: Icon emoji/text
            position: Position in menu (-1 for end)
        """
        item = TrayMenuItem(label=label, action=action, icon=icon)
        
        if position < 0:
            # Insert before last item (Quit)
            self._menu_items.insert(len(self._menu_items) - 1, item)
        else:
            self._menu_items.insert(position, item)
        
        self._update_menu()
    
    def remove_menu_item(self, label: str) -> bool:
        """Remove a menu item by label."""
        original_len = len(self._menu_items)
        self._menu_items = [m for m in self._menu_items if m.label != label]
        
        if len(self._menu_items) < original_len:
            self._update_menu()
            return True
        return False
    
    def set_menu_item_action(self, label: str, action: Callable[[], None]) -> bool:
        """Set action for a menu item."""
        for item in self._menu_items:
            if item.label == label or label in item.label:
                item.action = action
                return True
        return False
    
    def update_status(self, status: TrayStatus) -> None:
        """Update tray status."""
        self._status = status
        
        # Update first menu item (status display)
        if self._menu_items:
            icon = STATUS_ICONS.get(status, "●")
            text = STATUS_TEXTS.get(status, status.name)
            self._menu_items[0].label = f"{icon} {text}"
        
        self._update_tooltip()
        self._update_menu()
        
        logger.debug(f"Tray status updated: {status.name}")
    
    def show(self) -> None:
        """Show the tray icon."""
        if self._running:
            return
        
        if self.use_qt:
            self._show_qt()
        else:
            self._show_pystray()
    
    def hide(self) -> None:
        """Hide the tray icon."""
        self._running = False
        
        if self._tray:
            try:
                if self.use_qt:
                    self._tray.hide()
                else:
                    self._tray.stop()
            except Exception as e:
                logger.debug(f"Error hiding tray: {e}")
            self._tray = None
    
    def notify(
        self,
        title: str,
        message: str,
        icon_type: str = "info",
        timeout: int = 3000,
    ) -> None:
        """
        Show a system notification.
        
        Args:
            title: Notification title
            message: Notification body
            icon_type: 'info', 'warning', 'error'
            timeout: Display time in ms
        """
        if not self._tray:
            logger.warning("Tray not initialized, cannot show notification")
            return
        
        try:
            if self.use_qt:
                from PyQt5.QtWidgets import QSystemTrayIcon
                
                icon_map = {
                    "info": QSystemTrayIcon.Information,
                    "warning": QSystemTrayIcon.Warning,
                    "error": QSystemTrayIcon.Critical,
                }
                icon = icon_map.get(icon_type, QSystemTrayIcon.Information)
                self._tray.showMessage(title, message, icon, timeout)
            else:
                self._tray.notify(title, message)
            
            logger.debug(f"Notification shown: {title}")
            
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")
    
    def _show_qt(self) -> None:
        """Show tray using PyQt5."""
        try:
            from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QApplication
            from PyQt5.QtGui import QIcon
            from PyQt5.QtCore import QTimer
            
            # Create or get application
            self._app = QApplication.instance()
            if not self._app:
                self._app = QApplication([])
            
            # Create tray icon
            icon = QIcon(self.icon_path) if os.path.exists(self.icon_path) else QIcon()
            self._tray = QSystemTrayIcon(icon, self._app)
            self._tray.setToolTip(self.tooltip)
            
            # Build menu
            self._update_menu()
            
            # Connect signals
            self._tray.activated.connect(self._on_tray_activated)
            
            # Show
            self._tray.show()
            self._running = True
            
            logger.info("System tray shown (PyQt5)")
            
        except ImportError:
            logger.warning("PyQt5 not available, falling back to pystray")
            self.use_qt = False
            self._show_pystray()
        except Exception as e:
            logger.error(f"Failed to show Qt tray: {e}")
            self.use_qt = False
            self._show_pystray()
    
    def _show_pystray(self) -> None:
        """Show tray using pystray (fallback)."""
        try:
            import pystray
            from PIL import Image
            
            # Load or create icon
            if os.path.exists(self.icon_path):
                icon_image = Image.open(self.icon_path)
            else:
                # Create a simple default icon
                icon_image = Image.new("RGBA", (64, 64), (66, 133, 244, 255))
            
            # Build menu
            menu_items = []
            for item in self._menu_items:
                if item.is_separator:
                    menu_items.append(pystray.Menu.SEPARATOR)
                else:
                    menu_items.append(pystray.MenuItem(
                        item.label,
                        item.action or (lambda: None),
                        enabled=item.enabled,
                        checked=lambda item=item: item.checked if item.checkable else None,
                    ))
            
            menu = pystray.Menu(*menu_items)
            
            # Create tray
            self._tray = pystray.Icon(
                "bantz",
                icon_image,
                self.tooltip,
                menu,
            )
            
            # Run in thread
            self._thread = threading.Thread(target=self._tray.run, daemon=True)
            self._thread.start()
            self._running = True
            
            logger.info("System tray shown (pystray)")
            
        except ImportError:
            logger.error("Neither PyQt5 nor pystray available for system tray")
        except Exception as e:
            logger.error(f"Failed to show pystray tray: {e}")
    
    def _update_menu(self) -> None:
        """Update the menu."""
        if not self._tray or not self.use_qt:
            return
        
        try:
            from PyQt5.QtWidgets import QMenu, QAction
            
            menu = QMenu()
            
            for item in self._menu_items:
                if item.is_separator:
                    menu.addSeparator()
                else:
                    action = menu.addAction(item.label)
                    action.setEnabled(item.enabled)
                    
                    if item.checkable:
                        action.setCheckable(True)
                        action.setChecked(item.checked)
                    
                    if item.action:
                        action.triggered.connect(item.action)
                    
                    # Special handling for Quit
                    if "Çıkış" in item.label or "Quit" in item.label:
                        action.triggered.connect(self._on_quit_clicked)
            
            self._tray.setContextMenu(menu)
            
        except Exception as e:
            logger.error(f"Failed to update menu: {e}")
    
    def _update_tooltip(self) -> None:
        """Update tooltip text."""
        if not self._tray:
            return
        
        status_text = STATUS_TEXTS.get(self._status, self._status.name)
        tooltip = f"{self.tooltip} - {status_text}"
        
        try:
            if self.use_qt:
                self._tray.setToolTip(tooltip)
        except Exception as e:
            logger.debug(f"Failed to update tooltip: {e}")
    
    def _on_tray_activated(self, reason) -> None:
        """Handle tray icon click (Qt)."""
        try:
            from PyQt5.QtWidgets import QSystemTrayIcon
            
            if reason == QSystemTrayIcon.Trigger:
                if self.on_click:
                    self.on_click()
            elif reason == QSystemTrayIcon.DoubleClick:
                if self.on_double_click:
                    self.on_double_click()
        except Exception as e:
            logger.error(f"Error handling tray activation: {e}")
    
    def _on_quit_clicked(self) -> None:
        """Handle quit menu item."""
        if self.on_quit:
            self.on_quit()
        else:
            self.hide()


class MockSystemTray(SystemTray):
    """
    Mock system tray for testing without GUI.
    """
    
    def __init__(self, *args, **kwargs):
        kwargs["use_qt"] = False
        super().__init__(*args, **kwargs)
        self._notifications: List[Dict[str, Any]] = []
        self._status_history: List[TrayStatus] = []
    
    def show(self) -> None:
        """Show mock tray."""
        self._running = True
        self._tray = True  # Mock tray object
        logger.info("Mock system tray shown")
    
    def hide(self) -> None:
        """Hide mock tray."""
        self._running = False
        self._tray = None
        logger.info("Mock system tray hidden")
    
    def notify(self, title: str, message: str, icon_type: str = "info", timeout: int = 3000) -> None:
        """Store notification for testing."""
        self._notifications.append({
            "title": title,
            "message": message,
            "icon_type": icon_type,
            "timeout": timeout,
        })
        logger.debug(f"Mock notification: {title}")
    
    def update_status(self, status: TrayStatus) -> None:
        """Update status and track history."""
        self._status_history.append(status)
        super().update_status(status)
    
    @property
    def notifications(self) -> List[Dict[str, Any]]:
        """Get notification history."""
        return self._notifications.copy()
    
    @property
    def status_history(self) -> List[TrayStatus]:
        """Get status history."""
        return self._status_history.copy()
    
    def clear_history(self) -> None:
        """Clear all history."""
        self._notifications.clear()
        self._status_history.clear()
    
    def click(self) -> None:
        """Simulate click."""
        if self.on_click:
            self.on_click()
    
    def double_click(self) -> None:
        """Simulate double click."""
        if self.on_double_click:
            self.on_double_click()
    
    def select_menu_item(self, label: str) -> bool:
        """Simulate menu item selection."""
        for item in self._menu_items:
            if item.label == label or label in item.label:
                if item.action and item.enabled:
                    item.action()
                    return True
        return False
