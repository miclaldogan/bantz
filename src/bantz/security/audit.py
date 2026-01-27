"""
Audit Logging.

Logs all significant actions for security review:
- Command execution
- File operations
- Permission changes
- Login/logout events
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum
import logging
import json
import os
import gzip
import threading

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class AuditLevel(Enum):
    """Audit entry severity levels."""
    
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    SECURITY = "security"
    
    @classmethod
    def from_string(cls, s: str) -> "AuditLevel":
        """Convert string to AuditLevel."""
        try:
            return cls(s.lower())
        except ValueError:
            return cls.INFO


class AuditAction(Enum):
    """Standard audit action types."""
    
    # Authentication
    LOGIN = "login"
    LOGOUT = "logout"
    AUTH_FAILURE = "auth_failure"
    
    # Commands
    COMMAND_EXECUTE = "command_execute"
    COMMAND_SUCCESS = "command_success"
    COMMAND_FAILURE = "command_failure"
    
    # Files
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    FILE_CREATE = "file_create"
    
    # Permissions
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_REVOKED = "permission_revoked"
    
    # System
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    CONFIG_CHANGE = "config_change"
    
    # Security
    SECURITY_ALERT = "security_alert"
    SENSITIVE_ACCESS = "sensitive_access"
    
    # Custom
    CUSTOM = "custom"


# =============================================================================
# Audit Entry
# =============================================================================


@dataclass
class AuditEntry:
    """
    Single audit log entry.
    """
    
    timestamp: datetime
    action: str
    actor: str  # Who did it (user, plugin, system)
    resource: str  # What resource was affected
    outcome: str  # success, failure, denied
    level: AuditLevel = AuditLevel.INFO
    details: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    ip_address: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ts": self.timestamp.isoformat(),
            "action": self.action,
            "actor": self.actor,
            "resource": self.resource,
            "outcome": self.outcome,
            "level": self.level.value,
            "details": self.details,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "ip_address": self.ip_address,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEntry":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["ts"]),
            action=data["action"],
            actor=data["actor"],
            resource=data["resource"],
            outcome=data["outcome"],
            level=AuditLevel.from_string(data.get("level", "info")),
            details=data.get("details"),
            session_id=data.get("session_id"),
            request_id=data.get("request_id"),
            ip_address=data.get("ip_address"),
        )


# =============================================================================
# Audit Logger
# =============================================================================


class AuditLogger:
    """
    Log all significant actions for review.
    
    Provides:
    - JSON-line formatted audit logs
    - Log rotation
    - Query capabilities
    - Export functionality
    
    Example:
        audit = AuditLogger(log_path=Path("~/.bantz/audit.log"))
        
        # Log an action
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="command_execute",
            actor="user",
            resource="ls -la",
            outcome="success",
        ))
        
        # Query logs
        entries = audit.query(
            start_time=datetime.now() - timedelta(hours=1),
            action="command_execute",
        )
    """
    
    DEFAULT_LOG_PATH = Path.home() / ".config" / "bantz" / "audit.log"
    
    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_size_mb: float = 10.0,
        max_files: int = 5,
        masker: Optional[Any] = None,
    ):
        """
        Initialize audit logger.
        
        Args:
            log_path: Path to audit log file
            max_size_mb: Maximum log file size before rotation
            max_files: Maximum number of rotated log files
            masker: Optional DataMasker for sensitive data
        """
        self.log_path = Path(log_path) if log_path else self.DEFAULT_LOG_PATH
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self.max_files = max_files
        self._masker = masker
        
        self._lock = threading.Lock()
        self._ensure_directory()
    
    def _ensure_directory(self) -> None:
        """Ensure log directory exists."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log(self, entry: AuditEntry) -> None:
        """
        Log an audit entry.
        
        Args:
            entry: Audit entry to log
        """
        with self._lock:
            self._rotate_if_needed()
            
            # Mask sensitive data if masker available
            if self._masker and entry.details:
                entry.details = self._masker.mask_dict(entry.details)
            
            line = entry.to_json() + "\n"
            
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
    
    def log_action(
        self,
        action: Union[str, AuditAction],
        actor: str,
        resource: str,
        outcome: str = "success",
        level: AuditLevel = AuditLevel.INFO,
        **details,
    ) -> None:
        """
        Convenience method to log an action.
        
        Args:
            action: Action type
            actor: Who performed the action
            resource: What was affected
            outcome: Result (success, failure, denied)
            level: Severity level
            **details: Additional details
        """
        if isinstance(action, AuditAction):
            action = action.value
        
        entry = AuditEntry(
            timestamp=datetime.now(),
            action=action,
            actor=actor,
            resource=resource,
            outcome=outcome,
            level=level,
            details=details if details else None,
        )
        self.log(entry)
    
    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        if not self.log_path.exists():
            return
        
        if self.log_path.stat().st_size < self.max_size_bytes:
            return
        
        # Rotate existing files
        for i in range(self.max_files - 1, 0, -1):
            old = self.log_path.with_suffix(f".log.{i}.gz")
            new = self.log_path.with_suffix(f".log.{i + 1}.gz")
            if old.exists():
                if i + 1 >= self.max_files:
                    old.unlink()
                else:
                    old.rename(new)
        
        # Compress current log
        compressed_path = self.log_path.with_suffix(".log.1.gz")
        with open(self.log_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                f_out.writelines(f_in)
        
        # Clear current log
        self.log_path.write_text("")
        
        logger.debug(f"Rotated audit log to {compressed_path}")
    
    def query(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        outcome: Optional[str] = None,
        level: Optional[AuditLevel] = None,
        limit: Optional[int] = None,
    ) -> List[AuditEntry]:
        """
        Query audit log.
        
        Args:
            start_time: Filter by start time
            end_time: Filter by end time
            action: Filter by action
            actor: Filter by actor
            resource: Filter by resource (partial match)
            outcome: Filter by outcome
            level: Filter by level
            limit: Maximum number of results
            
        Returns:
            List of matching audit entries
        """
        entries = []
        
        with self._lock:
            if not self.log_path.exists():
                return entries
            
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        entry = AuditEntry.from_dict(data)
                        
                        # Apply filters
                        if start_time and entry.timestamp < start_time:
                            continue
                        if end_time and entry.timestamp > end_time:
                            continue
                        if action and entry.action != action:
                            continue
                        if actor and entry.actor != actor:
                            continue
                        if resource and resource not in entry.resource:
                            continue
                        if outcome and entry.outcome != outcome:
                            continue
                        if level and entry.level != level:
                            continue
                        
                        entries.append(entry)
                        
                        if limit and len(entries) >= limit:
                            break
                            
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.debug(f"Skipping malformed audit entry: {e}")
        
        return entries
    
    def query_recent(
        self,
        hours: float = 24,
        **filters,
    ) -> List[AuditEntry]:
        """
        Query recent entries.
        
        Args:
            hours: How many hours back to query
            **filters: Additional filters for query()
            
        Returns:
            List of matching entries
        """
        start_time = datetime.now() - timedelta(hours=hours)
        return self.query(start_time=start_time, **filters)
    
    def export(
        self,
        output_path: Path,
        format: str = "json",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """
        Export audit log.
        
        Args:
            output_path: Output file path
            format: Export format (json, csv)
            start_time: Filter by start time
            end_time: Filter by end time
            
        Returns:
            Number of entries exported
        """
        entries = self.query(start_time=start_time, end_time=end_time)
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "json":
            data = [e.to_dict() for e in entries]
            output_path.write_text(json.dumps(data, indent=2))
        elif format == "csv":
            import csv
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "action", "actor", "resource", 
                    "outcome", "level", "details"
                ])
                for entry in entries:
                    writer.writerow([
                        entry.timestamp.isoformat(),
                        entry.action,
                        entry.actor,
                        entry.resource,
                        entry.outcome,
                        entry.level.value,
                        json.dumps(entry.details) if entry.details else "",
                    ])
        else:
            raise ValueError(f"Unsupported export format: {format}")
        
        logger.info(f"Exported {len(entries)} audit entries to {output_path}")
        return len(entries)
    
    def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get audit log statistics.
        
        Args:
            start_time: Filter by start time
            end_time: Filter by end time
            
        Returns:
            Statistics dictionary
        """
        entries = self.query(start_time=start_time, end_time=end_time)
        
        if not entries:
            return {
                "total_entries": 0,
                "actions": {},
                "actors": {},
                "outcomes": {},
                "levels": {},
            }
        
        actions: Dict[str, int] = {}
        actors: Dict[str, int] = {}
        outcomes: Dict[str, int] = {}
        levels: Dict[str, int] = {}
        
        for entry in entries:
            actions[entry.action] = actions.get(entry.action, 0) + 1
            actors[entry.actor] = actors.get(entry.actor, 0) + 1
            outcomes[entry.outcome] = outcomes.get(entry.outcome, 0) + 1
            levels[entry.level.value] = levels.get(entry.level.value, 0) + 1
        
        return {
            "total_entries": len(entries),
            "time_range": {
                "start": entries[0].timestamp.isoformat(),
                "end": entries[-1].timestamp.isoformat(),
            },
            "actions": actions,
            "actors": actors,
            "outcomes": outcomes,
            "levels": levels,
        }
    
    def clear(self) -> int:
        """
        Clear all audit logs.
        
        Returns:
            Number of entries cleared
        """
        entries = self.query()
        count = len(entries)
        
        with self._lock:
            if self.log_path.exists():
                self.log_path.write_text("")
        
        logger.warning(f"Cleared {count} audit entries")
        return count


# =============================================================================
# Mock Implementation
# =============================================================================


class MockAuditLogger(AuditLogger):
    """Mock audit logger for testing."""
    
    def __init__(self, *args, **kwargs):
        # Don't use file - store in memory
        self._entries: List[AuditEntry] = []
        self._lock = threading.Lock()
    
    def log(self, entry: AuditEntry) -> None:
        """Log to memory."""
        with self._lock:
            self._entries.append(entry)
    
    def query(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        outcome: Optional[str] = None,
        level: Optional[AuditLevel] = None,
        limit: Optional[int] = None,
    ) -> List[AuditEntry]:
        """Query from memory."""
        with self._lock:
            entries = self._entries.copy()
        
        # Apply filters
        if start_time:
            entries = [e for e in entries if e.timestamp >= start_time]
        if end_time:
            entries = [e for e in entries if e.timestamp <= end_time]
        if action:
            entries = [e for e in entries if e.action == action]
        if actor:
            entries = [e for e in entries if e.actor == actor]
        if resource:
            entries = [e for e in entries if resource in e.resource]
        if outcome:
            entries = [e for e in entries if e.outcome == outcome]
        if level:
            entries = [e for e in entries if e.level == level]
        if limit:
            entries = entries[:limit]
        
        return entries
    
    def clear(self) -> int:
        """Clear memory."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        return count
    
    def get_all_entries(self) -> List[AuditEntry]:
        """Get all logged entries."""
        with self._lock:
            return self._entries.copy()
