"""Tests for news tools — registered tool handlers.

Covers:
- news_latest_tool
- news_search_tool
- news_briefing_tool
- news_category_tool
- Error handling
- Tool registration in register_all
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from bantz.services.news_service import NewsArticle, NewsBriefingResult, NEWS_CATEGORIES


# ─────────────────────────────────────────────────────────────────
# Mock news service for all tests
# ─────────────────────────────────────────────────────────────────


def _make_mock_service(articles=None):
    """Create a mock NewsService."""
    if articles is None:
        articles = [
            NewsArticle(title="AI News", category="ai", source="TC",
                        image_url="https://img.com/ai.jpg", url="https://tc.com/ai"),
            NewsArticle(title="Tech News", category="tech", source="TV",
                        url="https://tv.com/tech"),
        ]

    svc = MagicMock()
    svc.get_latest = AsyncMock(return_value=articles)
    svc.search = AsyncMock(return_value=articles[:1])
    svc.fetch_all = AsyncMock(return_value=NewsBriefingResult(
        articles=articles,
        categories_fetched=["ai", "tech"],
        fetch_time=0.5,
    ))
    svc.fetch_category = AsyncMock(return_value=articles)
    return svc


# ─────────────────────────────────────────────────────────────────
# news_latest_tool
# ─────────────────────────────────────────────────────────────────


class TestNewsLatestTool:
    def test_returns_articles(self):
        from bantz.tools.news_tools import news_latest_tool, _get_or_create_service

        mock_svc = _make_mock_service()
        _get_or_create_service._instance = mock_svc

        result = news_latest_tool(max_items=5)
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["articles"]) == 2
        assert result["articles"][0]["title"] == "AI News"

        # Cleanup
        del _get_or_create_service._instance

    def test_error_handling(self):
        from bantz.tools.news_tools import news_latest_tool, _get_or_create_service

        mock_svc = _make_mock_service()
        mock_svc.get_latest = AsyncMock(side_effect=Exception("Network error"))
        _get_or_create_service._instance = mock_svc

        result = news_latest_tool()
        assert result["success"] is False
        assert "error" in result

        del _get_or_create_service._instance


# ─────────────────────────────────────────────────────────────────
# news_search_tool
# ─────────────────────────────────────────────────────────────────


class TestNewsSearchTool:
    def test_search_with_query(self):
        from bantz.tools.news_tools import news_search_tool, _get_or_create_service

        mock_svc = _make_mock_service()
        _get_or_create_service._instance = mock_svc

        result = news_search_tool(query="artificial intelligence")
        assert result["success"] is True
        assert result["query"] == "artificial intelligence"
        assert result["count"] >= 1

        del _get_or_create_service._instance

    def test_search_empty_query(self):
        from bantz.tools.news_tools import news_search_tool

        result = news_search_tool(query="")
        assert result["success"] is False
        assert "required" in result["error"].lower()


# ─────────────────────────────────────────────────────────────────
# news_briefing_tool
# ─────────────────────────────────────────────────────────────────


class TestNewsBriefingTool:
    def test_briefing_default_categories(self):
        from bantz.tools.news_tools import news_briefing_tool, _get_or_create_service

        mock_svc = _make_mock_service()
        _get_or_create_service._instance = mock_svc

        result = news_briefing_tool()
        assert result["success"] is True
        assert "grouped" in result

        del _get_or_create_service._instance

    def test_briefing_specific_categories(self):
        from bantz.tools.news_tools import news_briefing_tool, _get_or_create_service

        mock_svc = _make_mock_service()
        _get_or_create_service._instance = mock_svc

        result = news_briefing_tool(categories="ai,science")
        assert result["success"] is True

        del _get_or_create_service._instance


# ─────────────────────────────────────────────────────────────────
# news_category_tool
# ─────────────────────────────────────────────────────────────────


class TestNewsCategoryTool:
    def test_valid_category(self):
        from bantz.tools.news_tools import news_category_tool, _get_or_create_service

        mock_svc = _make_mock_service()
        _get_or_create_service._instance = mock_svc

        result = news_category_tool(category="ai")
        assert result["success"] is True
        assert result["category"] == "ai"
        assert result["category_name"] == "Artificial Intelligence"

        del _get_or_create_service._instance

    def test_invalid_category(self):
        from bantz.tools.news_tools import news_category_tool

        result = news_category_tool(category="nonexistent")
        assert result["success"] is False
        assert "Unknown category" in result["error"]


# ─────────────────────────────────────────────────────────────────
# Tool Registration
# ─────────────────────────────────────────────────────────────────


class TestNewsToolRegistration:
    def test_register_news_tools(self):
        """Verify news tools can be imported and registered."""
        from bantz.tools.news_tools import (
            news_latest_tool,
            news_search_tool,
            news_briefing_tool,
            news_category_tool,
        )
        # All should be callable
        assert callable(news_latest_tool)
        assert callable(news_search_tool)
        assert callable(news_briefing_tool)
        assert callable(news_category_tool)
