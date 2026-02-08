"""Unified Voice Pipeline — ASR → Router → Tool → Finalizer → TTS (Issue #296).

This module wires the complete voice-to-voice pipeline:

1. **ASR**:        Audio → text  (Whisper / Vosk)
2. **Router**:     text  → route + tool plan  (vLLM 3B)
3. **Tool exec**:  tool plan → results  (with narration before long ops)
4. **Finalizer**:  tool results → polished reply  (Gemini opt-in, 3B fallback)
5. **TTS**:        reply → speech  (Piper / Coqui)

The pipeline is driven by :func:`VoicePipeline.process_utterance`, which
accepts raw audio and returns the spoken reply.

For headless / test usage, :func:`VoicePipeline.process_text` skips ASR/TTS
and exercises Router → Tool → Finalizer only (via ``create_runtime()``).

Cloud-mode gating
-----------------
Gemini finalizer is invoked **only** when *all three* conditions hold:

1. ``GEMINI_API_KEY`` is set.
2. ``BANTZ_CLOUD_MODE`` ≠ ``local``  (default = local → Gemini disabled).
3. ``BANTZ_FINALIZE_WITH_GEMINI`` ≠ ``false``  (explicit kill-switch).

If any condition fails, the pipeline uses the 3B local finalizer.

Usage::

    from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig
    pipe = VoicePipeline()               # reads env vars
    result = pipe.process_text("haber var mı")
    print(result.reply, result.latency)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "VoicePipeline",
    "VoicePipelineConfig",
    "PipelineResult",
    "StepTiming",
]


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────


@dataclass
class StepTiming:
    """Timing for a single pipeline step."""

    name: str
    elapsed_ms: float
    budget_ms: float = 0.0

    @property
    def within_budget(self) -> bool:
        return self.budget_ms <= 0 or self.elapsed_ms <= self.budget_ms

    def __repr__(self) -> str:
        bud = f"/{self.budget_ms:.0f}" if self.budget_ms > 0 else ""
        return f"{self.name}={self.elapsed_ms:.0f}ms{bud}"


@dataclass
class PipelineResult:
    """Result of a full voice pipeline cycle."""

    # Core output
    transcription: str = ""
    route: str = ""
    intent: str = ""
    tool_plan: list[str] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    reply: str = ""
    finalizer_tier: str = ""  # "gemini" | "3b" | "default"

    # Narration phrase spoken before tool execution (if any)
    narration: Optional[str] = None

    # Timing
    timings: list[StepTiming] = field(default_factory=list)
    total_ms: float = 0.0

    # Error info
    error: Optional[str] = None
    success: bool = True

    # Cloud gating
    gemini_used: bool = False
    cloud_mode: str = "local"

    def timing_summary(self) -> str:
        """Human-readable timing summary."""
        parts = [repr(t) for t in self.timings]
        return f"total={self.total_ms:.0f}ms [{', '.join(parts)}]"


@dataclass
class VoicePipelineConfig:
    """Pipeline configuration — all defaults come from env vars.

    Attributes:
        enable_narration: Play tool narrations before long operations.
        finalize_with_gemini: Explicit toggle for Gemini finalizer.
        cloud_mode: Cloud privacy mode (``local`` | ``cloud``).
        debug: Enable verbose debug logging.
        tts_callback: Optional callback ``(text) -> None`` that speaks text.
        narration_callback: Optional callback ``(text) -> None`` for narrations.
        budget_asr_ms: ASR latency budget.
        budget_router_ms: Router latency budget.
        budget_tool_ms: Tool execution budget.
        budget_finalizer_ms: Finalizer budget.
        budget_tts_ms: TTS budget.
    """

    enable_narration: bool = True
    finalize_with_gemini: Optional[bool] = None  # None → auto (env-var)
    cloud_mode: Optional[str] = None  # None → auto (env-var)
    debug: bool = False

    # Callbacks for voice output (None = silent / headless)
    tts_callback: Optional[Callable[[str], None]] = None
    narration_callback: Optional[Callable[[str], None]] = None

    # Latency budgets (ms) — per Issue #296 spec
    budget_asr_ms: float = 500.0
    budget_router_ms: float = 500.0
    budget_tool_ms: float = 2000.0
    budget_finalizer_ms: float = 2000.0
    budget_tts_ms: float = 500.0

    def resolve_cloud_mode(self) -> str:
        """Resolve effective cloud mode from config or env."""
        if self.cloud_mode is not None:
            return self.cloud_mode
        raw = os.getenv("BANTZ_CLOUD_MODE", "local").strip().lower()
        if raw in {"1", "true", "yes", "cloud", "cloud-quality"}:
            return "cloud"
        return "local"

    def resolve_finalize_with_gemini(self) -> bool:
        """Resolve whether Gemini finalizer should be used.

        Three gates (all must pass):
          1. GEMINI_API_KEY is set
          2. cloud_mode != 'local'
          3. BANTZ_FINALIZE_WITH_GEMINI != 'false'
        """
        # Explicit config override
        if self.finalize_with_gemini is not None:
            return self.finalize_with_gemini

        # Gate 1: API key
        has_key = bool(
            os.getenv("GEMINI_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
            or os.getenv("BANTZ_GEMINI_API_KEY", "").strip()
        )
        if not has_key:
            return False

        # Gate 2: cloud mode
        if self.resolve_cloud_mode() == "local":
            return False

        # Gate 3: explicit kill-switch
        toggle = os.getenv("BANTZ_FINALIZE_WITH_GEMINI", "true").strip().lower()
        if toggle in {"0", "false", "no", "off", "disable", "disabled"}:
            return False

        return True


# ─────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────


class VoicePipeline:
    """Unified voice pipeline: ASR → Router → Tool → Finalizer → TTS.

    The pipeline uses :func:`create_runtime` to wire the brain,
    respecting the three rules:
      1. Debug trace on every step.
      2. Failure mode → user-friendly Turkish message.
      3. Always use ``create_runtime()`` — never re-wire manually.
    """

    def __init__(
        self,
        config: Optional[VoicePipelineConfig] = None,
        runtime: Any = None,
    ) -> None:
        self.config = config or VoicePipelineConfig()
        self._runtime = runtime  # lazy: created on first call if None
        self._narration_config: Any = None

    # ── Lazy runtime ────────────────────────────────────────────
    def _get_runtime(self) -> Any:
        if self._runtime is None:
            from bantz.brain.runtime_factory import create_runtime

            use_gemini = self.config.resolve_finalize_with_gemini()
            logger.info(
                "VoicePipeline: creating runtime (cloud_mode=%s, gemini=%s)",
                self.config.resolve_cloud_mode(),
                use_gemini,
            )
            # If Gemini is gated off, pass gemini_key=None to force 3B
            self._runtime = create_runtime(
                gemini_key="" if not use_gemini else None,
                debug=self.config.debug,
            )
        return self._runtime

    # ── Narration helper ────────────────────────────────────────
    def _narrate(self, tool_names: list[str]) -> Optional[str]:
        """Pick and play a narration for the first tool that has one."""
        if not self.config.enable_narration:
            return None

        from bantz.voice.narration import get_narration, NarrationConfig

        if self._narration_config is None:
            self._narration_config = NarrationConfig(
                enabled=True, debug=self.config.debug
            )

        for name in tool_names:
            phrase = get_narration(name, config=self._narration_config)
            if phrase:
                # Play narration via callback (non-blocking if possible)
                if self.config.narration_callback:
                    try:
                        self.config.narration_callback(phrase)
                    except Exception as exc:
                        logger.warning("Narration callback failed: %s", exc)
                elif self.config.tts_callback:
                    try:
                        self.config.tts_callback(phrase)
                    except Exception as exc:
                        logger.warning("TTS narration failed: %s", exc)
                return phrase
        return None

    # ── Step timer ──────────────────────────────────────────────
    @staticmethod
    def _timed(name: str, fn: Callable, budget_ms: float = 0.0) -> tuple[Any, StepTiming]:
        """Run ``fn()`` and return ``(result, StepTiming)``."""
        t0 = time.perf_counter()
        try:
            result = fn()
        except Exception:
            elapsed = (time.perf_counter() - t0) * 1000
            raise
        elapsed = (time.perf_counter() - t0) * 1000
        return result, StepTiming(name=name, elapsed_ms=elapsed, budget_ms=budget_ms)

    # ── Core: text → reply (no ASR/TTS) ────────────────────────
    def process_text(self, user_input: str) -> PipelineResult:
        """Process text through Router → Tool → Finalizer (no ASR/TTS).

        This is the main entry point for headless/test usage.
        """
        from bantz.brain.orchestrator_state import OrchestratorState

        result = PipelineResult(
            transcription=user_input,
            cloud_mode=self.config.resolve_cloud_mode(),
            gemini_used=False,
        )
        timings: list[StepTiming] = []
        t_total = time.perf_counter()

        try:
            runtime = self._get_runtime()
        except Exception as exc:
            result.error = f"Runtime oluşturulamadı: {exc}"
            result.success = False
            result.reply = "Bir sorun oluştu efendim, sistem başlatılamadı."
            logger.error("VoicePipeline runtime init failed: %s", exc)
            return result

        # ── Router + Tool + Finalizer (single turn) ────────────
        state = OrchestratorState()

        try:
            (output, new_state), timing = self._timed(
                "brain",
                lambda: runtime.process_turn(user_input, state),
                budget_ms=self.config.budget_router_ms
                + self.config.budget_tool_ms
                + self.config.budget_finalizer_ms,
            )
            timings.append(timing)
        except Exception as exc:
            result.error = f"Brain hatası: {exc}"
            result.success = False
            result.reply = "Bir sorun oluştu efendim, lütfen tekrar deneyin."
            logger.error("VoicePipeline brain error: %s", exc, exc_info=True)
            result.total_ms = (time.perf_counter() - t_total) * 1000
            result.timings = timings
            return result

        # Extract details from orchestrator output
        if hasattr(output, "route"):
            result.route = getattr(output, "route", "")
        if hasattr(output, "intent"):
            result.intent = getattr(output, "intent", "")
        if hasattr(output, "tool_plan"):
            result.tool_plan = getattr(output, "tool_plan", []) or []
        if hasattr(output, "assistant_reply"):
            result.reply = getattr(output, "assistant_reply", "") or ""

        # Check if Gemini was used
        result.gemini_used = getattr(runtime, "finalizer_is_gemini", False)
        result.finalizer_tier = "gemini" if result.gemini_used else "3b"

        # Tool results from state
        if hasattr(new_state, "tool_results"):
            result.tool_results = getattr(new_state, "tool_results", []) or []
        elif hasattr(new_state, "last_tool_results"):
            result.tool_results = getattr(new_state, "last_tool_results", []) or []

        result.total_ms = (time.perf_counter() - t_total) * 1000
        result.timings = timings
        result.success = True

        if self.config.debug:
            logger.info(
                "VoicePipeline[text] %s → route=%s, reply=%s, %s",
                user_input,
                result.route,
                result.reply[:80] if result.reply else "(empty)",
                result.timing_summary(),
            )

        return result

    # ── Full: audio → spoken reply ──────────────────────────────
    def process_utterance(
        self,
        audio_data: Any,
        *,
        sample_rate: int = 16000,
        asr_instance: Any = None,
    ) -> PipelineResult:
        """Full pipeline: Audio → ASR → Router → Tool → Finalizer → TTS.

        Parameters
        ----------
        audio_data:
            Raw audio as numpy float32 array.
        sample_rate:
            Audio sample rate.
        asr_instance:
            Pre-initialized ASR instance (created lazily if None).
        """
        result = PipelineResult(
            cloud_mode=self.config.resolve_cloud_mode(),
        )
        timings: list[StepTiming] = []
        t_total = time.perf_counter()

        # ── Step 1: ASR ─────────────────────────────────────────
        try:
            asr = asr_instance
            if asr is None:
                from bantz.voice.asr import ASR, ASRConfig

                asr = ASR(ASRConfig(language="tr", sample_rate=sample_rate))

            (text, meta), asr_timing = self._timed(
                "asr",
                lambda: asr.transcribe(audio_data),
                budget_ms=self.config.budget_asr_ms,
            )
            timings.append(asr_timing)
            result.transcription = text or ""

            if not result.transcription.strip():
                result.reply = "Sizi duyamadım efendim, tekrar söyler misiniz?"
                result.success = False
                result.error = "ASR: boş transkripsiyon"
                result.total_ms = (time.perf_counter() - t_total) * 1000
                result.timings = timings
                return result

        except Exception as exc:
            result.error = f"ASR hatası: {exc}"
            result.success = False
            result.reply = "Ses tanıma hatası efendim, tekrar deneyin."
            logger.error("VoicePipeline ASR failed: %s", exc)
            result.total_ms = (time.perf_counter() - t_total) * 1000
            result.timings = timings
            return result

        # ── Steps 2-4: Router → Tool → Finalizer ───────────────
        text_result = self.process_text(result.transcription)

        # Merge text_result into our result
        result.route = text_result.route
        result.intent = text_result.intent
        result.tool_plan = text_result.tool_plan
        result.tool_results = text_result.tool_results
        result.reply = text_result.reply
        result.finalizer_tier = text_result.finalizer_tier
        result.gemini_used = text_result.gemini_used
        result.narration = text_result.narration
        result.error = text_result.error
        result.success = text_result.success
        timings.extend(text_result.timings)

        # ── Step 5: TTS ─────────────────────────────────────────
        if result.reply and self.config.tts_callback:
            try:
                _, tts_timing = self._timed(
                    "tts",
                    lambda: self.config.tts_callback(result.reply),
                    budget_ms=self.config.budget_tts_ms,
                )
                timings.append(tts_timing)
            except Exception as exc:
                logger.warning("VoicePipeline TTS failed: %s", exc)
                # Don't mark as failure — reply text is still available

        result.total_ms = (time.perf_counter() - t_total) * 1000
        result.timings = timings

        if self.config.debug:
            logger.info(
                "VoicePipeline[full] ASR='%s' → route=%s, reply=%s, %s",
                result.transcription,
                result.route,
                result.reply[:80] if result.reply else "(empty)",
                result.timing_summary(),
            )

        return result


# ─────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────


def create_voice_pipeline(
    *,
    debug: bool = False,
    enable_narration: bool = True,
    tts_callback: Optional[Callable[[str], None]] = None,
    narration_callback: Optional[Callable[[str], None]] = None,
) -> VoicePipeline:
    """Factory for VoicePipeline with sensible defaults."""
    cfg = VoicePipelineConfig(
        debug=debug,
        enable_narration=enable_narration,
        tts_callback=tts_callback,
        narration_callback=narration_callback,
    )
    return VoicePipeline(config=cfg)
