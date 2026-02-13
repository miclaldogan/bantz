"""Tool-call narration for the voice pipeline (Issue #296).

When a tool call takes >instant-threshold, the user hears a short
Turkish narration *before* the tool executes, e.g.::

    "Haberleri kontrol ediyorum efendim..."

This eliminates dead air during long tool operations (news API,
Gmail fetch, calendar lookup) and signals that the system is working.

Usage::

    from bantz.voice.narration import get_narration, should_narrate

    phrase = get_narration("news.briefing")
    if phrase:
        tts.speak(phrase)   # play *before* tool.execute()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TOOL_NARRATIONS",
    "get_narration",
    "should_narrate",
    "NarrationConfig",
]


# ─────────────────────────────────────────────────────────────────
# Narration Map:  tool_name  →  Turkish phrase
# ─────────────────────────────────────────────────────────────────
# ``None`` → instant tool, no narration needed.

TOOL_NARRATIONS: Dict[str, Optional[str]] = {
    # ── News ─────────────────────────────────────────────────────
    "news.briefing": "Haberleri kontrol ediyorum efendim...",
    "news.search": "Haberlerde arıyorum efendim...",
    # ── Calendar ─────────────────────────────────────────────────
    "calendar.list_events": "Takviminize bakıyorum efendim...",
    "calendar.create_event": "Etkinliği oluşturuyorum efendim...",
    "calendar.update_event": "Etkinliği güncelliyorum efendim...",
    "calendar.delete_event": "Etkinliği siliyorum efendim...",
    "calendar.free_slots": "Müsait zamanlarınıza bakıyorum efendim...",
    # ── Gmail ────────────────────────────────────────────────────
    "gmail.list_messages": "Maillerinizi kontrol ediyorum efendim...",
    "gmail.read_message": "Maili okuyorum efendim...",
    "gmail.send_message": "Maili gönderiyorum efendim...",
    # ── Contacts ─────────────────────────────────────────────────
    "contacts.search": "Kişilerinize bakıyorum efendim...",
    # ── System ───────────────────────────────────────────────────
    "system.health_check": "Sistem durumunu kontrol ediyorum efendim...",
    "system.disk_usage": "Disk kullanımına bakıyorum efendim...",
    "system.memory_usage": "Bellek durumuna bakıyorum efendim...",
    # ── Web ──────────────────────────────────────────────────────
    "web.search": "İnternette arıyorum efendim...",
    "web.open": None,  # instant redirect, no narration
    # ── Time (instant) ───────────────────────────────────────────
    "time.now": None,
    "time.timezone": None,
}

# Generic fallback for unregistered tools
_GENERIC_NARRATION = "Bir bakayım efendim..."


@dataclass(frozen=True)
class NarrationConfig:
    """Narration behaviour tuning.

    Attributes:
        enabled: Master switch (can be disabled for tests or headless mode).
        generic_fallback: If True, unknown tools get a generic narration.
        debug: If True, log narration decisions.
    """

    enabled: bool = True
    generic_fallback: bool = True
    debug: bool = False


def get_narration(
    tool_name: str,
    *,
    config: Optional[NarrationConfig] = None,
) -> Optional[str]:
    """Return the narration phrase for a tool, or ``None`` if silent.

    Lookup order:
      1. Exact match in ``TOOL_NARRATIONS``.
      2. Prefix match (``calendar.*`` → first ``calendar.`` entry).
      3. Generic fallback if ``config.generic_fallback`` is True.
      4. ``None`` (no narration).

    A stored value of ``None`` in the map means "this tool is instant,
    never narrate" — that takes priority over the generic fallback.
    """
    cfg = config or NarrationConfig()
    if not cfg.enabled:
        return None

    # 1. Exact match
    if tool_name in TOOL_NARRATIONS:
        phrase = TOOL_NARRATIONS[tool_name]
        if cfg.debug:
            logger.debug("narration[%s] exact → %s", tool_name, phrase)
        return phrase  # may be None (instant tool)

    # 2. Prefix match  (e.g. "calendar.some_new_tool" → match "calendar.*")
    prefix = tool_name.split(".")[0] + "." if "." in tool_name else None
    if prefix:
        for key, phrase in TOOL_NARRATIONS.items():
            if key.startswith(prefix) and phrase is not None:
                if cfg.debug:
                    logger.debug("narration[%s] prefix(%s) → %s", tool_name, key, phrase)
                return phrase

    # 3. Generic fallback
    if cfg.generic_fallback:
        if cfg.debug:
            logger.debug("narration[%s] generic → %s", tool_name, _GENERIC_NARRATION)
        return _GENERIC_NARRATION

    return None


def should_narrate(tool_name: str, *, config: Optional[NarrationConfig] = None) -> bool:
    """Quick predicate: does this tool warrant a narration?"""
    return get_narration(tool_name, config=config) is not None
