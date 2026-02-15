"""Daily Brief Generator for the Proactive Secretary Engine.

Combines :class:`SignalCollector` + :class:`ProactiveRuleEngine` to produce
a formatted morning brief and deliver it through registered channels.

Issue #1293
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bantz.proactive.rule_engine import ProactiveRuleEngine, RuleSuggestion
from bantz.proactive.signals import DailySignals, SignalCollector

logger = logging.getLogger(__name__)


class DailyBriefGenerator:
    """Generates and delivers a daily brief.

    Parameters
    ----------
    collector:
        The :class:`SignalCollector` to gather signals.
    rule_engine:
        The :class:`ProactiveRuleEngine` to evaluate rules.
    delivery_channels:
        List of :class:`DeliveryChannel` instances.
    """

    def __init__(
        self,
        collector: SignalCollector,
        rule_engine: ProactiveRuleEngine,
        delivery_channels: Optional[list] = None,
    ) -> None:
        self._collector = collector
        self._rule_engine = rule_engine
        self._channels = delivery_channels or []
        self._last_brief: Optional[str] = None
        self._last_signals: Optional[DailySignals] = None
        self._last_suggestions: Optional[list[RuleSuggestion]] = None
        self._last_generated_at: Optional[datetime] = None

    # ── Public API ──────────────────────────────────────────────

    async def generate(self) -> str:
        """Collect signals, evaluate rules, format and deliver brief.

        Returns the formatted brief text.
        """
        # 1) Collect signals
        signals = await self._collector.collect_all()
        self._last_signals = signals

        # 2) Evaluate rules
        suggestions = await self._rule_engine.evaluate(signals)
        self._last_suggestions = suggestions

        # 3) Format brief
        brief = self.format_brief(signals, suggestions)
        self._last_brief = brief
        self._last_generated_at = datetime.now()

        # 4) Deliver through all channels
        await self._deliver(brief)

        logger.info("Daily brief generated (%d chars, %d suggestions)", len(brief), len(suggestions))
        return brief

    def format_brief(
        self,
        signals: DailySignals,
        suggestions: list[RuleSuggestion],
    ) -> str:
        """Format signals and suggestions into a readable brief.

        Returns
        -------
        str
            Multi-line Turkish brief text.
        """
        sections: list[str] = []
        sections.append("🌅 Günaydın! İşte bugünün özeti:\n")

        # ── Calendar ────────────────────────────────────────────
        cal = signals.calendar
        n_today = len(cal.today_events)
        if n_today:
            sections.append(f"📅 {n_today} toplantı bugün:")
            for evt in cal.today_events[:5]:
                if isinstance(evt, dict):
                    time_str = self._extract_time(evt)
                    summary = evt.get("summary", evt.get("title", "?"))
                    sections.append(f"   • {time_str} {summary}")
        else:
            sections.append("📅 Bugün toplantı yok — boş bir gün!")

        # ── Email ───────────────────────────────────────────────
        email = signals.emails
        if email.unread_count > 0:
            parts = [f"📧 {email.unread_count} okunmamış mail"]
            if email.urgent:
                parts.append(f"({len(email.urgent)} acil)")
            sections.append(" ".join(parts))
        else:
            sections.append("📧 Okunmamış mail yok — inbox sıfır!")

        # ── Weather ─────────────────────────────────────────────
        wx = signals.weather
        if wx.temperature is not None:
            sections.append(f"\n🌤️ {wx.temperature}°C, {wx.condition}")
            if wx.rain_probability > 0.5:
                sections.append(f"   🌧️ Yağmur olasılığı: %{int(wx.rain_probability * 100)}")
            if wx.alerts:
                for alert in wx.alerts[:2]:
                    sections.append(f"   ⚠️ {alert}")

        # ── Tasks ───────────────────────────────────────────────
        tasks = signals.tasks
        task_parts: list[str] = []
        if tasks.overdue:
            task_parts.append(f"{len(tasks.overdue)} gecikmiş")
        if tasks.due_today:
            task_parts.append(f"{len(tasks.due_today)} bugün")
        if tasks.due_tomorrow:
            task_parts.append(f"{len(tasks.due_tomorrow)} yarın")
        if task_parts:
            sections.append(f"\n📋 Görevler: {', '.join(task_parts)}")
            for t in tasks.overdue[:2]:
                if isinstance(t, dict):
                    sections.append(f"   🚨 {t.get('title', '?')} (gecikmiş)")
            for t in tasks.due_today[:2]:
                if isinstance(t, dict):
                    sections.append(f"   📌 {t.get('title', '?')} (bugün)")

        # ── News ────────────────────────────────────────────────
        if signals.news.headlines:
            sections.append("\n📰 Gündem:")
            for hl in signals.news.headlines[:3]:
                title = hl.get("title", "?") if isinstance(hl, dict) else str(hl)
                sections.append(f"   • {title}")

        # ── Suggestions ─────────────────────────────────────────
        if suggestions:
            sections.append("\n💡 Öneriler:")
            for s in suggestions[:5]:
                sections.append(f"   • {s.message}")

        return "\n".join(sections)

    @property
    def last_brief(self) -> Optional[str]:
        """The most recently generated brief."""
        return self._last_brief

    @property
    def last_signals(self) -> Optional[DailySignals]:
        """Signals from the most recent collection."""
        return self._last_signals

    @property
    def last_generated_at(self) -> Optional[datetime]:
        """When the last brief was generated."""
        return self._last_generated_at

    def get_status(self) -> Dict[str, Any]:
        """Return status information about the brief generator."""
        return {
            "last_generated_at": (
                self._last_generated_at.isoformat()
                if self._last_generated_at else None
            ),
            "has_brief": self._last_brief is not None,
            "brief_length": len(self._last_brief) if self._last_brief else 0,
            "suggestion_count": (
                len(self._last_suggestions) if self._last_suggestions else 0
            ),
            "delivery_channels": len(self._channels),
        }

    # ── Internal ────────────────────────────────────────────────

    async def _deliver(self, brief: str) -> None:
        """Deliver brief through all registered channels."""
        for channel in self._channels:
            try:
                await channel.deliver(brief)
            except Exception as exc:
                logger.warning(
                    "Delivery channel %s failed: %s",
                    type(channel).__name__, exc,
                )

    @staticmethod
    def _extract_time(event: Dict[str, Any]) -> str:
        """Extract a human-readable time string from a calendar event."""
        start = event.get("start", "")
        if isinstance(start, dict):
            start = start.get("dateTime", start.get("date", ""))
        if isinstance(start, str) and "T" in start:
            return start.split("T")[1][:5]
        if isinstance(start, str) and len(start) == 5 and ":" in start:
            return start
        return "??:??"
