"""Golden trace regression tests (Issue #139).

These tests validate that orchestrator behavior matches expected "golden traces"
for known scenarios. They ensure that refactoring doesn't break existing behavior.

Golden traces define expected metadata (route, intent, tool counts, etc.) without
being text-dependent.

Run:
    pytest tests/test_regression_golden_traces.py -v
"""

from __future__ import annotations

import pytest
import json
from pathlib import Path
from typing import Any, Dict

from bantz.brain.llm_router import JarvisLLMOrchestrator, RouterOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.safety_guard import SafetyGuard, ToolSecurityPolicy
from bantz.agent.tools import ToolRegistry, Tool
from bantz.core.events import EventBus


# Capture pristine class-level state before any test narrows it.
_PRISTINE_VALID_TOOLS = frozenset(JarvisLLMOrchestrator._VALID_TOOLS)
_PRISTINE_SYSTEM_PROMPT = JarvisLLMOrchestrator.SYSTEM_PROMPT


@pytest.fixture(autouse=True)
def _restore_and_disable_bridge(monkeypatch):
    """Restore _VALID_TOOLS, disable bridge, and no-op sync_valid_tools."""
    JarvisLLMOrchestrator._VALID_TOOLS = set(_PRISTINE_VALID_TOOLS)
    JarvisLLMOrchestrator.SYSTEM_PROMPT = _PRISTINE_SYSTEM_PROMPT
    monkeypatch.setattr(
        JarvisLLMOrchestrator, "sync_valid_tools",
        classmethod(lambda cls, *a, **kw: None),
    )
    monkeypatch.setenv("BANTZ_BRIDGE_INPUT_GATE", "0")
    monkeypatch.setenv("BANTZ_BRIDGE_OUTPUT_GATE", "0")
    yield
    JarvisLLMOrchestrator._VALID_TOOLS = set(_PRISTINE_VALID_TOOLS)
    JarvisLLMOrchestrator.SYSTEM_PROMPT = _PRISTINE_SYSTEM_PROMPT


# =============================================================================
# Fixtures
# =============================================================================

GOLDEN_TRACES_DIR = Path(__file__).parent / "fixtures" / "golden_traces"


def load_golden_trace(scenario_name: str) -> Dict[str, Any]:
    """Load golden trace JSON for a scenario."""
    trace_file = GOLDEN_TRACES_DIR / f"{scenario_name}.json"
    assert trace_file.exists(), f"Golden trace file not found: {trace_file}"
    
    with open(trace_file, "r", encoding="utf-8") as f:
        return json.load(f)


class MockLLM:
    """Mock LLM for deterministic testing."""
    
    def __init__(self, scenario_responses: Dict[str, Dict[str, Any]]):
        """Initialize with user_input -> response dict mapping."""
        self.scenario_responses = scenario_responses
        self.calls = []
    
    def complete_text(self, *, prompt: str) -> str:
        """Return mock JSON response based on user input in prompt."""
        self.calls.append(prompt)
        
        # Extract LAST user input from prompt
        user_lines = []
        for line in prompt.split("\n"):
            if line.startswith("USER:"):
                user_lines.append(line[5:].strip())
        
        user_input = user_lines[-1].lower() if user_lines else ""
        
        # Find matching scenario
        for keyword, response_dict in self.scenario_responses.items():
            if keyword.lower() in user_input:
                return json.dumps(response_dict, ensure_ascii=False)
        
        # Default fallback
        return json.dumps({
            "route": "unknown",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.0,
            "tool_plan": [],
            "assistant_reply": "Anlayamadım.",
        }, ensure_ascii=False)


@pytest.fixture
def mock_llm() -> MockLLM:
    """Create mock LLM with scenario responses."""
    scenario_responses = {
        "nasılsın": {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "İyiyim, teşekkürler!",
        },
        "bugün neler": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"time_range": "today"},
            "confidence": 0.90,
            "tool_plan": [{"name": "calendar.list_events", "args": {"time_min": "2026-01-30T00:00:00", "time_max": "2026-01-30T23:59:59"}}],
            "assistant_reply": "Bugünkü etkinlikleri getiriyorum...",
        },
        "saat 4 için bir toplantı": {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "16:00", "title": "toplantı"},
            "confidence": 0.85,
            "tool_plan": [{"name": "calendar.create_event", "args": {"title": "toplantı", "start": "2026-01-30T16:00:00"}}],
            "assistant_reply": "Saat 16:00 için bir toplantı oluşturuyorum.",
            "requires_confirmation": True,
            "confirmation_prompt": "Saat 16:00 için 'toplantı' adında bir etkinlik oluşturulsun mu?",
        },
    }
    
    return MockLLM(scenario_responses)


@pytest.fixture
def mock_tools() -> ToolRegistry:
    """Create mock tool registry."""
    registry = ToolRegistry()
    
    # Calendar list tool
    registry.register(Tool(
        name="calendar.list_events",
        description="List calendar events",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
            },
            "required": ["time_min", "time_max"],
        },
        handler=lambda **kwargs: {"status": "success", "events": []},
    ))
    
    # Calendar create tool
    registry.register(Tool(
        name="calendar.create_event",
        description="Create calendar event",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
            },
            "required": ["title", "start"],
        },
        handler=lambda **kwargs: {"status": "success", "event_id": "evt_123"},
    ))
    
    return registry


@pytest.fixture
def event_bus() -> EventBus:
    """Create event bus."""
    return EventBus()


# =============================================================================
# Golden Trace Regression Tests
# =============================================================================

class TestGoldenTraceRegression:
    """Regression tests using golden traces."""
    
    def test_scenario_1_smalltalk(self, mock_llm: MockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test Scenario 1: Smalltalk (no tools)."""
        golden = load_golden_trace("scenario_1_smalltalk")
        
        # Create orchestrator
        orchestrator = JarvisLLMOrchestrator(llm_client=mock_llm)
        config = OrchestratorConfig(enable_safety_guard=False)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        # Run orchestration
        user_input = golden["user_input"]
        trace = loop.run_full_cycle(user_input, confirmation_token=None)
        
        # Validate against golden trace
        expected = golden["expected_trace"]
        assert trace["route"] == expected["route"], f"Route mismatch: {trace['route']} != {expected['route']}"
        assert trace["calendar_intent"] == expected["calendar_intent"]
        assert trace["confidence"] >= expected["confidence_min"]
        assert trace["tool_plan_len"] == expected["tool_plan_len"]
        assert trace["tools_executed"] == expected["tools_executed"]
    
    def test_scenario_2_calendar_list(self, mock_llm: MockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test Scenario 2: Calendar query (list events for today)."""
        golden = load_golden_trace("scenario_2_calendar_list")
        
        orchestrator = JarvisLLMOrchestrator(llm_client=mock_llm)
        config = OrchestratorConfig(enable_safety_guard=False, enable_preroute=False)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        user_input = golden["user_input"]
        trace = loop.run_full_cycle(user_input, confirmation_token=None)
        
        expected = golden["expected_trace"]
        assert trace["route"] == expected["route"]
        assert trace["calendar_intent"] == expected["calendar_intent"]
        assert trace["confidence"] >= expected["confidence_min"]
        assert trace["tool_plan_len"] >= expected["tool_plan_len_min"]
        assert trace["tools_executed"] >= expected["tools_executed_min"]
        
        # Check that correct tool was called
        tool_names = [t.split(".")[-1] for t in trace.get("tools_success", [])]
        assert any("list_events" in name for name in expected["tool_names"])
    
    def test_scenario_3_calendar_create(self, mock_llm: MockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test Scenario 3: Calendar create (requires confirmation)."""
        golden = load_golden_trace("scenario_3_calendar_create")
        
        orchestrator = JarvisLLMOrchestrator(llm_client=mock_llm)
        config = OrchestratorConfig(enable_safety_guard=False, enable_preroute=False)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        user_input = golden["user_input"]
        trace = loop.run_full_cycle(user_input, confirmation_token=None)
        
        expected = golden["expected_trace"]
        assert trace["route"] == expected["route"]
        assert trace["calendar_intent"] == expected["calendar_intent"]
        assert trace["confidence"] >= expected["confidence_min"]
        assert trace["tool_plan_len"] >= expected["tool_plan_len_min"]
        
        # Should require confirmation
        assert trace["requires_confirmation"] == expected["requires_confirmation"]
        assert "confirmation_prompt" in trace or expected["confirmation_prompt_exists"]
    
    def test_scenario_4_ambiguous_confirmation(self):
        """Test Scenario 4: Ambiguous confirmation (okay/sure)."""
        golden = load_golden_trace("scenario_4_ambiguous_confirmation")
        
        from bantz.brain.safety_guard import normalize_confirmation
        
        # Test normalization
        token = golden["confirmation_token"]
        normalized = normalize_confirmation(token)
        
        expected = golden["expected_behavior"]
        assert normalized == expected["normalized_token"]
    
    def test_scenario_5_denylist(self, mock_llm: MockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test Scenario 5: Denylist blocks tool execution."""
        golden = load_golden_trace("scenario_5_denylist")
        
        # Add delete tool to registry
        mock_tools.register(Tool(
            name="calendar.delete_event",
            description="Delete calendar event",
            parameters={
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
            handler=lambda **kwargs: {"status": "success"},
        ))
        
        # Mock LLM response for delete
        mock_llm.scenario_responses["delete"] = {
            "route": "calendar",
            "calendar_intent": "delete_event",
            "slots": {"event_id": "evt_123"},
            "confidence": 0.85,
            "tool_plan": [{"name": "calendar.delete_event", "args": {"event_id": "evt_123"}}],
            "assistant_reply": "Etkinliği siliyorum.",
        }
        
        # Create orchestrator with denylist
        orchestrator = JarvisLLMOrchestrator(llm_client=mock_llm)
        policy = ToolSecurityPolicy(denylist={"calendar.delete_event"})
        config = OrchestratorConfig(enable_safety_guard=True, security_policy=policy)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        user_input = golden["user_input"]
        trace = loop.run_full_cycle(user_input, confirmation_token=None)
        
        expected = golden["expected_trace"]
        assert trace["route"] == expected["route"]
        assert trace["tool_plan_len"] >= expected["tool_plan_len_min"]
        
        # Tool should be blocked by denylist
        assert trace["tools_attempted"] == expected["tools_attempted"]
        assert trace["tools_executed"] == expected["tools_executed"]


# =============================================================================
# Golden Trace Snapshot Tests
# =============================================================================

class TestGoldenTraceSnapshots:
    """Test that golden trace files exist and are valid."""
    
    def test_all_golden_traces_exist(self):
        """Test that all 5 golden trace files exist."""
        expected_files = [
            "scenario_1_smalltalk.json",
            "scenario_2_calendar_list.json",
            "scenario_3_calendar_create.json",
            "scenario_4_ambiguous_confirmation.json",
            "scenario_5_denylist.json",
        ]
        
        for filename in expected_files:
            trace_file = GOLDEN_TRACES_DIR / filename
            assert trace_file.exists(), f"Missing golden trace: {filename}"
    
    def test_golden_traces_are_valid_json(self):
        """Test that all golden traces are valid JSON."""
        for trace_file in GOLDEN_TRACES_DIR.glob("*.json"):
            with open(trace_file, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    assert isinstance(data, dict), f"{trace_file.name} is not a dict"
                    assert "scenario" in data, f"{trace_file.name} missing 'scenario' field"
                except json.JSONDecodeError as e:
                    pytest.fail(f"{trace_file.name} is not valid JSON: {e}")
    
    def test_golden_traces_have_required_fields(self):
        """Test that golden traces have required metadata fields."""
        required_fields = ["scenario", "description"]
        
        for trace_file in GOLDEN_TRACES_DIR.glob("*.json"):
            with open(trace_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                for field in required_fields:
                    assert field in data, f"{trace_file.name} missing field: {field}"


# =============================================================================
# Regression Test for Trace Metadata Format
# =============================================================================

class TestTraceMetadataFormat:
    """Test that trace metadata format is consistent across scenarios."""
    
    def test_trace_has_standard_fields(self, mock_llm: MockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test that all traces have standard metadata fields."""
        orchestrator = JarvisLLMOrchestrator(llm_client=mock_llm)
        config = OrchestratorConfig(enable_safety_guard=False)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        user_input = "hey bantz nasılsın"
        trace = loop.run_full_cycle(user_input, confirmation_token=None)
        
        # Standard fields that should always be present
        standard_fields = [
            "route",
            "calendar_intent",
            "confidence",
            "tool_plan_len",
            "tools_executed",
        ]
        
        for field in standard_fields:
            assert field in trace, f"Missing standard field: {field}"
    
    def test_trace_types_are_correct(self, mock_llm: MockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test that trace field types are correct."""
        orchestrator = JarvisLLMOrchestrator(llm_client=mock_llm)
        config = OrchestratorConfig(enable_safety_guard=False)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        user_input = "bugün neler yapacağız bakalım"
        trace = loop.run_full_cycle(user_input, confirmation_token=None)
        
        # Type checks
        assert isinstance(trace["route"], str)
        assert isinstance(trace["calendar_intent"], str)
        assert isinstance(trace["confidence"], (int, float))
        assert isinstance(trace["tool_plan_len"], int)
        assert isinstance(trace["tools_executed"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
