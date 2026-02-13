"""Tests for web tools (Issue #89)."""

from __future__ import annotations

import pytest

from bantz.tools.web_search import web_search
from bantz.tools.web_open import web_open, _is_url_allowed


class TestWebSearch:
    """Tests for web_search tool."""
    
    def test_web_search_returns_dict(self):
        """Test that web_search returns proper structure."""
        result = web_search("python programming", count=3)
        
        assert isinstance(result, dict)
        assert "ok" in result
        assert "results" in result
        assert "query" in result
        assert "count" in result
        
        if result["ok"]:
            assert isinstance(result["results"], list)
            assert result["query"] == "python programming"
    
    def test_web_search_empty_query(self):
        """Test web_search with empty query."""
        result = web_search("", count=3)
        
        assert result["ok"] is False
        assert "error" in result
        assert result["count"] == 0
    
    def test_web_search_result_structure(self):
        """Test that search results have proper structure."""
        result = web_search("test query", count=3)
        
        if result["ok"] and result["results"]:
            for item in result["results"]:
                assert "title" in item
                assert "url" in item
                assert "snippet" in item
                assert isinstance(item["title"], str)
                assert isinstance(item["url"], str)
                assert isinstance(item["snippet"], str)
    
    def test_web_search_count_limit(self):
        """Test that count parameter limits results."""
        result = web_search("python", count=3)
        
        if result["ok"]:
            assert len(result["results"]) <= 3


class TestWebOpen:
    """Tests for web_open tool."""
    
    def test_web_open_returns_dict(self):
        """Test that web_open returns proper structure."""
        result = web_open("https://www.python.org")
        
        assert isinstance(result, dict)
        assert "ok" in result
        assert "title" in result
        assert "text" in result
        assert "url" in result
    
    def test_web_open_empty_url(self):
        """Test web_open with empty URL."""
        result = web_open("")
        
        assert result["ok"] is False
        assert "error" in result
    
    def test_web_open_disallowed_url(self):
        """Test web_open with localhost URL (should be denied)."""
        result = web_open("http://localhost:8000")
        
        assert result["ok"] is False
        assert "error" in result
    
    def test_web_open_https_wikipedia(self):
        """Test opening Wikipedia page."""
        result = web_open("https://en.wikipedia.org/wiki/Python_(programming_language)")
        
        if result["ok"]:
            assert len(result["title"]) > 0
            assert len(result["text"]) > 0
            assert "Python" in result["text"] or "python" in result["text"].lower()
    
    def test_web_open_text_truncation(self):
        """Test that text is truncated to max_chars."""
        result = web_open("https://www.python.org", max_chars=100)
        
        if result["ok"]:
            assert len(result["text"]) <= 100 + 3  # +3 for "..."


class TestURLPolicy:
    """Tests for URL policy checks."""
    
    def test_localhost_denied(self):
        """Test that localhost is denied."""
        assert not _is_url_allowed("http://localhost:8000")
        assert not _is_url_allowed("http://127.0.0.1:8080")
    
    def test_private_ip_denied(self):
        """Test that private IPs are denied."""
        assert not _is_url_allowed("http://192.168.1.1")
        assert not _is_url_allowed("http://10.0.0.1")
        assert not _is_url_allowed("http://172.16.0.1")
    
    def test_https_allowed(self):
        """Test that HTTPS URLs are generally allowed."""
        assert _is_url_allowed("https://www.python.org")
        assert _is_url_allowed("https://github.com")
    
    def test_non_http_denied(self):
        """Test that non-HTTP schemes are denied."""
        assert not _is_url_allowed("ftp://example.com")
        assert not _is_url_allowed("file:///etc/passwd")
