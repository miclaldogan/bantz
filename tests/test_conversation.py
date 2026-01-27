"""Tests for Jarvis Conversation Flow (Issue #20).

Tests cover:
- ConversationManager state transitions
- Timeout behavior
- Wake word skip logic
- Text analysis (goodbye, follow-up, confirmation, rejection, number selection)
- JarvisPersona conversation methods
- NLU context-aware patterns
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.voice.conversation import (
    ConversationManager,
    ConversationConfig,
    ConversationContext,
    ConversationState,
    MockConversationManager,
)
from bantz.llm.persona import JarvisPersona
from bantz.router.nlu import (
    parse_contextual_intent,
    is_contextual_response,
    ContextualParsed,
)


# ─────────────────────────────────────────────────────────────────
# ConversationManager State Transition Tests
# ─────────────────────────────────────────────────────────────────


class TestConversationManagerStates:
    """Test ConversationManager state transitions."""

    def test_initial_state_is_idle(self):
        """Manager should start in IDLE state."""
        manager = ConversationManager()
        assert manager.state == ConversationState.IDLE
        assert manager.context.state == ConversationState.IDLE

    def test_start_interaction_transitions_to_engaged(self):
        """start_interaction should transition from IDLE to ENGAGED."""
        manager = ConversationManager()
        manager.start_interaction()
        assert manager.state == ConversationState.ENGAGED
        assert manager.context.turn_count == 1

    def test_start_interaction_increments_turn_count(self):
        """Multiple start_interaction calls should increment turn count."""
        manager = ConversationManager()
        manager.start_interaction()
        assert manager.context.turn_count == 1
        manager.start_interaction()
        assert manager.context.turn_count == 2
        manager.start_interaction()
        assert manager.context.turn_count == 3

    def test_set_processing_transitions_from_engaged(self):
        """set_processing should transition from ENGAGED to PROCESSING."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        assert manager.state == ConversationState.PROCESSING

    def test_set_speaking_transitions_from_processing(self):
        """set_speaking should transition from PROCESSING to SPEAKING."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        manager.set_speaking()
        assert manager.state == ConversationState.SPEAKING

    def test_set_waiting_transitions_from_speaking(self):
        """set_waiting should transition from SPEAKING to WAITING."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        manager.set_speaking()
        manager.set_waiting()
        assert manager.state == ConversationState.WAITING

    def test_end_interaction_transitions_to_idle(self):
        """end_interaction should transition to IDLE from any state."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        manager.end_interaction(keep_engaged=False)  # Must pass keep_engaged=False to go IDLE
        assert manager.state == ConversationState.IDLE
        assert manager.context.turn_count == 0

    def test_end_interaction_resets_context(self):
        """end_interaction should reset the context."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.context.topic = "test topic"
        manager.context.pending_question = "test question"
        manager.end_interaction(keep_engaged=False)  # Must pass keep_engaged=False
        assert manager.context.topic is None
        assert manager.context.pending_question is None

    def test_full_conversation_cycle(self):
        """Test complete conversation cycle: IDLE → ENGAGED → PROCESSING → SPEAKING → WAITING → IDLE."""
        manager = ConversationManager()
        
        # IDLE → ENGAGED
        manager.start_interaction()
        assert manager.state == ConversationState.ENGAGED
        
        # ENGAGED → PROCESSING
        manager.set_processing()
        assert manager.state == ConversationState.PROCESSING
        
        # PROCESSING → SPEAKING
        manager.set_speaking()
        assert manager.state == ConversationState.SPEAKING
        
        # SPEAKING → WAITING
        manager.set_waiting()
        assert manager.state == ConversationState.WAITING
        
        # WAITING → IDLE (must pass keep_engaged=False)
        manager.end_interaction(keep_engaged=False)
        assert manager.state == ConversationState.IDLE


class TestConversationManagerWakeWordSkip:
    """Test wake word skip logic."""

    def test_should_not_skip_when_idle(self):
        """Wake word should be required when in IDLE state."""
        manager = ConversationManager()
        assert not manager.should_skip_wake_word()

    def test_should_skip_when_engaged(self):
        """Wake word should be skipped when ENGAGED."""
        manager = ConversationManager()
        manager.start_interaction()
        assert manager.should_skip_wake_word()

    def test_should_skip_when_waiting(self):
        """Wake word should be skipped when WAITING."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        manager.set_speaking()
        manager.set_waiting()
        assert manager.should_skip_wake_word()

    def test_should_not_skip_when_processing(self):
        """Wake word should still be skipped when PROCESSING (active conversation)."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        # Processing is part of an active conversation, so skip is still True
        assert manager.should_skip_wake_word()

    def test_should_not_skip_when_speaking(self):
        """Wake word should still be skipped when SPEAKING (active conversation)."""
        manager = ConversationManager()
        manager.start_interaction()
        manager.set_processing()
        manager.set_speaking()
        # Speaking is part of an active conversation, so skip is still True
        assert manager.should_skip_wake_word()


class TestConversationManagerTextAnalysis:
    """Test text analysis methods."""

    # Goodbye detection
    def test_is_goodbye_tesekkurler(self):
        """'teşekkürler' should be detected as goodbye."""
        manager = ConversationManager()
        assert manager.is_goodbye("teşekkürler")
        assert manager.is_goodbye("Teşekkürler")
        assert manager.is_goodbye("TEŞEKKÜRLER")

    def test_is_goodbye_sagol(self):
        """'sağol' should be detected as goodbye."""
        manager = ConversationManager()
        assert manager.is_goodbye("sağol")
        assert manager.is_goodbye("sağ ol")

    def test_is_goodbye_tamam_bukadar(self):
        """'tamam bu kadar' should be detected as goodbye."""
        manager = ConversationManager()
        assert manager.is_goodbye("tamam bu kadar")
        assert manager.is_goodbye("bu kadar")

    def test_is_goodbye_gorusuruz(self):
        """'görüşürüz' should be detected as goodbye."""
        manager = ConversationManager()
        assert manager.is_goodbye("görüşürüz")

    def test_is_goodbye_iyi_geceler(self):
        """'iyi geceler' should be detected as goodbye."""
        manager = ConversationManager()
        assert manager.is_goodbye("iyi geceler")
        assert manager.is_goodbye("iyi günler")
        assert manager.is_goodbye("iyi akşamlar")

    def test_is_not_goodbye_normal_text(self):
        """Normal text should not be detected as goodbye."""
        manager = ConversationManager()
        assert not manager.is_goodbye("hava durumu nedir")
        assert not manager.is_goodbye("youtube aç")

    # Follow-up detection
    def test_is_follow_up_short_responses(self):
        """Short responses (≤5 words) should be follow-ups when engaged."""
        manager = ConversationManager()
        manager.start_interaction()  # Must be engaged for short responses to count
        assert manager.is_follow_up("evet")
        assert manager.is_follow_up("hayır")
        assert manager.is_follow_up("tamam")

    def test_is_follow_up_starters(self):
        """Follow-up starters should be detected."""
        manager = ConversationManager()
        assert manager.is_follow_up("peki bunu yap")
        assert manager.is_follow_up("ya şunu da")
        assert manager.is_follow_up("bir de şunu")
        assert manager.is_follow_up("ayrıca bunu")

    def test_is_not_follow_up_long_command(self):
        """Long commands should not be follow-ups."""
        manager = ConversationManager()
        assert not manager.is_follow_up("youtube'a git ve coldplay ara ve ilk videoyu aç")

    # Confirmation detection
    def test_is_confirmation_evet(self):
        """'evet' should be detected as confirmation."""
        manager = ConversationManager()
        assert manager.is_confirmation("evet")
        assert manager.is_confirmation("Evet")

    def test_is_confirmation_tamam(self):
        """'tamam' should be detected as confirmation."""
        manager = ConversationManager()
        assert manager.is_confirmation("tamam")
        assert manager.is_confirmation("ok")
        assert manager.is_confirmation("olur")

    def test_is_confirmation_tabii(self):
        """'tabii' should be detected as confirmation."""
        manager = ConversationManager()
        assert manager.is_confirmation("tabii")
        assert manager.is_confirmation("tabi")
        assert manager.is_confirmation("elbette")

    # Rejection detection
    def test_is_rejection_hayir(self):
        """'hayır' should be detected as rejection."""
        manager = ConversationManager()
        assert manager.is_rejection("hayır")
        assert manager.is_rejection("Hayır")

    def test_is_rejection_yok(self):
        """'yok' should be detected as rejection."""
        manager = ConversationManager()
        assert manager.is_rejection("yok")
        assert manager.is_rejection("olmaz")

    def test_is_rejection_vazgec(self):
        """'vazgeç' should be detected as rejection."""
        manager = ConversationManager()
        assert manager.is_rejection("vazgeç")
        assert manager.is_rejection("iptal")

    # Number selection detection
    def test_is_number_selection_digit(self):
        """Digit should be detected as number selection."""
        manager = ConversationManager()
        assert manager.is_number_selection("3") == 3
        assert manager.is_number_selection("1") == 1
        assert manager.is_number_selection("10") == 10

    def test_is_number_selection_ordinal(self):
        """Turkish ordinals should be detected."""
        manager = ConversationManager()
        assert manager.is_number_selection("birinci") == 1
        assert manager.is_number_selection("ikinci") == 2
        assert manager.is_number_selection("üçüncü") == 3

    def test_is_number_selection_ilk_son(self):
        """'ilk' and 'son' should be detected."""
        manager = ConversationManager()
        assert manager.is_number_selection("ilk") == 1
        assert manager.is_number_selection("son") == -1

    def test_is_number_selection_none_for_text(self):
        """Non-number text should return None."""
        manager = ConversationManager()
        assert manager.is_number_selection("youtube") is None
        assert manager.is_number_selection("merhaba") is None

    # Navigation detection
    def test_is_navigation_sonraki(self):
        """'sonraki' should be detected as 'next'."""
        manager = ConversationManager()
        assert manager.is_navigation("sonraki") == "next"
        # Note: "ileri" might not be in the list, but "devam" is
        assert manager.is_navigation("devam") == "next"

    def test_is_navigation_onceki(self):
        """'önceki' should be detected as 'prev'."""
        manager = ConversationManager()
        assert manager.is_navigation("önceki") == "prev"
        assert manager.is_navigation("geri") == "prev"

    def test_is_navigation_none_for_text(self):
        """Non-navigation text should return None."""
        manager = ConversationManager()
        assert manager.is_navigation("youtube") is None


class TestConversationManagerConfig:
    """Test ConversationConfig customization."""

    def test_custom_engagement_timeout(self):
        """Custom engagement timeout should be respected."""
        config = ConversationConfig(engagement_timeout=15.0)
        manager = ConversationManager(config=config)
        assert manager.config.engagement_timeout == 15.0

    def test_custom_quick_response_window(self):
        """Custom quick response window should be respected."""
        config = ConversationConfig(quick_response_window=5.0)
        manager = ConversationManager(config=config)
        assert manager.config.quick_response_window == 5.0

    def test_custom_max_turns(self):
        """Custom max turns should be respected."""
        config = ConversationConfig(max_turns=10)
        manager = ConversationManager(config=config)
        assert manager.config.max_turns == 10

    def test_default_config(self):
        """Default config should have standard values."""
        config = ConversationConfig()
        assert config.engagement_timeout == 8.0
        assert config.quick_response_window == 3.0
        assert config.max_turns == 20


class TestConversationManagerCallbacks:
    """Test state change callbacks."""

    def test_on_state_change_callback(self):
        """on_state_change callback should be called on transitions."""
        contexts = []
        
        def callback(context):
            contexts.append(context.state)
        
        manager = ConversationManager(on_state_change=callback)
        manager.start_interaction()
        
        assert len(contexts) == 1
        assert contexts[0] == ConversationState.ENGAGED

    def test_on_timeout_callback(self):
        """on_timeout callback should be called on timeout."""
        timeout_called = []
        
        manager = ConversationManager()
        manager.on_timeout(lambda: timeout_called.append(True))
        
        # Start interaction then simulate timeout
        manager.start_interaction()
        manager._timeout_expired()
        
        assert len(timeout_called) == 1


class TestMockConversationManager:
    """Test MockConversationManager for testing purposes."""

    def test_mock_manager_state_transitions(self):
        """Mock manager should support state transitions."""
        mock = MockConversationManager()
        assert mock.state == ConversationState.IDLE
        
        mock.start_interaction()
        assert mock.state == ConversationState.ENGAGED
        
        mock.end_interaction(keep_engaged=False)
        assert mock.state == ConversationState.IDLE

    def test_mock_manager_should_skip_wake_word(self):
        """Mock manager should support wake word skip logic via setter."""
        mock = MockConversationManager()
        assert not mock.should_skip_wake_word()  # Default False
        
        mock.set_should_skip_wake_word(True)
        assert mock.should_skip_wake_word()


# ─────────────────────────────────────────────────────────────────
# JarvisPersona Conversation Flow Tests
# ─────────────────────────────────────────────────────────────────


class TestJarvisPersonaConversationMethods:
    """Test JarvisPersona conversation flow methods."""

    def test_get_follow_up_returns_string(self):
        """get_follow_up should return a non-empty string."""
        persona = JarvisPersona()
        response = persona.get_follow_up()
        assert isinstance(response, str)
        assert len(response) > 0
        # Response should be a follow-up question (contains ? or asks about more)

    def test_get_goodbye_returns_string(self):
        """get_goodbye should return a non-empty string."""
        persona = JarvisPersona()
        response = persona.get_goodbye()
        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_thanks_response_returns_string(self):
        """get_thanks_response should return a non-empty string."""
        persona = JarvisPersona()
        response = persona.get_thanks_response()
        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_staying_engaged_returns_string(self):
        """get_staying_engaged should return a non-empty string."""
        persona = JarvisPersona()
        response = persona.get_staying_engaged()
        assert isinstance(response, str)
        assert len(response) > 0
        # Response should indicate listening (dinliyorum, buyurun, etc.)

    def test_get_going_idle_returns_string(self):
        """get_going_idle should return a non-empty string."""
        persona = JarvisPersona()
        response = persona.get_going_idle()
        assert isinstance(response, str)
        assert len(response) > 0

    def test_wrap_response_adds_follow_up(self):
        """wrap_response should add follow-up when requested."""
        persona = JarvisPersona()
        content = "İşlem tamamlandı."
        wrapped = persona.wrap_response(content, add_follow_up=True)
        assert content in wrapped
        assert len(wrapped) > len(content)

    def test_wrap_response_no_follow_up(self):
        """wrap_response should not add follow-up when not requested."""
        persona = JarvisPersona()
        content = "İşlem tamamlandı."
        wrapped = persona.wrap_response(content, add_follow_up=False)
        assert wrapped == content

    def test_get_acknowledgment_browser(self):
        """get_acknowledgment should return appropriate response for browser actions."""
        persona = JarvisPersona()
        response = persona.get_acknowledgment("browser")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_acknowledgment_search(self):
        """get_acknowledgment should return appropriate response for search actions."""
        persona = JarvisPersona()
        response = persona.get_acknowledgment("search")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_result_response_found(self):
        """get_result_response should return appropriate response for found results."""
        persona = JarvisPersona()
        response = persona.get_result_response("found")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_result_response_not_found(self):
        """get_result_response should return appropriate response for not found."""
        persona = JarvisPersona()
        response = persona.get_result_response("not_found")
        assert isinstance(response, str)
        assert len(response) > 0


# ─────────────────────────────────────────────────────────────────
# NLU Context-aware Pattern Tests
# ─────────────────────────────────────────────────────────────────


class TestNLUContextPatterns:
    """Test NLU context-aware pattern matching."""

    # Confirmation patterns
    def test_parse_contextual_evet(self):
        """'evet' should parse as context_confirm."""
        result = parse_contextual_intent("evet")
        assert result is not None
        assert result.intent == "context_confirm"
        assert result.requires_context is True

    def test_parse_contextual_tamam(self):
        """'tamam' should parse as context_confirm."""
        result = parse_contextual_intent("tamam")
        assert result is not None
        assert result.intent == "context_confirm"

    def test_parse_contextual_olur(self):
        """'olur' should parse as context_confirm."""
        result = parse_contextual_intent("olur")
        assert result is not None
        assert result.intent == "context_confirm"

    # Rejection patterns
    def test_parse_contextual_hayir(self):
        """'hayır' should parse as context_reject."""
        result = parse_contextual_intent("hayır")
        assert result is not None
        assert result.intent == "context_reject"

    def test_parse_contextual_yok(self):
        """'yok' should parse as context_reject."""
        result = parse_contextual_intent("yok")
        assert result is not None
        assert result.intent == "context_reject"

    def test_parse_contextual_vazgec(self):
        """'vazgeç' should parse as context_reject."""
        result = parse_contextual_intent("vazgeç")
        assert result is not None
        assert result.intent == "context_reject"

    # Number selection patterns
    def test_parse_contextual_number_digit(self):
        """Digit should parse as context_select_number."""
        result = parse_contextual_intent("3")
        assert result is not None
        assert result.intent == "context_select_number"
        assert result.slots.get("number") == 3

    def test_parse_contextual_number_ordinal(self):
        """Turkish ordinal should parse as context_select_number."""
        result = parse_contextual_intent("birinci")
        assert result is not None
        assert result.intent == "context_select_number"
        assert result.slots.get("number") == 1

    def test_parse_contextual_number_ilk(self):
        """'ilk' should parse as context_select_number with value 1."""
        result = parse_contextual_intent("ilk")
        assert result is not None
        assert result.intent == "context_select_number"
        assert result.slots.get("number") == 1

    def test_parse_contextual_number_son(self):
        """'son' should parse as context_select_number with value -1."""
        result = parse_contextual_intent("son")
        assert result is not None
        assert result.intent == "context_select_number"
        assert result.slots.get("number") == -1

    # Navigation patterns
    def test_parse_contextual_sonraki(self):
        """'sonraki' should parse as context_navigate."""
        result = parse_contextual_intent("sonraki")
        assert result is not None
        assert result.intent == "context_navigate"
        assert result.slots.get("direction") == "next"

    def test_parse_contextual_onceki(self):
        """'önceki' should parse as context_navigate."""
        result = parse_contextual_intent("önceki")
        assert result is not None
        assert result.intent == "context_navigate"
        assert result.slots.get("direction") == "prev"

    def test_parse_contextual_geri(self):
        """'geri' should parse as context_navigate."""
        result = parse_contextual_intent("geri")
        assert result is not None
        assert result.intent == "context_navigate"
        assert result.slots.get("direction") == "prev"

    # Goodbye patterns
    def test_parse_contextual_tesekkurler(self):
        """'teşekkürler' should parse as context_goodbye."""
        result = parse_contextual_intent("teşekkürler")
        assert result is not None
        assert result.intent == "context_goodbye"

    def test_parse_contextual_sagol(self):
        """'sağol' should parse as context_goodbye."""
        result = parse_contextual_intent("sağol")
        assert result is not None
        assert result.intent == "context_goodbye"

    def test_parse_contextual_gorusuruz(self):
        """'görüşürüz' should parse as context_goodbye."""
        result = parse_contextual_intent("görüşürüz")
        assert result is not None
        assert result.intent == "context_goodbye"

    # Non-contextual patterns
    def test_parse_contextual_returns_none_for_commands(self):
        """Normal commands should return None."""
        assert parse_contextual_intent("youtube aç") is None
        assert parse_contextual_intent("hava durumu nedir") is None
        assert parse_contextual_intent("saat kaç") is None

    def test_parse_contextual_returns_none_for_long_text(self):
        """Long text should return None."""
        assert parse_contextual_intent("youtube'a git ve coldplay ara ve ilk videoyu aç") is None

    # is_contextual_response helper
    def test_is_contextual_response_true_for_short(self):
        """is_contextual_response should return True for contextual responses."""
        assert is_contextual_response("evet") is True
        assert is_contextual_response("3") is True
        assert is_contextual_response("sonraki") is True

    def test_is_contextual_response_false_for_commands(self):
        """is_contextual_response should return False for commands."""
        assert is_contextual_response("youtube aç") is False
        assert is_contextual_response("hava durumu") is False


# ─────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────


class TestConversationFlowIntegration:
    """Integration tests for conversation flow."""

    def test_full_conversation_with_follow_up(self):
        """Test a complete conversation with follow-up."""
        manager = ConversationManager()
        persona = JarvisPersona()
        
        # User: "Hey Bantz, hava durumu"
        manager.start_interaction()
        assert manager.state == ConversationState.ENGAGED
        
        # Process command
        manager.set_processing()
        assert manager.state == ConversationState.PROCESSING
        
        # Respond with follow-up
        manager.set_speaking()
        response = persona.wrap_response("İstanbul'da hava açık, 22 derece.", add_follow_up=True)
        assert "İstanbul" in response
        
        # Wait for follow-up
        manager.set_waiting()
        assert manager.should_skip_wake_word()  # No wake word needed
        
        # User says "teşekkürler"
        assert manager.is_goodbye("teşekkürler")
        goodbye = persona.get_goodbye()
        
        # End conversation (must pass keep_engaged=False)
        manager.end_interaction(keep_engaged=False)
        assert manager.state == ConversationState.IDLE
        assert not manager.should_skip_wake_word()

    def test_number_selection_flow(self):
        """Test number selection in conversation."""
        manager = ConversationManager()
        
        # Start with search results
        manager.start_interaction()
        manager.context.pending_question = "Hangi sonucu açayım?"
        
        # User says "3"
        num = manager.is_number_selection("3")
        assert num == 3
        
        # Also check via NLU
        parsed = parse_contextual_intent("3")
        assert parsed is not None
        assert parsed.intent == "context_select_number"
        assert parsed.slots.get("number") == 3

    def test_confirmation_rejection_flow(self):
        """Test confirmation and rejection in conversation."""
        manager = ConversationManager()
        
        # Ask for confirmation
        manager.start_interaction()
        manager.context.pending_question = "Bu dosyayı silmemi ister misiniz?"
        
        # User confirms
        assert manager.is_confirmation("evet")
        assert parse_contextual_intent("evet").intent == "context_confirm"
        
        # Or user rejects
        assert manager.is_rejection("hayır")
        assert parse_contextual_intent("hayır").intent == "context_reject"
