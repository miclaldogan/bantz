"""Unified Finalizer Strategy (Issue #356).

This module provides the shared finalizer implementation for OrchestratorLoop,
ensuring consistent quality in response generation.

Key Features:
- Unified prompt building with tool results support
- Smart truncation for large tool results (max 2000 tokens)
- No-new-facts guard to prevent hallucination
- Fallback strategies (quality → fast → draft)
- Support for different finalizer modes (off/calendar_only/smalltalk/always)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


class LLMClientProtocol(Protocol):
    """Protocol for LLM text completion."""
    
    def complete_text(self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:
        """Complete text from prompt."""
        ...


@dataclass(frozen=True)
class FinalizerConfig:
    """Configuration for finalizer behavior.
    
    Attributes:
        mode: Finalizer mode - "off", "calendar_only", "smalltalk", "always"
        temperature: LLM temperature for finalization (default 0.2)
        max_tokens: Max tokens for finalizer response (default 256)
        tool_results_token_budget: Token budget for tool results (default 2000)
        enable_no_new_facts_guard: Enable guard against hallucinated numbers/dates
        retry_on_guard_violation: Retry with stricter prompt if guard violated
    """
    mode: str = "calendar_only"
    temperature: float = 0.2
    max_tokens: int = 256
    tool_results_token_budget: int = 2000
    enable_no_new_facts_guard: bool = True
    retry_on_guard_violation: bool = True


@dataclass
class FinalizerResult:
    """Result of finalization attempt.
    
    Attributes:
        text: Final response text
        used_finalizer: Whether finalizer LLM was used (vs fallback to draft)
        was_truncated: Whether tool results were truncated
        guard_violated: Whether no-new-facts guard was violated
        guard_retried: Whether retry was attempted after guard violation
        tier_name: Tier used ("quality", "fast", or "draft")
        tier_reason: Reason for tier selection
    """
    text: str
    used_finalizer: bool = False
    was_truncated: bool = False
    guard_violated: bool = False
    guard_retried: bool = False
    tier_name: str = "draft"
    tier_reason: str = ""


def _estimate_tokens(text: str) -> int:
    """Token estimation — delegates to unified token_utils (Issue #406)."""
    from bantz.llm.token_utils import estimate_tokens
    return estimate_tokens(text)


def _prepare_tool_results_for_finalizer(
    tool_results: list[dict[str, Any]],
    max_tokens: int = 2000,
) -> tuple[list[dict[str, Any]], bool]:
    """Prepare tool results for finalizer with token budget control.
    
    Strategy (3-tier fallback):
    1. Try full raw_result for each tool
    2. If too large, use result_summary instead
    3. If still too large, keep only first 3 tools with aggressive truncation
    
    Args:
        tool_results: List of tool execution results
        max_tokens: Maximum tokens allowed for tool results
        
    Returns:
        Tuple of (prepared_results, was_truncated)
    """
    if not tool_results:
        return [], False
    
    # Tier 1: Try full raw_result
    full_results = []
    for result in tool_results:
        result_copy = {
            "tool": result.get("tool") or result.get("tool_name") or result.get("name") or "unknown",
            "status": "success" if result.get("success", True) else "error",
        }
        
        # Prefer raw_result if available (full detail)
        if "raw_result" in result:
            result_copy["result"] = result["raw_result"]
        elif "result" in result:
            result_copy["result"] = result["result"]
        elif "error" in result:
            result_copy["error"] = result["error"]
            
        full_results.append(result_copy)
    
    full_json = json.dumps(full_results, ensure_ascii=False)
    full_tokens = _estimate_tokens(full_json)
    
    if full_tokens <= max_tokens:
        return full_results, False
    
    # Tier 2: Use result_summary (medium detail)
    summary_results = []
    for result in tool_results:
        result_copy = {
            "tool": result.get("tool") or result.get("tool_name") or result.get("name") or "unknown",
            "status": "success" if result.get("success", True) else "error",
        }
        
        # Prefer result_summary if available
        if "result_summary" in result:
            result_copy["result"] = result["result_summary"]
        elif "raw_result" in result:
            # Truncate raw_result to 200 chars
            raw = json.dumps(result["raw_result"], ensure_ascii=False)
            if len(raw) > 200:
                result_copy["result"] = raw[:200] + "..."
            else:
                result_copy["result"] = result["raw_result"]
        elif "result" in result:
            result_str = str(result["result"])
            if len(result_str) > 200:
                result_copy["result"] = result_str[:200] + "..."
            else:
                result_copy["result"] = result["result"]
        elif "error" in result:
            result_copy["error"] = str(result["error"])[:200]
            
        summary_results.append(result_copy)
    
    summary_json = json.dumps(summary_results, ensure_ascii=False)
    summary_tokens = _estimate_tokens(summary_json)
    
    if summary_tokens <= max_tokens:
        return summary_results, True
    
    # Tier 3: Aggressive truncation - first 3 tools only, 200 chars each
    aggressive_results = []
    for result in tool_results[:3]:  # Only first 3 tools
        result_copy = {
            "tool": result.get("tool") or result.get("tool_name") or result.get("name") or "unknown",
            "status": "success" if result.get("success", True) else "error",
        }
        
        if "result_summary" in result:
            summary = str(result["result_summary"])
            result_copy["result"] = summary[:200] + ("..." if len(summary) > 200 else "")
        elif "result" in result or "raw_result" in result:
            res = result.get("result") or result.get("raw_result")
            res_str = json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)
            result_copy["result"] = res_str[:200] + ("..." if len(res_str) > 200 else "")
        elif "error" in result:
            result_copy["error"] = str(result["error"])[:200]
            
        aggressive_results.append(result_copy)
    
    return aggressive_results, True


def _build_finalizer_prompt(
    *,
    user_input: str,
    planner_decision: Optional[dict[str, Any]] = None,
    tool_results: Optional[list[dict[str, Any]]] = None,
    dialog_summary: Optional[str] = None,
    draft_text: Optional[str] = None,
    route: Optional[str] = None,
    last_tool: Optional[str] = None,
) -> str:
    """Build unified finalizer prompt.
    
    Supports both BrainLoop style (draft-based) and OrchestratorLoop style (decision-based).
    
    Args:
        user_input: User's message
        planner_decision: Orchestrator decision (route, intent, slots, etc.)
        tool_results: Tool execution results
        dialog_summary: Conversation history summary
        draft_text: Draft response (for BrainLoop compatibility)
        route: Route classification (for BrainLoop compatibility)
        last_tool: Last executed tool (for BrainLoop compatibility)
        
    Returns:
        Formatted finalizer prompt
    """
    prompt_lines = [
        "Kimlik / Roller:",
        "- Sen BANTZ'sın. Kullanıcı USER'dır.",
        "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
        "- 'Efendim' hitabını kullan.",
        "- Sadece kullanıcıya söyleyeceğin metni üret; JSON/Markdown yok.",
        "- Kısa ve öz cevap ver (1-2 cümle ideal).",
        "",
    ]
    
    # Add dialog history if available
    if dialog_summary:
        prompt_lines.extend([
            f"DIALOG_SUMMARY:\n{dialog_summary}",
            "",
        ])
    
    # Add planner decision if available (OrchestratorLoop style)
    if planner_decision:
        prompt_lines.extend([
            "PLANNER_DECISION (JSON):",
            json.dumps(planner_decision, ensure_ascii=False),
            "",
        ])
    
    # Add route/tool info if available (BrainLoop style)
    if route or last_tool:
        if route:
            prompt_lines.append(f"ROUTE: {route}")
        if last_tool:
            prompt_lines.append(f"LAST_TOOL: {last_tool}")
        prompt_lines.append("")
    
    # Add tool results if available
    if tool_results:
        prompt_lines.extend([
            "TOOL_RESULTS (JSON):",
            json.dumps(tool_results, ensure_ascii=False),
            "",
        ])
    
    # Add draft if available (BrainLoop style)
    if draft_text:
        prompt_lines.extend([
            "Görev: DRAFT cevabı daha doğal, kısa ve yardımcı bir dille yeniden yaz.",
            "Kural: DRAFT içindeki gerçekleri KESİN değiştirme (sayı/saat/tarih/başlık).",
            "Yeni etkinlik uydurma, ekstra detay ekleme. JSON/Markdown/backtick yazma.",
            "",
            f"DRAFT:\n{draft_text}",
            "",
        ])
    
    # Add user input and prompt for assistant response
    prompt_lines.extend([
        f"USER: {user_input}",
        "ASSISTANT (SADECE TÜRKÇE):",
    ])
    
    return "\n".join(prompt_lines)


def finalize(
    *,
    user_input: str,
    finalizer_llm: Optional[LLMClientProtocol],
    config: Optional[FinalizerConfig] = None,
    planner_decision: Optional[dict[str, Any]] = None,
    tool_results: Optional[list[dict[str, Any]]] = None,
    dialog_summary: Optional[str] = None,
    draft_text: Optional[str] = None,
    fallback_llm: Optional[LLMClientProtocol] = None,
    route: Optional[str] = None,
    last_tool: Optional[str] = None,
) -> FinalizerResult:
    """Unified finalization with quality LLM.
    
    This function provides a single entry point for both BrainLoop and OrchestratorLoop
    finalizers, with support for:
    - Smart truncation of large tool results
    - No-new-facts guard against hallucinated numbers/dates
    - Fallback strategies (quality → fast → draft)
    - Configurable modes (off/calendar_only/smalltalk/always)
    
    Args:
        user_input: User's message
        finalizer_llm: Quality LLM for finalization (e.g., Gemini)
        config: Finalizer configuration (defaults applied if None)
        planner_decision: Orchestrator decision (route, intent, slots, etc.)
        tool_results: Tool execution results
        dialog_summary: Conversation history summary
        draft_text: Draft response (required for BrainLoop, optional for OrchestratorLoop)
        fallback_llm: Fast LLM for fallback (e.g., 3B router)
        route: Route classification (for BrainLoop compatibility)
        last_tool: Last executed tool (for BrainLoop compatibility)
        
    Returns:
        FinalizerResult with final text and metadata
    """
    cfg = config or FinalizerConfig()
    
    # Check if finalization is disabled
    if cfg.mode == "off" or finalizer_llm is None:
        return FinalizerResult(
            text=draft_text or "",
            used_finalizer=False,
            tier_name="draft",
            tier_reason="finalizer_disabled" if cfg.mode == "off" else "no_finalizer_llm",
        )
    
    # Check if finalization should be skipped based on mode
    should_finalize = False
    tier_reason = ""
    
    if cfg.mode == "always":
        should_finalize = True
        tier_reason = "mode_always"
    elif cfg.mode == "smalltalk":
        route_norm = (route or "").lower().strip()
        is_smalltalk = route_norm in {"smalltalk", "smalltalk_stage1"}
        should_finalize = is_smalltalk
        tier_reason = "smalltalk_route" if is_smalltalk else "not_smalltalk"
    else:  # calendar_only
        is_calendar = bool(last_tool and last_tool.startswith("calendar."))
        should_finalize = is_calendar
        tier_reason = "calendar_tool" if is_calendar else "not_calendar"
    
    if not should_finalize:
        return FinalizerResult(
            text=draft_text or "",
            used_finalizer=False,
            tier_name="draft",
            tier_reason=tier_reason,
        )
    
    # Prepare tool results with token budget
    finalizer_tool_results = tool_results
    was_truncated = False
    
    if tool_results:
        finalizer_tool_results, was_truncated = _prepare_tool_results_for_finalizer(
            tool_results,
            max_tokens=cfg.tool_results_token_budget,
        )
        if was_truncated:
            logger.info("[FINALIZER] Tool results truncated to fit token budget")
    
    # Build finalizer prompt
    prompt = _build_finalizer_prompt(
        user_input=user_input,
        planner_decision=planner_decision,
        tool_results=finalizer_tool_results,
        dialog_summary=dialog_summary,
        draft_text=draft_text,
        route=route,
        last_tool=last_tool,
    )
    
    # Call finalizer LLM
    try:
        try:
            final_text = finalizer_llm.complete_text(
                prompt=prompt,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
        except TypeError:
            # Backward compatibility for mocks that only accept prompt
            final_text = finalizer_llm.complete_text(prompt=prompt)
        
        final_text = str(final_text or "").strip()
        
        if not final_text:
            # Empty response - fallback
            if fallback_llm and draft_text:
                try:
                    fallback_text = fallback_llm.complete_text(prompt=prompt, temperature=0.2, max_tokens=256)
                    fallback_text = str(fallback_text or "").strip()
                    if fallback_text:
                        return FinalizerResult(
                            text=fallback_text,
                            used_finalizer=True,
                            was_truncated=was_truncated,
                            tier_name="fast",
                            tier_reason="quality_empty_fallback_fast",
                        )
                except Exception:
                    pass
            
            return FinalizerResult(
                text=draft_text or "",
                used_finalizer=False,
                was_truncated=was_truncated,
                tier_name="draft",
                tier_reason="quality_empty_fallback_draft",
            )
        
        # Apply no-new-facts guard if enabled
        guard_violated = False
        guard_retried = False
        
        if cfg.enable_no_new_facts_guard:
            try:
                from bantz.llm.no_new_facts import find_new_numeric_facts
                
                allowed_sources = [user_input]
                if dialog_summary:
                    allowed_sources.append(dialog_summary)
                if draft_text:
                    allowed_sources.append(draft_text)
                if planner_decision:
                    allowed_sources.append(json.dumps(planner_decision, ensure_ascii=False))
                if tool_results:
                    allowed_sources.append(json.dumps(tool_results, ensure_ascii=False))
                
                violates, new_tokens = find_new_numeric_facts(
                    allowed_texts=allowed_sources,
                    candidate_text=final_text,
                )
                
                if violates:
                    guard_violated = True
                    
                    if cfg.retry_on_guard_violation:
                        guard_retried = True
                        # Retry with stricter constraint
                        retry_prompt = (
                            prompt
                            + "\n\nSTRICT_NO_NEW_FACTS: Sadece verilen metinlerde geçen sayı/saat/tarihleri kullan. "
                            "Yeni rakam ekleme. Gerekirse rakam içeren detayları çıkar.\n"
                        )
                        
                        try:
                            final_text2 = finalizer_llm.complete_text(
                                prompt=retry_prompt,
                                temperature=cfg.temperature * 0.5,  # Lower temperature for retry
                                max_tokens=cfg.max_tokens,
                            )
                        except TypeError:
                            final_text2 = finalizer_llm.complete_text(prompt=retry_prompt)
                        
                        final_text2 = str(final_text2 or "").strip()
                        
                        if final_text2:
                            violates2, _new2 = find_new_numeric_facts(
                                allowed_texts=allowed_sources,
                                candidate_text=final_text2,
                            )
                            if not violates2:
                                final_text = final_text2
                                guard_violated = False  # Successfully recovered
                            else:
                                # Retry still violated - fallback
                                if draft_text:
                                    return FinalizerResult(
                                        text=draft_text,
                                        used_finalizer=False,
                                        was_truncated=was_truncated,
                                        guard_violated=True,
                                        guard_retried=True,
                                        tier_name="draft",
                                        tier_reason="guard_retry_failed_fallback_draft",
                                    )
                        else:
                            # Empty retry - fallback
                            if draft_text:
                                return FinalizerResult(
                                    text=draft_text,
                                    used_finalizer=False,
                                    was_truncated=was_truncated,
                                    guard_violated=True,
                                    guard_retried=True,
                                    tier_name="draft",
                                    tier_reason="guard_retry_empty_fallback_draft",
                                )
            except Exception as e:
                # Guard is best-effort; log but don't block
                logger.warning(f"[FINALIZER] No-new-facts guard failed: {e}")
        
        return FinalizerResult(
            text=final_text,
            used_finalizer=True,
            was_truncated=was_truncated,
            guard_violated=guard_violated,
            guard_retried=guard_retried,
            tier_name="quality",
            tier_reason="success",
        )
        
    except Exception as e:
        # Finalizer LLM failed - try fallback
        logger.warning(f"[FINALIZER] Quality LLM failed: {e}")
        
        if fallback_llm:
            try:
                fallback_text = fallback_llm.complete_text(prompt=prompt, temperature=0.2, max_tokens=256)
                fallback_text = str(fallback_text or "").strip()
                if fallback_text:
                    return FinalizerResult(
                        text=fallback_text,
                        used_finalizer=True,
                        was_truncated=was_truncated,
                        tier_name="fast",
                        tier_reason="quality_failed_fallback_fast",
                    )
            except Exception:
                pass
        
        # Final fallback to draft
        return FinalizerResult(
            text=draft_text or "",
            used_finalizer=False,
            was_truncated=was_truncated,
            tier_name="draft",
            tier_reason="quality_failed_fallback_draft",
        )
