"""Tests for memory preferences module.

Issue #243: PROFILE preferences to steer router + finalizer.

Tests cover:
- Preference enums (ReplyLength, ConfirmWrites, CloudModeDefault)
- UserPreferences dataclass
- PreferenceStore with change tracking
- Config overrides (Router, BrainLoop)
- Preference inference from text
"""

import os
from typing import Any
from unittest.mock import patch

import pytest

from bantz.memory.preferences import (
    ReplyLength,
    ConfirmWrites,
    CloudModeDefault,
    UserPreferences,
    PreferenceChange,
    PreferenceStore,
    RouterConfigOverride,
    BrainLoopConfigOverride,
    get_default_preferences,
    infer_preferences_from_text,
    apply_inferences,
)


# =============================================================================
# ReplyLength Tests
# =============================================================================

class TestReplyLength:
    """Tests for ReplyLength enum."""
    
    def test_short_value(self) -> None:
        """Test SHORT value."""
        assert ReplyLength.SHORT.value == "short"
    
    def test_normal_value(self) -> None:
        """Test NORMAL value."""
        assert ReplyLength.NORMAL.value == "normal"
    
    def test_long_value(self) -> None:
        """Test LONG value."""
        assert ReplyLength.LONG.value == "long"
    
    def test_short_max_tokens(self) -> None:
        """Test SHORT max tokens."""
        assert ReplyLength.SHORT.max_tokens == 50
    
    def test_normal_max_tokens(self) -> None:
        """Test NORMAL max tokens."""
        assert ReplyLength.NORMAL.max_tokens == 150
    
    def test_long_max_tokens(self) -> None:
        """Test LONG max tokens."""
        assert ReplyLength.LONG.max_tokens == 300
    
    def test_short_description_tr(self) -> None:
        """Test SHORT Turkish description."""
        assert "Kısa" in ReplyLength.SHORT.description_tr
    
    def test_normal_description_tr(self) -> None:
        """Test NORMAL Turkish description."""
        assert "Normal" in ReplyLength.NORMAL.description_tr
    
    def test_long_description_tr(self) -> None:
        """Test LONG Turkish description."""
        assert "Detaylı" in ReplyLength.LONG.description_tr
    
    def test_from_str_short(self) -> None:
        """Test parsing short."""
        assert ReplyLength.from_str("short") == ReplyLength.SHORT
    
    def test_from_str_normal(self) -> None:
        """Test parsing normal."""
        assert ReplyLength.from_str("normal") == ReplyLength.NORMAL
    
    def test_from_str_long(self) -> None:
        """Test parsing long."""
        assert ReplyLength.from_str("long") == ReplyLength.LONG
    
    def test_from_str_case_insensitive(self) -> None:
        """Test case insensitive parsing."""
        assert ReplyLength.from_str("SHORT") == ReplyLength.SHORT
        assert ReplyLength.from_str("Normal") == ReplyLength.NORMAL
    
    def test_from_str_whitespace(self) -> None:
        """Test parsing with whitespace."""
        assert ReplyLength.from_str("  short  ") == ReplyLength.SHORT
    
    def test_from_str_unknown(self) -> None:
        """Test parsing unknown returns NORMAL."""
        assert ReplyLength.from_str("unknown") == ReplyLength.NORMAL


# =============================================================================
# ConfirmWrites Tests
# =============================================================================

class TestConfirmWrites:
    """Tests for ConfirmWrites enum."""
    
    def test_always_value(self) -> None:
        """Test ALWAYS value."""
        assert ConfirmWrites.ALWAYS.value == "always"
    
    def test_ask_value(self) -> None:
        """Test ASK value."""
        assert ConfirmWrites.ASK.value == "ask"
    
    def test_never_value(self) -> None:
        """Test NEVER value."""
        assert ConfirmWrites.NEVER.value == "never"
    
    def test_always_requires_confirmation(self) -> None:
        """Test ALWAYS requires confirmation."""
        assert ConfirmWrites.ALWAYS.requires_confirmation is True
    
    def test_ask_not_requires_confirmation(self) -> None:
        """Test ASK does not require confirmation."""
        assert ConfirmWrites.ASK.requires_confirmation is False
    
    def test_never_not_requires_confirmation(self) -> None:
        """Test NEVER does not require confirmation."""
        assert ConfirmWrites.NEVER.requires_confirmation is False
    
    def test_always_description_tr(self) -> None:
        """Test ALWAYS Turkish description."""
        assert "HER ZAMAN" in ConfirmWrites.ALWAYS.description_tr
    
    def test_from_str_always(self) -> None:
        """Test parsing always."""
        assert ConfirmWrites.from_str("always") == ConfirmWrites.ALWAYS
    
    def test_from_str_ask(self) -> None:
        """Test parsing ask."""
        assert ConfirmWrites.from_str("ask") == ConfirmWrites.ASK
    
    def test_from_str_never(self) -> None:
        """Test parsing never."""
        assert ConfirmWrites.from_str("never") == ConfirmWrites.NEVER
    
    def test_from_str_unknown(self) -> None:
        """Test parsing unknown returns ASK."""
        assert ConfirmWrites.from_str("unknown") == ConfirmWrites.ASK


# =============================================================================
# CloudModeDefault Tests
# =============================================================================

class TestCloudModeDefault:
    """Tests for CloudModeDefault enum."""
    
    def test_local_value(self) -> None:
        """Test LOCAL value."""
        assert CloudModeDefault.LOCAL.value == "local"
    
    def test_cloud_value(self) -> None:
        """Test CLOUD value."""
        assert CloudModeDefault.CLOUD.value == "cloud"
    
    def test_local_not_cloud_enabled(self) -> None:
        """Test LOCAL cloud not enabled."""
        assert CloudModeDefault.LOCAL.is_cloud_enabled is False
    
    def test_cloud_is_cloud_enabled(self) -> None:
        """Test CLOUD cloud enabled."""
        assert CloudModeDefault.CLOUD.is_cloud_enabled is True
    
    def test_local_description_tr(self) -> None:
        """Test LOCAL Turkish description."""
        assert "Yerel" in CloudModeDefault.LOCAL.description_tr
    
    def test_cloud_description_tr(self) -> None:
        """Test CLOUD Turkish description."""
        assert "cloud" in CloudModeDefault.CLOUD.description_tr
    
    def test_from_str_local(self) -> None:
        """Test parsing local."""
        assert CloudModeDefault.from_str("local") == CloudModeDefault.LOCAL
    
    def test_from_str_cloud(self) -> None:
        """Test parsing cloud."""
        assert CloudModeDefault.from_str("cloud") == CloudModeDefault.CLOUD
    
    def test_from_str_unknown(self) -> None:
        """Test parsing unknown returns LOCAL."""
        assert CloudModeDefault.from_str("unknown") == CloudModeDefault.LOCAL


# =============================================================================
# UserPreferences Tests
# =============================================================================

class TestUserPreferences:
    """Tests for UserPreferences dataclass."""
    
    def test_default_values(self) -> None:
        """Test default preference values."""
        prefs = UserPreferences()
        assert prefs.reply_length == ReplyLength.NORMAL
        assert prefs.confirm_writes == ConfirmWrites.ASK
        assert prefs.cloud_mode_default == CloudModeDefault.LOCAL
        assert prefs.language == "tr"
        assert prefs.timezone == "Europe/Istanbul"
    
    def test_custom_values(self) -> None:
        """Test custom preference values."""
        prefs = UserPreferences(
            reply_length=ReplyLength.SHORT,
            confirm_writes=ConfirmWrites.ALWAYS,
            cloud_mode_default=CloudModeDefault.CLOUD,
        )
        assert prefs.reply_length == ReplyLength.SHORT
        assert prefs.confirm_writes == ConfirmWrites.ALWAYS
        assert prefs.cloud_mode_default == CloudModeDefault.CLOUD
    
    def test_frozen(self) -> None:
        """Test preferences are frozen."""
        prefs = UserPreferences()
        with pytest.raises(Exception):  # FrozenInstanceError
            prefs.reply_length = ReplyLength.LONG  # type: ignore
    
    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        prefs = UserPreferences(
            reply_length=ReplyLength.SHORT,
            confirm_writes=ConfirmWrites.ALWAYS,
            cloud_mode_default=CloudModeDefault.CLOUD,
        )
        d = prefs.to_dict()
        assert d["reply_length"] == "short"
        assert d["confirm_writes"] == "always"
        assert d["cloud_mode_default"] == "cloud"
        assert d["language"] == "tr"
        assert d["timezone"] == "Europe/Istanbul"
    
    def test_from_dict(self) -> None:
        """Test from_dict creation."""
        data = {
            "reply_length": "long",
            "confirm_writes": "never",
            "cloud_mode_default": "cloud",
            "language": "en",
            "timezone": "UTC",
        }
        prefs = UserPreferences.from_dict(data)
        assert prefs.reply_length == ReplyLength.LONG
        assert prefs.confirm_writes == ConfirmWrites.NEVER
        assert prefs.cloud_mode_default == CloudModeDefault.CLOUD
        assert prefs.language == "en"
        assert prefs.timezone == "UTC"
    
    def test_from_dict_empty(self) -> None:
        """Test from_dict with empty dict uses defaults."""
        prefs = UserPreferences.from_dict({})
        assert prefs.reply_length == ReplyLength.NORMAL
        assert prefs.confirm_writes == ConfirmWrites.ASK
    
    def test_to_prompt_block(self) -> None:
        """Test prompt block generation."""
        prefs = UserPreferences(reply_length=ReplyLength.SHORT)
        block = prefs.to_prompt_block()
        assert "<PREFERENCES>" in block
        assert "</PREFERENCES>" in block
        assert "Kısa" in block
    
    def test_get_max_tokens(self) -> None:
        """Test max tokens getter."""
        prefs_short = UserPreferences(reply_length=ReplyLength.SHORT)
        prefs_long = UserPreferences(reply_length=ReplyLength.LONG)
        assert prefs_short.get_max_tokens() == 50
        assert prefs_long.get_max_tokens() == 300
    
    def test_should_confirm_write_always(self) -> None:
        """Test should_confirm_write with ALWAYS."""
        prefs = UserPreferences(confirm_writes=ConfirmWrites.ALWAYS)
        assert prefs.should_confirm_write() is True
        assert prefs.should_confirm_write(is_ambiguous=False) is True
    
    def test_should_confirm_write_never(self) -> None:
        """Test should_confirm_write with NEVER."""
        prefs = UserPreferences(confirm_writes=ConfirmWrites.NEVER)
        assert prefs.should_confirm_write() is False
        assert prefs.should_confirm_write(is_ambiguous=True) is False
    
    def test_should_confirm_write_ask(self) -> None:
        """Test should_confirm_write with ASK."""
        prefs = UserPreferences(confirm_writes=ConfirmWrites.ASK)
        assert prefs.should_confirm_write() is False
        assert prefs.should_confirm_write(is_ambiguous=True) is True
    
    def test_should_use_cloud_default_local(self) -> None:
        """Test should_use_cloud with LOCAL default."""
        prefs = UserPreferences(cloud_mode_default=CloudModeDefault.LOCAL)
        assert prefs.should_use_cloud() is False
        assert prefs.should_use_cloud(quality_requested=True) is True
    
    def test_should_use_cloud_default_cloud(self) -> None:
        """Test should_use_cloud with CLOUD default."""
        prefs = UserPreferences(cloud_mode_default=CloudModeDefault.CLOUD)
        assert prefs.should_use_cloud() is True


# =============================================================================
# PreferenceChange Tests
# =============================================================================

class TestPreferenceChange:
    """Tests for PreferenceChange dataclass."""
    
    def test_creation(self) -> None:
        """Test change creation."""
        change = PreferenceChange(
            key="reply_length",
            old_value="normal",
            new_value="short",
            source="user_stated",
        )
        assert change.key == "reply_length"
        assert change.old_value == "normal"
        assert change.new_value == "short"
        assert change.source == "user_stated"
        assert change.confidence == 1.0
    
    def test_custom_confidence(self) -> None:
        """Test change with custom confidence."""
        change = PreferenceChange(
            key="reply_length",
            old_value="normal",
            new_value="short",
            source="inferred",
            confidence=0.8,
        )
        assert change.confidence == 0.8


# =============================================================================
# PreferenceStore Tests
# =============================================================================

class TestPreferenceStore:
    """Tests for PreferenceStore class."""
    
    def test_default_init(self) -> None:
        """Test default initialization."""
        store = PreferenceStore()
        assert store.preferences.reply_length == ReplyLength.NORMAL
        assert len(store.changes) == 0
    
    def test_custom_init(self) -> None:
        """Test custom initialization."""
        prefs = UserPreferences(reply_length=ReplyLength.SHORT)
        store = PreferenceStore(prefs)
        assert store.preferences.reply_length == ReplyLength.SHORT
    
    def test_update_reply_length(self) -> None:
        """Test updating reply length."""
        store = PreferenceStore()
        new_prefs = store.update(reply_length=ReplyLength.SHORT)
        assert new_prefs.reply_length == ReplyLength.SHORT
        assert store.preferences.reply_length == ReplyLength.SHORT
    
    def test_update_tracks_change(self) -> None:
        """Test that update tracks changes."""
        store = PreferenceStore()
        store.update(reply_length=ReplyLength.SHORT)
        assert len(store.changes) == 1
        assert store.changes[0].key == "reply_length"
        assert store.changes[0].new_value == "short"
    
    def test_update_multiple_fields(self) -> None:
        """Test updating multiple fields."""
        store = PreferenceStore()
        store.update(
            reply_length=ReplyLength.SHORT,
            confirm_writes=ConfirmWrites.ALWAYS,
        )
        assert len(store.changes) == 2
    
    def test_update_no_change_no_record(self) -> None:
        """Test that no change is recorded if value same."""
        prefs = UserPreferences(reply_length=ReplyLength.SHORT)
        store = PreferenceStore(prefs)
        store.update(reply_length=ReplyLength.SHORT)
        assert len(store.changes) == 0
    
    def test_set_short_replies(self) -> None:
        """Test convenience method for short replies."""
        store = PreferenceStore()
        store.set_short_replies()
        assert store.preferences.reply_length == ReplyLength.SHORT
    
    def test_set_always_confirm(self) -> None:
        """Test convenience method for always confirm."""
        store = PreferenceStore()
        store.set_always_confirm()
        assert store.preferences.confirm_writes == ConfirmWrites.ALWAYS
    
    def test_set_cloud_enabled(self) -> None:
        """Test convenience method for cloud enabled."""
        store = PreferenceStore()
        store.set_cloud_enabled()
        assert store.preferences.cloud_mode_default == CloudModeDefault.CLOUD
    
    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        store = PreferenceStore()
        store.update(reply_length=ReplyLength.SHORT)
        d = store.to_dict()
        assert "preferences" in d
        assert "changes" in d
        assert d["preferences"]["reply_length"] == "short"
        assert len(d["changes"]) == 1
    
    def test_from_dict(self) -> None:
        """Test from_dict creation."""
        data = {
            "preferences": {"reply_length": "short"},
            "changes": [
                {"key": "reply_length", "old_value": "normal", "new_value": "short", "source": "user", "confidence": 0.9}
            ],
        }
        store = PreferenceStore.from_dict(data)
        assert store.preferences.reply_length == ReplyLength.SHORT
        assert len(store.changes) == 1


# =============================================================================
# RouterConfigOverride Tests
# =============================================================================

class TestRouterConfigOverride:
    """Tests for RouterConfigOverride."""
    
    def test_default_values(self) -> None:
        """Test default override values."""
        override = RouterConfigOverride()
        assert override.max_tokens == 150
        assert override.require_confirmation is False
        assert override.cloud_enabled is False
    
    def test_from_preferences_short(self) -> None:
        """Test from preferences with short replies."""
        prefs = UserPreferences(reply_length=ReplyLength.SHORT)
        override = RouterConfigOverride.from_preferences(prefs)
        assert override.max_tokens == 50
    
    def test_from_preferences_always_confirm(self) -> None:
        """Test from preferences with always confirm."""
        prefs = UserPreferences(confirm_writes=ConfirmWrites.ALWAYS)
        override = RouterConfigOverride.from_preferences(prefs)
        assert override.require_confirmation is True
    
    def test_from_preferences_cloud(self) -> None:
        """Test from preferences with cloud enabled."""
        prefs = UserPreferences(cloud_mode_default=CloudModeDefault.CLOUD)
        override = RouterConfigOverride.from_preferences(prefs)
        assert override.cloud_enabled is True
    
    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        override = RouterConfigOverride(max_tokens=50, require_confirmation=True, cloud_enabled=True)
        d = override.to_dict()
        assert d["max_tokens"] == 50
        assert d["require_confirmation"] is True
        assert d["cloud_enabled"] is True


# =============================================================================
# BrainLoopConfigOverride Tests
# =============================================================================

class TestBrainLoopConfigOverride:
    """Tests for BrainLoopConfigOverride."""
    
    def test_default_values(self) -> None:
        """Test default override values."""
        override = BrainLoopConfigOverride()
        assert override.max_response_tokens == 150
        assert override.always_confirm_writes is False
        assert override.enable_cloud_finalizer is False
    
    def test_from_preferences(self) -> None:
        """Test from preferences."""
        prefs = UserPreferences(
            reply_length=ReplyLength.LONG,
            confirm_writes=ConfirmWrites.ALWAYS,
            cloud_mode_default=CloudModeDefault.CLOUD,
        )
        override = BrainLoopConfigOverride.from_preferences(prefs)
        assert override.max_response_tokens == 300
        assert override.always_confirm_writes is True
        assert override.enable_cloud_finalizer is True
    
    def test_apply_to_config(self) -> None:
        """Test applying to config dict."""
        override = BrainLoopConfigOverride(
            max_response_tokens=50,
            always_confirm_writes=True,
            enable_cloud_finalizer=True,
        )
        config = {"some_key": "value"}
        result = override.apply_to_config(config)
        assert result["some_key"] == "value"
        assert result["max_response_tokens"] == 50
        assert result["always_confirm_writes"] is True
        assert result["enable_cloud_finalizer"] is True


# =============================================================================
# Environment Variable Tests
# =============================================================================

class TestGetDefaultPreferences:
    """Tests for get_default_preferences function."""
    
    def test_default_without_env(self) -> None:
        """Test defaults without environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            prefs = get_default_preferences()
            assert prefs.reply_length == ReplyLength.NORMAL
    
    def test_reply_length_from_env(self) -> None:
        """Test reply length from environment."""
        with patch.dict(os.environ, {"BANTZ_REPLY_LENGTH": "short"}):
            prefs = get_default_preferences()
            assert prefs.reply_length == ReplyLength.SHORT
    
    def test_confirm_writes_from_env(self) -> None:
        """Test confirm writes from environment."""
        with patch.dict(os.environ, {"BANTZ_CONFIRM_WRITES": "always"}):
            prefs = get_default_preferences()
            assert prefs.confirm_writes == ConfirmWrites.ALWAYS
    
    def test_cloud_mode_from_env(self) -> None:
        """Test cloud mode from environment."""
        with patch.dict(os.environ, {"BANTZ_CLOUD_MODE": "cloud"}):
            prefs = get_default_preferences()
            assert prefs.cloud_mode_default == CloudModeDefault.CLOUD
    
    def test_language_from_env(self) -> None:
        """Test language from environment."""
        with patch.dict(os.environ, {"BANTZ_LANGUAGE": "en"}):
            prefs = get_default_preferences()
            assert prefs.language == "en"
    
    def test_timezone_from_env(self) -> None:
        """Test timezone from environment."""
        with patch.dict(os.environ, {"BANTZ_TIMEZONE": "UTC"}):
            prefs = get_default_preferences()
            assert prefs.timezone == "UTC"


# =============================================================================
# Preference Inference Tests
# =============================================================================

class TestInferPreferencesFromText:
    """Tests for infer_preferences_from_text function."""
    
    def test_infer_short_reply(self) -> None:
        """Test inferring short reply preference."""
        inferences = infer_preferences_from_text("Kısa cevap ver lütfen")
        assert len(inferences) > 0
        assert ("reply_length", ReplyLength.SHORT, 0.9) in inferences
    
    def test_infer_short_reply_variant(self) -> None:
        """Test inferring short reply with variant phrase."""
        inferences = infer_preferences_from_text("Cevapları kısa tut")
        assert any(i[1] == ReplyLength.SHORT for i in inferences)
    
    def test_infer_long_reply(self) -> None:
        """Test inferring long reply preference."""
        inferences = infer_preferences_from_text("Detaylı cevap istiyorum")
        assert any(i[1] == ReplyLength.LONG for i in inferences)
    
    def test_infer_always_confirm(self) -> None:
        """Test inferring always confirm preference."""
        inferences = infer_preferences_from_text("Her zaman sor bana")
        assert any(i[1] == ConfirmWrites.ALWAYS for i in inferences)
    
    def test_infer_never_confirm(self) -> None:
        """Test inferring never confirm preference."""
        inferences = infer_preferences_from_text("Sormadan yap")
        assert any(i[1] == ConfirmWrites.NEVER for i in inferences)
    
    def test_infer_cloud_enabled(self) -> None:
        """Test inferring cloud enabled preference."""
        inferences = infer_preferences_from_text("Gemini kullan kaliteli cevap için")
        assert any(i[1] == CloudModeDefault.CLOUD for i in inferences)
    
    def test_infer_local_mode(self) -> None:
        """Test inferring local mode preference."""
        inferences = infer_preferences_from_text("Yerel model kullan")
        assert any(i[1] == CloudModeDefault.LOCAL for i in inferences)
    
    def test_infer_multiple_preferences(self) -> None:
        """Test inferring multiple preferences."""
        inferences = infer_preferences_from_text("Kısa cevap ver ve onay iste")
        assert len(inferences) >= 2
    
    def test_no_inference_generic_text(self) -> None:
        """Test no inference for generic text."""
        inferences = infer_preferences_from_text("Bugün hava nasıl?")
        assert len(inferences) == 0


# =============================================================================
# Apply Inferences Tests
# =============================================================================

class TestApplyInferences:
    """Tests for apply_inferences function."""
    
    def test_apply_high_confidence(self) -> None:
        """Test applying high confidence inferences."""
        store = PreferenceStore()
        inferences = [("reply_length", ReplyLength.SHORT, 0.9)]
        applied = apply_inferences(store, inferences)
        assert len(applied) == 1
        assert store.preferences.reply_length == ReplyLength.SHORT
    
    def test_skip_low_confidence(self) -> None:
        """Test skipping low confidence inferences."""
        store = PreferenceStore()
        inferences = [("reply_length", ReplyLength.SHORT, 0.5)]
        applied = apply_inferences(store, inferences, min_confidence=0.7)
        assert len(applied) == 0
        assert store.preferences.reply_length == ReplyLength.NORMAL
    
    def test_apply_multiple_inferences(self) -> None:
        """Test applying multiple inferences."""
        store = PreferenceStore()
        inferences = [
            ("reply_length", ReplyLength.SHORT, 0.9),
            ("confirm_writes", ConfirmWrites.ALWAYS, 0.8),
        ]
        applied = apply_inferences(store, inferences)
        assert len(applied) == 2
        assert store.preferences.reply_length == ReplyLength.SHORT
        assert store.preferences.confirm_writes == ConfirmWrites.ALWAYS
    
    def test_apply_cloud_mode(self) -> None:
        """Test applying cloud mode inference."""
        store = PreferenceStore()
        inferences = [("cloud_mode_default", CloudModeDefault.CLOUD, 0.9)]
        applied = apply_inferences(store, inferences)
        assert store.preferences.cloud_mode_default == CloudModeDefault.CLOUD


# =============================================================================
# E2E Integration Tests
# =============================================================================

class TestPreferenceE2E:
    """End-to-end integration tests."""
    
    def test_short_preference_to_config(self) -> None:
        """Test short preference flows to config."""
        # User says "kısa cevap ver"
        inferences = infer_preferences_from_text("Kısa cevap ver")
        
        # Apply to store
        store = PreferenceStore()
        apply_inferences(store, inferences)
        
        # Get config override
        override = BrainLoopConfigOverride.from_preferences(store.preferences)
        
        # Verify max tokens is 50 (short)
        assert override.max_response_tokens == 50
    
    def test_cloud_preference_to_config(self) -> None:
        """Test cloud preference flows to config."""
        # User says "kaliteli cevap ver"
        inferences = infer_preferences_from_text("Kaliteli cevap ver, gemini kullan")
        
        # Apply to store
        store = PreferenceStore()
        apply_inferences(store, inferences)
        
        # Get config override
        override = BrainLoopConfigOverride.from_preferences(store.preferences)
        
        # Verify cloud is enabled
        assert override.enable_cloud_finalizer is True
    
    def test_prompt_block_generation(self) -> None:
        """Test prompt block is properly generated."""
        prefs = UserPreferences(
            reply_length=ReplyLength.SHORT,
            confirm_writes=ConfirmWrites.ALWAYS,
            cloud_mode_default=CloudModeDefault.CLOUD,
        )
        block = prefs.to_prompt_block()
        
        # Verify block structure
        assert "<PREFERENCES>" in block
        assert "</PREFERENCES>" in block
        assert "Kısa" in block
        assert "HER ZAMAN" in block
        assert "cloud" in block
    
    def test_preference_persistence_round_trip(self) -> None:
        """Test preferences can be persisted and restored."""
        # Create and modify
        store1 = PreferenceStore()
        store1.set_short_replies()
        store1.set_cloud_enabled()
        
        # Persist
        data = store1.to_dict()
        
        # Restore
        store2 = PreferenceStore.from_dict(data)
        
        # Verify
        assert store2.preferences.reply_length == ReplyLength.SHORT
        assert store2.preferences.cloud_mode_default == CloudModeDefault.CLOUD
