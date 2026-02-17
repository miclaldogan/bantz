"""Startup Briefing Hook — auto-briefing on Bantz boot.

Integrates with the daemon startup sequence to:
1. Detect how long the user has been away
2. Generate a daily briefing
3. Send briefing to the overlay UI (with news image popups)
4. Speak the briefing via TTS

This module is called once at daemon startup, after all services
are initialized.

Usage::

    from bantz.services.startup_hook import run_startup_briefing
    await run_startup_briefing(event_bus=bus, overlay_client=client)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Callable

logger = logging.getLogger(__name__)

__all__ = ["run_startup_briefing", "StartupBriefingRunner"]


class StartupBriefingRunner:
    """Runs the startup briefing sequence.

    Coordinates between DailyBriefingService, overlay IPC,
    and TTS to deliver a smooth first-boot experience.

    Parameters
    ----------
    briefing_service:
        The DailyBriefingService instance.
    overlay_client:
        IPC overlay client for sending UI messages.
    tts_speak:
        Optional TTS function: async (text) → None.
    event_bus:
        EventBus for lifecycle events.
    """

    def __init__(
        self,
        briefing_service=None,
        overlay_client=None,
        tts_speak: Optional[Callable] = None,
        event_bus=None,
    ) -> None:
        self._briefing_service = briefing_service
        self._overlay = overlay_client
        self._tts_speak = tts_speak
        self._event_bus = event_bus

    async def run(
        self,
        *,
        calendar_events: Optional[list] = None,
        unread_emails: int = 0,
        important_emails: int = 0,
    ) -> dict:
        """Execute the full startup briefing sequence.

        Returns
        -------
        The briefing dict for logging/debugging.
        """
        # Import here to avoid circular deps
        from bantz.services.daily_briefing import DailyBriefingService

        if self._briefing_service is None:
            self._briefing_service = DailyBriefingService.from_env(
                event_bus=self._event_bus,
            )

        try:
            briefing = await self._briefing_service.generate(
                calendar_events=calendar_events,
                unread_emails=unread_emails,
                important_emails=important_emails,
            )
        except Exception as e:
            logger.error("[startup] briefing generation failed: %s", e)
            return {"error": str(e)}

        briefing_dict = briefing.to_dict()

        # ── Send overlay UI ──
        if self._overlay:
            await self._send_overlay_briefing(briefing)

        # ── TTS ──
        if self._tts_speak and briefing.spoken_text:
            try:
                await self._tts_speak(briefing.spoken_text)
            except Exception as e:
                logger.warning("[startup] TTS failed: %s", e)

        # ── Publish completion event ──
        if self._event_bus:
            try:
                self._event_bus.publish(
                    "startup.briefing_complete",
                    {"sections": len(briefing.sections), "days_away": briefing.days_away},
                    source="startup_hook",
                )
            except Exception as e:
                logger.warning("[startup] event publish failed: %s", e)

        logger.info(
            "[startup] briefing delivered: %d sections, %d news cards",
            len(briefing.sections),
            len(briefing.news_cards),
        )
        return briefing_dict

    async def _send_overlay_briefing(self, briefing) -> None:
        """Send briefing content to the overlay with news image popups."""
        from bantz.ipc.protocol import (
            StateMessage,
            OverlayState,
            ActionMessage,
            ActionType,
        )

        try:
            # Show greeting first
            greeting_msg = StateMessage(
                state=OverlayState.SPEAKING.value,
                text=briefing.greeting,
                timeout_ms=4000,
                priority=20,
            )
            self._overlay.send(greeting_msg)
            await asyncio.sleep(2.0)

            # Show news cards with popup images
            for i, card in enumerate(briefing.news_cards):
                # Show article title as overlay text
                article_msg = StateMessage(
                    state=OverlayState.SPEAKING.value,
                    text=f"📰 {card.get('title', '')}",
                    timeout_ms=5000,
                    priority=15,
                )
                self._overlay.send(article_msg)

                # Send image popup if available
                if card.get("image_url"):
                    img_msg = ActionMessage(
                        action="news_image",
                        text=card["image_url"],
                        duration_ms=4500,
                    )
                    self._overlay.send(img_msg)

                await asyncio.sleep(4.0)

            # Final state: show summary and transition to idle
            if briefing.sections:
                summary_text = " | ".join(
                    s.title for s in briefing.sections
                )
                summary_msg = StateMessage(
                    state=OverlayState.SPEAKING.value,
                    text=summary_text,
                    timeout_ms=3000,
                    priority=10,
                )
                self._overlay.send(summary_msg)
                await asyncio.sleep(3.0)

            # Return to idle
            idle_msg = StateMessage(
                state=OverlayState.IDLE.value,
                priority=5,
            )
            self._overlay.send(idle_msg)

        except Exception as e:
            logger.warning("[startup] overlay briefing failed: %s", e)


async def run_startup_briefing(
    event_bus=None,
    overlay_client=None,
    tts_speak=None,
    calendar_events=None,
    unread_emails: int = 0,
    important_emails: int = 0,
) -> dict:
    """Convenience function: run the startup briefing.

    Parameters
    ----------
    event_bus:
        EventBus for lifecycle events.
    overlay_client:
        IPC overlay client.
    tts_speak:
        Async TTS function.
    calendar_events:
        Today's calendar events (pre-fetched).
    unread_emails:
        Number of unread emails.
    important_emails:
        Number of important emails.

    Returns
    -------
    Briefing dict.
    """
    runner = StartupBriefingRunner(
        overlay_client=overlay_client,
        tts_speak=tts_speak,
        event_bus=event_bus,
    )
    return await runner.run(
        calendar_events=calendar_events,
        unread_emails=unread_emails,
        important_emails=important_emails,
    )
