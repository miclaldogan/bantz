"""
Profile Storage module.

Persistence layer for user profiles and learning data.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bantz.learning.profile import UserProfile


class ProfileStorage:
    """
    Storage backend for user profiles and learning data.
    
    Supports both JSON file storage and SQLite database.
    """
    
    # Default storage path
    DEFAULT_PATH = Path.home() / ".bantz" / "profiles"
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        use_sqlite: bool = False,
    ):
        """
        Initialize profile storage.
        
        Args:
            storage_path: Path for storage (directory or db file).
            use_sqlite: Whether to use SQLite instead of JSON files.
        """
        self._storage_path = storage_path or self.DEFAULT_PATH
        self._use_sqlite = use_sqlite
        self._db_connection: Optional[sqlite3.Connection] = None
        
        # Ensure storage path exists
        self._init_storage()
    
    @property
    def storage_path(self) -> Path:
        """Get storage path."""
        return self._storage_path
    
    def save_profile(self, user_id: str, profile: UserProfile) -> bool:
        """
        Save a user profile.
        
        Args:
            user_id: User identifier.
            profile: Profile to save.
            
        Returns:
            Whether save was successful.
        """
        try:
            if self._use_sqlite:
                return self._save_profile_sqlite(user_id, profile)
            else:
                return self._save_profile_json(user_id, profile)
        except Exception as e:
            print(f"Error saving profile: {e}")
            return False
    
    def load_profile(self, user_id: str) -> Optional[UserProfile]:
        """
        Load a user profile.
        
        Args:
            user_id: User identifier.
            
        Returns:
            Loaded profile or None.
        """
        try:
            if self._use_sqlite:
                return self._load_profile_sqlite(user_id)
            else:
                return self._load_profile_json(user_id)
        except Exception as e:
            print(f"Error loading profile: {e}")
            return None
    
    def delete_profile(self, user_id: str) -> bool:
        """
        Delete a user profile.
        
        Args:
            user_id: User identifier.
            
        Returns:
            Whether delete was successful.
        """
        try:
            if self._use_sqlite:
                return self._delete_profile_sqlite(user_id)
            else:
                return self._delete_profile_json(user_id)
        except Exception as e:
            print(f"Error deleting profile: {e}")
            return False
    
    def list_profiles(self) -> List[str]:
        """
        List all profile user IDs.
        
        Returns:
            List of user IDs.
        """
        try:
            if self._use_sqlite:
                return self._list_profiles_sqlite()
            else:
                return self._list_profiles_json()
        except Exception as e:
            print(f"Error listing profiles: {e}")
            return []
    
    def profile_exists(self, user_id: str) -> bool:
        """
        Check if a profile exists.
        
        Args:
            user_id: User identifier.
            
        Returns:
            Whether profile exists.
        """
        if self._use_sqlite:
            profiles = self._list_profiles_sqlite()
        else:
            profiles = self._list_profiles_json()
        
        return user_id in profiles
    
    def save_learning_data(
        self,
        user_id: str,
        data_type: str,
        data: Dict[str, Any],
    ) -> bool:
        """
        Save learning data (preferences, bandit stats, etc.).
        
        Args:
            user_id: User identifier.
            data_type: Type of data (e.g., 'preferences', 'bandit', 'temporal').
            data: Data to save.
            
        Returns:
            Whether save was successful.
        """
        try:
            if self._use_sqlite:
                return self._save_learning_data_sqlite(user_id, data_type, data)
            else:
                return self._save_learning_data_json(user_id, data_type, data)
        except Exception as e:
            print(f"Error saving learning data: {e}")
            return False
    
    def load_learning_data(
        self,
        user_id: str,
        data_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Load learning data.
        
        Args:
            user_id: User identifier.
            data_type: Type of data.
            
        Returns:
            Loaded data or None.
        """
        try:
            if self._use_sqlite:
                return self._load_learning_data_sqlite(user_id, data_type)
            else:
                return self._load_learning_data_json(user_id, data_type)
        except Exception as e:
            print(f"Error loading learning data: {e}")
            return None
    
    def backup(self, backup_path: Path) -> bool:
        """
        Create a backup of all profiles.
        
        Args:
            backup_path: Path for backup.
            
        Returns:
            Whether backup was successful.
        """
        try:
            backup_path.mkdir(parents=True, exist_ok=True)
            
            profiles = self.list_profiles()
            backup_data = {
                "timestamp": datetime.now().isoformat(),
                "profiles": {},
                "learning_data": {},
            }
            
            for user_id in profiles:
                profile = self.load_profile(user_id)
                if profile:
                    backup_data["profiles"][user_id] = profile.to_dict()
                
                # Backup learning data
                backup_data["learning_data"][user_id] = {}
                for data_type in ["preferences", "bandit", "temporal", "adaptive"]:
                    data = self.load_learning_data(user_id, data_type)
                    if data:
                        backup_data["learning_data"][user_id][data_type] = data
            
            backup_file = backup_path / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"Error creating backup: {e}")
            return False
    
    def restore(self, backup_file: Path) -> bool:
        """
        Restore profiles from backup.
        
        Args:
            backup_file: Backup file path.
            
        Returns:
            Whether restore was successful.
        """
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            # Restore profiles
            for user_id, profile_data in backup_data.get("profiles", {}).items():
                profile = UserProfile.from_dict(profile_data)
                self.save_profile(user_id, profile)
            
            # Restore learning data
            for user_id, learning_data in backup_data.get("learning_data", {}).items():
                for data_type, data in learning_data.items():
                    self.save_learning_data(user_id, data_type, data)
            
            return True
        except Exception as e:
            print(f"Error restoring backup: {e}")
            return False
    
    def close(self) -> None:
        """Close storage connections."""
        if self._db_connection:
            self._db_connection.close()
            self._db_connection = None
    
    def _init_storage(self) -> None:
        """Initialize storage backend."""
        if self._use_sqlite:
            self._init_sqlite()
        else:
            self._init_json_storage()
    
    def _init_json_storage(self) -> None:
        """Initialize JSON file storage."""
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (self._storage_path / "profiles").mkdir(exist_ok=True)
        (self._storage_path / "learning").mkdir(exist_ok=True)
    
    def _init_sqlite(self) -> None:
        """Initialize SQLite database."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self._storage_path.suffix != '.db':
            self._storage_path = self._storage_path / "profiles.db"
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._db_connection = sqlite3.connect(str(self._storage_path))
        cursor = self._db_connection.cursor()
        
        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_data (
                user_id TEXT NOT NULL,
                data_type TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, data_type)
            )
        """)
        
        self._db_connection.commit()
    
    # JSON storage methods
    
    def _save_profile_json(self, user_id: str, profile: UserProfile) -> bool:
        """Save profile to JSON file."""
        file_path = self._storage_path / "profiles" / f"{user_id}.json"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
        
        return True
    
    def _load_profile_json(self, user_id: str) -> Optional[UserProfile]:
        """Load profile from JSON file."""
        file_path = self._storage_path / "profiles" / f"{user_id}.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return UserProfile.from_dict(data)
    
    def _delete_profile_json(self, user_id: str) -> bool:
        """Delete profile JSON file."""
        file_path = self._storage_path / "profiles" / f"{user_id}.json"
        
        if file_path.exists():
            file_path.unlink()
            return True
        
        return False
    
    def _list_profiles_json(self) -> List[str]:
        """List profiles from JSON files."""
        profiles_dir = self._storage_path / "profiles"
        
        if not profiles_dir.exists():
            return []
        
        return [
            f.stem for f in profiles_dir.glob("*.json")
        ]
    
    def _save_learning_data_json(
        self,
        user_id: str,
        data_type: str,
        data: Dict[str, Any],
    ) -> bool:
        """Save learning data to JSON file."""
        user_dir = self._storage_path / "learning" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = user_dir / f"{data_type}.json"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return True
    
    def _load_learning_data_json(
        self,
        user_id: str,
        data_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Load learning data from JSON file."""
        file_path = self._storage_path / "learning" / user_id / f"{data_type}.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # SQLite storage methods
    
    def _save_profile_sqlite(self, user_id: str, profile: UserProfile) -> bool:
        """Save profile to SQLite."""
        if not self._db_connection:
            return False
        
        cursor = self._db_connection.cursor()
        
        cursor.execute(
            """
            INSERT OR REPLACE INTO profiles (user_id, data, updated_at)
            VALUES (?, ?, ?)
            """,
            (user_id, json.dumps(profile.to_dict()), datetime.now().isoformat()),
        )
        
        self._db_connection.commit()
        return True
    
    def _load_profile_sqlite(self, user_id: str) -> Optional[UserProfile]:
        """Load profile from SQLite."""
        if not self._db_connection:
            return None
        
        cursor = self._db_connection.cursor()
        cursor.execute("SELECT data FROM profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        data = json.loads(row[0])
        return UserProfile.from_dict(data)
    
    def _delete_profile_sqlite(self, user_id: str) -> bool:
        """Delete profile from SQLite."""
        if not self._db_connection:
            return False
        
        cursor = self._db_connection.cursor()
        cursor.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
        self._db_connection.commit()
        
        return cursor.rowcount > 0
    
    def _list_profiles_sqlite(self) -> List[str]:
        """List profiles from SQLite."""
        if not self._db_connection:
            return []
        
        cursor = self._db_connection.cursor()
        cursor.execute("SELECT user_id FROM profiles")
        
        return [row[0] for row in cursor.fetchall()]
    
    def _save_learning_data_sqlite(
        self,
        user_id: str,
        data_type: str,
        data: Dict[str, Any],
    ) -> bool:
        """Save learning data to SQLite."""
        if not self._db_connection:
            return False
        
        cursor = self._db_connection.cursor()
        
        cursor.execute(
            """
            INSERT OR REPLACE INTO learning_data (user_id, data_type, data, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, data_type, json.dumps(data), datetime.now().isoformat()),
        )
        
        self._db_connection.commit()
        return True
    
    def _load_learning_data_sqlite(
        self,
        user_id: str,
        data_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Load learning data from SQLite."""
        if not self._db_connection:
            return None
        
        cursor = self._db_connection.cursor()
        cursor.execute(
            "SELECT data FROM learning_data WHERE user_id = ? AND data_type = ?",
            (user_id, data_type),
        )
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return json.loads(row[0])


def create_profile_storage(
    storage_path: Optional[Path] = None,
    use_sqlite: bool = False,
) -> ProfileStorage:
    """
    Factory function to create a profile storage.
    
    Args:
        storage_path: Path for storage.
        use_sqlite: Whether to use SQLite.
        
    Returns:
        Configured ProfileStorage instance.
    """
    return ProfileStorage(
        storage_path=storage_path,
        use_sqlite=use_sqlite,
    )
