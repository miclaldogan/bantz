"""LLM Orchestrator Loop (Issue #134: LLM-first architecture).

This is the executor for JarvisLLMOrchestrator. Every turn:
1. LLM decides (route, intent, tools, confirmation, reasoning)
2. Executor runs tools (with confirmation firewall for destructive ops)
3. LLM finalizes response (using tool results)

No hard-coded routing - LLM controls everything.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Optional

from bantz.agent.tools import ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.brain.safety_guard import SafetyGuard, ToolSecurityPolicy
from bantz.brain.memory_lite import DialogSummaryManager, CompactSummary
from bantz.core.events import EventBus, EventType
from bantz.routing.preroute import PreRouter, IntentCategory, LocalResponseGenerator
from bantz.nlu.slots import SlotExtractor

# Issue #941: Extracted modules — keep backward-compat re-exports
from bantz.brain.tool_result_summarizer import (  # noqa: F401
    _summarize_tool_result,
    _prepare_tool_results_for_finalizer,
    _build_tool_success_summary,
    _count_items,
    _extract_count,
    _extract_field,
)
from bantz.brain.tool_plan_sanitizer import (
    TOOL_REMAP,
    force_tool_plan as _force_tool_plan_fn,
    sanitize_tool_plan as _sanitize_tool_plan_fn,
)
from bantz.brain.post_route_corrections import (
    looks_like_email_send_intent,
    extract_first_email,
    extract_recipient_name,
    extract_message_body_hint,
    post_route_correction_email_send,
)
from bantz.brain.plan_verifier import verify_plan
from bantz.brain.tool_param_builder import build_tool_params
from bantz.brain.misroute_integration import record_turn_misroute
from bantz.brain.context_builder import ContextBuilder

logger = logging.getLogger(__name__)

# Issue #941: Module-level helpers moved to bantz.brain.tool_result_summarizer
# Re-exported above for backward compatibility.


@dataclass
class OrchestratorConfig:
    """Configuration for orchestrator loop."""
    
    max_steps: int = 8  # Max tool execution steps per turn
    debug: bool = False  # Debug mode (verbose logging)
    require_confirmation_for: list[str] = None  # Tools requiring confirmation
    enable_safety_guard: bool = True  # Enable safety & policy checks (Issue #140)
    security_policy: Optional[ToolSecurityPolicy] = None  # Custom security policy
    memory_max_tokens: int = 1000  # Memory-lite token budget (Issue #368)
    memory_max_turns: int = 10  # Memory-lite max turns (Issue #368)
    memory_pii_filter: bool = True  # Memory-lite PII filtering (Issue #368)
    tool_timeout_seconds: float = 30.0  # Per-tool execution timeout (Issue #431)
    enable_preroute: bool = True  # Issue #407: Rule-based pre-route bypass
    finalizer_timeout_seconds: float = 10.0  # Issue #947: Finalizer LLM timeout (quality)
    fast_finalizer_timeout_seconds: float = 5.0  # Issue #947: Fast finalizer LLM timeout
    
    def __post_init__(self):
        if self.require_confirmation_for is None:
            # Default: destructive operations require confirmation
            self.require_confirmation_for = [
                "calendar.delete_event",
                "calendar.update_event",
                "calendar.create_event",  # Even creates need confirmation (Policy decision)
            ]


class OrchestratorLoop:
    """LLM-driven orchestrator loop (Issue #134).
    
    This executor implements the LLM-first architecture:
    - LLM makes all decisions (route, intent, tools, confirmation)
    - Executor enforces safety (confirmation firewall for destructive ops)
    - Rolling summary maintains memory across turns
    - Trace metadata for testing/debugging
    
    Usage:
        >>> orchestrator = JarvisLLMOrchestrator(llm_client)
        >>> loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
        >>> response = loop.process_turn(user_input, state)
    """
    
    def __init__(
        self,
        orchestrator: JarvisLLMOrchestrator,
        tools: ToolRegistry,
        event_bus: Optional[EventBus] = None,
        config: Optional[OrchestratorConfig] = None,
        finalizer_llm: Optional[Any] = None,
        audit_logger: Optional[Any] = None,
    ):
        self.orchestrator = orchestrator
        self.tools = tools
        self.event_bus = event_bus or EventBus()
        self.config = config or OrchestratorConfig()
        self.finalizer_llm = finalizer_llm
        self.audit_logger = audit_logger  # For tool execution auditing (Issue #160)

        # Issue #597: Cache FinalizationPipeline (avoid per-turn object allocation)
        self._finalization_pipeline: Any = None
        self._finalization_pipeline_key: tuple[int, int, int] | None = None

        # Issue #517: Finalizer wiring invariant — warn if no finalizer
        if finalizer_llm is None:
            import warnings as _fw

            _fw.warn(
                "OrchestratorLoop created without finalizer_llm. "
                "Finalization will use deterministic defaults only (no natural language). "
                "Pass a GeminiClient or LLM client as finalizer_llm for quality responses.",
                UserWarning,
                stacklevel=2,
            )
        else:
            _fm = (
                getattr(finalizer_llm, "model_name", None)
                or getattr(finalizer_llm, "model", None)
                or type(finalizer_llm).__name__
            )
            logger.info("OrchestratorLoop finalizer: %s", _fm)

        # Initialize memory-lite (Issue #141)
        self.memory = DialogSummaryManager(
            max_tokens=self.config.memory_max_tokens,
            max_turns=self.config.memory_max_turns,
            pii_filter_enabled=self.config.memory_pii_filter,
        )

        # Issue #873: Persistent user memory (profile + SQLite store + learning)
        try:
            from bantz.brain.user_memory import UserMemoryBridge

            self.user_memory: Any = UserMemoryBridge()
        except Exception as _umx:
            logger.warning("[ORCHESTRATOR] UserMemoryBridge init failed: %s", _umx)
            self.user_memory = None

        # Issue #874: Personality injection (Jarvis/Friday/Alfred presets)
        try:
            from bantz.brain.personality_injector import PersonalityInjector

            self.personality_injector: Any = PersonalityInjector()
        except Exception as _pix:
            logger.warning("[ORCHESTRATOR] PersonalityInjector init failed: %s", _pix)
            self.personality_injector = None

        # Issue #599: Memory injection trace/audit (best-effort, non-fatal)
        try:
            from bantz.brain.memory_trace import MemoryBudgetConfig, MemoryTracer

            self._memory_tracer = MemoryTracer(
                MemoryBudgetConfig(
                    max_tokens=int(self.config.memory_max_tokens),
                    max_turns=int(self.config.memory_max_turns),
                    pii_filter=bool(self.config.memory_pii_filter),
                )
            )
        except Exception:
            self._memory_tracer = None

        # Initialize safety guard (Issue #140)
        if self.config.enable_safety_guard:
            self.safety_guard = SafetyGuard(
                policy=self.config.security_policy or ToolSecurityPolicy()
            )
        else:
            self.safety_guard = None

        # Issue #417: Session context cache (TTL 60s) — avoid rebuild every turn
        # Issue #902: Per-session cache to prevent multi-user context leak.
        from bantz.brain.session_context_cache import SessionContextCache

        self._session_ctx_caches: dict[str, SessionContextCache] = {}
        self._session_ctx_ttl = 60.0

        # Issue #942: Caches to avoid redundant work in _llm_planning_phase
        # Issue #1010: Context assembly extracted to ContextBuilder
        self._context_builder = ContextBuilder(
            memory=self.memory,
            user_memory=self.user_memory,
            personality_injector=getattr(self, "personality_injector", None),
            pii_filter=self.config.memory_pii_filter,
            memory_max_tokens=self.config.memory_max_tokens,
        )

        # Issue #407: Pre-route rule engine — bypass LLM for obvious patterns
        self.prerouter = PreRouter()
        self._local_responder = LocalResponseGenerator()

        # Issue #938: Wire NLU slot extraction into brain pipeline
        self._slot_extractor = SlotExtractor()

        # Issue #946: Shared executor for tool calls — avoids per-tool ThreadPoolExecutor churn
        self._tool_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="bantz-tool",
        )

        # Issue #900: Sync router _VALID_TOOLS with actual ToolRegistry
        try:
            JarvisLLMOrchestrator.sync_valid_tools(self.tools.names())
        except Exception:
            logger.warning("[ORCHESTRATOR] sync_valid_tools failed", exc_info=True)

        # Route+Intent → Mandatory Tools mapping (Issue #282)
        # Prevents hallucination when LLM returns empty tool_plan for queries
        # Issue #897: Gmail entries removed — they were keyed by
        # calendar_intent which is the wrong field.  Gmail lookups now
        # go exclusively through _gmail_intent_map (below).
        self._mandatory_tool_map: dict[tuple[str, str], list[str]] = {
            # Calendar routes
            ("calendar", "query"): ["calendar.list_events"],
            ("calendar", "create"): ["calendar.create_event"],
            ("calendar", "modify"): ["calendar.update_event"],
            ("calendar", "cancel"): ["calendar.delete_event"],
            # System routes
            ("system", "time"): ["time.now"],
            ("system", "status"): ["system.status"],
            ("system", "query"): ["time.now"],  # Default for system queries
        }

        # Gmail intent mapping (gmail_intent → mandatory tools)
        # Issue #317: Extended Gmail label/category support
        self._gmail_intent_map: dict[str, list[str]] = {
            "list": ["gmail.list_messages"],
            "search": ["gmail.smart_search"],
            "read": ["gmail.get_message"],
            "send": ["gmail.send"],
        }

    def close(self) -> None:
        """Shut down the shared tool executor. Safe to call multiple times."""
        try:
            self._tool_executor.shutdown(wait=False)
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()

    def _get_finalization_pipeline(self) -> Any:
        from bantz.brain.finalization_pipeline import create_pipeline

        planner_llm = getattr(self.orchestrator, "_llm", None)
        if planner_llm is not None and not hasattr(planner_llm, "complete_text"):
            planner_llm = None
        key = (id(self.finalizer_llm), id(planner_llm), id(self.event_bus))
        if self._finalization_pipeline is None or self._finalization_pipeline_key != key:
            self._finalization_pipeline = create_pipeline(
                finalizer_llm=self.finalizer_llm,
                planner_llm=planner_llm,
                event_bus=self.event_bus,
                quality_timeout=self.config.finalizer_timeout_seconds,
                fast_timeout=self.config.fast_finalizer_timeout_seconds,
            )
            self._finalization_pipeline_key = key
        return self._finalization_pipeline
    
    # Issue #941: _force_tool_plan, _TOOL_REMAP, _sanitize_tool_plan
    # extracted to bantz.brain.tool_plan_sanitizer.  Thin wrappers kept
    # so existing callers inside this class continue to work.

    _TOOL_REMAP = TOOL_REMAP  # backward-compat alias

    def _force_tool_plan(self, output: OrchestratorOutput) -> OrchestratorOutput:
        return _force_tool_plan_fn(
            output,
            self._mandatory_tool_map,
            self._gmail_intent_map,
            debug=self.config.debug,
        )

    def _sanitize_tool_plan(self, output: OrchestratorOutput) -> OrchestratorOutput:
        return _sanitize_tool_plan_fn(output, self._TOOL_REMAP)

    def process_turn(
        self,
        user_input: str,
        state: Optional[OrchestratorState] = None,
    ) -> tuple[OrchestratorOutput, OrchestratorState]:
        """Process a single conversation turn (LLM-first).
        
        Flow:
        1. Call LLM with context (rolling summary + recent history + tool results)
        2. Execute tools (if any), respecting confirmation firewall
        3. Update state (rolling summary, tool results, conversation history)
        4. Return orchestrator output + updated state
        
        Args:
            user_input: User's message
            state: Orchestrator state (creates new if None)
        
        Returns:
            (orchestrator_output, updated_state)
        """
        if state is None:
            state = OrchestratorState()
        
        start_time = time.time()

        # Issue #417: Build session context once per turn (cached with TTL)
        # Issue #902: Per-session cache keyed by state identity
        if not state.session_context:
            sid = id(state)
            if sid not in self._session_ctx_caches:
                from bantz.brain.session_context_cache import SessionContextCache
                self._session_ctx_caches[sid] = SessionContextCache(ttl_seconds=self._session_ctx_ttl)
            state.session_context = self._session_ctx_caches[sid].get_or_build()
        
        # Emit turn start event
        self.event_bus.publish("turn.start", {"user_input": user_input})
        
        try:
            # ── Issue #894 fix: Auto-detect affirmative input when a pending
            # confirmation exists and set confirmed_tool automatically.
            # Without this, process_turn (which has no confirmation_token
            # parameter) could never resolve pending confirmations — the
            # prerouter would intercept "evet" as AFFIRMATIVE/smalltalk and
            # return "Tamam efendim" while the confirmed tool never executes.
            _AFFIRMATIVE_TOKENS = frozenset({
                "evet", "e", "yes", "y", "ok", "okay", "tamam", "olur",
                "peki", "tabii", "tabi", "elbette", "onaylıyorum",
            })
            _NEGATIVE_TOKENS = frozenset({
                "hayır", "h", "no", "n", "iptal", "vazgeç", "istemiyorum",
            })
            _user_stripped = user_input.strip().lower().rstrip(".!,?")
            if (
                state.has_pending_confirmation()
                and not state.confirmed_tool
                and _user_stripped in _AFFIRMATIVE_TOKENS
            ):
                pending = state.peek_pending_confirmation() or {}
                pending_tool = str(pending.get("tool") or "").strip()
                if pending_tool:
                    state.confirmed_tool = pending_tool
                    logger.info(
                        "[CONFIRMATION] Auto-confirmed tool %s from "
                        "affirmative input '%s'",
                        pending_tool, user_input,
                    )
            elif (
                state.has_pending_confirmation()
                and not state.confirmed_tool
                and _user_stripped in _NEGATIVE_TOKENS
            ):
                state.clear_pending_confirmation()
                logger.info(
                    "[CONFIRMATION] User rejected pending confirmation "
                    "with '%s' — cleared.",
                    user_input,
                )
                from bantz.brain.llm_router import OrchestratorOutput
                return (
                    OrchestratorOutput(
                        route="smalltalk",
                        calendar_intent="none",
                        slots={},
                        confidence=1.0,
                        tool_plan=[],
                        assistant_reply="Tamam, iptal ettim.",
                        raw_output={"confirmation_rejected": True},
                    ),
                    state,
                )

            # ── Issue #869 fix: When a confirmed_tool is set and there is a
            # pending confirmation, skip LLM planning entirely.  The prerouter
            # would otherwise intercept "evet" as AFFIRMATIVE/smalltalk and
            # return "Tamam, anlaşıldı" with preroute_complete=True, which
            # causes _execute_tools_phase to be skipped and the confirmed tool
            # to never execute.
            if (
                state.confirmed_tool
                and state.has_pending_confirmation()
            ):
                pending = state.peek_pending_confirmation() or {}
                pending_tool = str(pending.get("tool") or "").strip()
                pending_slots = pending.get("slots") or {}
                # Derive route/intent from the tool name (e.g. "calendar.create_event" → "calendar" / "create_event")
                _parts = pending_tool.split(".", 1)
                _derived_route = _parts[0] if _parts else "unknown"
                _derived_intent = _parts[1] if len(_parts) > 1 else "none"
                logger.info(
                    "[CONFIRMATION] Bypassing LLM planning — executing confirmed "
                    "tool %s directly.",
                    pending_tool,
                )
                from bantz.brain.llm_router import OrchestratorOutput
                orchestrator_output = OrchestratorOutput(
                    route=_derived_route,
                    calendar_intent=_derived_intent,
                    slots=pending_slots,
                    confidence=1.0,
                    tool_plan=[pending_tool] if pending_tool else [],
                    assistant_reply="",
                    raw_output={"confirmation_bypass": True, "confirmed_tool": pending_tool},
                )
            else:
                # Phase 1: LLM Planning (route, intent, tools, confirmation)
                orchestrator_output = self._llm_planning_phase(user_input, state)
            
            # Issue #837: Self-Evolving Agent — detect skill gaps
            if (
                orchestrator_output.route == "unknown"
                and not orchestrator_output.ask_user
                and orchestrator_output.confidence < 0.5
            ):
                try:
                    from bantz.skills.declarative.generator import get_self_evolving_manager
                    mgr = get_self_evolving_manager()
                    if mgr is not None:
                        gap = mgr.check_for_skill_gap(
                            user_input=user_input,
                            route=orchestrator_output.route,
                            confidence=orchestrator_output.confidence,
                        )
                        if gap is not None:
                            gen_result = mgr.generate_skill(gap)
                            if gen_result.success and gen_result.skill:
                                skill = gen_result.skill
                                orchestrator_output = replace(
                                    orchestrator_output,
                                    assistant_reply=(
                                        f"Bu isteği karşılayacak bir yeteneğim yok, ama "
                                        f"{skill.metadata.icon} **{skill.name}** adında bir skill "
                                        f"oluşturdum.\n\n"
                                        f"📝 {skill.metadata.description}\n\n"
                                        f"Kurmamı ister misiniz? "
                                        f"(**evet** / **hayır**)"
                                    ),
                                    raw_output={
                                        **orchestrator_output.raw_output,
                                        "skill_gap_detected": True,
                                        "generated_skill": gen_result.to_dict(),
                                    },
                                    ask_user=True,
                                )
                                logger.info(
                                    "[Issue #837] Skill gap → generated %r, awaiting approval",
                                    skill.name,
                                )
                except Exception as exc:
                    logger.debug("[Issue #837] Self-evolving check failed: %s", exc)

            # Issue #407: Full preroute bypass → skip tools + finalization
            if orchestrator_output.raw_output.get("preroute_complete"):
                final_output = orchestrator_output
                tool_results = []
            else:
                # Phase 2: Tool Execution (with confirmation firewall)
                tool_results = self._execute_tools_phase(orchestrator_output, state)

                # Phase 2.5: Verify tool results (Issue #591 / #523)
                tool_results = self._verify_results_phase(tool_results, state)

                # Phase 3: LLM Finalization (generate final response with tool results)
                final_output = self._llm_finalization_phase(
                    user_input,
                    orchestrator_output,
                    tool_results,
                    state,
                )

            # Phase 4: Update State (rolling summary, conversation history, trace)
            self._update_state_phase(user_input, final_output, tool_results, state)
            
            # Emit turn end event
            elapsed = time.time() - start_time
            self.event_bus.publish("turn.end", {
                "elapsed_ms": int(elapsed * 1000),
                "route": final_output.route,
                "intent": final_output.calendar_intent,
                "confidence": final_output.confidence,
            })

            # Issue #664: Structured trace export (per turn)
            try:
                from bantz.brain.trace_exporter import build_turn_trace, write_turn_trace
                turn_trace = build_turn_trace(
                    turn_id=state.turn_count,
                    user_input=user_input,
                    output=final_output,
                    tool_results=tool_results,
                    state_trace=state.trace,
                    total_elapsed_ms=int(elapsed * 1000),
                )
                write_turn_trace(turn_trace)
            except Exception as exc:
                logger.debug("[TRACE] Export failed: %s", exc)

            # Issue #1012: Record potential misroutes for dataset collection
            try:
                record_turn_misroute(
                    user_input=user_input,
                    route=final_output.route,
                    intent=final_output.calendar_intent or final_output.gmail_intent,
                    confidence=final_output.confidence,
                    tool_plan=final_output.tool_plan or [],
                    tool_results=tool_results,
                    original_route=getattr(orchestrator_output, "route", None)
                    if orchestrator_output.route != final_output.route else None,
                    model_name=getattr(self.orchestrator, "model_name", ""),
                )
            except Exception as exc:
                logger.debug("[MISROUTE] Recording failed: %s", exc)
            
            return final_output, state
        
        except Exception as e:
            logger.exception(f"Orchestrator turn failed: {e}")
            self.event_bus.publish(EventType.ERROR.value, {"error": str(e)})
            
            # Return fallback output
            from bantz.brain.llm_router import OrchestratorOutput
            fallback = OrchestratorOutput(
                route="unknown",
                calendar_intent="none",
                slots={},
                confidence=0.0,
                tool_plan=[],
                assistant_reply="Efendim, bir sorun oluştu. Lütfen tekrar deneyin.",
                raw_output={"error": str(e)},
            )
            return fallback, state

    # ---------------------------------------------------------------------
    # Backward-compat / test helper
    # ---------------------------------------------------------------------
    def run_full_cycle(
        self,
        user_input: str,
        confirmation_token: Optional[str] = None,
        state: Optional[OrchestratorState] = None,
    ) -> dict[str, Any]:
        """Run a full orchestration cycle and return a trace dict.

        This is a backward-compat shim used by golden regression tests.

                Notes:
                - If a destructive tool requires confirmation, the first cycle will add
                    to `state.pending_confirmations` and not execute the tool.
                - If `confirmation_token` is provided and a pending confirmation exists,
                    we attempt a second execution pass for the next queued confirmation.
        """
        if state is None:
            state = OrchestratorState()

        start_time = time.time()

        # Phase 1: plan
        orchestrator_output = self._llm_planning_phase(user_input, state)

        # Issue #407: Full preroute bypass → skip tools + finalization
        if orchestrator_output.raw_output.get("preroute_complete"):
            final_output = orchestrator_output
            tool_results = []
        else:
            # Phase 2: execute tools
            tool_results = self._execute_tools_phase(orchestrator_output, state)

            # Phase 2.5: verify
            tool_results = self._verify_results_phase(tool_results, state)

            # Phase 3: finalize
            final_output = self._llm_finalization_phase(
                user_input,
                orchestrator_output,
                tool_results,
                state,
            )

        # Phase 4: update state
        self._update_state_phase(user_input, final_output, tool_results, state)

        # Optional: if confirmation was requested and user provided a token,
        # attempt to execute the pending tool immediately.
        if confirmation_token is not None and state.has_pending_confirmation():
            pending = state.peek_pending_confirmation() or {}
            pending_tool = str(pending.get("tool") or "").strip()

            if self.safety_guard and pending_tool:
                accepted, _reason = self.safety_guard.check_confirmation_token(
                    pending_tool,
                    confirmation_token,
                )
            else:
                # Best-effort: accept only obvious "yes" tokens.
                accepted = str(confirmation_token).strip().lower() in {"yes", "y", "evet", "e", "1", "ok", "tamam"}

            if accepted:
                # Mark the pending tool as confirmed for this execution pass.
                state.confirmed_tool = pending_tool or None
                # Second execution pass: execute only the confirmed tool.
                tool_results_2 = self._execute_tools_phase(orchestrator_output, state)
                tool_results_2 = self._verify_results_phase(tool_results_2, state)
                final_output = self._llm_finalization_phase(
                    user_input,
                    orchestrator_output,
                    tool_results_2,
                    state,
                )
                self._update_state_phase(user_input, final_output, tool_results_2, state)
                tool_results = tool_results_2
            else:
                # User rejected/unclear: clear all pending confirmations and return.
                state.clear_pending_confirmation()

        # Build a trace dict in the format expected by regression tests.
        tools_attempted = len(tool_results)
        tools_executed = sum(1 for r in tool_results if r.get("success") is True)
        tools_success_names = [
            str(r.get("tool") or "")
            for r in tool_results
            if r.get("success") is True and r.get("tool")
        ]

        policy_violation = False
        violation_type: Optional[str] = None
        for r in tool_results:
            if r.get("success") is True:
                continue
            err = str(r.get("error") or "")
            tool_name = str(r.get("tool") or "")
            if self.safety_guard and tool_name in getattr(self.safety_guard.policy, "denylist", set()):
                policy_violation = True
                violation_type = "denylist"
                break
            if "not in allowlist" in err:
                policy_violation = True
                violation_type = "allowlist"
                break
            if "denied by policy" in err:
                policy_violation = True
                violation_type = "policy"
                break

        trace: dict[str, Any] = {
            "route": final_output.route,
            "calendar_intent": final_output.calendar_intent,
            "confidence": final_output.confidence,
            "tool_plan_len": len(final_output.tool_plan),
            "tools_attempted": tools_attempted,
            "tools_executed": tools_executed,
            # Regression tests expect this to be iterable of strings.
            "tools_success": tools_success_names,
            "requires_confirmation": bool(final_output.requires_confirmation),
            # Include final_output for terminal jarvis to access assistant_reply
            "final_output": {
                "assistant_reply": final_output.assistant_reply,
                "route": final_output.route,
                "calendar_intent": final_output.calendar_intent,
                "confidence": final_output.confidence,
                "tool_plan": final_output.tool_plan,
                "requires_confirmation": final_output.requires_confirmation,
                "confirmation_prompt": final_output.confirmation_prompt,
                "reasoning_summary": final_output.reasoning_summary,
            },
        }

        if final_output.confirmation_prompt:
            trace["confirmation_prompt"] = final_output.confirmation_prompt

        if policy_violation:
            trace["policy_violation"] = True
            trace["violation_type"] = violation_type or "policy"

        # Issue #664: Structured trace export for replay/regression
        try:
            from bantz.brain.trace_exporter import build_turn_trace, write_turn_trace
            elapsed_ms = int((time.time() - start_time) * 1000)
            turn_trace = build_turn_trace(
                turn_id=state.turn_count,
                user_input=user_input,
                output=final_output,
                tool_results=tool_results,
                state_trace=state.trace,
                total_elapsed_ms=elapsed_ms,
            )
            write_turn_trace(turn_trace)
        except Exception as exc:
            logger.debug("[TRACE] Export failed: %s", exc)

        return trace
    
    def _llm_planning_phase(
        self,
        user_input: str,
        state: OrchestratorState,
    ) -> OrchestratorOutput:
        """Phase 1: LLM Planning (route, intent, tools, confirmation).
        
        LLM receives:
        - User input
        - Rolling summary (if any)
        - Recent conversation history
        - Last tool results
        
        LLM returns:
        - Orchestrator output (route, intent, tools, confirmation, reasoning)
        """
        # Issue #407: Pre-route check — bypass LLM for obvious patterns
        preroute_match = None
        _preroute_hint = None

        if self.config.enable_preroute:
            preroute_match = self.prerouter.route(
                user_input,
                has_pending_confirmation=state.has_pending_confirmation(),
            )
        else:
            from bantz.routing.preroute import PreRouteMatch
            preroute_match = PreRouteMatch.no_match()

        if preroute_match.should_bypass(min_confidence=0.9):
            intent = preroute_match.intent
            handler_type = intent.handler_type

            if handler_type == "local":
                # Greeting, farewell, thanks, smalltalk → local reply, skip 3B + Gemini
                reply = self._local_responder.generate(intent)
                output = OrchestratorOutput(
                    route="smalltalk",
                    calendar_intent="none",
                    slots={},
                    confidence=preroute_match.confidence,
                    tool_plan=[],
                    assistant_reply=reply,
                    raw_output={
                        "preroute": True,
                        "preroute_complete": True,
                        "rule": preroute_match.rule_name,
                        "intent": intent.value,
                    },
                )
                self.event_bus.publish("preroute.bypass", {
                    "intent": intent.value,
                    "confidence": preroute_match.confidence,
                    "rule": preroute_match.rule_name,
                    "handler_type": handler_type,
                })
                logger.info(
                    "[PREROUTE] Bypass LLM: intent=%s conf=%.2f rule=%s",
                    intent.value, preroute_match.confidence, preroute_match.rule_name,
                )
                return output

            elif handler_type == "system":
                # Time/date/screenshot → system route with tool plan, skip 3B only
                _sys_tool_map = {
                    IntentCategory.TIME_QUERY: (["time.now"], "time"),
                    IntentCategory.DATE_QUERY: (["time.now"], "time"),
                    IntentCategory.SCREENSHOT: (["system.screenshot"], "query"),
                }
                if intent in _sys_tool_map:
                    tools, cal_intent = _sys_tool_map[intent]
                    output = OrchestratorOutput(
                        route="system",
                        calendar_intent=cal_intent,
                        slots={},
                        confidence=preroute_match.confidence,
                        tool_plan=tools,
                        assistant_reply="",
                        raw_output={
                            "preroute": True,
                            "rule": preroute_match.rule_name,
                            "intent": intent.value,
                        },
                    )
                    self.event_bus.publish("preroute.bypass", {
                        "intent": intent.value,
                        "confidence": preroute_match.confidence,
                        "rule": preroute_match.rule_name,
                        "handler_type": handler_type,
                    })
                    logger.info(
                        "[PREROUTE] Bypass LLM (system): intent=%s conf=%.2f rule=%s",
                        intent.value, preroute_match.confidence, preroute_match.rule_name,
                    )
                    return output

                # Unknown system tool (volume, brightness, etc.): fall through

            # Issue #650: Destructive intents (calendar create/delete/update)
            # are never bypassed — they always fall through to LLM planning
            # so that safety guard and confirmation firewall remain active.
            if preroute_match.intent.is_destructive:
                logger.info(
                    "[PREROUTE] Destructive intent blocked from bypass: "
                    "intent=%s conf=%.2f rule=%s → routing to LLM",
                    preroute_match.intent.value,
                    preroute_match.confidence,
                    preroute_match.rule_name,
                )
                self.event_bus.publish("preroute.destructive_blocked", {
                    "intent": preroute_match.intent.value,
                    "confidence": preroute_match.confidence,
                    "rule": preroute_match.rule_name,
                })

        # Issue #407: Prepare preroute hint for medium-confidence or calendar bypass
        if preroute_match.matched and preroute_match.confidence >= 0.5:
            _preroute_hint = {
                "preroute_intent": preroute_match.intent.value,
                "preroute_confidence": round(preroute_match.confidence, 2),
                "preroute_rule": preroute_match.rule_name,
            }
            # Issue #948: Inject extracted slots from PreRouter into hint
            # CalendarListRule extracts date/time/window_hint via nlu/slots.py
            if preroute_match.extracted:
                _preroute_hint["extracted"] = preroute_match.extracted
            self.event_bus.publish("preroute.hint", {
                "intent": preroute_match.intent.value,
                "confidence": preroute_match.confidence,
                "rule": preroute_match.rule_name,
            })
            if self.config.debug:
                logger.debug(
                    "[PREROUTE] Hint: intent=%s conf=%.2f",
                    preroute_match.intent.value, preroute_match.confidence,
                )

        # Build context for LLM
        context = state.get_context_for_llm()
        conversation_history = context.get("recent_conversation", [])
        tool_results = context.get("last_tool_results", [])

        # Issue #1010: Context assembly delegated to ContextBuilder
        _is_smalltalk_preroute = (
            preroute_match is not None
            and preroute_match.matched
            and preroute_match.intent.handler_type == "local"
        )
        _ctx_result = self._context_builder.build(
            user_input=user_input,
            conversation_history=conversation_history,
            tool_results=tool_results,
            state=state,
            is_smalltalk=_is_smalltalk_preroute,
            memory_tracer=getattr(self, "_memory_tracer", None),
        )
        enhanced_summary = _ctx_result.enhanced_summary
        dialog_summary = _ctx_result.dialog_summary

        # Issue #599: Publish memory injection diagnostics and store in trace
        if getattr(self, "_memory_tracer", None) is not None:
            try:
                rec = self._memory_tracer.end_turn()
            except Exception:
                rec = None
            if rec is not None:
                try:
                    state.trace.setdefault("memory_trace", []).append(rec.to_trace_line())
                except Exception:
                    pass
                try:
                    self.event_bus.publish(
                        "memory.injected",
                        {
                            "turn_number": rec.turn_number,
                            "memory_injected": rec.memory_injected,
                            "memory_tokens": rec.memory_tokens,
                            "memory_turns_count": rec.memory_turns_count,
                            "was_trimmed": rec.was_trimmed,
                            "trim_reason": rec.trim_reason,
                            "memory_preview": (dialog_summary or "")[:200],
                        },
                    )
                except Exception:
                    pass
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] LLM Planning Phase:")
            logger.debug(f"  User: {user_input}")
            logger.debug(f"  Dialog Summary (memory-lite): {dialog_summary or 'None'}")
            logger.debug(f"  Recent History: {len(conversation_history)} turns")
            logger.debug(f"  Tool Results: {len(tool_results)}")
        
        # Issue #417: Use cached session context from state (built once in process_turn)
        # Issue #359: state.session_context is always set by process_turn (or externally)
        session_context = state.session_context
        if not session_context:
            # Fallback: build fresh if somehow missing (e.g. direct _llm_planning_phase call)
            sid = id(state)
            if sid not in self._session_ctx_caches:
                from bantz.brain.session_context_cache import SessionContextCache
                self._session_ctx_caches[sid] = SessionContextCache(ttl_seconds=self._session_ctx_ttl)
            session_context = self._session_ctx_caches[sid].get_or_build()
            state.session_context = session_context
        
        # Issue #339: Add recent conversation for anaphora / multi-turn
        if state.conversation_history:
            session_context["recent_conversation"] = state.conversation_history[-3:]

        # Issue #407: Merge preroute hint into session_context
        if _preroute_hint:
            session_context["preroute_hint"] = _preroute_hint

        # Issue #938: Run NLU slot extraction BEFORE LLM router
        # Extracts Turkish time/date, URLs, app names, queries, positions
        # and injects them as pre-parsed hints so the 3B model doesn't hallucinate.
        try:
            _nlu_slots = self._slot_extractor.extract_all(user_input)
            if _nlu_slots:
                _flat_slots = self._slot_extractor.to_flat_dict(_nlu_slots)
                # Serialize datetime objects to ISO strings for JSON compat
                _serialized: dict[str, Any] = {}
                for _sk, _sv in _flat_slots.items():
                    if hasattr(_sv, "isoformat"):
                        _serialized[_sk] = _sv.isoformat()
                    elif hasattr(_sv, "__str__") and not isinstance(_sv, (str, int, float, bool)):
                        _serialized[_sk] = str(_sv)
                    else:
                        _serialized[_sk] = _sv
                session_context["nlu_slots"] = _serialized
                self.event_bus.publish("nlu.slots_extracted", {
                    "slots": _serialized,
                    "source": "nlu/slots.py",
                })
                logger.info(
                    "[NLU] Pre-extracted slots: %s",
                    ", ".join(f"{k}={v}" for k, v in _serialized.items()),
                )
        except Exception as _slot_exc:
            logger.debug("[NLU] Slot extraction failed (non-fatal): %s", _slot_exc)

        # Call orchestrator with enhanced summary + session context
        output = self.orchestrator.route(
            user_input=user_input,
            dialog_summary=enhanced_summary,
            session_context=session_context,
        )

        # Issue #938: Merge NLU pre-extracted slots into LLM output
        # NLU slots (Turkish time parser etc.) are authoritative — LLM slots
        # are overridden only for keys that NLU confidently extracted.
        _nlu_merged = session_context.get("nlu_slots") or {}
        if _nlu_merged and output.slots is not None:
            for _nk, _nv in _nlu_merged.items():
                if _nk not in output.slots or not output.slots[_nk]:
                    output.slots[_nk] = _nv
            if "time" in _nlu_merged:
                # Time from NLU's Turkish parser is more reliable than LLM guess
                output.slots["time"] = _nlu_merged["time"]

        # Issue #607: Post-route correction for email sending.
        # The 3B router can misroute send-intents to smalltalk/unknown.
        output = self._post_route_correction_email_send(user_input, output)
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] LLM Decision:")
            logger.debug(f"  Route: {output.route}")
            logger.debug(f"  Intent: {output.calendar_intent}")
            logger.debug(f"  Confidence: {output.confidence:.2f}")
            logger.debug(f"  Tool Plan: {output.tool_plan}")
            logger.debug(f"  Ask User: {output.ask_user}")
            logger.debug(f"  Requires Confirmation: {output.requires_confirmation}")
            if output.reasoning_summary:
                logger.debug(f"  Reasoning: {output.reasoning_summary}")
        
        # Emit routing event
        self.event_bus.publish("llm.decision", {
            "route": output.route,
            "intent": output.calendar_intent,
            "confidence": output.confidence,
            "tool_plan": output.tool_plan,
            "requires_confirmation": output.requires_confirmation,
            "reasoning_summary": output.reasoning_summary,
        })
        
        # Issue #284: Emit granular trace events for step-by-step visualization
        self.event_bus.publish("intent.detected", {
            "route": output.route,
            "intent": output.calendar_intent,
            "confidence": output.confidence,
        })
        
        if output.slots:
            self.event_bus.publish("slots.extracted", {
                "slots": output.slots,
            })
        
        if output.tool_plan:
            self.event_bus.publish("tool.selected", {
                "tools": output.tool_plan,
            })
        
        # Issue #282: Force mandatory tools if LLM returned empty tool_plan
        output = self._force_tool_plan(output)

        # Issue #870: Sanitize tool_plan — remap hallucinated/mismatched tools
        output = self._sanitize_tool_plan(output)

        # Issue #907: Static plan verification
        from bantz.brain.llm_router import _VALID_TOOLS
        plan_ok, plan_errors = verify_plan(
            output.__dict__ if hasattr(output, "__dict__") else vars(output),
            user_input,
            _VALID_TOOLS,
        )
        if not plan_ok:
            logger.warning("[PLAN_VERIFIER] errors=%s — falling back to ask_user", plan_errors)
            # For hard errors (unknown tool, missing slot) — ask user to clarify
            hard = [e for e in plan_errors if not e.startswith("tool_plan_no_indicators")]
            if hard:
                output = replace(output, ask_user=True, question="Anlayamadım, tekrar eder misin?")

        return output

    # Issue #941: Static email helpers and _post_route_correction_email_send
    # extracted to bantz.brain.post_route_corrections.  Thin wrappers kept.

    _looks_like_email_send_intent = staticmethod(looks_like_email_send_intent)
    _extract_first_email = staticmethod(extract_first_email)
    _extract_recipient_name = staticmethod(extract_recipient_name)
    _extract_message_body_hint = staticmethod(extract_message_body_hint)

    def _post_route_correction_email_send(
        self,
        user_input: str,
        output: OrchestratorOutput,
    ) -> OrchestratorOutput:
        return post_route_correction_email_send(
            user_input, output, debug=self.config.debug,
        )

    def _verify_results_phase(
        self,
        tool_results: list[dict[str, Any]],
        state: OrchestratorState,
    ) -> list[dict[str, Any]]:
        """Phase 2.5: Verify tool results (Plan→Act→Verify loop).

        This runs lightweight validation on tool results and performs a
        best-effort single retry for non-destructive tools.
        """
        if not tool_results:
            return tool_results

        try:
            from bantz.brain.verify_results import VerifyConfig, verify_tool_results
        except Exception:
            # If the verify module isn't available for any reason, proceed.
            return tool_results

        def _retry_fn(tool_name: str, original: dict[str, Any]) -> dict[str, Any]:
            """Retry callback — safety/whitelist checks in verify_results."""
            try:
                tool = self.tools.get(tool_name)
                if tool is None or tool.function is None:
                    return original

                params = original.get("params")
                if not isinstance(params, dict):
                    params = {}

                timeout = self.config.tool_timeout_seconds

                try:
                    future = self._tool_executor.submit(tool.function, **params)
                    result = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    return {
                        **original,
                        "success": False,
                        "error": f"Tool '{tool_name}' timed out after {timeout:.0f}s",
                        "raw_result": None,
                        "result_summary": f"timeout after {timeout:.0f}s",
                    }

                tool_returned_ok = True
                tool_error: Optional[str] = None
                if isinstance(result, dict) and result.get("ok") is False:
                    tool_returned_ok = False
                    err_val = result.get("error")
                    tool_error = str(err_val) if err_val is not None else "tool_returned_ok_false"

                risk_level = None
                try:
                    risk_level = get_tool_risk(tool_name).value
                except Exception:
                    risk_level = original.get("risk_level")

                return {
                    "tool": tool_name,
                    "success": bool(tool_returned_ok),
                    "raw_result": result,
                    "result_summary": _summarize_tool_result(result, max_items=5, max_chars=500),
                    "error": tool_error,
                    "risk_level": risk_level,
                    "params": params,
                }
            except Exception:
                return original

        vr = verify_tool_results(
            tool_results,
            config=VerifyConfig(),
            retry_fn=_retry_fn,
        )

        # Trace + event for observability
        try:
            if isinstance(getattr(state, "trace", None), dict):
                state.trace["verify"] = {
                    "verified": vr.verified,
                    "tools_ok": vr.tools_ok,
                    "tools_retry": vr.tools_retry,
                    "tools_fail": vr.tools_fail,
                    "elapsed_ms": vr.elapsed_ms,
                }
        except Exception:
            pass

        try:
            self.event_bus.publish("tool.verify", {
                "verified": vr.verified,
                "tools_ok": vr.tools_ok,
                "tools_retry": vr.tools_retry,
                "tools_fail": vr.tools_fail,
                "elapsed_ms": vr.elapsed_ms,
            })
        except Exception:
            pass

        return vr.verified_results
    
    def _execute_tools_phase(
        self,
        output: OrchestratorOutput,
        state: OrchestratorState,
    ) -> list[dict[str, Any]]:
        """Phase 2: Tool Execution (with safety guards & confirmation firewall).
        
        Safety guards (Issue #140):
        - Tool allowlist/denylist check
        - Route-tool match validation (no tools for smalltalk)
        - Argument schema validation
        - Confirmation firewall for destructive ops
        
        Returns:
            List of tool results
        """
        # Issue #351: Confirmation queue support — check BEFORE early return.
        # When user confirms a pending destructive tool, the new LLM pass may
        # produce an empty tool_plan (since input is just "evet").  We must
        # still execute the confirmed tool, so handle confirmation first.
        confirmed_override_tool: Optional[str] = None
        if state.has_pending_confirmation():
            pending = state.peek_pending_confirmation() or {}
            pending_tool = str(pending.get("tool") or "").strip()

            if state.confirmed_tool and pending_tool and pending_tool == state.confirmed_tool:
                # Confirmation accepted for the head of the queue.
                confirmed_override_tool = pending_tool
                state.pop_pending_confirmation()
                state.confirmed_tool = None
                logger.info("[FIREWALL] Confirmation accepted for %s — executing.", pending_tool)
            else:
                prompt = str(pending.get("prompt") or "Confirm to continue")
                logger.warning(
                    f"[FIREWALL] Cannot execute tools - confirmation pending for {pending_tool}. "
                    f"User must confirm first."
                )
                return [{
                    "tool": "blocked",
                    "success": False,
                    "error": f"Confirmation required for {pending_tool}: {prompt}",
                    "pending_confirmation": True,
                    "confirmation_prompt": prompt,
                }]

        if not output.tool_plan and not confirmed_override_tool:
            return []

        # Support both legacy `tool_plan: ["tool.name", ...]` and richer
        # forms emitted by some tests/models: `tool_plan: [{"name": ..., "args": {...}}, ...]`.
        tool_args_by_name: dict[str, dict[str, Any]] = {}
        raw_plan = getattr(output, "raw_output", None)
        if isinstance(raw_plan, dict):
            raw_entries = raw_plan.get("tool_plan")
            if isinstance(raw_entries, list):
                for entry in raw_entries:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("name") or entry.get("tool") or entry.get("tool_name") or "").strip()
                    args = entry.get("args")
                    if name and isinstance(args, dict):
                        tool_args_by_name[name] = args
        
        # Safety Guard: Filter tool plan based on route
        filtered_tool_plan = output.tool_plan
        if self.safety_guard and not confirmed_override_tool:
            filtered_tool_plan, violations = self.safety_guard.filter_tool_plan(
                route=output.route,
                tool_plan=output.tool_plan,
            )
            
            if violations:
                for violation in violations:
                    logger.warning(f"[SAFETY] Tool plan violation: {violation.reason}")
                    self.safety_guard.audit_decision(
                        decision_type="filter_tool_plan",
                        tool_name=violation.tool_name,
                        allowed=False,
                        reason=violation.reason,
                        metadata=violation.metadata,
                    )
        elif confirmed_override_tool:
            filtered_tool_plan = [confirmed_override_tool]
        
        tool_results = []


        # If no confirmation is pending AND we're not executing a confirmed tool,
        # pre-scan tool_plan and queue all confirmations in order.
        if not state.has_pending_confirmation() and not confirmed_override_tool:
            try:
                from bantz.tools.metadata import (
                    get_tool_risk,
                    is_destructive,
                    requires_confirmation as check_confirmation,
                    get_confirmation_prompt,
                )

                confirmations_to_queue: list[dict[str, Any]] = []
                for tool_name in filtered_tool_plan:
                    needs_confirmation = check_confirmation(
                        tool_name,
                        llm_requested=bool(output.requires_confirmation)
                    )
                    if needs_confirmation:
                        risk = get_tool_risk(tool_name)
                        prompt = get_confirmation_prompt(tool_name, output.slots)
                        confirmations_to_queue.append({
                            "tool": tool_name,
                            "prompt": prompt,
                            "slots": output.slots,
                            "risk_level": risk.value,
                        })

                        # Audit confirmation request
                        if self.safety_guard:
                            self.safety_guard.audit_decision(
                                decision_type="confirmation_required",
                                tool_name=tool_name,
                                allowed=False,
                                reason=f"Destructive tool ({risk.value}) requires user confirmation",
                                metadata={"prompt": prompt, "params": output.slots},
                            )

                if confirmations_to_queue:
                    for confirmation in confirmations_to_queue:
                        state.add_pending_confirmation(confirmation)

                    first = state.peek_pending_confirmation() or {}
                    tool_results.append({
                        "tool": str(first.get("tool") or ""),
                        "success": False,
                        "pending_confirmation": True,
                        "risk_level": str(first.get("risk_level") or ""),
                        "confirmation_prompt": str(first.get("prompt") or ""),
                    })
                    return tool_results
            except Exception:
                # Best-effort: if pre-scan fails, fall back to existing logic.
                pass
        
        for tool_name in filtered_tool_plan:
            if self.config.debug:
                logger.debug(f"[ORCHESTRATOR] Executing tool: {tool_name}")
            
            # Safety Guard: Check tool allowlist/denylist
            if self.safety_guard:
                allowed, deny_reason = self.safety_guard.check_tool_allowed(tool_name)
                if not allowed:
                    logger.warning(f"[SAFETY] Tool '{tool_name}' denied: {deny_reason}")
                    self.safety_guard.audit_decision(
                        decision_type="tool_allowlist",
                        tool_name=tool_name,
                        allowed=False,
                        reason=deny_reason or "Policy violation",
                    )
                    tool_results.append({
                        "tool": tool_name,
                        "success": False,
                        "error": deny_reason,
                    })
                    continue
            
            # Confirmation firewall (Issue #160 - enhanced)
            # Import metadata module for risk classification
            from bantz.tools.metadata import (
                get_tool_risk,
                is_destructive,
                requires_confirmation as check_confirmation,
                get_confirmation_prompt,
            )
            
            risk = get_tool_risk(tool_name)
            needs_confirmation = check_confirmation(
                tool_name,
                llm_requested=bool(output.requires_confirmation)
            )

            was_confirmed = False
            if confirmed_override_tool and tool_name == confirmed_override_tool:
                # This tool was explicitly confirmed (queue head accepted).
                needs_confirmation = False
                was_confirmed = True

            if needs_confirmation:
                # FIREWALL: Destructive tools always need confirmation
                # Even if LLM didn't request it
                if is_destructive(tool_name) and not output.requires_confirmation:
                    logger.warning(
                        f"[FIREWALL] Tool {tool_name} is DESTRUCTIVE but LLM didn't request confirmation. "
                        f"Enforcing confirmation requirement (Issue #160)."
                    )

                # If we reach here, confirmation wasn't queued in pre-scan.
                # Queue it now and return a pending confirmation placeholder.
                prompt = get_confirmation_prompt(tool_name, output.slots)
                logger.info(f"[FIREWALL] Tool {tool_name} ({risk.value}) requires confirmation.")

                state.add_pending_confirmation({
                    "tool": tool_name,
                    "prompt": prompt,
                    "slots": output.slots,
                    "risk_level": risk.value,
                })

                tool_results.append({
                    "tool": tool_name,
                    "success": False,
                    "pending_confirmation": True,
                    "risk_level": risk.value,
                    "confirmation_prompt": prompt,
                })

                # Audit confirmation request
                if self.safety_guard:
                    self.safety_guard.audit_decision(
                        decision_type="confirmation_required",
                        tool_name=tool_name,
                        allowed=False,
                        reason=f"Destructive tool ({risk.value}) requires user confirmation",
                        metadata={"prompt": prompt, "params": output.slots},
                    )

                return tool_results
            
            # Get tool definition
            try:
                tool = self.tools.get(tool_name)
                if tool is None:
                    logger.error("[TOOLS] Tool not found in registry: %s", tool_name)
                    self.event_bus.publish("tool.not_found", {
                        "tool": tool_name,
                        "route": output.route,
                    })
                    tool_results.append({
                        "tool": tool_name,
                        "success": False,
                        "error": f"Efendim, '{tool_name}' işlemi şu an kullanılamıyor.",
                        "user_message": f"Efendim, '{tool_name}' işlemi şu an kullanılamıyor.",
                    })
                    continue
                
                if tool.function is None:
                    logger.warning(
                        "[TOOLS] Tool '%s' has no function impl (schema-only), skipping",
                        tool_name,
                    )
                    tool_results.append({
                        "tool": tool_name,
                        "success": False,
                        "error": f"'{tool_name}' henüz aktif değil (schema-only tool).",
                        "user_message": f"'{tool_name}' komutu şu an kullanılamıyor.",
                    })
                    continue
                
                # Build parameters: prefer explicit tool_plan args, else fall back to slots.
                args = tool_args_by_name.get(tool_name)
                if args is not None:
                    params = dict(output.slots)
                    params.update(args)
                else:
                    params = self._build_tool_params(tool_name, output.slots, output)

                # Drop nulls (LLM JSON often includes explicit nulls for optional slots).
                # Prevents spurious schema/type failures.
                if isinstance(params, dict):
                    params = {k: v for k, v in params.items() if v is not None}
                
                # Safety Guard: Validate tool arguments
                if self.safety_guard:
                    valid, error = self.safety_guard.validate_tool_args(tool, params)
                    if not valid:
                        logger.warning(f"[SAFETY] Tool '{tool_name}' args invalid: {error}")
                        self.safety_guard.audit_decision(
                            decision_type="arg_validation",
                            tool_name=tool_name,
                            allowed=False,
                            reason=error or "Invalid arguments",
                            metadata={"params": params},
                        )
                        tool_results.append({
                            "tool": tool_name,
                            "success": False,
                            "error": f"Invalid arguments: {error}",
                            "safety_rejected": True,
                            "params": params,
                            "elapsed_ms": 0,
                        })
                        continue
                
                # Execute tool (Issue #431: with timeout protection)
                timeout = self.config.tool_timeout_seconds
                try:
                    exec_start = time.time()
                    future = self._tool_executor.submit(tool.function, **params)
                    result = future.result(timeout=timeout)
                    elapsed_ms = int((time.time() - exec_start) * 1000)
                except concurrent.futures.TimeoutError:
                    elapsed_ms = int((time.time() - exec_start) * 1000) if "exec_start" in locals() else 0
                    logger.error(
                        "[TOOLS] Tool %s timed out after %.1fs",
                        tool_name, timeout,
                    )
                    self.event_bus.publish("tool.timeout", {
                        "tool": tool_name,
                        "timeout_seconds": timeout,
                    })
                    tool_results.append({
                        "tool": tool_name,
                        "success": False,
                        "error": f"Tool '{tool_name}' timed out after {timeout:.0f}s",
                        "user_message": f"Efendim, '{tool_name}' işlemi zaman aşımına uğradı. Lütfen tekrar deneyin.",
                        "risk_level": risk.value,
                        "params": params,
                        "elapsed_ms": elapsed_ms,
                    })
                    state.add_tool_result(tool_name, f"timeout after {timeout}s", success=False)
                    continue

                # Convention: tool functions often return a tool-friendly dict
                # like {"ok": bool, "error": ...}. Treat ok=false as failure so
                # the finalization phase can render a deterministic error.
                tool_returned_ok = True
                tool_error: Optional[str] = None
                if isinstance(result, dict) and result.get("ok") is False:
                    tool_returned_ok = False
                    err_val = result.get("error")
                    tool_error = str(err_val) if err_val is not None else "tool_returned_ok_false"

                # Issue #353: Preserve structured data + smart summarization
                # Store both raw_result (for finalizer LLM) and result_summary (for logs)
                result_summary = _summarize_tool_result(result, max_items=5, max_chars=500)
                
                tool_results.append({
                    "tool": tool_name,
                    "success": bool(tool_returned_ok),
                    "raw_result": result,  # ✅ Original structured data
                    "result_summary": result_summary,  # ✅ Smart summary for display
                    "error": tool_error,
                    "risk_level": risk.value,
                    "params": params,
                    "elapsed_ms": elapsed_ms,
                })

                # Add to state
                state.add_tool_result(tool_name, result, success=bool(tool_returned_ok))
                
                # Audit successful execution (Issue #160)
                if self.audit_logger:
                    try:
                        from bantz.tools.metadata import get_tool_risk
                        risk_level = get_tool_risk(tool_name)
                        self.audit_logger.log_tool_execution(
                            tool_name=tool_name,
                            risk_level=risk_level.value,
                            success=True,
                            confirmed=was_confirmed,  # Issue #352: Use tracked confirmation flag
                            params=params,
                            result=result,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log tool execution: {e}")
                
                # Audit successful execution (Safety Guard)
                if self.safety_guard:
                    self.safety_guard.audit_decision(
                        decision_type="tool_execute",
                        tool_name=tool_name,
                        allowed=True,
                        reason="Tool executed successfully",
                        metadata={"params": params, "risk_level": risk.value},
                    )
                
                # Emit tool event
                self.event_bus.publish("tool.call", {
                    "tool": tool_name,
                    "params": params,
                    "result": str(result)[:200],
                })
                
            except Exception as e:
                logger.exception(f"Tool {tool_name} failed: {e}")
                tool_results.append({
                    "tool": tool_name,
                    "success": False,
                    "error": str(e),
                    "risk_level": risk.value,
                    "params": params if "params" in locals() else {},
                    "elapsed_ms": 0,
                })
                state.add_tool_result(tool_name, str(e), success=False)
                
                # Audit failed execution (Issue #160)
                if self.audit_logger:
                    try:
                        from bantz.tools.metadata import get_tool_risk
                        risk_level = get_tool_risk(tool_name)
                        self.audit_logger.log_tool_execution(
                            tool_name=tool_name,
                            risk_level=risk_level.value,
                            success=False,
                            confirmed=False,
                            error=str(e),
                            params=params if 'params' in locals() else None,
                        )
                    except Exception as audit_err:
                        logger.warning(f"Failed to log tool execution error: {audit_err}")
        
        return tool_results
    
    # Issue #941: _build_tool_params extracted to bantz.brain.tool_param_builder
    def _build_tool_params(
        self,
        tool_name: str,
        slots: dict[str, Any],
        output: Optional["OrchestratorOutput"] = None,
    ) -> dict[str, Any]:
        return build_tool_params(tool_name, slots, output)
    
    def _llm_finalization_phase(
        self,
        user_input: str,
        orchestrator_output: OrchestratorOutput,
        tool_results: list[dict[str, Any]],
        state: OrchestratorState,
    ) -> OrchestratorOutput:
        """Phase 3: LLM Finalization — delegates to ``FinalizationPipeline``.

        Issue #404: Extracted from 300-line monolith into Strategy pattern.
        See ``bantz.brain.finalization_pipeline`` for the full pipeline.
        """
        from bantz.brain.finalization_pipeline import (
            build_finalization_context,
        )

        # Issue #874: Build personality block for finalizer prompt
        _personality_block: Optional[str] = None
        try:
            if hasattr(self, "personality_injector") and self.personality_injector:
                _pi = self.personality_injector
                # Gather user facts/preferences from user_memory if available
                _fin_facts: dict = {}
                _fin_prefs: dict = {}
                if hasattr(self, "user_memory") and self.user_memory:
                    try:
                        _um_data = self.user_memory.on_turn_start(user_input)
                        _fin_facts = _um_data.get("facts", {}) if isinstance(_um_data, dict) else {}
                        # Extract preferences from profile_context
                        _pc = _um_data.get("profile_context", "") if isinstance(_um_data, dict) else ""
                        if "tercih" in str(_pc).lower() or "preference" in str(_pc).lower():
                            _fin_prefs = {"raw_context": str(_pc)[:300]}
                    except Exception:
                        pass
                _personality_block = _pi.build_finalizer_block(
                    user_name=getattr(_pi, "_config", None) and _pi._config.user_name or None,
                    facts=_fin_facts,
                    preferences=_fin_prefs,
                )
        except Exception:
            _personality_block = None

        ctx = build_finalization_context(
            user_input=user_input,
            orchestrator_output=orchestrator_output,
            tool_results=tool_results,
            state=state,
            memory=self.memory,
            finalizer_llm=self.finalizer_llm,
            personality_block=_personality_block,
        )

        pipeline = self._get_finalization_pipeline()

        return pipeline.run(ctx)
    
    def _update_state_phase(
        self,
        user_input: str,
        output: OrchestratorOutput,
        tool_results: list[dict[str, Any]],
        state: OrchestratorState,
    ) -> None:
        """Phase 4: Update State (memory-lite summary, conversation history, trace).
        
        Updates:
        - Memory-lite summary (Issue #141)
        - Rolling summary (from LLM's memory_update - legacy)
        - Conversation history (user + assistant)
        - Trace metadata (for testing/debugging)
        """
        # Update memory-lite (Issue #141)
        summary = CompactSummary(
            turn_number=state.turn_count + 1,
            user_intent=self._extract_user_intent(user_input, output),
            action_taken=self._extract_action_taken(output),
            pending_items=self._extract_pending_items(output),
        )
        self.memory.add_turn(summary)

        # Issue #873: Persistent user memory — learn from interaction
        if getattr(self, "user_memory", None) is not None:
            try:
                self.user_memory.on_turn_end(
                    user_input=user_input,
                    assistant_reply=output.assistant_reply or "",
                    route=output.route or "",
                    tool_results=tool_results,
                )
            except Exception as _um_exc:
                logger.debug("[ORCHESTRATOR] user_memory.on_turn_end failed: %s", _um_exc)
        
        # Update rolling summary (legacy - for backward compatibility)
        if output.memory_update:
            # Append to existing summary
            if state.rolling_summary:
                new_summary = f"{state.rolling_summary}\n{output.memory_update}"
            else:
                new_summary = output.memory_update
            
            # Keep summary under 500 chars
            if len(new_summary) > 500:
                new_summary = new_summary[-500:]
            
            state.update_rolling_summary(new_summary)
        
        # Add conversation turn
        state.add_conversation_turn(user_input, output.assistant_reply)
        
        # Update trace
        success_count = sum(1 for r in tool_results if r.get("success", False))
        # Best-effort capture of which models were used.
        planner_llm = getattr(self.orchestrator, "_llm", None)
        planner_model = getattr(planner_llm, "model_name", None) if planner_llm is not None else None
        planner_backend = getattr(planner_llm, "backend_name", None) if planner_llm is not None else None

        finalizer_model = getattr(self.finalizer_llm, "model_name", None) if self.finalizer_llm is not None else None
        finalizer_backend = getattr(self.finalizer_llm, "backend_name", None) if self.finalizer_llm is not None else None

        # Issue #517: Also capture which finalizer strategy was actually used
        prior_strategy = str(state.trace.get("finalizer_strategy") or "").strip()
        finalizer_strategy = prior_strategy or (getattr(output, "finalizer_model", "") or "")

        state.update_trace(
            route_source="llm",  # Everything comes from LLM now
            route=output.route,
            intent=output.calendar_intent,
            calendar_intent=output.calendar_intent,
            confidence=output.confidence,
            tool_plan_len=len(output.tool_plan),
            tools_attempted=len(tool_results),
            tools_executed=success_count,  # Only successful tools
            tools_success=[r.get("success", False) for r in tool_results],
            requires_confirmation=output.requires_confirmation,
            ask_user=output.ask_user,
            reasoning_summary=output.reasoning_summary,
            planner_model=planner_model,
            planner_backend=planner_backend,
            finalizer_model=finalizer_model,
            finalizer_backend=finalizer_backend,
            finalizer_strategy=finalizer_strategy,
        )

        # Issue #662: Tier decision trace (router vs finalizer)
        response_tier = str(state.trace.get("response_tier") or "").strip().lower()
        tier_reason = str(state.trace.get("response_tier_reason") or "").strip()

        planner_model_l = str(planner_model or "").lower()
        planner_backend_l = str(planner_backend or "").lower()
        router_label = "gemini" if ("gemini" in planner_model_l or planner_backend_l == "gemini") else "3b"

        if response_tier == "quality":
            if str(finalizer_strategy or "").strip().lower() == "fast_fallback":
                finalizer_label = "3b_fallback"
            else:
                finalizer_label = "gemini"
        else:
            finalizer_label = "3b"

        state.update_trace(
            tier_decision={
                "router": router_label,
                "finalizer": finalizer_label,
                "reason": tier_reason or "unknown",
            }
        )
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] State Updated:")
            logger.debug(f"  Rolling Summary: {state.rolling_summary[:100] if state.rolling_summary else 'None'}...")
            logger.debug(f"  Memory-lite: {len(self.memory)} turns")
            logger.debug(f"  Conversation Turns: {len(state.conversation_history)}")
            logger.debug(f"  Tool Results: {len(state.last_tool_results)}")

        # Advance turn counter (used by memory-lite summaries)
        state.turn_count += 1
    
    # =========================================================================
    # Memory-lite Helper Methods (Issue #141)
    # =========================================================================
    
    def _extract_user_intent(self, user_input: str, output: OrchestratorOutput) -> str:
        """Extract concise user intent (1-3 words).

        Issue #944: Uses the generic `intent` property so all routes are covered.
        """
        route = (output.route or "").lower()
        intent = output.intent  # generic accessor

        if route == "calendar":
            return f"asked about {intent}"
        elif route == "gmail":
            return f"email {intent}"
        elif route == "system":
            return f"system {intent}"
        elif route == "smalltalk":
            if any(word in user_input.lower() for word in ["merhaba", "selam", "hey", "nasılsın"]):
                return "greeted"
            elif any(word in user_input.lower() for word in ["kendini tanıt", "kimsin"]):
                return "asked about identity"
            else:
                return "casual chat"
        else:
            return f"request ({intent})"
    
    def _extract_action_taken(self, output: OrchestratorOutput) -> str:
        """Extract action taken (1-3 words)."""
        if output.tool_plan:
            # Summarize tools
            tool_names = [t.split(".")[-1] for t in output.tool_plan[:2]]  # First 2
            tools_str = ", ".join(tool_names)
            return f"called {tools_str}"
        elif output.ask_user:
            return "asked for clarification"
        elif output.assistant_reply:
            return "responded with chat"
        else:
            return "acknowledged"
    
    def _extract_pending_items(self, output: OrchestratorOutput) -> list[str]:
        """Extract pending items from output."""
        pending = []
        if output.requires_confirmation:
            pending.append("waiting for confirmation")
        if output.ask_user and output.question:
            # Truncate question
            question_short = output.question[:30] + "..." if len(output.question) > 30 else output.question
            pending.append(f"need: {question_short}")
        return pending
