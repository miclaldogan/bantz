"""Tests for Gmail Argument Aliasing (Issue #340)."""

import pytest
from unittest.mock import Mock
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.llm_router import OrchestratorOutput


@pytest.fixture
def loop():
    """Create OrchestratorLoop for testing."""
    return OrchestratorLoop(
        orchestrator=Mock(),
        tools=Mock(),
        event_bus=Mock(),
        config=OrchestratorConfig(enable_safety_guard=False),
    )


def make_output(**gmail_fields):
    """Helper to create OrchestratorOutput with gmail fields."""
    return OrchestratorOutput(
        route="gmail",
        calendar_intent="none",
        gmail_intent="send",
        gmail=gmail_fields,
        slots={},
        confidence=0.9,
        tool_plan=["gmail.send"],
        assistant_reply="",
    )


class TestGmailSendAliasing:
    """Test gmail.send argument aliasing (Issue #340)."""
    
    def test_recipient_aliased_to_to(self, loop):
        """Test 'recipient' → 'to'."""
        output = make_output(recipient="test@example.com", subject="Test", body="Hello")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["to"] == "test@example.com"
        assert "recipient" not in params
    
    def test_email_aliased_to_to(self, loop):
        """Test 'email' → 'to'."""
        output = make_output(email="user@domain.com", subject="Hi", body="Text")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["to"] == "user@domain.com"
        assert "email" not in params
    
    def test_address_aliased_to_to(self, loop):
        """Test 'address' → 'to'."""
        output = make_output(address="contact@test.org", subject="Msg", body="Content")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["to"] == "contact@test.org"
        assert "address" not in params
    
    def test_message_aliased_to_body(self, loop):
        """Test 'message' → 'body'."""
        output = make_output(to="test@test.com", subject="Hi", message="Message text")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["body"] == "Message text"
        assert "message" not in params
    
    def test_text_aliased_to_body(self, loop):
        """Test 'text' → 'body'."""
        output = make_output(to="test@test.com", subject="Hi", text="Text content")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["body"] == "Text content"
        assert "text" not in params
    
    def test_title_aliased_to_subject(self, loop):
        """Test 'title' → 'subject'."""
        output = make_output(to="test@test.com", title="Email Title", body="Content")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["subject"] == "Email Title"
        assert "title" not in params
    
    def test_real_world_example(self, loop):
        """
        Issue #340: 'dostum iclaldgn@gmail.com maiilne merhaba yaz bakalım'
        LLM used 'email' instead of 'to'.
        """
        output = make_output(email="iclaldgn@gmail.com", subject="merhaba", body="merhaba")
        params = loop._build_tool_params("gmail.send", {}, output)
        
        assert params["to"] == "iclaldgn@gmail.com"
        assert "email" not in params
    
    def test_no_aliasing_for_other_tools(self, loop):
        """Aliasing only applies to gmail.send."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="list",
            gmail={"recipient": "test@test.com"},
            slots={},
            confidence=0.9,
            tool_plan=["gmail.list_messages"],
            assistant_reply="",
        )
        
        params = loop._build_tool_params("gmail.list_messages", {}, output)
        
        # Should NOT alias for other tools
        assert params.get("recipient") == "test@test.com"
        assert "to" not in params
