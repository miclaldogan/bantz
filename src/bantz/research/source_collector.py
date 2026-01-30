"""
Source Collector (Issue #33 - V2-3).

Collects and extracts sources from web searches for the
cite-first research pipeline.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse


@dataclass
class Source:
    """
    Represents a research source with metadata.
    
    Attributes:
        url: Full URL of the source
        title: Title of the article/page
        snippet: Short excerpt or description
        date: Publication date if available
        domain: Extracted domain (e.g., "reuters.com")
        reliability_score: 0.0-1.0 reliability rating
        content_type: Type of content (article, news, academic, social)
    """
    url: str
    title: str
    snippet: str
    date: Optional[datetime] = None
    domain: str = ""
    reliability_score: float = 0.0
    content_type: str = "article"  # article, news, academic, social
    
    def __post_init__(self):
        """Extract domain from URL if not provided."""
        if not self.domain and self.url:
            self.domain = self._extract_domain(self.url)
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""


# Common date patterns for parsing
DATE_PATTERNS = [
    # ISO format
    (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
    # US format
    (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
    # European format
    (r"(\d{1,2}\.\d{1,2}\.\d{4})", "%d.%m.%Y"),
    # Month name format
    (r"(\w+ \d{1,2},? \d{4})", None),  # Special handling
    # Relative dates handled separately
]

# Month name mapping for parsing
MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class SourceCollector:
    """
    Collects sources from web searches.
    
    Uses web search tools to gather sources and extracts
    metadata for each source.
    """
    
    def __init__(self, search_tool=None):
        """
        Initialize SourceCollector.
        
        Args:
            search_tool: Optional web search tool to use.
                        If not provided, uses mock search for testing.
        """
        self.search_tool = search_tool
    
    async def collect(
        self,
        query: str,
        max_sources: int = 10
    ) -> list[Source]:
        """
        Collect sources for a query.
        
        Args:
            query: Search query string
            max_sources: Maximum number of sources to return
        
        Returns:
            List of Source objects ordered by relevance
        """
        if self.search_tool:
            # Use actual search tool
            from bantz.agent.tool_base import ToolContext
            context = ToolContext(job_id=f"collect-{int(time.time())}")
            result = await self.search_tool.run(
                {"query": query, "max_results": max_sources},
                context
            )
            
            if result.success and result.data:
                raw_results = result.data.get("results", [])
                sources = []
                for r in raw_results[:max_sources]:
                    source = Source(
                        url=r.get("url", ""),
                        title=r.get("title", ""),
                        snippet=r.get("snippet", ""),
                        date=self.parse_date(r.get("date", ""))
                    )
                    sources.append(source)
                return sources
        
        # Mock search for testing - returns empty list
        # Real implementation would use web search
        return []
    
    async def extract_metadata(self, url: str) -> Source:
        """
        Extract metadata from a URL.
        
        Args:
            url: URL to extract metadata from
        
        Returns:
            Source object with extracted metadata
        """
        # Parse domain from URL
        domain = ""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            pass
        
        # Determine content type from domain
        content_type = self._detect_content_type(domain)
        
        # Create source with basic info
        source = Source(
            url=url,
            title="",  # Would be fetched
            snippet="",  # Would be fetched
            domain=domain,
            content_type=content_type
        )
        
        return source
    
    def parse_date(self, raw_date: str) -> Optional[datetime]:
        """
        Parse a date string into datetime.
        
        Handles multiple formats:
        - ISO: 2024-01-15
        - US: 01/15/2024, 1/15/2024
        - European: 15.01.2024
        - Text: January 15, 2024, Jan 15 2024
        
        Args:
            raw_date: Raw date string
        
        Returns:
            datetime if parseable, None otherwise
        """
        if not raw_date:
            return None
        
        raw_date = raw_date.strip()
        
        # Try ISO format first (most common in APIs)
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_date)
        if iso_match:
            try:
                return datetime.strptime(iso_match.group(1), "%Y-%m-%d")
            except ValueError:
                pass
        
        # Try US format
        us_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", raw_date)
        if us_match:
            try:
                return datetime.strptime(us_match.group(1), "%m/%d/%Y")
            except ValueError:
                pass
        
        # Try European format
        eu_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", raw_date)
        if eu_match:
            try:
                return datetime.strptime(eu_match.group(1), "%d.%m.%Y")
            except ValueError:
                pass
        
        # Try text month format (e.g., "January 15, 2024")
        text_match = re.search(
            r"(\w+)\s+(\d{1,2}),?\s+(\d{4})",
            raw_date,
            re.IGNORECASE
        )
        if text_match:
            month_str = text_match.group(1).lower()
            day = int(text_match.group(2))
            year = int(text_match.group(3))
            
            if month_str in MONTH_NAMES:
                month = MONTH_NAMES[month_str]
                try:
                    return datetime(year, month, day)
                except ValueError:
                    pass
        
        # Try short format: "15 Jan 2024"
        short_match = re.search(
            r"(\d{1,2})\s+(\w+)\s+(\d{4})",
            raw_date,
            re.IGNORECASE
        )
        if short_match:
            day = int(short_match.group(1))
            month_str = short_match.group(2).lower()
            year = int(short_match.group(3))
            
            if month_str in MONTH_NAMES:
                month = MONTH_NAMES[month_str]
                try:
                    return datetime(year, month, day)
                except ValueError:
                    pass
        
        return None
    
    def _detect_content_type(self, domain: str) -> str:
        """Detect content type from domain."""
        domain_lower = domain.lower()
        
        # News domains
        news_domains = [
            "reuters.com", "bbc.com", "cnn.com", "nytimes.com",
            "theguardian.com", "apnews.com", "bloomberg.com"
        ]
        if any(d in domain_lower for d in news_domains):
            return "news"
        
        # Academic domains
        academic_domains = [
            "arxiv.org", "scholar.google", "pubmed", "doi.org",
            ".edu", "researchgate.net", "nature.com", "science.org"
        ]
        if any(d in domain_lower for d in academic_domains):
            return "academic"
        
        # Social media
        social_domains = [
            "twitter.com", "x.com", "facebook.com", "reddit.com",
            "instagram.com", "tiktok.com", "youtube.com"
        ]
        if any(d in domain_lower for d in social_domains):
            return "social"
        
        # Default to article
        return "article"
