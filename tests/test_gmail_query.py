"""Tests for Gmail Query Parameter (Issue #285).

Tests that gmail.list_messages supports the query parameter for
filtering messages (from:, subject:, label:, etc.).
"""

import pytest
from unittest.mock import patch, MagicMock


# ============================================================================
# Test gmail_list_messages_tool with query
# ============================================================================

class TestGmailListMessagesQuery:
    """Test gmail_list_messages_tool with query parameter."""
    
    def test_list_messages_with_linkedin_query(self):
        """Query 'from:linkedin' should be passed to API."""
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        
        with patch('bantz.tools.gmail_tools.gmail_list_messages') as mock_list:
            mock_list.return_value = {
                "ok": True,
                "query": "from:linkedin",
                "messages": [{"id": "1", "subject": "Job Alert"}],
            }
            
            result = gmail_list_messages_tool(query="from:linkedin")
            
            assert mock_list.called
            call_kwargs = mock_list.call_args.kwargs
            assert call_kwargs.get("query") == "from:linkedin"
    
    def test_list_messages_with_amazon_query(self):
        """Query 'from:amazon' should be passed to API."""
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        
        with patch('bantz.tools.gmail_tools.gmail_list_messages') as mock_list:
            mock_list.return_value = {"ok": True, "messages": []}
            
            result = gmail_list_messages_tool(query="from:amazon subject:order")
            
            call_kwargs = mock_list.call_args.kwargs
            assert "amazon" in call_kwargs.get("query", "")
    
    def test_list_messages_with_label_query(self):
        """Query 'label:CATEGORY_UPDATES' should work."""
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        
        with patch('bantz.tools.gmail_tools.gmail_list_messages') as mock_list:
            mock_list.return_value = {"ok": True, "messages": []}
            
            result = gmail_list_messages_tool(query="label:CATEGORY_UPDATES")
            
            call_kwargs = mock_list.call_args.kwargs
            assert call_kwargs.get("query") == "label:CATEGORY_UPDATES"
    
    def test_list_messages_without_query(self):
        """Without query, should list inbox normally."""
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        
        with patch('bantz.tools.gmail_tools.gmail_list_messages') as mock_list:
            mock_list.return_value = {"ok": True, "messages": []}
            
            result = gmail_list_messages_tool()
            
            call_kwargs = mock_list.call_args.kwargs
            assert call_kwargs.get("query") is None
    
    def test_list_messages_with_unread_and_query(self):
        """Query and unread_only should work together."""
        from bantz.tools.gmail_tools import gmail_list_messages_tool
        
        with patch('bantz.tools.gmail_tools.gmail_list_messages') as mock_list:
            mock_list.return_value = {"ok": True, "messages": []}
            
            result = gmail_list_messages_tool(
                query="from:linkedin",
                unread_only=True,
            )
            
            call_kwargs = mock_list.call_args.kwargs
            assert call_kwargs.get("query") == "from:linkedin"
            assert call_kwargs.get("unread_only") is True


class TestGmailRelativeDateWindow:
    def test_today_injects_after_filter(self):
        from datetime import datetime, timezone
        from bantz.tools.gmail_tools import gmail_list_messages_tool

        with patch("bantz.tools.gmail_tools._now_local") as mock_now, patch(
            "bantz.tools.gmail_tools.gmail_list_messages"
        ) as mock_list:
            mock_now.return_value = datetime(2026, 2, 9, 12, 0, tzinfo=timezone.utc)
            mock_list.return_value = {"ok": True, "messages": []}

            gmail_list_messages_tool(date_window="today")

            call_kwargs = mock_list.call_args.kwargs
            assert "after:2026/02/09" in (call_kwargs.get("query") or "")

    def test_yesterday_injects_after_before_filter(self):
        from datetime import datetime, timezone
        from bantz.tools.gmail_tools import gmail_list_messages_tool

        with patch("bantz.tools.gmail_tools._now_local") as mock_now, patch(
            "bantz.tools.gmail_tools.gmail_list_messages"
        ) as mock_list:
            mock_now.return_value = datetime(2026, 2, 9, 9, 0, tzinfo=timezone.utc)
            mock_list.return_value = {"ok": True, "messages": []}

            gmail_list_messages_tool(date_window="yesterday")

            call_kwargs = mock_list.call_args.kwargs
            q = call_kwargs.get("query") or ""
            assert "after:2026/02/08" in q
            assert "before:2026/02/09" in q

    def test_does_not_override_existing_after_filter(self):
        from datetime import datetime, timezone
        from bantz.tools.gmail_tools import gmail_list_messages_tool

        with patch("bantz.tools.gmail_tools._now_local") as mock_now, patch(
            "bantz.tools.gmail_tools.gmail_list_messages"
        ) as mock_list:
            mock_now.return_value = datetime(2026, 2, 9, 9, 0, tzinfo=timezone.utc)
            mock_list.return_value = {"ok": True, "messages": []}

            gmail_list_messages_tool(query="after:2026/02/01 from:amazon", date_window="today")

            call_kwargs = mock_list.call_args.kwargs
            q = call_kwargs.get("query") or ""
            assert "after:2026/02/01" in q
            assert "after:2026/02/09" not in q


# ============================================================================
# Test gmail.py gmail_list_messages with query
# ============================================================================

class TestGmailListMessagesAPIQuery:
    """Test the gmail.py gmail_list_messages function with query."""
    
    def test_query_parameter_in_function_signature(self):
        """Function should accept query parameter."""
        from bantz.google.gmail import gmail_list_messages
        import inspect
        
        sig = inspect.signature(gmail_list_messages)
        assert "query" in sig.parameters
    
    def test_query_uses_q_parameter(self):
        """When query is provided, should use q= in API call."""
        from bantz.google.gmail import gmail_list_messages
        
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
        }
        
        gmail_list_messages(
            query="from:linkedin",
            service=mock_service,
            interactive=False,
        )
        
        # Check that list() was called with q parameter
        call_kwargs = mock_service.users().messages().list.call_args.kwargs
        assert "q" in call_kwargs
        assert "linkedin" in call_kwargs["q"]
    
    def test_no_query_uses_label_ids(self):
        """Without query, should use labelIds instead of q."""
        from bantz.google.gmail import gmail_list_messages
        
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
        }
        
        gmail_list_messages(
            service=mock_service,
            interactive=False,
        )
        
        call_kwargs = mock_service.users().messages().list.call_args.kwargs
        # Should use labelIds, not q
        assert "labelIds" in call_kwargs or "q" not in call_kwargs


# ============================================================================
# Test LLM Router Prompt
# ============================================================================

class TestLLMRouterGmailPrompt:
    """Test that LLM router prompt includes Gmail query examples."""
    
    def test_prompt_has_gmail_query_examples(self):
        """Prompt should have Gmail-related examples."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Should have gmail route and intent examples
        assert "gmail" in prompt.lower()
        assert "smart_search" in prompt or "list_messages" in prompt or "gmail_intent" in prompt
    
    def test_prompt_mentions_query_parameter(self):
        """Prompt should mention query parameter for gmail.list_messages."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        assert "query" in prompt.lower()
    
    def test_prompt_has_label_category_examples(self):
        """Prompt should have gmail search/label examples."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        prompt = JarvisLLMOrchestrator.SYSTEM_PROMPT
        
        # Should have gmail search examples (smart_search or query-based)
        assert "smart_search" in prompt or "label:" in prompt or "GMAIL" in prompt


# ============================================================================
# Test Query Building
# ============================================================================

class TestQueryBuilding:
    """Test query string building logic."""
    
    def test_unread_only_appends_to_query(self):
        """unread_only should add is:unread to query."""
        from bantz.google.gmail import gmail_list_messages
        
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
        }
        
        gmail_list_messages(
            query="from:linkedin",
            unread_only=True,
            service=mock_service,
            interactive=False,
        )
        
        call_kwargs = mock_service.users().messages().list.call_args.kwargs
        q = call_kwargs.get("q", "")
        assert "linkedin" in q
        assert "is:unread" in q
    
    def test_empty_query_defaults_to_inbox(self):
        """Empty query should list inbox."""
        from bantz.google.gmail import gmail_list_messages
        
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
        }
        
        gmail_list_messages(
            query="",
            service=mock_service,
            interactive=False,
        )
        
        call_kwargs = mock_service.users().messages().list.call_args.kwargs
        # Should use labelIds for inbox, not q
        assert "labelIds" in call_kwargs or call_kwargs.get("q") is None
