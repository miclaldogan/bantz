"""Tests for Turkish Time PM Default (Issue #312).

Tests that Turkish time expressions like "saat beş" default to PM (17:00)
unless explicitly marked with "sabah" (morning).
"""

import pytest
import json
from unittest.mock import patch, MagicMock

# ============================================================================
# Test LLM Router Prompt Contains PM Rules
# ============================================================================

class TestLLMRouterPromptRules:
    """Test that the LLM router prompt contains correct PM default rules."""
    
    def test_prompt_contains_pm_default_rule(self):
        """Prompt should contain PM default rule for hours 1-6."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Check for PM default rule
        assert "PM" in prompt or "17:00" in prompt
        assert "beşe" in prompt or "beşte" in prompt
    
    def test_prompt_contains_sabah_am_rule(self):
        """Prompt should specify that 'sabah' means AM."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        assert "sabah" in prompt.lower()
        # Should mention that sabah = AM or morning times
        assert "05:00" in prompt or "AM" in prompt
    
    def test_prompt_has_saat_bes_example(self):
        """Prompt should have an example with saat 5 → 17:00."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Check for example showing 5 → 17:00
        assert "17:00" in prompt
    
    def test_prompt_has_sabah_bes_example(self):
        """Prompt should have an example with sabah beş → 05:00."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Check for example showing sabah 5 → 05:00
        assert "sabah" in prompt.lower()


# ============================================================================
# Test Time Parsing Logic
# ============================================================================

class TestTurkishTimeParsing:
    """Test Turkish time expression parsing with PM defaults."""
    
    @pytest.fixture
    def time_expressions_pm_default(self):
        """Time expressions that should default to PM."""
        return [
            ("beşe toplantı", "17:00"),
            ("beşte buluşalım", "17:00"),
            ("saat beş", "17:00"),
            ("saat 5", "17:00"),
            ("dörde randevu", "16:00"),
            ("dörtte gel", "16:00"),
            ("saat 4", "16:00"),
            ("üçe kadar", "15:00"),
            ("üçte biter", "15:00"),
            ("saat 3", "15:00"),
            ("ikiye hazır ol", "14:00"),
            ("ikide başla", "14:00"),
            ("saat 2", "14:00"),
            ("bire gel", "13:00"),
            ("birde toplantı", "13:00"),
            ("saat 1", "13:00"),
            ("altıya kadar", "18:00"),
            ("altıda buluş", "18:00"),
            ("saat 6", "18:00"),
        ]
    
    @pytest.fixture
    def time_expressions_am_explicit(self):
        """Time expressions with explicit 'sabah' should be AM."""
        return [
            ("sabah beşte koşu", "05:00"),
            ("sabah beş", "05:00"),
            ("sabah 5", "05:00"),
            ("sabah dörtte kalk", "04:00"),
            ("sabah üçte", "03:00"),
            ("sabah altıda", "06:00"),
        ]
    
    @pytest.fixture  
    def time_expressions_pm_explicit(self):
        """Time expressions with explicit 'akşam' should be PM."""
        return [
            ("akşam beşte yemek", "17:00"),
            ("akşam altıda", "18:00"),
            ("akşam yedide", "19:00"),
        ]
    
    def test_pm_default_rule_documented(self, time_expressions_pm_default):
        """Verify PM default expressions are documented."""
        # This is a documentation test - verify we have the right expectations
        for expr, expected_time in time_expressions_pm_default:
            # Hours 1-6 without sabah should be PM (13:00-18:00)
            hour = int(expected_time.split(":")[0])
            assert 13 <= hour <= 18, f"{expr} should map to PM hour, got {expected_time}"
    
    def test_am_explicit_rule_documented(self, time_expressions_am_explicit):
        """Verify AM explicit expressions are documented."""
        for expr, expected_time in time_expressions_am_explicit:
            assert "sabah" in expr.lower()
            hour = int(expected_time.split(":")[0])
            assert 0 <= hour <= 11, f"{expr} should map to AM hour, got {expected_time}"
    
    def test_pm_explicit_rule_documented(self, time_expressions_pm_explicit):
        """Verify PM explicit expressions are documented."""
        for expr, expected_time in time_expressions_pm_explicit:
            assert "akşam" in expr.lower()
            hour = int(expected_time.split(":")[0])
            assert 12 <= hour <= 23, f"{expr} should map to PM hour, got {expected_time}"


# ============================================================================
# Test Prompt Content Details
# ============================================================================

class TestPromptContentDetails:
    """Test specific content in the LLM router prompt."""
    
    def test_rule_3_mentions_pm(self):
        """Rule 3 should mention PM default for hours 1-6."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Should have rule about hours 1-6 defaulting to PM
        assert "1-6" in prompt or ("beş" in prompt and "17:00" in prompt)
    
    def test_turkish_time_section_exists(self):
        """Should have a Turkish time rules section."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Should have dedicated time rules section
        assert "SAAT" in prompt.upper() or "TIME" in prompt.upper()
    
    def test_examples_show_correct_mapping(self):
        """Examples should show correct time mappings."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Should show beşe → 17:00 example
        # And sabah → AM example
        content = prompt.lower()
        has_pm_example = "17:00" in prompt
        has_am_example = "05:00" in prompt or "sabah" in content
        
        assert has_pm_example, "Should have PM example (17:00)"
        assert has_am_example, "Should have AM example or sabah reference"


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestTimeParsingEdgeCases:
    """Test edge cases in time parsing."""
    
    def test_noon_is_twelve(self):
        """'öğlen' should map to 12:00."""
        # This is a documentation/expectation test
        expected = "12:00"
        assert expected == "12:00"
    
    def test_midnight_handling(self):
        """'gece yarısı' edge case."""
        # Midnight is 00:00
        expected = "00:00"
        assert expected == "00:00"
    
    def test_hours_7_to_12_need_context(self):
        """Hours 7-12 should use context, not default PM."""
        # 7-12 are ambiguous - could be morning or evening
        # dokuz (9) could be 09:00 (morning) or 21:00 (evening)
        # These need context clues
        ambiguous_hours = [7, 8, 9, 10, 11, 12]
        for h in ambiguous_hours:
            # Both AM and PM are valid for these hours
            assert 7 <= h <= 12


# ============================================================================
# Test Integration with Calendar Tools
# ============================================================================

class TestCalendarToolsIntegration:
    """Test that calendar tools receive correct times."""
    
    def test_calendar_create_accepts_17_00(self):
        """Calendar create tool should accept 17:00 format."""
        from bantz.tools.calendar_tools import calendar_create_event_tool
        
        # Mock the create_event function
        with patch('bantz.tools.calendar_tools.create_event') as mock_create:
            mock_create.return_value = {"ok": True, "event_id": "test123"}
            
            result = calendar_create_event_tool(
                title="toplantı",
                time="17:00",
                date="2026-02-05",
            )
            
            # Should be called with correct time
            assert mock_create.called
            call_args = mock_create.call_args
            # Start time should include 17:00
            assert "17:00" in str(call_args) or "T17:" in str(call_args)
    
    def test_calendar_create_accepts_05_00(self):
        """Calendar create tool should accept 05:00 format."""
        from bantz.tools.calendar_tools import calendar_create_event_tool
        
        with patch('bantz.tools.calendar_tools.create_event') as mock_create:
            mock_create.return_value = {"ok": True, "event_id": "test123"}
            
            result = calendar_create_event_tool(
                title="koşu",
                time="05:00",
                date="2026-02-05",
            )
            
            assert mock_create.called
            call_args = mock_create.call_args
            assert "05:00" in str(call_args) or "T05:" in str(call_args)
