"""
Gemini Hybrid Integration Test Fixtures & Tests — Issue #436.

Mock servers for vLLM (3B router) and Gemini (finalizer) + golden trace
regression tests for the complete: 3B route → tool execute → Gemini finalize pipeline.

These tests use mock HTTP responses instead of real model calls,
enabling deterministic verification of the full hybrid flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest


# ─────────────────────────────────────────────────────────────────
# Mock vLLM Server (3B Router)
# ─────────────────────────────────────────────────────────────────


@dataclass
class MockVLLMResponse:
    """Simulated vLLM /v1/completions response."""
    route: str
    calendar_intent: str = "none"
    gmail_intent: str = "none"
    slots: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.92
    tool_plan: List[str] = field(default_factory=list)
    assistant_reply: str = ""
    ask_user: bool = False
    question: str = ""

    def to_router_json(self) -> str:
        """Return the JSON string the 3B model would output."""
        return json.dumps({
            "route": self.route,
            "calendar_intent": self.calendar_intent,
            "gmail_intent": self.gmail_intent,
            "slots": self.slots,
            "confidence": self.confidence,
            "tool_plan": self.tool_plan,
            "assistant_reply": self.assistant_reply,
            "ask_user": self.ask_user,
            "question": self.question,
        }, ensure_ascii=False)


class MockVLLMServer:
    """In-memory mock vLLM server for integration tests.

    Maps user_text patterns → predetermined router responses.
    """

    def __init__(self) -> None:
        self._responses: Dict[str, MockVLLMResponse] = {}
        self._calls: List[str] = []

    def register(self, pattern: str, response: MockVLLMResponse) -> None:
        self._responses[pattern.lower()] = response

    def complete(self, user_text: str) -> str:
        """Simulate /v1/completions endpoint."""
        self._calls.append(user_text)
        text_lower = user_text.lower()
        for pattern, resp in self._responses.items():
            if pattern in text_lower:
                return resp.to_router_json()
        # Default: smalltalk
        return MockVLLMResponse(route="smalltalk", assistant_reply="Evet efendim?").to_router_json()

    @property
    def call_count(self) -> int:
        return len(self._calls)


# ─────────────────────────────────────────────────────────────────
# Mock Gemini Server (Finalizer)
# ─────────────────────────────────────────────────────────────────


@dataclass
class MockGeminiResponse:
    """Simulated Gemini API response."""
    text: str
    tokens_used: int = 50
    finish_reason: str = "STOP"


class MockGeminiServer:
    """In-memory mock Gemini server for integration tests."""

    def __init__(self) -> None:
        self._responses: Dict[str, MockGeminiResponse] = {}
        self._default = MockGeminiResponse(text="Tabii efendim, yardımcı olabilirim.")
        self._calls: List[str] = []
        self._fail: bool = False

    def register(self, pattern: str, response: MockGeminiResponse) -> None:
        self._responses[pattern.lower()] = response

    def set_fail(self, fail: bool = True) -> None:
        """Simulate Gemini API failures."""
        self._fail = fail

    def generate(self, prompt: str) -> MockGeminiResponse:
        """Simulate Gemini generateContent."""
        self._calls.append(prompt)
        if self._fail:
            raise ConnectionError("Gemini API unavailable")
        prompt_lower = prompt.lower()
        for pattern, resp in self._responses.items():
            if pattern in prompt_lower:
                return resp
        return self._default

    @property
    def call_count(self) -> int:
        return len(self._calls)


# ─────────────────────────────────────────────────────────────────
# Mock Tool Executor
# ─────────────────────────────────────────────────────────────────


class MockToolExecutor:
    """Simulates tool execution for integration tests."""

    def __init__(self) -> None:
        self._results: Dict[str, Any] = {}
        self._calls: List[str] = []

    def register(self, tool_name: str, result: Any) -> None:
        self._results[tool_name] = result

    def execute(self, tool_name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._calls.append(tool_name)
        if tool_name in self._results:
            return self._results[tool_name]
        return {"ok": True}

    @property
    def call_count(self) -> int:
        return len(self._calls)


# ─────────────────────────────────────────────────────────────────
# Golden Trace
# ─────────────────────────────────────────────────────────────────


@dataclass
class GoldenTrace:
    """Expected trace for a single turn in an integration test."""
    user_text: str
    expected_route: str
    expected_intent: str = "none"
    expected_tools: List[str] = field(default_factory=list)
    expected_reply_contains: str = ""
    expected_ask_user: bool = False
    expected_gemini_called: bool = True


# ─────────────────────────────────────────────────────────────────
# Integration Test Harness
# ─────────────────────────────────────────────────────────────────


class HybridIntegrationHarness:
    """
    Test harness simulating the full 3B → Tool → Gemini pipeline.

    Steps:
    1. User text → MockVLLMServer (3B router) → OrchestratorOutput
    2. If tool_plan → MockToolExecutor → tool results
    3. If not ask_user → MockGeminiServer (finalize) → final reply
    4. Compare against GoldenTrace
    """

    def __init__(self) -> None:
        self.vllm = MockVLLMServer()
        self.gemini = MockGeminiServer()
        self.tools = MockToolExecutor()

    def run_turn(self, user_text: str) -> Dict[str, Any]:
        """Simulate a full turn."""
        # Phase 1: 3B routing
        router_json = self.vllm.complete(user_text)
        router_output = json.loads(router_json)

        route = router_output.get("route", "unknown")
        intent = router_output.get("calendar_intent", "none")
        tool_plan = router_output.get("tool_plan", [])
        ask_user = router_output.get("ask_user", False)
        assistant_reply = router_output.get("assistant_reply", "")

        # Phase 2: Tool execution
        tool_results = {}
        for tool_name in tool_plan:
            tool_results[tool_name] = self.tools.execute(tool_name)

        # Phase 3: Gemini finalization
        gemini_reply = None
        gemini_called = False
        if not ask_user:
            try:
                prompt = f"Route: {route}, Tools: {json.dumps(tool_results, ensure_ascii=False)}"
                gemini_resp = self.gemini.generate(prompt)
                gemini_reply = gemini_resp.text
                gemini_called = True
            except Exception:
                # Fallback to 3B reply
                gemini_reply = assistant_reply
                gemini_called = False

        final_reply = gemini_reply or assistant_reply

        return {
            "route": route,
            "intent": intent,
            "tool_plan": tool_plan,
            "tool_results": tool_results,
            "ask_user": ask_user,
            "gemini_called": gemini_called,
            "final_reply": final_reply,
        }

    def verify_trace(self, trace: GoldenTrace) -> List[str]:
        """Run a turn and verify against golden trace. Returns list of errors (empty = pass)."""
        result = self.run_turn(trace.user_text)
        errors: List[str] = []

        if result["route"] != trace.expected_route:
            errors.append(f"route: expected '{trace.expected_route}', got '{result['route']}'")
        if result["intent"] != trace.expected_intent:
            errors.append(f"intent: expected '{trace.expected_intent}', got '{result['intent']}'")
        if result["tool_plan"] != trace.expected_tools:
            errors.append(f"tools: expected {trace.expected_tools}, got {result['tool_plan']}")
        if trace.expected_reply_contains and trace.expected_reply_contains not in result["final_reply"]:
            errors.append(f"reply: expected to contain '{trace.expected_reply_contains}', got '{result['final_reply']}'")
        if result["ask_user"] != trace.expected_ask_user:
            errors.append(f"ask_user: expected {trace.expected_ask_user}, got {result['ask_user']}")
        if result["gemini_called"] != trace.expected_gemini_called:
            errors.append(f"gemini_called: expected {trace.expected_gemini_called}, got {result['gemini_called']}")

        return errors


# ─────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def harness() -> HybridIntegrationHarness:
    h = HybridIntegrationHarness()

    # Register vLLM (3B router) responses
    h.vllm.register("bugün takvimde ne var", MockVLLMResponse(
        route="calendar", calendar_intent="query",
        tool_plan=["calendar.list_events"],
        slots={"window_hint": "today"},
    ))
    h.vllm.register("yarın 14'te toplantı oluştur", MockVLLMResponse(
        route="calendar", calendar_intent="create",
        tool_plan=["calendar.create_event"],
        slots={"title": "Toplantı", "time": "14:00", "window_hint": "tomorrow"},
        assistant_reply="Toplantı oluşturulacak efendim.",
    ))
    h.vllm.register("nasılsın", MockVLLMResponse(
        route="smalltalk",
        assistant_reply="İyiyim efendim, teşekkür ederim!",
    ))
    h.vllm.register("saat kaç", MockVLLMResponse(
        route="system", calendar_intent="time",
        tool_plan=["time.now"],
    ))
    h.vllm.register("ne demek istiyorsun", MockVLLMResponse(
        route="smalltalk", ask_user=True,
        question="Sorunuzu biraz daha açar mısınız efendim?",
        confidence=0.4,
    ))

    # Register tool results
    h.tools.register("calendar.list_events", {
        "ok": True, "events": [
            {"summary": "Standup", "start": "2025-01-15T09:00:00+03:00", "end": "2025-01-15T09:30:00+03:00"},
            {"summary": "Sprint Review", "start": "2025-01-15T14:00:00+03:00", "end": "2025-01-15T15:00:00+03:00"},
        ]
    })
    h.tools.register("calendar.create_event", {"ok": True, "summary": "Toplantı", "start": "2025-01-16T14:00:00+03:00"})
    h.tools.register("time.now", {"time": "14:30", "date": "2025-01-15"})

    # Register Gemini finalizer responses
    h.gemini.register("calendar", MockGeminiResponse(
        text="Bugün 2 etkinliğiniz var efendim: 09:00'da Standup ve 14:00'da Sprint Review.",
    ))
    h.gemini.register("smalltalk", MockGeminiResponse(
        text="İyiyim efendim, size nasıl yardımcı olabilirim?",
    ))
    h.gemini.register("system", MockGeminiResponse(
        text="Saat 14:30 efendim.",
    ))

    return h


class TestSmalltalk:
    def test_smalltalk_route_and_gemini_finalize(self, harness: HybridIntegrationHarness):
        errors = harness.verify_trace(GoldenTrace(
            user_text="nasılsın",
            expected_route="smalltalk",
            expected_intent="none",
            expected_tools=[],
            expected_gemini_called=True,
        ))
        assert errors == [], errors


class TestCalendarQuery:
    def test_calendar_query_with_tools(self, harness: HybridIntegrationHarness):
        errors = harness.verify_trace(GoldenTrace(
            user_text="bugün takvimde ne var",
            expected_route="calendar",
            expected_intent="query",
            expected_tools=["calendar.list_events"],
            expected_gemini_called=True,
        ))
        assert errors == [], errors

    def test_calendar_query_tool_executed(self, harness: HybridIntegrationHarness):
        result = harness.run_turn("bugün takvimde ne var")
        assert "calendar.list_events" in result["tool_results"]
        assert result["tool_results"]["calendar.list_events"]["ok"]


class TestCalendarCreate:
    def test_calendar_create_flow(self, harness: HybridIntegrationHarness):
        errors = harness.verify_trace(GoldenTrace(
            user_text="yarın 14'te toplantı oluştur",
            expected_route="calendar",
            expected_intent="create",
            expected_tools=["calendar.create_event"],
            expected_gemini_called=True,
        ))
        assert errors == [], errors


class TestLowConfidenceAskUser:
    def test_low_confidence_no_gemini(self, harness: HybridIntegrationHarness):
        errors = harness.verify_trace(GoldenTrace(
            user_text="ne demek istiyorsun",
            expected_route="smalltalk",
            expected_intent="none",
            expected_tools=[],
            expected_ask_user=True,
            expected_gemini_called=False,
        ))
        assert errors == [], errors


class TestGeminiFail:
    def test_gemini_fail_fallback_to_3b(self, harness: HybridIntegrationHarness):
        harness.gemini.set_fail(True)
        result = harness.run_turn("nasılsın")
        # Should fallback to 3B assistant_reply
        assert result["final_reply"] == "İyiyim efendim, teşekkür ederim!"
        assert not result["gemini_called"]


class TestSystemRoute:
    def test_time_query(self, harness: HybridIntegrationHarness):
        result = harness.run_turn("saat kaç")
        assert result["route"] == "system"
        assert "time.now" in result["tool_plan"]
        assert result["gemini_called"]


class TestHarnessMechanics:
    def test_vllm_call_count(self, harness: HybridIntegrationHarness):
        harness.run_turn("nasılsın")
        harness.run_turn("saat kaç")
        assert harness.vllm.call_count == 2

    def test_gemini_call_count(self, harness: HybridIntegrationHarness):
        harness.run_turn("nasılsın")
        assert harness.gemini.call_count == 1

    def test_tool_call_count(self, harness: HybridIntegrationHarness):
        harness.run_turn("bugün takvimde ne var")
        assert harness.tools.call_count == 1

    def test_unknown_input_defaults_smalltalk(self, harness: HybridIntegrationHarness):
        result = harness.run_turn("asdgjasdjgasd")
        assert result["route"] == "smalltalk"

    def test_golden_trace_error_detection(self, harness: HybridIntegrationHarness):
        """Verify that trace mismatch is detected."""
        errors = harness.verify_trace(GoldenTrace(
            user_text="nasılsın",
            expected_route="calendar",  # wrong!
            expected_intent="query",    # wrong!
        ))
        assert len(errors) >= 2
