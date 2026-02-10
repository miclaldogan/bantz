"""
Secrets Vault for V2-5 (Issue #37).

Encrypted storage for sensitive data:
- API keys
- Passwords
- Tokens
- Credentials

Uses Fernet symmetric encryption for security.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Issue #692: cryptography is mandatory — base64 is NOT encryption.
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    raise RuntimeError(
        "The 'cryptography' package is required for the secrets vault. "
        "Install it with: pip install cryptography"
    )


class SecretType(Enum):
    """Types of secrets that can be stored."""
    
    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    CREDENTIAL = "credential"
    CERTIFICATE = "certificate"
    SSH_KEY = "ssh_key"
    OTHER = "other"


@dataclass
class Secret:
    """A stored secret."""
    
    name: str
    secret_type: SecretType
    value: str  # Encrypted value
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (without value)."""
        return {
            "name": self.name,
            "secret_type": self.secret_type.value,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "metadata": self.metadata,
        }


class VaultError(Exception):
    """Base exception for vault errors."""
    pass


class EncryptionError(VaultError):
    """Error during encryption."""
    pass


class DecryptionError(VaultError):
    """Error during decryption."""
    pass


class SecretNotFoundError(VaultError):
    """Secret not found in vault."""
    pass


class SecretsVault:
    """
    Encrypted secrets vault.
    
    Stores secrets with Fernet symmetric encryption.
    Requires the ``cryptography`` package — will fail fast on import
    if it is not installed.
    """
    
    def __init__(
        self,
        encryption_key: Optional[bytes] = None,
        storage_path: Optional[Path] = None
    ):
        """
        Initialize secrets vault.
        
        Args:
            encryption_key: 32-byte key for encryption. Generated if not provided.
            storage_path: Path to store secrets. Defaults to ~/.bantz/vault.json
        """
        if storage_path is None:
            storage_path = Path.home() / ".bantz" / "vault.json"
        
        self._storage_path = storage_path
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate or use provided key
        if encryption_key is None:
            encryption_key = self._get_or_create_key()
        
        self._key = encryption_key
        
        # Initialize Fernet (always available — cryptography is mandatory)
        try:
            # Ensure key is valid Fernet key (32 bytes, base64 encoded)
            if len(encryption_key) == 32:
                fernet_key = base64.urlsafe_b64encode(encryption_key)
            elif len(encryption_key) == 44:  # Already base64
                fernet_key = encryption_key
            else:
                # Hash to 32 bytes
                fernet_key = base64.urlsafe_b64encode(
                    hashlib.sha256(encryption_key).digest()
                )
            self._fernet = Fernet(fernet_key)
        except Exception as e:
            raise EncryptionError(
                f"Failed to initialize Fernet encryption: {e}. "
                f"Key length: {len(encryption_key)}"
            )
        
        self._secrets: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        
        self._load()
    
    def _get_or_create_key(self) -> bytes:
        """Get existing key or create new one."""
        key_path = self._storage_path.parent / ".vault_key"
        
        if key_path.exists():
            try:
                with open(key_path, "rb") as f:
                    return f.read()
            except IOError as e:
                raise VaultError(
                    f"Vault key file exists but cannot be read: {key_path} — {e}"
                ) from e
        
        # Generate new key
        key = os.urandom(32)
        
        try:
            with open(key_path, "wb") as f:
                f.write(key)
            # Set restrictive permissions
            os.chmod(key_path, 0o600)
        except IOError as e:
            raise VaultError(
                f"Vault key could not be written to {key_path}: {e}. "
                "Without a persisted key, secrets will be lost on restart."
            ) from e
        
        return key
    
    def _load(self) -> None:
        """Load secrets from storage."""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r") as f:
                    self._secrets = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._secrets = {}
    
    def _save(self) -> None:
        """Save secrets to storage."""
        try:
            fd = os.open(
                str(self._storage_path),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                json.dump(self._secrets, f, indent=2)
        except IOError:
            pass
    
    def _encrypt(self, value: str) -> str:
        """Encrypt a value using Fernet."""
        try:
            encrypted = self._fernet.encrypt(value.encode())
            return encrypted.decode()
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")
    
    def _decrypt(self, encrypted: str) -> str:
        """Decrypt a value using Fernet."""
        try:
            decrypted = self._fernet.decrypt(encrypted.encode())
            return decrypted.decode()
        except InvalidToken:
            raise DecryptionError("Invalid encryption key or corrupted data")
        except Exception as e:
            raise DecryptionError(f"Decryption failed: {e}")
    
    def store(
        self,
        name: str,
        value: str,
        secret_type: SecretType = SecretType.OTHER,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Store a secret.
        
        Args:
            name: Unique name for the secret
            value: Secret value to store
            secret_type: Type of secret
            metadata: Optional metadata
        """
        with self._lock:
            encrypted = self._encrypt(value)
            
            self._secrets[name] = {
                "value": encrypted,
                "secret_type": secret_type.value,
                "created_at": datetime.now().isoformat(),
                "last_accessed": None,
                "metadata": metadata or {},
            }
            
            self._save()
    
    def retrieve(self, name: str) -> Optional[str]:
        """
        Retrieve a secret value.
        
        Args:
            name: Name of the secret
            
        Returns:
            Decrypted value or None if not found
        """
        with self._lock:
            if name not in self._secrets:
                return None
            
            data = self._secrets[name]
            
            # Update last accessed
            data["last_accessed"] = datetime.now().isoformat()
            self._save()
            
            return self._decrypt(data["value"])
    
    def delete(self, name: str) -> bool:
        """
        Delete a secret.
        
        Args:
            name: Name of the secret
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if name not in self._secrets:
                return False
            
            del self._secrets[name]
            self._save()
            return True
    
    def list_names(self) -> List[str]:
        """List all secret names (not values)."""
        with self._lock:
            return list(self._secrets.keys())
    
    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a secret."""
        with self._lock:
            if name not in self._secrets:
                return None
            return self._secrets[name].get("metadata", {})
    
    def exists(self, name: str) -> bool:
        """Check if a secret exists."""
        with self._lock:
            return name in self._secrets
    
    def count(self) -> int:
        """Get number of stored secrets."""
        with self._lock:
            return len(self._secrets)
    
    def clear(self) -> int:
        """Clear all secrets."""
        with self._lock:
            count = len(self._secrets)
            self._secrets.clear()
            self._save()
            return count


def create_secrets_vault(
    encryption_key: Optional[bytes] = None,
    storage_path: Optional[Path] = None
) -> SecretsVault:
    """Factory for creating secrets vault."""
    return SecretsVault(
        encryption_key=encryption_key,
        storage_path=storage_path
    )
