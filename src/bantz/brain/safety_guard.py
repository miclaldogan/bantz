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

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from bantz.agent.tools import Tool, ToolRegistry
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
    ):
        self.policy = policy or ToolSecurityPolicy()
        self.policy_engine = policy_engine
    
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
        """Validate tool arguments against schema.
        
        Args:
            tool: Tool definition
            params: Parameters to validate
        
        Returns:
            (valid: bool, error: Optional[str])
        """
        if not tool.parameters:
            return True, None
        
        schema = tool.parameters
        
        # Check required fields
        required = schema.get("required", [])
        for field in required:
            if field not in params:
                return False, f"Missing required field: {field}"
        
        # Check field types (basic validation)
        properties = schema.get("properties", {})
        for field, value in params.items():
            if field not in properties:
                logger.warning(f"Unknown field '{field}' in tool '{tool.name}'")
                continue
            
            field_schema = properties[field]
            expected_type = field_schema.get("type")
            
            if expected_type == "string" and not isinstance(value, str):
                return False, f"Field '{field}' must be string, got {type(value).__name__}"
            elif expected_type == "number" and not isinstance(value, (int, float)):
                return False, f"Field '{field}' must be number, got {type(value).__name__}"
            elif expected_type == "boolean" and not isinstance(value, bool):
                return False, f"Field '{field}' must be boolean, got {type(value).__name__}"
        
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
        """Log policy decision for audit trail.
        
        Args:
            decision_type: Type of decision (allow/deny/filter/validate)
            tool_name: Tool being checked
            allowed: Whether tool was allowed
            reason: Reason for decision
            metadata: Additional context
        """
        audit_entry = {
            "decision_type": decision_type,
            "tool_name": tool_name,
            "allowed": allowed,
            "reason": reason,
            "metadata": metadata or {},
        }
        
        logger.info(f"[POLICY] {decision_type}: {tool_name} - {reason}")
        
        # TODO: Write to audit log file if configured
        # For now, just log to logger
