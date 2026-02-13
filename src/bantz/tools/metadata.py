"""Tool Risk Classification & Metadata (Issue #160, #424).

Single source of truth: ``config/policy.json`` → ``tool_levels`` section.
This module loads risk levels from the JSON file at import time and falls
back to hardcoded defaults if the file is missing or malformed.

Risk Levels:
- SAFE: Read-only operations, harmless queries (web.search, calendar.list_events)
- MODERATE: State changes with low impact (calendar.create_event, notifications)
- DESTRUCTIVE: Dangerous operations requiring confirmation (delete, file operations, payments)

Issue #424 additions:
- ``load_policy_json()`` reads tool_levels / always_confirm_tools / undefined_tool_policy
- ``UNDEFINED_TOOL_POLICY`` controls behaviour for tools not listed in policy.json
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Confirmation timeout in seconds (Issue #663)
CONFIRMATION_TIMEOUT_SECONDS = 30


class ToolRisk(str, Enum):
    """Risk classification for tools."""
    
    SAFE = "safe"  # Read-only, no side effects
    MODERATE = "moderate"  # State changes, reversible
    DESTRUCTIVE = "destructive"  # Dangerous, requires confirmation


# ---------------------------------------------------------------------------
# Hardcoded fallback registry (used when policy.json is absent)
# ---------------------------------------------------------------------------

_FALLBACK_TOOL_REGISTRY: dict[str, ToolRisk] = {
    # SAFE
    "web.search": ToolRisk.SAFE,
    "web.open": ToolRisk.SAFE,
    "calendar.list_events": ToolRisk.SAFE,
    "calendar.find_event": ToolRisk.SAFE,
    "calendar.get_event": ToolRisk.SAFE,
    "gmail.list_messages": ToolRisk.SAFE,
    "gmail.unread_count": ToolRisk.SAFE,
    "gmail.get_message": ToolRisk.SAFE,
    "gmail.query_from_nl": ToolRisk.SAFE,
    "gmail.smart_search": ToolRisk.SAFE,
    "gmail.search_template_upsert": ToolRisk.SAFE,
    "gmail.search_template_get": ToolRisk.SAFE,
    "gmail.search_template_list": ToolRisk.SAFE,
    "gmail.search_template_delete": ToolRisk.MODERATE,
    "gmail.list_labels": ToolRisk.SAFE,
    "gmail.add_label": ToolRisk.SAFE,
    "gmail.remove_label": ToolRisk.SAFE,
    "gmail.mark_read": ToolRisk.SAFE,
    "gmail.mark_unread": ToolRisk.SAFE,
    "gmail.create_draft": ToolRisk.SAFE,
    "gmail.list_drafts": ToolRisk.SAFE,
    "gmail.update_draft": ToolRisk.SAFE,
    "gmail.delete_draft": ToolRisk.MODERATE,
    "contacts.upsert": ToolRisk.SAFE,
    "contacts.resolve": ToolRisk.SAFE,
    "contacts.list": ToolRisk.SAFE,
    "contacts.delete": ToolRisk.DESTRUCTIVE,
    "time.now": ToolRisk.SAFE,
    "time.date": ToolRisk.SAFE,
    "weather.current": ToolRisk.SAFE,
    "weather.forecast": ToolRisk.SAFE,
    "system.status": ToolRisk.SAFE,
    "system.screenshot": ToolRisk.SAFE,
    "calendar.find_free_slots": ToolRisk.SAFE,
    "file.read": ToolRisk.SAFE,
    "file.list": ToolRisk.SAFE,
    "vision.analyze": ToolRisk.SAFE,
    "vision.ocr": ToolRisk.SAFE,
    "vision.screenshot": ToolRisk.SAFE,
    # MODERATE
    "gmail.download_attachment": ToolRisk.MODERATE,
    "gmail.archive": ToolRisk.MODERATE,
    "gmail.batch_modify": ToolRisk.MODERATE,
    "gmail.send": ToolRisk.MODERATE,
    "gmail.send_to_contact": ToolRisk.MODERATE,
    "gmail.send_draft": ToolRisk.MODERATE,
    "gmail.generate_reply": ToolRisk.MODERATE,
    "calendar.create_event": ToolRisk.MODERATE,
    "calendar.update_event": ToolRisk.MODERATE,
    "notification.send": ToolRisk.MODERATE,
    "clipboard.set": ToolRisk.MODERATE,
    "clipboard.get": ToolRisk.MODERATE,
    "file.write": ToolRisk.MODERATE,
    "browser.open": ToolRisk.MODERATE,
    "browser.navigate": ToolRisk.MODERATE,
    "app.open": ToolRisk.MODERATE,
    "app.focus": ToolRisk.MODERATE,
    "email.send": ToolRisk.MODERATE,
    "notes.create": ToolRisk.MODERATE,
    # DESTRUCTIVE
    "calendar.delete_event": ToolRisk.DESTRUCTIVE,
    "file.delete": ToolRisk.DESTRUCTIVE,
    "file.move": ToolRisk.DESTRUCTIVE,
    "browser.submit_form": ToolRisk.DESTRUCTIVE,
    "browser.click_button": ToolRisk.DESTRUCTIVE,
    "payment.submit": ToolRisk.DESTRUCTIVE,
    "payment.confirm": ToolRisk.DESTRUCTIVE,
    "system.shutdown": ToolRisk.DESTRUCTIVE,
    "system.restart": ToolRisk.DESTRUCTIVE,
    "system.execute_command": ToolRisk.DESTRUCTIVE,
    "system.sudo": ToolRisk.DESTRUCTIVE,
    "app.close": ToolRisk.DESTRUCTIVE,
    "app.kill": ToolRisk.DESTRUCTIVE,
    "email.delete": ToolRisk.DESTRUCTIVE,
    "database.delete": ToolRisk.DESTRUCTIVE,
    "database.update": ToolRisk.DESTRUCTIVE,
}

_FALLBACK_ALWAYS_CONFIRM: set[str] = {
    "calendar.create_event",
    "calendar.update_event",
    "gmail.send",
    "gmail.send_draft",
    "gmail.send_to_contact",
    "gmail.download_attachment",
    "gmail.generate_reply",
}


# ---------------------------------------------------------------------------
# Policy JSON loader (Issue #424)
# ---------------------------------------------------------------------------

_RISK_NAME_MAP = {"safe": ToolRisk.SAFE, "moderate": ToolRisk.MODERATE, "destructive": ToolRisk.DESTRUCTIVE}

# Default policy.json path (relative to project root)
_DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "policy.json"


def load_policy_json(
    path: Optional[Path] = None,
) -> tuple[dict[str, ToolRisk], set[str], str]:
    """Load tool_levels, always_confirm_tools, and undefined_tool_policy from policy.json.

    Returns:
        (tool_registry, always_confirm_set, undefined_policy)
        - tool_registry: mapping of tool name → ToolRisk
        - always_confirm_set: set of tool names that always need confirmation
        - undefined_policy: "deny" | "moderate" — behaviour for tools not in tool_levels

    Falls back to hardcoded defaults on any error.
    """
    policy_path = path or _DEFAULT_POLICY_PATH

    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.warning("policy.json load failed (%s), using hardcoded fallback", exc)
        return dict(_FALLBACK_TOOL_REGISTRY), set(_FALLBACK_ALWAYS_CONFIRM), "deny"

    # tool_levels → TOOL_REGISTRY
    tool_levels = raw.get("tool_levels")
    if not isinstance(tool_levels, dict):
        logger.warning("policy.json missing tool_levels, using hardcoded fallback")
        return dict(_FALLBACK_TOOL_REGISTRY), set(_FALLBACK_ALWAYS_CONFIRM), "deny"

    registry: dict[str, ToolRisk] = {}
    for tool_name, risk_str in tool_levels.items():
        if tool_name == "__comment":
            continue
        risk_enum = _RISK_NAME_MAP.get(str(risk_str).lower())
        if risk_enum is None:
            logger.warning("policy.json: unknown risk '%s' for tool '%s', skipping", risk_str, tool_name)
            continue
        registry[tool_name] = risk_enum

    # always_confirm_tools
    raw_confirm = raw.get("always_confirm_tools")
    if isinstance(raw_confirm, list):
        confirm_set = {str(t) for t in raw_confirm}
    else:
        confirm_set = set(_FALLBACK_ALWAYS_CONFIRM)

    # undefined_tool_policy
    undef = str(raw.get("undefined_tool_policy", "deny")).lower()
    if undef not in ("deny", "moderate"):
        undef = "deny"

    logger.info(
        "policy.json loaded: %d tool_levels, %d always_confirm, undefined=%s",
        len(registry), len(confirm_set), undef,
    )
    return registry, confirm_set, undef


# ---------------------------------------------------------------------------
# Module-level globals (populated from policy.json at import time)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolRisk]
ALWAYS_CONFIRM_TOOLS: set[str]
UNDEFINED_TOOL_POLICY: str  # "deny" or "moderate"

TOOL_REGISTRY, ALWAYS_CONFIRM_TOOLS, UNDEFINED_TOOL_POLICY = load_policy_json()


def reload_policy(path: Optional[Path] = None) -> None:
    """Re-read policy.json and refresh the module-level globals.

    Useful after config changes or in tests.
    """
    global TOOL_REGISTRY, ALWAYS_CONFIRM_TOOLS, UNDEFINED_TOOL_POLICY  # noqa: PLW0603
    TOOL_REGISTRY, ALWAYS_CONFIRM_TOOLS, UNDEFINED_TOOL_POLICY = load_policy_json(path)


def get_tool_risk(tool_name: str, default: Optional[ToolRisk] = None) -> ToolRisk:
    """Get risk level for a tool.

    If the tool is not in the registry the ``UNDEFINED_TOOL_POLICY`` from
    policy.json decides:
    - ``"deny"``     → treat as DESTRUCTIVE (requires confirmation, Issue #424)
    - ``"moderate"`` → treat as MODERATE (legacy behaviour)

    A caller-supplied *default* overrides the policy when given explicitly.
    
    Args:
        tool_name: Name of the tool (e.g., "calendar.delete_event")
        default: Explicit default risk level (overrides undefined_tool_policy)
    
    Returns:
        ToolRisk enum value
    """
    risk = TOOL_REGISTRY.get(tool_name)
    if risk is not None:
        return risk

    # Caller override
    if default is not None:
        return default

    # Policy-driven default for undefined tools (Issue #424)
    if UNDEFINED_TOOL_POLICY == "deny":
        return ToolRisk.DESTRUCTIVE
    return ToolRisk.MODERATE


def is_destructive(tool_name: str) -> bool:
    """Check if tool is destructive and requires confirmation.
    
    Args:
        tool_name: Name of the tool
    
    Returns:
        True if tool is DESTRUCTIVE, False otherwise
    
    Examples:
        >>> is_destructive("calendar.delete_event")
        True
        >>> is_destructive("web.search")
        False
    """
    return get_tool_risk(tool_name) == ToolRisk.DESTRUCTIVE


def requires_confirmation(tool_name: str, llm_requested: bool = False) -> bool:
    """Determine if tool requires user confirmation.
    
    This is the FIREWALL: even if LLM says confirmation=False,
    we override for DESTRUCTIVE tools.
    
    Args:
        tool_name: Name of the tool
        llm_requested: Whether LLM requested confirmation
    
    Returns:
        True if confirmation required (DESTRUCTIVE tools always require it)
    
    Examples:
        >>> requires_confirmation("calendar.delete_event", llm_requested=False)
        True
        >>> requires_confirmation("calendar.delete_event", llm_requested=True)
        True
        >>> requires_confirmation("web.search", llm_requested=False)
        False
        >>> requires_confirmation("web.search", llm_requested=True)
        True
    """
    # DESTRUCTIVE tools ALWAYS require confirmation (firewall)
    if is_destructive(tool_name):
        return True

    # Some MODERATE tools still require confirmation by policy.
    if tool_name in ALWAYS_CONFIRM_TOOLS:
        return True
    
    # Non-destructive tools respect LLM decision
    return llm_requested


def get_confirmation_prompt(tool_name: str, params: dict) -> str:
    """Generate deterministic confirmation prompt for a tool (Issue #426).

    Delegates to ``confirmation_ux.deterministic_confirmation_prompt`` which
    builds prompts exclusively from slot data — never from LLM output.

    Args:
        tool_name: Name of the tool
        params: Tool parameters (slots)

    Returns:
        User-friendly Turkish confirmation prompt
    """
    try:
        from bantz.brain.confirmation_ux import deterministic_confirmation_prompt
        return deterministic_confirmation_prompt(tool_name, params)
    except Exception:
        # Ultimate fallback if confirmation_ux is not available
        return f"{tool_name} çalıştırılsın mı? (evet/hayır)"


def register_tool_risk(tool_name: str, risk: ToolRisk) -> None:
    """Register or update risk level for a tool.
    
    This allows dynamic registration of new tools at runtime.
    
    Args:
        tool_name: Name of the tool
        risk: Risk level to assign
    
    Examples:
        >>> register_tool_risk("custom.dangerous_tool", ToolRisk.DESTRUCTIVE)
    """
    TOOL_REGISTRY[tool_name] = risk


def get_all_tools_by_risk(risk: ToolRisk) -> list[str]:
    """Get all tools with specified risk level.
    
    Args:
        risk: Risk level to filter by
    
    Returns:
        List of tool names with that risk level
    
    Examples:
        >>> destructive = get_all_tools_by_risk(ToolRisk.DESTRUCTIVE)
        >>> "calendar.delete_event" in destructive
        True
    """
    return [name for name, r in TOOL_REGISTRY.items() if r == risk]


def get_registry_stats() -> dict[str, int]:
    """Get statistics about tool registry.
    
    Returns:
        Dict with counts per risk level
    
    Examples:
        >>> stats = get_registry_stats()
        >>> stats["destructive"] >= 1
        True
    """
    from collections import Counter
    
    counts = Counter(TOOL_REGISTRY.values())
    return {
        "safe": counts.get(ToolRisk.SAFE, 0),
        "moderate": counts.get(ToolRisk.MODERATE, 0),
        "destructive": counts.get(ToolRisk.DESTRUCTIVE, 0),
        "total": len(TOOL_REGISTRY),
    }
