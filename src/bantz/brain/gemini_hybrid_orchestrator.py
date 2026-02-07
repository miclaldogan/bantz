"""Gemini Hybrid Orchestrator - 3B Router + Gemini Finalizer.

Strategy (Issues #131, #134, #135):
- Phase 1: 3B Local Router (vLLM) - Fast routing & slot extraction (~50ms)
- Phase 2: Tool Execution (if confirmed)
- Phase 3: Gemini Finalizer (Flash/Pro) - Natural language response generation

Architecture:
    User Input
        ↓
    3B Router (local)
    - Route classification (calendar/smalltalk/unknown)
    - Intent extraction (create/modify/cancel/query)
    - Slot extraction (date/time/title/duration)
    - Tool planning
        ↓
    [Tool Execution if approved]
        ↓
    Gemini Finalizer (cloud)
    - Natural language response
    - Context-aware replies
    - Jarvis personality
        ↓
    User Output

Benefits:
- Low latency: 3B router is fast (41ms TTFT)
- High quality: Gemini for natural responses
- Cost effective: Cloud only for finalization
- Privacy: Sensitive planning stays local
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from bantz.brain.llm_router import (
    OrchestratorOutput,
    JarvisLLMOrchestrator,
)
from bantz.llm.base import LLMClient, LLMMessage
from bantz.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


def _summarize_tool_results_for_gemini(
    tool_results: list[dict[str, Any]],
    max_chars: int = 2000,
) -> tuple[str, bool]:
    """Summarize tool results for Gemini context, preventing overflow.
    
    Prevents context overflow by truncating large tool results to max_chars.
    Uses smart truncation:
    - Lists: First 5 items + metadata
    - Dicts with "events": Calendar-aware preview (5 events + metadata)
    - Large strings/dicts: Truncate to 500 chars
    - Fallback: Keep only first 3 tools if still too large
    
    Args:
        tool_results: List of tool results to summarize
        max_chars: Maximum characters allowed (default 2000 = ~2KB)
        
    Returns:
        Tuple of (summary_str, was_truncated)
    """
    if not tool_results:
        return "", False
    
    def _truncate_single_result(result: Any, max_size: int = 500) -> tuple[Any, bool]:
        """Truncate a single result value."""
        truncated = False
        
        if isinstance(result, list):
            if len(result) > 5:
                truncated = True
                preview = result[:5]
                return {
                    "_preview": preview,
                    "_truncated": True,
                    "_total_count": len(result),
                    "_message": f"Showing first 5 of {len(result)} items"
                }, truncated
            return result, False
            
        elif isinstance(result, dict):
            # Special handling for calendar events
            if "events" in result and isinstance(result["events"], list):
                events = result["events"]
                if len(events) > 5:
                    truncated = True
                    return {
                        "events": events[:5],
                        "_preview": True,
                        "_total_events": len(events),
                        "_message": f"Showing first 5 of {len(events)} events",
                        **{k: v for k, v in result.items() if k != "events"}
                    }, truncated
                return result, False
            
            # Generic dict truncation
            result_str = json.dumps(result, ensure_ascii=False)
            if len(result_str) > max_size:
                truncated = True
                return f"{result_str[:max_size]}... (truncated from {len(result_str)} chars)", truncated
            return result, False
            
        elif isinstance(result, str):
            if len(result) > max_size:
                truncated = True
                return f"{result[:max_size]}... (truncated from {len(result)} chars)", truncated
            return result, False
            
        return result, False
    
    # First pass: Try to fit all tool results with smart truncation
    summarized_results = []
    any_truncated = False
    
    for tool_result in tool_results:
        summarized = tool_result.copy()
        if "result" in summarized:
            truncated_result, was_truncated = _truncate_single_result(summarized["result"])
            summarized["result"] = truncated_result
            any_truncated = any_truncated or was_truncated
        summarized_results.append(summarized)
    
    # Convert to JSON and check size
    try:
        results_str = json.dumps(summarized_results, ensure_ascii=False)
    except (TypeError, ValueError):
        # Fallback to string representation if JSON fails
        results_str = str(summarized_results)
        any_truncated = True
    
    # If still too large, keep only first 3 tools and truncate more aggressively
    if len(results_str) > max_chars:
        any_truncated = True
        aggressive_results = []
        for tool_result in tool_results[:3]:  # Only first 3 tools
            aggressive = {
                "tool_name": tool_result.get("tool_name", "unknown"),
                "status": tool_result.get("status", "unknown"),
            }
            if "result" in tool_result:
                result_preview, _ = _truncate_single_result(tool_result["result"], max_size=200)
                aggressive["result"] = result_preview
            aggressive_results.append(aggressive)
        
        try:
            results_str = json.dumps(aggressive_results, ensure_ascii=False)
        except (TypeError, ValueError):
            results_str = str(aggressive_results)
        
        # Final truncation if still too large
        if len(results_str) > max_chars:
            results_str = results_str[:max_chars] + "... (truncated)"
    
    return results_str, any_truncated


class Local3BRouterProtocol(Protocol):
    """Protocol for local 3B router (vLLM)."""

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        """Complete text from prompt."""
        ...


@dataclass(frozen=True)
class HybridOrchestratorConfig:
    """Configuration for Gemini Hybrid Orchestrator.
    
    Attributes:
        router_backend: Router backend ("vllm")
        router_model: Router model name (e.g., "Qwen/Qwen2.5-3B-Instruct")
        router_temperature: Temperature for router (0.0 for deterministic)
        router_max_tokens: Max tokens for router output
        
        gemini_model: Gemini model (e.g., "gemini-1.5-flash", "gemini-1.5-pro")
        gemini_temperature: Temperature for Gemini (0.4 for balanced)
        gemini_max_tokens: Max tokens for Gemini response
        
        confidence_threshold: Minimum confidence to call tools (0.7 default)
        enable_gemini_finalization: If False, only use router (debug mode)
    """
    
    router_backend: str = "vllm"
    router_model: str = "Qwen/Qwen2.5-3B-Instruct"
    router_temperature: float = 0.0
    router_max_tokens: int = 512
    
    gemini_model: str = "gemini-1.5-flash"
    gemini_temperature: float = 0.4
    gemini_max_tokens: int = 512
    
    confidence_threshold: float = 0.7
    enable_gemini_finalization: bool = True


class GeminiHybridOrchestrator:
    """Hybrid orchestrator: 3B router (local) + Gemini finalizer (cloud).
    
    .. deprecated::
        Use ``bantz.brain.hybrid_orchestrator.HybridOrchestrator`` instead.
        ``GeminiHybridOrchestrator`` will be removed in a future release.
        See Issue #412 for migration details.

    This implements the strategy from Issues #131, #134, #135:
    - Fast routing with local 3B model
    - Quality responses with Gemini
    
    Usage:
        router = create_3b_router()  # vLLM
        gemini = GeminiClient(api_key="...", model="gemini-1.5-flash")
        orchestrator = GeminiHybridOrchestrator(
            router=router,
            gemini_client=gemini,
            config=config
        )
        
        output = orchestrator.orchestrate(
            user_input="bugün toplantılarım neler?",
            dialog_summary="",
            tool_results=None
        )
    """
    
    def __init__(
        self,
        *,
        router: Local3BRouterProtocol,
        gemini_client: GeminiClient,
        config: Optional[HybridOrchestratorConfig] = None,
    ):
        import warnings
        warnings.warn(
            "GeminiHybridOrchestrator is deprecated. "
            "Use bantz.brain.hybrid_orchestrator.HybridOrchestrator instead. "
            "See Issue #412.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._router = router
        self._gemini = gemini_client
        self._config = config or HybridOrchestratorConfig()
        
        # Internal JarvisLLMOrchestrator for router prompts
        self._router_orchestrator = JarvisLLMOrchestrator(llm_client=router)
    
    def orchestrate(
        self,
        *,
        user_input: str,
        dialog_summary: str = "",
        tool_results: Optional[list[dict[str, Any]]] = None,
        session_context: Optional[dict[str, Any]] = None,
        retrieved_memory: Optional[str] = None,
    ) -> OrchestratorOutput:
        """Orchestrate user input through hybrid pipeline.
        
        Args:
            user_input: User message
            dialog_summary: Rolling dialog context
            tool_results: Results from previous tool execution (list of dicts).
                          If provided, Gemini finalization will include them.
            session_context: Session context (timezone, location hints)
            retrieved_memory: Retrieved long-term memory
            
        Returns:
            OrchestratorOutput with route, intent, slots, and final response
            
        Note:
            For best results with tool-based routes, prefer the two-phase API:
            1. plan() → get router output + execute tools externally
            2. finalize() → pass tool_results to Gemini
            
            The single-call orchestrate() works but Gemini won't see tool
            results unless you pass them explicitly.
        """
        
        # Phase 1: 3B Router - Fast routing & slot extraction
        router_output = self.plan(
            user_input=user_input,
            dialog_summary=dialog_summary,
            session_context=session_context,
            retrieved_memory=retrieved_memory,
        )
        
        # If ask_user or low confidence, skip finalization
        if router_output.ask_user:
            return router_output
        if router_output.confidence < self._config.confidence_threshold:
            return router_output
        
        # Phase 2: Tool execution happens externally (BrainLoop/OrchestratorLoop)
        # If tool_results were passed in, they'll be forwarded to Gemini.
        
        # Phase 3: Gemini Finalizer
        return self.finalize(
            router_output=router_output,
            user_input=user_input,
            dialog_summary=dialog_summary,
            tool_results=tool_results,
        )
    
    def plan(
        self,
        *,
        user_input: str,
        dialog_summary: str = "",
        session_context: Optional[dict[str, Any]] = None,
        retrieved_memory: Optional[str] = None,
    ) -> OrchestratorOutput:
        """Phase 1 only: Run 3B router to get routing decision without finalization.
        
        Issue #408: Two-phase API so callers can execute tools between
        plan() and finalize(), ensuring Gemini sees real tool results.
        
        Args:
            user_input: User message
            dialog_summary: Rolling dialog context
            session_context: Session context
            retrieved_memory: Retrieved long-term memory
            
        Returns:
            OrchestratorOutput from 3B router (no Gemini finalization)
        """
        logger.info("[HYBRID] Phase 1: 3B Router")
        router_output = self._router_orchestrator.route(
            user_input=user_input,
            dialog_summary=dialog_summary,
            session_context=session_context,
            retrieved_memory=retrieved_memory,
            temperature=self._config.router_temperature,
            max_tokens_override=self._config.router_max_tokens,
        )
        
        logger.debug(
            f"[HYBRID] Router: route={router_output.route}, "
            f"intent={router_output.calendar_intent}, "
            f"confidence={router_output.confidence:.2f}"
        )
        
        return router_output
    
    def finalize(
        self,
        *,
        router_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str = "",
        tool_results: Optional[list[dict[str, Any]]] = None,
    ) -> OrchestratorOutput:
        """Phase 3 only: Run Gemini finalizer with tool results.
        
        Issue #408: Two-phase API — call this after external tool execution
        so Gemini gets the actual tool results instead of None.
        
        Args:
            router_output: Output from plan() phase
            user_input: Original user input
            dialog_summary: Rolling dialog context
            tool_results: Results from tool execution (list of dicts)
            
        Returns:
            OrchestratorOutput with Gemini-generated assistant_reply
        """
        # If ask_user is set, return immediately
        if router_output.ask_user:
            logger.info("[HYBRID] Router wants clarification, skipping Gemini")
            return router_output
        
        # If confidence too low, return as-is
        if router_output.confidence < self._config.confidence_threshold:
            logger.warning(
                f"[HYBRID] Low confidence ({router_output.confidence:.2f}), "
                f"skipping Gemini"
            )
            return router_output
        
        # Skip finalization if disabled
        if not self._config.enable_gemini_finalization:
            logger.info("[HYBRID] Gemini finalization disabled, using router response")
            return router_output
        
        logger.info("[HYBRID] Phase 3: Gemini Finalizer (tool_results=%s)",
                     "present" if tool_results else "none")
        final_response = self._finalize_with_gemini(
            router_output=router_output,
            user_input=user_input,
            dialog_summary=dialog_summary,
            tool_results=tool_results,
        )
        
        # Merge router output with Gemini response
        return OrchestratorOutput(
            route=router_output.route,
            calendar_intent=router_output.calendar_intent,
            slots=router_output.slots,
            confidence=router_output.confidence,
            tool_plan=router_output.tool_plan,
            assistant_reply=final_response,
            ask_user=router_output.ask_user,
            question=router_output.question,
            requires_confirmation=router_output.requires_confirmation,
            confirmation_prompt=router_output.confirmation_prompt,
            memory_update=router_output.memory_update,
            reasoning_summary=router_output.reasoning_summary,
            raw_output={
                "router": router_output.raw_output,
                "gemini_response": final_response,
            },
        )
    
    def _finalize_with_gemini(
        self,
        *,
        router_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str,
        tool_results: Optional[list[dict[str, Any]]],
    ) -> str:
        """Generate natural language response using Gemini.
        
        Args:
            router_output: Output from 3B router
            user_input: Original user input
            dialog_summary: Dialog context
            tool_results: Tool execution results (list of dicts)
            
        Returns:
            Natural language response (Jarvis style)
        """
        
        # Build context for Gemini
        context_parts = []
        
        if dialog_summary:
            context_parts.append(f"Dialog Context:\n{dialog_summary}")
        
        context_parts.append(f"User: {user_input}")
        
        if router_output.route == "calendar":
            context_parts.append(f"Intent: {router_output.calendar_intent}")
            if router_output.slots:
                slots_str = json.dumps(router_output.slots, ensure_ascii=False)
                context_parts.append(f"Extracted Slots: {slots_str}")
        
        if tool_results:
            # tool_results is now list[dict], convert to JSON with size control
            results_str, was_truncated = _summarize_tool_results_for_gemini(tool_results, max_chars=2000)
            context_parts.append(f"Tool Results: {results_str}")
            if was_truncated:
                logger.warning(
                    f"Tool results truncated for Gemini context (original size exceeded 2KB)"
                )
        
        context = "\n\n".join(context_parts)
        
        # Gemini system prompt (Jarvis personality)
        system_prompt = """Sen BANTZ'sın - Jarvis tarzı Türkçe asistan.

Özellikler:
- "Efendim" hitabı kullan
- Nazik, profesyonel ama samimi
- Kısa ve öz cevaplar (1-2 cümle ideal)
- Türkçe doğal konuş (İngilizce teknik terimler OK)

Görev:
Kullanıcıya verilen context'e göre doğal, yardımsever bir cevap ver.
Takvim işlemlerinde sonucu özetle.
Sohbette samimi ve kısa cevap ver.
"""
        
        # Special handling for smalltalk
        if router_output.route == "smalltalk":
            system_prompt += "\n\nBu bir sohbet mesajı. Samimi ve kısa yanıt ver (1 cümle yeterli)."
        
        # Build Gemini prompt
        if router_output.route == "calendar" and tool_results:
            user_prompt = (
                f"{context}\n\n"
                "Yukarıdaki takvim işleminin sonucunu kullanıcıya kısa ve öz şekilde aktar. "
                "Jarvis tarzında, profesyonel ama samimi ol."
            )
        elif router_output.route == "smalltalk":
            user_prompt = (
                f"Kullanıcı: {user_input}\n\n"
                "Samimi ve kısa bir yanıt ver (1-2 cümle). Jarvis tarzında."
            )
        else:
            user_prompt = (
                f"{context}\n\n"
                "Kullanıcıya yardımcı ol. Kısa ve öz yanıt ver."
            )
        
        # Call Gemini
        try:
            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ]
            
            response = self._gemini.chat_detailed(
                messages=messages,
                temperature=self._config.gemini_temperature,
                max_tokens=self._config.gemini_max_tokens,
            )
            
            logger.info(
                f"[HYBRID] Gemini finalization: {len(response.content)} chars, "
                f"{response.tokens_used} tokens"
            )
            
            gemini_text = response.content.strip()
            
            # Issue #357: no-new-facts guard (numbers/time/date must not be invented).
            # Gemini should not hallucinate numeric facts that aren't in the input sources.
            if gemini_text:
                try:
                    from bantz.llm.no_new_facts import find_new_numeric_facts
                    
                    # Build allowed sources: user input, context, tool results
                    allowed_sources = [user_input]
                    if dialog_summary:
                        allowed_sources.append(dialog_summary)
                    if router_output.slots:
                        allowed_sources.append(json.dumps(router_output.slots, ensure_ascii=False))
                    if tool_results:
                        allowed_sources.append(json.dumps(tool_results, ensure_ascii=False))
                    
                    violates, new_tokens = find_new_numeric_facts(
                        allowed_texts=allowed_sources,
                        candidate_text=gemini_text,
                    )
                    
                    if violates:
                        logger.warning(
                            f"[HYBRID] Gemini response contains new numeric facts: {new_tokens}, retrying with strict constraint"
                        )
                        
                        # Retry with stricter prompt
                        strict_system = system_prompt + (
                            "\n\nSTRICT_NO_NEW_FACTS: Sadece verilen context'te geçen sayı/saat/tarihleri kullan. "
                            "Yeni rakam ekleme. Gerekirse rakam içeren detayları çıkar."
                        )
                        
                        retry_messages = [
                            LLMMessage(role="system", content=strict_system),
                            LLMMessage(role="user", content=user_prompt),
                        ]
                        
                        retry_response = self._gemini.chat_detailed(
                            messages=retry_messages,
                            temperature=0.2,  # Lower temperature for stricter adherence
                            max_tokens=self._config.gemini_max_tokens,
                        )
                        
                        retry_text = retry_response.content.strip()
                        
                        if retry_text:
                            # Check retry result
                            violates2, _new2 = find_new_numeric_facts(
                                allowed_texts=allowed_sources,
                                candidate_text=retry_text,
                            )
                            
                            if not violates2:
                                logger.info("[HYBRID] Retry succeeded, using corrected response")
                                gemini_text = retry_text
                            else:
                                # Retry still violates, fall back to router response
                                logger.warning("[HYBRID] Retry still violates guard, falling back to router response")
                                gemini_text = router_output.assistant_reply or "Anladım efendim."
                        else:
                            # Empty retry, fall back to router response
                            logger.warning("[HYBRID] Empty retry response, falling back to router response")
                            gemini_text = router_output.assistant_reply or "Anladım efendim."
                            
                except Exception as guard_exc:
                    # Guard is best-effort, don't block user
                    logger.debug(f"[HYBRID] no-new-facts guard error: {guard_exc}")
                    # Continue with original Gemini response
            
            return gemini_text
            
        except Exception as e:
            logger.error(f"[HYBRID] Gemini finalization failed: {e}")
            # Fallback to router response
            return router_output.assistant_reply or "Üzgünüm efendim, bir sorun oluştu."


def create_gemini_hybrid_orchestrator(
    *,
    router_client: Local3BRouterProtocol,
    gemini_api_key: str,
    config: Optional[HybridOrchestratorConfig] = None,
) -> GeminiHybridOrchestrator:
    """Create Gemini Hybrid Orchestrator with given configuration.
    
    Args:
        router_client: 3B router client (vLLM)
        gemini_api_key: Gemini API key
        config: Optional configuration (uses defaults if None)
        
    Returns:
        Configured GeminiHybridOrchestrator
        
    Example:
        >>> from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        >>> router = VLLMOpenAIClient(
        ...     base_url="http://localhost:8001",
        ...     model="Qwen/Qwen2.5-3B-Instruct"
        ... )
        >>> orchestrator = create_gemini_hybrid_orchestrator(
        ...     router_client=router,
        ...     gemini_api_key="YOUR_API_KEY"
        ... )
    """
    
    config = config or HybridOrchestratorConfig()
    
    gemini = GeminiClient(
        api_key=gemini_api_key,
        model=config.gemini_model,
        timeout_seconds=30.0,
    )
    
    return GeminiHybridOrchestrator(
        router=router_client,
        gemini_client=gemini,
        config=config,
    )
