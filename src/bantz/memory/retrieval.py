"""
Memory Retrieval for V2-4 Memory System (Issue #36).

Provides:
- RetrievalContext: Query context for retrieval
- MemoryRetriever: Multi-store retrieval with ranking

Retrieves relevant memories from session/profile/episodic stores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from bantz.memory.snippet import MemorySnippet, SnippetType
from bantz.memory.snippet_store import SnippetStore


@dataclass
class RetrievalContext:
    """Context for memory retrieval."""
    
    query: str
    current_topic: Optional[str] = None
    max_snippets: int = 5
    include_expired: bool = False
    min_confidence: float = 0.5
    snippet_types: Optional[List[SnippetType]] = None
    
    def __post_init__(self):
        """Validate context."""
        self.max_snippets = max(1, min(100, self.max_snippets))
        self.min_confidence = max(0.0, min(1.0, self.min_confidence))


class MemoryRetriever:
    """
    Multi-store memory retriever.
    
    Searches across session, profile, and episodic stores
    and ranks results by relevance.
    """
    
    def __init__(
        self,
        session_store: SnippetStore,
        profile_store: SnippetStore,
        episodic_store: SnippetStore
    ):
        """
        Initialize retriever with stores.
        
        Args:
            session_store: Store for session memories
            profile_store: Store for profile memories
            episodic_store: Store for episodic memories
        """
        self._session_store = session_store
        self._profile_store = profile_store
        self._episodic_store = episodic_store
    
    async def retrieve(
        self,
        context: RetrievalContext
    ) -> List[MemorySnippet]:
        """
        Retrieve relevant snippets from all stores.
        
        Args:
            context: Retrieval context with query and filters
            
        Returns:
            Ranked list of relevant snippets
        """
        all_snippets: List[MemorySnippet] = []
        
        # Determine which stores to search
        stores_to_search = []
        
        if context.snippet_types is None:
            # Search all stores
            stores_to_search = [
                (self._session_store, SnippetType.SESSION),
                (self._profile_store, SnippetType.PROFILE),
                (self._episodic_store, SnippetType.EPISODIC),
            ]
        else:
            if SnippetType.SESSION in context.snippet_types:
                stores_to_search.append((self._session_store, SnippetType.SESSION))
            if SnippetType.PROFILE in context.snippet_types:
                stores_to_search.append((self._profile_store, SnippetType.PROFILE))
            if SnippetType.EPISODIC in context.snippet_types:
                stores_to_search.append((self._episodic_store, SnippetType.EPISODIC))
        
        # Search each store
        for store, stype in stores_to_search:
            snippets = await store.search(
                query=context.query,
                snippet_type=stype,
                limit=context.max_snippets
            )
            all_snippets.extend(snippets)
        
        # Filter by confidence
        filtered = [
            s for s in all_snippets
            if s.confidence >= context.min_confidence
        ]
        
        # Filter expired if not including them
        if not context.include_expired:
            filtered = [s for s in filtered if not s.is_expired()]
        
        # Rank snippets
        ranked = self.rank_snippets(filtered, context.query)
        
        # Return top N
        return ranked[:context.max_snippets]
    
    async def retrieve_for_job(
        self,
        job_request: str,
        max_snippets: int = 5
    ) -> List[MemorySnippet]:
        """
        Retrieve snippets relevant to a job request.
        
        Args:
            job_request: The job/task description
            max_snippets: Maximum snippets to return
            
        Returns:
            Relevant snippets for the job
        """
        context = RetrievalContext(
            query=job_request,
            max_snippets=max_snippets,
            min_confidence=0.5
        )
        
        return await self.retrieve(context)
    
    def rank_snippets(
        self,
        snippets: List[MemorySnippet],
        query: str
    ) -> List[MemorySnippet]:
        """
        Rank snippets by relevance to query.
        
        Ranking factors:
        - Text match quality
        - Snippet type priority
        - Confidence score
        - Recency
        
        Args:
            snippets: Snippets to rank
            query: Query to rank against
            
        Returns:
            Sorted list (highest relevance first)
        """
        def score_snippet(snippet: MemorySnippet) -> float:
            score = 0.0
            query_lower = query.lower()
            content_lower = snippet.content.lower()
            
            # Exact match bonus
            if query_lower in content_lower:
                score += 3.0
            
            # Word overlap
            query_words = set(query_lower.split())
            content_words = set(content_lower.split())
            overlap = len(query_words & content_words)
            score += overlap * 0.5
            
            # Type priority (session=3, profile=2, episodic=1)
            score += snippet.snippet_type.priority
            
            # Confidence
            score += snippet.confidence
            
            # Recency (newer = higher)
            age_hours = snippet.age_seconds / 3600
            recency_bonus = max(0, 2 - (age_hours / 24))  # Up to 2 points for recent
            score += recency_bonus
            
            # Access count bonus (frequently accessed = more relevant)
            score += min(snippet.access_count * 0.1, 1.0)
            
            return score
        
        # Sort by score (descending)
        return sorted(snippets, key=score_snippet, reverse=True)
    
    async def get_session_context(
        self,
        limit: int = 10
    ) -> List[MemorySnippet]:
        """Get recent session context."""
        return await self._session_store.list_all(limit=limit)
    
    async def get_user_profile(
        self,
        limit: int = 10
    ) -> List[MemorySnippet]:
        """Get user profile snippets."""
        return await self._profile_store.list_all(limit=limit)
    
    async def get_recent_episodes(
        self,
        limit: int = 10
    ) -> List[MemorySnippet]:
        """Get recent episodic memories."""
        return await self._episodic_store.list_all(limit=limit)


def create_retriever(
    session_store: SnippetStore,
    profile_store: SnippetStore,
    episodic_store: SnippetStore
) -> MemoryRetriever:
    """Factory for creating memory retriever."""
    return MemoryRetriever(
        session_store=session_store,
        profile_store=profile_store,
        episodic_store=episodic_store
    )
