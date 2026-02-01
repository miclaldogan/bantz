#!/usr/bin/env python3
"""Demo script for LLM Orchestrator (Issue #137).

Shows 5 scenarios with LLM-first architecture:
1. "hey bantz nasılsın" - Smalltalk
2. "bugün neler yapacağız bakalım" - Calendar query (today)
3. "saat 4 için bir toplantı oluştur" - Calendar create (requires confirmation)
4. "bu akşam neler yapacağız" - Calendar query (evening)
5. "bu hafta planımda önemli işler var mı?" - Calendar query (week)

Usage:
    python3 scripts/demo_orchestrator.py --backend vllm --debug
    python3 scripts/demo_orchestrator.py --backend mock  # Uses mock LLM (no server needed)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

# Allow running directly from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bantz.agent.tools import ToolRegistry, Tool
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.core.events import EventBus
from bantz.llm.base import create_client

logger = logging.getLogger(__name__)


# ========================================================================
# Mock Tools (for demo without calendar backend)
# ========================================================================

def mock_list_events(time_min: str = "", time_max: str = "", **kwargs) -> dict:
    """Mock calendar.list_events tool."""
    # Return fake events
    events = [
        {
            "id": "evt1",
            "summary": "Team Meeting",
            "start": {"dateTime": time_min or "2026-01-30T10:00:00+03:00"},
            "end": {"dateTime": time_min or "2026-01-30T11:00:00+03:00"},
        },
        {
            "id": "evt2",
            "summary": "Code Review",
            "start": {"dateTime": time_max or "2026-01-30T14:00:00+03:00"},
            "end": {"dateTime": time_max or "2026-01-30T15:00:00+03:00"},
        },
    ]
    return {"items": events, "count": len(events)}


def mock_create_event(title: str, start_time: str, end_time: str = "", **kwargs) -> dict:
    """Mock calendar.create_event tool."""
    event_id = f"evt_{title.lower().replace(' ', '_')}"
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time or start_time},
        "status": "confirmed",
    }


def build_mock_tool_registry() -> ToolRegistry:
    """Build mock tool registry for demo."""
    registry = ToolRegistry()
    
    # Calendar list_events
    list_tool = Tool(
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
    )
    registry.register(list_tool)
    
    # Calendar create_event
    create_tool = Tool(
        name="calendar.create_event",
        description="Create calendar event",
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
        requires_confirmation=True,
    )
    registry.register(create_tool)
    
    return registry


# ========================================================================
# Mock LLM Client (for --backend mock)
# ========================================================================

class MockLLMForDemo:
    """Mock LLM client with canned responses for 5 scenarios."""
    
    RESPONSES = {
        "nasılsın": {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "İyiyim efendim, teşekkür ederim. Size nasıl yardımcı olabilirim?",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı hal hatır sordu, karşılık verdim.",
            "reasoning_summary": ["Smalltalk girdi", "Samimi cevap verildi"],
        },
        "bugün": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "Bugünün programına bakıyorum efendim.",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı bugünün programını sordu.",
            "reasoning_summary": ["Takvim sorgusu", "Bugün window'u", "list_events çağrılacak"],
        },
        "toplantı": {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "16:00", "title": "toplantı"},
            "confidence": 0.6,
            "tool_plan": [],
            "assistant_reply": "",
            "ask_user": True,
            "question": "Toplantı ne kadar sürecek efendim? (örn: 30 dk, 1 saat)",
            "requires_confirmation": True,
            "confirmation_prompt": "Saat 16:00'da toplantı oluşturayım mı?",
            "memory_update": "Kullanıcı saat 4'e toplantı oluşturmak istedi, süre belirsiz.",
            "reasoning_summary": ["Saat belirsiz: 4 → 16:00 varsayıldı", "Süre eksik", "Önce netleştirme gerekli"],
        },
        "akşam": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "evening"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "Bu akşamın programına bakıyorum.",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı bu akşamın programını sordu.",
            "reasoning_summary": ["Evening window sorgusu", "list_events ile bakılacak"],
        },
        "hafta": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "week"},
            "confidence": 0.85,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "Bu haftanın programına bakıyorum.",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı bu haftanın programını sordu.",
            "reasoning_summary": ["Haftalık sorgu", "Tüm hafta için list_events"],
        },
    }
    
    def complete_text(self, *, prompt: str) -> str:
        """Return mock JSON based on user input."""
        # Extract LAST user input (not examples in SYSTEM_PROMPT)
        user_lines = []
        for line in prompt.split("\n"):
            if line.startswith("USER:"):
                user_lines.append(line[5:].strip())
        
        # Take the last USER line (actual input, not examples)
        user_input = user_lines[-1].lower() if user_lines else ""
        
        # Debug
        import sys
        print(f"[MockLLM] Found {len(user_lines)} USER lines", file=sys.stderr)
        print(f"[MockLLM] Extracted LAST user_input: '{user_input}'", file=sys.stderr)
        
        # Match scenario (check normalized input)
        for keyword, response in self.RESPONSES.items():
            if keyword in user_input:
                print(f"[MockLLM] Matched keyword: '{keyword}'", file=sys.stderr)
                return json.dumps(response, ensure_ascii=False)
        
        # Fallback
        print(f"[MockLLM] No match, using fallback", file=sys.stderr)
        return json.dumps({
            "route": "unknown",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.0,
            "tool_plan": [],
            "assistant_reply": "Anlamadım efendim.",
            "memory_update": "Belirsiz girdi.",
            "reasoning_summary": ["Bilinmeyen komut"],
        }, ensure_ascii=False)


# ========================================================================
# Demo Scenarios
# ========================================================================

def run_scenario(
    loop: OrchestratorLoop,
    state: OrchestratorState,
    scenario_num: int,
    user_input: str,
    debug: bool,
) -> OrchestratorState:
    """Run a single scenario and print results."""
    print(f"\n{'='*70}")
    print(f"SCENARIO {scenario_num}: {user_input}")
    print(f"{'='*70}")
    
    output, state = loop.process_turn(user_input, state)
    
    # Print orchestrator decision
    print(f"\n📋 ORCHESTRATOR DECISION:")
    print(f"  Route: {output.route}")
    print(f"  Intent: {output.calendar_intent}")
    print(f"  Confidence: {output.confidence:.2f}")
    print(f"  Tool Plan: {output.tool_plan}")
    
    if output.ask_user:
        print(f"  ❓ Ask User: {output.question}")
    
    if output.requires_confirmation:
        print(f"  ⚠️  Requires Confirmation: {output.confirmation_prompt}")
    
    # Print reasoning (debug mode)
    if debug and output.reasoning_summary:
        print(f"\n🧠 REASONING SUMMARY:")
        for i, reason in enumerate(output.reasoning_summary, 1):
            print(f"  {i}. {reason}")
    
    # Print memory update
    if output.memory_update:
        print(f"\n💾 MEMORY UPDATE: {output.memory_update}")
    
    # Print assistant reply
    if output.assistant_reply:
        print(f"\n🤖 ASSISTANT: {output.assistant_reply}")
    
    # Print trace metadata
    if debug:
        print(f"\n🔍 TRACE:")
        for key, value in state.trace.items():
            print(f"  {key}: {value}")
    
    return state


def main():
    parser = argparse.ArgumentParser(description="Demo LLM Orchestrator (Issue #137)")
    parser.add_argument(
        "--backend",
        choices=["vllm", "mock"],
        default="mock",
        help="LLM backend (default: mock for quick demo)",
    )
    parser.add_argument("--debug", action="store_true", help="Debug mode (verbose output)")
    parser.add_argument(
        "--model",
        default="Qwen/Qwen2.5-3B-Instruct",
        help="Model name (for vLLM)",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(message)s",
    )
    
    print("🚀 LLM Orchestrator Demo (Issue #137)")
    print(f"Backend: {args.backend}")
    print(f"Debug: {args.debug}")
    print()
    
    # Create LLM client
    if args.backend == "mock":
        llm = MockLLMForDemo()
        print("ℹ️  Using mock LLM (canned responses)")
    else:
        llm = create_client(args.backend, model=args.model)
        print(f"ℹ️  Using {args.backend} backend with model {args.model}")
    
    # Create orchestrator components
    orchestrator = JarvisLLMOrchestrator(llm=llm)
    tools = build_mock_tool_registry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=args.debug)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    state = OrchestratorState()
    
    # Run 5 scenarios
    scenarios = [
        "hey bantz nasılsın",
        "bugün neler yapacağız bakalım",
        "saat 4 için bir toplantı oluştur",
        "bu akşam neler yapacağız",
        "bu hafta planımda önemli işler var mı?",
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        state = run_scenario(loop, state, i, scenario, args.debug)
    
    print(f"\n{'='*70}")
    print("✅ Demo completed!")
    print(f"{'='*70}")
    print(f"\nFinal state:")
    print(f"  Rolling Summary: {state.rolling_summary}")
    print(f"  Conversation History: {len(state.conversation_history)} turns")
    print(f"  Tool Results: {len(state.last_tool_results)} stored")


if __name__ == "__main__":
    main()
