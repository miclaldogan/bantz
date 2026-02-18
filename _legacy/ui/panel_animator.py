"""
Panel Animator (Issue #34 - UI-2).

Provides animations for JarvisPanel:
- Iris: Circular reveal from center
- Curtain: Horizontal split reveal
- Fade: Opacity transition
- Slide: Vertical slide from bottom
"""

from enum import Enum
from typing import Optional
from PyQt5.QtWidgets import QWidget, QGraphicsOpacityEffect
from PyQt5.QtCore import (
    QObject, QPropertyAnimation, QEasingCurve,
    QRect, QPoint, QSize, pyqtSignal, QTimer,
    QSequentialAnimationGroup, QParallelAnimationGroup
)
from PyQt5.QtGui import QPainter, QColor, QRegion, QPainterPath


class AnimationType(Enum):
    """Available animation types."""
    IRIS = "iris"           # Circular reveal from center
    CURTAIN = "curtain"     # Horizontal split reveal
    FADE = "fade"           # Opacity transition
    SLIDE = "slide"         # Vertical slide from bottom


class PanelAnimator(QObject):
    """
    Animator for JarvisPanel opening/closing effects.
    
    Supports multiple animation types with configurable duration.
    """
    
    # Signals
    animation_finished = pyqtSignal()
    animation_started = pyqtSignal()
    
    # Default durations
    DEFAULT_OPEN_DURATION = 300
    DEFAULT_CLOSE_DURATION = 200
    
    def __init__(self, panel: QWidget, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        self._panel = panel
        self._is_animating = False
        self._current_animation: Optional[QPropertyAnimation] = None
        self._opacity_effect: Optional[QGraphicsOpacityEffect] = None
        self._original_geometry: Optional[QRect] = None
        
        # Setup opacity effect for fade animations
        self._setup_opacity_effect()
    
    def _setup_opacity_effect(self):
        """Setup opacity effect for the panel."""
        self._opacity_effect = QGraphicsOpacityEffect(self._panel)
        self._opacity_effect.setOpacity(1.0)
        self._panel.setGraphicsEffect(self._opacity_effect)
    
    def animate_open(
        self,
        animation_type: AnimationType,
        duration_ms: int = DEFAULT_OPEN_DURATION
    ) -> None:
        """
        Animate panel opening.
        
        Args:
            animation_type: Type of animation to use
            duration_ms: Duration in milliseconds
        """
        if self._is_animating:
            return
        
        self._is_animating = True
        self.animation_started.emit()
        
        # Store original geometry
        self._original_geometry = self._panel.geometry()
        
        if animation_type == AnimationType.IRIS:
            self._animate_iris_open(duration_ms)
        elif animation_type == AnimationType.CURTAIN:
            self._animate_curtain_open(duration_ms)
        elif animation_type == AnimationType.FADE:
            self._animate_fade_open(duration_ms)
        elif animation_type == AnimationType.SLIDE:
            self._animate_slide_open(duration_ms)
        else:
            # Fallback to fade
            self._animate_fade_open(duration_ms)
    
    def animate_close(
        self,
        animation_type: AnimationType,
        duration_ms: int = DEFAULT_CLOSE_DURATION
    ) -> None:
        """
        Animate panel closing.
        
        Args:
            animation_type: Type of animation to use
            duration_ms: Duration in milliseconds
        """
        if self._is_animating:
            return
        
        self._is_animating = True
        self.animation_started.emit()
        
        if animation_type == AnimationType.IRIS:
            self._animate_iris_close(duration_ms)
        elif animation_type == AnimationType.CURTAIN:
            self._animate_curtain_close(duration_ms)
        elif animation_type == AnimationType.FADE:
            self._animate_fade_close(duration_ms)
        elif animation_type == AnimationType.SLIDE:
            self._animate_slide_close(duration_ms)
        else:
            self._animate_fade_close(duration_ms)
    
    def is_animating(self) -> bool:
        """Check if animation is in progress."""
        return self._is_animating
    
    def stop(self) -> None:
        """Stop current animation."""
        if self._current_animation:
            self._current_animation.stop()
        self._is_animating = False
    
    # Iris animations (circular reveal)
    def _animate_iris_open(self, duration_ms: int):
        """Iris opening animation - expand from center."""
        # Use opacity combined with size for iris effect
        # Start from center point, small size
        center = self._panel.rect().center()
        start_rect = QRect(center.x() - 10, center.y() - 10, 20, 20)
        end_rect = self._original_geometry
        
        self._opacity_effect.setOpacity(0.0)
        self._panel.setGeometry(start_rect)
        
        # Create parallel animation for geometry and opacity
        anim_group = QParallelAnimationGroup(self)
        
        # Geometry animation
        geom_anim = QPropertyAnimation(self._panel, b"geometry")
        geom_anim.setDuration(duration_ms)
        geom_anim.setStartValue(start_rect)
        geom_anim.setEndValue(end_rect)
        geom_anim.setEasingCurve(QEasingCurve.OutCubic)
        anim_group.addAnimation(geom_anim)
        
        # Opacity animation
        opacity_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        opacity_anim.setDuration(duration_ms)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        anim_group.addAnimation(opacity_anim)
        
        anim_group.finished.connect(self._on_animation_finished)
        anim_group.start()
        self._current_animation = anim_group
    
    def _animate_iris_close(self, duration_ms: int):
        """Iris closing animation - shrink to center."""
        center = self._panel.rect().center()
        global_center = self._panel.mapToGlobal(center)
        end_rect = QRect(global_center.x() - 10, global_center.y() - 10, 20, 20)
        start_rect = self._panel.geometry()
        
        anim_group = QParallelAnimationGroup(self)
        
        # Geometry animation
        geom_anim = QPropertyAnimation(self._panel, b"geometry")
        geom_anim.setDuration(duration_ms)
        geom_anim.setStartValue(start_rect)
        geom_anim.setEndValue(end_rect)
        geom_anim.setEasingCurve(QEasingCurve.InCubic)
        anim_group.addAnimation(geom_anim)
        
        # Opacity animation
        opacity_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        opacity_anim.setDuration(duration_ms)
        opacity_anim.setStartValue(1.0)
        opacity_anim.setEndValue(0.0)
        opacity_anim.setEasingCurve(QEasingCurve.InCubic)
        anim_group.addAnimation(opacity_anim)
        
        anim_group.finished.connect(self._on_animation_finished)
        anim_group.start()
        self._current_animation = anim_group
    
    # Curtain animations (horizontal split)
    def _animate_curtain_open(self, duration_ms: int):
        """Curtain opening animation - expand from center horizontally."""
        geom = self._original_geometry
        center_x = geom.x() + geom.width() // 2
        start_rect = QRect(center_x - 2, geom.y(), 4, geom.height())
        end_rect = geom
        
        self._opacity_effect.setOpacity(1.0)
        self._panel.setGeometry(start_rect)
        
        anim = QPropertyAnimation(self._panel, b"geometry")
        anim.setDuration(duration_ms)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._on_animation_finished)
        anim.start()
        self._current_animation = anim
    
    def _animate_curtain_close(self, duration_ms: int):
        """Curtain closing animation - collapse to center."""
        geom = self._panel.geometry()
        center_x = geom.x() + geom.width() // 2
        end_rect = QRect(center_x - 2, geom.y(), 4, geom.height())
        
        anim = QPropertyAnimation(self._panel, b"geometry")
        anim.setDuration(duration_ms)
        anim.setStartValue(geom)
        anim.setEndValue(end_rect)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self._on_animation_finished)
        anim.start()
        self._current_animation = anim
    
    # Fade animations
    def _animate_fade_open(self, duration_ms: int):
        """Fade in animation."""
        self._opacity_effect.setOpacity(0.0)
        
        if self._original_geometry:
            self._panel.setGeometry(self._original_geometry)
        
        anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        anim.setDuration(duration_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._on_animation_finished)
        anim.start()
        self._current_animation = anim
    
    def _animate_fade_close(self, duration_ms: int):
        """Fade out animation."""
        anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        anim.setDuration(duration_ms)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self._on_animation_finished)
        anim.start()
        self._current_animation = anim
    
    # Slide animations
    def _animate_slide_open(self, duration_ms: int):
        """Slide up animation from bottom."""
        geom = self._original_geometry
        screen_height = self._panel.screen().availableGeometry().height() if self._panel.screen() else 1080
        start_rect = QRect(geom.x(), screen_height, geom.width(), geom.height())
        end_rect = geom
        
        self._opacity_effect.setOpacity(1.0)
        self._panel.setGeometry(start_rect)
        
        anim = QPropertyAnimation(self._panel, b"geometry")
        anim.setDuration(duration_ms)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._on_animation_finished)
        anim.start()
        self._current_animation = anim
    
    def _animate_slide_close(self, duration_ms: int):
        """Slide down animation."""
        geom = self._panel.geometry()
        screen_height = self._panel.screen().availableGeometry().height() if self._panel.screen() else 1080
        end_rect = QRect(geom.x(), screen_height, geom.width(), geom.height())
        
        anim = QPropertyAnimation(self._panel, b"geometry")
        anim.setDuration(duration_ms)
        anim.setStartValue(geom)
        anim.setEndValue(end_rect)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self._on_animation_finished)
        anim.start()
        self._current_animation = anim
    
    def _on_animation_finished(self):
        """Handle animation completion."""
        self._is_animating = False
        
        # Restore opacity for closed panels
        if self._opacity_effect.opacity() < 0.1:
            self._opacity_effect.setOpacity(1.0)
        
        # Restore geometry if we have it
        if self._original_geometry and self._opacity_effect.opacity() >= 0.9:
            self._panel.setGeometry(self._original_geometry)
        
        self.animation_finished.emit()
