"""Unified Permission Engine v0 (Issue #452).

Evaluates tool + action requests against a set of :class:`PermissionRule`
objects and returns an ALLOW / CONFIRM / DENY decision.

Features:

- YAML/JSON policy DSL via :mod:`bantz.policy.dsl`
- Built-in default rules (read → allow, write → confirm, execute → deny)
- Wildcard matching (``calendar.*``, ``*``)
- Rate limiting (``max_per_day``, ``max_per_session``)
- Risk-level lookup
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from bantz.policy.dsl import (
    PermissionDecision,
    PermissionRule,
    load_policy,
    load_policy_str,
    match_rule,
)

logger = logging.getLogger(__name__)

__all__ = ["PermissionEngine"]


# ── Built-in default rules ───────────────────────────────────────────

_DEFAULT_RULES: List[PermissionRule] = [
    # Read operations → ALLOW
    PermissionRule(tool="*.list_*", action="read", risk="low", decision=PermissionDecision.ALLOW),
    PermissionRule(tool="*.get_*", action="read", risk="low", decision=PermissionDecision.ALLOW),
    PermissionRule(tool="*.read_*", action="read", risk="low", decision=PermissionDecision.ALLOW),
    PermissionRule(tool="calendar.list_events", action="read", risk="low", decision=PermissionDecision.ALLOW),
    PermissionRule(tool="gmail.read", action="read", risk="low", decision=PermissionDecision.ALLOW),
    # Calendar / Gmail write → CONFIRM
    PermissionRule(tool="calendar.create_event", action="write", risk="medium", decision=PermissionDecision.CONFIRM),
    PermissionRule(tool="calendar.update_event", action="write", risk="medium", decision=PermissionDecision.CONFIRM),
    PermissionRule(tool="calendar.delete_event", action="delete", risk="high", decision=PermissionDecision.CONFIRM),
    PermissionRule(tool="gmail.send", action="write", risk="high", decision=PermissionDecision.CONFIRM),
    # File system write → CONFIRM
    PermissionRule(tool="file.*", action="write", risk="medium", decision=PermissionDecision.CONFIRM),
    # System execute → DENY
    PermissionRule(tool="system.execute_command", action="execute", risk="critical", decision=PermissionDecision.DENY),
    PermissionRule(tool="system.*", action="execute", risk="critical", decision=PermissionDecision.DENY),
    # Catch-all → CONFIRM
    PermissionRule(tool="*", action="*", risk="medium", decision=PermissionDecision.CONFIRM),
]


class PermissionEngine:
    """Evaluates permission requests.

    Parameters
    ----------
    rules:
        Ordered list of rules.  First match wins.
        If *None*, built-in defaults are used.
    """

    def __init__(self, rules: Optional[List[PermissionRule]] = None) -> None:
        self._rules: List[PermissionRule] = rules if rules is not None else list(_DEFAULT_RULES)
        # Rate-limit counters: key = (tool, action)
        self._day_counts: Dict[str, int] = defaultdict(int)
        self._session_counts: Dict[str, int] = defaultdict(int)
        self._day_start: float = time.time()
        self._DAY_SECONDS = 86_400

    # ── policy loading ────────────────────────────────────────────────

    def load_policy(self, path: str) -> None:
        """Replace rules from a YAML/JSON policy file.

        Custom rules are prepended before the built-in defaults so they
        take priority (first-match-wins).
        """
        custom = load_policy(path)
        self._rules = custom + list(_DEFAULT_RULES)
        logger.info("Loaded %d custom rules from %s", len(custom), path)

    def load_policy_str(self, text: str) -> None:
        """Load rules from a raw YAML/JSON string (for tests)."""
        custom = load_policy_str(text)
        self._rules = custom + list(_DEFAULT_RULES)

    # ── evaluation ────────────────────────────────────────────────────

    def evaluate(
        self,
        tool: str,
        action: str = "*",
        context: Optional[Dict[str, Any]] = None,
    ) -> PermissionDecision:
        """Evaluate a permission request.

        Parameters
        ----------
        tool:
            Tool name (e.g. ``"calendar.create_event"``).
        action:
            Action type (``"read"`` / ``"write"`` / ``"delete"`` / ``"execute"``).
        context:
            Optional context dict (unused for now, reserved for future
            conditions like time-of-day or user role).

        Returns
        -------
        PermissionDecision
            The decision for this request.
        """
        self._maybe_reset_day()

        for rule in self._rules:
            if not match_rule(rule, tool, action):
                continue

            # Check rate-limit conditions
            key = f"{tool}:{action}"
            max_day = rule.conditions.get("max_per_day")
            max_sess = rule.conditions.get("max_per_session")

            if max_day is not None and self._day_counts[key] >= max_day:
                logger.warning("Rate limit (day) hit for %s", key)
                return PermissionDecision.DENY

            if max_sess is not None and self._session_counts[key] >= max_sess:
                logger.warning("Rate limit (session) hit for %s", key)
                return PermissionDecision.DENY

            # Bump counters
            self._day_counts[key] += 1
            self._session_counts[key] += 1

            return rule.decision

        # Fallback (should never happen because catch-all is last)
        return PermissionDecision.CONFIRM

    def get_risk(self, tool: str) -> str:
        """Return the risk level for a tool (first matching rule with a specific tool pattern)."""
        from fnmatch import fnmatch as _fnmatch
        for rule in self._rules:
            if _fnmatch(tool, rule.tool):
                return rule.risk
        return "medium"

    # ── rate limiting helpers ─────────────────────────────────────────

    def reset_session(self) -> None:
        """Reset per-session counters (call on new conversation)."""
        self._session_counts.clear()

    def _maybe_reset_day(self) -> None:
        now = time.time()
        if now - self._day_start > self._DAY_SECONDS:
            self._day_counts.clear()
            self._day_start = now
