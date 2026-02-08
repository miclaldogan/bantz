"""Personalized boot greeting with safe profile + last-session summary (Issue #303).

Generates a time-of-day greeting with optional last session context.
All output is PII-free (max 300 chars).

Safety rules:
1. No PII in greeting (names, emails, phone numbers)
2. No specific event titles (might be sensitive)
3. No email subjects
4. Only counts and generic references

Usage::

    from bantz.voice.personalized_greeting import build_greeting
    greeting = build_greeting()
    # "Günaydın efendim. Dün 3 takvim etkinliği vardı."
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "build_greeting",
    "GreetingConfig",
    "SessionSummary",
    "get_time_greeting",
    "get_last_session_summary",
    "save_session_summary",
]

MAX_GREETING_CHARS = 300
SESSION_FILE = Path(
    os.getenv("BANTZ_SESSION_FILE", "~/.config/bantz/last_session.json")
).expanduser()


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


@dataclass
class GreetingConfig:
    """Greeting configuration.

    Attributes
    ----------
    include_session_summary:
        Include last session summary in greeting.
    max_chars:
        Maximum greeting length.
    session_file:
        Path to last session summary file.
    """

    include_session_summary: bool = True
    max_chars: int = MAX_GREETING_CHARS
    session_file: Path = field(default_factory=lambda: SESSION_FILE)


# ─────────────────────────────────────────────────────────────────
# Session summary
# ─────────────────────────────────────────────────────────────────


@dataclass
class SessionSummary:
    """Safe, PII-free summary of last session activity.

    Only stores counts and generic references — never specific
    event titles, email subjects, or user names.
    """

    calendar_events: int = 0
    emails_checked: int = 0
    tasks_completed: int = 0
    web_searches: int = 0
    total_turns: int = 0
    date: str = ""  # ISO date

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calendar_events": self.calendar_events,
            "emails_checked": self.emails_checked,
            "tasks_completed": self.tasks_completed,
            "web_searches": self.web_searches,
            "total_turns": self.total_turns,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionSummary":
        return cls(
            calendar_events=int(data.get("calendar_events", 0)),
            emails_checked=int(data.get("emails_checked", 0)),
            tasks_completed=int(data.get("tasks_completed", 0)),
            web_searches=int(data.get("web_searches", 0)),
            total_turns=int(data.get("total_turns", 0)),
            date=str(data.get("date", "")),
        )

    def to_turkish(self) -> Optional[str]:
        """Generate a safe Turkish summary sentence.

        Returns None if there's nothing meaningful to report.
        """
        parts: List[str] = []

        if self.calendar_events > 0:
            parts.append(f"{self.calendar_events} takvim etkinliği")
        if self.emails_checked > 0:
            parts.append(f"{self.emails_checked} mail")
        if self.tasks_completed > 0:
            parts.append(f"{self.tasks_completed} görev")
        if self.web_searches > 0:
            parts.append(f"{self.web_searches} arama")

        if not parts:
            return None

        # Determine time reference
        today = datetime.date.today().isoformat()
        if self.date == today:
            prefix = "Bugün"
        elif self.date:
            prefix = "Son oturumda"
        else:
            prefix = "Geçen sefer"

        items = ", ".join(parts)
        return f"{prefix} {items} işlendi efendim."

    @property
    def has_activity(self) -> bool:
        return (
            self.calendar_events > 0
            or self.emails_checked > 0
            or self.tasks_completed > 0
            or self.web_searches > 0
        )


# ─────────────────────────────────────────────────────────────────
# Time-of-day greeting
# ─────────────────────────────────────────────────────────────────


def get_time_greeting(hour: Optional[int] = None) -> str:
    """Return a Turkish time-of-day greeting.

    Parameters
    ----------
    hour:
        Hour (0–23). If None, uses current time.
    """
    if hour is None:
        hour = datetime.datetime.now().hour

    if 5 <= hour < 12:
        return "Günaydın efendim."
    elif 12 <= hour < 18:
        return "İyi günler efendim."
    elif 18 <= hour < 22:
        return "İyi akşamlar efendim."
    else:
        return "İyi geceler efendim."


# ─────────────────────────────────────────────────────────────────
# File I/O for session summary
# ─────────────────────────────────────────────────────────────────


def get_last_session_summary(path: Optional[Path] = None) -> Optional[SessionSummary]:
    """Load last session summary from disk.

    Returns None if file doesn't exist or is corrupt.
    """
    p = path or SESSION_FILE
    if not p.is_file():
        logger.debug("No last session file at %s", p)
        return None

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        summary = SessionSummary.from_dict(data)
        if summary.has_activity:
            return summary
        return None
    except Exception as exc:
        logger.debug("Failed to load session summary: %s", exc)
        return None


def save_session_summary(summary: SessionSummary, path: Optional[Path] = None) -> bool:
    """Save session summary to disk.

    Returns True on success.
    """
    p = path or SESSION_FILE

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(summary.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.debug("Session summary saved to %s", p)
        return True
    except Exception as exc:
        logger.warning("Failed to save session summary: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────
# Main greeting builder
# ─────────────────────────────────────────────────────────────────


def build_greeting(
    config: Optional[GreetingConfig] = None,
    hour: Optional[int] = None,
    session_summary: Optional[SessionSummary] = None,
) -> str:
    """Build a personalized, PII-free boot greeting.

    Parameters
    ----------
    config:
        Greeting configuration.
    hour:
        Override hour for testing.
    session_summary:
        Override session summary (if None, loads from disk).

    Returns
    -------
    str
        Greeting text, max 300 chars, no PII.
    """
    cfg = config or GreetingConfig()
    greeting = get_time_greeting(hour)

    if cfg.include_session_summary:
        summary = session_summary
        if summary is None:
            summary = get_last_session_summary(cfg.session_file)

        if summary and summary.has_activity:
            summary_text = summary.to_turkish()
            if summary_text:
                # Ensure PII-free (use redaction as safety net)
                try:
                    from bantz.privacy.redaction import redact_pii
                    summary_text = redact_pii(summary_text)
                except ImportError:
                    pass  # Privacy module not available — summary is already safe by design

                candidate = f"{greeting} {summary_text}"
                if len(candidate) <= cfg.max_chars:
                    greeting = candidate

    # Final safety: truncate if somehow too long
    if len(greeting) > cfg.max_chars:
        greeting = greeting[: cfg.max_chars - 3] + "..."

    logger.debug("Boot greeting: %s", greeting)
    return greeting
