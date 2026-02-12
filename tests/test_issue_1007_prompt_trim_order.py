"""Tests for Issue #1007: SESSION_CONTEXT must be dropped last during trim.

Verifies that _trim_to_budget drops RECENT_TURNS and DIALOG_SUMMARY
before SESSION_CONTEXT so the model always knows the current date/time.
"""

import pytest

from bantz.brain.prompt_engineering import estimate_tokens


class FakeBuilder:
    """Minimal shim to test trim ordering without full PromptBuilder deps."""

    def __init__(self, token_budget: int):
        self._token_budget = token_budget

    def _assemble(self, *, system, template, blocks, user_input):
        lines = [system.strip(), "", template.strip(), ""]
        for name, content in blocks:
            c = str(content or "").strip()
            if not c:
                continue
            lines.append(f"{name}:")
            lines.append(c)
            lines.append("")
        lines.append(f"USER: {user_input}")
        lines.append("ASSISTANT:")
        return "\n".join(lines).strip()

    # Borrow the real _trim_to_budget logic
    from bantz.brain.prompt_engineering import PromptBuilder
    _trim_to_budget = PromptBuilder._trim_to_budget


SYSTEM = "Sen bir yardımcısın."
TEMPLATE = "Basit bir cevap ver."
USER_INPUT = "yarın saat 3'te toplantı koy"


def _blocks(session_ctx="current_datetime: 2025-07-21T10:00:00+03:00",
            recent="USER: merhaba\nASSISTANT: merhaba",
            summary="Kullanıcı toplantı istedi.",
            planner="{}",
            tools=""):
    blocks = []
    if session_ctx:
        blocks.append(("SESSION_CONTEXT", session_ctx))
    if summary:
        blocks.append(("DIALOG_SUMMARY", summary))
    if planner:
        blocks.append(("PLANNER_DECISION", planner))
    if tools:
        blocks.append(("TOOL_RESULTS", tools))
    if recent:
        blocks.append(("RECENT_TURNS", recent))
    return blocks


class TestTrimDropOrder:
    """Verify SESSION_CONTEXT survives longer than RECENT_TURNS and DIALOG_SUMMARY."""

    def test_session_context_survives_when_turns_dropped(self):
        """With a tight budget, RECENT_TURNS should be dropped before SESSION_CONTEXT."""
        blocks = _blocks(
            recent="USER: çok uzun bir mesaj " * 30,
            summary="Özet " * 20,
        )
        # Set budget so it fits IF we drop recent turns but not session context
        full = FakeBuilder(9999)._assemble(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        full_tokens = estimate_tokens(full)

        # Budget tight enough to force drops but enough to keep session_context
        budget = full_tokens - 50
        builder = FakeBuilder(token_budget=budget)
        result = builder._trim_to_budget(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        assert "current_datetime" in result, (
            "SESSION_CONTEXT (current_datetime) should survive trimming"
        )

    def test_recent_turns_dropped_before_session_context(self):
        """When budget is very tight, RECENT_TURNS disappears first."""
        blocks = _blocks()
        # Make budget very tight — force multiple drops
        builder = FakeBuilder(token_budget=40)
        result = builder._trim_to_budget(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        # SESSION_CONTEXT should be the last block standing
        has_session = "current_datetime" in result
        has_recent = "merhaba" in result
        # If both are gone, that's fine (budget too small), but
        # if only one remains, it should be SESSION_CONTEXT
        if has_session or has_recent:
            assert has_session or not has_recent, (
                "RECENT_TURNS should be dropped before SESSION_CONTEXT"
            )

    def test_within_budget_no_drops(self):
        """When budget is generous, nothing is dropped."""
        blocks = _blocks()
        builder = FakeBuilder(token_budget=9999)
        result = builder._trim_to_budget(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        assert "current_datetime" in result
        assert "merhaba" in result
        assert "toplantı" in result

    def test_dialog_summary_dropped_before_session_context(self):
        """DIALOG_SUMMARY should be dropped before SESSION_CONTEXT."""
        blocks = _blocks(
            summary="Uzun bir özet " * 40,  # Big summary to force drop
        )
        full = FakeBuilder(9999)._assemble(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        # Budget that forces summary drop but keeps session context
        budget = estimate_tokens(full) - 100
        builder = FakeBuilder(token_budget=budget)
        result = builder._trim_to_budget(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        assert "current_datetime" in result

    def test_extreme_trim_still_has_user_input(self):
        """Even with extreme trimming, user input should survive (possibly truncated)."""
        blocks = _blocks()
        builder = FakeBuilder(token_budget=10)
        result = builder._trim_to_budget(
            system=SYSTEM, template=TEMPLATE, blocks=blocks, user_input=USER_INPUT,
        )
        assert "USER:" in result
