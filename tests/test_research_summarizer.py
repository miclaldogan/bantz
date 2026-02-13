"""Tests for ResearchSummarizer (Issue #861)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.research.summarizer import (
    ResearchSummarizer,
    SummaryRequest,
    SummaryResult,
    create_research_summarizer,
    MAX_SOURCE_CHARS,
)
from bantz.research.source_collector import Source
from bantz.research.contradiction import ContradictionResult


# ── helpers ──────────────────────────────────────────────────────

def _source(title="T", snippet="S", url="https://x.com", domain="x.com", date=None):
    return Source(
        url=url, title=title, snippet=snippet, domain=domain,
        date=date, reliability_score=0.8, content_type="news",
    )


def _contradiction(has_contradiction=False, descriptions=None):
    claims = []
    for desc in (descriptions or []):
        s1 = _source(title="Src1")
        s2 = _source(title="Src2")
        claims.append((s1, s2, desc))
    return ContradictionResult(
        has_contradiction=has_contradiction,
        conflicting_claims=claims,
        agreement_score=0.9 if not has_contradiction else 0.4,
    )


# ── SummaryResult ────────────────────────────────────────────────

class TestSummaryResult:

    def test_defaults(self):
        r = SummaryResult(text="test")
        assert r.method == "llm"
        assert r.citations == []


# ── ResearchSummarizer ──────────────────────────────────────────

class TestResearchSummarizer:

    @pytest.mark.asyncio
    async def test_empty_sources(self):
        s = ResearchSummarizer()
        result = await s.summarize(query="test", sources=[])
        assert "bulunamadı" in result.text
        assert result.method == "fallback"

    @pytest.mark.asyncio
    async def test_llm_success(self):
        mock_client = AsyncMock()
        mock_client.generate.return_value = "LLM özet metni."

        s = ResearchSummarizer(llm_client=mock_client)
        result = await s.summarize(
            query="Python 3.13",
            sources=[_source(title="Py News", snippet="Python 3.13 released")],
        )
        assert result.text == "LLM özet metni."
        assert result.method == "llm"
        assert result.source_count == 1

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self):
        mock_client = AsyncMock()
        mock_client.generate.side_effect = RuntimeError("API down")

        s = ResearchSummarizer(llm_client=mock_client)
        result = await s.summarize(
            query="test",
            sources=[_source(snippet="data here")],
        )
        assert result.method == "fallback"
        assert "data here" in result.text

    @pytest.mark.asyncio
    async def test_citations_built(self):
        s = ResearchSummarizer(llm_client=AsyncMock(generate=AsyncMock(return_value="ok")))
        result = await s.summarize(
            query="q",
            sources=[
                _source(title="A", url="https://a.com", domain="a.com"),
                _source(title="B", url="https://b.com", domain="b.com"),
            ],
        )
        assert len(result.citations) == 2
        assert result.citations[0]["title"] == "A"
        assert result.citations[1]["domain"] == "b.com"

    @pytest.mark.asyncio
    async def test_contradiction_flag(self):
        mock_client = AsyncMock()
        mock_client.generate.return_value = "Çelişkili."

        s = ResearchSummarizer(llm_client=mock_client)
        result = await s.summarize(
            query="q",
            sources=[_source()],
            contradiction=_contradiction(has_contradiction=True, descriptions=["A vs B"]),
        )
        assert result.has_contradictions is True

    @pytest.mark.asyncio
    async def test_fallback_includes_sources(self):
        s = ResearchSummarizer()
        domain = "newsportal.example"
        # No LLM → fallback
        with patch.object(s, "_get_llm_client", side_effect=RuntimeError):
            result = await s.summarize(
                query="q",
                sources=[_source(title="NewsX", snippet="content here", domain=domain)],
            )
        assert result.method == "fallback"
        assert "NewsX" in result.text
        assert domain in result.text

    @pytest.mark.asyncio
    async def test_fallback_contradiction_warning(self):
        s = ResearchSummarizer()
        with patch.object(s, "_get_llm_client", side_effect=RuntimeError):
            result = await s.summarize(
                query="q",
                sources=[_source()],
                contradiction=_contradiction(has_contradiction=True, descriptions=["X vs Y"]),
            )
        assert "çelişkili" in result.text.lower()


# ── build_citations ─────────────────────────────────────────────

class TestBuildCitations:

    def test_ordered(self):
        sources = [
            _source(title="First", url="https://1.com", domain="1.com"),
            _source(title="Second", url="https://2.com", domain="2.com"),
        ]
        cits = ResearchSummarizer._build_citations(sources)
        assert cits[0]["title"] == "First"
        assert cits[1]["title"] == "Second"

    def test_with_date(self):
        dt = datetime(2025, 6, 15)
        cits = ResearchSummarizer._build_citations([_source(date=dt)])
        assert "2025" in cits[0]["date"]


# ── factory ──────────────────────────────────────────────────────

class TestFactory:

    def test_create_default(self):
        s = create_research_summarizer()
        assert isinstance(s, ResearchSummarizer)
        assert s._language == "tr"

    def test_create_english(self):
        s = create_research_summarizer(language="en")
        assert s._language == "en"
