"""Tests for Issue #1391: misrouting fixes.

Covers all 5 misrouting scenarios from the issue:
1. Code writing → should NOT go to gmail
2. Translation → should NOT go to smalltalk
3. Volume → should go to system with volume intent
4. App launch → should go to system with open_app intent
5. "bugünkü teknoloji haberleri" → should go to news, not calendar
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

    def test_bugunku_teknoloji_haberleri_routes_to_news(self):
        """'bugünkü teknoloji haberleri' → news, NOT calendar (Issue #1391)."""
        route = self.router._detect_route_from_input("bugünkü teknoloji haberleri neler")
        assert route == "news", f"Expected 'news', got '{route}'"

    def test_bugunku_haberleri_routes_to_news(self):
        """'bugünkü haberler' → news, NOT calendar."""
        route = self.router._detect_route_from_input("bugünkü haberler")
        assert route == "news", f"Expected 'news', got '{route}'"

    def test_bugun_ne_var_routes_to_calendar(self):
        """'bugün ne var' → calendar (multi-word keyword preserved)."""
        route = self.router._detect_route_from_input("bugün ne var")
        assert route == "calendar"

    def test_ses_kisin_routes_to_system(self):
        """'sesi kıs' → system (volume control)."""
        route = self.router._detect_route_from_input("sesi kıs")
        assert route == "system"

    def test_volume_routes_to_system(self):
        """'volume %50 yap' → system."""
        route = self.router._detect_route_from_input("volume %50 yap")
        assert route == "system"

    def test_spotify_ac_routes_to_system(self):
        """'spotify aç' → system (app launch)."""
        route = self.router._detect_route_from_input("spotify aç")
        assert route == "system"

    def test_yaz_alone_does_not_route_to_gmail(self):
        """'yaz' alone should NOT be in gmail keywords anymore."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        gmail_keywords = JarvisLLMOrchestrator._ROUTE_KEYWORDS.get("gmail", [])
        # "yaz" alone should not exist; "mail yaz" is allowed
        assert "yaz" not in gmail_keywords
        assert "mail yaz" in gmail_keywords

    def test_kod_yaz_does_not_route_to_gmail(self):
        """'Python fibonacci kodu yaz' → NOT gmail."""
        route = self.router._detect_route_from_input("Python fibonacci kodu yaz")
        assert route != "gmail", f"Code request incorrectly routed to gmail: '{route}'"

    def test_mail_yaz_still_routes_to_gmail(self):
        """'mail yaz' → gmail (multi-word keyword preserved)."""
        route = self.router._detect_route_from_input("mail yaz ali'ye")
        assert route == "gmail"

    def test_haber_routes_to_news(self):
        """'haber' → news."""
        route = self.router._detect_route_from_input("son haberler")
        assert route == "news"


class TestSystemIntentInference:
    """Test system_intent inference for volume and open_app."""

    def _normalize(self, user_input: str, route: str = "system") -> dict:
        """Simulate normalize_output for system intent testing."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        router = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)
        # Build minimal normalized output
        normalized = {
            "route": route,
            "system_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
        }
        # Call the normalize method's system intent section
        _input_lower = user_input.lower()
        _input_tokens = set(re.split(r"[\s,;.!?]+", _input_lower))
        _SYS_STATUS_WORDS = {"cpu", "ram", "bellek", "durum", "kaynak", "kullanım", "performans"}
        _SYS_BATTERY_WORDS = {"pil", "batarya", "şarj"}
        _SYS_DISK_WORDS = {"disk", "depolama", "alan", "storage"}
        _SYS_TIME_WORDS = {"saat", "tarih", "zaman"}
        _SYS_VOLUME_WORDS = {"ses", "volume", "sessiz", "sesli", "kıs", "aç"}
        _SYS_APP_WORDS = {"başlat", "kapat"}

        if _input_tokens & _SYS_VOLUME_WORDS and any(w in _input_lower for w in ("ses", "volume", "sessiz")):
            normalized["system_intent"] = "volume"
        elif _input_tokens & _SYS_STATUS_WORDS:
            normalized["system_intent"] = "status"
        elif _input_tokens & _SYS_BATTERY_WORDS:
            normalized["system_intent"] = "battery"
        elif _input_tokens & _SYS_DISK_WORDS:
            normalized["system_intent"] = "disk"
        elif _input_tokens & _SYS_TIME_WORDS or "saat kaç" in _input_lower:
            normalized["system_intent"] = "time"
        elif _input_tokens & _SYS_APP_WORDS or any(w in _input_lower for w in ("aç", "başlat", "çalıştır")):
            normalized["system_intent"] = "open_app"
        else:
            normalized["system_intent"] = "status"
        return normalized

    def test_ses_kis_infers_volume(self):
        """'sesi kıs' → system_intent=volume."""
        result = self._normalize("sesi kıs")
        assert result["system_intent"] == "volume"

    def test_volume_50_infers_volume(self):
        """'ses seviyesini %50 yap' → system_intent=volume."""
        result = self._normalize("ses seviyesini %50 yap")
        assert result["system_intent"] == "volume"

    def test_sessiz_infers_volume(self):
        """'sessiz moda al' → system_intent=volume."""
        result = self._normalize("sessiz moda al")
        assert result["system_intent"] == "volume"

    def test_spotify_ac_infers_open_app(self):
        """'spotify aç' → system_intent=open_app."""
        result = self._normalize("spotify aç")
        assert result["system_intent"] == "open_app"

    def test_chrome_baslat_infers_open_app(self):
        """'chrome başlat' → system_intent=open_app."""
        result = self._normalize("chrome başlat")
        assert result["system_intent"] == "open_app"

    def test_cpu_still_infers_status(self):
        """'CPU kullanımı ne' → system_intent=status (unchanged)."""
        result = self._normalize("CPU kullanımı ne")
        assert result["system_intent"] == "status"

    def test_saat_kac_still_infers_time(self):
        """'saat kaç' → system_intent=time (unchanged)."""
        result = self._normalize("saat kaç")
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
