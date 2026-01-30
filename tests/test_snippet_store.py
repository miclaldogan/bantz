"""
Tests for SnippetStore implementations (Issue #36 - V2-4).

Tests:
- InMemoryStore CRUD
- SQLiteStore CRUD
- Search functionality
- Cleanup of expired snippets
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta


class TestInMemoryStore:
    """Tests for InMemoryStore."""
    
    @pytest.fixture
    def store(self):
        """Create InMemoryStore for testing."""
        from bantz.memory.snippet_store import InMemoryStore
        return InMemoryStore()
    
    @pytest.fixture
    def snippet(self):
        """Create test snippet."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        return MemorySnippet(
            content="Test content for memory",
            snippet_type=SnippetType.SESSION,
            tags=["test"]
        )
    
    @pytest.mark.asyncio
    async def test_store_write_returns_id(self, store, snippet):
        """Test write() returns snippet ID."""
        result = await store.write(snippet)
        
        assert result == snippet.id
    
    @pytest.mark.asyncio
    async def test_store_read_existing(self, store, snippet):
        """Test reading existing snippet."""
        await store.write(snippet)
        
        result = await store.read(snippet.id)
        
        assert result is not None
        assert result.content == snippet.content
    
    @pytest.mark.asyncio
    async def test_store_read_nonexistent(self, store):
        """Test reading nonexistent snippet returns None."""
        result = await store.read("nonexistent-id")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_store_search_by_query(self, store, snippet):
        """Test search by query string."""
        await store.write(snippet)
        
        results = await store.search("Test content")
        
        assert len(results) >= 1
        assert any(s.id == snippet.id for s in results)
    
    @pytest.mark.asyncio
    async def test_store_search_by_type(self, store):
        """Test search with type filter."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        session_snippet = MemorySnippet(
            content="Session memory",
            snippet_type=SnippetType.SESSION
        )
        await store.write(session_snippet)
        
        results = await store.search("memory", snippet_type=SnippetType.SESSION)
        
        assert len(results) >= 1
    
    @pytest.mark.asyncio
    async def test_store_delete_removes(self, store, snippet):
        """Test delete removes snippet."""
        await store.write(snippet)
        
        deleted = await store.delete(snippet.id)
        
        assert deleted == True
        assert await store.read(snippet.id) is None
    
    @pytest.mark.asyncio
    async def test_store_delete_nonexistent(self, store):
        """Test delete returns False for nonexistent."""
        deleted = await store.delete("nonexistent-id")
        
        assert deleted == False
    
    @pytest.mark.asyncio
    async def test_store_cleanup_removes_expired(self, store):
        """Test cleanup removes expired snippets."""
        from bantz.memory.snippet import MemorySnippet
        
        expired = MemorySnippet(
            content="Expired",
            timestamp=datetime.now() - timedelta(hours=2),
            ttl=timedelta(hours=1)
        )
        await store.write(expired)
        
        removed = await store.cleanup_expired()
        
        assert removed >= 1
    
    @pytest.mark.asyncio
    async def test_store_count(self, store, snippet):
        """Test count returns correct number."""
        await store.write(snippet)
        
        count = await store.count()
        
        assert count >= 1
    
    @pytest.mark.asyncio
    async def test_store_list_all(self, store, snippet):
        """Test list_all returns snippets."""
        await store.write(snippet)
        
        all_snippets = await store.list_all()
        
        assert len(all_snippets) >= 1


class TestSQLiteStore:
    """Tests for SQLiteStore."""
    
    @pytest.fixture
    def store(self):
        """Create SQLiteStore with temp database."""
        from bantz.memory.snippet_store import SQLiteStore
        
        # Create temp file
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        store = SQLiteStore(db_path=path)
        yield store
        
        # Cleanup
        os.unlink(path)
    
    @pytest.fixture
    def snippet(self):
        """Create test snippet."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        return MemorySnippet(
            content="SQLite test content",
            snippet_type=SnippetType.PROFILE,
            tags=["sqlite", "test"]
        )
    
    @pytest.mark.asyncio
    async def test_sqlite_write_read(self, store, snippet):
        """Test write and read cycle."""
        await store.write(snippet)
        
        result = await store.read(snippet.id)
        
        assert result is not None
        assert result.content == snippet.content
        assert result.snippet_type == snippet.snippet_type
    
    @pytest.mark.asyncio
    async def test_sqlite_search(self, store, snippet):
        """Test search functionality."""
        await store.write(snippet)
        
        results = await store.search("SQLite")
        
        assert len(results) >= 1
    
    @pytest.mark.asyncio
    async def test_sqlite_delete(self, store, snippet):
        """Test delete functionality."""
        await store.write(snippet)
        
        deleted = await store.delete(snippet.id)
        
        assert deleted == True
        assert await store.read(snippet.id) is None
    
    @pytest.mark.asyncio
    async def test_sqlite_persistence(self, snippet):
        """Test data persists across instances."""
        from bantz.memory.snippet_store import SQLiteStore
        
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        try:
            # Write with first instance
            store1 = SQLiteStore(db_path=path)
            await store1.write(snippet)
            
            # Read with second instance
            store2 = SQLiteStore(db_path=path)
            result = await store2.read(snippet.id)
            
            assert result is not None
            assert result.content == snippet.content
        finally:
            os.unlink(path)


class TestStoreFactories:
    """Tests for store factory functions."""
    
    def test_create_session_store(self):
        """Test session store factory."""
        from bantz.memory.snippet_store import create_session_store, InMemoryStore
        
        store = create_session_store()
        
        assert isinstance(store, InMemoryStore)
    
    def test_create_persistent_store(self):
        """Test persistent store factory."""
        from bantz.memory.snippet_store import create_persistent_store, SQLiteStore
        
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        try:
            store = create_persistent_store(db_path=path)
            assert isinstance(store, SQLiteStore)
        finally:
            os.unlink(path)
