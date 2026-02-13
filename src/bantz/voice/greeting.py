"""Boot greeting + immediate active listen (Issue #292).

Boot'ta kullanıcıyı karşıla, TTS ile selam ver, hemen ACTIVE_LISTEN geç.

Config env vars::

    BANTZ_BOOT_GREETING=true
    BANTZ_QUIET_HOURS_START=00:00
    BANTZ_QUIET_HOURS_END=07:00
    BANTZ_GREETING_TEXT=Sizi tekrardan görmek güzel efendim.

Behaviour:
    1. LLM warmup complete
    2. TTS: greeting text (fallback: print)
    3. FSM → ACTIVE_LISTEN
    4. User can speak immediately (no wake word)

Greeting once-per-boot guaranteed via ``_greeted`` flag.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "GreetingConfig",
    "boot_greeting",
    "is_quiet_hours",
    "pick_greeting",
]


# ── Configuration ─────────────────────────────────────────────

@dataclass
class GreetingConfig:
    """Boot greeting configuration."""

    enabled: bool = True
    quiet_hours_start: str = "00:00"  # HH:MM
    quiet_hours_end: str = "07:00"    # HH:MM
    greeting_text: str = "Sizi tekrardan görmek güzel efendim."
    morning_text: str = "Günaydın efendim, size nasıl yardımcı olabilirim?"
    evening_text: str = "İyi akşamlar efendim."

    @classmethod
    def from_env(cls) -> "GreetingConfig":
        """Load config from environment variables."""
        enabled = os.getenv("BANTZ_BOOT_GREETING", "true").strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            enabled=enabled,
            quiet_hours_start=os.getenv("BANTZ_QUIET_HOURS_START", "00:00").strip(),
            quiet_hours_end=os.getenv("BANTZ_QUIET_HOURS_END", "07:00").strip(),
            greeting_text=os.getenv("BANTZ_GREETING_TEXT", cls.greeting_text),
            morning_text=os.getenv("BANTZ_MORNING_TEXT", cls.morning_text),
            evening_text=os.getenv("BANTZ_EVENING_TEXT", cls.evening_text),
        )


# ── Quiet hours ───────────────────────────────────────────────

def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse ``"HH:MM"`` to ``(hour, minute)``."""
    parts = value.strip().split(":")
    return int(parts[0]), int(parts[1])


def is_quiet_hours(
    config: Optional[GreetingConfig] = None,
    now: Optional[datetime.datetime] = None,
) -> bool:
    """Check if current time is within quiet hours.

    Parameters
    ----------
    config:
        Greeting config. Defaults to GreetingConfig().
    now:
        Override current time for testing.
    """
    config = config or GreetingConfig()
    now = now or datetime.datetime.now()

    start_h, start_m = _parse_hhmm(config.quiet_hours_start)
    end_h, end_m = _parse_hhmm(config.quiet_hours_end)

    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    if start <= end:
        # Same-day range (e.g. 00:00–07:00)
        return start <= now < end
    else:
        # Cross-midnight range (e.g. 23:00–06:00)
        return now >= start or now < end


# ── Greeting selection ────────────────────────────────────────

def pick_greeting(
    config: Optional[GreetingConfig] = None,
    now: Optional[datetime.datetime] = None,
) -> str:
    """Pick the best greeting based on time of day.

    Parameters
    ----------
    config:
        Greeting config.
    now:
        Override current time for testing.
    """
    config = config or GreetingConfig()
    now = now or datetime.datetime.now()
    hour = now.hour

    if 5 <= hour < 12:
        return config.morning_text
    elif 18 <= hour < 24:
        return config.evening_text
    else:
        return config.greeting_text


# ── Boot greeting flow ────────────────────────────────────────

_greeted = False


def reset_greeted() -> None:
    """Reset greeting flag (for testing)."""
    global _greeted
    _greeted = False


async def boot_greeting(
    config: Optional[GreetingConfig] = None,
    tts_speak: Optional[Callable] = None,
    fsm_activate: Optional[Callable] = None,
    now: Optional[datetime.datetime] = None,
) -> dict:
    """Run boot greeting flow.

    Parameters
    ----------
    config:
        Greeting config. Uses from_env() if None.
    tts_speak:
        Async callable to speak text. Falls back to print.
    fsm_activate:
        Callable to enter ACTIVE_LISTEN (e.g. ``fsm.on_boot_ready``).
    now:
        Override current time for testing.

    Returns
    -------
    dict with keys:
        - greeted (bool): whether greeting was spoken/printed
        - reason (str): why greeting was skipped (if applicable)
        - text (str): greeting text used
        - method (str): "tts" | "print" | "skipped"
    """
    global _greeted

    config = config or GreetingConfig.from_env()

    result = {"greeted": False, "reason": "", "text": "", "method": "skipped"}

    # Once-per-boot guarantee
    if _greeted:
        result["reason"] = "already_greeted"
        logger.debug("[greeting] already greeted this boot — skipping")
        return result

    # Disabled?
    if not config.enabled:
        result["reason"] = "disabled"
        logger.info("[greeting] boot greeting disabled")
        _greeted = True
        return result

    # Quiet hours?
    if is_quiet_hours(config, now):
        result["reason"] = "quiet_hours"
        logger.info("[greeting] quiet hours — skipping greeting")
        _greeted = True
        return result

    # Pick greeting
    text = pick_greeting(config, now)
    result["text"] = text

    # Speak or fallback print
    if tts_speak is not None:
        try:
            if asyncio.iscoroutinefunction(tts_speak):
                await tts_speak(text)
            else:
                tts_speak(text)
            result["method"] = "tts"
            logger.info("[greeting] TTS: %s", text)
        except Exception:
            logger.warning("[greeting] TTS failed — falling back to print")
            print(f"[BANTZ] {text}")
            result["method"] = "print"
    else:
        print(f"[BANTZ] {text}")
        result["method"] = "print"
        logger.info("[greeting] print fallback: %s", text)

    result["greeted"] = True
    _greeted = True

    # Activate FSM
    if fsm_activate is not None:
        try:
            fsm_activate()
            logger.debug("[greeting] FSM activated to ACTIVE_LISTEN")
        except Exception:
            logger.exception("[greeting] FSM activation failed")

    return result
