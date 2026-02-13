"""Tests for memory-lite implementation (Issue #141)."""

from __future__ import annotations

import pytest
from datetime import datetime

from bantz.brain.memory_lite import CompactSummary, PIIFilter, DialogSummaryManager


# =============================================================================
# CompactSummary Tests
# =============================================================================

def test_compact_summary_format():
    """Test summary formatting."""
    summary = CompactSummary(
        turn_number=1,
        user_intent="asked about calendar",
        action_taken="listed events",
    )
    
    result = summary.to_prompt_block()
    assert "Turn 1:" in result
    assert "asked about calendar" in result
    assert "listed events" in result


def test_compact_summary_with_pending():
    """Test summary with pending items."""
    summary = CompactSummary(
        turn_number=2,
        user_intent="requested meeting",
        action_taken="created event",
        pending_items=["waiting for confirmation"],
    )
    
    result = summary.to_prompt_block()
    assert "Pending: waiting for confirmation" in result


def test_compact_summary_no_pending():
    """Test summary without pending items."""
    summary = CompactSummary(
        turn_number=1,
        user_intent="greeting",
        action_taken="greeted back",
    )
    
    result = summary.to_prompt_block()
    assert "Pending" not in result


# =============================================================================
# PIIFilter Tests
# =============================================================================

def test_pii_filter_email():
    """Test email filtering."""
    text = "Send to user@example.com and admin@test.org"
    filtered = PIIFilter.filter(text)
    
    assert "user@example.com" not in filtered
    assert "admin@test.org" not in filtered
    assert "<EMAIL>" in filtered


def test_pii_filter_phone():
    """Test phone number filtering."""
    text = "Call me at 555-123-4567 or (555) 987-6543"
    filtered = PIIFilter.filter(text)
    
    assert "555-123-4567" not in filtered
    assert "555" not in filtered or "<PHONE>" in filtered


def test_pii_filter_credit_card():
    """Test credit card filtering."""
    text = "Card: 1234-5678-9012-3456"
    filtered = PIIFilter.filter(text)
    
    assert "1234-5678-9012-3456" not in filtered
    assert "<CREDIT_CARD>" in filtered


def test_pii_filter_ssn():
    """Test SSN filtering."""
    text = "SSN: 123-45-6789"
    filtered = PIIFilter.filter(text)
    
    assert "123-45-6789" not in filtered
    assert "<SSN>" in filtered


def test_pii_filter_address():
    """Test address filtering."""
    text = "Located at 123 Main Street"
    filtered = PIIFilter.filter(text)
    
    assert "123 Main Street" not in filtered
    assert "<ADDRESS>" in filtered


def test_pii_filter_url():
    """Test URL filtering."""
    text = "Check https://example.com/secret"
    filtered = PIIFilter.filter(text)
    
    assert "https://example.com" not in filtered
    assert "<URL>" in filtered


def test_pii_filter_disabled():
    """Test PII filter can be disabled."""
    text = "user@example.com"
    filtered = PIIFilter.filter(text, enabled=False)
    
    assert "user@example.com" in filtered


# =============================================================================
# DialogSummaryManager Tests
# =============================================================================

def test_dialog_manager_add_single():
    """Test adding single summary."""
    manager = DialogSummaryManager()
    summary = CompactSummary(
        turn_number=1,
        user_intent="asked about calendar",
        action_taken="listed events",
    )
    
    manager.add_turn(summary)
    
    assert len(manager) == 1
    assert manager.get_latest() == summary


def test_dialog_manager_add_multiple():
    """Test adding multiple summaries."""
    manager = DialogSummaryManager()
    
    for i in range(3):
        summary = CompactSummary(
            turn_number=i + 1,
            user_intent=f"action {i}",
            action_taken=f"response {i}",
        )
        manager.add_turn(summary)
    
    assert len(manager) == 3


def test_dialog_manager_max_turns_limit():
    """Test max turns limit enforcement."""
    manager = DialogSummaryManager(max_turns=3)
    
    for i in range(5):
        summary = CompactSummary(
            turn_number=i + 1,
            user_intent=f"action {i}",
            action_taken=f"response {i}",
        )
        manager.add_turn(summary)
    
    # Should keep only last 3
    assert len(manager) == 3
    assert manager.summaries[0].turn_number == 3
    assert manager.summaries[-1].turn_number == 5


def test_dialog_manager_token_limit():
    """Test token limit enforcement."""
    manager = DialogSummaryManager(max_tokens=50, max_turns=100)
    
    # Add many long summaries
    for i in range(20):
        summary = CompactSummary(
            turn_number=i + 1,
            user_intent="a very long user intent description with many words",
            action_taken="a very long action taken description with many words",
        )
        manager.add_turn(summary)
    
    # Should evict oldest to stay under 50 tokens
    token_count = manager._estimate_tokens()
    assert token_count <= 50
    assert len(manager) < 20  # Some were evicted


def test_dialog_manager_pii_filtering():
    """Test PII filtering during add."""
    manager = DialogSummaryManager(pii_filter_enabled=True)
    
    summary = CompactSummary(
        turn_number=1,
        user_intent="email to user@example.com",
        action_taken="sent email",
        pending_items=["call 555-123-4567"],
    )
    
    manager.add_turn(summary)
    
    stored = manager.summaries[0]
    assert "user@example.com" not in stored.user_intent
    assert "<EMAIL>" in stored.user_intent
    assert "555-123-4567" not in stored.pending_items[0]


def test_dialog_manager_pii_disabled():
    """Test PII filtering can be disabled."""
    manager = DialogSummaryManager(pii_filter_enabled=False)
    
    summary = CompactSummary(
        turn_number=1,
        user_intent="email to user@example.com",
        action_taken="sent email",
    )
    
    manager.add_turn(summary)
    
    stored = manager.summaries[0]
    assert "user@example.com" in stored.user_intent


def test_dialog_manager_prompt_block():
    """Test prompt block generation."""
    manager = DialogSummaryManager()
    
    manager.add_turn(CompactSummary(
        turn_number=1,
        user_intent="asked about calendar",
        action_taken="listed events",
    ))
    
    manager.add_turn(CompactSummary(
        turn_number=2,
        user_intent="requested meeting",
        action_taken="created event",
        pending_items=["confirmation"],
    ))
    
    prompt = manager.to_prompt_block()
    
    assert "DIALOG_SUMMARY" in prompt
    assert "Turn 1:" in prompt
    assert "Turn 2:" in prompt
    assert "listed events" in prompt
    assert "created event" in prompt
    assert "confirmation" in prompt


def test_dialog_manager_empty_prompt_block():
    """Test prompt block when empty."""
    manager = DialogSummaryManager()
    prompt = manager.to_prompt_block()
    
    assert prompt == ""


def test_dialog_manager_clear():
    """Test clearing summaries."""
    manager = DialogSummaryManager()
    
    manager.add_turn(CompactSummary(
        turn_number=1,
        user_intent="test",
        action_taken="test",
    ))
    
    assert len(manager) == 1
    
    manager.clear()
    
    assert len(manager) == 0
    assert manager.to_prompt_block() == ""


# =============================================================================
# Integration Tests
# =============================================================================

def test_full_conversation_flow():
    """Test realistic conversation flow."""
    manager = DialogSummaryManager(max_tokens=200, max_turns=5)
    
    # Turn 1: Greeting
    manager.add_turn(CompactSummary(
        turn_number=1,
        user_intent="greeted",
        action_taken="greeted back",
    ))
    
    # Turn 2: Calendar query
    manager.add_turn(CompactSummary(
        turn_number=2,
        user_intent="asked about today's events",
        action_taken="listed calendar events",
    ))
    
    # Turn 3: Create meeting (with PII)
    manager.add_turn(CompactSummary(
        turn_number=3,
        user_intent="requested meeting with john@company.com",
        action_taken="created meeting",
        pending_items=["waiting for confirmation"],
    ))
    
    # Turn 4: Confirmation
    manager.add_turn(CompactSummary(
        turn_number=4,
        user_intent="confirmed meeting",
        action_taken="finalized meeting",
    ))
    
    prompt = manager.to_prompt_block()
    
    # Check structure
    assert "DIALOG_SUMMARY" in prompt
    assert "Turn 1:" in prompt
    assert "Turn 4:" in prompt
    
    # Check PII filtered
    assert "john@company.com" not in prompt
    assert "<EMAIL>" in prompt
    
    # Check token limit
    token_count = manager._estimate_tokens()
    assert token_count <= 200


def test_memory_continuity_scenario():
    """Test 'az önce ne yaptık?' scenario."""
    manager = DialogSummaryManager()
    
    # Previous turn
    manager.add_turn(CompactSummary(
        turn_number=1,
        user_intent="asked about calendar",
        action_taken="listed events for today",
    ))
    
    # Current prompt should include this context
    prompt = manager.to_prompt_block()
    
    # When user asks "az önce ne yaptık?", this prompt will be injected
    # and LLM can respond based on the summary
    assert "listed events for today" in prompt
    assert "Turn 1:" in prompt
