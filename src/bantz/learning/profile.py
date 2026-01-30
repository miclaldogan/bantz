"""
User Profile module.

Stores learned user preferences, behavior patterns, and personality traits.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class UserProfile:
    """
    Öğrenilen kullanıcı profili.
    
    Kullanıcının tercihlerini, davranış kalıplarını ve
    kişilik özelliklerini saklar.
    """
    
    id: str = ""
    """Unique profile ID."""
    
    created_at: datetime = field(default_factory=datetime.now)
    """Profile creation time."""
    
    updated_at: datetime = field(default_factory=datetime.now)
    """Last update time."""
    
    # ============================================================
    # Temel Tercihler
    # ============================================================
    
    preferred_apps: Dict[str, float] = field(default_factory=dict)
    """App -> affinity score (0.0 - 1.0)."""
    
    preferred_intents: Dict[str, float] = field(default_factory=dict)
    """Intent -> preference score (0.0 - 1.0)."""
    
    active_hours: Dict[int, float] = field(default_factory=dict)
    """Hour (0-23) -> activity level (0.0 - 1.0)."""
    
    # ============================================================
    # Davranış Kalıpları
    # ============================================================
    
    command_sequences: List[Tuple[str, str, float]] = field(default_factory=list)
    """(action_a, action_b, probability) - A'dan sonra B olasılığı."""
    
    time_patterns: Dict[str, Dict[int, float]] = field(default_factory=dict)
    """Intent -> hour -> frequency."""
    
    frequent_commands: Dict[str, int] = field(default_factory=dict)
    """Command -> usage count."""
    
    # ============================================================
    # Kişilik Özellikleri (Inferred)
    # ============================================================
    
    verbosity_preference: float = 0.5
    """0 = kısa yanıtlar, 1 = detaylı yanıtlar."""
    
    confirmation_preference: float = 0.5
    """0 = direkt yap, 1 = her şeyi onayla."""
    
    exploration_tendency: float = 0.5
    """0 = aynı şeyler, 1 = yeni şeyler dener."""
    
    speed_preference: float = 0.5
    """0 = yavaş/dikkatli, 1 = hızlı/direkt."""
    
    formality_preference: float = 0.5
    """0 = informal, 1 = formal."""
    
    # ============================================================
    # Meta Veriler
    # ============================================================
    
    total_interactions: int = 0
    """Total number of interactions."""
    
    successful_interactions: int = 0
    """Number of successful interactions."""
    
    last_interaction_at: Optional[datetime] = None
    """Last interaction time."""
    
    custom_data: Dict[str, Any] = field(default_factory=dict)
    """Custom user data."""
    
    def __post_init__(self):
        """Generate ID if empty."""
        if not self.id:
            self.id = str(uuid.uuid4())
    
    @property
    def success_rate(self) -> float:
        """Get interaction success rate."""
        if self.total_interactions == 0:
            return 0.0
        return self.successful_interactions / self.total_interactions
    
    @property
    def is_new_user(self) -> bool:
        """Check if user is new (< 10 interactions)."""
        return self.total_interactions < 10
    
    @property
    def experience_level(self) -> str:
        """Get user experience level."""
        if self.total_interactions < 10:
            return "new"
        elif self.total_interactions < 100:
            return "intermediate"
        else:
            return "experienced"
    
    def get_top_apps(self, n: int = 5) -> List[Tuple[str, float]]:
        """Get top N preferred apps."""
        sorted_apps = sorted(
            self.preferred_apps.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_apps[:n]
    
    def get_top_intents(self, n: int = 5) -> List[Tuple[str, float]]:
        """Get top N preferred intents."""
        sorted_intents = sorted(
            self.preferred_intents.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_intents[:n]
    
    def get_active_hours(self) -> List[int]:
        """Get hours with above-average activity."""
        if not self.active_hours:
            return list(range(9, 18))  # Default work hours
        
        avg = sum(self.active_hours.values()) / len(self.active_hours)
        return [h for h, level in self.active_hours.items() if level > avg]
    
    def get_sequence_probability(self, action_a: str, action_b: str) -> float:
        """Get probability of action_b following action_a."""
        for a, b, prob in self.command_sequences:
            if a == action_a and b == action_b:
                return prob
        return 0.0
    
    def update_app_preference(self, app: str, delta: float) -> None:
        """Update app preference score."""
        current = self.preferred_apps.get(app, 0.5)
        new_value = max(0.0, min(1.0, current + delta))
        self.preferred_apps[app] = new_value
        self.updated_at = datetime.now()
    
    def update_intent_preference(self, intent: str, delta: float) -> None:
        """Update intent preference score."""
        current = self.preferred_intents.get(intent, 0.5)
        new_value = max(0.0, min(1.0, current + delta))
        self.preferred_intents[intent] = new_value
        self.updated_at = datetime.now()
    
    def update_active_hour(self, hour: int) -> None:
        """Record activity at given hour."""
        current = self.active_hours.get(hour, 0.0)
        # Exponential moving average
        alpha = 0.1
        self.active_hours[hour] = current + alpha * (1.0 - current)
        self.updated_at = datetime.now()
    
    def record_command_sequence(self, action_a: str, action_b: str) -> None:
        """Record a command sequence."""
        # Find existing sequence
        for i, (a, b, prob) in enumerate(self.command_sequences):
            if a == action_a and b == action_b:
                # Increase probability
                new_prob = min(1.0, prob + 0.1)
                self.command_sequences[i] = (a, b, new_prob)
                self.updated_at = datetime.now()
                return
        
        # Add new sequence
        self.command_sequences.append((action_a, action_b, 0.1))
        self.updated_at = datetime.now()
    
    def record_interaction(self, success: bool = True) -> None:
        """Record an interaction."""
        self.total_interactions += 1
        if success:
            self.successful_interactions += 1
        self.last_interaction_at = datetime.now()
        self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "preferred_apps": self.preferred_apps,
            "preferred_intents": self.preferred_intents,
            "active_hours": self.active_hours,
            "command_sequences": self.command_sequences,
            "time_patterns": self.time_patterns,
            "frequent_commands": self.frequent_commands,
            "verbosity_preference": self.verbosity_preference,
            "confirmation_preference": self.confirmation_preference,
            "exploration_tendency": self.exploration_tendency,
            "speed_preference": self.speed_preference,
            "formality_preference": self.formality_preference,
            "total_interactions": self.total_interactions,
            "successful_interactions": self.successful_interactions,
            "last_interaction_at": self.last_interaction_at.isoformat() if self.last_interaction_at else None,
            "custom_data": self.custom_data,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Create from dictionary."""
        profile = cls(
            id=data.get("id", ""),
            preferred_apps=data.get("preferred_apps", {}),
            preferred_intents=data.get("preferred_intents", {}),
            active_hours={int(k): v for k, v in data.get("active_hours", {}).items()},
            command_sequences=[tuple(s) for s in data.get("command_sequences", [])],
            time_patterns=data.get("time_patterns", {}),
            frequent_commands=data.get("frequent_commands", {}),
            verbosity_preference=data.get("verbosity_preference", 0.5),
            confirmation_preference=data.get("confirmation_preference", 0.5),
            exploration_tendency=data.get("exploration_tendency", 0.5),
            speed_preference=data.get("speed_preference", 0.5),
            formality_preference=data.get("formality_preference", 0.5),
            total_interactions=data.get("total_interactions", 0),
            successful_interactions=data.get("successful_interactions", 0),
            custom_data=data.get("custom_data", {}),
        )
        
        if data.get("created_at"):
            profile.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at"):
            profile.updated_at = datetime.fromisoformat(data["updated_at"])
        if data.get("last_interaction_at"):
            profile.last_interaction_at = datetime.fromisoformat(data["last_interaction_at"])
        
        return profile
    
    def reset(self) -> None:
        """Reset profile to defaults."""
        self.preferred_apps.clear()
        self.preferred_intents.clear()
        self.active_hours.clear()
        self.command_sequences.clear()
        self.time_patterns.clear()
        self.frequent_commands.clear()
        self.verbosity_preference = 0.5
        self.confirmation_preference = 0.5
        self.exploration_tendency = 0.5
        self.speed_preference = 0.5
        self.formality_preference = 0.5
        self.total_interactions = 0
        self.successful_interactions = 0
        self.last_interaction_at = None
        self.custom_data.clear()
        self.updated_at = datetime.now()


class ProfileManager:
    """
    Manages user profiles.
    
    Handles profile loading, saving, and lifecycle.
    """
    
    def __init__(self, storage: Any = None):
        """
        Initialize the profile manager.
        
        Args:
            storage: Optional ProfileStorage instance.
        """
        self._storage = storage
        self._current_profile: Optional[UserProfile] = None
        self._profiles: Dict[str, UserProfile] = {}
    
    @property
    def current_profile(self) -> Optional[UserProfile]:
        """Get current active profile."""
        return self._current_profile
    
    def create_profile(self, profile_id: str = None) -> UserProfile:
        """
        Create a new profile.
        
        Args:
            profile_id: Optional custom profile ID.
            
        Returns:
            New UserProfile instance.
        """
        profile = UserProfile(id=profile_id or "")
        self._profiles[profile.id] = profile
        
        if self._current_profile is None:
            self._current_profile = profile
        
        return profile
    
    def get_profile(self, profile_id: str) -> Optional[UserProfile]:
        """
        Get profile by ID.
        
        Args:
            profile_id: Profile ID.
            
        Returns:
            Profile if found, None otherwise.
        """
        return self._profiles.get(profile_id)
    
    def set_current_profile(self, profile_id: str) -> bool:
        """
        Set current active profile.
        
        Args:
            profile_id: Profile ID to activate.
            
        Returns:
            True if successful, False if profile not found.
        """
        profile = self._profiles.get(profile_id)
        if profile:
            self._current_profile = profile
            return True
        return False
    
    def list_profiles(self) -> List[str]:
        """List all profile IDs."""
        return list(self._profiles.keys())
    
    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a profile.
        
        Args:
            profile_id: Profile ID to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            
            if self._current_profile and self._current_profile.id == profile_id:
                self._current_profile = None
            
            return True
        return False
    
    def reset_current_profile(self) -> None:
        """Reset current profile to defaults."""
        if self._current_profile:
            self._current_profile.reset()
    
    async def load_profiles(self) -> int:
        """
        Load profiles from storage.
        
        Returns:
            Number of profiles loaded.
        """
        if not self._storage:
            return 0
        
        loaded = await self._storage.load_all()
        for profile in loaded:
            self._profiles[profile.id] = profile
        
        # Set first as current if none set
        if not self._current_profile and self._profiles:
            self._current_profile = next(iter(self._profiles.values()))
        
        return len(loaded)
    
    async def save_profiles(self) -> int:
        """
        Save all profiles to storage.
        
        Returns:
            Number of profiles saved.
        """
        if not self._storage:
            return 0
        
        count = 0
        for profile in self._profiles.values():
            await self._storage.save(profile)
            count += 1
        
        return count
    
    async def save_current_profile(self) -> bool:
        """
        Save current profile to storage.
        
        Returns:
            True if saved, False if no current profile.
        """
        if not self._current_profile or not self._storage:
            return False
        
        await self._storage.save(self._current_profile)
        return True
    
    def export_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """
        Export profile as dictionary.
        
        Args:
            profile_id: Profile ID to export.
            
        Returns:
            Profile data dictionary, None if not found.
        """
        profile = self._profiles.get(profile_id)
        if profile:
            return profile.to_dict()
        return None
    
    def import_profile(self, data: Dict[str, Any]) -> UserProfile:
        """
        Import profile from dictionary.
        
        Args:
            data: Profile data dictionary.
            
        Returns:
            Imported UserProfile instance.
        """
        profile = UserProfile.from_dict(data)
        self._profiles[profile.id] = profile
        return profile


def create_profile_manager(storage: Any = None) -> ProfileManager:
    """
    Factory function to create a profile manager.
    
    Args:
        storage: Optional ProfileStorage instance.
        
    Returns:
        Configured ProfileManager instance.
    """
    return ProfileManager(storage=storage)
