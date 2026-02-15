"""
Tests for Web Tools (Issue #32 - V2-2).

Tests WebSearchTool, WebSearchRequestsTool, PageReaderTool.
"""

import pytest
from bantz.agent.tool_base import ToolContext, ToolResult
from bantz.agent.web_tools import (
    WebSearchTool,
    WebSearchRequestsTool,
    PageReaderTool,
    FetchUrlTool,
    web_search_tool,
    web_search_requests_tool,
    page_reader_tool,
    fetch_url_tool,
)
from bantz.core.events import EventBus, EventType


@pytest.fixture
def event_bus():
    """Create EventBus for testing."""
    return EventBus()


@pytest.fixture
def context(event_bus):
    """Create ToolContext for testing."""
    return ToolContext(job_id="test-job-123", event_bus=event_bus)


class TestWebSearchToolSpec:
    """Test WebSearchTool specification."""
    
    def test_web_search_spec_valid(self):
        """WebSearchTool.spec() returns valid spec."""
        tool = WebSearchTool()
        spec = tool.spec()
        
        assert spec.name == "web_search"
        assert spec.description is not None
        assert "query" in spec.parameters
    
    def test_web_search_spec_timeout(self):
        """WebSearchTool has 30s timeout."""
        tool = WebSearchTool()
        spec = tool.spec()
        
        assert spec.timeout == 30.0
    
    def test_web_search_spec_retries(self):
        """WebSearchTool has 3 retries."""
        tool = WebSearchTool()
        spec = tool.spec()
        
        assert spec.max_retries == 3
    
    def test_web_search_spec_fallback(self):
        """WebSearchTool has fallback configured."""
        tool = WebSearchTool()
        spec = tool.spec()
        
        assert spec.fallback_tool == "web_search_requests"
    
    def test_web_search_query_required(self):
        """query parameter is required."""
        tool = WebSearchTool()
        spec = tool.spec()
        
        assert spec.parameters["query"]["required"] is True


class TestWebSearchToolRun:
    """Test WebSearchTool execution."""
    
    @pytest.mark.asyncio
    async def test_web_search_run_mock(self, context):
        """WebSearchTool.run() returns failure (Issue #1015: Playwright stub)."""
        tool = WebSearchTool()
        
        result = await tool.run({"query": "python programming"}, context)
        
        # Issue #1015: Playwright search is intentionally unimplemented.
        # The tool returns a failure with a "not implemented" message.
        assert result.success is False
        assert "not implemented" in (result.error or "").lower()
    
    @pytest.mark.asyncio
    async def test_web_search_publishes_found(self, context):
        """WebSearchTool does NOT publish FOUND (Issue #1015: stub fails)."""
        events = []
        context.event_bus.subscribe("found", lambda e: events.append(e))
        
        tool = WebSearchTool()
        await tool.run({"query": "test"}, context)
        
        # Stub fails before publishing events
        assert len(events) == 0
    
    @pytest.mark.asyncio
    async def test_web_search_publishes_progress(self, context):
        """WebSearchTool publishes PROGRESS event."""
        events = []
        context.event_bus.subscribe("progress", lambda e: events.append(e))
        
        tool = WebSearchTool()
        await tool.run({"query": "test"}, context)
        
        assert len(events) >= 1
    
    @pytest.mark.asyncio
    async def test_web_search_tracks_duration(self, context):
        """WebSearchTool tracks execution duration."""
        tool = WebSearchTool()
        
        result = await tool.run({"query": "test"}, context)
        
        assert result.duration_ms >= 0


class TestWebSearchRequestsToolSpec:
    """Test WebSearchRequestsTool specification."""
    
    def test_web_search_requests_spec_valid(self):
        """WebSearchRequestsTool.spec() returns valid spec."""
        tool = WebSearchRequestsTool()
        spec = tool.spec()
        
        assert spec.name == "web_search_requests"
        assert "query" in spec.parameters
    
    def test_web_search_requests_no_fallback(self):
        """WebSearchRequestsTool has no further fallback."""
        tool = WebSearchRequestsTool()
        spec = tool.spec()
        
        assert spec.fallback_tool is None


class TestWebSearchRequestsToolRun:
    """Test WebSearchRequestsTool execution."""
    
    @pytest.mark.asyncio
    async def test_web_search_requests_run_mock(self, context):
        """WebSearchRequestsTool.run() returns failure (Issue #1015: stub)."""
        tool = WebSearchRequestsTool()
        
        result = await tool.run({"query": "fallback test"}, context)
        
        # Issue #1015: Requests search is intentionally unimplemented.
        assert result.success is False
        assert "not implemented" in (result.error or "").lower()


class TestPageReaderToolSpec:
    """Test PageReaderTool specification."""
    
    def test_page_reader_spec_valid(self):
        """PageReaderTool.spec() returns valid spec."""
        tool = PageReaderTool()
        spec = tool.spec()
        
        assert spec.name == "page_reader"
        assert "url" in spec.parameters
    
    def test_page_reader_timeout_45s(self):
        """PageReaderTool has 45s timeout."""
        tool = PageReaderTool()
        spec = tool.spec()
        
        assert spec.timeout == 45.0
    
    def test_page_reader_url_required(self):
        """url parameter is required."""
        tool = PageReaderTool()
        spec = tool.spec()
        
        assert spec.parameters["url"]["required"] is True


class TestPageReaderToolRun:
    """Test PageReaderTool execution."""
    
    @pytest.mark.asyncio
    async def test_page_reader_run_mock(self, context):
        """PageReaderTool.run() returns failure (Issue #1015: stub)."""
        tool = PageReaderTool()
        
        result = await tool.run(
            {"url": "https://example.com"},
            context
        )
        
        # Issue #1015: Page reader is intentionally unimplemented.
        assert result.success is False
        assert "not implemented" in (result.error or "").lower()


class TestFetchUrlToolSpec:
    """Test FetchUrlTool specification."""
    
    def test_fetch_url_spec_valid(self):
        """FetchUrlTool.spec() returns valid spec."""
        tool = FetchUrlTool()
        spec = tool.spec()
        
        assert spec.name == "fetch_url"
        assert "url" in spec.parameters
    
    def test_fetch_url_headers_optional(self):
        """headers parameter is optional."""
        tool = FetchUrlTool()
        spec = tool.spec()
        
        assert spec.parameters["headers"]["required"] is False


class TestFetchUrlToolRun:
    """Test FetchUrlTool execution."""
    
    @pytest.mark.asyncio
    async def test_fetch_url_run_mock(self, context):
        """FetchUrlTool.run() returns failure (Issue #1015: stub)."""
        tool = FetchUrlTool()
        
        result = await tool.run(
            {"url": "https://example.com"},
            context
        )
        
        # Issue #1015: Fetch URL is intentionally unimplemented.
        assert result.success is False
        assert "not implemented" in (result.error or "").lower()


class TestToolInstances:
    """Test pre-created tool instances."""
    
    def test_web_search_tool_instance(self):
        """web_search_tool is WebSearchTool instance."""
        assert isinstance(web_search_tool, WebSearchTool)
    
    def test_web_search_requests_tool_instance(self):
        """web_search_requests_tool is WebSearchRequestsTool instance."""
        assert isinstance(web_search_requests_tool, WebSearchRequestsTool)
    
    def test_page_reader_tool_instance(self):
        """page_reader_tool is PageReaderTool instance."""
        assert isinstance(page_reader_tool, PageReaderTool)
    
    def test_fetch_url_tool_instance(self):
        """fetch_url_tool is FetchUrlTool instance."""
        assert isinstance(fetch_url_tool, FetchUrlTool)


class TestToolValidation:
    """Test input validation for web tools."""
    
    def test_web_search_validates_query(self):
        """WebSearchTool validates query parameter."""
        tool = WebSearchTool()
        
        is_valid, error = tool.validate_input({})
        assert is_valid is False
        assert "query" in error
    
    def test_page_reader_validates_url(self):
        """PageReaderTool validates url parameter."""
        tool = PageReaderTool()
        
        is_valid, error = tool.validate_input({})
        assert is_valid is False
        assert "url" in error
    
    def test_fetch_url_validates_url(self):
        """FetchUrlTool validates url parameter."""
        tool = FetchUrlTool()
        
        is_valid, error = tool.validate_input({})
        assert is_valid is False
        assert "url" in error
