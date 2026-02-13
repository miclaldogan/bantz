"""Capability model and confirmation enforcement (Issue #1222).

Defines a formal capability taxonomy for tools:
  read, write, send, delete, execute_external, filesystem

Each tool declares its required capabilities.  The enforcement gate
checks whether the current policy allows the action or requires
confirmation.

Audit decisions are logged via :class:`CapabilityAuditLog`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "Capability",
    "ToolCapability",
    "CapabilityGate",
    "CapabilityAuditLog",
    "AuditEntry",
    "get_tool_capabilities",
]


# ============================================================================
# Capability taxonomy
# ============================================================================

class Capability(str, Enum):
    """Core capability taxonomy (Issue #1222)."""

    READ = "read"                      # Read-only data access
    WRITE = "write"                    # Create/modify data
    SEND = "send"                      # Send emails, messages
    DELETE = "delete"                   # Delete/destroy data
    EXECUTE_EXTERNAL = "execute_external"  # Run external commands/processes
    FILESYSTEM = "filesystem"          # File system access


# Capability → default policy
_CAPABILITY_POLICY: Dict[Capability, str] = {
    Capability.READ: "allow",
    Capability.WRITE: "confirm",
    Capability.SEND: "confirm",
    Capability.DELETE: "confirm",
    Capability.EXECUTE_EXTERNAL: "deny",
    Capability.FILESYSTEM: "confirm",
}


# ============================================================================
# Tool → Capability mapping
# ============================================================================

@dataclass(frozen=True)
class ToolCapability:
    """Capabilities required by a specific tool."""

    tool_name: str
    capabilities: frozenset[Capability]
    risk_level: str = "safe"  # safe / moderate / destructive

    @property
    def requires_confirmation(self) -> bool:
        """True if any capability requires confirmation by default."""
        return any(
            _CAPABILITY_POLICY.get(cap) in ("confirm", "deny")
            for cap in self.capabilities
        )

    @property
    def max_risk_capability(self) -> Capability:
        """Return the highest-risk capability."""
        _risk_order = [
            Capability.READ,
            Capability.FILESYSTEM,
            Capability.WRITE,
            Capability.SEND,
            Capability.DELETE,
            Capability.EXECUTE_EXTERNAL,
        ]
        for cap in reversed(_risk_order):
            if cap in self.capabilities:
                return cap
        return Capability.READ


# Comprehensive tool → capability mapping
_TOOL_CAPABILITIES: Dict[str, ToolCapability] = {
    # Calendar — read
    "calendar.list_events": ToolCapability("calendar.list_events", frozenset({Capability.READ}), "safe"),
    "calendar.find_event": ToolCapability("calendar.find_event", frozenset({Capability.READ}), "safe"),
    "calendar.get_event": ToolCapability("calendar.get_event", frozenset({Capability.READ}), "safe"),
    "calendar.find_free_slots": ToolCapability("calendar.find_free_slots", frozenset({Capability.READ}), "safe"),
    # Calendar — write
    "calendar.create_event": ToolCapability("calendar.create_event", frozenset({Capability.WRITE}), "moderate"),
    "calendar.update_event": ToolCapability("calendar.update_event", frozenset({Capability.WRITE}), "moderate"),
    # Calendar — delete
    "calendar.delete_event": ToolCapability("calendar.delete_event", frozenset({Capability.DELETE}), "destructive"),
    # Gmail — read
    "gmail.list_messages": ToolCapability("gmail.list_messages", frozenset({Capability.READ}), "safe"),
    "gmail.get_message": ToolCapability("gmail.get_message", frozenset({Capability.READ}), "safe"),
    "gmail.unread_count": ToolCapability("gmail.unread_count", frozenset({Capability.READ}), "safe"),
    "gmail.query_from_nl": ToolCapability("gmail.query_from_nl", frozenset({Capability.READ}), "safe"),
    "gmail.smart_search": ToolCapability("gmail.smart_search", frozenset({Capability.READ}), "safe"),
    "gmail.list_labels": ToolCapability("gmail.list_labels", frozenset({Capability.READ}), "safe"),
    "gmail.list_drafts": ToolCapability("gmail.list_drafts", frozenset({Capability.READ}), "safe"),
    # Gmail — write
    "gmail.create_draft": ToolCapability("gmail.create_draft", frozenset({Capability.WRITE}), "safe"),
    "gmail.update_draft": ToolCapability("gmail.update_draft", frozenset({Capability.WRITE}), "safe"),
    "gmail.mark_read": ToolCapability("gmail.mark_read", frozenset({Capability.WRITE}), "safe"),
    "gmail.mark_unread": ToolCapability("gmail.mark_unread", frozenset({Capability.WRITE}), "safe"),
    "gmail.add_label": ToolCapability("gmail.add_label", frozenset({Capability.WRITE}), "safe"),
    "gmail.remove_label": ToolCapability("gmail.remove_label", frozenset({Capability.WRITE}), "safe"),
    "gmail.archive": ToolCapability("gmail.archive", frozenset({Capability.WRITE}), "moderate"),
    # Gmail — send
    "gmail.send": ToolCapability("gmail.send", frozenset({Capability.SEND}), "moderate"),
    "gmail.send_draft": ToolCapability("gmail.send_draft", frozenset({Capability.SEND}), "moderate"),
    "gmail.send_to_contact": ToolCapability("gmail.send_to_contact", frozenset({Capability.SEND}), "moderate"),
    "gmail.generate_reply": ToolCapability("gmail.generate_reply", frozenset({Capability.SEND, Capability.WRITE}), "moderate"),
    # Gmail — delete
    "gmail.delete_draft": ToolCapability("gmail.delete_draft", frozenset({Capability.DELETE}), "moderate"),
    "gmail.download_attachment": ToolCapability("gmail.download_attachment", frozenset({Capability.READ, Capability.FILESYSTEM}), "moderate"),
    # Contacts
    "contacts.list": ToolCapability("contacts.list", frozenset({Capability.READ}), "safe"),
    "contacts.resolve": ToolCapability("contacts.resolve", frozenset({Capability.READ}), "safe"),
    "contacts.upsert": ToolCapability("contacts.upsert", frozenset({Capability.WRITE}), "safe"),
    "contacts.delete": ToolCapability("contacts.delete", frozenset({Capability.DELETE}), "destructive"),
    # File system
    "file.read": ToolCapability("file.read", frozenset({Capability.READ, Capability.FILESYSTEM}), "safe"),
    "file.list": ToolCapability("file.list", frozenset({Capability.READ, Capability.FILESYSTEM}), "safe"),
    "file.write": ToolCapability("file.write", frozenset({Capability.WRITE, Capability.FILESYSTEM}), "moderate"),
    "file.delete": ToolCapability("file.delete", frozenset({Capability.DELETE, Capability.FILESYSTEM}), "destructive"),
    "file.move": ToolCapability("file.move", frozenset({Capability.WRITE, Capability.FILESYSTEM}), "destructive"),
    # System
    "system.status": ToolCapability("system.status", frozenset({Capability.READ}), "safe"),
    "system.screenshot": ToolCapability("system.screenshot", frozenset({Capability.READ}), "safe"),
    "system.execute_command": ToolCapability("system.execute_command", frozenset({Capability.EXECUTE_EXTERNAL}), "destructive"),
    "system.shutdown": ToolCapability("system.shutdown", frozenset({Capability.EXECUTE_EXTERNAL}), "destructive"),
    "system.restart": ToolCapability("system.restart", frozenset({Capability.EXECUTE_EXTERNAL}), "destructive"),
    # Browser
    "browser.open": ToolCapability("browser.open", frozenset({Capability.EXECUTE_EXTERNAL}), "moderate"),
    "browser.navigate": ToolCapability("browser.navigate", frozenset({Capability.EXECUTE_EXTERNAL}), "moderate"),
    "browser.submit_form": ToolCapability("browser.submit_form", frozenset({Capability.WRITE, Capability.EXECUTE_EXTERNAL}), "destructive"),
    "browser.click_button": ToolCapability("browser.click_button", frozenset({Capability.EXECUTE_EXTERNAL}), "destructive"),
    # Web
    "web.search": ToolCapability("web.search", frozenset({Capability.READ}), "safe"),
    "web.open": ToolCapability("web.open", frozenset({Capability.READ}), "safe"),
    # Time
    "time.now": ToolCapability("time.now", frozenset({Capability.READ}), "safe"),
    "time.date": ToolCapability("time.date", frozenset({Capability.READ}), "safe"),
    # Vision
    "vision.analyze": ToolCapability("vision.analyze", frozenset({Capability.READ}), "safe"),
    "vision.ocr": ToolCapability("vision.ocr", frozenset({Capability.READ}), "safe"),
    "vision.screenshot": ToolCapability("vision.screenshot", frozenset({Capability.READ}), "safe"),
}

# Default for unknown tools
_UNKNOWN_TOOL_CAPABILITY = ToolCapability(
    "unknown", frozenset({Capability.EXECUTE_EXTERNAL}), "destructive"
)


def get_tool_capabilities(tool_name: str) -> ToolCapability:
    """Return capability metadata for a tool.

    Unknown tools default to EXECUTE_EXTERNAL + destructive risk.
    """
    return _TOOL_CAPABILITIES.get(tool_name, ToolCapability(
        tool_name, _UNKNOWN_TOOL_CAPABILITY.capabilities,
        _UNKNOWN_TOOL_CAPABILITY.risk_level,
    ))


# ============================================================================
# Capability gate — enforcement
# ============================================================================

class CapabilityGate:
    """Single enforcement gate for capability-based confirmation (Issue #1222).

    Default mode is read-only: only READ capabilities are auto-allowed;
    everything else triggers confirmation.  Can be configured with
    allowed_capabilities to auto-allow more.
    """

    def __init__(
        self,
        *,
        allowed_capabilities: Optional[Set[Capability]] = None,
        denied_capabilities: Optional[Set[Capability]] = None,
    ) -> None:
        self._allowed = allowed_capabilities or {Capability.READ}
        self._denied = denied_capabilities or {Capability.EXECUTE_EXTERNAL}

    def check(self, tool_name: str) -> tuple[str, str]:
        """Check whether a tool is allowed, needs confirmation, or is denied.

        Returns:
            (decision, reason)
            decision: "allow" | "confirm" | "deny"
            reason: human-readable explanation
        """
        tc = get_tool_capabilities(tool_name)

        # Any denied capability → deny
        for cap in tc.capabilities:
            if cap in self._denied:
                return "deny", f"Capability {cap.value} is denied for {tool_name}"

        # All capabilities allowed → allow
        if tc.capabilities.issubset(self._allowed):
            return "allow", f"All capabilities {set(c.value for c in tc.capabilities)} are allowed"

        # Some capabilities need confirmation
        needs_confirm = tc.capabilities - self._allowed
        return "confirm", f"Capabilities {set(c.value for c in needs_confirm)} require confirmation for {tool_name}"


# ============================================================================
# Audit log
# ============================================================================

@dataclass
class AuditEntry:
    """Single audit log entry."""

    timestamp: str = ""
    trace_id: str = ""
    tool_name: str = ""
    capabilities: List[str] = field(default_factory=list)
    decision: str = ""          # allow / confirm / deny / confirmed / rejected
    reason: str = ""
    user_input: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""    # Brief outcome after execution

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d["trace_id"]:
            del d["trace_id"]
        if not d["params"]:
            del d["params"]
        if not d["result_summary"]:
            del d["result_summary"]
        return d


class CapabilityAuditLog:
    """Thread-safe JSONL audit log for capability decisions (Issue #1222).

    Records: who requested what, which tool, which capabilities,
    what decision was made, and (optionally) what changed.
    """

    DEFAULT_PATH = "artifacts/logs/capability_audit.jsonl"

    def __init__(self, path: Optional[str] = None, enabled: Optional[bool] = None) -> None:
        self._path = path or os.getenv("BANTZ_CAPABILITY_AUDIT_FILE", self.DEFAULT_PATH)
        if enabled is not None:
            self._enabled = enabled
        else:
            raw = os.getenv("BANTZ_CAPABILITY_AUDIT", "1").strip().lower()
            self._enabled = raw in ("1", "true", "yes")
        self._lock = threading.Lock()
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def log(
        self,
        *,
        tool_name: str,
        decision: str,
        reason: str = "",
        trace_id: str = "",
        user_input: str = "",
        params: Optional[Dict[str, Any]] = None,
        result_summary: str = "",
    ) -> bool:
        """Write a single audit entry.  Returns True on success."""
        if not self._enabled:
            return False

        tc = get_tool_capabilities(tool_name)
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id,
            tool_name=tool_name,
            capabilities=[c.value for c in tc.capabilities],
            decision=decision,
            reason=reason,
            user_input=user_input[:200] if user_input else "",
            params=params or {},
            result_summary=result_summary[:500] if result_summary else "",
        )

        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        p = Path(self._path)

        with self._lock:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                self._count += 1
                return True
            except OSError as exc:
                logger.warning("Audit log write failed: %s", exc)
                return False
