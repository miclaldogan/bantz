"""Tests for Issue #647: Tiering is ON by default.

Before this fix, BANTZ_TIER_MODE defaulted to False, which meant the tiering
engine was completely disabled unless the user explicitly set the env var.
This caused all requests — including complex writing tasks — to be handled
by the fast 3B model, degrading output quality.

After the fix:
- Tiering is ON by default (no env var needed).
- Users can explicitly disable it with BANTZ_TIER_MODE=0.
- Legacy alias BANTZ_TIERED_MODE=0 also works.
"""

from __future__ import annotations

import pytest

from bantz.llm.tiered import decide_tier, _env_flag


# ─────────────────────────────────────────────────────────────────────────────
# _env_flag default=True behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvFlagDefaults:
    """Verify _env_flag honours the new default=True for tier mode."""

    def test_env_flag_default_true_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("BANTZ_TIER_MODE", raising=False)
        assert _env_flag("BANTZ_TIER_MODE", default=True) is True

    def test_env_flag_explicit_zero_disables(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_MODE", "0")
        assert _env_flag("BANTZ_TIER_MODE", default=True) is False

    def test_env_flag_explicit_false_disables(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_MODE", "false")
        assert _env_flag("BANTZ_TIER_MODE", default=True) is False

    def test_env_flag_explicit_one_enables(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_MODE", "1")
        assert _env_flag("BANTZ_TIER_MODE", default=True) is True

    def test_env_flag_explicit_true_enables(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_MODE", "true")
        assert _env_flag("BANTZ_TIER_MODE", default=True) is True


# ─────────────────────────────────────────────────────────────────────────────
# decide_tier() with default env (tiering ON)
# ─────────────────────────────────────────────────────────────────────────────

class TestTieringOnByDefault:
    """When no BANTZ_TIER_MODE env var is set, tiering should be active."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch):
        """Remove all tier-related env vars to test pure defaults."""
        for var in (
            "BANTZ_TIER_MODE",
            "BANTZ_TIERED_MODE",
            "BANTZ_LLM_TIER",
            "BANTZ_TIER_FORCE",
            "BANTZ_TIER_DEBUG",
            "BANTZ_TIERED_DEBUG",
            "BANTZ_TIER_METRICS",
            "BANTZ_TIERED_METRICS",
            "BANTZ_LLM_METRICS",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_default_does_not_return_tiering_disabled(self):
        """The core regression: decide_tier must NOT return 'tiering_disabled'."""
        decision = decide_tier("bugün toplantım var mı?", route="calendar")
        assert decision.reason != "tiering_disabled", (
            "Tiering should be ON by default (Issue #647)"
        )

    def test_simple_query_routes_to_fast(self):
        """Simple calendar query should still go to fast tier via scoring."""
        decision = decide_tier(
            "saat kaç?",
            route="system",
            tool_names=["system.time"],
            requires_confirmation=False,
        )
        assert decision.use_quality is False
        assert decision.reason != "tiering_disabled"

    def test_complex_writing_routes_to_quality(self):
        """Complex writing request should escalate to quality tier."""
        decision = decide_tier(
            "Ahmet hocaya resmi bir email taslağı yaz, nazik ve kibar olsun",
            route="gmail",
            tool_names=[],
            requires_confirmation=False,
        )
        assert decision.use_quality is True
        assert decision.reason != "tiering_disabled"


# ─────────────────────────────────────────────────────────────────────────────
# decide_tier() with explicit disable
# ─────────────────────────────────────────────────────────────────────────────

class TestTieringExplicitDisable:
    """When user explicitly sets BANTZ_TIER_MODE=0, tiering should be off."""

    def test_explicit_disable_via_tier_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_MODE", "0")
        monkeypatch.setenv("BANTZ_TIERED_MODE", "0")
        monkeypatch.delenv("BANTZ_LLM_TIER", raising=False)
        monkeypatch.delenv("BANTZ_TIER_FORCE", raising=False)

        decision = decide_tier(
            "Ahmet hocaya detaylı bir roadmap hazırla, adım adım planla",
            route="gmail",
        )
        assert decision.reason == "tiering_disabled"
        assert decision.use_quality is False

    def test_explicit_disable_via_legacy_alias(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_MODE", "0")
        monkeypatch.setenv("BANTZ_TIERED_MODE", "0")
        monkeypatch.delenv("BANTZ_LLM_TIER", raising=False)
        monkeypatch.delenv("BANTZ_TIER_FORCE", raising=False)

        decision = decide_tier("detaylı analiz yaz", route="unknown")
        assert decision.reason == "tiering_disabled"


# ─────────────────────────────────────────────────────────────────────────────
# Force tier still works
# ─────────────────────────────────────────────────────────────────────────────

class TestForceTier:
    """BANTZ_TIER_FORCE / BANTZ_LLM_TIER bypass should still work."""

    def test_force_fast(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_FORCE", "fast")
        decision = decide_tier("detaylı roadmap yaz", route="unknown")
        assert decision.use_quality is False
        assert decision.reason == "forced_fast"

    def test_force_quality(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BANTZ_TIER_FORCE", "quality")
        decision = decide_tier("saat kaç", route="system")
        assert decision.use_quality is True
        assert decision.reason == "forced_quality"

    def test_force_via_legacy_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("BANTZ_TIER_FORCE", raising=False)
        monkeypatch.setenv("BANTZ_LLM_TIER", "fast")
        decision = decide_tier("detaylı analiz", route="unknown")
        assert decision.use_quality is False
        assert decision.reason == "forced_fast"
