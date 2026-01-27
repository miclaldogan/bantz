"""
ASR Learning.

Learn from ASR corrections to improve accuracy:
- Record manual corrections
- Auto-correct common errors
- Track error patterns
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import logging
import sqlite3
import threading
import re

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Correction:
    """Record of an ASR correction."""
    
    raw: str
    corrected: str
    count: int
    first_seen: datetime
    last_seen: datetime
    
    @property
    def is_word_level(self) -> bool:
        """Check if this is a word-level correction."""
        return " " not in self.raw and " " not in self.corrected
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "raw": self.raw,
            "corrected": self.corrected,
            "count": self.count,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }


# =============================================================================
# ASR Learner
# =============================================================================


class ASRLearner:
    """
    Learn from ASR corrections to improve accuracy.
    
    Records corrections and can auto-correct based on learned patterns.
    All data stored locally for privacy.
    
    Example:
        learner = ASRLearner(Path("~/.bantz/corrections.db"))
        
        # Record a correction
        learner.record_correction("krom aç", "chrome aç")
        
        # Auto-correct future input
        corrected = learner.auto_correct("krom aç")  # Returns "chrome aç"
    """
    
    DEFAULT_DB_PATH = Path.home() / ".config" / "bantz" / "corrections.db"
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        min_confidence_count: int = 2,
    ):
        """
        Initialize ASR learner.
        
        Args:
            db_path: Path to SQLite database
            min_confidence_count: Minimum corrections before auto-applying
        """
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.min_confidence_count = min_confidence_count
        
        self._corrections: Dict[str, str] = {}
        self._lock = threading.Lock()
        
        self._init_db()
        self._load_corrections()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS corrections (
                    raw TEXT PRIMARY KEY,
                    corrected TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_count 
                ON corrections(count)
            """)
            conn.commit()
        finally:
            conn.close()
    
    def _load_corrections(self) -> None:
        """Load corrections into memory for fast lookup."""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                rows = conn.execute("""
                    SELECT raw, corrected FROM corrections 
                    WHERE count >= ?
                """, (self.min_confidence_count,)).fetchall()
                
                self._corrections = {raw: corrected for raw, corrected in rows}
                logger.debug(f"Loaded {len(self._corrections)} corrections")
            finally:
                conn.close()
    
    def record_correction(self, raw: str, corrected: str) -> bool:
        """
        Record a manual correction.
        
        Args:
            raw: Original ASR output
            corrected: User's correction
            
        Returns:
            True if new correction, False if updated existing
        """
        raw_lower = raw.lower().strip()
        corrected_lower = corrected.lower().strip()
        
        # Skip if identical
        if raw_lower == corrected_lower:
            return False
        
        now = datetime.now().isoformat()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Check if exists
                existing = conn.execute(
                    "SELECT count FROM corrections WHERE raw = ?",
                    (raw_lower,)
                ).fetchone()
                
                if existing:
                    conn.execute("""
                        UPDATE corrections 
                        SET count = count + 1, 
                            corrected = ?,
                            last_seen = ?
                        WHERE raw = ?
                    """, (corrected_lower, now, raw_lower))
                    is_new = False
                else:
                    conn.execute("""
                        INSERT INTO corrections (raw, corrected, count, first_seen, last_seen)
                        VALUES (?, ?, 1, ?, ?)
                    """, (raw_lower, corrected_lower, now, now))
                    is_new = True
                
                conn.commit()
                
                # Update cache if meets threshold
                new_count = (existing[0] + 1) if existing else 1
                if new_count >= self.min_confidence_count:
                    self._corrections[raw_lower] = corrected_lower
                
                logger.debug(f"Recorded correction: '{raw}' -> '{corrected}'")
                return is_new
                
            finally:
                conn.close()
    
    def auto_correct(self, text: str) -> str:
        """
        Apply learned corrections to text.
        
        Args:
            text: Text to correct
            
        Returns:
            Corrected text
        """
        if not text:
            return text
        
        text_lower = text.lower().strip()
        
        with self._lock:
            # Check full phrase first
            if text_lower in self._corrections:
                corrected = self._corrections[text_lower]
                # Preserve original case if possible
                if text[0].isupper():
                    corrected = corrected.capitalize()
                logger.debug(f"Auto-corrected phrase: '{text}' -> '{corrected}'")
                return corrected
            
            # Word-by-word correction
            words = text.split()
            corrected_words = []
            changed = False
            
            for word in words:
                word_lower = word.lower()
                if word_lower in self._corrections:
                    new_word = self._corrections[word_lower]
                    # Preserve case
                    if word[0].isupper():
                        new_word = new_word.capitalize()
                    corrected_words.append(new_word)
                    changed = True
                else:
                    corrected_words.append(word)
            
            if changed:
                result = " ".join(corrected_words)
                logger.debug(f"Auto-corrected words: '{text}' -> '{result}'")
                return result
            
            return text
    
    def get_common_errors(self, min_count: int = 3, limit: int = 50) -> List[Correction]:
        """
        Get most common ASR errors.
        
        Args:
            min_count: Minimum occurrences
            limit: Maximum results
            
        Returns:
            List of Correction objects
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                rows = conn.execute("""
                    SELECT raw, corrected, count, first_seen, last_seen
                    FROM corrections 
                    WHERE count >= ?
                    ORDER BY count DESC
                    LIMIT ?
                """, (min_count, limit)).fetchall()
                
                return [
                    Correction(
                        raw=row[0],
                        corrected=row[1],
                        count=row[2],
                        first_seen=datetime.fromisoformat(row[3]),
                        last_seen=datetime.fromisoformat(row[4]),
                    )
                    for row in rows
                ]
            finally:
                conn.close()
    
    def get_all_corrections(self) -> List[Correction]:
        """
        Get all recorded corrections.
        
        Returns:
            List of all corrections
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                rows = conn.execute("""
                    SELECT raw, corrected, count, first_seen, last_seen
                    FROM corrections 
                    ORDER BY count DESC
                """).fetchall()
                
                return [
                    Correction(
                        raw=row[0],
                        corrected=row[1],
                        count=row[2],
                        first_seen=datetime.fromisoformat(row[3]),
                        last_seen=datetime.fromisoformat(row[4]),
                    )
                    for row in rows
                ]
            finally:
                conn.close()
    
    def get_correction(self, raw: str) -> Optional[Correction]:
        """
        Get correction for specific input.
        
        Args:
            raw: Original text
            
        Returns:
            Correction or None
        """
        raw_lower = raw.lower().strip()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                row = conn.execute("""
                    SELECT raw, corrected, count, first_seen, last_seen
                    FROM corrections 
                    WHERE raw = ?
                """, (raw_lower,)).fetchone()
                
                if row:
                    return Correction(
                        raw=row[0],
                        corrected=row[1],
                        count=row[2],
                        first_seen=datetime.fromisoformat(row[3]),
                        last_seen=datetime.fromisoformat(row[4]),
                    )
                return None
            finally:
                conn.close()
    
    def delete_correction(self, raw: str) -> bool:
        """
        Delete a correction.
        
        Args:
            raw: Original text
            
        Returns:
            True if deleted
        """
        raw_lower = raw.lower().strip()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute(
                    "DELETE FROM corrections WHERE raw = ?",
                    (raw_lower,)
                )
                conn.commit()
                
                if cursor.rowcount > 0:
                    self._corrections.pop(raw_lower, None)
                    return True
                return False
            finally:
                conn.close()
    
    def import_corrections(self, corrections: List[Tuple[str, str]]) -> int:
        """
        Bulk import corrections.
        
        Args:
            corrections: List of (raw, corrected) tuples
            
        Returns:
            Number imported
        """
        count = 0
        for raw, corrected in corrections:
            if self.record_correction(raw, corrected):
                count += 1
        return count
    
    def export_corrections(self) -> List[Tuple[str, str, int]]:
        """
        Export all corrections.
        
        Returns:
            List of (raw, corrected, count) tuples
        """
        corrections = self.get_all_corrections()
        return [(c.raw, c.corrected, c.count) for c in corrections]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get learner statistics.
        
        Returns:
            Statistics dictionary
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                total = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
                active = conn.execute(
                    "SELECT COUNT(*) FROM corrections WHERE count >= ?",
                    (self.min_confidence_count,)
                ).fetchone()[0]
                total_uses = conn.execute("SELECT SUM(count) FROM corrections").fetchone()[0] or 0
                
                return {
                    "total_corrections": total,
                    "active_corrections": active,
                    "total_correction_uses": total_uses,
                    "min_confidence_count": self.min_confidence_count,
                }
            finally:
                conn.close()
    
    def clear_all(self) -> int:
        """
        Delete all corrections.
        
        Returns:
            Number deleted
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute("DELETE FROM corrections")
                conn.commit()
                self._corrections.clear()
                return cursor.rowcount
            finally:
                conn.close()


# =============================================================================
# Mock Implementation
# =============================================================================


class MockASRLearner(ASRLearner):
    """Mock ASR learner for testing."""
    
    def __init__(
        self,
        *args,
        min_confidence_count: int = 1,
        **kwargs,
    ):
        # Don't use database
        self.min_confidence_count = min_confidence_count
        self._corrections: Dict[str, str] = {}
        self._correction_counts: Dict[str, int] = {}
        self._correction_records: Dict[str, Correction] = {}
        self._lock = threading.Lock()
    
    def _init_db(self) -> None:
        """No database initialization needed."""
        pass
    
    def _load_corrections(self) -> None:
        """No loading needed."""
        pass
    
    def record_correction(self, raw: str, corrected: str) -> bool:
        """Record to memory."""
        raw_lower = raw.lower().strip()
        corrected_lower = corrected.lower().strip()
        
        if raw_lower == corrected_lower:
            return False
        
        now = datetime.now()
        
        with self._lock:
            if raw_lower in self._correction_records:
                record = self._correction_records[raw_lower]
                self._correction_records[raw_lower] = Correction(
                    raw=raw_lower,
                    corrected=corrected_lower,
                    count=record.count + 1,
                    first_seen=record.first_seen,
                    last_seen=now,
                )
                is_new = False
            else:
                self._correction_records[raw_lower] = Correction(
                    raw=raw_lower,
                    corrected=corrected_lower,
                    count=1,
                    first_seen=now,
                    last_seen=now,
                )
                is_new = True
            
            # Update cache
            new_count = self._correction_records[raw_lower].count
            if new_count >= self.min_confidence_count:
                self._corrections[raw_lower] = corrected_lower
            
            return is_new
    
    def get_all_corrections(self) -> List[Correction]:
        """Get all from memory."""
        with self._lock:
            return list(self._correction_records.values())
    
    def get_common_errors(self, min_count: int = 3, limit: int = 50) -> List[Correction]:
        """Get common errors from memory."""
        with self._lock:
            corrections = [
                c for c in self._correction_records.values()
                if c.count >= min_count
            ]
            return sorted(corrections, key=lambda c: c.count, reverse=True)[:limit]
    
    def get_correction(self, raw: str) -> Optional[Correction]:
        """Get correction from memory."""
        raw_lower = raw.lower().strip()
        with self._lock:
            return self._correction_records.get(raw_lower)
    
    def delete_correction(self, raw: str) -> bool:
        """Delete from memory."""
        raw_lower = raw.lower().strip()
        with self._lock:
            if raw_lower in self._correction_records:
                del self._correction_records[raw_lower]
                self._corrections.pop(raw_lower, None)
                return True
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get stats from memory."""
        with self._lock:
            total = len(self._correction_records)
            active = sum(
                1 for c in self._correction_records.values()
                if c.count >= self.min_confidence_count
            )
            total_uses = sum(c.count for c in self._correction_records.values())
            
            return {
                "total_corrections": total,
                "active_corrections": active,
                "total_correction_uses": total_uses,
                "min_confidence_count": self.min_confidence_count,
            }
    
    def clear_all(self) -> int:
        """Clear memory."""
        with self._lock:
            count = len(self._correction_records)
            self._corrections.clear()
            self._correction_records.clear()
            return count
