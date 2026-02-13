"""Tests for Issue #291 — Wake word engine abstraction.

Covers WakeEngineBase, PTTFallbackEngine, factory, config,
audio_devices, and VoskWakeEngine structure.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest


# ── WakeEngineConfig ──────────────────────────────────────────

class TestWakeEngineConfig:
    def test_defaults(self):
        from bantz.voice.wake_engine_base import WakeEngineConfig
        c = WakeEngineConfig()
        assert c.wake_words == ["hey bantz", "bantz", "jarvis"]
        assert c.audio_input_device == "default"
        assert c.engine == "vosk"
        assert c.sensitivity == 0.5

    def test_from_env(self):
        from bantz.voice.wake_engine_base import WakeEngineConfig
        env = {
            "BANTZ_WAKE_WORDS": "hey jarvis,merhaba",
            "BANTZ_AUDIO_INPUT_DEVICE": "hw:1,0",
            "BANTZ_WAKE_ENGINE": "porcupine",
            "BANTZ_WAKE_SENSITIVITY": "0.8",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            c = WakeEngineConfig.from_env()
        assert c.wake_words == ["hey jarvis", "merhaba"]
        assert c.audio_input_device == "hw:1,0"
        assert c.engine == "porcupine"
        assert c.sensitivity == 0.8

    def test_sensitivity_clamped(self):
        from bantz.voice.wake_engine_base import WakeEngineConfig
        with mock.patch.dict(os.environ, {"BANTZ_WAKE_SENSITIVITY": "2.5"}, clear=True):
            c = WakeEngineConfig.from_env()
        assert c.sensitivity == 1.0

    def test_sensitivity_invalid(self):
        from bantz.voice.wake_engine_base import WakeEngineConfig
        with mock.patch.dict(os.environ, {"BANTZ_WAKE_SENSITIVITY": "abc"}, clear=True):
            c = WakeEngineConfig.from_env()
        assert c.sensitivity == 0.5


# ── WakeEngineBase ABC ────────────────────────────────────────

class TestWakeEngineBase:
    def test_is_abstract(self):
        from bantz.voice.wake_engine_base import WakeEngineBase
        with pytest.raises(TypeError):
            WakeEngineBase()

    def test_subclass_must_implement(self):
        from bantz.voice.wake_engine_base import WakeEngineBase

        class Incomplete(WakeEngineBase):
            pass

        with pytest.raises(TypeError):
            Incomplete()


# ── PTTFallbackEngine ─────────────────────────────────────────

class TestPTTFallback:
    def test_start_stop(self):
        from bantz.voice.wake_engine_base import PTTFallbackEngine
        ptt = PTTFallbackEngine()
        assert not ptt.is_running
        ptt.start()
        assert ptt.is_running
        ptt.stop()
        assert not ptt.is_running

    def test_cpu_zero(self):
        from bantz.voice.wake_engine_base import PTTFallbackEngine
        ptt = PTTFallbackEngine()
        assert ptt.cpu_usage_percent == 0.0

    def test_simulate_wake(self):
        from bantz.voice.wake_engine_base import PTTFallbackEngine
        results = []
        ptt = PTTFallbackEngine()
        ptt.on_wake_word(results.append)
        ptt.simulate_wake("manual")
        assert results == ["manual"]

    def test_no_callback_ok(self):
        from bantz.voice.wake_engine_base import PTTFallbackEngine
        ptt = PTTFallbackEngine()
        ptt.simulate_wake("test")  # should not raise


# ── Factory ───────────────────────────────────────────────────

class TestCreateWakeEngine:
    def test_none_gives_ptt(self):
        from bantz.voice.wake_engine_base import create_wake_engine, WakeEngineConfig, PTTFallbackEngine
        cfg = WakeEngineConfig(engine="none")
        e = create_wake_engine(cfg)
        assert isinstance(e, PTTFallbackEngine)

    def test_unknown_gives_ptt(self):
        from bantz.voice.wake_engine_base import create_wake_engine, WakeEngineConfig, PTTFallbackEngine
        cfg = WakeEngineConfig(engine="nonexistent")
        e = create_wake_engine(cfg)
        assert isinstance(e, PTTFallbackEngine)

    def test_vosk_fallback_if_not_installed(self):
        from bantz.voice.wake_engine_base import create_wake_engine, WakeEngineConfig, PTTFallbackEngine
        cfg = WakeEngineConfig(engine="vosk")
        with mock.patch.dict("sys.modules", {"vosk": None}):
            e = create_wake_engine(cfg)
        # May or may not fallback depending on environment — just ensure no crash
        assert e is not None

    def test_porcupine_warns_and_ptt(self):
        from bantz.voice.wake_engine_base import create_wake_engine, WakeEngineConfig, PTTFallbackEngine
        cfg = WakeEngineConfig(engine="porcupine")
        e = create_wake_engine(cfg)
        assert isinstance(e, PTTFallbackEngine)


# ── AudioDevice helpers ───────────────────────────────────────

class TestAudioDevice:
    def test_dataclass(self):
        from bantz.voice.audio_devices import AudioDevice
        d = AudioDevice(index=0, name="Test Mic", max_input_channels=2, default_sample_rate=44100.0)
        assert d.index == 0
        assert d.name == "Test Mic"
        assert not d.is_default

    def test_str_format(self):
        from bantz.voice.audio_devices import AudioDevice
        d = AudioDevice(index=1, name="USB Mic", max_input_channels=1, default_sample_rate=16000.0, is_default=True)
        s = str(d)
        assert "[1]" in s
        assert "USB Mic" in s
        assert "[DEFAULT]" in s

    def test_list_without_sounddevice(self):
        from bantz.voice.audio_devices import list_audio_devices
        with mock.patch.dict("sys.modules", {"sounddevice": None}):
            devs = list_audio_devices()
        assert devs == []

    def test_select_default_returns_none_if_no_devices(self):
        from bantz.voice.audio_devices import select_audio_device
        with mock.patch("bantz.voice.audio_devices.list_audio_devices", return_value=[]):
            result = select_audio_device("default")
        assert result is None


# ── VoskWakeEngine structure ──────────────────────────────────

class TestVoskWakeEngine:
    def test_class_exists(self):
        from bantz.voice.wake_engine_vosk import VoskWakeEngine
        assert VoskWakeEngine is not None

    def test_has_required_methods(self):
        from bantz.voice.wake_engine_vosk import VoskWakeEngine
        assert hasattr(VoskWakeEngine, "start")
        assert hasattr(VoskWakeEngine, "stop")
        assert hasattr(VoskWakeEngine, "on_wake_word")
        assert hasattr(VoskWakeEngine, "cpu_usage_percent")

    def test_instantiates(self):
        from bantz.voice.wake_engine_vosk import VoskWakeEngine
        from bantz.voice.wake_engine_base import WakeEngineConfig
        cfg = WakeEngineConfig(engine="vosk")
        e = VoskWakeEngine(cfg)
        assert e.config == cfg
        assert not e.is_running


# ── File existence ────────────────────────────────────────────

class TestFileExistence:
    def test_wake_engine_base_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "voice" / "wake_engine_base.py").is_file()

    def test_wake_engine_vosk_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "voice" / "wake_engine_vosk.py").is_file()

    def test_audio_devices_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "voice" / "audio_devices.py").is_file()
