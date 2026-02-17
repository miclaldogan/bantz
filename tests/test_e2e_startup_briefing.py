"""End-to-end startup briefing scenario tests.

Simulates the real computer boot-up flow:
    1. Bantz daemon starts
    2. Absence is detected (first time / same day / 3+ days)
    3. News is fetched from multiple sources
    4. Calendar and email data is gathered
    5. Briefing is generated with correct greeting
    6. Overlay UI receives IPC messages (start → cards with images → end)
    7. TTS speaks the briefing
    8. EventBus publishes completion
    9. System transitions to idle

Tests cover:
    - Morning boot (first install)
    - Morning boot (daily user)
    - Boot after 5-day absence
    - Boot after 2-week absence
    - Evening boot
    - Late night boot
    - Boot with no internet (news fails gracefully)
    - Boot with calendar + emails
    - Full IPC message sequence verification
    - News image popup flow
"""

from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.services.daily_briefing import (
    DailyBriefing,
    DailyBriefingConfig,
    DailyBriefingService,
)
from bantz.services.time_context import TimeContext, DayPeriod
from bantz.services.news_service import NewsArticle, NewsBriefingResult
from bantz.services.briefing_overlay import (
    BriefingStartMessage,
    BriefingCardMessage,
    BriefingEndMessage,
    encode_briefing_message,
    send_briefing_sequence,
    CATEGORY_DISPLAY,
)
from bantz.services.startup_hook import StartupBriefingRunner


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


SAMPLE_ARTICLES = [
    NewsArticle(
        title="GPT-5 Released with Breakthrough Reasoning",
        summary="OpenAI announced GPT-5 with significant improvements in multi-step reasoning.",
        category="ai",
        source="TechCrunch",
        image_url="https://techcrunch.com/wp-content/uploads/gpt5.jpg",
        url="https://techcrunch.com/2026/02/17/gpt5-released",
    ),
    NewsArticle(
        title="Linux 7.0 Kernel Released",
        summary="The Linux kernel 7.0 brings major performance improvements.",
        category="tech",
        source="The Verge",
        image_url="https://cdn.vox-cdn.com/linux7.jpg",
        url="https://theverge.com/2026/02/17/linux-7",
    ),
    NewsArticle(
        title="Earthquake in Eastern Turkey",
        summary="A 5.2 magnitude earthquake struck eastern Turkey early this morning.",
        category="turkey",
        source="NTV",
        image_url="https://ntv.com.tr/images/quake.jpg",
        url="https://ntv.com.tr/turkiye/deprem",
    ),
    NewsArticle(
        title="SpaceX Mars Mission Update",
        summary="SpaceX announced new timeline for Mars crewed mission.",
        category="science",
        source="BBC",
        url="https://bbc.com/news/science/spacex",
    ),
    NewsArticle(
        title="Markets Rally on AI Optimism",
        summary="Global markets rose 2% on AI sector growth expectations.",
        category="business",
        source="Bloomberg",
        image_url="https://img.bloomberg.com/markets.jpg",
        url="https://bloomberg.com/markets/rally",
    ),
]

SAMPLE_CALENDAR = [
    {
        "title": "Team Standup",
        "start": "2026-02-17T09:30:00",
        "end": "2026-02-17T09:45:00",
    },
    {
        "title": "1:1 with Manager",
        "start": "2026-02-17T14:00:00",
        "end": "2026-02-17T14:30:00",
    },
    {
        "title": "Sprint Review",
        "start": "2026-02-17T16:00:00",
        "end": "2026-02-17T17:00:00",
    },
]


def _mock_news_service(articles=None):
    """Create a mock NewsService returning sample articles."""
    arts = articles or SAMPLE_ARTICLES
    svc = AsyncMock()
    svc.fetch_all = AsyncMock(return_value=NewsBriefingResult(
        articles=arts,
        categories_fetched=list({a.category for a in arts}),
        fetch_time=0.35,
    ))
    svc.get_latest = AsyncMock(return_value=arts)
    svc.search = AsyncMock(return_value=arts[:2])
    return svc


def _mock_news_service_offline():
    """Create a mock that simulates network failure."""
    svc = AsyncMock()
    svc.fetch_all = AsyncMock(side_effect=ConnectionError("Network unreachable"))
    svc.get_latest = AsyncMock(side_effect=ConnectionError("Network unreachable"))
    return svc


def _make_service(
    *,
    clock_time: datetime.datetime,
    last_seen: datetime.datetime | None = "yesterday",
    news_service=None,
    summarizer=None,
    event_bus=None,
    tmp_path: Path,
    include_news: bool = True,
):
    """Create a DailyBriefingService with injectable clock and last_seen."""
    last_seen_file = str(tmp_path / "last_seen.txt")

    if last_seen == "yesterday":
        # Default: user was here yesterday
        yesterday = clock_time - datetime.timedelta(days=1)
        Path(last_seen_file).parent.mkdir(parents=True, exist_ok=True)
        Path(last_seen_file).write_text(yesterday.isoformat())
    elif last_seen is not None:
        Path(last_seen_file).parent.mkdir(parents=True, exist_ok=True)
        Path(last_seen_file).write_text(last_seen.isoformat())
    # else: no file → first time

    config = DailyBriefingConfig(
        enabled=True,
        include_news=include_news,
        include_calendar=True,
        include_email=True,
        max_news_items=3,
        summarize_news=bool(summarizer),
        last_seen_file=last_seen_file,
    )

    return DailyBriefingService(
        config=config,
        news_service=news_service or _mock_news_service(),
        summarizer=summarizer,
        event_bus=event_bus,
        clock=lambda: clock_time,
    )


# ═════════════════════════════════════════════════════════════════
# SCENARIO 1: First-time morning boot (fresh install)
# ═════════════════════════════════════════════════════════════════


class TestFirstInstallMorningBoot:
    """User just installed Bantz and boots up at 08:30 on a Tuesday."""

    @pytest.mark.asyncio
    async def test_greeting_is_first_time(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 8, 30)
        svc = _make_service(
            clock_time=morning,
            last_seen=None,  # No file → first install
            tmp_path=tmp_path,
        )

        briefing = await svc.generate(
            calendar_events=SAMPLE_CALENDAR,
            unread_emails=5,
            important_emails=1,
        )

        assert "memnun" in briefing.greeting.lower()
        assert briefing.days_away == -1

    @pytest.mark.asyncio
    async def test_news_cards_have_images(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 8, 30)
        svc = _make_service(clock_time=morning, last_seen=None, tmp_path=tmp_path)

        briefing = await svc.generate()

        cards_with_images = [c for c in briefing.news_cards if c.get("image_url")]
        assert len(cards_with_images) >= 2, "Most cards should have images"

    @pytest.mark.asyncio
    async def test_full_spoken_text_structure(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 8, 30)
        svc = _make_service(
            clock_time=morning,
            last_seen=None,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate(
            calendar_events=SAMPLE_CALENDAR,
            unread_emails=12,
            important_emails=3,
        )

        # Spoken text should have greeting + news + calendar + email
        text = briefing.spoken_text
        assert "memnun" in text.lower()          # First-time greeting
        assert "Birincisi" in text                # News ordinals
        assert "etkinliğiniz" in text             # Calendar
        assert "e-posta" in text.lower()          # Email


# ═════════════════════════════════════════════════════════════════
# SCENARIO 2: Daily user morning boot
# ═════════════════════════════════════════════════════════════════


class TestDailyUserMorningBoot:
    """Regular user boots up at 09:00 — was here yesterday."""

    @pytest.mark.asyncio
    async def test_greeting_is_standard_morning(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        yesterday = morning - datetime.timedelta(days=1)
        svc = _make_service(
            clock_time=morning,
            last_seen=yesterday,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        # Standard morning greeting, no special absence message
        assert "günaydın" in briefing.greeting.lower()
        assert briefing.days_away == 1

    @pytest.mark.asyncio
    async def test_three_news_cards_returned(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        svc = _make_service(clock_time=morning, tmp_path=tmp_path)

        briefing = await svc.generate()

        assert len(briefing.news_cards) == 3  # max_news_items=3
        for card in briefing.news_cards:
            assert "title" in card
            assert "category" in card
            assert "source" in card

    @pytest.mark.asyncio
    async def test_sections_order(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        svc = _make_service(clock_time=morning, tmp_path=tmp_path)

        briefing = await svc.generate(
            calendar_events=SAMPLE_CALENDAR[:1],
            unread_emails=3,
            important_emails=0,
        )

        types = [s.section_type for s in briefing.sections]
        assert "news" in types
        assert "calendar" in types
        assert "email" in types


# ═════════════════════════════════════════════════════════════════
# SCENARIO 3: Boot after 5-day absence
# ═════════════════════════════════════════════════════════════════


class TestFiveDayAbsenceBoot:
    """User returns after 5 days away. Should get warm welcome-back."""

    @pytest.mark.asyncio
    async def test_absence_greeting(self, tmp_path):
        now = datetime.datetime(2026, 2, 17, 10, 0)
        last_seen = now - datetime.timedelta(days=5)
        svc = _make_service(
            clock_time=now,
            last_seen=last_seen,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        assert "tekrardan" in briefing.greeting.lower()
        assert "5 gündür" in briefing.greeting
        assert briefing.days_away == 5

    @pytest.mark.asyncio
    async def test_spoken_text_includes_absence(self, tmp_path):
        now = datetime.datetime(2026, 2, 17, 10, 0)
        last_seen = now - datetime.timedelta(days=5)
        svc = _make_service(
            clock_time=now,
            last_seen=last_seen,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        assert "tekrardan" in briefing.spoken_text.lower()


# ═════════════════════════════════════════════════════════════════
# SCENARIO 4: Boot after 2-week absence
# ═════════════════════════════════════════════════════════════════


class TestTwoWeekAbsenceBoot:
    """User returns after 14 days. Greeting should mention weeks."""

    @pytest.mark.asyncio
    async def test_weeks_mentioned(self, tmp_path):
        now = datetime.datetime(2026, 2, 17, 9, 0)
        last_seen = now - datetime.timedelta(days=14)
        svc = _make_service(
            clock_time=now,
            last_seen=last_seen,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        assert "hafta" in briefing.greeting.lower()
        assert briefing.days_away == 14

    @pytest.mark.asyncio
    async def test_last_seen_updated_after_briefing(self, tmp_path):
        now = datetime.datetime(2026, 2, 17, 9, 0)
        last_seen = now - datetime.timedelta(days=14)
        svc = _make_service(
            clock_time=now,
            last_seen=last_seen,
            tmp_path=tmp_path,
        )

        await svc.generate()

        # After briefing, last_seen should be updated to now
        ls_file = tmp_path / "last_seen.txt"
        content = ls_file.read_text().strip()
        assert now.isoformat() == content


# ═════════════════════════════════════════════════════════════════
# SCENARIO 5: Evening boot
# ═════════════════════════════════════════════════════════════════


class TestEveningBoot:
    """User boots up at 19:30 in the evening."""

    @pytest.mark.asyncio
    async def test_evening_greeting(self, tmp_path):
        evening = datetime.datetime(2026, 2, 17, 19, 30)
        svc = _make_service(clock_time=evening, tmp_path=tmp_path)

        briefing = await svc.generate()

        assert "akşam" in briefing.greeting.lower()

    @pytest.mark.asyncio
    async def test_time_context_is_evening(self, tmp_path):
        evening = datetime.datetime(2026, 2, 17, 19, 30)
        svc = _make_service(clock_time=evening, tmp_path=tmp_path)

        briefing = await svc.generate()

        assert briefing.time_context["period"] == "evening"


# ═════════════════════════════════════════════════════════════════
# SCENARIO 6: Late night boot
# ═════════════════════════════════════════════════════════════════


class TestLateNightBoot:
    """User works late — boots up at 02:00."""

    @pytest.mark.asyncio
    async def test_late_night_greeting(self, tmp_path):
        late = datetime.datetime(2026, 2, 17, 2, 0)
        svc = _make_service(clock_time=late, tmp_path=tmp_path)

        briefing = await svc.generate()

        # Late night greeting should acknowledge the hour
        assert "efendim" in briefing.greeting.lower()


# ═════════════════════════════════════════════════════════════════
# SCENARIO 7: Boot with no internet (graceful fallback)
# ═════════════════════════════════════════════════════════════════


class TestOfflineBoot:
    """Network is down — news fetch fails, but briefing still works."""

    @pytest.mark.asyncio
    async def test_briefing_succeeds_without_news(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        svc = _make_service(
            clock_time=morning,
            news_service=_mock_news_service_offline(),
            tmp_path=tmp_path,
        )

        briefing = await svc.generate(
            calendar_events=SAMPLE_CALENDAR,
            unread_emails=8,
            important_emails=2,
        )

        # Briefing should still generate even without news
        assert briefing.greeting
        assert briefing.spoken_text

        # No news cards, but calendar/email sections should exist
        assert len(briefing.news_cards) == 0
        types = [s.section_type for s in briefing.sections]
        assert "calendar" in types
        assert "email" in types


# ═════════════════════════════════════════════════════════════════
# SCENARIO 8: Full IPC overlay message sequence
# ═════════════════════════════════════════════════════════════════


class TestOverlayIPCSequence:
    """Verify the complete IPC message flow to the overlay UI."""

    @pytest.mark.asyncio
    async def test_full_sequence_start_cards_end(self):
        """Complete flow: start → card popups with images → end."""
        briefing_data = {
            "greeting": "Günaydın efendim.",
            "time_context": {"period": "morning"},
            "days_away": 0,
            "news_cards": [
                {
                    "title": "GPT-5 Released",
                    "summary": "OpenAI announced GPT-5.",
                    "source": "TechCrunch",
                    "category": "ai",
                    "image_url": "https://img.com/gpt5.jpg",
                    "url": "https://tc.com/gpt5",
                },
                {
                    "title": "Linux 7.0",
                    "summary": "New kernel released.",
                    "source": "The Verge",
                    "category": "tech",
                    "image_url": "https://img.com/linux.jpg",
                    "url": "https://verge.com/linux7",
                },
                {
                    "title": "SpaceX Update",
                    "summary": "Mars mission timeline.",
                    "source": "BBC",
                    "category": "science",
                    "url": "https://bbc.com/spacex",
                },
            ],
        }

        messages = []

        def capture(msg):
            messages.append(msg)

        count = await send_briefing_sequence(
            briefing_data,
            send_fn=capture,
            card_delay=0.0,
            greeting_delay=0.0,
        )

        # Verify message order
        assert messages[0]["type"] == "briefing_start"
        assert messages[0]["greeting"] == "Günaydın efendim."
        assert messages[0]["total_cards"] == 3

        # Cards
        cards = [m for m in messages if m["type"] == "briefing_card"]
        assert len(cards) == 3

        # Card 0: AI with image
        assert cards[0]["title"] == "GPT-5 Released"
        assert cards[0]["image_url"] == "https://img.com/gpt5.jpg"
        assert cards[0]["category"] == "ai"
        assert cards[0]["index"] == 0

        # Card 1: Tech with image
        assert cards[1]["title"] == "Linux 7.0"
        assert cards[1]["image_url"] == "https://img.com/linux.jpg"

        # Card 2: Science without image
        assert cards[2]["title"] == "SpaceX Update"
        assert cards[2].get("image_url") is None

        # End message
        assert messages[-1]["type"] == "briefing_end"
        assert messages[-1]["total_shown"] == 3
        assert count == 3

    @pytest.mark.asyncio
    async def test_absence_boot_ipc_includes_days_away(self):
        """After absence, the start message should indicate days_away."""
        briefing_data = {
            "greeting": "Sizi tekrardan görmek güzel efendim, 5 gündür görüşememiştik.",
            "time_context": {"period": "morning"},
            "days_away": 5,
            "news_cards": [
                {"title": "News", "category": "world", "source": "BBC", "url": "#"},
            ],
        }

        messages = []

        def capture(msg):
            messages.append(msg)

        await send_briefing_sequence(
            briefing_data, send_fn=capture, card_delay=0.0, greeting_delay=0.0,
        )

        assert messages[0]["days_away"] == 5
        assert "tekrardan" in messages[0]["greeting"]

    @pytest.mark.asyncio
    async def test_ipc_messages_are_jsonl_serializable(self):
        """All messages must be valid JSON for the Unix socket protocol."""
        briefing_data = {
            "greeting": "İyi akşamlar efendim.",
            "time_context": {"period": "evening"},
            "days_away": 0,
            "news_cards": [
                {"title": "Test", "category": "ai", "source": "S", "url": "#",
                 "image_url": "https://img.com/test.jpg"},
            ],
        }

        messages = []

        def capture(msg):
            messages.append(msg)

        await send_briefing_sequence(
            briefing_data, send_fn=capture, card_delay=0.0, greeting_delay=0.0,
        )

        for msg in messages:
            # Every message must be JSON-serializable
            raw = json.dumps(msg, ensure_ascii=False)
            decoded = json.loads(raw)
            assert decoded["type"] in {"briefing_start", "briefing_card", "briefing_end"}

    @pytest.mark.asyncio
    async def test_card_category_emoji_auto_populated(self):
        """Cards should have category emoji from CATEGORY_DISPLAY."""
        briefing_data = {
            "greeting": "Günaydın efendim.",
            "time_context": {},
            "days_away": 0,
            "news_cards": [
                {"title": "N", "category": "ai", "source": "S", "url": "#"},
                {"title": "N", "category": "turkey", "source": "S", "url": "#"},
            ],
        }

        messages = []

        def capture(msg):
            messages.append(msg)

        await send_briefing_sequence(
            briefing_data, send_fn=capture, card_delay=0.0, greeting_delay=0.0,
        )

        cards = [m for m in messages if m["type"] == "briefing_card"]

        # AI category
        ai_card = cards[0]
        assert ai_card["category_emoji"] == CATEGORY_DISPLAY["ai"]["emoji"]
        assert ai_card["category_color"] == CATEGORY_DISPLAY["ai"]["color"]

        # Turkey category
        tr_card = cards[1]
        assert tr_card["category_emoji"] == CATEGORY_DISPLAY["turkey"]["emoji"]


# ═════════════════════════════════════════════════════════════════
# SCENARIO 9: StartupBriefingRunner full flow
# ═════════════════════════════════════════════════════════════════


class TestStartupRunnerFullFlow:
    """Full e2e: runner → briefing_service → overlay → TTS → EventBus."""

    @pytest.mark.asyncio
    async def test_complete_morning_boot(self, tmp_path):
        """Simulate complete morning boot with all services."""
        morning = datetime.datetime(2026, 2, 17, 8, 30)
        yesterday = morning - datetime.timedelta(days=1)

        briefing_svc = _make_service(
            clock_time=morning,
            last_seen=yesterday,
            tmp_path=tmp_path,
        )

        # Mock overlay, TTS, EventBus
        overlay_calls = []
        mock_overlay = MagicMock()
        mock_overlay.send = lambda msg: overlay_calls.append(msg)

        tts_texts = []
        async def mock_tts(text):
            tts_texts.append(text)

        mock_bus = MagicMock()

        runner = StartupBriefingRunner(
            briefing_service=briefing_svc,
            overlay_client=mock_overlay,
            tts_speak=mock_tts,
            event_bus=mock_bus,
        )

        with patch("bantz.services.startup_hook.asyncio.sleep", new_callable=AsyncMock):
            result = await runner.run(
                calendar_events=SAMPLE_CALENDAR,
                unread_emails=8,
                important_emails=2,
            )

        # Greeting was spoken
        assert len(tts_texts) == 1
        assert "günaydın" in tts_texts[0].lower() or "Dün" in tts_texts[0]

        # EventBus was notified
        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "startup.briefing_complete"

        # Overlay received messages
        assert len(overlay_calls) > 0

        # Result has all expected fields
        assert "greeting" in result
        assert "sections" in result
        assert "news_cards" in result

    @pytest.mark.asyncio
    async def test_absence_boot_with_event_bus(self, tmp_path):
        """After 5-day absence, EventBus should get days_away data."""
        now = datetime.datetime(2026, 2, 17, 10, 0)
        last_seen = now - datetime.timedelta(days=5)

        briefing_svc = _make_service(
            clock_time=now,
            last_seen=last_seen,
            tmp_path=tmp_path,
        )

        mock_bus = MagicMock()

        runner = StartupBriefingRunner(
            briefing_service=briefing_svc,
            event_bus=mock_bus,
        )

        result = await runner.run()

        mock_bus.publish.assert_called_once()
        event_data = mock_bus.publish.call_args[0][1]
        assert event_data["days_away"] == 5

        assert result["days_away"] == 5


# ═════════════════════════════════════════════════════════════════
# SCENARIO 10: LLM Summarization Flow
# ═════════════════════════════════════════════════════════════════


class TestLLMSummarizationBoot:
    """When LLM summarizer is available, news spoken text
    should come from the LLM, not the ordinals fallback."""

    @pytest.mark.asyncio
    async def test_llm_summary_used_instead_of_ordinals(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)

        def mock_summarizer(prompt: str) -> str:
            return (
                "Efendim, bugün önemli gelişmeler var. "
                "Yapay zeka dünyasında GPT-5 duyuruldu, "
                "Linux 7.0 çekirdeği yayınlandı."
            )

        svc = _make_service(
            clock_time=morning,
            summarizer=mock_summarizer,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        # Should use LLM summary, not "Birincisi, İkincisi..."
        assert "yapay zeka" in briefing.spoken_text.lower()
        assert "Birincisi" not in briefing.spoken_text

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_ordinals(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)

        def bad_summarizer(prompt: str) -> str:
            raise RuntimeError("LLM timeout")

        svc = _make_service(
            clock_time=morning,
            summarizer=bad_summarizer,
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        # Should fall back to deterministic ordinals
        assert "Birincisi" in briefing.spoken_text


# ═════════════════════════════════════════════════════════════════
# SCENARIO 11: TimeContext covers all day periods
# ═════════════════════════════════════════════════════════════════


class TestAllDayPeriodsBoot:
    """Verify greeting + briefing style across the full 24-hour cycle."""

    @pytest.mark.parametrize("hour,expected_period", [
        (5, DayPeriod.DAWN),
        (8, DayPeriod.MORNING),
        (12, DayPeriod.NOON),
        (14, DayPeriod.AFTERNOON),
        (19, DayPeriod.EVENING),
        (22, DayPeriod.NIGHT),
        (2, DayPeriod.LATE_NIGHT),
    ])
    def test_period_detection(self, hour, expected_period):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, hour, 0))
        assert ctx.period == expected_period

    @pytest.mark.parametrize("hour", [5, 8, 12, 14, 19, 22, 2])
    def test_every_period_has_greeting_with_efendim(self, hour):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, hour, 0))
        assert "efendim" in ctx.greeting.lower()

    @pytest.mark.parametrize("hour,quiet", [
        (5, True),     # dawn = quiet
        (9, False),    # morning = not quiet
        (2, True),     # late night = quiet
        (15, False),   # afternoon = not quiet
    ])
    def test_quiet_hours(self, hour, quiet):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, hour, 0))
        assert ctx.is_quiet_hours == quiet


# ═════════════════════════════════════════════════════════════════
# SCENARIO 12: Absence greeting tiers
# ═════════════════════════════════════════════════════════════════


class TestAbsenceGreetingTiers:
    """Verify the escalating absence detection system."""

    @pytest.mark.parametrize("days,expected_fragment", [
        (-1, "memnun"),              # First time ever
        (0, "günaydın"),             # Same day (morning)
        (1, "günaydın"),             # Yesterday (morning, normal greeting)
        (3, "tekrardan"),            # 3 days
        (5, "5 gündür"),             # 5 days
        (7, "7 gündür"),             # Week
        (14, "hafta"),              # 2 weeks
        (45, "uzun süredir"),        # 45 days
    ])
    def test_absence_tier(self, days, expected_fragment):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        ctx = TimeContext(now=morning)
        greeting = ctx.absence_greeting(days)
        assert expected_fragment in greeting.lower(), \
            f"days={days}, greeting={greeting!r} missing {expected_fragment!r}"


# ═════════════════════════════════════════════════════════════════
# SCENARIO 13: News card image popup flow
# ═════════════════════════════════════════════════════════════════


class TestNewsImagePopupFlow:
    """Verify that news images are properly routed to overlay."""

    @pytest.mark.asyncio
    async def test_image_urls_in_cards(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        svc = _make_service(clock_time=morning, tmp_path=tmp_path)

        briefing = await svc.generate()

        # At least some cards should have images
        images = [c["image_url"] for c in briefing.news_cards if c.get("image_url")]
        assert len(images) >= 1

        # All image URLs should be valid HTTP(S)
        for url in images:
            assert url.startswith("https://"), f"Invalid image URL: {url}"

    @pytest.mark.asyncio
    async def test_card_without_image_is_none(self, tmp_path):
        """Articles without images should have image_url=None."""
        no_img_articles = [
            NewsArticle(title="No Image News", category="world",
                        source="BBC", url="https://bbc.com/noimg"),
        ]
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        svc = _make_service(
            clock_time=morning,
            news_service=_mock_news_service(no_img_articles),
            tmp_path=tmp_path,
        )

        briefing = await svc.generate()

        assert len(briefing.news_cards) == 1
        assert briefing.news_cards[0]["image_url"] is None


# ═════════════════════════════════════════════════════════════════
# SCENARIO 14: Briefing → to_dict roundtrip
# ═════════════════════════════════════════════════════════════════


class TestBriefingSerializationRoundtrip:
    """Ensure the complete briefing is JSON-serializable for IPC."""

    @pytest.mark.asyncio
    async def test_full_briefing_is_json_serializable(self, tmp_path):
        morning = datetime.datetime(2026, 2, 17, 9, 0)
        svc = _make_service(clock_time=morning, tmp_path=tmp_path)

        briefing = await svc.generate(
            calendar_events=SAMPLE_CALENDAR,
            unread_emails=10,
            important_emails=4,
        )

        d = briefing.to_dict()
        raw = json.dumps(d, ensure_ascii=False, indent=2)
        decoded = json.loads(raw)

        assert decoded["greeting"]
        assert decoded["days_away"] >= 0
        assert len(decoded["sections"]) >= 1
        assert len(decoded["news_cards"]) >= 1
        assert decoded["time_context"]["period"] == "morning"
        assert decoded["generated_at"]
