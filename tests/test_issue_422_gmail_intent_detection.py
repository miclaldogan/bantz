"""Tests for Issue #422: Gmail intent detection — rule-based Turkish keyword fallback.

Covers:
- detect_gmail_intent: keyword pattern matching for send/read/search/list
- resolve_gmail_intent: combining LLM output with keyword fallback
- Integration: _extract_output applies gmail intent resolution
- 20+ Turkish gmail sentences for accuracy measurement
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from bantz.brain.gmail_intent import detect_gmail_intent, resolve_gmail_intent


# ============================================================================
# Helper
# ============================================================================

class MockLLM:
    def __init__(self, response=""):
        self.response = response
    def complete_text(self, *, prompt, temperature=0.0, max_tokens=200):
        return self.response


def _make_router(response=""):
    from bantz.brain.llm_router import JarvisLLMOrchestrator
    return JarvisLLMOrchestrator(llm=MockLLM(response))


# ============================================================================
# detect_gmail_intent: Send patterns
# ============================================================================

class TestDetectSend:
    """Test send intent detection."""

    @pytest.mark.parametrize("text", [
        "Ali'ye mail gönder",
        "ali'ye e-posta gönder",
        "ahmet'e mesaj gönder",
        "mail at ali'ye",
        "ali'ye mail at",
        "mail yolla",
        "e-posta ilet",
        "mail yaz ahmet'e",
        "e-posta yaz",
        "maili cevapla",
        "cevap ver maile",
        "maili yanıtla",
    ])
    def test_send_detected(self, text):
        assert detect_gmail_intent(text) == "send"

    def test_at_without_mail_context_not_detected(self):
        """'at' alone without mail context should not trigger send."""
        assert detect_gmail_intent("topu at") is None

    def test_yaz_without_mail_context_not_detected(self):
        """'yaz' alone without mail context should not trigger send."""
        assert detect_gmail_intent("bir şey yaz") is None


# ============================================================================
# detect_gmail_intent: Read patterns
# ============================================================================

class TestDetectRead:
    """Test read intent detection."""

    @pytest.mark.parametrize("text", [
        "maili oku",
        "e-postayı oku",
        "mesajı oku",
        "maili aç",
        "e-postayı aç",
        "maile bak",
        "maili göster",
        "son maili oku",
        "gelen maili aç",
        "yeni maili göster",
    ])
    def test_read_detected(self, text):
        assert detect_gmail_intent(text) == "read"


# ============================================================================
# detect_gmail_intent: Search patterns
# ============================================================================

class TestDetectSearch:
    """Test search intent detection."""

    @pytest.mark.parametrize("text", [
        "mail ara",
        "e-posta bul",
        "mail filtrele",
        "linkedin maili",
        "amazon mailini",
        "ali'den gelen mail",
    ])
    def test_search_detected(self, text):
        assert detect_gmail_intent(text) == "search"


# ============================================================================
# detect_gmail_intent: List patterns
# ============================================================================

class TestDetectList:
    """Test list intent detection."""

    @pytest.mark.parametrize("text", [
        "mailleri listele",
        "e-postaları sırala",
        "kaç mail var",
        "gelen kutum",
        "gelen kutusu",
        "maillerim",
        "son mailler",
        "tüm mailleri göster",
        "yeni mesajları göster",
    ])
    def test_list_detected(self, text):
        assert detect_gmail_intent(text) == "list"


# ============================================================================
# detect_gmail_intent: No detection
# ============================================================================

class TestDetectNone:
    """Test cases where no gmail intent should be detected."""

    @pytest.mark.parametrize("text", [
        "",
        "bugün hava nasıl",
        "saat beşte toplantı yap",
        "youtube aç",
        "müzik çal",
        "merhaba",
    ])
    def test_no_gmail_context(self, text):
        assert detect_gmail_intent(text) is None


# ============================================================================
# resolve_gmail_intent: LLM trust vs fallback
# ============================================================================

class TestResolveGmailIntent:
    """Test the resolution logic combining LLM and keyword detection."""

    def test_valid_llm_intent_trusted(self):
        """LLM returns valid intent → trust it."""
        assert resolve_gmail_intent(llm_intent="send", user_text="mail gönder", route="gmail") == "send"
        assert resolve_gmail_intent(llm_intent="read", user_text="mail oku", route="gmail") == "read"
        assert resolve_gmail_intent(llm_intent="search", user_text="mail ara", route="gmail") == "search"
        assert resolve_gmail_intent(llm_intent="list", user_text="maillerim", route="gmail") == "list"

    def test_none_llm_falls_back_to_keyword(self):
        """LLM returns 'none' → use keyword detection."""
        assert resolve_gmail_intent(llm_intent="none", user_text="ali'ye mail gönder", route="gmail") == "send"
        assert resolve_gmail_intent(llm_intent="none", user_text="maili oku", route="gmail") == "read"
        assert resolve_gmail_intent(llm_intent="none", user_text="mail ara", route="gmail") == "search"

    def test_llm_wrong_intent_overridden(self):
        """LLM returns valid but wrong intent → we trust LLM (conservative)."""
        # LLM said 'send' but user said 'oku' — we trust LLM when it's not 'none'
        result = resolve_gmail_intent(llm_intent="send", user_text="maili oku", route="gmail")
        assert result == "send"  # Trust LLM

    def test_route_gmail_no_keyword_defaults_to_list(self):
        """Route is gmail but no keyword match → default to 'list'."""
        assert resolve_gmail_intent(llm_intent="none", user_text="gmail", route="gmail") == "list"

    def test_no_gmail_context_returns_none(self):
        """No gmail context in text and LLM says none → return 'none'."""
        assert resolve_gmail_intent(llm_intent="none", user_text="hava nasıl", route="smalltalk") == "none"


# ============================================================================
# Integration: _extract_output uses resolve_gmail_intent
# ============================================================================

class TestExtractOutputGmailIntegration:
    """Test that _extract_output applies gmail intent resolution."""

    def test_llm_none_keyword_send(self):
        """LLM gmail_intent=none + user says 'mail gönder' → send."""
        router = _make_router()
        parsed = {
            "route": "gmail",
            "calendar_intent": "none",
            "gmail_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "test",
            "slots": {},
        }
        result = router._extract_output(parsed, raw_text="", user_input="ali'ye mail gönder", repaired=False)
        assert result.gmail_intent == "send"

    def test_llm_none_keyword_read(self):
        """LLM gmail_intent=none + user says 'maili oku' → read."""
        router = _make_router()
        parsed = {
            "route": "gmail",
            "calendar_intent": "none",
            "gmail_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
            "slots": {},
        }
        result = router._extract_output(parsed, raw_text="", user_input="maili oku", repaired=False)
        assert result.gmail_intent == "read"

    def test_llm_valid_intent_preserved(self):
        """LLM gmail_intent=send → preserved even with different keywords."""
        router = _make_router()
        parsed = {
            "route": "gmail",
            "calendar_intent": "none",
            "gmail_intent": "send",
            "confidence": 0.9,
            "tool_plan": ["gmail.send"],
            "assistant_reply": "test",
            "slots": {},
        }
        result = router._extract_output(parsed, raw_text="", user_input="mail gönder", repaired=False)
        assert result.gmail_intent == "send"

    def test_no_user_input_no_change(self):
        """Without user_input, gmail_intent from LLM is used as-is."""
        router = _make_router()
        parsed = {
            "route": "gmail",
            "calendar_intent": "none",
            "gmail_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
            "slots": {},
        }
        result = router._extract_output(parsed, raw_text="", user_input="", repaired=False)
        assert result.gmail_intent == "none"


# ============================================================================
# Accuracy: 20+ Turkish Gmail sentences
# ============================================================================

class TestTurkishGmailAccuracy:
    """Accuracy test with 20+ real-world Turkish Gmail sentences."""

    @pytest.mark.parametrize("text,expected", [
        # SEND (7)
        ("Ali'ye mail gönder", "send"),
        ("ahmet'e e-posta at", "send"),
        ("Mehmet'e mesaj yolla", "send"),
        ("mail yaz direktöre", "send"),
        ("e-posta gönder patrona", "send"),
        ("maili yanıtla", "send"),
        ("cevap ver maile", "send"),
        # READ (5)
        ("son maili oku", "read"),
        ("gelen maili aç", "read"),
        ("maili göster", "read"),
        ("e-postayı oku", "read"),
        ("yeni maile bak", "read"),
        # SEARCH (4)
        ("linkedin maili", "search"),
        ("amazon mailini bul", "search"),
        ("mail ara promotions", "search"),
        ("ali'den gelen mail", "search"),
        # LIST (4)
        ("mailleri listele", "list"),
        ("kaç mail var", "list"),
        ("gelen kutum", "list"),
        ("son mailler", "list"),
    ])
    def test_accuracy_corpus(self, text, expected):
        result = detect_gmail_intent(text)
        assert result == expected, f"Text: '{text}' → expected '{expected}', got '{result}'"

    def test_accuracy_rate(self):
        """Overall accuracy should be 100% on this corpus."""
        corpus = [
            ("Ali'ye mail gönder", "send"),
            ("ahmet'e e-posta at", "send"),
            ("Mehmet'e mesaj yolla", "send"),
            ("mail yaz direktöre", "send"),
            ("e-posta gönder patrona", "send"),
            ("maili yanıtla", "send"),
            ("cevap ver maile", "send"),
            ("son maili oku", "read"),
            ("gelen maili aç", "read"),
            ("maili göster", "read"),
            ("e-postayı oku", "read"),
            ("yeni maile bak", "read"),
            ("linkedin maili", "search"),
            ("amazon mailini bul", "search"),
            ("mail ara promotions", "search"),
            ("ali'den gelen mail", "search"),
            ("mailleri listele", "list"),
            ("kaç mail var", "list"),
            ("gelen kutum", "list"),
            ("son mailler", "list"),
        ]
        correct = sum(1 for text, exp in corpus if detect_gmail_intent(text) == exp)
        accuracy = correct / len(corpus) * 100
        assert accuracy == 100.0, f"Accuracy: {accuracy}% ({correct}/{len(corpus)})"
