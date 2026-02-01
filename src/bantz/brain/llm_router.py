"""LLM Orchestrator: Single entry point for all user inputs (LLM-first architecture).

Provides:
- Route classification (calendar | smalltalk | unknown)
- Intent extraction (create | modify | cancel | query)
- Slot extraction (date, time, duration, title, window_hint)
- Confidence scoring
- Tool planning
- Assistant reply (chat part)
- Confirmation management
- Memory/reasoning tracking

This is the "Jarvis orchestrator" - every turn goes through LLM first.
LLM controls routing, tool selection, confirmation prompts, and reasoning summary.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrchestratorOutput:
    """LLM Orchestrator decision output (expanded from RouterOutput).
    
    This is the unified decision structure that drives the entire turn.
    LLM controls everything: route, intent, tools, confirmation, memory, reasoning.
    """

    # Core routing (from original RouterOutput)
    route: str  # calendar | smalltalk | unknown
    calendar_intent: str  # create | modify | cancel | query | none
    slots: dict[str, Any]  # {date?, time?, duration?, title?, window_hint?}
    confidence: float  # 0.0-1.0
    tool_plan: list[str]  # ["calendar.list_events", ...]
    assistant_reply: str  # Chat/response text
    
    # Orchestrator extensions (Issue #134)
    ask_user: bool = False  # Need clarification?
    question: str = ""  # Clarification question (if ask_user=True)
    requires_confirmation: bool = False  # Destructive operation?
    confirmation_prompt: str = ""  # LLM-generated confirmation text
    memory_update: str = ""  # 1-2 line summary for rolling memory
    reasoning_summary: list[str] = field(default_factory=list)  # 1-3 bullet points (not raw CoT)
    
    # Debug/trace
    raw_output: dict[str, Any] = field(default_factory=dict)  # Full LLM response for debugging


# Legacy alias for backward compatibility
RouterOutput = OrchestratorOutput


class LLMOrchestratorProtocol(Protocol):
    """Protocol for LLM text completion (orchestrator interface)."""

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        """Complete text from prompt."""
        ...


# Legacy alias
LLMRouterProtocol = LLMOrchestratorProtocol


class JarvisLLMOrchestrator:
    """Jarvis-style LLM Orchestrator (Issue #134: LLM-first architecture).
    
    This orchestrator is the "single decision maker" - every user input goes through LLM
    to determine route, intent, slots, tool plan, confirmation needs, and reasoning.
    
    Design principles (LLM-first):
    - LLM controls everything: routing, tool selection, confirmation prompts
    - Strict JSON output only
    - Tool calls only if confidence >= threshold
    - Destructive operations require confirmation (LLM generates prompt, executor enforces)
    - Memory tracking with rolling summary
    - Reasoning summary (not raw CoT) for transparency
    """

    # Orchestrator system prompt (LLM-first architecture)
    SYSTEM_PROMPT = """Kimlik / Roller:
- Sen BANTZ'sın. Kullanıcı USER'dır.
- Rol: Jarvis-vari asistan. Türkçe konuş; 'Efendim' hitabını kullan.

Görev: Her kullanıcı mesajını şu şemaya göre sınıflandır ve **orkestra et**:

OUTPUT SCHEMA (zorunlu - genişletilmiş orchestrator):
{
  "route": "calendar | smalltalk | unknown",
  "calendar_intent": "create | modify | cancel | query | none",
  "slots": {
    "date": "YYYY-MM-DD veya null",
    "time": "HH:MM veya null",
    "duration": "süre (dk) veya null",
    "title": "etkinlik başlığı veya null",
    "window_hint": "evening|tomorrow|morning|today|week veya null"
  },
  "confidence": 0.0-1.0,
  "tool_plan": ["tool_name", ...],
  "assistant_reply": "Kullanıcıya söyleyeceğin metin",
  
  // Orchestrator extensions (Issue #134)
  "ask_user": false,  // Eksik bilgi var mı?
  "question": "",  // Netleştirme sorusu (ask_user=true ise)
  "requires_confirmation": false,  // Tehlikeli işlem? (delete/update)
  "confirmation_prompt": "",  // Onay isteme metni (requires_confirmation=true ise)
  "memory_update": "",  // 1-2 satır: bu turda ne oldu?
  "reasoning_summary": ["madde1", "madde2"]  // 1-3 madde: düşünce özeti (ham CoT değil)
}

KURALLAR (kritik):
1. Sadece tek bir JSON object döndür; Markdown yok; açıklama yok.
2. confidence < 0.7 → tool_plan boş bırak, ask_user=true + question doldur.
3. Saat belirsiz ("4" gibi) → 16:00 varsay ama confidence düşür (0.5).
4. Destructive işler (delete/modify) → requires_confirmation=true + confirmation_prompt doldur.
5. Tool çağırma ancak netse; belirsizlikte ask_user=true ile sor.
6. **ÖNEMLI: route="smalltalk" ise MUTLAKA assistant_reply doldur! (Jarvis tarzı, samimi, Türkçe)**
7. route="calendar" + tool çağırırsan assistant_reply boş bırakabilirsin.
8. **memory_update**: Her turda doldur! (örn: "Kullanıcı nasılsın diye sordu, karşılık verdim")
9. **reasoning_summary**: 1-3 madde, kısa ve net (örn: ["Saat belirsiz", "16:00 varsaydım", "Onay gerekir"])

ROUTE KURALLARI:
- "calendar": takvim sorgusu veya değişikliği
- "smalltalk": sohbet, selam, durum sorma
- "unknown": belirsiz veya başka kategoriler

CALENDAR_INTENT:
- "query": takvimi oku/sorgula
- "create": yeni etkinlik ekle
- "modify": mevcut etkinliği değiştir
- "cancel": etkinliği sil
- "none": takvim değil

TOOL_PLAN:
- "calendar.list_events": takvim sorgusu
- "calendar.find_free_slots": boş slot ara
- "calendar.create_event": etkinlik oluştur
- Birden fazla tool sıralı çağrılabilir.

TIME AWARENESS:
- "bu akşam" → window_hint="evening"
- "yarın" → window_hint="tomorrow"
- "yarın sabah" → window_hint="morning"
- "bugün" → window_hint="today"
- "bu hafta" → window_hint="week"
- Türkçe saat formatları (dikkat: context'e göre sabah/öğle/akşam):
  - "bire" / "birde" → time="01:00" veya "13:00" (context)
  - "ikiye" / "ikide" → time="02:00" veya "14:00" (context)
  - "üçe" / "üçte" → time="03:00" veya "15:00" (context)
  - "dörde" / "dörtte" → time="04:00" veya "16:00" (context)
  - "beşe" / "beşte" → time="05:00" veya "17:00" (context)
  - "altıya" / "altıda" → time="06:00" veya "18:00" (context)
  - "yediye" / "yedide" → time="07:00" veya "19:00" (context)
  - "sekize" / "sekizde" → time="08:00" veya "20:00" (context)
  - "dokuza" / "dokuzda" → time="09:00" veya "21:00" (context)
  - "ona" / "onda" → time="10:00" veya "22:00" (context)
  - "on bire" / "on birde" → time="11:00" veya "23:00" (context)
  - "on ikiye" / "on ikide" → time="12:00" veya "00:00" (context)
  - DEFAULT: yarın/öğle/iş saatleri → 13:00-17:00 arası tahmin et
  - "sabah" context → 07:00-11:00
  - "öğle" context → 12:00-14:00
  - "akşam" context → 17:00-21:00
  - Belirsizse → time field boş bırak

ÖRNEKLER:
USER: hey bantz nasılsın
→ {
  "route": "smalltalk",
  "calendar_intent": "none",
  "slots": {},
  "confidence": 1.0,
  "tool_plan": [],
  "assistant_reply": "İyiyim efendim, teşekkür ederim. Size nasıl yardımcı olabilirim?"
}

USER: nasılsın dostum
→ {
  "route": "smalltalk",
  "calendar_intent": "none",
  "slots": {},
  "confidence": 1.0,
  "tool_plan": [],
  "assistant_reply": "Çok iyiyim efendim, teşekkür ederim. Siz nasılsınız?"
}

USER: selam
→ {
  "route": "smalltalk",
  "calendar_intent": "none",
  "slots": {},
  "confidence": 1.0,
  "tool_plan": [],
  "assistant_reply": "Merhaba efendim! Size nasıl yardımcı olabilirim?"
}

USER: bugün neler yapacağız bakalım
→ {
  "route": "calendar",
  "calendar_intent": "query",
  "slots": {"window_hint": "today"},
  "confidence": 0.9,
  "tool_plan": ["calendar.list_events"],
  "assistant_reply": ""
}

USER: saat 4 için bir toplantı oluştur
→ {
  "route": "calendar",
  "calendar_intent": "create",
  "slots": {"time": "16:00", "title": "toplantı", "duration": null},
  "confidence": 0.5,
  "tool_plan": [],
  "assistant_reply": "Süre ne olsun efendim? (örn. 30 dk / 1 saat)"
}

USER: yarın ikide toplantım var
→ {
  "route": "calendar",
  "calendar_intent": "create",
  "slots": {"time": "14:00", "title": "toplantı", "window_hint": "tomorrow"},
  "confidence": 0.85,
  "tool_plan": ["calendar.create_event"],
  "assistant_reply": ""
}

USER: öğlene doktor randevusu koy
→ {
  "route": "calendar",
  "calendar_intent": "create",
  "slots": {"time": "12:00", "title": "doktor randevusu"},
  "confidence": 0.9,
  "tool_plan": ["calendar.create_event"],
  "assistant_reply": ""
}

USER: bu akşam neler yapacağız
→ {
  "route": "calendar",
  "calendar_intent": "query",
  "slots": {"window_hint": "evening"},
  "confidence": 0.9,
  "tool_plan": ["calendar.list_events"],
  "assistant_reply": ""
}

USER: bu akşam sekize parti ekle
→ {
  "route": "calendar",
  "calendar_intent": "create",
  "slots": {"time": "20:00", "title": "parti", "window_hint": "evening", "duration": null},
  "confidence": 0.7,
  "tool_plan": ["calendar.create_event"],
  "assistant_reply": ""
}
"""

    def __init__(
        self,
        *,
        llm: Optional[LLMRouterProtocol] = None,
        llm_client: Optional[LLMRouterProtocol] = None,
        system_prompt: Optional[str] = None,
        confidence_threshold: float = 0.7,
        max_attempts: int = 2,
    ):
        """Initialize router.
        
        Args:
            llm: LLM client implementing LLMRouterProtocol
            system_prompt: Override the default SYSTEM_PROMPT (useful for benchmarking)
            confidence_threshold: Minimum confidence to execute tools (default 0.7)
            max_attempts: Max repair attempts for malformed JSON (default 2)
        """
        effective_llm = llm if llm is not None else llm_client
        if effective_llm is None:
            raise TypeError("JarvisLLMOrchestrator requires `llm=` (or legacy `llm_client=`)")

        self._llm = effective_llm
        self._system_prompt = (system_prompt if system_prompt is not None else self.SYSTEM_PROMPT)
        self._confidence_threshold = float(confidence_threshold)
        self._max_attempts = int(max_attempts)

    def route(
        self,
        *,
        user_input: str,
        dialog_summary: Optional[str] = None,
        session_context: Optional[dict[str, Any]] = None,
    ) -> RouterOutput:
        """Route user input through LLM.
        
        Args:
            user_input: User's message
            dialog_summary: Previous turns summary (for memory)
            session_context: Session info (timezone, windows, etc.)
        
        Returns:
            RouterOutput with route, intent, slots, confidence, tool_plan, reply
        """
        # Build prompt with context
        prompt = self._build_prompt(
            user_input=user_input,
            dialog_summary=dialog_summary,
            session_context=session_context,
        )

        # Call LLM
        # JSON outputs can exceed small defaults (e.g. 200 tokens) and get truncated,
        # causing parse failures. Use a safer default.
        try:
            raw_text = self._llm.complete_text(prompt=prompt, temperature=0.0, max_tokens=512)
        except TypeError:
            # Backward compatibility for mocks/adapters that only accept `prompt`.
            raw_text = self._llm.complete_text(prompt=prompt)

        # Parse JSON
        try:
            parsed = self._parse_json(raw_text)
        except Exception as e:
            logger.warning(f"Router JSON parse failed: {e}")
            # Fallback: unknown route with low confidence
            return self._fallback_output(user_input, error=str(e))

        # Validate and extract
        return self._extract_output(parsed, raw_text=raw_text)

    def _build_prompt(
        self,
        *,
        user_input: str,
        dialog_summary: Optional[str] = None,
        session_context: Optional[dict[str, Any]] = None,
    ) -> str:
        """Build router prompt with context."""
        lines = [self._system_prompt, ""]

        # Add dialog memory if available
        if dialog_summary:
            lines.append(f"DIALOG_SUMMARY (önceki turlar):\n{dialog_summary}\n")

        # Add session context hints
        if session_context:
            ctx_str = json.dumps(session_context, ensure_ascii=False, indent=2)
            lines.append(f"SESSION_CONTEXT:\n{ctx_str}\n")

        # Add current user input
        lines.append(f"USER: {user_input}")
        lines.append("ASSISTANT (sadece JSON):")

        return "\n".join(lines)

    def _parse_json(self, raw_text: str) -> dict[str, Any]:
        """Parse JSON from LLM output (tolerates markdown wrappers)."""
        text = (raw_text or "").strip()

        # Remove markdown code blocks
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        text = text.strip()

        # Find the first JSON object start
        start = text.find("{")
        if start == -1:
            raise ValueError("No JSON object found")

        candidate = text[start:]

        # Some models occasionally omit the final closing brace of the outer object.
        # If braces are unbalanced, append the missing number of '}' characters.
        brace_balance = candidate.count("{") - candidate.count("}")
        if brace_balance > 0:
            candidate = candidate + ("}" * brace_balance)

        # Trim to the last closing brace (in case extra text follows)
        end = candidate.rfind("}")
        if end == -1:
            raise ValueError("No JSON object found")

        json_text = candidate[: end + 1]
        return json.loads(json_text)

    def _extract_output(self, parsed: dict[str, Any], raw_text: str) -> OrchestratorOutput:
        """Extract OrchestratorOutput from parsed JSON (expanded with orchestrator fields)."""
        route = str(parsed.get("route") or "unknown").strip().lower()
        if route not in {"calendar", "smalltalk", "unknown"}:
            route = "unknown"

        calendar_intent = str(parsed.get("calendar_intent") or "none").strip().lower()
        # Allow both high-level intents (create/modify/cancel/query) and tool-like intents
        # used by regression tests (list_events/create_event/update_event/delete_event).
        if not calendar_intent:
            calendar_intent = "none"
        elif not re.match(r"^[a-z0-9_]+$", calendar_intent):
            calendar_intent = "none"

        slots = parsed.get("slots") or {}
        if not isinstance(slots, dict):
            slots = {}

        confidence = float(parsed.get("confidence") or 0.0)
        confidence = max(0.0, min(1.0, confidence))

        raw_tool_plan = parsed.get("tool_plan") or []
        tool_plan: list[str] = []
        if isinstance(raw_tool_plan, list):
            for item in raw_tool_plan:
                if isinstance(item, str):
                    name = item
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("tool") or item.get("tool_name")
                else:
                    name = str(item)

                name = str(name or "").strip()
                if name:
                    tool_plan.append(name)

        # Apply confidence threshold: if below threshold, clear tool_plan
        if confidence < self._confidence_threshold:
            tool_plan = []

        assistant_reply = str(parsed.get("assistant_reply") or "").strip()
        
        # Orchestrator extensions (Issue #134)
        ask_user = bool(parsed.get("ask_user", False))
        question = str(parsed.get("question") or "").strip()
        requires_confirmation = bool(parsed.get("requires_confirmation", False))
        confirmation_prompt = str(parsed.get("confirmation_prompt") or "").strip()
        memory_update = str(parsed.get("memory_update") or "").strip()
        
        reasoning_summary = parsed.get("reasoning_summary") or []
        if not isinstance(reasoning_summary, list):
            reasoning_summary = []
        reasoning_summary = [str(r).strip() for r in reasoning_summary if r]

        return OrchestratorOutput(
            route=route,
            calendar_intent=calendar_intent,
            slots=slots,
            confidence=confidence,
            tool_plan=tool_plan,
            assistant_reply=assistant_reply,
            ask_user=ask_user,
            question=question,
            requires_confirmation=requires_confirmation,
            confirmation_prompt=confirmation_prompt,
            memory_update=memory_update,
            reasoning_summary=reasoning_summary,
            raw_output=parsed,
        )

    def _fallback_output(self, user_input: str, error: str) -> OrchestratorOutput:
        """Fallback output when parsing fails."""
        logger.warning(f"Orchestrator fallback triggered: {error}")
        return OrchestratorOutput(
            route="unknown",
            calendar_intent="none",
            slots={},
            confidence=0.0,
            tool_plan=[],
            assistant_reply="Efendim, tam anlayamadım. Tekrar eder misiniz?",
            raw_output={"error": error, "user_input": user_input},
        )


class HybridJarvisLLMOrchestrator:
    """Hybrid orchestrator: plan with one model, reply with another.

    Intended usage:
    - planner (3B): strict JSON decision (route/intent/slots/tool_plan)
    - finalizer (8B): natural-language assistant reply

    This wrapper keeps the decision JSON from the planner and overwrites
    `assistant_reply` using the finalizer model.
    """

    def __init__(
        self,
        *,
        planner: JarvisLLMOrchestrator,
        finalizer_llm: LLMOrchestratorProtocol,
        override_mode: str = "smalltalk_only",  # smalltalk_only | always
    ):
        self._planner = planner
        self._finalizer = finalizer_llm
        self._override_mode = (override_mode or "smalltalk_only").strip().lower()

    def route(
        self,
        *,
        user_input: str,
        dialog_summary: Optional[str] = None,
        session_context: Optional[dict[str, Any]] = None,
    ) -> RouterOutput:
        planned = self._planner.route(
            user_input=user_input,
            dialog_summary=dialog_summary,
            session_context=session_context,
        )

        should_override = False
        if self._override_mode == "always":
            should_override = True
        else:
            should_override = planned.route == "smalltalk"

        if planned.ask_user and planned.question:
            # Prefer explicit clarifying question.
            if not planned.assistant_reply:
                from dataclasses import replace

                return replace(planned, assistant_reply=planned.question)
            return planned

        if not should_override:
            return planned

        try:
            prompt_lines = [
                "Kimlik / Roller:",
                "- Sen BANTZ'sın. Kullanıcı USER'dır.",
                "- Türkçe konuş; 'Efendim' hitabını kullan.",
                "- Sadece kullanıcıya söyleyeceğin metni üret; JSON/Markdown yok.",
                "",
            ]

            if dialog_summary:
                prompt_lines.append(f"DIALOG_SUMMARY:\n{dialog_summary}\n")

            if session_context:
                ctx_str = json.dumps(session_context, ensure_ascii=False)
                prompt_lines.append(f"SESSION_CONTEXT (JSON):\n{ctx_str}\n")

            prompt_lines.append("PLANNER_DECISION (JSON):")
            prompt_lines.append(
                json.dumps(
                    {
                        "route": planned.route,
                        "calendar_intent": planned.calendar_intent,
                        "slots": planned.slots,
                        "confidence": planned.confidence,
                    },
                    ensure_ascii=False,
                )
            )
            prompt_lines.append(f"\nUSER: {user_input}\nASSISTANT:")

            try:
                reply = self._finalizer.complete_text(
                    prompt="\n".join(prompt_lines),
                    temperature=0.2,
                    max_tokens=256,
                )
            except TypeError:
                reply = self._finalizer.complete_text(prompt="\n".join(prompt_lines))
            reply = str(reply or "").strip()
            if reply:
                from dataclasses import replace

                return replace(planned, assistant_reply=reply)
        except Exception:
            pass

        return planned


# Legacy alias for backward compatibility
JarvisLLMRouter = JarvisLLMOrchestrator
