"""Tests for Issue #297 — TTS Barge-in + Turkish Voice Settings.

Covers:
  - TTSSettings: from_env, defaults, clamping, all env vars
  - TTSBase: ABC contract enforcement
  - PrintTTSFallback: speak/stop/is_speaking, supports_barge_in=False
  - PiperTTSAdapter: construction, speak fallback, stop/is_speaking, barge-in
  - create_tts factory: piper, print, unknown backends, edge/google fallback
  - BargeInConfig: defaults, custom values
  - BargeInEvent: creation and fields
  - BargeInController: start/stop monitoring, on_speech_detected, check_energy
  - File existence checks
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# TTSSettings
# ─────────────────────────────────────────────────────────────────


class TestTTSSettings:
    """Unified TTS settings from environment variables."""

    def test_defaults(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {}, clear=True):
            s = TTSSettings.from_env()
        assert s.backend == "piper"
        assert s.voice == ""
        assert s.rate == 1.0
        assert s.pitch == 1.0
        assert s.volume == 1.0

    def test_env_vars_loaded(self):
        from bantz.voice.tts_base import TTSSettings

        env = {
            "BANTZ_TTS_BACKEND": "edge",
            "BANTZ_TTS_VOICE": "tr-TR-EmelNeural",
            "BANTZ_TTS_RATE": "1.5",
            "BANTZ_TTS_PITCH": "0.8",
            "BANTZ_TTS_VOLUME": "0.6",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            s = TTSSettings.from_env()
        assert s.backend == "edge"
        assert s.voice == "tr-TR-EmelNeural"
        assert s.rate == 1.5
        assert s.pitch == 0.8
        assert s.volume == 0.6

    def test_backend_case_insensitive(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {"BANTZ_TTS_BACKEND": "  PIPER  "}, clear=True):
            s = TTSSettings.from_env()
        assert s.backend == "piper"

    def test_rate_clamped_low(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {"BANTZ_TTS_RATE": "0.1"}, clear=True):
            s = TTSSettings.from_env()
        assert s.rate == 0.5

    def test_rate_clamped_high(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {"BANTZ_TTS_RATE": "5.0"}, clear=True):
            s = TTSSettings.from_env()
        assert s.rate == 2.0

    def test_pitch_clamped(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {"BANTZ_TTS_PITCH": "-1"}, clear=True):
            s = TTSSettings.from_env()
        assert s.pitch == 0.5

    def test_volume_clamped_0_to_1(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {"BANTZ_TTS_VOLUME": "3"}, clear=True):
            s = TTSSettings.from_env()
        assert s.volume == 1.0

        with mock.patch.dict(os.environ, {"BANTZ_TTS_VOLUME": "-0.5"}, clear=True):
            s2 = TTSSettings.from_env()
        assert s2.volume == 0.0

    def test_voice_whitespace_stripped(self):
        from bantz.voice.tts_base import TTSSettings

        with mock.patch.dict(os.environ, {"BANTZ_TTS_VOICE": "  my-model.onnx  "}, clear=True):
            s = TTSSettings.from_env()
        assert s.voice == "my-model.onnx"


# ─────────────────────────────────────────────────────────────────
# TTSBase ABC
# ─────────────────────────────────────────────────────────────────


class TestTTSBaseABC:
    """TTSBase cannot be instantiated directly."""

    def test_abc_not_instantiable(self):
        from bantz.voice.tts_base import TTSBase

        with pytest.raises(TypeError):
            TTSBase()

    def test_concrete_subclass_works(self):
        from bantz.voice.tts_base import TTSBase

        class DummyTTS(TTSBase):
            def speak(self, text: str) -> None:
                pass

            def stop(self) -> None:
                pass

            def is_speaking(self) -> bool:
                return False

            @property
            def supports_barge_in(self) -> bool:
                return True

        tts = DummyTTS()
        assert tts.supports_barge_in is True
        assert tts.is_speaking() is False
        assert tts.backend_name == "DummyTTS"


# ─────────────────────────────────────────────────────────────────
# PrintTTSFallback
# ─────────────────────────────────────────────────────────────────


class TestPrintTTSFallback:
    """Fallback TTS that prints text to stdout."""

    def test_speak_prints(self, capsys):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        tts.speak("Merhaba efendim")
        captured = capsys.readouterr()
        assert "Merhaba efendim" in captured.out

    def test_speak_empty_string(self, capsys):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        tts.speak("")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_speak_whitespace_only(self, capsys):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        tts.speak("   ")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_is_speaking_false_after_speak(self):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        tts.speak("test")
        assert tts.is_speaking() is False

    def test_stop_sets_not_speaking(self):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        tts._speaking = True
        tts.stop()
        assert tts.is_speaking() is False

    def test_supports_barge_in_false(self):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        assert tts.supports_barge_in is False

    def test_backend_name(self):
        from bantz.voice.tts_base import PrintTTSFallback

        tts = PrintTTSFallback()
        assert tts.backend_name == "PrintTTSFallback"


# ─────────────────────────────────────────────────────────────────
# PiperTTSAdapter
# ─────────────────────────────────────────────────────────────────


class TestPiperTTSAdapter:
    """Piper TTS wrapped as TTSBase."""

    def test_construction(self):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter(model_path="/path/to/model.onnx")
        assert tts._model_path == "/path/to/model.onnx"
        assert tts.is_speaking() is False

    def test_supports_barge_in(self):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter()
        assert tts.supports_barge_in is True

    def test_speak_no_model_fallback(self, capsys):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter(model_path="")
        tts.speak("test fallback")
        captured = capsys.readouterr()
        assert "test fallback" in captured.out

    def test_speak_empty_text(self):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter(model_path="/model.onnx")
        tts.speak("")  # Should return without error
        assert tts.is_speaking() is False

    def test_stop_terminates_process(self):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter()
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None  # Process running
        tts._play_process = mock_proc
        tts._speaking = True

        tts.stop()
        mock_proc.terminate.assert_called_once()
        assert tts._speaking is False

    def test_stop_no_process(self):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter()
        tts.stop()  # Should not raise
        assert tts.is_speaking() is False

    def test_backend_name(self):
        from bantz.voice.tts_base import PiperTTSAdapter

        tts = PiperTTSAdapter()
        assert tts.backend_name == "PiperTTSAdapter"


# ─────────────────────────────────────────────────────────────────
# create_tts factory
# ─────────────────────────────────────────────────────────────────


class TestCreateTTS:
    """Factory function for TTS backends."""

    def test_default_piper(self):
        from bantz.voice.tts_base import create_tts, PiperTTSAdapter, TTSSettings

        tts = create_tts(TTSSettings(backend="piper"))
        assert isinstance(tts, PiperTTSAdapter)

    def test_print_backend(self):
        from bantz.voice.tts_base import create_tts, PrintTTSFallback, TTSSettings

        tts = create_tts(TTSSettings(backend="print"))
        assert isinstance(tts, PrintTTSFallback)

    def test_unknown_backend_falls_back_to_print(self):
        from bantz.voice.tts_base import create_tts, PrintTTSFallback, TTSSettings

        tts = create_tts(TTSSettings(backend="nonexistent"))
        assert isinstance(tts, PrintTTSFallback)

    def test_edge_fallback(self):
        from bantz.voice.tts_base import create_tts, PrintTTSFallback, TTSSettings

        tts = create_tts(TTSSettings(backend="edge"))
        assert isinstance(tts, PrintTTSFallback)

    def test_google_fallback(self):
        from bantz.voice.tts_base import create_tts, PrintTTSFallback, TTSSettings

        tts = create_tts(TTSSettings(backend="google"))
        assert isinstance(tts, PrintTTSFallback)

    def test_from_env_default(self):
        from bantz.voice.tts_base import create_tts, PiperTTSAdapter

        with mock.patch.dict(os.environ, {}, clear=True):
            tts = create_tts()
        assert isinstance(tts, PiperTTSAdapter)

    def test_from_env_print(self):
        from bantz.voice.tts_base import create_tts, PrintTTSFallback

        with mock.patch.dict(os.environ, {"BANTZ_TTS_BACKEND": "print"}, clear=True):
            tts = create_tts()
        assert isinstance(tts, PrintTTSFallback)


# ─────────────────────────────────────────────────────────────────
# BargeInConfig
# ─────────────────────────────────────────────────────────────────


class TestBargeInConfig:
    """Barge-in detection parameters."""

    def test_defaults(self):
        from bantz.voice.barge_in import BargeInConfig

        cfg = BargeInConfig()
        assert cfg.energy_threshold == 0.02
        assert cfg.min_duration_ms == 200
        assert cfg.sample_rate == 16000
        assert cfg.enabled is True

    def test_custom_values(self):
        from bantz.voice.barge_in import BargeInConfig

        cfg = BargeInConfig(energy_threshold=0.05, min_duration_ms=100, enabled=False)
        assert cfg.energy_threshold == 0.05
        assert cfg.min_duration_ms == 100
        assert cfg.enabled is False


# ─────────────────────────────────────────────────────────────────
# BargeInEvent
# ─────────────────────────────────────────────────────────────────


class TestBargeInEvent:
    """Data about a detected barge-in."""

    def test_creation(self):
        from bantz.voice.barge_in import BargeInEvent

        ev = BargeInEvent(timestamp=1234.5, energy=0.03, duration_ms=250.0)
        assert ev.timestamp == 1234.5
        assert ev.energy == 0.03
        assert ev.duration_ms == 250.0

    def test_defaults(self):
        from bantz.voice.barge_in import BargeInEvent

        ev = BargeInEvent()
        assert ev.timestamp == 0.0
        assert ev.energy == 0.0
        assert ev.duration_ms == 0.0


# ─────────────────────────────────────────────────────────────────
# BargeInController
# ─────────────────────────────────────────────────────────────────


class TestBargeInController:
    """Barge-in controller — mic monitoring during TTS playback."""

    def test_construction(self):
        from bantz.voice.barge_in import BargeInController, BargeInConfig

        ctrl = BargeInController(config=BargeInConfig())
        assert ctrl.monitoring is False
        assert ctrl.barge_in_count == 0
        assert ctrl.last_event is None

    def test_disabled_config_prevents_start(self):
        from bantz.voice.barge_in import BargeInController, BargeInConfig

        ctrl = BargeInController(config=BargeInConfig(enabled=False))
        result = ctrl.start_monitoring()
        assert result is False
        assert ctrl.monitoring is False

    def test_tts_without_barge_in_prevents_start(self):
        from bantz.voice.barge_in import BargeInController

        mock_tts = mock.MagicMock()
        mock_tts.supports_barge_in = False
        ctrl = BargeInController(tts=mock_tts)
        result = ctrl.start_monitoring()
        assert result is False

    def test_tts_with_barge_in_allows_start(self):
        from bantz.voice.barge_in import BargeInController

        mock_tts = mock.MagicMock()
        mock_tts.supports_barge_in = True
        ctrl = BargeInController(tts=mock_tts)
        # start_monitoring will spawn a thread (which may fail without sounddevice)
        result = ctrl.start_monitoring()
        assert result is True
        assert ctrl.monitoring is True
        ctrl.stop_monitoring()

    def test_stop_monitoring(self):
        from bantz.voice.barge_in import BargeInController

        ctrl = BargeInController()
        ctrl.start_monitoring()
        ctrl.stop_monitoring()
        assert ctrl.monitoring is False

    def test_double_start_returns_true(self):
        from bantz.voice.barge_in import BargeInController

        ctrl = BargeInController()
        ctrl.start_monitoring()
        result = ctrl.start_monitoring()
        assert result is True
        ctrl.stop_monitoring()

    def test_on_speech_detected_stops_tts(self):
        from bantz.voice.barge_in import BargeInController

        mock_tts = mock.MagicMock()
        ctrl = BargeInController(tts=mock_tts)
        ctrl._on_speech_detected(energy=0.05, duration_ms=300)

        mock_tts.stop.assert_called_once()
        assert ctrl.barge_in_count == 1
        assert ctrl.last_event is not None
        assert ctrl.last_event.energy == 0.05
        assert ctrl.last_event.duration_ms == 300

    def test_on_speech_detected_calls_callback(self):
        from bantz.voice.barge_in import BargeInController

        callback_events = []
        ctrl = BargeInController(on_barge_in=lambda ev: callback_events.append(ev))
        ctrl._on_speech_detected(energy=0.04, duration_ms=250)

        assert len(callback_events) == 1
        assert callback_events[0].energy == 0.04

    def test_on_speech_detected_tts_stop_failure_handled(self):
        from bantz.voice.barge_in import BargeInController

        mock_tts = mock.MagicMock()
        mock_tts.stop.side_effect = RuntimeError("TTS stop failed")
        ctrl = BargeInController(tts=mock_tts)
        # Should not raise
        ctrl._on_speech_detected(energy=0.03, duration_ms=200)
        assert ctrl.barge_in_count == 1

    def test_on_speech_detected_callback_failure_handled(self):
        from bantz.voice.barge_in import BargeInController

        def bad_callback(ev):
            raise ValueError("callback error")

        ctrl = BargeInController(on_barge_in=bad_callback)
        # Should not raise
        ctrl._on_speech_detected(energy=0.03, duration_ms=200)
        assert ctrl.barge_in_count == 1

    def test_multiple_barge_ins_counted(self):
        from bantz.voice.barge_in import BargeInController

        ctrl = BargeInController()
        ctrl._on_speech_detected(energy=0.03, duration_ms=200)
        ctrl._on_speech_detected(energy=0.04, duration_ms=250)
        ctrl._on_speech_detected(energy=0.05, duration_ms=300)
        assert ctrl.barge_in_count == 3
        assert ctrl.last_event.energy == 0.05

    def test_check_energy_above_threshold(self):
        from bantz.voice.barge_in import BargeInController, BargeInConfig

        try:
            import numpy as np
        except ImportError:
            pytest.skip("numpy not available")

        ctrl = BargeInController(config=BargeInConfig(energy_threshold=0.02))
        loud = np.ones(100, dtype=np.float32) * 0.5  # RMS=0.5
        assert ctrl.check_energy(loud) is True

    def test_check_energy_below_threshold(self):
        from bantz.voice.barge_in import BargeInController, BargeInConfig

        try:
            import numpy as np
        except ImportError:
            pytest.skip("numpy not available")

        ctrl = BargeInController(config=BargeInConfig(energy_threshold=0.5))
        quiet = np.ones(100, dtype=np.float32) * 0.01  # RMS=0.01
        assert ctrl.check_energy(quiet) is False

    def test_check_energy_handles_error(self):
        from bantz.voice.barge_in import BargeInController

        ctrl = BargeInController()
        # Pass something that isn't a numpy array
        assert ctrl.check_energy("not audio") is False

    def test_config_property(self):
        from bantz.voice.barge_in import BargeInController, BargeInConfig

        cfg = BargeInConfig(energy_threshold=0.1)
        ctrl = BargeInController(config=cfg)
        assert ctrl.config.energy_threshold == 0.1

    def test_no_tts_on_speech_detected(self):
        from bantz.voice.barge_in import BargeInController

        ctrl = BargeInController(tts=None)
        # Should not raise when tts is None
        ctrl._on_speech_detected(energy=0.03, duration_ms=200)
        assert ctrl.barge_in_count == 1


# ─────────────────────────────────────────────────────────────────
# File existence
# ─────────────────────────────────────────────────────────────────


class TestFileExistence:
    """Verify files from Issue #297 exist on disk."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_tts_base_py_exists(self):
        assert (self.ROOT / "src" / "bantz" / "voice" / "tts_base.py").is_file()

    def test_barge_in_py_exists(self):
        assert (self.ROOT / "src" / "bantz" / "voice" / "barge_in.py").is_file()
