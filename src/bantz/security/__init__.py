"""
Bantz Security Module.

Security and privacy hardening:
- Encrypted storage for sensitive data
- Permission system for dangerous operations
- Audit logging for all actions
- Sensitive data masking
- Code sandboxing (future)
"""

from bantz.security.storage import (
    SecureStorage,
    StorageError,
    KeyNotFoundError,
    DecryptionError,
    MockSecureStorage,
)
from bantz.security.permissions import (
    Permission,
    PermissionRequest,
    PermissionManager,
    PermissionDeniedError,
    MockPermissionManager,
)
from bantz.security.audit import (
    AuditEntry,
    AuditLogger,
    AuditLevel,
    MockAuditLogger,
)
from bantz.security.masking import (
    DataMasker,
    MaskingPattern,
    get_default_masker,
)
from bantz.security.sandbox import (
    Sandbox,
    SandboxConfig,
    SandboxResult,
    SandboxError,
    MockSandbox,
)

__all__ = [
    # Storage
    "SecureStorage",
    "StorageError",
    "KeyNotFoundError",
    "DecryptionError",
    "MockSecureStorage",
    # Permissions
    "Permission",
    "PermissionRequest",
    "PermissionManager",
    "PermissionDeniedError",
    "MockPermissionManager",
    # Audit
    "AuditEntry",
    "AuditLogger",
    "AuditLevel",
    "MockAuditLogger",
    # Masking
    "DataMasker",
    "MaskingPattern",
    "get_default_masker",
    # Sandbox
    "Sandbox",
    "SandboxConfig",
    "SandboxResult",
    "SandboxError",
    "MockSandbox",
]
