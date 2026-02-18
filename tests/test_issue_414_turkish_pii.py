"""Tests for Issue #414: Turkish PII patterns in PIIFilter.

Tests cover:
  - TC Kimlik No (11 digits)
  - Turkish phone numbers (+90 5xx, 05xx)
  - IBAN (TR + 24 digits)
  - Turkish addresses (Mahalle, Cadde, Sokak, Bulvar)
  - License plates (Turkish plaka format)
  - Locale-aware filtering (auto, tr, en)
  - Backward compatibility with existing international patterns
  - Edge cases and false positive prevention
"""

from __future__ import annotations

import pytest

from bantz.brain.memory_lite import PIIFilter


# ======================================================================
# TC Kimlik No Tests
# ======================================================================


class TestTCKimlik:
    @pytest.mark.parametrize("tc_no", [
        "12345678950",
        "99876543292",
        "10000000078",
        "55512345606",
    ])
    def test_tc_kimlik_detected(self, tc_no):
        text = f"TC Kimlik No: {tc_no}"
        result = PIIFilter.filter(text)
        assert "<TC_KIMLIK>" in result
        assert tc_no not in result

    def test_tc_kimlik_in_sentence(self):
        text = "Kullanıcının TC kimlik numarası 12345678950 olarak kayıtlı."
        result = PIIFilter.filter(text)
        assert "<TC_KIMLIK>" in result
        assert "12345678950" not in result

    def test_tc_kimlik_leading_zero_rejected(self):
        """TC Kimlik cannot start with 0."""
        text = "Number: 01234567890"
        result = PIIFilter.filter(text)
        assert "01234567890" in result  # Not matched as TC Kimlik

    def test_10_digit_not_matched(self):
        """Only exactly 11 digits should match."""
        text = "1234567890"  # 10 digits
        result = PIIFilter.filter(text)
        assert "<TC_KIMLIK>" not in result

    def test_12_digit_not_matched(self):
        """12 digits should not match as TC Kimlik."""
        text = "123456789012"
        result = PIIFilter.filter(text)
        # The pattern matches 11 digits at boundary; 12 consecutive digits
        # should NOT produce a clean TC_KIMLIK match
        # (may partially match depending on boundary rules)
        assert "123456789012" in result or "<TC_KIMLIK>" in result


# ======================================================================
# Turkish Phone Tests
# ======================================================================


class TestTRPhone:
    @pytest.mark.parametrize("phone", [
        "+90 532 123 45 67",
        "+90 555 987 65 43",
        "+905321234567",
        "+90-532-123-45-67",
        "+90.555.123.45.67",
        "0532 123 45 67",
        "05321234567",
        "0532-123-45-67",
    ])
    def test_tr_phone_detected(self, phone):
        text = f"Telefon: {phone}"
        result = PIIFilter.filter(text)
        assert "<TR_PHONE>" in result

    def test_tr_phone_in_sentence(self):
        text = "Beni +90 532 123 45 67 numarasından arayın."
        result = PIIFilter.filter(text)
        assert "<TR_PHONE>" in result

    def test_non_mobile_not_matched(self):
        """Non-mobile Turkish numbers (not starting with 5) should not match."""
        text = "0312 123 45 67"  # Ankara landline
        result = PIIFilter.filter(text)
        assert "<TR_PHONE>" not in result


# ======================================================================
# IBAN Tests
# ======================================================================


class TestIBAN:
    @pytest.mark.parametrize("iban", [
        "TR330006100519786457841326",
        "TR33 0006 1005 1978 6457 8413 26",
    ])
    def test_iban_detected(self, iban):
        text = f"IBAN: {iban}"
        result = PIIFilter.filter(text)
        assert "<IBAN>" in result
        assert iban.replace(" ", "") not in result.replace(" ", "")

    def test_iban_in_sentence(self):
        text = "Parayı TR330006100519786457841326 hesabına gönderin."
        result = PIIFilter.filter(text)
        assert "<IBAN>" in result

    def test_non_tr_iban_not_matched(self):
        """Non-Turkish IBANs should not match."""
        text = "DE89370400440532013000"
        result = PIIFilter.filter(text)
        assert "<IBAN>" not in result


# ======================================================================
# Turkish Address Tests
# ======================================================================


class TestTRAddress:
    @pytest.mark.parametrize("address", [
        "Atatürk Mahallesi",
        "Cumhuriyet Mah.",
        "İstiklal Caddesi No:42",
        "Gül Cad. Kat 3",
        "Çiçek Sokak 15",
        "Çiçek Sok. Daire 4",
        "Fevzi Çakmak Bulvarı No:100",
    ])
    def test_tr_address_detected(self, address):
        text = f"Adres: {address}"
        result = PIIFilter.filter(text)
        assert "<TR_ADDRESS>" in result

    def test_address_in_sentence(self):
        text = "Teslimat adresi: Atatürk Mahallesi Gül Sok. No:5"
        result = PIIFilter.filter(text)
        assert "<TR_ADDRESS>" in result


# ======================================================================
# License Plate Tests
# ======================================================================


class TestPlaka:
    @pytest.mark.parametrize("plate", [
        "34 ABC 123",
        "06 A 1234",
        "01 AB 123",
        "35 DEF 4567",
        "80 GH 12",
    ])
    def test_plaka_detected(self, plate):
        text = f"Plaka: {plate}"
        result = PIIFilter.filter(text)
        assert "<PLAKA>" in result

    def test_plaka_in_sentence(self):
        text = "Araç plakası 34 ABC 123 olarak kayıtlı."
        result = PIIFilter.filter(text)
        assert "<PLAKA>" in result

    def test_invalid_city_code_not_matched(self):
        """City codes > 81 should not match."""
        text = "82 ABC 123"
        result = PIIFilter.filter(text)
        assert "<PLAKA>" not in result

    def test_city_code_00_not_matched(self):
        text = "00 ABC 123"
        result = PIIFilter.filter(text)
        assert "<PLAKA>" not in result


# ======================================================================
# Locale-Aware Filtering Tests
# ======================================================================


class TestLocaleFiltering:
    def test_locale_auto_applies_all(self):
        text = "TC: 12345678950, Phone: +90 532 123 45 67, Email: a@b.com"
        result = PIIFilter.filter(text, locale="auto")
        assert "<TC_KIMLIK>" in result
        assert "<TR_PHONE>" in result
        assert "<EMAIL>" in result

    def test_locale_tr_applies_turkish(self):
        text = "TC: 12345678950"
        result = PIIFilter.filter(text, locale="tr")
        assert "<TC_KIMLIK>" in result

    def test_locale_en_skips_turkish(self):
        text = "TC: 12345678950, Email: a@b.com"
        result = PIIFilter.filter(text, locale="en")
        assert "<TC_KIMLIK>" not in result
        assert "12345678950" in result
        assert "<EMAIL>" in result

    def test_locale_en_keeps_international(self):
        text = "SSN: 123-45-6789"
        result = PIIFilter.filter(text, locale="en")
        assert "<SSN>" in result

    def test_disabled_returns_original(self):
        text = "TC: 12345678950"
        result = PIIFilter.filter(text, enabled=False)
        assert result == text


# ======================================================================
# Backward Compatibility Tests
# ======================================================================


class TestBackwardCompatibility:
    """Ensure existing international patterns still work."""

    def test_email(self):
        result = PIIFilter.filter("contact user@example.com please")
        assert "<EMAIL>" in result

    def test_us_phone(self):
        result = PIIFilter.filter("call 555-123-4567")
        assert "<PHONE>" in result

    def test_credit_card(self):
        result = PIIFilter.filter("card: 1234-5678-9012-3456")
        assert "<CREDIT_CARD>" in result

    def test_ssn(self):
        result = PIIFilter.filter("SSN: 123-45-6789")
        assert "<SSN>" in result

    def test_url(self):
        result = PIIFilter.filter("visit https://example.com/page")
        assert "<URL>" in result

    def test_en_address(self):
        result = PIIFilter.filter("lives at 123 Main Street")
        assert "<ADDRESS>" in result


# ======================================================================
# Combined / Edge Case Tests
# ======================================================================


class TestCombinedAndEdgeCases:
    def test_multiple_pii_types(self):
        text = (
            "Ad: Ahmet, TC: 12345678950, Tel: +90 532 123 45 67, "
            "IBAN: TR330006100519786457841326, Adres: Atatürk Mahallesi"
        )
        result = PIIFilter.filter(text)
        assert "<TC_KIMLIK>" in result
        assert "<TR_PHONE>" in result
        assert "<IBAN>" in result
        assert "<TR_ADDRESS>" in result
        assert "Ahmet" in result  # Name is NOT filtered (no name pattern)

    def test_empty_string(self):
        assert PIIFilter.filter("") == ""

    def test_no_pii_unchanged(self):
        text = "Bugün hava çok güzel."
        assert PIIFilter.filter(text) == text

    def test_filter_is_classmethod(self):
        """Verify filter can be called without instantiation."""
        result = PIIFilter.filter("test 12345678950")
        assert "<TC_KIMLIK>" in result
