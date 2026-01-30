"""
Tests for V2-5 Secrets Vault (Issue #37).
"""

import pytest
import tempfile
from pathlib import Path

from bantz.security.vault import (
    Secret,
    SecretType,
    SecretsVault,
    VaultError,
    EncryptionError,
    DecryptionError,
    SecretNotFoundError,
    create_secrets_vault,
)


class TestSecretType:
    """Tests for SecretType enum."""
    
    def test_secret_types_exist(self):
        """Test all secret types exist."""
        assert SecretType.API_KEY is not None
        assert SecretType.PASSWORD is not None
        assert SecretType.TOKEN is not None
        assert SecretType.CREDENTIAL is not None
        assert SecretType.SSH_KEY is not None
        assert SecretType.OTHER is not None
    
    def test_secret_type_values(self):
        """Test secret type string values."""
        assert SecretType.API_KEY.value == "api_key"
        assert SecretType.PASSWORD.value == "password"
        assert SecretType.TOKEN.value == "token"


class TestSecret:
    """Tests for Secret dataclass."""
    
    def test_create_secret(self):
        """Test creating secret."""
        secret = Secret(
            name="my_api_key",
            secret_type=SecretType.API_KEY,
            value="encrypted_value_here"
        )
        
        assert secret.name == "my_api_key"
        assert secret.secret_type == SecretType.API_KEY
    
    def test_secret_to_dict(self):
        """Test secret to_dict excludes value."""
        secret = Secret(
            name="test_secret",
            secret_type=SecretType.PASSWORD,
            value="super_secret",
            metadata={"service": "github"}
        )
        
        data = secret.to_dict()
        
        # Value should NOT be in dict for safety
        assert "value" not in data
        assert data["name"] == "test_secret"
        assert data["secret_type"] == "password"
        assert data["metadata"]["service"] == "github"


class TestSecretsVault:
    """Tests for SecretsVault."""
    
    def test_store_and_retrieve(self):
        """Test storing and retrieving a secret."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            vault.store("my_api_key", "sk-12345abcdef", SecretType.API_KEY)
            
            retrieved = vault.retrieve("my_api_key")
            assert retrieved == "sk-12345abcdef"
    
    def test_retrieve_nonexistent(self):
        """Test retrieving nonexistent secret."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            retrieved = vault.retrieve("nonexistent")
            assert retrieved is None
    
    def test_delete_secret(self):
        """Test deleting a secret."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            vault.store("to_delete", "secret_value")
            assert vault.delete("to_delete") is True
            assert vault.retrieve("to_delete") is None
    
    def test_delete_nonexistent(self):
        """Test deleting nonexistent secret."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            assert vault.delete("nonexistent") is False
    
    def test_list_names(self):
        """Test listing secret names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            vault.store("secret1", "value1")
            vault.store("secret2", "value2")
            vault.store("secret3", "value3")
            
            names = vault.list_names()
            assert len(names) == 3
            assert "secret1" in names
            assert "secret2" in names
            assert "secret3" in names
    
    def test_exists(self):
        """Test checking if secret exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            vault.store("exists", "value")
            
            assert vault.exists("exists") is True
            assert vault.exists("not_exists") is False
    
    def test_count(self):
        """Test counting secrets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            assert vault.count() == 0
            
            vault.store("s1", "v1")
            vault.store("s2", "v2")
            
            assert vault.count() == 2
    
    def test_clear(self):
        """Test clearing all secrets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            vault.store("s1", "v1")
            vault.store("s2", "v2")
            vault.store("s3", "v3")
            
            cleared = vault.clear()
            
            assert cleared == 3
            assert vault.count() == 0
    
    def test_metadata_storage(self):
        """Test storing metadata with secret."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = SecretsVault(storage_path=vault_path)
            
            metadata = {"service": "github", "created_by": "user1"}
            vault.store("api_key", "value", SecretType.API_KEY, metadata=metadata)
            
            retrieved_metadata = vault.get_metadata("api_key")
            assert retrieved_metadata["service"] == "github"
            assert retrieved_metadata["created_by"] == "user1"
    
    def test_encryption_decryption_cycle(self):
        """Test full encryption/decryption cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            key = b"0123456789abcdef0123456789abcdef"  # 32 bytes
            
            vault = SecretsVault(encryption_key=key, storage_path=vault_path)
            
            original = "super_secret_api_key_12345"
            vault.store("test", original)
            
            retrieved = vault.retrieve("test")
            assert retrieved == original
    
    def test_factory_function(self):
        """Test create_secrets_vault factory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.json"
            vault = create_secrets_vault(storage_path=vault_path)
            
            assert isinstance(vault, SecretsVault)
