"""User Preferences for Router and Finalizer Behavior.

Issue #243: Use PROFILE preferences to steer router + finalizer.

This module provides:
- Preference schema (reply_length, confirm_writes, cloud_mode_default)
- Preference injection into router prompts
- BrainLoop config override based on preferences

Preferences affect:
- reply_length: short/normal/long -> controls max tokens
- confirm_writes: always/ask/never -> write flow confirmation
- cloud_mode_default: local/cloud -> finalizer gating
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ReplyLength(Enum):
    """User's preferred reply length."""
    SHORT = "short"      # Kısa ve öz cevaplar
    NORMAL = "normal"    # Normal uzunlukta cevaplar
    LONG = "long"        # Detaylı, uzun cevaplar
    
    @property
    def max_tokens(self) -> int:
        """Get max tokens for this length preference."""
        token_limits = {
            ReplyLength.SHORT: 50,
            ReplyLength.NORMAL: 150,
            ReplyLength.LONG: 300,
        }
        return token_limits.get(self, 150)
    
    @property
    def description_tr(self) -> str:
        """Turkish description for prompts."""
        descriptions = {
            ReplyLength.SHORT: "Kısa ve öz cevaplar ver.",
            ReplyLength.NORMAL: "Normal uzunlukta cevaplar ver.",
            ReplyLength.LONG: "Detaylı ve kapsamlı cevaplar ver.",
        }
        return descriptions.get(self, "Normal uzunlukta cevaplar ver.")
    
    @classmethod
    def from_str(cls, value: str) -> ReplyLength:
        """Parse from string."""
        value = value.strip().lower()
        for member in cls:
            if member.value == value:
                return member
        return cls.NORMAL


class ConfirmWrites(Enum):
    """User's preference for write operation confirmations."""
    ALWAYS = "always"    # Her zaman onay iste
    ASK = "ask"          # Belirsizse sor
    NEVER = "never"      # Hiç onay isteme
    
    @property
    def requires_confirmation(self) -> bool:
        """Check if confirmation is always required."""
        return self == ConfirmWrites.ALWAYS
    
    @property
    def description_tr(self) -> str:
        """Turkish description for prompts."""
        descriptions = {
            ConfirmWrites.ALWAYS: "Yazma işlemlerinden önce HER ZAMAN kullanıcıdan onay al.",
            ConfirmWrites.ASK: "Belirsiz durumlarda onay iste.",
            ConfirmWrites.NEVER: "Onay istemeden işlemleri gerçekleştir.",
        }
        return descriptions.get(self, "Belirsiz durumlarda onay iste.")
    
    @classmethod
    def from_str(cls, value: str) -> ConfirmWrites:
        """Parse from string."""
        value = value.strip().lower()
        for member in cls:
            if member.value == value:
                return member
        return cls.ASK


class CloudModeDefault(Enum):
    """User's default cloud mode preference."""
    LOCAL = "local"      # Varsayılan olarak yerel model
    CLOUD = "cloud"      # Varsayılan olarak cloud (Gemini)
    
    @property
    def is_cloud_enabled(self) -> bool:
        """Check if cloud is enabled by default."""
        return self == CloudModeDefault.CLOUD
    
    @property
    def description_tr(self) -> str:
        """Turkish description for prompts."""
        descriptions = {
            CloudModeDefault.LOCAL: "Yerel modeli kullan, cloud'a gönderme.",
            CloudModeDefault.CLOUD: "Kaliteli cevap için cloud kullan.",
        }
        return descriptions.get(self, "Yerel modeli kullan.")
    
    @classmethod
    def from_str(cls, value: str) -> CloudModeDefault:
        """Parse from string."""
        value = value.strip().lower()
        for member in cls:
            if member.value == value:
                return member
        return cls.LOCAL


@dataclass(frozen=True)
class UserPreferences:
    """User preferences container.
    
    Stores user preferences that affect router and finalizer behavior.
    """
    reply_length: ReplyLength = ReplyLength.NORMAL
    confirm_writes: ConfirmWrites = ConfirmWrites.ASK
    cloud_mode_default: CloudModeDefault = CloudModeDefault.LOCAL
    
    # Additional preferences
    language: str = "tr"
    timezone: str = "Europe/Istanbul"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "reply_length": self.reply_length.value,
            "confirm_writes": self.confirm_writes.value,
            "cloud_mode_default": self.cloud_mode_default.value,
            "language": self.language,
            "timezone": self.timezone,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPreferences:
        """Create from dictionary."""
        return cls(
            reply_length=ReplyLength.from_str(data.get("reply_length", "normal")),
            confirm_writes=ConfirmWrites.from_str(data.get("confirm_writes", "ask")),
            cloud_mode_default=CloudModeDefault.from_str(data.get("cloud_mode_default", "local")),
            language=data.get("language", "tr"),
            timezone=data.get("timezone", "Europe/Istanbul"),
        )
    
    def to_prompt_block(self) -> str:
        """Generate preference block for router prompt injection.
        
        Returns:
            Formatted preference block for system prompt.
        """
        lines = [
            "<PREFERENCES>",
            f"- Cevap uzunluğu: {self.reply_length.description_tr}",
            f"- Yazma onayı: {self.confirm_writes.description_tr}",
            f"- Cloud modu: {self.cloud_mode_default.description_tr}",
            f"- Dil: {self.language}",
            "</PREFERENCES>",
        ]
        return "\n".join(lines)
    
    def get_max_tokens(self) -> int:
        """Get max tokens based on reply length preference."""
        return self.reply_length.max_tokens
    
    def should_confirm_write(self, is_ambiguous: bool = False) -> bool:
        """Determine if write operation should be confirmed.
        
        Args:
            is_ambiguous: Whether the operation is ambiguous.
        
        Returns:
            True if confirmation should be requested.
        """
        if self.confirm_writes == ConfirmWrites.ALWAYS:
            return True
        elif self.confirm_writes == ConfirmWrites.NEVER:
            return False
        else:
            return is_ambiguous
    
    def should_use_cloud(self, quality_requested: bool = False) -> bool:
        """Determine if cloud should be used.
        
        Args:
            quality_requested: Whether quality tier is explicitly requested.
        
        Returns:
            True if cloud should be used.
        """
        if quality_requested:
            return True
        return self.cloud_mode_default.is_cloud_enabled


# =============================================================================
# Environment-based defaults
# =============================================================================

def _env_str(name: str, default: str = "") -> str:
    """Get string from environment."""
    return os.getenv(name, default).strip()


def get_default_preferences() -> UserPreferences:
    """Get default preferences from environment.
    
    Environment variables:
    - BANTZ_REPLY_LENGTH: short/normal/long
    - BANTZ_CONFIRM_WRITES: always/ask/never
    - BANTZ_CLOUD_MODE: local/cloud
    - BANTZ_LANGUAGE: tr/en
    - BANTZ_TIMEZONE: Europe/Istanbul
    """
    return UserPreferences(
        reply_length=ReplyLength.from_str(_env_str("BANTZ_REPLY_LENGTH", "normal")),
        confirm_writes=ConfirmWrites.from_str(_env_str("BANTZ_CONFIRM_WRITES", "ask")),
        cloud_mode_default=CloudModeDefault.from_str(_env_str("BANTZ_CLOUD_MODE", "local")),
        language=_env_str("BANTZ_LANGUAGE", "tr"),
        timezone=_env_str("BANTZ_TIMEZONE", "Europe/Istanbul"),
    )


# =============================================================================
# Preference Store
# =============================================================================

@dataclass
class PreferenceChange:
    """Record of a preference change."""
    key: str
    old_value: Any
    new_value: Any
    source: str  # "user_stated", "inferred", "default"
    confidence: float = 1.0


class PreferenceStore:
    """Store for user preferences with change tracking.
    
    Supports:
    - Get/set individual preferences
    - Track changes for learning
    - Persist to file
    """
    
    def __init__(self, preferences: Optional[UserPreferences] = None):
        """Initialize preference store.
        
        Args:
            preferences: Initial preferences (uses defaults if None).
        """
        self._preferences = preferences or get_default_preferences()
        self._changes: list[PreferenceChange] = []
    
    @property
    def preferences(self) -> UserPreferences:
        """Get current preferences."""
        return self._preferences
    
    @property
    def changes(self) -> list[PreferenceChange]:
        """Get change history."""
        return list(self._changes)
    
    def update(
        self,
        reply_length: Optional[ReplyLength] = None,
        confirm_writes: Optional[ConfirmWrites] = None,
        cloud_mode_default: Optional[CloudModeDefault] = None,
        language: Optional[str] = None,
        timezone: Optional[str] = None,
        source: str = "user_stated",
    ) -> UserPreferences:
        """Update preferences.
        
        Args:
            reply_length: New reply length preference.
            confirm_writes: New confirm writes preference.
            cloud_mode_default: New cloud mode preference.
            language: New language.
            timezone: New timezone.
            source: Source of the change.
        
        Returns:
            Updated UserPreferences.
        """
        old = self._preferences
        
        new_prefs = UserPreferences(
            reply_length=reply_length or old.reply_length,
            confirm_writes=confirm_writes or old.confirm_writes,
            cloud_mode_default=cloud_mode_default or old.cloud_mode_default,
            language=language or old.language,
            timezone=timezone or old.timezone,
        )
        
        # Track changes
        if reply_length and reply_length != old.reply_length:
            self._changes.append(PreferenceChange(
                key="reply_length",
                old_value=old.reply_length.value,
                new_value=reply_length.value,
                source=source,
            ))
        
        if confirm_writes and confirm_writes != old.confirm_writes:
            self._changes.append(PreferenceChange(
                key="confirm_writes",
                old_value=old.confirm_writes.value,
                new_value=confirm_writes.value,
                source=source,
            ))
        
        if cloud_mode_default and cloud_mode_default != old.cloud_mode_default:
            self._changes.append(PreferenceChange(
                key="cloud_mode_default",
                old_value=old.cloud_mode_default.value,
                new_value=cloud_mode_default.value,
                source=source,
            ))
        
        self._preferences = new_prefs
        return new_prefs
    
    def set_short_replies(self, source: str = "user_stated") -> UserPreferences:
        """Convenience: Set reply length to short."""
        return self.update(reply_length=ReplyLength.SHORT, source=source)
    
    def set_always_confirm(self, source: str = "user_stated") -> UserPreferences:
        """Convenience: Set confirm writes to always."""
        return self.update(confirm_writes=ConfirmWrites.ALWAYS, source=source)
    
    def set_cloud_enabled(self, source: str = "user_stated") -> UserPreferences:
        """Convenience: Enable cloud by default."""
        return self.update(cloud_mode_default=CloudModeDefault.CLOUD, source=source)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "preferences": self._preferences.to_dict(),
            "changes": [
                {
                    "key": c.key,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "source": c.source,
                    "confidence": c.confidence,
                }
                for c in self._changes
            ],
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreferenceStore:
        """Create from dictionary."""
        prefs = UserPreferences.from_dict(data.get("preferences", {}))
        store = cls(prefs)
        
        for change_data in data.get("changes", []):
            store._changes.append(PreferenceChange(
                key=change_data["key"],
                old_value=change_data["old_value"],
                new_value=change_data["new_value"],
                source=change_data.get("source", "unknown"),
                confidence=change_data.get("confidence", 1.0),
            ))
        
        return store


# =============================================================================
# Router Config Override
# =============================================================================

@dataclass
class RouterConfigOverride:
    """Configuration overrides for router based on preferences.
    
    Used to modify router behavior at runtime.
    """
    max_tokens: int = 150
    require_confirmation: bool = False
    cloud_enabled: bool = False
    
    @classmethod
    def from_preferences(cls, prefs: UserPreferences) -> RouterConfigOverride:
        """Create config override from user preferences."""
        return cls(
            max_tokens=prefs.get_max_tokens(),
            require_confirmation=prefs.confirm_writes == ConfirmWrites.ALWAYS,
            cloud_enabled=prefs.cloud_mode_default.is_cloud_enabled,
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_tokens": self.max_tokens,
            "require_confirmation": self.require_confirmation,
            "cloud_enabled": self.cloud_enabled,
        }


# =============================================================================
# BrainLoop Config Override
# =============================================================================

@dataclass
class BrainLoopConfigOverride:
    """Configuration overrides for BrainLoop based on preferences.
    
    Passed to BrainLoop to modify behavior.
    """
    max_response_tokens: int = 150
    always_confirm_writes: bool = False
    enable_cloud_finalizer: bool = False
    
    @classmethod
    def from_preferences(cls, prefs: UserPreferences) -> BrainLoopConfigOverride:
        """Create BrainLoop config from user preferences."""
        return cls(
            max_response_tokens=prefs.get_max_tokens(),
            always_confirm_writes=prefs.confirm_writes == ConfirmWrites.ALWAYS,
            enable_cloud_finalizer=prefs.cloud_mode_default.is_cloud_enabled,
        )
    
    def apply_to_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Apply overrides to a config dictionary.
        
        Args:
            config: Original config dict.
        
        Returns:
            Modified config dict.
        """
        result = dict(config)
        result["max_response_tokens"] = self.max_response_tokens
        result["always_confirm_writes"] = self.always_confirm_writes
        result["enable_cloud_finalizer"] = self.enable_cloud_finalizer
        return result


# =============================================================================
# Inference from user text
# =============================================================================

def infer_preferences_from_text(text: str) -> list[tuple[str, Any, float]]:
    """Infer preference changes from user text.
    
    Args:
        text: User's message.
    
    Returns:
        List of (preference_key, value, confidence) tuples.
    """
    text_lower = text.lower()
    inferences: list[tuple[str, Any, float]] = []
    
    # Reply length inference
    short_phrases = ["kısa cevap", "kısa ver", "öz cevap", "kısa tut"]
    long_phrases = ["detaylı cevap", "uzun cevap", "detaylı anlat", "kapsamlı"]
    
    for phrase in short_phrases:
        if phrase in text_lower:
            inferences.append(("reply_length", ReplyLength.SHORT, 0.9))
            break
    
    for phrase in long_phrases:
        if phrase in text_lower:
            inferences.append(("reply_length", ReplyLength.LONG, 0.9))
            break
    
    # Confirm writes inference
    confirm_phrases = ["onay iste", "onay al", "sormadan yapma", "her zaman sor"]
    no_confirm_phrases = ["onay isteme", "sormadan yap", "direkt yap"]
    
    for phrase in confirm_phrases:
        if phrase in text_lower:
            inferences.append(("confirm_writes", ConfirmWrites.ALWAYS, 0.9))
            break
    
    for phrase in no_confirm_phrases:
        if phrase in text_lower:
            inferences.append(("confirm_writes", ConfirmWrites.NEVER, 0.8))
            break
    
    # Cloud mode inference
    cloud_phrases = ["kaliteli cevap", "gemini kullan", "cloud aç"]
    local_phrases = ["yerel kullan", "cloud kapalı", "yerel model"]
    
    for phrase in cloud_phrases:
        if phrase in text_lower:
            inferences.append(("cloud_mode_default", CloudModeDefault.CLOUD, 0.9))
            break
    
    for phrase in local_phrases:
        if phrase in text_lower:
            inferences.append(("cloud_mode_default", CloudModeDefault.LOCAL, 0.9))
            break
    
    return inferences


def apply_inferences(
    store: PreferenceStore,
    inferences: list[tuple[str, Any, float]],
    min_confidence: float = 0.7,
) -> list[PreferenceChange]:
    """Apply inferred preferences to store.
    
    Args:
        store: Preference store to update.
        inferences: List of (key, value, confidence) tuples.
        min_confidence: Minimum confidence to apply.
    
    Returns:
        List of applied changes.
    """
    applied: list[PreferenceChange] = []
    
    for key, value, confidence in inferences:
        if confidence < min_confidence:
            continue
        
        if key == "reply_length" and isinstance(value, ReplyLength):
            store.update(reply_length=value, source="inferred")
            applied.append(PreferenceChange(key, None, value.value, "inferred", confidence))
        
        elif key == "confirm_writes" and isinstance(value, ConfirmWrites):
            store.update(confirm_writes=value, source="inferred")
            applied.append(PreferenceChange(key, None, value.value, "inferred", confidence))
        
        elif key == "cloud_mode_default" and isinstance(value, CloudModeDefault):
            store.update(cloud_mode_default=value, source="inferred")
            applied.append(PreferenceChange(key, None, value.value, "inferred", confidence))
    
    return applied
