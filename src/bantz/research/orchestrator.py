"""
Research Orchestrator (Issue #33 - V2-3).

Orchestrates the full cite-first research pipeline:
1. Collect sources
2. Rank by reliability
3. Detect contradictions
4. Calculate confidence
5. Generate summary
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from bantz.research.source_collector import Source, SourceCollector
from bantz.research.source_ranker import SourceRanker
from bantz.research.contradiction import ContradictionResult, ContradictionDetector
from bantz.research.confidence import ConfidenceResult, ConfidenceScorer
from bantz.core.events import EventBus, EventType


@dataclass
class ResearchResult:
    """
    Complete research result.
    
    Attributes:
        query: Original search query
        sources: Ranked sources used
        summary: Generated summary
        confidence: Confidence scoring result
        contradiction: Contradiction detection result
        duration_ms: Total research duration in milliseconds
    """
    query: str
    sources: list[Source] = field(default_factory=list)
    summary: str = ""
    confidence: Optional[ConfidenceResult] = None
    contradiction: Optional[ContradictionResult] = None
    duration_ms: float = 0.0


class ResearchOrchestrator:
    """
    Orchestrates the full research pipeline.
    
    Combines source collection, ranking, contradiction detection,
    and confidence scoring into a single pipeline.
    """
    
    # Configuration
    MIN_SOURCES: int = 2
    MAX_SOURCES: int = 10
    QUALITY_THRESHOLD: float = 0.3
    
    def __init__(
        self,
        collector: SourceCollector,
        ranker: SourceRanker,
        contradiction_detector: ContradictionDetector,
        confidence_scorer: ConfidenceScorer,
        event_bus: Optional[EventBus] = None,
        summarizer=None
    ):
        """
        Initialize ResearchOrchestrator.
        
        Args:
            collector: Source collector for gathering sources
            ranker: Source ranker for reliability scoring
            contradiction_detector: For finding conflicting claims
            confidence_scorer: For calculating confidence
            event_bus: Optional event bus for publishing events
            summarizer: Optional summarizer for generating summaries
        """
        self.collector = collector
        self.ranker = ranker
        self.contradiction_detector = contradiction_detector
        self.confidence_scorer = confidence_scorer
        self.event_bus = event_bus
        self.summarizer = summarizer
    
    async def research(self, query: str) -> ResearchResult:
        """
        Execute full research pipeline.
        
        Pipeline steps:
        1. Collect sources from search
        2. Rank sources by reliability
        3. Filter low-quality sources
        4. Extract summaries from sources
        5. Detect contradictions
        6. Calculate confidence
        7. Generate final summary
        
        Args:
            query: Research query
        
        Returns:
            ResearchResult with all findings
        """
        start_time = time.time()
        
        # Step 1: Collect sources
        self._emit_event(EventType.PROGRESS, {
            "step": "collecting",
            "message": f"Searching for: {query}"
        })
        
        sources = await self.collector.collect(
            query=query,
            max_sources=self.MAX_SOURCES
        )
        
        self._emit_event(EventType.FOUND, {
            "step": "sources_found",
            "count": len(sources),
            "query": query
        })
        
        # Step 2: Rank sources by reliability
        self._emit_event(EventType.PROGRESS, {
            "step": "ranking",
            "message": "Ranking sources by reliability"
        })
        
        ranked_sources = self.ranker.rank(sources)
        
        # Step 3: Filter low-quality sources
        filtered_sources = self.ranker.filter_low_quality(
            ranked_sources,
            threshold=self.QUALITY_THRESHOLD
        )
        
        # Ensure minimum sources
        if len(filtered_sources) < self.MIN_SOURCES and len(ranked_sources) >= self.MIN_SOURCES:
            # Use top ranked sources if filtering is too aggressive
            filtered_sources = ranked_sources[:self.MIN_SOURCES]
        
        # Step 4: Extract summaries (use snippets for now)
        summaries = [s.snippet for s in filtered_sources if s.snippet]
        
        # Step 5: Detect contradictions
        self._emit_event(EventType.PROGRESS, {
            "step": "analyzing",
            "message": "Analyzing for contradictions"
        })
        
        contradiction = self.contradiction_detector.detect(
            sources=filtered_sources,
            summaries=summaries
        )
        
        # Step 6: Calculate confidence
        confidence = self.confidence_scorer.score(
            sources=filtered_sources,
            contradiction=contradiction
        )
        
        # Step 7: Generate summary
        self._emit_event(EventType.PROGRESS, {
            "step": "summarizing",
            "message": "Generating summary"
        })
        
        summary = await self._generate_summary(
            query=query,
            sources=filtered_sources,
            contradiction=contradiction,
            confidence=confidence
        )
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Create result
        result = ResearchResult(
            query=query,
            sources=filtered_sources,
            summary=summary,
            confidence=confidence,
            contradiction=contradiction,
            duration_ms=duration_ms
        )
        
        # Emit result event
        self._emit_event(EventType.RESULT, {
            "step": "complete",
            "query": query,
            "source_count": len(filtered_sources),
            "confidence_level": confidence.level,
            "has_contradictions": contradiction.has_contradiction,
            "duration_ms": duration_ms
        })
        
        return result
    
    async def _generate_summary(
        self,
        query: str,
        sources: list[Source],
        contradiction: ContradictionResult,
        confidence: ConfidenceResult
    ) -> str:
        """
        Generate research summary.
        
        If a summarizer is provided, uses it.
        Otherwise, generates a basic summary from snippets.
        """
        if self.summarizer:
            # Use provided summarizer
            try:
                return await self.summarizer.summarize(
                    query=query,
                    sources=sources,
                    contradiction=contradiction
                )
            except Exception:
                pass  # Fall through to basic summary
        
        # Basic summary from snippets
        if not sources:
            return f"No reliable sources found for: {query}"
        
        # Combine top snippets
        top_sources = sources[:3]
        snippets = []
        
        for source in top_sources:
            if source.snippet:
                snippets.append(f"• {source.snippet}")
        
        if not snippets:
            return f"Found {len(sources)} sources but no summaries available."
        
        summary_parts = [
            f"Research results for: {query}",
            "",
            "Key findings:",
            *snippets,
        ]
        
        # Add confidence note
        summary_parts.append("")
        summary_parts.append(confidence.explanation)
        
        # Add contradiction warning if needed
        if contradiction.has_contradiction:
            summary_parts.append("")
            summary_parts.append(
                f"⚠️ Note: {len(contradiction.conflicting_claims)} "
                f"conflicting claims detected between sources."
            )
        
        return "\n".join(summary_parts)
    
    def _emit_event(self, event_type: EventType, data: dict) -> None:
        """Emit event to event bus if available."""
        if self.event_bus:
            self.event_bus.publish(
                event_type=event_type.value,
                data=data,
                source="research_orchestrator"
            )


# Factory function for creating orchestrator with defaults
def create_research_orchestrator(
    event_bus: Optional[EventBus] = None,
    search_tool=None
) -> ResearchOrchestrator:
    """
    Create a ResearchOrchestrator with default components.
    
    Args:
        event_bus: Optional event bus for events
        search_tool: Optional search tool for source collection
    
    Returns:
        Configured ResearchOrchestrator
    """
    return ResearchOrchestrator(
        collector=SourceCollector(search_tool=search_tool),
        ranker=SourceRanker(),
        contradiction_detector=ContradictionDetector(),
        confidence_scorer=ConfidenceScorer(),
        event_bus=event_bus
    )
