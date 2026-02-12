"""Tests for Issue #1017: Arabic/Hebrew detection gap."""

from __future__ import annotations

import unittest


class TestArabicHebrewDetection(unittest.TestCase):
    """Arabic/Hebrew text should be detected by language_guard."""

    def test_has_arabic_hebrew_function_exists(self):
        """has_arabic_hebrew should be importable."""
        from bantz.brain.language_guard import has_arabic_hebrew
        self.assertTrue(callable(has_arabic_hebrew))

    def test_arabic_text_detected(self):
        """Arabic text should be detected."""
        from bantz.brain.language_guard import has_arabic_hebrew
        self.assertTrue(has_arabic_hebrew("مرحبا بالعالم"))  # "Hello World" in Arabic

    def test_hebrew_text_detected(self):
        """Hebrew text should be detected."""
        from bantz.brain.language_guard import has_arabic_hebrew
        self.assertTrue(has_arabic_hebrew("שלום עולם"))  # "Hello World" in Hebrew

    def test_latin_text_not_detected(self):
        """Latin text should NOT trigger Arabic/Hebrew detection."""
        from bantz.brain.language_guard import has_arabic_hebrew
        self.assertFalse(has_arabic_hebrew("Hello World"))

    def test_turkish_text_not_detected(self):
        """Turkish text should NOT trigger Arabic/Hebrew detection."""
        from bantz.brain.language_guard import has_arabic_hebrew
        self.assertFalse(has_arabic_hebrew("Merhaba dünya, nasılsın?"))

    def test_detect_language_issue_arabic(self):
        """detect_language_issue should return 'arabic_hebrew_detected' for Arabic."""
        from bantz.brain.language_guard import detect_language_issue
        result = detect_language_issue("مرحبا بالعالم هذا نص عربي")
        self.assertEqual(result, "arabic_hebrew_detected")

    def test_detect_language_issue_hebrew(self):
        """detect_language_issue should return 'arabic_hebrew_detected' for Hebrew."""
        from bantz.brain.language_guard import detect_language_issue
        result = detect_language_issue("שלום עולם זה טקסט בעברית")
        self.assertEqual(result, "arabic_hebrew_detected")

    def test_detect_language_issue_turkish_ok(self):
        """detect_language_issue should return None for Turkish text."""
        from bantz.brain.language_guard import detect_language_issue
        result = detect_language_issue("Merhaba efendim, bugün hava çok güzel.")
        self.assertIsNone(result)

    def test_docstring_mentions_arabic_hebrew(self):
        """detect_language_issue docstring should document arabic_hebrew_detected."""
        from bantz.brain.language_guard import detect_language_issue
        doc = detect_language_issue.__doc__ or ""
        self.assertIn("arabic_hebrew_detected", doc)

    def test_threshold_parameter(self):
        """has_arabic_hebrew threshold should be respected."""
        from bantz.brain.language_guard import has_arabic_hebrew
        # Single Arabic char — below default threshold of 2
        self.assertFalse(has_arabic_hebrew("test م ok"))
        # Two Arabic chars — meets threshold
        self.assertTrue(has_arabic_hebrew("test مر ok"))


if __name__ == "__main__":
    unittest.main()
