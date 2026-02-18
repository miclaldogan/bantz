"""Async News Service — multi-source news aggregation with images.

Fetches news from multiple providers (RSS feeds + NewsAPI-compatible APIs),
caches results, extracts images, and provides structured data for the
daily briefing and on-demand news tools.

Env vars::

    BANTZ_NEWS_API_KEY=<your-newsapi-key>   # optional, enables NewsAPI
    BANTZ_NEWS_CACHE_TTL=1800               # 30 min cache (seconds)
    BANTZ_NEWS_MAX_ITEMS=10                 # max items per category
    BANTZ_NEWS_CATEGORIES=ai,tech,world,turkey
    BANTZ_NEWS_IMAGE_ENABLED=true           # fetch article images
    BANTZ_NEWS_TIMEOUT=15                   # HTTP timeout (seconds)

Categories::

    ai       — Artificial Intelligence (TechCrunch AI, The Verge AI, OpenAI blog)
    tech     — Technology (The Verge, Ars Technica, Hacker News)
    world    — World News (Reuters, BBC, AP)
    turkey   — Turkey / Türkiye (NTV, Hürriyet, TRT)
    science  — Science (Nature, Science Daily)
    business — Business (Bloomberg, Financial Times)

Usage::

    from bantz.services.news_service import NewsService
    svc = NewsService.from_env()
    items = await svc.fetch_category("ai")
    briefing = await svc.build_briefing(["ai", "tech", "turkey"])
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import ssl
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import quote_plus

import aiohttp

logger = logging.getLogger(__name__)

__all__ = [
    "NewsArticle",
    "NewsCategoryDef",
    "NEWS_CATEGORIES",
    "NewsService",
    "NewsServiceConfig",
    "NewsBriefingResult",
]


# ─────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────


@dataclass
class NewsArticle:
    """A single news article with optional image."""

    title: str
    summary: str = ""
    url: str = ""
    source: str = ""
    image_url: Optional[str] = None
    published: str = ""
    category: str = ""

    @property
    def fingerprint(self) -> str:
        """Unique hash for deduplication."""
        raw = f"{self.title}:{self.url}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable dict for IPC/API."""
        return {
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "image_url": self.image_url,
            "published": self.published,
            "category": self.category,
            "fingerprint": self.fingerprint,
        }


@dataclass
class NewsCategoryDef:
    """Category definition with feed URLs."""

    key: str
    name: str
    rss_feeds: List[str] = field(default_factory=list)
    newsapi_query: str = ""
    keywords: List[str] = field(default_factory=list)


@dataclass
class NewsBriefingResult:
    """Aggregated briefing result across categories."""

    articles: List[NewsArticle] = field(default_factory=list)
    categories_fetched: List[str] = field(default_factory=list)
    fetch_time: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.articles)

    @property
    def has_articles(self) -> bool:
        return len(self.articles) > 0

    def by_category(self, category: str) -> List[NewsArticle]:
        """Filter articles by category."""
        return [a for a in self.articles if a.category == category]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "articles": [a.to_dict() for a in self.articles],
            "categories_fetched": self.categories_fetched,
            "fetch_time": round(self.fetch_time, 2),
            "count": self.count,
            "errors": self.errors,
        }


# ─────────────────────────────────────────────────────────────────
# Category Definitions
# ─────────────────────────────────────────────────────────────────

NEWS_CATEGORIES: Dict[str, NewsCategoryDef] = {
    "ai": NewsCategoryDef(
        key="ai",
        name="Artificial Intelligence",
        rss_feeds=[
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        ],
        newsapi_query="artificial intelligence OR AI OR machine learning",
        keywords=["AI", "GPT", "LLM", "machine learning", "neural network",
                  "OpenAI", "Anthropic", "Google DeepMind"],
    ),
    "tech": NewsCategoryDef(
        key="tech",
        name="Technology",
        rss_feeds=[
            "https://www.theverge.com/rss/index.xml",
            "https://feeds.arstechnica.com/arstechnica/index",
            "https://hnrss.org/frontpage?count=10",
        ],
        newsapi_query="technology OR software OR hardware",
        keywords=["technology", "software", "hardware", "startup", "silicon valley"],
    ),
    "world": NewsCategoryDef(
        key="world",
        name="World News",
        rss_feeds=[
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        ],
        newsapi_query="world news OR international",
        keywords=["world", "international", "politics", "diplomacy"],
    ),
    "turkey": NewsCategoryDef(
        key="turkey",
        name="Turkey",
        rss_feeds=[
            "https://www.ntv.com.tr/son-dakika.rss",
            "https://www.hurriyet.com.tr/rss/gundem",
        ],
        newsapi_query="Turkey OR Türkiye",
        keywords=["Turkey", "Türkiye", "Istanbul", "Ankara"],
    ),
    "science": NewsCategoryDef(
        key="science",
        name="Science",
        rss_feeds=[
            "https://www.sciencedaily.com/rss/all.xml",
        ],
        newsapi_query="science research discovery",
        keywords=["science", "research", "study", "discovery", "space", "NASA"],
    ),
    "business": NewsCategoryDef(
        key="business",
        name="Business",
        rss_feeds=[
            "https://feeds.bbci.co.uk/news/business/rss.xml",
        ],
        newsapi_query="business economy markets",
        keywords=["business", "economy", "markets", "stocks", "finance"],
    ),
}


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


@dataclass
class NewsServiceConfig:
    """Service configuration loaded from env."""

    api_key: str = ""
    cache_ttl: int = 1800
    max_items_per_category: int = 10
    categories: List[str] = field(
        default_factory=lambda: ["ai", "tech", "world", "turkey"]
    )
    image_enabled: bool = True
    timeout: float = 15.0
    newsapi_base_url: str = "https://newsapi.org/v2"

    @classmethod
    def from_env(cls) -> "NewsServiceConfig":
        """Load config from environment variables."""
        raw_cats = os.getenv("BANTZ_NEWS_CATEGORIES", "ai,tech,world,turkey")
        cats = [c.strip() for c in raw_cats.split(",") if c.strip()]

        try:
            ttl = int(os.getenv("BANTZ_NEWS_CACHE_TTL", "1800"))
        except ValueError:
            ttl = 1800

        try:
            max_items = int(os.getenv("BANTZ_NEWS_MAX_ITEMS", "10"))
        except ValueError:
            max_items = 10

        try:
            timeout = float(os.getenv("BANTZ_NEWS_TIMEOUT", "15"))
        except ValueError:
            timeout = 15.0

        img_raw = os.getenv("BANTZ_NEWS_IMAGE_ENABLED", "true").lower().strip()
        image_enabled = img_raw in {"1", "true", "yes", "on"}

        return cls(
            api_key=os.getenv("BANTZ_NEWS_API_KEY", ""),
            cache_ttl=ttl,
            max_items_per_category=max_items,
            categories=cats,
            image_enabled=image_enabled,
            timeout=timeout,
        )


# ─────────────────────────────────────────────────────────────────
# News Cache (thread-safe, TTL-based)
# ─────────────────────────────────────────────────────────────────


class _NewsCache:
    """In-memory TTL cache for news articles."""

    def __init__(self, ttl_seconds: int = 1800, clock: Optional[Callable] = None):
        self._ttl = ttl_seconds
        self._clock = clock or time.monotonic
        self._store: Dict[str, tuple[float, List[NewsArticle]]] = {}

    def get(self, key: str) -> Optional[List[NewsArticle]]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, items = entry
        if self._clock() - ts > self._ttl:
            del self._store[key]
            return None
        return items

    def set(self, key: str, items: List[NewsArticle]) -> None:
        self._store[key] = (self._clock(), items)

    def clear(self) -> None:
        self._store.clear()

    @property
    def age(self) -> Dict[str, float]:
        """Age in seconds for each cached category."""
        now = self._clock()
        return {k: now - ts for k, (ts, _) in self._store.items()}


# ─────────────────────────────────────────────────────────────────
# RSS Parser (async)
# ─────────────────────────────────────────────────────────────────

_RSS_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Bantz/2.0"
)

# Common image extraction patterns
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_MEDIA_CONTENT_RE = re.compile(
    r'url=["\']([^"\']+\.(jpg|jpeg|png|webp|gif))["\']',
    re.IGNORECASE,
)
_ENCLOSURE_RE = re.compile(
    r'<enclosure[^>]+url=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _extract_image_from_xml(item_text: str) -> Optional[str]:
    """Try to extract an image URL from RSS item XML chunk."""
    # media:content
    for pattern in (_MEDIA_CONTENT_RE, _ENCLOSURE_RE, _OG_IMAGE_RE):
        m = pattern.search(item_text)
        if m:
            return m.group(1)
    return None


def _extract_image_from_description(desc: str) -> Optional[str]:
    """Try to extract an image from HTML description content."""
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.IGNORECASE)
    if img_match:
        return img_match.group(1)
    return None


def _clean_html(text: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _fetch_rss_feed(
    session: aiohttp.ClientSession,
    feed_url: str,
    category: NewsCategoryDef,
    *,
    max_items: int = 10,
    extract_images: bool = True,
) -> List[NewsArticle]:
    """Fetch and parse a single RSS/Atom feed."""
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        async with session.get(
            feed_url,
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=ssl_ctx,
            headers={"User-Agent": _RSS_USER_AGENT},
        ) as resp:
            if resp.status != 200:
                logger.warning("[news] HTTP %d from %s", resp.status, feed_url)
                return []
            data = await resp.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("[news] fetch error for %s: %s", feed_url, e)
        return []

    return _parse_feed_xml(data, category, feed_url, max_items, extract_images)


def _parse_feed_xml(
    data: bytes,
    category: NewsCategoryDef,
    source_url: str,
    max_items: int,
    extract_images: bool,
) -> List[NewsArticle]:
    """Parse RSS/Atom XML into NewsArticle list."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        logger.warning("[news] XML parse error for %s", source_url)
        return []

    articles: List[NewsArticle] = []
    raw_xml = data.decode("utf-8", errors="replace")

    # RSS 2.0 — <channel><item>
    for item_el in root.iter("item"):
        if len(articles) >= max_items:
            break

        title = _clean_html(item_el.findtext("title") or "")
        desc_raw = item_el.findtext("description") or ""
        link = (item_el.findtext("link") or "").strip()
        pub = (item_el.findtext("pubDate") or "").strip()

        if not title:
            continue

        summary = _clean_html(desc_raw)
        if len(summary) > 250:
            summary = summary[:247] + "..."

        image_url = None
        if extract_images:
            # Try media:content, enclosure, then description img
            item_str = ET.tostring(item_el, encoding="unicode", method="xml")
            image_url = _extract_image_from_xml(item_str)
            if not image_url:
                image_url = _extract_image_from_description(desc_raw)

        # Extract source name from URL
        source_name = _url_to_source_name(source_url)

        articles.append(NewsArticle(
            title=title,
            summary=summary,
            url=link,
            source=source_name,
            image_url=image_url,
            published=pub,
            category=category.key,
        ))

    # Atom — <entry>
    atom_ns = "http://www.w3.org/2005/Atom"
    for entry in root.iter(f"{{{atom_ns}}}entry"):
        if len(articles) >= max_items:
            break

        title = _clean_html(
            entry.findtext(f"{{{atom_ns}}}title") or ""
        )
        summary_el = entry.find(f"{{{atom_ns}}}summary")
        summary_raw = (summary_el.text or "") if summary_el is not None else ""
        link_el = entry.find(f"{{{atom_ns}}}link")
        link = link_el.get("href", "") if link_el is not None else ""

        if not title:
            continue

        summary = _clean_html(summary_raw)
        if len(summary) > 250:
            summary = summary[:247] + "..."

        image_url = None
        if extract_images:
            item_str = ET.tostring(entry, encoding="unicode", method="xml")
            image_url = _extract_image_from_xml(item_str)
            if not image_url:
                image_url = _extract_image_from_description(summary_raw)

        source_name = _url_to_source_name(source_url)

        articles.append(NewsArticle(
            title=title,
            summary=summary,
            url=link,
            source=source_name,
            image_url=image_url,
            category=category.key,
        ))

    return articles


def _url_to_source_name(url: str) -> str:
    """Extract human-readable source name from feed URL."""
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        # Remove www. prefix
        if hostname.startswith("www."):
            hostname = hostname[4:]
        # Remove TLD
        parts = hostname.split(".")
        if len(parts) >= 2:
            return parts[0].capitalize()
        return hostname.capitalize()
    except Exception:
        return "Unknown"


# ─────────────────────────────────────────────────────────────────
# NewsAPI Client (optional, needs API key)
# ─────────────────────────────────────────────────────────────────


async def _fetch_newsapi(
    session: aiohttp.ClientSession,
    api_key: str,
    query: str,
    category: NewsCategoryDef,
    base_url: str = "https://newsapi.org/v2",
    max_items: int = 10,
) -> List[NewsArticle]:
    """Fetch from NewsAPI.org (requires API key)."""
    if not api_key:
        return []

    url = f"{base_url}/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": min(max_items, 100),
        "apiKey": api_key,
    }

    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning("[news][api] HTTP %d for query=%s", resp.status, query)
                return []
            data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("[news][api] fetch error for %s: %s", query, e)
        return []

    if data.get("status") != "ok":
        logger.warning("[news][api] status=%s for %s", data.get("status"), query)
        return []

    articles: List[NewsArticle] = []
    for item in data.get("articles", [])[:max_items]:
        title = (item.get("title") or "").strip()
        if not title or title == "[Removed]":
            continue

        articles.append(NewsArticle(
            title=title,
            summary=(item.get("description") or "")[:250],
            url=item.get("url", ""),
            source=item.get("source", {}).get("name", ""),
            image_url=item.get("urlToImage"),
            published=item.get("publishedAt", ""),
            category=category.key,
        ))

    return articles


# ─────────────────────────────────────────────────────────────────
# Main Service
# ─────────────────────────────────────────────────────────────────


class NewsService:
    """Async news aggregation service.

    Fetches from RSS feeds and optionally from NewsAPI,
    caches results, and serves structured data.

    Parameters
    ----------
    config:
        Service configuration.
    clock:
        Injectable clock for testing.
    """

    def __init__(
        self,
        config: Optional[NewsServiceConfig] = None,
        clock: Optional[Callable] = None,
    ) -> None:
        self._config = config or NewsServiceConfig()
        self._cache = _NewsCache(
            ttl_seconds=self._config.cache_ttl,
            clock=clock,
        )
        self._session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def from_env(cls) -> "NewsService":
        """Create service from environment variables."""
        return cls(config=NewsServiceConfig.from_env())

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazy session creation."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Clean up HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def fetch_category(
        self,
        category_key: str,
        *,
        force_refresh: bool = False,
    ) -> List[NewsArticle]:
        """Fetch news for a category, using cache when available.

        Parameters
        ----------
        category_key:
            Category key (e.g. 'ai', 'tech', 'world').
        force_refresh:
            Bypass cache and fetch fresh.

        Returns
        -------
        List of NewsArticle, deduplicated and sorted by recency.
        """
        if not force_refresh:
            cached = self._cache.get(category_key)
            if cached is not None:
                logger.debug("[news] cache hit for %s (%d items)", category_key, len(cached))
                return cached

        cat = NEWS_CATEGORIES.get(category_key)
        if cat is None:
            logger.warning("[news] unknown category: %s", category_key)
            return []

        session = await self._get_session()
        all_articles: List[NewsArticle] = []

        # Fetch RSS feeds concurrently
        rss_tasks = [
            _fetch_rss_feed(
                session, feed_url, cat,
                max_items=self._config.max_items_per_category,
                extract_images=self._config.image_enabled,
            )
            for feed_url in cat.rss_feeds
        ]

        # Also query NewsAPI if configured
        if self._config.api_key and cat.newsapi_query:
            rss_tasks.append(
                _fetch_newsapi(
                    session,
                    self._config.api_key,
                    cat.newsapi_query,
                    cat,
                    base_url=self._config.newsapi_base_url,
                    max_items=self._config.max_items_per_category,
                )
            )

        results = await asyncio.gather(*rss_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("[news] feed error: %s", result)
                continue
            all_articles.extend(result)

        # Deduplicate by fingerprint
        seen: set[str] = set()
        unique: List[NewsArticle] = []
        for article in all_articles:
            fp = article.fingerprint
            if fp not in seen:
                seen.add(fp)
                unique.append(article)

        # Trim to max items
        unique = unique[: self._config.max_items_per_category]

        self._cache.set(category_key, unique)
        logger.info("[news] fetched %d articles for %s", len(unique), category_key)
        return unique

    async def fetch_all(
        self,
        categories: Optional[Sequence[str]] = None,
        *,
        force_refresh: bool = False,
    ) -> NewsBriefingResult:
        """Fetch news across multiple categories concurrently.

        Parameters
        ----------
        categories:
            List of category keys. Defaults to configured categories.
        force_refresh:
            Bypass cache.

        Returns
        -------
        NewsBriefingResult with aggregated articles.
        """
        cats = list(categories or self._config.categories)
        start_time = time.monotonic()

        result = NewsBriefingResult(categories_fetched=cats)

        tasks = [self.fetch_category(c, force_refresh=force_refresh) for c in cats]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for cat_key, outcome in zip(cats, outcomes):
            if isinstance(outcome, Exception):
                result.errors.append(f"{cat_key}: {outcome}")
                logger.warning("[news] category %s failed: %s", cat_key, outcome)
            else:
                result.articles.extend(outcome)

        result.fetch_time = time.monotonic() - start_time
        logger.info(
            "[news] briefing: %d articles from %d categories in %.2fs",
            result.count, len(cats), result.fetch_time,
        )
        return result

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> List[NewsArticle]:
        """Search across all cached news + live NewsAPI search.

        Parameters
        ----------
        query:
            Search query string.
        max_results:
            Maximum results to return.

        Returns
        -------
        Matching NewsArticles ranked by relevance.
        """
        query_lower = query.lower()
        results: List[NewsArticle] = []

        # Search cached articles first
        for cat_key in self._config.categories:
            cached = self._cache.get(cat_key)
            if cached:
                for article in cached:
                    if (query_lower in article.title.lower()
                            or query_lower in article.summary.lower()):
                        results.append(article)

        # If API key is available, do a live search too
        if self._config.api_key and len(results) < max_results:
            session = await self._get_session()
            # Create a pseudo-category for search
            search_cat = NewsCategoryDef(key="search", name="Search")
            api_results = await _fetch_newsapi(
                session,
                self._config.api_key,
                query,
                search_cat,
                max_items=max_results,
            )
            # Deduplicate against existing
            seen = {a.fingerprint for a in results}
            for article in api_results:
                if article.fingerprint not in seen:
                    results.append(article)
                    seen.add(article.fingerprint)

        return results[:max_results]

    async def get_latest(self, max_items: int = 5) -> List[NewsArticle]:
        """Get the latest news from all configured categories.

        Fetches all categories and returns a mixed list.
        """
        briefing = await self.fetch_all()
        return briefing.articles[:max_items]

    @property
    def cache_info(self) -> Dict[str, Any]:
        """Cache status for debugging."""
        return {
            "ttl": self._config.cache_ttl,
            "ages": self._cache.age,
            "categories": self._config.categories,
        }
