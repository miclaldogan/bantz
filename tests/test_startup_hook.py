"""Tests for startup hook — StartupBriefingRunner.

Covers:
- Briefing generation coordination
- Overlay IPC message dispatch
- TTS integration
- Error recovery
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.services.startup_hook import StartupBriefingRunner, run_startup_briefing


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _make_mock_briefing(
    greeting="Günaydın efendim",
    spoken_text="Günaydın efendim. İşte bugünkü haberler.",
    news_cards=None,
    days_away=0,
):
    """Create a mock DailyBriefing result."""
    briefing = MagicMock()
    briefing.greeting = greeting
    briefing.spoken_text = spoken_text
    briefing.days_away = days_away
    briefing.news_cards = news_cards or []

    # Sections
    news_section = MagicMock()
    news_section.section_type = "news"
    news_section.spoken = "AI haberleri geldi."
    news_section.title = "News"
    briefing.sections = [news_section]

    briefing.to_dict.return_value = {
        "greeting": greeting,
        "spoken_text": spoken_text,
        "days_away": days_away,
        "news_cards": news_cards or [],
        "sections": [{"title": "News"}],
        "time_context": {"period": "morning"},
    }

    return briefing


# ─────────────────────────────────────────────────────────────────
# StartupBriefingRunner
# ─────────────────────────────────────────────────────────────────


class TestStartupBriefingRunner:
    def test_init(self):
        runner = StartupBriefingRunner()
        assert runner is not None

    @pytest.mark.asyncio
    async def test_run_calls_briefing_service(self):
        """Briefing service should be called."""
        briefing = _make_mock_briefing()

        mock_service = AsyncMock()
        mock_service.generate = AsyncMock(return_value=briefing)

        runner = StartupBriefingRunner(briefing_service=mock_service)

        result = await runner.run()

        mock_service.generate.assert_awaited_once()
        assert "greeting" in result

    @pytest.mark.asyncio
    async def test_run_with_overlay_sends_greeting(self):
        """Overlay client should receive state messages."""
        cards = [
            {"title": "AI News", "image_url": "https://img.com/ai.jpg"},
        ]
        briefing = _make_mock_briefing(news_cards=cards)

        mock_service = AsyncMock()
        mock_service.generate = AsyncMock(return_value=briefing)

        mock_overlay = MagicMock()

        runner = StartupBriefingRunner(
            briefing_service=mock_service,
            overlay_client=mock_overlay,
        )

        with patch("bantz.services.startup_hook.asyncio.sleep", new_callable=AsyncMock):
            await runner.run()

        # Overlay should have been called
        assert mock_overlay.send.call_count > 0

    @pytest.mark.asyncio
    async def test_tts_called_with_spoken_text(self):
        """TTS should be called with the briefing spoken text."""
        briefing = _make_mock_briefing(
            spoken_text="Günaydın efendim. İşte bugünkü haberler.",
            news_cards=[],
        )

        mock_service = AsyncMock()
        mock_service.generate = AsyncMock(return_value=briefing)

        mock_tts = AsyncMock()

        runner = StartupBriefingRunner(
            briefing_service=mock_service,
            tts_speak=mock_tts,
        )

        await runner.run()

        mock_tts.assert_awaited_once_with("Günaydın efendim. İşte bugünkü haberler.")

    @pytest.mark.asyncio
    async def test_error_in_briefing_service(self):
        """Runner should handle errors gracefully."""
        mock_service = AsyncMock()
        mock_service.generate = AsyncMock(side_effect=Exception("Service down"))

        runner = StartupBriefingRunner(briefing_service=mock_service)

        # Should not raise
        result = await runner.run()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_event_bus_publish(self):
        """Event bus should receive completion event."""
        briefing = _make_mock_briefing()

        mock_service = AsyncMock()
        mock_service.generate = AsyncMock(return_value=briefing)

        mock_bus = MagicMock()

        runner = StartupBriefingRunner(
            briefing_service=mock_service,
            event_bus=mock_bus,
        )

        await runner.run()

        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "startup.briefing_complete"


# ─────────────────────────────────────────────────────────────────
# run_startup_briefing convenience function
# ─────────────────────────────────────────────────────────────────


class TestRunStartupBriefing:
    def test_callable(self):
        """The convenience function should be importable and callable."""
        assert callable(run_startup_briefing)
