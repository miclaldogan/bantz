"""Tests for Issue #294 — News briefing skill.

Covers data models, RSS parsing, cache TTL, voice formatting,
config, provider base, and edge cases.
"""

from __future__ import annotations

import os
import textwrap
from unittest import mock

import pytest


# ── NewsItem ──────────────────────────────────────────────────

class TestNewsItem:
    def test_fields(self):
        from bantz.skills.news_briefing import NewsItem
        item = NewsItem(title="Test", summary="Sum", source="rss", url="http://x")
        assert item.title == "Test"
        assert item.summary == "Sum"

    def test_fingerprint_deterministic(self):
        from bantz.skills.news_briefing import NewsItem
        a = NewsItem(title="AI News", url="http://example.com/1")
        b = NewsItem(title="AI News", url="http://example.com/1")
        assert a.fingerprint == b.fingerprint

    def test_fingerprint_differs(self):
        from bantz.skills.news_briefing import NewsItem
        a = NewsItem(title="AI News", url="http://example.com/1")
        b = NewsItem(title="Tech News", url="http://example.com/2")
        assert a.fingerprint != b.fingerprint


# ── NewsCategory ──────────────────────────────────────────────

class TestNewsCategory:
    def test_defaults(self):
        from bantz.skills.news_briefing import NewsCategory
        c = NewsCategory(key="test", name="Test")
        assert c.rss_feeds == []
        assert c.keywords == []

    def test_builtin_categories(self):
        from bantz.skills.news_briefing import NEWS_CATEGORIES
        assert "ai" in NEWS_CATEGORIES
        assert "tech" in NEWS_CATEGORIES
        assert "turkey" in NEWS_CATEGORIES
        assert NEWS_CATEGORIES["ai"].name == "Yapay Zeka"


# ── Config ────────────────────────────────────────────────────

class TestNewsBriefingConfig:
    def test_defaults(self):
        from bantz.skills.news_briefing import NewsBriefingConfig
        c = NewsBriefingConfig()
        assert c.cache_ttl == 1800
        assert c.max_items == 3
        assert c.categories == ["ai", "tech", "turkey"]

    def test_from_env(self):
        from bantz.skills.news_briefing import NewsBriefingConfig
        env = {
            "BANTZ_NEWS_CACHE_TTL": "3600",
            "BANTZ_NEWS_MAX_ITEMS": "5",
            "BANTZ_NEWS_CATEGORIES": "ai,turkey",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            c = NewsBriefingConfig.from_env()
        assert c.cache_ttl == 3600
        assert c.max_items == 5
        assert c.categories == ["ai", "turkey"]

    def test_from_env_invalid(self):
        from bantz.skills.news_briefing import NewsBriefingConfig
        env = {"BANTZ_NEWS_CACHE_TTL": "abc", "BANTZ_NEWS_MAX_ITEMS": "xyz"}
        with mock.patch.dict(os.environ, env, clear=True):
            c = NewsBriefingConfig.from_env()
        assert c.cache_ttl == 1800
        assert c.max_items == 3


# ── NewsProviderBase ──────────────────────────────────────────

class TestProviderBase:
    def test_abstract(self):
        from bantz.skills.news_briefing import NewsProviderBase
        with pytest.raises(TypeError):
            NewsProviderBase()


# ── RSS parsing (offline XML) ─────────────────────────────────

RSS_SAMPLE = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>AI Model Released</title>
      <description>A new AI model was released today. It performs well.</description>
      <link>http://example.com/1</link>
      <pubDate>Mon, 01 Jan 2025 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Tech Update</title>
      <description>Latest tech news summary. More details inside.</description>
      <link>http://example.com/2</link>
    </item>
  </channel>
</rss>
""")

ATOM_SAMPLE = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom Article</title>
    <summary>Atom summary text. More info here.</summary>
    <link href="http://example.com/atom/1"/>
  </entry>
</feed>
""")


class TestRSSParsing:
    def test_parse_rss(self):
        from bantz.skills.news_briefing import RSSNewsProvider, NewsCategory
        prov = RSSNewsProvider()
        cat = NewsCategory(key="test", name="Test")
        items = prov._parse_xml(RSS_SAMPLE.encode(), cat, source="test")
        assert len(items) == 2
        assert items[0].title == "AI Model Released"
        assert items[0].category == "test"
        assert "http://example.com/1" in items[0].url

    def test_parse_atom(self):
        from bantz.skills.news_briefing import RSSNewsProvider, NewsCategory
        prov = RSSNewsProvider()
        cat = NewsCategory(key="atom", name="Atom")
        items = prov._parse_xml(ATOM_SAMPLE.encode(), cat, source="test")
        assert len(items) == 1
        assert items[0].title == "Atom Article"

    def test_parse_invalid_xml(self):
        from bantz.skills.news_briefing import RSSNewsProvider, NewsCategory
        prov = RSSNewsProvider()
        cat = NewsCategory(key="bad", name="Bad")
        items = prov._parse_xml(b"not xml at all", cat, source="test")
        assert items == []

    def test_deduplication(self):
        from bantz.skills.news_briefing import RSSNewsProvider, NewsCategory
        # Same item twice in one feed
        double_rss = RSS_SAMPLE.replace("</channel>",
            "<item><title>AI Model Released</title><link>http://example.com/1</link></item></channel>")
        prov = RSSNewsProvider()
        cat = NewsCategory(key="test", name="Test", rss_feeds=[])
        items_raw = prov._parse_xml(double_rss.encode(), cat, source="test")
        # Manual dedup via fetch logic
        seen = set()
        unique = []
        for i in items_raw:
            if i.fingerprint not in seen:
                seen.add(i.fingerprint)
                unique.append(i)
        assert len(unique) == 2  # AI Model + Tech Update


# ── Cache ─────────────────────────────────────────────────────

class TestNewsCache:
    def test_empty_cache(self):
        from bantz.skills.news_briefing import NewsCache
        cache = NewsCache(ttl_seconds=60)
        assert cache.get("ai") is None
        assert cache.is_stale("ai") is True

    def test_set_and_get(self):
        from bantz.skills.news_briefing import NewsCache, NewsItem
        cache = NewsCache(ttl_seconds=60)
        items = [NewsItem(title="Test")]
        cache.set("ai", items)
        assert cache.get("ai") == items
        assert not cache.is_stale("ai")

    def test_ttl_expiry(self):
        from bantz.skills.news_briefing import NewsCache, NewsItem
        t = [0.0]
        cache = NewsCache(ttl_seconds=60, clock=lambda: t[0])
        cache.set("ai", [NewsItem(title="Test")])
        assert cache.get("ai") is not None

        t[0] = 61.0
        assert cache.get("ai") is None
        assert cache.is_stale("ai") is True

    def test_clear(self):
        from bantz.skills.news_briefing import NewsCache, NewsItem
        cache = NewsCache()
        cache.set("ai", [NewsItem(title="A")])
        cache.set("tech", [NewsItem(title="B")])
        cache.clear()
        assert cache.get("ai") is None
        assert cache.get("tech") is None


# ── Voice formatter ───────────────────────────────────────────

class TestFormatNewsForVoice:
    def test_empty_items(self):
        from bantz.skills.news_briefing import format_news_for_voice
        text = format_news_for_voice([])
        assert "bulunamadı" in text

    def test_empty_with_category(self):
        from bantz.skills.news_briefing import format_news_for_voice
        text = format_news_for_voice([], category_name="Yapay Zeka")
        assert "Yapay Zeka" in text
        assert "bulunamadı" in text

    def test_three_items(self):
        from bantz.skills.news_briefing import format_news_for_voice, NewsItem
        items = [
            NewsItem(title="AI Model Released", summary="New model is fast."),
            NewsItem(title="Tech Update", summary="Big tech news."),
            NewsItem(title="Turkey News", summary="Local developments."),
        ]
        text = format_news_for_voice(items, max_items=3, category_name="Yapay Zeka")
        assert "Birincisi" in text
        assert "İkincisi" in text
        assert "Üçüncüsü" in text
        assert "AI Model Released" in text
        assert "Detayları ister misiniz?" in text

    def test_max_items_limit(self):
        from bantz.skills.news_briefing import format_news_for_voice, NewsItem
        items = [NewsItem(title=f"Item {i}") for i in range(10)]
        text = format_news_for_voice(items, max_items=2)
        assert "Birincisi" in text
        assert "İkincisi" in text
        assert "Üçüncüsü" not in text

    def test_efendim_in_output(self):
        from bantz.skills.news_briefing import format_news_for_voice, NewsItem
        items = [NewsItem(title="Test")]
        text = format_news_for_voice(items)
        assert "efendim" in text


# ── File existence ────────────────────────────────────────────

class TestFileExistence:
    def test_news_briefing_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "skills" / "news_briefing.py").is_file()
