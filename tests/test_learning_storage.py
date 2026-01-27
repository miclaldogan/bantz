"""
Tests for ProfileStorage.
"""

import json
import pytest
import tempfile
from pathlib import Path

from bantz.learning.profile import UserProfile
from bantz.learning.storage import (
    ProfileStorage,
    create_profile_storage,
)


class TestProfileStorageJSON:
    """Tests for JSON-based profile storage."""
    
    def test_create_storage(self):
        """Test creating storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            assert storage.storage_path == Path(tmpdir)
    
    def test_save_profile(self):
        """Test saving a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            profile = UserProfile()
            profile.update_app_preference("browser", 0.8)
            
            result = storage.save_profile("user1", profile)
            
            assert result is True
            
            # Check file exists
            file_path = Path(tmpdir) / "profiles" / "user1.json"
            assert file_path.exists()
    
    def test_load_profile(self):
        """Test loading a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            # Save first
            profile = UserProfile()
            profile.preferred_apps["browser"] = 0.8  # Set directly
            storage.save_profile("user1", profile)
            
            # Load
            loaded = storage.load_profile("user1")
            
            assert loaded is not None
            assert loaded.preferred_apps["browser"] == 0.8
    
    def test_load_nonexistent_profile(self):
        """Test loading nonexistent profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            loaded = storage.load_profile("unknown")
            
            assert loaded is None
    
    def test_delete_profile(self):
        """Test deleting a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            profile = UserProfile()
            storage.save_profile("user1", profile)
            
            result = storage.delete_profile("user1")
            
            assert result is True
            assert storage.load_profile("user1") is None
    
    def test_delete_nonexistent_profile(self):
        """Test deleting nonexistent profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            result = storage.delete_profile("unknown")
            
            assert result is False
    
    def test_list_profiles(self):
        """Test listing profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            storage.save_profile("user1", UserProfile())
            storage.save_profile("user2", UserProfile())
            storage.save_profile("user3", UserProfile())
            
            profiles = storage.list_profiles()
            
            assert len(profiles) == 3
            assert "user1" in profiles
            assert "user2" in profiles
            assert "user3" in profiles
    
    def test_profile_exists(self):
        """Test checking if profile exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            storage.save_profile("user1", UserProfile())
            
            assert storage.profile_exists("user1") is True
            assert storage.profile_exists("unknown") is False
    
    def test_save_learning_data(self):
        """Test saving learning data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            data = {"preferences": {"a": 0.5, "b": 0.3}}
            
            result = storage.save_learning_data("user1", "preferences", data)
            
            assert result is True
    
    def test_load_learning_data(self):
        """Test loading learning data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            data = {"preferences": {"a": 0.5, "b": 0.3}}
            storage.save_learning_data("user1", "preferences", data)
            
            loaded = storage.load_learning_data("user1", "preferences")
            
            assert loaded is not None
            assert loaded["preferences"]["a"] == 0.5
    
    def test_load_nonexistent_learning_data(self):
        """Test loading nonexistent learning data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            loaded = storage.load_learning_data("user1", "unknown")
            
            assert loaded is None


class TestProfileStorageSQLite:
    """Tests for SQLite-based profile storage."""
    
    def test_create_sqlite_storage(self):
        """Test creating SQLite storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            assert storage.storage_path.suffix == ".db"
    
    def test_save_profile_sqlite(self):
        """Test saving profile to SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            profile = UserProfile()
            profile.update_intent_preference("test", 0.7)
            
            result = storage.save_profile("user1", profile)
            
            assert result is True
    
    def test_load_profile_sqlite(self):
        """Test loading profile from SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            profile = UserProfile()
            profile.preferred_intents["test"] = 0.7  # Set directly
            storage.save_profile("user1", profile)
            
            loaded = storage.load_profile("user1")
            
            assert loaded is not None
            assert loaded.preferred_intents["test"] == 0.7
    
    def test_delete_profile_sqlite(self):
        """Test deleting profile from SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            storage.save_profile("user1", UserProfile())
            
            result = storage.delete_profile("user1")
            
            assert result is True
            assert storage.load_profile("user1") is None
    
    def test_list_profiles_sqlite(self):
        """Test listing profiles from SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            storage.save_profile("alice", UserProfile())
            storage.save_profile("bob", UserProfile())
            
            profiles = storage.list_profiles()
            
            assert len(profiles) == 2
            assert "alice" in profiles
            assert "bob" in profiles
    
    def test_learning_data_sqlite(self):
        """Test learning data with SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            data = {"q_values": {"a": 0.5}}
            storage.save_learning_data("user1", "bandit", data)
            
            loaded = storage.load_learning_data("user1", "bandit")
            
            assert loaded is not None
            assert loaded["q_values"]["a"] == 0.5


class TestBackupRestore:
    """Tests for backup and restore functionality."""
    
    def test_backup(self):
        """Test creating backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir) / "data")
            backup_path = Path(tmpdir) / "backups"
            
            # Create some data
            profile = UserProfile()
            profile.update_app_preference("test", 0.5)
            storage.save_profile("user1", profile)
            storage.save_learning_data("user1", "prefs", {"key": "value"})
            
            # Backup
            result = storage.backup(backup_path)
            
            assert result is True
            
            # Check backup file exists
            backup_files = list(backup_path.glob("backup_*.json"))
            assert len(backup_files) == 1
    
    def test_restore(self):
        """Test restoring from backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage1 = ProfileStorage(storage_path=Path(tmpdir) / "data1")
            storage2 = ProfileStorage(storage_path=Path(tmpdir) / "data2")
            backup_path = Path(tmpdir) / "backups"
            
            # Create data in storage1
            profile = UserProfile()
            profile.preferred_apps["browser"] = 0.9  # Set directly
            storage1.save_profile("user1", profile)
            
            # Backup storage1
            storage1.backup(backup_path)
            
            # Get backup file
            backup_file = list(backup_path.glob("backup_*.json"))[0]
            
            # Restore to storage2
            result = storage2.restore(backup_file)
            
            assert result is True
            
            # Verify data in storage2
            loaded = storage2.load_profile("user1")
            assert loaded is not None
            assert loaded.preferred_apps["browser"] == 0.9
    
    def test_backup_multiple_profiles(self):
        """Test backing up multiple profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir) / "data")
            backup_path = Path(tmpdir) / "backups"
            
            # Create multiple profiles
            for i in range(5):
                profile = UserProfile()
                storage.save_profile(f"user{i}", profile)
            
            # Backup
            storage.backup(backup_path)
            
            # Read backup
            backup_file = list(backup_path.glob("backup_*.json"))[0]
            with open(backup_file) as f:
                data = json.load(f)
            
            assert len(data["profiles"]) == 5


class TestStorageClose:
    """Tests for storage close functionality."""
    
    def test_close_json(self):
        """Test closing JSON storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(storage_path=Path(tmpdir))
            
            # Should not raise
            storage.close()
    
    def test_close_sqlite(self):
        """Test closing SQLite storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = ProfileStorage(
                storage_path=Path(tmpdir) / "profiles.db",
                use_sqlite=True,
            )
            
            storage.save_profile("test", UserProfile())
            
            # Close should work
            storage.close()
            
            # After close, operations should fail gracefully
            # (depending on implementation)


class TestFactory:
    """Tests for factory function."""
    
    def test_create_profile_storage(self):
        """Test factory function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = create_profile_storage(storage_path=Path(tmpdir))
            
            assert storage is not None
            assert isinstance(storage, ProfileStorage)
    
    def test_create_sqlite_storage(self):
        """Test factory with SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = create_profile_storage(
                storage_path=Path(tmpdir) / "test.db",
                use_sqlite=True,
            )
            
            assert storage is not None
