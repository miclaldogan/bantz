"""
Tests for V2-5 Permission Level System (Issue #37).
"""

import pytest
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from bantz.security.permission_level import (
    PermissionLevel,
    PermissionRequest,
    PermissionDecision,
    PermissionStore,
    PermissionEngine,
    create_permission_engine,
)


class TestPermissionLevel:
    """Tests for PermissionLevel enum."""
    
    def test_permission_levels_exist(self):
        """Test all permission levels exist."""
        assert PermissionLevel.LOW is not None
        assert PermissionLevel.MEDIUM is not None
        assert PermissionLevel.HIGH is not None
    
    def test_permission_level_values(self):
        """Test permission level string values."""
        assert PermissionLevel.LOW.value == "low"
        assert PermissionLevel.MEDIUM.value == "medium"
        assert PermissionLevel.HIGH.value == "high"
    
    def test_permission_level_comparison(self):
        """Test permission levels can be compared."""
        # Enum members are singletons
        assert PermissionLevel.LOW == PermissionLevel.LOW
        assert PermissionLevel.HIGH != PermissionLevel.LOW


class TestPermissionRequest:
    """Tests for PermissionRequest dataclass."""
    
    def test_create_request(self):
        """Test creating permission request."""
        request = PermissionRequest(
            action="send_email",
            level=PermissionLevel.MEDIUM,
            description="Send email to user@example.com"
        )
        
        assert request.action == "send_email"
        assert request.level == PermissionLevel.MEDIUM
        assert "email" in request.description
    
    def test_request_with_domain(self):
        """Test request with domain context."""
        request = PermissionRequest(
            action="browser_open",
            level=PermissionLevel.LOW,
            description="Open URL",
            domain="google.com"
        )
        
        assert request.domain == "google.com"
    
    def test_request_remember_key(self):
        """Test request with remember key."""
        request = PermissionRequest(
            action="file_write",
            level=PermissionLevel.MEDIUM,
            description="Write file",
            remember_key="file_write_documents"
        )
        
        assert request.remember_key == "file_write_documents"


class TestPermissionDecision:
    """Tests for PermissionDecision dataclass."""
    
    def test_allowed_decision(self):
        """Test creating allowed decision."""
        decision = PermissionDecision(allowed=True)
        
        assert decision.allowed is True
        assert decision.remembered is False
    
    def test_remembered_decision(self):
        """Test creating remembered decision."""
        expires = datetime.now() + timedelta(days=7)
        decision = PermissionDecision(
            allowed=True,
            remembered=True,
            expires_at=expires
        )
        
        assert decision.remembered is True
        assert decision.expires_at == expires
    
    def test_denied_decision(self):
        """Test creating denied decision."""
        decision = PermissionDecision(allowed=False)
        
        assert decision.allowed is False


class TestPermissionStore:
    """Tests for PermissionStore."""
    
    def test_store_decision(self):
        """Test storing a decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            
            expires = datetime.now() + timedelta(days=7)
            
            store.set("send_email", True, expires_at=expires)
            
            retrieved = store.get("send_email")
            assert retrieved is not None
            assert retrieved.allowed is True
    
    def test_get_nonexistent(self):
        """Test getting nonexistent decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            
            retrieved = store.get("nonexistent")
            assert retrieved is None
    
    def test_delete_decision(self):
        """Test deleting a decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            
            store.set("test_key", True)
            
            assert store.remove("test_key") is True
            assert store.get("test_key") is None
    
    def test_expired_decision_cleaned(self):
        """Test expired decisions are cleaned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            
            # Store expired decision
            expired = datetime.now() - timedelta(days=1)
            store.set("expired_key", True, expires_at=expired)
            
            # Expired decision should return None
            retrieved = store.get("expired_key")
            assert retrieved is None


class TestPermissionEngine:
    """Tests for PermissionEngine."""
    
    @pytest.mark.asyncio
    async def test_low_permission_auto_allowed(self):
        """Test LOW permission is auto-allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            engine = PermissionEngine(store=store)
            
            request = PermissionRequest(
                action="browser_open",
                level=PermissionLevel.LOW,
                description="Open browser"
            )
            
            decision = await engine.check(request)
            assert decision.allowed is True
    
    @pytest.mark.asyncio
    async def test_remembered_decision_used(self):
        """Test remembered decisions are used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            engine = PermissionEngine(store=store)
            
            request = PermissionRequest(
                action="send_email",
                level=PermissionLevel.MEDIUM,
                description="Send email",
                remember_key="send_email"
            )
            
            # Remember a decision using store directly
            store.set("send_email", True, expires_at=datetime.now() + timedelta(days=7))
            
            decision = await engine.check(request)
            assert decision.allowed is True
            assert decision.remembered is True
    
    def test_forget_choice(self):
        """Test forgetting a choice."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            store = PermissionStore(storage_path=store_path)
            engine = PermissionEngine(store=store)
            
            # Store directly
            store.set("test_action", True)
            assert engine.forget_choice("test_action") is True
    
    def test_factory_function(self):
        """Test create_permission_engine factory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "permissions.json"
            engine = create_permission_engine(storage_path=store_path)
            
            assert isinstance(engine, PermissionEngine)
