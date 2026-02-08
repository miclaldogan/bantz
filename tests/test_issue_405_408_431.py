"""Tests for Issues #405, #408, #431: Quality & Safety Fixes.

#405 — Router prompt budget: system prompt restructured into tiers,
       compact-system-prompt now strips examples → detail → hard-trim.
#408 — Gemini Hybrid: two-phase API (plan + finalize) so callers can
       pass real tool_results to Gemini instead of None.
#431 — Tool execution timeout: configurable per-tool timeout prevents
       API hangs from blocking turns forever.
"""

from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Issue #405 tests — Router prompt tiered compaction
# ---------------------------------------------------------------------------

class TestIssue405PromptBudget:
    """Verify the restructured system prompt fits in small context windows."""

    def _import(self):
        from bantz.brain.llm_router import (
            JarvisLLMOrchestrator,
            _estimate_tokens,
        )
        return JarvisLLMOrchestrator, _estimate_tokens

    def test_core_prompt_under_800_tokens(self):
        cls, est = self._import()
        core_tokens = est(cls._SYSTEM_PROMPT_CORE)
        assert core_tokens <= 800, f"CORE prompt {core_tokens} tokens > 800"

    def test_full_prompt_under_1600_tokens(self):
        cls, est = self._import()
        full_tokens = est(cls.SYSTEM_PROMPT)
        assert full_tokens <= 1600, f"Full prompt {full_tokens} tokens > 1600"

    def test_full_prompt_equals_core_plus_detail_plus_examples(self):
        cls, _ = self._import()
        expected = cls._SYSTEM_PROMPT_CORE + cls._SYSTEM_PROMPT_DETAIL + cls._SYSTEM_PROMPT_EXAMPLES
        assert cls.SYSTEM_PROMPT == expected

    def test_compact_removes_examples_first(self):
        cls, est = self._import()
        # Budget that fits CORE+DETAIL but not EXAMPLES
        budget = est(cls._SYSTEM_PROMPT_CORE + cls._SYSTEM_PROMPT_DETAIL) + 10

        orch = cls.__new__(cls)
        compact = orch._maybe_compact_system_prompt(cls.SYSTEM_PROMPT, token_budget=budget)
        assert "ÖRNEKLER:" not in compact
        assert "KURALLAR:" in compact  # core rules preserved

    def test_compact_removes_detail_when_tight(self):
        cls, est = self._import()
        # Budget that fits only CORE
        budget = est(cls._SYSTEM_PROMPT_CORE) + 10

        orch = cls.__new__(cls)
        compact = orch._maybe_compact_system_prompt(cls.SYSTEM_PROMPT, token_budget=budget)
        assert "ÖRNEKLER:" not in compact
        assert "GMAIL ARAMA" not in compact
        assert "SAAT FORMATLARI" not in compact
        # Core rules should still be present
        assert "KURALLAR:" in compact

    def test_compact_zero_budget_returns_empty(self):
        cls, _ = self._import()
        orch = cls.__new__(cls)
        assert orch._maybe_compact_system_prompt(cls.SYSTEM_PROMPT, token_budget=0) == ""

    def test_compact_large_budget_returns_full(self):
        cls, _ = self._import()
        orch = cls.__new__(cls)
        result = orch._maybe_compact_system_prompt(cls.SYSTEM_PROMPT, token_budget=5000)
        assert result == cls.SYSTEM_PROMPT

    def test_core_contains_critical_sections(self):
        """Core prompt must have: identity, schema, rules, routes, tools, time rules."""
        cls, _ = self._import()
        core = cls._SYSTEM_PROMPT_CORE
        for keyword in ["BANTZ", "OUTPUT SCHEMA", "KURALLAR", "ROUTE:", "TOOLS:", "SAAT:"]:
            assert keyword in core, f"Core prompt missing '{keyword}'"

    def test_core_has_all_tool_names(self):
        """Core prompt must list all tool names (without descriptions)."""
        cls, _ = self._import()
        core = cls._SYSTEM_PROMPT_CORE
        critical_tools = [
            "calendar.list_events", "calendar.create_event",
            "gmail.list_messages", "gmail.send",
            "contacts.resolve", "contacts.list",
            "time.now", "system.status",
        ]
        for tool in critical_tools:
            assert tool in core, f"Core prompt missing tool '{tool}'"

    def test_prompt_fits_2048_context(self):
        """After compaction, system prompt + user input must fit in 2048-ctx."""
        cls, est = self._import()
        from bantz.brain.llm_router import PromptBudgetConfig

        budget = PromptBudgetConfig.for_context(2048)
        prompt_avail = budget.available_for_prompt  # 2048-512-32 = 1504

        # Simulate: compact system prompt + typical user input
        orch = cls.__new__(cls)
        compact = orch._maybe_compact_system_prompt(
            cls.SYSTEM_PROMPT, token_budget=int(prompt_avail * 0.6)
        )
        user_input_tokens = est("USER: bugün beşe toplantı koy\nASSISTANT (sadece JSON):")

        total = est(compact) + user_input_tokens
        assert total < prompt_avail, (
            f"System({est(compact)}) + user({user_input_tokens}) = {total} > {prompt_avail}"
        )


# ---------------------------------------------------------------------------
# Issue #408 tests — REMOVED (GeminiHybridOrchestrator deleted in #519)
# The two-phase plan()+finalize() API is now covered by OrchestratorLoop
# and FinalizationPipeline tests.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue #431 tests — Tool execution timeout
# ---------------------------------------------------------------------------

class TestIssue431ToolTimeout:
    """Verify tool execution timeout wrapping."""

    def test_config_has_tool_timeout(self):
        from bantz.brain.orchestrator_loop import OrchestratorConfig
        cfg = OrchestratorConfig()
        assert hasattr(cfg, "tool_timeout_seconds")
        assert cfg.tool_timeout_seconds == 30.0

    def test_config_custom_timeout(self):
        from bantz.brain.orchestrator_loop import OrchestratorConfig
        cfg = OrchestratorConfig()
        cfg.tool_timeout_seconds = 5.0
        assert cfg.tool_timeout_seconds == 5.0

    def test_slow_tool_times_out(self):
        """A tool that sleeps longer than timeout should produce a timeout error."""
        import warnings
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
        from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
        from bantz.agent.tools import ToolRegistry, Tool
        from bantz.core.events import EventBus
        from bantz.tools.metadata import register_tool_risk, ToolRisk

        register_tool_risk("slow_tool", ToolRisk.SAFE)

        # Slow tool: sleeps 5 seconds
        def slow_tool(**kwargs):
            time.sleep(5)
            return {"ok": True}

        tools = ToolRegistry()
        tools.register(Tool(
            name="slow_tool",
            description="A slow tool",
            function=slow_tool,
            parameters={},
        ))

        router_json = json.dumps({
            "route": "calendar", "calendar_intent": "query",
            "slots": {}, "confidence": 0.9,
            "tool_plan": ["slow_tool"],
            "assistant_reply": "",
        })
        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = router_json

        config = OrchestratorConfig()
        config.tool_timeout_seconds = 0.5  # 500ms timeout
        config.enable_safety_guard = False

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            loop = OrchestratorLoop(
                orchestrator=JarvisLLMOrchestrator(llm=mock_llm),
                tools=tools,
                event_bus=EventBus(),
                config=config,
            )

        # Run a full cycle
        trace = loop.run_full_cycle("test")
        
        # Tool should have failed with timeout
        assert trace["tools_executed"] == 0
        assert trace["tools_attempted"] == 1

        # Cleanup
        from bantz.tools.metadata import TOOL_REGISTRY
        TOOL_REGISTRY.pop("slow_tool", None)

    def test_fast_tool_succeeds_within_timeout(self):
        """A tool that returns quickly should succeed normally."""
        import warnings
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        from bantz.agent.tools import ToolRegistry, Tool
        from bantz.core.events import EventBus
        from bantz.tools.metadata import register_tool_risk, ToolRisk

        register_tool_risk("fast_tool", ToolRisk.SAFE)

        def fast_tool(**kwargs):
            return {"ok": True, "data": "hello"}

        tools = ToolRegistry()
        tools.register(Tool(
            name="fast_tool",
            description="A fast tool",
            function=fast_tool,
            parameters={},
        ))

        router_json = json.dumps({
            "route": "calendar", "calendar_intent": "query",
            "slots": {}, "confidence": 0.9,
            "tool_plan": ["fast_tool"],
            "assistant_reply": "Tamamdır.",
        })
        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = router_json

        config = OrchestratorConfig()
        config.tool_timeout_seconds = 5.0
        config.enable_safety_guard = False

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            loop = OrchestratorLoop(
                orchestrator=JarvisLLMOrchestrator(llm=mock_llm),
                tools=tools,
                event_bus=EventBus(),
                config=config,
            )

        trace = loop.run_full_cycle("test")
        assert trace["tools_executed"] == 1

        # Cleanup
        from bantz.tools.metadata import TOOL_REGISTRY
        TOOL_REGISTRY.pop("fast_tool", None)

    def test_timeout_event_published(self):
        """Verify tool.timeout event is published on timeout."""
        import warnings
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        from bantz.agent.tools import ToolRegistry, Tool
        from bantz.core.events import EventBus
        from bantz.tools.metadata import register_tool_risk, ToolRisk

        register_tool_risk("slow_tool", ToolRisk.SAFE)

        def slow_tool(**kwargs):
            time.sleep(5)
            return {"ok": True}

        tools = ToolRegistry()
        tools.register(Tool(
            name="slow_tool",
            description="Slow",
            function=slow_tool,
            parameters={},
        ))

        router_json = json.dumps({
            "route": "calendar", "calendar_intent": "query",
            "slots": {}, "confidence": 0.9,
            "tool_plan": ["slow_tool"],
            "assistant_reply": "",
        })
        mock_llm = MagicMock()
        mock_llm.complete_text.return_value = router_json

        config = OrchestratorConfig()
        config.tool_timeout_seconds = 0.5
        config.enable_safety_guard = False

        events_captured = []
        event_bus = EventBus()
        event_bus.subscribe("tool.timeout", lambda event: events_captured.append(event.data))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            loop = OrchestratorLoop(
                orchestrator=JarvisLLMOrchestrator(llm=mock_llm),
                tools=tools,
                event_bus=event_bus,
                config=config,
            )

        loop.run_full_cycle("test")
        assert len(events_captured) == 1
        assert events_captured[0]["tool"] == "slow_tool"
        assert events_captured[0]["timeout_seconds"] == 0.5

        # Cleanup
        from bantz.tools.metadata import TOOL_REGISTRY
        TOOL_REGISTRY.pop("slow_tool", None)
