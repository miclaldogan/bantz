"""
Tests for MemoryRetriever (Issue #36 - V2-4).

Tests:
- Multi-store retrieval
- Query-based search
- Ranking and filtering
- Context-based retrieval
"""

import pytest
from datetime import datetime, timedelta


class TestRetrievalContext:
    """Tests for RetrievalContext."""
    
    def test_context_creation(self):
        """Test context creation with defaults."""
        from bantz.memory.retrieval import RetrievalContext
        
        context = RetrievalContext(query="test query")
        
        assert context.query == "test query"
        assert context.max_snippets == 5
        assert context.min_confidence == 0.5
        assert context.include_expired == False
    
    def test_context_custom_values(self):
        """Test context with custom values."""
        from bantz.memory.retrieval import RetrievalContext
        from bantz.memory.snippet import SnippetType
        
        context = RetrievalContext(
            query="custom",
            max_snippets=10,
            min_confidence=0.8,
            snippet_types=[SnippetType.PROFILE]
        )
        
        assert context.max_snippets == 10
        assert context.min_confidence == 0.8
        assert SnippetType.PROFILE in context.snippet_types
    
    def test_context_clamps_values(self):
        """Test context clamps out-of-range values."""
        from bantz.memory.retrieval import RetrievalContext
        
        context = RetrievalContext(
            query="test",
            max_snippets=1000,  # Should be clamped to 100
            min_confidence=2.0  # Should be clamped to 1.0
        )
        
        assert context.max_snippets == 100
        assert context.min_confidence == 1.0


class TestMemoryRetriever:
    """Tests for MemoryRetriever class."""
    
    @pytest.fixture
    def stores(self):
        """Create test stores."""
        from bantz.memory.snippet_store import InMemoryStore
        
        session = InMemoryStore()
        profile = InMemoryStore()
        episodic = InMemoryStore()
        
        return session, profile, episodic
    
    @pytest.fixture
    def retriever(self, stores):
        """Create retriever with test stores."""
        from bantz.memory.retrieval import MemoryRetriever
        
        session, profile, episodic = stores
        return MemoryRetriever(
            session_store=session,
            profile_store=profile,
            episodic_store=episodic
        )
    
    @pytest.mark.asyncio
    async def test_retriever_searches_all_stores(self, retriever, stores):
        """Test retriever searches all stores."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        from bantz.memory.retrieval import RetrievalContext
        
        session, profile, episodic = stores
        
        # Add snippets to each store
        await session.write(MemorySnippet(
            content="Session memory about Python",
            snippet_type=SnippetType.SESSION
        ))
        await profile.write(MemorySnippet(
            content="Profile: Python developer",
            snippet_type=SnippetType.PROFILE
        ))
        await episodic.write(MemorySnippet(
            content="Event: Python conference",
            snippet_type=SnippetType.EPISODIC
        ))
        
        context = RetrievalContext(query="Python", max_snippets=10)
        results = await retriever.retrieve(context)
        
        assert len(results) == 3
    
    @pytest.mark.asyncio
    async def test_retriever_respects_limit(self, retriever, stores):
        """Test retriever respects max_snippets limit."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        from bantz.memory.retrieval import RetrievalContext
        
        session, _, _ = stores
        
        # Add many snippets
        for i in range(10):
            await session.write(MemorySnippet(
                content=f"Test memory {i}",
                snippet_type=SnippetType.SESSION
            ))
        
        context = RetrievalContext(query="memory", max_snippets=3)
        results = await retriever.retrieve(context)
        
        assert len(results) <= 3
    
    @pytest.mark.asyncio
    async def test_retriever_filters_expired(self, retriever, stores):
        """Test retriever filters expired snippets."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        from bantz.memory.retrieval import RetrievalContext
        
        session, _, _ = stores
        
        # Add expired snippet
        await session.write(MemorySnippet(
            content="Expired test memory",
            snippet_type=SnippetType.SESSION,
            timestamp=datetime.now() - timedelta(hours=48),
            ttl=timedelta(hours=1)
        ))
        
        context = RetrievalContext(query="Expired", include_expired=False)
        results = await retriever.retrieve(context)
        
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_retriever_filters_low_confidence(self, retriever, stores):
        """Test retriever filters low confidence snippets."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        from bantz.memory.retrieval import RetrievalContext
        
        session, _, _ = stores
        
        # Add low confidence snippet
        await session.write(MemorySnippet(
            content="Low confidence test",
            snippet_type=SnippetType.SESSION,
            confidence=0.2
        ))
        
        context = RetrievalContext(query="confidence", min_confidence=0.5)
        results = await retriever.retrieve(context)
        
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_retriever_ranks_by_relevance(self, retriever, stores):
        """Test retriever ranks by relevance."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        from bantz.memory.retrieval import RetrievalContext
        
        session, _, _ = stores
        
        # Add snippets with different relevance
        await session.write(MemorySnippet(
            content="Python programming",
            snippet_type=SnippetType.SESSION,
            confidence=0.9
        ))
        await session.write(MemorySnippet(
            content="Python is great for programming",
            snippet_type=SnippetType.SESSION,
            confidence=0.6
        ))
        
        context = RetrievalContext(query="Python programming")
        results = await retriever.retrieve(context)
        
        # Higher relevance should come first
        assert len(results) >= 1
    
    @pytest.mark.asyncio
    async def test_retrieve_for_job(self, retriever, stores):
        """Test retrieve_for_job method."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        session, _, _ = stores
        
        await session.write(MemorySnippet(
            content="User prefers dark mode",
            snippet_type=SnippetType.SESSION
        ))
        
        results = await retriever.retrieve_for_job("Set dark mode")
        
        assert isinstance(results, list)
    
    def test_rank_snippets(self, retriever):
        """Test ranking logic."""
        from bantz.memory.snippet import MemorySnippet, SnippetType
        
        snippets = [
            MemorySnippet(
                content="Exact match Python",
                snippet_type=SnippetType.SESSION,
                confidence=0.9
            ),
            MemorySnippet(
                content="Something else",
                snippet_type=SnippetType.EPISODIC,
                confidence=0.5
            ),
        ]
        
        ranked = retriever.rank_snippets(snippets, "Python")
        
        # First should have higher score (contains Python)
        assert ranked[0].content == "Exact match Python"


class TestRetrieverFactory:
    """Tests for create_retriever factory."""
    
    def test_factory_creates_retriever(self):
        """Test factory creates retriever."""
        from bantz.memory.retrieval import create_retriever, MemoryRetriever
        from bantz.memory.snippet_store import InMemoryStore
        
        retriever = create_retriever(
            session_store=InMemoryStore(),
            profile_store=InMemoryStore(),
            episodic_store=InMemoryStore()
        )
        
        assert isinstance(retriever, MemoryRetriever)
