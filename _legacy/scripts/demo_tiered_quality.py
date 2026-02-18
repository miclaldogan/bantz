#!/usr/bin/env python3
"""Demo: Tiered LLM behavior (Issue #206).

Goal
- Fast local model is used for routing + tool selection.
- Quality model (Gemini) is used only for writing-heavy requests (email drafts).
- Calendar/tool answers stay on the fast path (no Gemini escalation).

Run (mock-only, no external deps):
  python scripts/demo_tiered_quality.py --router-backend mock --finalizer mock --debug

Run (vLLM router + Gemini finalizer):
  export GEMINI_API_KEY='...'
  export BANTZ_VLLM_URL='http://localhost:8001'
  python scripts/demo_tiered_quality.py --router-backend vllm --finalizer gemini --debug

Notes
- Tiering is enabled by default in this demo via BANTZ_TIERED_MODE=1.
- Use --no-tiered to force the legacy "always finalizer" behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.llm.base import create_client
from bantz.llm.gemini_client import GeminiClient


def _mock_list_events(**_kwargs: Any) -> dict[str, Any]:
    return {
        "items": [
            {
                "summary": "Team Meeting",
                "start": {"dateTime": "2026-02-04T10:00:00+03:00"},
                "end": {"dateTime": "2026-02-04T10:30:00+03:00"},
            },
            {
                "summary": "Code Review",
                "start": {"dateTime": "2026-02-04T15:00:00+03:00"},
                "end": {"dateTime": "2026-02-04T16:00:00+03:00"},
            },
        ],
        "count": 2,
    }


def build_demo_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="calendar.list_events",
            description="List calendar events (demo)",
            parameters={
                "type": "object",
                "properties": {
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "window_hint": {"type": "string"},
                },
                "required": [],
            },
            function=_mock_list_events,
        )
    )
    return registry


class MockRouterLLM:
    """Mock planner/router that returns deterministic JSON."""

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:  # noqa: ARG002
        user_lines = [line[5:].strip() for line in prompt.split("\n") if line.startswith("USER:")]
        user_input = (user_lines[-1] if user_lines else "").lower()

        if "email" in user_input or "e-posta" in user_input or "mail" in user_input:
            return json.dumps(
                {
                    "route": "gmail",
                    "calendar_intent": "none",
                    "slots": {},
                    "confidence": 0.95,
                    "tool_plan": [],
                    "assistant_reply": "",
                    "ask_user": False,
                    "question": "",
                    "requires_confirmation": False,
                    "confirmation_prompt": "",
                    "memory_update": "Kullanıcı bir email taslağı istedi.",
                    "reasoning_summary": ["Yazım/üslup ağırlıklı istek"],
                },
                ensure_ascii=False,
            )

        if "bugün" in user_input or "takvim" in user_input or "plan" in user_input:
            return json.dumps(
                {
                    "route": "calendar",
                    "calendar_intent": "query",
                    "slots": {"window_hint": "today"},
                    "confidence": 0.9,
                    "tool_plan": ["calendar.list_events"],
                    "assistant_reply": "",
                    "ask_user": False,
                    "question": "",
                    "requires_confirmation": False,
                    "confirmation_prompt": "",
                    "memory_update": "Kullanıcı bugünün takvimini sordu.",
                    "reasoning_summary": ["Takvim sorgusu", "list_events çağrılacak"],
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "route": "unknown",
                "calendar_intent": "none",
                "slots": {},
                "confidence": 0.3,
                "tool_plan": [],
                "assistant_reply": "Efendim, bunu tam anlayamadım.",
                "ask_user": True,
                "question": "Ne yapmak istediğinizi biraz daha açar mısınız efendim?",
                "requires_confirmation": False,
                "confirmation_prompt": "",
                "memory_update": "Belirsiz istek.",
                "reasoning_summary": ["Belirsiz"],
            },
            ensure_ascii=False,
        )


class MockFinalizerLLM:
    """Mock quality finalizer for demo output."""

    def __init__(self) -> None:
        self.calls: int = 0

    @property
    def model_name(self) -> str:
        return "mock-quality"

    @property
    def backend_name(self) -> str:
        return "mock"

    def complete_text(self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:  # noqa: ARG002
        self.calls += 1
        return "[QUALITY] Efendim, işte nazik bir email taslağı:\n\nKonu: Gecikme için özür\n\nMerhaba Ahmet Bey,\n..."


def _get_gemini_api_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("BANTZ_GEMINI_API_KEY")
        or ""
    ).strip()


def run(loop: OrchestratorLoop, scenarios: list[str], debug: bool) -> int:
    state = OrchestratorState()
    for i, user_input in enumerate(scenarios, 1):
        print("=" * 80)
        print(f"[{i}/{len(scenarios)}] USER: {user_input}")
        output, state = loop.process_turn(user_input, state)

        tier = state.trace.get("response_tier")
        used = state.trace.get("finalizer_used")
        reason = state.trace.get("response_tier_reason")

        print(f"Route: {output.route} | Tool plan: {output.tool_plan} | Confidence: {output.confidence:.2f}")
        print(f"Tier: {tier} | Finalizer used: {used} | Reason: {reason}")
        print(f"ASSISTANT: {output.assistant_reply}")

        if debug:
            print("TRACE:")
            for k, v in state.trace.items():
                print(f"  {k}: {v}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo tiered quality behavior (Issue #206)")
    parser.add_argument("--router-backend", choices=["mock", "vllm"], default="mock")
    parser.add_argument("--router-model", default="Qwen/Qwen2.5-3B-Instruct-AWQ")
    parser.add_argument("--finalizer", choices=["mock", "gemini", "none"], default="mock")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-tiered", action="store_true", help="Disable tiering (legacy always-finalizer behavior)")

    args = parser.parse_args()

    # Enable tiering by default for this demo.
    if args.no_tiered:
        os.environ.pop("BANTZ_TIERED_MODE", None)
    else:
        os.environ["BANTZ_TIERED_MODE"] = "1"

    # Router (planner)
    if args.router_backend == "mock":
        router_llm: Any = MockRouterLLM()
        print("Router: mock (fast/local)")
    else:
        router_llm = create_client("vllm", model=args.router_model)
        print(f"Router: vLLM ({args.router_model})")

    orchestrator = JarvisLLMOrchestrator(llm=router_llm)

    # Finalizer (quality)
    finalizer_llm: Optional[Any] = None
    if args.finalizer == "none":
        finalizer_llm = None
        print("Finalizer: none")
    elif args.finalizer == "mock":
        finalizer_llm = MockFinalizerLLM()
        print("Finalizer: mock-quality")
    else:
        api_key = _get_gemini_api_key()
        if not api_key:
            print("ERROR: GEMINI_API_KEY not set")
            print("Set one of: GEMINI_API_KEY / GOOGLE_API_KEY / BANTZ_GEMINI_API_KEY")
            return 2
        model = os.environ.get("BANTZ_GEMINI_MODEL", "gemini-2.0-flash")
        finalizer_llm = GeminiClient(api_key=api_key, model=model)
        print(f"Finalizer: Gemini ({model})")

    tools = build_demo_tools()

    config = OrchestratorConfig(debug=args.debug)
    loop = OrchestratorLoop(orchestrator, tools, config=config, finalizer_llm=finalizer_llm)

    scenarios = [
        "bugün neler yapacağız bakalım",
        "Ahmet'e geciktiğim için özür dileyen nazik bir email taslağı yaz",
        "bugün tekrar takvimime bakar mısın?",
    ]

    return run(loop, scenarios, debug=args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
