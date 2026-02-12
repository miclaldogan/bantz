"""LLM-based research summarizer.

Replaces the fallback concatenation in ResearchOrchestrator with a real
multi-source synthesis pipeline:

- Accepts ranked sources + contradiction data
- Builds a structured prompt for quality-tier LLM (Gemini)
- Preserves source citations ([1], [2], …)
- Detects and flags conflicting claims
- Falls back to snippet concatenation when LLM is unavailable
"""

from __future__ import annotations

import logging
import os
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bantz.research.source_collector import Source
from bantz.research.contradiction import ContradictionResult

logger = logging.getLogger(__name__)

# Max source text per source to avoid token overflow
MAX_SOURCE_CHARS = 1500
# Max total chars from all sources combined
MAX_TOTAL_SOURCE_CHARS = 8000


@dataclass
class SummaryRequest:
    """Input to the summarizer."""

    query: str
    sources: List[Source]
    contradiction: Optional[ContradictionResult] = None
    language: str = "tr"  # Turkish by default
    max_words: int = 300


@dataclass
class SummaryResult:
    """Output from the summarizer."""

    text: str
    citations: List[Dict[str, str]] = field(default_factory=list)
    method: str = "llm"  # "llm" | "fallback"
    source_count: int = 0
    has_contradictions: bool = False


class ResearchSummarizer:
    """LLM-powered research summarizer with citation preservation.

    Example::

        summarizer = ResearchSummarizer()
        result = await summarizer.summarize(
            query="Python 3.13 yenilikleri",
            sources=ranked_sources,
            contradiction=contradiction_result,
        )
        print(result.text)
    """

    # System prompt template
    SYSTEM_PROMPT = textwrap.dedent("""\
        Sen bir araştırma asistanısın. Verilen kaynaklardan kapsamlı bir özet çıkar.

        Kurallar:
        1. Her bilginin kaynağını [1], [2] gibi numaralarla belirt.
        2. Kaynaklar arasında çelişki varsa açıkça belirt.
        3. En güvenilir kaynaklara öncelik ver.
        4. Özet {language} dilinde olsun.
        5. Maksimum {max_words} kelime.
        6. Nesnel ve bilgilendirici ol, yorum katma.
    """)

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        model: Optional[str] = None,
        language: str = "tr",
    ):
        """
        Args:
            llm_client: LLM client for summarization. If None, uses Gemini via env.
            model: Model name override.
            language: Output language (default: Turkish).
        """
        self._llm_client = llm_client
        self._model = model or os.getenv("BANTZ_GEMINI_MODEL", "gemini-2.0-flash")
        self._language = language

    async def summarize(
        self,
        query: str,
        sources: List[Source],
        contradiction: Optional[ContradictionResult] = None,
        max_words: int = 300,
    ) -> SummaryResult:
        """Generate a multi-source summary with citations.

        Args:
            query: Original research query.
            sources: Ranked sources to summarize.
            contradiction: Contradiction detection result.
            max_words: Maximum output words.

        Returns:
            SummaryResult with text and citation metadata.
        """
        if not sources:
            return SummaryResult(
                text=f"'{query}' için güvenilir kaynak bulunamadı.",
                method="fallback",
            )

        # Build citation index
        citations = self._build_citations(sources)

        # Try LLM summarization
        try:
            text = await self._llm_summarize(
                query=query,
                sources=sources,
                contradiction=contradiction,
                citations=citations,
                max_words=max_words,
            )
            return SummaryResult(
                text=text,
                citations=citations,
                method="llm",
                source_count=len(sources),
                has_contradictions=bool(
                    contradiction and contradiction.has_contradiction
                ),
            )
        except Exception as exc:
            logger.warning("LLM summarization failed, using fallback: %s", exc)

        # Fallback: structured snippet concatenation
        text = self._fallback_summarize(query, sources, contradiction, citations)
        return SummaryResult(
            text=text,
            citations=citations,
            method="fallback",
            source_count=len(sources),
            has_contradictions=bool(
                contradiction and contradiction.has_contradiction
            ),
        )

    async def _llm_summarize(
        self,
        query: str,
        sources: List[Source],
        contradiction: Optional[ContradictionResult],
        citations: List[Dict[str, str]],
        max_words: int,
    ) -> str:
        """Call the LLM to generate a summary."""
        system = self.SYSTEM_PROMPT.format(
            language="Türkçe" if self._language == "tr" else "English",
            max_words=max_words,
        )

        # Build source context
        source_parts: List[str] = []
        total_chars = 0
        for i, src in enumerate(sources, 1):
            snippet = (src.snippet or "")[:MAX_SOURCE_CHARS]
            if total_chars + len(snippet) > MAX_TOTAL_SOURCE_CHARS:
                break
            total_chars += len(snippet)
            source_parts.append(
                f"[{i}] {src.title or src.url}\n"
                f"   Kaynak: {src.domain or src.url}\n"
                f"   İçerik: {snippet}"
            )

        # Add contradiction info if present
        contradiction_note = ""
        if contradiction and contradiction.has_contradiction:
            claims = contradiction.conflicting_claims[:3]
            contradiction_note = (
                "\n\n⚠️ Çelişkili bilgiler tespit edildi:\n"
                + "\n".join(f"- {c}" for c in claims)
            )

        user_prompt = (
            f"Araştırma sorusu: {query}\n\n"
            f"Kaynaklar:\n{''.join(source_parts)}"
            f"{contradiction_note}\n\n"
            f"Yukarıdaki kaynaklara dayanarak kapsamlı bir özet yaz."
        )

        # Call LLM
        client = self._get_llm_client()
        response = await client.generate(
            prompt=user_prompt,
            system=system,
            model=self._model,
        )

        return response.strip()

    def _get_llm_client(self):
        """Get or create an LLM client."""
        if self._llm_client is not None:
            return self._llm_client

        # Try to get Gemini client from Bantz infra
        try:
            from bantz.brain.gemini_client import get_gemini_client

            self._llm_client = get_gemini_client()
            return self._llm_client
        except ImportError:
            pass

        raise RuntimeError(
            "No LLM client available. Set GEMINI_API_KEY or provide llm_client."
        )

    def _fallback_summarize(
        self,
        query: str,
        sources: List[Source],
        contradiction: Optional[ContradictionResult],
        citations: List[Dict[str, str]],
    ) -> str:
        """Structured fallback when LLM is unavailable."""
        parts = [f"Araştırma: {query}\n"]

        # Key findings with citations
        parts.append("Bulgular:")
        for i, src in enumerate(sources[:5], 1):
            if src.snippet:
                parts.append(f"  [{i}] {src.snippet}")

        # Contradiction warning
        if contradiction and contradiction.has_contradiction:
            parts.append(
                f"\n⚠️ {len(contradiction.conflicting_claims)} çelişkili bilgi tespit edildi."
            )

        # Source list
        parts.append("\nKaynaklar:")
        for i, c in enumerate(citations[:5], 1):
            parts.append(f"  [{i}] {c['title']} — {c['domain']}")

        return "\n".join(parts)

    @staticmethod
    def _build_citations(sources: List[Source]) -> List[Dict[str, str]]:
        """Build citation metadata from sources."""
        citations = []
        for src in sources:
            citations.append(
                {
                    "url": src.url,
                    "title": src.title or src.url,
                    "domain": src.domain or "",
                    "date": str(src.date) if src.date else "",
                }
            )
        return citations


def create_research_summarizer(
    llm_client: Optional[Any] = None,
    language: str = "tr",
) -> ResearchSummarizer:
    """Factory for creating a ResearchSummarizer."""
    return ResearchSummarizer(llm_client=llm_client, language=language)
