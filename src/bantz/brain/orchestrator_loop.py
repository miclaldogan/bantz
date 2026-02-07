"""LLM Orchestrator Loop (Issue #134: LLM-first architecture).

This is the executor for JarvisLLMOrchestrator. Every turn:
1. LLM decides (route, intent, tools, confirmation, reasoning)
2. Executor runs tools (with confirmation firewall for destructive ops)
3. LLM finalizes response (using tool results)

No hard-coded routing - LLM controls everything.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from bantz.agent.tools import ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.brain.safety_guard import SafetyGuard, ToolSecurityPolicy
from bantz.brain.memory_lite import DialogSummaryManager, CompactSummary
from bantz.core.events import EventBus, EventType

logger = logging.getLogger(__name__)


def _summarize_tool_result(result: Any, max_items: int = 5, max_chars: int = 500) -> str:
    """Smart summarization of tool results that preserves structure.
    
    Issue #353: Avoid naive string truncation that breaks JSON and loses
    structured data. Instead, intelligently summarize based on type.
    
    Args:
        result: Tool result (dict, list, string, or other)
        max_items: Maximum number of items to show for lists
        max_chars: Maximum characters for final summary
        
    Returns:
        Human-readable summary string
    """
    try:
        if result is None:
            return "None"
            
        # Handle lists: show total count + first N items
        if isinstance(result, list):
            total = len(result)
            if total == 0:
                return "[]"
            preview = result[:max_items]
            preview_json = json.dumps(preview, ensure_ascii=False)
            if len(preview_json) > max_chars:
                preview_json = preview_json[:max_chars] + "..."
            if total > max_items:
                return f"[{total} items, showing first {len(preview)}] {preview_json}"
            return preview_json
            
        # Handle dicts: show keys + truncated JSON
        if isinstance(result, dict):
            if not result:
                return "{}"
            keys = list(result.keys())
            result_json = json.dumps(result, ensure_ascii=False)
            if len(result_json) > max_chars:
                result_json = result_json[:max_chars] + "..."
            return f"{{keys: {keys}}} {result_json}"
            
        # Handle strings: smart truncation
        if isinstance(result, str):
            if len(result) > max_chars:
                return result[:max_chars] + f"... ({len(result)} chars total)"
            return result
            
        # Other types: convert to string with length limit
        result_str = str(result)
        if len(result_str) > max_chars:
            return result_str[:max_chars] + "..."
        return result_str
        
    except Exception as e:
        # Fallback: safe string conversion
        try:
            s = str(result)
            return s[:max_chars] if len(s) > max_chars else s
        except Exception:
            return f"<error serializing result: {e}>"


def _prepare_tool_results_for_finalizer(
    tool_results: list[dict[str, Any]],
    max_tokens: int = 2000,
) -> tuple[list[dict[str, Any]], bool]:
    """Prepare tool results for finalizer prompt with token budget control.
    
    Issue #354: Finalizer prompts can overflow context when tool results are large.
    This function intelligently truncates/summarizes results to fit within budget.
    
    Strategy:
    1. Try full raw_result for each tool (best quality)
    2. If budget exceeded, use result_summary instead (smart truncation)
    3. If still too large, truncate summaries further
    4. Return warning flag if truncation occurred
    
    Args:
        tool_results: List of tool result dicts with raw_result and result_summary
        max_tokens: Maximum tokens to allocate for tool results section
        
    Returns:
        Tuple of (processed_results, was_truncated)
    """
    if not tool_results:
        return [], False
    
    # Rough token estimation: ~4 chars per token for JSON
    def estimate_result_tokens(results: list[dict]) -> int:
        try:
            json_str = json.dumps(results, ensure_ascii=False)
            return len(json_str) // 4
        except Exception:
            # Fallback: assume worst case
            return max_tokens + 1
    
    # Step 1: Try using raw_result for all tools (best quality)
    finalizer_results = []
    for r in tool_results:
        finalizer_r = {
            "tool": r.get("tool"),
            "success": r.get("success"),
            "result": r.get("raw_result"),  # Full structured data
            "error": r.get("error"),
        }
        finalizer_results.append(finalizer_r)
    
    tokens = estimate_result_tokens(finalizer_results)
    if tokens <= max_tokens:
        # Fits within budget, use raw results
        return finalizer_results, False
    
    # Step 2: Budget exceeded, use result_summary instead
    logger.warning(
        f"[FINALIZER] Tool results ({tokens} tokens) exceed budget ({max_tokens}), "
        f"using summaries instead of raw data"
    )
    
    finalizer_results = []
    for r in tool_results:
        finalizer_r = {
            "tool": r.get("tool"),
            "success": r.get("success"),
            "result": r.get("result_summary", ""),  # Use summary
            "error": r.get("error"),
        }
        finalizer_results.append(finalizer_r)
    
    tokens = estimate_result_tokens(finalizer_results)
    if tokens <= max_tokens:
        # Summaries fit within budget
        return finalizer_results, True
    
    # Step 3: Even summaries are too large, truncate aggressively
    logger.warning(
        f"[FINALIZER] Tool result summaries ({tokens} tokens) still exceed budget, "
        f"truncating to first 3 tools"
    )
    
    # Keep only first 3 tools and truncate their summaries
    truncated_results = []
    for r in finalizer_results[:3]:
        summary = str(r.get("result", ""))
        if len(summary) > 200:
            summary = summary[:200] + "..."
        
        truncated_r = {
            "tool": r.get("tool"),
            "success": r.get("success"),
            "result": summary,
            "error": r.get("error"),
        }
        truncated_results.append(truncated_r)
    
    return truncated_results, True


def _build_tool_success_summary(tool_results: list[dict[str, Any]]) -> str:
    """Build a tool-aware success summary instead of generic 'Tamamlandı efendim'.
    
    Issue #370: When assistant_reply is empty after successful tool execution,
    generate a meaningful summary from tool results instead of a generic message.
    
    Heuristics:
    - list/query tools → count items found
    - create tools → confirm what was created  
    - send tools → confirm what was sent
    - Multiple tools → summarize each
    
    Args:
        tool_results: List of tool result dicts with tool name, success, raw_result
        
    Returns:
        User-friendly Turkish summary of tool results
    """
    if not tool_results:
        return "Tamamlandı efendim."

    parts: list[str] = []
    
    for r in tool_results:
        tool_name = str(r.get("tool") or "")
        raw = r.get("raw_result")
        success = r.get("success", False)
        
        if not success:
            continue
        
        # Calendar query tools: count events
        if tool_name in ("calendar.list_events", "calendar.find_free_slots"):
            count = _count_items(raw)
            if tool_name == "calendar.list_events":
                if count == 0:
                    parts.append("Takvimde etkinlik bulunamadı efendim.")
                elif count == 1:
                    parts.append("1 etkinlik bulundu efendim.")
                else:
                    parts.append(f"{count} etkinlik bulundu efendim.")
            else:
                if count == 0:
                    parts.append("Uygun boş zaman dilimi bulunamadı efendim.")
                else:
                    parts.append(f"{count} uygun zaman dilimi bulundu efendim.")
        
        # Calendar create
        elif tool_name == "calendar.create_event":
            title = _extract_field(raw, "title", "summary")
            if title:
                parts.append(f"'{title}' etkinliği oluşturuldu efendim.")
            else:
                parts.append("Etkinlik oluşturuldu efendim.")
        
        # Gmail list/search
        elif tool_name in ("gmail.list_messages", "gmail.smart_search"):
            count = _count_items(raw)
            if count == 0:
                parts.append("Mesaj bulunamadı efendim.")
            elif count == 1:
                parts.append("1 mesaj bulundu efendim.")
            else:
                parts.append(f"{count} mesaj bulundu efendim.")
        
        # Gmail unread count
        elif tool_name == "gmail.unread_count":
            count = _extract_count(raw)
            if count is not None:
                if count == 0:
                    parts.append("Okunmamış mesajınız yok efendim.")
                else:
                    parts.append(f"{count} okunmamış mesajınız var efendim.")
            else:
                parts.append("Okunmamış mesaj sayısı alındı efendim.")
        
        # Gmail send
        elif tool_name in ("gmail.send", "gmail.send_to_contact", "gmail.send_draft"):
            parts.append("Mail gönderildi efendim.")
        
        # Gmail read
        elif tool_name == "gmail.get_message":
            parts.append("Mesaj getirildi efendim.")
        
        # Gmail draft
        elif tool_name == "gmail.create_draft":
            parts.append("Taslak oluşturuldu efendim.")
        
        # Contacts
        elif tool_name == "contacts.list":
            count = _count_items(raw)
            parts.append(f"{count} kişi listelendi efendim." if count > 0 else "Kayıtlı kişi bulunamadı efendim.")
        
        elif tool_name == "contacts.resolve":
            parts.append("Kişi bilgisi çözümlendi efendim.")
        
        # Generic fallback for unknown tools
        else:
            tool_short = tool_name.split(".")[-1] if "." in tool_name else tool_name
            parts.append(f"{tool_short} tamamlandı efendim.")
    
    if not parts:
        # All tools either failed or unrecognized
        if len(tool_results) > 1:
            return f"{len(tool_results)} işlem tamamlandı efendim."
        return "Tamamlandı efendim."
    
    if len(parts) == 1:
        return parts[0]
    
    # Multiple tool summaries: join with newlines
    return "\n".join(parts)


def _count_items(raw: Any) -> int:
    """Count items from a tool result (list, dict with items/events, or count field)."""
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        # Check for nested lists
        for key in ("events", "items", "messages", "results", "data", "contacts", "slots"):
            val = raw.get(key)
            if isinstance(val, list):
                return len(val)
        # Check for count fields
        for key in ("count", "total", "total_count"):
            val = raw.get(key)
            if isinstance(val, (int, float)):
                return int(val)
    return 0


def _extract_count(raw: Any) -> int | None:
    """Extract a count value from a tool result."""
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, dict):
        for key in ("count", "total", "unread_count", "value"):
            val = raw.get(key)
            if isinstance(val, (int, float)):
                return int(val)
    return None


def _extract_field(raw: Any, *field_names: str) -> str | None:
    """Extract a string field from a tool result dict."""
    if isinstance(raw, dict):
        for name in field_names:
            val = raw.get(name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


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
        # Issue #403: deprecation notice — prefer unified_loop.create_brain()
        import warnings as _w
        _w.warn(
            "OrchestratorLoop is deprecated and will be removed in a future release. "
            "Use bantz.brain.create_brain(mode='orchestrator', ...) instead. "
            "See Issue #403 for migration details.",
            DeprecationWarning,
            stacklevel=2,
        )

        self.orchestrator = orchestrator
        self.tools = tools
        self.event_bus = event_bus or EventBus()
        self.config = config or OrchestratorConfig()
        self.finalizer_llm = finalizer_llm
        self.audit_logger = audit_logger  # For tool execution auditing (Issue #160)
        
        # Initialize memory-lite (Issue #141)
        self.memory = DialogSummaryManager(
            max_tokens=self.config.memory_max_tokens,
            max_turns=self.config.memory_max_turns,
            pii_filter_enabled=self.config.memory_pii_filter,
        )
        
        # Initialize safety guard (Issue #140)
        if self.config.enable_safety_guard:
            self.safety_guard = SafetyGuard(
                policy=self.config.security_policy or ToolSecurityPolicy()
            )
        else:
            self.safety_guard = None
        
        # Route+Intent → Mandatory Tools mapping (Issue #282)
        # Prevents hallucination when LLM returns empty tool_plan for queries
        self._mandatory_tool_map: dict[tuple[str, str], list[str]] = {
            # Calendar routes
            ("calendar", "query"): ["calendar.list_events"],
            ("calendar", "create"): ["calendar.create_event"],
            ("calendar", "modify"): ["calendar.update_event"],
            ("calendar", "cancel"): ["calendar.delete_event"],
            # Gmail routes (calendar_intent is used for backwards compat)
            ("gmail", "list"): ["gmail.list_messages"],
            ("gmail", "query"): ["gmail.list_messages"],
            ("gmail", "read"): ["gmail.get_message"],
            ("gmail", "send"): ["gmail.send"],
            ("gmail", "search"): ["gmail.smart_search"],  # Issue #317: Gmail label search
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
    
    def _force_tool_plan(self, output: OrchestratorOutput) -> OrchestratorOutput:
        """Force mandatory tools based on route+intent (Issue #282).
        
        Prevents LLM hallucination by ensuring queries always have tool_plan.
        If LLM returns empty tool_plan but route+intent requires tools,
        we inject the mandatory tools.
        
        Issue #347: Respects router's confidence threshold. If router cleared
        tool_plan due to low confidence, we honor that decision instead of
        forcing tools back in. Only force tools when confidence is adequate.
        
        Args:
            output: Original LLM output
            
        Returns:
            Updated output with forced tool_plan if needed
        """
        # Issue #347: Skip if confidence is too low - router wants clarification
        # Confidence threshold: 0.7 (same as router's default threshold)
        if output.confidence < 0.7:
            return output
        
        # Skip if tool_plan already populated
        if output.tool_plan:
            return output
        
        # Skip if LLM is asking user for clarification (not ready to execute)
        if output.ask_user:
            return output
        
        # Skip for smalltalk/unknown - no tools needed
        if output.route in ("smalltalk", "unknown"):
            return output
        
        # Issue #317: Check gmail_intent first for gmail route
        gmail_intent = getattr(output, "gmail_intent", None) or ""
        if output.route == "gmail" and gmail_intent and gmail_intent != "none":
            mandatory_tools = self._gmail_intent_map.get(gmail_intent)
            if mandatory_tools:
                if self.config.debug:
                    logger.debug(f"[FORCE_TOOL_PLAN] Gmail intent '{gmail_intent}', forcing: {mandatory_tools}")
                from dataclasses import replace
                return replace(output, tool_plan=mandatory_tools)
        
        # Skip if intent is "none" - no action needed (e.g., email drafting)
        if output.calendar_intent in ("none", ""):
            # For gmail without gmail_intent, try fallback based on route
            if output.route == "gmail":
                mandatory_tools = ["gmail.list_messages"]
                if self.config.debug:
                    logger.debug(f"[FORCE_TOOL_PLAN] Gmail fallback, forcing: {mandatory_tools}")
                from dataclasses import replace
                return replace(output, tool_plan=mandatory_tools)
            return output
        
        # Lookup mandatory tools
        key = (output.route, output.calendar_intent)
        mandatory_tools = self._mandatory_tool_map.get(key)
        
        if not mandatory_tools:
            # Try route-only fallback for system route
            if output.route == "system":
                mandatory_tools = ["time.now"]
            elif output.route == "gmail":
                mandatory_tools = ["gmail.list_messages"]
            else:
                # No mandatory tools for this route+intent
                return output
        
        if self.config.debug:
            logger.debug(f"[FORCE_TOOL_PLAN] Empty tool_plan for {key}, forcing: {mandatory_tools}")
        
        # Create new output with forced tool_plan
        # We use dataclass replace pattern
        from dataclasses import replace
        updated_output = replace(output, tool_plan=mandatory_tools)
        
        return updated_output
    
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
        
        # Emit turn start event
        self.event_bus.publish("turn.start", {"user_input": user_input})
        
        try:
            # Phase 1: LLM Planning (route, intent, tools, confirmation)
            orchestrator_output = self._llm_planning_phase(user_input, state)
            
            # Phase 2: Tool Execution (with confirmation firewall)
            tool_results = self._execute_tools_phase(orchestrator_output, state)
            
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
                assistant_reply=f"Efendim, bir sorun oluştu: {e}",
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

        # Phase 1: plan
        orchestrator_output = self._llm_planning_phase(user_input, state)

        # Phase 2: execute tools
        tool_results = self._execute_tools_phase(orchestrator_output, state)

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
        # Build context for LLM
        context = state.get_context_for_llm()
        conversation_history = context.get("recent_conversation", [])
        tool_results = context.get("last_tool_results", [])
        
        # Use memory-lite summary instead of rolling_summary from state (Issue #141)
        dialog_summary = self.memory.to_prompt_block()
        
        # Issue #339: Include conversation history and tool results in context
        # Build enhanced context block
        context_parts = []
        
        if dialog_summary:
            context_parts.append(dialog_summary)
        
        # Add recent conversation (last 2 turns)
        if conversation_history:
            conv_lines = ["RECENT_CONVERSATION:"]
            for turn in conversation_history[-2:]:
                user_text = str(turn.get("user", ""))[:100]
                asst_text = str(turn.get("assistant", ""))[:150]
                conv_lines.append(f"  U: {user_text}")
                conv_lines.append(f"  A: {asst_text}")
            context_parts.append("\n".join(conv_lines))
        
        # Add recent tool results (for context continuity)
        if tool_results:
            result_lines = ["LAST_TOOL_RESULTS:"]
            for tr in tool_results[-2:]:
                tool_name = str(tr.get("tool", ""))
                # Issue #353: Use result_summary instead of truncated result
                result_str = str(tr.get("result_summary", ""))[:200]
                success = tr.get("success", True)
                status = "ok" if success else "fail"
                result_lines.append(f"  {tool_name} ({status}): {result_str}")
            context_parts.append("\n".join(result_lines))
        
        enhanced_summary = "\n\n".join(context_parts) if context_parts else None
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] LLM Planning Phase:")
            logger.debug(f"  User: {user_input}")
            logger.debug(f"  Dialog Summary (memory-lite): {dialog_summary or 'None'}")
            logger.debug(f"  Recent History: {len(conversation_history)} turns")
            logger.debug(f"  Tool Results: {len(tool_results)}")
        
        # Session context injection (Issue #191): datetime/location hints.
        # Issue #339: Add recent conversation to session_context for multi-turn memory
        # Issue #359: Use state.session_context if available (preserves timezone/locale)
        session_context = state.session_context
        
        if not session_context:
            # Fallback: build fresh session context
            try:
                from bantz.brain.prompt_engineering import build_session_context
                session_context = build_session_context()
            except Exception:
                session_context = None
        
        # Add recent conversation for anaphora resolution (Issue #339)
        # This helps LLM understand references like "saat kaçta" (what time) 
        # by looking at previous turns ("bugün için toplantı var")
        # NOTE: Use state.conversation_history directly (not from get_context_for_llm)
        # because get_context_for_llm limits to [-2:] for legacy compatibility
        if session_context and state.conversation_history:
            session_context["recent_conversation"] = state.conversation_history[-3:]  # Last 3 turns

        # Call orchestrator with enhanced summary + session context
        output = self.orchestrator.route(
            user_input=user_input,
            dialog_summary=enhanced_summary,
            session_context=session_context,
        )
        
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
        
        return output
    
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
        if not output.tool_plan:
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
        if self.safety_guard:
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
        
        tool_results = []

        # Issue #351: Confirmation queue support (multiple destructive tools)
        # If a confirmation is already pending, block all tools unless the
        # pending tool is explicitly confirmed for this execution pass.
        confirmed_override_tool: Optional[str] = None
        if state.has_pending_confirmation():
            pending = state.peek_pending_confirmation() or {}
            pending_tool = str(pending.get("tool") or "").strip()

            if state.confirmed_tool and pending_tool and pending_tool == state.confirmed_tool:
                # Confirmation accepted for the head of the queue.
                confirmed_override_tool = pending_tool
                state.pop_pending_confirmation()
                state.confirmed_tool = None
                filtered_tool_plan = [pending_tool]
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

        # If no confirmation is pending, pre-scan tool_plan and queue all
        # confirmations in order, then return a pending confirmation placeholder.
        if not state.has_pending_confirmation():
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
                    raise ValueError(f"Tool {tool_name} has no function implementation")
                
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
                        })
                        continue
                
                # Execute tool
                result = tool.function(**params)

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
    
    def _build_tool_params(
        self,
        tool_name: str,
        slots: dict[str, Any],
        output: Optional["OrchestratorOutput"] = None,
    ) -> dict[str, Any]:
        """Build tool parameters from orchestrator slots.
        
        This maps orchestrator slots to tool-specific parameters.
        Handles nested objects like gmail: {to, subject, body}.
        
        Issue #340: Applies field aliasing for common LLM variations
        (recipient → to, email → to, address → to, etc.)
        
        Args:
            tool_name: Name of the tool to build params for
            slots: Calendar/system slots dict
            output: Full orchestrator output (for gmail params)
        """
        params: dict[str, Any] = {}
        
        # Gmail tools: whitelist gmail params only (Issue #365)
        if tool_name.startswith("gmail."):
            gmail_valid_params = {
                "to",
                "subject",
                "body",
                "cc",
                "bcc",
                "label",
                "category",
                "query",
                "search_term",
                "natural_query",
                "message_id",
                "max_results",
                "unread_only",
                "prefer_unread",
            }

            # First check slots.gmail (legacy)
            gmail_params = slots.get("gmail")
            if isinstance(gmail_params, dict):
                for key, val in gmail_params.items():
                    if key in gmail_valid_params and val is not None:
                        params[key] = val
            
            # Then check output.gmail (Issue #317)
            if output is not None:
                gmail_obj = getattr(output, "gmail", None) or {}
                if isinstance(gmail_obj, dict):
                    for key, val in gmail_obj.items():
                        if key in gmail_valid_params and val is not None:
                            params[key] = val
            
            # Issue #340: Apply field aliasing for gmail.send
            # LLM often uses alternative field names (recipient, email, address, etc.)
            if tool_name == "gmail.send":
                # Alias: recipient/email/address/emails → to
                for alias in ["recipient", "email", "address", "emails", "to_address"]:
                    if alias in params and "to" not in params:
                        params["to"] = params.pop(alias)
                        break
                
                # Alias: message/text/content → body
                for alias in ["message", "text", "content", "message_body"]:
                    if alias in params and "body" not in params:
                        params["body"] = params.pop(alias)
                        break
                
                # Alias: title → subject
                if "title" in params and "subject" not in params:
                    params["subject"] = params.pop("title")
        
        else:
            # Calendar/system tools: use slots directly (already flat)
            params = dict(slots)
        
        return params
    
    def _llm_finalization_phase(
        self,
        user_input: str,
        orchestrator_output: OrchestratorOutput,
        tool_results: list[dict[str, Any]],
        state: OrchestratorState,
    ) -> OrchestratorOutput:
        """Phase 3: LLM Finalization (generate final response with tool results).
        
        If tools were executed, we can optionally call LLM again to generate
        a final response incorporating tool results.
        
        For now, we'll use the original assistant_reply if tools succeeded,
        or generate an error message if tools failed.
        
        TODO: Implement proper LLM finalization call
        """
        # Issue #284: Emit finalizer.start event for trace visualization
        self.event_bus.publish("finalizer.start", {
            "has_tool_results": bool(tool_results),
            "tool_count": len(tool_results),
        })
        
        # If LLM asked a clarifying question, ensure we have a user-visible reply.
        if orchestrator_output.ask_user and orchestrator_output.question and not orchestrator_output.assistant_reply:
            from dataclasses import replace

            return replace(orchestrator_output, assistant_reply=orchestrator_output.question)

        # If any tools failed (excluding pending-confirmation placeholders),
        # short-circuit with a deterministic error message.
        # This prevents the finalizer LLM from hallucinating a "successful" outcome
        # when the tool returned {ok:false} or otherwise failed.
        if tool_results:
            hard_failures = [
                r
                for r in tool_results
                if (not r.get("success", False)) and (not r.get("pending_confirmation"))
            ]
            if hard_failures:
                error_msg = "Üzgünüm efendim, bazı işlemler başarısız oldu:\n"
                for result in hard_failures:
                    tool_name = str(result.get("tool") or "")
                    err = str(result.get("error") or "Unknown error")
                    error_msg += f"- {tool_name}: {err}\n"

                from dataclasses import replace

                return replace(orchestrator_output, assistant_reply=error_msg.strip())

        def _extract_reason_code(err: Exception) -> str:
            try:
                import re

                m = re.search(r"\breason=([a-z_]+)\b", str(err))
                if m:
                    return str(m.group(1))
            except Exception:
                pass
            return "unknown_error"

        def _fast_finalize_with_planner() -> str | None:
            try:
                planner_llm = getattr(self.orchestrator, "_llm", None)
                if planner_llm is None or not hasattr(planner_llm, "complete_text"):
                    return None

                planner_decision = {
                    "route": orchestrator_output.route,
                    "calendar_intent": orchestrator_output.calendar_intent,
                    "slots": orchestrator_output.slots,
                    "tool_plan": orchestrator_output.tool_plan,
                    "requires_confirmation": orchestrator_output.requires_confirmation,
                }

                prompt_lines = [
                    "Kimlik / Roller:",
                    "- Sen BANTZ'sın. Kullanıcı USER'dır.",
                    "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
                    "- 'Efendim' hitabını kullan.",
                    "- Sadece kullanıcıya söyleyeceğin düz metni üret.",
                    "- JSON üretme ({...} YASAK). Markdown üretme (**, #, ``` YASAK).",
                    "- Yeni sayı/saat/tarih/isim uydurma; SADECE verilerdeki bilgileri kullan.",
                    "- Kısa ve öz cevap ver (1-3 cümle).",
                    "",
                    "PLANNER_DECISION (JSON):",
                    json.dumps(planner_decision, ensure_ascii=False),
                ]
                if tool_results:
                    # Issue #353, #354: Use raw_result with token budget control
                    finalizer_results, was_truncated = _prepare_tool_results_for_finalizer(
                        tool_results,
                        max_tokens=1500  # Leave room for planner decision + user input
                    )
                    if was_truncated:
                        logger.info("[FAST_FINALIZE] Tool results truncated to fit budget")
                    prompt_lines.extend(["", "TOOL_RESULTS (JSON):", json.dumps(finalizer_results, ensure_ascii=False)])
                prompt_lines.extend(["", f"USER: {user_input}", "ASSISTANT (SADECE TÜRKÇE, düz metin, yeni bilgi ekleme):"])
                fast_prompt = "\n".join(prompt_lines)

                try:
                    fast_text = planner_llm.complete_text(prompt=fast_prompt, temperature=0.2, max_tokens=256)
                except TypeError:
                    fast_text = planner_llm.complete_text(prompt=fast_prompt)
                fast_text = str(fast_text or "").strip()
                return fast_text or None
            except Exception:
                return None

        # Hybrid mode: if a finalizer LLM is provided, optionally generate the
        # user-facing reply using that model (e.g., Gemini), while keeping planning/tool
        # decisions from the planner model (e.g., 3B).
        use_finalizer: bool = False
        tier_reason: str = ""
        tier_name: str = ""

        if self.finalizer_llm is not None:
            # Issue #346: Always use quality finalizer for smalltalk route.
            # Smalltalk is conversational/narrative content that benefits from Gemini's
            # natural language generation quality, even when no tools were executed.
            if orchestrator_output.route == "smalltalk":
                use_finalizer = True
                tier_name = "quality"
                tier_reason = "smalltalk_route_always_quality"
            else:
                use_finalizer = True
                tier_name = "quality"
                tier_reason = "finalizer_default"

                try:
                    # Default behavior is unchanged unless tiering is enabled.
                    from bantz.llm.tiered import decide_tier
                    import os

                    decision = decide_tier(
                        user_input,
                        tool_names=orchestrator_output.tool_plan,
                        requires_confirmation=bool(orchestrator_output.requires_confirmation),
                        route=orchestrator_output.route,
                    )

                    if decision.reason == "tiering_disabled":
                        use_finalizer = True
                        tier_name = "quality"
                        tier_reason = "tiering_disabled_default_quality"
                    else:
                        use_finalizer = bool(decision.use_quality)
                        tier_name = "quality" if use_finalizer else "fast"
                        tier_reason = str(decision.reason)

                    if str(os.getenv("BANTZ_TIERED_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}:
                        logger.info(
                            "[tiered] orchestrator_finalizer tier=%s reason=%s c=%s w=%s r=%s",
                            tier_name,
                            decision.reason,
                            decision.complexity,
                            decision.writing,
                            decision.risk,
                        )
                except Exception:
                    use_finalizer = True
                    tier_name = "quality"
                    tier_reason = "tiering_error_default_quality"

        if self.finalizer_llm is not None and use_finalizer:
            try:
                context = state.get_context_for_llm()
                dialog_summary = self.memory.to_prompt_block()

                planner_decision = {
                    "route": orchestrator_output.route,
                    "calendar_intent": orchestrator_output.calendar_intent,
                    "slots": orchestrator_output.slots,
                    "tool_plan": orchestrator_output.tool_plan,
                    "requires_confirmation": orchestrator_output.requires_confirmation,
                    "confirmation_prompt": orchestrator_output.confirmation_prompt,
                    "ask_user": orchestrator_output.ask_user,
                    "question": orchestrator_output.question,
                }

                recent = context.get("recent_conversation")
                recent_turns = recent if isinstance(recent, list) else None

                # Issue #359: Use state.session_context if available (preserves timezone/locale)
                session_context = state.session_context
                
                if not session_context:
                    # Fallback: build fresh session context
                    try:
                        from bantz.brain.prompt_engineering import build_session_context
                        session_context = build_session_context()
                    except Exception:
                        session_context = None

                seed = str(session_context.get("session_id") or "default") if session_context else "default"
                
                try:
                    from bantz.brain.prompt_engineering import PromptBuilder
                    
                    builder = PromptBuilder(token_budget=3500, experiment="issue191_orchestrator_finalizer")
                    
                    # Issue #353, #354: Prepare tool_results with budget control
                    finalizer_results, was_truncated = _prepare_tool_results_for_finalizer(
                        tool_results or [],
                        max_tokens=2000  # Allocate 2000 tokens for tool results
                    )
                    if was_truncated:
                        logger.info("[FINALIZER] Tool results truncated to fit token budget")
                    
                    built = builder.build_finalizer_prompt(
                        route=orchestrator_output.route,
                        user_input=user_input,
                        planner_decision=planner_decision,
                        tool_results=finalizer_results or None,  # ✅ Budget-controlled results
                        dialog_summary=dialog_summary or None,
                        recent_turns=recent_turns,
                        session_context=session_context,
                        seed=seed,
                    )
                    finalizer_prompt = built.prompt
                except Exception:
                    # Fallback to simple prompt if prompt builder fails.
                    # Issue #353, #354: Use budget-controlled results in fallback
                    finalizer_results, was_truncated = _prepare_tool_results_for_finalizer(
                        tool_results or [],
                        max_tokens=2000
                    )
                    if was_truncated:
                        logger.warning("[FINALIZER_FALLBACK] Tool results truncated to fit budget")
                    
                    finalizer_prompt = "\n".join(
                        [
                            "Kimlik / Roller:",
                            "- Sen BANTZ'sın. Kullanıcı USER'dır.",
                            "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
                            "- 'Efendim' hitabını kullan.",
                            "",
                            "FORMAT KURALLARI (KESİN):",
                            "- Sadece kullanıcıya söyleyeceğin düz metni üret.",
                            "- JSON üretme. Örnek: {\"route\": ...} YASAK.",
                            "- Markdown üretme. Örnek: **kalın**, # başlık, ```kod``` YASAK.",
                            "- Kod bloğu üretme.",
                            "- Liste işareti (-, *, 1.) kullanma; düz cümle kur.",
                            "",
                            "DOĞRULUK KURALLARI (KESİN):",
                            "- SADECE verilen TOOL_RESULTS ve PLANNER_DECISION içindeki bilgileri kullan.",
                            "- Yeni sayı, saat, tarih, miktar, fiyat UYDURMA. Verilerde yoksa söyleme.",
                            "- Yeni isim, e-posta, telefon UYDURMA.",
                            "- Emin olmadığın bilgiyi söyleme; belirsizse 'bilgi yok' de.",
                            "",
                            "- Kısa ve öz cevap ver (1-3 cümle).",
                            "",
                            f"DIALOG_SUMMARY:\n{dialog_summary}\n" if dialog_summary else "",
                            "PLANNER_DECISION (JSON):",
                            json.dumps(planner_decision, ensure_ascii=False),
                            "\nTOOL_RESULTS (JSON):\n" + json.dumps(finalizer_results, ensure_ascii=False) if finalizer_results else "",
                            f"\nUSER: {user_input}\nASSISTANT (SADECE TÜRKÇE, düz metin, yeni bilgi ekleme):",
                        ]
                    ).strip()

                try:
                    final_text = self.finalizer_llm.complete_text(
                        prompt=finalizer_prompt,
                        temperature=0.2,
                        max_tokens=256,
                    )
                except TypeError:
                    final_text = self.finalizer_llm.complete_text(prompt=finalizer_prompt)

                final_text = str(final_text or "").strip()

                # Issue #215: no-new-facts guard (numbers/time/date must not be invented).
                if final_text:
                    try:
                        from bantz.llm.no_new_facts import find_new_numeric_facts

                        allowed_sources = [
                            user_input,
                            dialog_summary or "",
                            json.dumps(planner_decision, ensure_ascii=False),
                            json.dumps(tool_results or [], ensure_ascii=False),
                        ]
                        violates, new_tokens = find_new_numeric_facts(
                            allowed_texts=allowed_sources,
                            candidate_text=final_text,
                        )

                        if violates:
                            # One minimal retry with stricter constraint.
                            state.update_trace(
                                finalizer_attempted=True,
                                finalizer_guard="no_new_facts",
                                finalizer_guard_violation=True,
                                finalizer_guard_new_tokens_count=len(new_tokens),
                            )
                            retry_prompt = (
                                finalizer_prompt
                                + "\n\nSTRICT_NO_NEW_FACTS: Sadece verilen metinlerde geçen sayı/saat/tarihleri kullan. "
                                "Yeni rakam ekleme. Gerekirse rakam içeren detayları çıkar.\n"
                            )
                            try:
                                final_text2 = self.finalizer_llm.complete_text(
                                    prompt=retry_prompt,
                                    temperature=0.2,
                                    max_tokens=256,
                                )
                            except TypeError:
                                final_text2 = self.finalizer_llm.complete_text(prompt=retry_prompt)
                            final_text2 = str(final_text2 or "").strip()
                            if final_text2:
                                violates2, _new2 = find_new_numeric_facts(
                                    allowed_texts=allowed_sources,
                                    candidate_text=final_text2,
                                )
                                if not violates2:
                                    final_text = final_text2
                                else:
                                    final_text = ""
                            else:
                                final_text = ""
                    except Exception:
                        # Guard is best-effort; continue.
                        pass

                if not final_text:
                    # Guard rejected the quality output; fall back cleanly.
                    fallback_text = _fast_finalize_with_planner()
                    if fallback_text:
                        from dataclasses import replace

                        state.update_trace(
                            response_tier=tier_name or "quality",
                            response_tier_reason=tier_reason or "quality_finalizer",
                            finalizer_attempted=True,
                            finalizer_used=False,
                            finalizer_fallback="planner",
                        )
                        return replace(orchestrator_output, assistant_reply=fallback_text)

                if final_text:
                    from dataclasses import replace

                    state.update_trace(
                        response_tier=tier_name or "quality",
                        response_tier_reason=tier_reason or "quality_finalizer",
                        finalizer_used=True,
                        finalizer_attempted=True,
                    )

                    return replace(orchestrator_output, assistant_reply=final_text)
            except Exception as e:
                # Issue #215: clean fallback on auth/limit/etc errors with reason code.
                try:
                    from bantz.llm.base import LLMClientError

                    if isinstance(e, LLMClientError):
                        code = _extract_reason_code(e)
                        state.update_trace(
                            response_tier=tier_name or "quality",
                            response_tier_reason=tier_reason or "quality_finalizer",
                            finalizer_attempted=True,
                            finalizer_used=False,
                            finalizer_error_code=code,
                            finalizer_error_backend=str(getattr(self.finalizer_llm, "backend_name", "") or ""),
                        )

                        fallback_text = _fast_finalize_with_planner()
                        if fallback_text:
                            from dataclasses import replace

                            return replace(orchestrator_output, assistant_reply=fallback_text)
                except Exception:
                    pass

                # Fall back to non-hybrid behavior below.
                pass

        # Tiered fast path (no quality finalizer): for tool-based routes, produce
        # a user-facing reply without escalating to the cloud finalizer.
        if self.finalizer_llm is not None and not use_finalizer:
            state.update_trace(
                response_tier=tier_name or "fast",
                response_tier_reason=tier_reason or "fast_ok",
                finalizer_used=False,
            )

            should_fast_finalize = bool(tool_results) and not bool(orchestrator_output.ask_user)
            if should_fast_finalize:
                try:
                    fallback_text = _fast_finalize_with_planner()
                    if fallback_text:
                        from dataclasses import replace

                        return replace(orchestrator_output, assistant_reply=fallback_text)
                except Exception:
                    # Best-effort; continue to default behavior.
                    pass

        if not tool_results:
            return orchestrator_output
        
        # Check if any tools failed
        failed_tools = [r for r in tool_results if not r.get("success", False)]
        
        if failed_tools:
            # Generate error response (preserve orchestrator fields)
            error_msg = "Üzgünüm efendim, bazı işlemler başarısız oldu:\n"
            for result in failed_tools:
                error_msg += f"- {result['tool']}: {result.get('error', 'Unknown error')}\n"
            
            from dataclasses import replace
            return replace(orchestrator_output, assistant_reply=error_msg.strip())
        
        # Tools succeeded - use original response or generate success message
        if orchestrator_output.assistant_reply:
            return orchestrator_output
        
        # Issue #370: Try fast finalizer first for tool-aware summary
        try:
            fast_summary = _fast_finalize_with_planner()
            if fast_summary:
                from dataclasses import replace
                return replace(orchestrator_output, assistant_reply=fast_summary)
        except Exception:
            pass
        
        # Issue #370: Generate tool-aware success message instead of generic "Tamamlandı"
        success_msg = _build_tool_success_summary(tool_results)
        
        from dataclasses import replace
        return replace(orchestrator_output, assistant_reply=success_msg)
    
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
        """Extract concise user intent (1-3 words)."""
        if output.route == "calendar":
            return f"asked about {output.calendar_intent}"
        elif output.route == "smalltalk":
            # Check for common patterns
            if any(word in user_input.lower() for word in ["merhaba", "selam", "hey", "nasılsın"]):
                return "greeted"
            elif any(word in user_input.lower() for word in ["kendini tanıt", "kimsin"]):
                return "asked about identity"
            else:
                return "casual chat"
        else:
            return "unclear request"
    
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
