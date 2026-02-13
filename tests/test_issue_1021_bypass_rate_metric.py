"""Tests for issue #1021 — PreRouter bypass-rate metric deflation.

Two bugs fixed:
1. ``should_bypass()`` called ``route()`` which double-incremented
   ``_total_queries``.  Now uses ``_track_stats=False``.
2. Destructive matches (correctly detected but never bypassed by design)
   deflated the bypass-rate denominator.  They are now tracked separately
   and excluded from the denominator.
"""

import pytest
from bantz.routing.preroute import PreRouter, PreRouteMatch, PreRouteRule, IntentCategory


# ---------------------------------------------------------------------------
# Helpers — tiny rules for controlled testing
# ---------------------------------------------------------------------------

class _AlwaysMatchRule(PreRouteRule):
    """Test rule that always matches with configurable confidence."""

    def __init__(self, name: str, intent: IntentCategory, confidence: float = 0.95):
        super().__init__(name, intent)
        self._confidence = confidence

    def match(self, text: str) -> PreRouteMatch:
        return PreRouteMatch.create(
            intent=self.intent,
            confidence=self._confidence,
            rule_name=self.name,
        )


class _NeverMatchRule(PreRouteRule):
    """Test rule that never matches."""

    def __init__(self):
        super().__init__("never", IntentCategory.GREETING)

    def match(self, text: str) -> PreRouteMatch:
        return PreRouteMatch.no_match()


# ---------------------------------------------------------------------------
# Bug 1 — should_bypass() must not double-count _total_queries
# ---------------------------------------------------------------------------

class TestShouldBypassDoubleCounting:
    """PreRouter.should_bypass() must not inflate _total_queries."""

    def test_should_bypass_no_stat_increment(self):
        """Calling should_bypass() should NOT increment _total_queries."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("greet", IntentCategory.GREETING)],
        )
        router.should_bypass("hello")
        assert router._total_queries == 0, (
            "should_bypass() must not increment _total_queries"
        )

    def test_route_increments_once(self):
        """route() should increment _total_queries exactly once."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("greet", IntentCategory.GREETING)],
        )
        router.route("hello")
        assert router._total_queries == 1

    def test_route_then_should_bypass_still_one(self):
        """route() + should_bypass() on same text → total_queries == 1."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("greet", IntentCategory.GREETING)],
        )
        router.route("hello")
        router.should_bypass("hello")
        assert router._total_queries == 1


# ---------------------------------------------------------------------------
# Bug 2 — Destructive matches must not deflate bypass_rate
# ---------------------------------------------------------------------------

class TestDestructiveMatchDeflation:
    """Destructive matches should be excluded from bypass rate denominator."""

    def _make_router(self) -> PreRouter:
        """Router with one greeting rule and one destructive rule."""
        return PreRouter(
            rules=[
                _AlwaysMatchRule("greet", IntentCategory.GREETING, confidence=0.95),
                _AlwaysMatchRule("delete", IntentCategory.CALENDAR_DELETE, confidence=0.95),
            ],
            min_confidence=0.8,
        )

    def test_destructive_match_tracked_separately(self):
        """Destructive match should increment _destructive_matches."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("delete", IntentCategory.CALENDAR_DELETE)],
            min_confidence=0.8,
        )
        result = router.route("delete event")
        assert result.matched
        assert router._destructive_matches == 1
        assert router._bypassed_queries == 0

    def test_bypass_rate_excludes_destructive(self):
        """bypass_rate denominator should exclude destructive matches."""
        # Purely destructive queries — rate should be 0.0, not 0/1
        router = PreRouter(
            rules=[_AlwaysMatchRule("delete", IntentCategory.CALENDAR_DELETE)],
            min_confidence=0.8,
        )
        router.route("delete event")
        # effective_total = 1 - 1 = 0 → rate = 0.0
        assert router.get_bypass_rate() == 0.0

    def test_bypass_rate_accuracy_mixed(self):
        """With 1 bypass + 1 destructive match, rate should be 1/1 = 100%."""
        # First: create router with greeting rule only → bypasses
        router = PreRouter(
            rules=[_AlwaysMatchRule("greet", IntentCategory.GREETING)],
            min_confidence=0.8,
        )
        router.route("merhaba")  # total=1, bypassed=1
        assert router._bypassed_queries == 1

        # Now add a destructive rule and query
        router.rules = [_AlwaysMatchRule("delete", IntentCategory.CALENDAR_DELETE)]
        router.route("sil")  # total=2, destructive=1, bypassed=1

        # effective_total = 2 - 1 = 1, bypassed = 1 → rate = 1.0
        assert router.get_bypass_rate() == pytest.approx(1.0)

    def test_stats_include_destructive_count(self):
        """get_stats() should include destructive_matches key."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("delete", IntentCategory.CALENDAR_DELETE)],
            min_confidence=0.8,
        )
        router.route("sil")
        stats = router.get_stats()
        assert "destructive_matches" in stats
        assert stats["destructive_matches"] == 1

    def test_reset_clears_destructive(self):
        """reset_stats() should zero out destructive counter."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("delete", IntentCategory.CALENDAR_DELETE)],
            min_confidence=0.8,
        )
        router.route("sil")
        router.reset_stats()
        assert router._destructive_matches == 0


# ---------------------------------------------------------------------------
# Regression — existing stats still work
# ---------------------------------------------------------------------------

class TestStatsRegression:
    """Ensure existing stat tracking still works correctly."""

    def test_no_match_counts_total_only(self):
        """Unmatched queries count in total, not bypassed."""
        router = PreRouter(rules=[_NeverMatchRule()])
        router.route("gibberish")
        assert router._total_queries == 1
        assert router._bypassed_queries == 0
        assert router._destructive_matches == 0
        assert router.get_bypass_rate() == 0.0

    def test_track_stats_false_skips_all(self):
        """route(_track_stats=False) should not touch any counter."""
        router = PreRouter(
            rules=[_AlwaysMatchRule("greet", IntentCategory.GREETING)],
        )
        router.route("hello", _track_stats=False)
        assert router._total_queries == 0
        assert router._bypassed_queries == 0
        assert router._destructive_matches == 0

    def test_source_has_track_stats_param(self):
        """route() signature should have _track_stats parameter."""
        import inspect
        sig = inspect.signature(PreRouter.route)
        assert "_track_stats" in sig.parameters
