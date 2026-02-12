"""Tests for issue #1022 — prompt engineering hardcoded limits.

All formerly-hardcoded char/token limits are now in ``PromptLimits``
and fully configurable via the ``limits`` constructor parameter.
"""

import inspect

import pytest
from bantz.brain.prompt_engineering import PromptBuilder, PromptLimits


# ---------------------------------------------------------------------------
# PromptLimits defaults
# ---------------------------------------------------------------------------

class TestPromptLimitsDefaults:
    """PromptLimits dataclass should have the correct legacy defaults."""

    def test_defaults(self):
        lim = PromptLimits()
        assert lim.session_context == 1200
        assert lim.dialog_summary == 6000
        assert lim.planner_decision == 4000
        assert lim.tool_results == 12000
        assert lim.tool_results_trim == 700
        assert lim.dialog_summary_trim == 450
        assert lim.planner_decision_trim == 600
        assert lim.user_input_trim == 500
        assert lim.token_budget == 3500

    def test_frozen(self):
        lim = PromptLimits()
        with pytest.raises(AttributeError):
            lim.token_budget = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PromptBuilder respects custom limits
# ---------------------------------------------------------------------------

class TestPromptBuilderLimits:
    """PromptBuilder should use the PromptLimits passed at construction."""

    def test_default_limits_used(self):
        pb = PromptBuilder()
        assert pb._limits == PromptLimits()
        assert pb._token_budget == 3500

    def test_custom_limits(self):
        custom = PromptLimits(token_budget=5000, tool_results=8000)
        pb = PromptBuilder(limits=custom)
        assert pb._token_budget == 5000
        assert pb._limits.tool_results == 8000

    def test_legacy_token_budget_overrides_limits(self):
        """Explicit token_budget= kwarg overrides PromptLimits.token_budget."""
        pb = PromptBuilder(token_budget=2000)
        assert pb._token_budget == 2000

    def test_limits_attr_exists(self):
        pb = PromptBuilder()
        assert hasattr(pb, "_limits")
        assert isinstance(pb._limits, PromptLimits)


# ---------------------------------------------------------------------------
# Assembly uses configurable limits (not hardcoded)
# ---------------------------------------------------------------------------

class TestAssemblyUsesLimits:
    """build_finalizer_prompt should truncate using _limits values."""

    def _build(self, limits: PromptLimits, **kwargs):
        pb = PromptBuilder(limits=limits)
        defaults = dict(
            route="chat",
            user_input="test",
            planner_decision={"route": "chat"},
        )
        defaults.update(kwargs)
        return pb.build_finalizer_prompt(**defaults)

    def test_session_context_truncated(self):
        """SESSION_CONTEXT should be truncated to limits.session_context."""
        short_limit = PromptLimits(session_context=50, token_budget=100_000)
        result = self._build(short_limit, session_context={"data": "x" * 200})
        # The session_context section should be truncated — the full 200-x
        # string must NOT appear verbatim in the assembled prompt.
        assert "x" * 200 not in result.prompt

    def test_tool_results_truncated(self):
        """TOOL_RESULTS should respect limits.tool_results."""
        short_limit = PromptLimits(tool_results=100, token_budget=100_000)
        result = self._build(short_limit, tool_results=[{"r": "A" * 500}])
        # tool result section should be truncated
        assert "A" * 200 not in result.prompt

    def test_dialog_summary_truncated(self):
        """DIALOG_SUMMARY should respect limits.dialog_summary."""
        short_limit = PromptLimits(dialog_summary=80, token_budget=100_000)
        result = self._build(short_limit, dialog_summary="B" * 300)
        assert "B" * 200 not in result.prompt


# ---------------------------------------------------------------------------
# Source code — no remaining hardcoded magic numbers
# ---------------------------------------------------------------------------

class TestNoHardcodedLimits:
    """Source should reference self._limits.* instead of raw integers."""

    def test_build_finalizer_no_hardcoded_max_chars(self):
        """build_finalizer_prompt should not contain hardcoded max_chars ints."""
        source = inspect.getsource(PromptBuilder.build_finalizer_prompt)
        # These were the old hardcoded values; none should appear as literals
        for val in ["max_chars=1200", "max_chars=6000", "max_chars=4000", "max_chars=12000"]:
            assert val not in source, f"Hardcoded {val} still in build_finalizer_prompt"

    def test_trim_to_budget_no_hardcoded_max_chars(self):
        """_trim_to_budget should not contain hardcoded max_chars ints."""
        source = inspect.getsource(PromptBuilder._trim_to_budget)
        for val in ["max_chars=700", "max_chars=450", "max_chars=600", "max_chars=500"]:
            assert val not in source, f"Hardcoded {val} still in _trim_to_budget"

    def test_init_no_hardcoded_3500(self):
        """__init__ default token_budget should come from PromptLimits."""
        source = inspect.getsource(PromptBuilder.__init__)
        assert "3500" not in source, "Hardcoded 3500 still in __init__"
