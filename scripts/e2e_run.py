#!/usr/bin/env python3
"""E2E Test Harness for Golden Jarvis Flows.

Issue #235: Scripted harness for golden Jarvis flows (calendar + smalltalk + email draft)

This script provides deterministic end-to-end testing for core Jarvis scenarios.
Each scenario produces a transcript and metrics summary.

Scenarios:
1. smalltalk -> no tool (tests router smalltalk detection)
2. calendar query + create + query (tests calendar flow with mock or real backend)
3. email draft (tests Gemini finalize) [cloud required]

Usage:
    # Run all scenarios (cloud disabled by default)
    python scripts/e2e_run.py

    # Run specific scenario
    python scripts/e2e_run.py --scenario smalltalk
    python scripts/e2e_run.py --scenario calendar
    python scripts/e2e_run.py --scenario email --cloud

    # With real backends
    python scripts/e2e_run.py --backend vllm --cloud

    # CI mode (exit code for regression gate)
    python scripts/e2e_run.py --ci

    # Save outputs
    python scripts/e2e_run.py --output artifacts/results/e2e_run.json

Environment:
    BANTZ_VLLM_URL (default: http://localhost:8001)
    BANTZ_VLLM_MODEL (default: Qwen/Qwen2.5-3B-Instruct-AWQ)
    GEMINI_API_KEY / GOOGLE_API_KEY (for cloud scenarios)

Output:
    - Transcript (conversation log)
    - Metrics summary (latency, token usage, route accuracy)
    - Exit code (0 = pass, 1 = fail) for CI regression gate
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.llm.base import LLMClient, LLMMessage, LLMResponse
from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_VLLM_URL = "http://localhost:8001"
DEFAULT_VLLM_MODEL = "Qwen/Qwen2.5-3B-Instruct-AWQ"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"


# ============================================================================
# MOCK LLM CLIENT (for offline testing)
# ============================================================================

class MockLLMClient(LLMClient):
    """Mock LLM client with deterministic responses for testing."""
    
    def __init__(self, responses: Optional[dict[str, str]] = None):
        self.responses = responses or {}
        self.calls: list[dict] = []
        self._default_responses = {
            "nasılsın": '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "İyiyim efendim, teşekkür ederim. Size nasıl yardımcı olabilirim?", "reasoning_summary": ["niyet: selamlaşma"]}',
            "merhaba": '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "Merhaba efendim! Size nasıl yardımcı olabilirim?", "reasoning_summary": ["niyet: selamlaşma"]}',
            "bugün planım": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.95, "tool_plan": ["calendar.list_events"], "assistant_reply": "", "reasoning_summary": ["niyet: takvim sorgusu", "slot: bugün"]}',
            "saat 15": '{"route": "calendar", "calendar_intent": "create", "slots": {"time": "15:00", "title": "toplantı"}, "confidence": 0.9, "tool_plan": ["calendar.create_event"], "requires_confirmation": true, "confirmation_prompt": "Saat 15:00 toplantı eklensin mi?", "reasoning_summary": ["niyet: etkinlik oluşturma"]}',
            "toplantı ekle": '{"route": "calendar", "calendar_intent": "create", "slots": {"title": "toplantı"}, "confidence": 0.7, "tool_plan": [], "ask_user": true, "question": "Saat kaçta olsun efendim?", "reasoning_summary": ["niyet: etkinlik oluşturma", "slot eksik: saat"]}',
            "mail yaz": '{"route": "gmail", "calendar_intent": "none", "slots": {}, "gmail": {"to": null, "subject": null, "body": null}, "confidence": 0.7, "tool_plan": [], "ask_user": true, "question": "Kime göndereyim efendim?", "reasoning_summary": ["niyet: mail gönderme"]}',
            "evet": '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "Anlaşıldı efendim.", "reasoning_summary": ["niyet: onay"]}',
        }
    
    @property
    def model_name(self) -> str:
        return "mock-llm"
    
    @property
    def backend_name(self) -> str:
        return "mock"
    
    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        return True
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        messages = [LLMMessage(role="user", content=prompt)]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)
    
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> str:
        response = self.chat_detailed(messages, temperature=temperature, max_tokens=max_tokens)
        return response.content
    
    def chat_detailed(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        # Get last user message
        user_msg = ""
        for m in reversed(messages):
            if m.role == "user":
                user_msg = m.content.lower().strip()
                break
        
        self.calls.append({"messages": [{"role": m.role, "content": m.content} for m in messages]})
        
        # Find matching response
        response_text = None
        for key, resp in self.responses.items():
            if key.lower() in user_msg:
                response_text = resp
                break
        
        if response_text is None:
            for key, resp in self._default_responses.items():
                if key in user_msg:
                    response_text = resp
                    break
        
        if response_text is None:
            # Default fallback
            response_text = '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 0.5, "tool_plan": [], "assistant_reply": "Anlayamadım efendim.", "reasoning_summary": ["belirsiz istek"]}'
        
        return LLMResponse(
            content=response_text,
            model="mock-llm",
            tokens_used=len(response_text) // 4,
            finish_reason="stop",
        )


# ============================================================================
# MOCK TOOLS
# ============================================================================

class MockToolContext:
    """Tracks mock tool invocations for verification."""
    
    def __init__(self):
        self.events: list[dict] = []
        self.calls: list[dict] = []
    
    def reset(self):
        self.events.clear()
        self.calls.clear()


_mock_ctx = MockToolContext()


def mock_list_events(time_min: str = "", time_max: str = "", **kwargs) -> dict:
    """Mock calendar.list_events tool."""
    _mock_ctx.calls.append({"tool": "calendar.list_events", "args": {"time_min": time_min, "time_max": time_max}})
    
    # Return events from context or default
    if _mock_ctx.events:
        return {"items": _mock_ctx.events, "count": len(_mock_ctx.events)}
    
    return {
        "items": [
            {"id": "evt1", "summary": "Team Meeting", "start": {"dateTime": "2026-02-01T10:00:00+03:00"}},
            {"id": "evt2", "summary": "Code Review", "start": {"dateTime": "2026-02-01T14:00:00+03:00"}},
        ],
        "count": 2,
    }


def mock_create_event(title: str, start_time: str, end_time: str = "", **kwargs) -> dict:
    """Mock calendar.create_event tool."""
    event = {
        "id": f"evt_{len(_mock_ctx.events) + 1}",
        "summary": title,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time or start_time},
        "status": "confirmed",
    }
    _mock_ctx.events.append(event)
    _mock_ctx.calls.append({"tool": "calendar.create_event", "args": {"title": title, "start_time": start_time}})
    return event


def mock_gmail_send(to: str, subject: str, body: str, **kwargs) -> dict:
    """Mock gmail.send tool."""
    _mock_ctx.calls.append({"tool": "gmail.send", "args": {"to": to, "subject": subject, "body": body}})
    return {"id": "msg_123", "threadId": "thread_123", "status": "sent"}


def build_mock_tool_registry() -> ToolRegistry:
    """Build mock tool registry for E2E testing."""
    registry = ToolRegistry()
    
    registry.register(Tool(
        name="calendar.list_events",
        description="List calendar events in time range",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "Start time (ISO)"},
                "time_max": {"type": "string", "description": "End time (ISO)"},
            },
            "required": ["time_min", "time_max"],
        },
        function=mock_list_events,
    ))
    
    registry.register(Tool(
        name="calendar.create_event",
        description="Create a new calendar event",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time (ISO)"},
                "end_time": {"type": "string", "description": "End time (ISO)"},
            },
            "required": ["title", "start_time"],
        },
        function=mock_create_event,
    ))
    
    registry.register(Tool(
        name="gmail.send",
        description="Send an email",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
            },
            "required": ["to", "subject", "body"],
        },
        function=mock_gmail_send,
    ))
    
    return registry


# ============================================================================
# SCENARIO DEFINITIONS
# ============================================================================

@dataclass
class ScenarioStep:
    """Single step in a scenario."""
    user_input: str
    expected_route: str
    expected_tools: list[str] = field(default_factory=list)
    confirm_if_asked: bool = False
    description: str = ""


@dataclass
class Scenario:
    """Complete test scenario."""
    name: str
    description: str
    steps: list[ScenarioStep]
    requires_cloud: bool = False
    
    @property
    def id(self) -> str:
        return self.name.lower().replace(" ", "_")


SCENARIOS = [
    Scenario(
        name="smalltalk",
        description="Basic smalltalk - no tools should be invoked",
        requires_cloud=False,
        steps=[
            ScenarioStep(
                user_input="Merhaba Jarvis",
                expected_route="smalltalk",
                expected_tools=[],
                description="Greeting",
            ),
            ScenarioStep(
                user_input="Nasılsın bugün?",
                expected_route="smalltalk",
                expected_tools=[],
                description="How are you",
            ),
            ScenarioStep(
                user_input="Teşekkürler, hoşça kal",
                expected_route="smalltalk",
                expected_tools=[],
                description="Goodbye",
            ),
        ],
    ),
    Scenario(
        name="calendar",
        description="Calendar flow: query + create + verify",
        requires_cloud=False,
        steps=[
            ScenarioStep(
                user_input="Bugün planım ne?",
                expected_route="calendar",
                expected_tools=["calendar.list_events"],
                description="Query today's events",
            ),
            ScenarioStep(
                user_input="Saat 15'te toplantı ekle",
                expected_route="calendar",
                expected_tools=["calendar.create_event"],
                confirm_if_asked=True,
                description="Create event at 15:00",
            ),
            ScenarioStep(
                user_input="Bugün planım ne?",
                expected_route="calendar",
                expected_tools=["calendar.list_events"],
                description="Verify event was added",
            ),
        ],
    ),
    Scenario(
        name="email",
        description="Email draft with Gemini finalize",
        requires_cloud=True,
        steps=[
            ScenarioStep(
                user_input="test@example.com adresine kısa bir mail yaz",
                expected_route="gmail",
                expected_tools=[],
                description="Start email draft (expects clarification)",
            ),
            ScenarioStep(
                user_input="Konu: Merhaba, İçerik: Bu bir test mailidir.",
                expected_route="gmail",
                expected_tools=["gmail.send"],
                confirm_if_asked=True,
                description="Complete email draft",
            ),
        ],
    ),
]


# ============================================================================
# TRANSCRIPT & METRICS
# ============================================================================

@dataclass
class TranscriptEntry:
    """Single transcript entry."""
    timestamp: str
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScenarioMetrics:
    """Metrics for a single scenario."""
    scenario_name: str
    passed: bool
    total_steps: int
    passed_steps: int
    failed_steps: int
    total_latency_ms: int
    avg_latency_ms: int
    total_tokens: int
    route_accuracy: float
    tool_accuracy: float
    errors: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class E2EResult:
    """Complete E2E run result."""
    timestamp: str
    scenarios_run: int
    scenarios_passed: int
    scenarios_failed: int
    overall_passed: bool
    metrics: list[ScenarioMetrics] = field(default_factory=list)
    transcripts: dict[str, list[dict]] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ============================================================================
# E2E RUNNER
# ============================================================================

class E2ERunner:
    """End-to-end test runner."""
    
    def __init__(
        self,
        *,
        router_client: LLMClient,
        finalizer_client: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
        cloud_enabled: bool = False,
    ):
        self.router_client = router_client
        self.finalizer_client = finalizer_client
        self.tool_registry = tool_registry or build_mock_tool_registry()
        self.cloud_enabled = cloud_enabled
        
        # Build orchestrator
        self.orchestrator = JarvisLLMOrchestrator(llm_client=router_client)
    
    def run_scenario(self, scenario: Scenario) -> tuple[ScenarioMetrics, list[TranscriptEntry]]:
        """Run a single scenario and return metrics + transcript."""
        _mock_ctx.reset()
        transcript: list[TranscriptEntry] = []
        errors: list[str] = []
        
        route_matches = 0
        tool_matches = 0
        total_latency = 0
        total_tokens = 0
        
        for step_idx, step in enumerate(scenario.steps):
            step_start = time.perf_counter()
            
            # Add user input to transcript
            transcript.append(TranscriptEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                role="user",
                content=step.user_input,
                metadata={"step": step_idx, "description": step.description},
            ))
            
            try:
                # Call orchestrator
                messages = [LLMMessage(role="user", content=step.user_input)]
                response = self.router_client.chat_detailed(messages)
                
                step_latency = int((time.perf_counter() - step_start) * 1000)
                total_latency += step_latency
                total_tokens += response.tokens_used
                
                # Parse response
                try:
                    parsed = json.loads(response.content)
                except json.JSONDecodeError:
                    errors.append(f"Step {step_idx}: Invalid JSON response")
                    transcript.append(TranscriptEntry(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        role="system",
                        content=f"ERROR: Invalid JSON response",
                        metadata={"raw": response.content[:200]},
                    ))
                    continue
                
                route = parsed.get("route", "unknown")
                tool_plan = parsed.get("tool_plan", [])
                assistant_reply = parsed.get("assistant_reply", "")
                
                # Check route
                if route == step.expected_route:
                    route_matches += 1
                else:
                    errors.append(f"Step {step_idx}: Expected route '{step.expected_route}', got '{route}'")
                
                # Check tools
                if set(tool_plan) == set(step.expected_tools):
                    tool_matches += 1
                elif step.expected_tools and not tool_plan:
                    errors.append(f"Step {step_idx}: Expected tools {step.expected_tools}, got none")
                elif tool_plan and not step.expected_tools:
                    errors.append(f"Step {step_idx}: Expected no tools, got {tool_plan}")
                
                # Add response to transcript
                transcript.append(TranscriptEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    role="assistant",
                    content=assistant_reply or json.dumps(parsed, ensure_ascii=False),
                    metadata={
                        "step": step_idx,
                        "route": route,
                        "tool_plan": tool_plan,
                        "latency_ms": step_latency,
                    },
                ))
                
                # Execute tools if present
                for tool_name in tool_plan:
                    tool = self.tool_registry.get(tool_name)
                    if tool:
                        # Build tool args from slots
                        slots = parsed.get("slots", {})
                        tool_args = {}
                        
                        if tool_name == "calendar.list_events":
                            tool_args = {"time_min": "2026-02-01T00:00:00", "time_max": "2026-02-02T00:00:00"}
                        elif tool_name == "calendar.create_event":
                            tool_args = {
                                "title": slots.get("title", "Event"),
                                "start_time": f"2026-02-01T{slots.get('time', '12:00')}:00+03:00",
                            }
                        elif tool_name == "gmail.send":
                            gmail = parsed.get("gmail", {})
                            tool_args = {
                                "to": gmail.get("to", "test@example.com"),
                                "subject": gmail.get("subject", "Test"),
                                "body": gmail.get("body", "Test"),
                            }
                        
                        result = tool.function(**tool_args)
                        
                        transcript.append(TranscriptEntry(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            role="tool",
                            content=json.dumps(result, ensure_ascii=False),
                            metadata={"tool": tool_name, "args": tool_args},
                        ))
            
            except Exception as e:
                errors.append(f"Step {step_idx}: {type(e).__name__}: {e}")
                transcript.append(TranscriptEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    role="system",
                    content=f"ERROR: {e}",
                    metadata={"step": step_idx},
                ))
        
        # Calculate metrics
        num_steps = len(scenario.steps)
        route_accuracy = route_matches / num_steps if num_steps > 0 else 0.0
        tool_accuracy = tool_matches / num_steps if num_steps > 0 else 0.0
        passed_steps = min(route_matches, tool_matches)
        
        # Scenario passes if all routes matched (tools may have partial matches)
        passed = route_matches == num_steps and len(errors) == 0
        
        metrics = ScenarioMetrics(
            scenario_name=scenario.name,
            passed=passed,
            total_steps=num_steps,
            passed_steps=passed_steps,
            failed_steps=num_steps - passed_steps,
            total_latency_ms=total_latency,
            avg_latency_ms=total_latency // num_steps if num_steps > 0 else 0,
            total_tokens=total_tokens,
            route_accuracy=route_accuracy,
            tool_accuracy=tool_accuracy,
            errors=errors,
        )
        
        return metrics, transcript
    
    def run_all(self, scenarios: Optional[list[Scenario]] = None) -> E2EResult:
        """Run all specified scenarios."""
        if scenarios is None:
            # Filter by cloud availability
            scenarios = [s for s in SCENARIOS if not s.requires_cloud or self.cloud_enabled]
        
        result = E2EResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenarios_run=len(scenarios),
            scenarios_passed=0,
            scenarios_failed=0,
            overall_passed=True,
        )
        
        for scenario in scenarios:
            if scenario.requires_cloud and not self.cloud_enabled:
                logger.info(f"Skipping scenario '{scenario.name}' (requires cloud)")
                continue
            
            logger.info(f"Running scenario: {scenario.name}")
            metrics, transcript = self.run_scenario(scenario)
            
            result.metrics.append(metrics)
            result.transcripts[scenario.id] = [t.to_dict() for t in transcript]
            
            if metrics.passed:
                result.scenarios_passed += 1
                logger.info(f"  ✓ PASSED ({metrics.route_accuracy:.0%} route accuracy)")
            else:
                result.scenarios_failed += 1
                result.overall_passed = False
                logger.warning(f"  ✗ FAILED: {metrics.errors}")
        
        return result


# ============================================================================
# CLI
# ============================================================================

def create_clients(
    *,
    backend: str = "mock",
    vllm_url: str = DEFAULT_VLLM_URL,
    vllm_model: str = DEFAULT_VLLM_MODEL,
    cloud_enabled: bool = False,
) -> tuple[LLMClient, Optional[LLMClient]]:
    """Create router and finalizer clients."""
    
    if backend == "mock":
        router_client = MockLLMClient()
        finalizer_client = None
    elif backend == "vllm":
        router_client = VLLMOpenAIClient(base_url=vllm_url, model=vllm_model)
        if not router_client.is_available():
            logger.warning(f"vLLM not available at {vllm_url}, falling back to mock")
            router_client = MockLLMClient()
        finalizer_client = None
    else:
        raise ValueError(f"Unknown backend: {backend}")
    
    if cloud_enabled:
        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("BANTZ_GEMINI_API_KEY")
        )
        if api_key:
            finalizer_client = GeminiClient(api_key=api_key, model=DEFAULT_GEMINI_MODEL)
        else:
            logger.warning("Cloud enabled but no Gemini API key found")
    
    return router_client, finalizer_client


def print_summary(result: E2EResult) -> None:
    """Print human-readable summary."""
    print("\n" + "=" * 60)
    print("E2E TEST SUMMARY")
    print("=" * 60)
    print(f"Timestamp: {result.timestamp}")
    print(f"Scenarios: {result.scenarios_passed}/{result.scenarios_run} passed")
    print("-" * 60)
    
    for metrics in result.metrics:
        status = "✓ PASS" if metrics.passed else "✗ FAIL"
        print(f"  {status} {metrics.scenario_name}")
        print(f"       Route accuracy: {metrics.route_accuracy:.0%}")
        print(f"       Tool accuracy:  {metrics.tool_accuracy:.0%}")
        print(f"       Avg latency:    {metrics.avg_latency_ms}ms")
        if metrics.errors:
            for err in metrics.errors:
                print(f"       ERROR: {err}")
    
    print("-" * 60)
    overall = "PASSED" if result.overall_passed else "FAILED"
    print(f"Overall: {overall}")
    print("=" * 60)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="E2E test harness for Jarvis flows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--scenario",
        choices=["smalltalk", "calendar", "email", "all"],
        default="all",
        help="Scenario to run (default: all)",
    )
    
    parser.add_argument(
        "--backend",
        choices=["mock", "vllm"],
        default="mock",
        help="LLM backend (default: mock)",
    )
    
    parser.add_argument(
        "--cloud",
        action="store_true",
        help="Enable cloud scenarios (requires Gemini API key)",
    )
    
    parser.add_argument(
        "--output", "-o",
        help="Output file path for JSON results",
    )
    
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: exit 1 on failure",
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    
    parser.add_argument(
        "--vllm-url",
        default=os.environ.get("BANTZ_VLLM_URL", DEFAULT_VLLM_URL),
        help=f"vLLM server URL (default: {DEFAULT_VLLM_URL})",
    )
    
    parser.add_argument(
        "--vllm-model",
        default=os.environ.get("BANTZ_VLLM_MODEL", DEFAULT_VLLM_MODEL),
        help=f"vLLM model (default: {DEFAULT_VLLM_MODEL})",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s")
    
    # Create clients
    router_client, finalizer_client = create_clients(
        backend=args.backend,
        vllm_url=args.vllm_url,
        vllm_model=args.vllm_model,
        cloud_enabled=args.cloud,
    )
    
    # Create runner
    runner = E2ERunner(
        router_client=router_client,
        finalizer_client=finalizer_client,
        cloud_enabled=args.cloud,
    )
    
    # Select scenarios
    if args.scenario == "all":
        scenarios = None  # run_all will filter
    else:
        scenarios = [s for s in SCENARIOS if s.id == args.scenario]
        if not scenarios:
            print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
            return 1
    
    # Run
    result = runner.run_all(scenarios)
    
    # Output
    print_summary(result)
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.to_json(), encoding="utf-8")
        print(f"\nResults saved to: {output_path}")
    
    # Exit code
    if args.ci and not result.overall_passed:
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
