"""Tests for E2E Test Harness.

Issue #235: E2E Scripted harness for golden Jarvis flows

Test categories:
1. MockLLMClient behavior
2. Scenario definitions
3. E2ERunner execution
4. Metrics calculation
5. Transcript generation
6. CI mode and exit codes
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

# Add scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from e2e_run import (
    E2EResult,
    E2ERunner,
    MockLLMClient,
    MockToolContext,
    Scenario,
    ScenarioMetrics,
    ScenarioStep,
    TranscriptEntry,
    SCENARIOS,
    _mock_ctx,
    build_mock_tool_registry,
    mock_create_event,
    mock_list_events,
)
from bantz.llm.base import LLMMessage


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_client() -> MockLLMClient:
    """Create a MockLLMClient instance."""
    return MockLLMClient()


@pytest.fixture
def tool_registry():
    """Create mock tool registry."""
    return build_mock_tool_registry()


@pytest.fixture(autouse=True)
def reset_mock_context():
    """Reset mock context before each test."""
    _mock_ctx.reset()
    yield
    _mock_ctx.reset()


# ============================================================================
# MOCK LLM CLIENT TESTS
# ============================================================================

class TestMockLLMClient:
    """Test MockLLMClient behavior."""
    
    def test_is_available(self, mock_client):
        """Test that mock client is always available."""
        assert mock_client.is_available() is True
        assert mock_client.is_available(timeout_seconds=0.1) is True
    
    def test_chat_returns_string(self, mock_client):
        """Test that chat returns a string."""
        messages = [LLMMessage(role="user", content="merhaba")]
        response = mock_client.chat(messages)
        
        assert isinstance(response, str)
        assert len(response) > 0
    
    def test_chat_detailed_returns_response(self, mock_client):
        """Test that chat_detailed returns LLMResponse."""
        messages = [LLMMessage(role="user", content="merhaba")]
        response = mock_client.chat_detailed(messages)
        
        assert response.content is not None
        assert response.model == "mock-llm"
        assert response.finish_reason == "stop"
    
    def test_smalltalk_response(self, mock_client):
        """Test smalltalk detection."""
        messages = [LLMMessage(role="user", content="Nasılsın?")]
        response = mock_client.chat(messages)
        
        parsed = json.loads(response)
        assert parsed["route"] == "smalltalk"
        assert parsed["tool_plan"] == []
        assert "assistant_reply" in parsed
    
    def test_merhaba_response(self, mock_client):
        """Test greeting response."""
        messages = [LLMMessage(role="user", content="Merhaba Jarvis")]
        response = mock_client.chat(messages)
        
        parsed = json.loads(response)
        assert parsed["route"] == "smalltalk"
        assert "Merhaba" in parsed.get("assistant_reply", "")
    
    def test_calendar_query_response(self, mock_client):
        """Test calendar query detection."""
        messages = [LLMMessage(role="user", content="Bugün planım ne?")]
        response = mock_client.chat(messages)
        
        parsed = json.loads(response)
        assert parsed["route"] == "calendar"
        assert "calendar.list_events" in parsed.get("tool_plan", [])
    
    def test_calendar_create_response(self, mock_client):
        """Test calendar create detection."""
        messages = [LLMMessage(role="user", content="Saat 15'te toplantı ekle")]
        response = mock_client.chat(messages)
        
        parsed = json.loads(response)
        assert parsed["route"] == "calendar"
        assert parsed.get("requires_confirmation") is True
    
    def test_custom_responses(self):
        """Test custom response injection."""
        custom = {"test": '{"route": "custom", "tool_plan": ["custom.tool"]}'}
        client = MockLLMClient(responses=custom)
        
        messages = [LLMMessage(role="user", content="test input")]
        response = client.chat(messages)
        
        parsed = json.loads(response)
        assert parsed["route"] == "custom"
        assert parsed["tool_plan"] == ["custom.tool"]
    
    def test_unknown_input_fallback(self, mock_client):
        """Test fallback for unknown inputs."""
        messages = [LLMMessage(role="user", content="xyz123abc456")]
        response = mock_client.chat(messages)
        
        parsed = json.loads(response)
        assert "route" in parsed
        # Should have low confidence or fallback
        assert parsed.get("confidence", 1.0) <= 0.6
    
    def test_calls_tracked(self, mock_client):
        """Test that calls are tracked."""
        messages = [LLMMessage(role="user", content="test")]
        mock_client.chat(messages)
        mock_client.chat(messages)
        
        assert len(mock_client.calls) == 2


# ============================================================================
# MOCK TOOLS TESTS
# ============================================================================

class TestMockTools:
    """Test mock tool implementations."""
    
    def test_mock_list_events_default(self):
        """Test mock_list_events returns default events."""
        result = mock_list_events()
        
        assert "items" in result
        assert len(result["items"]) == 2
        assert result["count"] == 2
    
    def test_mock_list_events_tracks_calls(self):
        """Test that list_events tracks calls."""
        _mock_ctx.reset()
        mock_list_events(time_min="2026-01-01", time_max="2026-01-02")
        
        assert len(_mock_ctx.calls) == 1
        assert _mock_ctx.calls[0]["tool"] == "calendar.list_events"
    
    def test_mock_create_event(self):
        """Test mock_create_event creates and stores event."""
        _mock_ctx.reset()
        result = mock_create_event(title="Test Event", start_time="2026-01-01T10:00:00")
        
        assert result["summary"] == "Test Event"
        assert result["status"] == "confirmed"
        assert len(_mock_ctx.events) == 1
    
    def test_mock_create_event_increments_id(self):
        """Test that event IDs increment."""
        _mock_ctx.reset()
        r1 = mock_create_event(title="Event 1", start_time="2026-01-01T10:00:00")
        r2 = mock_create_event(title="Event 2", start_time="2026-01-01T11:00:00")
        
        assert r1["id"] == "evt_1"
        assert r2["id"] == "evt_2"
        assert len(_mock_ctx.events) == 2
    
    def test_mock_list_events_returns_created(self):
        """Test that list_events returns created events."""
        _mock_ctx.reset()
        mock_create_event(title="My Event", start_time="2026-01-01T10:00:00")
        
        result = mock_list_events()
        assert len(result["items"]) == 1
        assert result["items"][0]["summary"] == "My Event"
    
    def test_build_mock_tool_registry(self, tool_registry):
        """Test that tool registry is built correctly."""
        assert tool_registry.get("calendar.list_events") is not None
        assert tool_registry.get("calendar.create_event") is not None
        assert tool_registry.get("gmail.send") is not None


# ============================================================================
# SCENARIO DEFINITION TESTS
# ============================================================================

class TestScenarios:
    """Test scenario definitions."""
    
    def test_scenarios_exist(self):
        """Test that default scenarios are defined."""
        assert len(SCENARIOS) >= 3
    
    def test_smalltalk_scenario(self):
        """Test smalltalk scenario structure."""
        smalltalk = next((s for s in SCENARIOS if s.id == "smalltalk"), None)
        assert smalltalk is not None
        assert smalltalk.requires_cloud is False
        assert len(smalltalk.steps) >= 2
        
        for step in smalltalk.steps:
            assert step.expected_route == "smalltalk"
            assert step.expected_tools == []
    
    def test_calendar_scenario(self):
        """Test calendar scenario structure."""
        calendar = next((s for s in SCENARIOS if s.id == "calendar"), None)
        assert calendar is not None
        assert calendar.requires_cloud is False
        assert len(calendar.steps) >= 2
        
        # Should have at least one list_events
        has_list = any("calendar.list_events" in s.expected_tools for s in calendar.steps)
        assert has_list
    
    def test_email_scenario(self):
        """Test email scenario structure."""
        email = next((s for s in SCENARIOS if s.id == "email"), None)
        assert email is not None
        assert email.requires_cloud is True
    
    def test_scenario_id_generation(self):
        """Test scenario ID generation."""
        s = Scenario(name="My Test Scenario", description="Test", steps=[])
        assert s.id == "my_test_scenario"
    
    def test_scenario_step_defaults(self):
        """Test ScenarioStep defaults."""
        step = ScenarioStep(user_input="test", expected_route="smalltalk")
        
        assert step.expected_tools == []
        assert step.confirm_if_asked is False
        assert step.description == ""


# ============================================================================
# E2E RUNNER TESTS
# ============================================================================

class TestE2ERunner:
    """Test E2ERunner execution."""
    
    def test_runner_creation(self, mock_client, tool_registry):
        """Test runner can be created."""
        runner = E2ERunner(
            router_client=mock_client,
            tool_registry=tool_registry,
        )
        
        assert runner.router_client is mock_client
        assert runner.cloud_enabled is False
    
    def test_run_smalltalk_scenario(self, mock_client, tool_registry):
        """Test running smalltalk scenario."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        scenario = Scenario(
            name="test_smalltalk",
            description="Test smalltalk",
            steps=[
                ScenarioStep(user_input="Merhaba", expected_route="smalltalk"),
            ],
        )
        
        metrics, transcript = runner.run_scenario(scenario)
        
        assert metrics.scenario_name == "test_smalltalk"
        assert metrics.total_steps == 1
        assert metrics.route_accuracy == 1.0
        assert len(transcript) >= 2  # user + assistant
    
    def test_run_calendar_query_scenario(self, mock_client, tool_registry):
        """Test running calendar query scenario."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        scenario = Scenario(
            name="test_calendar",
            description="Test calendar query",
            steps=[
                ScenarioStep(
                    user_input="Bugün planım ne?",
                    expected_route="calendar",
                    expected_tools=["calendar.list_events"],
                ),
            ],
        )
        
        metrics, transcript = runner.run_scenario(scenario)
        
        assert metrics.route_accuracy == 1.0
        # Should have tool invocation in transcript
        tool_entries = [t for t in transcript if t.role == "tool"]
        assert len(tool_entries) >= 1
    
    def test_run_all_scenarios(self, mock_client, tool_registry):
        """Test running all non-cloud scenarios."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry, cloud_enabled=False)
        
        result = runner.run_all()
        
        assert result.scenarios_run >= 2  # At least smalltalk + calendar
        assert result.scenarios_run == len(result.metrics)
        assert len(result.transcripts) >= 2
    
    def test_cloud_scenario_skipped(self, mock_client, tool_registry):
        """Test that cloud scenarios are skipped when cloud disabled."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry, cloud_enabled=False)
        
        result = runner.run_all()
        
        # Email scenario should not be in results
        scenario_names = [m.scenario_name for m in result.metrics]
        assert "email" not in scenario_names
    
    def test_metrics_calculation(self, mock_client, tool_registry):
        """Test metrics are calculated correctly."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        scenario = Scenario(
            name="test_metrics",
            description="Test metrics",
            steps=[
                ScenarioStep(user_input="Merhaba", expected_route="smalltalk"),
                ScenarioStep(user_input="Nasılsın", expected_route="smalltalk"),
            ],
        )
        
        metrics, _ = runner.run_scenario(scenario)
        
        assert metrics.total_steps == 2
        assert metrics.route_accuracy == 1.0
        assert metrics.total_latency_ms >= 0
        assert metrics.avg_latency_ms >= 0


# ============================================================================
# TRANSCRIPT TESTS
# ============================================================================

class TestTranscript:
    """Test transcript generation."""
    
    def test_transcript_entry_creation(self):
        """Test TranscriptEntry creation."""
        entry = TranscriptEntry(
            timestamp="2026-01-01T10:00:00Z",
            role="user",
            content="Test message",
            metadata={"step": 0},
        )
        
        assert entry.role == "user"
        assert entry.content == "Test message"
        assert entry.metadata["step"] == 0
    
    def test_transcript_entry_to_dict(self):
        """Test TranscriptEntry serialization."""
        entry = TranscriptEntry(
            timestamp="2026-01-01T10:00:00Z",
            role="assistant",
            content="Response",
        )
        
        data = entry.to_dict()
        
        assert data["role"] == "assistant"
        assert data["content"] == "Response"
        assert "metadata" in data
    
    def test_transcript_contains_user_inputs(self, mock_client, tool_registry):
        """Test that transcript contains user inputs."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        scenario = Scenario(
            name="test",
            description="Test",
            steps=[
                ScenarioStep(user_input="Test input 1", expected_route="smalltalk"),
                ScenarioStep(user_input="Test input 2", expected_route="smalltalk"),
            ],
        )
        
        _, transcript = runner.run_scenario(scenario)
        
        user_entries = [t for t in transcript if t.role == "user"]
        assert len(user_entries) == 2
        assert user_entries[0].content == "Test input 1"
        assert user_entries[1].content == "Test input 2"
    
    def test_transcript_contains_assistant_responses(self, mock_client, tool_registry):
        """Test that transcript contains assistant responses."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        scenario = Scenario(
            name="test",
            description="Test",
            steps=[
                ScenarioStep(user_input="Merhaba", expected_route="smalltalk"),
            ],
        )
        
        _, transcript = runner.run_scenario(scenario)
        
        assistant_entries = [t for t in transcript if t.role == "assistant"]
        assert len(assistant_entries) >= 1


# ============================================================================
# METRICS TESTS
# ============================================================================

class TestMetrics:
    """Test metrics calculation."""
    
    def test_scenario_metrics_creation(self):
        """Test ScenarioMetrics creation."""
        metrics = ScenarioMetrics(
            scenario_name="test",
            passed=True,
            total_steps=5,
            passed_steps=5,
            failed_steps=0,
            total_latency_ms=1000,
            avg_latency_ms=200,
            total_tokens=500,
            route_accuracy=1.0,
            tool_accuracy=1.0,
        )
        
        assert metrics.passed is True
        assert metrics.total_steps == 5
    
    def test_scenario_metrics_to_dict(self):
        """Test ScenarioMetrics serialization."""
        metrics = ScenarioMetrics(
            scenario_name="test",
            passed=True,
            total_steps=3,
            passed_steps=3,
            failed_steps=0,
            total_latency_ms=600,
            avg_latency_ms=200,
            total_tokens=300,
            route_accuracy=1.0,
            tool_accuracy=0.67,
            errors=["error1"],
        )
        
        data = metrics.to_dict()
        
        assert data["scenario_name"] == "test"
        assert data["passed"] is True
        assert data["errors"] == ["error1"]
    
    def test_e2e_result_creation(self):
        """Test E2EResult creation."""
        result = E2EResult(
            timestamp="2026-01-01T10:00:00Z",
            scenarios_run=3,
            scenarios_passed=2,
            scenarios_failed=1,
            overall_passed=False,
        )
        
        assert result.scenarios_run == 3
        assert result.overall_passed is False
    
    def test_e2e_result_to_json(self):
        """Test E2EResult JSON serialization."""
        result = E2EResult(
            timestamp="2026-01-01T10:00:00Z",
            scenarios_run=2,
            scenarios_passed=2,
            scenarios_failed=0,
            overall_passed=True,
        )
        
        json_str = result.to_json()
        data = json.loads(json_str)
        
        assert data["scenarios_run"] == 2
        assert data["overall_passed"] is True


# ============================================================================
# ROUTE ACCURACY TESTS
# ============================================================================

class TestRouteAccuracy:
    """Test route detection accuracy."""
    
    def test_correct_route_detection(self, mock_client, tool_registry):
        """Test that correct routes are detected."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        scenario = Scenario(
            name="test_routes",
            description="Test route detection",
            steps=[
                ScenarioStep(user_input="Merhaba", expected_route="smalltalk", expected_tools=[]),
                ScenarioStep(user_input="Bugün planım ne?", expected_route="calendar", expected_tools=["calendar.list_events"]),
            ],
        )
        
        metrics, _ = runner.run_scenario(scenario)
        
        assert metrics.route_accuracy == 1.0
        assert metrics.passed is True
    
    def test_incorrect_route_detected(self, mock_client, tool_registry):
        """Test that incorrect routes are detected."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        # Expect calendar but mock will return smalltalk for greeting
        scenario = Scenario(
            name="test_mismatch",
            description="Test route mismatch",
            steps=[
                ScenarioStep(user_input="Merhaba", expected_route="calendar"),  # Wrong expectation
            ],
        )
        
        metrics, _ = runner.run_scenario(scenario)
        
        assert metrics.route_accuracy == 0.0
        assert len(metrics.errors) > 0


# ============================================================================
# CI MODE TESTS
# ============================================================================

class TestCIMode:
    """Test CI mode behavior."""
    
    def test_ci_mode_pass_exit_code(self, mock_client, tool_registry):
        """Test that passing scenarios return exit code 0."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        result = runner.run_all([
            Scenario(
                name="pass_test",
                description="Test",
                steps=[ScenarioStep(user_input="Merhaba", expected_route="smalltalk")],
            ),
        ])
        
        assert result.overall_passed is True
    
    def test_ci_mode_fail_exit_code(self, mock_client, tool_registry):
        """Test that failing scenarios return exit code 1."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        result = runner.run_all([
            Scenario(
                name="fail_test",
                description="Test",
                steps=[ScenarioStep(user_input="Merhaba", expected_route="calendar")],  # Will fail
            ),
        ])
        
        assert result.overall_passed is False


# ============================================================================
# OUTPUT TESTS
# ============================================================================

class TestOutput:
    """Test output generation."""
    
    def test_json_output_structure(self, mock_client, tool_registry):
        """Test that JSON output has correct structure."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        result = runner.run_all([
            Scenario(
                name="test",
                description="Test",
                steps=[ScenarioStep(user_input="Merhaba", expected_route="smalltalk")],
            ),
        ])
        
        json_str = result.to_json()
        data = json.loads(json_str)
        
        assert "timestamp" in data
        assert "scenarios_run" in data
        assert "scenarios_passed" in data
        assert "scenarios_failed" in data
        assert "overall_passed" in data
        assert "metrics" in data
        assert "transcripts" in data
    
    def test_output_file_creation(self, mock_client, tool_registry, tmp_path):
        """Test that output file is created correctly."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        result = runner.run_all([
            Scenario(
                name="test",
                description="Test",
                steps=[ScenarioStep(user_input="Merhaba", expected_route="smalltalk")],
            ),
        ])
        
        output_path = tmp_path / "result.json"
        output_path.write_text(result.to_json(), encoding="utf-8")
        
        assert output_path.exists()
        
        # Verify can be read back
        loaded = json.loads(output_path.read_text())
        assert loaded["scenarios_run"] == 1


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for complete E2E flows."""
    
    def test_full_smalltalk_flow(self, mock_client, tool_registry):
        """Test complete smalltalk scenario flow."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        smalltalk = next((s for s in SCENARIOS if s.id == "smalltalk"), None)
        assert smalltalk is not None
        
        metrics, transcript = runner.run_scenario(smalltalk)
        
        # Smalltalk should pass with mock client
        assert metrics.route_accuracy >= 0.8
        assert len(transcript) > 0
    
    def test_full_calendar_flow(self, mock_client, tool_registry):
        """Test complete calendar scenario flow."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        calendar = next((s for s in SCENARIOS if s.id == "calendar"), None)
        assert calendar is not None
        
        metrics, transcript = runner.run_scenario(calendar)
        
        # Calendar should have tool invocations
        tool_entries = [t for t in transcript if t.role == "tool"]
        assert len(tool_entries) >= 1
    
    def test_acceptance_criteria_ci_pass(self, mock_client, tool_registry):
        """Test acceptance criteria: CI mode with cloud off passes scenario 1+2."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry, cloud_enabled=False)
        
        # Run non-cloud scenarios
        result = runner.run_all()
        
        # At least smalltalk and calendar should run
        assert result.scenarios_run >= 2
        
        # Verify transcripts exist for each
        for metrics in result.metrics:
            assert metrics.scenario_name in result.transcripts
    
    def test_transcript_output_format(self, mock_client, tool_registry):
        """Test that transcript follows expected format."""
        runner = E2ERunner(router_client=mock_client, tool_registry=tool_registry)
        
        result = runner.run_all([
            Scenario(
                name="format_test",
                description="Test format",
                steps=[
                    ScenarioStep(user_input="Merhaba", expected_route="smalltalk"),
                    ScenarioStep(user_input="Bugün planım ne?", expected_route="calendar", expected_tools=["calendar.list_events"]),
                ],
            ),
        ])
        
        transcript = result.transcripts.get("format_test", [])
        assert len(transcript) >= 4  # 2 user + 2 assistant (+ maybe tools)
        
        # Check structure
        for entry in transcript:
            assert "timestamp" in entry
            assert "role" in entry
            assert "content" in entry
            assert entry["role"] in ["user", "assistant", "system", "tool"]
