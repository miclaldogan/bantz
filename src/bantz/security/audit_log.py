"""Append-only JSONL audit logger with PII redaction (Issue #453).

Provides:

- :class:`AuditEventType` enum (tool_call, permission_decision, …)
- :class:`AuditEvent` dataclass — a single audit record
- :class:`AuditLogger` — append to ``~/.bantz/audit.jsonl``, search, tail
- :func:`redact_pii` — PII scrubbing before write

Features:

- Append-only JSONL (one JSON object per line)
- Automatic PII redaction (emails, phones, tokens, file paths)
- File rotation when log exceeds ``max_bytes`` (default 50 MB)
- ``search()`` and ``tail()`` for querying
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

__all__ = [
    "AuditEventType",
    "AuditEvent",
    "AuditLogger",
    "redact_pii",
    "hash_value",
]


# ── Enum ──────────────────────────────────────────────────────────────

class AuditEventType(Enum):
    TOOL_CALL = "tool_call"
    PERMISSION_DECISION = "permission_decision"
    USER_CONFIRMATION = "user_confirmation"
    MEMORY_WRITE = "memory_write"
    ERROR = "error"
    SESSION_START = "session_start"
    SESSION_END = "session_end"


# ── PII redaction ─────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"(?<!\d)(?<!T)\+?\d[\d\s\-()]{7,}\d(?!T)")
_TOKEN_RE = re.compile(
    r"(?i)(?:token|secret|api[_-]?key|password|passwd"
    r"|[Şş]ifre|parola|auth[_-]?token)\s*[:=]\s*\S+",
)
_PATH_RE = re.compile(r"/home/[a-zA-Z0-9_.]+/")


def redact_pii(text: str) -> str:
    """Redact PII from *text*.

    - Emails → ``u***@***.com``
    - Phone numbers → ``[PHONE]``
    - Token/secret values → ``[REDACTED]``
    - Home directory paths → ``~/.../``
    """
    if not text:
        return text
    text = _EMAIL_RE.sub(_redact_email, text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _TOKEN_RE.sub("[REDACTED]", text)
    text = _PATH_RE.sub("~/.../", text)
    return text


def _redact_email(match: re.Match) -> str:
    local, domain = match.group(0).split("@", 1)
    parts = domain.rsplit(".", 1)
    tld = parts[-1] if len(parts) > 1 else "com"
    return f"{local[0]}***@***.{tld}"


def hash_value(value: Any) -> str:
    """SHA-256 hash of a JSON-serialised value (for args/result hashing)."""
    raw = json.dumps(value, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Data model ────────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """A single audit record."""

    event_type: AuditEventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tool: Optional[str] = None
    args_hash: Optional[str] = None
    decision: Optional[str] = None
    decision_reason: Optional[str] = None
    user_confirmed: Optional[bool] = None
    latency_ms: Optional[float] = None
    result_hash: Optional[str] = None
    success: Optional[bool] = None
    session_id: Optional[str] = None
    turn_number: Optional[int] = None
    risk_level: Optional[str] = None
    message: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["timestamp"] = self.timestamp.isoformat()
        # Remove None values for compact JSONL
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        data = dict(data)  # copy
        data["event_type"] = AuditEventType(data["event_type"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Logger ────────────────────────────────────────────────────────────

class AuditLogger:
    """Append-only JSONL audit logger.

    Parameters
    ----------
    log_path:
        Path to the audit log file.  Defaults to ``~/.bantz/audit.jsonl``.
    max_bytes:
        Maximum log file size before rotation (default 50 MB).
    max_backups:
        Number of rotated backup files to keep.
    redact:
        Whether to apply PII redaction before writing.
    """

    def __init__(
        self,
        log_path: Optional[str] = None,
        max_bytes: int = 50 * 1024 * 1024,
        max_backups: int = 5,
        redact: bool = True,
    ) -> None:
        if log_path is None:
            base = Path.home() / ".bantz"
            base.mkdir(parents=True, exist_ok=True)
            log_path = str(base / "audit.jsonl")

        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._max_backups = max_backups
        self._redact = redact
        self._lock = threading.Lock()

    # ── writing ───────────────────────────────────────────────────────

    def log(self, event: AuditEvent) -> None:
        """Append an :class:`AuditEvent` to the log file."""
        data = event.to_dict()
        if self._redact:
            data = self._redact_dict(data)
        line = json.dumps(data, ensure_ascii=False, default=str)

        with self._lock:
            self._maybe_rotate()
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def log_tool_call(
        self,
        tool: str,
        args: Any = None,
        decision: Optional[str] = None,
        result: Any = None,
        latency_ms: Optional[float] = None,
        success: bool = True,
        session_id: Optional[str] = None,
        turn_number: Optional[int] = None,
        risk_level: Optional[str] = None,
    ) -> None:
        """Convenience method to log a tool invocation."""
        self.log(AuditEvent(
            event_type=AuditEventType.TOOL_CALL,
            tool=tool,
            args_hash=hash_value(args) if args is not None else None,
            decision=decision,
            result_hash=hash_value(result) if result is not None else None,
            latency_ms=latency_ms,
            success=success,
            session_id=session_id,
            turn_number=turn_number,
            risk_level=risk_level,
        ))

    # ── reading ───────────────────────────────────────────────────────

    def tail(self, n: int = 20) -> List[AuditEvent]:
        """Return the last *n* events from the log."""
        lines = self._read_lines()
        return [AuditEvent.from_dict(json.loads(l)) for l in lines[-n:]]

    def search(
        self,
        query: Optional[str] = None,
        event_type: Optional[Union[str, AuditEventType]] = None,
        since: Optional[timedelta] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Search the audit log.

        Parameters
        ----------
        query:
            Text substring to match in any field value.
        event_type:
            Filter to a specific event type.
        since:
            Only include events newer than ``now - since``.
        limit:
            Maximum results.
        """
        if isinstance(event_type, AuditEventType):
            event_type = event_type.value

        cutoff = datetime.utcnow() - since if since else None
        results: List[AuditEvent] = []

        for line in self._read_lines():
            if limit and len(results) >= limit:
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event_type and data.get("event_type") != event_type:
                continue
            if cutoff:
                ts = datetime.fromisoformat(data.get("timestamp", ""))
                if ts < cutoff:
                    continue
            if query and query.lower() not in line.lower():
                continue

            results.append(AuditEvent.from_dict(data))

        return results

    # ── rotation ──────────────────────────────────────────────────────

    def _maybe_rotate(self) -> None:
        """Rotate log if it exceeds max_bytes (must hold lock)."""
        if not self._path.exists():
            return
        if self._path.stat().st_size < self._max_bytes:
            return

        # Shift backups: .5 → delete, .4 → .5, … .1 → .2, current → .1
        for i in range(self._max_backups, 0, -1):
            src = self._path.with_suffix(f".jsonl.{i}")
            dst = self._path.with_suffix(f".jsonl.{i + 1}")
            if i == self._max_backups and src.exists():
                src.unlink()
            elif src.exists():
                shutil.move(str(src), str(dst))

        shutil.move(str(self._path), str(self._path.with_suffix(".jsonl.1")))
        logger.info("Audit log rotated: %s", self._path)

    # ── helpers ───────────────────────────────────────────────────────

    def _read_lines(self) -> List[str]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]

    def _redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact PII in string values."""
        # Keys that should never be redacted (contain non-PII structured data)
        _EXEMPT_KEYS = frozenset({"timestamp", "event_type", "args_hash", "result_hash"})
        out: Dict[str, Any] = {}
        for k, v in data.items():
            if k in _EXEMPT_KEYS:
                out[k] = v
            elif isinstance(v, str):
                out[k] = redact_pii(v)
            elif isinstance(v, dict):
                out[k] = self._redact_dict(v)
            else:
                out[k] = v
        return out
