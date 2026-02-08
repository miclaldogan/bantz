"""Tests for Issue #298 — Controls: PTT hotkey + mic mute + status indicator.

Covers:
  - HotkeyConfig: defaults, from_env, custom values
  - HotkeyManager: register, unregister, simulate_combo, start/stop
  - PTTController: press/release, min_hold_ms, cancel, reset, stats
  - PTTState: enum values
  - MuteController: toggle, mute/unmute, callbacks, reset
  - StatusIndicator: update, terminal/callback/silent, status_line
  - VoiceStatus: enum, labels, icons
  - File existence
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# HotkeyConfig
# ─────────────────────────────────────────────────────────────────


class TestHotkeyConfig:
    """Hotkey configuration from env vars."""

    def test_defaults(self):
        from bantz.controls.hotkeys import HotkeyConfig

        cfg = HotkeyConfig()
        assert cfg.ptt_key == "ctrl+space"
        assert cfg.mute_key == "ctrl+shift+m"
        assert cfg.status_key == "ctrl+shift+s"
        assert cfg.enabled is True

    def test_from_env(self):
        from bantz.controls.hotkeys import HotkeyConfig

        env = {
            "BANTZ_PTT_KEY": "alt+space",
            "BANTZ_MUTE_KEY": "f9",
            "BANTZ_STATUS_KEY": "f10",
            "BANTZ_HOTKEYS_ENABLED": "false",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = HotkeyConfig.from_env()
        assert cfg.ptt_key == "alt+space"
        assert cfg.mute_key == "f9"
        assert cfg.status_key == "f10"
        assert cfg.enabled is False

    def test_enabled_truthy(self):
        from bantz.controls.hotkeys import HotkeyConfig

        with mock.patch.dict(os.environ, {"BANTZ_HOTKEYS_ENABLED": "1"}, clear=True):
            cfg = HotkeyConfig.from_env()
        assert cfg.enabled is True


# ─────────────────────────────────────────────────────────────────
# HotkeyManager
# ─────────────────────────────────────────────────────────────────


class TestHotkeyManager:
    """Hotkey manager — register, simulate, start/stop."""

    def test_register_and_simulate(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        mgr = HotkeyManager(config=HotkeyConfig(enabled=False))
        results = []
        mgr.register("ctrl+space", lambda: results.append("ptt"))
        assert mgr.simulate_combo("ctrl+space") is True
        assert results == ["ptt"]

    def test_simulate_unregistered(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        mgr = HotkeyManager(config=HotkeyConfig(enabled=False))
        assert mgr.simulate_combo("ctrl+x") is False

    def test_unregister(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        mgr = HotkeyManager(config=HotkeyConfig(enabled=False))
        mgr.register("ctrl+space", lambda: None)
        mgr.unregister("ctrl+space")
        assert mgr.simulate_combo("ctrl+space") is False

    def test_start_disabled(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        mgr = HotkeyManager(config=HotkeyConfig(enabled=False))
        assert mgr.start() is False
        assert mgr.running is False

    def test_stop_idempotent(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        mgr = HotkeyManager(config=HotkeyConfig(enabled=False))
        mgr.stop()  # Should not raise
        assert mgr.running is False

    def test_config_property(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        cfg = HotkeyConfig(ptt_key="f5")
        mgr = HotkeyManager(config=cfg)
        assert mgr.config.ptt_key == "f5"

    def test_normalize_key_combo(self):
        from bantz.controls.hotkeys import HotkeyManager, HotkeyConfig

        mgr = HotkeyManager(config=HotkeyConfig(enabled=False))
        results = []
        mgr.register("CTRL+SPACE", lambda: results.append("hit"))
        assert mgr.simulate_combo("ctrl+space") is True


# ─────────────────────────────────────────────────────────────────
# PTTState
# ─────────────────────────────────────────────────────────────────


class TestPTTState:
    """PTT state enum."""

    def test_values(self):
        from bantz.controls.ptt import PTTState

        assert PTTState.IDLE.value == "idle"
        assert PTTState.HELD.value == "held"
        assert PTTState.PROCESSING.value == "processing"


# ─────────────────────────────────────────────────────────────────
# PTTController
# ─────────────────────────────────────────────────────────────────


class TestPTTController:
    """Push-to-talk controller."""

    def test_initial_state_idle(self):
        from bantz.controls.ptt import PTTController, PTTState

        ptt = PTTController()
        assert ptt.state == PTTState.IDLE
        assert ptt.is_held is False
        assert ptt.press_count == 0

    def test_press_enters_held(self):
        from bantz.controls.ptt import PTTController, PTTState

        ptt = PTTController()
        assert ptt.press() is True
        assert ptt.state == PTTState.HELD
        assert ptt.is_held is True

    def test_double_press_ignored(self):
        from bantz.controls.ptt import PTTController

        ptt = PTTController()
        ptt.press()
        assert ptt.press() is False

    def test_release_after_hold(self):
        from bantz.controls.ptt import PTTController, PTTState

        ptt = PTTController(min_hold_ms=0)
        ptt.press()
        time.sleep(0.01)
        assert ptt.release() is True
        assert ptt.state == PTTState.IDLE
        assert ptt.press_count == 1

    def test_release_too_short(self):
        from bantz.controls.ptt import PTTController

        ptt = PTTController(min_hold_ms=5000)  # 5 seconds
        ptt.press()
        assert ptt.release() is False  # Way too short
        assert ptt.press_count == 0

    def test_release_without_press(self):
        from bantz.controls.ptt import PTTController

        ptt = PTTController()
        assert ptt.release() is False

    def test_callbacks_called(self):
        from bantz.controls.ptt import PTTController

        events = []
        ptt = PTTController(
            on_start=lambda: events.append("start"),
            on_stop=lambda: events.append("stop"),
            min_hold_ms=0,
        )
        ptt.press()
        time.sleep(0.01)
        ptt.release()
        assert events == ["start", "stop"]

    def test_callback_error_handled(self):
        from bantz.controls.ptt import PTTController

        def bad_start():
            raise RuntimeError("broken")

        ptt = PTTController(on_start=bad_start)
        ptt.press()  # Should not raise
        assert ptt.is_held is True

    def test_cancel(self):
        from bantz.controls.ptt import PTTController, PTTState

        ptt = PTTController()
        ptt.press()
        ptt.cancel()
        assert ptt.state == PTTState.IDLE
        assert ptt.press_count == 0

    def test_reset(self):
        from bantz.controls.ptt import PTTController

        ptt = PTTController(min_hold_ms=0)
        ptt.press()
        time.sleep(0.01)
        ptt.release()
        assert ptt.press_count == 1
        ptt.reset()
        assert ptt.press_count == 0
        assert ptt.total_hold_ms == 0.0

    def test_total_hold_ms(self):
        from bantz.controls.ptt import PTTController

        ptt = PTTController(min_hold_ms=0)
        ptt.press()
        time.sleep(0.05)
        ptt.release()
        assert ptt.total_hold_ms >= 40  # ~50ms


# ─────────────────────────────────────────────────────────────────
# MuteController
# ─────────────────────────────────────────────────────────────────


class TestMuteController:
    """Mic mute/unmute toggle."""

    def test_default_unmuted(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController()
        assert ctrl.muted is False
        assert ctrl.toggle_count == 0

    def test_toggle_mutes(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController()
        result = ctrl.toggle()
        assert result is True  # Now muted
        assert ctrl.muted is True
        assert ctrl.toggle_count == 1

    def test_double_toggle_unmutes(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController()
        ctrl.toggle()  # Mute
        ctrl.toggle()  # Unmute
        assert ctrl.muted is False
        assert ctrl.toggle_count == 2

    def test_mute_method(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController()
        ctrl.mute()
        assert ctrl.muted is True
        ctrl.mute()  # Already muted — no-op
        assert ctrl.toggle_count == 1

    def test_unmute_method(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController(initially_muted=True)
        ctrl.unmute()
        assert ctrl.muted is False
        ctrl.unmute()  # Already unmuted — no-op
        assert ctrl.toggle_count == 1

    def test_callbacks(self):
        from bantz.controls.mute import MuteController

        events = []
        ctrl = MuteController(
            on_mute=lambda: events.append("muted"),
            on_unmute=lambda: events.append("unmuted"),
        )
        ctrl.toggle()  # Mute
        ctrl.toggle()  # Unmute
        assert events == ["muted", "unmuted"]

    def test_callback_error_handled(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController(on_mute=lambda: 1 / 0)
        ctrl.toggle()  # Should not raise
        assert ctrl.muted is True

    def test_initially_muted(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController(initially_muted=True)
        assert ctrl.muted is True

    def test_reset(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController()
        ctrl.toggle()
        ctrl.toggle()
        ctrl.reset()
        assert ctrl.muted is False
        assert ctrl.toggle_count == 0
        assert ctrl.last_toggle_time is None

    def test_last_toggle_time(self):
        from bantz.controls.mute import MuteController

        ctrl = MuteController()
        assert ctrl.last_toggle_time is None
        ctrl.toggle()
        assert ctrl.last_toggle_time is not None


# ─────────────────────────────────────────────────────────────────
# VoiceStatus
# ─────────────────────────────────────────────────────────────────


class TestVoiceStatus:
    """Voice status enum."""

    def test_values(self):
        from bantz.controls.indicator import VoiceStatus

        assert VoiceStatus.WAKE_ONLY.value == "wake_only"
        assert VoiceStatus.LISTENING.value == "listening"
        assert VoiceStatus.MUTED.value == "muted"

    def test_turkish_labels(self):
        from bantz.controls.indicator import VoiceStatus

        assert VoiceStatus.LISTENING.label_tr == "DİNLİYOR"
        assert VoiceStatus.WAKE_ONLY.label_tr == "BEKLEMEDE"
        assert VoiceStatus.MUTED.label_tr == "SESSİZ"

    def test_icons(self):
        from bantz.controls.indicator import VoiceStatus

        assert VoiceStatus.LISTENING.icon == "🎤"
        assert VoiceStatus.MUTED.icon == "🔇"
        assert VoiceStatus.SPEAKING.icon == "🔊"


# ─────────────────────────────────────────────────────────────────
# StatusIndicator
# ─────────────────────────────────────────────────────────────────


class TestStatusIndicator:
    """Status display indicator."""

    def test_default_idle_sleep(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="silent")
        assert ind.status == VoiceStatus.IDLE_SLEEP

    def test_update_changes_status(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="silent")
        ind.update(VoiceStatus.LISTENING)
        assert ind.status == VoiceStatus.LISTENING
        assert ind.update_count == 1

    def test_same_status_no_op(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="silent")
        ind.update(VoiceStatus.LISTENING)
        ind.update(VoiceStatus.LISTENING)
        assert ind.update_count == 1

    def test_callback_mode(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        received = []
        ind = StatusIndicator(mode="callback", callback=lambda s: received.append(s))
        ind.update(VoiceStatus.LISTENING)
        ind.update(VoiceStatus.SPEAKING)
        assert received == [VoiceStatus.LISTENING, VoiceStatus.SPEAKING]

    def test_callback_error_handled(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="callback", callback=lambda s: 1 / 0)
        ind.update(VoiceStatus.LISTENING)  # Should not raise
        assert ind.status == VoiceStatus.LISTENING

    def test_status_duration(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="silent")
        ind.update(VoiceStatus.LISTENING)
        time.sleep(0.05)
        assert ind.status_duration >= 0.04

    def test_get_status_line(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="silent")
        ind.update(VoiceStatus.LISTENING)
        line = ind.get_status_line()
        assert "🎤" in line
        assert "DİNLİYOR" in line

    def test_reset(self):
        from bantz.controls.indicator import StatusIndicator, VoiceStatus

        ind = StatusIndicator(mode="silent")
        ind.update(VoiceStatus.LISTENING)
        ind.update(VoiceStatus.SPEAKING)
        ind.reset()
        assert ind.status == VoiceStatus.IDLE_SLEEP
        assert ind.update_count == 0


# ─────────────────────────────────────────────────────────────────
# File existence
# ─────────────────────────────────────────────────────────────────


class TestFileExistence:
    """Verify all Issue #298 files exist."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_init_exists(self):
        assert (self.ROOT / "src" / "bantz" / "controls" / "__init__.py").is_file()

    def test_hotkeys_exists(self):
        assert (self.ROOT / "src" / "bantz" / "controls" / "hotkeys.py").is_file()

    def test_ptt_exists(self):
        assert (self.ROOT / "src" / "bantz" / "controls" / "ptt.py").is_file()

    def test_mute_exists(self):
        assert (self.ROOT / "src" / "bantz" / "controls" / "mute.py").is_file()

    def test_indicator_exists(self):
        assert (self.ROOT / "src" / "bantz" / "controls" / "indicator.py").is_file()
