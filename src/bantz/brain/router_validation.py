"""Router output strict schema validation + repair metrics (Issue #526).

Builds on top of the existing ``json_protocol.py`` validation and
``RepairTracker`` from ``llm_router.py``. Adds:

1. **Strict dataclass-based schema validation** with typed field checks.
2. **Field-level repair**: Missing/invalid fields filled with smart defaults.
3. **Repair metrics**: ``repair_rate``, ``repair_success_rate`` for trace/dashboard.
4. **``/status`` integration**: Repair rate for last N turns.

Usage::

    from bantz.brain.router_validation import (
        validate_router_output,
        repair_router_output,
        RepairMetrics,
    )

    raw = {"route": "calender", "confidence": "0.8", "tool_plan": "calendar.list"}
    repaired, report = repair_router_output(raw)
    # repaired = {"route": "calendar", "confidence": 0.8, "tool_plan": ["calendar.list"], ...}
    # report.fields_repaired = ["route", "confidence", "tool_plan"]
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "validate_router_output",
    "repair_router_output",
    "RepairReport",
    "RepairMetrics",
    "FieldValidation",
]


# ── Constants ─────────────────────────────────────────────────

VALID_ROUTES: Set[str] = {"calendar", "gmail", "smalltalk", "system", "wiki", "chat", "unknown"}
VALID_CALENDAR_INTENTS: Set[str] = {"create", "modify", "cancel", "delete", "query", "none"}
VALID_GMAIL_INTENTS: Set[str] = {"list", "search", "read", "send", "reply", "forward", "delete", "mark_read", "none"}

REQUIRED_FIELDS: List[str] = [
    "route",
    "calendar_intent",
    "confidence",
    "tool_plan",
    "assistant_reply",
]

FIELD_DEFAULTS: Dict[str, Any] = {
    "route": "unknown",
    "calendar_intent": "none",
    "confidence": 0.0,
    "tool_plan": [],
    "assistant_reply": "",
    "slots": {},
    "ask_user": False,
    "question": "",
    "requires_confirmation": False,
    "confirmation_prompt": "",
    "memory_update": "",
    "reasoning_summary": [],
    "gmail_intent": "none",
    "gmail": {},
}


# ── Field validation ──────────────────────────────────────────

@dataclass
class FieldValidation:
    """Result of validating a single field."""

    field_name: str = ""
    valid: bool = True
    original_value: Any = None
    repaired_value: Any = None
    error: str = ""

    def was_repaired(self) -> bool:
        return not self.valid and self.repaired_value is not None


# ── Repair report ─────────────────────────────────────────────

@dataclass
class RepairReport:
    """Report from a single repair_router_output() call."""

    is_valid_before: bool = True
    is_valid_after: bool = True
    fields_missing: List[str] = field(default_factory=list)
    fields_repaired: List[str] = field(default_factory=list)
    fields_invalid: List[str] = field(default_factory=list)
    validations: List[FieldValidation] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def needed_repair(self) -> bool:
        return not self.is_valid_before

    @property
    def repair_succeeded(self) -> bool:
        return self.is_valid_after

    def to_trace_line(self) -> str:
        if self.is_valid_before:
            return "[schema] valid=true no_repair_needed"
        repaired_str = ",".join(self.fields_repaired) if self.fields_repaired else "none"
        return (
            f"[schema] valid_before={self.is_valid_before} valid_after={self.is_valid_after} "
            f"repaired=[{repaired_str}]"
        )


# ── Validation ────────────────────────────────────────────────

def _validate_route(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="route", original_value=value)
    if not isinstance(value, str):
        fv.valid = False
        fv.error = f"not a string: {type(value).__name__}"
        return fv
    normalized = value.strip().lower()
    if normalized not in VALID_ROUTES:
        fv.valid = False
        fv.error = f"invalid route: {normalized}"
    return fv


def _validate_calendar_intent(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="calendar_intent", original_value=value)
    if not isinstance(value, str):
        fv.valid = False
        fv.error = f"not a string: {type(value).__name__}"
        return fv
    normalized = value.strip().lower()
    if normalized not in VALID_CALENDAR_INTENTS:
        fv.valid = False
        fv.error = f"invalid intent: {normalized}"
    return fv


def _validate_confidence(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="confidence", original_value=value)
    try:
        conf = float(value)
        if conf < 0.0 or conf > 1.0:
            fv.valid = False
            fv.error = f"out of range: {conf}"
    except (TypeError, ValueError):
        fv.valid = False
        fv.error = f"not a number: {value}"
    return fv


def _validate_tool_plan(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="tool_plan", original_value=value)
    if not isinstance(value, list):
        fv.valid = False
        fv.error = f"not a list: {type(value).__name__}"
        return fv

    # Issue #360: tool_plan may contain dict items like
    # {"name": "gmail.send", "args": {...}}. Treat these as valid.
    for item in value:
        if isinstance(item, str):
            continue
        if isinstance(item, dict):
            name = item.get("name") or item.get("tool") or item.get("tool_name")
            if str(name or "").strip():
                continue
            fv.valid = False
            fv.error = "dict item missing tool name"
            return fv
        # Unknown item type
        fv.valid = False
        fv.error = f"invalid item type: {type(item).__name__}"
        return fv

    return fv


def _validate_assistant_reply(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="assistant_reply", original_value=value)
    if not isinstance(value, str):
        fv.valid = False
        fv.error = f"not a string: {type(value).__name__}"
    return fv


def _validate_slots(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="slots", original_value=value)
    if not isinstance(value, dict):
        fv.valid = False
        fv.error = f"not a dict: {type(value).__name__}"
    return fv


def _validate_gmail_intent(value: Any) -> FieldValidation:
    fv = FieldValidation(field_name="gmail_intent", original_value=value)
    if not isinstance(value, str):
        fv.valid = False
        fv.error = f"not a string: {type(value).__name__}"
        return fv
    if value.strip().lower() not in VALID_GMAIL_INTENTS:
        fv.valid = False
        fv.error = f"invalid gmail_intent: {value}"
    return fv


def _validate_ask_user(value: Any) -> FieldValidation:
    """Issue #1011: validate ask_user is bool-like."""
    fv = FieldValidation(field_name="ask_user", original_value=value)
    if not isinstance(value, (bool, int)):
        fv.valid = False
        fv.error = f"not a bool: {type(value).__name__}"
    return fv


def _validate_question(value: Any) -> FieldValidation:
    """Issue #1011: validate question is a string."""
    fv = FieldValidation(field_name="question", original_value=value)
    if not isinstance(value, str):
        fv.valid = False
        fv.error = f"not a string: {type(value).__name__}"
    return fv


def _validate_requires_confirmation(value: Any) -> FieldValidation:
    """Issue #1011: validate requires_confirmation is bool-like."""
    fv = FieldValidation(field_name="requires_confirmation", original_value=value)
    if not isinstance(value, (bool, int)):
        fv.valid = False
        fv.error = f"not a bool: {type(value).__name__}"
    return fv


def _validate_gmail(value: Any) -> FieldValidation:
    """Issue #1011: validate gmail is a dict."""
    fv = FieldValidation(field_name="gmail", original_value=value)
    if not isinstance(value, dict):
        fv.valid = False
        fv.error = f"not a dict: {type(value).__name__}"
    return fv


_FIELD_VALIDATORS = {
    "route": _validate_route,
    "calendar_intent": _validate_calendar_intent,
    "confidence": _validate_confidence,
    "tool_plan": _validate_tool_plan,
    "assistant_reply": _validate_assistant_reply,
    "slots": _validate_slots,
    "gmail_intent": _validate_gmail_intent,
    "ask_user": _validate_ask_user,
    "question": _validate_question,
    "requires_confirmation": _validate_requires_confirmation,
    "gmail": _validate_gmail,
}


def validate_router_output(parsed: Dict[str, Any]) -> Tuple[bool, List[FieldValidation]]:
    """Validate parsed router output field-by-field.

    Returns (is_valid, list_of_field_validations).
    """
    if not isinstance(parsed, dict):
        return False, [FieldValidation(field_name="_root", valid=False, error="not a dict")]

    validations: List[FieldValidation] = []
    all_valid = True

    # Check required fields exist
    for fname in REQUIRED_FIELDS:
        if fname not in parsed:
            fv = FieldValidation(field_name=fname, valid=False, error="missing")
            validations.append(fv)
            all_valid = False
            continue

        # Validate field value
        validator = _FIELD_VALIDATORS.get(fname)
        if validator:
            fv = validator(parsed[fname])
            validations.append(fv)
            if not fv.valid:
                all_valid = False

    # Validate optional fields if present
    for fname in ["slots", "gmail_intent", "ask_user", "question",
                  "requires_confirmation", "gmail"]:
        if fname in parsed and fname not in [v.field_name for v in validations]:
            validator = _FIELD_VALIDATORS.get(fname)
            if validator:
                fv = validator(parsed[fname])
                validations.append(fv)
                if not fv.valid:
                    all_valid = False

    return all_valid, validations


# ── Repair ────────────────────────────────────────────────────

def _repair_route(value: Any) -> str:
    """Fuzzy-repair invalid route values."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_ROUTES:
            return normalized
        # Fuzzy match
        matches = get_close_matches(normalized, list(VALID_ROUTES), n=1, cutoff=0.6)
        if matches:
            return matches[0]
    return "unknown"


def _repair_calendar_intent(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_CALENDAR_INTENTS:
            return normalized
        matches = get_close_matches(normalized, list(VALID_CALENDAR_INTENTS), n=1, cutoff=0.6)
        if matches:
            return matches[0]
    return "none"


def _repair_confidence(value: Any) -> float:
    try:
        conf = float(value)
        return max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        return 0.0


def _repair_tool_plan(value: Any) -> List[Any]:
    if isinstance(value, list):
        repaired: list[Any] = []
        for item in value:
            if not item:
                continue
            if isinstance(item, str):
                repaired.append(item)
                continue
            if isinstance(item, dict):
                name = item.get("name") or item.get("tool") or item.get("tool_name")
                name = str(name or "").strip()
                if not name:
                    continue
                args = item.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                repaired.append({"name": name, "args": args})
                continue
            repaired.append(str(item))
        return repaired  # type: ignore[return-value]
    if isinstance(value, str):
        # "calendar.list_events" → ["calendar.list_events"]
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def _repair_slots(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _repair_gmail_intent(value: Any) -> str:
    """Fuzzy-repair invalid gmail_intent values."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_GMAIL_INTENTS:
            return normalized
        matches = get_close_matches(normalized, list(VALID_GMAIL_INTENTS), n=1, cutoff=0.6)
        if matches:
            return matches[0]
    return "none"


def _repair_assistant_reply(value: Any) -> str:
    """Issue #1011: coerce assistant_reply to string."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _repair_ask_user(value: Any) -> bool:
    """Issue #1011: coerce ask_user to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "evet")
    return False


def _repair_question(value: Any) -> str:
    """Issue #1011: coerce question to string."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _repair_requires_confirmation(value: Any) -> bool:
    """Issue #1011: coerce requires_confirmation to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "evet")
    return False


def _repair_gmail(value: Any) -> dict:
    """Issue #1011: coerce gmail to dict."""
    if isinstance(value, dict):
        return value
    return {}


def repair_router_output(
    parsed: Dict[str, Any],
) -> Tuple[Dict[str, Any], RepairReport]:
    """Validate and repair router output field-by-field.

    Returns (repaired_dict, repair_report).
    """
    report = RepairReport()

    if not isinstance(parsed, dict):
        repaired = dict(FIELD_DEFAULTS)
        report.is_valid_before = False
        report.is_valid_after = True
        report.fields_repaired = list(FIELD_DEFAULTS.keys())
        return repaired, report

    # Validate first
    is_valid, validations = validate_router_output(parsed)
    report.is_valid_before = is_valid
    report.validations = validations

    if is_valid:
        report.is_valid_after = True
        return dict(parsed), report

    # Repair
    # Issue #1011: Don't blindly copy ALL parsed values — invalid ones would
    # overwrite good defaults.  Instead, only copy VALID parsed values.
    repaired = dict(FIELD_DEFAULTS)
    validated_names = {fv.field_name for fv in validations}
    for fv in validations:
        if fv.valid and fv.field_name in parsed:
            repaired[fv.field_name] = parsed[fv.field_name]

    # Copy unvalidated parsed fields with type-safe check against defaults
    for key, value in parsed.items():
        if key in validated_names:
            continue  # Handled above (valid) or below (repair)
        if key in FIELD_DEFAULTS:
            default = FIELD_DEFAULTS[key]
            if isinstance(value, type(default)):
                repaired[key] = value
            # else: keep safer default
        else:
            # Unknown extra field — pass through
            repaired[key] = value

    for fv in validations:
        if fv.valid:
            continue

        if fv.error == "missing":
            report.fields_missing.append(fv.field_name)
            report.fields_repaired.append(fv.field_name)
            # Default already applied from FIELD_DEFAULTS
            continue

        report.fields_invalid.append(fv.field_name)
        report.fields_repaired.append(fv.field_name)

        # Apply field-specific repair
        original = parsed.get(fv.field_name)
        if fv.field_name == "route":
            repaired["route"] = _repair_route(original)
        elif fv.field_name == "calendar_intent":
            repaired["calendar_intent"] = _repair_calendar_intent(original)
        elif fv.field_name == "confidence":
            repaired["confidence"] = _repair_confidence(original)
        elif fv.field_name == "tool_plan":
            repaired["tool_plan"] = _repair_tool_plan(original)
        elif fv.field_name == "slots":
            repaired["slots"] = _repair_slots(original)
        elif fv.field_name == "gmail_intent":
            repaired["gmail_intent"] = _repair_gmail_intent(original)
        elif fv.field_name == "assistant_reply":
            repaired["assistant_reply"] = _repair_assistant_reply(original)
        elif fv.field_name == "ask_user":
            repaired["ask_user"] = _repair_ask_user(original)
        elif fv.field_name == "question":
            repaired["question"] = _repair_question(original)
        elif fv.field_name == "requires_confirmation":
            repaired["requires_confirmation"] = _repair_requires_confirmation(original)
        elif fv.field_name == "gmail":
            repaired["gmail"] = _repair_gmail(original)
        else:
            repaired[fv.field_name] = FIELD_DEFAULTS.get(fv.field_name, "")

    # Re-validate after repair
    is_valid_after, _ = validate_router_output(repaired)
    report.is_valid_after = is_valid_after

    return repaired, report


# ── Repair metrics (rolling window) ──────────────────────────

class RepairMetrics:
    """Rolling-window repair metrics for ``/status`` dashboard.

    Tracks the last N repair reports for calculating repair rate
    and success rate over a sliding window.

    Parameters
    ----------
    window_size:
        Maximum reports to keep (default: 100).
    """

    def __init__(self, window_size: int = 100) -> None:
        self._window_size = window_size
        self._reports: deque[RepairReport] = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def record(self, report: RepairReport) -> None:
        """Record a repair report."""
        with self._lock:
            self._reports.append(report)

    @property
    def total(self) -> int:
        with self._lock:
            return len(self._reports)

    @property
    def repair_count(self) -> int:
        with self._lock:
            return sum(1 for r in self._reports if r.needed_repair)

    @property
    def repair_success_count(self) -> int:
        with self._lock:
            return sum(1 for r in self._reports if r.needed_repair and r.repair_succeeded)

    @property
    def repair_rate(self) -> float:
        """Percentage of turns that needed repair (0-100)."""
        with self._lock:
            total = len(self._reports)
        if total == 0:
            return 0.0
        return (self.repair_count / total) * 100.0

    @property
    def repair_success_rate(self) -> float:
        """Percentage of repairs that succeeded (0-100)."""
        rc = self.repair_count
        if rc == 0:
            return 100.0  # Nothing to repair = 100% success
        return (self.repair_success_count / rc) * 100.0

    def summary(self) -> Dict[str, Any]:
        """Summary dict for /status command."""
        return {
            "window_size": self._window_size,
            "total_turns": self.total,
            "repairs_needed": self.repair_count,
            "repairs_succeeded": self.repair_success_count,
            "repair_rate_pct": round(self.repair_rate, 1),
            "repair_success_rate_pct": round(self.repair_success_rate, 1),
        }

    def format_status(self) -> str:
        """Format for /status terminal output."""
        s = self.summary()
        return (
            f"📊 Router Schema Repair (last {s['total_turns']}/{s['window_size']} turns):\n"
            f"   Repairs needed: {s['repairs_needed']} ({s['repair_rate_pct']:.1f}%)\n"
            f"   Repair success: {s['repairs_succeeded']}/{s['repairs_needed']} "
            f"({s['repair_success_rate_pct']:.1f}%)"
        )

    def clear(self) -> None:
        with self._lock:
            self._reports.clear()
