"""
Global Keyboard Shortcuts.

Provides system-wide keyboard shortcuts using pynput.
Works on GNOME, KDE, XFCE, and other Linux desktop environments.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Set, Any
import logging
import threading
import time

logger = logging.getLogger(__name__)


class ShortcutAction(Enum):
    """Predefined shortcut actions."""
    ACTIVATE = auto()       # Bring up Bantz
    TOGGLE_MUTE = auto()    # Mute/unmute
    TOGGLE_PAUSE = auto()   # Pause/resume listening
    TOGGLE_OVERLAY = auto() # Show/hide overlay
    VOICE_COMMAND = auto()  # Start voice command
    TEXT_COMMAND = auto()   # Open text input
    SCREENSHOT = auto()     # Take screenshot
    QUIT = auto()           # Quit application
    CUSTOM = auto()         # Custom action


@dataclass
class ShortcutConfig:
    """Configuration for a keyboard shortcut."""
    
    keys: str               # Key combination (e.g., "<ctrl>+<alt>+b")
    action: ShortcutAction  # Action to perform
    enabled: bool = True    # Whether shortcut is enabled
    description: str = ""   # Human-readable description
    custom_handler: Optional[Callable[[], None]] = None  # For CUSTOM action
    
    def __post_init__(self):
        if not self.description:
            self.description = self.action.name.replace("_", " ").title()


# Default shortcuts
DEFAULT_SHORTCUTS: List[ShortcutConfig] = [
    ShortcutConfig(
        keys="<ctrl>+<alt>+b",
        action=ShortcutAction.ACTIVATE,
        description="Bantz'ı aktifleştir",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+m",
        action=ShortcutAction.TOGGLE_MUTE,
        description="Mikrofonu sessize al/aç",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+p",
        action=ShortcutAction.TOGGLE_PAUSE,
        description="Dinlemeyi duraklat/devam et",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+o",
        action=ShortcutAction.TOGGLE_OVERLAY,
        description="Overlay'i göster/gizle",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+v",
        action=ShortcutAction.VOICE_COMMAND,
        description="Sesli komut ver",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+t",
        action=ShortcutAction.TEXT_COMMAND,
        description="Yazılı komut gir",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+s",
        action=ShortcutAction.SCREENSHOT,
        description="Ekran görüntüsü al",
    ),
    ShortcutConfig(
        keys="<ctrl>+<alt>+q",
        action=ShortcutAction.QUIT,
        description="Çıkış",
    ),
]


class GlobalShortcuts:
    """
    Global keyboard shortcuts for quick access.
    
    Uses pynput for system-wide keyboard monitoring.
    
    Example:
        def on_activate():
            print("Bantz activated!")
        
        shortcuts = GlobalShortcuts()
        shortcuts.register_handler(ShortcutAction.ACTIVATE, on_activate)
        shortcuts.start()
    """
    
    def __init__(
        self,
        shortcuts: Optional[List[ShortcutConfig]] = None,
        handlers: Optional[Dict[ShortcutAction, Callable[[], None]]] = None,
    ):
        """
        Initialize global shortcuts.
        
        Args:
            shortcuts: List of shortcut configurations (defaults to DEFAULT_SHORTCUTS)
            handlers: Optional dict of action handlers
        """
        self.shortcuts = shortcuts or DEFAULT_SHORTCUTS.copy()
        self.handlers: Dict[ShortcutAction, Callable[[], None]] = handlers or {}
        
        self._listener = None
        self._running = False
        self._lock = threading.Lock()
        self._pressed_keys: Set[str] = set()
        self._last_trigger_time: Dict[str, float] = {}
        self._debounce_interval = 0.3  # 300ms debounce
    
    @property
    def is_running(self) -> bool:
        """Check if shortcuts are active."""
        return self._running
    
    def register_handler(
        self,
        action: ShortcutAction,
        handler: Callable[[], None],
    ) -> None:
        """
        Register a handler for an action.
        
        Args:
            action: The action to handle
            handler: Function to call when action triggered
        """
        with self._lock:
            self.handlers[action] = handler
        logger.debug(f"Registered handler for {action.name}")
    
    def unregister_handler(self, action: ShortcutAction) -> None:
        """Unregister a handler."""
        with self._lock:
            self.handlers.pop(action, None)
    
    def add_shortcut(self, config: ShortcutConfig) -> None:
        """Add a new shortcut."""
        with self._lock:
            # Remove existing if same keys
            self.shortcuts = [s for s in self.shortcuts if s.keys != config.keys]
            self.shortcuts.append(config)
        
        # Restart if running to apply changes
        if self._running:
            self.stop()
            self.start()
    
    def remove_shortcut(self, keys: str) -> bool:
        """Remove a shortcut by its key combination."""
        with self._lock:
            original_len = len(self.shortcuts)
            self.shortcuts = [s for s in self.shortcuts if s.keys != keys]
            removed = len(self.shortcuts) < original_len
        
        if removed and self._running:
            self.stop()
            self.start()
        
        return removed
    
    def enable_shortcut(self, keys: str, enabled: bool = True) -> bool:
        """Enable or disable a shortcut."""
        with self._lock:
            for shortcut in self.shortcuts:
                if shortcut.keys == keys:
                    shortcut.enabled = enabled
                    return True
        return False
    
    def start(self) -> None:
        """Start listening for shortcuts."""
        if self._running:
            logger.warning("Shortcuts already running")
            return
        
        try:
            from pynput import keyboard
            
            # Build hotkey mappings
            hotkeys = {}
            for shortcut in self.shortcuts:
                if not shortcut.enabled:
                    continue
                
                def make_handler(sc):
                    def handler():
                        self._on_shortcut(sc)
                    return handler
                
                hotkeys[shortcut.keys] = make_handler(shortcut)
            
            if not hotkeys:
                logger.warning("No shortcuts configured")
                return
            
            self._listener = keyboard.GlobalHotKeys(hotkeys)
            self._listener.start()
            self._running = True
            
            logger.info(f"Global shortcuts started ({len(hotkeys)} shortcuts)")
            
        except ImportError:
            logger.error("pynput not installed. Install with: pip install pynput")
            raise
        except Exception as e:
            logger.error(f"Failed to start global shortcuts: {e}")
            raise
    
    def stop(self) -> None:
        """Stop listening for shortcuts."""
        if not self._running:
            return
        
        self._running = False
        
        if self._listener:
            try:
                self._listener.stop()
            except Exception as e:
                logger.debug(f"Error stopping listener: {e}")
            self._listener = None
        
        logger.info("Global shortcuts stopped")
    
    def _on_shortcut(self, shortcut: ShortcutConfig) -> None:
        """Handle shortcut trigger."""
        # Debounce
        now = time.time()
        last_trigger = self._last_trigger_time.get(shortcut.keys, 0)
        if now - last_trigger < self._debounce_interval:
            return
        self._last_trigger_time[shortcut.keys] = now
        
        logger.debug(f"Shortcut triggered: {shortcut.keys} -> {shortcut.action.name}")
        
        # Get handler
        handler = None
        
        if shortcut.action == ShortcutAction.CUSTOM:
            handler = shortcut.custom_handler
        else:
            handler = self.handlers.get(shortcut.action)
        
        if handler:
            try:
                # Run handler in thread to avoid blocking
                threading.Thread(target=handler, daemon=True).start()
            except Exception as e:
                logger.error(f"Error in shortcut handler: {e}")
        else:
            logger.warning(f"No handler for action: {shortcut.action.name}")
    
    def get_shortcut_list(self) -> List[Dict[str, Any]]:
        """Get list of all shortcuts with their status."""
        return [
            {
                "keys": s.keys,
                "action": s.action.name,
                "enabled": s.enabled,
                "description": s.description,
                "has_handler": (
                    s.action == ShortcutAction.CUSTOM and s.custom_handler is not None
                ) or s.action in self.handlers,
            }
            for s in self.shortcuts
        ]
    
    def set_debounce_interval(self, interval: float) -> None:
        """Set debounce interval in seconds."""
        self._debounce_interval = max(0.1, interval)


class MockGlobalShortcuts(GlobalShortcuts):
    """
    Mock global shortcuts for testing without pynput.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._triggered_shortcuts: List[ShortcutConfig] = []
    
    def start(self) -> None:
        """Start mock shortcuts."""
        self._running = True
        logger.info("Mock global shortcuts started")
    
    def stop(self) -> None:
        """Stop mock shortcuts."""
        self._running = False
        logger.info("Mock global shortcuts stopped")
    
    def trigger(self, keys: str) -> bool:
        """Trigger a shortcut for testing."""
        if not self._running:
            return False
        
        for shortcut in self.shortcuts:
            if shortcut.keys == keys and shortcut.enabled:
                self._triggered_shortcuts.append(shortcut)
                self._on_shortcut(shortcut)
                return True
        
        return False
    
    def trigger_action(self, action: ShortcutAction) -> bool:
        """Trigger a shortcut by action for testing."""
        if not self._running:
            return False
        
        for shortcut in self.shortcuts:
            if shortcut.action == action and shortcut.enabled:
                self._triggered_shortcuts.append(shortcut)
                self._on_shortcut(shortcut)
                return True
        
        return False
    
    @property
    def triggered_shortcuts(self) -> List[ShortcutConfig]:
        """Get list of triggered shortcuts."""
        return self._triggered_shortcuts.copy()
    
    def clear_triggered(self) -> None:
        """Clear triggered shortcuts list."""
        self._triggered_shortcuts.clear()


def parse_shortcut_string(shortcut: str) -> Dict[str, Any]:
    """
    Parse a shortcut string into its components.
    
    Args:
        shortcut: Shortcut string like "<ctrl>+<alt>+b"
        
    Returns:
        Dict with modifiers and key
    """
    parts = shortcut.lower().split("+")
    
    modifiers = set()
    key = None
    
    for part in parts:
        part = part.strip()
        if part in ("<ctrl>", "<control>"):
            modifiers.add("ctrl")
        elif part in ("<alt>",):
            modifiers.add("alt")
        elif part in ("<shift>",):
            modifiers.add("shift")
        elif part in ("<super>", "<cmd>", "<win>"):
            modifiers.add("super")
        elif part.startswith("<") and part.endswith(">"):
            # Special key like <space>, <enter>
            key = part[1:-1]
        else:
            key = part
    
    return {
        "modifiers": modifiers,
        "key": key,
        "original": shortcut,
    }


def format_shortcut_display(shortcut: str) -> str:
    """
    Format shortcut for display.
    
    Args:
        shortcut: Shortcut string like "<ctrl>+<alt>+b"
        
    Returns:
        Display string like "Ctrl+Alt+B"
    """
    replacements = {
        "<ctrl>": "Ctrl",
        "<control>": "Ctrl",
        "<alt>": "Alt",
        "<shift>": "Shift",
        "<super>": "Super",
        "<cmd>": "Cmd",
        "<win>": "Win",
        "<space>": "Space",
        "<enter>": "Enter",
        "<return>": "Return",
        "<tab>": "Tab",
        "<escape>": "Esc",
        "<backspace>": "Backspace",
        "<delete>": "Delete",
    }
    
    result = shortcut
    for old, new in replacements.items():
        result = result.replace(old, new)
    
    # Capitalize single letter keys
    parts = result.split("+")
    formatted = []
    for part in parts:
        if len(part) == 1:
            formatted.append(part.upper())
        else:
            formatted.append(part)
    
    return "+".join(formatted)
