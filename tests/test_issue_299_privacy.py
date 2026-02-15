"""Tests for Issue #299 — Privacy: Mic indicator + local-only + cloud consent.

Covers:
  - PrivacyConfig: defaults, serialization, skill gating
  - SkillPermissions: enable/disable, any_enabled
  - load_privacy_config / save_privacy_config: file I/O, error handling
  - ConsentManager: consent flow, grant/revoke, persistence
  - ConsentResult / ConsentStatus: allowed property
  - redact_pii: all PII patterns (phone, email, TC, IBAN, card, IP)
  - RedactionStats: counting, patterns matched
  - MicIndicator / MicState: state changes, terminal mode, callback mode
  - File existence
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# PrivacyConfig
# ─────────────────────────────────────────────────────────────────


class TestPrivacyConfig:
    """Privacy configuration defaults and serialization."""

    def test_defaults_local_only(self):
        from bantz.privacy.config import PrivacyConfig

        cfg = PrivacyConfig()
        assert cfg.cloud_mode is False
        assert cfg.is_local_only is True
        assert cfg.consent_given_at is None
        assert cfg.has_consent is False
        assert cfg.data_retention_days == 7

    def test_skill_not_allowed_when_local(self):
        from bantz.privacy.config import PrivacyConfig

        cfg = PrivacyConfig(cloud_mode=False)
        assert cfg.is_skill_allowed("gemini_finalize") is False
        assert cfg.is_skill_allowed("news_web_fetch") is False

    def test_skill_allowed_when_cloud_and_enabled(self):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions

        cfg = PrivacyConfig(
            cloud_mode=True,
            consent_given_at="2024-01-01T00:00:00Z",
            skills=SkillPermissions(gemini_finalize=True),
        )
        assert cfg.is_skill_allowed("gemini_finalize") is True
        assert cfg.is_skill_allowed("news_web_fetch") is False

    def test_unknown_skill_returns_false(self):
        from bantz.privacy.config import PrivacyConfig

        cfg = PrivacyConfig(cloud_mode=True)
        assert cfg.is_skill_allowed("nonexistent_skill") is False

    def test_has_consent_requires_both(self):
        from bantz.privacy.config import PrivacyConfig

        # cloud_mode=True but no consent_given_at
        cfg1 = PrivacyConfig(cloud_mode=True, consent_given_at=None)
        assert cfg1.has_consent is False

        # consent_given_at set but cloud_mode=False
        cfg2 = PrivacyConfig(cloud_mode=False, consent_given_at="2024-01-01T00:00:00Z")
        assert cfg2.has_consent is False

        # Both set → True
        cfg3 = PrivacyConfig(cloud_mode=True, consent_given_at="2024-01-01T00:00:00Z")
        assert cfg3.has_consent is True

    def test_to_dict_roundtrip(self):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions

        orig = PrivacyConfig(
            cloud_mode=True,
            consent_given_at="2024-06-15T12:00:00Z",
            consent_version="1.0",
            skills=SkillPermissions(gemini_finalize=True, web_search=True),
            data_retention_days=14,
        )
        d = orig.to_dict()
        restored = PrivacyConfig.from_dict(d)
        assert restored.cloud_mode is True
        assert restored.consent_given_at == "2024-06-15T12:00:00Z"
        assert restored.skills.gemini_finalize is True
        assert restored.skills.web_search is True
        assert restored.skills.news_web_fetch is False
        assert restored.data_retention_days == 14

    def test_from_dict_handles_missing_fields(self):
        from bantz.privacy.config import PrivacyConfig

        cfg = PrivacyConfig.from_dict({})
        assert cfg.cloud_mode is False
        assert cfg.consent_given_at is None

    def test_from_dict_handles_invalid_skills(self):
        from bantz.privacy.config import PrivacyConfig

        cfg = PrivacyConfig.from_dict({"skills": "invalid"})
        assert cfg.skills.gemini_finalize is False


# ─────────────────────────────────────────────────────────────────
# SkillPermissions
# ─────────────────────────────────────────────────────────────────


class TestSkillPermissions:
    """Per-skill cloud permission flags."""

    def test_defaults_all_false(self):
        from bantz.privacy.config import SkillPermissions

        s = SkillPermissions()
        assert s.news_web_fetch is False
        assert s.gemini_finalize is False
        assert s.web_search is False
        assert s.any_enabled() is False

    def test_enable_all(self):
        from bantz.privacy.config import SkillPermissions

        s = SkillPermissions()
        s.enable_all()
        assert s.news_web_fetch is True
        assert s.gemini_finalize is True
        assert s.web_search is True
        assert s.any_enabled() is True

    def test_disable_all(self):
        from bantz.privacy.config import SkillPermissions

        s = SkillPermissions(news_web_fetch=True, gemini_finalize=True, web_search=True)
        s.disable_all()
        assert s.any_enabled() is False

    def test_any_enabled_partial(self):
        from bantz.privacy.config import SkillPermissions

        s = SkillPermissions(web_search=True)
        assert s.any_enabled() is True


# ─────────────────────────────────────────────────────────────────
# Load / Save
# ─────────────────────────────────────────────────────────────────


class TestLoadSaveConfig:
    """File I/O for privacy config."""

    def test_load_missing_file_returns_defaults(self, tmp_path):
        from bantz.privacy.config import load_privacy_config

        cfg = load_privacy_config(tmp_path / "nonexistent.json")
        assert cfg.cloud_mode is False

    def test_save_and_load_roundtrip(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions, save_privacy_config, load_privacy_config

        path = tmp_path / "privacy.json"
        orig = PrivacyConfig(
            cloud_mode=True,
            consent_given_at="2024-01-01T00:00:00Z",
            skills=SkillPermissions(gemini_finalize=True),
        )
        assert save_privacy_config(orig, path) is True
        assert path.is_file()

        loaded = load_privacy_config(path)
        assert loaded.cloud_mode is True
        assert loaded.skills.gemini_finalize is True

    def test_save_creates_directories(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig, save_privacy_config

        path = tmp_path / "deep" / "nested" / "privacy.json"
        assert save_privacy_config(PrivacyConfig(), path) is True
        assert path.is_file()

    def test_load_corrupt_file_returns_defaults(self, tmp_path):
        from bantz.privacy.config import load_privacy_config

        path = tmp_path / "bad.json"
        path.write_text("this is not json!!!", encoding="utf-8")
        cfg = load_privacy_config(path)
        assert cfg.cloud_mode is False

    def test_saved_json_readable(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig, save_privacy_config

        path = tmp_path / "privacy.json"
        save_privacy_config(PrivacyConfig(), path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["cloud_mode"] is False
        assert "skills" in data


# ─────────────────────────────────────────────────────────────────
# ConsentManager
# ─────────────────────────────────────────────────────────────────


class TestConsentManager:
    """Consent flow for cloud features."""

    def test_already_granted_skill(self):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions
        from bantz.privacy.consent import ConsentManager, ConsentStatus

        cfg = PrivacyConfig(
            cloud_mode=True,
            consent_given_at="2024-01-01T00:00:00Z",
            skills=SkillPermissions(gemini_finalize=True),
        )
        mgr = ConsentManager(config=cfg)
        result = mgr.check_skill("gemini_finalize")
        assert result.status == ConsentStatus.ALREADY_GRANTED
        assert result.allowed is True

    def test_consent_newly_granted(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig
        from bantz.privacy.consent import ConsentManager, ConsentStatus

        cfg = PrivacyConfig()  # local-only
        path = tmp_path / "privacy.json"
        mgr = ConsentManager(
            config=cfg,
            config_path=path,
            ask_fn=lambda _: "evet",
        )
        result = mgr.check_skill("gemini_finalize")
        assert result.status == ConsentStatus.NEWLY_GRANTED
        assert result.allowed is True
        assert mgr.config.cloud_mode is True
        assert mgr.config.skills.gemini_finalize is True
        # Should be persisted
        assert path.is_file()

    def test_consent_declined(self):
        from bantz.privacy.config import PrivacyConfig
        from bantz.privacy.consent import ConsentManager, ConsentStatus

        cfg = PrivacyConfig()
        mgr = ConsentManager(config=cfg, ask_fn=lambda _: "hayır")
        result = mgr.check_skill("web_search")
        assert result.status == ConsentStatus.DECLINED
        assert result.allowed is False
        assert mgr.config.cloud_mode is False

    def test_no_ask_fn_declines(self):
        from bantz.privacy.config import PrivacyConfig
        from bantz.privacy.consent import ConsentManager, ConsentStatus

        mgr = ConsentManager(config=PrivacyConfig(), ask_fn=None)
        result = mgr.check_skill("news_web_fetch")
        assert result.status == ConsentStatus.DECLINED

    def test_ask_fn_error_declines(self):
        from bantz.privacy.config import PrivacyConfig
        from bantz.privacy.consent import ConsentManager, ConsentStatus

        def bad_ask(prompt):
            raise RuntimeError("broken")

        mgr = ConsentManager(config=PrivacyConfig(), ask_fn=bad_ask)
        result = mgr.check_skill("gemini_finalize")
        assert result.status == ConsentStatus.DECLINED

    def test_grant_all(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig
        from bantz.privacy.consent import ConsentManager, ConsentStatus

        cfg = PrivacyConfig()
        path = tmp_path / "privacy.json"
        mgr = ConsentManager(config=cfg, config_path=path)
        result = mgr.grant_all()
        assert result.status == ConsentStatus.NEWLY_GRANTED
        assert result.skill == "all"
        assert mgr.config.skills.any_enabled() is True

    def test_revoke_all(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions
        from bantz.privacy.consent import ConsentManager

        cfg = PrivacyConfig(
            cloud_mode=True,
            consent_given_at="2024-01-01T00:00:00Z",
            skills=SkillPermissions(gemini_finalize=True, web_search=True),
        )
        mgr = ConsentManager(config=cfg, config_path=tmp_path / "p.json")
        mgr.revoke_all()
        assert mgr.config.cloud_mode is False
        assert mgr.config.consent_given_at is None
        assert mgr.config.skills.any_enabled() is False

    def test_revoke_skill(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions
        from bantz.privacy.consent import ConsentManager

        cfg = PrivacyConfig(
            cloud_mode=True,
            skills=SkillPermissions(gemini_finalize=True, web_search=True),
        )
        mgr = ConsentManager(config=cfg, config_path=tmp_path / "p.json")
        mgr.revoke_skill("gemini_finalize")
        assert mgr.config.skills.gemini_finalize is False
        assert mgr.config.skills.web_search is True
        assert mgr.config.cloud_mode is True  # still has web_search

    def test_revoke_last_skill_disables_cloud(self, tmp_path):
        from bantz.privacy.config import PrivacyConfig, SkillPermissions
        from bantz.privacy.consent import ConsentManager

        cfg = PrivacyConfig(
            cloud_mode=True,
            skills=SkillPermissions(gemini_finalize=True),
        )
        mgr = ConsentManager(config=cfg, config_path=tmp_path / "p.json")
        mgr.revoke_skill("gemini_finalize")
        assert mgr.config.cloud_mode is False

    def test_affirmative_words(self):
        from bantz.privacy.consent import ConsentManager

        mgr = ConsentManager.__new__(ConsentManager)
        for word in ["evet", "tamam", "olur", "kabul", "onay", "yes", "ok", "elbette", "tabi"]:
            assert mgr._is_affirmative(word) is True, f"'{word}' should be affirmative"

    def test_non_affirmative_words(self):
        from bantz.privacy.consent import ConsentManager

        mgr = ConsentManager.__new__(ConsentManager)
        for word in ["hayır", "yok", "no", "istemiyorum", ""]:
            assert mgr._is_affirmative(word) is False, f"'{word}' should not be affirmative"


# ─────────────────────────────────────────────────────────────────
# ConsentResult
# ─────────────────────────────────────────────────────────────────


class TestConsentResult:
    """ConsentResult allowed property."""

    def test_granted_is_allowed(self):
        from bantz.privacy.consent import ConsentResult, ConsentStatus

        assert ConsentResult(status=ConsentStatus.ALREADY_GRANTED).allowed is True
        assert ConsentResult(status=ConsentStatus.NEWLY_GRANTED).allowed is True
        assert ConsentResult(status=ConsentStatus.NOT_NEEDED).allowed is True

    def test_declined_not_allowed(self):
        from bantz.privacy.consent import ConsentResult, ConsentStatus

        assert ConsentResult(status=ConsentStatus.DECLINED).allowed is False


# ─────────────────────────────────────────────────────────────────
# PII Redaction
# ─────────────────────────────────────────────────────────────────


class TestRedaction:
    """PII redaction patterns."""

    def test_turkish_phone_mobile(self):
        from bantz.privacy.redaction import redact_pii

        assert "[TELEFON]" in redact_pii("Numaram 05321234567")

    def test_turkish_phone_with_country_code(self):
        from bantz.privacy.redaction import redact_pii

        assert "[TELEFON]" in redact_pii("Ara +905321234567")

    def test_turkish_phone_with_spaces(self):
        from bantz.privacy.redaction import redact_pii

        assert "[TELEFON]" in redact_pii("Numaram 0532 123 45 67")

    def test_email(self):
        from bantz.privacy.redaction import redact_pii

        result = redact_pii("Mail adresim test@example.com")
        assert "[EMAIL]" in result
        assert "test@example.com" not in result

    def test_turkish_id(self):
        from bantz.privacy.redaction import redact_pii

        # TC Kimlik: 11 digits, first digit 1-9, last digit even
        result = redact_pii("TC numaram 12345678900")
        assert "[TC_KIMLIK]" in result

    def test_credit_card(self):
        from bantz.privacy.redaction import redact_pii

        result = redact_pii("Kart: 4532 1234 5678 9012")
        assert "[KART]" in result

    def test_ip_address(self):
        from bantz.privacy.redaction import redact_pii

        result = redact_pii("IP: 192.168.1.100")
        assert "[IP]" in result

    def test_empty_text(self):
        from bantz.privacy.redaction import redact_pii

        assert redact_pii("") == ""

    def test_no_pii(self):
        from bantz.privacy.redaction import redact_pii

        text = "Yarın hava nasıl olacak?"
        assert redact_pii(text) == text

    def test_multiple_pii_in_one_text(self):
        from bantz.privacy.redaction import redact_pii

        text = "Mail: a@b.com, Tel: 05321234567"
        result = redact_pii(text)
        assert "[EMAIL]" in result
        assert "[TELEFON]" in result

    def test_stats_collection(self):
        from bantz.privacy.redaction import redact_pii

        result, stats = redact_pii("Mail: test@x.com", collect_stats=True)
        assert "[EMAIL]" in result
        assert stats.total_redactions >= 1
        assert len(stats.patterns_matched) >= 1

    def test_stats_no_pii(self):
        from bantz.privacy.redaction import redact_pii

        result, stats = redact_pii("Merhaba efendim", collect_stats=True)
        assert stats.total_redactions == 0

    def test_extra_patterns(self):
        from bantz.privacy.redaction import redact_pii

        custom = [(re.compile(r"SECRET_\w+"), "[GİZLİ]", "Custom secret")]
        result = redact_pii("Token: SECRET_abc123", extra_patterns=custom)
        assert "[GİZLİ]" in result


# ─────────────────────────────────────────────────────────────────
# MicState
# ─────────────────────────────────────────────────────────────────


class TestMicState:
    """Microphone state enum."""

    def test_states_exist(self):
        from bantz.privacy.indicator import MicState

        assert MicState.IDLE.value == "idle"
        assert MicState.LISTENING.value == "listening"
        assert MicState.PROCESSING.value == "processing"
        assert MicState.SPEAKING.value == "speaking"
        assert MicState.ERROR.value == "error"

    def test_turkish_labels(self):
        from bantz.privacy.indicator import MicState

        assert MicState.LISTENING.label_tr == "DİNLENİYOR"
        assert MicState.IDLE.label_tr == "HAZIR"
        assert MicState.PROCESSING.label_tr == "İŞLENİYOR"

    def test_icons(self):
        from bantz.privacy.indicator import MicState

        assert MicState.LISTENING.icon == "🔴"
        assert MicState.IDLE.icon == "⚪"


# ─────────────────────────────────────────────────────────────────
# MicIndicator
# ─────────────────────────────────────────────────────────────────


class TestMicIndicator:
    """Mic state indicator."""

    def test_default_state_idle(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        ind = MicIndicator(mode="silent")
        assert ind.state == MicState.IDLE

    def test_state_change(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        ind = MicIndicator(mode="silent")
        ind.on_state_change(MicState.LISTENING)
        assert ind.state == MicState.LISTENING

    def test_no_change_on_same_state(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        ind = MicIndicator(mode="silent")
        ind.on_state_change(MicState.LISTENING)
        history_len = len(ind.state_history)
        ind.on_state_change(MicState.LISTENING)  # Same state
        assert len(ind.state_history) == history_len

    def test_state_history_tracked(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        ind = MicIndicator(mode="silent")
        ind.on_state_change(MicState.LISTENING)
        ind.on_state_change(MicState.PROCESSING)
        ind.on_state_change(MicState.SPEAKING)
        assert len(ind.state_history) == 3
        assert ind.state_history[0][0] == MicState.LISTENING
        assert ind.state_history[2][0] == MicState.SPEAKING

    def test_state_duration(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        ind = MicIndicator(mode="silent")
        ind.on_state_change(MicState.LISTENING)
        time.sleep(0.05)
        assert ind.state_duration >= 0.04

    def test_callback_mode(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        received = []
        ind = MicIndicator(mode="callback", callback=lambda s: received.append(s))
        ind.on_state_change(MicState.LISTENING)
        ind.on_state_change(MicState.IDLE)
        assert len(received) == 2
        assert received[0] == MicState.LISTENING

    def test_callback_error_handled(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        def bad_cb(s):
            raise ValueError("broken")

        ind = MicIndicator(mode="callback", callback=bad_cb)
        ind.on_state_change(MicState.LISTENING)  # Should not raise
        assert ind.state == MicState.LISTENING

    def test_reset(self):
        from bantz.privacy.indicator import MicIndicator, MicState

        ind = MicIndicator(mode="silent")
        ind.on_state_change(MicState.LISTENING)
        ind.on_state_change(MicState.PROCESSING)
        ind.reset()
        assert ind.state == MicState.IDLE
        assert len(ind.state_history) == 0


# ─────────────────────────────────────────────────────────────────
# File existence
# ─────────────────────────────────────────────────────────────────


class TestFileExistence:
    """Verify all Issue #299 files exist."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_init_exists(self):
        assert (self.ROOT / "src" / "bantz" / "privacy" / "__init__.py").is_file()

    def test_config_exists(self):
        assert (self.ROOT / "src" / "bantz" / "privacy" / "config.py").is_file()

    def test_consent_exists(self):
        assert (self.ROOT / "src" / "bantz" / "privacy" / "consent.py").is_file()

    def test_redaction_exists(self):
        assert (self.ROOT / "src" / "bantz" / "privacy" / "redaction.py").is_file()

    def test_indicator_exists(self):
        assert (self.ROOT / "src" / "bantz" / "privacy" / "indicator.py").is_file()
