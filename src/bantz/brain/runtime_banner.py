"""Runtime banner + turn trace (Issue #520).

Boot banner showing brain configuration and per-turn debug trace.

Boot banner::

    ╭──────────────────────────────────────╮
    │  🧠 BANTZ Brain v2.0                │
    │  Mode:      orchestrator             │
    │  Router:    Qwen2.5-3B @ vLLM:8001  │
    │  Finalizer: gemini-2.0-flash ✓      │
    │  Memory:    lite (10 turns, 1000tok) │
    │  Prompt:    tiered (CORE+DETAIL)     │
    │  Context:   2048 tokens              │
    ╰──────────────────────────────────────╯

Turn trace (debug mode)::

    [turn] route=calendar intent=query conf=0.92 prompt=1340tok
           finalizer=gemini tools=[calendar.list_events] elapsed=1.2s
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "RuntimeBanner",
    "TurnTrace",
    "TurnTraceRecord",
    "format_banner",
    "format_turn_trace",
]


# ── Banner ────────────────────────────────────────────────────


@dataclass
class RuntimeBanner:
    """Structured brain configuration for boot banner."""

    mode: str = "orchestrator"
    active_path: str = "brain"  # "brain" or "legacy"
    router_model: str = ""
    router_url: str = "http://localhost:8001"
    finalizer_model: str = ""
    finalizer_type: str = "3B (local)"  # "Gemini" or "3B (local)"
    finalizer_ok: bool = False
    memory_turns: int = 10
    memory_tokens: int = 1000
    prompt_strategy: str = "tiered (CORE+DETAIL)"
    context_window: int = 2048
    tools_registered: int = 0
    forced_tier: str = ""  # e.g. "quality" or "fast"
    debug: bool = False

    @classmethod
    def from_runtime(cls, runtime: Any) -> "RuntimeBanner":
        """Build banner from BantzRuntime."""
        finalizer_type = "Gemini" if runtime.finalizer_is_gemini else "3B (local)"
        finalizer_model = (
            runtime.gemini_model if runtime.finalizer_is_gemini else runtime.router_model
        )

        # Extract config from loop if available
        memory_turns = 10
        memory_tokens = 1000
        tools_count = 0
        debug = False

        if hasattr(runtime, "loop") and runtime.loop is not None:
            loop = runtime.loop
            if hasattr(loop, "config"):
                cfg = loop.config
                memory_turns = getattr(cfg, "memory_max_turns", 10)
                memory_tokens = getattr(cfg, "memory_max_tokens", 1000)
                debug = getattr(cfg, "debug", False)
            if hasattr(loop, "_tools"):
                tools_count = len(getattr(loop._tools, "_tools", {}))

        # Try to get tools count from runtime.tools
        if tools_count == 0 and hasattr(runtime, "tools"):
            tools_obj = runtime.tools
            if hasattr(tools_obj, "_tools"):
                tools_count = len(tools_obj._tools)

        # Extract vLLM URL from router_client
        router_url = "http://localhost:8001"
        if hasattr(runtime, "router_client"):
            client = runtime.router_client
            if hasattr(client, "base_url"):
                router_url = str(client.base_url)

        # Forced tier override
        forced_tier = os.getenv("BANTZ_FORCE_FINALIZER_TIER", "").strip().lower()

        return cls(
            mode="orchestrator",
            active_path="brain",
            router_model=runtime.router_model,
            router_url=router_url,
            finalizer_model=finalizer_model,
            finalizer_type=finalizer_type,
            finalizer_ok=runtime.finalizer_is_gemini,
            memory_turns=memory_turns,
            memory_tokens=memory_tokens,
            tools_registered=tools_count,
            forced_tier=forced_tier,
            debug=debug,
        )


def format_banner(b: RuntimeBanner) -> str:
    """Format a pretty box banner for terminal output."""
    ok_mark = "✓" if b.finalizer_ok else "✗"
    router_short = b.router_model.split("/")[-1] if "/" in b.router_model else b.router_model
    path_label = "brain (default)" if b.active_path == "brain" else "legacy"

    lines = [
        f"  🧠 BANTZ Brain v2.0",
        f"  Path:      {path_label}",
        f"  Mode:      {b.mode}",
        f"  Router:    {router_short}",
        f"  vLLM:      {b.router_url}",
        f"  Finalizer: {b.finalizer_model} {ok_mark} ({b.finalizer_type})",
        f"  Memory:    lite ({b.memory_turns} turns, {b.memory_tokens}tok)",
        f"  Prompt:    {b.prompt_strategy}",
        f"  Context:   {b.context_window} tokens",
        f"  Tools:     {b.tools_registered} registered",
    ]
    if b.forced_tier:
        lines.append(f"  Tier:      {b.forced_tier} (forced)")
    if b.debug:
        lines.append(f"  Debug:     ON")

    width = max(len(line) for line in lines) + 2
    top = "╭" + "─" * width + "╮"
    bottom = "╰" + "─" * width + "╯"
    body = "\n".join(f"│{line.ljust(width)}│" for line in lines)
    return f"{top}\n{body}\n{bottom}"


# ── Turn trace ────────────────────────────────────────────────


@dataclass
class TurnTraceRecord:
    """Single turn trace record for debug output."""

    turn_number: int = 0
    route: str = ""
    intent: str = ""
    confidence: float = 0.0
    prompt_tokens: int = 0
    finalizer: str = ""
    tools_called: List[str] = field(default_factory=list)
    tools_ok: int = 0
    tools_failed: int = 0
    elapsed_s: float = 0.0
    memory_injected: bool = False
    memory_tokens: int = 0
    tier: str = ""
    prerouted: bool = False

    def to_trace_line(self) -> str:
        """Format as single-line debug trace."""
        parts = [f"[turn #{self.turn_number}]"]
        if self.prerouted:
            parts.append("prerouted=true")
        else:
            parts.append(f"route={self.route}")
            parts.append(f"intent={self.intent}")
            parts.append(f"conf={self.confidence:.2f}")
        parts.append(f"prompt={self.prompt_tokens}tok")
        parts.append(f"finalizer={self.finalizer}")
        if self.tools_called:
            parts.append(f"tools=[{','.join(self.tools_called)}]")
        parts.append(f"ok={self.tools_ok}")
        if self.tools_failed:
            parts.append(f"fail={self.tools_failed}")
        if self.memory_injected:
            parts.append(f"mem={self.memory_tokens}tok")
        if self.tier:
            parts.append(f"tier={self.tier}")
        parts.append(f"elapsed={self.elapsed_s:.2f}s")
        return " ".join(parts)


class TurnTrace:
    """Accumulates trace data across a single turn.

    Call methods as each phase completes, then finalize with ``record()``.
    """

    def __init__(self, turn_number: int = 0, finalizer_name: str = "") -> None:
        self._data = TurnTraceRecord(
            turn_number=turn_number,
            finalizer=finalizer_name,
        )
        self._start = time.monotonic()

    def set_route(self, route: str, intent: str, confidence: float) -> None:
        self._data.route = route
        self._data.intent = intent
        self._data.confidence = confidence

    def set_prerouted(self) -> None:
        self._data.prerouted = True

    def set_prompt_tokens(self, tokens: int) -> None:
        self._data.prompt_tokens = tokens

    def set_tools(self, names: List[str], ok: int, failed: int) -> None:
        self._data.tools_called = names
        self._data.tools_ok = ok
        self._data.tools_failed = failed

    def set_memory(self, injected: bool, tokens: int) -> None:
        self._data.memory_injected = injected
        self._data.memory_tokens = tokens

    def set_tier(self, tier: str) -> None:
        self._data.tier = tier

    def record(self) -> TurnTraceRecord:
        """Finalize and return the trace record."""
        self._data.elapsed_s = time.monotonic() - self._start
        return self._data
