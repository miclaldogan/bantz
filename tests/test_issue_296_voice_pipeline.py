"""Tests for Issue #296 — Voice Pipeline E2E.

Covers:
  - Tool narration system (narration.py)
  - Voice pipeline config & cloud gating (pipeline.py)
  - Pipeline result dataclass
  - Narration callback integration
  - Failure mode handling
"""

from __future__ import annotations

import os
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# Narration tests
# ─────────────────────────────────────────────────────────────────


class TestNarration:
    """Tests for bantz.voice.narration."""

    def test_known_tool_returns_phrase(self):
        from bantz.voice.narration import get_narration

        phrase = get_narration("news.briefing")
        assert phrase is not None
        assert "Haber" in phrase

    def test_instant_tool_returns_none(self):
        from bantz.voice.narration import get_narration

        assert get_narration("time.now") is None

    def test_calendar_tool_has_narration(self):
        from bantz.voice.narration import get_narration

        phrase = get_narration("calendar.list_events")
        assert phrase is not None
        assert "Takvim" in phrase

    def test_gmail_tool_has_narration(self):
        from bantz.voice.narration import get_narration

        phrase = get_narration("gmail.list_messages")
        assert phrase is not None
        assert "Mail" in phrase

    def test_system_tool_has_narration(self):
        from bantz.voice.narration import get_narration

        phrase = get_narration("system.health_check")
        assert phrase is not None
        assert "Sistem" in phrase

    def test_unknown_tool_gets_generic_fallback(self):
        from bantz.voice.narration import get_narration, NarrationConfig

        cfg = NarrationConfig(generic_fallback=True)
        phrase = get_narration("some.unknown.tool", config=cfg)
        assert phrase is not None
        assert "efendim" in phrase

    def test_unknown_tool_no_fallback_returns_none(self):
        from bantz.voice.narration import get_narration, NarrationConfig

        cfg = NarrationConfig(generic_fallback=False)
        assert get_narration("some.unknown.tool", config=cfg) is None

    def test_disabled_narration_returns_none(self):
        from bantz.voice.narration import get_narration, NarrationConfig

        cfg = NarrationConfig(enabled=False)
        assert get_narration("news.briefing", config=cfg) is None

    def test_should_narrate_predicate(self):
        from bantz.voice.narration import should_narrate

        assert should_narrate("news.briefing") is True
        assert should_narrate("time.now") is False

    def test_prefix_match_for_new_calendar_tool(self):
        from bantz.voice.narration import get_narration

        # A new calendar.* tool should match via prefix
        phrase = get_narration("calendar.some_new_feature")
        assert phrase is not None
        assert "efendim" in phrase.lower() or "Takvim" in phrase


# ─────────────────────────────────────────────────────────────────
# Pipeline config tests
# ─────────────────────────────────────────────────────────────────


class TestVoicePipelineConfig:
    """Tests for VoicePipelineConfig cloud gating."""

    def test_cloud_mode_defaults_to_local(self):
        from bantz.voice.pipeline import VoicePipelineConfig

        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = VoicePipelineConfig()
            assert cfg.resolve_cloud_mode() == "local"

    def test_cloud_mode_from_env(self):
        from bantz.voice.pipeline import VoicePipelineConfig

        with mock.patch.dict(os.environ, {"BANTZ_CLOUD_MODE": "cloud"}):
            cfg = VoicePipelineConfig()
            assert cfg.resolve_cloud_mode() == "cloud"

    def test_cloud_mode_explicit_override(self):
        from bantz.voice.pipeline import VoicePipelineConfig

        cfg = VoicePipelineConfig(cloud_mode="cloud")
        assert cfg.resolve_cloud_mode() == "cloud"

    def test_finalize_with_gemini_no_key(self):
        """Without API key, Gemini should NOT be used."""
        from bantz.voice.pipeline import VoicePipelineConfig

        env = {
            "BANTZ_CLOUD_MODE": "cloud",
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "BANTZ_GEMINI_API_KEY": "",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = VoicePipelineConfig()
            assert cfg.resolve_finalize_with_gemini() is False

    def test_finalize_with_gemini_local_mode(self):
        """With API key but local mode, Gemini should NOT be used."""
        from bantz.voice.pipeline import VoicePipelineConfig

        env = {
            "BANTZ_CLOUD_MODE": "local",
            "GEMINI_API_KEY": "test-key",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = VoicePipelineConfig()
            assert cfg.resolve_finalize_with_gemini() is False

    def test_finalize_with_gemini_all_gates_pass(self):
        """With API key + cloud mode + toggle on → Gemini used."""
        from bantz.voice.pipeline import VoicePipelineConfig

        env = {
            "BANTZ_CLOUD_MODE": "cloud",
            "GEMINI_API_KEY": "test-key",
            "BANTZ_FINALIZE_WITH_GEMINI": "true",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = VoicePipelineConfig()
            assert cfg.resolve_finalize_with_gemini() is True

    def test_finalize_with_gemini_explicit_killswitch(self):
        """Kill-switch overrides even with key + cloud mode."""
        from bantz.voice.pipeline import VoicePipelineConfig

        env = {
            "BANTZ_CLOUD_MODE": "cloud",
            "GEMINI_API_KEY": "test-key",
            "BANTZ_FINALIZE_WITH_GEMINI": "false",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = VoicePipelineConfig()
            assert cfg.resolve_finalize_with_gemini() is False

    def test_explicit_config_overrides_env(self):
        """Explicit finalize_with_gemini config takes priority."""
        from bantz.voice.pipeline import VoicePipelineConfig

        cfg = VoicePipelineConfig(finalize_with_gemini=True)
        assert cfg.resolve_finalize_with_gemini() is True

        cfg2 = VoicePipelineConfig(finalize_with_gemini=False)
        assert cfg2.resolve_finalize_with_gemini() is False


# ─────────────────────────────────────────────────────────────────
# PipelineResult tests
# ─────────────────────────────────────────────────────────────────


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_default_values(self):
        from bantz.voice.pipeline import PipelineResult

        r = PipelineResult()
        assert r.success is True
        assert r.reply == ""
        assert r.total_ms == 0.0
        assert r.timings == []

    def test_timing_summary(self):
        from bantz.voice.pipeline import PipelineResult, StepTiming

        r = PipelineResult(
            timings=[
                StepTiming("asr", 120.5, 500),
                StepTiming("brain", 340.2, 4500),
            ],
            total_ms=460.7,
        )
        summary = r.timing_summary()
        assert "asr=120ms/500" in summary
        assert "brain=340ms/4500" in summary
        assert "total=461ms" in summary


class TestStepTiming:
    """Tests for StepTiming."""

    def test_within_budget(self):
        from bantz.voice.pipeline import StepTiming

        t = StepTiming("test", 100, 200)
        assert t.within_budget is True

    def test_over_budget(self):
        from bantz.voice.pipeline import StepTiming

        t = StepTiming("test", 300, 200)
        assert t.within_budget is False

    def test_no_budget(self):
        from bantz.voice.pipeline import StepTiming

        t = StepTiming("test", 300, 0)
        assert t.within_budget is True


# ─────────────────────────────────────────────────────────────────
# Pipeline integration tests (mocked runtime)
# ─────────────────────────────────────────────────────────────────


class TestVoicePipelineMocked:
    """Tests with a mocked runtime to avoid needing live vLLM."""

    def _make_mock_runtime(self, reply="Test yanıtı efendim.", route="system"):
        """Create a mock runtime that returns predictable output."""
        mock_output = mock.MagicMock()
        mock_output.route = route
        mock_output.intent = "test_intent"
        mock_output.tool_plan = []
        mock_output.assistant_reply = reply

        mock_state = mock.MagicMock()
        mock_state.tool_results = []

        mock_runtime = mock.MagicMock()
        mock_runtime.process_turn.return_value = (mock_output, mock_state)
        mock_runtime.finalizer_is_gemini = False
        return mock_runtime

    def test_process_text_happy_path(self):
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        runtime = self._make_mock_runtime(reply="Merhaba efendim!")
        cfg = VoicePipelineConfig(debug=False)
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        result = pipe.process_text("merhaba")
        assert result.success is True
        assert result.reply == "Merhaba efendim!"
        assert result.route == "system"
        assert result.total_ms > 0

    def test_process_text_runtime_failure(self):
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        runtime = self._make_mock_runtime()
        runtime.process_turn.side_effect = RuntimeError("vLLM down")

        cfg = VoicePipelineConfig(debug=False)
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        result = pipe.process_text("test")
        assert result.success is False
        assert "sorun" in result.reply.lower() or "hata" in result.reply.lower()
        assert result.error is not None

    def test_narration_callback_called(self):
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        narrations = []
        runtime = self._make_mock_runtime()
        cfg = VoicePipelineConfig(
            enable_narration=True,
            narration_callback=lambda phrase: narrations.append(phrase),
        )
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        # Trigger narration manually (narration happens before tool exec)
        pipe._narrate(["news.briefing"])
        assert len(narrations) == 1
        assert "Haber" in narrations[0]

    def test_no_narration_for_instant_tools(self):
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        narrations = []
        runtime = self._make_mock_runtime()
        cfg = VoicePipelineConfig(
            enable_narration=True,
            narration_callback=lambda phrase: narrations.append(phrase),
        )
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        phrase = pipe._narrate(["time.now"])
        assert phrase is None
        assert len(narrations) == 0

    def test_cloud_mode_local_no_gemini(self):
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        runtime = self._make_mock_runtime()
        runtime.finalizer_is_gemini = False

        cfg = VoicePipelineConfig(cloud_mode="local")
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        result = pipe.process_text("test")
        assert result.gemini_used is False
        assert result.cloud_mode == "local"

    def test_tts_callback_called_in_process_utterance(self):
        """TTS callback should be called during full pipeline."""
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        tts_calls = []
        runtime = self._make_mock_runtime(reply="Saat on iki efendim.")
        cfg = VoicePipelineConfig(
            tts_callback=lambda text: tts_calls.append(text),
        )
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        # Mock ASR
        import numpy as np

        mock_asr = mock.MagicMock()
        mock_asr.transcribe.return_value = ("saat kaç", {"language": "tr"})

        result = pipe.process_utterance(
            np.zeros(16000, dtype=np.float32),
            asr_instance=mock_asr,
        )
        assert result.success is True
        assert result.transcription == "saat kaç"
        assert len(tts_calls) == 1
        assert "Saat" in tts_calls[0]

    def test_empty_asr_returns_friendly_error(self):
        """Empty ASR transcription → user-friendly message."""
        from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

        import numpy as np

        runtime = self._make_mock_runtime()
        cfg = VoicePipelineConfig()
        pipe = VoicePipeline(config=cfg, runtime=runtime)

        mock_asr = mock.MagicMock()
        mock_asr.transcribe.return_value = ("", {"language": "tr"})

        result = pipe.process_utterance(
            np.zeros(16000, dtype=np.float32),
            asr_instance=mock_asr,
        )
        assert result.success is False
        assert "duyamadım" in result.reply.lower() or "tekrar" in result.reply.lower()
