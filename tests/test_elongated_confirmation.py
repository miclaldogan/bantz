"""Tests for Elongated Confirmation Parser (Issue #311).

Tests that elongated characters like 'haaaayırrr' are properly
normalized and detected as confirmations/rejections.
"""

import pytest
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from terminal_jarvis import (
    _normalize_elongated,
    _is_confirmation_yes,
    _is_confirmation_no,
)


# ============================================================================
# Test _normalize_elongated Function
# ============================================================================

class TestNormalizeElongated:
    """Test the elongated character normalizer."""
    
    def test_normalize_single_repeated_char(self):
        """Single repeated char should be reduced."""
        assert _normalize_elongated("aaaa") == "a"
    
    def test_normalize_hayir_elongated(self):
        """'haaaayırrr' should become 'hayır'."""
        assert _normalize_elongated("haaaayırrr") == "hayır"
    
    def test_normalize_evet_elongated(self):
        """'eveeet' should become 'evet'."""
        assert _normalize_elongated("eveeet") == "evet"
    
    def test_normalize_tamam_elongated(self):
        """'tamaaaam' should become 'tamam'."""
        assert _normalize_elongated("tamaaaam") == "tamam"
    
    def test_normalize_yok_elongated(self):
        """'yoook' should become 'yok'."""
        assert _normalize_elongated("yoook") == "yok"
    
    def test_normalize_olmaz_elongated(self):
        """'olmaaaaaz' should become 'olmaz'."""
        assert _normalize_elongated("olmaaaaaz") == "olmaz"
    
    def test_normalize_preserves_single_chars(self):
        """Normal text without repetition should be unchanged."""
        assert _normalize_elongated("hayır") == "hayır"
        assert _normalize_elongated("evet") == "evet"
        assert _normalize_elongated("tamam") == "tamam"
    
    def test_normalize_preserves_double_letters(self):
        """Words with legitimate double letters should have one removed."""
        # This is acceptable - the normalization is aggressive
        # but confirmation matching will still work
        assert _normalize_elongated("alli") == "ali"
    
    def test_normalize_empty_string(self):
        """Empty string should return empty."""
        assert _normalize_elongated("") == ""
    
    def test_normalize_none(self):
        """None should return None."""
        assert _normalize_elongated(None) is None
    
    def test_normalize_mixed_case(self):
        """Mixed case should be handled."""
        assert _normalize_elongated("HAAAAYIR") == "HAYIR"
        assert _normalize_elongated("EveeeT") == "EveT"


# ============================================================================
# Test Elongated YES Confirmations
# ============================================================================

class TestElongatedYesConfirmations:
    """Test that elongated YES words are detected."""
    
    def test_eveeet(self):
        """'eveeet' should be detected as yes."""
        assert _is_confirmation_yes("eveeet") is True
    
    def test_eveeeet(self):
        """'eveeeet' should be detected as yes."""
        assert _is_confirmation_yes("eveeeet") is True
    
    def test_tamaaaam(self):
        """'tamaaaam' should be detected as yes."""
        assert _is_confirmation_yes("tamaaaam") is True
    
    def test_tamaaaaaam(self):
        """'tamaaaaaam' should be detected as yes."""
        assert _is_confirmation_yes("tamaaaaaam") is True
    
    def test_oluuur(self):
        """'oluuur' should be detected as yes."""
        assert _is_confirmation_yes("oluuur") is True
    
    def test_olurrr(self):
        """'olurrr' should be detected as yes."""
        assert _is_confirmation_yes("olurrr") is True
    
    def test_okkk(self):
        """'okkk' should be detected as yes."""
        assert _is_confirmation_yes("okkk") is True
    
    def test_yesss(self):
        """'yesss' should be detected as yes."""
        assert _is_confirmation_yes("yesss") is True
    
    def test_elongated_with_phrase(self):
        """'tamaaaam yap' should be detected as yes."""
        assert _is_confirmation_yes("tamaaaam yap") is True
    
    def test_elongated_uppercase(self):
        """'EVEEET' should be detected as yes (case insensitive)."""
        assert _is_confirmation_yes("EVEEET") is True
        assert _is_confirmation_yes("TAMAAAAM") is True


# ============================================================================
# Test Elongated NO Confirmations
# ============================================================================

class TestElongatedNoConfirmations:
    """Test that elongated NO words are detected."""
    
    def test_haaaayir(self):
        """'haaaayırrr' should be detected as no."""
        assert _is_confirmation_no("haaaayırrr") is True
    
    def test_hayirrr(self):
        """'hayırrr' should be detected as no."""
        assert _is_confirmation_no("hayırrr") is True
    
    def test_hayiiir(self):
        """'hayııır' should be detected as no."""
        assert _is_confirmation_no("hayııır") is True
    
    def test_yoook(self):
        """'yoook' should be detected as no."""
        assert _is_confirmation_no("yoook") is True
    
    def test_yooook(self):
        """'yooook' should be detected as no."""
        assert _is_confirmation_no("yooook") is True
    
    def test_olmaaaaaz(self):
        """'olmaaaaaz' should be detected as no."""
        assert _is_confirmation_no("olmaaaaaz") is True
    
    def test_iptaaal(self):
        """'iptaaal' should be detected as no."""
        assert _is_confirmation_no("iptaaal") is True
    
    def test_nooo(self):
        """'nooo' should be detected as no."""
        assert _is_confirmation_no("nooo") is True
    
    def test_elongated_with_phrase(self):
        """'haaaayır vazgeç' should be detected as no."""
        assert _is_confirmation_no("haaaayır vazgeç") is True
    
    def test_elongated_uppercase(self):
        """'HAAAAYIR' should be detected as no (case insensitive)."""
        assert _is_confirmation_no("HAAAAYIR") is True
        assert _is_confirmation_no("YOOOK") is True


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestElongatedEdgeCases:
    """Test edge cases for elongated detection."""
    
    def test_gibberish_not_detected_as_yes(self):
        """Random elongated text should not be detected."""
        assert _is_confirmation_yes("aaaaaaa") is False
        assert _is_confirmation_yes("bbbbb") is False
    
    def test_gibberish_not_detected_as_no(self):
        """Random elongated text should not be detected."""
        assert _is_confirmation_no("aaaaaaa") is False
        assert _is_confirmation_no("bbbbb") is False
    
    def test_numbers_elongated(self):
        """Numbers should be normalized too."""
        assert _normalize_elongated("1111") == "1"
    
    def test_punctuation_elongated(self):
        """Punctuation should be normalized."""
        assert _normalize_elongated("!!!") == "!"
    
    def test_mixed_elongation(self):
        """Mixed elongated chars should all be reduced."""
        assert _normalize_elongated("haaayııırrrr") == "hayır"
    
    def test_real_world_scenario_1(self):
        """Real scenario: User types 'eveeet dostum' quickly."""
        assert _is_confirmation_yes("eveeet dostum") is True
    
    def test_real_world_scenario_2(self):
        """Real scenario: User types 'haaaayır istemiyorum' emphatically."""
        assert _is_confirmation_no("haaaayır istemiyorum") is True
    
    def test_turkish_char_elongation(self):
        """Turkish special chars should be handled."""
        assert _normalize_elongated("ıııı") == "ı"
        assert _normalize_elongated("üüüü") == "ü"
        assert _normalize_elongated("şşşş") == "ş"
        assert _normalize_elongated("öööö") == "ö"
        assert _normalize_elongated("çççç") == "ç"
        assert _normalize_elongated("ğğğğ") == "ğ"


# ============================================================================
# Test Action Words as Confirmation (Issue #316)
# ============================================================================

class TestActionWordConfirmations:
    """Test that action words like 'ekle', 'yap', 'koy' are accepted as yes."""
    
    def test_ekle_is_yes(self):
        """'ekle' should be detected as yes confirmation."""
        assert _is_confirmation_yes("ekle") is True
    
    def test_ekle_bakalim_is_yes(self):
        """'ekle bakalım' should be detected as yes confirmation."""
        assert _is_confirmation_yes("ekle bakalım") is True
    
    def test_ekle_onu_is_yes(self):
        """'ekle onu' should be detected as yes confirmation."""
        assert _is_confirmation_yes("ekle onu") is True
    
    def test_yap_is_yes(self):
        """'yap' should be detected as yes confirmation."""
        assert _is_confirmation_yes("yap") is True
    
    def test_yap_hadi_is_yes(self):
        """'yap hadi' should be detected as yes confirmation."""
        assert _is_confirmation_yes("yap hadi") is True
    
    def test_koy_is_yes(self):
        """'koy' should be detected as yes confirmation."""
        assert _is_confirmation_yes("koy") is True
    
    def test_koy_onu_is_yes(self):
        """'koy onu' should be detected as yes confirmation."""
        assert _is_confirmation_yes("koy onu") is True
    
    def test_kaydet_is_yes(self):
        """'kaydet' should be detected as yes confirmation."""
        assert _is_confirmation_yes("kaydet") is True
    
    def test_kaydet_lutfen_is_yes(self):
        """'kaydet lütfen' should be detected as yes confirmation."""
        assert _is_confirmation_yes("kaydet lütfen") is True
    
    def test_ekleee_elongated_is_yes(self):
        """'ekleee' (elongated) should be detected as yes."""
        assert _is_confirmation_yes("ekleee") is True
    
    def test_yappp_elongated_is_yes(self):
        """'yappp' (elongated) should be detected as yes."""
        assert _is_confirmation_yes("yappp") is True
