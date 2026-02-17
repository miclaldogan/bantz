"""Tests for weather tools (Issue #838)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from bantz.tools.weather_tools import (
    weather_get_current_tool,
    weather_get_forecast_tool,
    weather_check_outdoor_tool,
    _parse_wttr_current,
    _parse_wttr_forecast,
    _safe_float,
    _safe_int,
    _deg_to_compass,
)


# ── Sample wttr.in response ───────────────────────────────────

SAMPLE_WTTR_RESPONSE = {
    "current_condition": [{
        "temp_C": "12",
        "FeelsLikeC": "10",
        "humidity": "65",
        "windspeedKmph": "15",
        "winddir16Point": "NE",
        "uvIndex": "3",
        "visibility": "10",
        "pressure": "1013",
        "weatherDesc": [{"value": "Partly cloudy"}],
    }],
    "nearest_area": [{
        "areaName": [{"value": "Istanbul"}],
        "country": [{"value": "Turkey"}],
    }],
    "weather": [
        {
            "date": "2026-02-17",
            "mintempC": "5",
            "maxtempC": "14",
            "uvIndex": "3",
            "hourly": [
                {"chanceofrain": "20", "weatherDesc": [{"value": "Sunny"}]},
                {"chanceofrain": "15", "weatherDesc": [{"value": "Partly cloudy"}]},
                {"chanceofrain": "40", "weatherDesc": [{"value": "Cloudy"}]},
            ],
        },
        {
            "date": "2026-02-18",
            "mintempC": "3",
            "maxtempC": "11",
            "uvIndex": "2",
            "hourly": [
                {"chanceofrain": "70", "weatherDesc": [{"value": "Light rain"}]},
                {"chanceofrain": "80", "weatherDesc": [{"value": "Rain"}]},
                {"chanceofrain": "60", "weatherDesc": [{"value": "Overcast"}]},
            ],
        },
        {
            "date": "2026-02-19",
            "mintempC": "6",
            "maxtempC": "15",
            "uvIndex": "4",
            "hourly": [
                {"chanceofrain": "10", "weatherDesc": [{"value": "Sunny"}]},
                {"chanceofrain": "5", "weatherDesc": [{"value": "Clear"}]},
            ],
        },
    ],
}


# ── Parser tests ───────────────────────────────────────────────


class TestParseWttrCurrent:
    """Tests for _parse_wttr_current."""

    def test_basic_parsing(self):
        result = _parse_wttr_current(SAMPLE_WTTR_RESPONSE, "Istanbul")
        assert result["ok"] is True
        assert result["temperature"] == 12.0
        assert result["feels_like"] == 10.0
        assert result["humidity"] == 65
        assert result["condition"] == "Partly cloudy"
        assert result["wind_speed_kmh"] == 15.0
        assert result["wind_direction"] == "NE"
        assert result["location"] == "Istanbul"

    def test_rain_probability_max(self):
        result = _parse_wttr_current(SAMPLE_WTTR_RESPONSE, "Istanbul")
        # max hourly chanceofrain is 40 → 0.4
        assert result["rain_probability"] == 0.4

    def test_missing_current_condition(self):
        data = {"current_condition": [], "nearest_area": [], "weather": []}
        result = _parse_wttr_current(data, "Test")
        assert result["ok"] is True
        assert result["temperature"] is None
        assert result["condition"] == ""

    def test_empty_data(self):
        result = _parse_wttr_current({}, "X")
        assert result["ok"] is True
        assert result["rain_probability"] == 0.0


class TestParseWttrForecast:
    """Tests for _parse_wttr_forecast."""

    def test_forecast_days(self):
        result = _parse_wttr_forecast(SAMPLE_WTTR_RESPONSE, "Istanbul", 3)
        assert result["ok"] is True
        assert result["days"] == 3
        assert len(result["forecast"]) == 3

    def test_forecast_limited_days(self):
        result = _parse_wttr_forecast(SAMPLE_WTTR_RESPONSE, "Istanbul", 2)
        assert result["days"] == 2

    def test_forecast_rain_probability(self):
        result = _parse_wttr_forecast(SAMPLE_WTTR_RESPONSE, "Istanbul", 3)
        # Day 2 (2026-02-18) has max 80% → 0.8
        day2 = result["forecast"][1]
        assert day2["rain_probability"] == 0.8

    def test_forecast_date_and_temps(self):
        result = _parse_wttr_forecast(SAMPLE_WTTR_RESPONSE, "Istanbul", 1)
        day1 = result["forecast"][0]
        assert day1["date"] == "2026-02-17"
        assert day1["temp_min"] == 5.0
        assert day1["temp_max"] == 14.0


# ── Utility tests ──────────────────────────────────────────────


class TestUtilities:
    """Tests for helper functions."""

    def test_safe_float_valid(self):
        assert _safe_float("12.5") == 12.5
        assert _safe_float(7) == 7.0

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_invalid(self):
        assert _safe_float("abc") is None

    def test_safe_int_valid(self):
        assert _safe_int("42") == 42

    def test_safe_int_none(self):
        assert _safe_int(None) is None

    def test_deg_to_compass(self):
        assert _deg_to_compass(0) == "N"
        assert _deg_to_compass(90) == "E"
        assert _deg_to_compass(180) == "S"
        assert _deg_to_compass(270) == "W"
        assert _deg_to_compass(45) == "NE"


# ── Tool handler tests ────────────────────────────────────────


class TestWeatherGetCurrentTool:
    """Tests for weather_get_current_tool."""

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_success_wttr(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_WTTR_RESPONSE
        result = weather_get_current_tool(location="Istanbul")
        assert result["ok"] is True
        assert result["temperature"] == 12.0
        assert result["condition"] == "Partly cloudy"
        mock_fetch.assert_called_once()

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_default_location(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_WTTR_RESPONSE
        weather_get_current_tool()
        # Should use default location
        mock_fetch.assert_called_once()

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_failure_returns_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("Network error")
        result = weather_get_current_tool(location="Istanbul")
        assert result["ok"] is False
        assert "error" in result

    @patch("bantz.tools.weather_tools._OWM_API_KEY", "test-key")
    @patch("bantz.tools.weather_tools._fetch_owm_current")
    def test_owm_preferred_when_key_set(self, mock_owm):
        mock_owm.return_value = {
            "main": {"temp": 15, "feels_like": 13, "humidity": 60, "pressure": 1010},
            "wind": {"speed": 5, "deg": 180},
            "weather": [{"description": "clear sky"}],
            "name": "Istanbul",
            "visibility": 10000,
        }
        result = weather_get_current_tool(location="Istanbul")
        assert result["ok"] is True
        assert result["temperature"] == 15
        mock_owm.assert_called_once()


class TestWeatherGetForecastTool:
    """Tests for weather_get_forecast_tool."""

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_success(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_WTTR_RESPONSE
        result = weather_get_forecast_tool(location="Istanbul", days=3)
        assert result["ok"] is True
        assert result["days"] == 3
        assert len(result["forecast"]) == 3

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_days_clamped(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_WTTR_RESPONSE
        result = weather_get_forecast_tool(location="Istanbul", days=10)
        # Should be clamped to 5 (but only 3 days in sample)
        assert result["ok"] is True
        assert result["days"] <= 5

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_failure(self, mock_fetch):
        mock_fetch.side_effect = Exception("API down")
        result = weather_get_forecast_tool(location="X")
        assert result["ok"] is False


class TestWeatherCheckOutdoorTool:
    """Tests for weather_check_outdoor_tool."""

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_safe_weather(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_WTTR_RESPONSE
        result = weather_check_outdoor_tool(location="Istanbul")
        assert result["ok"] is True
        assert result["safe"] is True

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_rainy_day_unsafe(self, mock_fetch):
        rainy = json.loads(json.dumps(SAMPLE_WTTR_RESPONSE))
        rainy["weather"][0]["hourly"] = [
            {"chanceofrain": "85", "weatherDesc": [{"value": "Heavy rain"}]},
        ]
        mock_fetch.return_value = rainy
        result = weather_check_outdoor_tool(location="Istanbul")
        assert result["ok"] is True
        assert result["safe"] is False
        assert len(result["reasons"]) > 0

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_storm_unsafe(self, mock_fetch):
        stormy = json.loads(json.dumps(SAMPLE_WTTR_RESPONSE))
        stormy["current_condition"][0]["weatherDesc"] = [{"value": "Thunderstorm"}]
        mock_fetch.return_value = stormy
        result = weather_check_outdoor_tool(location="Istanbul")
        assert result["ok"] is True
        assert result["safe"] is False

    @patch("bantz.tools.weather_tools._fetch_wttr")
    def test_fetch_failure(self, mock_fetch):
        mock_fetch.side_effect = Exception("timeout")
        result = weather_check_outdoor_tool(location="X")
        assert result["ok"] is False
        assert result["safe"] is None


# ── Cross-analysis test ───────────────────────────────────────


class TestWeatherCalendarCrossAnalysis:
    """Test the weather+calendar cross-analysis rule."""

    def test_bad_weather_outdoor_event(self):
        from bantz.proactive.cross_analyzer import _rule_weather_calendar_cross

        tool_results = {
            "weather": {
                "temperature": 5,
                "condition": "rain",
                "rain_probability": 0.8,
            },
            "calendar": {
                "events": [
                    {"title": "Parkta yürüyüş", "location": "Maçka Parkı", "start": "14:00"},
                ],
            },
        }
        insights, suggestions = _rule_weather_calendar_cross(tool_results)
        assert len(insights) >= 1
        assert "park" in insights[0].message.lower() or "yürüyüş" in insights[0].message.lower()
        assert len(suggestions) >= 1

    def test_good_weather_no_warning(self):
        from bantz.proactive.cross_analyzer import _rule_weather_calendar_cross

        tool_results = {
            "weather": {
                "temperature": 22,
                "condition": "sunny",
                "rain_probability": 0.1,
            },
            "calendar": {
                "events": [
                    {"title": "Parkta piknik", "location": "Park", "start": "12:00"},
                ],
            },
        }
        insights, suggestions = _rule_weather_calendar_cross(tool_results)
        assert len(insights) == 0

    def test_indoor_event_no_warning(self):
        from bantz.proactive.cross_analyzer import _rule_weather_calendar_cross

        tool_results = {
            "weather": {
                "temperature": 5,
                "condition": "rain",
                "rain_probability": 0.9,
            },
            "calendar": {
                "events": [
                    {"title": "Team meeting", "location": "Office"},
                ],
            },
        }
        insights, suggestions = _rule_weather_calendar_cross(tool_results)
        assert len(insights) == 0


# ── Router integration test ───────────────────────────────────

class TestWeatherRouting:
    """Test that weather route is properly configured."""

    def test_weather_in_valid_routes(self):
        from bantz.brain.llm_router import VALID_ROUTES
        assert "weather" in VALID_ROUTES

    def test_weather_intent_in_valid_intents(self):
        from bantz.brain.llm_router import VALID_WEATHER_INTENTS
        assert "current" in VALID_WEATHER_INTENTS
        assert "forecast" in VALID_WEATHER_INTENTS
        assert "outdoor" in VALID_WEATHER_INTENTS

    def test_weather_tools_in_risk_metadata(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("weather.get_current") == ToolRisk.SAFE
        assert get_tool_risk("weather.get_forecast") == ToolRisk.SAFE
        assert get_tool_risk("weather.check_outdoor") == ToolRisk.SAFE

    def test_orchestrator_output_has_weather_intent(self):
        from bantz.brain.llm_router import OrchestratorOutput
        out = OrchestratorOutput(
            route="weather", calendar_intent="none", slots={},
            confidence=0.9, tool_plan=[], assistant_reply="",
            weather_intent="current",
        )
        assert out.intent == "current"

    def test_force_tool_plan_weather(self):
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.tool_plan_sanitizer import force_tool_plan

        out = OrchestratorOutput(
            route="weather", calendar_intent="none", slots={},
            confidence=0.9, tool_plan=[], assistant_reply="",
            weather_intent="forecast",
        )
        result = force_tool_plan(out, {}, {})
        assert "weather.get_forecast" in result.tool_plan

    def test_force_tool_plan_weather_default(self):
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.tool_plan_sanitizer import force_tool_plan

        out = OrchestratorOutput(
            route="weather", calendar_intent="none", slots={},
            confidence=0.9, tool_plan=[], assistant_reply="",
            weather_intent="current",
        )
        result = force_tool_plan(out, {}, {})
        assert "weather.get_current" in result.tool_plan
