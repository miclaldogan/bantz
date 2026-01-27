"""
Panel Event Binding (Issue #34 - UI-2).

Connects JarvisPanel to EventBus for:
- Research events (found, progress, result, error)
- State synchronization
- Command routing
"""

from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass
from PyQt5.QtCore import QObject, pyqtSignal

# Import from core events
from bantz.core.events import EventBus, Event


@dataclass
class PanelEventConfig:
    """Configuration for panel event binding."""
    auto_show_on_result: bool = True
    auto_hide_on_error: bool = False
    show_progress_ticker: bool = True
    max_source_cards: int = 5


class PanelEventBinder(QObject):
    """
    Binds JarvisPanel to EventBus events.
    
    Handles:
    - research.found -> Add source cards
    - research.progress -> Update ticker
    - research.result -> Show result, update ticker
    - research.error -> Show error state
    - panel.* commands -> Panel state control
    """
    
    # Internal signals for thread-safe updates
    _found_signal = pyqtSignal(dict)
    _progress_signal = pyqtSignal(str, float)
    _result_signal = pyqtSignal(dict)
    _error_signal = pyqtSignal(str)
    _command_signal = pyqtSignal(str, dict)
    
    def __init__(
        self,
        panel,  # JarvisPanelV2
        event_bus: Optional[EventBus] = None,
        config: Optional[PanelEventConfig] = None
    ):
        super().__init__()
        
        self.panel = panel
        self.event_bus = event_bus
        self.config = config or PanelEventConfig()
        
        self._subscriptions: List[int] = []
        self._bound = False
        
        # Connect internal signals to handlers
        self._found_signal.connect(self._handle_found)
        self._progress_signal.connect(self._handle_progress)
        self._result_signal.connect(self._handle_result)
        self._error_signal.connect(self._handle_error)
        self._command_signal.connect(self._handle_command)
    
    def bind_all(self) -> None:
        """Bind all panel-related events."""
        if self._bound:
            return
        
        if not self.event_bus:
            return
        
        # Subscribe to research events
        self._subscriptions.append(
            self.event_bus.subscribe("research.found", self.on_found)
        )
        self._subscriptions.append(
            self.event_bus.subscribe("research.progress", self.on_progress)
        )
        self._subscriptions.append(
            self.event_bus.subscribe("research.result", self.on_result)
        )
        self._subscriptions.append(
            self.event_bus.subscribe("research.error", self.on_error)
        )
        
        # Subscribe to panel commands
        self._subscriptions.append(
            self.event_bus.subscribe("panel.show", lambda e: self._command_signal.emit("show", e.data))
        )
        self._subscriptions.append(
            self.event_bus.subscribe("panel.hide", lambda e: self._command_signal.emit("hide", e.data))
        )
        self._subscriptions.append(
            self.event_bus.subscribe("panel.minimize", lambda e: self._command_signal.emit("minimize", e.data))
        )
        self._subscriptions.append(
            self.event_bus.subscribe("panel.clear", lambda e: self._command_signal.emit("clear", e.data))
        )
        
        self._bound = True
    
    def unbind_all(self) -> None:
        """Unbind all subscribed events."""
        if not self._bound or not self.event_bus:
            return
        
        for sub_id in self._subscriptions:
            self.event_bus.unsubscribe(sub_id)
        
        self._subscriptions.clear()
        self._bound = False
    
    def on_found(self, event: Event) -> None:
        """
        Handle research.found event.
        
        Expected event.data:
            - sources: List[dict] with title, url, date, snippet, reliability
        """
        self._found_signal.emit(event.data)
    
    def on_progress(self, event: Event) -> None:
        """
        Handle research.progress event.
        
        Expected event.data:
            - message: str - Progress message
            - percent: float - Progress percentage (0-1)
        """
        message = event.data.get("message", "")
        percent = event.data.get("percent", 0.0)
        self._progress_signal.emit(message, percent)
    
    def on_result(self, event: Event) -> None:
        """
        Handle research.result event.
        
        Expected event.data:
            - summary: str - Result summary
            - sources: List[dict] - Source references
            - image: Optional[str] - Image path
        """
        self._result_signal.emit(event.data)
    
    def on_error(self, event: Event) -> None:
        """
        Handle research.error event.
        
        Expected event.data:
            - message: str - Error message
        """
        message = event.data.get("message", "Bir hata oluştu")
        self._error_signal.emit(message)
    
    def _handle_found(self, data: dict) -> None:
        """Handle found sources (thread-safe)."""
        sources = data.get("sources", [])
        
        for source in sources[:self.config.max_source_cards]:
            self.panel.add_card(source)
    
    def _handle_progress(self, message: str, percent: float) -> None:
        """Handle progress update (thread-safe)."""
        if self.config.show_progress_ticker:
            # Format progress message
            if percent > 0:
                progress_text = f"{message} ({int(percent * 100)}%)"
            else:
                progress_text = message
            
            self.panel.update_ticker(progress_text)
    
    def _handle_result(self, data: dict) -> None:
        """Handle research result (thread-safe)."""
        # Show panel if configured
        if self.config.auto_show_on_result:
            self.panel.show_panel()
        
        # Update ticker with summary
        summary = data.get("summary", "")
        if summary:
            self.panel.update_ticker(summary)
        
        # Add source cards
        sources = data.get("sources", [])
        for source in sources[:self.config.max_source_cards]:
            self.panel.add_card(source)
        
        # Set image if available
        image_path = data.get("image")
        if image_path:
            self.panel.set_image(image_path)
    
    def _handle_error(self, message: str) -> None:
        """Handle error (thread-safe)."""
        # Update ticker with error
        self.panel.update_ticker(f"⚠️ {message}")
        
        # Hide panel if configured
        if self.config.auto_hide_on_error:
            self.panel.hide_panel()
    
    def _handle_command(self, command: str, data: dict) -> None:
        """Handle panel command (thread-safe)."""
        if command == "show":
            animation = data.get("animation")
            self.panel.show_panel(animation_type=animation)
        elif command == "hide":
            self.panel.hide_panel()
        elif command == "minimize":
            self.panel.minimize()
        elif command == "clear":
            self.panel.clear()
    
    def is_bound(self) -> bool:
        """Check if binder is currently bound to events."""
        return self._bound


def create_panel_binder(
    panel,
    event_bus: Optional[EventBus] = None,
    auto_bind: bool = True,
    **config_kwargs
) -> PanelEventBinder:
    """
    Factory function to create and optionally bind a panel event binder.
    
    Args:
        panel: JarvisPanelV2 instance
        event_bus: Optional EventBus instance
        auto_bind: Whether to automatically bind events
        **config_kwargs: PanelEventConfig parameters
    
    Returns:
        Configured PanelEventBinder
    """
    config = PanelEventConfig(**config_kwargs)
    binder = PanelEventBinder(panel, event_bus, config)
    
    if auto_bind and event_bus:
        binder.bind_all()
    
    return binder
