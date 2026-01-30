"""Real-time audio waveform visualization widget (Issue #5).

Displays animated waveform bars synchronized with audio input.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional, List
import random

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QLinearGradient, QPen

from ..themes import OverlayTheme, JARVIS_THEME


class WaveformWidget(QWidget):
    """Real-time audio waveform visualization.
    
    Displays vertical bars that respond to audio levels.
    Can operate in:
    - Real mode: Fed with actual audio data
    - Demo mode: Animated placeholder bars
    
    Signals:
        level_changed: Emitted when audio level changes (0.0-1.0)
    """
    
    level_changed = pyqtSignal(float)
    
    def __init__(
        self,
        num_bars: int = 20,
        bar_width: int = 4,
        bar_gap: int = 2,
        min_height: int = 2,
        max_height: int = 40,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.num_bars = num_bars
        self.bar_width = bar_width
        self.bar_gap = bar_gap
        self.min_height = min_height
        self.max_height = max_height
        self.theme = theme or JARVIS_THEME
        
        # Bar heights (0.0 to 1.0)
        self._bar_levels: List[float] = [0.0] * num_bars
        self._target_levels: List[float] = [0.0] * num_bars
        
        # Audio samples buffer
        self._samples: deque = deque(maxlen=1000)
        
        # Mode
        self._demo_mode = True
        self._active = False
        
        # Smoothing factor (higher = smoother)
        self._smoothing = 0.3
        
        # Calculate widget size
        total_width = num_bars * bar_width + (num_bars - 1) * bar_gap
        self.setFixedSize(total_width, max_height)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._update_bars)
        self._anim_timer.setInterval(30)  # ~33fps
        
        # Demo timer for idle animation
        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._update_demo)
        self._demo_timer.setInterval(100)
        
        self._demo_phase = 0.0
    
    # ─────────────────────────────────────────────────────────────────
    # Audio Input
    # ─────────────────────────────────────────────────────────────────
    
    def update_audio(self, audio_chunk: bytes):
        """Update with new audio data.
        
        Args:
            audio_chunk: Raw audio bytes (16-bit PCM assumed)
        """
        if len(audio_chunk) < 2:
            return
        
        self._demo_mode = False
        
        # Convert bytes to samples (assuming 16-bit PCM)
        samples = []
        for i in range(0, len(audio_chunk) - 1, 2):
            sample = int.from_bytes(audio_chunk[i:i+2], 'little', signed=True)
            samples.append(abs(sample) / 32768.0)  # Normalize to 0.0-1.0
        
        self._samples.extend(samples)
        
        # Calculate levels for each bar
        self._calculate_levels(samples)
    
    def update_audio_float(self, samples: List[float]):
        """Update with float audio samples (0.0-1.0 range).
        
        Args:
            samples: List of audio sample values
        """
        if not samples:
            return
        
        self._demo_mode = False
        self._samples.extend(samples)
        self._calculate_levels(samples)
    
    def _calculate_levels(self, samples: List[float]):
        """Calculate bar levels from audio samples."""
        if not samples:
            return
        
        # Divide samples into bar_count groups
        chunk_size = max(1, len(samples) // self.num_bars)
        
        for i in range(self.num_bars):
            start = i * chunk_size
            end = min(start + chunk_size, len(samples))
            
            if start < len(samples):
                chunk = samples[start:end]
                # RMS level
                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) if chunk else 0
                # Apply some gain and clamp
                level = min(1.0, rms * 3.0)
                self._target_levels[i] = level
        
        # Emit average level
        avg_level = sum(self._target_levels) / self.num_bars
        self.level_changed.emit(avg_level)
    
    def set_level(self, level: float):
        """Set uniform level for all bars.
        
        Args:
            level: Audio level (0.0-1.0)
        """
        self._demo_mode = False
        self._target_levels = [level] * self.num_bars
        self.level_changed.emit(level)
    
    # ─────────────────────────────────────────────────────────────────
    # Animation
    # ─────────────────────────────────────────────────────────────────
    
    def start(self):
        """Start the waveform animation."""
        self._active = True
        self._anim_timer.start()
        if self._demo_mode:
            self._demo_timer.start()
    
    def stop(self):
        """Stop the waveform animation."""
        self._active = False
        self._anim_timer.stop()
        self._demo_timer.stop()
        self._target_levels = [0.0] * self.num_bars
    
    def set_demo_mode(self, enabled: bool):
        """Enable/disable demo mode."""
        self._demo_mode = enabled
        if enabled and self._active:
            self._demo_timer.start()
        else:
            self._demo_timer.stop()
    
    def _update_bars(self):
        """Smooth bar level updates."""
        changed = False
        
        for i in range(self.num_bars):
            current = self._bar_levels[i]
            target = self._target_levels[i]
            
            if abs(current - target) > 0.01:
                # Smooth interpolation
                self._bar_levels[i] = current + (target - current) * self._smoothing
                changed = True
            else:
                self._bar_levels[i] = target
        
        if changed:
            self.update()
    
    def _update_demo(self):
        """Update demo animation."""
        if not self._demo_mode:
            return
        
        self._demo_phase += 0.2
        
        # Create wave-like pattern
        for i in range(self.num_bars):
            # Base wave
            wave = math.sin(self._demo_phase + i * 0.3) * 0.3 + 0.3
            # Add some randomness
            noise = random.uniform(-0.1, 0.1)
            self._target_levels[i] = max(0.05, min(0.6, wave + noise))
    
    # ─────────────────────────────────────────────────────────────────
    # Painting
    # ─────────────────────────────────────────────────────────────────
    
    def paintEvent(self, event):
        """Draw the waveform bars."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center_y = self.height() / 2
        
        for i in range(self.num_bars):
            level = self._bar_levels[i]
            
            # Bar dimensions
            bar_height = self.min_height + level * (self.max_height - self.min_height)
            x = i * (self.bar_width + self.bar_gap)
            y = center_y - bar_height / 2
            
            # Gradient based on level
            gradient = QLinearGradient(x, y, x, y + bar_height)
            
            primary = QColor(self.theme.primary)
            secondary = QColor(self.theme.secondary)
            
            # Higher level = brighter
            alpha = int(100 + 155 * level)
            primary.setAlpha(alpha)
            secondary.setAlpha(int(alpha * 0.7))
            
            gradient.setColorAt(0.0, primary)
            gradient.setColorAt(0.5, secondary)
            gradient.setColorAt(1.0, primary)
            
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            
            # Draw rounded bar
            rect = QRectF(x, y, self.bar_width, bar_height)
            painter.drawRoundedRect(rect, self.bar_width / 2, self.bar_width / 2)
    
    # ─────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────
    
    def showEvent(self, event):
        """Start animation when shown."""
        self.start()
        super().showEvent(event)
    
    def hideEvent(self, event):
        """Stop animation when hidden."""
        self.stop()
        super().hideEvent(event)
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme colors."""
        self.theme = theme
        self.update()


class CompactWaveform(WaveformWidget):
    """Smaller waveform for inline display."""
    
    def __init__(
        self,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(
            num_bars=12,
            bar_width=3,
            bar_gap=1,
            min_height=2,
            max_height=20,
            theme=theme,
            parent=parent,
        )
