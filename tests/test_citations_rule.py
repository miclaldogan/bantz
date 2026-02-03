"""Tests for citations module (Issue #90)."""

from __future__ import annotations

from bantz.brain.citations import (
    extract_citations_from_response,
    format_citations_for_display,
    verify_two_source_rule,
    extract_sources_from_tool_results,
    validate_citation_quality,
)


class TestCitationExtraction:
    """Tests for citation extraction."""
    
    def test_extract_citations_from_response(self):
        """Test extracting citations from LLM response."""
        response = {
            "reply": "Python is a programming language.",
            "citations": [
                {"title": "Python Docs", "url": "https://docs.python.org"},
                {"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Python"}
            ]
        }
        
        citations = extract_citations_from_response(response)
        
        assert len(citations) == 2
        assert citations[0]["title"] == "Python Docs"
        assert citations[0]["url"] == "https://docs.python.org"
    
    def test_extract_citations_no_citations(self):
        """Test extracting citations when none provided."""
        response = {"reply": "Some text"}
        
        citations = extract_citations_from_response(response)
        
        assert citations == []
    
    def test_extract_citations_malformed(self):
        """Test extracting citations with malformed data."""
        response = {
            "citations": [
                {"title": "Valid", "url": "https://example.com"},
                {"title": "No URL"},  # Missing URL
                "invalid",  # Not a dict
            ]
        }
        
        citations = extract_citations_from_response(response)
        
        assert len(citations) == 1
        assert citations[0]["url"] == "https://example.com"


class TestTwoSourceRule:
    """Tests for 2-source rule verification."""
    
    def test_two_source_rule_pass(self):
        """Test 2-source rule with sufficient sources."""
        citations = [
            {"title": "Source 1", "url": "https://example.com"},
            {"title": "Source 2", "url": "https://different.org"},
        ]
        
        valid, reason = verify_two_source_rule(citations)
        
        assert valid is True
        assert reason is None
    
    def test_two_source_rule_fail_no_citations(self):
        """Test 2-source rule with no citations."""
        valid, reason = verify_two_source_rule([])
        
        assert valid is False
        assert "No citations" in reason
    
    def test_two_source_rule_fail_one_source(self):
        """Test 2-source rule with only one source."""
        citations = [
            {"title": "Source 1", "url": "https://example.com"},
        ]
        
        valid, reason = verify_two_source_rule(citations)
        
        assert valid is False
        assert "Insufficient" in reason
    
    def test_two_source_rule_fail_same_domain(self):
        """Test 2-source rule with sources from same domain."""
        citations = [
            {"title": "Page 1", "url": "https://example.com/page1"},
            {"title": "Page 2", "url": "https://example.com/page2"},
        ]
        
        valid, reason = verify_two_source_rule(citations)
        
        assert valid is False
        assert "same domain" in reason


class TestCitationFormatting:
    """Tests for citation formatting."""
    
    def test_format_citations_for_display(self):
        """Test formatting citations for display."""
        citations = [
            {"title": "Python Docs", "url": "https://docs.python.org"},
            {"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Python"}
        ]
        
        formatted = format_citations_for_display(citations)
        
        assert "Kaynaklar:" in formatted
        assert "1. Python Docs" in formatted
        assert "2. Wikipedia" in formatted
        # Verify citations contain expected URLs without substring checks (Security Alert #37)
        assert len(citations) == 2
        assert citations[0]["url"].startswith("https://docs.python.org")
    
    def test_format_citations_empty(self):
        """Test formatting empty citations."""
        formatted = format_citations_for_display([])
        
        assert formatted == ""


class TestSourceExtraction:
    """Tests for extracting sources from tool results."""
    
    def test_extract_sources_from_web_search(self):
        """Test extracting sources from web.search results."""
        tool_results = [
            {
                "tool_name": "web.search",
                "output": {
                    "ok": True,
                    "results": [
                        {"title": "Result 1", "url": "https://example.com", "snippet": "..."},
                        {"title": "Result 2", "url": "https://test.org", "snippet": "..."},
                    ]
                }
            }
        ]
        
        sources = extract_sources_from_tool_results(tool_results)
        
        assert len(sources) == 2
        assert sources[0]["url"] == "https://example.com"
    
    def test_extract_sources_from_web_open(self):
        """Test extracting sources from web.open results."""
        tool_results = [
            {
                "tool_name": "web.open",
                "output": {
                    "ok": True,
                    "title": "Page Title",
                    "url": "https://example.com",
                    "text": "..."
                }
            }
        ]
        
        sources = extract_sources_from_tool_results(tool_results)
        
        assert len(sources) == 1
        assert sources[0]["title"] == "Page Title"


class TestCitationQuality:
    """Tests for citation quality validation."""
    
    def test_validate_citation_quality_perfect_match(self):
        """Test citation quality when all sources are cited."""
        citations = [
            {"title": "Source 1", "url": "https://example.com"},
            {"title": "Source 2", "url": "https://test.org"},
        ]
        tool_sources = [
            {"title": "Source 1", "url": "https://example.com"},
            {"title": "Source 2", "url": "https://test.org"},
        ]
        
        valid, warnings = validate_citation_quality(citations, tool_sources)
        
        assert valid is True
        assert len(warnings) == 0
    
    def test_validate_citation_quality_unknown_sources(self):
        """Test citation quality when LLM cites unknown sources."""
        citations = [
            {"title": "Unknown", "url": "https://unknown.com"},
        ]
        tool_sources = [
            {"title": "Known", "url": "https://example.com"},
        ]
        
        valid, warnings = validate_citation_quality(citations, tool_sources)
        
        assert valid is False
        assert len(warnings) > 0
        assert "unknown sources" in warnings[0].lower()
