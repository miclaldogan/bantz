"""Daily Briefing Service — startup intelligence digest.

Orchestrates the "first boot" experience: when the user opens their
computer (and Bantz auto-starts), the assistant delivers a contextual
briefing covering news, calendar, emails, GitHub, and more.

Features:
    - Time-of-day awareness (morning vs evening style)
    - Absence detection (3+ days → "nice to see you again")
    - Multi-source aggregation (news, calendar, gmail, GitHub)
    - News summarization via LLM
    - Image-rich news cards for the overlay UI
    - Persistent last-seen tracking

Env vars::

    BANTZ_BRIEFING_ENABLED=true
    BANTZ_BRIEFING_NEWS=true
    BANTZ_BRIEFING_CALENDAR=true
    BANTZ_BRIEFING_EMAIL=true
    BANTZ_BRIEFING_GITHUB=false
    BANTZ_BRIEFING_MAX_NEWS=3
    BANTZ_BRIEFING_SUMMARIZE=true
    BANTZ_LAST_SEEN_FILE=~/.local/share/bantz/last_seen.txt

Architecture::

    DailyBriefingService
      ├── TimeContext        (time awareness)
      ├── NewsService        (news fetching)
      ├── CalendarConnector  (optional, calendar events)
      ├── GmailConnector     (optional, email summary)
      ├── LLM Summarizer     (optional, news digest)
      └── EventBus           (briefing.ready event)

Usage::

    from bantz.services.daily_briefing import DailyBriefingService
    svc = DailyBriefingService.from_env()
    briefing = await svc.generate()
    # briefing.greeting     → "Günaydın efendim. Sizi tekrardan görmek güzel."
    # briefing.sections     → [NewsBriefingSection, CalendarSection, ...]
    # briefing.news_cards   → [{title, summary, image_url}, ...]
    # briefing.spoken_text  → Full TTS-ready monologue
"""

from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from bantz.services.time_context import TimeContext

logger = logging.getLogger(__name__)

__all__ = [
    "BriefingSection",
    "NewsBriefingSection",
    "CalendarBriefingSection",
    "EmailBriefingSection",
    "DailyBriefing",
    "DailyBriefingConfig",
    "DailyBriefingService",
]


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class DailyBriefingConfig:
    """Configuration for the daily briefing service."""

    enabled: bool = True
    include_news: bool = True
    include_calendar: bool = True
    include_email: bool = True
    include_github: bool = False
    max_news_items: int = 3
    summarize_news: bool = True
    last_seen_file: str = ""

    @classmethod
    def from_env(cls) -> "DailyBriefingConfig":
        default_path = str(
            Path.home() / ".local" / "share" / "bantz" / "last_seen.txt"
        )
        return cls(
            enabled=_env_bool("BANTZ_BRIEFING_ENABLED", True),
            include_news=_env_bool("BANTZ_BRIEFING_NEWS", True),
            include_calendar=_env_bool("BANTZ_BRIEFING_CALENDAR", True),
            include_email=_env_bool("BANTZ_BRIEFING_EMAIL", True),
            include_github=_env_bool("BANTZ_BRIEFING_GITHUB", False),
            max_news_items=_env_int("BANTZ_BRIEFING_MAX_NEWS", 3),
            summarize_news=_env_bool("BANTZ_BRIEFING_SUMMARIZE", True),
            last_seen_file=os.getenv("BANTZ_LAST_SEEN_FILE", default_path),
        )


# ─────────────────────────────────────────────────────────────────
# Briefing Sections
# ─────────────────────────────────────────────────────────────────


@dataclass
class BriefingSection:
    """Base class for a briefing section."""

    section_type: str = ""
    title: str = ""
    spoken_text: str = ""
    items: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.section_type,
            "title": self.title,
            "spoken_text": self.spoken_text,
            "items": self.items,
        }


@dataclass
class NewsBriefingSection(BriefingSection):
    """News section with article cards."""

    section_type: str = "news"
    title: str = "News Digest"
    summary: str = ""
    news_cards: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["summary"] = self.summary
        d["news_cards"] = self.news_cards
        return d


@dataclass
class CalendarBriefingSection(BriefingSection):
    """Calendar section with today's events."""

    section_type: str = "calendar"
    title: str = "Today's Schedule"
    event_count: int = 0


@dataclass
class EmailBriefingSection(BriefingSection):
    """Email section with unread summary."""

    section_type: str = "email"
    title: str = "Email Summary"
    unread_count: int = 0
    important_count: int = 0


# ─────────────────────────────────────────────────────────────────
# Daily Briefing Result
# ─────────────────────────────────────────────────────────────────


@dataclass
class DailyBriefing:
    """Complete daily briefing result."""

    greeting: str = ""
    time_context: Optional[Dict[str, Any]] = None
    sections: List[BriefingSection] = field(default_factory=list)
    spoken_text: str = ""
    news_cards: List[Dict[str, Any]] = field(default_factory=list)
    days_away: int = 0
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "greeting": self.greeting,
            "time_context": self.time_context,
            "sections": [s.to_dict() for s in self.sections],
            "spoken_text": self.spoken_text,
            "news_cards": self.news_cards,
            "days_away": self.days_away,
            "generated_at": self.generated_at,
        }


# ─────────────────────────────────────────────────────────────────
# Last-Seen Persistence
# ─────────────────────────────────────────────────────────────────


def _read_last_seen(path: str) -> Optional[datetime.datetime]:
    """Read last-seen timestamp from file."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        raw = p.read_text().strip()
        if not raw:
            return None
        return datetime.datetime.fromisoformat(raw)
    except Exception as e:
        logger.warning("[briefing] failed to read last_seen: %s", e)
        return None


def _write_last_seen(path: str, dt: Optional[datetime.datetime] = None) -> None:
    """Write current timestamp to last-seen file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = dt or datetime.datetime.now()
        p.write_text(ts.isoformat())
    except Exception as e:
        logger.warning("[briefing] failed to write last_seen: %s", e)


# ─────────────────────────────────────────────────────────────────
# News Summarizer
# ─────────────────────────────────────────────────────────────────


def _build_news_summary_prompt(articles: List[Dict[str, Any]]) -> str:
    """Build an LLM prompt for summarizing news articles."""
    lines = ["Summarize the following news headlines into a brief, conversational briefing "
             "in Turkish (2-4 sentences). Speak as a polite butler (use 'efendim'). "
             "Highlight the most interesting or important items:\n"]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. [{a.get('category', '?')}] {a['title']}")
        if a.get("summary"):
            lines.append(f"   {a['summary'][:100]}")
    lines.append("\nBriefing:")
    return "\n".join(lines)


def _build_news_spoken_text(articles: List[Dict[str, Any]]) -> str:
    """Build fallback spoken text without LLM summarization."""
    if not articles:
        return "Bugün için önemli bir haber bulamadım efendim."

    ordinals = ["Birincisi", "İkincisi", "Üçüncüsü", "Dördüncüsü", "Beşincisi"]
    lines = ["Gündemdeki gelişmeler efendim:"]

    for i, a in enumerate(articles):
        ordinal = ordinals[i] if i < len(ordinals) else f"{i + 1}."
        source = a.get("source", "")
        source_text = f" ({source})" if source else ""
        lines.append(f"{ordinal}, {a['title']}{source_text}.")

    return " ".join(lines)


# ─────────────────────────────────────────────────────────────────
# Main Service
# ─────────────────────────────────────────────────────────────────


class DailyBriefingService:
    """Orchestrates the daily startup briefing.

    Parameters
    ----------
    config:
        Briefing configuration.
    news_service:
        NewsService instance (or None for lazy creation).
    summarizer:
        Optional callable(prompt) → str for LLM summarization.
    event_bus:
        Optional EventBus for publishing briefing events.
    clock:
        Injectable datetime for testing.
    """

    def __init__(
        self,
        config: Optional[DailyBriefingConfig] = None,
        news_service=None,
        summarizer: Optional[Callable[[str], str]] = None,
        event_bus=None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
    ) -> None:
        self._config = config or DailyBriefingConfig()
        self._news_service = news_service
        self._summarizer = summarizer
        self._event_bus = event_bus
        self._clock = clock
        self._last_briefing: Optional[DailyBriefing] = None

    @classmethod
    def from_env(cls, **kwargs) -> "DailyBriefingService":
        """Create service from environment variables."""
        return cls(config=DailyBriefingConfig.from_env(), **kwargs)

    def _now(self) -> datetime.datetime:
        if self._clock:
            return self._clock()
        return datetime.datetime.now()

    async def _get_news_service(self):
        """Lazy-load news service."""
        if self._news_service is None:
            from bantz.services.news_service import NewsService
            self._news_service = NewsService.from_env()
        return self._news_service

    async def generate(
        self,
        *,
        calendar_events: Optional[List[dict]] = None,
        unread_emails: int = 0,
        important_emails: int = 0,
        github_notifications: Optional[List[dict]] = None,
    ) -> DailyBriefing:
        """Generate the full daily briefing.

        Parameters
        ----------
        calendar_events:
            Pre-fetched calendar events for today.
        unread_emails:
            Number of unread emails.
        important_emails:
            Number of important/urgent emails.
        github_notifications:
            Pre-fetched GitHub notifications.

        Returns
        -------
        Complete DailyBriefing with greeting, sections, and spoken text.
        """
        now = self._now()
        time_ctx = TimeContext(now=now)

        # ── Absence detection ──
        last_seen = _read_last_seen(self._config.last_seen_file)
        days_away = time_ctx.elapsed_days_since(last_seen)
        greeting = time_ctx.absence_greeting(days_away)

        # Update last-seen immediately
        _write_last_seen(self._config.last_seen_file, now)

        briefing = DailyBriefing(
            greeting=greeting,
            time_context=time_ctx.to_dict(),
            days_away=days_away,
            generated_at=now.isoformat(),
        )

        spoken_parts = [greeting]

        # ── News section ──
        if self._config.include_news:
            news_section = await self._build_news_section(time_ctx)
            if news_section:
                briefing.sections.append(news_section)
                briefing.news_cards = news_section.news_cards
                spoken_parts.append(news_section.spoken_text)

        # ── Calendar section ──
        if self._config.include_calendar and calendar_events is not None:
            cal_section = self._build_calendar_section(calendar_events, time_ctx)
            if cal_section:
                briefing.sections.append(cal_section)
                spoken_parts.append(cal_section.spoken_text)

        # ── Email section ──
        if self._config.include_email and (unread_emails > 0 or important_emails > 0):
            email_section = self._build_email_section(
                unread_emails, important_emails
            )
            if email_section:
                briefing.sections.append(email_section)
                spoken_parts.append(email_section.spoken_text)

        # ── Build composite spoken text ──
        briefing.spoken_text = " ".join(spoken_parts)

        # ── Publish event ──
        if self._event_bus:
            try:
                self._event_bus.publish(
                    "briefing.ready",
                    briefing.to_dict(),
                    source="daily_briefing",
                )
            except Exception as e:
                logger.warning("[briefing] event publish failed: %s", e)

        self._last_briefing = briefing
        logger.info(
            "[briefing] generated: %d sections, %d news cards, days_away=%d",
            len(briefing.sections),
            len(briefing.news_cards),
            days_away,
        )
        return briefing

    async def _build_news_section(
        self, time_ctx: TimeContext
    ) -> Optional[NewsBriefingSection]:
        """Fetch and format news articles."""
        try:
            news_svc = await self._get_news_service()
            briefing_result = await news_svc.fetch_all()

            if not briefing_result.has_articles:
                return None

            max_items = self._config.max_news_items
            articles = briefing_result.articles[:max_items]
            article_dicts = [a.to_dict() for a in articles]

            # Build news cards (with images for UI)
            news_cards = []
            for a in articles:
                card = {
                    "title": a.title,
                    "summary": a.summary,
                    "source": a.source,
                    "category": a.category,
                    "url": a.url,
                    "image_url": a.image_url,
                }
                news_cards.append(card)

            # Summarize via LLM if available
            summary = ""
            spoken_text = _build_news_spoken_text(article_dicts)

            if self._config.summarize_news and self._summarizer:
                try:
                    prompt = _build_news_summary_prompt(article_dicts)
                    summary = self._summarizer(prompt)
                    if summary:
                        spoken_text = summary
                except Exception as e:
                    logger.warning("[briefing] news summarization failed: %s", e)

            section = NewsBriefingSection(
                spoken_text=spoken_text,
                summary=summary,
                items=article_dicts,
                news_cards=news_cards,
            )
            return section

        except Exception as e:
            logger.error("[briefing] news section failed: %s", e)
            return None

    def _build_calendar_section(
        self, events: List[dict], time_ctx: TimeContext
    ) -> Optional[CalendarBriefingSection]:
        """Build calendar briefing section."""
        count = len(events)
        if count == 0:
            return None

        if count == 1:
            spoken = "Bugün takviminizde 1 etkinliğiniz var efendim."
        else:
            spoken = f"Bugün takviminizde {count} etkinliğiniz var efendim."

        # Add first event time if available
        first = events[0]
        start_time = first.get("start_time") or first.get("start") or first.get("time")
        if start_time and isinstance(start_time, str):
            if "T" in start_time:
                try:
                    dt = datetime.datetime.fromisoformat(
                        start_time.replace("Z", "+00:00")
                    )
                    spoken += f" İlki saat {dt.strftime('%H:%M')}'de."
                except Exception:
                    pass

        section = CalendarBriefingSection(
            spoken_text=spoken,
            event_count=count,
            items=[{"title": e.get("title", ""), "start": e.get("start", "")} for e in events],
        )
        return section

    def _build_email_section(
        self, unread: int, important: int
    ) -> Optional[EmailBriefingSection]:
        """Build email briefing section."""
        parts = []

        if important > 0:
            parts.append(f"{important} önemli e-postanız var")
        if unread > 0:
            parts.append(f"toplam {unread} okunmamış e-postanız var")

        if not parts:
            return None

        spoken = "E-posta durumu: " + ", ".join(parts) + " efendim."

        section = EmailBriefingSection(
            spoken_text=spoken,
            unread_count=unread,
            important_count=important,
            items=[{"unread": unread, "important": important}],
        )
        return section

    @property
    def last_briefing(self) -> Optional[DailyBriefing]:
        """Most recently generated briefing."""
        return self._last_briefing
