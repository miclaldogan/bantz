"""
Bantz Security Module.

Security and privacy hardening:
- Encrypted storage for sensitive data
- Permission system for dangerous operations
- Audit logging for all actions
- Sensitive data masking
- Code sandboxing (future)

V2-5 Additions (Issue #37):
- Permission levels (LOW/MEDIUM/HIGH) with remember capability
- Action classification for permission mapping
- Secrets vault with encryption
- Log redaction for sensitive data
- Daily activity summary
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
    AuditAction,
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

# V2-5 Security Components (Issue #37)
from bantz.security.permission_level import (
    PermissionLevel,
    PermissionRequest as PermissionLevelRequest,
    PermissionDecision,
    PermissionStore,
    PermissionEngine,
    create_permission_engine,
)
from bantz.security.action_classifier import (
    ActionClassification,
    ActionClassifier,
    create_action_classifier,
)
from bantz.security.vault import (
    Secret,
    SecretType,
    SecretsVault,
    VaultError,
    EncryptionError,
    DecryptionError as VaultDecryptionError,
    SecretNotFoundError,
    create_secrets_vault,
)
from bantz.security.redaction import (
    SensitivityLevel,
    RedactionPattern,
    LogRedactor,
    create_log_redactor,
    DEFAULT_PATTERNS,
    SENSITIVE_KEYS,
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
    "AuditAction",
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
    # V2-5: Permission Levels
    "PermissionLevel",
    "PermissionLevelRequest",
    "PermissionDecision",
    "PermissionStore",
    "PermissionEngine",
    "create_permission_engine",
    # V2-5: Action Classifier
    "ActionClassification",
    "ActionClassifier",
    "create_action_classifier",
    # V2-5: Secrets Vault
    "Secret",
    "SecretType",
    "SecretsVault",
    "VaultError",
    "EncryptionError",
    "VaultDecryptionError",
    "SecretNotFoundError",
    "create_secrets_vault",
    # V2-5: Redaction
    "SensitivityLevel",
    "RedactionPattern",
    "LogRedactor",
    "create_log_redactor",
    "DEFAULT_PATTERNS",
    "SENSITIVE_KEYS",
]
