"""YAML / JSON policy DSL for the Permission Engine (Issue #452).

Loads permission rules from YAML or JSON files and provides:

- :class:`PermissionDecision` enum (ALLOW / CONFIRM / DENY)
- :class:`PermissionRule` dataclass
- :func:`load_policy` — parse a YAML/JSON file into rules
- :func:`load_policy_str` — parse a raw string (for tests)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "PermissionDecision",
    "PermissionRule",
    "load_policy",
    "load_policy_str",
    "match_rule",
]

# ── Enum ──────────────────────────────────────────────────────────────

class PermissionDecision(Enum):
    """Outcome of a permission evaluation."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


# ── Data model ────────────────────────────────────────────────────────

@dataclass
class PermissionRule:
    """A single permission rule.

    Attributes
    ----------
    tool:
        Tool name pattern (supports ``*`` and ``?`` wildcards via :func:`fnmatch`).
    action:
        Action pattern (``read`` / ``write`` / ``delete`` / ``execute`` / ``*``).
    risk:
        Risk level label (``low`` / ``medium`` / ``high`` / ``critical``).
    decision:
        What to do when the rule matches.
    conditions:
        Optional extra constraints (e.g. ``max_per_day``, ``max_per_session``).
    """

    tool: str = "*"
    action: str = "*"
    risk: str = "medium"
    decision: PermissionDecision = PermissionDecision.CONFIRM
    conditions: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.decision, str):
            self.decision = PermissionDecision(self.decision.lower())


# ── Matching ──────────────────────────────────────────────────────────

def match_rule(rule: PermissionRule, tool: str, action: str) -> bool:
    """Return *True* if *rule* matches the given *tool* and *action*.

    Uses :func:`fnmatch` for glob-style wildcards (``*``, ``?``).
    """
    tool_ok = fnmatch(tool, rule.tool)
    action_ok = rule.action == "*" or fnmatch(action, rule.action)
    return tool_ok and action_ok


# ── Loaders ───────────────────────────────────────────────────────────

def _parse_rules(data: dict) -> List[PermissionRule]:
    raw_rules = data.get("permissions", [])
    rules: List[PermissionRule] = []
    for entry in raw_rules:
        rules.append(
            PermissionRule(
                tool=entry.get("tool", "*"),
                action=entry.get("action", "*"),
                risk=entry.get("risk", "medium"),
                decision=entry.get("decision", "confirm"),
                conditions=entry.get("conditions", {}),
            )
        )
    return rules


def load_policy(path: str) -> List[PermissionRule]:
    """Load rules from a YAML or JSON file.

    Falls back to JSON parsing if PyYAML is not installed.
    """
    text = Path(path).read_text(encoding="utf-8")
    return load_policy_str(text)


def load_policy_str(text: str) -> List[PermissionRule]:
    """Parse rules from a raw YAML / JSON string."""
    data: Optional[dict] = None

    # Try YAML first (superset of JSON)
    try:
        import yaml  # type: ignore[import-untyped]
        data = yaml.safe_load(text)
    except ImportError:
        pass
    except Exception:
        pass

    if data is None:
        # Fall back to JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cannot parse policy: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Policy must be a mapping with a 'permissions' key")

    return _parse_rules(data)
