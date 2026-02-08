"""Tests for Issue #443 — UnifiedBrain Facade enhancements.

Covers:
- Auto-mode detection (jarvis patterns → jarvis, fallback → orchestrator)
- Deprecation warnings via deprecated_direct_backend()
- Diagnostics tracking (turn count, latency, backend usage, errors)
- create_brain() factory with mode="auto"
- Edge cases: empty input, error handling, missing backends
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.unified_loop import (
    UnifiedBrain,
    UnifiedConfig,
    UnifiedResult,
    create_brain,
    deprecated_direct_backend,
)


# ---------------------------------------------------------------------------
# Helpers / mocks
# ---------------------------------------------------------------------------

@dataclass
class _FakeBrainResult:
    kind: str = "say"
    text: str = "brain says hi"
    steps_used: int = 1
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {"route": "calendar.list", "trace": {}}


@dataclass
class _FakeOrchestratorOutput:
    assistant_reply: str = "orch says hi"
    ask_user: bool = False
    question: Optional[str] = None
    route: str = "general"
    calendar_intent: str = ""
    confidence: float = 0.85
    tool_plan: list = None
    requires_confirmation: bool = False
    confirmation_prompt: str = ""
    reasoning_summary: list = None
    memory_update: str = ""
    raw_output: dict = None

    def __post_init__(self):
        if self.tool_plan is None:
            self.tool_plan = []
        if self.reasoning_summary is None:
            self.reasoning_summary = []
        if self.raw_output is None:
            self.raw_output = {}


class _FakeOrchestratorState:
    session_context: dict = None
    trace: dict = None

    def __init__(self):
        self.session_context = {}
        self.trace = {}


def _make_brain_loop() -> MagicMock:
    mock = MagicMock()
    mock.run.return_value = _FakeBrainResult()
    return mock


def _make_orchestrator_loop() -> MagicMock:
    mock = MagicMock()
    mock.process_turn.return_value = (
        _FakeOrchestratorOutput(),
        _FakeOrchestratorState(),
    )
    return mock


def _make_brain(
    mode: str = "orchestrator",
    brain_loop: Any = None,
    orchestrator_loop: Any = None,
    config: Optional[UnifiedConfig] = None,
) -> UnifiedBrain:
    """Shortcut to create a UnifiedBrain with mock backends."""
    if mode in ("orchestrator", "auto") and orchestrator_loop is None:
        orchestrator_loop = _make_orchestrator_loop()
    if mode in ("jarvis", "auto") and brain_loop is None:
        brain_loop = _make_brain_loop()
    cfg = config or UnifiedConfig(mode=mode)
    return UnifiedBrain(
        mode=mode,
        brain_loop=brain_loop,
        orchestrator_loop=orchestrator_loop,
        config=cfg,
    )


# ===================================================================
# 1. Basic construction
# ===================================================================

class TestConstruction:
    def test_jarvis_mode(self):
        brain = _make_brain("jarvis")
        assert brain.mode == "jarvis"

    def test_orchestrator_mode(self):
        brain = _make_brain("orchestrator")
        assert brain.mode == "orchestrator"

    def test_auto_mode(self):
        brain = _make_brain("auto")
        assert brain.mode == "auto"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="auto"):
            UnifiedBrain(
                mode="invalid_mode",
                config=UnifiedConfig(mode="invalid_mode"),
            )


# ===================================================================
# 2. Auto-mode detection
# ===================================================================

class TestAutoMode:
    def test_calendar_keyword_routes_to_jarvis(self):
        brain = _make_brain("auto")
        result = brain.process("takvimde yarın ne var?")
        assert result.backend == "brain_loop"

    def test_toplantı_keyword_routes_to_jarvis(self):
        brain = _make_brain("auto")
        result = brain.process("toplantı ayarla saat 3'e")
        assert result.backend == "brain_loop"

    def test_etkinlik_keyword_routes_to_jarvis(self):
        brain = _make_brain("auto")
        result = brain.process("etkinlik oluştur bugüne")
        assert result.backend == "brain_loop"

    def test_randevu_keyword_routes_to_jarvis(self):
        brain = _make_brain("auto")
        result = brain.process("randevumu iptal et")
        assert result.backend == "brain_loop"

    def test_general_input_routes_to_orchestrator(self):
        brain = _make_brain("auto")
        result = brain.process("bugün hava nasıl?")
        assert result.backend == "orchestrator"

    def test_auto_fallback_when_no_brain_loop(self):
        """Auto mode with only orchestrator available falls back."""
        brain = UnifiedBrain(
            mode="auto",
            brain_loop=None,
            orchestrator_loop=_make_orchestrator_loop(),
            config=UnifiedConfig(mode="auto"),
        )
        result = brain.process("takvimde ne var?")
        assert result.backend == "orchestrator"

    def test_auto_fallback_when_no_orchestrator(self):
        """Auto mode with only brain loop uses jarvis even for non-matching."""
        brain = UnifiedBrain(
            mode="auto",
            brain_loop=_make_brain_loop(),
            orchestrator_loop=None,
            config=UnifiedConfig(mode="auto"),
        )
        result = brain.process("bugün hava nasıl?")
        assert result.backend == "brain_loop"

    def test_non_auto_mode_ignores_patterns(self):
        """In orchestrator mode, calendar keywords still go to orchestrator."""
        brain = _make_brain("orchestrator")
        result = brain.process("takvimde yarın ne var?")
        assert result.backend == "orchestrator"


# ===================================================================
# 3. Deprecation warnings
# ===================================================================

class TestDeprecationWarnings:
    def test_deprecated_direct_backend_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            deprecated_direct_backend("BrainLoop")
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "BrainLoop" in str(w[0].message)
            assert "create_brain" in str(w[0].message)

    def test_deprecation_message_mentions_factory(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            deprecated_direct_backend("OrchestratorLoop")
            assert "create_brain" in str(w[0].message)


# ===================================================================
# 4. Diagnostics
# ===================================================================

class TestDiagnostics:
    def test_initial_diagnostics(self):
        brain = _make_brain("orchestrator")
        diag = brain.get_diagnostics()
        assert diag["turn_count"] == 0
        assert diag["avg_latency_ms"] == 0.0
        assert diag["error_count"] == 0
        assert diag["backend_usage"]["brain_loop"] == 0
        assert diag["backend_usage"]["orchestrator"] == 0
        assert diag["has_orchestrator_loop"] is True

    def test_turn_count_increments(self):
        brain = _make_brain("orchestrator")
        brain.process("hello")
        brain.process("world")
        diag = brain.get_diagnostics()
        assert diag["turn_count"] == 2

    def test_latency_tracking(self):
        brain = _make_brain("orchestrator")
        brain.process("hello")
        diag = brain.get_diagnostics()
        # Mocks return near-instantly, so latency may be 0.0
        assert diag["total_latency_ms"] >= 0.0
        assert diag["avg_latency_ms"] >= 0.0
        assert diag["turn_count"] == 1

    def test_backend_usage_tracking(self):
        brain = _make_brain("auto")
        brain.process("takvimde ne var?")  # → jarvis
        brain.process("hava nasıl?")       # → orchestrator
        diag = brain.get_diagnostics()
        assert diag["backend_usage"]["brain_loop"] == 1
        assert diag["backend_usage"]["orchestrator"] == 1

    def test_error_count_tracking(self):
        orch = _make_orchestrator_loop()
        orch.process_turn.side_effect = RuntimeError("boom")
        brain = _make_brain("orchestrator", orchestrator_loop=orch)
        result = brain.process("hello")
        assert result.kind == "fail"
        diag = brain.get_diagnostics()
        assert diag["error_count"] == 1

    def test_diagnostics_has_backend_flags(self):
        brain = _make_brain("auto")
        diag = brain.get_diagnostics()
        assert diag["has_brain_loop"] is True
        assert diag["has_orchestrator_loop"] is True
        assert diag["mode"] == "auto"


# ===================================================================
# 5. UnifiedResult
# ===================================================================

class TestUnifiedResult:
    def test_defaults(self):
        r = UnifiedResult(kind="say", text="hello")
        assert r.backend == ""
        assert r.confidence == 0.0
        assert r.tools_executed == []
        assert r.metadata == {}

    def test_is_error_property(self):
        r = UnifiedResult(kind="fail", text="oops")
        assert r.is_error is True
        r2 = UnifiedResult(kind="say", text="ok")
        assert r2.is_error is False


# ===================================================================
# 6. UnifiedConfig
# ===================================================================

class TestUnifiedConfig:
    def test_default_mode(self):
        cfg = UnifiedConfig()
        assert cfg.mode == "orchestrator"

    def test_auto_jarvis_patterns_default(self):
        cfg = UnifiedConfig(mode="auto")
        # Default is None; resolved to built-in list inside UnifiedBrain.__init__
        assert cfg.auto_jarvis_patterns is None

    def test_custom_patterns(self):
        patterns = ["test", "deneme"]
        cfg = UnifiedConfig(mode="auto", auto_jarvis_patterns=patterns)
        assert cfg.auto_jarvis_patterns == patterns


# ===================================================================
# 7. Empty / edge cases
# ===================================================================

class TestEdgeCases:
    def test_empty_input(self):
        brain = _make_brain("orchestrator")
        result = brain.process("")
        assert result.kind == "fail"
        assert "empty" in result.text.lower()

    def test_whitespace_input(self):
        brain = _make_brain("orchestrator")
        result = brain.process("   ")
        assert result.kind == "fail"

    def test_none_input(self):
        brain = _make_brain("orchestrator")
        result = brain.process(None)
        assert result.kind == "fail"

    def test_reset_clears_state(self):
        brain = _make_brain("orchestrator")
        brain.process("hello")
        brain.reset()
        assert brain.orchestrator_state is None


# ===================================================================
# 8. create_brain() factory
# ===================================================================

class TestCreateBrain:
    def test_create_orchestrator_mode(self):
        """Factory creates orchestrator backend by default."""
        with patch("bantz.brain.orchestrator_loop.OrchestratorLoop") as mock_ol, \
             patch("bantz.brain.llm_router.JarvisLLMOrchestrator"):
            mock_ol.return_value = _make_orchestrator_loop()
            brain = create_brain(llm=MagicMock(), tools=MagicMock())
            assert brain.mode == "orchestrator"

    def test_create_jarvis_mode(self):
        """Factory creates jarvis backend."""
        with patch("bantz.brain.brain_loop.BrainLoop") as mock_bl:
            mock_bl.return_value = _make_brain_loop()
            brain = create_brain(mode="jarvis", llm=MagicMock(), tools=MagicMock())
            assert brain.mode == "jarvis"

    def test_create_auto_mode(self):
        """Factory with mode='auto' creates both backends (mocked)."""
        with patch("bantz.brain.brain_loop.BrainLoop") as mock_bl, \
             patch("bantz.brain.orchestrator_loop.OrchestratorLoop") as mock_ol, \
             patch("bantz.brain.llm_router.JarvisLLMOrchestrator"):
            mock_bl.return_value = _make_brain_loop()
            mock_ol.return_value = _make_orchestrator_loop()
            brain = create_brain(mode="auto", llm=MagicMock(), tools=MagicMock())
            assert brain.mode == "auto"

    def test_create_auto_tolerates_brain_loop_failure(self):
        """Auto mode gracefully handles BrainLoop init failure."""
        with patch("bantz.brain.brain_loop.BrainLoop", side_effect=ImportError("no BrainLoop")), \
             patch("bantz.brain.orchestrator_loop.OrchestratorLoop") as mock_ol, \
             patch("bantz.brain.llm_router.JarvisLLMOrchestrator"):
            mock_ol.return_value = _make_orchestrator_loop()
            brain = create_brain(mode="auto", llm=MagicMock(), tools=MagicMock())
            assert brain.mode == "auto"
            diag = brain.get_diagnostics()
            assert diag["has_brain_loop"] is False
            assert diag["has_orchestrator_loop"] is True


# ===================================================================
# 9. Process flow
# ===================================================================

class TestProcessFlow:
    def test_jarvis_process_returns_result(self):
        brain = _make_brain("jarvis")
        result = brain.process("takvimi göster")
        assert result.kind == "say"
        assert result.backend == "brain_loop"

    def test_orchestrator_process_returns_result(self):
        brain = _make_brain("orchestrator")
        result = brain.process("hava nasıl?")
        assert result.kind == "say"
        assert result.backend == "orchestrator"

    def test_error_returns_fail(self):
        orch = _make_orchestrator_loop()
        orch.process_turn.side_effect = RuntimeError("test error")
        brain = _make_brain("orchestrator", orchestrator_loop=orch)
        result = brain.process("hello")
        assert result.kind == "fail"
        assert "test error" in result.text

    def test_multi_turn_preserves_diagnostics(self):
        brain = _make_brain("orchestrator")
        for i in range(5):
            brain.process(f"turn {i}")
        diag = brain.get_diagnostics()
        assert diag["turn_count"] == 5
        assert diag["backend_usage"]["orchestrator"] == 5


# ===================================================================
# 10. Custom jarvis patterns
# ===================================================================

class TestCustomPatterns:
    def test_custom_pattern_in_auto_mode(self):
        cfg = UnifiedConfig(mode="auto", auto_jarvis_patterns=["özel_komut"])
        brain = UnifiedBrain(
            mode="auto",
            brain_loop=_make_brain_loop(),
            orchestrator_loop=_make_orchestrator_loop(),
            config=cfg,
        )
        result = brain.process("özel_komut çalıştır")
        assert result.backend == "brain_loop"

    def test_custom_pattern_no_match_goes_orchestrator(self):
        cfg = UnifiedConfig(mode="auto", auto_jarvis_patterns=["özel_komut"])
        brain = UnifiedBrain(
            mode="auto",
            brain_loop=_make_brain_loop(),
            orchestrator_loop=_make_orchestrator_loop(),
            config=cfg,
        )
        result = brain.process("genel soru sor")
        assert result.backend == "orchestrator"
