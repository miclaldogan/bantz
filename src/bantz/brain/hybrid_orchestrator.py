"""Unified Hybrid Orchestrator — 3B Router + Quality Finalizer (Issue #412).

Consolidates GeminiHybridOrchestrator and FlexibleHybridOrchestrator into
a single ``HybridOrchestrator`` class.

Features (best of both):
  - From GeminiHybridOrchestrator: no-new-facts guard, smart tool result
    summarisation (2KB cap), two-phase plan()+finalize() API
  - From FlexibleHybridOrchestrator: env-based config, finalizer availability
    check, 3B fallback, finalizer type selection (Gemini / vLLM 7B)

Usage:
    >>> orchestrator = HybridOrchestrator(
    ...     router=router_client,
    ...     finalizer=gemini_client,
    ...     config=HybridConfig(finalizer_type="gemini"),
    ... )
    >>> plan_output = orchestrator.plan("bugün toplantılarım neler?")
    >>> # ... execute tools ...
    >>> final_output = orchestrator.finalize(plan_output, tool_results=[...])
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol

from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.llm.base import LLMClient, LLMMessage

logger = logging.getLogger(__name__)

__all__ = [
    "HybridOrchestrator",
    "HybridConfig",
    "create_hybrid_orchestrator",
]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class FinalizerProtocol(Protocol):
    """Protocol for any finalizer LLM (Gemini, vLLM 7B, etc.)."""

    def chat_detailed(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> Any: ...

    def is_available(self, *, timeout_seconds: float = 1.5) -> bool: ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HybridConfig:
    """Configuration for unified HybridOrchestrator.

    Attributes:
        finalizer_type: ``"gemini"`` or ``"vllm_7b"``
        finalizer_model: Model name (e.g. ``gemini-1.5-flash``)
        finalizer_temperature: Sampling temperature for finalizer
        finalizer_max_tokens: Max output tokens for finalizer
        router_temperature: Temperature for 3B router (0.0 = deterministic)
        router_max_tokens: Max output tokens for router
        fallback_to_3b: Use 3B router reply when finalizer fails
        confidence_threshold: Minimum confidence to execute tools
        no_new_facts_guard: Enable hallucination guard retry (Issue #357)
        tool_results_max_chars: Max chars for tool result context
    """

    finalizer_type: Literal["gemini", "vllm_7b"] = "gemini"
    finalizer_model: str = "gemini-1.5-flash"
    finalizer_temperature: float = 0.4
    finalizer_max_tokens: int = 512

    router_temperature: float = 0.0
    router_max_tokens: int = 512

    fallback_to_3b: bool = True
    confidence_threshold: float = 0.7
    no_new_facts_guard: bool = True
    tool_results_max_chars: int = 2000

    @classmethod
    def from_env(cls) -> "HybridConfig":
        """Create config from environment variables.

        Env vars:
          BANTZ_FINALIZER_TYPE: ``gemini`` | ``vllm_7b`` (default: gemini)
          BANTZ_FINALIZER_MODEL: override model name
          BANTZ_NO_NEW_FACTS_GUARD: ``0`` to disable
        """
        ft = os.getenv("BANTZ_FINALIZER_TYPE", "gemini").strip().lower()
        if ft not in {"gemini", "vllm_7b"}:
            logger.warning("[HYBRID] Invalid BANTZ_FINALIZER_TYPE=%s, defaulting to gemini", ft)
            ft = "gemini"

        model = os.getenv("BANTZ_FINALIZER_MODEL", "").strip()
        if not model:
            model = "gemini-1.5-flash" if ft == "gemini" else "Qwen/Qwen2.5-7B-Instruct"

        guard_str = os.getenv("BANTZ_NO_NEW_FACTS_GUARD", "1").strip().lower()
        guard = guard_str not in {"0", "false", "no", "off"}

        return cls(
            finalizer_type=ft,  # type: ignore[arg-type]
            finalizer_model=model,
            no_new_facts_guard=guard,
        )


# ---------------------------------------------------------------------------
# Tool result summarisation (from GeminiHybridOrchestrator)
# ---------------------------------------------------------------------------

def summarize_tool_results(
    tool_results: list[dict[str, Any]],
    max_chars: int = 2000,
) -> tuple[str, bool]:
    """Summarize tool results for finalizer context, preventing overflow.

    Smart truncation strategy:
      - Lists: first 5 items + metadata
      - Dicts with ``events``: calendar-aware preview (5 events)
      - Large strings/dicts: 500-char preview
      - Fallback: keep only first 3 tools if still too large

    Returns:
        ``(summary_string, was_truncated)``
    """
    if not tool_results:
        return "", False

    def _truncate(result: Any, max_size: int = 500) -> tuple[Any, bool]:
        if isinstance(result, list):
            if len(result) > 5:
                return {
                    "_preview": result[:5],
                    "_truncated": True,
                    "_total_count": len(result),
                    "_message": f"Showing first 5 of {len(result)} items",
                }, True
            return result, False
        if isinstance(result, dict):
            if "events" in result and isinstance(result["events"], list):
                events = result["events"]
                if len(events) > 5:
                    return {
                        "events": events[:5],
                        "_preview": True,
                        "_total_events": len(events),
                        "_message": f"Showing first 5 of {len(events)} events",
                        **{k: v for k, v in result.items() if k != "events"},
                    }, True
                return result, False
            s = json.dumps(result, ensure_ascii=False)
            if len(s) > max_size:
                return f"{s[:max_size]}… (truncated from {len(s)} chars)", True
            return result, False
        if isinstance(result, str) and len(result) > max_size:
            return f"{result[:max_size]}… (truncated from {len(result)} chars)", True
        return result, False

    summarized: list[dict] = []
    truncated_any = False
    for tr in tool_results:
        row = dict(tr)
        if "result" in row:
            row["result"], t = _truncate(row["result"])
            truncated_any = truncated_any or t
        summarized.append(row)

    try:
        out = json.dumps(summarized, ensure_ascii=False)
    except (TypeError, ValueError):
        out = str(summarized)
        truncated_any = True

    if len(out) > max_chars:
        truncated_any = True
        agg: list[dict] = []
        for tr in tool_results[:3]:
            a: dict = {"tool_name": tr.get("tool_name", "?"), "status": tr.get("status", "?")}
            if "result" in tr:
                a["result"], _ = _truncate(tr["result"], 200)
            agg.append(a)
        try:
            out = json.dumps(agg, ensure_ascii=False)
        except (TypeError, ValueError):
            out = str(agg)
        if len(out) > max_chars:
            out = out[:max_chars] + "… (truncated)"

    return out, truncated_any


# ---------------------------------------------------------------------------
# No-new-facts guard (from GeminiHybridOrchestrator)
# ---------------------------------------------------------------------------

_NO_NEW_FACTS_SYSTEM = (
    "Sadece verilen TOOL RESULTS bilgisine dayanarak cevap ver. "
    "Eğer tool sonuçlarında olmayan yeni bilgiler üretirsen cevabın reddedilecek. "
    "Bilinmeyen detayları uydurmak yerine 'bilmiyorum' de."
)


def _check_no_new_facts(response: str, tool_summary: str) -> bool:
    """Heuristic: does the response appear to fabricate facts?

    Very simple check — look for date/time patterns in the response that
    don't appear in the tool summary.
    """
    import re

    date_pattern = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}")
    time_pattern = re.compile(r"\d{1,2}:\d{2}")

    resp_dates = set(date_pattern.findall(response))
    resp_times = set(time_pattern.findall(response))
    tool_dates = set(date_pattern.findall(tool_summary))
    tool_times = set(time_pattern.findall(tool_summary))

    new_dates = resp_dates - tool_dates
    new_times = resp_times - tool_times

    if new_dates or new_times:
        logger.warning(
            "[HYBRID] No-new-facts violation: new_dates=%s new_times=%s",
            new_dates,
            new_times,
        )
        return False  # violated
    return True  # ok


# ---------------------------------------------------------------------------
# HybridOrchestrator
# ---------------------------------------------------------------------------

class HybridOrchestrator:
    """Unified hybrid orchestrator: 3B Router + Quality Finalizer.

    Merges the capabilities of ``GeminiHybridOrchestrator`` and
    ``FlexibleHybridOrchestrator`` into a single, well-tested class.

    Two-phase API (recommended):
      1. ``plan(user_input)`` → ``OrchestratorOutput`` (from 3B router)
      2. Execute tools externally
      3. ``finalize(plan_output, tool_results=...)`` → ``OrchestratorOutput``

    Single-call API:
      - ``orchestrate(user_input=..., tool_results=...)``
    """

    def __init__(
        self,
        *,
        router: LLMClient,
        finalizer: Optional[FinalizerProtocol] = None,
        config: Optional[HybridConfig] = None,
    ):
        self._router_orchestrator = JarvisLLMOrchestrator(llm_client=router)
        self._finalizer = finalizer
        self._config = config or HybridConfig.from_env()
        self._finalizer_available = self._check_finalizer()

        logger.info(
            "[HYBRID] finalizer=%s model=%s available=%s fallback=%s guard=%s",
            self._config.finalizer_type,
            self._config.finalizer_model,
            self._finalizer_available,
            self._config.fallback_to_3b,
            self._config.no_new_facts_guard,
        )

    # ---- availability -------------------------------------------------

    def _check_finalizer(self) -> bool:
        if self._finalizer is None:
            return False
        try:
            return self._finalizer.is_available(timeout_seconds=1.5)
        except Exception:
            return False

    @property
    def finalizer_available(self) -> bool:
        return self._finalizer_available

    # ---- two-phase API ------------------------------------------------

    def plan(
        self,
        user_input: str,
        *,
        dialog_summary: str = "",
    ) -> OrchestratorOutput:
        """Phase 1: Route and extract intent/slots via 3B router."""
        logger.info("[HYBRID] Phase-1 plan: '%s'", user_input[:60])
        return self._router_orchestrator.route(
            user_input=user_input,
            dialog_summary=dialog_summary,
        )

    def finalize(
        self,
        plan_output: OrchestratorOutput,
        *,
        user_input: str = "",
        dialog_summary: str = "",
        tool_results: Optional[list[dict[str, Any]]] = None,
    ) -> OrchestratorOutput:
        """Phase 3: Generate natural-language response via finalizer.

        If the finalizer is unavailable or fails, falls back to the 3B
        router's ``assistant_reply`` (if ``fallback_to_3b`` is enabled).
        """
        final_text = self._do_finalize(
            plan_output=plan_output,
            user_input=user_input or plan_output.raw_output.get("user_input", ""),
            dialog_summary=dialog_summary,
            tool_results=tool_results,
        )

        return OrchestratorOutput(
            route=plan_output.route,
            calendar_intent=plan_output.calendar_intent,
            slots=plan_output.slots,
            confidence=plan_output.confidence,
            tool_plan=plan_output.tool_plan,
            assistant_reply=final_text,
            ask_user=plan_output.ask_user,
            question=plan_output.question,
            requires_confirmation=plan_output.requires_confirmation,
            confirmation_prompt=plan_output.confirmation_prompt,
            memory_update=plan_output.memory_update,
            reasoning_summary=plan_output.reasoning_summary,
            raw_output={
                "router": plan_output.raw_output,
                "finalizer_type": self._active_finalizer_type,
            },
        )

    # ---- single-call API (convenience) --------------------------------

    def orchestrate(
        self,
        *,
        user_input: str,
        dialog_summary: str = "",
        tool_results: Optional[list[dict[str, Any]]] = None,
    ) -> OrchestratorOutput:
        """Plan + finalize in one call."""
        plan_out = self.plan(user_input, dialog_summary=dialog_summary)
        return self.finalize(
            plan_out,
            user_input=user_input,
            dialog_summary=dialog_summary,
            tool_results=tool_results,
        )

    # ---- internals ----------------------------------------------------

    def _do_finalize(
        self,
        *,
        plan_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str,
        tool_results: Optional[list[dict[str, Any]]],
    ) -> str:
        if not self._finalizer_available:
            logger.warning("[HYBRID] Finalizer unavailable — 3B fallback")
            return self._fallback(plan_output)

        try:
            return self._call_finalizer(
                plan_output=plan_output,
                user_input=user_input,
                dialog_summary=dialog_summary,
                tool_results=tool_results,
            )
        except Exception as exc:
            logger.error("[HYBRID] Finalizer error: %s", exc)
            if self._config.fallback_to_3b:
                logger.warning("[HYBRID] Falling back to 3B router response")
                return self._fallback(plan_output)
            raise

    def _call_finalizer(
        self,
        *,
        plan_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str,
        tool_results: Optional[list[dict[str, Any]]],
    ) -> str:
        # Build tool summary
        tool_summary = ""
        was_truncated = False
        if tool_results:
            tool_summary, was_truncated = summarize_tool_results(
                tool_results, max_chars=self._config.tool_results_max_chars
            )

        # Build messages
        system_prompt = self._build_system_prompt(
            has_tool_results=bool(tool_results),
            no_new_facts=self._config.no_new_facts_guard and bool(tool_results),
        )
        user_prompt = self._build_user_prompt(
            plan_output=plan_output,
            user_input=user_input,
            dialog_summary=dialog_summary,
            tool_summary=tool_summary,
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = self._finalizer.chat_detailed(
            messages=messages,
            temperature=self._config.finalizer_temperature,
            max_tokens=self._config.finalizer_max_tokens,
        )
        text = (response.content or "").strip()

        # No-new-facts guard
        if self._config.no_new_facts_guard and tool_summary and text:
            if not _check_no_new_facts(text, tool_summary):
                logger.warning("[HYBRID] No-new-facts guard triggered — retrying with strict prompt")
                strict_msgs = [
                    LLMMessage(role="system", content=_NO_NEW_FACTS_SYSTEM),
                    LLMMessage(role="user", content=user_prompt),
                ]
                retry_resp = self._finalizer.chat_detailed(
                    messages=strict_msgs,
                    temperature=max(0.1, self._config.finalizer_temperature - 0.2),
                    max_tokens=self._config.finalizer_max_tokens,
                )
                text = (retry_resp.content or "").strip()

        return text

    @property
    def _active_finalizer_type(self) -> str:
        if not self._finalizer_available:
            return "3b_fallback"
        return self._config.finalizer_type

    @staticmethod
    def _fallback(plan_output: OrchestratorOutput) -> str:
        return plan_output.assistant_reply or "Üzgünüm efendim, bir sorun oluştu."

    @staticmethod
    def _build_system_prompt(*, has_tool_results: bool, no_new_facts: bool) -> str:
        base = (
            "Sen BANTZ'sın — Jarvis tarzı Türkçe asistan.\n\n"
            "Kurallar:\n"
            "- \"Efendim\" hitabı kullan\n"
            "- Nazik, profesyonel ama samimi\n"
            "- Kısa ve öz cevaplar (1-2 cümle ideal)\n"
            "- Türkçe doğal konuş\n"
        )
        if has_tool_results:
            base += "\nTakvim/araç sonuçlarını kullanıcıya kısa ve öz aktar.\n"
        if no_new_facts:
            base += (
                "\nÖNEMLİ: Sadece TOOL RESULTS bilgisine dayanarak cevap ver. "
                "Yeni bilgi UYDURMAK YASAK.\n"
            )
        return base

    @staticmethod
    def _build_user_prompt(
        *,
        plan_output: OrchestratorOutput,
        user_input: str,
        dialog_summary: str,
        tool_summary: str,
    ) -> str:
        parts: list[str] = []
        if dialog_summary:
            parts.append(f"Dialog Context:\n{dialog_summary}")
        parts.append(f"User: {user_input}")
        if plan_output.route == "calendar":
            parts.append(f"Intent: {plan_output.calendar_intent}")
            if plan_output.slots:
                parts.append(f"Slots: {json.dumps(plan_output.slots, ensure_ascii=False)}")
        if tool_summary:
            parts.append(f"Tool Results:\n{tool_summary}")
        parts.append("Yanıtını Türkçe ver:")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_hybrid_orchestrator(
    *,
    router: LLMClient,
    finalizer: Optional[LLMClient] = None,
    config: Optional[HybridConfig] = None,
) -> HybridOrchestrator:
    """Create a unified HybridOrchestrator.

    Args:
        router: 3B router LLM client.
        finalizer: Finalizer LLM client (Gemini or 7B vLLM).
        config: Optional configuration (falls back to env vars).
    """
    return HybridOrchestrator(
        router=router,
        finalizer=finalizer,
        config=config or HybridConfig.from_env(),
    )
