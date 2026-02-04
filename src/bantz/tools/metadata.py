"""Tool Risk Classification & Metadata (Issue #160).

This module defines risk levels for all tools and enforces the confirmation
firewall for destructive operations.

Risk Levels:
- SAFE: Read-only operations, harmless queries (web.search, calendar.list_events)
- MODERATE: State changes with low impact (calendar.create_event, notifications)
- DESTRUCTIVE: Dangerous operations requiring confirmation (delete, file operations, payments)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ToolRisk(str, Enum):
    """Risk classification for tools."""
    
    SAFE = "safe"  # Read-only, no side effects
    MODERATE = "moderate"  # State changes, reversible
    DESTRUCTIVE = "destructive"  # Dangerous, requires confirmation


# Tool Risk Registry
# Maps tool names to their risk levels
TOOL_REGISTRY: dict[str, ToolRisk] = {
    # ═══════════════════════════════════════════════════════════
    # SAFE Tools (Read-only, no side effects)
    # ═══════════════════════════════════════════════════════════
    "web.search": ToolRisk.SAFE,
    "web.open": ToolRisk.SAFE,
    "calendar.list_events": ToolRisk.SAFE,
    "calendar.find_event": ToolRisk.SAFE,
    "calendar.get_event": ToolRisk.SAFE,
    "gmail.list_messages": ToolRisk.SAFE,
    "gmail.unread_count": ToolRisk.SAFE,
    "gmail.get_message": ToolRisk.SAFE,
    "gmail.send": ToolRisk.MODERATE,
    "time.now": ToolRisk.SAFE,
    "time.date": ToolRisk.SAFE,
    "weather.current": ToolRisk.SAFE,
    "weather.forecast": ToolRisk.SAFE,
    "system.status": ToolRisk.SAFE,
    "file.read": ToolRisk.SAFE,
    "file.list": ToolRisk.SAFE,
    "vision.analyze": ToolRisk.SAFE,
    "vision.ocr": ToolRisk.SAFE,
    "vision.screenshot": ToolRisk.SAFE,
    
    # ═══════════════════════════════════════════════════════════
    # MODERATE Tools (State changes, reversible)
    # ═══════════════════════════════════════════════════════════
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
    
    # ═══════════════════════════════════════════════════════════
    # DESTRUCTIVE Tools (Dangerous, requires confirmation)
    # ═══════════════════════════════════════════════════════════
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


# Moderate tools that must always require confirmation.
ALWAYS_CONFIRM_TOOLS: set[str] = {
    "gmail.send",
}


def get_tool_risk(tool_name: str, default: ToolRisk = ToolRisk.MODERATE) -> ToolRisk:
    """Get risk level for a tool.
    
    Args:
        tool_name: Name of the tool (e.g., "calendar.delete_event")
        default: Default risk level if tool not in registry (default: MODERATE)
    
    Returns:
        ToolRisk enum value
    
    Examples:
        >>> get_tool_risk("web.search")
        ToolRisk.SAFE
        >>> get_tool_risk("calendar.delete_event")
        ToolRisk.DESTRUCTIVE
        >>> get_tool_risk("unknown.tool")
        ToolRisk.MODERATE
    """
    return TOOL_REGISTRY.get(tool_name, default)


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
    """Generate confirmation prompt for destructive tool.
    
    Args:
        tool_name: Name of the tool
        params: Tool parameters
    
    Returns:
        User-friendly confirmation prompt
    
    Examples:
        >>> get_confirmation_prompt("calendar.delete_event", {"event_id": "abc123"})
        "Delete calendar event 'abc123'? This cannot be undone."
    """
    # Tool-specific confirmation prompts
    prompts = {
        "calendar.delete_event": "Delete calendar event '{event_id}'? This cannot be undone.",
        "file.delete": "Delete file '{path}'? This cannot be undone.",
        "file.move": "Move file from '{source}' to '{destination}'?",
        "browser.submit_form": "Submit form on '{url}'? This may trigger a transaction.",
        "payment.submit": "Submit payment of {amount} to {recipient}? This cannot be undone.",
        "system.shutdown": "Shutdown system? All unsaved work will be lost.",
        "system.execute_command": "Execute command '{command}'? This may modify your system.",
        "app.close": "Close application '{app_name}'? Unsaved work may be lost.",
        "email.delete": "Delete email '{subject}'? This cannot be undone.",
        "database.delete": "Delete from database? This cannot be undone.",
        "gmail.send": "Send email to '{to}' with subject '{subject}'?",
    }
    
    # Get template or use generic
    template = prompts.get(tool_name, f"Execute {tool_name}? This is a destructive operation.")
    
    # Format with parameters (safely handle missing params)
    try:
        return template.format(**params)
    except (KeyError, ValueError):
        # Fallback if params don't match template
        return f"Execute {tool_name}? This is a destructive operation."


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
