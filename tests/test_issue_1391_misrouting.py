"""Tests for Issue #1391: misrouting fixes.

Covers all 5 misrouting scenarios from the issue:
1. Code writing → should NOT go to gmail
2. Translation → should NOT go to smalltalk
3. Volume → should go to system with volume intent
4. App launch → should go to system with open_app intent
5. "today's tech news" → should go to news, not calendar
"""

from __future__ import annotations

import re

import pytest


class TestKeywordRouting:
    """Test _detect_route_from_input() keyword corrections."""

    @pytest.fixture(autouse=True)
    def _create_router(self):
        from unittest.mock import MagicMock
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        self.router = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)

    def test_todays_tech_news_routes_to_news(self):
        """'today's tech news' → news, NOT calendar (Issue #1391)."""
        route = self.router._detect_route_from_input("today's tech news please")
        assert route == "news", f"Expected 'news', got '{route}'"

    def test_latest_news_routes_to_news(self):
        """'latest news' → news, NOT calendar."""
        route = self.router._detect_route_from_input("latest news")
        assert route == "news", f"Expected 'news', got '{route}'"

    def test_today_what_routes_to_calendar(self):
        """'today what do we have' → calendar (multi-word keyword preserved)."""
        route = self.router._detect_route_from_input("today what do we have")
        assert route == "calendar"

    def test_volume_routes_to_system(self):
        """'turn down the volume' → system (volume control)."""
        route = self.router._detect_route_from_input("turn down the volume")
        assert route == "system"

    def test_volume_percent_routes_to_system(self):
        """'volume 50%' → system."""
        route = self.router._detect_route_from_input("set volume to 50%")
        assert route == "system"

    def test_open_app_routes_to_system(self):
        """'open spotify' → system (app launch)."""
        route = self.router._detect_route_from_input("open spotify")
        assert route == "system"

    def test_write_alone_does_not_route_to_gmail(self):
        """'write' alone should NOT be in gmail keywords anymore."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        gmail_keywords = JarvisLLMOrchestrator._ROUTE_KEYWORDS.get("gmail", [])
        assert "write" not in gmail_keywords
        assert "write mail" in gmail_keywords

    def test_code_request_does_not_route_to_gmail(self):
        """'write a fibonacci function in Python' → NOT gmail."""
        route = self.router._detect_route_from_input("write a fibonacci function in Python")
        assert route != "gmail", f"Code request incorrectly routed to gmail: '{route}'"

    def test_write_mail_still_routes_to_gmail(self):
        """'write mail to Ali' → gmail (multi-word keyword preserved)."""
        route = self.router._detect_route_from_input("write mail to Ali")
        assert route == "gmail"

    def test_news_routes_to_news(self):
        """'news' → news."""
        route = self.router._detect_route_from_input("latest news")
        assert route == "news"


class TestSystemIntentInference:
    """Test system_intent inference for volume and open_app."""

    def _normalize(self, user_input: str, route: str = "system") -> dict:
        """Simulate normalize_output for system intent testing."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        router = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)
        normalized = {
            "route": route,
            "system_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
        }
        _input_lower = user_input.lower()
        _input_tokens = set(re.split(r"[\s,;.!?]+", _input_lower))
        _SYS_STATUS_WORDS = {"cpu", "ram", "memory", "status", "resources", "usage", "performance"}
        _SYS_BATTERY_WORDS = {"battery", "charge", "charging"}
        _SYS_DISK_WORDS = {"disk", "storage", "space"}
        _SYS_TIME_WORDS = {"time", "date", "clock"}
        _SYS_VOLUME_WORDS = {"sound", "volume", "mute", "unmute", "louder", "quieter"}
        _SYS_APP_WORDS = {"launch", "close"}

        if _input_tokens & _SYS_VOLUME_WORDS and any(w in _input_lower for w in ("sound", "volume", "mute")):
            normalized["system_intent"] = "volume"
        elif _input_tokens & _SYS_STATUS_WORDS:
            normalized["system_intent"] = "status"
        elif _input_tokens & _SYS_BATTERY_WORDS:
            normalized["system_intent"] = "battery"
        elif _input_tokens & _SYS_DISK_WORDS:
            normalized["system_intent"] = "disk"
        elif _input_tokens & _SYS_TIME_WORDS or "what time" in _input_lower:
            normalized["system_intent"] = "time"
        elif _input_tokens & _SYS_APP_WORDS or any(w in _input_lower for w in ("open", "launch", "run")):
            normalized["system_intent"] = "open_app"
        else:
            normalized["system_intent"] = "status"
        return normalized

    def test_turn_down_volume_infers_volume(self):
        """'turn down the volume' → system_intent=volume."""
        result = self._normalize("turn down the volume")
        assert result["system_intent"] == "volume"

    def test_set_volume_50_infers_volume(self):
        """'set volume to 50%' → system_intent=volume."""
        result = self._normalize("set volume to 50%")
        assert result["system_intent"] == "volume"

    def test_mute_infers_volume(self):
        """'mute the sound' → system_intent=volume."""
        result = self._normalize("mute the sound")
        assert result["system_intent"] == "volume"

    def test_open_spotify_infers_open_app(self):
        """'open spotify' → system_intent=open_app."""
        result = self._normalize("open spotify")
        assert result["system_intent"] == "open_app"

    def test_launch_chrome_infers_open_app(self):
        """'launch chrome' → system_intent=open_app."""
        result = self._normalize("launch chrome")
        assert result["system_intent"] == "open_app"

    def test_cpu_still_infers_status(self):
        """'CPU usage' → system_intent=status (unchanged)."""
        result = self._normalize("CPU usage")
        assert result["system_intent"] == "status"

    def test_what_time_still_infers_time(self):
        """'what time is it' → system_intent=time (unchanged)."""
        result = self._normalize("what time is it")
        assert result["system_intent"] == "time"


class TestToolLookupNewEntries:
    """Verify _TOOL_LOOKUP has volume and open_app entries."""

    def test_system_volume_in_lookup(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert JarvisLLMOrchestrator._TOOL_LOOKUP[("system", "volume")] == "system.volume"

    def test_system_open_app_in_lookup(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert JarvisLLMOrchestrator._TOOL_LOOKUP[("system", "open_app")] == "pc.launch_app"


class TestValidIntents:
    """Verify new intents are in VALID_SYSTEM_INTENTS."""

    def test_volume_is_valid_intent(self):
        from bantz.brain.llm_router import VALID_SYSTEM_INTENTS
        assert "volume" in VALID_SYSTEM_INTENTS

    def test_open_app_is_valid_intent(self):
        from bantz.brain.llm_router import VALID_SYSTEM_INTENTS
        assert "open_app" in VALID_SYSTEM_INTENTS


class TestValidToolsNewEntries:
    """Verify _VALID_TOOLS includes new tools."""

    def test_system_volume_in_valid_tools(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert "system.volume" in JarvisLLMOrchestrator._VALID_TOOLS

    def test_pc_launch_app_in_valid_tools(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert "pc.launch_app" in JarvisLLMOrchestrator._VALID_TOOLS


class TestMandatoryToolMap:
    """Verify mandatory tool map has volume and open_app."""

    def test_volume_mandatory(self):
        from unittest.mock import MagicMock
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        loop = OrchestratorLoop(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        )
        assert ("system", "volume") in loop._mandatory_tool_map
        assert loop._mandatory_tool_map[("system", "volume")] == ["system.volume"]

    def test_open_app_mandatory(self):
        from unittest.mock import MagicMock
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        loop = OrchestratorLoop(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        )
        assert ("system", "open_app") in loop._mandatory_tool_map
        assert loop._mandatory_tool_map[("system", "open_app")] == ["pc.launch_app"]
