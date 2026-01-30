"""
Tests for Bantz Memory System - Issue #6

Comprehensive tests for:
- Memory types
- Memory store (SQLite)
- User profile
- Personality system
- Context builder
- Learning engine
"""

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
import pytest


# ============================================================================
# Memory Types Tests
# ============================================================================

class TestMemoryType:
    """Tests for MemoryType enum."""
    
    def test_memory_type_values(self):
        """Test MemoryType enum values."""
        from bantz.memory.types import MemoryType
        
        assert MemoryType.CONVERSATION.value == "conversation"
        assert MemoryType.TASK.value == "task"
        assert MemoryType.PREFERENCE.value == "preference"
        assert MemoryType.FACT.value == "fact"
        assert MemoryType.EVENT.value == "event"
        assert MemoryType.RELATIONSHIP.value == "relationship"
    
    def test_importance_weight(self):
        """Test importance weight property."""
        from bantz.memory.types import MemoryType
        
        assert MemoryType.FACT.importance_weight == 0.8
        assert MemoryType.PREFERENCE.importance_weight == 0.7
        assert MemoryType.TASK.importance_weight == 0.5
        assert MemoryType.CONVERSATION.importance_weight == 0.3
    
    def test_decay_rate(self):
        """Test decay rate property."""
        from bantz.memory.types import MemoryType
        
        assert MemoryType.FACT.decay_rate == 0.005
        assert MemoryType.PREFERENCE.decay_rate == 0.01
        assert MemoryType.CONVERSATION.decay_rate == 0.05


class TestMemory:
    """Tests for Memory dataclass."""
    
    def test_memory_creation(self):
        """Test basic memory creation."""
        from bantz.memory.types import Memory, MemoryType
        
        memory = Memory(
            content="Test memory",
            type=MemoryType.CONVERSATION,
            importance=0.5,
        )
        
        assert memory.content == "Test memory"
        assert memory.type == MemoryType.CONVERSATION
        assert memory.importance == 0.5
        assert memory.access_count == 0
        assert memory.id is not None
    
    def test_memory_access(self):
        """Test memory access tracking."""
        from bantz.memory.types import Memory
        
        memory = Memory(content="Test", importance=0.5)
        initial_importance = memory.importance
        
        memory.access()
        
        assert memory.access_count == 1
        assert memory.last_accessed is not None
        assert memory.importance > initial_importance
    
    def test_memory_decay(self):
        """Test memory importance decay."""
        from bantz.memory.types import Memory
        
        memory = Memory(content="Test", importance=0.5)
        
        memory.decay(days=10)
        
        assert memory.importance < 0.5
    
    def test_memory_matches_query(self):
        """Test query matching."""
        from bantz.memory.types import Memory
        
        memory = Memory(
            content="Discord'u açtım",
            tags=["app", "discord"],
        )
        
        assert memory.matches_query("discord")
        assert memory.matches_query("Discord")
        assert memory.matches_query("app")
        assert not memory.matches_query("spotify")
    
    def test_memory_relevance_score(self):
        """Test relevance scoring."""
        from bantz.memory.types import Memory
        
        memory = Memory(
            content="Discord uygulamasını açtım",
            importance=0.7,
        )
        
        score = memory.relevance_score("discord aç")
        assert score > 0
        
        empty_score = memory.relevance_score("")
        assert empty_score == memory.importance
    
    def test_memory_serialization(self):
        """Test memory to/from dict."""
        from bantz.memory.types import Memory, MemoryType
        
        memory = Memory(
            content="Test memory",
            type=MemoryType.TASK,
            importance=0.8,
            tags=["test", "unit"],
        )
        
        data = memory.to_dict()
        restored = Memory.from_dict(data)
        
        assert restored.content == memory.content
        assert restored.type == memory.type
        assert restored.importance == memory.importance
        assert restored.tags == memory.tags


class TestConversationMemory:
    """Tests for ConversationMemory."""
    
    def test_conversation_memory_creation(self):
        """Test conversation memory creation."""
        from bantz.memory.types import ConversationMemory, MemoryType
        
        memory = ConversationMemory(
            user_message="Merhaba",
            assistant_response="Buyurun efendim",
            topic="greeting",
            sentiment=0.5,
        )
        
        assert memory.type == MemoryType.CONVERSATION
        assert "User: Merhaba" in memory.content
        assert "Assistant: Buyurun efendim" in memory.content
        assert memory.metadata["topic"] == "greeting"
    
    def test_from_exchange_factory(self):
        """Test from_exchange factory method."""
        from bantz.memory.types import ConversationMemory
        
        memory = ConversationMemory.from_exchange(
            user_message="Discord aç",
            assistant_response="Hemen açıyorum",
            topic="app_control",
        )
        
        assert "Discord aç" in memory.content
        assert "conversation" in memory.tags


class TestTaskMemory:
    """Tests for TaskMemory."""
    
    def test_task_memory_creation(self):
        """Test task memory creation."""
        from bantz.memory.types import TaskMemory, MemoryType
        
        memory = TaskMemory(
            task_description="Discord'u aç",
            steps=["App bulundu", "Başlatıldı"],
            success=True,
            duration_seconds=1.5,
        )
        
        assert memory.type == MemoryType.TASK
        assert "✓" in memory.content
        assert memory.metadata["success"] is True
    
    def test_failed_task_importance(self):
        """Test failed task has lower importance."""
        from bantz.memory.types import TaskMemory
        
        success_task = TaskMemory.from_execution(
            description="Test",
            steps=[],
            success=True,
        )
        
        failed_task = TaskMemory.from_execution(
            description="Test",
            steps=[],
            success=False,
        )
        
        assert success_task.importance > failed_task.importance


class TestPreferenceMemory:
    """Tests for PreferenceMemory."""
    
    def test_preference_memory_creation(self):
        """Test preference memory creation."""
        from bantz.memory.types import PreferenceMemory, MemoryType
        
        memory = PreferenceMemory(
            preference_key="app.discord.monitor",
            preference_value="left",
            confidence=0.8,
        )
        
        assert memory.type == MemoryType.PREFERENCE
        assert "Preference:" in memory.content
        assert memory.metadata["confidence"] == 0.8
    
    def test_preference_confirm(self):
        """Test preference confirmation."""
        from bantz.memory.types import PreferenceMemory
        
        memory = PreferenceMemory(
            preference_key="test",
            preference_value="value",
            confidence=0.5,
        )
        
        memory.confirm()
        
        assert memory.confidence > 0.5
        assert memory.source_count == 2
        assert memory.last_confirmed is not None
    
    def test_preference_contradict(self):
        """Test preference contradiction."""
        from bantz.memory.types import PreferenceMemory
        
        memory = PreferenceMemory(
            preference_key="test",
            preference_value="value",
            confidence=0.8,
        )
        
        memory.contradict()
        
        assert memory.confidence < 0.8


class TestFactMemory:
    """Tests for FactMemory."""
    
    def test_fact_memory_creation(self):
        """Test fact memory creation."""
        from bantz.memory.types import FactMemory, MemoryType
        
        memory = FactMemory(
            fact_category="name",
            fact_value="Ahmet",
            fact_source="user_stated",
        )
        
        assert memory.type == MemoryType.FACT
        assert "name: Ahmet" in memory.content
        # verified is only True when using from_statement factory with user_stated
        assert memory.metadata["fact_source"] == "user_stated"
    
    def test_fact_verify(self):
        """Test fact verification."""
        from bantz.memory.types import FactMemory
        
        memory = FactMemory.from_statement(
            category="job",
            value="Developer",
            source="inferred",
        )
        
        initial_importance = memory.importance
        memory.verify()
        
        assert memory.verified is True
        assert memory.importance > initial_importance


class TestMemoryQuery:
    """Tests for MemoryQuery."""
    
    def test_query_matches(self):
        """Test query matching logic."""
        from bantz.memory.types import Memory, MemoryType, MemoryQuery
        
        memory = Memory(
            content="Test content",
            type=MemoryType.TASK,
            importance=0.5,
            tags=["test"],
        )
        
        # Matching query
        query = MemoryQuery(
            types=[MemoryType.TASK],
            min_importance=0.3,
            tags=["test"],
        )
        assert query.matches(memory)
        
        # Non-matching type
        query = MemoryQuery(types=[MemoryType.FACT])
        assert not query.matches(memory)
        
        # Non-matching importance
        query = MemoryQuery(min_importance=0.9)
        assert not query.matches(memory)


class TestMemoryStats:
    """Tests for MemoryStats."""
    
    def test_stats_summary(self):
        """Test stats summary generation."""
        from bantz.memory.types import MemoryStats
        
        stats = MemoryStats(
            total_memories=100,
            by_type={"conversation": 50, "task": 30, "fact": 20},
            avg_importance=0.5,
        )
        
        summary = stats.summary()
        
        assert "100 memories" in summary
        assert "conversation: 50" in summary


# ============================================================================
# Memory Store Tests
# ============================================================================

class TestMemoryStore:
    """Tests for MemoryStore."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield f.name
        os.unlink(f.name)
    
    def test_store_creation(self, temp_db):
        """Test memory store creation."""
        from bantz.memory.store import MemoryStore
        
        store = MemoryStore(db_path=temp_db)
        
        assert store.db_path.exists()
        store.close()
    
    def test_store_and_get(self, temp_db):
        """Test storing and retrieving memories."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory
        
        store = MemoryStore(db_path=temp_db)
        
        memory = Memory(content="Test memory", importance=0.7)
        memory_id = store.store(memory)
        
        retrieved = store.get(memory_id)
        
        assert retrieved is not None
        assert retrieved.content == "Test memory"
        assert retrieved.importance == 0.7
        
        store.close()
    
    def test_recall(self, temp_db):
        """Test memory recall with search."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory
        
        store = MemoryStore(db_path=temp_db)
        
        # Store some memories
        store.store(Memory(content="Discord uygulaması", importance=0.8))
        store.store(Memory(content="Spotify müzik çalar", importance=0.7))
        store.store(Memory(content="Chrome tarayıcı", importance=0.6))
        
        # Recall
        results = store.recall("discord", limit=5)
        
        assert len(results) >= 1
        assert any("Discord" in m.content for m in results)
        
        store.close()
    
    def test_get_recent(self, temp_db):
        """Test getting recent memories."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory, MemoryType
        
        store = MemoryStore(db_path=temp_db)
        
        store.store(Memory(content="First", type=MemoryType.TASK))
        store.store(Memory(content="Second", type=MemoryType.TASK))
        store.store(Memory(content="Third", type=MemoryType.CONVERSATION))
        
        # Get recent tasks
        recent = store.get_recent(type=MemoryType.TASK, limit=5)
        
        assert len(recent) == 2
        assert all(m.type == MemoryType.TASK for m in recent)
        
        store.close()
    
    def test_update_importance(self, temp_db):
        """Test importance update."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory
        
        store = MemoryStore(db_path=temp_db)
        
        memory = Memory(content="Test", importance=0.5)
        memory_id = store.store(memory)
        
        store.update_importance(memory_id, 0.2)
        
        updated = store.get(memory_id)
        assert updated.importance == 0.7
        
        store.close()
    
    def test_delete(self, temp_db):
        """Test memory deletion."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory
        
        store = MemoryStore(db_path=temp_db)
        
        memory = Memory(content="To delete")
        memory_id = store.store(memory)
        
        assert store.get(memory_id) is not None
        
        store.delete(memory_id)
        
        assert store.get(memory_id) is None
        
        store.close()
    
    def test_forget(self, temp_db):
        """Test forgetting old memories."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory
        from datetime import timedelta
        
        store = MemoryStore(db_path=temp_db)
        
        # Store old, unimportant memory
        old_memory = Memory(
            content="Old memory",
            importance=0.1,
            timestamp=datetime.now() - timedelta(days=100),
        )
        store.store(old_memory)
        
        # Store recent memory
        store.store(Memory(content="Recent memory", importance=0.8))
        
        # Forget old ones (dry run)
        forgotten = store.forget(older_than_days=90, importance_below=0.2, dry_run=True)
        
        assert len(forgotten) >= 1
        
        store.close()
    
    def test_get_stats(self, temp_db):
        """Test getting statistics."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory, MemoryType
        
        store = MemoryStore(db_path=temp_db)
        
        store.store(Memory(content="Test 1", type=MemoryType.TASK))
        store.store(Memory(content="Test 2", type=MemoryType.FACT))
        
        stats = store.get_stats()
        
        assert stats.total_memories == 2
        assert "task" in stats.by_type or "fact" in stats.by_type
        
        store.close()
    
    def test_export_import_json(self, temp_db):
        """Test JSON export/import."""
        from bantz.memory.store import MemoryStore
        from bantz.memory.types import Memory
        
        store = MemoryStore(db_path=temp_db)
        
        store.store(Memory(content="Memory 1"))
        store.store(Memory(content="Memory 2"))
        
        # Export
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            export_path = f.name
        
        count = store.export_json(export_path)
        assert count == 2
        
        # Clear and import
        store.clear()
        assert store.get_stats().total_memories == 0
        
        imported = store.import_json(export_path)
        assert imported == 2
        
        os.unlink(export_path)
        store.close()


class TestMemoryDecay:
    """Tests for MemoryDecay."""
    
    def test_decay_config(self):
        """Test decay configuration."""
        from bantz.memory.store import MemoryDecay
        from bantz.memory.types import Memory, MemoryType
        
        decay = MemoryDecay(
            protected_types=[MemoryType.FACT],
        )
        
        fact_memory = Memory(type=MemoryType.FACT)
        task_memory = Memory(type=MemoryType.TASK)
        
        assert decay.should_protect(fact_memory)
        assert not decay.should_protect(task_memory)


# ============================================================================
# User Profile Tests
# ============================================================================

class TestCommunicationStyle:
    """Tests for CommunicationStyle enum."""
    
    def test_communication_style_values(self):
        """Test CommunicationStyle enum values."""
        from bantz.memory.profile import CommunicationStyle
        
        assert CommunicationStyle.FORMAL.value == "formal"
        assert CommunicationStyle.CASUAL.value == "casual"
        assert CommunicationStyle.BRIEF.value == "brief"
    
    def test_description_tr(self):
        """Test Turkish descriptions."""
        from bantz.memory.profile import CommunicationStyle
        
        assert "Resmi" in CommunicationStyle.FORMAL.description_tr
        assert "Samimi" in CommunicationStyle.CASUAL.description_tr


class TestPreferenceConfidence:
    """Tests for PreferenceConfidence enum."""
    
    def test_confidence_from_float(self):
        """Test confidence level from float."""
        from bantz.memory.profile import PreferenceConfidence
        
        assert PreferenceConfidence.from_float(0.95) == PreferenceConfidence.CONFIRMED
        assert PreferenceConfidence.from_float(0.75) == PreferenceConfidence.STATED
        assert PreferenceConfidence.from_float(0.55) == PreferenceConfidence.OBSERVED
        assert PreferenceConfidence.from_float(0.35) == PreferenceConfidence.INFERRED
        assert PreferenceConfidence.from_float(0.15) == PreferenceConfidence.GUESSED


class TestWorkPattern:
    """Tests for WorkPattern."""
    
    def test_work_pattern_defaults(self):
        """Test default work pattern."""
        from bantz.memory.profile import WorkPattern
        
        pattern = WorkPattern()
        
        assert pattern.start_hour == 9
        assert pattern.end_hour == 18
        assert 0 in pattern.active_days  # Monday
        assert 6 not in pattern.active_days  # Sunday
    
    def test_is_work_hour(self):
        """Test work hour checking."""
        from bantz.memory.profile import WorkPattern
        
        pattern = WorkPattern(start_hour=9, end_hour=18)
        
        assert pattern.is_work_hour(10)
        assert pattern.is_work_hour(17)
        assert not pattern.is_work_hour(8)
        assert not pattern.is_work_hour(19)
    
    def test_serialization(self):
        """Test work pattern serialization."""
        from bantz.memory.profile import WorkPattern
        
        pattern = WorkPattern(start_hour=10, end_hour=19)
        data = pattern.to_dict()
        restored = WorkPattern.from_dict(data)
        
        assert restored.start_hour == 10
        assert restored.end_hour == 19


class TestUserProfile:
    """Tests for UserProfile."""
    
    def test_profile_creation(self):
        """Test profile creation."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile(name="Test User")
        
        assert profile.name == "Test User"
        assert profile.preferred_language == "tr"
    
    def test_set_get_fact(self):
        """Test fact setting and getting."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile()
        
        profile.set_fact("job", "Developer")
        
        assert profile.get_fact("job") == "Developer"
        assert profile.get_fact("missing") is None
    
    def test_set_get_preference(self):
        """Test preference setting and getting."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile()
        
        profile.set_preference("app.discord.monitor", "left", confidence=0.8)
        
        assert profile.get_preference("app.discord.monitor") == "left"
        assert profile.get_preference("missing", "default") == "default"
    
    def test_preference_confirm(self):
        """Test preference confirmation increases confidence."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile()
        
        profile.set_preference("test", "value", confidence=0.5)
        profile.set_preference("test", "value", confidence=0.5)  # Same value = confirm
        
        assert profile.preferences["test"].confidence > 0.5
    
    def test_record_interaction(self):
        """Test interaction recording."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile()
        
        profile.record_interaction()
        profile.record_interaction()
        
        assert profile.total_interactions == 2
        assert profile.first_interaction is not None
        assert profile.last_interaction is not None
    
    def test_add_favorite_app(self):
        """Test adding favorite apps."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile()
        
        profile.add_favorite_app("Discord")
        profile.add_favorite_app("Spotify")
        profile.add_favorite_app("Discord")  # Duplicate
        
        assert len(profile.favorite_apps) == 2
        assert "Discord" in profile.favorite_apps
    
    def test_app_position(self):
        """Test app position storage."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile()
        
        profile.set_app_position("discord", 0, 0, 800, 600)
        
        pos = profile.get_app_position("Discord")  # Case insensitive
        assert pos == (0, 0, 800, 600)
    
    def test_communication_prompt(self):
        """Test communication prompt generation."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile(
            formality_level=0.9,
            verbosity_preference=0.2,
        )
        
        prompt = profile.get_communication_prompt()
        
        assert "Resmi" in prompt
        assert "Kısa" in prompt
    
    def test_serialization(self):
        """Test profile serialization."""
        from bantz.memory.profile import UserProfile
        
        profile = UserProfile(
            name="Test",
            formality_level=0.8,
        )
        profile.set_fact("job", "Dev")
        
        data = profile.to_dict()
        restored = UserProfile.from_dict(data)
        
        assert restored.name == "Test"
        assert restored.formality_level == 0.8
        assert restored.get_fact("job") == "Dev"


class TestProfileManager:
    """Tests for ProfileManager."""
    
    @pytest.fixture
    def temp_profile(self):
        """Create temporary profile file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            yield f.name
        if os.path.exists(f.name):
            os.unlink(f.name)
    
    def test_manager_creation(self, temp_profile):
        """Test profile manager creation."""
        from bantz.memory.profile import ProfileManager
        
        manager = ProfileManager(profile_path=temp_profile, auto_save=False)
        
        assert manager.profile is not None
    
    def test_save_load(self, temp_profile):
        """Test profile save and load."""
        from bantz.memory.profile import ProfileManager
        
        manager = ProfileManager(profile_path=temp_profile, auto_save=False)
        manager.set_name("Test User")
        manager.save()
        
        # New manager should load saved profile
        manager2 = ProfileManager(profile_path=temp_profile, auto_save=False)
        
        assert manager2.get_name() == "Test User"
    
    def test_learn_preference(self, temp_profile):
        """Test learning preferences."""
        from bantz.memory.profile import ProfileManager
        
        manager = ProfileManager(profile_path=temp_profile, auto_save=False)
        
        manager.learn_preference("test.key", "value", confidence=0.7)
        
        assert manager.get_preference("test.key") == "value"
    
    def test_learn_fact(self, temp_profile):
        """Test learning facts."""
        from bantz.memory.profile import ProfileManager
        
        manager = ProfileManager(profile_path=temp_profile, auto_save=False)
        
        manager.learn_fact("name", "Ahmet", source="user_stated")
        
        assert manager.get_fact("name") == "Ahmet"
    
    def test_record_app_usage(self, temp_profile):
        """Test app usage recording."""
        from bantz.memory.profile import ProfileManager
        
        manager = ProfileManager(profile_path=temp_profile, auto_save=False)
        
        manager.record_app_usage("Discord")
        
        assert "Discord" in manager.profile.favorite_apps


# ============================================================================
# Personality System Tests
# ============================================================================

class TestSpeakingStyle:
    """Tests for SpeakingStyle enum."""
    
    def test_speaking_style_values(self):
        """Test SpeakingStyle enum values."""
        from bantz.memory.personality import SpeakingStyle
        
        assert SpeakingStyle.FORMAL.value == "formal"
        assert SpeakingStyle.CASUAL.value == "casual"
        assert SpeakingStyle.FORMAL_FRIENDLY.value == "formal_friendly"
    
    def test_uses_honorifics(self):
        """Test honorifics property."""
        from bantz.memory.personality import SpeakingStyle
        
        assert SpeakingStyle.FORMAL.uses_honorifics
        assert SpeakingStyle.BUTLER.uses_honorifics
        assert not SpeakingStyle.CASUAL.uses_honorifics


class TestResponseType:
    """Tests for ResponseType enum."""
    
    def test_response_type_values(self):
        """Test ResponseType enum values."""
        from bantz.memory.personality import ResponseType
        
        assert ResponseType.GREETING.value == "greeting"
        assert ResponseType.ACKNOWLEDGMENT.value == "acknowledgment"
        assert ResponseType.ERROR.value == "error"
    
    def test_icons(self):
        """Test response type icons."""
        from bantz.memory.personality import ResponseType
        
        assert ResponseType.COMPLETION.icon == "✅"
        assert ResponseType.ERROR.icon == "❌"
        assert ResponseType.WARNING.icon == "⚠️"


class TestResponseTemplates:
    """Tests for ResponseTemplates."""
    
    def test_get_template(self):
        """Test getting templates."""
        from bantz.memory.personality import ResponseTemplates, ResponseType
        
        templates = ResponseTemplates()
        
        greeting = templates.get(ResponseType.GREETING)
        assert greeting is not None
        assert len(greeting) > 0
    
    def test_format_template(self):
        """Test formatting templates."""
        from bantz.memory.personality import ResponseTemplates, ResponseType
        
        templates = ResponseTemplates()
        
        error = templates.format(ResponseType.ERROR, reason="Test error")
        assert "Test error" in error


class TestPersonality:
    """Tests for Personality."""
    
    def test_personality_creation(self):
        """Test personality creation."""
        from bantz.memory.personality import Personality, SpeakingStyle
        
        personality = Personality(
            name="TestBot",
            speaking_style=SpeakingStyle.FORMAL,
        )
        
        assert personality.name == "TestBot"
        assert personality.speaking_style == SpeakingStyle.FORMAL
    
    def test_get_greeting(self):
        """Test getting greeting."""
        from bantz.memory.personality import Personality
        
        personality = Personality()
        
        greeting = personality.get_greeting()
        assert greeting is not None
    
    def test_get_acknowledgment(self):
        """Test getting acknowledgment."""
        from bantz.memory.personality import Personality
        
        personality = Personality(witty_remarks=False)
        
        ack = personality.get_acknowledgment()
        assert ack is not None
    
    def test_get_error(self):
        """Test getting error response."""
        from bantz.memory.personality import Personality
        
        personality = Personality()
        
        error = personality.get_error("File not found")
        assert "File not found" in error
    
    def test_system_prompt(self):
        """Test system prompt generation."""
        from bantz.memory.personality import Personality
        
        personality = Personality(name="Jarvis")
        
        prompt = personality.get_system_prompt(user_name="Ahmet")
        
        assert "Jarvis" in prompt
        assert "Ahmet" in prompt
    
    def test_adapt_to_user(self):
        """Test adapting to user preferences."""
        from bantz.memory.personality import Personality, SpeakingStyle
        
        personality = Personality()
        
        personality.adapt_to_user(formality=0.1, humor=0.9)
        
        assert personality.speaking_style == SpeakingStyle.CASUAL
        assert personality.use_honorifics is False
        assert personality.witty_remarks is True
    
    def test_serialization(self):
        """Test personality serialization."""
        from bantz.memory.personality import Personality, SpeakingStyle
        
        personality = Personality(
            name="Custom",
            speaking_style=SpeakingStyle.BUTLER,
        )
        
        data = personality.to_dict()
        restored = Personality.from_dict(data)
        
        assert restored.name == "Custom"
        assert restored.speaking_style == SpeakingStyle.BUTLER


class TestPersonalityPresets:
    """Tests for personality presets."""
    
    def test_get_jarvis(self):
        """Test getting Jarvis personality."""
        from bantz.memory.personality import get_personality
        
        jarvis = get_personality("jarvis")
        
        assert jarvis.name == "Jarvis"
        assert jarvis.use_honorifics is True
    
    def test_get_friday(self):
        """Test getting Friday personality."""
        from bantz.memory.personality import get_personality
        
        friday = get_personality("friday")
        
        assert friday.name == "Friday"
        assert friday.use_honorifics is False
    
    def test_get_alfred(self):
        """Test getting Alfred personality."""
        from bantz.memory.personality import get_personality
        
        alfred = get_personality("alfred")
        
        assert alfred.name == "Alfred"
        assert alfred.sarcasm_level > 0  # Alfred is sarcastic
    
    def test_list_personalities(self):
        """Test listing personalities."""
        from bantz.memory.personality import list_personalities
        
        names = list_personalities()
        
        assert "jarvis" in names
        assert "friday" in names
        assert "alfred" in names
    
    def test_create_custom(self):
        """Test creating custom personality."""
        from bantz.memory.personality import create_custom_personality
        
        custom = create_custom_personality(
            name="MyBot",
            base="jarvis",
            sarcasm_level=0.5,
        )
        
        assert custom.name == "MyBot"
        assert custom.sarcasm_level == 0.5


# ============================================================================
# Context Builder Tests
# ============================================================================

class TestPromptSection:
    """Tests for PromptSection enum."""
    
    def test_section_values(self):
        """Test section values."""
        from bantz.memory.context import PromptSection
        
        assert PromptSection.SYSTEM.value == "system"
        assert PromptSection.PERSONALITY.value == "personality"
        assert PromptSection.MEMORIES.value == "memories"
    
    def test_section_priority(self):
        """Test section priority."""
        from bantz.memory.context import PromptSection
        
        assert PromptSection.SYSTEM.priority > PromptSection.MEMORIES.priority
        assert PromptSection.PERSONALITY.priority > PromptSection.TASK_HISTORY.priority


class TestContextConfig:
    """Tests for ContextConfig."""
    
    def test_config_defaults(self):
        """Test default configuration."""
        from bantz.memory.context import ContextConfig
        
        config = ContextConfig()
        
        assert config.max_total_tokens == 4000
        assert config.max_memories == 5
    
    def test_estimate_tokens(self):
        """Test token estimation."""
        from bantz.memory.context import ContextConfig
        
        config = ContextConfig()
        
        # 100 chars should be ~25 tokens
        tokens = config.estimate_tokens("a" * 100)
        assert tokens == 25


class TestContextBuilder:
    """Tests for ContextBuilder."""
    
    def test_builder_creation(self):
        """Test context builder creation."""
        from bantz.memory.context import ContextBuilder
        from bantz.memory.profile import UserProfile
        from bantz.memory.personality import Personality
        
        builder = ContextBuilder(
            profile=UserProfile(name="Test"),
            personality=Personality(name="Jarvis"),
        )
        
        assert builder.profile.name == "Test"
        assert builder.personality.name == "Jarvis"
    
    def test_build_system_prompt(self):
        """Test system prompt building."""
        from bantz.memory.context import ContextBuilder
        from bantz.memory.profile import UserProfile
        from bantz.memory.personality import Personality
        
        builder = ContextBuilder(
            profile=UserProfile(name="Ahmet"),
            personality=Personality(name="Jarvis"),
        )
        
        prompt = builder.build_system_prompt()
        
        assert "Jarvis" in prompt
        assert "Ahmet" in prompt
        assert "Kısa ve net" in prompt  # Rules
    
    def test_build_context(self):
        """Test context building."""
        from bantz.memory.context import ContextBuilder
        from bantz.memory.profile import UserProfile
        
        builder = ContextBuilder(profile=UserProfile())
        
        context = builder.build_context(
            current_query="Discord aç",
            conversation_history=[
                ("Merhaba", "Buyurun efendim"),
            ],
        )
        
        assert "Son Konuşma" in context
        assert "Merhaba" in context
    
    def test_get_response_template(self):
        """Test getting response templates."""
        from bantz.memory.context import ContextBuilder
        from bantz.memory.personality import ResponseType
        
        builder = ContextBuilder()
        
        template = builder.get_response_template(ResponseType.GREETING)
        assert template is not None
    
    def test_estimate_token_usage(self):
        """Test token usage estimation."""
        from bantz.memory.context import ContextBuilder
        
        builder = ContextBuilder()
        
        usage = builder.estimate_token_usage()
        
        assert "total" in usage
        assert usage["total"] > 0
    
    def test_cache_invalidation(self):
        """Test cache invalidation."""
        from bantz.memory.context import ContextBuilder
        from bantz.memory.profile import UserProfile
        
        builder = ContextBuilder(profile=UserProfile(name="First"))
        
        prompt1 = builder.build_system_prompt()
        
        builder.update_profile(UserProfile(name="Second"))
        
        prompt2 = builder.build_system_prompt()
        
        assert "First" in prompt1
        assert "Second" in prompt2


# ============================================================================
# Learning Engine Tests
# ============================================================================

class TestExtractedFact:
    """Tests for ExtractedFact."""
    
    def test_fact_creation(self):
        """Test fact creation."""
        from bantz.memory.learning import ExtractedFact
        
        fact = ExtractedFact(
            category="name",
            value="Ahmet",
            confidence=0.9,
            source="name_statement",
            original_text="Benim adım Ahmet",
        )
        
        assert fact.category == "name"
        assert fact.value == "Ahmet"
        assert fact.confidence == 0.9
    
    def test_to_dict(self):
        """Test fact serialization."""
        from bantz.memory.learning import ExtractedFact
        
        fact = ExtractedFact(
            category="job",
            value="Developer",
            confidence=0.7,
            source="job_statement",
            original_text="Developer olarak çalışıyorum",
        )
        
        data = fact.to_dict()
        
        assert data["category"] == "job"
        assert data["value"] == "Developer"


class TestInteractionResult:
    """Tests for InteractionResult."""
    
    def test_success_result(self):
        """Test success result factory."""
        from bantz.memory.learning import InteractionResult
        
        result = InteractionResult.success_result(
            description="Discord opened",
            duration=1.5,
            apps=["Discord"],
        )
        
        assert result.success is True
        assert result.duration_seconds == 1.5
        assert "Discord" in result.apps_used
    
    def test_failure_result(self):
        """Test failure result factory."""
        from bantz.memory.learning import InteractionResult
        
        result = InteractionResult.failure_result(
            description="Failed to open",
            error="App not found",
        )
        
        assert result.success is False
        assert result.error_message == "App not found"


class TestFactExtractor:
    """Tests for FactExtractor."""
    
    def test_extract_name(self):
        """Test name extraction."""
        from bantz.memory.learning import FactExtractor
        
        extractor = FactExtractor()
        
        facts = extractor.extract("Benim adım Ahmet")
        
        assert len(facts) >= 1
        name_facts = [f for f in facts if f.category == "name"]
        assert len(name_facts) >= 1
        assert name_facts[0].value == "Ahmet"
    
    def test_extract_job(self):
        """Test job extraction."""
        from bantz.memory.learning import FactExtractor
        
        extractor = FactExtractor()
        
        facts = extractor.extract("Yazılımcı olarak çalışıyorum")
        
        job_facts = [f for f in facts if f.category == "job"]
        assert len(job_facts) >= 1
    
    def test_extract_age(self):
        """Test age extraction."""
        from bantz.memory.learning import FactExtractor
        
        extractor = FactExtractor()
        
        facts = extractor.extract("30 yaşındayım")
        
        age_facts = [f for f in facts if f.category == "age"]
        assert len(age_facts) >= 1
        assert age_facts[0].value == "30"
    
    def test_no_extraction(self):
        """Test no extraction from irrelevant text."""
        from bantz.memory.learning import FactExtractor
        
        extractor = FactExtractor()
        
        facts = extractor.extract("Discord'u aç")
        
        # Should have few or no facts
        important_facts = [f for f in facts if f.category in ["name", "job", "age"]]
        assert len(important_facts) == 0


class TestPreferenceExtractor:
    """Tests for PreferenceExtractor."""
    
    def test_extract_theme(self):
        """Test theme preference extraction."""
        from bantz.memory.learning import PreferenceExtractor
        
        extractor = PreferenceExtractor()
        
        prefs = extractor.extract("Karanlık tema kullan")
        
        theme_prefs = [p for p in prefs if "theme" in p.key]
        assert len(theme_prefs) >= 1
        assert theme_prefs[0].value == "dark"
    
    def test_extract_volume(self):
        """Test volume preference extraction."""
        from bantz.memory.learning import PreferenceExtractor
        
        extractor = PreferenceExtractor()
        
        prefs = extractor.extract("Sesi 50 yap")
        
        volume_prefs = [p for p in prefs if "volume" in p.key]
        assert len(volume_prefs) >= 1
        assert volume_prefs[0].value == 50


class TestTopicExtractor:
    """Tests for TopicExtractor."""
    
    def test_extract_topic(self):
        """Test topic extraction."""
        from bantz.memory.learning import TopicExtractor
        
        extractor = TopicExtractor()
        
        topic = extractor.extract("Discord uygulamasını aç")
        
        assert topic is not None
        assert len(topic) > 0
    
    def test_keyword_topic(self):
        """Test keyword-based topic."""
        from bantz.memory.learning import TopicExtractor
        
        extractor = TopicExtractor()
        
        topic = extractor.extract("Tarayıcıda YouTube aç")
        
        assert topic == "browser"


class TestSentimentAnalyzer:
    """Tests for SentimentAnalyzer."""
    
    def test_positive_sentiment(self):
        """Test positive sentiment detection."""
        from bantz.memory.learning import SentimentAnalyzer
        
        analyzer = SentimentAnalyzer()
        
        score = analyzer.analyze("Harika, teşekkür ederim!")
        
        assert score > 0
    
    def test_negative_sentiment(self):
        """Test negative sentiment detection."""
        from bantz.memory.learning import SentimentAnalyzer
        
        analyzer = SentimentAnalyzer()
        
        score = analyzer.analyze("Bu çok kötü, berbat oldu")
        
        assert score < 0
    
    def test_neutral_sentiment(self):
        """Test neutral sentiment."""
        from bantz.memory.learning import SentimentAnalyzer
        
        analyzer = SentimentAnalyzer()
        
        score = analyzer.analyze("Discord'u aç")
        
        assert score == 0


class TestLearningEngine:
    """Tests for LearningEngine."""
    
    @pytest.fixture
    def learning_setup(self):
        """Create learning engine with temp storage."""
        import tempfile
        from bantz.memory.store import MemoryStore
        from bantz.memory.profile import ProfileManager
        from bantz.memory.learning import LearningEngine
        
        db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        profile_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        
        db_path = db_file.name
        profile_path = profile_file.name
        
        # Close temp files before using them
        db_file.close()
        profile_file.close()
        
        store = MemoryStore(db_path=db_path)
        profile = ProfileManager(profile_path=profile_path, auto_save=False)
        engine = LearningEngine(memory_store=store, profile_manager=profile)
        
        yield engine, store, profile
        
        store.close()
        if os.path.exists(db_path):
            os.unlink(db_path)
        if os.path.exists(profile_path):
            os.unlink(profile_path)
    
    def test_engine_creation(self, learning_setup):
        """Test learning engine creation."""
        engine, _, _ = learning_setup
        
        assert engine.memory is not None
        assert engine.profile is not None
    
    def test_start_session(self, learning_setup):
        """Test starting a session."""
        engine, _, _ = learning_setup
        
        engine.start_session("test-session")
        
        assert engine.session_id == "test-session"
        assert engine.interaction_count == 0
    
    def test_process_interaction(self, learning_setup):
        """Test processing an interaction."""
        engine, store, _ = learning_setup
        
        engine.start_session("test")
        
        learned = engine.process_interaction(
            user_input="Benim adım Ali",
            assistant_response="Merhaba Ali",
        )
        
        assert "facts" in learned
        assert "memory_id" in learned
        assert engine.interaction_count == 1
    
    def test_learn_facts(self, learning_setup):
        """Test fact learning from interaction."""
        engine, _, profile = learning_setup
        
        engine.start_session("test")
        
        engine.process_interaction(
            user_input="Benim adım Mehmet, yazılımcıyım",
            assistant_response="Merhaba Mehmet",
        )
        
        # Facts should be in profile
        assert profile.get_fact("name") == "Mehmet"
    
    def test_learn_task(self, learning_setup):
        """Test task learning."""
        from bantz.memory.learning import InteractionResult
        from bantz.memory.types import MemoryType
        
        engine, store, profile = learning_setup
        
        engine.start_session("test")
        
        result = InteractionResult.success_result(
            description="Discord açıldı",
            apps=["Discord"],
        )
        
        engine.process_interaction(
            user_input="Discord aç",
            assistant_response="Açtım",
            task_result=result,
        )
        
        # App should be in favorites
        assert "Discord" in profile.profile.favorite_apps
        
        # Task should be stored
        tasks = store.get_recent(type=MemoryType.TASK)
        assert len(tasks) >= 1
    
    def test_get_learning_stats(self, learning_setup):
        """Test getting learning statistics."""
        engine, _, _ = learning_setup
        
        engine.start_session("test")
        engine.process_interaction("Test", "Response")
        
        stats = engine.get_learning_stats()
        
        assert stats["interaction_count"] == 1
        assert stats["session_id"] == "test"
    
    def test_forget_fact(self, learning_setup):
        """Test forgetting a fact."""
        engine, _, profile = learning_setup
        
        profile.learn_fact("test_fact", "value")
        assert profile.get_fact("test_fact") == "value"
        
        engine.forget_fact("test_fact")
        
        assert profile.get_fact("test_fact") is None


# ============================================================================
# Package Exports Tests
# ============================================================================

class TestPackageExports:
    """Tests for package exports."""
    
    def test_types_exports(self):
        """Test types module exports."""
        from bantz.memory.types import (
            Memory,
            MemoryType,
            ConversationMemory,
            TaskMemory,
            PreferenceMemory,
            FactMemory,
            MemoryQuery,
            MemoryStats,
        )
        
        assert Memory is not None
        assert MemoryType is not None
    
    def test_store_exports(self):
        """Test store module exports."""
        from bantz.memory.store import (
            MemoryStore,
            MemoryIndex,
            MemoryDecay,
        )
        
        assert MemoryStore is not None
        assert MemoryDecay is not None
    
    def test_profile_exports(self):
        """Test profile module exports."""
        from bantz.memory.profile import (
            UserProfile,
            ProfileManager,
            PreferenceConfidence,
            CommunicationStyle,
            WorkPattern,
        )
        
        assert UserProfile is not None
        assert ProfileManager is not None
    
    def test_personality_exports(self):
        """Test personality module exports."""
        from bantz.memory.personality import (
            Personality,
            SpeakingStyle,
            ResponseType,
            PersonalityPreset,
            PERSONALITIES,
            get_personality,
        )
        
        assert Personality is not None
        assert get_personality is not None
    
    def test_context_exports(self):
        """Test context module exports."""
        from bantz.memory.context import (
            ContextBuilder,
            ContextConfig,
            PromptSection,
        )
        
        assert ContextBuilder is not None
        assert ContextConfig is not None
    
    def test_learning_exports(self):
        """Test learning module exports."""
        from bantz.memory.learning import (
            LearningEngine,
            ExtractedFact,
            InteractionResult,
            LearningConfig,
        )
        
        assert LearningEngine is not None
        assert ExtractedFact is not None
    
    def test_main_package_exports(self):
        """Test main package exports."""
        from bantz.memory import (
            Memory,
            MemoryStore,
            UserProfile,
            Personality,
            ContextBuilder,
            LearningEngine,
            get_personality,
        )
        
        assert Memory is not None
        assert MemoryStore is not None
        assert UserProfile is not None
        assert Personality is not None
        assert ContextBuilder is not None
        assert LearningEngine is not None
        assert get_personality is not None
