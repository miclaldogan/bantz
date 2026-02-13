"""Tests for Confirmation Parser Natural Language (Issue #283).

Tests that the confirmation parser accepts natural language
confirmations like "evet ekle dostum" and "hayır vazgeç".
"""

import pytest
import sys
from pathlib import Path

# Add scripts to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from terminal_jarvis import _is_confirmation_yes, _is_confirmation_no


# ============================================================================
# Test _is_confirmation_yes
# ============================================================================

class TestConfirmationYes:
    """Tests for _is_confirmation_yes function."""
    
    # Exact match cases
    @pytest.mark.parametrize("text", [
        "evet",
        "e",
        "ok",
        "tamam",
        "onay",
        "onaylıyorum",
        "kabul",
        "yes",
        "y",
        "olur",
        "peki",
    ])
    def test_exact_match_yes(self, text):
        """Exact match tokens should be recognized as yes."""
        assert _is_confirmation_yes(text) is True
    
    # Case insensitivity
    @pytest.mark.parametrize("text", [
        "EVET",
        "Evet",
        "TAMAM",
        "OK",
        "Yes",
        "YES",
    ])
    def test_case_insensitive_yes(self, text):
        """Confirmation should be case insensitive."""
        assert _is_confirmation_yes(text) is True
    
    # Natural language confirmations (Issue #283 main cases)
    @pytest.mark.parametrize("text", [
        "evet ekle dostum",
        "evet yap şunu",
        "evet lütfen",
        "tamam yap",
        "tamam ekle",
        "tamam devam et",
        "ok devam",
        "ok yap",
        "kabul ediyorum",
        "yes please",
        "yes do it",
        "olur yap",
        "peki tamam",
    ])
    def test_natural_language_yes(self, text):
        """Natural language confirmations should be recognized."""
        assert _is_confirmation_yes(text) is True
    
    # Whitespace handling
    @pytest.mark.parametrize("text", [
        "  evet  ",
        "evet ",
        " evet",
        "  tamam  ",
    ])
    def test_whitespace_handling_yes(self, text):
        """Leading/trailing whitespace should be stripped."""
        assert _is_confirmation_yes(text) is True
    
    # Negative cases - should NOT be recognized as yes
    @pytest.mark.parametrize("text", [
        "hayır",
        "no",
        "iptal",
        "vazgeç",
        "",
        "belki",
        "bilmiyorum",
        "düşüneyim",
        "bir dakika",
        "bugün toplantı var mı",  # Normal query, not confirmation
    ])
    def test_not_yes(self, text):
        """Non-confirmation texts should return False."""
        assert _is_confirmation_yes(text) is False
    
    def test_empty_string(self):
        """Empty string should return False."""
        assert _is_confirmation_yes("") is False
    
    def test_none_input(self):
        """None input should return False."""
        assert _is_confirmation_yes(None) is False


# ============================================================================
# Test _is_confirmation_no
# ============================================================================

class TestConfirmationNo:
    """Tests for _is_confirmation_no function."""
    
    # Exact match cases
    @pytest.mark.parametrize("text", [
        "hayır",
        "h",
        "no",
        "n",
        "iptal",
        "vazgeç",
        "reddet",
        "istemiyorum",
        "olmaz",
    ])
    def test_exact_match_no(self, text):
        """Exact match tokens should be recognized as no."""
        assert _is_confirmation_no(text) is True
    
    # Case insensitivity
    @pytest.mark.parametrize("text", [
        "HAYIR",
        "Hayır",
        "NO",
        "No",
        "Iptal",  # Note: İPTAL.lower() = i̇ptal due to Turkish locale, use Iptal instead
        "VAZGEÇ",
    ])
    def test_case_insensitive_no(self, text):
        """Rejection should be case insensitive."""
        assert _is_confirmation_no(text) is True
    
    # Natural language rejections (Issue #283 main cases)
    @pytest.mark.parametrize("text", [
        "hayır vazgeç",
        "hayır istemiyorum",
        "hayır yapma",
        "iptal et",
        "iptal et lütfen",
        "vazgeç artık",
        "no thanks",
        "no don't do it",
        "istemiyorum bunu",
        "olmaz böyle",
    ])
    def test_natural_language_no(self, text):
        """Natural language rejections should be recognized."""
        assert _is_confirmation_no(text) is True
    
    # Whitespace handling
    @pytest.mark.parametrize("text", [
        "  hayır  ",
        "hayır ",
        " hayır",
        "  iptal  ",
    ])
    def test_whitespace_handling_no(self, text):
        """Leading/trailing whitespace should be stripped."""
        assert _is_confirmation_no(text) is True
    
    # Negative cases - should NOT be recognized as no
    @pytest.mark.parametrize("text", [
        "evet",
        "yes",
        "tamam",
        "ok",
        "",
        "belki",
        "bir şey sor",
        "bugün toplantı var mı",  # Normal query
    ])
    def test_not_no(self, text):
        """Non-rejection texts should return False."""
        assert _is_confirmation_no(text) is False
    
    def test_empty_string(self):
        """Empty string should return False."""
        assert _is_confirmation_no("") is False
    
    def test_none_input(self):
        """None input should return False."""
        assert _is_confirmation_no(None) is False


# ============================================================================
# Test Mutual Exclusivity
# ============================================================================

class TestMutualExclusivity:
    """Test that yes and no are mutually exclusive."""
    
    @pytest.mark.parametrize("text", [
        "evet",
        "evet ekle",
        "tamam yap",
        "ok",
        "yes",
    ])
    def test_yes_is_not_no(self, text):
        """Yes confirmations should not be recognized as no."""
        assert _is_confirmation_yes(text) is True
        assert _is_confirmation_no(text) is False
    
    @pytest.mark.parametrize("text", [
        "hayır",
        "hayır vazgeç",
        "iptal et",
        "no",
        "vazgeç",
    ])
    def test_no_is_not_yes(self, text):
        """No rejections should not be recognized as yes."""
        assert _is_confirmation_no(text) is True
        assert _is_confirmation_yes(text) is False
    
    @pytest.mark.parametrize("text", [
        "bugün ne var",
        "takvimde toplantı var mı",
        "email gönder",
        "belki",
        "düşüneyim",
    ])
    def test_neutral_is_neither(self, text):
        """Neutral texts should be neither yes nor no."""
        assert _is_confirmation_yes(text) is False
        assert _is_confirmation_no(text) is False
