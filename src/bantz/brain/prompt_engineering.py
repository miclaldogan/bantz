from __future__ import annotations

import hashlib
import json
import os
import re as _re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional

from bantz.llm.tiered import score_complexity, score_writing_need


PromptVariant = Literal["A", "B"]

# ── Issue #1074: Instruction-like patterns to strip from tool results ────
_INJECTION_PATTERNS = _re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous\s+)?instructions|"
    r"you\s+are\s+now|system\s*:\s*|"
    r"forget\s+(everything|all)|"
    r"disregard\s+(all|previous)|"
    r"override\s+instructions|"
    r"new\s+instructions?\s*:)",
)


def _sanitize_tool_data(text: str) -> str:
    """Wrap tool results in boundary markers and strip injection patterns."""
    cleaned = _INJECTION_PATTERNS.sub("[FILTERED]", text)
    return f"--- DATA START ---\n{cleaned}\n--- DATA END ---"


@dataclass(frozen=True)
class PromptLimits:
    """Configurable char/token limits for prompt assembly and trimming.

    All ``max_*`` values are in **characters** (not tokens).
    ``token_budget`` is an estimated **token** cap.

    Issue #1022: Extracted from formerly hardcoded magic numbers so that
    callers (or config files) can override them.
    """

    # --- assembly limits ---------------------------------------------------
    session_context: int = 1200
    dialog_summary: int = 6000
    planner_decision: int = 4000
    tool_results: int = 12000

    # --- aggressive trim limits (used when over budget) --------------------
    tool_results_trim: int = 700
    dialog_summary_trim: int = 450
    planner_decision_trim: int = 600
    user_input_trim: int = 500

    # --- token budget ------------------------------------------------------
    token_budget: int = 3500


@dataclass(frozen=True)
class PromptBuildResult:
    prompt: str
    variant: PromptVariant
    estimated_tokens: int
    trimmed: bool


def estimate_tokens(text: str) -> int:
    """Token estimation — delegates to unified token_utils (Issue #406)."""
    from bantz.llm.token_utils import estimate_tokens as _estimate
    return _estimate(text)


def _stable_ab_variant(*, seed: str, experiment: str = "default") -> PromptVariant:
    """Deterministic A/B selection.

    Precedence:
    1) `BANTZ_PROMPT_VARIANT` (A/B)
    2) Hash-based on (experiment + seed)
    """

    forced = str(os.getenv("BANTZ_PROMPT_VARIANT", "")).strip().upper()
    if forced in {"A", "B"}:
        return forced  # type: ignore[return-value]

    h = hashlib.sha256(f"{experiment}:{seed}".encode("utf-8")).hexdigest()
    return "A" if (int(h[:8], 16) % 2 == 0) else "B"


def build_session_context(*, location: Optional[str] = None) -> dict[str, Any]:
    """Build lightweight session context for prompt injection."""

    now = datetime.now().astimezone()
    ctx: dict[str, Any] = {
        "current_datetime": now.isoformat(timespec="seconds"),
    }

    loc = (location or os.getenv("BANTZ_LOCATION") or os.getenv("BANTZ_DEFAULT_LOCATION") or "").strip()
    if loc:
        ctx["location"] = loc

    tz = now.tzinfo
    if tz is not None:
        ctx["timezone"] = str(tz)

    session_id = str(os.getenv("BANTZ_SESSION_ID", "")).strip()
    if session_id:
        ctx["session_id"] = session_id

    return ctx


def _truncate(text: str, *, max_chars: int) -> str:
    t = str(text or "")
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max(0, max_chars - 1)] + "…"


def _json_dumps_compact(value: Any, *, max_chars: Optional[int] = None) -> str:
    try:
        s = json.dumps(value, ensure_ascii=False)
    except Exception:
        s = str(value)
    if max_chars is not None:
        s = _truncate(s, max_chars=max_chars)
    return s


class PromptBuilder:
    """Context-aware prompt builder for finalizers (e.g., Gemini).

    This module focuses on the *user-facing response* generation prompt.
    Planning/routing remains in `JarvisLLMOrchestrator`.
    """

    def __init__(
        self,
        *,
        token_budget: int = 0,
        experiment: str = "brain_prompt_v1",
        limits: Optional[PromptLimits] = None,
    ):
        self._limits = limits or PromptLimits()
        # Legacy param: if token_budget was explicitly passed, override limits.
        if token_budget > 0:
            self._limits = PromptLimits(
                session_context=self._limits.session_context,
                dialog_summary=self._limits.dialog_summary,
                planner_decision=self._limits.planner_decision,
                tool_results=self._limits.tool_results,
                tool_results_trim=self._limits.tool_results_trim,
                dialog_summary_trim=self._limits.dialog_summary_trim,
                planner_decision_trim=self._limits.planner_decision_trim,
                user_input_trim=self._limits.user_input_trim,
                token_budget=int(token_budget),
            )
        self._token_budget = self._limits.token_budget
        self._experiment = str(experiment or "brain_prompt_v1")

    def build_finalizer_prompt(
        self,
        *,
        route: str,
        user_input: str,
        planner_decision: dict[str, Any],
        tool_results: Optional[list[dict[str, Any]]] = None,
        dialog_summary: Optional[str] = None,
        recent_turns: Optional[list[dict[str, str]]] = None,
        session_context: Optional[dict[str, Any]] = None,
        seed: str = "default",
        personality_block: Optional[str] = None,
    ) -> PromptBuildResult:
        """Return a single prompt string suitable for `complete_text(prompt=...)`."""

        route_key = str(route or "unknown").strip().lower()
        if route_key not in {"calendar", "gmail", "wiki", "smalltalk", "chat", "unknown"}:
            route_key = "unknown"

        # Dynamic prompt shaping based on the user input.
        complexity = score_complexity(user_input)
        writing = score_writing_need(user_input)

        variant = _stable_ab_variant(seed=seed, experiment=f"{self._experiment}:{route_key}")

        system = self._build_system_prompt(variant=variant, writing=writing, personality_block=personality_block)
        template = self._build_template(route=route_key, variant=variant, complexity=complexity, writing=writing)

        # Optional blocks (ordered by usefulness; trim later if needed).
        blocks: list[tuple[str, str]] = []

        # Issue #1059: Personality is already in the system prompt via
        # _build_system_prompt — do NOT add it again as a content block.

        if session_context:
            blocks.append(("SESSION_CONTEXT", _json_dumps_compact(session_context, max_chars=self._limits.session_context)))

        if dialog_summary:
            # Keep larger by default; trimming will enforce budgets.
            blocks.append(("DIALOG_SUMMARY", _truncate(dialog_summary, max_chars=self._limits.dialog_summary)))

        blocks.append(("PLANNER_DECISION", _json_dumps_compact(planner_decision, max_chars=self._limits.planner_decision)))

        if tool_results:
            # Tool results can be large; allow bigger and rely on trimming.
            raw = _json_dumps_compact(tool_results, max_chars=self._limits.tool_results)
            blocks.append(("TOOL_RESULTS", _sanitize_tool_data(raw)))

        if recent_turns:
            # Keep at most last 2 turns initially.
            turns = recent_turns[-2:]
            lines: list[str] = []
            for t in turns:
                if not isinstance(t, dict):
                    continue
                u = str(t.get("user") or "").strip()
                a = str(t.get("assistant") or "").strip()
                if u:
                    lines.append(f"USER: {u}")
                if a:
                    lines.append(f"ASSISTANT: {a}")
            if lines:
                blocks.append(("RECENT_TURNS", "\n".join(lines)))

        # Build prompt
        prompt = self._assemble(system=system, template=template, blocks=blocks, user_input=user_input)
        trimmed = False

        # Token-budget trimming
        if estimate_tokens(prompt) > self._token_budget:
            trimmed = True
            prompt = self._trim_to_budget(
                system=system,
                template=template,
                blocks=blocks,
                user_input=user_input,
            )

        return PromptBuildResult(
            prompt=prompt,
            variant=variant,
            estimated_tokens=estimate_tokens(prompt),
            trimmed=trimmed,
        )

    def _assemble(
        self,
        *,
        system: str,
        template: str,
        blocks: list[tuple[str, str]],
        user_input: str,
    ) -> str:
        lines: list[str] = [system.strip(), "", template.strip(), ""]
        for name, content in blocks:
            c = str(content or "").strip()
            if not c:
                continue
            lines.append(f"{name}:")
            lines.append(c)
            lines.append("")
        lines.append(f"USER: {user_input}")
        lines.append("ASSISTANT:")
        return "\n".join(lines).strip()

    def _trim_to_budget(
        self,
        *,
        system: str,
        template: str,
        blocks: list[tuple[str, str]],
        user_input: str,
    ) -> str:
        # Copy blocks so we can mutate
        b = list(blocks)

        def render() -> str:
            return self._assemble(system=system, template=template, blocks=b, user_input=user_input)

        # 1) Aggressively truncate TOOL_RESULTS
        for i, (name, content) in enumerate(b):
            if name == "TOOL_RESULTS":
                b[i] = (name, _truncate(content, max_chars=self._limits.tool_results_trim))

        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 2) Keep only last 1 recent turn
        for i, (name, content) in enumerate(b):
            if name == "RECENT_TURNS":
                lines = [ln for ln in str(content).splitlines() if ln.strip()]
                # Keep last USER/ASSISTANT pair if possible
                keep = lines[-2:] if len(lines) >= 2 else lines[-1:]
                b[i] = (name, "\n".join(keep))

        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 3) Truncate dialog summary
        for i, (name, content) in enumerate(b):
            if name == "DIALOG_SUMMARY":
                b[i] = (name, _truncate(content, max_chars=self._limits.dialog_summary_trim))

        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 4) Truncate planner decision
        for i, (name, content) in enumerate(b):
            if name == "PLANNER_DECISION":
                b[i] = (name, _truncate(content, max_chars=self._limits.planner_decision_trim))

        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 5) Issue #1059: Trim personality block if present (less critical than tool data)
        for i, (name, content) in enumerate(b):
            if name == "PERSONALITY":
                b[i] = (name, _truncate(content, max_chars=400))

        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 6) Drop PERSONALITY entirely — tool results matter more
        b = [(n, c) for (n, c) in b if n != "PERSONALITY"]
        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 7) Drop RECENT_TURNS entirely — less important than date/time
        b = [(n, c) for (n, c) in b if n != "RECENT_TURNS"]
        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 8) Drop DIALOG_SUMMARY — still less critical than SESSION_CONTEXT
        b = [(n, c) for (n, c) in b if n != "DIALOG_SUMMARY"]
        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 9) Drop SESSION_CONTEXT last — contains current_datetime which is
        # critical for calendar/scheduling accuracy (Issue #1007)
        b = [(n, c) for (n, c) in b if n != "SESSION_CONTEXT"]
        if estimate_tokens(render()) <= self._token_budget:
            return render()

        # 10) Last resort: truncate user input
        truncated_user = _truncate(user_input, max_chars=self._limits.user_input_trim)
        return self._assemble(system=system, template=template, blocks=b, user_input=truncated_user)

    def _build_system_prompt(self, *, variant: PromptVariant, writing: int, personality_block: Optional[str] = None) -> str:
        # Keep this short; we have a strict token budget.
        style = "kısa ve öz" if writing < 3 else "kibar ve akıcı"
        extra = "" if variant == "A" else "- Gereksiz teknik detay verme; sonuç odaklı ol."

        # Issue #874: Use personality identity lines if available
        if personality_block:
            # Personality block contains identity & style, but may omit
            # the 'Efendim' honorific.  Issue #1019: Add it as a fallback
            # line if the personality block doesn't already mention it.
            honorific_line = ""
            if "efendim" not in personality_block.lower():
                honorific_line = "- 'Efendim' hitabını kullan."
            return "\n".join(
                filter(None, [
                    "Kimlik / Roller:",
                    personality_block,
                    honorific_line,
                    "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
                    f"- Ton: {style}.",
                    "- Çıktı: Sadece kullanıcıya söyleyeceğin metin. JSON/Markdown yok.",
                    extra,
                ])
            ).strip()

        return "\n".join(
            [
                "Kimlik / Roller:",
                "- Sen BANTZ'sın. Kullanıcı USER'dır.",
                "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
                "- 'Efendim' hitabını kullan.",
                f"- Ton: {style}.",
                "- Çıktı: Sadece kullanıcıya söyleyeceğin metin. JSON/Markdown yok.",
                extra,
            ]
        ).strip()

    def _build_template(
        self,
        *,
        route: str,
        variant: PromptVariant,
        complexity: int,
        writing: int,
    ) -> str:
        # A/B variants are intentionally subtle so they can be compared.
        if route in {"smalltalk", "chat"}:
            return self._template_chat(variant=variant)
        if route == "calendar":
            return self._template_calendar(variant=variant, complexity=complexity)
        if route == "gmail":
            return self._template_gmail(variant=variant, writing=writing)
        if route == "wiki":
            return self._template_wiki(variant=variant, complexity=complexity)
        return self._template_unknown(variant=variant)

    def _template_chat(self, *, variant: PromptVariant) -> str:
        lines = [
            "Görev:",
            "- Bu bir sohbet mesajı. Samimi ama kısa cevap ver (1-2 cümle).",
        ]
        if variant == "B":
            lines.append("- Kullanıcı soru sormadıysa, nazikçe 'Nasıl yardımcı olayım?' ile bitir.")
        return "\n".join(lines)

    def _template_calendar(self, *, variant: PromptVariant, complexity: int) -> str:
        lines = [
            "Görev (Takvim):",
            "- Tool sonuçlarına göre programı özetle veya istenen işlemin sonucunu söyle.",
            "- Tarih/saat belirt; varsa 1-2 maddeyle öne çıkan etkinlikleri say.",
        ]
        if complexity >= 3:
            lines.append("- Birden çok sonuç varsa, en önemlileri önce ver.")
        if variant == "B":
            lines.append("- Saat aralığı belirsizse kullanıcıya netleştirme sorusu sor.")
        
        # Few-shot example (short)
        lines.extend(
            [
                "\nÖrnek:",
                "PLANNER_DECISION: {route: calendar, calendar_intent: query}",
                "TOOL_RESULTS: 2 etkinlik", 
                "Cevap: 'Bugün 2 toplantınız var efendim: 10:00 proje, 15:00 birebir.'",
            ]
        )
        return "\n".join(lines)

    def _template_gmail(self, *, variant: PromptVariant, writing: int) -> str:
        lines = [
            "Görev (Gmail):",
            "- Tool sonuçlarına göre kullanıcıya inbox/mesaj bilgisini özetle.",
            "- Konu, gönderen, tarih gibi bilgileri kısa ver.",
            "- Kullanıcı bir yanıt taslağı istiyorsa: 1 kısa taslak + 2 alternatif öner.",
        ]
        if writing >= 4:
            lines.append("- Yazım kalitesi önemli: akıcı, kibar, hatasız Türkçe kullan.")
        if variant == "B":
            lines.append("- Taslak oluştururken gereksiz uzatma; net bir kapanış cümlesi ekle.")
        return "\n".join(lines)

    def _template_wiki(self, *, variant: PromptVariant, complexity: int) -> str:
        lines = [
            "Görev (Wiki):",
            "- Verilen içerikten 3-6 maddelik özet çıkar.",
            "- Bilinmeyen/emin olunmayan kısımları kesin konuşma.",
        ]
        if complexity >= 3:
            lines.append("- Kısa bir 'TL;DR' satırı ekle.")
        if variant == "B":
            lines.append("- Kaynak adı/bağlantı varsa sona tek satırda ekle.")
        return "\n".join(lines)

    def _template_unknown(self, *, variant: PromptVariant) -> str:
        lines = [
            "Görev:",
            "- Kullanıcının isteğini netleştirmek için 1 soru sor veya kısa bir öneri sun.",
        ]
        if variant == "B":
            lines.append("- Alternatif olarak 2 seçenek sun (örn. 'Takvim mi Gmail mi?').")
        return "\n".join(lines)


def compute_prompt_metrics(prompt: str) -> dict[str, Any]:
    """Compute simple, stable prompt quality metrics.

    These metrics are intentionally model-agnostic and suitable for unit tests.
    """

    p = str(prompt or "")
    metrics: dict[str, Any] = {
        "estimated_tokens": estimate_tokens(p),
        "chars": len(p),
        "has_user": "USER:" in p,
        "has_assistant": "ASSISTANT:" in p,
        "has_planner_decision": "PLANNER_DECISION" in p,
        "has_tool_results": "TOOL_RESULTS" in p,
        "has_session_context": "SESSION_CONTEXT" in p,
        "has_dialog_summary": "DIALOG_SUMMARY" in p,
    }
    # A rough “instruction density” proxy.
    metrics["lines"] = len([ln for ln in p.splitlines() if ln.strip()])
    return metrics
