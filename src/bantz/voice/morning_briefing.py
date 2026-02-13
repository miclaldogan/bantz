"""Optional morning briefing — news + calendar + system status (Issue #304).

Disabled by default. When enabled, generates a morning briefing on first
boot after quiet hours:
- Calendar: event count only (no titles — privacy)
- News: cached summary reuse
- System: disk/memory status (optional)

Quiet hours (default 00:00–07:00) suppress the briefing.

Env vars::

    BANTZ_MORNING_BRIEFING=false          # Master toggle (default: off)
    BANTZ_BRIEFING_HOUR=08                # Earliest hour for briefing
    BANTZ_QUIET_HOURS_START=00:00
    BANTZ_QUIET_HOURS_END=07:00
    BANTZ_BRIEFING_INCLUDE_NEWS=true
    BANTZ_BRIEFING_INCLUDE_CALENDAR=true
    BANTZ_BRIEFING_INCLUDE_SYSTEM=false

Usage::

    from bantz.voice.morning_briefing import build_morning_briefing
    briefing = build_morning_briefing()
    if briefing:
        tts.speak(briefing)
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "BriefingConfig",
    "build_morning_briefing",
    "should_show_briefing",
    "get_calendar_summary",
    "get_news_summary",
    "get_system_summary",
    "is_quiet_hours",
]


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enable", "enabled"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_time(s: str) -> tuple[int, int]:
    """Parse 'HH:MM' to (hour, minute)."""
    parts = s.strip().split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


@dataclass
class BriefingConfig:
    """Morning briefing configuration.

    Attributes
    ----------
    enabled:
        Master toggle (default: False).
    briefing_hour:
        Earliest hour for briefing (0–23).
    quiet_start:
        Quiet hours start (hour, minute).
    quiet_end:
        Quiet hours end (hour, minute).
    include_news:
        Include news summary.
    include_calendar:
        Include calendar event count.
    include_system:
        Include system status.
    """

    enabled: bool = False
    briefing_hour: int = 8
    quiet_start: tuple[int, int] = (0, 0)
    quiet_end: tuple[int, int] = (7, 0)
    include_news: bool = True
    include_calendar: bool = True
    include_system: bool = False

    @classmethod
    def from_env(cls) -> "BriefingConfig":
        """Load config from environment variables."""
        qs = os.getenv("BANTZ_QUIET_HOURS_START", "00:00").strip()
        qe = os.getenv("BANTZ_QUIET_HOURS_END", "07:00").strip()

        return cls(
            enabled=_env_bool("BANTZ_MORNING_BRIEFING", False),
            briefing_hour=_env_int("BANTZ_BRIEFING_HOUR", 8),
            quiet_start=_parse_time(qs),
            quiet_end=_parse_time(qe),
            include_news=_env_bool("BANTZ_BRIEFING_INCLUDE_NEWS", True),
            include_calendar=_env_bool("BANTZ_BRIEFING_INCLUDE_CALENDAR", True),
            include_system=_env_bool("BANTZ_BRIEFING_INCLUDE_SYSTEM", False),
        )


# ─────────────────────────────────────────────────────────────────
# Quiet hours check
# ─────────────────────────────────────────────────────────────────


def is_quiet_hours(
    now: Optional[datetime.datetime] = None,
    config: Optional[BriefingConfig] = None,
) -> bool:
    """Check if current time is within quiet hours.

    During quiet hours, briefings are suppressed.
    """
    cfg = config or BriefingConfig()
    dt = now or datetime.datetime.now()
    current = (dt.hour, dt.minute)

    start = cfg.quiet_start
    end = cfg.quiet_end

    # Handle wrap-around (e.g., 23:00–06:00)
    if start <= end:
        return start <= current < end
    else:
        return current >= start or current < end


def should_show_briefing(
    now: Optional[datetime.datetime] = None,
    config: Optional[BriefingConfig] = None,
) -> bool:
    """Determine if a morning briefing should be shown.

    Conditions:
    1. Briefing is enabled.
    2. Not during quiet hours.
    3. Current hour >= briefing_hour.
    """
    cfg = config or BriefingConfig.from_env()
    dt = now or datetime.datetime.now()

    if not cfg.enabled:
        return False

    if is_quiet_hours(dt, cfg):
        return False

    if dt.hour < cfg.briefing_hour:
        return False

    return True


# ─────────────────────────────────────────────────────────────────
# Component summaries
# ─────────────────────────────────────────────────────────────────


def get_calendar_summary(
    events: Optional[List[dict]] = None,
) -> Optional[str]:
    """Generate a privacy-safe calendar summary.

    Only shows event count and first event time — never titles.

    Parameters
    ----------
    events:
        Pre-fetched events list. If None, returns a generic message.
    """
    if events is None:
        # No calendar data available
        return None

    count = len(events)

    if count == 0:
        return "Bugün takviminizde etkinlik yok."
    elif count == 1:
        first_time = _extract_time(events[0])
        if first_time:
            return f"Bugün 1 etkinliğiniz var, saat {first_time}'de."
        return "Bugün 1 etkinliğiniz var."
    else:
        first_time = _extract_time(events[0])
        if first_time:
            return f"Bugün {count} etkinliğiniz var, ilki saat {first_time}'de."
        return f"Bugün {count} etkinliğiniz var."


def _extract_time(event: dict) -> Optional[str]:
    """Extract start time from an event dict (HH:MM format)."""
    for key in ("start_time", "start", "time"):
        val = event.get(key)
        if val and isinstance(val, str):
            # Try to extract HH:MM
            if "T" in val:
                try:
                    dt = datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
                    return dt.strftime("%H:%M")
                except Exception:
                    pass
            if ":" in val and len(val) <= 8:
                return val[:5]  # HH:MM
    return None


def get_news_summary(cached_news: Optional[str] = None) -> Optional[str]:
    """Return a short news summary.

    Uses cached news if available. Does not make network calls.

    Parameters
    ----------
    cached_news:
        Pre-cached news summary text.
    """
    if cached_news:
        # Truncate to a reasonable length
        if len(cached_news) > 150:
            return cached_news[:147] + "..."
        return cached_news
    return None


def get_system_summary() -> Optional[str]:
    """Generate a brief system status summary.

    Includes disk usage and memory if available.
    """
    try:
        total, used, free = shutil.disk_usage("/")
        free_gb = free / (1024 ** 3)
        used_pct = (used / total) * 100

        if free_gb < 5:
            return f"⚠️ Disk alanı düşük: {free_gb:.1f} GB kaldı ({used_pct:.0f}% dolu)."
        return f"Sistem hazır, disk: {free_gb:.0f} GB boş."
    except Exception:
        return "Sistem hazır."


# ─────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────


def build_morning_briefing(
    config: Optional[BriefingConfig] = None,
    now: Optional[datetime.datetime] = None,
    calendar_events: Optional[List[dict]] = None,
    cached_news: Optional[str] = None,
) -> Optional[str]:
    """Build the morning briefing text.

    Returns None if briefing should not be shown (disabled, quiet hours, etc.).

    Parameters
    ----------
    config:
        Briefing configuration.
    now:
        Override current time (for testing).
    calendar_events:
        Pre-fetched calendar events.
    cached_news:
        Pre-cached news summary.
    """
    cfg = config or BriefingConfig.from_env()
    dt = now or datetime.datetime.now()

    if not should_show_briefing(dt, cfg):
        return None

    parts: List[str] = ["Günaydın efendim. Bugün için birkaç bilgi:"]

    if cfg.include_news:
        news = get_news_summary(cached_news)
        if news:
            parts.append(f"- {news}")

    if cfg.include_calendar:
        cal = get_calendar_summary(calendar_events)
        if cal:
            parts.append(f"- {cal}")

    if cfg.include_system:
        sys_status = get_system_summary()
        if sys_status:
            parts.append(f"- {sys_status}")

    # If only the header, don't show
    if len(parts) <= 1:
        return None

    parts.append("Daha fazla detay ister misiniz?")

    briefing = "\n".join(parts)
    logger.debug("Morning briefing: %s", briefing[:100])
    return briefing
