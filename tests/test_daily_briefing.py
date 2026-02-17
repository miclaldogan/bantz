"""Tests for DailyBriefingService — startup intelligence digest.

Covers:
- Greeting with time-of-day awareness
- Absence detection (same day, 3+ days, weeks)
- News section generation
- Calendar section generation
- Email section generation
- Composite spoken text
- Last-seen persistence (read/write)
- Event bus publishing
- LLM summarization (with and without)
- Edge cases (no news, no calendar, disabled sections)
"""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.services.daily_briefing import (
    BriefingSection,
    CalendarBriefingSection,
    DailyBriefing,
    DailyBriefingConfig,
    DailyBriefingService,
    EmailBriefingSection,
    NewsBriefingSection,
    _build_news_spoken_text,
    _build_news_summary_prompt,
    _read_last_seen,
    _write_last_seen,
)
from bantz.services.news_service import (
    NewsArticle,
    NewsBriefingResult,
)


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def config(tmp_path):
    return DailyBriefingConfig(
        enabled=True,
        include_news=True,
        include_calendar=True,
        include_email=True,
        max_news_items=3,
        summarize_news=False,  # no LLM in unit tests
        last_seen_file=str(tmp_path / "last_seen.txt"),
    )


@pytest.fixture
def mock_news_service():
    svc = AsyncMock()
    svc.fetch_all.return_value = NewsBriefingResult(
        articles=[
            NewsArticle(
                title="AI Breakthrough",
                summary="Major advance in AI.",
                source="TechCrunch",
                image_url="https://img.com/ai.jpg",
                category="ai",
                url="https://example.com/ai",
            ),
            NewsArticle(
                title="New Chip Released",
                summary="Faster processing.",
                source="The Verge",
                image_url="https://img.com/chip.jpg",
                category="tech",
                url="https://example.com/chip",
            ),
        ],
        categories_fetched=["ai", "tech"],
        fetch_time=1.5,
    )
    return svc


@pytest.fixture
def morning_clock():
    """Clock fixed at 2026-02-17 09:00 (Tuesday morning)."""
    return lambda: datetime.datetime(2026, 2, 17, 9, 0)


@pytest.fixture
def evening_clock():
    """Clock fixed at 2026-02-17 20:00 (Tuesday evening)."""
    return lambda: datetime.datetime(2026, 2, 17, 20, 0)


# ─────────────────────────────────────────────────────────────────
# Last-Seen Persistence
# ─────────────────────────────────────────────────────────────────


class TestLastSeen:
    def test_write_and_read(self, tmp_path):
        path = str(tmp_path / "last_seen.txt")
        dt = datetime.datetime(2026, 2, 17, 9, 0)
        _write_last_seen(path, dt)
        result = _read_last_seen(path)
        assert result is not None
        assert result.date() == dt.date()

    def test_read_nonexistent(self, tmp_path):
        path = str(tmp_path / "nonexistent.txt")
        assert _read_last_seen(path) is None

    def test_read_empty_file(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("")
        assert _read_last_seen(str(path)) is None

    def test_read_invalid_content(self, tmp_path):
        path = tmp_path / "bad.txt"
        path.write_text("not-a-date")
        assert _read_last_seen(str(path)) is None

    def test_write_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "last_seen.txt")
        _write_last_seen(path)
        assert _read_last_seen(path) is not None


# ─────────────────────────────────────────────────────────────────
# News Spoken Text
# ─────────────────────────────────────────────────────────────────


class TestNewSpokenText:
    def test_empty_articles(self):
        text = _build_news_spoken_text([])
        assert "bulamadım" in text

    def test_with_articles(self):
        articles = [
            {"title": "AI News", "source": "TC", "category": "ai"},
            {"title": "Tech News", "source": "TV", "category": "tech"},
        ]
        text = _build_news_spoken_text(articles)
        assert "AI News" in text
        assert "Tech News" in text
        assert "Birincisi" in text
        assert "İkincisi" in text

    def test_source_in_parentheses(self):
        articles = [{"title": "Test", "source": "BBC", "category": "world"}]
        text = _build_news_spoken_text(articles)
        assert "(BBC)" in text


class TestNewsSummaryPrompt:
    def test_prompt_format(self):
        articles = [
            {"title": "Headline 1", "summary": "Detail 1", "category": "ai"},
        ]
        prompt = _build_news_summary_prompt(articles)
        assert "Headline 1" in prompt
        assert "efendim" in prompt
        assert "Briefing:" in prompt


# ─────────────────────────────────────────────────────────────────
# DailyBriefing Dataclass
# ─────────────────────────────────────────────────────────────────


class TestDailyBriefing:
    def test_to_dict(self):
        b = DailyBriefing(
            greeting="Hello",
            spoken_text="Hello there",
            days_away=3,
            generated_at="2026-02-17T09:00:00",
        )
        d = b.to_dict()
        assert d["greeting"] == "Hello"
        assert d["days_away"] == 3
        assert d["generated_at"] == "2026-02-17T09:00:00"


# ─────────────────────────────────────────────────────────────────
# BriefingSection Variants
# ─────────────────────────────────────────────────────────────────


class TestSections:
    def test_news_section_to_dict(self):
        s = NewsBriefingSection(
            spoken_text="Here are the news.",
            news_cards=[{"title": "A", "image_url": "https://img.com/a.jpg"}],
        )
        d = s.to_dict()
        assert d["type"] == "news"
        assert len(d["news_cards"]) == 1
        assert d["news_cards"][0]["image_url"] == "https://img.com/a.jpg"

    def test_calendar_section(self):
        s = CalendarBriefingSection(
            spoken_text="2 events today.",
            event_count=2,
        )
        d = s.to_dict()
        assert d["type"] == "calendar"

    def test_email_section(self):
        s = EmailBriefingSection(
            spoken_text="5 unread emails.",
            unread_count=5,
            important_count=1,
        )
        d = s.to_dict()
        assert d["type"] == "email"


# ─────────────────────────────────────────────────────────────────
# DailyBriefingService
# ─────────────────────────────────────────────────────────────────


class TestDailyBriefingService:
    @pytest.mark.asyncio
    async def test_generate_morning_briefing(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate()

        assert "Günaydın" in briefing.greeting
        assert briefing.time_context["period"] == "morning"
        assert len(briefing.sections) > 0  # at least news
        assert len(briefing.news_cards) > 0
        assert briefing.spoken_text  # not empty
        assert briefing.generated_at

    @pytest.mark.asyncio
    async def test_generate_evening_briefing(
        self, config, mock_news_service, evening_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=evening_clock,
        )
        briefing = await svc.generate()
        assert "akşam" in briefing.greeting

    @pytest.mark.asyncio
    async def test_absence_detection_3_days(
        self, config, mock_news_service, morning_clock, tmp_path
    ):
        # Write a last_seen 4 days ago
        last_seen = datetime.datetime(2026, 2, 13, 15, 0)
        _write_last_seen(config.last_seen_file, last_seen)

        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate()
        assert briefing.days_away == 4
        assert "tekrardan" in briefing.greeting.lower()

    @pytest.mark.asyncio
    async def test_absence_first_time(
        self, config, mock_news_service, morning_clock
    ):
        # No last_seen file exists
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate()
        assert briefing.days_away == -1
        assert "memnun" in briefing.greeting.lower()

    @pytest.mark.asyncio
    async def test_news_cards_have_images(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate()
        for card in briefing.news_cards:
            assert "image_url" in card
            # At least some should have images
        has_images = [c for c in briefing.news_cards if c["image_url"]]
        assert len(has_images) > 0

    @pytest.mark.asyncio
    async def test_calendar_section(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        events = [
            {"title": "Standup", "start_time": "2026-02-17T10:00:00"},
            {"title": "Lunch", "start_time": "2026-02-17T12:00:00"},
        ]
        briefing = await svc.generate(calendar_events=events)

        cal_sections = [s for s in briefing.sections if s.section_type == "calendar"]
        assert len(cal_sections) == 1
        assert cal_sections[0].event_count == 2
        assert "2 etkinliğiniz" in cal_sections[0].spoken_text

    @pytest.mark.asyncio
    async def test_email_section(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate(
            unread_emails=12,
            important_emails=3,
        )

        email_sections = [s for s in briefing.sections if s.section_type == "email"]
        assert len(email_sections) == 1
        assert "12 okunmamış" in email_sections[0].spoken_text
        assert "3 önemli" in email_sections[0].spoken_text

    @pytest.mark.asyncio
    async def test_no_email_when_zero(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate(
            unread_emails=0,
            important_emails=0,
        )
        email_sections = [s for s in briefing.sections if s.section_type == "email"]
        assert len(email_sections) == 0

    @pytest.mark.asyncio
    async def test_no_calendar_when_none(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate(calendar_events=None)
        cal_sections = [s for s in briefing.sections if s.section_type == "calendar"]
        assert len(cal_sections) == 0

    @pytest.mark.asyncio
    async def test_empty_calendar(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate(calendar_events=[])
        cal_sections = [s for s in briefing.sections if s.section_type == "calendar"]
        assert len(cal_sections) == 0

    @pytest.mark.asyncio
    async def test_news_disabled(
        self, config, mock_news_service, morning_clock
    ):
        config.include_news = False
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        briefing = await svc.generate()
        news_sections = [s for s in briefing.sections if s.section_type == "news"]
        assert len(news_sections) == 0
        assert len(briefing.news_cards) == 0

    @pytest.mark.asyncio
    async def test_event_bus_publish(
        self, config, mock_news_service, morning_clock
    ):
        bus = MagicMock()
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
            event_bus=bus,
        )
        await svc.generate()
        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "briefing.ready"

    @pytest.mark.asyncio
    async def test_with_summarizer(
        self, config, mock_news_service, morning_clock
    ):
        config.summarize_news = True

        def mock_summarizer(prompt: str) -> str:
            return "Efendim, bugün yapay zeka dünyasında önemli gelişmeler var."

        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            summarizer=mock_summarizer,
            clock=morning_clock,
        )
        briefing = await svc.generate()
        news_sections = [s for s in briefing.sections if s.section_type == "news"]
        assert len(news_sections) == 1
        assert "yapay zeka" in news_sections[0].spoken_text

    @pytest.mark.asyncio
    async def test_last_briefing_property(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        assert svc.last_briefing is None
        await svc.generate()
        assert svc.last_briefing is not None

    @pytest.mark.asyncio
    async def test_updates_last_seen(
        self, config, mock_news_service, morning_clock
    ):
        svc = DailyBriefingService(
            config=config,
            news_service=mock_news_service,
            clock=morning_clock,
        )
        await svc.generate()
        last_seen = _read_last_seen(config.last_seen_file)
        assert last_seen is not None
        assert last_seen.date() == datetime.date(2026, 2, 17)


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


class TestBriefingConfig:
    def test_defaults(self):
        cfg = DailyBriefingConfig()
        assert cfg.enabled is True
        assert cfg.include_news is True
        assert cfg.max_news_items == 3

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("BANTZ_BRIEFING_ENABLED", "false")
        monkeypatch.setenv("BANTZ_BRIEFING_NEWS", "false")
        monkeypatch.setenv("BANTZ_BRIEFING_MAX_NEWS", "5")
        cfg = DailyBriefingConfig.from_env()
        assert cfg.enabled is False
        assert cfg.include_news is False
        assert cfg.max_news_items == 5
