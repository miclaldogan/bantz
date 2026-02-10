from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_LEGACY_WARNED: set[str] = set()


def _warn_legacy(legacy: str, new_name: str) -> None:
    if legacy in _LEGACY_WARNED:
        return
    _LEGACY_WARNED.add(legacy)
    logger.warning(
        "[tier-env] legacy env var %s is deprecated; use %s",
        legacy,
        new_name,
    )


def _env_raw(name: str, *legacy: str) -> str:
    raw = str(os.getenv(name, "")).strip()
    if raw:
        return raw
    for legacy_name in legacy:
        legacy_raw = str(os.getenv(legacy_name, "")).strip()
        if legacy_raw:
            _warn_legacy(legacy_name, name)
            return legacy_raw
    return ""


def _env_flag(name: str, *legacy: str, default: bool = False) -> bool:
    raw = _env_raw(name, *legacy).strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def get_tier_mode_enabled() -> bool:
    return _env_flag("BANTZ_TIER_MODE", "BANTZ_TIERED_MODE", default=True)


def get_tier_force() -> str:
    return _env_raw("BANTZ_TIER_FORCE", "BANTZ_LLM_TIER").strip().lower()


def get_tier_force_finalizer() -> str:
    return _env_raw(
        "BANTZ_TIER_FORCE_FINALIZER",
        "BANTZ_FORCE_FINALIZER_TIER",
    ).strip().lower()


def get_tier_debug() -> bool:
    return _env_flag("BANTZ_TIER_DEBUG", "BANTZ_TIERED_DEBUG", default=False)


def get_tier_metrics() -> bool:
    return _env_flag(
        "BANTZ_TIER_METRICS",
        "BANTZ_TIERED_METRICS",
        "BANTZ_LLM_METRICS",
        default=False,
    )