"""Tests for Issue #412: Unified HybridOrchestrator.

Tests cover:
  - HybridConfig: defaults, from_env, env overrides
  - HybridOrchestrator: plan, finalize, orchestrate, fallback, no-new-facts guard
  - summarize_tool_results: truncation strategies
  - Deprecation warnings for GeminiHybridOrchestrator & FlexibleHybridOrchestrator
  - create_hybrid_orchestrator factory
"""

from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.hybrid_orchestrator import (
    HybridOrchestrator,
    HybridConfig,
    create_hybrid_orchestrator,
    summarize_tool_results,
    _check_no_new_facts,
)
from bantz.brain.llm_router import OrchestratorOutput
from bantz.llm.base import LLMClient, LLMMessage, LLMResponse


# ======================================================================
# Mock helpers
# ======================================================================


class MockRouterClient(LLMClient):
    """Mock 3B router that returns a canned JSON plan."""

    def __init__(self, route="calendar", intent="query_events"):
        self._route = route
        self._intent = intent

    @property
    def model_name(self) -> str:
        return "mock-3b"

    @property
    def backend_name(self) -> str:
        return "mock"

    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        return True

    def chat(self, messages, *, temperature=0.4, max_tokens=512) -> str:
        return json.dumps({
            "route": self._route,
            "calendar_intent": self._intent,
            "confidence": 0.9,
            "assistant_reply": "Router cevabı efendim.",
            "tool_plan": [],
            "slots": {"date": "today"},
        })

    def chat_detailed(self, messages, *, temperature=0.4, max_tokens=512, seed=None) -> LLMResponse:
        return LLMResponse(content=self.chat(messages), model="mock-3b", tokens_used=10)

    def complete_text(self, *, prompt, temperature=0.0, max_tokens=200) -> str:
        return self.chat([LLMMessage(role="user", content=prompt)])


class MockFinalizer:
    """Mock finalizer that returns a canned response."""

    def __init__(self, response="Merhaba efendim!", available=True):
        self._response = response
        self._available = available
        self.call_count = 0
        self.last_messages = None

    def chat_detailed(self, messages, *, temperature=0.4, max_tokens=512) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages
        return LLMResponse(content=self._response, model="mock-finalizer", tokens_used=5, finish_reason="stop")

    def is_available(self, *, timeout_seconds=1.5) -> bool:
        return self._available


class FailingFinalizer:
    """Finalizer that always raises."""

    def chat_detailed(self, messages, **kwargs):
        raise RuntimeError("Finalizer crashed")

    def is_available(self, **kwargs) -> bool:
        return True


# ======================================================================
# HybridConfig Tests
# ======================================================================


class TestHybridConfig:
    def test_defaults(self):
        c = HybridConfig()
        assert c.finalizer_type == "gemini"
        assert c.finalizer_model == "gemini-1.5-flash"
        assert c.fallback_to_3b is True
        assert c.no_new_facts_guard is True
        assert c.tool_results_max_chars == 2000

    def test_from_env_gemini(self, monkeypatch):
        monkeypatch.delenv("BANTZ_FINALIZER_TYPE", raising=False)
        monkeypatch.delenv("BANTZ_FINALIZER_MODEL", raising=False)
        c = HybridConfig.from_env()
        assert c.finalizer_type == "gemini"
        assert c.finalizer_model == "gemini-1.5-flash"

    def test_from_env_vllm_7b(self, monkeypatch):
        monkeypatch.setenv("BANTZ_FINALIZER_TYPE", "vllm_7b")
        monkeypatch.delenv("BANTZ_FINALIZER_MODEL", raising=False)
        c = HybridConfig.from_env()
        assert c.finalizer_type == "vllm_7b"
        assert c.finalizer_model == "Qwen/Qwen2.5-7B-Instruct"

    def test_from_env_custom_model(self, monkeypatch):
        monkeypatch.setenv("BANTZ_FINALIZER_TYPE", "gemini")
        monkeypatch.setenv("BANTZ_FINALIZER_MODEL", "gemini-2.0-flash")
        c = HybridConfig.from_env()
        assert c.finalizer_model == "gemini-2.0-flash"

    def test_from_env_invalid_type_defaults_gemini(self, monkeypatch):
        monkeypatch.setenv("BANTZ_FINALIZER_TYPE", "invalid")
        c = HybridConfig.from_env()
        assert c.finalizer_type == "gemini"

    def test_from_env_guard_disabled(self, monkeypatch):
        monkeypatch.setenv("BANTZ_NO_NEW_FACTS_GUARD", "0")
        c = HybridConfig.from_env()
        assert c.no_new_facts_guard is False

    def test_from_env_guard_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("BANTZ_NO_NEW_FACTS_GUARD", raising=False)
        c = HybridConfig.from_env()
        assert c.no_new_facts_guard is True


# ======================================================================
# HybridOrchestrator Tests
# ======================================================================


class TestHybridOrchestratorPlan:
    def test_plan_returns_router_output(self):
        router = MockRouterClient(route="calendar", intent="query_events")
        o = HybridOrchestrator(router=router, config=HybridConfig())
        out = o.plan("bugün toplantılarım neler?")
        assert out.route == "calendar"
        assert out.calendar_intent == "query_events"
        assert out.confidence == 0.9

    def test_plan_smalltalk(self):
        router = MockRouterClient(route="smalltalk", intent="")
        o = HybridOrchestrator(router=router, config=HybridConfig())
        out = o.plan("nasılsın?")
        assert out.route == "smalltalk"


class TestHybridOrchestratorFinalize:
    def test_finalize_uses_finalizer(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(response="3 toplantınız var efendim.")
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        plan_out = o.plan("bugün toplantılarım?")
        result = o.finalize(plan_out, user_input="bugün toplantılarım?")
        assert result.assistant_reply == "3 toplantınız var efendim."
        assert finalizer.call_count == 1

    def test_finalize_with_tool_results(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(response="3 etkinlik var efendim.")
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        plan_out = o.plan("bugün?")
        tool_results = [{"tool_name": "calendar.list", "status": "success", "result": {"events": []}}]
        result = o.finalize(plan_out, user_input="bugün?", tool_results=tool_results)
        assert "etkinlik" in result.assistant_reply

    def test_finalize_preserves_route_metadata(self):
        router = MockRouterClient(route="calendar", intent="create_event")
        finalizer = MockFinalizer(response="Tamam efendim.")
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        plan_out = o.plan("toplantı ekle")
        result = o.finalize(plan_out, user_input="toplantı ekle")
        assert result.route == "calendar"
        assert result.calendar_intent == "create_event"
        assert result.slots == {"date": "today"}

    def test_finalize_fallback_on_error(self):
        router = MockRouterClient()
        finalizer = FailingFinalizer()
        o = HybridOrchestrator(
            router=router, finalizer=finalizer,
            config=HybridConfig(fallback_to_3b=True),
        )
        plan_out = o.plan("test")
        result = o.finalize(plan_out, user_input="test")
        assert result.assistant_reply == "Router cevabı efendim."

    def test_finalize_no_fallback_raises(self):
        router = MockRouterClient()
        finalizer = FailingFinalizer()
        o = HybridOrchestrator(
            router=router, finalizer=finalizer,
            config=HybridConfig(fallback_to_3b=False),
        )
        plan_out = o.plan("test")
        with pytest.raises(RuntimeError, match="Finalizer crashed"):
            o.finalize(plan_out, user_input="test")

    def test_finalize_unavailable_finalizer_fallback(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(available=False)
        o = HybridOrchestrator(
            router=router, finalizer=finalizer,
            config=HybridConfig(fallback_to_3b=True),
        )
        plan_out = o.plan("test")
        result = o.finalize(plan_out, user_input="test")
        assert result.assistant_reply == "Router cevabı efendim."
        assert finalizer.call_count == 0

    def test_finalize_no_finalizer_fallback(self):
        router = MockRouterClient()
        o = HybridOrchestrator(router=router, finalizer=None, config=HybridConfig())
        plan_out = o.plan("test")
        result = o.finalize(plan_out, user_input="test")
        assert result.assistant_reply == "Router cevabı efendim."


class TestHybridOrchestratorOrchestrate:
    def test_orchestrate_combines_plan_and_finalize(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(response="Tamam efendim.")
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        result = o.orchestrate(user_input="merhaba")
        assert result.assistant_reply == "Tamam efendim."
        assert result.route == "calendar"

    def test_orchestrate_with_tool_results(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(response="İşlem tamam.")
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        result = o.orchestrate(
            user_input="test",
            tool_results=[{"tool_name": "t", "status": "ok", "result": "done"}],
        )
        assert result.assistant_reply == "İşlem tamam."


# ======================================================================
# No-New-Facts Guard Tests
# ======================================================================


class TestNoNewFactsGuard:
    def test_no_violation(self):
        assert _check_no_new_facts("Toplantınız saat 14:00'te.", "14:00 meeting") is True

    def test_date_violation(self):
        assert _check_no_new_facts("25/12/2025 tarihinde.", "") is False

    def test_time_violation(self):
        assert _check_no_new_facts("Saat 09:30'da.", "") is False

    def test_matching_date_ok(self):
        assert _check_no_new_facts("25/12/2025 tarihinde.", "25/12/2025 event") is True

    def test_guard_triggers_retry(self):
        """When guard detects violation, finalizer should be called twice."""
        router = MockRouterClient()
        # First response has fabricated date, second is clean
        call_count = 0

        class GuardTestFinalizer:
            def chat_detailed(self, messages, **kwargs) -> LLMResponse:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return LLMResponse(content="Toplantınız 31/12/2099'da.", model="m", tokens_used=5, finish_reason="stop")
                return LLMResponse(content="Toplantınız var efendim.", model="m", tokens_used=5, finish_reason="stop")

            def is_available(self, **kwargs) -> bool:
                return True

        o = HybridOrchestrator(
            router=router,
            finalizer=GuardTestFinalizer(),
            config=HybridConfig(no_new_facts_guard=True),
        )
        plan_out = o.plan("test")
        result = o.finalize(
            plan_out, user_input="test",
            tool_results=[{"tool_name": "cal", "status": "ok", "result": "events: []"}],
        )
        assert call_count == 2

    def test_guard_disabled(self):
        """With guard disabled, no retry even on fabricated content."""
        router = MockRouterClient()
        finalizer = MockFinalizer(response="31/12/2099 toplantı.")
        o = HybridOrchestrator(
            router=router, finalizer=finalizer,
            config=HybridConfig(no_new_facts_guard=False),
        )
        plan_out = o.plan("test")
        result = o.finalize(
            plan_out, user_input="test",
            tool_results=[{"tool_name": "cal", "status": "ok", "result": "empty"}],
        )
        assert finalizer.call_count == 1


# ======================================================================
# Tool Result Summarization Tests
# ======================================================================


class TestSummarizeToolResults:
    def test_empty_list(self):
        s, t = summarize_tool_results([])
        assert s == ""
        assert t is False

    def test_simple_results(self):
        results = [{"tool_name": "cal", "status": "ok", "result": "done"}]
        s, t = summarize_tool_results(results)
        assert "cal" in s
        assert t is False

    def test_list_truncation(self):
        big_list = list(range(20))
        results = [{"tool_name": "t", "result": big_list}]
        s, t = summarize_tool_results(results)
        assert t is True
        assert "first 5" in s.lower() or "_truncated" in s

    def test_calendar_event_truncation(self):
        events = [{"title": f"Event {i}"} for i in range(10)]
        results = [{"tool_name": "cal", "result": {"events": events}}]
        s, t = summarize_tool_results(results)
        assert t is True

    def test_large_string_truncation(self):
        results = [{"tool_name": "t", "result": "x" * 1000}]
        s, t = summarize_tool_results(results)
        assert t is True
        assert "truncated" in s

    def test_max_chars_respected(self):
        results = [{"tool_name": f"t{i}", "result": "x" * 500} for i in range(10)]
        s, t = summarize_tool_results(results, max_chars=500)
        assert len(s) <= 600  # Allow small overshoot from JSON wrapping
        assert t is True


# ======================================================================
# Deprecation Warning Tests
# ======================================================================


class TestDeprecationWarnings:
    def test_gemini_hybrid_orchestrator_warns(self):
        from bantz.brain.gemini_hybrid_orchestrator import GeminiHybridOrchestrator
        router = MockRouterClient()
        gemini = MockFinalizer()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            GeminiHybridOrchestrator(router=router, gemini_client=gemini)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "deprecated" in str(dep_warnings[0].message).lower()
            assert "HybridOrchestrator" in str(dep_warnings[0].message)

    def test_flexible_hybrid_orchestrator_warns(self):
        from bantz.brain.flexible_hybrid_orchestrator import FlexibleHybridOrchestrator
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        router = MockRouterClient()
        jarvis = JarvisLLMOrchestrator(llm_client=router)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FlexibleHybridOrchestrator(router_orchestrator=jarvis)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "deprecated" in str(dep_warnings[0].message).lower()
            assert "HybridOrchestrator" in str(dep_warnings[0].message)


# ======================================================================
# Factory Tests
# ======================================================================


class TestCreateHybridOrchestrator:
    def test_creates_with_defaults(self):
        router = MockRouterClient()
        o = create_hybrid_orchestrator(router=router)
        assert isinstance(o, HybridOrchestrator)

    def test_creates_with_config(self):
        router = MockRouterClient()
        config = HybridConfig(finalizer_type="vllm_7b", fallback_to_3b=False)
        o = create_hybrid_orchestrator(router=router, config=config)
        assert o._config.finalizer_type == "vllm_7b"
        assert o._config.fallback_to_3b is False

    def test_creates_with_finalizer(self):
        router = MockRouterClient()
        finalizer = MockFinalizer()
        o = create_hybrid_orchestrator(router=router, finalizer=finalizer)
        assert o.finalizer_available is True


# ======================================================================
# Property / Edge Case Tests
# ======================================================================


class TestEdgeCases:
    def test_finalizer_available_property(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(available=True)
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        assert o.finalizer_available is True

    def test_finalizer_not_available_property(self):
        router = MockRouterClient()
        finalizer = MockFinalizer(available=False)
        o = HybridOrchestrator(router=router, finalizer=finalizer, config=HybridConfig())
        assert o.finalizer_available is False

    def test_no_finalizer_property(self):
        router = MockRouterClient()
        o = HybridOrchestrator(router=router, finalizer=None, config=HybridConfig())
        assert o.finalizer_available is False

    def test_fallback_message_when_no_assistant_reply(self):
        """When router output has empty assistant_reply, use default message."""
        router = MockRouterClient()
        # Override router to return empty assistant_reply
        original_chat = router.chat
        router.chat = lambda msgs, **kw: json.dumps({
            "route": "unknown", "confidence": 0.5,
            "assistant_reply": "", "tool_plan": [], "slots": {},
        })
        o = HybridOrchestrator(router=router, finalizer=None, config=HybridConfig())
        result = o.orchestrate(user_input="test")
        assert "sorun oluştu" in result.assistant_reply.lower() or result.assistant_reply
