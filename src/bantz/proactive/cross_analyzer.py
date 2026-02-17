"""Cross-analysis engine for combining tool results into insights.

The CrossAnalyzer takes results from multiple proactive checks and
produces higher-level insights by correlating data across domains
(calendar, weather, email, assignments, etc.).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from bantz.proactive.models import (
    CrossAnalysis,
    Insight,
    InsightSeverity,
    Suggestion,
)

logger = logging.getLogger(__name__)

# Type alias for cross-analysis rules
AnalysisRule = Callable[[Dict[str, Any]], Tuple[List[Insight], List[Suggestion]]]


class CrossAnalyzer:
    """Engine for multi-source cross-analysis.

    Maintains a set of analysis rules that examine combined tool results
    and produce insights and suggestions.

    Usage::

        analyzer = CrossAnalyzer()
        analyzer.add_rule("weather_calendar", my_rule_fn)

        analysis = analyzer.analyze("my_check", {
            "calendar": {"events": [...]},
            "weather": {"temperature": 5, "condition": "rain"},
        })
    """

    def __init__(self) -> None:
        self._rules: Dict[str, AnalysisRule] = {}
        self._register_builtin_rules()

    def add_rule(self, name: str, rule: AnalysisRule) -> None:
        """Register an analysis rule."""
        self._rules[name] = rule
        logger.debug("CrossAnalyzer rule registered: %s", name)

    def remove_rule(self, name: str) -> bool:
        """Remove an analysis rule. Returns True if found."""
        return self._rules.pop(name, None) is not None

    @property
    def rule_names(self) -> List[str]:
        return list(self._rules.keys())

    def analyze(
        self,
        check_name: str,
        tool_results: Dict[str, Any],
        *,
        rules: Optional[List[str]] = None,
    ) -> CrossAnalysis:
        """Run cross-analysis on combined tool results.

        Parameters
        ----------
        check_name:
            Name of the originating proactive check.
        tool_results:
            Combined results from multiple tools.
        rules:
            Optional list of rule names to apply (default: all).

        Returns
        -------
        CrossAnalysis with insights and suggestions.
        """
        all_insights: List[Insight] = []
        all_suggestions: List[Suggestion] = []

        target_rules = rules or list(self._rules.keys())

        for rule_name in target_rules:
            rule_fn = self._rules.get(rule_name)
            if rule_fn is None:
                continue
            try:
                insights, suggestions = rule_fn(tool_results)
                all_insights.extend(insights)
                all_suggestions.extend(suggestions)
            except Exception as e:
                logger.warning("CrossAnalyzer rule '%s' failed: %s", rule_name, e)
                all_insights.append(Insight(
                    message=f"Analiz kuralı '{rule_name}' başarısız: {e}",
                    severity=InsightSeverity.INFO,
                ))

        return CrossAnalysis(
            check_name=check_name,
            insights=all_insights,
            suggestions=all_suggestions,
            tool_results=tool_results,
        )

    # ── Built-in Rules ──────────────────────────────────────────

    def _register_builtin_rules(self) -> None:
        """Register the default analysis rules."""
        self.add_rule("high_email_volume", _rule_high_email_volume)
        self.add_rule("busy_calendar_day", _rule_busy_calendar_day)
        self.add_rule("weather_extreme", _rule_weather_extreme)
        self.add_rule("weather_calendar_cross", _rule_weather_calendar_cross)
        self.add_rule("news_calendar_cross", _rule_news_calendar_cross)


# ── Built-in Rule Implementations ──────────────────────────────


def _rule_high_email_volume(tool_results: Dict[str, Any]) -> Tuple[List[Insight], List[Suggestion]]:
    """Flag if unread email count is concerning."""
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    mail_data = tool_results.get("mail", tool_results.get("unread", {}))
    if not isinstance(mail_data, dict):
        return insights, suggestions

    unread = mail_data.get("unread", mail_data.get("count", 0))
    if not isinstance(unread, int):
        return insights, suggestions

    if unread >= 20:
        insights.append(Insight(
            message=f"📧 {unread} okunmamış mail birikmiş — inbox temizliği önerilir.",
            severity=InsightSeverity.WARNING,
            source_tools=["gmail.unread_count"],
            data={"unread": unread},
        ))
        suggestions.append(Suggestion(
            text="Önemli mailleri filtreleyip özetleyebilirim.",
            action="gmail.smart_search",
            action_params={"query": "is:unread is:important"},
        ))

    return insights, suggestions


def _rule_busy_calendar_day(tool_results: Dict[str, Any]) -> Tuple[List[Insight], List[Suggestion]]:
    """Warn if the day has many events."""
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    cal_data = tool_results.get("calendar", {})
    if not isinstance(cal_data, dict):
        return insights, suggestions

    events = cal_data.get("events", cal_data.get("data", []))
    if not isinstance(events, list):
        return insights, suggestions

    if len(events) >= 5:
        insights.append(Insight(
            message=f"Bugün {len(events)} etkinlik var — yoğun bir gün!",
            severity=InsightSeverity.WARNING,
            source_tools=["calendar.list_events"],
            data={"event_count": len(events)},
        ))
        suggestions.append(Suggestion(
            text="Etkinlikler arasında boşluk var mı kontrol edebilirim.",
            action="calendar.find_free_slots",
        ))

    return insights, suggestions


def _rule_weather_extreme(tool_results: Dict[str, Any]) -> Tuple[List[Insight], List[Suggestion]]:
    """Warn about extreme weather conditions."""
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    weather_data = tool_results.get("weather", {})
    if not isinstance(weather_data, dict):
        return insights, suggestions

    # Navigate to actual data
    if "data" in weather_data and isinstance(weather_data["data"], dict):
        weather_data = weather_data["data"]

    temp = weather_data.get("temperature")
    condition = str(weather_data.get("condition", "")).lower()

    storm_keywords = {"storm", "fırtına", "thunderstorm", "tornado", "hortum"}
    if any(kw in condition for kw in storm_keywords):
        insights.append(Insight(
            message=f"🌪️ Fırtına uyarısı: {condition}! Dışarı çıkmayın.",
            severity=InsightSeverity.CRITICAL,
            source_tools=["weather.get_current"],
        ))
        suggestions.append(Suggestion(
            text="Bugünkü dış mekan etkinliklerini iptal edebilirim.",
            action="calendar.list_events",
        ))

    if isinstance(temp, (int, float)):
        if temp <= -10:
            insights.append(Insight(
                message=f"🥶 Aşırı soğuk: {temp}°C! Dışarıda dikkatli olun.",
                severity=InsightSeverity.CRITICAL,
                source_tools=["weather.get_current"],
            ))
        elif temp >= 40:
            insights.append(Insight(
                message=f"🔥 Aşırı sıcak: {temp}°C! Bol su için ve güneşten korunun.",
                severity=InsightSeverity.CRITICAL,
                source_tools=["weather.get_current"],
            ))

    return insights, suggestions


def _rule_weather_calendar_cross(tool_results: Dict[str, Any]) -> Tuple[List[Insight], List[Suggestion]]:
    """Cross-analyze weather + calendar: warn about outdoor events in bad weather (Issue #838).

    Checks if any calendar event has outdoor-related keywords in its title
    or location while weather conditions are unfavorable (rain, storm, cold).
    """
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    weather_data = tool_results.get("weather", {})
    cal_data = tool_results.get("calendar", {})

    if not isinstance(weather_data, dict) or not isinstance(cal_data, dict):
        return insights, suggestions

    # Navigate to actual data
    if "data" in weather_data and isinstance(weather_data["data"], dict):
        weather_data = weather_data["data"]

    rain_prob = weather_data.get("rain_probability", 0)
    condition = str(weather_data.get("condition", "")).lower()
    temp = weather_data.get("temperature")

    # Is weather unfavorable?
    bad_conditions = {"rain", "storm", "thunder", "snow", "blizzard", "hail",
                      "yağmur", "fırtına", "kar", "dolu"}
    is_rainy = rain_prob > 0.5 or any(kw in condition for kw in bad_conditions)
    is_cold = isinstance(temp, (int, float)) and temp <= 0
    is_hot = isinstance(temp, (int, float)) and temp >= 38

    if not (is_rainy or is_cold or is_hot):
        return insights, suggestions

    # Check calendar events for outdoor keywords
    events = cal_data.get("events", cal_data.get("data", []))
    if not isinstance(events, list):
        return insights, suggestions

    outdoor_keywords = {
        "park", "yürüyüş", "piknik", "koşu", "bisiklet", "bahçe",
        "açık hava", "outdoor", "walk", "run", "bike", "garden",
        "swimming", "yüzme", "teras", "balkon", "stadyum", "stadium",
        "camping", "kamp", "hiking", "trekking", "sahil", "beach",
        "plaj", "göl", "lake", "orman", "forest",
    }

    for event in events:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title", event.get("summary", ""))).lower()
        location = str(event.get("location", "")).lower()
        combined = f"{title} {location}"

        if any(kw in combined for kw in outdoor_keywords):
            start = event.get("start", event.get("start_time", ""))
            if isinstance(start, dict):
                start = start.get("dateTime", start.get("date", ""))

            reasons = []
            if is_rainy:
                reasons.append(f"rain probability {int(rain_prob * 100)}%")
            if is_cold:
                reasons.append(f"cold ({temp}°C)")
            if is_hot:
                reasons.append(f"extreme heat ({temp}°C)")

            reason_str = ", ".join(reasons)
            insights.append(Insight(
                message=(
                    f"⚠️ Outdoor event '{event.get('title', event.get('summary', '?'))}' "
                    f"at {start} may be affected: {reason_str}."
                ),
                severity=InsightSeverity.WARNING,
                source_tools=["weather.get_current", "calendar.list_events"],
                data={"event": event.get("title", ""), "weather_reason": reason_str},
            ))
            suggestions.append(Suggestion(
                text=f"I can reschedule '{event.get('title', event.get('summary', '?'))}' to a better day.",
                action="calendar.list_events",
                action_params={"window_hint": "tomorrow"},
            ))

    return insights, suggestions


def _rule_news_calendar_cross(tool_results: Dict[str, Any]) -> Tuple[List[Insight], List[Suggestion]]:
    """Suggest relevant news reading before meetings with topic overlap.

    If a calendar event title contains keywords that match news article titles
    or categories, suggest catching up on relevant news before the meeting.
    """
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    calendar_data = tool_results.get("calendar", {})
    news_data = tool_results.get("news", {})

    events = []
    if isinstance(calendar_data, dict):
        events = calendar_data.get("events", calendar_data.get("items", []))
    elif isinstance(calendar_data, list):
        events = calendar_data

    articles = []
    if isinstance(news_data, dict):
        articles = news_data.get("articles", news_data.get("headlines", []))
    elif isinstance(news_data, list):
        articles = news_data

    if not events or not articles:
        return insights, suggestions

    # Build a keyword set from article titles
    article_keywords: set[str] = set()
    for article in articles[:20]:
        if isinstance(article, dict):
            title = (article.get("title") or "").lower()
            for word in title.split():
                if len(word) > 4:  # Skip short words
                    article_keywords.add(word)

    # Check each event for keyword overlap
    for event in events:
        if not isinstance(event, dict):
            continue
        event_title = (event.get("title") or event.get("summary") or "").lower()
        event_words = {w for w in event_title.split() if len(w) > 4}
        overlap = event_words & article_keywords

        if len(overlap) >= 1:
            matching = ", ".join(sorted(overlap)[:3])
            insights.append(Insight(
                message=(
                    f"📰 Your event '{event.get('title', event.get('summary', '?'))}' "
                    f"has related news (keywords: {matching})."
                ),
                severity=InsightSeverity.INFO,
                source_tools=["news.latest", "calendar.list_events"],
                data={"event": event.get("title", ""), "keywords": list(overlap)},
            ))
            suggestions.append(Suggestion(
                text=f"Catch up on news related to '{event.get('title', event.get('summary', '?'))}' before your meeting.",
                action="news.search",
                action_params={"query": matching},
            ))

    return insights, suggestions
