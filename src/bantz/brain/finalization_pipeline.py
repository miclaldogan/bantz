"""Finalization Pipeline for OrchestratorLoop (Issue #404).

Extracted from the monolithic ``_llm_finalization_phase()`` method (~300 lines)
into clean, independently testable Strategy classes:

- ``FinalizationContext`` — immutable input bag for every strategy
- ``NoNewFactsGuard`` — validates output against source data
- ``QualityFinalizer`` — cloud / Gemini response generation
- ``FastFinalizer`` — local 3B planner-based fast response
- ``FinalizationPipeline`` — orchestrates the full finalization flow

Each strategy produces ``Optional[str]`` (the final ``assistant_reply``)
or ``None`` when the next strategy should be tried.

Factory helpers:
    ``build_finalization_context()`` — builds the context from loop internals
    ``create_pipeline()`` — creates a pipeline from LLM instances
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, replace
from typing import Any, Optional, Protocol

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class LLMCompletionProtocol(Protocol):
    """Minimal protocol for an LLM that can complete text."""

    def complete_text(
        self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 256
    ) -> str: ...


# ---------------------------------------------------------------------------
# Context: immutable data bag for all strategies
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinalizationContext:
    """All data needed by finalization strategies.

    Replaces the long parameter lists that were threaded through the
    monolithic ``_llm_finalization_phase`` method.
    """

    user_input: str
    orchestrator_output: OrchestratorOutput
    tool_results: list[dict[str, Any]]
    state: OrchestratorState

    # Pre-computed helper fields (set by the factory)
    planner_decision: dict[str, Any]
    dialog_summary: Optional[str] = None
    recent_turns: Optional[list[dict[str, str]]] = None
    session_context: Optional[dict[str, Any]] = None

    # Tier decision
    tier_name: str = "quality"
    tier_reason: str = ""
    use_quality: bool = True


# ---------------------------------------------------------------------------
# No-New-Facts Guard
# ---------------------------------------------------------------------------

class NoNewFactsGuard:
    """Validates that a finalizer output contains no hallucinated numeric facts.

    If the candidate text introduces numbers / dates / times that do not
    appear in the allowed source texts, it is considered a violation.

    On violation a stricter retry is attempted.  If the retry also violates,
    the guard returns ``None`` to signal fallback.
    """

    def __init__(self, *, finalizer_llm: LLMCompletionProtocol):
        self._llm = finalizer_llm

    def check_and_retry(
        self,
        *,
        candidate_text: str,
        allowed_sources: list[str],
        original_prompt: str,
        state: OrchestratorState,
    ) -> Optional[str]:
        """Return the validated text, a retried text, or ``None`` on failure."""
        try:
            from bantz.llm.no_new_facts import find_new_numeric_facts
        except ImportError:
            return candidate_text

        try:
            violates, new_tokens = find_new_numeric_facts(
                allowed_texts=allowed_sources,
                candidate_text=candidate_text,
            )
        except Exception:
            return candidate_text  # best-effort

        if not violates:
            return candidate_text

        # --- Violation detected: retry with stricter prompt -----------------
        state.update_trace(
            finalizer_attempted=True,
            finalizer_guard="no_new_facts",
            finalizer_guard_violation=True,
            finalizer_guard_new_tokens_count=len(new_tokens),
        )

        retry_prompt = (
            original_prompt
            + "\n\nSTRICT_NO_NEW_FACTS: Sadece verilen metinlerde geçen "
            "sayı/saat/tarihleri kullan. "
            "Yeni rakam ekleme. Gerekirse rakam içeren detayları çıkar.\n"
        )

        retry_text = _safe_complete(self._llm, retry_prompt)
        if not retry_text:
            return None

        try:
            violates2, _ = find_new_numeric_facts(
                allowed_texts=allowed_sources,
                candidate_text=retry_text,
            )
        except Exception:
            return retry_text

        return retry_text if not violates2 else None


# ---------------------------------------------------------------------------
# Quality Finalizer (cloud / Gemini)
# ---------------------------------------------------------------------------

class QualityFinalizer:
    """Generate a user-facing reply via the quality (cloud) finalizer LLM."""

    def __init__(
        self,
        *,
        finalizer_llm: LLMCompletionProtocol,
        guard: Optional[NoNewFactsGuard] = None,
    ):
        self._llm = finalizer_llm
        self._guard = guard

    def finalize(self, ctx: FinalizationContext) -> Optional[str]:
        """Build a prompt, call the quality LLM, apply guard, return text or ``None``."""
        finalizer_prompt = self._build_prompt(ctx)
        text = _safe_complete(self._llm, finalizer_prompt)

        if not text:
            return None

        if self._guard is not None:
            allowed_sources = [
                ctx.user_input,
                ctx.dialog_summary or "",
                json.dumps(ctx.planner_decision, ensure_ascii=False),
                json.dumps(ctx.tool_results or [], ensure_ascii=False),
            ]
            text = self._guard.check_and_retry(
                candidate_text=text,
                allowed_sources=allowed_sources,
                original_prompt=finalizer_prompt,
                state=ctx.state,
            )

        return text or None

    # -- prompt building -----------------------------------------------------

    def _build_prompt(self, ctx: FinalizationContext) -> str:
        """Try ``PromptBuilder`` first, fall back to inline template."""
        from bantz.brain.orchestrator_loop import _prepare_tool_results_for_finalizer

        finalizer_results, was_truncated = _prepare_tool_results_for_finalizer(
            ctx.tool_results or [],
            max_tokens=2000,
        )
        if was_truncated:
            logger.info("[QUALITY_FINALIZER] Tool results truncated to fit token budget")

        try:
            return self._build_prompt_via_builder(ctx, finalizer_results)
        except Exception:
            return self._build_fallback_prompt(ctx, finalizer_results)

    def _build_prompt_via_builder(
        self,
        ctx: FinalizationContext,
        finalizer_results: list[dict[str, Any]],
    ) -> str:
        from bantz.brain.prompt_engineering import PromptBuilder

        seed = (
            str(ctx.session_context.get("session_id") or "default")
            if ctx.session_context
            else "default"
        )

        builder = PromptBuilder(
            token_budget=3500,
            experiment="issue191_orchestrator_finalizer",
        )
        built = builder.build_finalizer_prompt(
            route=ctx.orchestrator_output.route,
            user_input=ctx.user_input,
            planner_decision=ctx.planner_decision,
            tool_results=finalizer_results or None,
            dialog_summary=ctx.dialog_summary or None,
            recent_turns=ctx.recent_turns,
            session_context=ctx.session_context,
            seed=seed,
        )
        return built.prompt

    @staticmethod
    def _build_fallback_prompt(
        ctx: FinalizationContext,
        finalizer_results: list[dict[str, Any]],
    ) -> str:
        if finalizer_results:
            logger.warning("[FINALIZER_FALLBACK] Tool results truncated to fit budget")
        return "\n".join(
            [
                "Kimlik / Roller:",
                "- Sen BANTZ'sın. Kullanıcı USER'dır.",
                "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
                "- 'Efendim' hitabını kullan.",
                "",
                "FORMAT KURALLARI (KESİN):",
                "- Sadece kullanıcıya söyleyeceğin düz metni üret.",
                '- JSON üretme. Örnek: {"route": ...} YASAK.',
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
                (
                    f"DIALOG_SUMMARY:\n{ctx.dialog_summary}\n"
                    if ctx.dialog_summary
                    else ""
                ),
                "PLANNER_DECISION (JSON):",
                json.dumps(ctx.planner_decision, ensure_ascii=False),
                (
                    "\nTOOL_RESULTS (JSON):\n"
                    + json.dumps(finalizer_results, ensure_ascii=False)
                )
                if finalizer_results
                else "",
                (
                    f"\nUSER: {ctx.user_input}\n"
                    "ASSISTANT (SADECE TÜRKÇE, düz metin, yeni bilgi ekleme):"
                ),
            ]
        ).strip()


# ---------------------------------------------------------------------------
# Fast Finalizer (local 3B planner)
# ---------------------------------------------------------------------------

class FastFinalizer:
    """Generate a user-facing reply using the local planner (3B) model."""

    def __init__(self, *, planner_llm: LLMCompletionProtocol):
        self._llm = planner_llm

    def finalize(self, ctx: FinalizationContext) -> Optional[str]:
        """Build a fast prompt, call the planner LLM, return text or ``None``."""
        try:
            prompt = self._build_prompt(ctx)
            return _safe_complete(self._llm, prompt)
        except Exception:
            return None

    def _build_prompt(self, ctx: FinalizationContext) -> str:
        from bantz.brain.orchestrator_loop import _prepare_tool_results_for_finalizer

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
            json.dumps(ctx.planner_decision, ensure_ascii=False),
        ]

        if ctx.tool_results:
            finalizer_results, was_truncated = _prepare_tool_results_for_finalizer(
                ctx.tool_results,
                max_tokens=1500,
            )
            if was_truncated:
                logger.info("[FAST_FINALIZER] Tool results truncated to fit budget")
            prompt_lines.extend([
                "",
                "TOOL_RESULTS (JSON):",
                json.dumps(finalizer_results, ensure_ascii=False),
            ])

        prompt_lines.extend([
            "",
            f"USER: {ctx.user_input}",
            "ASSISTANT (SADECE TÜRKÇE, düz metin, yeni bilgi ekleme):",
        ])
        return "\n".join(prompt_lines)


# ---------------------------------------------------------------------------
# Tier Decision Helper
# ---------------------------------------------------------------------------

def is_simple_greeting(user_input: str) -> bool:
    """Check if user input is a simple greeting that doesn't need Gemini.

    Issue #409: Simple greetings (merhaba/selam/nasılsın) can use the 3B
    router's reply directly — no need for a 300ms Gemini call.

    Returns:
        True if the input is a simple greeting pattern.
    """
    normalised = user_input.strip().lower().rstrip("!.?")
    _SIMPLE_PATTERNS = {
        "merhaba", "selam", "hey", "hi", "hello",
        "günaydın", "iyi akşamlar", "iyi geceler",
        "nasılsın", "naber", "ne haber", "nasilsin",
        "hoşça kal", "görüşürüz", "bye", "hoşçakal",
        "teşekkürler", "teşekkür ederim", "sağ ol", "eyvallah",
        "iyi günler", "kolay gelsin",
    }
    if normalised in _SIMPLE_PATTERNS:
        return True
    # Also match very short inputs (≤3 words) that start with a greeting word
    words = normalised.split()
    if len(words) <= 3 and words and words[0] in {
        "merhaba", "selam", "hey", "hi", "hello", "günaydın", "naber",
        "teşekkürler", "hoşça", "hoşçakal",
    }:
        return True
    return False


def decide_finalization_tier(
    *,
    orchestrator_output: OrchestratorOutput,
    user_input: str,
    has_finalizer: bool,
) -> tuple[bool, str, str]:
    """Decide whether to use quality (cloud) or fast (local) finalizer.

    Env overrides:
        BANTZ_TIER_FORCE_FINALIZER=quality  → always use Gemini
        BANTZ_TIER_FORCE_FINALIZER=fast     → always skip Gemini
        (legacy: BANTZ_FORCE_FINALIZER_TIER)

    Returns:
        ``(use_quality, tier_name, tier_reason)``
    """
    if not has_finalizer:
        return False, "fast", "no_finalizer"

    # Issue #517: env override for forcing finalizer tier
    forced = (
        os.getenv("BANTZ_TIER_FORCE_FINALIZER", "")
        or os.getenv("BANTZ_FORCE_FINALIZER_TIER", "")
    ).strip().lower()
    if forced in ("quality", "gemini"):
        logger.info("[TIER] forced=quality via tier env override")
        return True, "quality", "forced_quality"
    if forced in ("fast", "3b", "skip"):
        logger.info("[TIER] forced=fast via tier env override")
        return False, "fast", "forced_fast"

    # Issue #409: Split smalltalk into simple vs complex
    if orchestrator_output.route == "smalltalk":
        if is_simple_greeting(user_input):
            # Simple greeting → 3B reply is good enough, skip Gemini (~300ms saved)
            logger.info(
                "[TIER] gemini_calls_saved=1 reason=simple_greeting input=%r",
                user_input[:60],
            )
            return False, "fast", "simple_greeting_skip_gemini"
        # Complex smalltalk → still use Gemini
        return True, "quality", "complex_smalltalk_needs_quality"

    # Try tiered decision
    try:
        from bantz.llm.tiered import decide_tier

        decision = decide_tier(
            user_input,
            tool_names=orchestrator_output.tool_plan,
            requires_confirmation=bool(orchestrator_output.requires_confirmation),
            route=orchestrator_output.route,
        )

        if decision.reason == "tiering_disabled":
            return False, "fast", "tiering_disabled_default_fast"

        use_q = bool(decision.use_quality)
        tier = "quality" if use_q else "fast"

        if str(os.getenv("BANTZ_TIERED_DEBUG", "")).strip().lower() in {
            "1", "true", "yes", "on",
        }:
            logger.info(
                "[tiered] finalizer tier=%s reason=%s c=%s w=%s r=%s",
                tier,
                decision.reason,
                decision.complexity,
                decision.writing,
                decision.risk,
            )

        return use_q, tier, str(decision.reason)
    except Exception:
        return False, "fast", "tiering_error_default_fast"


# ---------------------------------------------------------------------------
# Finalization Pipeline
# ---------------------------------------------------------------------------

class FinalizationPipeline:
    """Orchestrates the full finalization flow.

    Replaces ``_llm_finalization_phase``'s 300-line monolith with a clean
    pipeline:

    1. Early exits (ask_user, hard failures)
    2. Quality finalizer (with no-new-facts guard) OR fast finalizer
    3. Default fallback (tool-success summary)
    """

    def __init__(
        self,
        *,
        quality: Optional[QualityFinalizer] = None,
        fast: Optional[FastFinalizer] = None,
        event_bus: Any = None,
    ):
        self._quality = quality
        self._fast = fast
        self._event_bus = event_bus

    def run(self, ctx: FinalizationContext) -> OrchestratorOutput:
        """Execute the finalization pipeline and return the updated output."""
        output = ctx.orchestrator_output

        # Emit event
        if self._event_bus is not None:
            self._event_bus.publish("finalizer.start", {
                "has_tool_results": bool(ctx.tool_results),
                "tool_count": len(ctx.tool_results),
            })

        # Issue #517: Determine finalizer model name for trace
        _quality_model = ""
        if self._quality is not None:
            _qlm = getattr(self._quality, "_llm", None)
            _quality_model = str(
                getattr(_qlm, "model_name", None) or getattr(_qlm, "model", None) or ""
            )
        _fast_model = ""
        if self._fast is not None:
            _flm = getattr(self._fast, "_planner", None) or getattr(self._fast, "_llm", None)
            _fast_model = str(
                getattr(_flm, "model_name", None) or getattr(_flm, "model", None) or ""
            )

        # --- Early exit: ask_user with no reply -----------------------------
        if output.ask_user and output.question and not output.assistant_reply:
            return replace(output, assistant_reply=output.question, finalizer_model="none(ask_user)")

        # --- Early exit: hard tool failures ---------------------------------
        error_reply = _check_hard_failures(ctx.tool_results)
        if error_reply is not None:
            return replace(output, assistant_reply=error_reply, finalizer_model="none(error)")

        # --- Early exit: tools succeeded but returned empty data (#628) -----
        # Prevents Gemini from hallucinating calendar events or emails when
        # the underlying API returned an empty result set.
        route = (output.route or "").strip().lower()
        if route in ("calendar", "gmail") and ctx.tool_results and _tool_data_is_empty(ctx.tool_results):
            cal_intent = (output.calendar_intent or "").strip().lower()
            ctx.state.update_trace(
                finalizer_guard="empty_data",
                finalizer_guard_triggered=True,
                finalizer_guard_route=route,
            )
            msg = _empty_data_message(route=route, calendar_intent=cal_intent)
            return replace(output, assistant_reply=msg, finalizer_model="none(empty_data_guard)")

        # --- Quality finalizer path -----------------------------------------
        if ctx.use_quality and self._quality is not None:
            text = self._try_quality(ctx)
            if text:
                return replace(output, assistant_reply=text, finalizer_model=_quality_model or "quality")

            # Quality failed / guard rejected → fall back to fast
            if self._fast is not None:
                text = self._fast.finalize(ctx)
                if text:
                    ctx.state.update_trace(
                        response_tier=ctx.tier_name or "quality",
                        response_tier_reason=ctx.tier_reason or "quality_finalizer",
                        finalizer_attempted=True,
                        finalizer_used=False,
                        finalizer_fallback="planner",
                    )
                    return replace(output, assistant_reply=text, finalizer_model=_fast_model or "fast(fallback)")

        # --- Fast-only path (tiered decision chose "fast") ------------------
        if not ctx.use_quality and self._fast is not None:
            ctx.state.update_trace(
                response_tier=ctx.tier_name or "fast",
                response_tier_reason=ctx.tier_reason or "fast_ok",
                finalizer_used=False,
            )
            should_fast_finalize = (
                (not output.ask_user)
                and (
                    bool(ctx.tool_results)
                    or not (output.assistant_reply or "").strip()
                )
            )
            if should_fast_finalize:
                text = self._fast.finalize(ctx)
                if text:
                    return replace(output, assistant_reply=text, finalizer_model=_fast_model or "fast")

        # --- Default fallback -----------------------------------------------
        return self._default_fallback(ctx)

    # -- internal helpers ----------------------------------------------------

    def _try_quality(self, ctx: FinalizationContext) -> Optional[str]:
        """Run quality finalizer, handle errors, return text or ``None``."""
        try:
            text = self._quality.finalize(ctx)  # type: ignore[union-attr]
            if text:
                ctx.state.update_trace(
                    response_tier=ctx.tier_name or "quality",
                    response_tier_reason=ctx.tier_reason or "quality_finalizer",
                    finalizer_used=True,
                    finalizer_attempted=True,
                )
                return text
            return None
        except Exception as e:
            self._handle_quality_error(e, ctx)
            return None

    def _handle_quality_error(
        self, e: Exception, ctx: FinalizationContext
    ) -> None:
        """Log quality finalizer error and update trace."""
        try:
            from bantz.llm.base import LLMClientError

            if isinstance(e, LLMClientError):
                code = _extract_reason_code(e)
                finalizer_llm = (
                    self._quality._llm if self._quality else None
                )
                ctx.state.update_trace(
                    response_tier=ctx.tier_name or "quality",
                    response_tier_reason=ctx.tier_reason or "quality_finalizer",
                    finalizer_attempted=True,
                    finalizer_used=False,
                    finalizer_error_code=code,
                    finalizer_error_backend=str(
                        getattr(finalizer_llm, "backend_name", "") or ""
                    ),
                )
        except Exception:
            pass

    @staticmethod
    def _default_fallback(ctx: FinalizationContext) -> OrchestratorOutput:
        """No finalizer produced a reply — use deterministic defaults."""
        output = ctx.orchestrator_output

        if not ctx.tool_results:
            guarded = _apply_tool_first_guard_if_needed(ctx)
            if guarded is not None:
                return guarded
            return replace(output, finalizer_model="none(no_tools)")

        # Check for failures
        failed = [r for r in ctx.tool_results if not r.get("success", False)]
        if failed:
            error_msg = "Üzgünüm efendim, bazı işlemler başarısız oldu:\n"
            for r in failed:
                error_msg += (
                    f"- {r.get('tool', '?')}: {r.get('error', 'Unknown error')}\n"
                )
            return replace(output, assistant_reply=error_msg.strip(), finalizer_model="none(error)")

        # Tools succeeded — use existing reply or generate summary
        if output.assistant_reply:
            return replace(output, finalizer_model="none(existing_reply)")

        from bantz.brain.orchestrator_loop import _build_tool_success_summary

        return replace(
            output,
            assistant_reply=_build_tool_success_summary(ctx.tool_results),
            finalizer_model="none(default_summary)",
        )


def _all_tools_failed(tool_results: list[dict[str, Any]]) -> bool:
    """Return True when every tool result is a non-confirmation failure."""
    if not tool_results:
        return False
    return all(
        (not r.get("success", False)) and (not r.get("pending_confirmation"))
        for r in tool_results
    )


def _tool_data_is_empty(tool_results: list[dict[str, Any]]) -> bool:
    """Return True when tools succeeded but returned no useful data.

    Detects the hallucination-prone case where calendar/gmail tools return
    ``{"ok": True, "events": []}`` or ``{"ok": True, "messages": []}`` etc.
    Gemini would fabricate content from these empty results.
    """
    if not tool_results:
        return True
    for r in tool_results:
        if not r.get("success", False):
            continue  # skip failures — handled elsewhere
        raw = r.get("raw_result")
        if not isinstance(raw, dict):
            return False  # non-dict result — assume it has data
        if raw.get("ok") is False:
            continue  # tool-level failure
        # Check known data-carrying keys
        for key in ("events", "messages", "slots", "results", "items", "data"):
            val = raw.get(key)
            if isinstance(val, list) and len(val) > 0:
                return False
            if isinstance(val, dict) and val:
                return False
        # Check count/total fields
        for key in ("total_count", "resultSizeEstimate", "count"):
            val = raw.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return False
    return True


def _empty_data_message(*, route: str, calendar_intent: str = "") -> str:
    """Deterministic message when tools succeed but return empty data."""
    if route == "calendar":
        if calendar_intent in ("query", "list"):
            return "Efendim, takvimde bu zaman aralığında etkinlik bulunamadı."
        if calendar_intent == "free_slots":
            return "Efendim, belirtilen aralıkta boş slot bulunamadı."
        return "Efendim, takvimden veri alınamadı."
    if route == "gmail":
        return "Efendim, gelen kutunuzda bu kriterlere uyan mesaj bulunamadı."
    return "Efendim, istenen bilgi bulunamadı."


def _apply_tool_first_guard_if_needed(ctx: FinalizationContext) -> Optional[OrchestratorOutput]:
    """Prevent tool-dependent hallucinations.

    Fires when:
    1. No tools were run at all (empty tool_results), OR
    2. All tools failed (every result has success=False)

    If the router decided a tool-dependent route+intent (calendar/gmail) but we
    have no usable tool data (and the turn isn't waiting on ask_user/confirmation),
    we replace any speculative assistant reply with a deterministic message.
    """
    output = ctx.orchestrator_output
    # Guard fires when there are NO results OR when ALL results are failures
    has_no_usable_results = (not ctx.tool_results) or _all_tools_failed(ctx.tool_results)
    if not has_no_usable_results:
        return None

    if output.ask_user or output.requires_confirmation:
        return None

    route = (output.route or "").strip().lower()
    calendar_intent = (output.calendar_intent or "").strip().lower()
    gmail_intent = (getattr(output, "gmail_intent", "") or "").strip().lower()

    needs_guard = False
    if route == "calendar":
        needs_guard = calendar_intent in {"query", "create", "modify", "cancel"}
    elif route == "gmail":
        needs_guard = gmail_intent in {"list", "search", "read", "send"}

    if not needs_guard:
        return None

    guard_reason = "all_tools_failed" if ctx.tool_results else "no_tools_run"
    ctx.state.update_trace(
        finalizer_guard="tool_first",
        finalizer_guard_triggered=True,
        finalizer_guard_route=route,
        finalizer_guard_intent=(gmail_intent if route == "gmail" else calendar_intent),
        finalizer_guard_reason=guard_reason,
    )

    msg = _tool_first_guard_message(route=route)
    return replace(output, assistant_reply=msg, finalizer_model=f"none(tool_first_guard/{guard_reason})")


def _tool_first_guard_message(*, route: str) -> str:
    if route == "gmail":
        return (
            "Efendim, bunu yanıtlamak için Gmail’inize bakmam gerekiyor. "
            "Gmail aracını çalıştırmadan e-posta listesi/sonuç uyduramam. "
            "İsterseniz şimdi kontrol edip sonuçları getireyim."
        )
    if route == "calendar":
        return (
            "Efendim, bunu yanıtlamak için takviminize bakmam gerekiyor. "
            "Takvim aracını çalıştırmadan etkinlik/boşluk bilgisi uyduramam. "
            "İsterseniz şimdi kontrol edip net sonucu söyleyeyim."
        )
    return "Efendim, bunu yanıtlamak için ilgili aracı çalıştırmam gerekiyor."


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _safe_complete(
    llm: LLMCompletionProtocol, prompt: str, **kwargs: Any
) -> Optional[str]:
    """Call ``complete_text`` with a TypeError fallback for simple mocks.

    Issue #601: When TypeError is caught (e.g. mock or API signature mismatch),
    we now log a warning so that dropped kwargs (temperature, max_tokens) are
    visible in production logs instead of being silently swallowed.
    """
    try:
        text = llm.complete_text(prompt=prompt, **kwargs)
    except TypeError as e:
        logger.warning(
            "[FINALIZER] LLM client TypeError — kwargs dropped %s: %s",
            list(kwargs.keys()),
            e,
        )
        text = llm.complete_text(prompt=prompt)
    return str(text or "").strip() or None


def _extract_reason_code(err: Exception) -> str:
    """Extract a coarse reason code from an exception message."""
    try:
        m = re.search(r"\breason=([a-z_]+)\b", str(err))
        if m:
            return str(m.group(1))
    except Exception:
        pass
    return "unknown_error"


def _check_hard_failures(
    tool_results: list[dict[str, Any]],
) -> Optional[str]:
    """If any tools hard-failed, return a deterministic error message."""
    if not tool_results:
        return None

    hard_failures = [
        r
        for r in tool_results
        if (not r.get("success", False)) and (not r.get("pending_confirmation"))
    ]
    if not hard_failures:
        return None

    error_msg = "Üzgünüm efendim, bazı işlemler başarısız oldu:\n"
    for result in hard_failures:
        tool_name = str(result.get("tool") or "")
        err = str(result.get("error") or "Unknown error")
        error_msg += f"- {tool_name}: {err}\n"
    return error_msg.strip()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def build_finalization_context(
    *,
    user_input: str,
    orchestrator_output: OrchestratorOutput,
    tool_results: list[dict[str, Any]],
    state: OrchestratorState,
    memory: Any,
    finalizer_llm: Any,
) -> FinalizationContext:
    """Build a ``FinalizationContext`` from ``OrchestratorLoop`` internals.

    This is the only place that touches the loop's private attributes to
    construct the context object — keeping the pipeline itself decoupled.
    """
    context = state.get_context_for_llm()
    dialog_summary = (
        memory.to_prompt_block() if hasattr(memory, "to_prompt_block") else None
    )

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

    # Session context (Issue #359)
    session_context = state.session_context
    if not session_context:
        try:
            from bantz.brain.prompt_engineering import build_session_context

            session_context = build_session_context()
        except Exception:
            session_context = None

    # Tier decision
    use_quality, tier_name, tier_reason = decide_finalization_tier(
        orchestrator_output=orchestrator_output,
        user_input=user_input,
        has_finalizer=finalizer_llm is not None,
    )

    return FinalizationContext(
        user_input=user_input,
        orchestrator_output=orchestrator_output,
        tool_results=tool_results,
        state=state,
        planner_decision=planner_decision,
        dialog_summary=dialog_summary,
        recent_turns=recent_turns,
        session_context=session_context,
        tier_name=tier_name,
        tier_reason=tier_reason,
        use_quality=use_quality,
    )


def create_pipeline(
    *,
    finalizer_llm: Any = None,
    planner_llm: Any = None,
    event_bus: Any = None,
) -> FinalizationPipeline:
    """Create a ``FinalizationPipeline`` from LLM instances."""
    guard = (
        NoNewFactsGuard(finalizer_llm=finalizer_llm) if finalizer_llm else None
    )
    quality = (
        QualityFinalizer(finalizer_llm=finalizer_llm, guard=guard)
        if finalizer_llm
        else None
    )
    fast = FastFinalizer(planner_llm=planner_llm) if planner_llm else None
    return FinalizationPipeline(
        quality=quality, fast=fast, event_bus=event_bus
    )
