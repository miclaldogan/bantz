"""Citation and source verification for BrainLoop (Issue #90).

Implements 2-source rule and citation formatting.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def extract_citations_from_response(response: dict[str, Any]) -> list[dict[str, str]]:
    """Extract citations from LLM response.
    
    Args:
        response: LLM response dict (should contain 'citations' field)
    
    Returns:
        List of citations: [{"title": str, "url": str}, ...]
    """
    if not isinstance(response, dict):
        return []
    
    citations = response.get("citations")
    if not isinstance(citations, list):
        return []
    
    result: list[dict[str, str]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        
        title = str(citation.get("title") or "").strip()
        url = str(citation.get("url") or "").strip()
        
        if url:  # URL is required
            result.append({
                "title": title or "Untitled",
                "url": url,
            })
    
    return result


def verify_two_source_rule(citations: list[dict[str, str]]) -> tuple[bool, Optional[str]]:
    """Verify that citations satisfy 2-source rule.
    
    Args:
        citations: List of citations
    
    Returns:
        (valid: bool, reason: Optional[str])
    """
    if not citations:
        return False, "No citations provided"
    
    if len(citations) < 2:
        return False, "Insufficient sources (need at least 2)"
    
    # Check domain diversity
    domains = set()
    for citation in citations:
        url = citation.get("url", "")
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            domains.add(domain)
        except Exception:
            continue
    
    if len(domains) < 2:
        return False, "Citations from same domain (need 2+ domains)"
    
    return True, None


def format_citations_for_display(citations: list[dict[str, str]]) -> str:
    """Format citations for user display.
    
    Args:
        citations: List of citations
    
    Returns:
        Formatted citation string
    """
    if not citations:
        return ""
    
    lines = ["Kaynaklar:"]
    for i, citation in enumerate(citations, start=1):
        title = citation.get("title", "Untitled")
        url = citation.get("url", "")
        lines.append(f"{i}. {title}")
        lines.append(f"   {url}")
    
    return "\n".join(lines)


def extract_sources_from_tool_results(tool_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract sources from web tool results.
    
    Args:
        tool_results: List of tool execution results
    
    Returns:
        List of sources: [{"title": str, "url": str}, ...]
    """
    sources: list[dict[str, str]] = []
    
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        
        tool_name = result.get("tool_name", "")
        output = result.get("output")
        
        # Handle web.search results
        if tool_name == "web.search" and isinstance(output, dict):
            search_results = output.get("results")
            if isinstance(search_results, list):
                for item in search_results:
                    if isinstance(item, dict):
                        title = item.get("title", "")
                        url = item.get("url", "")
                        if url:
                            sources.append({"title": title, "url": url})
        
        # Handle web.open results
        elif tool_name == "web.open" and isinstance(output, dict):
            if output.get("ok"):
                title = output.get("title", "")
                url = output.get("url", "")
                if url:
                    sources.append({"title": title, "url": url})
    
    return sources


def validate_citation_quality(
    citations: list[dict[str, str]],
    tool_sources: list[dict[str, str]],
) -> tuple[bool, list[str]]:
    """Validate citation quality against tool sources.
    
    Args:
        citations: Citations from LLM response
        tool_sources: Sources from tool execution
    
    Returns:
        (valid: bool, warnings: list[str])
    """
    warnings: list[str] = []
    
    # Check if citations match tool sources
    cited_urls = {c.get("url", "").lower() for c in citations}
    source_urls = {s.get("url", "").lower() for s in tool_sources}
    
    # Warn if citing sources that weren't in tool results
    unknown_citations = cited_urls - source_urls
    if unknown_citations:
        warnings.append(f"LLM cited {len(unknown_citations)} unknown sources")
    
    # Warn if tool sources weren't cited
    uncited_sources = source_urls - cited_urls
    if len(uncited_sources) > len(source_urls) / 2:
        warnings.append(f"Many tool sources not cited ({len(uncited_sources)}/{len(source_urls)})")
    
    # Valid if no major issues
    valid = len(warnings) == 0 or (len(citations) >= 2 and len(unknown_citations) == 0)
    
    return valid, warnings
