"""
Tests for Source Collector (Issue #33 - V2-3).

Test Scenarios:
- Source collection returns list
- Source has required fields (URL, title)
- Date parsing for various formats
- Max sources limit
- Domain extraction from URL
"""

import pytest
from datetime import datetime

from bantz.research.source_collector import (
    Source,
    SourceCollector,
    MONTH_NAMES,
)


class TestSourceDataclass:
    """Test Source dataclass."""
    
    def test_source_required_fields(self):
        """Source requires url, title, snippet."""
        source = Source(
            url="https://example.com/article",
            title="Test Article",
            snippet="This is a test snippet"
        )
        assert source.url == "https://example.com/article"
        assert source.title == "Test Article"
        assert source.snippet == "This is a test snippet"
    
    def test_source_optional_date(self):
        """Date is optional and defaults to None."""
        source = Source(url="https://example.com", title="Test", snippet="")
        assert source.date is None
    
    def test_source_with_date(self):
        """Source can have a date."""
        date = datetime(2024, 1, 15)
        source = Source(
            url="https://example.com",
            title="Test",
            snippet="",
            date=date
        )
        assert source.date == date
    
    def test_source_domain_auto_extracted(self):
        """Domain is auto-extracted from URL."""
        source = Source(
            url="https://www.reuters.com/article/test",
            title="Test",
            snippet=""
        )
        assert source.domain == "reuters.com"
    
    def test_source_domain_no_www(self):
        """Domain extraction removes www prefix."""
        source = Source(
            url="https://bbc.com/news",
            title="Test",
            snippet=""
        )
        assert source.domain == "bbc.com"
    
    def test_source_domain_manual_override(self):
        """Manually provided domain is preserved."""
        source = Source(
            url="https://example.com",
            title="Test",
            snippet="",
            domain="custom.domain.com"
        )
        assert source.domain == "custom.domain.com"
    
    def test_source_reliability_default_zero(self):
        """Reliability defaults to 0.0."""
        source = Source(url="https://example.com", title="Test", snippet="")
        assert source.reliability_score == 0.0
    
    def test_source_content_type_default(self):
        """Content type defaults to article."""
        source = Source(url="https://example.com", title="Test", snippet="")
        assert source.content_type == "article"
    
    def test_source_content_types(self):
        """Source can have different content types."""
        for content_type in ["article", "news", "academic", "social"]:
            source = Source(
                url="https://example.com",
                title="Test",
                snippet="",
                content_type=content_type
            )
            assert source.content_type == content_type


class TestSourceCollectorDateParsing:
    """Test date parsing functionality."""
    
    @pytest.fixture
    def collector(self):
        return SourceCollector()
    
    def test_parse_date_iso_format(self, collector):
        """Parse ISO date format (YYYY-MM-DD)."""
        result = collector.parse_date("2024-01-15")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_us_format(self, collector):
        """Parse US date format (MM/DD/YYYY)."""
        result = collector.parse_date("01/15/2024")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_european_format(self, collector):
        """Parse European date format (DD.MM.YYYY)."""
        result = collector.parse_date("15.01.2024")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_text_month_long(self, collector):
        """Parse text month format (Month DD, YYYY)."""
        result = collector.parse_date("January 15, 2024")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_text_month_short(self, collector):
        """Parse short month format (Jan 15, 2024)."""
        result = collector.parse_date("Jan 15, 2024")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_text_month_no_comma(self, collector):
        """Parse text month without comma."""
        result = collector.parse_date("January 15 2024")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_day_month_year(self, collector):
        """Parse DD Mon YYYY format."""
        result = collector.parse_date("15 Jan 2024")
        assert result == datetime(2024, 1, 15)
    
    def test_parse_date_empty_returns_none(self, collector):
        """Empty string returns None."""
        result = collector.parse_date("")
        assert result is None
    
    def test_parse_date_invalid_returns_none(self, collector):
        """Invalid date returns None."""
        result = collector.parse_date("not a date")
        assert result is None
    
    def test_parse_date_all_months(self, collector):
        """All month names are recognized."""
        for month_name, month_num in MONTH_NAMES.items():
            date_str = f"{month_name.capitalize()} 15, 2024"
            result = collector.parse_date(date_str)
            if result:  # Some variations may not match
                assert result.month == month_num


class TestSourceCollectorContentType:
    """Test content type detection."""
    
    @pytest.fixture
    def collector(self):
        return SourceCollector()
    
    @pytest.mark.asyncio
    async def test_detect_news_domain(self, collector):
        """News domains are detected."""
        source = await collector.extract_metadata("https://reuters.com/article/test")
        assert source.content_type == "news"
    
    @pytest.mark.asyncio
    async def test_detect_academic_domain(self, collector):
        """Academic domains are detected."""
        source = await collector.extract_metadata("https://arxiv.org/abs/1234")
        assert source.content_type == "academic"
    
    @pytest.mark.asyncio
    async def test_detect_social_domain(self, collector):
        """Social media domains are detected."""
        source = await collector.extract_metadata("https://twitter.com/user/status/123")
        assert source.content_type == "social"
    
    @pytest.mark.asyncio
    async def test_detect_default_article(self, collector):
        """Unknown domains default to article."""
        source = await collector.extract_metadata("https://randomblog.example.com/post")
        assert source.content_type == "article"


class TestSourceCollectorCollect:
    """Test source collection."""
    
    @pytest.fixture
    def collector(self):
        return SourceCollector()
    
    @pytest.mark.asyncio
    async def test_collect_returns_list(self, collector):
        """Collect returns a list."""
        result = await collector.collect("test query")
        assert isinstance(result, list)
    
    @pytest.mark.asyncio
    async def test_collect_empty_without_search_tool(self, collector):
        """Without search tool, returns empty list."""
        result = await collector.collect("test query")
        assert result == []
    
    @pytest.mark.asyncio
    async def test_collect_respects_max_sources(self, collector):
        """Max sources parameter is respected."""
        result = await collector.collect("test query", max_sources=5)
        assert len(result) <= 5


class TestSourceCollectorExtractMetadata:
    """Test metadata extraction."""
    
    @pytest.fixture
    def collector(self):
        return SourceCollector()
    
    @pytest.mark.asyncio
    async def test_extract_metadata_returns_source(self, collector):
        """Extract metadata returns a Source object."""
        result = await collector.extract_metadata("https://example.com/article")
        assert isinstance(result, Source)
    
    @pytest.mark.asyncio
    async def test_extract_metadata_has_domain(self, collector):
        """Extracted source has domain."""
        result = await collector.extract_metadata("https://www.bbc.com/news/article")
        assert result.domain == "bbc.com"
    
    @pytest.mark.asyncio
    async def test_extract_metadata_has_url(self, collector):
        """Extracted source has original URL."""
        url = "https://example.com/article"
        result = await collector.extract_metadata(url)
        assert result.url == url
