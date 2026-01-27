"""
Tests for V2-6 Conversation Context (Issue #38).
"""

import pytest
from datetime import datetime

from bantz.conversation.context import (
    TurnInfo,
    ConversationContext,
    create_conversation_context,
)


class TestTurnInfo:
    """Tests for TurnInfo."""
    
    def test_create_user_turn(self):
        """Test creating user turn."""
        turn = TurnInfo.user(
            text="Hava nasıl?",
            intent="weather_query"
        )
        
        assert turn.role == "user"
        assert turn.text == "Hava nasıl?"
        assert turn.intent == "weather_query"
        assert turn.turn_id is not None
    
    def test_create_assistant_turn(self):
        """Test creating assistant turn."""
        turn = TurnInfo.assistant(
            text="Bugün güneşli.",
            tts_duration_ms=1500
        )
        
        assert turn.role == "assistant"
        assert turn.text == "Bugün güneşli."
        assert turn.tts_duration_ms == 1500
    
    def test_turn_to_dict(self):
        """Test turn to_dict."""
        turn = TurnInfo.user(text="Test")
        
        data = turn.to_dict()
        
        assert data["role"] == "user"
        assert data["text"] == "Test"
        assert "turn_id" in data
        assert "timestamp" in data
    
    def test_turn_from_dict(self):
        """Test turn from_dict."""
        data = {
            "turn_id": "test-id",
            "role": "user",
            "text": "Hello",
            "timestamp": datetime.now().isoformat(),
            "intent": "greeting",
        }
        
        turn = TurnInfo.from_dict(data)
        
        assert turn.turn_id == "test-id"
        assert turn.role == "user"
        assert turn.text == "Hello"


class TestConversationContext:
    """Tests for ConversationContext."""
    
    def test_add_turn(self):
        """Test adding a turn."""
        ctx = ConversationContext()
        
        turn = TurnInfo.user(text="Hello")
        ctx.add_turn(turn)
        
        assert ctx.turn_count == 1
    
    def test_add_user_turn_convenience(self):
        """Test add_user_turn convenience method."""
        ctx = ConversationContext()
        
        turn = ctx.add_user_turn("Hello", intent="greeting")
        
        assert ctx.turn_count == 1
        assert turn.role == "user"
        assert turn.intent == "greeting"
    
    def test_add_assistant_turn_convenience(self):
        """Test add_assistant_turn convenience method."""
        ctx = ConversationContext()
        
        turn = ctx.add_assistant_turn("Hi there!", tts_duration_ms=800)
        
        assert ctx.turn_count == 1
        assert turn.role == "assistant"
        assert turn.tts_duration_ms == 800
    
    def test_max_turns_limit(self):
        """Test max turns limit evicts old turns."""
        ctx = ConversationContext(max_turns=3)
        
        for i in range(5):
            ctx.add_user_turn(f"Message {i}")
        
        assert ctx.turn_count == 3
        
        # Should have messages 2, 3, 4 (0, 1 evicted)
        turns = ctx.get_all_turns()
        assert turns[0].text == "Message 2"
    
    def test_get_recent_turns(self):
        """Test getting recent turns."""
        ctx = ConversationContext()
        
        for i in range(10):
            ctx.add_user_turn(f"Message {i}")
        
        recent = ctx.get_recent_turns(3)
        
        assert len(recent) == 3
        assert recent[0].text == "Message 7"
        assert recent[2].text == "Message 9"
    
    def test_get_last_turn(self):
        """Test getting last turn."""
        ctx = ConversationContext()
        
        ctx.add_user_turn("First")
        ctx.add_assistant_turn("Second")
        
        last = ctx.get_last_turn()
        
        assert last.text == "Second"
    
    def test_get_last_user_turn(self):
        """Test getting last user turn."""
        ctx = ConversationContext()
        
        ctx.add_user_turn("User 1")
        ctx.add_assistant_turn("Assistant 1")
        ctx.add_user_turn("User 2")
        ctx.add_assistant_turn("Assistant 2")
        
        last_user = ctx.get_last_user_turn()
        
        assert last_user.text == "User 2"
    
    def test_get_last_assistant_turn(self):
        """Test getting last assistant turn."""
        ctx = ConversationContext()
        
        ctx.add_user_turn("User 1")
        ctx.add_assistant_turn("Assistant 1")
        ctx.add_user_turn("User 2")
        
        last_assistant = ctx.get_last_assistant_turn()
        
        assert last_assistant.text == "Assistant 1"
    
    def test_clear(self):
        """Test clearing context."""
        ctx = ConversationContext()
        
        ctx.add_user_turn("Hello")
        ctx.add_assistant_turn("Hi")
        
        count = ctx.clear()
        
        assert count == 2
        assert ctx.turn_count == 0
    
    def test_conversation_id(self):
        """Test conversation ID."""
        ctx = ConversationContext()
        
        assert ctx.conversation_id is not None
        assert len(ctx.conversation_id) > 0
    
    def test_custom_conversation_id(self):
        """Test custom conversation ID."""
        ctx = ConversationContext(conversation_id="my-conversation")
        
        assert ctx.conversation_id == "my-conversation"
    
    def test_is_empty(self):
        """Test is_empty property."""
        ctx = ConversationContext()
        
        assert ctx.is_empty is True
        
        ctx.add_user_turn("Hello")
        
        assert ctx.is_empty is False
    
    def test_to_dict(self):
        """Test to_dict."""
        ctx = ConversationContext()
        ctx.add_user_turn("Hello")
        
        data = ctx.to_dict()
        
        assert "conversation_id" in data
        assert data["turn_count"] == 1
        assert len(data["turns"]) == 1
    
    def test_to_messages(self):
        """Test to_messages for LLM format."""
        ctx = ConversationContext()
        ctx.add_user_turn("Hello")
        ctx.add_assistant_turn("Hi there!")
        
        messages = ctx.to_messages()
        
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
    
    def test_get_summary(self):
        """Test get_summary."""
        ctx = ConversationContext()
        ctx.add_user_turn("Hello")
        ctx.add_assistant_turn("Hi there!")
        
        summary = ctx.get_summary()
        
        assert "User:" in summary
        assert "Assistant:" in summary
    
    def test_metadata(self):
        """Test context metadata."""
        ctx = ConversationContext()
        
        ctx.set_metadata("user_name", "Ahmet")
        
        assert ctx.get_metadata("user_name") == "Ahmet"
        assert ctx.get_metadata("nonexistent", "default") == "default"
    
    def test_factory_function(self):
        """Test create_conversation_context factory."""
        ctx = create_conversation_context(max_turns=5)
        
        assert isinstance(ctx, ConversationContext)
        assert ctx.max_turns == 5
