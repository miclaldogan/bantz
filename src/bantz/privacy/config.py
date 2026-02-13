"""Privacy configuration — persisted at ~/.config/bantz/privacy.json (Issue #299).

Default: local-only mode, no cloud calls.
Cloud features (Gemini, news, web search) require explicit consent.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "PrivacyConfig",
    "SkillPermissions",
    "load_privacy_config",
    "save_privacy_config",
    "DEFAULT_CONFIG_PATH",
]

DEFAULT_CONFIG_DIR = Path(os.getenv("BANTZ_CONFIG_DIR", "~/.config/bantz")).expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "privacy.json"
CURRENT_CONSENT_VERSION = "1.0"


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────


@dataclass
class SkillPermissions:
    """Per-skill cloud permission flags.

    Default: all False (local-only).
    """

    news_web_fetch: bool = False
    gemini_finalize: bool = False
    web_search: bool = False

    def any_enabled(self) -> bool:
        """Return True if any cloud skill is enabled."""
        return self.news_web_fetch or self.gemini_finalize or self.web_search

    def enable_all(self) -> None:
        self.news_web_fetch = True
        self.gemini_finalize = True
        self.web_search = True

    def disable_all(self) -> None:
        self.news_web_fetch = False
        self.gemini_finalize = False
        self.web_search = False


@dataclass
class PrivacyConfig:
    """Privacy configuration persisted on disk.

    Attributes
    ----------
    cloud_mode:
        False = strictly local, True = cloud features allowed (with consent).
    consent_given_at:
        ISO timestamp when consent was given, or None.
    consent_version:
        Version of the consent terms the user agreed to.
    skills:
        Per-skill cloud permission flags.
    data_retention_days:
        How many days to keep local data (logs, metrics, etc.).
    """

    cloud_mode: bool = False
    consent_given_at: Optional[str] = None
    consent_version: str = CURRENT_CONSENT_VERSION
    skills: SkillPermissions = field(default_factory=SkillPermissions)
    data_retention_days: int = 7

    @property
    def is_local_only(self) -> bool:
        """True if cloud mode is off (default, privacy-first)."""
        return not self.cloud_mode

    @property
    def has_consent(self) -> bool:
        """True if user has given consent."""
        return self.consent_given_at is not None and self.cloud_mode

    def is_skill_allowed(self, skill_name: str) -> bool:
        """Check if a specific cloud skill is allowed.

        Returns False if cloud_mode is off OR the specific skill is disabled.
        """
        if not self.cloud_mode:
            return False
        return getattr(self.skills, skill_name, False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (JSON-friendly)."""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrivacyConfig":
        """Deserialize from dictionary."""
        skills_data = data.get("skills", {})
        if isinstance(skills_data, dict):
            skills = SkillPermissions(**{
                k: v for k, v in skills_data.items()
                if k in SkillPermissions.__dataclass_fields__
            })
        else:
            skills = SkillPermissions()

        return cls(
            cloud_mode=bool(data.get("cloud_mode", False)),
            consent_given_at=data.get("consent_given_at"),
            consent_version=str(data.get("consent_version", CURRENT_CONSENT_VERSION)),
            skills=skills,
            data_retention_days=int(data.get("data_retention_days", 7)),
        )


# ─────────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────────


def load_privacy_config(path: Optional[Path] = None) -> PrivacyConfig:
    """Load privacy config from disk.

    If the file does not exist, returns the default (local-only) config.
    On parse error, logs a warning and returns defaults.
    """
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.is_file():
        logger.debug("Privacy config not found at %s — using defaults (local-only)", p)
        return PrivacyConfig()

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cfg = PrivacyConfig.from_dict(data)
        logger.debug("Privacy config loaded from %s (cloud_mode=%s)", p, cfg.cloud_mode)
        return cfg
    except Exception as exc:
        logger.warning("Privacy config parse error at %s: %s — using defaults", p, exc)
        return PrivacyConfig()


def save_privacy_config(config: PrivacyConfig, path: Optional[Path] = None) -> bool:
    """Save privacy config to disk.

    Creates parent directories if needed.
    Returns True on success, False on error.
    """
    p = Path(path) if path else DEFAULT_CONFIG_PATH

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.debug("Privacy config saved to %s", p)
        return True
    except Exception as exc:
        logger.warning("Privacy config save failed at %s: %s", p, exc)
        return False
