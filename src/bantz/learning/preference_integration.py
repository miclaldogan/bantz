"""
User Preferences Integration — Issue #441.

Connects the learning subsystem to the orchestrator loop so that:
- User corrections and choices feed back into the preference model
- Learned preferences inject context into LLM prompts
- Adaptive defaults (e.g. preferred calendar, email formality) apply
- Session-level preference cache persists across turns

Usage::

    from bantz.learning.preference_integration import PreferenceIntegration

    prefs = PreferenceIntegration(user_id="default")
    
    # Record a user correction
    prefs.record_correction(original="toplantı", corrected="buluşma")
    
    # Get preference context for LLM
    ctx = prefs.get_prompt_context()
    # → "Kullanıcı tercihleri: takvim uygulamasını sık kullanır, ..."
    
    # Get adaptive defaults for a tool
    defaults = prefs.get_tool_defaults("calendar_create_event")
    # → {"duration_minutes": 60, "reminder_minutes": 15}
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────


@dataclass
class UserPreference:
    """A single learned preference."""
    key: str
    value: Any
    confidence: float = 0.5  # 0.0–1.0
    source: str = "inferred"  # inferred | explicit | default
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
        }


@dataclass
class SessionPreferences:
    """Session-level preference cache (persists across turns)."""
    preferences: Dict[str, UserPreference] = field(default_factory=dict)
    corrections: List[Dict[str, str]] = field(default_factory=list)
    tool_usage_counts: Dict[str, int] = field(default_factory=dict)
    turn_count: int = 0

    def get(self, key: str) -> Optional[UserPreference]:
        return self.preferences.get(key)

    def set(self, key: str, value: Any, confidence: float = 0.5, source: str = "inferred"):
        self.preferences[key] = UserPreference(
            key=key, value=value, confidence=confidence, source=source
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preferences": {k: v.to_dict() for k, v in self.preferences.items()},
            "corrections_count": len(self.corrections),
            "tool_usage": self.tool_usage_counts,
            "turn_count": self.turn_count,
        }


# ─────────────────────────────────────────────────────────────────
# Adaptive defaults
# ─────────────────────────────────────────────────────────────────

# Tool → parameter → default value
_TOOL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "calendar_create_event": {
        "duration_minutes": 60,
        "reminder_minutes": 15,
        "calendar_id": "primary",
    },
    "calendar_list_events": {
        "max_results": 10,
        "time_range_days": 7,
    },
    "gmail_send": {
        "format": "plain",
    },
    "gmail_list_messages": {
        "max_results": 10,
    },
}


# ─────────────────────────────────────────────────────────────────
# Preference Integration
# ─────────────────────────────────────────────────────────────────


class PreferenceIntegration:
    """
    Bridges the learning subsystem and the orchestrator.

    Responsibilities:
    1. Record user feedback (corrections, choices, cancellations)
    2. Generate preference-enriched prompt context
    3. Provide adaptive defaults for tool parameters
    4. Maintain session-level preference cache
    """

    def __init__(
        self,
        user_id: str = "default",
        profile: Optional[Any] = None,
    ):
        self._user_id = user_id
        self._profile = profile
        self._session = SessionPreferences()

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def session(self) -> SessionPreferences:
        return self._session

    # ── Recording ───────────────────────────────────────────────

    def record_correction(self, original: str, corrected: str, intent: str = "") -> None:
        """Record a user correction (e.g. ASR fix, name correction)."""
        self._session.corrections.append({
            "original": original,
            "corrected": corrected,
            "intent": intent,
            "time": str(time.time()),
        })
        # Increase confidence for corrected terms
        self._session.set(
            f"correction:{original}",
            corrected,
            confidence=0.8,
            source="explicit",
        )
        logger.debug("Recorded correction: %r → %r", original, corrected)

    def record_choice(self, key: str, value: Any, intent: str = "") -> None:
        """Record a user choice (e.g. selected a calendar, chose email format)."""
        self._session.set(key, value, confidence=0.7, source="explicit")
        logger.debug("Recorded choice: %s = %r", key, value)

    def record_cancellation(self, intent: str, reason: str = "") -> None:
        """Record a user cancellation (helps learn what NOT to suggest)."""
        cancel_key = f"cancel:{intent}"
        existing = self._session.get(cancel_key)
        count = (existing.value if existing else 0) + 1
        self._session.set(cancel_key, count, confidence=min(0.9, 0.3 + count * 0.1))
        logger.debug("Recorded cancellation: intent=%s count=%d", intent, count)

    def record_tool_usage(self, tool_name: str) -> None:
        """Track tool usage frequency for adaptive defaults."""
        self._session.tool_usage_counts[tool_name] = (
            self._session.tool_usage_counts.get(tool_name, 0) + 1
        )

    def record_turn(self) -> None:
        """Called at start of each turn to track session length."""
        self._session.turn_count += 1

    # ── Prompt context ──────────────────────────────────────────

    def get_prompt_context(self) -> str:
        """Generate a preference-enriched context string for LLM prompts.

        Returns a Turkish description of known user preferences to inject
        into the system prompt, helping the LLM personalize responses.
        """
        parts: List[str] = []

        # Explicit preferences
        explicit = [
            p for p in self._session.preferences.values()
            if p.source == "explicit" and not p.key.startswith("cancel:")
            and not p.key.startswith("correction:")
        ]
        if explicit:
            for p in explicit:
                parts.append(f"- {p.key}: {p.value}")

        # Frequent tools
        if self._session.tool_usage_counts:
            top_tools = sorted(
                self._session.tool_usage_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            tool_str = ", ".join(f"{t[0]} ({t[1]}x)" for t in top_tools)
            parts.append(f"- Sık kullanılan araçlar: {tool_str}")

        # Corrections (for name/term consistency)
        recent_corrections = self._session.corrections[-5:]
        if recent_corrections:
            corr_parts = []
            for c in recent_corrections:
                corr_parts.append(f"{c['original']}→{c['corrected']}")
            parts.append(f"- Düzeltmeler: {', '.join(corr_parts)}")

        if not parts:
            return ""

        return "Kullanıcı tercihleri:\n" + "\n".join(parts)

    # ── Adaptive defaults ───────────────────────────────────────

    def get_tool_defaults(self, tool_name: str) -> Dict[str, Any]:
        """Get adaptive defaults for a tool, merging base defaults with learned prefs.

        Args:
            tool_name: Tool name (e.g. "calendar_create_event").

        Returns:
            Dict of parameter defaults.
        """
        defaults = dict(_TOOL_DEFAULTS.get(tool_name, {}))

        # Override with session preferences if available
        for key, pref in self._session.preferences.items():
            if key.startswith(f"{tool_name}:"):
                param = key.split(":", 1)[1]
                if pref.confidence >= 0.5:
                    defaults[param] = pref.value

        return defaults

    def apply_corrections(self, text: str) -> str:
        """Apply learned corrections to text (e.g. ASR autocorrect).

        Simple substring replacement for high-confidence corrections.
        """
        result = text
        for c in self._session.corrections:
            original = c["original"]
            corrected = c["corrected"]
            if original in result:
                result = result.replace(original, corrected)
        return result

    # ── Session management ──────────────────────────────────────

    def reset_session(self) -> None:
        """Reset session preferences (new conversation)."""
        self._session = SessionPreferences()

    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of the current session's learned preferences."""
        return self._session.to_dict()
