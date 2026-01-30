"""
Tests for security module.

Tests cover:
- Encrypted storage
- Permission system
- Audit logging
- Data masking
- Sandboxing
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import json
import os
import time


# =============================================================================
# Storage Tests
# =============================================================================


class TestSecureStorage:
    """Tests for encrypted storage."""
    
    def test_import(self):
        """Should import storage module."""
        from bantz.security.storage import (
            SecureStorage,
            StoredItem,
            MockSecureStorage,
            StorageError,
            KeyNotFoundError,
        )
    
    def test_mock_storage_store_retrieve(self):
        """Should store and retrieve values."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("test_key", "test_value")
        
        result = storage.retrieve("test_key")
        assert result == "test_value"
    
    def test_mock_storage_metadata(self):
        """Should store and retrieve metadata."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key", "value", tags=["test"])
        
        meta = storage.get_metadata("key")
        assert meta is not None
        assert "test" in meta.tags
    
    def test_mock_storage_list_keys(self):
        """Should list all keys."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key1", "value1")
        storage.store("key2", "value2")
        storage.store("key3", "value3")
        
        keys = storage.list_keys()
        assert len(keys) == 3
        assert "key1" in keys
        assert "key2" in keys
        assert "key3" in keys
    
    def test_mock_storage_delete(self):
        """Should delete key."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key", "value")
        
        result = storage.delete("key")
        assert result is True
        
        keys = storage.list_keys()
        assert "key" not in keys
    
    def test_mock_storage_key_not_found(self):
        """Should return default for missing key."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        
        result = storage.retrieve("nonexistent")
        assert result is None
        
        result = storage.retrieve("nonexistent", default="default")
        assert result == "default"
    
    def test_mock_storage_expiration(self):
        """Should handle expiration."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        # Store with very short TTL
        storage.store("key", "value", expires_in=0.001)
        
        # Wait for expiration
        time.sleep(0.01)
        
        # Should return None
        result = storage.retrieve("key")
        assert result is None
    
    def test_mock_storage_update(self):
        """Should update existing value."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key", "value1")
        storage.store("key", "value2")
        
        result = storage.retrieve("key")
        assert result == "value2"
    
    def test_mock_storage_cleanup_expired(self):
        """Should cleanup expired entries."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key1", "value1", expires_in=0.001)
        storage.store("key2", "value2")  # No expiration
        
        time.sleep(0.01)
        count = storage.cleanup_expired()
        
        assert count == 1
        assert storage.list_keys() == ["key2"]
    
    def test_mock_storage_clear_all(self):
        """Should clear all entries."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key1", "value1")
        storage.store("key2", "value2")
        
        storage.clear_all()
        
        assert storage.list_keys() == []
    
    def test_stored_item_expiration_check(self):
        """StoredItem should check expiration."""
        from bantz.security.storage import StoredItem
        
        now = datetime.now()
        
        # Not expired
        item = StoredItem(
            key="test",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert not item.is_expired()
        
        # Expired
        item2 = StoredItem(
            key="test",
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        assert item2.is_expired()
        
        # No expiration
        item3 = StoredItem(
            key="test",
            created_at=now,
            updated_at=now,
            expires_at=None,
        )
        assert not item3.is_expired()
    
    def test_mock_storage_exists(self):
        """Should check if key exists."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key", "value")
        
        assert storage.exists("key") is True
        assert storage.exists("nonexistent") is False
    
    def test_mock_storage_list_by_tag(self):
        """Should list keys by tag."""
        from bantz.security.storage import MockSecureStorage
        
        storage = MockSecureStorage()
        storage.store("key1", "value1", tags=["api"])
        storage.store("key2", "value2", tags=["config"])
        storage.store("key3", "value3", tags=["api"])
        
        keys = storage.list_keys(tag="api")
        assert len(keys) == 2
        assert "key1" in keys
        assert "key3" in keys


# =============================================================================
# Permission Tests
# =============================================================================


class TestPermissions:
    """Tests for permission system."""
    
    def test_import(self):
        """Should import permissions module."""
        from bantz.security.permissions import (
            Permission,
            PermissionManager,
            PermissionGrant,
            PermissionRequest,
            MockPermissionManager,
            PermissionDeniedError,
        )
    
    def test_permission_enum(self):
        """Permission enum should have expected values."""
        from bantz.security.permissions import Permission
        
        assert Permission.FILE_READ
        assert Permission.FILE_WRITE
        assert Permission.TERMINAL_EXECUTE
        assert Permission.NETWORK_ACCESS
    
    def test_permission_dangerous(self):
        """Should identify dangerous permissions."""
        from bantz.security.permissions import Permission
        
        dangerous = Permission.dangerous()
        
        assert Permission.FILE_DELETE in dangerous
        assert Permission.TERMINAL_EXECUTE in dangerous
        assert Permission.SYSTEM_SHUTDOWN in dangerous
    
    def test_mock_permission_manager_with_request(self):
        """Should check permissions with PermissionRequest."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
        )
        
        manager = MockPermissionManager(default_response=False)
        
        request = PermissionRequest(
            permission=Permission.FILE_READ,
            resource="/home/user/test.txt",
            reason="Read file",
        )
        
        # Default is False
        assert not manager.check(request)
        
        # Grant permission
        manager.grant(Permission.FILE_READ, "/home/user/*")
        
        # Now should be granted
        assert manager.check(request)
    
    def test_mock_permission_manager_default_response(self):
        """Should use default response."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
        )
        
        # Default True
        manager = MockPermissionManager(default_response=True)
        request = PermissionRequest(
            permission=Permission.FILE_READ,
            resource="/path",
            reason="test",
        )
        assert manager.check(request)
        
        # Default False
        manager2 = MockPermissionManager(default_response=False)
        assert not manager2.check(request)
    
    def test_mock_permission_manager_set_response(self):
        """Should set mock response."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
        )
        
        manager = MockPermissionManager(default_response=False)
        manager.set_response(Permission.FILE_READ, True)
        
        request = PermissionRequest(
            permission=Permission.FILE_READ,
            resource="/path",
            reason="test",
        )
        
        assert manager.check(request)
    
    def test_mock_permission_manager_require(self):
        """require() should raise on denial."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
            PermissionDeniedError,
        )
        
        manager = MockPermissionManager(default_response=False)
        
        request = PermissionRequest(
            permission=Permission.TERMINAL_EXECUTE,
            resource="rm -rf",
            reason="test",
        )
        
        with pytest.raises(PermissionDeniedError) as exc_info:
            manager.require(request)
        
        assert exc_info.value.permission == Permission.TERMINAL_EXECUTE
    
    def test_mock_permission_manager_revoke(self):
        """Should revoke permissions."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
        )
        
        manager = MockPermissionManager(default_response=False)
        manager.grant(Permission.FILE_READ)
        
        request = PermissionRequest(
            permission=Permission.FILE_READ,
            resource="/path",
            reason="test",
        )
        
        assert manager.check(request)
        
        manager.revoke(Permission.FILE_READ)
        
        assert not manager.check(request)
    
    def test_mock_permission_manager_deny(self):
        """Should deny permissions."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
        )
        
        manager = MockPermissionManager(default_response=True)
        manager.deny(Permission.FILE_DELETE)
        
        request = PermissionRequest(
            permission=Permission.FILE_DELETE,
            resource="/path",
            reason="test",
        )
        
        assert not manager.check(request)
    
    def test_permission_grant_matching(self):
        """PermissionGrant should match patterns."""
        from bantz.security.permissions import PermissionGrant, Permission
        
        grant = PermissionGrant(
            permission=Permission.FILE_READ,
            resource_pattern="/home/user/*",
            granted_at=datetime.now(),
            granted_by="test",
        )
        
        assert grant.matches("/home/user/test.txt")
        assert grant.matches("/home/user/any")
        assert not grant.matches("/etc/passwd")
    
    def test_permission_denied_error_message(self):
        """PermissionDeniedError should have clear message."""
        from bantz.security.permissions import PermissionDeniedError, Permission
        
        error = PermissionDeniedError(
            permission=Permission.FILE_DELETE,
            resource="/important/file.txt",
            reason="User denied",
        )
        
        msg = str(error)
        assert "FILE_DELETE" in msg
        assert "/important/file.txt" in msg
    
    def test_permission_grant_expiration(self):
        """PermissionGrant should expire."""
        from bantz.security.permissions import PermissionGrant, Permission
        
        # Not expired
        grant = PermissionGrant(
            permission=Permission.FILE_READ,
            resource_pattern="*",
            granted_at=datetime.now(),
            granted_by="test",
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert grant.is_valid()
        
        # Expired
        grant2 = PermissionGrant(
            permission=Permission.FILE_READ,
            resource_pattern="*",
            granted_at=datetime.now() - timedelta(hours=2),
            granted_by="test",
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert not grant2.is_valid()
    
    def test_mock_permission_manager_check_history(self):
        """Should track check history."""
        from bantz.security.permissions import (
            MockPermissionManager,
            Permission,
            PermissionRequest,
        )
        
        manager = MockPermissionManager()
        
        request = PermissionRequest(
            permission=Permission.FILE_READ,
            resource="/path",
            reason="test",
        )
        
        manager.check(request)
        manager.check(request)
        
        history = manager.get_check_history()
        assert len(history) == 2
    
    def test_permission_from_string(self):
        """Should convert string to Permission."""
        from bantz.security.permissions import Permission
        
        assert Permission.from_string("FILE_READ") == Permission.FILE_READ
        assert Permission.from_string("terminal_execute") == Permission.TERMINAL_EXECUTE
        
        with pytest.raises(ValueError):
            Permission.from_string("invalid")


# =============================================================================
# Audit Tests
# =============================================================================


class TestAudit:
    """Tests for audit logging."""
    
    def test_import(self):
        """Should import audit module."""
        from bantz.security.audit import (
            AuditLogger,
            AuditEntry,
            AuditLevel,
            AuditAction,
            MockAuditLogger,
        )
    
    def test_audit_entry_creation(self):
        """Should create audit entry."""
        from bantz.security.audit import AuditEntry, AuditLevel
        
        entry = AuditEntry(
            timestamp=datetime.now(),
            action="test_action",
            actor="user",
            resource="/test/path",
            outcome="success",
            level=AuditLevel.INFO,
        )
        
        assert entry.action == "test_action"
        assert entry.actor == "user"
        assert entry.outcome == "success"
    
    def test_audit_entry_to_dict(self):
        """Should convert to dictionary."""
        from bantz.security.audit import AuditEntry, AuditLevel
        
        now = datetime.now()
        entry = AuditEntry(
            timestamp=now,
            action="command_execute",
            actor="user",
            resource="ls -la",
            outcome="success",
            details={"exit_code": 0},
        )
        
        data = entry.to_dict()
        
        assert data["ts"] == now.isoformat()
        assert data["action"] == "command_execute"
        assert data["details"]["exit_code"] == 0
    
    def test_audit_entry_to_json(self):
        """Should serialize to JSON."""
        from bantz.security.audit import AuditEntry
        
        entry = AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="/path",
            outcome="success",
        )
        
        json_str = entry.to_json()
        data = json.loads(json_str)
        
        assert data["action"] == "test"
    
    def test_audit_entry_from_dict(self):
        """Should create from dictionary."""
        from bantz.security.audit import AuditEntry
        
        data = {
            "ts": datetime.now().isoformat(),
            "action": "file_read",
            "actor": "user",
            "resource": "/test",
            "outcome": "success",
        }
        
        entry = AuditEntry.from_dict(data)
        
        assert entry.action == "file_read"
    
    def test_mock_audit_logger_log(self):
        """MockAuditLogger should log to memory."""
        from bantz.security.audit import MockAuditLogger, AuditEntry
        
        logger = MockAuditLogger()
        
        entry = AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="/path",
            outcome="success",
        )
        
        logger.log(entry)
        
        entries = logger.get_all_entries()
        assert len(entries) == 1
        assert entries[0].action == "test"
    
    def test_mock_audit_logger_log_action(self):
        """Should log via convenience method."""
        from bantz.security.audit import MockAuditLogger, AuditAction
        
        logger = MockAuditLogger()
        
        logger.log_action(
            action=AuditAction.COMMAND_EXECUTE,
            actor="user",
            resource="ls",
            outcome="success",
        )
        
        entries = logger.query()
        assert len(entries) == 1
        assert entries[0].action == "command_execute"
    
    def test_mock_audit_logger_query(self):
        """Should query entries."""
        from bantz.security.audit import MockAuditLogger, AuditEntry
        
        logger = MockAuditLogger()
        
        # Add multiple entries
        logger.log(AuditEntry(
            timestamp=datetime.now(),
            action="action1",
            actor="user1",
            resource="/path1",
            outcome="success",
        ))
        logger.log(AuditEntry(
            timestamp=datetime.now(),
            action="action2",
            actor="user2",
            resource="/path2",
            outcome="failure",
        ))
        
        # Query by action
        results = logger.query(action="action1")
        assert len(results) == 1
        assert results[0].actor == "user1"
        
        # Query by outcome
        results = logger.query(outcome="failure")
        assert len(results) == 1
        assert results[0].action == "action2"
    
    def test_mock_audit_logger_query_limit(self):
        """Should respect query limit."""
        from bantz.security.audit import MockAuditLogger, AuditEntry
        
        logger = MockAuditLogger()
        
        for i in range(10):
            logger.log(AuditEntry(
                timestamp=datetime.now(),
                action=f"action{i}",
                actor="user",
                resource="/path",
                outcome="success",
            ))
        
        results = logger.query(limit=3)
        assert len(results) == 3
    
    def test_mock_audit_logger_clear(self):
        """Should clear entries."""
        from bantz.security.audit import MockAuditLogger, AuditEntry
        
        logger = MockAuditLogger()
        
        logger.log(AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="/path",
            outcome="success",
        ))
        
        count = logger.clear()
        
        assert count == 1
        assert len(logger.query()) == 0
    
    def test_audit_level_from_string(self):
        """Should convert string to AuditLevel."""
        from bantz.security.audit import AuditLevel
        
        assert AuditLevel.from_string("info") == AuditLevel.INFO
        assert AuditLevel.from_string("WARNING") == AuditLevel.WARNING
        assert AuditLevel.from_string("invalid") == AuditLevel.INFO  # Default
    
    def test_audit_action_values(self):
        """AuditAction should have expected values."""
        from bantz.security.audit import AuditAction
        
        assert AuditAction.LOGIN.value == "login"
        assert AuditAction.COMMAND_EXECUTE.value == "command_execute"
        assert AuditAction.PERMISSION_DENIED.value == "permission_denied"


# =============================================================================
# Masking Tests
# =============================================================================


class TestMasking:
    """Tests for data masking."""
    
    def test_import(self):
        """Should import masking module."""
        from bantz.security.masking import (
            DataMasker,
            MaskingPattern,
            mask,
            mask_dict,
            MaskedLogger,
        )
    
    def test_mask_email(self):
        """Should mask email addresses."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        text = "Contact user@example.com for info"
        result = masker.mask(text)
        
        assert "user@example.com" not in result
        assert "***@***.***" in result
    
    def test_mask_phone(self):
        """Should mask phone numbers."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        text = "Call me at +90 555 123 4567"
        result = masker.mask(text)
        
        assert "555 123 4567" not in result
    
    def test_mask_credit_card(self):
        """Should mask credit card numbers."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        text = "Card: 4111 1111 1111 1111"
        result = masker.mask(text)
        
        assert "4111" not in result
    
    def test_mask_password(self):
        """Should mask passwords."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        text = "password: supersecret123"
        result = masker.mask(text)
        
        assert "supersecret123" not in result
        assert "MASKED" in result
    
    def test_mask_api_key(self):
        """Should mask API keys."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        text = "api_key: abc123xyz"
        result = masker.mask(text)
        
        assert "abc123xyz" not in result
        assert "API_KEY" in result
    
    def test_mask_bearer_token(self):
        """Should mask bearer tokens."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = masker.mask(text)
        
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "TOKEN" in result
    
    def test_mask_dict_sensitive_fields(self):
        """Should mask sensitive dict fields."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        data = {
            "username": "john",
            "password": "secret123",
            "token": "abc123",
            "email": "john@example.com",
        }
        
        result = masker.mask_dict(data)
        
        # Username preserved
        assert result["username"] == "john"
        
        # Sensitive fields masked
        assert result["password"] == "***MASKED***"
        assert result["token"] == "***MASKED***"
        
        # Email pattern masked
        assert "john@example.com" not in result["email"]
    
    def test_mask_dict_nested(self):
        """Should mask nested dictionaries."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        data = {
            "user": {
                "name": "John",
                "password": "secret",
            },
        }
        
        result = masker.mask_dict(data)
        
        assert result["user"]["name"] == "John"
        assert result["user"]["password"] == "***MASKED***"
    
    def test_mask_dict_list(self):
        """Should mask data in lists."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        data = {
            "users": [
                {"name": "John", "email": "john@example.com"},
                {"name": "Jane", "email": "jane@example.com"},
            ],
        }
        
        result = masker.mask_dict(data)
        
        assert "john@example.com" not in result["users"][0]["email"]
        assert "jane@example.com" not in result["users"][1]["email"]
    
    def test_mask_convenience_function(self):
        """Should mask via convenience function."""
        from bantz.security.masking import mask
        
        result = mask("user@example.com")
        assert "user@example.com" not in result
    
    def test_mask_dict_convenience_function(self):
        """Should mask dict via convenience function."""
        from bantz.security.masking import mask_dict
        
        result = mask_dict({"password": "secret"})
        assert result["password"] == "***MASKED***"
    
    def test_masker_add_pattern(self):
        """Should add custom pattern."""
        from bantz.security.masking import DataMasker, MaskingPattern
        
        masker = DataMasker()
        
        masker.add_pattern(MaskingPattern(
            name="custom",
            pattern=r"SECRET_\w+",
            replacement="***CUSTOM***",
        ))
        
        result = masker.mask("Value: SECRET_ABC123")
        assert "SECRET_ABC123" not in result
        assert "***CUSTOM***" in result
    
    def test_masker_remove_pattern(self):
        """Should remove pattern."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        result = masker.remove_pattern("email")
        assert result is True
        
        # Email no longer masked
        text = "user@example.com"
        assert masker.mask(text) == text
    
    def test_masker_enable_disable_pattern(self):
        """Should enable/disable pattern."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        # Disable email pattern
        masker.enable_pattern("email", False)
        
        text = "user@example.com"
        assert masker.mask(text) == text
        
        # Re-enable
        masker.enable_pattern("email", True)
        assert masker.mask(text) != text
    
    def test_masker_list_patterns(self):
        """Should list pattern names."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        patterns = masker.list_patterns()
        
        assert "email" in patterns
        assert "password" in patterns
        assert "api_key" in patterns
    
    def test_masker_add_sensitive_field(self):
        """Should add sensitive field name."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        masker.add_sensitive_field("my_secret_field")
        
        result = masker.mask_dict({"my_secret_field": "value"})
        assert result["my_secret_field"] == "***MASKED***"
    
    def test_masker_mask_exception(self):
        """Should mask exception message."""
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        
        exc = ValueError("Auth failed for user@example.com")
        result = masker.mask_exception(exc)
        
        assert "user@example.com" not in result
    
    def test_masking_pattern_compile(self):
        """MaskingPattern should compile regex."""
        from bantz.security.masking import MaskingPattern
        import re
        
        pattern = MaskingPattern(
            name="test",
            pattern=r"\d+",
            replacement="NUM",
        )
        
        compiled = pattern.compile()
        assert isinstance(compiled, re.Pattern)
        
        # Should cache
        assert pattern.compile() is compiled
    
    def test_masked_logger(self):
        """MaskedLogger should mask output."""
        from bantz.security.masking import DataMasker
        import logging
        import logging.handlers
        
        masker = DataMasker()
        
        # Create test logger
        test_logger = logging.getLogger("test_masked")
        handler = logging.handlers.MemoryHandler(capacity=100)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)
        
        masked_logger = masker.create_safe_logger(test_logger)
        
        # Should work without error
        masked_logger.info("User email: user@example.com")
        masked_logger.debug("Password: secret123")


# =============================================================================
# Sandbox Tests
# =============================================================================


class TestSandbox:
    """Tests for sandbox environment."""
    
    def test_import(self):
        """Should import sandbox module."""
        from bantz.security.sandbox import (
            Sandbox,
            SandboxConfig,
            SandboxResult,
            MockSandbox,
            RestrictedSandbox,
            IsolationLevel,
            create_sandbox,
        )
    
    def test_sandbox_config_defaults(self):
        """SandboxConfig should have defaults."""
        from bantz.security.sandbox import SandboxConfig, IsolationLevel
        
        config = SandboxConfig()
        
        assert config.isolation_level == IsolationLevel.BASIC
        assert config.max_memory_mb == 512
        assert config.max_time_seconds == 30
        assert config.allow_network is False
    
    def test_sandbox_result(self):
        """SandboxResult should store execution result."""
        from bantz.security.sandbox import SandboxResult
        
        result = SandboxResult(
            success=True,
            return_value=42,
            execution_time=0.5,
        )
        
        assert result.success is True
        assert result.return_value == 42
        assert result.execution_time == 0.5
    
    def test_mock_sandbox_run(self):
        """MockSandbox should track run calls."""
        from bantz.security.sandbox import MockSandbox
        
        sandbox = MockSandbox()
        
        def test_func(x, y):
            return x + y
        
        result = sandbox.run(test_func, 1, 2)
        
        assert result.success is True
        assert result.return_value == 3
        
        calls = sandbox.get_run_calls()
        assert len(calls) == 1
        assert calls[0][0] == test_func
    
    def test_mock_sandbox_execute_command(self):
        """MockSandbox should track command calls."""
        from bantz.security.sandbox import MockSandbox
        
        sandbox = MockSandbox()
        
        result = sandbox.execute_command(["echo", "hello"])
        
        assert result.success is True
        
        calls = sandbox.get_command_calls()
        assert len(calls) == 1
        assert calls[0][0] == ["echo", "hello"]
    
    def test_mock_sandbox_set_result(self):
        """MockSandbox should use mock results."""
        from bantz.security.sandbox import MockSandbox, SandboxResult
        
        sandbox = MockSandbox()
        
        sandbox.set_mock_result("echo", SandboxResult(
            success=True,
            stdout="mock output",
        ))
        
        result = sandbox.execute_command(["echo", "test"])
        
        assert result.stdout == "mock output"
    
    def test_sandbox_context_manager(self):
        """Sandbox should work as context manager."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            assert sandbox is not None
        
        # Should cleanup after exit
    
    def test_sandbox_temp_dir(self):
        """Sandbox should create temp directory."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            temp_dir = sandbox.temp_dir
            assert temp_dir.exists()
            assert temp_dir.is_dir()
    
    def test_sandbox_create_file(self):
        """Sandbox should create files in temp dir."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            path = sandbox.create_file("test.txt", "hello world")
            
            assert path.exists()
            assert path.read_text() == "hello world"
    
    def test_sandbox_read_file(self):
        """Sandbox should read files from temp dir."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            sandbox.create_file("test.txt", "content")
            
            result = sandbox.read_file("test.txt")
            assert result == "content"
    
    def test_sandbox_list_files(self):
        """Sandbox should list files."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            sandbox.create_file("file1.txt", "a")
            sandbox.create_file("file2.txt", "b")
            sandbox.create_file("subdir/file3.txt", "c")
            
            files = sandbox.list_files()
            
            assert "file1.txt" in files
            assert "file2.txt" in files
    
    def test_sandbox_run_timeout(self):
        """Sandbox should timeout long-running functions."""
        from bantz.security.sandbox import Sandbox, SandboxConfig
        
        config = SandboxConfig(max_time_seconds=0.1)
        
        with Sandbox(config) as sandbox:
            def slow_func():
                time.sleep(10)
                return "done"
            
            result = sandbox.run(slow_func)
            
            assert result.success is False
            assert result.terminated is True
            assert result.termination_reason == "timeout"
    
    def test_sandbox_run_error(self):
        """Sandbox should catch function errors."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            def error_func():
                raise ValueError("test error")
            
            result = sandbox.run(error_func)
            
            assert result.success is False
            assert "test error" in result.error
    
    def test_sandbox_execute_real_command(self):
        """Sandbox should execute real commands."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            result = sandbox.execute_command(["echo", "hello"])
            
            assert result.success is True
            assert "hello" in result.stdout
            assert result.exit_code == 0
    
    def test_sandbox_execute_python(self):
        """Sandbox should execute Python code."""
        from bantz.security.sandbox import Sandbox
        
        with Sandbox() as sandbox:
            result = sandbox.execute_command(
                ["python3", "-c", "print('hello from sandbox')"]
            )
            
            assert result.success is True
            assert "hello from sandbox" in result.stdout
    
    def test_restricted_sandbox_blocked_command(self):
        """RestrictedSandbox should block dangerous commands."""
        from bantz.security.sandbox import RestrictedSandbox
        
        with RestrictedSandbox() as sandbox:
            result = sandbox.execute_command(["rm", "-rf", "/"])
            
            assert result.success is False
            assert result.terminated is True
            assert "not allowed" in result.error
    
    def test_create_sandbox_factory(self):
        """create_sandbox should create correct type."""
        from bantz.security.sandbox import (
            create_sandbox,
            IsolationLevel,
            Sandbox,
            RestrictedSandbox,
        )
        
        sandbox = create_sandbox(IsolationLevel.BASIC)
        assert isinstance(sandbox, Sandbox)
        
        restricted = create_sandbox(IsolationLevel.RESTRICTED)
        assert isinstance(restricted, RestrictedSandbox)
    
    def test_sandbox_is_active(self):
        """Sandbox should track active state."""
        from bantz.security.sandbox import Sandbox
        
        sandbox = Sandbox()
        
        assert sandbox.is_active is False


# =============================================================================
# Module Integration Tests
# =============================================================================


class TestSecurityModuleIntegration:
    """Integration tests for security module."""
    
    def test_module_init_exports(self):
        """Module should export all main classes."""
        from bantz.security import (
            SecureStorage,
            MockSecureStorage,
            Permission,
            PermissionManager,
            MockPermissionManager,
            AuditLogger,
            MockAuditLogger,
            DataMasker,
            Sandbox,
            MockSandbox,
        )
    
    def test_audit_with_masker(self):
        """AuditLogger should work with DataMasker."""
        from bantz.security.audit import MockAuditLogger, AuditEntry
        from bantz.security.masking import DataMasker
        
        masker = DataMasker()
        logger = MockAuditLogger()
        logger._masker = masker
        
        entry = AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="/path",
            outcome="success",
            details={"email": "user@example.com"},
        )
        
        logger.log(entry)
        
        # Entry should be logged
        logged = logger.get_all_entries()[0]
        assert logged.action == "test"
    
    def test_permission_with_audit(self):
        """Permission checks can be audited via callback."""
        from bantz.security.permissions import MockPermissionManager, Permission, PermissionRequest
        from bantz.security.audit import MockAuditLogger, AuditEntry, AuditAction
        
        audit = MockAuditLogger()
        
        # Set up audit callback
        def audit_callback(request, outcome):
            audit.log(AuditEntry(
                timestamp=datetime.now(),
                action=AuditAction.PERMISSION_GRANTED.value if outcome == "granted" else AuditAction.PERMISSION_DENIED.value,
                actor=request.actor,
                resource=request.resource,
                outcome=outcome,
            ))
        
        manager = MockPermissionManager(default_response=False)
        manager._audit_callback = audit_callback
        
        request = PermissionRequest(
            permission=Permission.FILE_DELETE,
            resource="/path",
            reason="test",
        )
        
        # Check permission (denied)
        manager.check(request)
        
        entries = audit.query()
        assert len(entries) == 1
        assert entries[0].action == "permission_denied"
    
    def test_sandbox_with_audit(self):
        """Sandbox execution should be auditable."""
        from bantz.security.sandbox import MockSandbox
        from bantz.security.audit import MockAuditLogger, AuditEntry
        
        audit = MockAuditLogger()
        sandbox = MockSandbox()
        
        # Execute command
        result = sandbox.execute_command(["echo", "test"])
        
        # Log result
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="sandbox_execute",
            actor="system",
            resource="echo",
            outcome="success" if result.success else "failure",
            details={
                "command": ["echo", "test"],
                "exit_code": result.exit_code,
            },
        ))
        
        entries = audit.query(action="sandbox_execute")
        assert len(entries) == 1
