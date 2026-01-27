"""
Permission Level System for V2-5 (Issue #37).

Three-tier permission levels:
- LOW: Auto-allow (read-only, local operations)
- MEDIUM: Ask first time, remember choice
- HIGH: Always ask (destructive, sensitive)

Provides PermissionEngine for checking and remembering choices.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class PermissionLevel(Enum):
    """Permission level for actions."""
    
    LOW = "low"       # Auto-allow (read-only, local)
    MEDIUM = "medium" # Ask first time, remember choice
    HIGH = "high"     # Always ask (destructive, sensitive)
    
    @property
    def requires_confirmation(self) -> bool:
        """Whether this level requires user confirmation."""
        return self != PermissionLevel.LOW
    
    @property
    def can_remember(self) -> bool:
        """Whether choices can be remembered for this level."""
        return self == PermissionLevel.MEDIUM
    
    def __lt__(self, other: "PermissionLevel") -> bool:
        """Compare levels for ordering."""
        order = {PermissionLevel.LOW: 0, PermissionLevel.MEDIUM: 1, PermissionLevel.HIGH: 2}
        return order[self] < order[other]


@dataclass
class PermissionRequest:
    """A request for permission to perform an action."""
    
    action: str
    level: PermissionLevel
    description: str
    domain: Optional[str] = None
    resource: Optional[str] = None
    remember_key: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Generate remember_key if not provided."""
        if self.remember_key is None and self.level == PermissionLevel.MEDIUM:
            # Create unique key from action and domain
            parts = [self.action]
            if self.domain:
                parts.append(self.domain)
            self.remember_key = ":".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "action": self.action,
            "level": self.level.value,
            "description": self.description,
            "domain": self.domain,
            "resource": self.resource,
            "remember_key": self.remember_key,
        }


@dataclass
class PermissionDecision:
    """Result of a permission check."""
    
    allowed: bool
    remembered: bool = False
    expires_at: Optional[datetime] = None
    reason: Optional[str] = None
    
    @property
    def is_expired(self) -> bool:
        """Check if decision has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "remembered": self.remembered,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reason": self.reason,
        }


class PermissionStore:
    """Store for remembered permission decisions."""
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize permission store.
        
        Args:
            storage_path: Path to store file. Defaults to ~/.bantz/permissions.json
        """
        if storage_path is None:
            storage_path = Path.home() / ".bantz" / "permissions.json"
        
        self._storage_path = storage_path
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._decisions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        
        self._load()
    
    def _load(self) -> None:
        """Load decisions from storage."""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r") as f:
                    self._decisions = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._decisions = {}
    
    def _save(self) -> None:
        """Save decisions to storage."""
        try:
            with open(self._storage_path, "w") as f:
                json.dump(self._decisions, f, indent=2)
        except IOError:
            pass
    
    def get(self, key: str) -> Optional[PermissionDecision]:
        """Get a remembered decision."""
        with self._lock:
            if key not in self._decisions:
                return None
            
            data = self._decisions[key]
            
            # Check expiry
            if data.get("expires_at"):
                expires = datetime.fromisoformat(data["expires_at"])
                if datetime.now() > expires:
                    del self._decisions[key]
                    self._save()
                    return None
            
            return PermissionDecision(
                allowed=data["allowed"],
                remembered=True,
                expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
                reason="Remembered choice"
            )
    
    def set(
        self,
        key: str,
        allowed: bool,
        expires_at: Optional[datetime] = None
    ) -> None:
        """Store a decision."""
        with self._lock:
            self._decisions[key] = {
                "allowed": allowed,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "stored_at": datetime.now().isoformat(),
            }
            self._save()
    
    def remove(self, key: str) -> bool:
        """Remove a stored decision."""
        with self._lock:
            if key in self._decisions:
                del self._decisions[key]
                self._save()
                return True
            return False
    
    def clear(self) -> int:
        """Clear all stored decisions."""
        with self._lock:
            count = len(self._decisions)
            self._decisions.clear()
            self._save()
            return count
    
    def list_keys(self) -> List[str]:
        """List all stored keys."""
        with self._lock:
            return list(self._decisions.keys())


class PermissionEngine:
    """
    Engine for checking and managing permissions.
    
    Handles:
    - Permission level checking
    - Remembered decisions
    - User prompts
    """
    
    def __init__(
        self,
        store: Optional[PermissionStore] = None,
        ask_callback: Optional[Callable[[PermissionRequest], bool]] = None
    ):
        """
        Initialize permission engine.
        
        Args:
            store: Permission store for remembered decisions
            ask_callback: Callback to ask user for permission
        """
        self._store = store or PermissionStore()
        self._ask_callback = ask_callback or self._default_ask
        self._pending_requests: Dict[str, PermissionRequest] = {}
    
    def _default_ask(self, request: PermissionRequest) -> bool:
        """Default ask callback (denies by default for safety)."""
        # In production, this would prompt the user
        # For testing, default to deny
        return False
    
    async def check(self, request: PermissionRequest) -> PermissionDecision:
        """
        Check if an action is permitted.
        
        Args:
            request: Permission request to check
            
        Returns:
            PermissionDecision with result
        """
        # LOW level: auto-allow
        if request.level == PermissionLevel.LOW:
            return PermissionDecision(
                allowed=True,
                remembered=False,
                reason="Low-risk action, auto-allowed"
            )
        
        # MEDIUM level: check remembered, then ask
        if request.level == PermissionLevel.MEDIUM:
            if request.remember_key:
                remembered = self._store.get(request.remember_key)
                if remembered and not remembered.is_expired:
                    return remembered
            
            # Ask user
            allowed = await self.ask_user(request)
            return PermissionDecision(
                allowed=allowed,
                remembered=False,
                reason="User decision"
            )
        
        # HIGH level: always ask
        if request.level == PermissionLevel.HIGH:
            allowed = await self.ask_user(request)
            return PermissionDecision(
                allowed=allowed,
                remembered=False,
                reason="High-risk action, user confirmation required"
            )
        
        # Unknown level: deny
        return PermissionDecision(
            allowed=False,
            reason="Unknown permission level"
        )
    
    async def ask_user(self, request: PermissionRequest) -> bool:
        """
        Ask user for permission.
        
        Args:
            request: Permission request
            
        Returns:
            True if allowed, False otherwise
        """
        # Store pending request
        self._pending_requests[request.action] = request
        
        try:
            # Call the ask callback
            if callable(self._ask_callback):
                result = self._ask_callback(request)
                # Handle async callback
                if hasattr(result, '__await__'):
                    return await result
                return result
            return False
        finally:
            # Remove from pending
            self._pending_requests.pop(request.action, None)
    
    async def remember_choice(
        self,
        request: PermissionRequest,
        allowed: bool,
        duration: Optional[timedelta] = None
    ) -> None:
        """
        Remember a permission choice.
        
        Args:
            request: The permission request
            allowed: Whether it was allowed
            duration: How long to remember (None = forever)
        """
        if request.level != PermissionLevel.MEDIUM:
            return  # Only MEDIUM level can be remembered
        
        if not request.remember_key:
            return
        
        expires_at = None
        if duration:
            expires_at = datetime.now() + duration
        
        self._store.set(request.remember_key, allowed, expires_at)
    
    def forget_choice(self, remember_key: str) -> bool:
        """Forget a remembered choice."""
        return self._store.remove(remember_key)
    
    def clear_remembered(self) -> int:
        """Clear all remembered choices."""
        return self._store.clear()
    
    def get_remembered_keys(self) -> List[str]:
        """Get list of remembered choice keys."""
        return self._store.list_keys()


def create_permission_engine(
    storage_path: Optional[Path] = None,
    ask_callback: Optional[Callable[[PermissionRequest], bool]] = None
) -> PermissionEngine:
    """Factory for creating permission engine."""
    store = PermissionStore(storage_path)
    return PermissionEngine(store=store, ask_callback=ask_callback)
