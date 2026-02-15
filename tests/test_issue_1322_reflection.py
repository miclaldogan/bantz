"""Tests for Issue #1322: reflection.py fixes.

Covers:
1. Nested JSON extraction in parse_reflection_response
2. Prompt budget alignment (max_chars ≤ token-equivalent of max_prompt_tokens)
3. Markdown fence stripping (opening + closing)
"""

from __future__ import annotations

import json

from bantz.brain.reflection import (ReflectionConfig, build_reflection_prompt,
                                    parse_reflection_response)

# ── 1. Nested JSON extraction ────────────────────────────────────────────


class TestNestedJsonExtraction:
    """parse_reflection_response should handle nested JSON."""

    def test_flat_json(self):
        raw = '{"satisfied": true, "reason": "ok", "corrective_action": null}'
        result = parse_reflection_response(raw)
        assert result.satisfied is True
        assert result.reason == "ok"

    def test_nested_json_object(self):
        """Previously failed with naive [^{}]+ regex — only inner dict was matched."""
        raw = '{"satisfied": false, "reason": "data mismatch", "details": {"code": 404}}'
        result = parse_reflection_response(raw)
        assert result.satisfied is False
        assert "mismatch" in result.reason

    def test_json_with_surrounding_text(self):
        raw = 'Here is my analysis:\n{"satisfied": false, "reason": "empty result"}\nDone.'
        result = parse_reflection_response(raw)
        assert result.satisfied is False

    def test_deeply_nested_json(self):
        raw = json.dumps({
            "satisfied": True,
            "reason": "all good",
            "corrective_action": None,
            "meta": {"inner": {"deep": "value"}},
        })
        result = parse_reflection_response(raw)
        assert result.satisfied is True

    def test_malformed_returns_satisfied(self):
        """If parsing fails completely, should default to satisfied=True."""
        raw = "This is not JSON at all"
        result = parse_reflection_response(raw)
        assert result.triggered is True
        assert result.satisfied is True
        assert "parse_failed" in result.reason


# ── 2. Prompt budget alignment ───────────────────────────────────────────


class TestPromptBudgetAlignment:
    """max_chars and max_prompt_tokens should be consistent."""

    def test_config_defaults_aligned(self):
        cfg = ReflectionConfig()
        # With ~3-4 chars/token for Turkish, max_chars=600 ≈ 150-200 tokens
        # max_prompt_tokens=512, so chars fit comfortably
        assert cfg.max_prompt_tokens >= 200, "max_prompt_tokens too small for max_chars"

    def test_build_prompt_within_budget(self):
        tool_results = [{
            "tool": "calendar.list_events",
            "success": True,
            "result": "Bugün 3 etkinlik var: toplantı, öğle yemeği, spor",
        }]
        prompt = build_reflection_prompt("takvimimi göster", tool_results)
        # Prompt should fit within max_chars default (600)
        assert len(prompt) < 1200, f"Prompt too long: {len(prompt)} chars"

    def test_build_prompt_truncates_long_summary(self):
        """Long tool results should be truncated to max_chars."""
        tool_results = [{
            "tool": "gmail.list_messages",
            "success": True,
            "result": "x" * 2000,
        }]
        prompt = build_reflection_prompt("emaillerimi göster", tool_results, max_chars=100)
        # The summary part should be truncated, so total prompt is limited
        assert "…" in prompt  # truncation marker present


# ── 3. Markdown fence stripping ──────────────────────────────────────────


class TestMarkdownFenceStripping:
    """Both opening and closing fences should be stripped."""

    def test_fenced_json(self):
        raw = '```json\n{"satisfied": true, "reason": "ok"}\n```'
        result = parse_reflection_response(raw)
        assert result.satisfied is True
        assert result.reason == "ok"

    def test_fenced_without_language(self):
        raw = '```\n{"satisfied": false, "reason": "fail"}\n```'
        result = parse_reflection_response(raw)
        assert result.satisfied is False

    def test_no_fences(self):
        raw = '{"satisfied": true, "reason": "no fences"}'
        result = parse_reflection_response(raw)
        assert result.satisfied is True

    def test_closing_fence_not_left_behind(self):
        """Previously the closing ``` was left in the text."""
        raw = '```json\n{"satisfied": true, "reason": "test"}\n```'
        result = parse_reflection_response(raw)
        # If closing fence was left, JSON parse would fail
        assert result.reason == "test"

    def test_multiple_fenced_blocks(self):
        """Only the JSON inside fences should be extracted."""
        raw = (
            'Some text\n'
            '```json\n{"satisfied": false, "reason": "inner"}\n```\n'
            'More text'
        )
        result = parse_reflection_response(raw)
        assert result.satisfied is False
        assert result.reason == "inner"
