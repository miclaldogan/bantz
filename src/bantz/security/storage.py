"""
Encrypted Storage.

Provides secure, encrypted storage for sensitive data like:
- API keys
- Passwords
- Personal information
- Configuration secrets

Uses Fernet symmetric encryption (AES-128-CBC).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from datetime import datetime
import logging
import json
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


class KeyNotFoundError(StorageError):
    """Raised when a key is not found in storage."""
    pass


class DecryptionError(StorageError):
    """Raised when decryption fails."""
    pass


class EncryptionKeyError(StorageError):
    """Raised when there's a problem with the encryption key."""
    pass


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class StoredItem:
    """Metadata about a stored item."""
    
    key: str
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    
    def is_expired(self) -> bool:
        """Check if item has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


# =============================================================================
# Secure Storage
# =============================================================================


class SecureStorage:
    """
    Encrypted storage for sensitive data.
    
    Uses Fernet symmetric encryption for data protection.
    Data is stored in an SQLite database with encrypted values.
    
    Example:
        storage = SecureStorage()
        
        # Store sensitive data
        storage.store("api_key", "sk-secret-key-12345")
        storage.store("user_data", {"email": "user@example.com", "token": "..."})
        
        # Retrieve data
        api_key = storage.retrieve("api_key")
        
        # Delete data
        storage.delete("api_key")
    """
    
    DEFAULT_KEY_PATH = Path.home() / ".config" / "bantz" / ".key"
    DEFAULT_DB_PATH = Path.home() / ".config" / "bantz" / "secure.db"
    
    def __init__(
        self,
        key_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
        auto_create_key: bool = True,
    ):
        """
        Initialize secure storage.
        
        Args:
            key_path: Path to encryption key file
            db_path: Path to SQLite database
            auto_create_key: Automatically create key if not exists
        """
        self.key_path = Path(key_path) if key_path else self.DEFAULT_KEY_PATH
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self._auto_create_key = auto_create_key
        
        self._fernet = None
        self._lock = threading.Lock()
        self._initialized = False
    
    def _ensure_initialized(self) -> None:
        """Ensure storage is initialized."""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._fernet = self._load_or_create_key()
            self._init_database()
            self._initialized = True
    
    def _load_or_create_key(self):
        """Load existing key or create new one."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise StorageError(
                "cryptography package not available. "
                "Install with: pip install cryptography"
            )
        
        if self.key_path.exists():
            try:
                key = self.key_path.read_bytes()
                return Fernet(key)
            except Exception as e:
                raise EncryptionKeyError(f"Failed to load encryption key: {e}")
        
        if not self._auto_create_key:
            raise EncryptionKeyError(f"Encryption key not found: {self.key_path}")
        
        # Generate new key
        key = Fernet.generate_key()
        
        # Create directory with secure permissions
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write key with restricted permissions
        self.key_path.write_bytes(key)
        
        # Set file permissions (read/write only for owner)
        try:
            os.chmod(self.key_path, 0o600)
        except Exception as e:
            logger.warning(f"Could not set key file permissions: {e}")
        
        logger.info(f"Created new encryption key at {self.key_path}")
        return Fernet(key)
    
    def _init_database(self) -> None:
        """Initialize SQLite database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS secure_storage (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    tags TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at 
                ON secure_storage(expires_at)
            """)
            conn.commit()
        finally:
            conn.close()
    
    def store(
        self,
        key: str,
        value: Any,
        expires_in: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        """
        Store encrypted value.
        
        Args:
            key: Storage key
            value: Value to store (will be JSON serialized)
            expires_in: Expiration time in seconds (optional)
            tags: Tags for categorization (optional)
        """
        self._ensure_initialized()
        
        # Serialize and encrypt
        data = json.dumps(value).encode("utf-8")
        encrypted = self._fernet.encrypt(data)
        
        now = datetime.now()
        expires_at = None
        if expires_in is not None:
            from datetime import timedelta
            expires_at = now + timedelta(seconds=expires_in)
        
        tags_json = json.dumps(tags or [])
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT OR REPLACE INTO secure_storage 
                (key, value, created_at, updated_at, expires_at, tags)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                key,
                encrypted,
                now.isoformat(),
                now.isoformat(),
                expires_at.isoformat() if expires_at else None,
                tags_json,
            ))
            conn.commit()
            logger.debug(f"Stored encrypted value for key: {key}")
        finally:
            conn.close()
    
    def retrieve(self, key: str, default: Any = None) -> Any:
        """
        Retrieve and decrypt value.
        
        Args:
            key: Storage key
            default: Default value if not found
            
        Returns:
            Decrypted value or default
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute("""
                SELECT value, expires_at FROM secure_storage WHERE key = ?
            """, (key,))
            row = cursor.fetchone()
            
            if row is None:
                return default
            
            encrypted, expires_at_str = row
            
            # Check expiration
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now() > expires_at:
                    # Delete expired entry
                    conn.execute("DELETE FROM secure_storage WHERE key = ?", (key,))
                    conn.commit()
                    return default
            
            # Decrypt
            try:
                data = self._fernet.decrypt(encrypted)
                return json.loads(data.decode("utf-8"))
            except Exception as e:
                raise DecryptionError(f"Failed to decrypt value for key '{key}': {e}")
                
        finally:
            conn.close()
    
    def delete(self, key: str) -> bool:
        """
        Delete stored value.
        
        Args:
            key: Storage key
            
        Returns:
            True if deleted, False if not found
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute("""
                DELETE FROM secure_storage WHERE key = ?
            """, (key,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug(f"Deleted key: {key}")
            return deleted
        finally:
            conn.close()
    
    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.retrieve(key, default=None) is not None
    
    def list_keys(self, tag: Optional[str] = None) -> List[str]:
        """
        List all stored keys.
        
        Args:
            tag: Filter by tag (optional)
            
        Returns:
            List of keys
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            if tag:
                # Filter by tag
                cursor = conn.execute("""
                    SELECT key, tags, expires_at FROM secure_storage
                """)
                keys = []
                for row in cursor:
                    key, tags_json, expires_at_str = row
                    tags = json.loads(tags_json) if tags_json else []
                    if tag in tags:
                        # Check expiration
                        if expires_at_str:
                            if datetime.now() > datetime.fromisoformat(expires_at_str):
                                continue
                        keys.append(key)
                return keys
            else:
                cursor = conn.execute("""
                    SELECT key, expires_at FROM secure_storage
                """)
                keys = []
                for row in cursor:
                    key, expires_at_str = row
                    if expires_at_str:
                        if datetime.now() > datetime.fromisoformat(expires_at_str):
                            continue
                    keys.append(key)
                return keys
        finally:
            conn.close()
    
    def get_metadata(self, key: str) -> Optional[StoredItem]:
        """
        Get metadata about a stored item.
        
        Args:
            key: Storage key
            
        Returns:
            StoredItem or None
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute("""
                SELECT key, created_at, updated_at, expires_at, tags
                FROM secure_storage WHERE key = ?
            """, (key,))
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            key, created_at, updated_at, expires_at, tags_json = row
            
            return StoredItem(
                key=key,
                created_at=datetime.fromisoformat(created_at),
                updated_at=datetime.fromisoformat(updated_at),
                expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
                tags=json.loads(tags_json) if tags_json else [],
            )
        finally:
            conn.close()
    
    def cleanup_expired(self) -> int:
        """
        Delete all expired entries.
        
        Returns:
            Number of deleted entries
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute("""
                DELETE FROM secure_storage 
                WHERE expires_at IS NOT NULL AND expires_at < ?
            """, (now,))
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired entries")
            return deleted
        finally:
            conn.close()
    
    def rotate_key(self, new_key_path: Optional[Path] = None) -> None:
        """
        Rotate encryption key.
        
        Creates a new key and re-encrypts all data.
        
        Args:
            new_key_path: Path for new key (optional, uses same path if not provided)
        """
        self._ensure_initialized()
        
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise StorageError("cryptography package not available")
        
        # Read all data with current key
        all_data = {}
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute("""
                SELECT key, value, created_at, updated_at, expires_at, tags
                FROM secure_storage
            """)
            for row in cursor:
                key, encrypted, created_at, updated_at, expires_at, tags = row
                try:
                    data = self._fernet.decrypt(encrypted)
                    all_data[key] = {
                        "value": json.loads(data.decode("utf-8")),
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "expires_at": expires_at,
                        "tags": tags,
                    }
                except Exception as e:
                    logger.warning(f"Could not decrypt key '{key}' during rotation: {e}")
        finally:
            conn.close()
        
        # Generate new key
        new_key = Fernet.generate_key()
        new_fernet = Fernet(new_key)
        
        # Write new key
        target_path = new_key_path or self.key_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(new_key)
        try:
            os.chmod(target_path, 0o600)
        except Exception:
            pass
        
        # Re-encrypt all data
        conn = sqlite3.connect(str(self.db_path))
        try:
            for key, item in all_data.items():
                data = json.dumps(item["value"]).encode("utf-8")
                encrypted = new_fernet.encrypt(data)
                
                conn.execute("""
                    UPDATE secure_storage 
                    SET value = ?, updated_at = ?
                    WHERE key = ?
                """, (encrypted, datetime.now().isoformat(), key))
            
            conn.commit()
        finally:
            conn.close()
        
        # Update fernet instance
        self._fernet = new_fernet
        self.key_path = target_path
        
        logger.info(f"Rotated encryption key, re-encrypted {len(all_data)} entries")
    
    def clear_all(self) -> int:
        """
        Delete all stored data.
        
        Returns:
            Number of deleted entries
        """
        self._ensure_initialized()
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute("DELETE FROM secure_storage")
            conn.commit()
            deleted = cursor.rowcount
            logger.info(f"Cleared all {deleted} entries from secure storage")
            return deleted
        finally:
            conn.close()


# =============================================================================
# Mock Implementation
# =============================================================================


class MockSecureStorage(SecureStorage):
    """Mock secure storage for testing."""
    
    def __init__(self, *args, **kwargs):
        # Don't call parent init - we use in-memory storage
        self._data: Dict[str, Any] = {}
        self._metadata: Dict[str, Dict] = {}
    
    def _ensure_initialized(self) -> None:
        """No initialization needed for mock."""
        pass
    
    def store(
        self,
        key: str,
        value: Any,
        expires_in: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Store in memory."""
        now = datetime.now()
        expires_at = None
        if expires_in is not None:
            from datetime import timedelta
            expires_at = now + timedelta(seconds=expires_in)
        
        self._data[key] = value
        self._metadata[key] = {
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "tags": tags or [],
        }
    
    def retrieve(self, key: str, default: Any = None) -> Any:
        """Retrieve from memory."""
        if key not in self._data:
            return default
        
        meta = self._metadata.get(key, {})
        expires_at = meta.get("expires_at")
        if expires_at and datetime.now() > expires_at:
            del self._data[key]
            del self._metadata[key]
            return default
        
        return self._data[key]
    
    def delete(self, key: str) -> bool:
        """Delete from memory."""
        if key in self._data:
            del self._data[key]
            if key in self._metadata:
                del self._metadata[key]
            return True
        return False
    
    def exists(self, key: str) -> bool:
        """Check if exists."""
        return self.retrieve(key) is not None
    
    def list_keys(self, tag: Optional[str] = None) -> List[str]:
        """List keys."""
        if tag:
            return [
                k for k, m in self._metadata.items()
                if tag in m.get("tags", [])
            ]
        return list(self._data.keys())
    
    def get_metadata(self, key: str) -> Optional[StoredItem]:
        """Get metadata."""
        if key not in self._metadata:
            return None
        
        meta = self._metadata[key]
        return StoredItem(
            key=key,
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
            expires_at=meta.get("expires_at"),
            tags=meta.get("tags", []),
        )
    
    def cleanup_expired(self) -> int:
        """Cleanup expired."""
        expired = []
        for key, meta in self._metadata.items():
            if meta.get("expires_at") and datetime.now() > meta["expires_at"]:
                expired.append(key)
        
        for key in expired:
            del self._data[key]
            del self._metadata[key]
        
        return len(expired)
    
    def clear_all(self) -> int:
        """Clear all."""
        count = len(self._data)
        self._data.clear()
        self._metadata.clear()
        return count
