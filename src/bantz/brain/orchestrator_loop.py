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


@dataclass
class OrchestratorConfig:
    """Configuration for orchestrator loop."""
    
    max_steps: int = 8  # Max tool execution steps per turn
    debug: bool = False  # Debug mode (verbose logging)
    require_confirmation_for: list[str] = None  # Tools requiring confirmation
    enable_safety_guard: bool = True  # Enable safety & policy checks (Issue #140)
    security_policy: Optional[ToolSecurityPolicy] = None  # Custom security policy
    
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
    ):
        self.orchestrator = orchestrator
        self.tools = tools
        self.event_bus = event_bus or EventBus()
        self.config = config or OrchestratorConfig()
        self.finalizer_llm = finalizer_llm
        
        # Initialize memory-lite (Issue #141)
        self.memory = DialogSummaryManager(
            max_tokens=500,
            max_turns=5,
            pii_filter_enabled=True,
        )
        
        # Initialize safety guard (Issue #140)
        if self.config.enable_safety_guard:
            self.safety_guard = SafetyGuard(
                policy=self.config.security_policy or ToolSecurityPolicy()
            )
        else:
            self.safety_guard = None
    
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
        - If a destructive tool requires confirmation, the first cycle will set
          `state.pending_confirmation` and not execute the tool.
        - If `confirmation_token` is provided and a pending confirmation exists,
          we attempt a second execution pass in the same call.
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
            pending = state.pending_confirmation or {}
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
                # Second execution pass: state already has pending confirmation.
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
                # User rejected/unclear: clear pending confirmation and return.
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
        
        # Use memory-lite summary instead of rolling_summary from state (Issue #141)
        dialog_summary = self.memory.to_prompt_block()
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] LLM Planning Phase:")
            logger.debug(f"  User: {user_input}")
            logger.debug(f"  Dialog Summary (memory-lite): {dialog_summary or 'None'}")
            logger.debug(f"  Recent History: {len(conversation_history)} turns")
            logger.debug(f"  Tool Results: {len(context.get('last_tool_results', []))}")
        
        # Call orchestrator with memory-lite summary
        output = self.orchestrator.route(
            user_input=user_input,
            dialog_summary=dialog_summary if dialog_summary else None,
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
        })
        
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
            
            # Confirmation firewall (destructive operations)
            if tool_name in self.config.require_confirmation_for:
                if not output.requires_confirmation:
                    logger.warning(
                        f"Tool {tool_name} requires confirmation but LLM didn't set requires_confirmation=True. "
                        f"Skipping tool for safety."
                    )
                    tool_results.append({
                        "tool": tool_name,
                        "success": False,
                        "error": "Confirmation required but not requested by LLM",
                    })
                    continue
                
                if not state.has_pending_confirmation():
                    # First time asking - don't execute yet
                    logger.info(f"Tool {tool_name} requires confirmation. Asking user first.")
                    state.set_pending_confirmation({
                        "tool": tool_name,
                        "prompt": output.confirmation_prompt,
                        "slots": output.slots,
                    })
                    tool_results.append({
                        "tool": tool_name,
                        "success": False,
                        "pending_confirmation": True,
                    })
                    continue
                else:
                    # Confirmation already pending - this is the confirmed execution
                    logger.info(f"Tool {tool_name} executing with confirmation.")
                    state.clear_pending_confirmation()
            
            # Get tool definition
            try:
                tool = self.tools.get(tool_name)
                if tool is None:
                    raise ValueError(f"Tool not found: {tool_name}")
                
                if tool.function is None:
                    raise ValueError(f"Tool {tool_name} has no function implementation")
                
                # Build parameters: prefer explicit tool_plan args, else fall back to slots.
                args = tool_args_by_name.get(tool_name)
                if args is not None:
                    params = dict(output.slots)
                    params.update(args)
                else:
                    params = self._build_tool_params(tool_name, output.slots)
                
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
                
                tool_results.append({
                    "tool": tool_name,
                    "success": True,
                    "result": str(result)[:500],  # Truncate
                })
                
                # Add to state
                state.add_tool_result(tool_name, result, success=True)
                
                # Audit successful execution
                if self.safety_guard:
                    self.safety_guard.audit_decision(
                        decision_type="tool_execute",
                        tool_name=tool_name,
                        allowed=True,
                        reason="Tool executed successfully",
                        metadata={"params": params},
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
                })
                state.add_tool_result(tool_name, str(e), success=False)
        
        return tool_results
    
    def _build_tool_params(self, tool_name: str, slots: dict[str, Any]) -> dict[str, Any]:
        """Build tool parameters from orchestrator slots.
        
        This maps orchestrator slots to tool-specific parameters.
        """
        # TODO: Implement proper parameter mapping
        # For now, pass slots directly (works for calendar tools)
        return dict(slots)
    
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
        # If LLM asked a clarifying question, ensure we have a user-visible reply.
        if orchestrator_output.ask_user and orchestrator_output.question and not orchestrator_output.assistant_reply:
            from dataclasses import replace

            return replace(orchestrator_output, assistant_reply=orchestrator_output.question)

        # Hybrid mode: if a finalizer LLM is provided, optionally generate the
        # user-facing reply using that model (e.g., 7B), while keeping planning/tool
        # decisions from the planner model (e.g., 3B).
        if self.finalizer_llm is not None:
            use_finalizer = True
            try:
                # Default behavior is unchanged unless tiering is enabled.
                from bantz.llm.tiered import decide_tier

                decision = decide_tier(
                    user_input,
                    tool_names=orchestrator_output.tool_plan,
                    requires_confirmation=bool(orchestrator_output.requires_confirmation),
                )
                if decision.reason == "tiering_disabled":
                    use_finalizer = True
                else:
                    use_finalizer = bool(decision.use_quality)
            except Exception:
                use_finalizer = True

        if self.finalizer_llm is not None and use_finalizer:
            try:
                context = state.get_context_for_llm()
                dialog_summary = self.memory.to_prompt_block()

                prompt_lines = [
                    "Kimlik / Roller:",
                    "- Sen BANTZ'sın. Kullanıcı USER'dır.",
                    "- Türkçe konuş; 'Efendim' hitabını kullan.",
                    "- Sadece kullanıcıya söyleyeceğin metni üret; JSON/Markdown yok.",
                    "",
                ]

                if dialog_summary:
                    prompt_lines.append(f"DIALOG_SUMMARY:\n{dialog_summary}\n")

                prompt_lines.append("PLANNER_DECISION (JSON):")
                prompt_lines.append(
                    json.dumps(
                        {
                            "route": orchestrator_output.route,
                            "calendar_intent": orchestrator_output.calendar_intent,
                            "slots": orchestrator_output.slots,
                            "tool_plan": orchestrator_output.tool_plan,
                            "requires_confirmation": orchestrator_output.requires_confirmation,
                            "confirmation_prompt": orchestrator_output.confirmation_prompt,
                            "ask_user": orchestrator_output.ask_user,
                            "question": orchestrator_output.question,
                        },
                        ensure_ascii=False,
                    )
                )

                if tool_results:
                    prompt_lines.append("\nTOOL_RESULTS (JSON):")
                    prompt_lines.append(json.dumps(tool_results, ensure_ascii=False))

                recent = context.get("recent_conversation")
                if isinstance(recent, list) and recent:
                    prompt_lines.append("\nRECENT_TURNS:")
                    for turn in recent[-2:]:
                        if isinstance(turn, dict):
                            u = str(turn.get("user") or "").strip()
                            a = str(turn.get("assistant") or "").strip()
                            if u:
                                prompt_lines.append(f"USER: {u}")
                            if a:
                                prompt_lines.append(f"ASSISTANT: {a}")

                prompt_lines.append(f"\nUSER: {user_input}\nASSISTANT:")

                try:
                    final_text = self.finalizer_llm.complete_text(
                        prompt="\n".join(prompt_lines),
                        temperature=0.2,
                        max_tokens=256,
                    )
                except TypeError:
                    final_text = self.finalizer_llm.complete_text(prompt="\n".join(prompt_lines))

                final_text = str(final_text or "").strip()
                if final_text:
                    from dataclasses import replace

                    return replace(orchestrator_output, assistant_reply=final_text)
            except Exception:
                # Fall back to non-hybrid behavior below.
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
        
        # Generate generic success message (preserve orchestrator fields)
        success_msg = "Tamamlandı efendim."
        if len(tool_results) > 1:
            success_msg = f"{len(tool_results)} işlem tamamlandı efendim."
        
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
