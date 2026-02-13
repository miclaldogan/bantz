"""
Memory Manager for V2-4 Memory System (Issue #36).

Unified interface for memory operations:
- remember(): Store with policy check
- recall(): Retrieve relevant memories
- forget(): Delete memories
- cleanup(): Remove expired memories

Orchestrates stores, policy, and retriever.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bantz.memory.snippet import MemorySnippet, SnippetType, create_snippet
from bantz.memory.snippet_store import (
    SnippetStore,
    InMemoryStore,
    SQLiteStore,
    create_session_store,
    create_persistent_store,
)
from bantz.memory.write_policy import (
    WritePolicy,
    WriteDecision,
    PolicyResult,
    create_write_policy,
)
from bantz.memory.retrieval import (
    MemoryRetriever,
    RetrievalContext,
    create_retriever,
)


class MemoryManager:
    """
    Unified memory manager for the V2-4 system.
    
    Provides a simple interface for:
    - Storing memories with policy checks
    - Retrieving relevant memories
    - Managing memory lifecycle
    """
    
    def __init__(
        self,
        session_store: SnippetStore,
        profile_store: SnippetStore,
        episodic_store: SnippetStore,
        write_policy: WritePolicy,
        retriever: MemoryRetriever
    ):
        """
        Initialize memory manager.
        
        Args:
            session_store: Store for session memories
            profile_store: Store for profile memories
            episodic_store: Store for episodic memories
            write_policy: Policy for write decisions
            retriever: Retriever for recall operations
        """
        self._session_store = session_store
        self._profile_store = profile_store
        self._episodic_store = episodic_store
        self._write_policy = write_policy
        self._retriever = retriever
    
    def _get_store(self, snippet_type: SnippetType) -> SnippetStore:
        """Get the appropriate store for a snippet type."""
        stores = {
            SnippetType.SESSION: self._session_store,
            SnippetType.PROFILE: self._profile_store,
            SnippetType.EPISODIC: self._episodic_store,
        }
        return stores.get(snippet_type, self._session_store)
    
    async def remember(
        self,
        content: str,
        snippet_type: SnippetType = SnippetType.SESSION,
        source: Optional[str] = None,
        confidence: float = 1.0,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        bypass_policy: bool = False
    ) -> Optional[str]:
        """
        Remember something with policy check.
        
        Args:
            content: Content to remember
            snippet_type: Type of memory
            source: Source of the memory
            confidence: Confidence score
            tags: Tags for filtering
            metadata: Additional metadata
            bypass_policy: If True, skip policy check
            
        Returns:
            Snippet ID if stored, None if denied
        """
        # Check policy unless bypassed
        if not bypass_policy:
            result = self._write_policy.check(content, snippet_type)
            
            if result.decision == WriteDecision.DENY:
                return None
            
            # Use redacted content if redacted
            if result.decision == WriteDecision.REDACT and result.redacted_content:
                content = result.redacted_content
        
        # Create snippet
        snippet = create_snippet(
            content=content,
            snippet_type=snippet_type,
            source=source,
            confidence=confidence,
            tags=tags,
            metadata=metadata
        )
        
        # Write to appropriate store
        store = self._get_store(snippet_type)
        return await store.write(snippet)
    
    async def recall(
        self,
        query: str,
        limit: int = 5,
        snippet_types: Optional[List[SnippetType]] = None,
        min_confidence: float = 0.5
    ) -> List[MemorySnippet]:
        """
        Recall relevant memories.
        
        Args:
            query: Query to search for
            limit: Maximum results
            snippet_types: Types to search (None = all)
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of relevant snippets
        """
        context = RetrievalContext(
            query=query,
            max_snippets=limit,
            snippet_types=snippet_types,
            min_confidence=min_confidence
        )
        
        return await self._retriever.retrieve(context)
    
    async def forget(self, snippet_id: str) -> bool:
        """
        Forget a specific memory.
        
        Args:
            snippet_id: ID of snippet to forget
            
        Returns:
            True if forgotten, False if not found
        """
        # Try all stores
        for store in [self._session_store, self._profile_store, self._episodic_store]:
            if await store.delete(snippet_id):
                return True
        
        return False
    
    async def cleanup(self) -> int:
        """
        Cleanup expired memories from all stores.
        
        Returns:
            Total number of memories cleaned up
        """
        count = 0
        
        count += await self._session_store.cleanup_expired()
        count += await self._profile_store.cleanup_expired()
        count += await self._episodic_store.cleanup_expired()
        
        return count
    
    async def get_snippet(self, snippet_id: str) -> Optional[MemorySnippet]:
        """
        Get a specific snippet by ID.
        
        Args:
            snippet_id: Snippet ID
            
        Returns:
            Snippet if found, None otherwise
        """
        # Try all stores
        for store in [self._session_store, self._profile_store, self._episodic_store]:
            snippet = await store.read(snippet_id)
            if snippet:
                return snippet
        
        return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        session_count = await self._session_store.count()
        profile_count = await self._profile_store.count()
        episodic_count = await self._episodic_store.count()
        
        return {
            "session_count": session_count,
            "profile_count": profile_count,
            "episodic_count": episodic_count,
            "total_count": session_count + profile_count + episodic_count,
            "policy_patterns": self._write_policy.pattern_names,
        }
    
    async def remember_session(
        self,
        content: str,
        source: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """Shortcut for session memory."""
        return await self.remember(
            content=content,
            snippet_type=SnippetType.SESSION,
            source=source,
            **kwargs
        )
    
    async def remember_profile(
        self,
        content: str,
        source: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """Shortcut for profile memory."""
        return await self.remember(
            content=content,
            snippet_type=SnippetType.PROFILE,
            source=source,
            **kwargs
        )
    
    async def remember_episode(
        self,
        content: str,
        source: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """Shortcut for episodic memory."""
        return await self.remember(
            content=content,
            snippet_type=SnippetType.EPISODIC,
            source=source,
            **kwargs
        )
    
    @property
    def session_store(self) -> SnippetStore:
        """Get session store."""
        return self._session_store
    
    @property
    def profile_store(self) -> SnippetStore:
        """Get profile store."""
        return self._profile_store
    
    @property
    def episodic_store(self) -> SnippetStore:
        """Get episodic store."""
        return self._episodic_store
    
    @property
    def write_policy(self) -> WritePolicy:
        """Get write policy."""
        return self._write_policy
    
    @property
    def retriever(self) -> MemoryRetriever:
        """Get retriever."""
        return self._retriever


def create_memory_manager(
    session_store: Optional[SnippetStore] = None,
    profile_store: Optional[SnippetStore] = None,
    episodic_store: Optional[SnippetStore] = None,
    write_policy: Optional[WritePolicy] = None,
    db_path: Optional[str] = None,
    strict_policy: bool = False
) -> MemoryManager:
    """
    Factory function for creating memory manager.
    
    Args:
        session_store: Custom session store (default: InMemoryStore)
        profile_store: Custom profile store (default: SQLiteStore)
        episodic_store: Custom episodic store (default: SQLiteStore)
        write_policy: Custom write policy
        db_path: Path for SQLite database
        strict_policy: If True, use strict write policy
        
    Returns:
        Configured MemoryManager instance
    """
    # Create stores with defaults
    if session_store is None:
        session_store = create_session_store()
    
    if profile_store is None:
        profile_store = create_persistent_store(db_path, table_name="snippets_profile")
    
    if episodic_store is None:
        episodic_store = create_persistent_store(db_path, table_name="snippets_episodic")
    
    # Create policy
    if write_policy is None:
        write_policy = create_write_policy(strict_mode=strict_policy)
    
    # Create retriever
    retriever = create_retriever(
        session_store=session_store,
        profile_store=profile_store,
        episodic_store=episodic_store
    )
    
    return MemoryManager(
        session_store=session_store,
        profile_store=profile_store,
        episodic_store=episodic_store,
        write_policy=write_policy,
        retriever=retriever
    )
