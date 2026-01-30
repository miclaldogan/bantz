"""Animation utilities for Jarvis-style overlay (Issue #5).

Provides smooth animations for:
- Fade in/out
- Pulse/breathing effects
- Slide transitions
- Glow pulsing
- State transitions
"""
from __future__ import annotations

from typing import Optional, Callable, List
from enum import Enum

from PyQt5.QtWidgets import QWidget, QGraphicsOpacityEffect, QGraphicsDropShadowEffect
from PyQt5.QtCore import (
    QPropertyAnimation, QSequentialAnimationGroup, QParallelAnimationGroup,
    QEasingCurve, QPoint, QSize, QTimer, pyqtSignal, QObject, QVariantAnimation
)
from PyQt5.QtGui import QColor


class AnimationState(Enum):
    """Animation state."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


class AnimationConfig:
    """Default animation durations and curves."""
    FADE_DURATION = 300
    PULSE_DURATION = 1500
    SLIDE_DURATION = 400
    GLOW_DURATION = 2000
    
    EASE_IN_OUT = QEasingCurve.InOutQuad
    EASE_OUT = QEasingCurve.OutCubic
    EASE_IN = QEasingCurve.InCubic
    EASE_BOUNCE = QEasingCurve.OutBounce


# ─────────────────────────────────────────────────────────────────
# Fade Animations
# ─────────────────────────────────────────────────────────────────

def fade_in(
    widget: QWidget,
    duration: int = AnimationConfig.FADE_DURATION,
    callback: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Fade in a widget from transparent to opaque.
    
    Args:
        widget: Target widget
        duration: Animation duration in ms
        callback: Optional callback when finished
        
    Returns:
        The animation object (keep reference to prevent GC)
    """
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    
    effect.setOpacity(0)
    widget.show()
    
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(AnimationConfig.EASE_OUT)
    
    if callback:
        anim.finished.connect(callback)
    
    anim.start()
    return anim


def fade_out(
    widget: QWidget,
    duration: int = AnimationConfig.FADE_DURATION,
    callback: Optional[Callable] = None,
    hide_on_finish: bool = True,
) -> QPropertyAnimation:
    """Fade out a widget from opaque to transparent.
    
    Args:
        widget: Target widget
        duration: Animation duration in ms
        callback: Optional callback when finished
        hide_on_finish: Hide widget when animation finishes
        
    Returns:
        The animation object
    """
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(AnimationConfig.EASE_IN)
    
    def on_finished():
        if hide_on_finish:
            widget.hide()
        if callback:
            callback()
    
    anim.finished.connect(on_finished)
    anim.start()
    return anim


# ─────────────────────────────────────────────────────────────────
# Pulse Animations
# ─────────────────────────────────────────────────────────────────

class PulseAnimation(QObject):
    """Continuous pulse/breathing animation.
    
    Animates between min and max opacity in a loop.
    """
    value_changed = pyqtSignal(float)  # 0.0 to 1.0
    
    def __init__(
        self,
        widget: Optional[QWidget] = None,
        min_opacity: float = 0.5,
        max_opacity: float = 1.0,
        duration: int = AnimationConfig.PULSE_DURATION,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        
        self.widget = widget
        self.min_opacity = min_opacity
        self.max_opacity = max_opacity
        self.duration = duration
        self._running = False
        
        # Setup effect if widget provided
        if widget:
            self._effect = widget.graphicsEffect()
            if not isinstance(self._effect, QGraphicsOpacityEffect):
                self._effect = QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(self._effect)
        else:
            self._effect = None
        
        # Animation group for smooth looping
        self._anim_group = QSequentialAnimationGroup(self)
        
        # Fade up
        self._fade_up = QVariantAnimation()
        self._fade_up.setDuration(duration // 2)
        self._fade_up.setStartValue(min_opacity)
        self._fade_up.setEndValue(max_opacity)
        self._fade_up.setEasingCurve(QEasingCurve.InOutSine)
        self._fade_up.valueChanged.connect(self._on_value_changed)
        
        # Fade down
        self._fade_down = QVariantAnimation()
        self._fade_down.setDuration(duration // 2)
        self._fade_down.setStartValue(max_opacity)
        self._fade_down.setEndValue(min_opacity)
        self._fade_down.setEasingCurve(QEasingCurve.InOutSine)
        self._fade_down.valueChanged.connect(self._on_value_changed)
        
        self._anim_group.addAnimation(self._fade_up)
        self._anim_group.addAnimation(self._fade_down)
        self._anim_group.setLoopCount(-1)  # Infinite
    
    def _on_value_changed(self, value: float):
        """Handle animation value change."""
        if self._effect:
            self._effect.setOpacity(value)
        self.value_changed.emit(value)
    
    def start(self):
        """Start the pulse animation."""
        if not self._running:
            self._running = True
            self._anim_group.start()
    
    def stop(self):
        """Stop the pulse animation."""
        if self._running:
            self._running = False
            self._anim_group.stop()
            if self._effect:
                self._effect.setOpacity(1.0)
    
    def is_running(self) -> bool:
        """Check if animation is running."""
        return self._running
    
    def set_range(self, min_opacity: float, max_opacity: float):
        """Update opacity range."""
        self.min_opacity = min_opacity
        self.max_opacity = max_opacity
        self._fade_up.setStartValue(min_opacity)
        self._fade_up.setEndValue(max_opacity)
        self._fade_down.setStartValue(max_opacity)
        self._fade_down.setEndValue(min_opacity)


# ─────────────────────────────────────────────────────────────────
# Slide Animations
# ─────────────────────────────────────────────────────────────────

class SlideDirection(Enum):
    """Slide direction."""
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


def slide_in(
    widget: QWidget,
    direction: SlideDirection = SlideDirection.RIGHT,
    distance: int = 100,
    duration: int = AnimationConfig.SLIDE_DURATION,
    callback: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Slide widget in from off-screen.
    
    Args:
        widget: Target widget
        direction: Direction to slide from
        distance: Distance to slide in pixels
        duration: Animation duration in ms
        callback: Optional callback when finished
        
    Returns:
        The animation object
    """
    end_pos = widget.pos()
    
    # Calculate start position based on direction
    if direction == SlideDirection.LEFT:
        start_pos = QPoint(end_pos.x() - distance, end_pos.y())
    elif direction == SlideDirection.RIGHT:
        start_pos = QPoint(end_pos.x() + distance, end_pos.y())
    elif direction == SlideDirection.UP:
        start_pos = QPoint(end_pos.x(), end_pos.y() - distance)
    else:  # DOWN
        start_pos = QPoint(end_pos.x(), end_pos.y() + distance)
    
    widget.move(start_pos)
    widget.show()
    
    anim = QPropertyAnimation(widget, b"pos")
    anim.setDuration(duration)
    anim.setStartValue(start_pos)
    anim.setEndValue(end_pos)
    anim.setEasingCurve(AnimationConfig.EASE_OUT)
    
    if callback:
        anim.finished.connect(callback)
    
    anim.start()
    return anim


def slide_out(
    widget: QWidget,
    direction: SlideDirection = SlideDirection.RIGHT,
    distance: int = 100,
    duration: int = AnimationConfig.SLIDE_DURATION,
    callback: Optional[Callable] = None,
    hide_on_finish: bool = True,
) -> QPropertyAnimation:
    """Slide widget out off-screen.
    
    Args:
        widget: Target widget
        direction: Direction to slide to
        distance: Distance to slide in pixels
        duration: Animation duration in ms
        callback: Optional callback when finished
        hide_on_finish: Hide widget when animation finishes
        
    Returns:
        The animation object
    """
    start_pos = widget.pos()
    
    # Calculate end position based on direction
    if direction == SlideDirection.LEFT:
        end_pos = QPoint(start_pos.x() - distance, start_pos.y())
    elif direction == SlideDirection.RIGHT:
        end_pos = QPoint(start_pos.x() + distance, start_pos.y())
    elif direction == SlideDirection.UP:
        end_pos = QPoint(start_pos.x(), start_pos.y() - distance)
    else:  # DOWN
        end_pos = QPoint(start_pos.x(), start_pos.y() + distance)
    
    anim = QPropertyAnimation(widget, b"pos")
    anim.setDuration(duration)
    anim.setStartValue(start_pos)
    anim.setEndValue(end_pos)
    anim.setEasingCurve(AnimationConfig.EASE_IN)
    
    def on_finished():
        if hide_on_finish:
            widget.hide()
            widget.move(start_pos)  # Reset position
        if callback:
            callback()
    
    anim.finished.connect(on_finished)
    anim.start()
    return anim


def slide_to(
    widget: QWidget,
    target_pos: QPoint,
    duration: int = AnimationConfig.SLIDE_DURATION,
    callback: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Slide widget to a specific position.
    
    Args:
        widget: Target widget
        target_pos: Target position
        duration: Animation duration in ms
        callback: Optional callback when finished
        
    Returns:
        The animation object
    """
    anim = QPropertyAnimation(widget, b"pos")
    anim.setDuration(duration)
    anim.setStartValue(widget.pos())
    anim.setEndValue(target_pos)
    anim.setEasingCurve(AnimationConfig.EASE_OUT)
    
    if callback:
        anim.finished.connect(callback)
    
    anim.start()
    return anim


# ─────────────────────────────────────────────────────────────────
# Glow Animation
# ─────────────────────────────────────────────────────────────────

class GlowAnimation(QObject):
    """Animated glow effect for widgets.
    
    Uses QGraphicsDropShadowEffect to create pulsing glow.
    """
    blur_changed = pyqtSignal(float)
    
    def __init__(
        self,
        widget: QWidget,
        color: QColor,
        min_blur: float = 10,
        max_blur: float = 30,
        duration: int = AnimationConfig.GLOW_DURATION,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        
        self.widget = widget
        self.color = color
        self.min_blur = min_blur
        self.max_blur = max_blur
        self.duration = duration
        self._running = False
        
        # Setup shadow effect
        self._effect = QGraphicsDropShadowEffect(widget)
        self._effect.setColor(color)
        self._effect.setBlurRadius(min_blur)
        self._effect.setOffset(0, 0)
        widget.setGraphicsEffect(self._effect)
        
        # Animation
        self._anim_group = QSequentialAnimationGroup(self)
        
        # Glow up
        self._glow_up = QVariantAnimation()
        self._glow_up.setDuration(duration // 2)
        self._glow_up.setStartValue(min_blur)
        self._glow_up.setEndValue(max_blur)
        self._glow_up.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_up.valueChanged.connect(self._on_blur_changed)
        
        # Glow down
        self._glow_down = QVariantAnimation()
        self._glow_down.setDuration(duration // 2)
        self._glow_down.setStartValue(max_blur)
        self._glow_down.setEndValue(min_blur)
        self._glow_down.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_down.valueChanged.connect(self._on_blur_changed)
        
        self._anim_group.addAnimation(self._glow_up)
        self._anim_group.addAnimation(self._glow_down)
        self._anim_group.setLoopCount(-1)
    
    def _on_blur_changed(self, value: float):
        """Handle blur value change."""
        self._effect.setBlurRadius(value)
        self.blur_changed.emit(value)
    
    def start(self):
        """Start the glow animation."""
        if not self._running:
            self._running = True
            self._anim_group.start()
    
    def stop(self):
        """Stop the glow animation."""
        if self._running:
            self._running = False
            self._anim_group.stop()
            self._effect.setBlurRadius(self.min_blur)
    
    def is_running(self) -> bool:
        """Check if animation is running."""
        return self._running
    
    def set_color(self, color: QColor):
        """Update glow color."""
        self.color = color
        self._effect.setColor(color)


# ─────────────────────────────────────────────────────────────────
# Scale Animation
# ─────────────────────────────────────────────────────────────────

def scale_bounce(
    widget: QWidget,
    scale_factor: float = 1.1,
    duration: int = 200,
    callback: Optional[Callable] = None,
) -> QPropertyAnimation:
    """Quick scale bounce effect (grow then shrink back).
    
    Args:
        widget: Target widget
        scale_factor: Maximum scale (e.g., 1.1 = 10% larger)
        duration: Total animation duration in ms
        callback: Optional callback when finished
        
    Returns:
        The animation object
    """
    original_size = widget.size()
    scaled_size = QSize(
        int(original_size.width() * scale_factor),
        int(original_size.height() * scale_factor),
    )
    
    group = QSequentialAnimationGroup(widget)
    
    # Scale up
    scale_up = QPropertyAnimation(widget, b"size")
    scale_up.setDuration(duration // 2)
    scale_up.setStartValue(original_size)
    scale_up.setEndValue(scaled_size)
    scale_up.setEasingCurve(QEasingCurve.OutQuad)
    
    # Scale down
    scale_down = QPropertyAnimation(widget, b"size")
    scale_down.setDuration(duration // 2)
    scale_down.setStartValue(scaled_size)
    scale_down.setEndValue(original_size)
    scale_down.setEasingCurve(QEasingCurve.InQuad)
    
    group.addAnimation(scale_up)
    group.addAnimation(scale_down)
    
    if callback:
        group.finished.connect(callback)
    
    group.start()
    return group


# ─────────────────────────────────────────────────────────────────
# Color Transition
# ─────────────────────────────────────────────────────────────────

class ColorTransition(QObject):
    """Smooth color transition animation.
    
    Emits color_changed signal with interpolated QColor.
    """
    color_changed = pyqtSignal(QColor)
    
    def __init__(
        self,
        start_color: QColor,
        end_color: QColor,
        duration: int = 500,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        
        self.start_color = start_color
        self.end_color = end_color
        self.duration = duration
        
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.valueChanged.connect(self._on_value_changed)
    
    def _on_value_changed(self, t: float):
        """Interpolate color at time t (0.0 to 1.0)."""
        r = int(self.start_color.red() + t * (self.end_color.red() - self.start_color.red()))
        g = int(self.start_color.green() + t * (self.end_color.green() - self.start_color.green()))
        b = int(self.start_color.blue() + t * (self.end_color.blue() - self.start_color.blue()))
        a = int(self.start_color.alpha() + t * (self.end_color.alpha() - self.start_color.alpha()))
        
        self.color_changed.emit(QColor(r, g, b, a))
    
    def start(self):
        """Start the color transition."""
        self._anim.start()
    
    def set_colors(self, start: QColor, end: QColor):
        """Update transition colors."""
        self.start_color = start
        self.end_color = end


# ─────────────────────────────────────────────────────────────────
# Animation Manager
# ─────────────────────────────────────────────────────────────────

class AnimationManager:
    """Manages multiple animations on a widget.
    
    Prevents animation conflicts and provides easy state management.
    """
    
    def __init__(self, widget: QWidget):
        self.widget = widget
        self._animations: dict = {}
        self._pulse: Optional[PulseAnimation] = None
        self._glow: Optional[GlowAnimation] = None
    
    def fade_in(self, duration: int = AnimationConfig.FADE_DURATION) -> QPropertyAnimation:
        """Fade in the widget."""
        self.stop("fade")
        anim = fade_in(self.widget, duration)
        self._animations["fade"] = anim
        return anim
    
    def fade_out(self, duration: int = AnimationConfig.FADE_DURATION) -> QPropertyAnimation:
        """Fade out the widget."""
        self.stop("fade")
        anim = fade_out(self.widget, duration)
        self._animations["fade"] = anim
        return anim
    
    def start_pulse(
        self,
        min_opacity: float = 0.5,
        max_opacity: float = 1.0,
        duration: int = AnimationConfig.PULSE_DURATION,
    ) -> PulseAnimation:
        """Start pulse animation."""
        self.stop_pulse()
        self._pulse = PulseAnimation(
            self.widget, min_opacity, max_opacity, duration
        )
        self._pulse.start()
        return self._pulse
    
    def stop_pulse(self):
        """Stop pulse animation."""
        if self._pulse:
            self._pulse.stop()
            self._pulse = None
    
    def start_glow(
        self,
        color: QColor,
        min_blur: float = 10,
        max_blur: float = 30,
        duration: int = AnimationConfig.GLOW_DURATION,
    ) -> GlowAnimation:
        """Start glow animation."""
        self.stop_glow()
        self._glow = GlowAnimation(
            self.widget, color, min_blur, max_blur, duration
        )
        self._glow.start()
        return self._glow
    
    def stop_glow(self):
        """Stop glow animation."""
        if self._glow:
            self._glow.stop()
            self._glow = None
    
    def slide_to(self, pos: QPoint, duration: int = AnimationConfig.SLIDE_DURATION) -> QPropertyAnimation:
        """Slide widget to position."""
        self.stop("slide")
        anim = slide_to(self.widget, pos, duration)
        self._animations["slide"] = anim
        return anim
    
    def stop(self, name: str):
        """Stop a specific animation by name."""
        if name in self._animations:
            anim = self._animations.pop(name)
            if hasattr(anim, 'stop'):
                anim.stop()
    
    def stop_all(self):
        """Stop all running animations."""
        for anim in self._animations.values():
            if hasattr(anim, 'stop'):
                anim.stop()
        self._animations.clear()
        self.stop_pulse()
        self.stop_glow()
