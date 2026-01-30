"""LLM Router: Single entry point for all user inputs.

Provides:
- Route classification (calendar | smalltalk | unknown)
- Intent extraction (create | modify | cancel | query)
- Slot extraction (date, time, duration, title, window_hint)
- Confidence scoring
- Tool planning
- Assistant reply (chat part)

This is the "Jarvis consistency layer" - every turn goes through LLM first.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouterOutput:
    """LLM Router decision output."""

    route: str  # calendar | smalltalk | unknown
    calendar_intent: str  # create | modify | cancel | query | none
    slots: dict[str, Any]  # {date?, time?, duration?, title?, window_hint?}
    confidence: float  # 0.0-1.0
    tool_plan: list[str]  # ["calendar.list_events", ...]
    assistant_reply: str  # Chat/response text
    raw_output: dict[str, Any]  # Full LLM response for debugging


class LLMRouterProtocol(Protocol):
    """Protocol for LLM text completion."""

    def complete_text(self, *, prompt: str) -> str:
        """Complete text from prompt."""
        ...


class JarvisLLMRouter:
    """Jarvis-style LLM Router with strict rules and confidence thresholds.
    
    This router is the "single entry point" - every user input goes through it
    to determine route, intent, slots, and tool plan.
    
    Design principles:
    - Strict JSON output only
    - Tool calls only if confidence >= threshold
    - Destructive operations require confirmation (handled by PolicyEngine)
    - Time ambiguity handled with confidence reduction
    """

    # Router system prompt (OPTIMIZED - shorter for speed)
    SYSTEM_PROMPT = """Sen BANTZ'sın. Kullanıcı USER. Türkçe konuş, 'Efendim' hitabı kullan.

Görev: Her mesajı şu JSON'a çevir:

{
  "route": "calendar|smalltalk|unknown",
  "calendar_intent": "create|modify|cancel|query|none",
  "slots": {"date": "YYYY-MM-DD", "time": "HH:MM", "duration": dk, "title": "...", "window_hint": "today|tomorrow|morning|evening|week"},
  "confidence": 0.0-1.0,
  "tool_plan": ["tool_name"],
  "assistant_reply": "cevabın"
}

Kurallar:
- Tek JSON, açıklama yok
- confidence < 0.7 → tool_plan=[], soru sor
- route="smalltalk" → assistant_reply DOLDUR (samimi, Türkçe)
- route="calendar" + tool → assistant_reply boş ok

Route:
- "calendar": takvim işlemi
- "smalltalk": sohbet/selam
- "unknown": belirsiz

Calendar Intent:
- "query": takvimi oku
- "create": etkinlik ekle
- "modify": değiştir
- "cancel": sil
- "none": takvim değil

Tools:
- "calendar.list_events": takvim sorgusu
- "calendar.find_free_slots": boş slot
- "calendar.create_event": etkinlik oluştur

Time Formats:
- "ikiye/ikide" → "14:00"
- "üçe/üçte" → "15:00"
- "dörde" → "16:00"
- "beşe" → "17:00"
- "öğlene" → "12:00"
- Sabah: 07-11, Öğle: 12-14, Akşam: 17-21

Window Hints:
- "bu akşam" → "evening"
- "yarın" → "tomorrow"
- "bugün" → "today"

ÖRNEKLER:
USER: merhaba
→ {"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "Merhaba efendim!"}

USER: bugün neler var
→ {"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}

USER: yarın ikide toplantım var
→ {"route": "calendar", "calendar_intent": "create", "slots": {"time": "14:00", "title": "toplantı", "window_hint": "tomorrow"}, "confidence": 0.85, "tool_plan": ["calendar.create_event"], "assistant_reply": ""}
"""
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
        llm: LLMRouterProtocol,
        confidence_threshold: float = 0.7,
        max_attempts: int = 2,
    ):
        """Initialize router.
        
        Args:
            llm: LLM client implementing LLMRouterProtocol
            confidence_threshold: Minimum confidence to execute tools (default 0.7)
            max_attempts: Max repair attempts for malformed JSON (default 2)
        """
        self._llm = llm
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
        lines = [self.SYSTEM_PROMPT, ""]

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

        # Find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object found")

        json_text = text[start : end + 1]
        return json.loads(json_text)

    def _extract_output(self, parsed: dict[str, Any], raw_text: str) -> RouterOutput:
        """Extract RouterOutput from parsed JSON."""
        route = str(parsed.get("route") or "unknown").strip().lower()
        if route not in {"calendar", "smalltalk", "unknown"}:
            route = "unknown"

        calendar_intent = str(parsed.get("calendar_intent") or "none").strip().lower()
        if calendar_intent not in {"create", "modify", "cancel", "query", "none"}:
            calendar_intent = "none"

        slots = parsed.get("slots") or {}
        if not isinstance(slots, dict):
            slots = {}

        confidence = float(parsed.get("confidence") or 0.0)
        confidence = max(0.0, min(1.0, confidence))

        tool_plan = parsed.get("tool_plan") or []
        if not isinstance(tool_plan, list):
            tool_plan = []
        tool_plan = [str(t).strip() for t in tool_plan if t]

        # Apply confidence threshold: if below threshold, clear tool_plan
        if confidence < self._confidence_threshold:
            tool_plan = []

        assistant_reply = str(parsed.get("assistant_reply") or "").strip()

        return RouterOutput(
            route=route,
            calendar_intent=calendar_intent,
            slots=slots,
            confidence=confidence,
            tool_plan=tool_plan,
            assistant_reply=assistant_reply,
            raw_output=parsed,
        )

    def _fallback_output(self, user_input: str, error: str) -> RouterOutput:
        """Fallback output when parsing fails."""
        logger.warning(f"Router fallback triggered: {error}")
        return RouterOutput(
            route="unknown",
            calendar_intent="none",
            slots={},
            confidence=0.0,
            tool_plan=[],
            assistant_reply="Efendim, tam anlayamadım. Tekrar eder misiniz?",
            raw_output={"error": error, "user_input": user_input},
        )
