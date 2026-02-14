"""Safety & Policy Guards for LLM Orchestrator (Issue #140).

This module provides security and validation layers for the orchestrator:
- Tool allowlist/denylist enforcement
- Argument schema validation
- Confirmation token standardization
- Tool plan security filtering
- Audit trail for policy decisions

Principle: "LLM controls everything, but executor enforces guardrails"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

from bantz.agent.tools import Tool
from bantz.brain.arg_sanitizer import ArgSanitizer
from bantz.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)


# ============================================================================
# Confirmation Token Validation
# ============================================================================

# Strict confirmation tokens (no ambiguity)
CONFIRMATION_ACCEPT_TOKENS = {
    "1", "yes", "y", "evet", "e", "ok", "tamam", "onaylıyorum", "kabul"
}

CONFIRMATION_REJECT_TOKENS = {
    "0", "no", "n", "hayır", "h", "vazgeç", "iptal", "red", "istemiyorum"
}

# Ambiguous tokens (NOT accepted for destructive operations)
AMBIGUOUS_TOKENS = {
    "okay", "yep", "sure", "fine", "alright", "olur", "peki"
}

# Route-independent safe tools (Issue #286)
# These read-only tools can run regardless of route (even route=unknown)
ROUTE_INDEPENDENT_SAFE_TOOLS = {
    "time.now",           # Get current time - always safe
    "system.status",      # Get system info - always safe  
    "calendar.list_events",  # Read-only calendar query
    "gmail.list_messages",   # Read-only email listing
    "gmail.get_message",     # Read-only email reading
    "gmail.unread_count",    # Read-only unread count
}


def normalize_confirmation(user_response: str) -> Literal["accept", "reject", "ambiguous", "unknown"]:
    """Normalize user confirmation response.
    
    Args:
        user_response: User's confirmation response
    
    Returns:
        "accept" | "reject" | "ambiguous" | "unknown"
    """
    text = (user_response or "").strip().lower()
    
    # Remove punctuation for better matching
    text = re.sub(r'[^\w\s]', '', text)
    
    # Exact match first
    if text in CONFIRMATION_ACCEPT_TOKENS:
        return "accept"
    if text in CONFIRMATION_REJECT_TOKENS:
        return "reject"
    if text in AMBIGUOUS_TOKENS:
        return "ambiguous"
    
    # Multi-word match (first word)
    first_word = text.split()[0] if text.split() else ""
    if first_word in CONFIRMATION_ACCEPT_TOKENS:
        return "accept"
    if first_word in CONFIRMATION_REJECT_TOKENS:
        return "reject"
    if first_word in AMBIGUOUS_TOKENS:
        return "ambiguous"
    
    return "unknown"


# ============================================================================
# Tool Security Policy
# ============================================================================

@dataclass
class ToolSecurityPolicy:
    """Security policy for tool execution."""
    
    # Tools allowed to execute (None = all allowed)
    allowlist: Optional[set[str]] = None
    
    # Tools explicitly denied (takes precedence over allowlist)
    denylist: set[str] = field(default_factory=set)
    
    # Tools requiring strict confirmation (no ambiguous tokens)
    strict_confirmation: set[str] = field(default_factory=lambda: {
        "calendar.delete_event",
        "calendar.update_event",
        "calendar.create_event",
    })
    
    # Reject ambiguous confirmations for destructive ops
    reject_ambiguous_confirmation: bool = True
    
    # Drop tool plan if route doesn't match (e.g., route=smalltalk but tool_plan=[...])
    enforce_route_tool_match: bool = True


@dataclass
class PolicyViolation:
    """Policy violation record."""
    
    violation_type: str
    tool_name: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_type": self.violation_type,
            "tool_name": self.tool_name,
            "reason": self.reason,
            "metadata": self.metadata,
        }


class SafetyGuard:
    """Safety guardrails for orchestrator tool execution.
    
    This enforces:
    - Tool allowlist/denylist
    - Argument schema validation
    - Confirmation token standardization
    - Tool plan security filtering
    """
    
    def __init__(
        self,
        policy: Optional[ToolSecurityPolicy] = None,
        policy_engine: Optional[PolicyEngine] = None,
        policy_engine_v2: Optional[Any] = None,
        audit_log_path: Optional[Path] = None,
        audit_retention_days: int = 90,
        sanitizer: Optional[ArgSanitizer] = None,
    ):
        self.policy = policy or ToolSecurityPolicy()
        self.policy_engine = policy_engine
        self.policy_engine_v2 = policy_engine_v2  # Issue #1291
        self._audit_retention_days = audit_retention_days
        self._audit_logger: Optional[Any] = None
        self._audit_log_path = audit_log_path
        self._sanitizer = sanitizer or ArgSanitizer()

    # ── Issue #1291: PolicyEngineV2 integration ──

    def evaluate_policy(
        self,
        tool_name: str,
        params: Optional[dict[str, Any]] = None,
        session_id: str = "default",
    ) -> Optional[Any]:
        """Evaluate tool via PolicyEngineV2 if available.

        Returns a PolicyDecision or None if v2 engine is not configured.
        """
        if self.policy_engine_v2 is None:
            return None
        try:
            return self.policy_engine_v2.evaluate(
                tool_name, params or {}, session_id=session_id,
            )
        except Exception as exc:
            logger.debug("[SafetyGuard] PolicyEngineV2.evaluate failed: %s", exc)
            return None

    def _get_audit_logger(self) -> Any:
        """Lazily initialize the persistent audit logger (Issue #423)."""
        if self._audit_logger is None:
            try:
                from bantz.security.audit import AuditLogger
                self._audit_logger = AuditLogger(
                    log_path=self._audit_log_path,
                )
            except Exception as e:
                logger.debug("[audit] Could not initialize AuditLogger: %s", e)
                self._audit_logger = False  # sentinel: don't retry
        return self._audit_logger if self._audit_logger is not False else None
    
    def check_tool_allowed(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """Check if tool is allowed by policy.
        
        Args:
            tool_name: Tool name to check
        
        Returns:
            (allowed: bool, reason: Optional[str])
        """
        # Check denylist first
        if tool_name in self.policy.denylist:
            return False, f"Tool '{tool_name}' is denied by policy"
        
        # Check allowlist
        if self.policy.allowlist is not None:
            if tool_name not in self.policy.allowlist:
                return False, f"Tool '{tool_name}' not in allowlist"
        
        return True, None
    
    def validate_tool_args(
        self,
        tool: Tool,
        params: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """Validate tool arguments against schema + sanitization (Issue #425).
        
        Two-phase validation:
        1. Schema validation (required fields, types)
        2. Sanitization (HTML injection, email format, length, prompt injection, shell)

        If sanitization finds only warnings, the params dict is **mutated** in-place
        with the cleaned values. If blocking issues are found, validation fails.
        
        Args:
            tool: Tool definition
            params: Parameters to validate (mutated in-place for sanitized values)
        
        Returns:
            (valid: bool, error: Optional[str])
        """
        # --- Phase 1: Schema validation ---
        if tool.parameters:
            schema = tool.parameters
            
            # Check required fields
            required = schema.get("required", [])
            for fld in required:
                if fld not in params:
                    return False, f"Missing required field: {fld}"
            
            # Check field types (basic validation)
            properties = schema.get("properties", {})
            for fld, value in params.items():
                if fld not in properties:
                    logger.warning(f"Unknown field '{fld}' in tool '{tool.name}'")
                    continue
                
                field_schema = properties[fld]
                expected_type = field_schema.get("type")
                
                if expected_type == "string" and not isinstance(value, str):
                    return False, f"Field '{fld}' must be string, got {type(value).__name__}"
                elif expected_type == "integer":
                    if isinstance(value, bool):
                        return False, f"Field '{fld}' must be integer, got bool"
                    if isinstance(value, str):
                        # LLM often returns "30" instead of 30 — coerce gracefully
                        try:
                            params[fld] = int(value)
                        except (ValueError, TypeError):
                            return False, f"Field '{fld}' must be integer, got non-numeric string"
                    elif not isinstance(value, int):
                        return False, f"Field '{fld}' must be integer, got {type(value).__name__}"
                elif expected_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                    return False, f"Field '{fld}' must be number, got {type(value).__name__}"
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return False, f"Field '{fld}' must be boolean, got {type(value).__name__}"

        # --- Phase 2: Sanitization (Issue #425) ---
        tool_name = getattr(tool, "name", "") or ""
        cleaned, issues = self._sanitizer.sanitize(tool_name, params)

        # Apply cleaned values back to params (in-place mutation)
        for key, val in cleaned.items():
            params[key] = val

        if self._sanitizer.has_blocking_issues(issues):
            summary = self._sanitizer.blocking_summary(issues)
            logger.warning("[SANITIZE] Blocked %s: %s", tool_name, summary)
            return False, f"Sanitization failed: {summary}"

        # Log warnings (non-blocking)
        for issue in issues:
            if issue.severity == "warning":
                logger.info("[SANITIZE] %s.%s: %s", tool_name, issue.field, issue.description)
        
        return True, None
    
    def check_confirmation_token(
        self,
        tool_name: str,
        user_response: str,
    ) -> tuple[bool, Optional[str]]:
        """Check if confirmation token is acceptable.
        
        For strict confirmation tools, ambiguous tokens are rejected.
        
        Args:
            tool_name: Tool requiring confirmation
            user_response: User's confirmation response
        
        Returns:
            (accepted: bool, reason: Optional[str])
        """
        status = normalize_confirmation(user_response)
        
        if status == "accept":
            return True, None
        
        if status == "reject":
            return False, "User rejected confirmation"
        
        if status == "ambiguous":
            if tool_name in self.policy.strict_confirmation and self.policy.reject_ambiguous_confirmation:
                return False, f"Ambiguous confirmation '{user_response}' not accepted for destructive operation"
            # For non-strict tools, ambiguous is OK
            return True, None
        
        # Unknown token
        return False, f"Unclear confirmation response: '{user_response}'"
    
    def filter_tool_plan(
        self,
        route: str,
        tool_plan: list[str],
    ) -> tuple[list[str], list[PolicyViolation]]:
        """Filter tool plan based on route.
        
        If route=smalltalk but tool_plan has tools, drop them.
        Route-independent safe tools (Issue #286) are allowed regardless of route.
        
        Args:
            route: Orchestrator route (calendar, smalltalk, unknown)
            tool_plan: Tools LLM wants to execute
        
        Returns:
            (filtered_tool_plan, violations)
        """
        if not self.policy.enforce_route_tool_match:
            return tool_plan, []
        
        # If route is not a tool-allowed route, filter based on safety
        # (Issue #170 adds read-only Gmail tools under route="gmail").
        # "system" route allows safe tools like time.now and system.status.
        allowed_routes = {"calendar", "gmail", "system"}
        
        if route in allowed_routes:
            # Route explicitly allows tools
            return tool_plan, []
        
        # For non-allowed routes (smalltalk, unknown), check each tool
        # Issue #286: Allow route-independent safe tools regardless of route
        filtered_plan = []
        violations = []
        
        for tool in tool_plan:
            if tool in ROUTE_INDEPENDENT_SAFE_TOOLS:
                # Safe tool - allow regardless of route
                filtered_plan.append(tool)
                logger.debug(
                    f"Safe tool '{tool}' allowed despite route={route} (Issue #286)"
                )
            else:
                # Not a safe tool - drop and record violation
                violations.append(
                    PolicyViolation(
                        violation_type="route_tool_mismatch",
                        tool_name=tool,
                        reason=f"Route '{route}' does not allow tool '{tool}'",
                        metadata={"route": route, "tool": tool},
                    )
                )
                logger.warning(
                    f"Tool '{tool}' dropped: route={route} does not allow this tool"
                )
        
        return filtered_plan, violations
    
    def audit_decision(
        self,
        decision_type: str,
        tool_name: str,
        allowed: bool,
        reason: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log policy decision for audit trail (Issue #423: persistent storage).
        
        Writes to both Python logger AND persistent AuditLogger (JSON-line file
        with rotation and retention).

        Args:
            decision_type: Type of decision (allow/deny/filter/validate)
            tool_name: Tool being checked
            allowed: Whether tool was allowed
            reason: Reason for decision
            metadata: Additional context
        """
        logger.info(f"[POLICY] {decision_type}: {tool_name} - {reason}")

        # ── Issue #423: Persistent audit storage ─────────────────────────
        audit_logger = self._get_audit_logger()
        if audit_logger is not None:
            try:
                from bantz.security.audit import AuditLevel
                audit_logger.log_action(
                    action=f"policy.{decision_type}",
                    actor="safety_guard",
                    resource=tool_name,
                    outcome="allowed" if allowed else "denied",
                    level=AuditLevel.SECURITY if not allowed else AuditLevel.INFO,
                    decision_type=decision_type,
                    allowed=allowed,
                    reason=reason,
                    **(metadata or {}),
                )
            except Exception as e:
                logger.debug("[audit] Failed to write persistent audit: %s", e)

    def query_audit(
        self,
        *,
        last_days: Optional[int] = None,
        action: Optional[str] = None,
        tool_name: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query persistent audit trail (Issue #423).

        Args:
            last_days: Filter to last N days (default: all)
            action: Filter by action pattern (e.g. 'policy.deny')
            tool_name: Filter by resource (tool name, partial match)
            outcome: Filter by outcome ('allowed' or 'denied')
            limit: Max results

        Returns:
            List of audit entry dicts, newest first.
        """
        audit_logger = self._get_audit_logger()
        if audit_logger is None:
            return []

        try:
            start_time = None
            if last_days is not None:
                start_time = datetime.now() - timedelta(days=last_days)

            entries = audit_logger.query(
                start_time=start_time,
                action=action,
                resource=tool_name,
                outcome=outcome,
                limit=limit,
            )
            return [e.to_dict() for e in entries]
        except Exception as e:
            logger.debug("[audit] Query failed: %s", e)
            return []

    def cleanup_old_audit(self, retention_days: Optional[int] = None) -> int:
        """Remove audit entries older than retention period (Issue #423).

        Args:
            retention_days: Override default retention (default: 90 days)

        Returns:
            Number of entries removed.
        """
        days = retention_days if retention_days is not None else self._audit_retention_days
        audit_logger = self._get_audit_logger()
        if audit_logger is None:
            return 0

        try:
            cutoff = datetime.now() - timedelta(days=days)
            # Read all entries, keep only those after cutoff
            all_entries = audit_logger.query()
            kept = [e for e in all_entries if e.timestamp >= cutoff]
            removed = len(all_entries) - len(kept)

            if removed > 0:
                # Rewrite log with only kept entries
                with audit_logger._lock:
                    with open(audit_logger.log_path, "w", encoding="utf-8") as f:
                        for entry in kept:
                            f.write(entry.to_json() + "\n")
                logger.info("[audit] Cleaned up %d entries older than %d days", removed, days)

            return removed
        except Exception as e:
            logger.debug("[audit] Cleanup failed: %s", e)
            return 0
