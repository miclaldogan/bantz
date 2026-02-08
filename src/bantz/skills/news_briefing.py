"""News briefing skill — provider, cache, formatter (Issue #294).

Provides news from RSS feeds with caching and voice-friendly output.

Categories::

    ai      — Yapay Zeka (TechCrunch, The Verge AI)
    tech    — Teknoloji (The Verge, Ars Technica)
    turkey  — Türkiye Gündemi (NTV, Hürriyet)

Config env vars::

    BANTZ_NEWS_CACHE_TTL=1800      # 30 minutes
    BANTZ_NEWS_MAX_ITEMS=3
    BANTZ_NEWS_CATEGORIES=ai,tech,turkey
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

__all__ = [
    "NewsItem",
    "NewsCategory",
    "NEWS_CATEGORIES",
    "NewsProviderBase",
    "RSSNewsProvider",
    "NewsCache",
    "format_news_for_voice",
    "NewsBriefingConfig",
]


# ── Data models ───────────────────────────────────────────────

@dataclass
class NewsItem:
    """A single news article."""

    title: str
    summary: str = ""
    source: str = ""
    url: str = ""
    published: str = ""
    category: str = ""

    @property
    def fingerprint(self) -> str:
        """Unique fingerprint for deduplication."""
        raw = f"{self.title}:{self.url}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class NewsCategory:
    """News category definition."""

    key: str
    name: str
    rss_feeds: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


# ── Default categories ────────────────────────────────────────

NEWS_CATEGORIES: Dict[str, NewsCategory] = {
    "ai": NewsCategory(
        key="ai",
        name="Yapay Zeka",
        rss_feeds=[
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        ],
        keywords=["AI", "GPT", "LLM", "machine learning", "yapay zeka"],
    ),
    "tech": NewsCategory(
        key="tech",
        name="Teknoloji",
        rss_feeds=[
            "https://www.theverge.com/rss/index.xml",
            "https://feeds.arstechnica.com/arstechnica/index",
        ],
        keywords=["technology", "software", "hardware", "teknoloji"],
    ),
    "turkey": NewsCategory(
        key="turkey",
        name="Türkiye Gündemi",
        rss_feeds=[
            "https://www.ntv.com.tr/son-dakika.rss",
            "https://www.hurriyet.com.tr/rss/gundem",
        ],
        keywords=["Türkiye", "gündem", "son dakika"],
    ),
}


# ── Config ────────────────────────────────────────────────────

@dataclass
class NewsBriefingConfig:
    """News briefing configuration."""

    cache_ttl: int = 1800  # 30 minutes
    max_items: int = 3
    categories: List[str] = field(default_factory=lambda: ["ai", "tech", "turkey"])
    timeout: float = 10.0  # HTTP request timeout

    @classmethod
    def from_env(cls) -> "NewsBriefingConfig":
        try:
            ttl = int(os.getenv("BANTZ_NEWS_CACHE_TTL", "1800"))
        except ValueError:
            ttl = 1800
        try:
            max_items = int(os.getenv("BANTZ_NEWS_MAX_ITEMS", "3"))
        except ValueError:
            max_items = 3
        raw_cats = os.getenv("BANTZ_NEWS_CATEGORIES", "ai,tech,turkey")
        cats = [c.strip() for c in raw_cats.split(",") if c.strip()]
        return cls(cache_ttl=ttl, max_items=max_items, categories=cats)


# ── Provider base ─────────────────────────────────────────────

class NewsProviderBase(ABC):
    """Abstract news provider."""

    @abstractmethod
    def fetch(self, category: NewsCategory) -> List[NewsItem]:
        """Fetch news items for a category."""
        ...


# ── RSS provider ──────────────────────────────────────────────

class RSSNewsProvider(NewsProviderBase):
    """Fetch news from RSS feeds."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def fetch(self, category: NewsCategory) -> List[NewsItem]:
        """Fetch and parse RSS feeds for a category."""
        items: List[NewsItem] = []

        for feed_url in category.rss_feeds:
            try:
                fetched = self._parse_feed(feed_url, category)
                items.extend(fetched)
                logger.debug("[news][rss] %d items from %s", len(fetched), feed_url)
            except Exception:
                logger.warning("[news][rss] failed to fetch %s", feed_url)

        # Deduplicate by fingerprint
        seen = set()
        unique = []
        for item in items:
            fp = item.fingerprint
            if fp not in seen:
                seen.add(fp)
                unique.append(item)

        return unique

    def _parse_feed(self, url: str, category: NewsCategory) -> List[NewsItem]:
        """Parse a single RSS feed URL."""
        req = Request(url, headers={"User-Agent": "Bantz/1.0 NewsBot"})
        with urlopen(req, timeout=self.timeout) as resp:
            data = resp.read()

        return self._parse_xml(data, category, source=url)

    @staticmethod
    def _parse_xml(data: bytes, category: NewsCategory, source: str = "") -> List[NewsItem]:
        """Parse RSS/Atom XML into NewsItem list."""
        items: List[NewsItem] = []

        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            logger.warning("[news][rss] XML parse error for %s", source)
            return []

        # RSS 2.0 — <channel><item>
        for item_el in root.iter("item"):
            title = (item_el.findtext("title") or "").strip()
            desc = (item_el.findtext("description") or "").strip()
            link = (item_el.findtext("link") or "").strip()
            pub = (item_el.findtext("pubDate") or "").strip()

            if title:
                # Truncate description for voice
                summary = desc[:200].split(".")[0] + "." if desc else ""
                items.append(NewsItem(
                    title=title,
                    summary=summary,
                    source=source,
                    url=link,
                    published=pub,
                    category=category.key,
                ))

        # Atom — <entry>
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("atom:title", namespaces=ns) or
                     entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
            summary_text = (summary_el.text or "") if summary_el is not None else ""
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""

            if title:
                summary = summary_text[:200].split(".")[0] + "." if summary_text else ""
                items.append(NewsItem(
                    title=title,
                    summary=summary,
                    source=source,
                    url=link,
                    category=category.key,
                ))

        return items


# ── Cache ─────────────────────────────────────────────────────

class NewsCache:
    """In-memory TTL cache for news items.

    Parameters
    ----------
    ttl_seconds:
        Time-to-live for cached items (default: 1800 = 30 min).
    clock:
        Injectable clock for testing.
    """

    def __init__(
        self,
        ttl_seconds: int = 1800,
        clock=None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._store: Dict[str, tuple[float, List[NewsItem]]] = {}

    def get(self, category: str) -> Optional[List[NewsItem]]:
        """Get cached items, or None if stale/missing."""
        entry = self._store.get(category)
        if entry is None:
            return None
        ts, items = entry
        if self._clock() - ts > self.ttl_seconds:
            return None
        return items

    def set(self, category: str, items: List[NewsItem]) -> None:
        """Store items with current timestamp."""
        self._store[category] = (self._clock(), items)

    def is_stale(self, category: str) -> bool:
        """Check if category cache is stale or missing."""
        return self.get(category) is None

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()


# ── Voice formatter ───────────────────────────────────────────

_ORDINALS = ["Birincisi", "İkincisi", "Üçüncüsü", "Dördüncüsü", "Beşincisi"]


def format_news_for_voice(
    items: List[NewsItem],
    max_items: int = 3,
    category_name: str = "",
) -> str:
    """Format news items for voice output.

    Returns Turkish voice-friendly text with numbered items.
    """
    if not items:
        if category_name:
            return f"{category_name} kategorisinde şu an güncel haber bulunamadı efendim."
        return "Şu an güncel haber bulunamadı efendim."

    display = items[:max_items]
    cat_intro = f"{category_name} dünyasında" if category_name else "Güncel haberlerde"

    lines = [f"{cat_intro} birkaç gelişme var efendim:"]
    for i, item in enumerate(display):
        ordinal = _ORDINALS[i] if i < len(_ORDINALS) else f"{i+1}."
        line = f"{ordinal}, {item.title}."
        if item.summary:
            line += f" {item.summary}"
        lines.append(line)

    lines.append("Detayları ister misiniz?")
    return "\n".join(lines)
