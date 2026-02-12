"""Tests for Issue #1015: Web tools stubs raise NotImplementedError."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


class TestWebToolStubsExplicit(unittest.TestCase):
    """Stub web tools should raise NotImplementedError, not return fake data."""

    def test_no_todo_stubs_in_web_tools(self):
        """web_tools.py should not contain TODO stub markers."""
        source = (_SRC / "agent" / "web_tools.py").read_text("utf-8")
        # Old stubs had 'TODO: Implement actual' comments
        self.assertNotIn(
            "TODO: Implement actual",
            source,
            "web_tools.py still contains TODO stub placeholders",
        )

    def test_web_search_tool_raises(self):
        """WebSearchTool._search_with_playwright should raise NotImplementedError."""
        from bantz.agent.web_tools import WebSearchTool
        tool = WebSearchTool()
        with self.assertRaises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                tool._search_with_playwright("test", 5)
            )

    def test_web_search_requests_tool_raises(self):
        """WebSearchRequestsTool._search_with_requests should raise NotImplementedError."""
        from bantz.agent.web_tools import WebSearchRequestsTool
        tool = WebSearchRequestsTool()
        with self.assertRaises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                tool._search_with_requests("test", 5)
            )

    def test_page_reader_tool_raises(self):
        """PageReaderTool._read_page should raise NotImplementedError."""
        from bantz.agent.web_tools import PageReaderTool
        tool = PageReaderTool()
        with self.assertRaises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                tool._read_page("https://example.com", "text")
            )

    def test_fetch_url_tool_raises(self):
        """FetchUrlTool._fetch should raise NotImplementedError."""
        from bantz.agent.web_tools import FetchUrlTool
        tool = FetchUrlTool()
        with self.assertRaises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                tool._fetch("https://example.com", {})
            )

    def test_real_web_search_exists(self):
        """bantz.tools.web_search.web_search should be a real implementation."""
        from bantz.tools.web_search import web_search
        # Should not raise NotImplementedError
        self.assertTrue(callable(web_search))

    def test_real_web_open_exists(self):
        """bantz.tools.web_open.web_open should be a real implementation."""
        from bantz.tools.web_open import web_open
        self.assertTrue(callable(web_open))


if __name__ == "__main__":
    unittest.main()
