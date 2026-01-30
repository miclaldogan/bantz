"""
Tests for MemoryManager (Issue #36 - V2-4).

Tests:
- remember() with policy check
- recall() with retrieval
- forget() and cleanup()
- Shortcut methods
"""

import pytest
import tempfile
import os


class TestMemoryManager:
    """Tests for MemoryManager class."""
    
    @pytest.fixture
    def manager(self):
        """Create MemoryManager for testing."""
        from bantz.memory.snippet_manager import create_memory_manager
        from bantz.memory.snippet_store import InMemoryStore
        
        # Use in-memory stores for all to avoid file IO
        return create_memory_manager(
            session_store=InMemoryStore(),
            profile_store=InMemoryStore(),
            episodic_store=InMemoryStore()
        )
    
    @pytest.mark.asyncio
    async def test_manager_remember_with_policy(self, manager):
        """Test remember checks policy."""
        from bantz.memory.snippet import SnippetType
        
        # Normal content should be allowed
        snippet_id = await manager.remember(
            content="Normal memory content",
            snippet_type=SnippetType.SESSION
        )
        
        assert snippet_id is not None
    
    @pytest.mark.asyncio
    async def test_manager_remember_denied_returns_none(self, manager):
        """Test remember returns None when denied."""
        from bantz.memory.snippet import SnippetType
        
        # Password content should be denied
        snippet_id = await manager.remember(
            content="Password: secret123",
            snippet_type=SnippetType.SESSION
        )
        
        assert snippet_id is None
    
    @pytest.mark.asyncio
    async def test_manager_remember_redacts(self, manager):
        """Test remember redacts sensitive content."""
        from bantz.memory.snippet import SnippetType
        
        # Email should be redacted
        snippet_id = await manager.remember(
            content="Contact: user@example.com",
            snippet_type=SnippetType.SESSION
        )
        
        assert snippet_id is not None
        
        # Verify redaction
        snippet = await manager.get_snippet(snippet_id)
        assert "[EMAIL]" in snippet.content
        assert "user@example.com" not in snippet.content
    
    @pytest.mark.asyncio
    async def test_manager_remember_bypass_policy(self, manager):
        """Test remember with bypass_policy."""
        from bantz.memory.snippet import SnippetType
        
        # Password content with bypass should work
        snippet_id = await manager.remember(
            content="Password: secret123",
            snippet_type=SnippetType.SESSION,
            bypass_policy=True
        )
        
        assert snippet_id is not None
    
    @pytest.mark.asyncio
    async def test_manager_recall_uses_retriever(self, manager):
        """Test recall uses retriever."""
        from bantz.memory.snippet import SnippetType
        
        # Store some memories
        await manager.remember(
            content="Python programming language",
            snippet_type=SnippetType.SESSION
        )
        
        # Recall
        results = await manager.recall("Python")
        
        assert len(results) >= 1
        assert any("Python" in s.content for s in results)
    
    @pytest.mark.asyncio
    async def test_manager_forget_deletes(self, manager):
        """Test forget deletes snippet."""
        from bantz.memory.snippet import SnippetType
        
        snippet_id = await manager.remember(
            content="To be forgotten",
            snippet_type=SnippetType.SESSION
        )
        
        forgotten = await manager.forget(snippet_id)
        
        assert forgotten == True
        assert await manager.get_snippet(snippet_id) is None
    
    @pytest.mark.asyncio
    async def test_manager_forget_nonexistent(self, manager):
        """Test forget returns False for nonexistent."""
        forgotten = await manager.forget("nonexistent-id")
        
        assert forgotten == False
    
    @pytest.mark.asyncio
    async def test_manager_cleanup_all_stores(self, manager):
        """Test cleanup cleans all stores."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        from datetime import datetime, timedelta
        
        # Add expired snippets to each store
        expired = MemorySnippet(
            content="Expired",
            snippet_type=SnippetType.SESSION,
            timestamp=datetime.now() - timedelta(hours=48),
            ttl=timedelta(hours=1)
        )
        await manager.session_store.write(expired)
        
        count = await manager.cleanup()
        
        assert count >= 1
    
    @pytest.mark.asyncio
    async def test_manager_get_stats(self, manager):
        """Test get_stats returns statistics."""
        from bantz.memory.snippet import SnippetType
        
        await manager.remember("Test", SnippetType.SESSION)
        
        stats = await manager.get_stats()
        
        assert "session_count" in stats
        assert "profile_count" in stats
        assert "episodic_count" in stats
        assert "total_count" in stats
        assert stats["total_count"] >= 1


class TestMemoryManagerShortcuts:
    """Tests for MemoryManager shortcut methods."""
    
    @pytest.fixture
    def manager(self):
        """Create MemoryManager for testing."""
        from bantz.memory.snippet_manager import create_memory_manager
        from bantz.memory.snippet_store import InMemoryStore
        
        return create_memory_manager(
            session_store=InMemoryStore(),
            profile_store=InMemoryStore(),
            episodic_store=InMemoryStore()
        )
    
    @pytest.mark.asyncio
    async def test_remember_session(self, manager):
        """Test remember_session shortcut."""
        snippet_id = await manager.remember_session("Session memory")
        
        assert snippet_id is not None
        
        snippet = await manager.get_snippet(snippet_id)
        assert snippet.snippet_type.value == "session"
    
    @pytest.mark.asyncio
    async def test_remember_profile(self, manager):
        """Test remember_profile shortcut."""
        snippet_id = await manager.remember_profile("Profile memory")
        
        assert snippet_id is not None
        
        snippet = await manager.get_snippet(snippet_id)
        assert snippet.snippet_type.value == "profile"
    
    @pytest.mark.asyncio
    async def test_remember_episode(self, manager):
        """Test remember_episode shortcut."""
        snippet_id = await manager.remember_episode("Episodic memory")
        
        assert snippet_id is not None
        
        snippet = await manager.get_snippet(snippet_id)
        assert snippet.snippet_type.value == "episodic"


class TestMemoryManagerFactory:
    """Tests for create_memory_manager factory."""
    
    def test_factory_creates_manager(self):
        """Test factory creates manager with defaults."""
        from bantz.memory.snippet_manager import create_memory_manager, MemoryManager
        from bantz.memory.snippet_store import InMemoryStore
        
        manager = create_memory_manager(
            session_store=InMemoryStore(),
            profile_store=InMemoryStore(),
            episodic_store=InMemoryStore()
        )
        
        assert isinstance(manager, MemoryManager)
    
    def test_factory_strict_policy(self):
        """Test factory with strict policy."""
        from bantz.memory.snippet_manager import create_memory_manager
        from bantz.memory.snippet_store import InMemoryStore
        
        manager = create_memory_manager(
            session_store=InMemoryStore(),
            profile_store=InMemoryStore(),
            episodic_store=InMemoryStore(),
            strict_policy=True
        )
        
        assert manager.write_policy is not None
    
    def test_factory_properties(self):
        """Test manager properties."""
        from bantz.memory.snippet_manager import create_memory_manager
        from bantz.memory.snippet_store import InMemoryStore
        
        manager = create_memory_manager(
            session_store=InMemoryStore(),
            profile_store=InMemoryStore(),
            episodic_store=InMemoryStore()
        )
        
        assert manager.session_store is not None
        assert manager.profile_store is not None
        assert manager.episodic_store is not None
        assert manager.write_policy is not None
        assert manager.retriever is not None
