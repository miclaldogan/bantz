"""
Tests for Page Summarizer Improvements (Issue #61).

Tests:
- Caching System
- Progress Callbacks
- Summary History
- Summary Length Options
- Rate Limiting
- Error Recovery
- Helper Functions
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple
from unittest.mock import MagicMock, AsyncMock, patch

from bantz.skills.summarizer import (
    # Enums
    SummaryLength,
    ProgressStage,
    # Data Classes
    PageSummary,
    ExtractedPage,
    CacheEntry,
    # Core Classes
    SummaryCache,
    SummaryHistory,
    RateLimiter,
    PageSummarizer,
    MockPageSummarizer,
    # Helper Functions
    extract_question,
    parse_summary_length,
)


# =============================================================================
# SummaryLength Tests
# =============================================================================


class TestSummaryLength:
    """Tests for SummaryLength enum."""
    
    def test_from_str_english(self):
        """Test parsing English length names."""
        assert SummaryLength.from_str("tweet") == SummaryLength.TWEET
        assert SummaryLength.from_str("paragraph") == SummaryLength.PARAGRAPH
        assert SummaryLength.from_str("full") == SummaryLength.FULL
    
    def test_from_str_turkish(self):
        """Test parsing Turkish length names."""
        assert SummaryLength.from_str("kısa") == SummaryLength.TWEET
        assert SummaryLength.from_str("kisa") == SummaryLength.TWEET
        assert SummaryLength.from_str("orta") == SummaryLength.PARAGRAPH
        assert SummaryLength.from_str("paragraf") == SummaryLength.PARAGRAPH
        assert SummaryLength.from_str("uzun") == SummaryLength.FULL
        assert SummaryLength.from_str("detaylı") == SummaryLength.FULL
        assert SummaryLength.from_str("detayli") == SummaryLength.FULL
        assert SummaryLength.from_str("tam") == SummaryLength.FULL
    
    def test_from_str_case_insensitive(self):
        """Test case insensitivity."""
        assert SummaryLength.from_str("TWEET") == SummaryLength.TWEET
        assert SummaryLength.from_str("Tweet") == SummaryLength.TWEET
        assert SummaryLength.from_str("KISA") == SummaryLength.TWEET
    
    def test_from_str_unknown_defaults_paragraph(self):
        """Test unknown values default to PARAGRAPH."""
        assert SummaryLength.from_str("unknown") == SummaryLength.PARAGRAPH
        assert SummaryLength.from_str("xyz") == SummaryLength.PARAGRAPH
        assert SummaryLength.from_str("") == SummaryLength.PARAGRAPH


# =============================================================================
# ProgressStage Tests
# =============================================================================


class TestProgressStage:
    """Tests for ProgressStage enum."""
    
    def test_progress_stages_exist(self):
        """Test all progress stages are defined."""
        assert ProgressStage.STARTED
        assert ProgressStage.EXTRACTING
        assert ProgressStage.EXTRACTED
        assert ProgressStage.SUMMARIZING
        assert ProgressStage.COMPLETED
        assert ProgressStage.CACHED
        assert ProgressStage.FAILED
    
    def test_progress_stage_values(self):
        """Test progress stage values."""
        assert ProgressStage.STARTED.value == "started"
        assert ProgressStage.EXTRACTING.value == "extracting"
        assert ProgressStage.COMPLETED.value == "completed"
        assert ProgressStage.CACHED.value == "cached"


# =============================================================================
# PageSummary Tests
# =============================================================================


class TestPageSummary:
    """Tests for PageSummary dataclass."""
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        summary = PageSummary(
            title="Test",
            url="https://example.com",
            short_summary="Short",
            detailed_summary="Detailed",
            key_points=["Point 1", "Point 2"],
        )
        
        d = summary.to_dict()
        
        assert d["title"] == "Test"
        assert d["url"] == "https://example.com"
        assert d["short_summary"] == "Short"
        assert d["detailed_summary"] == "Detailed"
        assert d["key_points"] == ["Point 1", "Point 2"]
        assert "generated_at" in d
        assert d["length_type"] == "paragraph"
        assert d["from_cache"] is False
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "title": "Test",
            "url": "https://example.com",
            "short_summary": "Short",
            "detailed_summary": "Detailed",
            "key_points": ["Point 1"],
            "generated_at": "2024-01-15T10:30:00",
            "length_type": "tweet",
            "from_cache": True,
        }
        
        summary = PageSummary.from_dict(data)
        
        assert summary.title == "Test"
        assert summary.url == "https://example.com"
        assert summary.short_summary == "Short"
        assert summary.length_type == SummaryLength.TWEET
        assert summary.from_cache is True
    
    def test_defaults(self):
        """Test default values."""
        summary = PageSummary(
            title="Test",
            url="https://example.com",
            short_summary="Short",
            detailed_summary="",
            key_points=[],
        )
        
        assert summary.source_content == ""
        assert summary.length_type == SummaryLength.PARAGRAPH
        assert summary.from_cache is False
        assert isinstance(summary.generated_at, datetime)


# =============================================================================
# CacheEntry Tests
# =============================================================================


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""
    
    def test_is_expired_not_expired(self):
        """Test non-expired entry."""
        summary = PageSummary(
            title="Test", url="https://example.com",
            short_summary="Short", detailed_summary="", key_points=[]
        )
        entry = CacheEntry(
            url_hash="abc123",
            summary=summary,
            created_at=datetime.now(),
        )
        
        assert entry.is_expired(ttl_seconds=3600) is False
    
    def test_is_expired_expired(self):
        """Test expired entry."""
        summary = PageSummary(
            title="Test", url="https://example.com",
            short_summary="Short", detailed_summary="", key_points=[]
        )
        entry = CacheEntry(
            url_hash="abc123",
            summary=summary,
            created_at=datetime.now() - timedelta(hours=2),
        )
        
        assert entry.is_expired(ttl_seconds=3600) is True
    
    def test_touch_updates_access(self):
        """Test touch updates access count and time."""
        summary = PageSummary(
            title="Test", url="https://example.com",
            short_summary="Short", detailed_summary="", key_points=[]
        )
        entry = CacheEntry(
            url_hash="abc123",
            summary=summary,
            created_at=datetime.now(),
        )
        
        assert entry.access_count == 0
        
        entry.touch()
        assert entry.access_count == 1
        
        entry.touch()
        assert entry.access_count == 2


# =============================================================================
# SummaryCache Tests
# =============================================================================


class TestSummaryCache:
    """Tests for SummaryCache class."""
    
    @pytest.fixture
    def cache(self):
        """Create a test cache."""
        return SummaryCache(max_size=5, ttl_seconds=3600)
    
    @pytest.fixture
    def sample_summary(self):
        """Create a sample summary."""
        return PageSummary(
            title="Test Page",
            url="https://example.com/test",
            short_summary="This is a test summary",
            detailed_summary="",
            key_points=[],
        )
    
    @pytest.mark.asyncio
    async def test_set_and_get(self, cache, sample_summary):
        """Test setting and getting from cache."""
        url = "https://example.com/test"
        
        await cache.set(url, sample_summary)
        result = await cache.get(url)
        
        assert result is not None
        assert result.title == sample_summary.title
        assert result.from_cache is True
    
    @pytest.mark.asyncio
    async def test_get_missing(self, cache):
        """Test getting missing entry."""
        result = await cache.get("https://nonexistent.com")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_expired_entry_removed(self):
        """Test expired entries are removed."""
        cache = SummaryCache(max_size=5, ttl_seconds=1)
        summary = PageSummary(
            title="Test", url="https://example.com",
            short_summary="Short", detailed_summary="", key_points=[]
        )
        
        await cache.set("https://example.com", summary)
        
        # Should exist immediately
        result = await cache.get("https://example.com")
        assert result is not None
        
        # Wait for expiration
        await asyncio.sleep(1.5)
        
        # Should be expired
        result = await cache.get("https://example.com")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_eviction_when_full(self):
        """Test LRU eviction when cache is full."""
        cache = SummaryCache(max_size=3, ttl_seconds=3600)
        
        for i in range(4):
            summary = PageSummary(
                title=f"Page {i}",
                url=f"https://example.com/{i}",
                short_summary=f"Summary {i}",
                detailed_summary="",
                key_points=[],
            )
            await cache.set(f"https://example.com/{i}", summary)
        
        # Oldest should be evicted
        stats = cache.stats()
        assert stats["size"] == 3
    
    @pytest.mark.asyncio
    async def test_clear(self, cache, sample_summary):
        """Test clearing cache."""
        await cache.set("https://example.com/1", sample_summary)
        await cache.set("https://example.com/2", sample_summary)
        
        assert cache.stats()["size"] == 2
        
        await cache.clear()
        
        assert cache.stats()["size"] == 0
    
    def test_stats(self, cache):
        """Test cache statistics."""
        stats = cache.stats()
        
        assert "size" in stats
        assert "max_size" in stats
        assert "ttl_seconds" in stats
        assert "entries" in stats
        assert stats["max_size"] == 5
        assert stats["ttl_seconds"] == 3600


# =============================================================================
# SummaryHistory Tests
# =============================================================================


class TestSummaryHistory:
    """Tests for SummaryHistory class."""
    
    @pytest.fixture
    def history(self):
        """Create a test history."""
        return SummaryHistory(max_size=5)
    
    @pytest.fixture
    def sample_summaries(self):
        """Create sample summaries."""
        return [
            PageSummary(
                title=f"Page {i}",
                url=f"https://example.com/{i}",
                short_summary=f"Summary {i}",
                detailed_summary="",
                key_points=[],
            )
            for i in range(7)
        ]
    
    def test_add_and_get_recent(self, history, sample_summaries):
        """Test adding and getting recent summaries."""
        history.add(sample_summaries[0])
        history.add(sample_summaries[1])
        
        recent = history.get_recent(2)
        
        assert len(recent) == 2
        # Most recent first
        assert recent[0].title == "Page 1"
        assert recent[1].title == "Page 0"
    
    def test_max_size_enforced(self, history, sample_summaries):
        """Test max size is enforced."""
        for summary in sample_summaries:
            history.add(summary)
        
        assert history.count == 5
        
        recent = history.get_recent(10)
        assert len(recent) == 5
    
    def test_duplicate_url_replaced(self, history):
        """Test duplicate URLs replace old entry."""
        summary1 = PageSummary(
            title="Old",
            url="https://example.com/test",
            short_summary="Old summary",
            detailed_summary="",
            key_points=[],
        )
        summary2 = PageSummary(
            title="New",
            url="https://example.com/test",
            short_summary="New summary",
            detailed_summary="",
            key_points=[],
        )
        
        history.add(summary1)
        history.add(summary2)
        
        assert history.count == 1
        assert history.get_by_url("https://example.com/test").title == "New"
    
    def test_get_by_url(self, history, sample_summaries):
        """Test getting by URL."""
        history.add(sample_summaries[0])
        history.add(sample_summaries[1])
        
        result = history.get_by_url("https://example.com/0")
        assert result is not None
        assert result.title == "Page 0"
        
        result = history.get_by_url("https://nonexistent.com")
        assert result is None
    
    def test_get_by_index(self, history, sample_summaries):
        """Test getting by index."""
        history.add(sample_summaries[0])
        history.add(sample_summaries[1])
        
        # Index 0 = most recent
        assert history.get_by_index(0).title == "Page 1"
        assert history.get_by_index(1).title == "Page 0"
        assert history.get_by_index(5) is None
    
    def test_clear(self, history, sample_summaries):
        """Test clearing history."""
        history.add(sample_summaries[0])
        history.add(sample_summaries[1])
        
        assert history.count == 2
        
        history.clear()
        
        assert history.count == 0
    
    def test_to_list(self, history, sample_summaries):
        """Test converting to list."""
        history.add(sample_summaries[0])
        history.add(sample_summaries[1])
        
        items = history.to_list()
        
        assert len(items) == 2
        assert items[0]["index"] == 0
        assert items[0]["title"] == "Page 1"
        assert "url" in items[0]
        assert "short_summary" in items[0]
        assert "generated_at" in items[0]


# =============================================================================
# RateLimiter Tests
# =============================================================================


class TestRateLimiter:
    """Tests for RateLimiter class."""
    
    @pytest.fixture
    def limiter(self):
        """Create a test rate limiter."""
        return RateLimiter(max_requests=3, window_seconds=1.0)
    
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self, limiter):
        """Test acquiring within limit."""
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True
    
    @pytest.mark.asyncio
    async def test_acquire_over_limit(self, limiter):
        """Test acquiring over limit."""
        for _ in range(3):
            await limiter.acquire()
        
        # 4th should fail
        assert await limiter.acquire() is False
    
    @pytest.mark.asyncio
    async def test_window_reset(self):
        """Test window reset after time passes."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.5)
        
        await limiter.acquire()
        await limiter.acquire()
        assert await limiter.acquire() is False
        
        # Wait for window to reset
        await asyncio.sleep(0.6)
        
        # Should work again
        assert await limiter.acquire() is True
    
    @pytest.mark.asyncio
    async def test_wait_if_needed_success(self):
        """Test wait_if_needed succeeds."""
        limiter = RateLimiter(max_requests=2, window_seconds=0.5)
        
        await limiter.acquire()
        await limiter.acquire()
        
        # Start wait in background
        task = asyncio.create_task(limiter.wait_if_needed(timeout=1.0))
        
        # Wait for window to reset
        await asyncio.sleep(0.6)
        
        result = await task
        assert result is True
    
    @pytest.mark.asyncio
    async def test_wait_if_needed_timeout(self):
        """Test wait_if_needed times out."""
        limiter = RateLimiter(max_requests=2, window_seconds=10.0)
        
        await limiter.acquire()
        await limiter.acquire()
        
        result = await limiter.wait_if_needed(timeout=0.5)
        assert result is False
    
    def test_current_usage(self, limiter):
        """Test current usage property."""
        assert limiter.current_usage == 0


# =============================================================================
# MockPageSummarizer Tests
# =============================================================================


class TestMockPageSummarizer:
    """Tests for MockPageSummarizer class."""
    
    @pytest.fixture
    def summarizer(self):
        """Create a mock summarizer."""
        return MockPageSummarizer()
    
    @pytest.mark.asyncio
    async def test_extract_current_page(self, summarizer):
        """Test extracting current page."""
        page = await summarizer.extract_current_page()
        
        assert page is not None
        assert page.title == "Test Sayfası"
        assert page.url == "https://example.com/test"
        assert len(page.content) > 0
    
    @pytest.mark.asyncio
    async def test_summarize_tweet_length(self, summarizer):
        """Test summarizing with tweet length."""
        summary = await summarizer.summarize(length=SummaryLength.TWEET)
        
        assert summary is not None
        assert summary.length_type == SummaryLength.TWEET
        assert len(summary.short_summary) <= 280
        assert summary.detailed_summary == ""
        assert summary.key_points == []
    
    @pytest.mark.asyncio
    async def test_summarize_paragraph_length(self, summarizer):
        """Test summarizing with paragraph length."""
        summary = await summarizer.summarize(length=SummaryLength.PARAGRAPH)
        
        assert summary is not None
        assert summary.length_type == SummaryLength.PARAGRAPH
        assert len(summary.short_summary) > 0
    
    @pytest.mark.asyncio
    async def test_summarize_full_length(self, summarizer):
        """Test summarizing with full length."""
        summary = await summarizer.summarize(length=SummaryLength.FULL)
        
        assert summary is not None
        assert summary.length_type == SummaryLength.FULL
        assert len(summary.short_summary) > 0
        assert len(summary.detailed_summary) > 0
        assert len(summary.key_points) > 0
    
    @pytest.mark.asyncio
    async def test_caching(self, summarizer):
        """Test caching works."""
        summary1 = await summarizer.summarize()
        summary2 = await summarizer.summarize()
        
        assert summary2.from_cache is True
    
    @pytest.mark.asyncio
    async def test_history(self, summarizer):
        """Test history is populated."""
        await summarizer.summarize()
        
        assert summarizer.history.count == 1
    
    @pytest.mark.asyncio
    async def test_progress_callback(self, summarizer):
        """Test progress callback is called."""
        stages: List[Tuple[ProgressStage, str]] = []
        
        def callback(stage, message):
            stages.append((stage, message))
        
        await summarizer.summarize(progress_callback=callback)
        
        stage_types = [s[0] for s in stages]
        assert ProgressStage.STARTED in stage_types
        assert ProgressStage.COMPLETED in stage_types
    
    @pytest.mark.asyncio
    async def test_answer_question_ceo(self, summarizer):
        """Test answering CEO question."""
        await summarizer.extract_current_page()
        answer = await summarizer.answer_question("CEO kim?")
        
        assert "Musk" in answer
    
    @pytest.mark.asyncio
    async def test_answer_question_price(self, summarizer):
        """Test answering price question."""
        await summarizer.extract_current_page()
        answer = await summarizer.answer_question("Fiyatı ne?")
        
        assert "50.000" in answer or "50000" in answer
    
    @pytest.mark.asyncio
    async def test_answer_question_date(self, summarizer):
        """Test answering date question."""
        await summarizer.extract_current_page()
        answer = await summarizer.answer_question("Ne zaman çıkacak?")
        
        assert "2025" in answer


# =============================================================================
# PageSummarizer Tests
# =============================================================================


class TestPageSummarizer:
    """Tests for PageSummarizer class."""
    
    @pytest.fixture
    def summarizer(self):
        """Create a page summarizer without real bridge/llm."""
        return PageSummarizer()
    
    def test_initialization_defaults(self, summarizer):
        """Test default initialization."""
        assert summarizer.extract_timeout == 5.0
        assert summarizer.llm_timeout == 60.0
        assert summarizer.max_retries == 3
        assert isinstance(summarizer.cache, SummaryCache)
        assert isinstance(summarizer.history, SummaryHistory)
    
    def test_custom_initialization(self):
        """Test custom initialization."""
        summarizer = PageSummarizer(
            cache_ttl=7200,
            cache_size=50,
            history_size=20,
            max_retries=5,
            rate_limit=5,
        )
        
        assert summarizer.cache.max_size == 50
        assert summarizer.cache.ttl_seconds == 7200
        assert summarizer.history.max_size == 20
        assert summarizer.max_retries == 5
    
    def test_has_summary_false(self, summarizer):
        """Test has_summary when no summary."""
        assert summarizer.has_summary is False
    
    def test_has_content_false(self, summarizer):
        """Test has_content when no content."""
        assert summarizer.has_content is False
    
    def test_format_for_tts_no_summary(self, summarizer):
        """Test format_for_tts with no summary."""
        result = summarizer.format_for_tts()
        assert result == "Özet bulunamadı."
    
    def test_format_for_overlay_no_summary(self, summarizer):
        """Test format_for_overlay with no summary."""
        result = summarizer.format_for_overlay()
        
        assert result["type"] == "summary"
        assert result["title"] == "Özet Yok"
    
    def test_format_for_tts_with_summary(self, summarizer):
        """Test format_for_tts with summary."""
        summary = PageSummary(
            title="Test",
            url="https://example.com",
            short_summary="Kısa özet burada",
            detailed_summary="",
            key_points=[],
        )
        summarizer._last_summary = summary
        
        result = summarizer.format_for_tts()
        assert result == "Kısa özet burada"
    
    def test_format_for_overlay_short(self, summarizer):
        """Test format_for_overlay short version."""
        summary = PageSummary(
            title="Test Page",
            url="https://example.com",
            short_summary="Short summary",
            detailed_summary="",
            key_points=[],
        )
        summarizer._last_summary = summary
        
        result = summarizer.format_for_overlay(detailed=False)
        
        assert result["type"] == "summary"
        assert result["title"] == "Test Page"
        assert result["content"] == "Short summary"
        assert result["from_cache"] is False
    
    def test_format_for_overlay_detailed(self, summarizer):
        """Test format_for_overlay detailed version."""
        summary = PageSummary(
            title="Test Page",
            url="https://example.com",
            short_summary="Short",
            detailed_summary="Detailed summary here",
            key_points=["Point 1", "Point 2"],
        )
        summarizer._last_summary = summary
        
        result = summarizer.format_for_overlay(detailed=True)
        
        assert result["type"] == "summary_detailed"
        assert result["content"] == "Detailed summary here"
        assert len(result["items"]) == 2
        assert result["items"][0]["text"] == "Point 1"
    
    def test_clear(self, summarizer):
        """Test clear method."""
        summarizer._last_extracted = ExtractedPage(
            url="https://example.com",
            title="Test",
            content="Content",
            content_length=7,
            extracted_at="",
        )
        summarizer._last_summary = PageSummary(
            title="Test",
            url="https://example.com",
            short_summary="Short",
            detailed_summary="",
            key_points=[],
        )
        
        summarizer.clear()
        
        assert summarizer._last_extracted is None
        assert summarizer._last_summary is None
    
    @pytest.mark.asyncio
    async def test_clear_all(self, summarizer):
        """Test clear_all method."""
        await summarizer.cache.set("https://example.com", PageSummary(
            title="Test", url="https://example.com",
            short_summary="Short", detailed_summary="", key_points=[],
        ))
        
        await summarizer.clear_all()
        
        assert summarizer.cache.stats()["size"] == 0
        assert summarizer.history.count == 0
    
    def test_get_stats(self, summarizer):
        """Test get_stats method."""
        stats = summarizer.get_stats()
        
        assert "cache" in stats
        assert "history_count" in stats
        assert "rate_limiter_usage" in stats
        assert "has_summary" in stats
        assert "has_content" in stats


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestExtractQuestion:
    """Tests for extract_question function."""
    
    def test_question_mark(self):
        """Test extracting question with question mark."""
        result = extract_question("Bu CEO kim?")
        assert result == "Bu CEO kim?"
    
    def test_anlat_pattern(self):
        """Test 'anlat' pattern."""
        result = extract_question("anlat bakalım ne olmuş")
        assert "ne olmuş" in result
    
    def test_question_words(self):
        """Test question word patterns."""
        result = extract_question("neden böyle oldu")
        assert "neden" in result
    
    def test_empty_string(self):
        """Test empty string."""
        result = extract_question("")
        assert result is None
    
    def test_whitespace_only(self):
        """Test whitespace only."""
        result = extract_question("   ")
        assert result is None


class TestParseSummaryLength:
    """Tests for parse_summary_length function."""
    
    def test_short_keywords(self):
        """Test short/tweet keywords."""
        assert parse_summary_length("kısa özetle") == SummaryLength.TWEET
        assert parse_summary_length("tweet gibi yaz") == SummaryLength.TWEET
        assert parse_summary_length("çok kısa anlat") == SummaryLength.TWEET
    
    def test_full_keywords(self):
        """Test full/detailed keywords."""
        assert parse_summary_length("detaylı anlat") == SummaryLength.FULL
        assert parse_summary_length("uzun özet") == SummaryLength.FULL
        assert parse_summary_length("tam açıkla") == SummaryLength.FULL
    
    def test_default_paragraph(self):
        """Test default is paragraph."""
        assert parse_summary_length("özetle") == SummaryLength.PARAGRAPH
        assert parse_summary_length("anlat") == SummaryLength.PARAGRAPH
        assert parse_summary_length("sayfayı özetle") == SummaryLength.PARAGRAPH


# =============================================================================
# Integration Tests
# =============================================================================


class TestSummarizerIntegration:
    """Integration tests for the summarizer system."""
    
    @pytest.fixture
    def summarizer(self):
        """Create a mock summarizer for integration tests."""
        return MockPageSummarizer()
    
    @pytest.mark.asyncio
    async def test_full_workflow(self, summarizer):
        """Test full summarization workflow."""
        # Track progress
        stages: List[ProgressStage] = []
        
        def on_progress(stage, message):
            stages.append(stage)
        
        # First summarization
        summary1 = await summarizer.summarize(
            length=SummaryLength.PARAGRAPH,
            use_cache=True,
            progress_callback=on_progress,
        )
        
        assert summary1 is not None
        assert ProgressStage.STARTED in stages
        assert ProgressStage.COMPLETED in stages
        
        # Second summarization (should be cached)
        stages.clear()
        summary2 = await summarizer.summarize(
            length=SummaryLength.PARAGRAPH,
            use_cache=True,
            progress_callback=on_progress,
        )
        
        assert summary2 is not None
        assert summary2.from_cache is True
        assert ProgressStage.CACHED in stages
    
    @pytest.mark.asyncio
    async def test_history_navigation(self, summarizer):
        """Test navigating through history."""
        # Create summaries for different URLs
        # Clear last_extracted each time to force re-extraction with new URL
        
        summarizer._mock_url = "https://example.com/page1"
        summarizer._last_extracted = None  # Force re-extract
        await summarizer.summarize(use_cache=False)
        
        summarizer._mock_url = "https://example.com/page2"
        summarizer._last_extracted = None  # Force re-extract
        await summarizer.summarize(use_cache=False)
        
        summarizer._mock_url = "https://example.com/page3"
        summarizer._last_extracted = None  # Force re-extract
        await summarizer.summarize(use_cache=False)
        
        # Check history
        assert summarizer.history.count == 3
        
        # Most recent first
        recent = summarizer.history.get_recent(2)
        assert len(recent) == 2
        assert recent[0].url == "https://example.com/page3"
        assert recent[1].url == "https://example.com/page2"
        
        # Get by index
        oldest = summarizer.history.get_by_index(2)
        assert oldest.url == "https://example.com/page1"
    
    @pytest.mark.asyncio
    async def test_different_lengths_same_url(self, summarizer):
        """Test different summary lengths for same URL."""
        # Tweet summary
        tweet_summary = await summarizer.summarize(
            length=SummaryLength.TWEET,
            use_cache=False,
        )
        assert tweet_summary.length_type == SummaryLength.TWEET
        assert len(tweet_summary.short_summary) <= 280
        
        # Full summary
        full_summary = await summarizer.summarize(
            length=SummaryLength.FULL,
            use_cache=False,
        )
        assert full_summary.length_type == SummaryLength.FULL
        assert len(full_summary.detailed_summary) > 0
        assert len(full_summary.key_points) > 0
    
    @pytest.mark.asyncio
    async def test_stats_after_operations(self, summarizer):
        """Test statistics after operations."""
        await summarizer.summarize()
        await summarizer.summarize()  # Cached
        
        stats = summarizer.get_stats()
        
        assert stats["cache"]["size"] == 1
        assert stats["history_count"] == 1  # Same URL, no duplicate
        assert stats["has_summary"] is True


# =============================================================================
# Performance Tests
# =============================================================================


class TestSummarizerPerformance:
    """Performance tests for the summarizer."""
    
    @pytest.mark.asyncio
    async def test_cache_performance(self):
        """Test cache performance with many entries."""
        cache = SummaryCache(max_size=100, ttl_seconds=3600)
        
        # Insert 100 entries
        for i in range(100):
            summary = PageSummary(
                title=f"Page {i}",
                url=f"https://example.com/{i}",
                short_summary=f"Summary {i}",
                detailed_summary="",
                key_points=[],
            )
            await cache.set(f"https://example.com/{i}", summary)
        
        # All should be retrievable
        for i in range(100):
            result = await cache.get(f"https://example.com/{i}")
            assert result is not None
    
    @pytest.mark.asyncio
    async def test_rate_limiter_burst(self):
        """Test rate limiter under burst conditions."""
        limiter = RateLimiter(max_requests=5, window_seconds=1.0)
        
        success_count = 0
        for _ in range(10):
            if await limiter.acquire():
                success_count += 1
        
        assert success_count == 5  # Only 5 should succeed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
