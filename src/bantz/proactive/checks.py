"""Built-in proactive checks for the Proactive Intelligence Engine.

Provides the default set of proactive checks:
- Morning Briefing: calendar + weather + mail + assignment summary
- Weather × Calendar: cross-analysis for outdoor events
- Email Digest: periodic unread email summary
- Assignment Tracker: upcoming homework/deadlines

Each check handler receives the check definition and a context dict
containing ``tool_registry`` and ``event_bus``, and returns a ``CheckResult``.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from bantz.proactive.models import (
    CheckResult,
    CheckSchedule,
    CrossAnalysis,
    Insight,
    InsightSeverity,
    ProactiveCheck,
    Suggestion,
)

logger = logging.getLogger(__name__)


# ── Tool Helpers ────────────────────────────────────────────────


def _call_tool(tool_registry: Any, tool_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call a tool from the registry, returning its result dict.

    Returns ``{"ok": False, "error": "..."}`` on failure.
    """
    try:
        tool = tool_registry.get(tool_name)
        if tool is None:
            return {"ok": False, "error": f"Tool '{tool_name}' not found"}
        handler = getattr(tool, "handler", None)
        if handler is None:
            return {"ok": False, "error": f"Tool '{tool_name}' has no handler"}
        result = handler(**(params or {}))
        if isinstance(result, dict):
            return result
        return {"ok": True, "data": result}
    except Exception as e:
        logger.warning("Proactive tool call '%s' failed: %s", tool_name, e)
        return {"ok": False, "error": str(e)}


def _safe_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


# ── Morning Briefing ────────────────────────────────────────────


def morning_briefing_handler(check: ProactiveCheck, ctx: Dict[str, Any]) -> CheckResult:
    """Sabah brifing: takvim + hava + mail + ödev özeti.

    Combines results from multiple tools and produces cross-analysis
    insights (e.g., outdoor meeting + rain warning).
    """
    start = datetime.now()
    tool_registry = ctx.get("tool_registry")
    if not tool_registry:
        return CheckResult(check_name=check.name, ok=False, error="No tool_registry in context")

    tool_results: Dict[str, Any] = {}
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    # 1) Calendar events for today
    calendar_result = _call_tool(tool_registry, "calendar.list_events")
    tool_results["calendar"] = calendar_result
    events = []
    if calendar_result.get("ok"):
        events = calendar_result.get("events", calendar_result.get("data", []))
        if isinstance(events, list):
            n_events = len(events)
            insights.append(Insight(
                message=f"Bugün {n_events} etkinliğiniz var." if n_events else "Bugün takviminiz boş.",
                severity=InsightSeverity.INFO,
                source_tools=["calendar.list_events"],
                data={"event_count": n_events},
            ))

    # 2) Weather forecast
    weather_result = _call_tool(tool_registry, "weather.get_current")
    tool_results["weather"] = weather_result
    weather_data = {}
    if weather_result.get("ok"):
        weather_data = weather_result.get("data", weather_result)
        temp = _safe_get(weather_data, "temperature")
        condition = _safe_get(weather_data, "condition", default="")
        if temp is not None:
            insights.append(Insight(
                message=f"Hava: {temp}°C, {condition}",
                severity=InsightSeverity.INFO,
                source_tools=["weather.get_current"],
                data=weather_data,
            ))

    # 3) Cross-analysis: outdoor events × bad weather
    outdoor_weather_insights, outdoor_suggestions = _cross_analyze_weather_calendar(
        events, weather_data
    )
    insights.extend(outdoor_weather_insights)
    suggestions.extend(outdoor_suggestions)

    # 4) Unread mail count
    mail_result = _call_tool(tool_registry, "gmail.unread_count")
    tool_results["mail"] = mail_result
    if mail_result.get("ok"):
        unread = mail_result.get("unread", mail_result.get("count", 0))
        if isinstance(unread, int) and unread > 0:
            sev = InsightSeverity.WARNING if unread >= 10 else InsightSeverity.INFO
            insights.append(Insight(
                message=f"📧 {unread} okunmamış mail var.",
                severity=sev,
                source_tools=["gmail.unread_count"],
                data={"unread_count": unread},
            ))

    # 5) Build summary
    analysis = CrossAnalysis(
        check_name=check.name,
        insights=insights,
        suggestions=suggestions,
        tool_results=tool_results,
    )

    summary_lines = [f"Günaydın efendim! İşte bugünkü brifing:"]
    for insight in insights:
        summary_lines.append(f"  {insight.icon} {insight.message}")
    for suggestion in suggestions:
        summary_lines.append(f"  💡 {suggestion.text}")

    elapsed = (datetime.now() - start).total_seconds() * 1000

    return CheckResult(
        check_name=check.name,
        ok=True,
        summary="\n".join(summary_lines),
        analysis=analysis,
        raw_data=tool_results,
        duration_ms=elapsed,
    )


# ── Weather × Calendar Cross-Analysis ──────────────────────────


def _cross_analyze_weather_calendar(
    events: Any,
    weather_data: Dict[str, Any],
) -> tuple[List[Insight], List[Suggestion]]:
    """Cross-analyze calendar events with weather conditions.

    Detects scenarios like outdoor meetings during rain.
    """
    insights: List[Insight] = []
    suggestions: List[Suggestion] = []

    if not events or not isinstance(events, list) or not weather_data:
        return insights, suggestions

    condition = str(_safe_get(weather_data, "condition", default="")).lower()
    temp = _safe_get(weather_data, "temperature")

    bad_weather_keywords = {"rain", "snow", "storm", "yağmur", "kar", "fırtına", "thunderstorm"}
    is_bad_weather = any(kw in condition for kw in bad_weather_keywords)
    is_cold = isinstance(temp, (int, float)) and temp < 5
    is_very_hot = isinstance(temp, (int, float)) and temp > 35

    outdoor_keywords = {"dışarı", "outdoor", "park", "bahçe", "garden", "cafe", "kafe",
                        "piknik", "picnic", "yürüyüş", "walk", "koşu", "run", "buluşma"}

    for event in events:
        if not isinstance(event, dict):
            continue
        title = str(event.get("summary", event.get("title", ""))).lower()
        location = str(event.get("location", "")).lower()
        event_time = event.get("start", event.get("time", ""))

        # Check if event seems outdoor
        is_outdoor = any(kw in title or kw in location for kw in outdoor_keywords)

        if is_outdoor and is_bad_weather:
            insights.append(Insight(
                message=f"'{event.get('summary', event.get('title', ''))}' dışarıda ama {condition} bekleniyor!",
                severity=InsightSeverity.WARNING,
                source_tools=["calendar.list_events", "weather.get_current"],
                data={"event": event, "weather_condition": condition},
            ))
            suggestions.append(Suggestion(
                text=f"Toplantıyı online'a çevirebilirim veya erteleyebilirim.",
                action="calendar.update_event",
                action_params={"event_id": event.get("id", "")},
            ))

        if is_outdoor and is_cold:
            insights.append(Insight(
                message=f"'{event.get('summary', event.get('title', ''))}' dışarıda ve sıcaklık {temp}°C — sıcak giyinin!",
                severity=InsightSeverity.INFO,
                source_tools=["calendar.list_events", "weather.get_current"],
            ))

        if is_outdoor and is_very_hot:
            insights.append(Insight(
                message=f"'{event.get('summary', event.get('title', ''))}' dışarıda ve {temp}°C — su almayı unutmayın!",
                severity=InsightSeverity.WARNING,
                source_tools=["calendar.list_events", "weather.get_current"],
            ))

    return insights, suggestions


def weather_calendar_handler(check: ProactiveCheck, ctx: Dict[str, Any]) -> CheckResult:
    """Standalone weather×calendar cross-analysis check.

    This is a lighter version of the morning briefing that focuses
    specifically on weather-related calendar conflicts.
    """
    start = datetime.now()
    tool_registry = ctx.get("tool_registry")
    if not tool_registry:
        return CheckResult(check_name=check.name, ok=False, error="No tool_registry in context")

    tool_results: Dict[str, Any] = {}

    calendar_result = _call_tool(tool_registry, "calendar.list_events")
    tool_results["calendar"] = calendar_result
    events = []
    if calendar_result.get("ok"):
        events = calendar_result.get("events", calendar_result.get("data", []))

    weather_result = _call_tool(tool_registry, "weather.get_current")
    tool_results["weather"] = weather_result
    weather_data = weather_result.get("data", weather_result) if weather_result.get("ok") else {}

    insights, suggestions = _cross_analyze_weather_calendar(events, weather_data)

    if not insights:
        insights.append(Insight(
            message="Hava durumu ile takvim çakışması yok — her şey yolunda!",
            severity=InsightSeverity.INFO,
            source_tools=["calendar.list_events", "weather.get_current"],
        ))

    analysis = CrossAnalysis(
        check_name=check.name,
        insights=insights,
        suggestions=suggestions,
        tool_results=tool_results,
    )

    summary_lines = []
    for insight in insights:
        summary_lines.append(f"{insight.icon} {insight.message}")
    for suggestion in suggestions:
        summary_lines.append(f"💡 {suggestion.text}")

    elapsed = (datetime.now() - start).total_seconds() * 1000

    return CheckResult(
        check_name=check.name,
        ok=True,
        summary="\n".join(summary_lines),
        analysis=analysis,
        raw_data=tool_results,
        duration_ms=elapsed,
    )


# ── Email Digest ────────────────────────────────────────────────


def email_digest_handler(check: ProactiveCheck, ctx: Dict[str, Any]) -> CheckResult:
    """Periodic email digest — unread count + important senders.

    Provides a summary of unread emails with urgency detection.
    """
    start = datetime.now()
    tool_registry = ctx.get("tool_registry")
    if not tool_registry:
        return CheckResult(check_name=check.name, ok=False, error="No tool_registry in context")

    tool_results: Dict[str, Any] = {}
    insights: List[Insight] = []

    # Unread count
    mail_result = _call_tool(tool_registry, "gmail.unread_count")
    tool_results["unread"] = mail_result

    unread = 0
    if mail_result.get("ok"):
        unread = mail_result.get("unread", mail_result.get("count", 0))
        if isinstance(unread, int):
            if unread == 0:
                insights.append(Insight(
                    message="📭 Okunmamış mail yok — inbox sıfır!",
                    severity=InsightSeverity.INFO,
                    source_tools=["gmail.unread_count"],
                ))
            elif unread < 5:
                insights.append(Insight(
                    message=f"📧 {unread} okunmamış mail var.",
                    severity=InsightSeverity.INFO,
                    source_tools=["gmail.unread_count"],
                    data={"unread": unread},
                ))
            else:
                sev = InsightSeverity.CRITICAL if unread >= 20 else InsightSeverity.WARNING
                insights.append(Insight(
                    message=f"📧 {unread} okunmamış mail birikmiş!",
                    severity=sev,
                    source_tools=["gmail.unread_count"],
                    data={"unread": unread},
                ))

    analysis = CrossAnalysis(
        check_name=check.name,
        insights=insights,
        tool_results=tool_results,
    )

    summary = insights[0].message if insights else "Mail kontrolü tamamlandı."
    elapsed = (datetime.now() - start).total_seconds() * 1000

    return CheckResult(
        check_name=check.name,
        ok=True,
        summary=summary,
        analysis=analysis,
        raw_data=tool_results,
        duration_ms=elapsed,
    )


# ── Registry of Built-in Checks ────────────────────────────────


def get_builtin_checks() -> List[ProactiveCheck]:
    """Return all built-in proactive checks.

    These are registered by default when the ProactiveEngine starts.
    """
    return [
        ProactiveCheck(
            name="morning_briefing",
            description="Sabah brifing: takvim + hava + mail özeti + çapraz analiz",
            schedule=CheckSchedule.daily_at(8, 0),
            handler=morning_briefing_handler,
            required_tools=["calendar.list_events", "weather.get_current", "gmail.unread_count"],
            tags=["briefing", "proactive", "daily"],
        ),
        ProactiveCheck(
            name="weather_calendar",
            description="Hava durumu × takvim çapraz kontrolü",
            schedule=CheckSchedule.every(hours=3),
            handler=weather_calendar_handler,
            required_tools=["calendar.list_events", "weather.get_current"],
            tags=["weather", "calendar", "cross-analysis"],
        ),
        ProactiveCheck(
            name="email_digest",
            description="Periyodik mail özeti",
            schedule=CheckSchedule.every(hours=2),
            handler=email_digest_handler,
            required_tools=["gmail.unread_count"],
            tags=["email", "digest"],
        ),
    ]
