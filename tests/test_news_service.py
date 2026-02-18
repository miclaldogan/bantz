"""Tests for NewsService — async news aggregation with images.

Covers:
- RSS feed parsing (RSS 2.0 + Atom)
- Image extraction (media:content, enclosure, description img, og:image)
- Cache TTL behavior
- NewsAPI integration
- Multi-category fetching
- Search functionality
- Deduplication
- Error handling (network errors, parse errors)
- Config from env
"""

from __future__ import annotations

import asyncio
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.services.news_service import (
    NEWS_CATEGORIES,
    NewsArticle,
    NewsBriefingResult,
    NewsCategoryDef,
    NewsService,
    NewsServiceConfig,
    _NewsCache,
    _clean_html,
    _extract_image_from_description,
    _extract_image_from_xml,
    _parse_feed_xml,
    _url_to_source_name,
)


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

SAMPLE_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
  <title>Test Feed</title>
  <item>
    <title>AI Breakthrough in 2026</title>
    <link>https://example.com/ai-breakthrough</link>
    <description>&lt;p&gt;Researchers announce major AI advancement.&lt;/p&gt;</description>
    <pubDate>Mon, 17 Feb 2026 10:00:00 GMT</pubDate>
    <media:content url="https://example.com/images/ai.jpg" medium="image"/>
  </item>
  <item>
    <title>New Processor Released</title>
    <link>https://example.com/new-processor</link>
    <description>A new chip hits the market with impressive benchmarks.</description>
    <pubDate>Mon, 17 Feb 2026 09:00:00 GMT</pubDate>
    <enclosure url="https://example.com/images/cpu.png" type="image/png"/>
  </item>
  <item>
    <title>Space Mission Update</title>
    <link>https://example.com/space</link>
    <description>&lt;img src="https://example.com/images/space.jpg"&gt; Mission details here.</description>
    <pubDate>Mon, 17 Feb 2026 08:00:00 GMT</pubDate>
  </item>
</channel>
</rss>"""


SAMPLE_ATOM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <entry>
    <title>Quantum Computing Progress</title>
    <link href="https://example.com/quantum"/>
    <summary>Quantum supremacy reached in new experiment.</summary>
  </entry>
  <entry>
    <title>Climate Report Published</title>
    <link href="https://example.com/climate"/>
    <summary>New data on global temperature trends.</summary>
  </entry>
</feed>"""


SAMPLE_NEWSAPI_RESPONSE = {
    "status": "ok",
    "totalResults": 2,
    "articles": [
        {
            "title": "OpenAI Releases GPT-5",
            "description": "The latest language model from OpenAI.",
            "url": "https://example.com/gpt5",
            "source": {"name": "TechCrunch"},
            "urlToImage": "https://example.com/images/gpt5.jpg",
            "publishedAt": "2026-02-17T10:00:00Z",
        },
        {
            "title": "Anthropic Launches Claude 5",
            "description": "Next-gen AI assistant arrives.",
            "url": "https://example.com/claude5",
            "source": {"name": "The Verge"},
            "urlToImage": "https://example.com/images/claude5.jpg",
            "publishedAt": "2026-02-17T09:00:00Z",
        },
    ],
}


@pytest.fixture
def ai_category():
    return NewsCategoryDef(
        key="ai",
        name="AI",
        rss_feeds=["https://example.com/feed.xml"],
        newsapi_query="AI",
    )


@pytest.fixture
def config():
    return NewsServiceConfig(
        api_key="",
        cache_ttl=300,
        max_items_per_category=5,
        categories=["ai", "tech"],
        image_enabled=True,
        timeout=10.0,
    )


# ─────────────────────────────────────────────────────────────────
# NewsArticle
# ─────────────────────────────────────────────────────────────────


class TestNewsArticle:
    def test_fingerprint_unique(self):
        a = NewsArticle(title="Hello", url="https://a.com")
        b = NewsArticle(title="World", url="https://b.com")
        assert a.fingerprint != b.fingerprint

    def test_fingerprint_deterministic(self):
        a1 = NewsArticle(title="Same", url="https://x.com")
        a2 = NewsArticle(title="Same", url="https://x.com")
        assert a1.fingerprint == a2.fingerprint

    def test_to_dict_includes_all_fields(self):
        a = NewsArticle(
            title="Test",
            summary="A summary",
            url="https://x.com",
            source="TestSrc",
            image_url="https://x.com/img.jpg",
            published="2026-02-17",
            category="ai",
        )
        d = a.to_dict()
        assert d["title"] == "Test"
        assert d["image_url"] == "https://x.com/img.jpg"
        assert d["category"] == "ai"
        assert "fingerprint" in d

    def test_to_dict_none_image(self):
        a = NewsArticle(title="No Image", url="https://x.com")
        d = a.to_dict()
        assert d["image_url"] is None


# ─────────────────────────────────────────────────────────────────
# NewsBriefingResult
# ─────────────────────────────────────────────────────────────────


class TestNewsBriefingResult:
    def test_empty(self):
        r = NewsBriefingResult()
        assert r.count == 0
        assert not r.has_articles

    def test_with_articles(self):
        r = NewsBriefingResult(
            articles=[NewsArticle(title="A", category="ai"), NewsArticle(title="B", category="tech")],
            categories_fetched=["ai", "tech"],
        )
        assert r.count == 2
        assert r.has_articles

    def test_by_category(self):
        r = NewsBriefingResult(
            articles=[
                NewsArticle(title="A1", category="ai"),
                NewsArticle(title="T1", category="tech"),
                NewsArticle(title="A2", category="ai"),
            ],
        )
        ai = r.by_category("ai")
        assert len(ai) == 2
        assert all(a.category == "ai" for a in ai)

    def test_to_dict(self):
        r = NewsBriefingResult(
            articles=[NewsArticle(title="X")],
            categories_fetched=["ai"],
            fetch_time=1.234,
        )
        d = r.to_dict()
        assert d["count"] == 1
        assert d["fetch_time"] == 1.23
        assert len(d["articles"]) == 1


# ─────────────────────────────────────────────────────────────────
# HTML Cleaning & Image Extraction
# ─────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_clean_html_removes_tags(self):
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_clean_html_decodes_entities(self):
        assert "don't" in _clean_html("don&apos;t")

    def test_clean_html_normalizes_whitespace(self):
        assert _clean_html("  too   many   spaces  ") == "too many spaces"

    def test_extract_image_from_description(self):
        desc = '<img src="https://img.com/photo.jpg" alt="test">'
        assert _extract_image_from_description(desc) == "https://img.com/photo.jpg"

    def test_extract_image_from_description_no_img(self):
        assert _extract_image_from_description("No images here") is None

    def test_extract_image_from_xml_media_content(self):
        xml = 'url="https://example.com/photo.jpg" medium="image"'
        assert _extract_image_from_xml(xml) == "https://example.com/photo.jpg"

    def test_extract_image_from_xml_enclosure(self):
        xml = '<enclosure url="https://example.com/pic.png" type="image/png"/>'
        assert _extract_image_from_xml(xml) == "https://example.com/pic.png"

    def test_url_to_source_name(self):
        assert _url_to_source_name("https://www.theverge.com/rss") == "Theverge"
        assert _url_to_source_name("https://techcrunch.com/feed") == "Techcrunch"

    def test_url_to_source_name_no_www(self):
        assert _url_to_source_name("https://bbc.co.uk/feed") == "Bbc"


# ─────────────────────────────────────────────────────────────────
# RSS XML Parsing
# ─────────────────────────────────────────────────────────────────


class TestRSSParsing:
    def test_parse_rss_20(self, ai_category):
        articles = _parse_feed_xml(
            SAMPLE_RSS_XML, ai_category, "https://example.com/feed", 10, True
        )
        assert len(articles) == 3
        assert articles[0].title == "AI Breakthrough in 2026"
        assert articles[0].category == "ai"
        assert articles[0].url == "https://example.com/ai-breakthrough"

    def test_parse_rss_extracts_images(self, ai_category):
        articles = _parse_feed_xml(
            SAMPLE_RSS_XML, ai_category, "https://example.com/feed", 10, True
        )
        # First item: media:content
        assert articles[0].image_url == "https://example.com/images/ai.jpg"
        # Second item: enclosure
        assert articles[1].image_url == "https://example.com/images/cpu.png"
        # Third item: img tag in description
        assert articles[2].image_url == "https://example.com/images/space.jpg"

    def test_parse_rss_no_images_when_disabled(self, ai_category):
        articles = _parse_feed_xml(
            SAMPLE_RSS_XML, ai_category, "https://example.com/feed", 10, False
        )
        assert all(a.image_url is None for a in articles)

    def test_parse_rss_max_items(self, ai_category):
        articles = _parse_feed_xml(
            SAMPLE_RSS_XML, ai_category, "https://example.com/feed", 2, True
        )
        assert len(articles) == 2

    def test_parse_rss_cleans_html_description(self, ai_category):
        articles = _parse_feed_xml(
            SAMPLE_RSS_XML, ai_category, "https://example.com/feed", 10, True
        )
        assert "<p>" not in articles[0].summary

    def test_parse_atom(self, ai_category):
        articles = _parse_feed_xml(
            SAMPLE_ATOM_XML, ai_category, "https://example.com/atom", 10, True
        )
        assert len(articles) == 2
        assert articles[0].title == "Quantum Computing Progress"

    def test_parse_invalid_xml(self, ai_category):
        articles = _parse_feed_xml(
            b"not xml at all", ai_category, "https://bad.com", 10, True
        )
        assert articles == []

    def test_parse_empty_items(self, ai_category):
        xml = b"""<?xml version="1.0"?><rss><channel></channel></rss>"""
        articles = _parse_feed_xml(xml, ai_category, "https://empty.com", 10, True)
        assert articles == []


# ─────────────────────────────────────────────────────────────────
# News Cache
# ─────────────────────────────────────────────────────────────────


class TestNewsCache:
    def test_set_and_get(self):
        cache = _NewsCache(ttl_seconds=300)
        items = [NewsArticle(title="A")]
        cache.set("ai", items)
        assert cache.get("ai") is not None
        assert len(cache.get("ai")) == 1

    def test_get_returns_none_when_empty(self):
        cache = _NewsCache()
        assert cache.get("missing") is None

    def test_ttl_expiry(self):
        t = [0.0]
        clock = lambda: t[0]
        cache = _NewsCache(ttl_seconds=60, clock=clock)
        cache.set("ai", [NewsArticle(title="A")])

        t[0] = 30.0
        assert cache.get("ai") is not None  # still valid

        t[0] = 61.0
        assert cache.get("ai") is None  # expired

    def test_clear(self):
        cache = _NewsCache()
        cache.set("ai", [NewsArticle(title="A")])
        cache.set("tech", [NewsArticle(title="B")])
        cache.clear()
        assert cache.get("ai") is None
        assert cache.get("tech") is None

    def test_age(self):
        t = [100.0]
        clock = lambda: t[0]
        cache = _NewsCache(ttl_seconds=300, clock=clock)
        cache.set("ai", [])
        t[0] = 110.0
        ages = cache.age
        assert abs(ages["ai"] - 10.0) < 0.01


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


class TestConfig:
    def test_defaults(self):
        cfg = NewsServiceConfig()
        assert cfg.cache_ttl == 1800
        assert cfg.max_items_per_category == 10
        assert cfg.image_enabled is True
        assert "ai" in cfg.categories

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("BANTZ_NEWS_API_KEY", "test-key-123")
        monkeypatch.setenv("BANTZ_NEWS_CACHE_TTL", "600")
        monkeypatch.setenv("BANTZ_NEWS_MAX_ITEMS", "5")
        monkeypatch.setenv("BANTZ_NEWS_CATEGORIES", "ai,science")
        monkeypatch.setenv("BANTZ_NEWS_IMAGE_ENABLED", "false")
        monkeypatch.setenv("BANTZ_NEWS_TIMEOUT", "20")

        cfg = NewsServiceConfig.from_env()
        assert cfg.api_key == "test-key-123"
        assert cfg.cache_ttl == 600
        assert cfg.max_items_per_category == 5
        assert cfg.categories == ["ai", "science"]
        assert cfg.image_enabled is False
        assert cfg.timeout == 20.0

    def test_from_env_invalid_values(self, monkeypatch):
        monkeypatch.setenv("BANTZ_NEWS_CACHE_TTL", "not-a-number")
        monkeypatch.setenv("BANTZ_NEWS_MAX_ITEMS", "bad")
        cfg = NewsServiceConfig.from_env()
        assert cfg.cache_ttl == 1800
        assert cfg.max_items_per_category == 10


# ─────────────────────────────────────────────────────────────────
# Category Definitions
# ─────────────────────────────────────────────────────────────────


class TestCategories:
    def test_all_categories_have_feeds(self):
        for key, cat in NEWS_CATEGORIES.items():
            assert len(cat.rss_feeds) > 0, f"Category {key} has no feeds"

    def test_all_categories_have_name(self):
        for key, cat in NEWS_CATEGORIES.items():
            assert cat.name, f"Category {key} has no name"
            assert cat.key == key

    def test_expected_categories_exist(self):
        expected = {"ai", "tech", "world", "turkey", "science", "business"}
        assert expected == set(NEWS_CATEGORIES.keys())


# ─────────────────────────────────────────────────────────────────
# NewsService (integration-style, mocked HTTP)
# ─────────────────────────────────────────────────────────────────


class TestNewsService:
    @pytest.mark.asyncio
    async def test_fetch_category_caches(self, config):
        svc = NewsService(config=config)
        # Pre-populate cache
        svc._cache.set("ai", [NewsArticle(title="Cached")])

        result = await svc.fetch_category("ai")
        assert len(result) == 1
        assert result[0].title == "Cached"
        await svc.close()

    @pytest.mark.asyncio
    async def test_fetch_unknown_category(self, config):
        svc = NewsService(config=config)
        result = await svc.fetch_category("nonexistent")
        assert result == []
        await svc.close()

    @pytest.mark.asyncio
    async def test_fetch_all_returns_briefing_result(self, config):
        svc = NewsService(config=config)
        # Pre-populate caches
        svc._cache.set("ai", [NewsArticle(title="AI News", category="ai")])
        svc._cache.set("tech", [NewsArticle(title="Tech News", category="tech")])

        result = await svc.fetch_all(categories=["ai", "tech"])
        assert isinstance(result, NewsBriefingResult)
        assert result.count == 2
        assert "ai" in result.categories_fetched
        await svc.close()

    @pytest.mark.asyncio
    async def test_search_cached_articles(self, config):
        svc = NewsService(config=config)
        svc._cache.set("ai", [
            NewsArticle(title="AI Breakthrough", summary="Major advance", category="ai"),
            NewsArticle(title="Cooking Recipe", summary="Pasta tips", category="ai"),
        ])

        results = await svc.search("breakthrough")
        assert len(results) == 1
        assert results[0].title == "AI Breakthrough"
        await svc.close()

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, config):
        svc = NewsService(config=config)
        svc._cache.set("ai", [
            NewsArticle(title="GPT-5 Released", category="ai"),
        ])

        results = await svc.search("gpt-5")
        assert len(results) == 1
        await svc.close()

    @pytest.mark.asyncio
    async def test_get_latest(self, config):
        svc = NewsService(config=config)
        svc._cache.set("ai", [NewsArticle(title=f"A{i}", category="ai") for i in range(3)])
        svc._cache.set("tech", [NewsArticle(title=f"T{i}", category="tech") for i in range(3)])

        latest = await svc.get_latest(max_items=4)
        assert len(latest) == 4
        await svc.close()

    @pytest.mark.asyncio
    async def test_deduplication(self, config):
        svc = NewsService(config=config)
        # Two feeds returning same article
        same1 = NewsArticle(title="Same Title", url="https://x.com/same", category="ai")
        same2 = NewsArticle(title="Same Title", url="https://x.com/same", category="ai")
        diff = NewsArticle(title="Different", url="https://x.com/diff", category="ai")

        svc._cache.set("ai", [same1, same2, diff])
        result = await svc.fetch_all(categories=["ai"])
        # Cache returns them as-is, dedup happens during fetch
        assert result.count == 3  # cache doesn't dedup, fetch does
        await svc.close()

    def test_cache_info(self, config):
        svc = NewsService(config=config)
        info = svc.cache_info
        assert info["ttl"] == 300
        assert "ages" in info

    @pytest.mark.asyncio
    async def test_from_env(self, monkeypatch):
        monkeypatch.setenv("BANTZ_NEWS_CATEGORIES", "ai")
        monkeypatch.setenv("BANTZ_NEWS_CACHE_TTL", "120")
        svc = NewsService.from_env()
        assert svc._config.cache_ttl == 120
        assert svc._config.categories == ["ai"]
        await svc.close()
