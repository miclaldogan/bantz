"""Briefing Overlay UI — IPC message types and rendering hints for the startup briefing.

Extends the base IPC protocol with briefing-specific message types
that the overlay renderer uses to show:

1. A full-screen briefing card with greeting
2. News image popups that fade in/out as articles are read
3. Category badges (AI 🤖, Tech 💻, World 🌍, etc.)
4. A conversation input at the bottom

IPC Message Flow::

    daemon → overlay:
        BriefingStartMessage    → show briefing overlay
        BriefingCardMessage     → show a news card with image
        BriefingEndMessage      → fade out briefing, show chat input

    overlay → daemon:
        BriefingDismissedEvent  → user clicked away / closed

Message Format (JSONL over Unix socket)::

    {"type":"briefing_start","greeting":"...","time_context":{...}}
    {"type":"briefing_card","title":"...","image_url":"...","category":"ai"}
    {"type":"briefing_end"}

Usage::

    from bantz.services.briefing_overlay import (
        BriefingStartMessage, BriefingCardMessage, BriefingEndMessage,
        send_briefing_sequence,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "BriefingStartMessage",
    "BriefingCardMessage",
    "BriefingEndMessage",
    "BriefingDismissedEvent",
    "send_briefing_sequence",
    "encode_briefing_message",
]


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_ms() -> int:
    return int(time.time() * 1000)


# Category display metadata
CATEGORY_DISPLAY: Dict[str, Dict[str, str]] = {
    "ai": {"emoji": "🤖", "label": "AI", "color": "#8B5CF6"},
    "tech": {"emoji": "💻", "label": "Tech", "color": "#3B82F6"},
    "world": {"emoji": "🌍", "label": "World", "color": "#10B981"},
    "turkey": {"emoji": "🇹🇷", "label": "Turkey", "color": "#EF4444"},
    "science": {"emoji": "🔬", "label": "Science", "color": "#F59E0B"},
    "business": {"emoji": "📈", "label": "Business", "color": "#6366F1"},
}


@dataclass
class BriefingStartMessage:
    """Signals the overlay to show the briefing screen.

    The overlay should:
    - Dim the desktop background
    - Show a centered panel with the greeting
    - Show time context (day, time, weather icon)
    - Prepare for incoming news cards
    """

    type: str = "briefing_start"
    id: str = field(default_factory=_generate_id)
    ts: int = field(default_factory=_now_ms)
    greeting: str = ""
    time_context: Dict[str, Any] = field(default_factory=dict)
    total_cards: int = 0
    days_away: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "ts": self.ts,
            "greeting": self.greeting,
            "time_context": self.time_context,
            "total_cards": self.total_cards,
            "days_away": self.days_away,
        }


@dataclass
class BriefingCardMessage:
    """A single news card to display in the briefing overlay.

    The overlay should:
    - Pop in the card with a fade/slide animation
    - Show the article image (full-width) if available
    - Show title, source, category badge
    - Auto-advance after duration_ms
    """

    type: str = "briefing_card"
    id: str = field(default_factory=_generate_id)
    ts: int = field(default_factory=_now_ms)
    index: int = 0
    total: int = 0
    title: str = ""
    summary: str = ""
    source: str = ""
    category: str = ""
    image_url: Optional[str] = None
    url: str = ""
    duration_ms: int = 4500
    category_emoji: str = ""
    category_color: str = ""

    def __post_init__(self):
        cat_meta = CATEGORY_DISPLAY.get(self.category, {})
        if not self.category_emoji:
            self.category_emoji = cat_meta.get("emoji", "📰")
        if not self.category_color:
            self.category_color = cat_meta.get("color", "#6B7280")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "ts": self.ts,
            "index": self.index,
            "total": self.total,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "category": self.category,
            "image_url": self.image_url,
            "url": self.url,
            "duration_ms": self.duration_ms,
            "category_emoji": self.category_emoji,
            "category_color": self.category_color,
        }


@dataclass
class BriefingEndMessage:
    """Signals the overlay to end the briefing and transition to chat.

    The overlay should:
    - Fade out news cards
    - Fade out the greeting panel
    - Show the conversation input at the bottom
    - Transition to normal idle/listening state
    """

    type: str = "briefing_end"
    id: str = field(default_factory=_generate_id)
    ts: int = field(default_factory=_now_ms)
    summary: str = ""
    total_shown: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "ts": self.ts,
            "summary": self.summary,
            "total_shown": self.total_shown,
        }


@dataclass
class BriefingDismissedEvent:
    """Overlay → Daemon: User dismissed the briefing early."""

    type: str = "briefing_dismissed"
    id: str = field(default_factory=_generate_id)
    ts: int = field(default_factory=_now_ms)
    cards_shown: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "ts": self.ts,
            "cards_shown": self.cards_shown,
        }


def encode_briefing_message(msg) -> bytes:
    """Encode a briefing message to JSONL bytes."""
    data = msg.to_dict()
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (json_str + "\n").encode("utf-8")


async def send_briefing_sequence(
    briefing_data: Dict[str, Any],
    send_fn,
    *,
    card_delay: float = 4.5,
    greeting_delay: float = 2.5,
) -> int:
    """Send the complete briefing IPC sequence.

    Parameters
    ----------
    briefing_data:
        The DailyBriefing.to_dict() output.
    send_fn:
        Callable that sends a message dict to the overlay.
        Signature: send_fn(msg_dict) → None
    card_delay:
        Seconds between news cards (default: 4.5).
    greeting_delay:
        Seconds to show greeting before news (default: 2.5).

    Returns
    -------
    Number of cards shown.
    """
    news_cards = briefing_data.get("news_cards", [])

    async def _call_send(msg_dict):
        """Call send_fn — supports both sync and async callables."""
        import inspect
        result = send_fn(msg_dict)
        if inspect.isawaitable(result):
            await result

    # 1. Send briefing start
    start_msg = BriefingStartMessage(
        greeting=briefing_data.get("greeting", ""),
        time_context=briefing_data.get("time_context", {}),
        total_cards=len(news_cards),
        days_away=briefing_data.get("days_away", 0),
    )
    await _call_send(start_msg.to_dict())
    await asyncio.sleep(greeting_delay)

    # 2. Send news cards one by one
    cards_shown = 0
    for i, card in enumerate(news_cards):
        card_msg = BriefingCardMessage(
            index=i,
            total=len(news_cards),
            title=card.get("title", ""),
            summary=card.get("summary", ""),
            source=card.get("source", ""),
            category=card.get("category", ""),
            image_url=card.get("image_url"),
            url=card.get("url", ""),
        )
        await _call_send(card_msg.to_dict())
        cards_shown += 1
        await asyncio.sleep(card_delay)

    # 3. Send briefing end
    end_msg = BriefingEndMessage(
        total_shown=cards_shown,
    )
    await _call_send(end_msg.to_dict())

    logger.info("[briefing_overlay] sequence complete: %d cards shown", cards_shown)
    return cards_shown
