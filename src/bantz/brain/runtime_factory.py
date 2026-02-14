"""Runtime Factory — canonical brain wiring for all entry points (Issue #516).

This is the SINGLE source of truth for how a BANTZ brain is created.
Both ``terminal_jarvis.py`` and ``server.py`` MUST use this factory
instead of directly instantiating ``OrchestratorLoop`` or ``Router``.

Usage::

    from bantz.brain.runtime_factory import create_runtime, BantzRuntime

    runtime = create_runtime()  # reads from env vars
    output, state = runtime.process_turn("bugün plan var mı", state)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["BantzRuntime", "create_runtime"]


def _env_get_any(*keys: str) -> Optional[str]:
    """Return the first non-empty env var from the given keys."""
    for k in keys:
        v = os.getenv(k, "").strip()
        if v:
            return v
    return None


@dataclass
class BantzRuntime:
    """Holds all runtime components created by :func:`create_runtime`.

    This is the canonical brain wiring.  All entry points (terminal, server,
    tests) should use this instead of manually assembling the pipeline.

    Attributes:
        router_client: vLLM-backed LLM client for routing.
        gemini_client: Gemini client for finalization (may be None).
        tools: Registered tool registry.
        event_bus: Shared event bus.
        loop: The OrchestratorLoop instance.
        router_model: Model name used for routing.
        gemini_model: Model name used for finalization.
        finalizer_is_gemini: True if Gemini is the finalizer.
    """

    router_client: Any
    gemini_client: Any  # Optional[GeminiClient]
    tools: Any  # ToolRegistry
    event_bus: Any  # EventBus
    loop: Any  # OrchestratorLoop
    router_model: str = ""
    gemini_model: str = ""
    finalizer_is_gemini: bool = False

    def process_turn(
        self, user_input: str, state: Any
    ) -> tuple[Any, Any]:
        """Process a single turn through the brain.

        Returns:
            (OrchestratorOutput, OrchestratorState) tuple.
        """
        return self.loop.process_turn(user_input, state)

    def run_full_cycle(
        self, user_input: str, *, confirmation_token: str = "", state: Any = None
    ) -> dict:
        """Run a full orchestration cycle (for confirmation flows)."""
        return self.loop.run_full_cycle(
            user_input, confirmation_token=confirmation_token, state=state
        )


def create_runtime(
    *,
    vllm_url: Optional[str] = None,
    router_model: Optional[str] = None,
    gemini_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    event_bus: Any = None,
    tools: Any = None,
    debug: bool = False,
) -> BantzRuntime:
    """Create a fully wired BANTZ runtime.

    This is the **single canonical factory** for creating the brain.
    All parameters default to environment variables.

    Parameters
    ----------
    vllm_url:
        vLLM server URL (default: ``BANTZ_VLLM_URL`` or ``http://localhost:8001``).
    router_model:
        Router model name (default: ``BANTZ_VLLM_MODEL``).
    gemini_key:
        Gemini API key (default: ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``).
    gemini_model:
        Gemini model name (default: ``BANTZ_GEMINI_MODEL``).
    event_bus:
        Shared EventBus (created if not provided).
    tools:
        ToolRegistry (created with default tools if not provided).
    debug:
        Enable debug logging.

    Returns
    -------
    BantzRuntime
        Ready-to-use runtime with all components wired.
    """
    from bantz.core.events import EventBus
    from bantz.brain.llm_router import JarvisLLMOrchestrator
    from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop
    from bantz.llm.vllm_openai_client import VLLMOpenAIClient

    # ── Resolve parameters from env ─────────────────────────────────
    _vllm_url = vllm_url or os.getenv("BANTZ_VLLM_URL", "http://localhost:8001")
    _router_model = router_model or os.getenv("BANTZ_VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct-AWQ")
    _gemini_model = gemini_model or os.getenv("BANTZ_GEMINI_MODEL", "gemini-2.0-flash")
    _gemini_key = gemini_key or _env_get_any(
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY"
    )

    # ── Router LLM client ───────────────────────────────────────────
    router_client = VLLMOpenAIClient(
        base_url=_vllm_url, model=_router_model, timeout_seconds=30.0
    )

    # ── Gemini finalizer client ─────────────────────────────────────
    gemini_client = None
    finalizer_is_gemini = False
    if _gemini_key:
        try:
            from bantz.llm.gemini_client import (
                GeminiClient,
                get_default_quota_tracker,
                get_default_circuit_breaker,
            )

            gemini_client = GeminiClient(
                api_key=_gemini_key,
                model=_gemini_model,
                timeout_seconds=30.0,
                quota_tracker=get_default_quota_tracker(),
                circuit_breaker=get_default_circuit_breaker(),
            )
            finalizer_is_gemini = True
            logger.info(
                "Finalizer: %s ✓ (Gemini, quota_tracker=active, circuit_breaker=active)",
                _gemini_model,
            )
        except Exception as e:
            logger.warning("Gemini client init failed: %s — using 3B fallback", e)
    else:
        logger.warning(
            "⚠ GEMINI_API_KEY not set — finalization will use 3B router (%s). "
            "Quality may be degraded.",
            _router_model,
        )

    # ── Event bus ───────────────────────────────────────────────────
    _event_bus = event_bus
    if _event_bus is None:
        _event_bus = EventBus(history_size=200)

    # ── Tool registry ───────────────────────────────────────────────
    _tools = tools
    if _tools is None:
        from bantz.agent.registry import build_default_registry
        _tools = build_default_registry()

    # ── Declarative Skills (Issue #833) ─────────────────────────────
    try:
        from bantz.skills.declarative.bridge import setup_declarative_skills

        _skill_registry = setup_declarative_skills(_tools)
        _skill_count = len(_skill_registry.skill_names)
        if _skill_count:
            logger.info("Declarative skills loaded: %d", _skill_count)
    except Exception as exc:
        # Never block startup due to skill loading failure
        logger.warning("Declarative skill loading failed: %s", exc)

    # ── Proactive Engine (Issue #835) ───────────────────────────────
    try:
        from bantz.proactive.engine import setup_proactive_engine

        _proactive_engine = setup_proactive_engine(
            tool_registry=_tools,
            event_bus=_event_bus,
            auto_start=True,
        )
        logger.info("Proactive Engine started: %d checks", len(_proactive_engine.get_all_checks()))
    except Exception as exc:
        # Never block startup due to proactive engine failure
        logger.warning("Proactive Engine startup failed: %s", exc)

    # ── Orchestrator ────────────────────────────────────────────────
    orchestrator = JarvisLLMOrchestrator(llm_client=router_client)

    # ── Finalizer wiring (#517 invariant) ───────────────────────────
    effective_finalizer = gemini_client or router_client

    # ── Issue #1290: Observability — RunTracker ───────────────────
    _run_tracker = None
    if os.getenv("BANTZ_OBSERVABILITY", "1").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from bantz.data.run_tracker import RunTracker

            _run_tracker = RunTracker()
            _run_tracker.initialise_sync()
            logger.info("RunTracker ✓ (%s)", _run_tracker.db_path)
        except Exception as exc:
            logger.warning("RunTracker init failed (non-fatal): %s", exc)
            _run_tracker = None

    # ── OrchestratorLoop ────────────────────────────────────────────
    loop = OrchestratorLoop(
        orchestrator=orchestrator,
        tools=_tools,
        event_bus=_event_bus,
        config=OrchestratorConfig(debug=debug),
        finalizer_llm=effective_finalizer,
        run_tracker=_run_tracker,
    )

    # ── Build runtime ──────────────────────────────────────────────
    runtime = BantzRuntime(
        router_client=router_client,
        gemini_client=gemini_client,
        tools=_tools,
        event_bus=_event_bus,
        loop=loop,
        router_model=_router_model,
        gemini_model=_gemini_model,
        finalizer_is_gemini=finalizer_is_gemini,
    )

    # ── Boot banner (Issue #588: visible diagnostics at every start) ──
    from bantz.brain.runtime_banner import RuntimeBanner, format_banner

    banner = RuntimeBanner.from_runtime(runtime)
    banner_text = format_banner(banner)
    print(banner_text, flush=True)
    logger.info("\n%s", banner_text)

    if not finalizer_is_gemini:
        logger.warning(
            "⚠ Finalizer is 3B — set GEMINI_API_KEY for quality responses. "
            "Override: BANTZ_TIER_FORCE_FINALIZER=quality|fast (legacy: BANTZ_FORCE_FINALIZER_TIER)"
        )

    return runtime
