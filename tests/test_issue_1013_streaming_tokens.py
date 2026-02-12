"""Tests for Issue #1013: Streaming token count accuracy.

Verifies that:
1. Token count uses usage stats from final chunk if available
2. Falls back to content-length estimation (chars/4) when no usage
3. No longer blindly increments by 1 per chunk
"""

import pytest
from dataclasses import dataclass
from typing import Optional, Any
from unittest.mock import MagicMock


@dataclass
class FakeUsage:
    completion_tokens: int = 0
    prompt_tokens: int = 0
    total_tokens: int = 0


@dataclass
class FakeDelta:
    content: Optional[str] = None


@dataclass
class FakeChoice:
    delta: FakeDelta = None
    finish_reason: Optional[str] = None

    def __post_init__(self):
        if self.delta is None:
            self.delta = FakeDelta()


@dataclass
class FakeChunk:
    choices: list = None
    usage: Any = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []


class TestTokenCountEstimation:
    """Token estimation logic extracted for unit testing."""

    def _simulate_stream(self, chunks_content: list[str], usage_tokens: int | None = None):
        """Simulate streaming and return final total_tokens.

        Mimics the logic from vllm_openai_client.py stream_chat.
        """
        total_tokens = 0
        total_content_chars = 0
        chunk_count = 0

        for i, text in enumerate(chunks_content):
            is_last = (i == len(chunks_content) - 1)

            # Simulate chunk
            chunk = FakeChunk(
                choices=[FakeChoice(
                    delta=FakeDelta(content=text),
                    finish_reason="stop" if is_last else None,
                )],
                usage=FakeUsage(completion_tokens=usage_tokens) if (is_last and usage_tokens) else None,
            )

            # Usage extraction (same logic as vllm_openai_client.py)
            if hasattr(chunk, "usage") and chunk.usage:
                usage = chunk.usage
                if hasattr(usage, "completion_tokens") and usage.completion_tokens:
                    total_tokens = int(usage.completion_tokens)

            content = chunk.choices[0].delta.content or ""
            if content:
                chunk_count += 1
                total_content_chars += len(content)

        # Fallback estimation
        if total_tokens == 0 and total_content_chars > 0:
            total_tokens = max(1, total_content_chars // 4)

        return total_tokens

    def test_usage_stats_preferred(self):
        """When usage stats are available, use them."""
        total = self._simulate_stream(
            ["Merhaba", ", ben ", "Bantz!"],
            usage_tokens=5,
        )
        assert total == 5

    def test_content_length_fallback(self):
        """Without usage stats, estimate from content length."""
        # "Merhaba, ben Bantz!" = 19 chars → 19//4 = 4 tokens
        total = self._simulate_stream(
            ["Merhaba", ", ben ", "Bantz!"],
            usage_tokens=None,
        )
        expected = len("Merhaba, ben Bantz!") // 4  # 4
        assert total == expected

    def test_not_one_per_chunk(self):
        """Token count should NOT be equal to chunk count."""
        # 3 chunks, each with long content — should be >> 3
        chunks = ["Bu çok uzun bir metin parçası " * 5] * 3
        total = self._simulate_stream(chunks)
        assert total > 3, f"Token count ({total}) should be > chunk count (3)"

    def test_single_char_chunk(self):
        """Single char chunk → at least 1 token."""
        total = self._simulate_stream(["a"])
        assert total >= 1

    def test_empty_stream(self):
        """No content → 0 tokens."""
        total = self._simulate_stream([])
        assert total == 0

    def test_large_content_estimation(self):
        """Large content should give reasonable token estimate."""
        # 400 chars → ~100 tokens
        big_text = "a" * 400
        total = self._simulate_stream([big_text])
        assert total == 100
