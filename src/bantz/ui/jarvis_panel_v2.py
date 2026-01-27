"""
Panel State and Extended JarvisPanel (Issue #34 - UI-2).

Extends the existing JarvisPanel with:
- State machine (HIDDEN, OPENING, OPEN, CLOSING, MINIMIZED)
- Iris/curtain animation support
- SourceCard integration
- Ticker integration
- ImageSlot integration
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Callable
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QScrollArea, QLabel, QGridLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve

from bantz.core.events import EventBus


class PanelState(Enum):
    """Panel visibility states."""
    HIDDEN = "hidden"
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    MINIMIZED = "minimized"


@dataclass
class PanelConfig:
    """Configuration for JarvisPanelV2."""
    width: int = 400
    height: int = 600
    min_width: int = 300
    min_height: int = 200
    max_cards: int = 10
    max_images: int = 4
    default_animation: str = "iris"
    animation_duration_ms: int = 300


class JarvisPanelV2(QWidget):
    """
    Extended Jarvis Panel with state machine and animations.
    
    Features:
    - State machine: HIDDEN → OPENING → OPEN → CLOSING → HIDDEN
    - Iris/curtain/fade/slide animations
    - SourceCard list with scroll
    - Ticker for status messages
    - Image slots for visual content
    """
    
    # Signals
    state_changed = pyqtSignal(str)  # Emits new state name
    card_clicked = pyqtSignal(str)   # Emits card URL
    animation_finished = pyqtSignal()
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[PanelConfig] = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        
        self.event_bus = event_bus
        self.config = config or PanelConfig()
        self._state = PanelState.HIDDEN
        self._cards: List["SourceCard"] = []
        self._animator: Optional["PanelAnimator"] = None
        self._ticker: Optional["Ticker"] = None
        self._image_slots: List["ImageSlot"] = []
        
        self._setup_ui()
        self._setup_animations()
        
        # Initially hidden
        self.hide()
    
    def _setup_ui(self):
        """Setup panel UI structure."""
        # Import here to avoid circular imports
        from bantz.ui.source_card import SourceCard
        from bantz.ui.ticker import Ticker
        from bantz.ui.image_slot import ImageSlot
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Set size
        self.setMinimumSize(self.config.min_width, self.config.min_height)
        self.resize(self.config.width, self.config.height)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)
        
        # Container frame with styling
        self._container = QFrame()
        self._container.setObjectName("jarvis_container")
        self._container.setStyleSheet("""
            QFrame#jarvis_container {
                background-color: rgba(10, 25, 47, 0.92);
                border: 1px solid rgba(0, 162, 255, 0.6);
                border-radius: 12px;
            }
        """)
        
        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(12, 12, 12, 12)
        container_layout.setSpacing(10)
        
        # Ticker at top
        self._ticker = Ticker()
        container_layout.addWidget(self._ticker)
        
        # Image slots row
        image_row = QHBoxLayout()
        image_row.setSpacing(8)
        for i in range(self.config.max_images):
            slot = ImageSlot(slot_id=i)
            slot.setVisible(False)  # Hidden by default
            self._image_slots.append(slot)
            image_row.addWidget(slot)
        image_row.addStretch()
        container_layout.addLayout(image_row)
        
        # Scrollable card area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(0, 40, 80, 0.5);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 162, 255, 0.6);
                border-radius: 4px;
            }
        """)
        
        # Card container
        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)
        self._card_layout.addStretch()
        
        scroll_area.setWidget(self._card_container)
        container_layout.addWidget(scroll_area, 1)  # Stretch
        
        main_layout.addWidget(self._container)
    
    def _setup_animations(self):
        """Setup animation controller."""
        from bantz.ui.panel_animator import PanelAnimator
        self._animator = PanelAnimator(self)
        self._animator.animation_finished.connect(self._on_animation_finished)
    
    # State management
    @property
    def state(self) -> PanelState:
        """Get current panel state."""
        return self._state
    
    def _set_state(self, new_state: PanelState):
        """Set panel state and emit signal."""
        if self._state != new_state:
            self._state = new_state
            self.state_changed.emit(new_state.value)
    
    def show_panel(self, animation: str = "iris") -> None:
        """
        Show panel with animation.
        
        Args:
            animation: Animation type ("iris", "curtain", "fade", "slide")
        """
        if self._state in (PanelState.OPEN, PanelState.OPENING):
            return
        
        self._set_state(PanelState.OPENING)
        self.show()
        
        if self._animator:
            from bantz.ui.panel_animator import AnimationType
            anim_type = AnimationType(animation)
            self._animator.animate_open(
                anim_type,
                duration_ms=self.config.animation_duration_ms
            )
        else:
            # No animation, go directly to OPEN
            self._set_state(PanelState.OPEN)
    
    def hide_panel(self, animation: str = "fade") -> None:
        """
        Hide panel with animation.
        
        Args:
            animation: Animation type ("iris", "curtain", "fade", "slide")
        """
        if self._state in (PanelState.HIDDEN, PanelState.CLOSING):
            return
        
        self._set_state(PanelState.CLOSING)
        
        if self._animator:
            from bantz.ui.panel_animator import AnimationType
            anim_type = AnimationType(animation)
            self._animator.animate_close(
                anim_type,
                duration_ms=self.config.animation_duration_ms
            )
        else:
            # No animation
            self.hide()
            self._set_state(PanelState.HIDDEN)
    
    def minimize(self) -> None:
        """Minimize panel to icon/bar."""
        if self._state == PanelState.MINIMIZED:
            return
        
        # Shrink animation
        self._set_state(PanelState.MINIMIZED)
        self.resize(self.config.min_width, 40)  # Thin bar
    
    def maximize(self) -> None:
        """Restore panel from minimized state."""
        if self._state != PanelState.MINIMIZED:
            return
        
        self._set_state(PanelState.OPEN)
        self.resize(self.config.width, self.config.height)
    
    def _on_animation_finished(self):
        """Handle animation completion."""
        if self._state == PanelState.OPENING:
            self._set_state(PanelState.OPEN)
        elif self._state == PanelState.CLOSING:
            self.hide()
            self._set_state(PanelState.HIDDEN)
        
        self.animation_finished.emit()
    
    # Content management
    def add_card(self, card: "SourceCard") -> None:
        """
        Add a source card to the panel.
        
        Args:
            card: SourceCard widget to add
        """
        from bantz.ui.source_card import SourceCard
        
        # Remove stretch temporarily
        stretch = self._card_layout.takeAt(self._card_layout.count() - 1)
        
        # Add card
        self._card_layout.addWidget(card)
        self._cards.append(card)
        
        # Connect click
        card.clicked.connect(lambda url=card.data.url: self.card_clicked.emit(url))
        
        # Re-add stretch
        self._card_layout.addStretch()
        
        # Limit cards
        while len(self._cards) > self.config.max_cards:
            old_card = self._cards.pop(0)
            old_card.deleteLater()
    
    def update_ticker(self, message: str) -> None:
        """
        Update ticker with new message.
        
        Args:
            message: Message to display
        """
        if self._ticker:
            self._ticker.set_message(message)
    
    def set_image(self, slot: int, image_path: str) -> None:
        """
        Set image in a slot.
        
        Args:
            slot: Slot index (0-based)
            image_path: Path or URL to image
        """
        if 0 <= slot < len(self._image_slots):
            self._image_slots[slot].set_image(image_path)
            self._image_slots[slot].setVisible(True)
    
    def clear(self) -> None:
        """Clear all content from panel."""
        # Clear cards
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        
        # Clear ticker
        if self._ticker:
            self._ticker.clear()
        
        # Clear image slots
        for slot in self._image_slots:
            slot.clear()
            slot.setVisible(False)
    
    def get_card_count(self) -> int:
        """Get number of cards in panel."""
        return len(self._cards)
