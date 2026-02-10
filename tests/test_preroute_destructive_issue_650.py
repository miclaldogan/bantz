"""Tests for Issue #650: PreRouter destructive calendar ops bypass engelleme.

Bug:
  PreRouter'da CALENDAR_CREATE, CALENDAR_DELETE, CALENDAR_UPDATE intent'leri
  can_bypass_router=True olarak tanımlıydı. Yüksek confidence ile should_bypass()
  True dönüyordu. Orchestrator'da "calendar" handler bloğu yoktu — fall-through
  ile hint'e düşüyordu ama bu "şans eseri" çalışıyordu. Birisi calendar handler
  eklerse safety guard ve confirmation firewall atlanırdı.

Fix:
  1. is_destructive property eklendi: create/delete/update + email_send
  2. can_bypass_router: destructive intent'ler False döndürüyor
  3. should_bypass(): defense-in-depth — is_destructive kontrolü eklendi
  4. orchestrator_loop.py: destructive intent blocked log ve event eklendi
"""

from __future__ import annotations

import pytest

from bantz.routing.preroute import (
    IntentCategory,
    PreRouteMatch,
    PreRouter,
)


# ─────────────────────────────────────────────────────────────────────────────
# is_destructive property
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDestructive:
    """Destructive intents: create, delete, update, email_send."""

    def test_calendar_create_is_destructive(self):
        assert IntentCategory.CALENDAR_CREATE.is_destructive is True

    def test_calendar_delete_is_destructive(self):
        assert IntentCategory.CALENDAR_DELETE.is_destructive is True

    def test_calendar_update_is_destructive(self):
        assert IntentCategory.CALENDAR_UPDATE.is_destructive is True

    def test_email_send_is_destructive(self):
        assert IntentCategory.EMAIL_SEND.is_destructive is True

    def test_calendar_list_not_destructive(self):
        assert IntentCategory.CALENDAR_LIST.is_destructive is False

    def test_greeting_not_destructive(self):
        assert IntentCategory.GREETING.is_destructive is False

    def test_time_query_not_destructive(self):
        assert IntentCategory.TIME_QUERY.is_destructive is False

    def test_screenshot_not_destructive(self):
        assert IntentCategory.SCREENSHOT.is_destructive is False

    def test_unknown_not_destructive(self):
        assert IntentCategory.UNKNOWN.is_destructive is False

    def test_smalltalk_not_destructive(self):
        assert IntentCategory.SMALLTALK.is_destructive is False


# ─────────────────────────────────────────────────────────────────────────────
# can_bypass_router property
# ─────────────────────────────────────────────────────────────────────────────

class TestCanBypassRouter:
    """Destructive intents CANNOT bypass router."""

    def test_calendar_create_cannot_bypass(self):
        assert IntentCategory.CALENDAR_CREATE.can_bypass_router is False

    def test_calendar_delete_cannot_bypass(self):
        assert IntentCategory.CALENDAR_DELETE.can_bypass_router is False

    def test_calendar_update_cannot_bypass(self):
        assert IntentCategory.CALENDAR_UPDATE.can_bypass_router is False

    def test_email_send_cannot_bypass(self):
        assert IntentCategory.EMAIL_SEND.can_bypass_router is False

    def test_calendar_list_can_bypass(self):
        """Read-only calendar listing is safe to bypass."""
        assert IntentCategory.CALENDAR_LIST.can_bypass_router is True

    def test_greeting_can_bypass(self):
        assert IntentCategory.GREETING.can_bypass_router is True

    def test_farewell_can_bypass(self):
        assert IntentCategory.FAREWELL.can_bypass_router is True

    def test_time_query_can_bypass(self):
        assert IntentCategory.TIME_QUERY.can_bypass_router is True

    def test_screenshot_can_bypass(self):
        assert IntentCategory.SCREENSHOT.can_bypass_router is True


# ─────────────────────────────────────────────────────────────────────────────
# should_bypass — destructive intents never bypass even with high confidence
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldBypassBlocked:
    """Destructive PreRouteMatch should_bypass always returns False."""

    def test_calendar_create_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.CALENDAR_CREATE, 0.99, "calendar_create")
        assert m.should_bypass(min_confidence=0.5) is False

    def test_calendar_delete_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.CALENDAR_DELETE, 0.99, "calendar_delete")
        assert m.should_bypass(min_confidence=0.5) is False

    def test_calendar_update_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.CALENDAR_UPDATE, 0.99, "calendar_update")
        assert m.should_bypass(min_confidence=0.5) is False

    def test_email_send_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.EMAIL_SEND, 0.99, "email_send")
        assert m.should_bypass(min_confidence=0.5) is False

    def test_calendar_create_perfect_confidence(self):
        """Even with confidence=1.0, destructive intents don't bypass."""
        m = PreRouteMatch.create(IntentCategory.CALENDAR_CREATE, 1.0, "calendar_create")
        assert m.should_bypass(min_confidence=0.0) is False

    def test_calendar_delete_with_orchestrator_threshold(self):
        """Exact threshold used in orchestrator (0.9)."""
        m = PreRouteMatch.create(IntentCategory.CALENDAR_DELETE, 0.95, "calendar_delete")
        assert m.should_bypass(min_confidence=0.9) is False


class TestShouldBypassAllowed:
    """Safe (non-destructive) PreRouteMatch should_bypass works normally."""

    def test_greeting_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.GREETING, 0.95, "greeting")
        assert m.should_bypass(min_confidence=0.9) is True

    def test_calendar_list_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.CALENDAR_LIST, 0.95, "calendar_list")
        assert m.should_bypass(min_confidence=0.9) is True

    def test_time_query_high_confidence(self):
        m = PreRouteMatch.create(IntentCategory.TIME_QUERY, 0.95, "time_query")
        assert m.should_bypass(min_confidence=0.9) is True

    def test_greeting_below_threshold(self):
        """Should NOT bypass if confidence is below threshold."""
        m = PreRouteMatch.create(IntentCategory.GREETING, 0.80, "greeting")
        assert m.should_bypass(min_confidence=0.9) is False

    def test_no_match(self):
        m = PreRouteMatch.no_match()
        assert m.should_bypass(min_confidence=0.5) is False


# ─────────────────────────────────────────────────────────────────────────────
# PreRouter E2E: destructive patterns produce hints, not bypasses
# ─────────────────────────────────────────────────────────────────────────────

class TestPreRouterDestructivePatterns:
    """PreRouter correctly matches destructive patterns but won't bypass."""

    @pytest.fixture
    def router(self):
        return PreRouter()

    def test_calendar_create_matches_but_no_bypass(self, router: PreRouter):
        """'yeni etkinlik ekle' → matches calendar_create but should_bypass=False."""
        result = router.route("yeni etkinlik ekle")
        if result.matched and result.intent == IntentCategory.CALENDAR_CREATE:
            assert result.should_bypass(0.9) is False
            assert result.intent.is_destructive is True

    def test_calendar_delete_matches_but_no_bypass(self, router: PreRouter):
        """'etkinlik sil' → matches calendar_delete but should_bypass=False."""
        result = router.route("etkinlik sil")
        if result.matched and result.intent == IntentCategory.CALENDAR_DELETE:
            assert result.should_bypass(0.9) is False
            assert result.intent.is_destructive is True

    def test_calendar_list_matches_and_can_bypass(self, router: PreRouter):
        """'takvimde ne var' → matches calendar_list and CAN bypass."""
        result = router.route("takvimde ne var")
        if result.matched and result.intent == IntentCategory.CALENDAR_LIST:
            assert result.should_bypass(0.9) is True
            assert result.intent.is_destructive is False

    def test_greeting_matches_and_can_bypass(self, router: PreRouter):
        """'merhaba' → greeting, can bypass."""
        result = router.route("merhaba")
        assert result.matched is True
        assert result.should_bypass(0.9) is True


# ─────────────────────────────────────────────────────────────────────────────
# Comprehensive: no destructive intent can bypass
# ─────────────────────────────────────────────────────────────────────────────

DESTRUCTIVE_INTENTS = [
    IntentCategory.CALENDAR_CREATE,
    IntentCategory.CALENDAR_DELETE,
    IntentCategory.CALENDAR_UPDATE,
    IntentCategory.EMAIL_SEND,
]

SAFE_BYPASS_INTENTS = [
    IntentCategory.GREETING,
    IntentCategory.FAREWELL,
    IntentCategory.THANKS,
    IntentCategory.AFFIRMATIVE,
    IntentCategory.NEGATIVE,
    IntentCategory.SMALLTALK,
    IntentCategory.TIME_QUERY,
    IntentCategory.DATE_QUERY,
    IntentCategory.CALENDAR_LIST,
    IntentCategory.VOLUME_CONTROL,
    IntentCategory.BRIGHTNESS,
    IntentCategory.APP_LAUNCH,
    IntentCategory.SCREENSHOT,
]


@pytest.mark.parametrize("intent", DESTRUCTIVE_INTENTS)
def test_destructive_intent_never_bypasses(intent: IntentCategory):
    """No destructive intent can bypass, regardless of confidence."""
    m = PreRouteMatch.create(intent, 1.0, f"test_{intent.value}")
    assert m.should_bypass(min_confidence=0.0) is False
    assert intent.can_bypass_router is False
    assert intent.is_destructive is True


@pytest.mark.parametrize("intent", SAFE_BYPASS_INTENTS)
def test_safe_intent_can_bypass(intent: IntentCategory):
    """Safe intents can bypass when confidence is sufficient."""
    m = PreRouteMatch.create(intent, 0.99, f"test_{intent.value}")
    assert m.should_bypass(min_confidence=0.9) is True
    assert intent.can_bypass_router is True
    assert intent.is_destructive is False


# ─────────────────────────────────────────────────────────────────────────────
# Defense-in-depth: even if can_bypass_router were True, is_destructive blocks
# ─────────────────────────────────────────────────────────────────────────────

class TestDefenseInDepth:
    """should_bypass checks is_destructive independently of can_bypass_router."""

    def test_is_destructive_checked_before_can_bypass(self):
        """If is_destructive is True, should_bypass is False regardless."""
        # Direct check: even with matched=True, high confidence
        m = PreRouteMatch.create(IntentCategory.CALENDAR_DELETE, 1.0, "test")
        # Verify defense-in-depth: is_destructive alone blocks bypass
        assert m.intent.is_destructive is True
        assert m.should_bypass(0.0) is False

    def test_handler_type_still_calendar(self):
        """Handler type remains 'calendar' for routing hints."""
        assert IntentCategory.CALENDAR_CREATE.handler_type == "calendar"
        assert IntentCategory.CALENDAR_DELETE.handler_type == "calendar"
        assert IntentCategory.CALENDAR_UPDATE.handler_type == "calendar"
