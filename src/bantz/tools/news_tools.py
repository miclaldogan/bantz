"""News tools — registered handlers for the tool registry.

Provides the following tools:
    news.latest     — Get latest news headlines across categories
    news.search     — Search news by query
    news.briefing   — Get a full news briefing (multi-category)
    news.category   — Get news for a specific category

All tools return structured dicts suitable for the finalizer LLM
to compose natural language responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "news_latest_tool",
    "news_search_tool",
    "news_briefing_tool",
    "news_category_tool",
]


def _get_or_create_service():
    """Lazy-load the NewsService singleton."""
    # Import here to avoid circular imports
    from bantz.services.news_service import NewsService

    if not hasattr(_get_or_create_service, "_instance"):
        _get_or_create_service._instance = NewsService.from_env()
    return _get_or_create_service._instance


def _run_async(coro):
    """Run async coroutine from sync tool handler."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an event loop — create a task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    else:
        return asyncio.run(coro)


def news_latest_tool(max_items: int = 5, **kwargs) -> Dict[str, Any]:
    """Get the latest news headlines.

    Parameters
    ----------
    max_items:
        Maximum number of articles to return (default: 5).

    Returns
    -------
    Dict with 'articles' list and metadata.
    """
    try:
        svc = _get_or_create_service()
        articles = _run_async(svc.get_latest(max_items=max_items))
        return {
            "success": True,
            "count": len(articles),
            "articles": [a.to_dict() for a in articles],
        }
    except Exception as e:
        logger.error("[news_tool] latest failed: %s", e)
        return {"success": False, "error": str(e), "articles": []}


def news_search_tool(query: str = "", max_results: int = 10, **kwargs) -> Dict[str, Any]:
    """Search news articles by query.

    Parameters
    ----------
    query:
        Search query string.
    max_results:
        Maximum number of results (default: 10).

    Returns
    -------
    Dict with matching articles.
    """
    if not query:
        return {"success": False, "error": "Query is required.", "articles": []}

    try:
        svc = _get_or_create_service()
        articles = _run_async(svc.search(query, max_results=max_results))
        return {
            "success": True,
            "query": query,
            "count": len(articles),
            "articles": [a.to_dict() for a in articles],
        }
    except Exception as e:
        logger.error("[news_tool] search failed: %s", e)
        return {"success": False, "error": str(e), "articles": []}


def news_briefing_tool(
    categories: str = "",
    max_items: int = 3,
    **kwargs,
) -> Dict[str, Any]:
    """Get a multi-category news briefing.

    Parameters
    ----------
    categories:
        Comma-separated category keys (e.g. 'ai,tech,world').
        Defaults to configured categories.
    max_items:
        Max articles per category (default: 3).

    Returns
    -------
    Dict with articles grouped by category.
    """
    try:
        svc = _get_or_create_service()
        cat_list = None
        if categories:
            cat_list = [c.strip() for c in categories.split(",") if c.strip()]

        briefing = _run_async(svc.fetch_all(categories=cat_list))

        # Group by category for structured output
        grouped: Dict[str, list] = {}
        for article in briefing.articles:
            cat = article.category
            if cat not in grouped:
                grouped[cat] = []
            if len(grouped[cat]) < max_items:
                grouped[cat].append(article.to_dict())

        return {
            "success": True,
            "count": briefing.count,
            "categories": briefing.categories_fetched,
            "fetch_time": round(briefing.fetch_time, 2),
            "grouped": grouped,
            "errors": briefing.errors,
        }
    except Exception as e:
        logger.error("[news_tool] briefing failed: %s", e)
        return {"success": False, "error": str(e), "grouped": {}}


def news_category_tool(
    category: str = "ai",
    max_items: int = 5,
    **kwargs,
) -> Dict[str, Any]:
    """Get news for a specific category.

    Parameters
    ----------
    category:
        Category key: ai, tech, world, turkey, science, business.
    max_items:
        Maximum articles (default: 5).

    Returns
    -------
    Dict with articles from the specified category.
    """
    try:
        from bantz.services.news_service import NEWS_CATEGORIES

        if category not in NEWS_CATEGORIES:
            available = ", ".join(sorted(NEWS_CATEGORIES.keys()))
            return {
                "success": False,
                "error": f"Unknown category: {category}. Available: {available}",
                "articles": [],
            }

        svc = _get_or_create_service()
        articles = _run_async(svc.fetch_category(category))
        trimmed = articles[:max_items]

        return {
            "success": True,
            "category": category,
            "category_name": NEWS_CATEGORIES[category].name,
            "count": len(trimmed),
            "articles": [a.to_dict() for a in trimmed],
        }
    except Exception as e:
        logger.error("[news_tool] category %s failed: %s", category, e)
        return {"success": False, "error": str(e), "articles": []}
