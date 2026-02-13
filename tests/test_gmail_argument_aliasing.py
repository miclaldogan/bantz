"""Tests for Gmail Argument Handling (Issue #340).

Verifies that _build_tool_params correctly extracts canonical gmail
parameters (to, subject, body) from OrchestratorOutput.gmail dict.

Note: The whitelist filter only passes canonical keys (to, subject, body,
cc, bcc). Non-canonical keys like 'recipient', 'email', 'message' are
dropped. This is the intended behavior — the LLM should be prompted to
use canonical names.
"""

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


class TestGmailSendCanonicalParams:
    """Test gmail.send canonical parameter handling (Issue #340)."""
    
    def test_canonical_to_passes_through(self, loop):
        """Canonical 'to' should pass through."""
        output = make_output(to="test@example.com", subject="Test", body="Hello")
        params = loop._build_tool_params("gmail.send", {}, output)
        assert params["to"] == "test@example.com"
    
    def test_canonical_subject_passes_through(self, loop):
        """Canonical 'subject' should pass through."""
        output = make_output(to="user@domain.com", subject="Hi there", body="Text")
        params = loop._build_tool_params("gmail.send", {}, output)
        assert params["subject"] == "Hi there"
    
    def test_canonical_body_passes_through(self, loop):
        """Canonical 'body' should pass through."""
        output = make_output(to="test@test.com", subject="Hi", body="Message text")
        params = loop._build_tool_params("gmail.send", {}, output)
        assert params["body"] == "Message text"
    
    def test_non_canonical_keys_dropped(self, loop):
        """Non-canonical keys like 'recipient', 'email', 'message' are dropped by whitelist."""
        output = make_output(recipient="test@example.com", message="Hello", title="Subject")
        params = loop._build_tool_params("gmail.send", {}, output)
        # Non-canonical keys should not appear
        assert "recipient" not in params
        assert "message" not in params
        assert "title" not in params
    
    def test_real_world_canonical(self, loop):
        """
        Issue #340: LLM should produce canonical keys.
        'dostum iclaldgn@gmail.com mailine merhaba yaz bakalım'
        """
        output = make_output(to="iclaldgn@gmail.com", subject="merhaba", body="merhaba")
        params = loop._build_tool_params("gmail.send", {}, output)
        assert params["to"] == "iclaldgn@gmail.com"
        assert params["subject"] == "merhaba"
        assert params["body"] == "merhaba"
    
    def test_all_canonical_fields(self, loop):
        """All three canonical fields should be present."""
        output = make_output(to="a@b.com", subject="Sub", body="Content")
        params = loop._build_tool_params("gmail.send", {}, output)
        assert params == {"to": "a@b.com", "subject": "Sub", "body": "Content"}
    
    def test_gmail_list_messages_empty_params(self, loop):
        """gmail.list_messages should have empty params (no gmail fields needed)."""
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
        # Non-canonical keys are dropped
        assert "recipient" not in params
        assert "to" not in params
