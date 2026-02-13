"""Tests for Issue #293 — Dismiss / stop intent detection.

Covers all Turkish dismiss phrases, confidence scoring,
confirmation threshold, response selection, and edge cases.
"""

from __future__ import annotations

import pytest


# ── Phrase detection ──────────────────────────────────────────

class TestDismissPhrases:
    """Ensure all specified Turkish phrases are detected."""

    @pytest.mark.parametrize("text", [
        "teşekkürler şimdilik",
        "teşekkür ederim",
        "teşekkürler artık",
        "şimdilik sana ihtiyacım yok",
        "görüşürüz",
        "hoşça kal",
        "kapat kendini",
        "kapat",
        "sus artık",
        "tamam bu kadar",
        "tamam",
        "yeter bu kadar",
        "yeter",
        "iyi çalışmalar",
        "sağ ol bantz",
        "sağ ol",
        "eyvallah",
        "güle güle",
        "bay bay",
        "hadi görüşürüz",
        "sonra görüşürüz",
    ])
    def test_phrase_detected(self, text):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        result = det.detect(text)
        assert result.is_dismiss, f"'{text}' should be detected as dismiss"
        assert result.confidence > 0.5
        assert result.response is not None

    @pytest.mark.parametrize("text", [
        "hava durumu nasıl",
        "toplantım saat kaçta",
        "python ile nasıl dosya açarım",
        "bu projede kaç test var",
        "",
        "   ",
    ])
    def test_non_dismiss(self, text):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        result = det.detect(text)
        assert not result.is_dismiss
        assert result.confidence == 0.0


# ── Case insensitive ─────────────────────────────────────────

class TestCaseInsensitive:
    def test_uppercase(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        result = det.detect("GÖRÜŞÜRÜZ")
        assert result.is_dismiss

    def test_mixed_case(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        result = det.detect("Teşekkürler Şimdilik")
        assert result.is_dismiss


# ── Confidence scoring ────────────────────────────────────────

class TestConfidence:
    def test_exact_phrase_high_confidence(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        result = det.detect("görüşürüz")
        assert result.confidence >= 0.9

    def test_phrase_in_sentence_lower_confidence(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        result = det.detect("ben şimdi başka bir şey yapacağım tamam bu kadar yardım için teşekkürler")
        assert result.is_dismiss
        assert result.confidence >= 0.6


# ── Confirmation threshold ────────────────────────────────────

class TestConfirmation:
    def test_high_confidence_no_confirm(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        assert not det.needs_confirmation(0.95)

    def test_low_confidence_no_confirm(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        assert not det.needs_confirmation(0.3)

    def test_ambiguous_needs_confirm(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        assert det.needs_confirmation(0.65)


# ── Response pool ─────────────────────────────────────────────

class TestResponses:
    def test_pick_response(self):
        from bantz.intents.dismiss import DismissIntentDetector
        det = DismissIntentDetector()
        resp = det.pick_response()
        assert isinstance(resp, str)
        assert "efendim" in resp

    def test_all_responses_have_efendim(self):
        from bantz.intents.dismiss import DISMISS_RESPONSES
        for r in DISMISS_RESPONSES:
            assert "efendim" in r, f"Response missing 'efendim': {r}"


# ── DismissResult ─────────────────────────────────────────────

class TestDismissResult:
    def test_fields(self):
        from bantz.intents.dismiss import DismissResult
        r = DismissResult(is_dismiss=True, confidence=0.9, matched_phrase="görüşürüz", response="Bye")
        assert r.is_dismiss
        assert r.confidence == 0.9
        assert r.matched_phrase == "görüşürüz"

    def test_false_result(self):
        from bantz.intents.dismiss import DismissResult
        r = DismissResult(is_dismiss=False, confidence=0.0)
        assert not r.is_dismiss
        assert r.matched_phrase is None


# ── File existence ────────────────────────────────────────────

class TestFileExistence:
    def test_dismiss_py_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "intents" / "dismiss.py").is_file()

    def test_intents_init_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "intents" / "__init__.py").is_file()
