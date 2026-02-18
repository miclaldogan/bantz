"""Tests for briefing overlay IPC messages.

Covers:
- BriefingStartMessage
- BriefingCardMessage
- BriefingEndMessage
- BriefingDismissedEvent
- CATEGORY_DISPLAY metadata
- encode_briefing_message
- send_briefing_sequence
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.services.briefing_overlay import (
    BriefingCardMessage,
    BriefingEndMessage,
    BriefingStartMessage,
    BriefingDismissedEvent,
    CATEGORY_DISPLAY,
    encode_briefing_message,
    send_briefing_sequence,
)


# ─────────────────────────────────────────────────────────────────
# Message Construction
# ─────────────────────────────────────────────────────────────────


class TestBriefingStartMessage:
    def test_basic(self):
        msg = BriefingStartMessage(
            greeting="Günaydın efendim",
            time_context={"period": "morning"},
            total_cards=5,
        )
        assert msg.type == "briefing_start"
        assert msg.greeting == "Günaydın efendim"
        assert msg.total_cards == 5

    def test_to_dict(self):
        msg = BriefingStartMessage(
            greeting="Günaydın efendim",
            time_context={"period": "morning"},
            total_cards=3,
            days_away=5,
        )
        d = msg.to_dict()
        assert d["type"] == "briefing_start"
        assert d["greeting"] == "Günaydın efendim"
        assert d["days_away"] == 5
        assert d["total_cards"] == 3

    def test_default_days_away_is_zero(self):
        msg = BriefingStartMessage(
            greeting="Günaydın efendim",
            total_cards=0,
        )
        assert msg.days_away == 0

    def test_has_id_and_ts(self):
        msg = BriefingStartMessage(greeting="Test")
        assert msg.id  # non-empty
        assert msg.ts > 0


class TestBriefingCardMessage:
    def test_basic(self):
        msg = BriefingCardMessage(
            title="AI Breakthrough",
            summary="New AI model beats humans",
            source="TechCrunch",
            category="ai",
        )
        assert msg.type == "briefing_card"
        assert msg.title == "AI Breakthrough"
        assert msg.source == "TechCrunch"

    def test_with_image(self):
        msg = BriefingCardMessage(
            title="AI Breakthrough",
            summary="Summary",
            source="TC",
            category="ai",
            image_url="https://img.com/pic.jpg",
        )
        assert msg.image_url == "https://img.com/pic.jpg"

    def test_auto_fills_emoji_and_color(self):
        msg = BriefingCardMessage(
            title="News",
            summary="Summary",
            source="S",
            category="ai",
        )
        assert msg.category_emoji != ""
        assert msg.category_color != ""

    def test_custom_emoji_override(self):
        msg = BriefingCardMessage(
            title="News",
            summary="Summary",
            source="S",
            category="ai",
            category_emoji="🎯",
            category_color="#FF0000",
        )
        assert msg.category_emoji == "🎯"
        assert msg.category_color == "#FF0000"

    def test_to_dict(self):
        msg = BriefingCardMessage(
            title="News",
            summary="Summary",
            source="S",
            category="tech",
            duration_ms=5000,
        )
        d = msg.to_dict()
        assert d["title"] == "News"
        assert d["duration_ms"] == 5000
        assert d["type"] == "briefing_card"


class TestBriefingEndMessage:
    def test_basic(self):
        msg = BriefingEndMessage(
            summary="İşte bugünkü haberler efendim",
            total_shown=7,
        )
        assert msg.type == "briefing_end"
        assert msg.total_shown == 7

    def test_to_dict(self):
        msg = BriefingEndMessage(summary="Done", total_shown=3)
        d = msg.to_dict()
        assert d["total_shown"] == 3


class TestBriefingDismissedEvent:
    def test_basic(self):
        msg = BriefingDismissedEvent()
        assert msg.type == "briefing_dismissed"

    def test_to_dict(self):
        msg = BriefingDismissedEvent(cards_shown=4)
        d = msg.to_dict()
        assert d["type"] == "briefing_dismissed"
        assert d["cards_shown"] == 4


# ─────────────────────────────────────────────────────────────────
# Category Display
# ─────────────────────────────────────────────────────────────────


class TestCategoryDisplay:
    def test_known_categories_have_metadata(self):
        expected = {"ai", "tech", "world", "turkey", "science", "business"}
        for cat in expected:
            assert cat in CATEGORY_DISPLAY, f"{cat} missing from CATEGORY_DISPLAY"
            info = CATEGORY_DISPLAY[cat]
            assert "emoji" in info
            assert "label" in info
            assert "color" in info

    def test_emoji_not_empty(self):
        for cat, info in CATEGORY_DISPLAY.items():
            assert len(info["emoji"]) > 0, f"{cat} has empty emoji"

    def test_label_not_empty(self):
        for cat, info in CATEGORY_DISPLAY.items():
            assert len(info["label"]) > 0, f"{cat} has empty label"

    def test_color_is_hex(self):
        for cat, info in CATEGORY_DISPLAY.items():
            color = info["color"]
            assert color.startswith("#"), f"{cat} color not hex: {color}"
            assert len(color) == 7, f"{cat} color wrong length: {color}"


# ─────────────────────────────────────────────────────────────────
# Encoding
# ─────────────────────────────────────────────────────────────────


class TestEncodeBriefingMessage:
    def test_returns_bytes(self):
        msg = BriefingStartMessage(
            greeting="Günaydın efendim",
            total_cards=3,
        )
        encoded = encode_briefing_message(msg)
        assert isinstance(encoded, bytes)

    def test_jsonl_format(self):
        msg = BriefingStartMessage(
            greeting="Günaydın efendim",
            total_cards=3,
        )
        encoded = encode_briefing_message(msg)
        decoded = encoded.decode("utf-8")
        assert decoded.endswith("\n")
        parsed = json.loads(decoded.strip())
        assert parsed["type"] == "briefing_start"

    def test_card_roundtrip(self):
        msg = BriefingCardMessage(
            title="Breaking News",
            summary="Brief summary of the article",
            source="NTV",
            category="turkey",
            image_url="https://img.ntv.com/pic.jpg",
        )
        encoded = encode_briefing_message(msg)
        parsed = json.loads(encoded.decode("utf-8").strip())
        assert parsed["title"] == "Breaking News"
        assert parsed["image_url"] == "https://img.ntv.com/pic.jpg"

    def test_unicode_preserved(self):
        msg = BriefingEndMessage(
            summary="İyi akşamlar efendim, bugünkü haberler burada",
            total_shown=5,
        )
        encoded = encode_briefing_message(msg)
        parsed = json.loads(encoded.decode("utf-8").strip())
        assert "İyi akşamlar" in parsed["summary"]
        assert "efendim" in parsed["summary"]


# ─────────────────────────────────────────────────────────────────
# send_briefing_sequence
# ─────────────────────────────────────────────────────────────────


class TestSendBriefingSequence:
    @pytest.mark.asyncio
    async def test_sends_start_cards_end(self):
        """Sends start, cards, then end."""
        briefing_data = {
            "greeting": "Günaydın efendim",
            "time_context": {"period": "morning"},
            "days_away": 0,
            "news_cards": [
                {"title": "AI News", "category": "ai", "source": "TC",
                 "image_url": "https://img.com/ai.jpg", "url": "https://tc.com/ai"},
                {"title": "World News", "category": "world", "source": "BBC",
                 "url": "https://bbc.com/news"},
            ],
        }

        sent = []

        def capture(msg):
            sent.append(msg)

        count = await send_briefing_sequence(
            briefing_data,
            send_fn=capture,
            card_delay=0.0,
            greeting_delay=0.0,
        )

        assert count == 2
        assert sent[0]["type"] == "briefing_start"
        assert sent[0]["total_cards"] == 2

        cards = [m for m in sent if m["type"] == "briefing_card"]
        assert len(cards) == 2
        assert cards[0]["title"] == "AI News"

        assert sent[-1]["type"] == "briefing_end"
        assert sent[-1]["total_shown"] == 2

    @pytest.mark.asyncio
    async def test_empty_cards(self):
        briefing_data = {
            "greeting": "İyi akşamlar efendim",
            "time_context": {"period": "evening"},
            "days_away": 0,
            "news_cards": [],
        }

        sent = []

        def capture(msg):
            sent.append(msg)

        count = await send_briefing_sequence(
            briefing_data,
            send_fn=capture,
            card_delay=0.0,
            greeting_delay=0.0,
        )

        assert count == 0
        assert sent[0]["type"] == "briefing_start"
        assert sent[-1]["type"] == "briefing_end"

    @pytest.mark.asyncio
    async def test_days_away_passed_through(self):
        briefing_data = {
            "greeting": "Sizi tekrardan görmek güzel",
            "time_context": {"period": "morning"},
            "days_away": 5,
            "news_cards": [],
        }

        sent = []

        def capture(msg):
            sent.append(msg)

        await send_briefing_sequence(
            briefing_data,
            send_fn=capture,
            card_delay=0.0,
            greeting_delay=0.0,
        )

        assert sent[0]["days_away"] == 5
