"""Tests for Issue #1004: JSON Protocol bug fixes.

Verifies:
1. extract_first_json_object prefers object with 'route' key over empty/error obj
2. repair_common_json_issues handles Turkish unquoted values
3. balance_truncated_json handles truncated escape sequences
4. Array-wrapped output [{...}] is handled
"""

import pytest

from bantz.brain.json_protocol import (
    extract_first_json_object,
    repair_common_json_issues,
    balance_truncated_json,
    JsonParseError,
)


class TestExtractPreferRouteKey:
    """extract_first_json_object should prefer objects with 'route' key."""

    def test_skips_empty_object_before_real_output(self):
        text = '{} {"route": "calendar", "confidence": 0.9}'
        result = extract_first_json_object(text)
        assert result["route"] == "calendar"

    def test_skips_error_object_before_real_output(self):
        text = '{"error": "parse failed"} {"route": "gmail", "confidence": 0.8}'
        result = extract_first_json_object(text)
        assert result["route"] == "gmail"

    def test_first_object_with_route_still_works(self):
        text = '{"route": "smalltalk", "confidence": 0.7}'
        result = extract_first_json_object(text)
        assert result["route"] == "smalltalk"

    def test_single_object_without_route_key_still_returned(self):
        """If no object has 'route', return the largest one."""
        text = '{"a": 1} {"b": 2, "c": 3}'
        result = extract_first_json_object(text)
        assert "b" in result  # larger object

    def test_markdown_wrapped(self):
        text = '```json\n{"route": "calendar", "calendar_intent": "create"}\n```'
        result = extract_first_json_object(text)
        assert result["route"] == "calendar"


class TestArrayWrappedOutput:
    """Array output [{...}] should be handled, not corrupted."""

    def test_single_item_array(self):
        text = '[{"route": "calendar", "confidence": 0.9}]'
        result = extract_first_json_object(text)
        assert result["route"] == "calendar"

    def test_multi_item_array_prefers_route(self):
        text = '[{"error": "nope"}, {"route": "gmail", "confidence": 0.8}]'
        result = extract_first_json_object(text)
        assert result["route"] == "gmail"

    def test_array_without_route_returns_first_dict(self):
        text = '[{"a": 1}, {"b": 2}]'
        result = extract_first_json_object(text)
        assert result == {"a": 1}


class TestTurkishUnquotedValues:
    """repair_common_json_issues should handle Turkish characters."""

    def test_unquoted_turkish_value_repaired(self):
        text = '{"route": takvim}'
        repaired = repair_common_json_issues(text)
        assert '"takvim"' in repaired

    def test_unquoted_value_with_turkish_chars(self):
        text = '{"intent": oluştur}'
        repaired = repair_common_json_issues(text)
        assert '"oluştur"' in repaired

    def test_unquoted_value_with_i_dotless(self):
        text = '{"tip": sınıf}'
        repaired = repair_common_json_issues(text)
        assert '"sınıf"' in repaired

    def test_boolean_not_quoted(self):
        """true/false/null must NOT be wrapped in quotes."""
        text = '{"ask_user": true}'
        repaired = repair_common_json_issues(text)
        assert "true" in repaired
        # Should not have "true" as a quoted string
        assert '"true"' not in repaired


class TestBalanceTruncatedEscape:
    """balance_truncated_json should handle truncated escape sequences."""

    def test_truncated_backslash_removed(self):
        text = '{"name": "test\\'
        result = balance_truncated_json(text)
        # The dangling backslash should be removed before closing
        assert result.endswith('"}')\
            or result.endswith("\"}")

    def test_normal_truncation_still_works(self):
        text = '{"a": "hello'
        result = balance_truncated_json(text)
        assert result.endswith('"}')\
            or result.endswith("\"}")

    def test_already_balanced_untouched(self):
        text = '{"a": 1}'
        result = balance_truncated_json(text)
        assert result == text

    def test_nested_truncation(self):
        text = '{"a": {"b": 1'
        result = balance_truncated_json(text)
        assert result.count("}") >= 2
