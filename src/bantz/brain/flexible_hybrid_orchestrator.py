"""Flexible Hybrid Orchestrator - 3B Router + (Gemini OR 7B vLLM) Finalizer.

Issue #157: OrchestratorLoop Hybrid Split

Strategy:
- Phase 1: 3B Local Router (vLLM port 8001) - Fast routing (~40ms)
- Phase 2: Tool Execution (if confirmed)  
- Phase 3: Flexible Finalizer:
  - Option A: Gemini (Flash/Pro) - Highest quality
  - Option B: 7B vLLM (port 8002) - Local, privacy-preserving
  - Fallback: 3B router if both fail

Architecture:
    User Input
        ↓
    3B Router (vLLM :8001)
    - Route classification
    - Intent & slot extraction
        ↓
    [Tool Execution]
        ↓
    Finalizer (Gemini OR 7B vLLM :8002)
    - Natural language response
    - Streaming support
    - Fallback to 3B if unavailable
        ↓
    User Output

Benefits:
- Flexible: Choose Gemini (quality) or 7B (privacy)
- Fallback: Graceful degradation if 7B/Gemini down
- Streaming: TTS-ready streaming responses
- Low latency: TTFT <500ms target
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Literal

from bantz.brain.llm_router import OrchestratorOutput, JarvisLLMOrchestrator
from bantz.llm.base import LLMClient, LLMMessage


logger = logging.getLogger(__name__)


class FinalizerProtocol(Protocol):
    """Protocol for finalizer LLM (Gemini or 7B vLLM)."""

    def chat_detailed(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> Any:
        """Chat with detailed response."""
        ...

    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        """Check if finalizer is reachable."""
        ...


@dataclass(frozen=True)
class FlexibleHybridConfig:
    """Configuration for Flexible Hybrid Orchestrator.
    
    Attributes:
        router_backend: 3B router backend ("vllm")
        router_model: 3B model name
        router_temperature: Temperature for router (0.0 deterministic)
        router_max_tokens: Max tokens for router output
        
        finalizer_type: "gemini" or "vllm_7b"
        finalizer_model: Finalizer model name
        finalizer_temperature: Temperature for finalizer (0.4-0.7)
        finalizer_max_tokens: Max tokens for finalizer response
        
        fallback_to_3b: If True, use 3B router as fallback finalizer
        enable_streaming: Enable streaming for TTS integration
        confidence_threshold: Min confidence to execute tools (0.7)
    """
    
    # Router (3B)
    router_backend: str = "vllm"
    router_model: str = "Qwen/Qwen2.5-3B-Instruct"
    router_temperature: float = 0.0
    router_max_tokens: int = 512
    
    # Finalizer (Gemini OR 7B vLLM)
    finalizer_type: Literal["gemini", "vllm_7b"] = "vllm_7b"
    finalizer_model: str = "Qwen/Qwen2.5-7B-Instruct"
    finalizer_temperature: float = 0.6
    finalizer_max_tokens: int = 512
    
    # Fallback & features
    fallback_to_3b: bool = True
    enable_streaming: bool = False
    confidence_threshold: float = 0.7


class FlexibleHybridOrchestrator:
    """Flexible hybrid orchestrator: 3B router + (Gemini OR 7B) finalizer.
    
    This implements Issue #157:
    - Phase 1: 3B router (fast planning)
    - Phase 2: Tool execution
    - Phase 3: Flexible finalizer (Gemini OR 7B vLLM with fallback)
    
    Usage:
        >>> from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        >>> router = VLLMOpenAIClient(base_url="http://localhost:8001", model="Qwen/Qwen2.5-3B-Instruct")
        >>> finalizer = VLLMOpenAIClient(base_url="http://localhost:8002", model="Qwen/Qwen2.5-7B-Instruct")
        >>> config = FlexibleHybridConfig(finalizer_type="vllm_7b")
        >>> orchestrator = FlexibleHybridOrchestrator(
        ...     router_orchestrator=jarvis_orchestrator,
        ...     finalizer=finalizer,
        ...     config=config,
        ... )
    """
    
    def __init__(
        self,
        router_orchestrator: JarvisLLMOrchestrator,
        finalizer: Optional[FinalizerProtocol] = None,
        config: Optional[FlexibleHybridConfig] = None,
    ):
        """Initialize flexible hybrid orchestrator.
        
        Args:
            router_orchestrator: 3B router orchestrator
            finalizer: Finalizer LLM (Gemini or 7B vLLM) - optional for fallback mode
            config: Configuration (uses defaults if None)
        """
        self._router_orchestrator = router_orchestrator
        self._finalizer = finalizer
        self._config = config or FlexibleHybridConfig()
        
        # Check finalizer availability
        self._finalizer_available = self._check_finalizer_availability()
        
        logger.info(
            f"[FLEXIBLE-HYBRID] Router: {self._config.router_backend}/{self._config.router_model}, "
            f"Finalizer: {self._config.finalizer_type}/{self._config.finalizer_model}, "
            f"Available: {self._finalizer_available}, Fallback: {self._config.fallback_to_3b}"
        )
    
    def _check_finalizer_availability(self) -> bool:
        """Check if finalizer is available."""
        if self._finalizer is None:
            logger.warning("[FLEXIBLE-HYBRID] No finalizer configured, fallback mode only")
            return False
        
        try:
            is_avail = self._finalizer.is_available(timeout_seconds=1.5)
            if not is_avail:
                logger.warning(f"[FLEXIBLE-HYBRID] Finalizer ({self._config.finalizer_type}) not available")
            return is_avail
        except Exception as e:
            logger.warning(f"[FLEXIBLE-HYBRID] Finalizer availability check failed: {e}")
            return False
    
    def plan(
        self,
        user_input: str,
        *,
        dialog_summary: str = "",
        tool_results: Optional[dict[str, Any]] = None,
    ) -> OrchestratorOutput:
        """Full hybrid planning + finalization.
        
        Flow:
        1. Phase 1: 3B router planning
        2. Phase 3: Finalizer response (Gemini OR 7B vLLM with fallback)
        
        Args:
            user_input: User input
            dialog_summary: Dialog context
            tool_results: Tool execution results (from Phase 2)
            
        Returns:
            OrchestratorOutput with finalized assistant_reply
        """
        
        # Phase 1: 3B Router Planning
        logger.info(f"[FLEXIBLE-HYBRID] Phase 1: 3B router planning for '{user_input[:50]}...'")
        router_output = self._router_orchestrator.plan(
            user_input=user_input,
            dialog_summary=dialog_summary,
        )
        
        logger.info(
            f"[FLEXIBLE-HYBRID] Router: route={router_output.route}, "
            f"intent={router_output.calendar_intent}, conf={router_output.confidence:.2f}"
        )
        
        # Phase 3: Finalization (Gemini OR 7B vLLM with fallback)
        final_response = self._finalize_response(
            router_output=router_output,
            user_input=user_input,
            dialog_summary=dialog_summary,
            tool_results=tool_results,
        )
        
        # Return finalized output
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
                "finalizer_type": self._get_active_finalizer_type(),
            },
        )
    
    def _finalize_response(
        self,
        *,
        router_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str,
        tool_results: Optional[dict[str, Any]],
    ) -> str:
        """Generate final response using flexible finalizer with fallback.
        
        Strategy:
        1. Try primary finalizer (Gemini OR 7B vLLM)
        2. On failure, fallback to 3B router response
        3. Log all attempts for debugging
        
        Args:
            router_output: Output from 3B router
            user_input: Original user input
            dialog_summary: Dialog context
            tool_results: Tool execution results
            
        Returns:
            Final natural language response
        """
        
        # Check if finalizer is available
        if not self._finalizer_available:
            logger.warning("[FLEXIBLE-HYBRID] Finalizer unavailable, using 3B fallback")
            return self._fallback_to_router(router_output)
        
        # Try primary finalizer
        try:
            logger.info(f"[FLEXIBLE-HYBRID] Phase 3: {self._config.finalizer_type} finalization")
            final_response = self._call_finalizer(
                router_output=router_output,
                user_input=user_input,
                dialog_summary=dialog_summary,
                tool_results=tool_results,
            )
            
            logger.info(f"[FLEXIBLE-HYBRID] Finalization successful: {len(final_response)} chars")
            return final_response
            
        except Exception as e:
            logger.error(f"[FLEXIBLE-HYBRID] Finalizer failed: {e}")
            
            if self._config.fallback_to_3b:
                logger.warning("[FLEXIBLE-HYBRID] Falling back to 3B router response")
                return self._fallback_to_router(router_output)
            else:
                # No fallback, raise error
                raise
    
    def _call_finalizer(
        self,
        *,
        router_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str,
        tool_results: Optional[dict[str, Any]],
    ) -> str:
        """Call finalizer LLM (Gemini or 7B vLLM).
        
        Args:
            router_output: Router output
            user_input: User input
            dialog_summary: Dialog context
            tool_results: Tool results
            
        Returns:
            Natural language response
        """
        
        # Build context for finalizer
        context_parts = []
        
        if dialog_summary:
            context_parts.append(f"Dialog Context:\n{dialog_summary}")
        
        context_parts.append(f"User: {user_input}")
        
        if router_output.route == "calendar":
            context_parts.append(f"Intent: {router_output.calendar_intent}")
            if router_output.slots:
                slots_str = json.dumps(router_output.slots, ensure_ascii=False)
                context_parts.append(f"Slots: {slots_str}")
        
        if tool_results:
            results_str = json.dumps(tool_results, ensure_ascii=False)
            context_parts.append(f"Tool Results: {results_str}")
        
        context = "\n\n".join(context_parts)
        
        # System prompt (Jarvis personality)
        system_prompt = """Sen BANTZ'sın - Jarvis tarzı Türkçe asistan.

Özellikler:
- "Efendim" hitabı kullan
- Nazik, profesyonel ama samimi
- Kısa ve öz cevaplar (1-2 cümle ideal)
- Türkçe doğal konuş

Görev:
Context'e göre doğal, yardımsever bir cevap ver.
Takvim işlemlerinde sonucu özetle.
Sohbette samimi ve kısa yanıt ver.
"""
        
        # User prompt based on route
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
        
        # Call finalizer
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
        
        response = self._finalizer.chat_detailed(
            messages=messages,
            temperature=self._config.finalizer_temperature,
            max_tokens=self._config.finalizer_max_tokens,
        )
        
        return response.content.strip()
    
    def _fallback_to_router(self, router_output: OrchestratorOutput) -> str:
        """Fallback to 3B router response."""
        logger.info("[FLEXIBLE-HYBRID] Using 3B router response as fallback")
        return router_output.assistant_reply or "Üzgünüm efendim, bir sorun oluştu."
    
    def _get_active_finalizer_type(self) -> str:
        """Get active finalizer type for logging."""
        if not self._finalizer_available:
            return "3b_fallback"
        return self._config.finalizer_type


def create_flexible_hybrid_orchestrator(
    *,
    router_client: LLMClient,
    finalizer_client: Optional[LLMClient] = None,
    config: Optional[FlexibleHybridConfig] = None,
) -> FlexibleHybridOrchestrator:
    """Create flexible hybrid orchestrator with 3B router + (Gemini OR 7B) finalizer.
    
    Args:
        router_client: 3B router LLM client
        finalizer_client: Finalizer LLM client (Gemini or 7B vLLM) - optional for fallback mode
        config: Configuration (uses defaults if None)
        
    Returns:
        Configured FlexibleHybridOrchestrator
        
    Example (7B vLLM finalizer):
        >>> from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        >>> from bantz.brain.llm_router import JarvisLLMOrchestrator
        >>> 
        >>> router = VLLMOpenAIClient(base_url="http://localhost:8001", model="Qwen/Qwen2.5-3B-Instruct")
        >>> finalizer = VLLMOpenAIClient(base_url="http://localhost:8002", model="Qwen/Qwen2.5-7B-Instruct")
        >>> 
        >>> jarvis_router = JarvisLLMOrchestrator(llm_client=router)
        >>> 
        >>> config = FlexibleHybridConfig(finalizer_type="vllm_7b")
        >>> orchestrator = create_flexible_hybrid_orchestrator(
        ...     router_client=router,
        ...     finalizer_client=finalizer,
        ...     config=config,
        ... )
    
    Example (Gemini finalizer):
        >>> from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        >>> from bantz.llm.gemini_client import GeminiClient
        >>> 
        >>> router = VLLMOpenAIClient(base_url="http://localhost:8001", model="Qwen/Qwen2.5-3B-Instruct")
        >>> gemini = GeminiClient(api_key="YOUR_KEY", model="gemini-1.5-flash")
        >>> 
        >>> jarvis_router = JarvisLLMOrchestrator(llm_client=router)
        >>> 
        >>> config = FlexibleHybridConfig(finalizer_type="gemini")
        >>> orchestrator = create_flexible_hybrid_orchestrator(
        ...     router_client=router,
        ...     finalizer_client=gemini,
        ...     config=config,
        ... )
    """
    
    config = config or FlexibleHybridConfig()
    
    # Create Jarvis router orchestrator
    jarvis_router = JarvisLLMOrchestrator(llm_client=router_client)
    
    return FlexibleHybridOrchestrator(
        router_orchestrator=jarvis_router,
        finalizer=finalizer_client,
        config=config,
    )
