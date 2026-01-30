"""
Memory Store - SQLite-backed long-term memory storage.

Provides persistent storage for memories with:
- Full CRUD operations
- Semantic search (keyword-based)
- Memory decay and forgetting
- Statistics and analytics
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from bantz.memory.types import (
    Memory,
    MemoryType,
    MemoryQuery,
    MemoryStats,
    ConversationMemory,
    TaskMemory,
    PreferenceMemory,
    FactMemory,
)


# Schema version for migrations
SCHEMA_VERSION = 1


@dataclass
class MemoryDecay:
    """Configuration for memory decay."""
    
    enabled: bool = True
    default_rate: float = 0.03  # Daily decay rate
    min_importance: float = 0.1  # Minimum importance before eligible for forgetting
    forget_threshold: float = 0.05  # Below this importance, memory can be forgotten
    protected_types: List[MemoryType] = field(default_factory=lambda: [
        MemoryType.FACT,
        MemoryType.PREFERENCE,
    ])
    max_age_days: int = 365  # Maximum age before forced review
    
    def should_protect(self, memory: Memory) -> bool:
        """Check if memory should be protected from forgetting."""
        return memory.type in self.protected_types
    
    def calculate_decay(self, memory: Memory, days: float) -> float:
        """Calculate decay amount for a memory."""
        if self.should_protect(memory):
            return 0.0
        
        rate = memory.type.decay_rate if hasattr(memory.type, 'decay_rate') else self.default_rate
        return rate * days


@dataclass
class MemoryIndex:
    """In-memory index for fast memory lookup."""
    
    # Indexes
    by_id: Dict[str, Memory] = field(default_factory=dict)
    by_type: Dict[MemoryType, List[str]] = field(default_factory=dict)
    by_tag: Dict[str, List[str]] = field(default_factory=dict)
    by_session: Dict[str, List[str]] = field(default_factory=dict)
    
    # Keyword index for search
    keywords: Dict[str, List[str]] = field(default_factory=dict)
    
    def add(self, memory: Memory) -> None:
        """Add a memory to the index."""
        self.by_id[memory.id] = memory
        
        # Type index
        if memory.type not in self.by_type:
            self.by_type[memory.type] = []
        self.by_type[memory.type].append(memory.id)
        
        # Tag index
        for tag in memory.tags:
            if tag not in self.by_tag:
                self.by_tag[tag] = []
            self.by_tag[tag].append(memory.id)
        
        # Session index
        if memory.session_id:
            if memory.session_id not in self.by_session:
                self.by_session[memory.session_id] = []
            self.by_session[memory.session_id].append(memory.id)
        
        # Keyword index
        words = memory.content.lower().split()
        for word in words:
            if len(word) >= 3:  # Only index words with 3+ chars
                if word not in self.keywords:
                    self.keywords[word] = []
                if memory.id not in self.keywords[word]:
                    self.keywords[word].append(memory.id)
    
    def remove(self, memory_id: str) -> Optional[Memory]:
        """Remove a memory from the index."""
        memory = self.by_id.pop(memory_id, None)
        if not memory:
            return None
        
        # Remove from type index
        if memory.type in self.by_type:
            self.by_type[memory.type] = [
                mid for mid in self.by_type[memory.type] if mid != memory_id
            ]
        
        # Remove from tag index
        for tag in memory.tags:
            if tag in self.by_tag:
                self.by_tag[tag] = [
                    mid for mid in self.by_tag[tag] if mid != memory_id
                ]
        
        # Remove from session index
        if memory.session_id and memory.session_id in self.by_session:
            self.by_session[memory.session_id] = [
                mid for mid in self.by_session[memory.session_id] if mid != memory_id
            ]
        
        # Remove from keyword index
        words = memory.content.lower().split()
        for word in words:
            if word in self.keywords:
                self.keywords[word] = [
                    mid for mid in self.keywords[word] if mid != memory_id
                ]
        
        return memory
    
    def search(self, query: str) -> List[str]:
        """Search for memory IDs matching query."""
        query_words = [w.lower() for w in query.split() if len(w) >= 3]
        if not query_words:
            return []
        
        # Find memories containing all query words
        result_sets = []
        for word in query_words:
            matching_ids = set()
            for keyword, ids in self.keywords.items():
                if word in keyword:
                    matching_ids.update(ids)
            result_sets.append(matching_ids)
        
        if not result_sets:
            return []
        
        # Intersection of all results
        result = result_sets[0]
        for s in result_sets[1:]:
            result &= s
        
        return list(result)
    
    def clear(self) -> None:
        """Clear all indexes."""
        self.by_id.clear()
        self.by_type.clear()
        self.by_tag.clear()
        self.by_session.clear()
        self.keywords.clear()


class MemoryStore:
    """
    SQLite-backed long-term memory storage.
    
    Provides persistent storage with:
    - CRUD operations
    - Semantic search
    - Memory decay
    - Session tracking
    """
    
    def __init__(
        self,
        db_path: str = "~/.bantz/memory.db",
        decay_config: Optional[MemoryDecay] = None,
        use_index: bool = True,
    ):
        """
        Initialize memory store.
        
        Args:
            db_path: Path to SQLite database
            decay_config: Configuration for memory decay
            use_index: Whether to use in-memory index
        """
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.decay = decay_config or MemoryDecay()
        self.use_index = use_index
        self.index = MemoryIndex() if use_index else None
        
        # Thread safety
        self._lock = threading.RLock()
        self._local = threading.local()
        
        # Initialize database
        self._init_db()
        
        # Load index if enabled
        if self.use_index:
            self._load_index()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Main memories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                last_accessed TEXT,
                tags TEXT,
                source TEXT DEFAULT 'user_interaction',
                session_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Indexes for efficient queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id)
        """)
        
        # Schema version table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            )
        """)
        
        # Insert or update version
        cursor.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        
        conn.commit()
    
    def _load_index(self) -> None:
        """Load all memories into in-memory index."""
        if not self.index:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories")
        
        for row in cursor.fetchall():
            memory = self._row_to_memory(row)
            self.index.add(memory)
    
    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        """Convert database row to Memory object."""
        memory_type = MemoryType(row["type"])
        
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        tags = json.loads(row["tags"]) if row["tags"] else []
        
        base_kwargs = {
            "id": row["id"],
            "timestamp": datetime.fromisoformat(row["timestamp"]),
            "type": memory_type,
            "content": row["content"],
            "metadata": metadata,
            "importance": row["importance"],
            "access_count": row["access_count"],
            "last_accessed": datetime.fromisoformat(row["last_accessed"]) if row["last_accessed"] else None,
            "tags": tags,
            "source": row["source"],
            "session_id": row["session_id"],
        }
        
        # Create appropriate subclass based on type
        if memory_type == MemoryType.CONVERSATION:
            return ConversationMemory(
                **base_kwargs,
                user_message=metadata.get("user_message", ""),
                assistant_response=metadata.get("assistant_response", ""),
                topic=metadata.get("topic", ""),
                sentiment=metadata.get("sentiment", 0.0),
            )
        elif memory_type == MemoryType.TASK:
            return TaskMemory(
                **base_kwargs,
                task_description=metadata.get("task_description", ""),
                steps=metadata.get("steps", []),
                success=metadata.get("success", True),
                duration_seconds=metadata.get("duration_seconds", 0.0),
            )
        elif memory_type == MemoryType.PREFERENCE:
            return PreferenceMemory(
                **base_kwargs,
                preference_key=metadata.get("preference_key", ""),
                preference_value=metadata.get("preference_value"),
                confidence=metadata.get("confidence", 0.5),
            )
        elif memory_type == MemoryType.FACT:
            return FactMemory(
                **base_kwargs,
                fact_category=metadata.get("fact_category", ""),
                fact_value=metadata.get("fact_value", ""),
                fact_source=metadata.get("fact_source", "user_stated"),
            )
        else:
            return Memory(**base_kwargs)
    
    def store(self, memory: Memory) -> str:
        """
        Store a new memory.
        
        Args:
            memory: Memory to store
            
        Returns:
            Memory ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO memories 
                (id, timestamp, type, content, metadata, importance, 
                 access_count, last_accessed, tags, source, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory.id,
                memory.timestamp.isoformat(),
                memory.type.value,
                memory.content,
                json.dumps(memory.metadata),
                memory.importance,
                memory.access_count,
                memory.last_accessed.isoformat() if memory.last_accessed else None,
                json.dumps(memory.tags),
                memory.source,
                memory.session_id,
            ))
            
            conn.commit()
            
            # Update index
            if self.index:
                self.index.add(memory)
            
            return memory.id
    
    def get(self, memory_id: str) -> Optional[Memory]:
        """
        Get a memory by ID.
        
        Args:
            memory_id: Memory ID
            
        Returns:
            Memory if found, None otherwise
        """
        # Try index first
        if self.index and memory_id in self.index.by_id:
            return self.index.by_id[memory_id]
        
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        
        if row:
            return self._row_to_memory(row)
        return None
    
    def recall(
        self,
        query: str,
        limit: int = 5,
        types: Optional[List[MemoryType]] = None,
        min_importance: float = 0.0,
    ) -> List[Memory]:
        """
        Recall relevant memories using keyword search.
        
        Args:
            query: Search query
            limit: Maximum number of results
            types: Filter by memory types
            min_importance: Minimum importance threshold
            
        Returns:
            List of relevant memories
        """
        with self._lock:
            # Use index for initial search
            candidate_ids = []
            if self.index:
                candidate_ids = self.index.search(query)
            
            if candidate_ids and self.index:
                # Get memories from index
                memories = [
                    self.index.by_id[mid]
                    for mid in candidate_ids
                    if mid in self.index.by_id
                ]
            else:
                # Fall back to database search
                conn = self._get_connection()
                cursor = conn.cursor()
                
                sql = "SELECT * FROM memories WHERE content LIKE ? AND importance >= ?"
                params: List[Any] = [f"%{query}%", min_importance]
                
                if types:
                    type_placeholders = ",".join(["?" for _ in types])
                    sql += f" AND type IN ({type_placeholders})"
                    params.extend([t.value for t in types])
                
                cursor.execute(sql, params)
                memories = [self._row_to_memory(row) for row in cursor.fetchall()]
            
            # Filter by types and importance
            filtered = []
            for memory in memories:
                if types and memory.type not in types:
                    continue
                if memory.importance < min_importance:
                    continue
                filtered.append(memory)
            
            # Sort by relevance score
            scored = [(m, m.relevance_score(query)) for m in filtered]
            scored.sort(key=lambda x: x[1], reverse=True)
            
            # Access the recalled memories (reinforcement)
            result = []
            for memory, _ in scored[:limit]:
                memory.access()
                self._update_access(memory)
                result.append(memory)
            
            return result
    
    def _update_access(self, memory: Memory) -> None:
        """Update memory access in database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE memories 
            SET access_count = ?, last_accessed = ?, importance = ?
            WHERE id = ?
        """, (
            memory.access_count,
            memory.last_accessed.isoformat() if memory.last_accessed else None,
            memory.importance,
            memory.id,
        ))
        conn.commit()
    
    def get_recent(
        self,
        type: Optional[MemoryType] = None,
        limit: int = 10,
        session_id: Optional[str] = None,
    ) -> List[Memory]:
        """
        Get recent memories.
        
        Args:
            type: Filter by memory type
            limit: Maximum number of results
            session_id: Filter by session
            
        Returns:
            List of recent memories
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        sql = "SELECT * FROM memories WHERE 1=1"
        params: List[Any] = []
        
        if type:
            sql += " AND type = ?"
            params.append(type.value)
        
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        return [self._row_to_memory(row) for row in cursor.fetchall()]
    
    def query(self, query: MemoryQuery) -> List[Memory]:
        """
        Query memories with complex filters.
        
        Args:
            query: Query parameters
            
        Returns:
            List of matching memories
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        sql = "SELECT * FROM memories WHERE 1=1"
        params: List[Any] = []
        
        # Type filter
        if query.types:
            type_placeholders = ",".join(["?" for _ in query.types])
            sql += f" AND type IN ({type_placeholders})"
            params.extend([t.value for t in query.types])
        
        # Time range
        if query.since:
            sql += " AND timestamp >= ?"
            params.append(query.since.isoformat())
        if query.until:
            sql += " AND timestamp <= ?"
            params.append(query.until.isoformat())
        
        # Importance filter
        sql += " AND importance >= ? AND importance <= ?"
        params.extend([query.min_importance, query.max_importance])
        
        # Session filter
        if query.session_id:
            sql += " AND session_id = ?"
            params.append(query.session_id)
        
        # Text search
        if query.query:
            sql += " AND content LIKE ?"
            params.append(f"%{query.query}%")
        
        # Sorting
        sort_column = {
            "relevance": "importance",
            "timestamp": "timestamp",
            "importance": "importance",
            "access_count": "access_count",
        }.get(query.sort_by, "timestamp")
        
        order = "DESC" if query.sort_desc else "ASC"
        sql += f" ORDER BY {sort_column} {order}"
        
        # Pagination
        sql += " LIMIT ? OFFSET ?"
        params.extend([query.limit, query.offset])
        
        cursor.execute(sql, params)
        memories = [self._row_to_memory(row) for row in cursor.fetchall()]
        
        # Additional filtering (tags)
        if query.tags:
            memories = [
                m for m in memories
                if any(tag in m.tags for tag in query.tags)
            ]
        
        return memories
    
    def update_importance(self, memory_id: str, delta: float) -> bool:
        """
        Update memory importance.
        
        Args:
            memory_id: Memory ID
            delta: Change in importance
            
        Returns:
            True if updated, False if not found
        """
        with self._lock:
            memory = self.get(memory_id)
            if not memory:
                return False
            
            memory.importance = max(0.0, min(1.0, memory.importance + delta))
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE memories SET importance = ? WHERE id = ?",
                (memory.importance, memory_id)
            )
            conn.commit()
            
            # Update index
            if self.index and memory_id in self.index.by_id:
                self.index.by_id[memory_id].importance = memory.importance
            
            return True
    
    def delete(self, memory_id: str) -> bool:
        """
        Delete a memory.
        
        Args:
            memory_id: Memory ID
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            
            # Update index
            if self.index:
                self.index.remove(memory_id)
            
            return deleted
    
    def forget(
        self,
        older_than_days: int = 90,
        importance_below: float = 0.2,
        dry_run: bool = False,
    ) -> List[str]:
        """
        Forget old, unimportant memories.
        
        Args:
            older_than_days: Only forget memories older than this
            importance_below: Only forget memories with importance below this
            dry_run: If True, only return IDs without deleting
            
        Returns:
            List of forgotten memory IDs
        """
        cutoff = datetime.now() - timedelta(days=older_than_days)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Find candidates
        cursor.execute("""
            SELECT id, type FROM memories 
            WHERE timestamp < ? AND importance < ?
        """, (cutoff.isoformat(), importance_below))
        
        candidates = cursor.fetchall()
        
        # Filter out protected types
        to_forget = []
        for row in candidates:
            memory_type = MemoryType(row["type"])
            if not self.decay.should_protect(Memory(type=memory_type)):
                to_forget.append(row["id"])
        
        if not dry_run:
            for memory_id in to_forget:
                self.delete(memory_id)
        
        return to_forget
    
    def apply_decay(self, days: float = 1.0) -> int:
        """
        Apply importance decay to all memories.
        
        Args:
            days: Number of days of decay to apply
            
        Returns:
            Number of memories updated
        """
        if not self.decay.enabled:
            return 0
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get all memories
        cursor.execute("SELECT * FROM memories")
        rows = cursor.fetchall()
        
        updated = 0
        for row in rows:
            memory = self._row_to_memory(row)
            decay_amount = self.decay.calculate_decay(memory, days)
            
            if decay_amount > 0:
                new_importance = max(0.0, memory.importance - decay_amount)
                cursor.execute(
                    "UPDATE memories SET importance = ? WHERE id = ?",
                    (new_importance, memory.id)
                )
                updated += 1
                
                # Update index
                if self.index and memory.id in self.index.by_id:
                    self.index.by_id[memory.id].importance = new_importance
        
        conn.commit()
        return updated
    
    def get_stats(self) -> MemoryStats:
        """Get memory store statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Total count
        cursor.execute("SELECT COUNT(*) as count FROM memories")
        total = cursor.fetchone()["count"]
        
        # Count by type
        cursor.execute("""
            SELECT type, COUNT(*) as count 
            FROM memories 
            GROUP BY type
        """)
        by_type = {row["type"]: row["count"] for row in cursor.fetchall()}
        
        # Average importance
        cursor.execute("SELECT AVG(importance) as avg FROM memories")
        avg_row = cursor.fetchone()
        avg_importance = avg_row["avg"] if avg_row["avg"] else 0.0
        
        # Time range
        cursor.execute("""
            SELECT MIN(timestamp) as oldest, MAX(timestamp) as newest
            FROM memories
        """)
        time_row = cursor.fetchone()
        oldest = datetime.fromisoformat(time_row["oldest"]) if time_row["oldest"] else None
        newest = datetime.fromisoformat(time_row["newest"]) if time_row["newest"] else None
        
        # Total accesses
        cursor.execute("SELECT SUM(access_count) as total FROM memories")
        access_row = cursor.fetchone()
        total_accesses = access_row["total"] if access_row["total"] else 0
        
        # Storage size
        storage_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        
        return MemoryStats(
            total_memories=total,
            by_type=by_type,
            avg_importance=avg_importance,
            oldest_memory=oldest,
            newest_memory=newest,
            total_accesses=total_accesses,
            storage_bytes=storage_bytes,
        )
    
    def clear(self) -> int:
        """
        Clear all memories.
        
        Returns:
            Number of memories deleted
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM memories")
            count = cursor.fetchone()["count"]
            cursor.execute("DELETE FROM memories")
            conn.commit()
            
            if self.index:
                self.index.clear()
            
            return count
    
    def export_json(self, filepath: str) -> int:
        """
        Export all memories to JSON file.
        
        Args:
            filepath: Output file path
            
        Returns:
            Number of memories exported
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories ORDER BY timestamp")
        
        memories = []
        for row in cursor.fetchall():
            memory = self._row_to_memory(row)
            memories.append(memory.to_dict())
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(memories, f, indent=2, ensure_ascii=False)
        
        return len(memories)
    
    def import_json(self, filepath: str) -> int:
        """
        Import memories from JSON file.
        
        Args:
            filepath: Input file path
            
        Returns:
            Number of memories imported
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        count = 0
        for item in data:
            memory = Memory.from_dict(item)
            self.store(memory)
            count += 1
        
        return count
    
    def close(self) -> None:
        """Close database connection."""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            del self._local.connection
