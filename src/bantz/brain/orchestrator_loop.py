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
from bantz.core.events import EventBus, EventType

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for orchestrator loop."""
    
    max_steps: int = 8  # Max tool execution steps per turn
    debug: bool = False  # Debug mode (verbose logging)
    require_confirmation_for: list[str] = None  # Tools requiring confirmation
    
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
    ):
        self.orchestrator = orchestrator
        self.tools = tools
        self.event_bus = event_bus or EventBus()
        self.config = config or OrchestratorConfig()
    
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
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] LLM Planning Phase:")
            logger.debug(f"  User: {user_input}")
            logger.debug(f"  Rolling Summary: {context.get('rolling_summary', 'None')}")
            logger.debug(f"  Recent History: {len(conversation_history)} turns")
            logger.debug(f"  Tool Results: {len(context.get('last_tool_results', []))}")
        
        # Call orchestrator (Note: current route() method doesn't support conversation_history yet)
        # TODO: Extend route() to accept rolling summary and conversation history
        output = self.orchestrator.route(user_input=user_input)
        
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
        """Phase 2: Tool Execution (with confirmation firewall).
        
        Confirmation firewall:
        - If tool is in require_confirmation_for list, check requires_confirmation=True
        - If requires_confirmation but no pending confirmation, skip tool (ask first)
        - If confirmed, execute tool
        
        Returns:
            List of tool results
        """
        if not output.tool_plan:
            return []
        
        tool_results = []
        
        for tool_name in output.tool_plan:
            if self.config.debug:
                logger.debug(f"[ORCHESTRATOR] Executing tool: {tool_name}")
            
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
            
            # Execute tool
            try:
                tool = self.tools.get_tool(tool_name)
                if tool is None:
                    raise ValueError(f"Tool not found: {tool_name}")
                
                # Build parameters from slots
                params = self._build_tool_params(tool_name, output.slots)
                
                # Execute
                result = tool.execute(**params)
                
                tool_results.append({
                    "tool": tool_name,
                    "success": True,
                    "result": str(result)[:500],  # Truncate
                })
                
                # Add to state
                state.add_tool_result(tool_name, result, success=True)
                
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
        if not tool_results:
            return orchestrator_output
        
        # Check if any tools failed
        failed_tools = [r for r in tool_results if not r.get("success", False)]
        
        if failed_tools:
            # Generate error response
            error_msg = "Üzgünüm efendim, bazı işlemler başarısız oldu:\n"
            for result in failed_tools:
                error_msg += f"- {result['tool']}: {result.get('error', 'Unknown error')}\n"
            
            return OrchestratorOutput(
                route=orchestrator_output.route,
                calendar_intent=orchestrator_output.calendar_intent,
                slots=orchestrator_output.slots,
                confidence=orchestrator_output.confidence,
                tool_plan=orchestrator_output.tool_plan,
                assistant_reply=error_msg.strip(),
                raw_output=orchestrator_output.raw_output,
            )
        
        # Tools succeeded - use original response or generate success message
        if orchestrator_output.assistant_reply:
            return orchestrator_output
        
        # Generate generic success message
        success_msg = "Tamamlandı efendim."
        if len(tool_results) > 1:
            success_msg = f"{len(tool_results)} işlem tamamlandı efendim."
        
        return OrchestratorOutput(
            route=orchestrator_output.route,
            calendar_intent=orchestrator_output.calendar_intent,
            slots=orchestrator_output.slots,
            confidence=orchestrator_output.confidence,
            tool_plan=orchestrator_output.tool_plan,
            assistant_reply=success_msg,
            raw_output=orchestrator_output.raw_output,
        )
    
    def _update_state_phase(
        self,
        user_input: str,
        output: OrchestratorOutput,
        tool_results: list[dict[str, Any]],
        state: OrchestratorState,
    ) -> None:
        """Phase 4: Update State (rolling summary, conversation history, trace).
        
        Updates:
        - Rolling summary (from LLM's memory_update)
        - Conversation history (user + assistant)
        - Trace metadata (for testing/debugging)
        """
        # Update rolling summary
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
        state.update_trace(
            route_source="llm",  # Everything comes from LLM now
            route=output.route,
            intent=output.calendar_intent,
            confidence=output.confidence,
            tool_plan_len=len(output.tool_plan),
            tools_executed=len(tool_results),
            tools_success=[r.get("success", False) for r in tool_results],
            requires_confirmation=output.requires_confirmation,
            ask_user=output.ask_user,
            reasoning_summary=output.reasoning_summary,
        )
        
        if self.config.debug:
            logger.debug(f"[ORCHESTRATOR] State Updated:")
            logger.debug(f"  Rolling Summary: {state.rolling_summary[:100]}...")
            logger.debug(f"  Conversation Turns: {len(state.conversation_history)}")
            logger.debug(f"  Tool Results: {len(state.last_tool_results)}")
