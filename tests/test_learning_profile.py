"""
Tests for UserProfile and ProfileManager.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from bantz.learning.profile import (
    UserProfile,
    ProfileManager,
    create_profile_manager,
)


class TestUserProfile:
    """Tests for UserProfile dataclass."""
    
    def test_create_default_profile(self):
        """Test creating a profile with defaults."""
        profile = UserProfile()
        
        assert profile.preferred_apps == {}
        assert profile.preferred_intents == {}
        assert profile.active_hours == {}
        assert profile.command_sequences == []
        assert profile.total_interactions == 0
        assert profile.successful_interactions == 0
    
    def test_success_rate_no_interactions(self):
        """Test success rate with no interactions."""
        profile = UserProfile()
        
        assert profile.success_rate == 0.0
    
    def test_success_rate_with_interactions(self):
        """Test success rate calculation."""
        profile = UserProfile(
            total_interactions=10,
            successful_interactions=7,
        )
        
        assert profile.success_rate == 0.7
    
    def test_is_new_user(self):
        """Test new user detection."""
        profile = UserProfile(total_interactions=5)
        assert profile.is_new_user is True
        
        profile2 = UserProfile(total_interactions=15)
        assert profile2.is_new_user is False
    
    def test_experience_level(self):
        """Test experience level calculation."""
        new_user = UserProfile(total_interactions=5)
        assert new_user.experience_level == "new"
        
        mid_user = UserProfile(total_interactions=50)
        assert mid_user.experience_level == "intermediate"
        
        advanced_user = UserProfile(total_interactions=150)
        assert advanced_user.experience_level == "experienced"
    
    def test_update_app_preference(self):
        """Test app preference update."""
        profile = UserProfile()
        
        # Default is 0.5, delta 0.5 -> 1.0
        profile.update_app_preference("browser", 0.5)
        assert profile.preferred_apps["browser"] == 1.0
        
        # Reset and test incremental
        profile.preferred_apps["editor"] = 0.3
        profile.update_app_preference("editor", 0.2)
        assert profile.preferred_apps["editor"] == 0.5
        
        # Test clamping at max
        profile.update_app_preference("browser", 0.5)
        assert profile.preferred_apps["browser"] == 1.0
    
    def test_update_intent_preference(self):
        """Test intent preference update."""
        profile = UserProfile()
        
        # Default is 0.5, delta 0.4 -> 0.9
        profile.update_intent_preference("open_app", 0.4)
        assert profile.preferred_intents["open_app"] == 0.9
    
    def test_update_active_hour(self):
        """Test active hour update."""
        profile = UserProfile()
        
        profile.update_active_hour(14)
        assert 14 in profile.active_hours
        assert profile.active_hours[14] > 0
    
    def test_record_command_sequence(self):
        """Test command sequence recording."""
        profile = UserProfile()
        
        profile.record_command_sequence("open_browser", "search")
        assert len(profile.command_sequences) == 1
        assert profile.command_sequences[0][0] == "open_browser"
        assert profile.command_sequences[0][1] == "search"
        assert profile.command_sequences[0][2] == 0.1  # Initial probability
        
        # Record same sequence again
        profile.record_command_sequence("open_browser", "search")
        assert profile.command_sequences[0][2] == 0.2  # Probability increased by 0.1
    
    def test_get_sequence_probability(self):
        """Test getting sequence probability."""
        profile = UserProfile()
        profile.record_command_sequence("a", "b")
        
        prob = profile.get_sequence_probability("a", "b")
        assert prob > 0
        
        prob_unknown = profile.get_sequence_probability("x", "y")
        assert prob_unknown == 0.0
    
    def test_record_interaction(self):
        """Test interaction recording."""
        profile = UserProfile()
        
        profile.record_interaction(success=True)
        assert profile.total_interactions == 1
        assert profile.successful_interactions == 1
        
        profile.record_interaction(success=False)
        assert profile.total_interactions == 2
        assert profile.successful_interactions == 1
    
    def test_get_top_apps(self):
        """Test getting top apps."""
        profile = UserProfile(
            preferred_apps={"browser": 0.8, "editor": 0.6, "terminal": 0.4}
        )
        
        top = profile.get_top_apps(2)
        assert len(top) == 2
        assert top[0][0] == "browser"
        assert top[1][0] == "editor"
    
    def test_get_top_intents(self):
        """Test getting top intents."""
        profile = UserProfile(
            preferred_intents={"open": 0.9, "search": 0.7, "close": 0.3}
        )
        
        top = profile.get_top_intents(2)
        assert len(top) == 2
        assert top[0][0] == "open"
    
    def test_get_active_hours(self):
        """Test getting active hours."""
        profile = UserProfile(
            active_hours={9: 0.8, 14: 0.9, 20: 0.3}
        )
        
        # get_active_hours returns hours above average
        active = profile.get_active_hours()
        # avg = (0.8 + 0.9 + 0.3) / 3 = 0.666
        # 9 (0.8) and 14 (0.9) are above avg
        assert 14 in active
        assert 9 in active
        assert 20 not in active  # Below average
    
    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        profile = UserProfile(
            preferred_apps={"browser": 0.8},
            preferred_intents={"open": 0.7},
            total_interactions=50,
            verbosity_preference=0.6,
        )
        
        data = profile.to_dict()
        restored = UserProfile.from_dict(data)
        
        assert restored.preferred_apps == profile.preferred_apps
        assert restored.preferred_intents == profile.preferred_intents
        assert restored.total_interactions == profile.total_interactions
        assert restored.verbosity_preference == profile.verbosity_preference
    
    def test_reset(self):
        """Test profile reset."""
        profile = UserProfile(
            preferred_apps={"browser": 0.8},
            total_interactions=100,
        )
        
        profile.reset()
        
        assert profile.preferred_apps == {}
        assert profile.total_interactions == 0


class TestProfileManager:
    """Tests for ProfileManager."""
    
    def test_create_profile(self):
        """Test profile creation."""
        manager = ProfileManager()
        
        profile = manager.create_profile("user1")
        
        assert profile is not None
        assert manager.get_profile("user1") == profile
    
    def test_create_duplicate_profile(self):
        """Test creating duplicate profile."""
        manager = ProfileManager()
        
        manager.create_profile("user1")
        profile2 = manager.create_profile("user1")
        
        # Should return existing
        assert profile2 is not None
    
    def test_get_nonexistent_profile(self):
        """Test getting nonexistent profile."""
        manager = ProfileManager()
        
        profile = manager.get_profile("unknown")
        assert profile is None
    
    def test_set_current_profile(self):
        """Test setting current profile."""
        manager = ProfileManager()
        
        manager.create_profile("user1")
        result = manager.set_current_profile("user1")
        
        assert result is True
        assert manager.current_profile is not None
    
    def test_list_profiles(self):
        """Test listing profiles."""
        manager = ProfileManager()
        
        manager.create_profile("user1")
        manager.create_profile("user2")
        
        profiles = manager.list_profiles()
        assert "user1" in profiles
        assert "user2" in profiles
    
    def test_delete_profile(self):
        """Test deleting profile."""
        manager = ProfileManager()
        
        manager.create_profile("user1")
        result = manager.delete_profile("user1")
        
        assert result is True
        assert manager.get_profile("user1") is None
    
    def test_save_and_load_profiles(self):
        """Test that save and load require storage."""
        import asyncio
        
        manager = ProfileManager()
        manager.create_profile("user1")
        
        # Without storage, save returns 0
        result = asyncio.get_event_loop().run_until_complete(manager.save_profiles())
        assert result == 0  # No storage configured
    
    def test_export_import_profile(self):
        """Test exporting and importing profile."""
        manager = ProfileManager()
        
        profile = manager.create_profile("user1")
        # Set specific value directly
        profile.preferred_apps["browser"] = 0.8
        
        exported = manager.export_profile("user1")
        
        assert exported is not None
        assert exported["preferred_apps"]["browser"] == 0.8
        
        # Import as new profile - needs different ID
        exported["id"] = "user2"
        imported = manager.import_profile(exported)
        
        assert imported is not None
        assert imported.preferred_apps["browser"] == 0.8
        assert manager.get_profile("user2") is not None


class TestFactory:
    """Tests for factory function."""
    
    def test_create_profile_manager(self):
        """Test factory function."""
        manager = create_profile_manager()
        
        assert manager is not None
        assert isinstance(manager, ProfileManager)
