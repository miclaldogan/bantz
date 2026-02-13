"""Tests for Issue #996: vLLM Health Check URL fix.

is_available() was using self.base_url/models instead of self.base_url/v1/models.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestIsAvailableURL:
    """is_available() should hit /v1/models, not /models."""

    def _make_client(self, base_url="http://localhost:8001"):
        from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        return VLLMOpenAIClient(base_url=base_url, model="test-model")

    @patch("requests.get")
    def test_url_includes_v1(self, mock_get):
        """Health check should use /v1/models endpoint."""
        mock_get.return_value = MagicMock(status_code=200)
        client = self._make_client("http://localhost:8001")
        result = client.is_available()
        assert result is True
        called_url = mock_get.call_args[0][0]
        assert called_url == "http://localhost:8001/v1/models"

    @patch("requests.get")
    def test_url_already_has_v1(self, mock_get):
        """If base_url already ends with /v1, don't double it."""
        mock_get.return_value = MagicMock(status_code=200)
        client = self._make_client("http://localhost:8001/v1")
        result = client.is_available()
        assert result is True
        called_url = mock_get.call_args[0][0]
        assert called_url == "http://localhost:8001/v1/models"

    @patch("requests.get")
    def test_trailing_slash_stripped(self, mock_get):
        """Trailing slash should be stripped before appending."""
        mock_get.return_value = MagicMock(status_code=200)
        client = self._make_client("http://localhost:8001/")
        result = client.is_available()
        assert result is True
        called_url = mock_get.call_args[0][0]
        assert called_url == "http://localhost:8001/v1/models"

    @patch("requests.get")
    def test_server_down_returns_false(self, mock_get):
        mock_get.side_effect = ConnectionError("refused")
        client = self._make_client()
        assert client.is_available() is False

    @patch("requests.get")
    def test_404_returns_false(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        client = self._make_client()
        assert client.is_available() is False
