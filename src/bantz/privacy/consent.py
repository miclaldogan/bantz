"""Consent manager — explicit cloud consent flow (Issue #299).

When a user tries to use a cloud feature (Gemini, web search, news)
and cloud_mode is off, we:
1. Prompt the user for consent (voice or text).
2. If accepted: persist consent, enable cloud_mode.
3. If declined: use local fallback, don't enable cloud.

The consent flow is designed for both voice and text interfaces.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from bantz.privacy.config import (
    CURRENT_CONSENT_VERSION,
    PrivacyConfig,
    load_privacy_config,
    save_privacy_config,
)

logger = logging.getLogger(__name__)

__all__ = ["ConsentManager", "ConsentResult", "ConsentStatus"]


# ─────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────


class ConsentStatus(str, Enum):
    """Result of a consent check."""

    ALREADY_GRANTED = "already_granted"
    NEWLY_GRANTED = "newly_granted"
    DECLINED = "declined"
    NOT_NEEDED = "not_needed"  # local feature, no consent required


@dataclass
class ConsentResult:
    """Result of a consent check or request."""

    status: ConsentStatus
    skill: str = ""
    message: str = ""

    @property
    def allowed(self) -> bool:
        """Whether the operation is allowed to proceed."""
        return self.status in (
            ConsentStatus.ALREADY_GRANTED,
            ConsentStatus.NEWLY_GRANTED,
            ConsentStatus.NOT_NEEDED,
        )


# ─────────────────────────────────────────────────────────────────
# Consent prompts (Turkish)
# ─────────────────────────────────────────────────────────────────

CONSENT_PROMPTS = {
    "gemini_finalize": (
        "Bu özellik için Gemini AI kullanılacak efendim. "
        "Bazı veriler Google'a gönderilecek. Onaylıyor musunuz?"
    ),
    "news_web_fetch": (
        "Haberleri getirmek için internet bağlantısı gerekiyor efendim. "
        "Bazı veriler dış servislere gönderilecek. Onaylıyor musunuz?"
    ),
    "web_search": (
        "Web araması için internet bağlantısı gerekiyor efendim. "
        "Arama terimi dış servislere gönderilecek. Onaylıyor musunuz?"
    ),
    "default": (
        "Bu özellik için internet bağlantısı gerekiyor efendim. "
        "Bazı veriler dış servislere gönderilecek. Onaylıyor musunuz?"
    ),
}

CONSENT_ACCEPTED_MSG = "Onay kaydedildi efendim. Özellik etkinleştirildi."
CONSENT_DECLINED_MSG = "Anlaşıldı efendim. Yerel alternatif kullanılacak."
AFFIRMATIVE_WORDS = frozenset({
    "evet", "tamam", "olur", "kabul", "onay", "onayla",
    "onaylıyorum", "yes", "ok", "okay", "yep", "sure",
    "elbette", "tabi", "tabii", "peki",
})


# ─────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────


class ConsentManager:
    """Manages user consent for cloud features.

    Parameters
    ----------
    config:
        Privacy config (loaded from disk or created fresh).
    config_path:
        Path to persist config changes. None = default.
    ask_fn:
        Callback to ask the user a question and get a response.
        ``ask_fn(prompt: str) -> str``
        If None, consent is always declined (headless mode).
    """

    def __init__(
        self,
        config: Optional[PrivacyConfig] = None,
        config_path=None,
        ask_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._config = config or load_privacy_config(config_path)
        self._config_path = config_path
        self._ask_fn = ask_fn

    @property
    def config(self) -> PrivacyConfig:
        return self._config

    def check_skill(self, skill_name: str) -> ConsentResult:
        """Check if a cloud skill is allowed, requesting consent if needed.

        Flow:
        1. If skill is already allowed → ALREADY_GRANTED
        2. If cloud_mode is off → ask for consent
        3. If consent given → enable skill, persist, NEWLY_GRANTED
        4. If declined → DECLINED
        """
        # Already have consent for this skill
        if self._config.is_skill_allowed(skill_name):
            logger.debug("Skill '%s' already allowed", skill_name)
            return ConsentResult(
                status=ConsentStatus.ALREADY_GRANTED,
                skill=skill_name,
            )

        # Need to ask for consent
        prompt = CONSENT_PROMPTS.get(skill_name, CONSENT_PROMPTS["default"])
        logger.info("Consent needed for skill '%s'", skill_name)

        if self._ask_fn is None:
            logger.debug("No ask_fn — declining consent (headless mode)")
            return ConsentResult(
                status=ConsentStatus.DECLINED,
                skill=skill_name,
                message=CONSENT_DECLINED_MSG,
            )

        # Ask the user
        try:
            response = self._ask_fn(prompt)
        except Exception as exc:
            logger.warning("Consent ask_fn failed: %s — declining", exc)
            return ConsentResult(
                status=ConsentStatus.DECLINED,
                skill=skill_name,
                message="Onay alınamadı efendim, yerel mod kullanılıyor.",
            )

        if self._is_affirmative(response):
            return self._grant_consent(skill_name)
        else:
            logger.info("User declined consent for '%s'", skill_name)
            return ConsentResult(
                status=ConsentStatus.DECLINED,
                skill=skill_name,
                message=CONSENT_DECLINED_MSG,
            )

    def grant_all(self) -> ConsentResult:
        """Grant consent for all cloud skills at once."""
        self._config.cloud_mode = True
        self._config.consent_given_at = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        self._config.consent_version = CURRENT_CONSENT_VERSION
        self._config.skills.enable_all()
        self._persist()
        logger.info("All cloud skills enabled")
        return ConsentResult(
            status=ConsentStatus.NEWLY_GRANTED,
            skill="all",
            message=CONSENT_ACCEPTED_MSG,
        )

    def revoke_all(self) -> None:
        """Revoke all cloud consent — return to local-only mode."""
        self._config.cloud_mode = False
        self._config.consent_given_at = None
        self._config.skills.disable_all()
        self._persist()
        logger.info("All cloud consent revoked — local-only mode")

    def revoke_skill(self, skill_name: str) -> None:
        """Revoke consent for a specific skill."""
        if hasattr(self._config.skills, skill_name):
            setattr(self._config.skills, skill_name, False)
            # If no skills remain, turn off cloud_mode
            if not self._config.skills.any_enabled():
                self._config.cloud_mode = False
            self._persist()
            logger.info("Consent revoked for '%s'", skill_name)

    def _grant_consent(self, skill_name: str) -> ConsentResult:
        """Internal: grant consent for a skill and persist."""
        self._config.cloud_mode = True
        self._config.consent_given_at = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        self._config.consent_version = CURRENT_CONSENT_VERSION

        if hasattr(self._config.skills, skill_name):
            setattr(self._config.skills, skill_name, True)

        self._persist()
        logger.info("Consent granted for '%s'", skill_name)

        return ConsentResult(
            status=ConsentStatus.NEWLY_GRANTED,
            skill=skill_name,
            message=CONSENT_ACCEPTED_MSG,
        )

    def _persist(self) -> None:
        """Save config to disk (best-effort)."""
        try:
            save_privacy_config(self._config, self._config_path)
        except Exception as exc:
            logger.warning("Failed to persist privacy config: %s", exc)

    @staticmethod
    def _is_affirmative(response: str) -> bool:
        """Check if user response is affirmative."""
        words = (response or "").strip().lower().split()
        return bool(words and words[0] in AFFIRMATIVE_WORDS)
