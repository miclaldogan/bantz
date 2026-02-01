from __future__ import annotations

import os
from dataclasses import dataclass

from bantz.security.masking import get_default_masker
from bantz.brain.memory_lite import PIIFilter


@dataclass(frozen=True)
class CloudPrivacyConfig:
    mode: str  # "local" | "cloud"
    redact: bool
    max_chars: int


def _env_str(*names: str, default: str = "") -> str:
    for name in names:
        v = str(os.getenv(name, "")).strip()
        if v:
            return v
    return default


def _env_flag(*names: str, default: bool = False) -> bool:
    raw = _env_str(*names, default="").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def _env_int(*names: str, default: int) -> int:
    raw = _env_str(*names, default="").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def get_cloud_privacy_config() -> CloudPrivacyConfig:
    """Cloud privacy gate.

    Two modes:
      - local: never call cloud providers
      - cloud: cloud calls allowed (still redact/minimize)

    Env:
      - BANTZ_CLOUD_MODE / CLOUD_MODE: local|cloud|0|1
      - BANTZ_LOCAL_ONLY=1 (forces local)
      - BANTZ_CLOUD_REDACT=1 (default true)
      - BANTZ_CLOUD_MAX_CHARS=12000
    """
    if _env_flag("BANTZ_LOCAL_ONLY", default=False):
        mode = "local"
    else:
        raw = _env_str("BANTZ_CLOUD_MODE", "CLOUD_MODE", default="local").lower()
        if raw in {"1", "true", "yes", "y", "on", "cloud", "cloud-quality"}:
            mode = "cloud"
        else:
            mode = "local"

    redact = _env_flag("BANTZ_CLOUD_REDACT", default=True)
    max_chars = _env_int("BANTZ_CLOUD_MAX_CHARS", default=12000)
    return CloudPrivacyConfig(mode=mode, redact=redact, max_chars=max_chars)


def redact_for_cloud(text: str) -> str:
    """Redact obvious PII/secrets from free-form text.

    Uses:
      - PIIFilter (email/phone/url/etc)
      - DataMasker (tokens/keys/password patterns)

    Note: This is best-effort. The caller should still minimize payload.
    """
    cfg = get_cloud_privacy_config()
    if not cfg.redact:
        return text

    t = str(text or "")
    t = PIIFilter.filter(t, enabled=True)
    t = get_default_masker().mask(t)
    return t


def minimize_for_cloud(text: str) -> str:
    """Minimize outgoing text size (best-effort).

    Env: BANTZ_CLOUD_MAX_CHARS
    """
    cfg = get_cloud_privacy_config()
    t = str(text or "")
    if cfg.max_chars <= 0:
        return t
    if len(t) <= cfg.max_chars:
        return t
    head = t[: cfg.max_chars]
    return head + "\n\n[TRUNCATED_FOR_CLOUD]"