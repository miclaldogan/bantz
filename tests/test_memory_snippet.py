"""
Tests for MemorySnippet types (Issue #36 - V2-4).

Tests:
- SnippetType enum values
- MemorySnippet creation
- TTL and expiry
- Serialization
"""

import pytest
from datetime import datetime, timedelta


class TestSnippetType:
    """Tests for SnippetType enum."""
    
    def test_snippet_types_exist(self):
        """Test all snippet types are defined."""
        from bantz.memory.snippet import SnippetType
        
        assert SnippetType.SESSION.value == "session"
        assert SnippetType.PROFILE.value == "profile"
        assert SnippetType.EPISODIC.value == "episodic"
    
    def test_snippet_type_persistence(self):
        """Test persistence property."""
        from bantz.memory.snippet import SnippetType
        
        assert SnippetType.SESSION.is_persistent == False
        assert SnippetType.PROFILE.is_persistent == True
        assert SnippetType.EPISODIC.is_persistent == True
    
    def test_snippet_type_priority(self):
        """Test priority ordering."""
        from bantz.memory.snippet import SnippetType
        
        assert SnippetType.SESSION.priority > SnippetType.PROFILE.priority
        assert SnippetType.PROFILE.priority > SnippetType.EPISODIC.priority
    
    def test_snippet_type_default_ttl(self):
        """Test default TTL values."""
        from bantz.memory.snippet import SnippetType
        
        assert SnippetType.SESSION.default_ttl == timedelta(hours=24)
        assert SnippetType.PROFILE.default_ttl is None
        assert SnippetType.EPISODIC.default_ttl == timedelta(days=90)


class TestMemorySnippet:
    """Tests for MemorySnippet dataclass."""
    
    def test_snippet_created_with_defaults(self):
        """Test snippet created with default values."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        snippet = MemorySnippet(content="Test content")
        
        assert snippet.content == "Test content"
        assert snippet.snippet_type == SnippetType.SESSION
        assert snippet.confidence == 1.0
        assert snippet.id is not None
        assert snippet.timestamp is not None
        assert snippet.tags == []
        assert snippet.metadata == {}
    
    def test_snippet_ttl_expiry(self):
        """Test TTL expiry detection."""
        from bantz.memory.snippet import MemorySnippet
        
        # Snippet with expired TTL
        snippet = MemorySnippet(
            content="Test",
            timestamp=datetime.now() - timedelta(hours=2),
            ttl=timedelta(hours=1)
        )
        
        assert snippet.is_expired() == True
    
    def test_snippet_no_ttl_never_expires(self):
        """Test snippet without TTL never expires."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        # Use PROFILE type which has no default TTL
        snippet = MemorySnippet(
            content="Test",
            snippet_type=SnippetType.PROFILE,
            timestamp=datetime.now() - timedelta(days=365),
            ttl=None
        )
        
        assert snippet.is_expired() == False
    
    def test_snippet_time_until_expiry(self):
        """Test time remaining until expiry."""
        from bantz.memory.snippet import MemorySnippet
        
        snippet = MemorySnippet(
            content="Test",
            timestamp=datetime.now(),
            ttl=timedelta(hours=1)
        )
        
        remaining = snippet.time_until_expiry()
        assert remaining is not None
        assert remaining.total_seconds() > 3500  # ~59 minutes
    
    def test_snippet_access_tracking(self):
        """Test access tracking."""
        from bantz.memory.snippet import MemorySnippet
        
        snippet = MemorySnippet(content="Test")
        assert snippet.access_count == 0
        
        snippet.access()
        
        assert snippet.access_count == 1
        assert snippet.last_accessed is not None
    
    def test_snippet_age(self):
        """Test age calculation."""
        from bantz.memory.snippet import MemorySnippet
        
        snippet = MemorySnippet(
            content="Test",
            timestamp=datetime.now() - timedelta(hours=2)
        )
        
        assert snippet.age.total_seconds() > 7100
        assert snippet.age_seconds > 7100
    
    def test_snippet_to_dict(self):
        """Test serialization to dict."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        snippet = MemorySnippet(
            content="Test",
            snippet_type=SnippetType.PROFILE,
            tags=["tag1"],
            metadata={"key": "value"}
        )
        
        data = snippet.to_dict()
        
        assert data["content"] == "Test"
        assert data["snippet_type"] == "profile"
        assert data["tags"] == ["tag1"]
        assert data["metadata"] == {"key": "value"}
    
    def test_snippet_from_dict(self):
        """Test deserialization from dict."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        data = {
            "id": "test-123",
            "content": "Test",
            "snippet_type": "episodic",
            "confidence": 0.8,
            "tags": ["important"],
        }
        
        snippet = MemorySnippet.from_dict(data)
        
        assert snippet.id == "test-123"
        assert snippet.content == "Test"
        assert snippet.snippet_type == SnippetType.EPISODIC
        assert snippet.confidence == 0.8
        assert snippet.tags == ["important"]


class TestCreateSnippet:
    """Tests for create_snippet factory."""
    
    def test_factory_creates_snippet(self):
        """Test factory function."""
        from bantz.memory.snippet import create_snippet, SnippetType
        
        snippet = create_snippet(
            content="Factory test",
            snippet_type=SnippetType.PROFILE,
            source="test",
            confidence=0.9,
            tags=["test"]
        )
        
        assert snippet.content == "Factory test"
        assert snippet.snippet_type == SnippetType.PROFILE
        assert snippet.source == "test"
        assert snippet.confidence == 0.9
        assert snippet.tags == ["test"]
    
    def test_factory_default_type(self):
        """Test factory uses SESSION as default type."""
        from bantz.memory.snippet import create_snippet, SnippetType
        
        snippet = create_snippet(content="Test")
        
        assert snippet.snippet_type == SnippetType.SESSION
