# SPDX-License-Identifier: MIT
"""
Tests for language_guard — Issue #653.

Verifies:
- CJK character detection (Chinese, Japanese, Korean)
- Turkish confidence scoring
- Language issue detection
- validate_turkish() fallback behavior
- Integration with llm_router and finalization_pipeline
"""

import pytest

from bantz.brain.language_guard import (
    count_language_chars,
    cjk_ratio,
    detect_language_issue,
    has_cjk,
    turkish_confidence,
    validate_turkish,
)


# ============================================================================
# CJK Detection
# ============================================================================


class TestCJKDetection:
    """Tests for Chinese/Japanese/Korean character detection."""

    def test_pure_chinese(self):
        """Pure Chinese text should be detected."""
        assert has_cjk("你好世界")
        assert has_cjk("我是一个AI助手")

    def test_pure_japanese_hiragana(self):
        """Japanese hiragana should be detected."""
        assert has_cjk("こんにちは")

    def test_pure_japanese_katakana(self):
        """Japanese katakana should be detected."""
        assert has_cjk("コンニチハ")

    def test_pure_korean(self):
        """Korean hangul should be detected."""
        assert has_cjk("안녕하세요")

    def test_mixed_turkish_chinese(self):
        """Turkish text with embedded Chinese should be detected."""
        assert has_cjk("Merhaba 你好 nasılsınız")

    def test_pure_turkish_no_cjk(self):
        """Pure Turkish text should NOT trigger CJK detection."""
        assert not has_cjk("Merhaba, nasılsınız? İyi günler!")
        assert not has_cjk("YouTube'u açıyorum efendim.")
        assert not has_cjk("Günaydın, bugün hava güzel.")

    def test_single_cjk_below_threshold(self):
        """Single CJK char should not trigger default threshold=2."""
        assert not has_cjk("test 你 test")

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        assert has_cjk("test 你 test", threshold=1)
        assert not has_cjk("test 你 test", threshold=2)

    def test_empty_string(self):
        assert not has_cjk("")

    def test_digits_only(self):
        assert not has_cjk("12345")


class TestCJKRatio:
    """Tests for CJK character ratio calculation."""

    def test_pure_chinese(self):
        assert cjk_ratio("你好世界") == 1.0

    def test_pure_turkish(self):
        assert cjk_ratio("merhaba") == 0.0

    def test_half_half(self):
        ratio = cjk_ratio("ab你好")  # 2 latin + 2 CJK
        assert 0.4 <= ratio <= 0.6

    def test_empty(self):
        assert cjk_ratio("") == 0.0

    def test_whitespace_only(self):
        assert cjk_ratio("   ") == 0.0


# ============================================================================
# Character Counting
# ============================================================================


class TestCharCounting:
    """Tests for count_language_chars()."""

    def test_turkish_special_chars(self):
        counts = count_language_chars("İstanbul güneşli")
        assert counts.get("turkish_latin", 0) >= 3  # İ, ü, ş

    def test_latin_chars(self):
        counts = count_language_chars("hello world")
        assert counts.get("latin", 0) >= 8

    def test_cjk_chars(self):
        counts = count_language_chars("你好")
        assert counts.get("cjk", 0) == 2

    def test_cyrillic_chars(self):
        counts = count_language_chars("Привет")
        assert counts.get("cyrillic", 0) >= 5

    def test_mixed(self):
        counts = count_language_chars("Merhaba 你好 Привет")
        assert counts.get("latin", 0) > 0
        assert counts.get("cjk", 0) > 0
        assert counts.get("cyrillic", 0) > 0


# ============================================================================
# Turkish Confidence
# ============================================================================


class TestTurkishConfidence:
    """Tests for turkish_confidence() scoring."""

    def test_pure_turkish_high_confidence(self):
        """Common Turkish text should score high."""
        conf = turkish_confidence("Merhaba, nasılsınız? İyi günler efendim.")
        assert conf >= 0.7, f"Turkish text scored only {conf}"

    def test_pure_chinese_low_confidence(self):
        """Chinese text should score very low."""
        conf = turkish_confidence("我是一个人工智能助手，很高兴为您服务")
        assert conf <= 0.2, f"Chinese text scored {conf}"

    def test_pure_english_moderate(self):
        """English text without Turkish markers should score moderate-low."""
        conf = turkish_confidence("Hello, how are you doing today? Fine thanks.")
        assert conf <= 0.55, f"English text scored {conf}"

    def test_turkish_with_special_chars(self):
        """Turkish chars (ı, ğ, ş, ç, ö, ü) should boost confidence."""
        # With Turkish chars
        conf_tr = turkish_confidence("şöyle güzel bir gün geçirdik")
        # Without Turkish chars (plain ASCII)
        conf_en = turkish_confidence("soyle guzel bir gun gecirdik")
        assert conf_tr > conf_en

    def test_empty_string(self):
        assert turkish_confidence("") == 0.0

    def test_whitespace_only(self):
        assert turkish_confidence("   ") == 0.0

    def test_digits_only_neutral(self):
        """Digit-only strings should be neutral (not rejected)."""
        conf = turkish_confidence("12345")
        assert conf == 0.5


# ============================================================================
# Language Issue Detection
# ============================================================================


class TestDetectLanguageIssue:
    """Tests for detect_language_issue()."""

    def test_turkish_text_no_issue(self):
        """Normal Turkish text should pass."""
        assert detect_language_issue("YouTube'u açıyorum efendim.") is None
        assert detect_language_issue("Tamam, hatırlatma oluşturdum.") is None
        assert detect_language_issue("İyi günler, nasıl yardımcı olabilirim?") is None

    def test_chinese_text_detected(self):
        assert detect_language_issue("我已经帮您打开了YouTube") == "cjk_detected"

    def test_japanese_text_detected(self):
        assert detect_language_issue("こんにちは、お元気ですか") == "cjk_detected"

    def test_korean_text_detected(self):
        assert detect_language_issue("안녕하세요 도움이 필요하시면") == "cjk_detected"

    def test_cyrillic_text_detected(self):
        assert detect_language_issue("Привет, как вы сегодня?") == "cyrillic_detected"

    def test_mixed_turkish_and_little_cjk(self):
        """Turkish with a few CJK chars should still be caught."""
        assert detect_language_issue("Merhaba 你好 efendim") == "cjk_detected"

    def test_very_short_text_passes(self):
        """Text shorter than 3 chars should not be judged."""
        assert detect_language_issue("") is None
        assert detect_language_issue("ab") is None

    def test_url_with_path_passes(self):
        """URLs and technical strings should not be flagged."""
        assert detect_language_issue("https://www.youtube.com/watch?v=abc123") is None

    def test_code_snippet_passes(self):
        """Code-like strings should pass (no Turkish markers but no foreign script)."""
        # Short code snippets are neutral
        assert detect_language_issue("print('hello')") is None

    def test_deterministic_turkish_replies_pass(self):
        """Standard Bantz deterministic replies should always pass."""
        replies = [
            "Efendim, isteğiniz işleniyor.",
            "Tamam, YouTube açılıyor.",
            "Hatırlatma oluşturuldu.",
            "Efendim, tam anlayamadım. Tekrar eder misiniz?",
            "Ses seviyesi artırıldı.",
        ]
        for reply in replies:
            assert detect_language_issue(reply) is None, f"False positive on: {reply}"


# ============================================================================
# validate_turkish()
# ============================================================================


class TestValidateTurkish:
    """Tests for the validate_turkish() convenience wrapper."""

    def test_valid_turkish_passes_through(self):
        text = "YouTube'u açıyorum efendim."
        result, valid = validate_turkish(text)
        assert valid is True
        assert result == text

    def test_chinese_returns_fallback(self):
        text = "我已经为您打开了YouTube浏览器"
        result, valid = validate_turkish(text)
        assert valid is False
        assert result != text
        # Fallback should be Turkish
        assert detect_language_issue(result) is None

    def test_custom_fallback(self):
        text = "你好世界"
        result, valid = validate_turkish(text, fallback="Özel mesaj.")
        assert valid is False
        assert result == "Özel mesaj."

    def test_empty_string_passes(self):
        """Empty/very short strings should pass (neutral)."""
        result, valid = validate_turkish("")
        assert valid is True

    def test_korean_returns_fallback(self):
        text = "안녕하세요 유튜브를 열었습니다"
        result, valid = validate_turkish(text)
        assert valid is False


# ============================================================================
# Integration: llm_router._extract_output language filtering
# ============================================================================


class TestIssue653RouterIntegration:
    """Verify _extract_output clears non-Turkish assistant_reply."""

    def test_chinese_reply_cleared_in_extract_output(self):
        """If 3B model outputs Chinese assistant_reply, it should be cleared."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        orch = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)
        orch._confidence_threshold = 0.3

        parsed = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "你好，我是Jarvis助手。很高兴为您服务！",
        }

        result = orch._extract_output(parsed, raw_text="{}", user_input="merhaba")
        # Chinese reply should have been cleared
        assert not has_cjk(result.assistant_reply), \
            f"Chinese text leaked through: {result.assistant_reply}"

    def test_turkish_reply_preserved_in_extract_output(self):
        """Normal Turkish assistant_reply should be preserved."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        orch = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)
        orch._confidence_threshold = 0.3

        parsed = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "Merhaba efendim, size nasıl yardımcı olabilirim?",
        }

        result = orch._extract_output(parsed, raw_text="{}", user_input="merhaba")
        assert result.assistant_reply == "Merhaba efendim, size nasıl yardımcı olabilirim?"


# ============================================================================
# Integration: finalization_pipeline language filtering
# ============================================================================


class TestIssue653FinalizationIntegration:
    """Verify _validate_reply_language works in finalization pipeline."""

    def test_validate_reply_language_passes_turkish(self):
        from bantz.brain.finalization_pipeline import _validate_reply_language

        text = "Takvim etkinliğiniz oluşturuldu efendim."
        assert _validate_reply_language(text) == text

    def test_validate_reply_language_rejects_chinese(self):
        from bantz.brain.finalization_pipeline import _validate_reply_language

        text = "我已经为您创建了日历事件"
        result = _validate_reply_language(text)
        assert result != text
        # Should return deterministic Turkish fallback
        assert detect_language_issue(result) is None

    def test_validate_reply_language_rejects_korean(self):
        from bantz.brain.finalization_pipeline import _validate_reply_language

        text = "캘린더 이벤트가 생성되었습니다"
        result = _validate_reply_language(text)
        assert result != text
