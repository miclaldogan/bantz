"""Policy Engine v2 — Risk Tiers + Param Redact + Presets (Issue #1291).

Replaces the binary (yes/no) confirmation system with a tiered policy:

- **LOW**  — read-only ops, auto-execute (no confirmation)
- **MED**  — write ops, standard confirmation prompt, confirm-once-per-session
- **HIGH** — destructive/dangerous ops, detailed confirmation + param edit + cooldown

Three presets control behaviour:

- **paranoid**  — confirm everything including LOW
- **balanced**  — default: LOW auto, MED confirm, HIGH confirm+edit
- **autopilot** — never confirm (test/demo mode)

Usage::

    from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset

    engine = PolicyEngineV2()
    decision = engine.evaluate(
        tool_name="calendar.delete_event",
        params={"event_id": "abc123", "title": "Meeting"},
        session_id="sess-42",
    )

    if decision.action == "execute":
        execute_tool(...)
    elif decision.action == "confirm":
        show_confirmation(decision.display_params, decision.prompt)
    elif decision.action == "confirm_with_edit":
        show_edit_ui(decision.display_params, decision.editable_fields)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "RiskTier",
    "PolicyPreset",
    "PolicyDecision",
    "PolicyEngineV2",
]


# ── Enums ─────────────────────────────────────────────────────────


class RiskTier(str, Enum):
    """Unified risk classification (replaces ToolRisk + RiskLevel)."""

    LOW = "LOW"  # Read-only — auto-execute
    MED = "MED"  # Write/modify — standard confirmation
    HIGH = "HIGH"  # Delete/send/system — detailed confirmation + edit


class PolicyPreset(str, Enum):
    """User-selectable policy presets."""

    PARANOID = "paranoid"  # Confirm everything (LOW included)
    BALANCED = "balanced"  # Default: LOW auto, MED confirm, HIGH confirm+edit
    AUTOPILOT = "autopilot"  # Never confirm (test/demo)


# ── Decision dataclass ────────────────────────────────────────────


@dataclass
class PolicyDecision:
    """Result of a policy evaluation.

    Attributes:
        action: "execute" | "confirm" | "confirm_with_edit" | "deny"
        tier: The risk tier of the tool.
        prompt: Confirmation prompt text (Turkish).
        display_params: Redacted params safe for display.
        original_params: Unredacted original params.
        editable_fields: List of param keys the user may edit (HIGH only).
        editable: Whether the user can edit params before confirming.
        requires_explicit_confirm: If True, user must type exact word (HIGH).
        cooldown_seconds: Forced delay before confirmation is accepted (HIGH).
        reason: Machine-readable reason for the decision.
    """

    action: Literal["execute", "confirm", "confirm_with_edit", "deny"]
    tier: RiskTier
    prompt: str = ""
    display_params: Dict[str, Any] = field(default_factory=dict)
    original_params: Dict[str, Any] = field(default_factory=dict)
    editable_fields: List[str] = field(default_factory=list)
    editable: bool = False
    requires_explicit_confirm: bool = False
    cooldown_seconds: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "tier": self.tier.value,
            "prompt": self.prompt,
            "display_params": self.display_params,
            "editable_fields": self.editable_fields,
            "editable": self.editable,
            "requires_explicit_confirm": self.requires_explicit_confirm,
            "cooldown_seconds": self.cooldown_seconds,
            "reason": self.reason,
        }


# ── Sensitive field detection ─────────────────────────────────────

# Global sensitive keys — always redacted regardless of tool-specific config.
_GLOBAL_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
    "set-cookie",
    "private_key",
    "client_secret",
})


def redact_value(value: str) -> str:
    """Mask a sensitive string, preserving prefix/suffix hints.

    >>> redact_value("sk-abc123xyz")
    'sk-***xyz'
    >>> redact_value("short")
    '***'
    """
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-3:]


def redact_sensitive(
    params: Dict[str, Any],
    tool_name: str = "",
    extra_fields: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Redact sensitive fields in params.

    Combines:
    - Global sensitive keys (passwords, tokens, etc.)
    - Per-tool redact_fields from config
    - Caller-supplied extra_fields

    Non-sensitive fields are left untouched.
    """
    fields_to_redact = set(_GLOBAL_SENSITIVE_KEYS)
    if extra_fields:
        fields_to_redact |= extra_fields

    redacted: Dict[str, Any] = {}
    for key, val in params.items():
        key_lower = key.lower()
        if key_lower in fields_to_redact:
            redacted[key] = redact_value(str(val)) if isinstance(val, str) else "***"
        elif isinstance(val, dict):
            redacted[key] = redact_sensitive(val, tool_name, extra_fields)
        else:
            redacted[key] = val
    return redacted


# ── Config loader ─────────────────────────────────────────────────

_DEFAULT_PERMISSIONS_YAML = Path(__file__).resolve().parents[3] / "config" / "permissions.yaml"
_DEFAULT_POLICY_JSON = Path(__file__).resolve().parents[3] / "config" / "policy.json"


def _load_risk_map_from_policy_json(
    path: Optional[Path] = None,
) -> Dict[str, RiskTier]:
    """Load tool→RiskTier mapping from config/policy.json → tool_levels."""
    policy_path = path or _DEFAULT_POLICY_JSON
    _RISK_MAP = {
        "safe": RiskTier.LOW,
        "moderate": RiskTier.MED,
        "destructive": RiskTier.HIGH,
    }
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        tool_levels = raw.get("tool_levels", {})
        result: Dict[str, RiskTier] = {}
        for tool, risk_str in tool_levels.items():
            if tool == "__comment":
                continue
            tier = _RISK_MAP.get(str(risk_str).lower())
            if tier:
                result[tool] = tier
        return result
    except Exception as exc:
        logger.warning("policy.json load failed: %s — using empty risk map", exc)
        return {}


def _load_redact_fields(
    path: Optional[Path] = None,
) -> Dict[str, Set[str]]:
    """Load per-tool redact fields from config/permissions.yaml → redact_fields."""
    yaml_path = path or _DEFAULT_PERMISSIONS_YAML
    try:
        import yaml  # type: ignore[import-untyped]
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except ImportError:
        # No PyYAML — try JSON fallback (permissions usually in YAML)
        return {}
    except Exception:
        return {}

    redact_section = raw.get("redact_fields", {})
    if not isinstance(redact_section, dict):
        return {}

    result: Dict[str, Set[str]] = {}
    for tool, fields in redact_section.items():
        if isinstance(fields, list):
            result[tool] = {str(f) for f in fields}
        elif isinstance(fields, str):
            result[tool] = {fields}
    return result


def _load_editable_fields(
    path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Load per-tool editable fields from config/permissions.yaml → editable_fields."""
    yaml_path = path or _DEFAULT_PERMISSIONS_YAML
    try:
        import yaml  # type: ignore[import-untyped]
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (ImportError, Exception):
        return {}

    section = raw.get("editable_fields", {})
    if not isinstance(section, dict):
        return {}

    result: Dict[str, List[str]] = {}
    for tool, fields in section.items():
        if isinstance(fields, list):
            result[tool] = [str(f) for f in fields]
    return result


# ── Session permits (confirm-once-per-session for MED) ────────────


class _SessionPermits:
    """Track which tools a session has already confirmed.

    MED-risk tools confirmed once don't need re-confirmation in the
    same session.  HIGH-risk tools are NEVER remembered.
    """

    def __init__(self) -> None:
        self._permits: Dict[tuple[str, str], float] = {}

    def is_confirmed(self, session_id: str, tool_name: str) -> bool:
        return (session_id, tool_name) in self._permits

    def confirm(self, session_id: str, tool_name: str) -> None:
        self._permits[(session_id, tool_name)] = time.time()

    def revoke(self, session_id: str, tool_name: str) -> None:
        self._permits.pop((session_id, tool_name), None)

    def clear_session(self, session_id: str) -> None:
        keys = [k for k in self._permits if k[0] == session_id]
        for k in keys:
            del self._permits[k]


# ── Policy Engine v2 ─────────────────────────────────────────────


class PolicyEngineV2:
    """Risk-tiered policy engine with presets, redaction, and param editing.

    Thread-safe for read operations. Mutable state (_permits, _preset)
    should be coordinated externally if multi-threaded.
    """

    def __init__(
        self,
        *,
        preset: PolicyPreset = PolicyPreset.BALANCED,
        risk_overrides: Optional[Dict[str, RiskTier]] = None,
        redact_fields: Optional[Dict[str, Set[str]]] = None,
        editable_fields: Optional[Dict[str, List[str]]] = None,
        policy_json_path: Optional[Path] = None,
        permissions_yaml_path: Optional[Path] = None,
    ) -> None:
        # Preset
        env_preset = os.getenv("BANTZ_POLICY_PRESET", "").strip().lower()
        if env_preset in {p.value for p in PolicyPreset}:
            self._preset = PolicyPreset(env_preset)
        else:
            self._preset = preset

        # Risk map: policy.json → tool_levels
        self._risk_map: Dict[str, RiskTier] = _load_risk_map_from_policy_json(
            policy_json_path
        )
        if risk_overrides:
            self._risk_map.update(risk_overrides)

        # Per-tool redact fields from permissions.yaml
        self._redact_fields: Dict[str, Set[str]] = (
            redact_fields
            if redact_fields is not None
            else _load_redact_fields(permissions_yaml_path)
        )

        # Per-tool editable fields (HIGH risk param edit UX)
        self._editable_fields: Dict[str, List[str]] = (
            editable_fields
            if editable_fields is not None
            else _load_editable_fields(permissions_yaml_path)
        )

        # Session permits (MED-risk confirm-once)
        self._permits = _SessionPermits()

        logger.info(
            "[PolicyEngineV2] preset=%s, risk_map=%d tools, redact=%d tools",
            self._preset.value,
            len(self._risk_map),
            len(self._redact_fields),
        )

    # ── Properties ──

    @property
    def preset(self) -> PolicyPreset:
        return self._preset

    @preset.setter
    def preset(self, value: PolicyPreset) -> None:
        self._preset = value
        logger.info("[PolicyEngineV2] Preset changed to %s", value.value)

    # ── Core evaluation ──

    def get_risk_tier(self, tool_name: str) -> RiskTier:
        """Resolve the risk tier for a tool.

        Priority:
        1. Explicit risk_overrides
        2. policy.json → tool_levels
        3. Wildcard match in risk_map (e.g. "system.*" → HIGH)
        4. Default: MED (safe default — requires confirmation)
        """
        # Exact match
        tier = self._risk_map.get(tool_name)
        if tier is not None:
            return tier

        # Wildcard match (e.g. "system.*" → all system tools)
        for pattern, t in self._risk_map.items():
            if "*" in pattern or "?" in pattern:
                if fnmatch(tool_name, pattern):
                    return t

        return RiskTier.MED  # Safe default: confirm before execute

    def evaluate(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        session_id: str = "default",
        preset: Optional[PolicyPreset] = None,
    ) -> PolicyDecision:
        """Evaluate a tool call and return a policy decision.

        Args:
            tool_name: Fully qualified tool name (e.g. "calendar.delete_event")
            params: Tool parameters (will be redacted in display_params)
            session_id: Current session ID for confirm-once tracking
            preset: Override the engine-level preset for this call
        """
        params = params or {}
        effective_preset = preset or self._preset
        tier = self.get_risk_tier(tool_name)

        # ── Autopilot: always execute ──
        if effective_preset == PolicyPreset.AUTOPILOT:
            return PolicyDecision(
                action="execute",
                tier=tier,
                reason="AUTOPILOT_ALLOW",
                original_params=params,
                display_params=self._redact(params, tool_name),
            )

        # ── Paranoid: confirm everything ──
        if effective_preset == PolicyPreset.PARANOID:
            if tier == RiskTier.HIGH:
                return self._high_decision(tool_name, params, session_id)
            # LOW and MED both require confirmation in paranoid
            return PolicyDecision(
                action="confirm",
                tier=tier,
                prompt=self._build_prompt(tool_name, tier, params),
                display_params=self._redact(params, tool_name),
                original_params=params,
                editable=False,
                reason="PARANOID_CONFIRM",
            )

        # ── Balanced (default) ──

        if tier == RiskTier.LOW:
            return PolicyDecision(
                action="execute",
                tier=tier,
                reason="LOW_AUTO_EXECUTE",
                original_params=params,
                display_params=self._redact(params, tool_name),
            )

        if tier == RiskTier.MED:
            # Confirm-once-per-session
            if self._permits.is_confirmed(session_id, tool_name):
                return PolicyDecision(
                    action="execute",
                    tier=tier,
                    reason="MED_SESSION_CONFIRMED",
                    original_params=params,
                    display_params=self._redact(params, tool_name),
                )
            return PolicyDecision(
                action="confirm",
                tier=tier,
                prompt=self._build_prompt(tool_name, tier, params),
                display_params=self._redact(params, tool_name),
                original_params=params,
                editable=False,
                reason="MED_REQUIRE_CONFIRMATION",
            )

        # HIGH
        return self._high_decision(tool_name, params, session_id)

    def confirm(
        self,
        tool_name: str,
        session_id: str,
        tier: RiskTier,
        *,
        edited_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record that a user confirmed a tool.

        For MED risk, remembers the confirmation for the session.
        For HIGH risk, each invocation requires fresh confirmation.

        Returns the effective params (edited or original).
        """
        if tier == RiskTier.MED:
            self._permits.confirm(session_id, tool_name)

        return edited_params or {}

    def deny(self, tool_name: str, session_id: str) -> None:
        """Record that a user denied a tool."""
        # Nothing to persist — just logging
        logger.info(
            "[PolicyEngineV2] User denied %s (session=%s)", tool_name, session_id
        )

    def clear_session(self, session_id: str) -> None:
        """Clear all session permits (e.g. on logout)."""
        self._permits.clear_session(session_id)

    # ── Redaction ──

    def get_redact_fields(self, tool_name: str) -> Set[str]:
        """Get the set of fields to redact for a tool.

        Combines global sensitive keys + per-tool config.
        """
        extra = set(_GLOBAL_SENSITIVE_KEYS)
        tool_specific = self._redact_fields.get(tool_name, set())
        extra |= tool_specific

        # Wildcard match
        for pattern, fields in self._redact_fields.items():
            if ("*" in pattern or "?" in pattern) and fnmatch(tool_name, pattern):
                extra |= fields

        return extra

    def _redact(self, params: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
        """Redact sensitive fields in params for display."""
        extra = self.get_redact_fields(tool_name)
        return redact_sensitive(params, tool_name, extra)

    # ── Internal helpers ──

    def _high_decision(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str,
    ) -> PolicyDecision:
        """Build a HIGH-risk policy decision with edit capability."""
        editable = self._editable_fields.get(tool_name, [])
        return PolicyDecision(
            action="confirm_with_edit",
            tier=RiskTier.HIGH,
            prompt=self._build_prompt(tool_name, RiskTier.HIGH, params),
            display_params=self._redact(params, tool_name),
            original_params=params,
            editable_fields=editable,
            editable=bool(editable),
            requires_explicit_confirm=True,
            cooldown_seconds=3,
            reason="HIGH_REQUIRE_CONFIRMATION_WITH_EDIT",
        )

    def _build_prompt(
        self,
        tool_name: str,
        tier: RiskTier,
        params: Dict[str, Any],
    ) -> str:
        """Build a Turkish confirmation prompt based on tier."""
        redacted = self._redact(params, tool_name)

        if tier == RiskTier.HIGH:
            param_lines = "\n".join(
                f"  {k}: {v}" for k, v in redacted.items()
            )
            editable_note = ""
            editable = self._editable_fields.get(tool_name, [])
            if editable:
                editable_note = (
                    "\n\nDüzenlemek ister misiniz? (evet/hayır/iptal)"
                )
            return (
                f"⚠️ YÜKSEK RİSK — {tool_name}\n\n"
                f"Parametreler:\n{param_lines}\n"
                f"{editable_note}\n"
                f"Bu işlem geri alınamaz. Onaylıyor musunuz?"
            )

        if tier == RiskTier.MED:
            short_params = ", ".join(
                f"{k}={v}" for k, v in list(redacted.items())[:3]
            )
            return (
                f"📝 {tool_name} çalıştırılsın mı?\n"
                f"Parametreler: {short_params}\n"
                f"(evet/hayır)"
            )

        # LOW (only in paranoid mode)
        return f"{tool_name} çalıştırılsın mı? (evet/hayır)"

    # ── Bridge: backward compat with ToolRisk / RiskLevel ──

    @staticmethod
    def tier_from_tool_risk(tool_risk_value: str) -> RiskTier:
        """Convert old ToolRisk value to RiskTier.

        'safe' → LOW, 'moderate' → MED, 'destructive' → HIGH
        """
        _MAP = {"safe": RiskTier.LOW, "moderate": RiskTier.MED, "destructive": RiskTier.HIGH}
        return _MAP.get(str(tool_risk_value).lower(), RiskTier.MED)

    @staticmethod
    def tier_to_tool_risk_value(tier: RiskTier) -> str:
        """Convert RiskTier to old ToolRisk-style string.

        LOW → 'safe', MED → 'moderate', HIGH → 'destructive'
        """
        _MAP = {RiskTier.LOW: "safe", RiskTier.MED: "moderate", RiskTier.HIGH: "destructive"}
        return _MAP.get(tier, "moderate")

    @staticmethod
    def tier_to_risk_level(tier: RiskTier) -> str:
        """Convert RiskTier to RiskLevel literal ('LOW'/'MED'/'HIGH')."""
        return tier.value

    def to_dict(self) -> Dict[str, Any]:
        """Serialise engine state for diagnostics."""
        return {
            "preset": self._preset.value,
            "risk_map_size": len(self._risk_map),
            "redact_fields_count": len(self._redact_fields),
            "editable_fields_count": len(self._editable_fields),
        }
