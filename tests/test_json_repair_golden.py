"""Golden tests for JSON repair pipeline (Issue #574).

Tests broken LLM responses against the full repair stack:
- brain/json_protocol.py  → extract_first_json_object
- llm/json_repair.py      → repair_json_structure, validate_and_repair_json
- brain/json_repair.py    → build_repair_prompt, repair_to_json_object

Covers: markdown fencing, trailing text, truncated output, wrong types,
wrong enums, empty output, prose-only, double JSON, Turkish unicode,
and multi-turn / error-fallback golden traces.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bantz.brain.json_protocol import (
    JsonParseError,
    extract_first_json_object,
)
from bantz.brain.json_repair import (
    RepairResult,
    build_repair_prompt,
    repair_to_json_object,
)
from bantz.llm.json_repair import (
    RepairStats,
    extract_json_from_text,
    repair_json_structure,
    repair_route_enum,
    repair_intent_enum,
    repair_tool_plan,
    reset_repair_stats,
    get_repair_stats,
    validate_and_repair_json,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "malformed_responses"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeRepairLLM:
    """Repair-LLM mock that returns canned JSON on complete_text."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[str] = []

    def complete_text(self, *, prompt: str) -> str:
        self.calls.append(prompt)
        if self._responses:
            return self._responses.pop(0)
        return '{"type": "FAIL", "message": "mock exhausted"}'


# ---------------------------------------------------------------------------
# 1. extract_first_json_object — happy paths with noise
# ---------------------------------------------------------------------------


class TestExtractFirstJsonObject:
    """Cover the 13 malformed fixtures against the balanced-braces scanner."""

    def test_markdown_fenced(self):
        raw = _load("markdown_fenced.txt")
        obj = extract_first_json_object(raw)
        assert obj["route"] == "calendar"
        assert obj["confidence"] == 0.9

    def test_markdown_fenced_with_prose(self):
        raw = _load("markdown_fenced_with_prose.txt")
        obj = extract_first_json_object(raw)
        assert obj["route"] == "calendar"
        assert obj["calendar_intent"] == "query"

    def test_trailing_turkish_text(self):
        raw = _load("trailing_turkish_text.txt")
        obj = extract_first_json_object(raw)
        assert obj["route"] == "calendar"
        assert "Umarım" not in json.dumps(obj)

    def test_trailing_comma_still_has_valid_json(self):
        """Trailing comma inside {} makes json.loads fail, but the
        balanced-braces scanner will still find the candidate.
        extract_first_json_object raises JsonParseError(json_decode_error)."""
        raw = _load("trailing_comma.txt")
        with pytest.raises(JsonParseError) as exc_info:
            extract_first_json_object(raw)
        assert exc_info.value.reason == "json_decode_error"

    def test_truncated_mid_key(self):
        raw = _load("truncated_mid_key.txt")
        with pytest.raises(JsonParseError) as exc_info:
            extract_first_json_object(raw)
        assert exc_info.value.reason == "unbalanced_json"

    def test_truncated_mid_value(self):
        raw = _load("truncated_mid_value.txt")
        with pytest.raises(JsonParseError) as exc_info:
            extract_first_json_object(raw)
        assert exc_info.value.reason == "unbalanced_json"

    def test_empty_output(self):
        with pytest.raises(JsonParseError) as exc_info:
            extract_first_json_object("")
        assert exc_info.value.reason == "empty_output"

    def test_prose_only(self):
        raw = _load("prose_only.txt")
        with pytest.raises(JsonParseError) as exc_info:
            extract_first_json_object(raw)
        assert exc_info.value.reason == "no_json_object"

    def test_double_json_takes_first(self):
        raw = _load("double_json.txt")
        obj = extract_first_json_object(raw)
        assert obj["route"] == "calendar"

    def test_nested_json_in_markdown(self):
        raw = _load("nested_json_in_markdown.txt")
        obj = extract_first_json_object(raw)
        assert obj["route"] == "calendar"
        assert "participants" in obj["slots"]

    def test_turkish_unicode(self):
        raw = _load("turkish_unicode.txt")
        obj = extract_first_json_object(raw)
        assert "Şükrü" in obj["slots"]["title"]
        assert obj["assistant_reply"].startswith("İlçe")

    def test_wrong_type_confidence_string_parses(self):
        """JSON itself is valid even if confidence is 'yüksek' (string)."""
        raw = _load("wrong_type_confidence_string.txt")
        obj = extract_first_json_object(raw)
        assert obj["confidence"] == "yüksek"

    def test_wrong_enums_parses(self):
        raw = _load("wrong_enums_and_types.txt")
        obj = extract_first_json_object(raw)
        assert obj["route"] == "create_meeting"


# ---------------------------------------------------------------------------
# 2. extract_json_from_text (regex-based, llm/json_repair)
# ---------------------------------------------------------------------------


class TestExtractJsonFromText:

    def test_markdown_block(self):
        raw = _load("markdown_fenced.txt")
        extracted = extract_json_from_text(raw)
        assert extracted is not None
        obj = json.loads(extracted)
        assert obj["route"] == "calendar"

    def test_prose_with_markdown(self):
        raw = _load("markdown_fenced_with_prose.txt")
        extracted = extract_json_from_text(raw)
        assert extracted is not None
        obj = json.loads(extracted)
        assert obj["route"] == "calendar"

    def test_prose_only_returns_none(self):
        raw = _load("prose_only.txt")
        extracted = extract_json_from_text(raw)
        # The prose has no JSON at all
        assert extracted is None


# ---------------------------------------------------------------------------
# 3. repair_json_structure — wrong types and enums
# ---------------------------------------------------------------------------


class TestRepairJsonStructure:

    def setup_method(self):
        reset_repair_stats()

    def test_wrong_enums_repaired(self):
        raw = _load("wrong_enums_and_types.txt")
        data = json.loads(raw)
        repaired = repair_json_structure(data)
        assert repaired["route"] == "calendar"
        assert repaired["calendar_intent"] == "create"
        assert isinstance(repaired["tool_plan"], list)

    def test_confidence_string_yuksek_defaults(self):
        raw = _load("wrong_type_confidence_string.txt")
        data = json.loads(raw)
        repaired = repair_json_structure(data)
        # "yüksek" can't be float → defaults to 0.5
        assert repaired["confidence"] == 0.5
        assert isinstance(repaired["tool_plan"], list)

    def test_confidence_turkish_comma(self):
        raw = _load("wrong_type_confidence_turkish_comma.txt")
        data = json.loads(raw)
        repaired = repair_json_structure(data)
        # "0,85" can't be float → defaults to 0.5
        assert repaired["confidence"] == 0.5

    def test_tool_plan_string_coerced_to_list(self):
        raw = _load("wrong_enums_and_types.txt")
        data = json.loads(raw)
        assert isinstance(data["tool_plan"], str)
        repaired = repair_json_structure(data)
        assert isinstance(repaired["tool_plan"], list)
        assert repaired["tool_plan"] == ["calendar.create_event"]

    def test_missing_fields_get_defaults(self):
        data = {"assistant_reply": "Merhaba!"}
        repaired = repair_json_structure(data)
        assert repaired["route"] == "unknown"
        assert repaired["calendar_intent"] == "none"
        assert repaired["confidence"] == 0.5

    def test_repair_stats_populated(self):
        raw = _load("wrong_enums_and_types.txt")
        data = json.loads(raw)
        repair_json_structure(data)
        stats = get_repair_stats()
        assert stats.successful_repairs > 0
        summary = stats.summary()
        assert summary["successful_repairs"] > 0


# ---------------------------------------------------------------------------
# 4. validate_and_repair_json — full round-trip
# ---------------------------------------------------------------------------


class TestValidateAndRepairJson:

    def setup_method(self):
        reset_repair_stats()

    def test_clean_json_validates_immediately(self):
        raw = json.dumps({
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "Oluşturuyorum.",
            "slots": {},
        })
        schema, error = validate_and_repair_json(raw)
        assert schema is not None
        assert error is None

    def test_wrong_enums_repaired_and_validated(self):
        raw = _load("wrong_enums_and_types.txt")
        schema, error = validate_and_repair_json(raw)
        assert schema is not None
        assert error is None
        assert schema.route.value == "calendar"
        assert schema.calendar_intent.value == "create"

    def test_unparseable_json_returns_error(self):
        raw = _load("truncated_mid_key.txt")
        schema, error = validate_and_repair_json(raw)
        assert schema is None
        assert error is not None
        assert "parse error" in error.lower()


# ---------------------------------------------------------------------------
# 5. repair_to_json_object — LLM-based repair (brain/json_repair)
# ---------------------------------------------------------------------------


class TestRepairToJsonObject:

    def test_successful_repair_after_one_attempt(self):
        llm = FakeRepairLLM([
            '{"type": "SAY", "message": "Merhaba efendim!"}'
        ])
        result = repair_to_json_object(
            llm=llm,
            raw_text="bu geçersiz çıktı",
            max_attempts=2,
        )
        assert result.ok is True
        assert result.value["type"] == "SAY"
        assert result.attempts == 1

    def test_all_attempts_fail(self):
        llm = FakeRepairLLM([
            "hala bozuk",
            "hala bozuk",
        ])
        result = repair_to_json_object(
            llm=llm,
            raw_text="geçersiz çıktı",
            max_attempts=2,
        )
        assert result.ok is False
        assert result.attempts == 2

    def test_repair_prompt_includes_raw_text(self):
        prompt = build_repair_prompt(
            raw_text='{"route": "calendar"',
            error_summary="unbalanced_json",
            validation_error=None,
        )
        assert "calendar" in prompt
        assert "unbalanced" in prompt.lower() or "hata" in prompt.lower()


# ---------------------------------------------------------------------------
# 6. repair_route_enum / repair_intent_enum — edge cases
# ---------------------------------------------------------------------------


class TestEnumRepair:

    def test_route_create_meeting(self):
        assert repair_route_enum("create_meeting") == "calendar"

    def test_route_chat(self):
        assert repair_route_enum("chat") == "smalltalk"

    def test_route_already_valid(self):
        assert repair_route_enum("calendar") == "calendar"

    def test_route_unknown_defaults(self):
        assert repair_route_enum("gibberish_xyz") == "unknown"

    def test_intent_schedule(self):
        assert repair_intent_enum("schedule") == "create"

    def test_intent_find(self):
        assert repair_intent_enum("find") == "query"

    def test_intent_already_valid(self):
        assert repair_intent_enum("create") == "create"


# ---------------------------------------------------------------------------
# 7. repair_tool_plan — type coercion edge cases
# ---------------------------------------------------------------------------


class TestRepairToolPlan:

    def test_none_returns_empty(self):
        assert repair_tool_plan(None) == []

    def test_string_becomes_list(self):
        result = repair_tool_plan("calendar.create_event")
        assert result == ["calendar.create_event"]

    def test_json_array_string(self):
        result = repair_tool_plan('["calendar.create_event", "gmail.send"]')
        assert result == ["calendar.create_event", "gmail.send"]

    def test_comma_separated(self):
        result = repair_tool_plan("calendar.create, gmail.send")
        assert result == ["calendar.create", "gmail.send"]

    def test_already_list(self):
        result = repair_tool_plan(["calendar.create_event"])
        assert result == ["calendar.create_event"]

    def test_empty_string(self):
        assert repair_tool_plan("") == []


# ---------------------------------------------------------------------------
# 8. RepairStats — metrics tracking
# ---------------------------------------------------------------------------


class TestRepairStats:

    def test_fresh_stats(self):
        stats = RepairStats()
        assert stats.repair_rate == 0.0
        assert stats.total_attempts == 0

    def test_after_mixed_operations(self):
        stats = RepairStats()
        for _ in range(8):
            stats.record_attempt()
            stats.record_success("route_enum")
        for _ in range(2):
            stats.record_attempt()
            stats.record_failure()
        assert stats.total_attempts == 10
        assert stats.successful_repairs == 8
        assert stats.failed_repairs == 2
        assert stats.repair_rate == 80.0
        summary = stats.summary()
        assert summary["repair_types"]["route_enum"] == 8


# ---------------------------------------------------------------------------
# 9. Golden traces — multi-turn and error/fallback
# ---------------------------------------------------------------------------


class TestGoldenTraceMultiTurn:
    """Simulates a multi-turn calendar conversation where the first
    response has wrong enums and the second has markdown fencing."""

    TURN_1_RAW = (
        '{"route": "create_meeting", "calendar_intent": "schedule", '
        '"confidence": 0.7, "tool_plan": "calendar.create_event", '
        '"assistant_reply": "Yarın toplantı oluşturuyorum.", '
        '"slots": {"date": "yarın"}, '
        '"ask_user": true, "question": "Saat kaçta?"}'
    )

    TURN_2_RAW = (
        'Tamam efendim:\n```json\n'
        '{"route": "calendar", "calendar_intent": "create", '
        '"confidence": 0.95, "tool_plan": ["calendar.create_event"], '
        '"assistant_reply": "Toplantı saat 17:00 için ayarlandı.", '
        '"slots": {"date": "yarın", "time": "17:00"}}\n```'
    )

    def test_turn_1_repair_and_validate(self):
        reset_repair_stats()
        schema, error = validate_and_repair_json(self.TURN_1_RAW)
        assert schema is not None
        assert error is None
        assert schema.route.value == "calendar"
        assert schema.calendar_intent.value == "create"
        assert isinstance(schema.tool_plan, list)
        assert schema.ask_user is True
        assert schema.question == "Saat kaçta?"

    def test_turn_2_extract_and_validate(self):
        obj = extract_first_json_object(self.TURN_2_RAW)
        assert obj["route"] == "calendar"
        assert obj["slots"]["time"] == "17:00"
        assert obj["confidence"] == 0.95


class TestGoldenTraceRepairFallback:
    """Simulates a scenario where first LLM output is truncated,
    LLM-based repair produces valid JSON."""

    def test_truncated_then_repaired(self):
        truncated = '{"route": "calendar", "calendar_in'
        # LLM repair mock returns valid action JSON
        repaired_json = (
            '{"type": "CALL_TOOL", "tool": "calendar.create_event", '
            '"params": {"title": "Toplantı", "date": "yarın"}}'
        )
        llm = FakeRepairLLM([repaired_json])
        result = repair_to_json_object(llm=llm, raw_text=truncated, max_attempts=2)
        assert result.ok is True
        assert result.value["type"] == "CALL_TOOL"
        assert result.attempts == 1

    def test_all_repair_attempts_fail_gracefully(self):
        truncated = '{"route": "calendar", "calendar_in'
        llm = FakeRepairLLM([
            "yine bozuk çıktı",
            "son deneme de bozuk",
        ])
        result = repair_to_json_object(llm=llm, raw_text=truncated, max_attempts=2)
        assert result.ok is False
        assert result.attempts == 2
        assert result.error is not None


# ---------------------------------------------------------------------------
# 10. Aggregate: all extractable fixtures pass repair pipeline
# ---------------------------------------------------------------------------


EXTRACTABLE_FIXTURES = [
    "markdown_fenced.txt",
    "markdown_fenced_with_prose.txt",
    "trailing_turkish_text.txt",
    "double_json.txt",
    "nested_json_in_markdown.txt",
    "turkish_unicode.txt",
    "wrong_type_confidence_string.txt",
    "wrong_enums_and_types.txt",
]


@pytest.mark.parametrize("fixture_name", EXTRACTABLE_FIXTURES)
def test_extractable_fixture_repair_roundtrip(fixture_name: str):
    """Every extractable fixture should survive extract → repair_json_structure."""
    raw = _load(fixture_name)
    obj = extract_first_json_object(raw)
    repaired = repair_json_structure(obj)
    # After repair, route should be a valid enum value
    assert repaired["route"] in {"calendar", "gmail", "smalltalk", "system", "unknown"}
    # Confidence should be float in [0, 1]
    assert isinstance(repaired["confidence"], float)
    assert 0.0 <= repaired["confidence"] <= 1.0
    # tool_plan should be list
    assert isinstance(repaired["tool_plan"], list)


UNEXTRACTABLE_FIXTURES = [
    ("truncated_mid_key.txt", "unbalanced_json"),
    ("truncated_mid_value.txt", "unbalanced_json"),
    ("prose_only.txt", "no_json_object"),
]


@pytest.mark.parametrize("fixture_name,expected_reason", UNEXTRACTABLE_FIXTURES)
def test_unextractable_fixture_correct_error(fixture_name: str, expected_reason: str):
    """Unextractable fixtures should raise the expected JsonParseError."""
    raw = _load(fixture_name)
    with pytest.raises(JsonParseError) as exc_info:
        extract_first_json_object(raw)
    assert exc_info.value.reason == expected_reason
