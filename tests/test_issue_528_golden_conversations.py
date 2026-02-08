"""Golden Conversations Test Suite — Türkçe Regresyon (Issue #528).

YAML-based golden scenarios → mock LLM → deterministic assertion.

Yeni senaryo eklemek: tests/golden/golden_conversations_tr.yaml dosyasına
bir blok ekle, testler otomatik çalışır.

Run:
    pytest tests/test_issue_528_golden_conversations.py -v
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml

# ── Golden YAML Loader ────────────────────────────────────────

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "golden_conversations_tr.yaml"


def load_golden_scenarios() -> List[Dict[str, Any]]:
    """Load all golden scenarios from YAML."""
    assert GOLDEN_FILE.exists(), f"Golden dosyası bulunamadı: {GOLDEN_FILE}"
    with open(GOLDEN_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["scenarios"]


SCENARIOS = load_golden_scenarios()

# Separate single-turn and multi-turn scenarios
SINGLE_TURN_SCENARIOS = [s for s in SCENARIOS if "turns" not in s]
MULTI_TURN_SCENARIOS = [s for s in SCENARIOS if "turns" in s]


# ── Language quality helpers ──────────────────────────────────

# Common English words that should NOT appear in Turkish responses
ENGLISH_STOP_WORDS = frozenset({
    "the", "is", "are", "was", "were", "have", "has", "been",
    "will", "would", "could", "should", "can", "may", "might",
    "this", "that", "these", "those", "what", "which", "where",
    "when", "how", "why", "who", "from", "with", "for", "and",
    "but", "not", "yes", "hello", "sorry", "please", "thank",
    "you", "your", "here", "there", "about", "just", "like",
    "very", "much", "more", "also", "too", "only", "really",
    "because", "however", "therefore", "although", "while",
    "still", "then", "than", "before", "after", "during",
})

# Chinese/Japanese/Korean Unicode ranges
CJK_PATTERN = re.compile(
    r"[\u4e00-\u9fff"    # CJK Unified Ideographs
    r"\u3400-\u4dbf"     # CJK Extension A
    r"\u3000-\u303f"     # CJK Symbols and Punctuation
    r"\u3040-\u309f"     # Hiragana
    r"\u30a0-\u30ff"     # Katakana
    r"\uac00-\ud7af]"    # Hangul
)

# Technical/domain terms that are OK in English
ALLOWED_ENGLISH = frozenset({
    "ok", "e-mail", "email", "gmail", "google", "calendar",
    "api", "json", "http", "url", "id", "event", "query",
    "tool", "slot", "route", "status", "pm", "am",
})


def contains_english_words(text: str) -> List[str]:
    """Return list of English stop words found in text."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
    found = []
    for word in words:
        if word in ENGLISH_STOP_WORDS and word not in ALLOWED_ENGLISH:
            found.append(word)
    return found


def contains_cjk_chars(text: str) -> List[str]:
    """Return list of CJK characters found in text."""
    if not text:
        return []
    return CJK_PATTERN.findall(text)


# ── Mock LLM for deterministic testing ───────────────────────

class GoldenMockLLM:
    """Deterministic mock LLM that returns exact JSON from golden spec."""

    def __init__(self) -> None:
        self._responses: Dict[str, Dict[str, Any]] = {}
        self.calls: List[str] = []

    def set_response(self, user_input: str, response: Dict[str, Any]) -> None:
        """Set the response for a specific user input."""
        self._responses[user_input.strip().lower()] = response

    def route(self, user_input: str, **kwargs: Any) -> Dict[str, Any]:
        """Simulate LLM routing — return mock JSON."""
        self.calls.append(user_input)
        key = user_input.strip().lower()

        # Exact match first
        if key in self._responses:
            return dict(self._responses[key])

        # Substring match fallback
        for pattern, response in self._responses.items():
            if pattern in key or key in pattern:
                return dict(response)

        # Fallback
        return {
            "route": "unknown",
            "calendar_intent": "none",
            "confidence": 0.0,
            "tool_plan": [],
            "assistant_reply": "",
            "slots": {},
        }


# ── Assertion helpers ─────────────────────────────────────────

def assert_expected_fields(
    output: Dict[str, Any],
    expected: Dict[str, Any],
    scenario_id: str,
) -> None:
    """Assert that output matches expected fields from golden spec."""
    for key, expected_value in expected.items():
        # Special constraint keys
        if key == "confidence_gte":
            actual = output.get("confidence", 0.0)
            assert actual >= expected_value, (
                f"[{scenario_id}] confidence={actual} < {expected_value}"
            )
            continue

        if key == "confidence_lte":
            actual = output.get("confidence", 1.0)
            assert actual <= expected_value, (
                f"[{scenario_id}] confidence={actual} > {expected_value}"
            )
            continue

        # Standard field comparison
        actual = output.get(key)

        if isinstance(expected_value, dict):
            # Partial dict match — all expected keys must be in actual
            assert isinstance(actual, dict), (
                f"[{scenario_id}] {key}: beklenen dict, gelen={type(actual).__name__}"
            )
            for dk, dv in expected_value.items():
                assert dk in actual, (
                    f"[{scenario_id}] {key}.{dk} bulunamadı"
                )
                assert actual[dk] == dv, (
                    f"[{scenario_id}] {key}.{dk}: beklenen={dv}, gelen={actual[dk]}"
                )
        elif isinstance(expected_value, list):
            assert isinstance(actual, list), (
                f"[{scenario_id}] {key}: beklenen list, gelen={type(actual).__name__}"
            )
            assert actual == expected_value, (
                f"[{scenario_id}] {key}: beklenen={expected_value}, gelen={actual}"
            )
        else:
            assert actual == expected_value, (
                f"[{scenario_id}] {key}: beklenen={expected_value}, gelen={actual}"
            )


def assert_constraints(
    output: Dict[str, Any],
    constraints: Dict[str, Any],
    scenario_id: str,
) -> None:
    """Assert language and quality constraints."""
    reply = output.get("assistant_reply", "")
    question = output.get("question", "")
    text_to_check = f"{reply} {question}".strip()

    if constraints.get("no_english"):
        english_found = contains_english_words(text_to_check)
        assert not english_found, (
            f"[{scenario_id}] İngilizce kelimeler bulundu: {english_found} — "
            f"text='{text_to_check[:80]}'"
        )

    if constraints.get("no_chinese"):
        cjk_found = contains_cjk_chars(text_to_check)
        assert not cjk_found, (
            f"[{scenario_id}] CJK karakterler bulundu: {cjk_found} — "
            f"text='{text_to_check[:80]}'"
        )


# ── SINGLE-TURN TESTS ────────────────────────────────────────

class TestGoldenSingleTurn:
    """Her tek-turn golden senaryoyu test et."""

    @pytest.fixture
    def mock_llm(self) -> GoldenMockLLM:
        return GoldenMockLLM()

    @pytest.mark.parametrize(
        "scenario",
        SINGLE_TURN_SCENARIOS,
        ids=[s["id"] for s in SINGLE_TURN_SCENARIOS],
    )
    def test_golden_scenario(
        self,
        scenario: Dict[str, Any],
        mock_llm: GoldenMockLLM,
    ) -> None:
        """Golden senaryo: {scenario[id]}"""
        sid = scenario["id"]
        user_input = scenario["input"]
        mock_response = scenario["mock_response"]
        expected = scenario["expected"]
        constraints = scenario.get("constraints", {})

        # Set up mock
        mock_llm.set_response(user_input, mock_response)

        # Run mock LLM
        output = mock_llm.route(user_input)

        # Assert expected fields
        assert_expected_fields(output, expected, sid)

        # Assert constraints
        assert_constraints(output, constraints, sid)


# ── MULTI-TURN TESTS ─────────────────────────────────────────

class TestGoldenMultiTurn:
    """Çok-turn golden senaryoları test et (anaphora vb.)."""

    @pytest.fixture
    def mock_llm(self) -> GoldenMockLLM:
        return GoldenMockLLM()

    @pytest.mark.parametrize(
        "scenario",
        MULTI_TURN_SCENARIOS,
        ids=[s["id"] for s in MULTI_TURN_SCENARIOS],
    )
    def test_golden_multi_turn(
        self,
        scenario: Dict[str, Any],
        mock_llm: GoldenMockLLM,
    ) -> None:
        """Çok-turn golden senaryo: {scenario[id]}"""
        sid = scenario["id"]
        turns = scenario["turns"]

        for i, turn in enumerate(turns):
            turn_id = f"{sid}_turn{i + 1}"
            user_input = turn["input"]
            mock_response = turn["mock_response"]
            expected = turn["expected"]
            constraints = turn.get("constraints", {})

            mock_llm.set_response(user_input, mock_response)
            output = mock_llm.route(user_input)

            assert_expected_fields(output, expected, turn_id)
            if constraints:
                assert_constraints(output, constraints, turn_id)


# ── LANGUAGE QUALITY TESTS ────────────────────────────────────

class TestLanguageQuality:
    """Tüm golden senaryoların dil kalitesini toplu kontrol et."""

    def test_all_mock_responses_turkish_only(self) -> None:
        """Tüm mock response'lar Türkçe olmalı — İngilizce/Çince yasak."""
        violations = []

        for scenario in SCENARIOS:
            sid = scenario["id"]

            if "turns" in scenario:
                responses = [t["mock_response"] for t in scenario["turns"]]
            else:
                responses = [scenario["mock_response"]]

            for resp in responses:
                reply = resp.get("assistant_reply", "")
                question = resp.get("question", "")
                text = f"{reply} {question}".strip()

                english = contains_english_words(text)
                if english:
                    violations.append(f"{sid}: İngilizce={english}")

                cjk = contains_cjk_chars(text)
                if cjk:
                    violations.append(f"{sid}: CJK={cjk}")

        assert not violations, (
            f"Dil ihlalleri ({len(violations)}):\n" +
            "\n".join(f"  • {v}" for v in violations)
        )

    def test_all_scenarios_have_required_fields(self) -> None:
        """Her senaryo id, input, mock_response, expected içermeli."""
        for scenario in SCENARIOS:
            sid = scenario.get("id", "???")
            if "turns" in scenario:
                # Multi-turn
                assert "turns" in scenario, f"{sid}: turns eksik"
                for i, turn in enumerate(scenario["turns"]):
                    assert "input" in turn, f"{sid} turn{i}: input eksik"
                    assert "mock_response" in turn, f"{sid} turn{i}: mock_response eksik"
                    assert "expected" in turn, f"{sid} turn{i}: expected eksik"
            else:
                # Single-turn
                assert "input" in scenario, f"{sid}: input eksik"
                assert "mock_response" in scenario, f"{sid}: mock_response eksik"
                assert "expected" in scenario, f"{sid}: expected eksik"

    def test_no_duplicate_scenario_ids(self) -> None:
        """Senaryo ID'leri benzersiz olmalı."""
        ids = [s["id"] for s in SCENARIOS]
        duplicates = [x for x in ids if ids.count(x) > 1]
        assert not duplicates, f"Duplicate ID'ler: {set(duplicates)}"

    def test_minimum_scenario_count(self) -> None:
        """En az 11 senaryo olmalı (issue gereksinimi)."""
        assert len(SCENARIOS) >= 11, (
            f"En az 11 senaryo gerekli, mevcut: {len(SCENARIOS)}"
        )


# ── HELPER UNIT TESTS ────────────────────────────────────────

class TestLanguageHelpers:
    """contains_english_words / contains_cjk_chars fonksiyonları."""

    def test_turkish_text_no_english(self) -> None:
        assert contains_english_words("Merhaba, nasılsın?") == []

    def test_english_detected(self) -> None:
        result = contains_english_words("Hello, this is a test")
        assert "hello" in result or "this" in result

    def test_allowed_english_ignored(self) -> None:
        """gmail, email gibi teknik terimler OK."""
        assert contains_english_words("Gmail hesabına bakıyorum") == []

    def test_no_cjk_in_turkish(self) -> None:
        assert contains_cjk_chars("Takvime etkinlik ekliyorum.") == []

    def test_cjk_detected(self) -> None:
        result = contains_cjk_chars("你好世界")
        assert len(result) > 0

    def test_mixed_text(self) -> None:
        """Karışık metin → hem İngilizce hem Türkçe."""
        text = "Bu very güzel bir the test"
        english = contains_english_words(text)
        assert "very" in english
        assert "the" in english


# ── MOCK LLM TESTS ───────────────────────────────────────────

class TestGoldenMockLLM:
    """GoldenMockLLM davranış testleri."""

    def test_exact_match(self) -> None:
        llm = GoldenMockLLM()
        llm.set_response("merhaba", {"route": "smalltalk"})
        result = llm.route("merhaba")
        assert result["route"] == "smalltalk"

    def test_case_insensitive(self) -> None:
        llm = GoldenMockLLM()
        llm.set_response("merhaba", {"route": "smalltalk"})
        result = llm.route("Merhaba")
        assert result["route"] == "smalltalk"

    def test_fallback_unknown(self) -> None:
        llm = GoldenMockLLM()
        result = llm.route("bilinmeyen komut xyz")
        assert result["route"] == "unknown"

    def test_calls_recorded(self) -> None:
        llm = GoldenMockLLM()
        llm.set_response("test", {"route": "system"})
        llm.route("test")
        llm.route("test")
        assert len(llm.calls) == 2

    def test_response_is_copy(self) -> None:
        """Dönen dict orijinal referansı değiştirmesin."""
        llm = GoldenMockLLM()
        llm.set_response("test", {"route": "system", "confidence": 0.9})
        r1 = llm.route("test")
        r1["route"] = "modified"
        r2 = llm.route("test")
        assert r2["route"] == "system"


# ── YAML INTEGRITY TESTS ─────────────────────────────────────

class TestYAMLIntegrity:
    """YAML dosyasının yapısal bütünlüğü."""

    def test_yaml_loads_without_error(self) -> None:
        """YAML dosyası hatasız yüklenir."""
        scenarios = load_golden_scenarios()
        assert len(scenarios) > 0

    def test_all_routes_valid(self) -> None:
        """Tüm mock route'lar geçerli enum değeri."""
        valid_routes = {"calendar", "gmail", "smalltalk", "system", "unknown"}
        for scenario in SCENARIOS:
            if "turns" in scenario:
                for turn in scenario["turns"]:
                    route = turn["mock_response"]["route"]
                    assert route in valid_routes, f"{scenario['id']}: route={route}"
            else:
                route = scenario["mock_response"]["route"]
                assert route in valid_routes, f"{scenario['id']}: route={route}"

    def test_all_confidence_in_range(self) -> None:
        """Tüm confidence değerleri 0-1 aralığında."""
        for scenario in SCENARIOS:
            if "turns" in scenario:
                responses = [t["mock_response"] for t in scenario["turns"]]
            else:
                responses = [scenario["mock_response"]]

            for resp in responses:
                conf = resp.get("confidence", 0.0)
                assert 0.0 <= conf <= 1.0, (
                    f"{scenario['id']}: confidence={conf}"
                )

    def test_expected_routes_match_mock(self) -> None:
        """Expected route ile mock_response route tutarlı olmalı."""
        for scenario in SCENARIOS:
            sid = scenario["id"]
            if "turns" in scenario:
                for i, turn in enumerate(scenario["turns"]):
                    if "route" in turn["expected"]:
                        assert turn["expected"]["route"] == turn["mock_response"]["route"], (
                            f"{sid}_turn{i}: expected route mismatch"
                        )
            else:
                if "route" in scenario["expected"]:
                    assert scenario["expected"]["route"] == scenario["mock_response"]["route"], (
                        f"{sid}: expected route mismatch"
                    )
