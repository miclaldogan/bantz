"""Web search tool for BrainLoop (Issue #89).

Minimal web search implementation using DuckDuckGo HTML scraping.
For production, consider using official search APIs.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def web_search(query: str, count: int = 5) -> dict[str, Any]:
    """Search the web and return results.
    
    Args:
        query: Search query
        count: Maximum number of results (default: 5)
    
    Returns:
        {
            "ok": bool,
            "results": [
                {"title": str, "url": str, "snippet": str},
                ...
            ],
            "query": str,
            "count": int
        }
    """
    try:
        import requests
    except ImportError:
        return {
            "ok": False,
            "error": "requests library not installed",
            "results": [],
            "query": query,
            "count": 0,
        }
    
    query = str(query or "").strip()
    if not query:
        return {
            "ok": False,
            "error": "Empty query",
            "results": [],
            "query": "",
            "count": 0,
        }
    
    count = max(1, min(int(count or 5), 20))  # Limit 1-20
    
    try:
        # Use DuckDuckGo HTML (no API key needed)
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        html = response.text
        results = _parse_duckduckgo_html(html, max_results=count)
        
        return {
            "ok": True,
            "results": results,
            "query": query,
            "count": len(results),
        }
    
    except Exception as e:
        logger.error(f"web_search error: {e}")
        return {
            "ok": False,
            "error": str(e),
            "results": [],
            "query": query,
            "count": 0,
        }


def _parse_duckduckgo_html(html: str, max_results: int = 5) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML search results.
    
    This is a simple regex-based parser. For production, use BeautifulSoup.
    """
    results: list[dict[str, str]] = []
    
    # Match result blocks (simplified pattern)
    # DuckDuckGo HTML structure: <div class="result">...</div>
    result_pattern = r'<div class="result[^"]*">(.*?)</div>\s*</div>'
    
    matches = re.findall(result_pattern, html, re.DOTALL | re.IGNORECASE)
    
    for match in matches[:max_results]:
        try:
            # Extract title
            title_match = re.search(r'<a[^>]*class="result__a[^"]*"[^>]*>(.*?)</a>', match, re.DOTALL)
            title = ""
            if title_match:
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            
            # Extract URL
            url_match = re.search(r'<a[^>]*href="([^"]+)"', match)
            url = url_match.group(1) if url_match else ""
            
            # Clean up DuckDuckGo redirect URL
            if url.startswith("//duckduckgo.com/l/?"):
                url_param_match = re.search(r'uddg=([^&]+)', url)
                if url_param_match:
                    from urllib.parse import unquote
                    url = unquote(url_param_match.group(1))
            
            # Extract snippet
            snippet_match = re.search(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', match, re.DOTALL)
            snippet = ""
            if snippet_match:
                snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()
            
            if title and url:
                results.append({
                    "title": title[:200],  # Limit title length
                    "url": url,
                    "snippet": snippet[:300],  # Limit snippet length
                })
        except Exception as e:
            logger.debug(f"Failed to parse result: {e}")
            continue
    
    # Fallback: if regex fails, return mock results for testing
    if not results:
        logger.warning("DuckDuckGo HTML parsing failed, returning empty results")
    
    return results
