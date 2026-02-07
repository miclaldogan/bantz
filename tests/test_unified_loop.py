"""Tests for UnifiedBrain — Issue #403 (Brain Consolidation Phase 1).

Covers:
- UnifiedBrain creation via factory
- Jarvis mode delegating to BrainLoop
- Orchestrator mode delegating to OrchestratorLoop
- Result normalisation (UnifiedResult)
- State persistence across turns
- Empty input handling
- Mode validation
- Deprecation warnings
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import Mock, MagicMock, patch

import pytest

from bantz.brain.unified_loop import (
    UnifiedBrain,
    UnifiedConfig,
    UnifiedResult,
    create_brain,
)


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


class FakeLLM:
    """Fake LLM that returns canned JSON outputs (for BrainLoop)."""

    def __init__(self, outputs: list[dict] | None = None):
        self._outputs = list(outputs or [])
        self.calls: int = 0

    def complete_json(
        self, *, messages: list[dict[str, str]], schema_hint: str
    ) -> dict:
        self.calls += 1
        if not self._outputs:
            return {"type": "FAIL", "error": "no_more_outputs"}
        return self._outputs.pop(0)

    def complete_text(
        self, *, prompt: str = "", temperature: float = 0.0, max_tokens: int = 200
    ) -> str:
        self.calls += 1
        return "Tamam efendim."


def _make_tool_registry():
    """Create a minimal ToolRegistry with one tool."""
    from bantz.agent.tools import Tool, ToolRegistry

    tools = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    tools.register(
        Tool(
            name="add",
            description="Add two integers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            function=add,
        )
    )
    return tools


# ---------------------------------------------------------------------------
# UnifiedResult dataclass
# ---------------------------------------------------------------------------


class TestUnifiedResult:
    def test_default_fields(self):
        r = UnifiedResult(kind="say", text="Merhaba")
        assert r.kind == "say"
        assert r.text == "Merhaba"
        assert r.route == ""
        assert r.intent == ""
        assert r.confidence == 0.0
        assert r.tool_plan == []
        assert r.tools_executed == []
        assert r.requires_confirmation is False
        assert r.steps_used == 0
        assert r.metadata == {}
        assert r.backend == ""
        assert r.state is None

    def test_all_fields(self):
        r = UnifiedResult(
            kind="ask_user",
            text="Saat kaç?",
            route="calendar",
            intent="query",
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            tools_executed=["calendar.list_events"],
            requires_confirmation=True,
            steps_used=2,
            metadata={"foo": "bar"},
            backend="orchestrator",
            state={"key": "val"},
        )
        assert r.kind == "ask_user"
        assert r.route == "calendar"
        assert r.confidence == 0.9
        assert r.backend == "orchestrator"


# ---------------------------------------------------------------------------
# UnifiedConfig
# ---------------------------------------------------------------------------


class TestUnifiedConfig:
    def test_defaults(self):
        c = UnifiedConfig()
        assert c.mode == "orchestrator"
        assert c.max_steps == 8
        assert c.debug is False
        assert c.enable_safety_guard is True

    def test_jarvis_mode(self):
        c = UnifiedConfig(mode="jarvis", debug=True)
        assert c.mode == "jarvis"
        assert c.debug is True


# ---------------------------------------------------------------------------
# UnifiedBrain — constructor
# ---------------------------------------------------------------------------


class TestUnifiedBrainInit:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown mode"):
            UnifiedBrain(mode="invalid")

    def test_jarvis_requires_brain_loop(self):
        with pytest.raises(ValueError, match="BrainLoop"):
            UnifiedBrain(mode="jarvis")

    def test_orchestrator_requires_orchestrator_loop(self):
        with pytest.raises(ValueError, match="OrchestratorLoop"):
            UnifiedBrain(mode="orchestrator")

    def test_jarvis_mode_ok(self):
        brain = UnifiedBrain(mode="jarvis", brain_loop=Mock())
        assert brain.mode == "jarvis"
        assert brain.backend is not None

    def test_orchestrator_mode_ok(self):
        brain = UnifiedBrain(mode="orchestrator", orchestrator_loop=Mock())
        assert brain.mode == "orchestrator"
        assert brain.backend is not None


# ---------------------------------------------------------------------------
# UnifiedBrain — empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_string(self):
        brain = UnifiedBrain(mode="jarvis", brain_loop=Mock())
        result = brain.process("")
        assert result.kind == "fail"
        assert result.text == "empty_input"

    def test_whitespace_only(self):
        brain = UnifiedBrain(mode="orchestrator", orchestrator_loop=Mock())
        result = brain.process("   ")
        assert result.kind == "fail"
        assert result.text == "empty_input"

    def test_none_input(self):
        brain = UnifiedBrain(mode="jarvis", brain_loop=Mock())
        result = brain.process(None)
        assert result.kind == "fail"


# ---------------------------------------------------------------------------
# UnifiedBrain — Jarvis mode (BrainLoop delegation)
# ---------------------------------------------------------------------------


class TestJarvisMode:
    def test_delegates_to_brain_loop(self):
        """process() calls BrainLoop.run() and returns a UnifiedResult."""
        from bantz.brain.brain_loop import BrainResult

        mock_bl = Mock()
        mock_bl.run.return_value = BrainResult(
            kind="say",
            text="Merhaba efendim",
            steps_used=1,
            metadata={"trace": {"intent": "smalltalk"}},
        )

        brain = UnifiedBrain(mode="jarvis", brain_loop=mock_bl)
        result = brain.process("merhaba")

        assert result.kind == "say"
        assert result.text == "Merhaba efendim"
        assert result.backend == "brain_loop"
        assert result.steps_used == 1
        mock_bl.run.assert_called_once()

    def test_session_context_merge(self):
        """Default + per-turn session_context merge correctly."""
        from bantz.brain.brain_loop import BrainResult

        mock_bl = Mock()
        mock_bl.run.return_value = BrainResult(
            kind="say", text="ok", steps_used=0, metadata={}
        )

        brain = UnifiedBrain(
            mode="jarvis",
            brain_loop=mock_bl,
            session_context={"tz_name": "Europe/Istanbul"},
        )
        brain.process("test", session_context={"locale": "tr"})

        call_kwargs = mock_bl.run.call_args
        ctx = call_kwargs.kwargs.get("session_context") or call_kwargs[1].get("session_context")
        assert ctx["tz_name"] == "Europe/Istanbul"
        assert ctx["locale"] == "tr"

    def test_state_persists_across_turns(self):
        """Internal jarvis_state dict persists between turns."""
        from bantz.brain.brain_loop import BrainResult

        call_count = 0

        def fake_run(*, turn_input, session_context, policy, context):
            nonlocal call_count
            call_count += 1
            context["last_intent"] = "calendar"
            return BrainResult(kind="say", text=f"turn {call_count}", steps_used=0, metadata={})

        mock_bl = Mock()
        mock_bl.run.side_effect = fake_run

        brain = UnifiedBrain(mode="jarvis", brain_loop=mock_bl)
        brain.process("first turn")
        brain.process("second turn")

        # The second call should see state from the first
        second_call = mock_bl.run.call_args_list[1]
        ctx_arg = second_call.kwargs.get("context") or second_call[1].get("context")
        assert ctx_arg.get("last_intent") == "calendar"

    def test_from_brain_result_with_trace(self):
        """BrainResult with rich trace metadata is normalised properly."""
        from bantz.brain.brain_loop import BrainResult

        br = BrainResult(
            kind="ask_user",
            text="Saat kaç olsun?",
            steps_used=0,
            metadata={
                "trace": {
                    "intent": "calendar.create",
                    "llm_router_route": "calendar",
                    "llm_router_confidence": 0.85,
                    "llm_router_tool_plan": ["calendar.create_event"],
                },
                "requires_confirmation": True,
            },
        )

        result = UnifiedBrain._from_brain_result(br)
        assert result.kind == "ask_user"
        assert result.route == "calendar"
        assert result.intent == "calendar.create"
        assert result.confidence == 0.85
        assert result.requires_confirmation is True
        assert result.tool_plan == ["calendar.create_event"]


# ---------------------------------------------------------------------------
# UnifiedBrain — Orchestrator mode (OrchestratorLoop delegation)
# ---------------------------------------------------------------------------


class TestOrchestratorMode:
    def _make_mock_output(self, **overrides):
        """Create a mock OrchestratorOutput."""
        defaults = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "Merhaba efendim!",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "",
            "reasoning_summary": [],
            "raw_output": {},
        }
        defaults.update(overrides)

        output = Mock()
        for k, v in defaults.items():
            setattr(output, k, v)
        return output

    def test_delegates_to_orchestrator_loop(self):
        """process() calls OrchestratorLoop.process_turn() and normalises."""
        from bantz.brain.orchestrator_state import OrchestratorState

        mock_output = self._make_mock_output()
        mock_state = OrchestratorState()

        mock_orch = Mock()
        mock_orch.process_turn.return_value = (mock_output, mock_state)

        brain = UnifiedBrain(mode="orchestrator", orchestrator_loop=mock_orch)
        result = brain.process("merhaba")

        assert result.kind == "say"
        assert result.text == "Merhaba efendim!"
        assert result.route == "smalltalk"
        assert result.backend == "orchestrator"
        mock_orch.process_turn.assert_called_once()

    def test_ask_user_normalisation(self):
        """When ask_user=True and question is set, kind should be 'ask_user'."""
        from bantz.brain.orchestrator_state import OrchestratorState

        mock_output = self._make_mock_output(
            ask_user=True,
            question="Hangi gün efendim?",
            assistant_reply="",
        )
        mock_state = OrchestratorState()

        mock_orch = Mock()
        mock_orch.process_turn.return_value = (mock_output, mock_state)

        brain = UnifiedBrain(mode="orchestrator", orchestrator_loop=mock_orch)
        result = brain.process("toplantı ekle")

        assert result.kind == "ask_user"
        assert result.text == "Hangi gün efendim?"

    def test_state_persists_across_turns(self):
        """OrchestratorState persists between turns."""
        from bantz.brain.orchestrator_state import OrchestratorState

        state_v1 = OrchestratorState()
        state_v1.turn_count = 1

        state_v2 = OrchestratorState()
        state_v2.turn_count = 2

        mock_orch = Mock()
        mock_orch.process_turn.side_effect = [
            (self._make_mock_output(assistant_reply="turn 1"), state_v1),
            (self._make_mock_output(assistant_reply="turn 2"), state_v2),
        ]

        brain = UnifiedBrain(mode="orchestrator", orchestrator_loop=mock_orch)
        brain.process("first")
        brain.process("second")

        # The second call should get state_v1 (returned from first call)
        second_call = mock_orch.process_turn.call_args_list[1]
        state_arg = second_call.kwargs.get("state") or second_call[0][1]
        assert state_arg.turn_count == 1

    def test_session_context_injected(self):
        """session_context is injected into OrchestratorState."""
        from bantz.brain.orchestrator_state import OrchestratorState

        mock_state = OrchestratorState()
        mock_orch = Mock()
        mock_orch.process_turn.return_value = (
            self._make_mock_output(),
            mock_state,
        )

        brain = UnifiedBrain(
            mode="orchestrator",
            orchestrator_loop=mock_orch,
            session_context={"tz_name": "Europe/Istanbul"},
        )
        brain.process("test", session_context={"locale": "tr"})

        call_args = mock_orch.process_turn.call_args
        state_arg = call_args.kwargs.get("state") or call_args[0][1]
        assert state_arg.session_context["tz_name"] == "Europe/Istanbul"
        assert state_arg.session_context["locale"] == "tr"

    def test_from_orchestrator_output_with_tools(self):
        """tools_executed extracted from state trace."""
        from bantz.brain.orchestrator_state import OrchestratorState

        mock_output = self._make_mock_output(
            route="calendar",
            calendar_intent="query",
            tool_plan=["calendar.list_events"],
            assistant_reply="2 etkinlik bulundu.",
        )

        state = OrchestratorState()
        state.trace = {"tools_success": ["calendar.list_events"]}

        result = UnifiedBrain._from_orchestrator_output(mock_output, state)
        assert result.route == "calendar"
        assert result.intent == "query"
        assert result.tools_executed == ["calendar.list_events"]


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_state(self):
        brain = UnifiedBrain(mode="orchestrator", orchestrator_loop=Mock())
        brain._orchestrator_state = "something"
        brain._jarvis_state = {"key": "value"}

        brain.reset()

        assert brain._orchestrator_state is None
        assert brain._jarvis_state == {}


# ---------------------------------------------------------------------------
# Factory — create_brain()
# ---------------------------------------------------------------------------


class TestFactory:
    def test_create_jarvis(self):
        """create_brain(mode='jarvis') creates BrainLoop internally."""
        llm = FakeLLM([{"type": "SAY", "text": "ok"}])
        tools = _make_tool_registry()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            brain = create_brain(mode="jarvis", llm=llm, tools=tools)

        assert brain.mode == "jarvis"
        assert brain.backend is not None

    def test_create_orchestrator(self):
        """create_brain(mode='orchestrator') creates OrchestratorLoop internally."""
        llm = FakeLLM()
        tools = _make_tool_registry()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            brain = create_brain(mode="orchestrator", llm=llm, tools=tools)

        assert brain.mode == "orchestrator"
        assert brain.backend is not None

    def test_create_with_finalizer(self):
        """Finalizer LLM is passed to OrchestratorLoop."""
        llm = FakeLLM()
        finalizer = FakeLLM()
        tools = _make_tool_registry()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            brain = create_brain(
                mode="orchestrator",
                llm=llm,
                tools=tools,
                finalizer_llm=finalizer,
            )

        assert brain.mode == "orchestrator"

    def test_create_with_config(self):
        """Custom config is applied to backend."""
        llm = FakeLLM()
        tools = _make_tool_registry()
        config = UnifiedConfig(mode="orchestrator", max_steps=3, debug=True)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            brain = create_brain(mode="orchestrator", llm=llm, tools=tools, config=config)

        assert brain._config.max_steps == 3
        assert brain._config.debug is True


# ---------------------------------------------------------------------------
# Deprecation warnings on legacy constructors
# ---------------------------------------------------------------------------


class TestDeprecationWarnings:
    def test_brain_loop_warns(self):
        """BrainLoop() emits DeprecationWarning."""
        from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig

        llm = FakeLLM()
        tools = _make_tool_registry()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=1))

        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "BrainLoop is deprecated" in str(dep_warnings[0].message)

    def test_orchestrator_loop_warns(self):
        """OrchestratorLoop() emits DeprecationWarning."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        llm = FakeLLM()
        tools = _make_tool_registry()
        orch = JarvisLLMOrchestrator(llm_client=llm)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            OrchestratorLoop(orch, tools, config=OrchestratorConfig())

        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1
        assert "OrchestratorLoop is deprecated" in str(dep_warnings[0].message)


# ---------------------------------------------------------------------------
# Integration: Jarvis mode end-to-end
# ---------------------------------------------------------------------------


class TestJarvisE2E:
    def test_say_result(self):
        """Full Jarvis flow: LLM says → UnifiedResult(kind='say')."""
        llm = FakeLLM([{"type": "SAY", "text": "Sonuç 5."}])
        tools = _make_tool_registry()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            brain = create_brain(mode="jarvis", llm=llm, tools=tools)

        result = brain.process("iki artı üç")
        assert result.kind == "say"
        assert "5" in result.text
        assert result.backend == "brain_loop"

    def test_tool_then_say(self):
        """Full Jarvis flow: LLM calls tool → says result → UnifiedResult."""
        llm = FakeLLM(
            [
                {"type": "CALL_TOOL", "name": "add", "params": {"a": 2, "b": 3}},
                {"type": "SAY", "text": "Sonuç 5."},
            ]
        )
        tools = _make_tool_registry()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            brain = create_brain(
                mode="jarvis",
                llm=llm,
                tools=tools,
                config=UnifiedConfig(mode="jarvis", max_steps=4),
            )

        result = brain.process("2 ile 3 topla")
        assert result.kind == "say"
        assert "5" in result.text
        assert result.steps_used == 2


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_imports_from_brain_package(self):
        """UnifiedBrain and create_brain are importable from bantz.brain."""
        from bantz.brain import UnifiedBrain, UnifiedConfig, UnifiedResult, create_brain

        assert UnifiedBrain is not None
        assert create_brain is not None
        assert UnifiedConfig is not None
        assert UnifiedResult is not None

    def test_legacy_imports_still_work(self):
        """BrainLoop and friends still importable from bantz.brain."""
        from bantz.brain import BrainLoop, BrainLoopConfig, BrainResult, LLMClient

        assert BrainLoop is not None
        assert BrainLoopConfig is not None
        assert BrainResult is not None
