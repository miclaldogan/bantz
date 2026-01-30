"""
Permission System.

Controls access to dangerous operations:
- File system access
- Terminal execution
- Network access
- Screen capture
- Audio recording
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union
from pathlib import Path
from datetime import datetime
from enum import Enum, auto
import logging
import json
import threading

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class PermissionDeniedError(Exception):
    """Raised when a permission is denied."""
    
    def __init__(self, permission: "Permission", resource: str, reason: str = ""):
        self.permission = permission
        self.resource = resource
        self.reason = reason
        super().__init__(
            f"Permission denied: {permission.name} for '{resource}'"
            + (f" - {reason}" if reason else "")
        )


# =============================================================================
# Permission Enum
# =============================================================================


class Permission(Enum):
    """Permission types for controlled operations."""
    
    # File system
    FILE_READ = auto()
    FILE_WRITE = auto()
    FILE_DELETE = auto()
    FILE_EXECUTE = auto()
    
    # Terminal/Process
    TERMINAL_EXECUTE = auto()
    PROCESS_SPAWN = auto()
    PROCESS_KILL = auto()
    
    # Network
    NETWORK_ACCESS = auto()
    NETWORK_LISTEN = auto()
    
    # Browser
    BROWSER_CONTROL = auto()
    BROWSER_NAVIGATE = auto()
    BROWSER_INJECT = auto()
    
    # Input/Output
    CLIPBOARD_READ = auto()
    CLIPBOARD_WRITE = auto()
    KEYBOARD_INPUT = auto()
    MOUSE_INPUT = auto()
    
    # Capture
    SCREEN_CAPTURE = auto()
    AUDIO_RECORD = auto()
    CAMERA_ACCESS = auto()
    
    # System
    SYSTEM_SETTINGS = auto()
    SYSTEM_SHUTDOWN = auto()
    
    # Data
    SENSITIVE_DATA_ACCESS = auto()
    CREDENTIAL_ACCESS = auto()
    
    @classmethod
    def dangerous(cls) -> Set["Permission"]:
        """Get set of dangerous permissions that always require confirmation."""
        return {
            cls.FILE_DELETE,
            cls.FILE_EXECUTE,
            cls.TERMINAL_EXECUTE,
            cls.PROCESS_KILL,
            cls.BROWSER_INJECT,
            cls.SYSTEM_SETTINGS,
            cls.SYSTEM_SHUTDOWN,
            cls.CREDENTIAL_ACCESS,
        }
    
    @classmethod
    def from_string(cls, s: str) -> "Permission":
        """Convert string to Permission."""
        try:
            return cls[s.upper()]
        except KeyError:
            raise ValueError(f"Unknown permission: {s}")


# =============================================================================
# Permission Request
# =============================================================================


@dataclass
class PermissionRequest:
    """Request for a permission."""
    
    permission: Permission
    resource: str  # What resource is being accessed
    reason: str    # Why access is needed
    actor: str = "system"  # Who is requesting
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "permission": self.permission.name,
            "resource": self.resource,
            "reason": self.reason,
            "actor": self.actor,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class PermissionGrant:
    """Record of a granted permission."""
    
    permission: Permission
    resource_pattern: str  # Glob pattern for matching resources
    granted_at: datetime
    granted_by: str
    expires_at: Optional[datetime] = None
    one_time: bool = False
    used: bool = False
    
    def matches(self, resource: str) -> bool:
        """Check if this grant matches a resource."""
        import fnmatch
        return fnmatch.fnmatch(resource, self.resource_pattern)
    
    def is_valid(self) -> bool:
        """Check if grant is still valid."""
        if self.one_time and self.used:
            return False
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True


# =============================================================================
# Permission Manager
# =============================================================================


class PermissionManager:
    """
    Manage and enforce permissions.
    
    Controls access to dangerous operations by requiring
    explicit permission grants or user confirmation.
    
    Example:
        manager = PermissionManager()
        
        # Check permission
        request = PermissionRequest(
            permission=Permission.FILE_DELETE,
            resource="/home/user/important.txt",
            reason="User requested file deletion",
        )
        
        if manager.check(request):
            # Proceed with operation
            pass
        
        # Grant permission
        manager.grant(Permission.FILE_READ, resource_pattern="~/*")
    """
    
    def __init__(
        self,
        config_path: Optional[Path] = None,
        ask_callback: Optional[Callable[[PermissionRequest], bool]] = None,
        audit_callback: Optional[Callable[[PermissionRequest, str], None]] = None,
    ):
        """
        Initialize permission manager.
        
        Args:
            config_path: Path to permission config file
            ask_callback: Callback to ask user for permission
            audit_callback: Callback to log permission checks
        """
        self.config_path = config_path
        self._ask_callback = ask_callback
        self._audit_callback = audit_callback
        
        self._grants: List[PermissionGrant] = []
        self._denied: Set[Permission] = set()
        self._always_ask: Set[Permission] = Permission.dangerous()
        self._never_ask: Set[Permission] = set()
        
        self._lock = threading.Lock()
        
        if config_path and config_path.exists():
            self._load_config()
    
    def check(self, request: PermissionRequest) -> bool:
        """
        Check if permission is granted.
        
        Args:
            request: Permission request
            
        Returns:
            True if granted, False if denied
        """
        with self._lock:
            result = self._check_internal(request)
        
        # Audit the check
        if self._audit_callback:
            outcome = "granted" if result else "denied"
            self._audit_callback(request, outcome)
        
        return result
    
    def _check_internal(self, request: PermissionRequest) -> bool:
        """Internal permission check."""
        permission = request.permission
        resource = request.resource
        
        # Check if explicitly denied
        if permission in self._denied:
            logger.debug(f"Permission {permission.name} is in denied set")
            return False
        
        # Check if we have a matching grant
        for grant in self._grants:
            if grant.permission == permission and grant.matches(resource):
                if grant.is_valid():
                    if grant.one_time:
                        grant.used = True
                    logger.debug(f"Permission {permission.name} granted by rule")
                    return True
        
        # Check if in never_ask set (auto-grant)
        if permission in self._never_ask:
            return True
        
        # Check if we need to ask user
        if permission in self._always_ask or permission in Permission.dangerous():
            if self._ask_callback:
                result = self._ask_callback(request)
                logger.debug(f"User {'granted' if result else 'denied'} {permission.name}")
                return result
            else:
                # No callback - deny dangerous permissions by default
                logger.debug(f"No ask callback, denying dangerous permission {permission.name}")
                return False
        
        # Default: allow non-dangerous permissions
        return True
    
    def require(self, request: PermissionRequest) -> None:
        """
        Require permission, raising exception if denied.
        
        Args:
            request: Permission request
            
        Raises:
            PermissionDeniedError: If permission is denied
        """
        if not self.check(request):
            raise PermissionDeniedError(
                permission=request.permission,
                resource=request.resource,
                reason="Permission not granted",
            )
    
    def grant(
        self,
        permission: Permission,
        resource_pattern: str = "*",
        expires_in: Optional[float] = None,
        one_time: bool = False,
        granted_by: str = "system",
    ) -> PermissionGrant:
        """
        Grant a permission.
        
        Args:
            permission: Permission to grant
            resource_pattern: Glob pattern for resources
            expires_in: Expiration in seconds
            one_time: Only valid for one use
            granted_by: Who granted the permission
            
        Returns:
            The created grant
        """
        expires_at = None
        if expires_in is not None:
            from datetime import timedelta
            expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        grant = PermissionGrant(
            permission=permission,
            resource_pattern=resource_pattern,
            granted_at=datetime.now(),
            granted_by=granted_by,
            expires_at=expires_at,
            one_time=one_time,
        )
        
        with self._lock:
            self._grants.append(grant)
            self._denied.discard(permission)
        
        logger.debug(f"Granted {permission.name} for pattern '{resource_pattern}'")
        return grant
    
    def deny(self, permission: Permission) -> None:
        """
        Deny a permission entirely.
        
        Args:
            permission: Permission to deny
        """
        with self._lock:
            self._denied.add(permission)
            # Remove any grants for this permission
            self._grants = [g for g in self._grants if g.permission != permission]
        
        logger.debug(f"Denied permission {permission.name}")
    
    def revoke(self, permission: Permission, resource_pattern: Optional[str] = None) -> int:
        """
        Revoke granted permissions.
        
        Args:
            permission: Permission to revoke
            resource_pattern: Optional pattern to match (revokes all if None)
            
        Returns:
            Number of grants revoked
        """
        with self._lock:
            before = len(self._grants)
            if resource_pattern:
                self._grants = [
                    g for g in self._grants
                    if not (g.permission == permission and g.resource_pattern == resource_pattern)
                ]
            else:
                self._grants = [g for g in self._grants if g.permission != permission]
            revoked = before - len(self._grants)
        
        logger.debug(f"Revoked {revoked} grants for {permission.name}")
        return revoked
    
    def set_always_ask(self, permission: Permission, always_ask: bool = True) -> None:
        """
        Set whether a permission should always require asking.
        
        Args:
            permission: Permission to configure
            always_ask: Whether to always ask
        """
        with self._lock:
            if always_ask:
                self._always_ask.add(permission)
                self._never_ask.discard(permission)
            else:
                self._always_ask.discard(permission)
    
    def set_never_ask(self, permission: Permission, never_ask: bool = True) -> None:
        """
        Set whether a permission should never require asking.
        
        Args:
            permission: Permission to configure
            never_ask: Whether to never ask
        """
        with self._lock:
            if never_ask:
                self._never_ask.add(permission)
                self._always_ask.discard(permission)
            else:
                self._never_ask.discard(permission)
    
    def list_grants(self, permission: Optional[Permission] = None) -> List[PermissionGrant]:
        """
        List active grants.
        
        Args:
            permission: Filter by permission (optional)
            
        Returns:
            List of grants
        """
        with self._lock:
            grants = [g for g in self._grants if g.is_valid()]
            if permission:
                grants = [g for g in grants if g.permission == permission]
            return grants
    
    def cleanup_expired(self) -> int:
        """
        Remove expired grants.
        
        Returns:
            Number of removed grants
        """
        with self._lock:
            before = len(self._grants)
            self._grants = [g for g in self._grants if g.is_valid()]
            return before - len(self._grants)
    
    def save_config(self) -> None:
        """Save configuration to file."""
        if not self.config_path:
            return
        
        config = {
            "denied": [p.name for p in self._denied],
            "always_ask": [p.name for p in self._always_ask],
            "never_ask": [p.name for p in self._never_ask],
            "grants": [
                {
                    "permission": g.permission.name,
                    "resource_pattern": g.resource_pattern,
                    "granted_at": g.granted_at.isoformat(),
                    "granted_by": g.granted_by,
                    "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                }
                for g in self._grants
                if g.is_valid() and not g.one_time
            ],
        }
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, indent=2))
        logger.debug(f"Saved permission config to {self.config_path}")
    
    def _load_config(self) -> None:
        """Load configuration from file."""
        try:
            config = json.loads(self.config_path.read_text())
            
            self._denied = {
                Permission.from_string(p) for p in config.get("denied", [])
            }
            self._always_ask = {
                Permission.from_string(p) for p in config.get("always_ask", [])
            }
            self._never_ask = {
                Permission.from_string(p) for p in config.get("never_ask", [])
            }
            
            for g in config.get("grants", []):
                expires_at = None
                if g.get("expires_at"):
                    expires_at = datetime.fromisoformat(g["expires_at"])
                
                grant = PermissionGrant(
                    permission=Permission.from_string(g["permission"]),
                    resource_pattern=g["resource_pattern"],
                    granted_at=datetime.fromisoformat(g["granted_at"]),
                    granted_by=g["granted_by"],
                    expires_at=expires_at,
                )
                if grant.is_valid():
                    self._grants.append(grant)
            
            logger.debug(f"Loaded permission config from {self.config_path}")
        except Exception as e:
            logger.warning(f"Failed to load permission config: {e}")


# =============================================================================
# Mock Implementation
# =============================================================================


class MockPermissionManager(PermissionManager):
    """Mock permission manager for testing."""
    
    def __init__(self, default_response: bool = True):
        """
        Initialize mock permission manager.
        
        Args:
            default_response: Default response for all checks
        """
        super().__init__()
        self._default_response = default_response
        self._check_history: List[PermissionRequest] = []
        self._mock_responses: Dict[str, bool] = {}
    
    def set_response(
        self,
        permission: Permission,
        response: bool,
        resource: Optional[str] = None,
    ) -> None:
        """
        Set mock response for a permission.
        
        Args:
            permission: Permission to mock
            response: Response to return
            resource: Optional resource pattern
        """
        key = f"{permission.name}:{resource or '*'}"
        self._mock_responses[key] = response
    
    def _check_internal(self, request: PermissionRequest) -> bool:
        """Mock check."""
        self._check_history.append(request)
        
        # Check if explicitly denied
        if request.permission in self._denied:
            return False
        
        # Check for specific mock
        key = f"{request.permission.name}:{request.resource}"
        if key in self._mock_responses:
            return self._mock_responses[key]
        
        # Check for permission-only mock
        key = f"{request.permission.name}:*"
        if key in self._mock_responses:
            return self._mock_responses[key]
        
        # Check grants
        for grant in self._grants:
            if grant.permission == request.permission and grant.matches(request.resource):
                if grant.is_valid():
                    return True
        
        return self._default_response
    
    def get_check_history(self) -> List[PermissionRequest]:
        """Get all permission checks made."""
        return self._check_history.copy()
    
    def clear_history(self) -> None:
        """Clear check history."""
        self._check_history.clear()
