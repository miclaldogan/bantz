"""
Memory Store - Storage backends for V2-4 Memory System (Issue #36).

Provides:
- SnippetStore: Abstract base class for memory storage
- InMemoryStore: In-memory storage for session memories
- SQLiteStore: Persistent storage for profile/episodic memories

All stores support CRUD operations and cleanup of expired snippets.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from bantz.memory.snippet import MemorySnippet, SnippetType


class SnippetStore(ABC):
    """
    Abstract base class for memory snippet storage.
    
    Defines the interface for all storage backends.
    """
    
    @abstractmethod
    async def write(self, snippet: MemorySnippet) -> str:
        """
        Write a snippet to storage.
        
        Args:
            snippet: The memory snippet to store
            
        Returns:
            The snippet ID
        """
        pass
    
    @abstractmethod
    async def read(self, snippet_id: str) -> Optional[MemorySnippet]:
        """
        Read a snippet by ID.
        
        Args:
            snippet_id: The snippet ID
            
        Returns:
            The snippet if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query: str,
        snippet_type: Optional[SnippetType] = None,
        limit: int = 5
    ) -> List[MemorySnippet]:
        """
        Search snippets by query string.
        
        Args:
            query: Search query
            snippet_type: Optional type filter
            limit: Maximum results to return
            
        Returns:
            List of matching snippets
        """
        pass
    
    @abstractmethod
    async def delete(self, snippet_id: str) -> bool:
        """
        Delete a snippet by ID.
        
        Args:
            snippet_id: The snippet ID
            
        Returns:
            True if deleted, False if not found
        """
        pass
    
    @abstractmethod
    async def cleanup_expired(self) -> int:
        """
        Remove all expired snippets.
        
        Returns:
            Number of snippets removed
        """
        pass
    
    @abstractmethod
    async def list_all(self, limit: int = 100) -> List[MemorySnippet]:
        """
        List all snippets.
        
        Args:
            limit: Maximum results to return
            
        Returns:
            List of all snippets
        """
        pass
    
    @abstractmethod
    async def count(self) -> int:
        """
        Count total snippets in store.
        
        Returns:
            Total count
        """
        pass
    
    async def get_stats(self) -> Dict:
        """Get storage statistics."""
        return {
            "total_count": await self.count(),
            "store_type": self.__class__.__name__,
        }


class InMemoryStore(SnippetStore):
    """
    In-memory storage for session memories.
    
    Fast access, but cleared on restart.
    Thread-safe with locking.
    """
    
    def __init__(self):
        """Initialize in-memory store."""
        self._snippets: Dict[str, MemorySnippet] = {}
        self._lock = threading.RLock()
    
    async def write(self, snippet: MemorySnippet) -> str:
        """Write snippet to memory."""
        with self._lock:
            self._snippets[snippet.id] = snippet
            return snippet.id
    
    async def read(self, snippet_id: str) -> Optional[MemorySnippet]:
        """Read snippet from memory."""
        with self._lock:
            snippet = self._snippets.get(snippet_id)
            if snippet:
                snippet.access()
            return snippet
    
    async def search(
        self,
        query: str,
        snippet_type: Optional[SnippetType] = None,
        limit: int = 5
    ) -> List[MemorySnippet]:
        """Search snippets by query."""
        with self._lock:
            results = []
            query_lower = query.lower()
            
            for snippet in self._snippets.values():
                # Skip expired
                if snippet.is_expired():
                    continue
                
                # Type filter
                if snippet_type and snippet.snippet_type != snippet_type:
                    continue
                
                # Simple text matching
                if query_lower in snippet.content.lower():
                    results.append(snippet)
                    snippet.access()
                
                if len(results) >= limit:
                    break
            
            # Sort by timestamp (newest first)
            results.sort(key=lambda s: s.timestamp, reverse=True)
            return results[:limit]
    
    async def delete(self, snippet_id: str) -> bool:
        """Delete snippet from memory."""
        with self._lock:
            if snippet_id in self._snippets:
                del self._snippets[snippet_id]
                return True
            return False
    
    async def cleanup_expired(self) -> int:
        """Remove expired snippets."""
        with self._lock:
            expired_ids = [
                sid for sid, snippet in self._snippets.items()
                if snippet.is_expired()
            ]
            
            for sid in expired_ids:
                del self._snippets[sid]
            
            return len(expired_ids)
    
    async def list_all(self, limit: int = 100) -> List[MemorySnippet]:
        """List all snippets."""
        with self._lock:
            snippets = list(self._snippets.values())
            snippets.sort(key=lambda s: s.timestamp, reverse=True)
            return snippets[:limit]
    
    async def count(self) -> int:
        """Count snippets."""
        with self._lock:
            return len(self._snippets)
    
    async def clear(self) -> int:
        """Clear all snippets."""
        with self._lock:
            count = len(self._snippets)
            self._snippets.clear()
            return count


class SQLiteStore(SnippetStore):
    """
    SQLite-based persistent storage for profile/episodic memories.
    
    Data persists across restarts.
    Thread-safe with connection pooling.
    """
    
    def __init__(self, db_path: Optional[str] = None, table_name: str = "snippets"):
        """
        Initialize SQLite store.
        
        Args:
            db_path: Path to database file. Defaults to ~/.bantz/memory.db
            table_name: SQLite table name. Use distinct names for profile
                        vs episodic stores to prevent ID collisions.
        """
        if db_path is None:
            db_dir = Path.home() / ".bantz"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "memory.db")
        
        self._db_path = db_path
        self._table = table_name
        self._lock = threading.RLock()
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        tbl = self._table
        with self._get_connection() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {tbl} (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    snippet_type TEXT NOT NULL,
                    source TEXT,
                    timestamp TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    ttl_seconds REAL,
                    tags TEXT,
                    metadata TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT
                )
            """)
            
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{tbl}_type 
                ON {tbl}(snippet_type)
            """)
            
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{tbl}_timestamp 
                ON {tbl}(timestamp)
            """)
            
            conn.commit()
    
    async def write(self, snippet: MemorySnippet) -> str:
        """Write snippet to database."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(f"""
                    INSERT OR REPLACE INTO {self._table} 
                    (id, content, snippet_type, source, timestamp, 
                     confidence, ttl_seconds, tags, metadata, 
                     access_count, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    snippet.id,
                    snippet.content,
                    snippet.snippet_type.value,
                    snippet.source,
                    snippet.timestamp.isoformat(),
                    snippet.confidence,
                    snippet.ttl.total_seconds() if snippet.ttl else None,
                    json.dumps(snippet.tags),
                    json.dumps(snippet.metadata),
                    snippet.access_count,
                    snippet.last_accessed.isoformat() if snippet.last_accessed else None,
                ))
                conn.commit()
            
            return snippet.id
    
    def _row_to_snippet(self, row: sqlite3.Row) -> MemorySnippet:
        """Convert database row to MemorySnippet."""
        from datetime import timedelta
        
        ttl = None
        if row["ttl_seconds"]:
            ttl = timedelta(seconds=row["ttl_seconds"])
        
        last_accessed = None
        if row["last_accessed"]:
            last_accessed = datetime.fromisoformat(row["last_accessed"])
        
        return MemorySnippet(
            id=row["id"],
            content=row["content"],
            snippet_type=SnippetType(row["snippet_type"]),
            source=row["source"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            confidence=row["confidence"],
            ttl=ttl,
            tags=json.loads(row["tags"]) if row["tags"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            access_count=row["access_count"],
            last_accessed=last_accessed,
        )
    
    async def read(self, snippet_id: str) -> Optional[MemorySnippet]:
        """Read snippet from database."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    f"SELECT * FROM {self._table} WHERE id = ?",
                    (snippet_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    snippet = self._row_to_snippet(row)
                    snippet.access()
                    
                    # Update access info
                    conn.execute(f"""
                        UPDATE {self._table} 
                        SET access_count = ?, last_accessed = ?
                        WHERE id = ?
                    """, (snippet.access_count, snippet.last_accessed.isoformat(), snippet_id))
                    conn.commit()
                    
                    return snippet
                
                return None
    
    async def search(
        self,
        query: str,
        snippet_type: Optional[SnippetType] = None,
        limit: int = 5
    ) -> List[MemorySnippet]:
        """Search snippets by query."""
        with self._lock:
            with self._get_connection() as conn:
                sql = f"SELECT * FROM {self._table} WHERE content LIKE ?"
                params = [f"%{query}%"]
                
                if snippet_type:
                    sql += " AND snippet_type = ?"
                    params.append(snippet_type.value)
                
                sql += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
                
                snippets = []
                for row in rows:
                    snippet = self._row_to_snippet(row)
                    if not snippet.is_expired():
                        snippets.append(snippet)
                
                return snippets
    
    async def delete(self, snippet_id: str) -> bool:
        """Delete snippet from database."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    f"DELETE FROM {self._table} WHERE id = ?",
                    (snippet_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
    
    async def cleanup_expired(self) -> int:
        """Remove expired snippets."""
        with self._lock:
            # First, find expired snippets
            all_snippets = await self.list_all(limit=10000)
            expired_ids = [s.id for s in all_snippets if s.is_expired()]
            
            if not expired_ids:
                return 0
            
            with self._get_connection() as conn:
                placeholders = ",".join("?" * len(expired_ids))
                conn.execute(
                    f"DELETE FROM {self._table} WHERE id IN ({placeholders})",
                    expired_ids
                )
                conn.commit()
            
            return len(expired_ids)
    
    async def list_all(self, limit: int = 100) -> List[MemorySnippet]:
        """List all snippets."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    f"SELECT * FROM {self._table} ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                )
                rows = cursor.fetchall()
                return [self._row_to_snippet(row) for row in rows]
    
    async def count(self) -> int:
        """Count snippets."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {self._table}")
                return cursor.fetchone()[0]


def create_session_store() -> InMemoryStore:
    """Factory for creating session store."""
    return InMemoryStore()


def create_persistent_store(
    db_path: Optional[str] = None, table_name: str = "snippets"
) -> SQLiteStore:
    """Factory for creating persistent store."""
    return SQLiteStore(db_path=db_path, table_name=table_name)
