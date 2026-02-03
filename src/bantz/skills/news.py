"""
News Briefing Skill.

Jarvis-style news search and briefing:
- Search news from various sources
- Format for TTS and overlay display
- Open specific results
- Continuous listening after action

Example:
    User: "Bugünkü haberlerde ne var?"
    Bantz: "Şimdi sizin için arıyorum efendim..."
           [searches news]
    Bantz: "Sonuçlar burada efendim. 8 haber buldum..."
           [shows in overlay]
    User: "3. haberi aç"
    Bantz: "Açıyorum efendim."
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
from urllib.parse import quote_plus, urlparse
import asyncio
import logging
import re

if TYPE_CHECKING:
    from bantz.browser.extension_bridge import ExtensionBridge

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NewsItem:
    """A single news item."""
    
    title: str
    snippet: str
    url: str
    source: str
    timestamp: Optional[str] = None
    image_url: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for overlay."""
        return {
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "source": self.source,
            "timestamp": self.timestamp,
            "image_url": self.image_url,
        }


@dataclass
class NewsSearchResult:
    """Result of a news search."""
    
    query: str
    items: List[NewsItem]
    source_url: str
    search_time: datetime = field(default_factory=datetime.now)
    
    @property
    def count(self) -> int:
        """Number of items found."""
        return len(self.items)
    
    @property
    def has_results(self) -> bool:
        """Check if any results found."""
        return len(self.items) > 0


# =============================================================================
# News Sources
# =============================================================================


class NewsSource:
    """Base class for news sources."""
    
    name: str = "base"
    
    def get_search_url(self, query: str) -> str:
        """Get search URL for query."""
        raise NotImplementedError
    
    def parse_results(self, scan_data: Dict[str, Any]) -> List[NewsItem]:
        """Parse scan results into news items."""
        raise NotImplementedError


class GoogleNewsSource(NewsSource):
    """Google News search source."""
    
    name = "google_news"
    
    def get_search_url(self, query: str) -> str:
        """Get Google News search URL."""
        encoded = quote_plus(query)
        return f"https://news.google.com/search?q={encoded}&hl=tr&gl=TR&ceid=TR:tr"
    
    def parse_results(self, scan_data: Dict[str, Any]) -> List[NewsItem]:
        """Parse Google News scan results."""
        items = []
        links = scan_data.get("links", [])
        
        for link in links:
            href = link.get("href", "")
            text = link.get("text", "").strip()
            
            # Filter news article links
            if not self._is_news_link(href, text):
                continue
            
            # Extract source from URL
            source = self._extract_source(href)
            
            items.append(NewsItem(
                title=text,
                snippet=link.get("aria", "") or link.get("title", ""),
                url=href,
                source=source,
            ))
        
        return items[:10]  # Limit to 10 results
    
    def _is_news_link(self, href: str, text: str) -> bool:
        """Check if link is a news article."""
        if not href or not text:
            return False
        
        # Skip navigation links
        skip_patterns = [
            "accounts.google.com",
            "support.google.com",
            "policies.google.com",
            "news.google.com/topics",
            "news.google.com/settings",
            "/preferences",
            "/signin",
        ]
        for pattern in skip_patterns:
            if pattern in href:
                return False
        
        # Must have substantial title
        if len(text) < 15:
            return False
        
        return True
    
    def _extract_source(self, url: str) -> str:
        """Extract source name from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            
            # Remove www. and common suffixes
            domain = domain.replace("www.", "")
            
            # Map common domains to friendly names
            source_map = {
                "hurriyet.com.tr": "Hürriyet",
                "haberturk.com": "Habertürk",
                "ntv.com.tr": "NTV",
                "cnnturk.com": "CNN Türk",
                "milliyet.com.tr": "Milliyet",
                "sabah.com.tr": "Sabah",
                "sozcu.com.tr": "Sözcü",
                "cumhuriyet.com.tr": "Cumhuriyet",
                "bbc.com": "BBC",
                "reuters.com": "Reuters",
                "aa.com.tr": "Anadolu Ajansı",
            }
            
            return source_map.get(domain, domain)
        except Exception:
            return "Bilinmeyen"


class GoogleSearchSource(NewsSource):
    """Google Search for news queries."""
    
    name = "google_search"
    
    def get_search_url(self, query: str) -> str:
        """Get Google search URL with news filter."""
        encoded = quote_plus(f"{query} haber")
        return f"https://www.google.com/search?q={encoded}&tbm=nws&hl=tr"
    
    def parse_results(self, scan_data: Dict[str, Any]) -> List[NewsItem]:
        """Parse Google search news results."""
        items = []
        links = scan_data.get("links", [])
        
        for link in links:
            href = link.get("href", "")
            text = link.get("text", "").strip()
            
            if not href or not text or len(text) < 15:
                continue
            
            # Skip Google internal links (Security Alert #9: use domain parsing)
            # Check if domain is google.com (not just substring)
            from urllib.parse import urlparse
            try:
                parsed = urlparse(href)
                is_google_internal = (parsed.netloc.endswith("google.com") or parsed.netloc == "google.com") and "url?" not in href
            except Exception:
                is_google_internal = False
            
            if is_google_internal:
                continue
            
            source = self._extract_source(href)
            
            items.append(NewsItem(
                title=text,
                snippet=link.get("aria", ""),
                url=href,
                source=source,
            ))
        
        return items[:10]
    
    def _extract_source(self, url: str) -> str:
        """Extract source from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return "Bilinmeyen"


# =============================================================================
# News Briefing System
# =============================================================================


class NewsBriefing:
    """
    Jarvis-style news briefing system.
    
    Searches news from configured sources, formats for TTS and overlay,
    and allows opening specific results.
    
    Example:
        news = NewsBriefing(extension_bridge)
        
        # Search news
        result = await news.search("ekonomi")
        
        # Format for TTS
        tts_text = news.format_for_tts()
        
        # Format for overlay
        overlay_data = news.format_for_overlay()
        
        # Open specific result
        await news.open_result(3)  # Opens 3rd result
    """
    
    DEFAULT_SOURCES = [
        GoogleNewsSource(),
        GoogleSearchSource(),
    ]
    
    def __init__(
        self,
        extension_bridge: Optional["ExtensionBridge"] = None,
        sources: Optional[List[NewsSource]] = None,
        search_timeout: float = 5.0,
        page_load_wait: float = 2.0,
    ):
        """
        Initialize news briefing.
        
        Args:
            extension_bridge: Browser extension bridge for web actions
            sources: List of news sources (uses defaults if None)
            search_timeout: Timeout for search operations
            page_load_wait: Wait time for page to load
        """
        self.bridge = extension_bridge
        self.sources = sources or self.DEFAULT_SOURCES
        self.search_timeout = search_timeout
        self.page_load_wait = page_load_wait
        
        # State
        self._last_result: Optional[NewsSearchResult] = None
        self._current_index: int = 0
    
    async def search(
        self,
        query: str = "gündem",
        source_name: Optional[str] = None,
    ) -> NewsSearchResult:
        """
        Search for news.
        
        Args:
            query: Search query (default: "gündem" for general news)
            source_name: Specific source to use (uses first available if None)
            
        Returns:
            NewsSearchResult with found items
        """
        # Select source
        source = self._get_source(source_name)
        if not source:
            logger.error("No news source available")
            return NewsSearchResult(query=query, items=[], source_url="")
        
        # Get search URL
        search_url = source.get_search_url(query)
        logger.info(f"[News] Searching: {query} via {source.name}")
        
        # Open search page
        if self.bridge:
            self.bridge.request_navigate(search_url)
            
            # Wait for page to load
            await asyncio.sleep(self.page_load_wait)
            
            # Scan page
            scan_data = self.bridge.request_scan()
            
            if scan_data:
                items = source.parse_results(scan_data)
                logger.info(f"[News] Found {len(items)} news items")
            else:
                items = []
                logger.warning("[News] No scan data received")
        else:
            # No bridge - return empty result
            items = []
            logger.warning("[News] No extension bridge available")
        
        # Store result
        self._last_result = NewsSearchResult(
            query=query,
            items=items,
            source_url=search_url,
        )
        self._current_index = 0
        
        return self._last_result
    
    def _get_source(self, source_name: Optional[str] = None) -> Optional[NewsSource]:
        """Get source by name or first available."""
        if source_name:
            for source in self.sources:
                if source.name == source_name:
                    return source
        return self.sources[0] if self.sources else None
    
    async def open_result(self, index: int) -> bool:
        """
        Open a specific search result.
        
        Args:
            index: 1-based index of result to open
            
        Returns:
            True if opened successfully
        """
        if not self._last_result or not self._last_result.items:
            logger.warning("[News] No results to open")
            return False
        
        # Convert to 0-based index
        idx = index - 1
        
        if idx < 0 or idx >= len(self._last_result.items):
            logger.warning(f"[News] Invalid index: {index}")
            return False
        
        item = self._last_result.items[idx]
        logger.info(f"[News] Opening: {item.title}")
        
        if self.bridge:
            self.bridge.request_navigate(item.url)
            self._current_index = idx
            return True
        
        return False
    
    async def open_current(self) -> bool:
        """Open currently highlighted result."""
        return await self.open_result(self._current_index + 1)
    
    async def open_next(self) -> bool:
        """Open next result."""
        if not self._last_result:
            return False
        next_idx = min(self._current_index + 1, len(self._last_result.items) - 1)
        return await self.open_result(next_idx + 1)
    
    async def open_previous(self) -> bool:
        """Open previous result."""
        if not self._last_result:
            return False
        prev_idx = max(self._current_index - 1, 0)
        return await self.open_result(prev_idx + 1)
    
    def format_for_tts(self, max_items: int = 3) -> str:
        """
        Format results for text-to-speech.
        
        Args:
            max_items: Maximum items to include in speech
            
        Returns:
            TTS-friendly summary string
        """
        if not self._last_result or not self._last_result.items:
            return "Maalesef haber bulunamadı efendim."
        
        items = self._last_result.items
        total = len(items)
        
        # Build summary
        parts = [f"{total} haber buldum efendim."]
        
        for i, item in enumerate(items[:max_items], 1):
            # Clean title for speech
            title = self._clean_for_speech(item.title)
            parts.append(f"{i}. {title}.")
        
        if total > max_items:
            parts.append(f"Devamını görmek için 'daha fazla' diyebilirsiniz.")
        
        return " ".join(parts)
    
    def format_more_for_tts(self, start: int = 4, count: int = 3) -> str:
        """Format additional results for TTS."""
        if not self._last_result or not self._last_result.items:
            return "Başka haber yok efendim."
        
        items = self._last_result.items[start - 1:start - 1 + count]
        
        if not items:
            return "Başka haber yok efendim."
        
        parts = []
        for i, item in enumerate(items, start):
            title = self._clean_for_speech(item.title)
            parts.append(f"{i}. {title}.")
        
        return " ".join(parts)
    
    def _clean_for_speech(self, text: str) -> str:
        """Clean text for TTS."""
        # Remove source prefixes like "Hürriyet - "
        text = re.sub(r"^[A-Za-zÇĞİÖŞÜçğıöşü\s]+\s*[-–—]\s*", "", text)
        
        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)
        
        # Remove special characters
        text = re.sub(r"[\"'`]", "", text)
        
        # Truncate long titles
        if len(text) > 100:
            text = text[:100].rsplit(" ", 1)[0] + "..."
        
        return text.strip()
    
    def format_for_overlay(self) -> Dict[str, Any]:
        """
        Format results for overlay display.
        
        Returns:
            Dictionary with overlay data
        """
        if not self._last_result:
            return {
                "type": "news_results",
                "query": "",
                "items": [],
                "total": 0,
            }
        
        items = []
        for i, item in enumerate(self._last_result.items):
            # Truncate snippet
            snippet = item.snippet
            if len(snippet) > 120:
                snippet = snippet[:120].rsplit(" ", 1)[0] + "..."
            
            items.append({
                "index": i + 1,
                "title": item.title,
                "source": item.source,
                "snippet": snippet,
                "url": item.url,
                "timestamp": item.timestamp,
            })
        
        return {
            "type": "news_results",
            "query": self._last_result.query,
            "items": items,
            "total": len(items),
            "current_index": self._current_index,
            "source_url": self._last_result.source_url,
        }
    
    def get_result_by_index(self, index: int) -> Optional[NewsItem]:
        """Get specific result by index (1-based)."""
        if not self._last_result:
            return None
        
        idx = index - 1
        if 0 <= idx < len(self._last_result.items):
            return self._last_result.items[idx]
        return None
    
    def get_current_result(self) -> Optional[NewsItem]:
        """Get currently selected result."""
        if not self._last_result or not self._last_result.items:
            return None
        return self._last_result.items[self._current_index]
    
    @property
    def has_results(self) -> bool:
        """Check if there are results available."""
        return self._last_result is not None and self._last_result.has_results
    
    @property
    def result_count(self) -> int:
        """Get number of results."""
        return self._last_result.count if self._last_result else 0
    
    def clear_results(self) -> None:
        """Clear stored results."""
        self._last_result = None
        self._current_index = 0


# =============================================================================
# Mock Implementation
# =============================================================================


class MockNewsBriefing(NewsBriefing):
    """Mock news briefing for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_items: List[NewsItem] = []
        self._search_calls: List[str] = []
        self._open_calls: List[int] = []
    
    def set_mock_results(self, items: List[NewsItem]) -> None:
        """Set mock search results."""
        self._mock_items = items
    
    async def search(
        self,
        query: str = "gündem",
        source_name: Optional[str] = None,
    ) -> NewsSearchResult:
        """Return mock results."""
        self._search_calls.append(query)
        
        self._last_result = NewsSearchResult(
            query=query,
            items=self._mock_items.copy(),
            source_url=f"https://news.google.com/search?q={quote_plus(query)}",
        )
        self._current_index = 0
        
        return self._last_result
    
    async def open_result(self, index: int) -> bool:
        """Record open call."""
        self._open_calls.append(index)
        
        if not self._last_result:
            return False
        
        idx = index - 1
        if 0 <= idx < len(self._last_result.items):
            self._current_index = idx
            return True
        return False
    
    def get_search_calls(self) -> List[str]:
        """Get all search queries."""
        return self._search_calls.copy()
    
    def get_open_calls(self) -> List[int]:
        """Get all open indices."""
        return self._open_calls.copy()


# =============================================================================
# Convenience Functions
# =============================================================================


def extract_news_query(text: str) -> str:
    """
    Extract news query from natural language.
    
    Examples:
        "teknoloji haberleri" -> "teknoloji"
        "ekonomi ile ilgili haberler" -> "ekonomi"
        "bugünkü haberler" -> "gündem"
    """
    text = text.lower().strip()
    
    # Remove common phrases
    removals = [
        r"\b(bugünkü|günlük|son)\s+",
        r"\bhaberleri?\b",
        r"\bile\s+ilgili\b",
        r"\bhakkında\b",
        r"\bne\s+var\b",
        r"\bneler?\s+var\b",
        r"\bgündem(i|de)?\b",
    ]
    
    for pattern in removals:
        text = re.sub(pattern, "", text)
    
    text = text.strip()
    
    # Default to "gündem" if empty
    return text if text else "gündem"


def is_news_intent(text: str) -> bool:
    """Check if text is a news-related intent."""
    patterns = [
        r"\b(bugünkü|günlük|son)?\s*haber",
        r"\bgündem\b",
        r"\bhaber.*ne\s+var\b",
        r"\bhaber.*neler\b",
    ]
    
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False
