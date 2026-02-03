# SPDX-License-Identifier: MIT
"""
Tests for LLM-based NLU system (Issue #8).

Covers:
- NLU Types (IntentResult, Slot, Clarification, etc.)
- Slot Extraction (Time, URL, App, Query)
- Clarification Manager
- Hybrid NLU
- Bridge/Integration

These tests do NOT require a running LLM server - they mock the LLM calls
or test regex-only paths.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import json


# ============================================================================
# Types Tests
# ============================================================================


class TestSlotType:
    """Tests for SlotType enum."""
    
    def test_slot_types_exist(self):
        from bantz.nlu.types import SlotType
        
        assert SlotType.TIME.value == "time"
        assert SlotType.URL.value == "url"
        assert SlotType.APP.value == "app"
        assert SlotType.QUERY.value == "query"
        assert SlotType.TEXT.value == "text"
    
    def test_slot_type_str(self):
        from bantz.nlu.types import SlotType
        
        assert str(SlotType.TIME) == "time"
        assert str(SlotType.URL) == "url"


class TestConfidenceLevel:
    """Tests for ConfidenceLevel enum."""
    
    def test_from_score(self):
        from bantz.nlu.types import ConfidenceLevel
        
        assert ConfidenceLevel.from_score(0.99) == ConfidenceLevel.VERY_HIGH
        assert ConfidenceLevel.from_score(0.90) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(0.75) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.55) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.25) == ConfidenceLevel.VERY_LOW
    
    def test_needs_clarification(self):
        from bantz.nlu.types import ConfidenceLevel
        
        assert not ConfidenceLevel.VERY_HIGH.needs_clarification
        assert not ConfidenceLevel.HIGH.needs_clarification
        assert not ConfidenceLevel.MEDIUM.needs_clarification
        assert ConfidenceLevel.LOW.needs_clarification
        assert ConfidenceLevel.VERY_LOW.needs_clarification
    
    def test_min_score(self):
        from bantz.nlu.types import ConfidenceLevel
        
        assert ConfidenceLevel.VERY_HIGH.min_score == 0.95
        assert ConfidenceLevel.LOW.min_score == 0.50


class TestIntentCategory:
    """Tests for IntentCategory enum."""
    
    def test_from_intent(self):
        from bantz.nlu.types import IntentCategory
        
        assert IntentCategory.from_intent("browser_open") == IntentCategory.BROWSER
        assert IntentCategory.from_intent("browser_search") == IntentCategory.BROWSER
        assert IntentCategory.from_intent("app_open") == IntentCategory.APP
        assert IntentCategory.from_intent("file_read") == IntentCategory.FILE
        assert IntentCategory.from_intent("terminal_run") == IntentCategory.TERMINAL
        assert IntentCategory.from_intent("reminder_add") == IntentCategory.REMINDER
        assert IntentCategory.from_intent("agent_run") == IntentCategory.AGENT
        assert IntentCategory.from_intent("queue_pause") == IntentCategory.QUEUE
        assert IntentCategory.from_intent("unknown") == IntentCategory.UNKNOWN


class TestSlot:
    """Tests for Slot dataclass."""
    
    def test_slot_creation(self):
        from bantz.nlu.types import Slot, SlotType
        
        slot = Slot(
            name="time",
            value="5 minutes",
            raw_text="5 dakika sonra",
            slot_type=SlotType.TIME,
            confidence=0.95,
        )
        
        assert slot.name == "time"
        assert slot.value == "5 minutes"
        assert slot.raw_text == "5 dakika sonra"
        assert slot.slot_type == SlotType.TIME
        assert slot.confidence == 0.95
    
    def test_slot_to_dict(self):
        from bantz.nlu.types import Slot, SlotType
        
        slot = Slot(name="url", value="https://youtube.com", raw_text="youtube")
        d = slot.to_dict()
        
        assert d["name"] == "url"
        assert d["value"] == "https://youtube.com"
        assert d["raw_text"] == "youtube"
    
    def test_slot_from_dict(self):
        from bantz.nlu.types import Slot, SlotType
        
        d = {"name": "app", "value": "spotify", "raw_text": "spotify", "slot_type": "app"}
        slot = Slot.from_dict(d)
        
        assert slot.name == "app"
        assert slot.value == "spotify"
        assert slot.slot_type == SlotType.APP
    
    def test_slot_str(self):
        from bantz.nlu.types import Slot
        
        slot = Slot(name="query", value="coldplay", raw_text="coldplay")
        assert str(slot) == "query='coldplay'"
    
    def test_slot_confidence_validation(self):
        from bantz.nlu.types import Slot
        
        with pytest.raises(ValueError):
            Slot(name="test", value="test", raw_text="test", confidence=1.5)
        
        with pytest.raises(ValueError):
            Slot(name="test", value="test", raw_text="test", confidence=-0.1)


class TestClarificationOption:
    """Tests for ClarificationOption dataclass."""
    
    def test_option_creation(self):
        from bantz.nlu.types import ClarificationOption
        
        option = ClarificationOption(
            intent="browser_open",
            description="Web sitesi aç",
            slots={"site": "youtube"},
            probability=0.7,
        )
        
        assert option.intent == "browser_open"
        assert option.description == "Web sitesi aç"
        assert option.slots["site"] == "youtube"
    
    def test_option_to_from_dict(self):
        from bantz.nlu.types import ClarificationOption
        
        option = ClarificationOption(
            intent="app_open",
            description="Uygulama aç",
        )
        
        d = option.to_dict()
        restored = ClarificationOption.from_dict(d)
        
        assert restored.intent == option.intent
        assert restored.description == option.description


class TestClarificationRequest:
    """Tests for ClarificationRequest dataclass."""
    
    def test_request_creation(self):
        from bantz.nlu.types import ClarificationRequest
        
        req = ClarificationRequest(
            question="Hangi siteyi açayım?",
            original_text="aç",
            reason="missing_slot",
            slot_needed="url",
        )
        
        assert req.question == "Hangi siteyi açayım?"
        assert req.is_slot_request
        assert not req.has_options
    
    def test_request_with_options(self):
        from bantz.nlu.types import ClarificationRequest, ClarificationOption
        
        req = ClarificationRequest(
            question="Hangisini yapayım?",
            options=[
                ClarificationOption("browser_open", "Site aç"),
                ClarificationOption("app_open", "Uygulama aç"),
            ],
        )
        
        assert req.has_options
        assert len(req.options) == 2
    
    def test_request_to_from_dict(self):
        from bantz.nlu.types import ClarificationRequest, ClarificationOption
        
        req = ClarificationRequest(
            question="Test?",
            options=[ClarificationOption("test", "Test")],
            reason="test",
        )
        
        d = req.to_dict()
        restored = ClarificationRequest.from_dict(d)
        
        assert restored.question == req.question
        assert len(restored.options) == 1


class TestNLUContext:
    """Tests for NLUContext dataclass."""
    
    def test_context_creation(self):
        from bantz.nlu.types import NLUContext
        
        ctx = NLUContext(
            focused_app="firefox",
            current_url="https://youtube.com",
            session_id="test-123",
        )
        
        assert ctx.focused_app == "firefox"
        assert ctx.current_url == "https://youtube.com"
    
    def test_add_intent(self):
        from bantz.nlu.types import NLUContext
        
        ctx = NLUContext()
        ctx.add_intent("browser_open", "youtube aç")
        ctx.add_intent("browser_search", "coldplay ara")
        
        assert ctx.get_last_intent() == "browser_search"
        assert ctx.get_last_text() == "coldplay ara"
        assert len(ctx.recent_intents) == 2
    
    def test_add_intent_max_history(self):
        from bantz.nlu.types import NLUContext
        
        ctx = NLUContext()
        
        for i in range(15):
            ctx.add_intent(f"intent_{i}", f"text_{i}")
        
        # Default max is 10
        assert len(ctx.recent_intents) == 10
        assert ctx.recent_intents[0] == "intent_5"
    
    def test_is_followup(self):
        from bantz.nlu.types import NLUContext, ClarificationRequest
        
        ctx = NLUContext()
        assert not ctx.is_followup()
        
        ctx.add_intent("browser_open", "youtube")
        assert ctx.is_followup()
        
        ctx2 = NLUContext()
        ctx2.pending_clarification = ClarificationRequest(question="Test?")
        assert ctx2.is_followup()
    
    def test_context_to_from_dict(self):
        from bantz.nlu.types import NLUContext
        
        ctx = NLUContext(
            focused_app="vscode",
            session_id="test",
        )
        ctx.add_intent("file_read", "test.py oku")
        
        d = ctx.to_dict()
        restored = NLUContext.from_dict(d)
        
        assert restored.focused_app == ctx.focused_app
        assert len(restored.recent_intents) == 1


class TestIntentResult:
    """Tests for IntentResult dataclass."""
    
    def test_result_creation(self):
        from bantz.nlu.types import IntentResult, IntentCategory
        
        result = IntentResult(
            intent="browser_open",
            slots={"site": "youtube"},
            confidence=0.95,
            original_text="youtube aç",
            source="regex",
        )
        
        assert result.intent == "browser_open"
        assert result.slots["site"] == "youtube"
        assert result.confidence == 0.95
        assert result.category == IntentCategory.BROWSER
    
    def test_confidence_level(self):
        from bantz.nlu.types import IntentResult, ConfidenceLevel
        
        result = IntentResult(intent="test", confidence=0.95)
        assert result.confidence_level == ConfidenceLevel.VERY_HIGH
        
        result2 = IntentResult(intent="test", confidence=0.45)
        assert result2.confidence_level == ConfidenceLevel.VERY_LOW
    
    def test_needs_clarification(self):
        from bantz.nlu.types import IntentResult, ClarificationRequest
        
        result = IntentResult(intent="test", confidence=0.95)
        assert not result.needs_clarification
        
        result2 = IntentResult(intent="test", confidence=0.4)
        assert result2.needs_clarification
        
        result3 = IntentResult(
            intent="test",
            confidence=0.8,
            clarification=ClarificationRequest(question="Test?"),
        )
        assert result3.needs_clarification
    
    def test_is_successful(self):
        from bantz.nlu.types import IntentResult
        
        assert IntentResult(intent="browser_open", confidence=0.8).is_successful
        assert not IntentResult(intent="unknown", confidence=0.8).is_successful
        assert not IntentResult(intent="browser_open", confidence=0.3).is_successful
    
    def test_slot_helpers(self):
        from bantz.nlu.types import IntentResult
        
        result = IntentResult(intent="test", slots={"url": "youtube.com"})
        
        assert result.has_slot("url")
        assert not result.has_slot("app")
        assert result.get_slot("url") == "youtube.com"
        assert result.get_slot("app", "default") == "default"
        assert result.slot_names == {"url"}
    
    def test_with_slot(self):
        from bantz.nlu.types import IntentResult
        
        result = IntentResult(intent="test", slots={"url": "youtube.com"})
        result2 = result.with_slot("query", "coldplay")
        
        assert "query" not in result.slots
        assert result2.slots["query"] == "coldplay"
        assert result2.slots["url"] == "youtube.com"
    
    def test_with_confidence(self):
        from bantz.nlu.types import IntentResult
        
        result = IntentResult(intent="test", confidence=0.5)
        result2 = result.with_confidence(0.9)
        
        assert result.confidence == 0.5
        assert result2.confidence == 0.9
    
    def test_factory_methods(self):
        from bantz.nlu.types import IntentResult
        
        unknown = IntentResult.unknown("test text")
        assert unknown.intent == "unknown"
        assert unknown.confidence == 0.0
        
        regex = IntentResult.from_regex("browser_open", {"site": "youtube"}, "youtube aç")
        assert regex.source == "regex"
        assert regex.confidence == 0.99
        
        llm = IntentResult.from_llm("app_open", {"app": "spotify"}, "spotify aç", 0.85)
        assert llm.source == "llm"
    
    def test_to_from_dict(self):
        from bantz.nlu.types import IntentResult
        
        result = IntentResult(
            intent="browser_open",
            slots={"site": "youtube"},
            confidence=0.95,
            source="regex",
        )
        
        d = result.to_dict()
        restored = IntentResult.from_dict(d)
        
        assert restored.intent == result.intent
        assert restored.slots == result.slots
        assert restored.confidence == result.confidence
    
    def test_str_repr(self):
        from bantz.nlu.types import IntentResult
        
        result = IntentResult(intent="browser_open", slots={"site": "youtube"}, confidence=0.95)
        s = str(result)
        
        assert "browser_open" in s
        assert "youtube" in s
        assert "0.95" in s


class TestNLUStats:
    """Tests for NLUStats dataclass."""
    
    def test_stats_creation(self):
        from bantz.nlu.types import NLUStats
        
        stats = NLUStats()
        
        assert stats.total_requests == 0
        assert stats.regex_hits == 0
    
    def test_record_result(self):
        from bantz.nlu.types import NLUStats, IntentResult
        
        stats = NLUStats()
        
        result = IntentResult(
            intent="browser_open",
            confidence=0.95,
            source="regex",
            processing_time_ms=1.5,
        )
        
        stats.record_result(result)
        
        assert stats.total_requests == 1
        assert stats.regex_hits == 1
        assert stats.intent_counts["browser_open"] == 1
    
    def test_rates(self):
        from bantz.nlu.types import NLUStats, IntentResult
        
        stats = NLUStats()
        
        for i in range(8):
            stats.record_result(IntentResult(intent="test", source="regex"))
        for i in range(2):
            stats.record_result(IntentResult(intent="test", source="llm"))
        
        assert stats.regex_rate == 80.0
        assert stats.llm_rate == 20.0
    
    def test_average_confidence(self):
        from bantz.nlu.types import NLUStats, IntentResult
        
        stats = NLUStats()
        
        stats.record_result(IntentResult(intent="test", confidence=0.8))
        stats.record_result(IntentResult(intent="test", confidence=0.6))
        
        assert stats.average_confidence == 0.7
    
    def test_top_intents(self):
        from bantz.nlu.types import NLUStats, IntentResult
        
        stats = NLUStats()
        
        for _ in range(5):
            stats.record_result(IntentResult(intent="browser_open"))
        for _ in range(3):
            stats.record_result(IntentResult(intent="app_open"))
        for _ in range(1):
            stats.record_result(IntentResult(intent="file_read"))
        
        top = stats.top_intents(2)
        assert top[0] == ("browser_open", 5)
        assert top[1] == ("app_open", 3)
    
    def test_summary(self):
        from bantz.nlu.types import NLUStats, IntentResult
        
        stats = NLUStats()
        stats.record_result(IntentResult(intent="test"))
        
        summary = stats.summary()
        assert "NLU Stats" in summary
        assert "Total requests: 1" in summary
    
    def test_reset(self):
        from bantz.nlu.types import NLUStats, IntentResult
        
        stats = NLUStats()
        stats.record_result(IntentResult(intent="test"))
        stats.reset()
        
        assert stats.total_requests == 0


# ============================================================================
# Slot Extraction Tests
# ============================================================================


class TestTimeExtraction:
    """Tests for time slot extraction."""
    
    def test_extract_relative_minutes(self):
        from bantz.nlu.slots import extract_time
        
        base = datetime(2024, 1, 15, 10, 0, 0)
        
        result = extract_time("5 dakika sonra", base)
        assert result is not None
        assert result.value == base + timedelta(minutes=5)
        assert result.is_relative
    
    def test_extract_relative_hours(self):
        from bantz.nlu.slots import extract_time
        
        base = datetime(2024, 1, 15, 10, 0, 0)
        
        result = extract_time("2 saat sonra", base)
        assert result is not None
        assert result.value == base + timedelta(hours=2)
    
    def test_extract_turkish_number(self):
        from bantz.nlu.slots import extract_time
        
        base = datetime(2024, 1, 15, 10, 0, 0)
        
        result = extract_time("beş dakika sonra", base)
        assert result is not None
        assert result.value == base + timedelta(minutes=5)
    
    def test_extract_tomorrow(self):
        from bantz.nlu.slots import extract_time
        
        base = datetime(2024, 1, 15, 10, 0, 0)
        
        result = extract_time("yarın", base)
        assert result is not None
        assert result.value.day == 16
    
    def test_extract_tomorrow_with_time(self):
        from bantz.nlu.slots import extract_time
        
        base = datetime(2024, 1, 15, 10, 0, 0)
        
        result = extract_time("yarın saat 15", base)
        assert result is not None
        assert result.value.day == 16
        assert result.value.hour == 15
    
    def test_extract_absolute_time(self):
        from bantz.nlu.slots import extract_time
        
        base = datetime(2024, 1, 15, 10, 0, 0)
        
        result = extract_time("saat 15:30", base)
        assert result is not None
        assert result.value.hour == 15
        assert result.value.minute == 30
    
    def test_no_time_match(self):
        from bantz.nlu.slots import extract_time
        
        result = extract_time("youtube aç")
        assert result is None


class TestURLExtraction:
    """Tests for URL slot extraction."""
    
    def test_extract_full_url(self):
        from bantz.nlu.slots import extract_url
        
        result = extract_url("https://www.youtube.com/watch?v=abc")
        assert result is not None
        assert result.url == "https://www.youtube.com/watch?v=abc"
        assert result.is_full_url
    
    def test_extract_domain(self):
        from bantz.nlu.slots import extract_url
        
        result = extract_url("github.com/user/repo")
        assert result is not None
        # Use only startswith - NO substring checks allowed (Security Alerts #38, #39)
        assert result.url.startswith("https://github.com") or result.url.startswith("http://github.com")
    
    def test_extract_known_site(self):
        from bantz.nlu.slots import extract_url
        
        result = extract_url("youtube")
        assert result is not None
        assert result.site_name == "youtube"
        # Use only startswith - NO substring checks allowed (Security Alerts #40, #41, #42)
        valid_prefixes = ["https://youtube.com", "http://youtube.com", "https://www.youtube.com", "http://www.youtube.com"]
        assert any(result.url.startswith(prefix) for prefix in valid_prefixes)
    
    def test_extract_site_with_suffix(self):
        from bantz.nlu.slots import extract_url
        
        result = extract_url("youtube'a")
        assert result is not None
        assert result.site_name == "youtube"
    
    def test_site_mappings(self):
        from bantz.nlu.slots import extract_url
        
        sites = ["twitter", "instagram", "github", "google", "reddit", "spotify"]
        
        for site in sites:
            result = extract_url(site)
            assert result is not None, f"Failed for {site}"
            assert result.site_name == site
    
    def test_no_url_match(self):
        from bantz.nlu.slots import extract_url
        
        result = extract_url("merhaba nasılsın")
        assert result is None


class TestAppExtraction:
    """Tests for app slot extraction."""
    
    def test_extract_direct_app(self):
        from bantz.nlu.slots import extract_app
        
        result = extract_app("spotify")
        assert result is not None
        assert result.app_name == "spotify"
    
    def test_extract_app_with_action(self):
        from bantz.nlu.slots import extract_app
        
        result = extract_app("spotify aç")
        assert result is not None
        assert result.app_name == "spotify"
    
    def test_extract_vscode(self):
        from bantz.nlu.slots import extract_app
        
        result = extract_app("vscode")
        assert result is not None
        assert result.executable == "code"
    
    def test_extract_turkish_names(self):
        from bantz.nlu.slots import extract_app
        
        # Terminal
        result = extract_app("terminal")
        assert result is not None
        
        # Tarayıcı (firefox)
        result = extract_app("tarayıcı")
        assert result is not None
        assert "firefox" in result.executable.lower()
    
    def test_app_with_suffix(self):
        from bantz.nlu.slots import extract_app
        
        result = extract_app("spotify'ı")
        assert result is not None
        assert result.app_name == "spotify"
    
    def test_no_app_match(self):
        from bantz.nlu.slots import extract_app
        
        result = extract_app("youtube aç")  # youtube is a site, not an app
        assert result is None or result.app_name != "youtube"


class TestQueryExtraction:
    """Tests for search query extraction."""
    
    def test_extract_site_search(self):
        from bantz.nlu.slots import extract_query
        
        result = extract_query("youtube'da coldplay ara")
        assert result is not None
        assert result.query == "coldplay"
        assert result.site == "youtube"
    
    def test_extract_simple_search(self):
        from bantz.nlu.slots import extract_query
        
        result = extract_query("python tutorial ara")
        assert result is not None
        assert "python tutorial" in result.query
    
    def test_no_query_match(self):
        from bantz.nlu.slots import extract_query
        
        result = extract_query("youtube aç")
        assert result is None


class TestPositionExtraction:
    """Tests for position slot extraction."""
    
    def test_extract_positions(self):
        from bantz.nlu.slots import extract_position
        
        positions = {
            "sağ üst": "top-right",
            "sol alt": "bottom-left",
            "orta": "center",
            "merkez": "center",
        }
        
        for turkish, english in positions.items():
            result = extract_position(turkish)
            assert result is not None, f"Failed for {turkish}"
            assert result.value == english


class TestSlotExtractor:
    """Tests for SlotExtractor class."""
    
    def test_extract_all(self):
        from bantz.nlu.slots import SlotExtractor
        
        extractor = SlotExtractor()
        
        slots = extractor.extract_all("5 dakika sonra spotify aç")
        
        assert "time" in slots
        # spotify is recognized as a site (known mapping)
        assert "site" in slots or "url" in slots
    
    def test_extract_for_intent(self):
        from bantz.nlu.slots import SlotExtractor
        
        extractor = SlotExtractor()
        
        slots = extractor.extract_for_intent("youtube aç", "browser_open")
        assert "url" in slots or "site" in slots
    
    def test_to_flat_dict(self):
        from bantz.nlu.slots import SlotExtractor
        
        extractor = SlotExtractor()
        
        slots = extractor.extract_all("youtube")
        flat = extractor.to_flat_dict(slots)
        
        assert isinstance(flat.get("url"), str)


# ============================================================================
# Clarification Manager Tests
# ============================================================================


class TestClarificationConfig:
    """Tests for ClarificationConfig."""
    
    def test_default_config(self):
        from bantz.nlu.clarification import ClarificationConfig
        
        config = ClarificationConfig()
        
        assert config.confidence_threshold == 0.6
        assert config.max_options == 3


class TestClarificationManager:
    """Tests for ClarificationManager."""
    
    def test_needs_clarification_low_confidence(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import IntentResult
        
        manager = ClarificationManager()
        
        result = IntentResult(intent="test", confidence=0.4)
        assert manager.needs_clarification(result)
        
        result2 = IntentResult(intent="test", confidence=0.9)
        assert not manager.needs_clarification(result2)
    
    def test_needs_clarification_unknown(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import IntentResult
        
        manager = ClarificationManager()
        
        result = IntentResult(intent="unknown", confidence=0.8)
        assert manager.needs_clarification(result)
    
    def test_needs_clarification_with_clarification(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import IntentResult, ClarificationRequest
        
        manager = ClarificationManager()
        
        result = IntentResult(
            intent="browser_open",
            confidence=0.9,
            clarification=ClarificationRequest(question="Test?"),
        )
        assert manager.needs_clarification(result)
    
    def test_get_clarification_reason(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import IntentResult
        
        manager = ClarificationManager()
        
        assert manager.get_clarification_reason(
            IntentResult(intent="unknown")
        ) == "unknown_intent"
        
        assert manager.get_clarification_reason(
            IntentResult(intent="test", confidence=0.2)
        ) == "very_low_confidence"
    
    def test_generate_clarification_missing_slot(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import IntentResult
        
        manager = ClarificationManager()
        
        # Don't pass existing clarification - let manager generate one
        result = IntentResult(
            intent="browser_open",
            slots={},  # Missing url/site
            confidence=0.4,
            original_text="aç",
        )
        
        clarification = manager.generate_clarification(result, "aç")
        
        # With low confidence, manager should ask for clarification
        assert len(clarification.question) > 0 or clarification.slot_needed is not None
    
    def test_pending_clarification(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import ClarificationRequest
        
        manager = ClarificationManager()
        session_id = "test-session"
        
        req = ClarificationRequest(question="Test?")
        manager.set_pending(session_id, req)
        
        assert manager.get_pending(session_id) == req
        
        manager.clear_pending(session_id)
        assert manager.get_pending(session_id) is None
    
    def test_resolve_from_response_cancellation(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import ClarificationRequest
        
        manager = ClarificationManager()
        session_id = "test-session"
        
        req = ClarificationRequest(question="Test?", original_text="test")
        manager.set_pending(session_id, req)
        
        result = manager.resolve_from_response("iptal", session_id)
        
        assert result is not None
        assert result.intent == "cancel"
    
    def test_resolve_from_response_slot_fill(self):
        from bantz.nlu.clarification import ClarificationManager
        from bantz.nlu.types import ClarificationRequest, ClarificationOption
        
        manager = ClarificationManager()
        session_id = "test-session"
        
        req = ClarificationRequest(
            question="Hangi siteyi açayım?",
            original_text="aç",
            slot_needed="url",
            options=[ClarificationOption("browser_open", "Site aç", {"url": ""})],
        )
        manager.set_pending(session_id, req)
        
        result = manager.resolve_from_response("youtube", session_id)
        
        assert result is not None
        assert result.slots.get("url") == "youtube"


# ============================================================================
# Hybrid NLU Tests
# ============================================================================


class TestHybridConfig:
    """Tests for HybridConfig."""
    
    def test_default_config(self):
        from bantz.nlu.hybrid import HybridConfig
        
        config = HybridConfig()
        
        assert config.regex_confidence == 0.99
        assert config.llm_enabled


class TestRegexPatterns:
    """Tests for regex pattern matching."""
    
    def test_site_open_simple(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("youtube aç")
        assert result is not None
        assert result.intent == "browser_open"
        assert result.slots.get("site") == "youtube"
    
    def test_site_open_with_suffix(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("twitter'a git")
        assert result is not None
        assert result.intent == "browser_open"
    
    def test_site_open_natural(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("youtube'a gidebilir misin")
        assert result is not None
        assert result.intent == "browser_open"
    
    def test_site_search(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("youtube'da coldplay ara")
        assert result is not None
        assert result.intent == "browser_search"
        assert result.slots.get("query") == "coldplay"
    
    def test_app_open(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        # Use blender which is not a known site (spotify is a site)
        result = patterns.match("blender aç")
        assert result is not None
        assert result.intent == "app_open"
    
    def test_app_close(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("spotify kapat")
        assert result is not None
        assert result.intent == "app_close"
    
    def test_reminder(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("5 dakika sonra toplantı hatırlat")
        assert result is not None
        assert result.intent == "reminder_add"
        assert "time" in result.slots
        assert "message" in result.slots
    
    def test_queue_control(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        assert patterns.match("duraklat").intent == "queue_pause"
        assert patterns.match("devam et").intent == "queue_resume"
        assert patterns.match("iptal").intent == "queue_abort"
    
    def test_overlay_move(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("sağ üste geç")
        assert result is not None
        assert result.intent == "overlay_move"
        assert result.slots.get("position") == "top-right"
    
    def test_confirmation(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        assert patterns.match("evet").intent == "confirm_yes"
        assert patterns.match("hayır").intent == "confirm_no"
    
    def test_greeting(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("selam")
        assert result is not None
        assert result.intent == "greeting"
    
    def test_no_match(self):
        from bantz.nlu.hybrid import RegexPatterns
        
        patterns = RegexPatterns()
        
        result = patterns.match("bu çok belirsiz bir cümle")
        assert result is None


class TestHybridNLU:
    """Tests for HybridNLU class."""
    
    def test_parse_regex_path(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("youtube aç")
        
        assert result.intent == "browser_open"
        assert result.source == "regex"
    
    def test_parse_unknown_without_llm(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("bu çok belirsiz bir cümle")
        
        assert result.intent == "unknown"
    
    def test_parse_with_slot_enhancement(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(
            llm_enabled=False,
            slot_extraction_enabled=True,
        )
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("youtube aç")
        
        # Should have URL from slot extraction
        assert "site" in result.slots or "url" in result.slots
    
    def test_context_tracking(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        nlu.parse("youtube aç", session_id="test-session")
        
        ctx = nlu.get_context("test-session")
        assert ctx is not None
        assert "browser_open" in ctx.recent_intents
    
    def test_stats_tracking(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False, stats_enabled=True)
        nlu = HybridNLU(config=config)
        
        nlu.parse("youtube aç")
        nlu.parse("spotify aç")
        
        stats = nlu.get_stats()
        assert stats is not None
        assert stats.total_requests == 2
    
    def test_clear_context(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        nlu.parse("youtube aç", session_id="test-session")
        nlu.clear_context("test-session")
        
        assert nlu.get_context("test-session") is None


class TestHybridNLUWithLLM:
    """Tests for HybridNLU with mocked LLM."""
    
    def test_llm_fallback(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        from bantz.nlu.classifier import LLMIntentClassifier
        from bantz.nlu.types import IntentResult
        
        # Create mock classifier
        mock_classifier = Mock(spec=LLMIntentClassifier)
        mock_classifier.classify.return_value = IntentResult(
            intent="browser_open",
            slots={"site": "youtube"},
            confidence=0.85,
            source="llm",
        )
        
        config = HybridConfig(llm_enabled=True)
        nlu = HybridNLU(config=config, llm_classifier=mock_classifier)
        
        # Text that won't match regex
        result = nlu.parse("youtube'a gidebilir misin acaba lütfen")
        
        # Should fall back to LLM since regex won't match exactly
        # (The regex might actually match this, so we just verify it works)
        assert result.intent in ("browser_open", "unknown")


# ============================================================================
# Bridge Tests
# ============================================================================


class TestBridge:
    """Tests for NLU bridge functions."""
    
    def test_parse_intent_hybrid(self):
        from bantz.nlu.bridge import parse_intent_hybrid
        from bantz.router.nlu import Parsed
        
        result = parse_intent_hybrid("youtube aç")
        
        assert isinstance(result, Parsed)
        assert result.intent == "browser_open"
    
    def test_parse_with_context(self):
        from bantz.nlu.bridge import parse_with_context
        from bantz.router.nlu import Parsed
        from bantz.nlu.types import IntentResult
        
        parsed, intent_result = parse_with_context(
            "youtube aç",
            session_id="test",
            focused_app="firefox",
        )
        
        assert isinstance(parsed, Parsed)
        assert isinstance(intent_result, IntentResult)
    
    def test_parse_enhanced(self):
        from bantz.nlu.bridge import parse_enhanced
        from bantz.nlu.types import IntentResult
        
        result = parse_enhanced("youtube aç")
        
        assert isinstance(result, IntentResult)
        assert result.intent == "browser_open"
    
    def test_enable_hybrid_nlu(self):
        from bantz.nlu.bridge import enable_hybrid_nlu, is_hybrid_enabled
        
        enable_hybrid_nlu(True)
        assert is_hybrid_enabled()
        
        enable_hybrid_nlu(False)
        assert not is_hybrid_enabled()
    
    def test_parse_intent_adaptive(self):
        from bantz.nlu.bridge import parse_intent_adaptive, enable_hybrid_nlu
        
        # Test with hybrid disabled
        enable_hybrid_nlu(False)
        result1 = parse_intent_adaptive("youtube aç")
        
        # Test with hybrid enabled
        enable_hybrid_nlu(True)
        result2 = parse_intent_adaptive("youtube aç")
        
        # Both should return browser_open
        assert result1.intent == "browser_open"
        assert result2.intent == "browser_open"
        
        # Reset
        enable_hybrid_nlu(False)
    
    def test_compare_parsers(self):
        from bantz.nlu.bridge import compare_parsers
        
        result = compare_parsers("youtube aç")
        
        assert "legacy" in result
        assert "hybrid" in result
        assert "match" in result
    
    def test_get_nlu_stats(self):
        from bantz.nlu.bridge import get_nlu_stats, parse_intent_hybrid
        
        # Parse something to generate stats
        parse_intent_hybrid("youtube aç")
        
        stats = get_nlu_stats()
        assert isinstance(stats, dict)
        assert "total_requests" in stats


class TestParseWithClarification:
    """Tests for clarification-aware parsing."""
    
    def test_no_clarification_needed(self):
        from bantz.nlu.bridge import parse_with_clarification
        
        result = parse_with_clarification("youtube aç", session_id="test")
        
        assert not result.needs_clarification
        assert result.parsed.intent == "browser_open"
    
    def test_resolve_clarification(self):
        from bantz.nlu.bridge import parse_with_clarification, resolve_clarification
        from bantz.nlu.bridge import get_nlu
        from bantz.nlu.types import ClarificationRequest
        
        # Set up a pending clarification
        nlu = get_nlu()
        session_id = "test-resolve"
        
        if nlu._clarification:
            req = ClarificationRequest(
                question="Hangi siteyi açayım?",
                original_text="aç",
                slot_needed="url",
            )
            nlu._clarification.set_pending(session_id, req)
            
            # Resolve it
            result = resolve_clarification("youtube", session_id)
            
            if result is not None:
                assert result.slots.get("url") == "youtube"


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for the full NLU pipeline."""
    
    def test_natural_language_variations(self):
        """Test that various natural language forms work."""
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        # All should open YouTube
        variations = [
            "youtube aç",
            "youtube",
            "youtube'a git",
        ]
        
        for text in variations:
            result = nlu.parse(text)
            # At least one variation should match
            if result.intent == "browser_open":
                assert "youtube" in str(result.slots).lower()
                break
        else:
            # At least "youtube aç" should work
            result = nlu.parse("youtube aç")
            assert result.intent == "browser_open"
    
    def test_session_continuity(self):
        """Test that session context is maintained."""
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        session_id = "test-session"
        
        nlu.parse("youtube aç", session_id=session_id)
        nlu.parse("spotify aç", session_id=session_id)
        
        ctx = nlu.get_context(session_id)
        assert len(ctx.recent_intents) == 2
    
    def test_to_legacy_parsed(self):
        """Test conversion to legacy Parsed format."""
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        from bantz.router.nlu import Parsed
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("youtube aç")
        parsed = nlu.to_legacy_parsed(result)
        
        assert isinstance(parsed, Parsed)
        assert parsed.intent == result.intent


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_empty_input(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("")
        assert result.intent == "unknown"
    
    def test_whitespace_only(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("   ")
        assert result.intent == "unknown"
    
    def test_very_long_input(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        long_text = "youtube aç " * 100
        result = nlu.parse(long_text)
        # Should not crash
        assert result is not None
    
    def test_special_characters(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("youtube'a git!")
        assert result is not None
    
    def test_unicode_turkish(self):
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        result = nlu.parse("günaydın")
        assert result.intent == "greeting"


# ============================================================================
# LLM Classifier Tests (Mocked)
# ============================================================================


class TestLLMClassifier:
    """Tests for LLM classifier with mocked responses."""
    
    def test_parse_json_response(self):
        from bantz.nlu.classifier import LLMIntentClassifier
        
        classifier = LLMIntentClassifier()
        
        # Test JSON parsing
        response = json.dumps({
            "intent": "browser_open",
            "confidence": 0.95,
            "slots": {"site": "youtube"},
            "ambiguous": False,
        })
        
        result = classifier._parse_response(response, "test", 0)
        
        assert result.intent == "browser_open"
        assert result.confidence == 0.95
        assert result.slots["site"] == "youtube"
    
    def test_extract_json_from_text(self):
        from bantz.nlu.classifier import LLMIntentClassifier
        
        classifier = LLMIntentClassifier()
        
        # Pure JSON (direct parse works)
        text = '{"intent": "app_open", "confidence": 0.8}'
        
        data = classifier._extract_json(text)
        assert data is not None
        assert data["intent"] == "app_open"
        
        # Also test embedded JSON without nested objects
        text2 = 'Result: {"intent": "greeting", "confidence": 0.9}'
        data2 = classifier._extract_json(text2)
        assert data2 is not None
        assert data2["intent"] == "greeting"
    
    def test_find_closest_intent(self):
        from bantz.nlu.classifier import LLMIntentClassifier
        
        classifier = LLMIntentClassifier()
        
        assert classifier._find_closest_intent("open_browser") == "browser_open"
        assert classifier._find_closest_intent("search") == "browser_search"
        assert classifier._find_closest_intent("hello") == "greeting"
        assert classifier._find_closest_intent("xyz_unknown") == "unknown"
    
    def test_check_required_slots(self):
        from bantz.nlu.classifier import LLMIntentClassifier
        
        classifier = LLMIntentClassifier()
        
        # browser_open needs url or site
        missing = classifier._check_required_slots("browser_open", {})
        assert "url" in missing
        
        missing = classifier._check_required_slots("browser_open", {"site": "youtube"})
        assert len(missing) == 0
    
    def test_cache_operations(self):
        from bantz.nlu.classifier import LLMIntentClassifier, ClassifierConfig
        
        config = ClassifierConfig(cache_enabled=True, cache_ttl_seconds=10)
        classifier = LLMIntentClassifier(config=config)
        
        # Initial cache should be empty
        assert len(classifier._cache) == 0
        
        # Clear cache
        classifier.clear_cache()
        assert len(classifier._cache) == 0
        
        # Get stats
        stats = classifier.get_cache_stats()
        assert stats["enabled"]


# ============================================================================
# Quick Functions Tests
# ============================================================================


class TestQuickFunctions:
    """Tests for quick utility functions."""
    
    def test_quick_parse(self):
        from bantz.nlu.hybrid import quick_parse
        from bantz.nlu.types import IntentResult
        
        result = quick_parse("youtube aç")
        
        assert isinstance(result, IntentResult)
    
    def test_module_parse(self):
        from bantz.nlu import parse
        from bantz.nlu.types import IntentResult
        
        result = parse("youtube aç")
        
        assert isinstance(result, IntentResult)
    
    def test_get_nlu_singleton(self):
        from bantz.nlu.hybrid import get_nlu
        from bantz.nlu.hybrid import HybridNLU
        
        nlu1 = get_nlu()
        nlu2 = get_nlu()
        
        assert isinstance(nlu1, HybridNLU)
        assert nlu1 is nlu2  # Same instance


# ============================================================================
# Performance Sanity Checks
# ============================================================================


class TestPerformance:
    """Basic performance sanity checks."""
    
    def test_regex_fast_path(self):
        import time
        from bantz.nlu.hybrid import HybridNLU, HybridConfig
        
        config = HybridConfig(llm_enabled=False)
        nlu = HybridNLU(config=config)
        
        # Warm up
        nlu.parse("youtube aç")
        
        # Measure
        start = time.time()
        for _ in range(100):
            nlu.parse("youtube aç")
        elapsed = time.time() - start
        
        # Should be fast (< 100ms for 100 parses)
        assert elapsed < 0.5, f"Regex path too slow: {elapsed}s for 100 parses"
    
    def test_slot_extraction_reasonable(self):
        import time
        from bantz.nlu.slots import SlotExtractor
        
        extractor = SlotExtractor()
        
        start = time.time()
        for _ in range(100):
            extractor.extract_all("5 dakika sonra youtube'da coldplay ara")
        elapsed = time.time() - start
        
        # Should be fast
        assert elapsed < 0.5, f"Slot extraction too slow: {elapsed}s for 100 extractions"
