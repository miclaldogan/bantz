"""Unified Brain Loop — single entry point for all brain backends.

Issue #403: Brain Consolidation EPIC — Phase 1 (Foundation).
Issue #443: Enhanced with auto-mode, deprecation warnings, diagnostics.

This module provides a unified interface over both:
- **BrainLoop** (Jarvis mode — deterministic calendar UX, voice menus)
- **OrchestratorLoop** (LLM-first — general purpose, multi-tool orchestration)

The goal is to decouple callers from the backend implementation so that
future PRs can gradually migrate BrainLoop features into OrchestratorLoop
and eventually retire brain_loop.py.

Usage::

    # Factory (recommended)
    brain = create_brain(
        mode="orchestrator",
        llm=my_llm,
        tools=my_tools,
        event_bus=bus,
    )
    result = brain.process("bugün takvimde ne var?")

    # Auto mode (Issue #443) — detects best backend per-turn
    brain = create_brain(
        mode="auto",
        llm=my_llm,
        tools=my_tools,
        event_bus=bus,
    )
    result = brain.process("yarın 15:00'te toplantı ekle")  # → jarvis
    result = brain.process("merhaba nasılsın")              # → orchestrator

    # Access the underlying backend when needed
    if brain.mode == "orchestrator":
        raw_state = brain.orchestrator_state
"""

from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "UnifiedBrain",
    "UnifiedResult",
    "UnifiedConfig",
    "create_brain",
    "deprecated_direct_backend",
]


# ---------------------------------------------------------------------------
# Deprecation helper (Issue #443)
# ---------------------------------------------------------------------------

def deprecated_direct_backend(backend_name: str) -> None:
    """Emit a deprecation warning when using BrainLoop/OrchestratorLoop directly.

    Call this at the start of code that directly instantiates a backend
    instead of using create_brain().

    Example::

        deprecated_direct_backend("BrainLoop")
        # → DeprecationWarning: Direct use of BrainLoop is deprecated.
        #   Use create_brain(mode='jarvis') instead.
    """
    mode_hint = "jarvis" if "brain" in backend_name.lower() else "orchestrator"
    warnings.warn(
        f"Direct use of {backend_name} is deprecated. "
        f"Use create_brain(mode='{mode_hint}') instead.",
        DeprecationWarning,
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Unified result type
# ---------------------------------------------------------------------------


@dataclass
class UnifiedResult:
    """Unified brain result — superset of BrainResult and OrchestratorOutput.

    This normalises both backends into a single structure so callers never
    need to know which backend produced the response.

    Attributes:
        kind: Result kind — ``"say"`` | ``"ask_user"`` | ``"fail"``.
        text: The assistant reply or error message.
        route: Detected route (``"calendar"`` | ``"gmail"`` | ``"smalltalk"``
               | ``"unknown"`` | ``""``).
        intent: Detected intent (``"create"`` | ``"query"`` | ``"none"`` …).
        confidence: LLM confidence 0.0–1.0.
        tool_plan: Tools that were planned (names).
        tools_executed: Tools that actually ran successfully.
        requires_confirmation: Whether the action needs user confirmation.
        steps_used: Number of LLM steps consumed (BrainLoop) or 0.
        metadata: Arbitrary backend-specific metadata / trace dict.
        backend: Which backend produced this result
                 (``"brain_loop"`` | ``"orchestrator"``).
        state: Opaque state object to pass back on the next turn.
    """

    kind: str
    text: str
    route: str = ""
    intent: str = ""
    confidence: float = 0.0
    tool_plan: list[str] = field(default_factory=list)
    tools_executed: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    steps_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    backend: str = ""
    state: Any = None

    @property
    def is_error(self) -> bool:
        """Return *True* if this result represents an error."""
        return self.kind == "fail"


# ---------------------------------------------------------------------------
# Unified config
# ---------------------------------------------------------------------------


@dataclass
class UnifiedConfig:
    """Configuration for :class:`UnifiedBrain`.

    Attributes:
        mode: ``"orchestrator"`` (default, LLM-first), ``"jarvis"``
              (deterministic calendar UX), or ``"auto"`` (per-turn detection).
        max_steps: Maximum LLM reasoning steps per turn.
        debug: Enable verbose logging.
        enable_safety_guard: Enable tool safety checks (OrchestratorLoop).
        memory_max_tokens: Token budget for memory-lite summaries.
        memory_max_turns: Max turns kept in memory-lite.
        require_confirmation_for: Tool names that require explicit confirmation.
        auto_jarvis_patterns: Patterns that trigger jarvis mode in auto detection.
    """

    mode: str = "orchestrator"
    max_steps: int = 8
    debug: bool = False
    enable_safety_guard: bool = True
    memory_max_tokens: int = 1000
    memory_max_turns: int = 10
    require_confirmation_for: Optional[list[str]] = None
    auto_jarvis_patterns: Optional[list[str]] = None  # Issue #443


# ---------------------------------------------------------------------------
# LLM protocol (union of both backends)
# ---------------------------------------------------------------------------


class LLMClientProtocol(Protocol):
    """Minimal LLM protocol accepted by :func:`create_brain`.

    At minimum the LLM must support ``complete_json`` (for BrainLoop) or
    ``complete_text`` (for OrchestratorLoop).  Ideally it supports both.
    """

    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema_hint: str,
    ) -> dict[str, Any]:
        ...  # pragma: no cover

    def complete_text(
        self,
        *,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str:
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Unified Brain
# ---------------------------------------------------------------------------


class UnifiedBrain:
    """Single entry point for both BrainLoop and OrchestratorLoop.

    Instead of importing either backend directly, callers should use this
    class (or the :func:`create_brain` factory) to get a brain instance.
    The underlying backend is selected by *mode* and is fully transparent
    to the caller.

    Parameters
    ----------
    mode:
        ``"orchestrator"`` for LLM-first or ``"jarvis"`` for deterministic.
    brain_loop:
        A ``BrainLoop`` instance (required when *mode* is ``"jarvis"``).
    orchestrator_loop:
        An ``OrchestratorLoop`` instance (required when *mode* is ``"orchestrator"``).
    config:
        Unified configuration.
    session_context:
        Default session context passed on every turn (timezone, locale, …).
    """

    def __init__(
        self,
        *,
        mode: str = "orchestrator",
        brain_loop: Any = None,
        orchestrator_loop: Any = None,
        config: Optional[UnifiedConfig] = None,
        session_context: Optional[dict[str, Any]] = None,
    ) -> None:
        if mode not in ("orchestrator", "jarvis", "auto"):
            raise ValueError(f"Unknown mode: {mode!r}. Use 'orchestrator', 'jarvis', or 'auto'.")

        self.mode = mode
        self._config = config or UnifiedConfig(mode=mode)
        self._session_context = session_context or {}

        # Backend instances
        self._brain_loop = brain_loop
        self._orchestrator_loop = orchestrator_loop

        # Orchestrator state (persisted across turns)
        self._orchestrator_state: Any = None

        # Jarvis state dict (persisted across turns)
        self._jarvis_state: dict[str, Any] = {}

        # Validate the right backend is provided
        if mode == "jarvis" and brain_loop is None:
            raise ValueError("Jarvis mode requires a BrainLoop instance.")
        if mode == "orchestrator" and orchestrator_loop is None:
            raise ValueError("Orchestrator mode requires an OrchestratorLoop instance.")
        if mode == "auto" and brain_loop is None and orchestrator_loop is None:
            raise ValueError("Auto mode requires at least one backend instance.")

        # Diagnostics (Issue #443)
        self._turn_count = 0
        self._total_latency = 0.0
        self._backend_usage: Dict[str, int] = {"brain_loop": 0, "orchestrator": 0}
        self._error_count = 0

        # Auto-mode patterns (Issue #443)
        self._jarvis_patterns = self._config.auto_jarvis_patterns or [
            "takvim", "etkinlik", "toplantı", "randevu",
            "hatırlat", "alarm", "saat kaç",
        ]

        logger.info(
            "[UnifiedBrain] Initialized in %s mode (config=%s)",
            mode,
            self._config,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        user_input: str,
        *,
        session_context: Optional[dict[str, Any]] = None,
        policy: Any = None,
        state: Any = None,
    ) -> UnifiedResult:
        """Process a single user turn and return a unified result.

        Parameters
        ----------
        user_input:
            The user's text input.
        session_context:
            Per-turn session context (merged with default).
        policy:
            Optional policy engine (BrainLoop / Jarvis mode only).
        state:
            Opaque state object from a previous ``UnifiedResult.state``.
            If *None*, the internal state is reused across turns.

        Returns
        -------
        UnifiedResult
            Normalised result regardless of backend.
        """
        user_input = (user_input or "").strip()
        if not user_input:
            return UnifiedResult(
                kind="fail",
                text="empty_input",
                backend=self.mode,
            )

        self._turn_count += 1
        t0 = time.time()

        try:
            effective_mode = self._resolve_mode(user_input)

            if effective_mode == "jarvis":
                result = self._process_jarvis(
                    user_input,
                    session_context=session_context,
                    policy=policy,
                    state=state,
                )
            else:
                result = self._process_orchestrator(
                    user_input,
                    session_context=session_context,
                    state=state,
                )

            self._backend_usage[result.backend] = (
                self._backend_usage.get(result.backend, 0) + 1
            )
            return result

        except Exception as exc:
            self._error_count += 1
            logger.error("[UnifiedBrain] Error processing turn: %s", exc)
            return UnifiedResult(
                kind="fail",
                text=str(exc),
                backend=self.mode,
            )
        finally:
            self._total_latency += time.time() - t0

    def reset(self) -> None:
        """Reset internal state (start a fresh conversation)."""
        self._orchestrator_state = None
        self._jarvis_state = {}
        logger.debug("[UnifiedBrain] State reset")

    # ------------------------------------------------------------------
    # Auto-mode detection (Issue #443)
    # ------------------------------------------------------------------

    def _resolve_mode(self, user_input: str) -> str:
        """Resolve effective mode for this turn.

        In ``"auto"`` mode, checks the input against jarvis patterns.
        Falls back to ``"orchestrator"`` if no match.
        """
        if self.mode != "auto":
            return self.mode

        text_lower = user_input.lower()
        for pattern in self._jarvis_patterns:
            if pattern in text_lower:
                if self._brain_loop is not None:
                    return "jarvis"
                break  # pattern matched but no brain_loop → fallback

        if self._orchestrator_loop is not None:
            return "orchestrator"
        return "jarvis"  # last resort if only brain_loop available

    # ------------------------------------------------------------------
    # Diagnostics (Issue #443)
    # ------------------------------------------------------------------

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return turn-level diagnostics for monitoring."""
        avg_latency = (
            self._total_latency / self._turn_count
            if self._turn_count > 0
            else 0.0
        )
        return {
            "mode": self.mode,
            "turn_count": self._turn_count,
            "avg_latency_ms": round(avg_latency * 1000, 1),
            "total_latency_ms": round(self._total_latency * 1000, 1),
            "backend_usage": dict(self._backend_usage),
            "error_count": self._error_count,
            "has_brain_loop": self._brain_loop is not None,
            "has_orchestrator_loop": self._orchestrator_loop is not None,
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def orchestrator_state(self) -> Any:
        """Access the raw OrchestratorState (orchestrator mode only)."""
        return self._orchestrator_state

    @property
    def jarvis_state(self) -> dict[str, Any]:
        """Access the raw Jarvis state dict (jarvis mode only)."""
        return dict(self._jarvis_state)

    @property
    def backend(self) -> Any:
        """Return the underlying backend instance."""
        if self.mode == "jarvis":
            return self._brain_loop
        return self._orchestrator_loop

    # ------------------------------------------------------------------
    # Jarvis backend
    # ------------------------------------------------------------------

    def _process_jarvis(
        self,
        user_input: str,
        *,
        session_context: Optional[dict[str, Any]],
        policy: Any,
        state: Any,
    ) -> UnifiedResult:
        """Delegate to BrainLoop and normalise the result."""
        from bantz.brain.brain_loop import BrainResult

        # Merge session contexts
        ctx = dict(self._session_context)
        if isinstance(session_context, dict):
            ctx.update(session_context)

        # Restore state from caller or use internal
        jarvis_ctx = state if isinstance(state, dict) else dict(self._jarvis_state)

        result: BrainResult = self._brain_loop.run(
            turn_input=user_input,
            session_context=ctx,
            policy=policy,
            context=jarvis_ctx,
        )

        # Persist state
        self._jarvis_state = jarvis_ctx

        return self._from_brain_result(result, jarvis_ctx)

    @staticmethod
    def _from_brain_result(result: Any, state: Any = None) -> UnifiedResult:
        """Convert BrainResult → UnifiedResult."""
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        trace = metadata.get("trace", {})

        return UnifiedResult(
            kind=result.kind,
            text=result.text,
            route=str(trace.get("llm_router_route") or metadata.get("route") or ""),
            intent=str(trace.get("intent") or ""),
            confidence=float(trace.get("llm_router_confidence") or 0.0),
            tool_plan=list(trace.get("llm_router_tool_plan") or []),
            tools_executed=[],  # BrainLoop doesn't expose this cleanly
            requires_confirmation=bool(metadata.get("requires_confirmation", False)),
            steps_used=result.steps_used,
            metadata=metadata,
            backend="brain_loop",
            state=state,
        )

    # ------------------------------------------------------------------
    # Orchestrator backend
    # ------------------------------------------------------------------

    def _process_orchestrator(
        self,
        user_input: str,
        *,
        session_context: Optional[dict[str, Any]],
        state: Any,
    ) -> UnifiedResult:
        """Delegate to OrchestratorLoop and normalise the result."""
        from bantz.brain.orchestrator_state import OrchestratorState

        # Restore state
        if isinstance(state, OrchestratorState):
            orch_state = state
        elif self._orchestrator_state is not None:
            orch_state = self._orchestrator_state
        else:
            orch_state = OrchestratorState()

        # Inject session context into state
        if session_context or self._session_context:
            merged_ctx = dict(self._session_context)
            if isinstance(session_context, dict):
                merged_ctx.update(session_context)
            orch_state.session_context = merged_ctx

        output, updated_state = self._orchestrator_loop.process_turn(
            user_input=user_input,
            state=orch_state,
        )

        # Persist state
        self._orchestrator_state = updated_state

        return self._from_orchestrator_output(output, updated_state)

    @staticmethod
    def _from_orchestrator_output(output: Any, state: Any = None) -> UnifiedResult:
        """Convert (OrchestratorOutput, OrchestratorState) → UnifiedResult."""
        # Determine kind
        if output.ask_user and output.question:
            kind = "ask_user"
            text = output.question
        elif output.assistant_reply:
            kind = "say"
            text = output.assistant_reply
        else:
            kind = "say"
            text = output.assistant_reply or ""

        # Extract executed tools from state trace
        tools_executed: list[str] = []
        if state is not None:
            trace = getattr(state, "trace", {})
            if isinstance(trace, dict):
                ts = trace.get("tools_success")
                if isinstance(ts, list):
                    tools_executed = [str(t) for t in ts if isinstance(t, str)]

        return UnifiedResult(
            kind=kind,
            text=text,
            route=output.route or "",
            intent=output.calendar_intent or "",
            confidence=output.confidence,
            tool_plan=list(output.tool_plan or []),
            tools_executed=tools_executed,
            requires_confirmation=bool(output.requires_confirmation),
            steps_used=0,
            metadata={
                "trace": getattr(state, "trace", {}) if state else {},
                "confirmation_prompt": output.confirmation_prompt or "",
                "reasoning_summary": list(output.reasoning_summary or []),
                "memory_update": output.memory_update or "",
                "raw_output": output.raw_output or {},
            },
            backend="orchestrator",
            state=state,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_brain(
    *,
    mode: str = "orchestrator",
    llm: Any = None,
    tools: Any = None,
    event_bus: Any = None,
    config: Optional[UnifiedConfig] = None,
    session_context: Optional[dict[str, Any]] = None,
    # OrchestratorLoop-specific
    finalizer_llm: Any = None,
    router_system_prompt: Optional[str] = None,
    audit_logger: Any = None,
    # BrainLoop-specific
    router: Any = None,
    memory_manager: Any = None,
    policy: Any = None,
) -> UnifiedBrain:
    """Create a :class:`UnifiedBrain` with the appropriate backend.

    This is the **recommended** way to get a brain instance.

    Parameters
    ----------
    mode:
        ``"orchestrator"`` (default, LLM-first), ``"jarvis"``
        (deterministic calendar UX), or ``"auto"`` (per-turn detection,
        Issue #443).
    llm:
        LLM client — must support ``complete_json`` (Jarvis) and/or
        ``complete_text`` (Orchestrator).
    tools:
        ``ToolRegistry`` instance with registered tools.
    event_bus:
        ``EventBus`` for publishing events.
    config:
        Optional unified configuration.
    session_context:
        Default session context for every turn.
    finalizer_llm:
        Separate LLM for response finalization (Orchestrator mode).
    router_system_prompt:
        Custom system prompt for the LLM router (Orchestrator mode).
    audit_logger:
        Audit logger for tool executions (Orchestrator mode).
    router:
        Optional LLM router (Jarvis mode).
    memory_manager:
        Optional memory manager (Jarvis mode).
    policy:
        Optional policy engine (Jarvis mode).

    Returns
    -------
    UnifiedBrain
        Ready-to-use brain instance.
    """
    cfg = config or UnifiedConfig(mode=mode)

    brain_loop = None
    orchestrator_loop = None

    # In auto mode, create both backends (Issue #443)
    need_jarvis = mode in ("jarvis", "auto")
    need_orch = mode in ("orchestrator", "auto")

    if need_jarvis:
        try:
            from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig

            bl_config = BrainLoopConfig(
                max_steps=cfg.max_steps,
                debug=cfg.debug,
            )
            brain_loop = BrainLoop(
                llm=llm,
                tools=tools,
                event_bus=event_bus,
                config=bl_config,
                router=router,
                memory_manager=memory_manager,
            )
        except Exception as e:
            if mode == "jarvis":
                raise
            logger.warning("[create_brain] BrainLoop init failed (auto mode): %s", e)

    if need_orch:
        try:
            from bantz.brain.llm_router import JarvisLLMOrchestrator
            from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop

            orchestrator = JarvisLLMOrchestrator(
                llm_client=llm,
                system_prompt=router_system_prompt,
            )

            orch_config = OrchestratorConfig(
                max_steps=cfg.max_steps,
                debug=cfg.debug,
                enable_safety_guard=cfg.enable_safety_guard,
                memory_max_tokens=cfg.memory_max_tokens,
                memory_max_turns=cfg.memory_max_turns,
                require_confirmation_for=cfg.require_confirmation_for,
            )

            orchestrator_loop = OrchestratorLoop(
                orchestrator=orchestrator,
                tools=tools,
                event_bus=event_bus,
                config=orch_config,
                finalizer_llm=finalizer_llm,
                audit_logger=audit_logger,
            )
        except Exception as e:
            if mode == "orchestrator":
                raise
            logger.warning("[create_brain] OrchestratorLoop init failed (auto mode): %s", e)

    return UnifiedBrain(
        mode=mode,
        brain_loop=brain_loop,
        orchestrator_loop=orchestrator_loop,
        config=cfg,
        session_context=session_context,
    )
