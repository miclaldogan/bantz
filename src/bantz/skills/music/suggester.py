"""Context-aware music suggester — calendar + time-based recommendations.

Issue #1296: Music Control — Context-Aware Suggestions.

Suggests music genres/playlists based on:
- Calendar context (meeting → mute, deep work → lo-fi, exercise → EDM)
- Time of day (morning → chill, afternoon → energy, night → ambient)
- User preferences (configurable mood map)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MusicSuggestion:
    """A music suggestion with context."""

    genres: list[str]
    reason: str
    context_type: str  # "calendar", "time", "user"
    event_title: str = ""
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "genres": self.genres,
            "reason": self.reason,
            "context_type": self.context_type,
            "event_title": self.event_title,
            "confidence": self.confidence,
        }


# ── Default mood mappings ────────────────────────────────────────

DEFAULT_CALENDAR_MOODS: dict[str, list[str] | None] = {
    # Calendar event keywords → suggested genres
    # None means "don't suggest music"
    "deep work": ["lo-fi beats", "ambient", "classical"],
    "focus": ["lo-fi beats", "ambient", "classical"],
    "work": ["lo-fi beats", "ambient", "classical"],
    "concentrate": ["lo-fi beats", "ambient"],
    "coding": ["lo-fi beats", "synthwave", "electronic"],
    "programming": ["lo-fi beats", "synthwave"],
    "meeting": None,
    "conference": None,
    "call": None,
    "phone": None,
    "interview": None,
    "lunch": ["pop", "chill", "bossa nova"],
    "meal": ["pop", "chill", "jazz"],
    "exercise": ["workout", "EDM", "rock", "hip-hop"],
    "gym": ["workout", "EDM", "rock"],
    "sport": ["workout", "EDM", "rock"],
    "yoga": ["ambient", "meditation", "nature sounds"],
    "meditation": ["ambient", "meditation", "nature sounds"],
    "study": ["classical", "lo-fi beats", "ambient"],
    "class": ["classical", "lo-fi beats"],
    "reading": ["classical", "jazz", "ambient"],
    "relax": ["chill", "jazz", "acoustic"],
    "rest": ["chill", "jazz", "acoustic"],
    "party": ["pop", "dance", "EDM"],
    "creative": ["indie", "alternative", "jazz"],
    "writing": ["classical", "ambient", "piano"],
}

DEFAULT_TIME_MOODS: dict[str, list[str]] = {
    # Time of day → suggested genres
    "early_morning": ["classical", "jazz", "acoustic"],  # 05:00-08:00
    "morning": ["indie", "pop", "Turkish pop"],  # 08:00-12:00
    "afternoon": ["rock", "electronic", "hip-hop"],  # 12:00-17:00
    "evening": ["chill", "jazz", "R&B"],  # 17:00-21:00
    "night": ["ambient", "lo-fi beats", "classical"],  # 21:00-05:00
}


class MusicSuggester:
    """Context-aware music recommendation engine.

    Uses calendar events and time of day to suggest appropriate music.
    """

    def __init__(
        self,
        *,
        calendar_moods: dict[str, list[str] | None] | None = None,
        time_moods: dict[str, list[str]] | None = None,
    ) -> None:
        self._calendar_moods = calendar_moods or dict(DEFAULT_CALENDAR_MOODS)
        self._time_moods = time_moods or dict(DEFAULT_TIME_MOODS)

    def suggest_from_calendar(
        self,
        event_title: str,
    ) -> MusicSuggestion | None:
        """Suggest music based on a calendar event title.

        Returns None if the event is a "no music" context (meetings, calls).
        """
        title_lower = event_title.lower()

        for keyword, genres in self._calendar_moods.items():
            if keyword in title_lower:
                if genres is None:
                    # Meeting/call — don't suggest music
                    return MusicSuggestion(
                        genres=[],
                        reason=f"Music not recommended during '{event_title}'.",
                        context_type="calendar",
                        event_title=event_title,
                        confidence=0.9,
                    )
                return MusicSuggestion(
                    genres=genres,
                    reason=f"Music suggestion based on '{event_title}'.",
                    context_type="calendar",
                    event_title=event_title,
                    confidence=0.8,
                )

        return None  # No matching context

    def suggest_from_time(
        self,
        now: datetime | None = None,
    ) -> MusicSuggestion:
        """Suggest music based on time of day."""
        current = now or datetime.now()
        hour = current.hour

        if 5 <= hour < 8:
            period = "early_morning"
            reason = "Good morning! Calm music for early hours."
        elif 8 <= hour < 12:
            period = "morning"
            reason = "Energetic music to start the day."
        elif 12 <= hour < 17:
            period = "afternoon"
            reason = "Keep your energy up this afternoon."
        elif 17 <= hour < 21:
            period = "evening"
            reason = "Time to relax this evening."
        else:
            period = "night"
            reason = "Calm melodies for the night."

        genres = self._time_moods.get(period, ["chill"])
        return MusicSuggestion(
            genres=genres,
            reason=reason,
            context_type="time",
            confidence=0.6,
        )

    def suggest(
        self,
        *,
        current_events: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> MusicSuggestion:
        """Get the best music suggestion considering all contexts.

        Calendar events take priority over time-based suggestions.
        If a calendar event says "no music", that's respected.

        Args:
            current_events: List of current calendar events (dicts with 'title').
            now: Current time (default: now).

        Returns:
            Best :class:`MusicSuggestion`.
        """
        # 1) Calendar context (highest priority)
        if current_events:
            for event in current_events:
                title = event.get("title", "") or event.get("summary", "")
                if not title:
                    continue
                suggestion = self.suggest_from_calendar(title)
                if suggestion is not None:
                    return suggestion

        # 2) Time-based fallback
        return self.suggest_from_time(now)

    def get_mood_map(self) -> dict[str, Any]:
        """Return the current mood mappings (for UI/config display)."""
        return {
            "calendar_moods": {
                k: v for k, v in self._calendar_moods.items()
            },
            "time_moods": self._time_moods,
        }

    def update_calendar_mood(
        self,
        keyword: str,
        genres: list[str] | None,
    ) -> None:
        """Update a calendar mood mapping.

        Args:
            keyword: Calendar event keyword.
            genres: List of genres, or None to mark as "no music".
        """
        self._calendar_moods[keyword.lower()] = genres
