"""Weather tools — registered handlers for the tool registry (Issue #838).

Provides the following tools:
    weather.get_current   — Get current weather for a location
    weather.get_forecast  — Get 5-day forecast for a location
    weather.check_outdoor — Check outdoor safety (rain/storm/cold/heat)

Uses wttr.in (free, no API key required) with optional OpenWeatherMap
fallback when ``BANTZ_WEATHER_API_KEY`` is set.

All tools return structured dicts suitable for the finalizer LLM
to compose natural language responses.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "weather_get_current_tool",
    "weather_get_forecast_tool",
    "weather_check_outdoor_tool",
]

# ── Defaults ────────────────────────────────────────────────────

_DEFAULT_LOCATION = os.getenv("BANTZ_WEATHER_LOCATION", "Istanbul")
_OWM_API_KEY = os.getenv("BANTZ_WEATHER_API_KEY", "")
_REQUEST_TIMEOUT = 8  # seconds


# ── Internal helpers ────────────────────────────────────────────


def _fetch_wttr(location: str) -> Dict[str, Any]:
    """Fetch weather data from wttr.in JSON API."""
    url = f"https://wttr.in/{urllib.request.quote(location)}?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": "Bantz/1.0"})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read())


def _fetch_owm_current(location: str) -> Dict[str, Any]:
    """Fetch current weather from OpenWeatherMap API."""
    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?q={urllib.request.quote(location)}"
        f"&appid={_OWM_API_KEY}&units=metric&lang=tr"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Bantz/1.0"})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read())


def _fetch_owm_forecast(location: str) -> Dict[str, Any]:
    """Fetch 5-day forecast from OpenWeatherMap API."""
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?q={urllib.request.quote(location)}"
        f"&appid={_OWM_API_KEY}&units=metric&lang=tr"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Bantz/1.0"})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read())


def _parse_wttr_current(data: Dict[str, Any], location: str) -> Dict[str, Any]:
    """Parse wttr.in JSON into a standardized weather dict."""
    current = data.get("current_condition", [{}])
    if isinstance(current, list) and current:
        current = current[0]
    else:
        current = {}

    nearest = data.get("nearest_area", [{}])
    if isinstance(nearest, list) and nearest:
        nearest = nearest[0]
    else:
        nearest = {}

    area_name = location
    area_vals = nearest.get("areaName", [])
    if isinstance(area_vals, list) and area_vals:
        area_name = area_vals[0].get("value", location)

    desc_vals = current.get("weatherDesc", [])
    description = ""
    if isinstance(desc_vals, list) and desc_vals:
        description = desc_vals[0].get("value", "")

    # Compute rain probability from hourly data if available
    rain_prob = 0.0
    today_weather = data.get("weather", [])
    if isinstance(today_weather, list) and today_weather:
        hourly = today_weather[0].get("hourly", [])
        if isinstance(hourly, list) and hourly:
            probs = []
            for h in hourly:
                try:
                    probs.append(float(h.get("chanceofrain", 0)))
                except (ValueError, TypeError):
                    pass
            if probs:
                rain_prob = max(probs) / 100.0

    return {
        "ok": True,
        "location": area_name,
        "temperature": _safe_float(current.get("temp_C")),
        "feels_like": _safe_float(current.get("FeelsLikeC")),
        "condition": description,
        "humidity": _safe_int(current.get("humidity")),
        "wind_speed_kmh": _safe_float(current.get("windspeedKmph")),
        "wind_direction": current.get("winddir16Point", ""),
        "rain_probability": round(rain_prob, 2),
        "uv_index": _safe_int(current.get("uvIndex")),
        "visibility_km": _safe_float(current.get("visibility")),
        "pressure_mb": _safe_float(current.get("pressure")),
        "alerts": [],
    }


def _parse_wttr_forecast(data: Dict[str, Any], location: str, days: int) -> Dict[str, Any]:
    """Parse wttr.in JSON into a standardized forecast dict."""
    weather_days = data.get("weather", [])
    forecast_list: List[Dict[str, Any]] = []

    for day_data in weather_days[:days]:
        desc = ""
        hourly = day_data.get("hourly", [])
        if isinstance(hourly, list) and hourly:
            # Use mid-day description
            mid = hourly[len(hourly) // 2] if hourly else {}
            desc_vals = mid.get("weatherDesc", [])
            if isinstance(desc_vals, list) and desc_vals:
                desc = desc_vals[0].get("value", "")

            # Max rain probability
            rain_probs = []
            for h in hourly:
                try:
                    rain_probs.append(float(h.get("chanceofrain", 0)))
                except (ValueError, TypeError):
                    pass
            rain_prob = max(rain_probs) / 100.0 if rain_probs else 0.0
        else:
            rain_prob = 0.0

        forecast_list.append({
            "date": day_data.get("date", ""),
            "temp_min": _safe_float(day_data.get("mintempC")),
            "temp_max": _safe_float(day_data.get("maxtempC")),
            "condition": desc,
            "rain_probability": round(rain_prob, 2),
            "uv_index": _safe_int(day_data.get("uvIndex")),
        })

    return {
        "ok": True,
        "location": location,
        "days": len(forecast_list),
        "forecast": forecast_list,
    }


def _parse_owm_current(data: Dict[str, Any], location: str) -> Dict[str, Any]:
    """Parse OWM current weather response."""
    main = data.get("main", {})
    wind = data.get("wind", {})
    weather = data.get("weather", [{}])
    desc = weather[0].get("description", "") if weather else ""

    # OWM doesn't provide rain probability in current endpoint
    rain = data.get("rain", {})
    rain_1h = rain.get("1h", 0) if isinstance(rain, dict) else 0
    rain_prob = min(1.0, rain_1h / 5.0)  # rough heuristic

    return {
        "ok": True,
        "location": data.get("name", location),
        "temperature": main.get("temp"),
        "feels_like": main.get("feels_like"),
        "condition": desc,
        "humidity": main.get("humidity"),
        "wind_speed_kmh": round((wind.get("speed", 0) or 0) * 3.6, 1),
        "wind_direction": _deg_to_compass(wind.get("deg", 0)),
        "rain_probability": round(rain_prob, 2),
        "uv_index": None,
        "visibility_km": round((data.get("visibility", 10000) or 10000) / 1000, 1),
        "pressure_mb": main.get("pressure"),
        "alerts": [],
    }


def _parse_owm_forecast(data: Dict[str, Any], location: str, days: int) -> Dict[str, Any]:
    """Parse OWM 5-day forecast into daily summaries."""
    from collections import defaultdict

    daily: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "temps": [], "descs": [], "rain_probs": [],
    })

    for item in data.get("list", []):
        dt_txt = item.get("dt_txt", "")
        date_str = dt_txt[:10] if dt_txt else ""
        if not date_str:
            continue
        main = item.get("main", {})
        weather = item.get("weather", [{}])
        pop = item.get("pop", 0)

        daily[date_str]["temps"].append(main.get("temp", 0))
        daily[date_str]["descs"].append(
            weather[0].get("description", "") if weather else ""
        )
        daily[date_str]["rain_probs"].append(pop)

    forecast_list = []
    for date_str in sorted(daily.keys())[:days]:
        d = daily[date_str]
        temps = d["temps"]
        forecast_list.append({
            "date": date_str,
            "temp_min": round(min(temps), 1) if temps else None,
            "temp_max": round(max(temps), 1) if temps else None,
            "condition": d["descs"][len(d["descs"]) // 2] if d["descs"] else "",
            "rain_probability": round(max(d["rain_probs"]) if d["rain_probs"] else 0, 2),
            "uv_index": None,
        })

    return {
        "ok": True,
        "location": location,
        "days": len(forecast_list),
        "forecast": forecast_list,
    }


# ── Utility ─────────────────────────────────────────────────────


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _deg_to_compass(deg: float) -> str:
    """Convert wind degrees to 16-point compass direction."""
    directions = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    idx = round(deg / 22.5) % 16
    return directions[idx]


# ── Public tool handlers ────────────────────────────────────────


def weather_get_current_tool(
    location: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Get current weather for a location.

    Parameters
    ----------
    location:
        City name (defaults to ``BANTZ_WEATHER_LOCATION`` or Istanbul).

    Returns
    -------
    Dict with temperature, condition, humidity, wind, rain_probability, etc.
    """
    loc = location.strip() or _DEFAULT_LOCATION
    logger.info("[weather] get_current for %s", loc)

    # Try OWM first if key is available, else wttr.in
    if _OWM_API_KEY:
        try:
            data = _fetch_owm_current(loc)
            return _parse_owm_current(data, loc)
        except Exception as e:
            logger.warning("[weather] OWM failed, falling back to wttr.in: %s", e)

    try:
        data = _fetch_wttr(loc)
        return _parse_wttr_current(data, loc)
    except Exception as e:
        logger.error("[weather] wttr.in also failed: %s", e)
        return {
            "ok": False,
            "error": f"Weather data unavailable for {loc}: {e}",
            "location": loc,
        }


def weather_get_forecast_tool(
    location: str = "",
    days: int = 5,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Get multi-day weather forecast.

    Parameters
    ----------
    location:
        City name (defaults to ``BANTZ_WEATHER_LOCATION`` or Istanbul).
    days:
        Number of days (1-5, default 5).

    Returns
    -------
    Dict with daily forecast list.
    """
    loc = location.strip() or _DEFAULT_LOCATION
    days = max(1, min(5, days))
    logger.info("[weather] get_forecast for %s, %d days", loc, days)

    if _OWM_API_KEY:
        try:
            data = _fetch_owm_forecast(loc)
            return _parse_owm_forecast(data, loc, days)
        except Exception as e:
            logger.warning("[weather] OWM forecast failed, falling back: %s", e)

    try:
        data = _fetch_wttr(loc)
        return _parse_wttr_forecast(data, loc, days)
    except Exception as e:
        logger.error("[weather] forecast failed: %s", e)
        return {
            "ok": False,
            "error": f"Forecast unavailable for {loc}: {e}",
            "location": loc,
        }


def weather_check_outdoor_tool(
    location: str = "",
    date: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Check outdoor safety for a location/date.

    Evaluates rain probability, wind speed, temperature extremes,
    and storm conditions to determine if outdoor activities are safe.

    Parameters
    ----------
    location:
        City name.
    date:
        Date to check (YYYY-MM-DD). Defaults to today.

    Returns
    -------
    Dict with safe (bool), reason, suggestion.
    """
    loc = location.strip() or _DEFAULT_LOCATION
    logger.info("[weather] check_outdoor for %s, date=%s", loc, date)

    try:
        data = _fetch_wttr(loc)
    except Exception as e:
        return {
            "ok": False,
            "safe": None,
            "error": f"Cannot check outdoor safety: {e}",
        }

    current_result = _parse_wttr_current(data, loc)
    if not current_result.get("ok"):
        return {"ok": False, "safe": None, "error": "Cannot parse weather data"}

    # Check forecast for target date if provided
    forecast_result = _parse_wttr_forecast(data, loc, 3)
    target_day = None
    if date and forecast_result.get("ok"):
        for day in forecast_result.get("forecast", []):
            if day.get("date") == date:
                target_day = day
                break

    # Use target day or current conditions
    temp = current_result.get("temperature")
    condition = (current_result.get("condition") or "").lower()
    rain_prob = current_result.get("rain_probability", 0)
    wind = current_result.get("wind_speed_kmh", 0) or 0

    if target_day:
        temp = target_day.get("temp_max", temp)
        condition = (target_day.get("condition") or condition).lower()
        rain_prob = target_day.get("rain_probability", rain_prob)

    # Safety evaluation
    reasons: List[str] = []
    safe = True

    storm_kw = {"storm", "thunder", "tornado", "hail", "blizzard"}
    if any(kw in condition for kw in storm_kw):
        safe = False
        reasons.append(f"Severe weather: {condition}")

    if rain_prob > 0.7:
        safe = False
        reasons.append(f"High rain probability: {int(rain_prob * 100)}%")

    if isinstance(temp, (int, float)):
        if temp <= -5:
            safe = False
            reasons.append(f"Extreme cold: {temp}°C")
        elif temp >= 40:
            safe = False
            reasons.append(f"Extreme heat: {temp}°C")

    if wind > 60:
        safe = False
        reasons.append(f"Strong wind: {wind} km/h")

    suggestion = ""
    if not safe:
        suggestion = "Consider rescheduling outdoor plans or take precautions."
    elif rain_prob > 0.4:
        suggestion = "Outdoor conditions are okay but bring an umbrella."

    return {
        "ok": True,
        "safe": safe,
        "location": loc,
        "reasons": reasons,
        "suggestion": suggestion,
        "temperature": temp,
        "condition": condition,
        "rain_probability": rain_prob,
        "wind_speed_kmh": wind,
    }
