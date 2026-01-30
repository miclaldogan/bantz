"""
Tests for Research Orchestrator (Issue #33 - V2-3).

Test Scenarios:
- Full pipeline execution
- Events emitted (FOUND, PROGRESS, RESULT)
- Minimum 2 sources target
- Contradiction in result
- Confidence in result
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from bantz.research.source_collector import Source, SourceCollector
from bantz.research.source_ranker import SourceRanker
from bantz.research.contradiction import ContradictionResult, ContradictionDetector
from bantz.research.confidence import ConfidenceResult, ConfidenceScorer
from bantz.research.orchestrator import (
    ResearchResult,
    ResearchOrchestrator,
    create_research_orchestrator,
)
from bantz.core.events import EventBus


class TestResearchResultDataclass:
    """Test ResearchResult dataclass."""
    
    def test_result_required_fields(self):
        """Result has required query field."""
        result = ResearchResult(query="test query")
        assert result.query == "test query"
    
    def test_result_default_empty_sources(self):
        """Sources defaults to empty list."""
        result = ResearchResult(query="test")
        assert result.sources == []
    
    def test_result_with_sources(self):
        """Result can have sources."""
        sources = [
            Source(url="https://a.com", title="A", snippet="Snippet A")
        ]
        result = ResearchResult(query="test", sources=sources)
        assert len(result.sources) == 1
    
    def test_result_with_confidence(self):
        """Result can have confidence."""
        confidence = ConfidenceResult(score=0.8, level="high")
        result = ResearchResult(query="test", confidence=confidence)
        assert result.confidence.level == "high"
    
    def test_result_with_contradiction(self):
        """Result can have contradiction."""
        contradiction = ContradictionResult(has_contradiction=False, agreement_score=1.0)
        result = ResearchResult(query="test", contradiction=contradiction)
        assert result.contradiction.has_contradiction is False
    
    def test_result_duration(self):
        """Result tracks duration."""
        result = ResearchResult(query="test", duration_ms=150.5)
        assert result.duration_ms == 150.5


class TestResearchOrchestratorSetup:
    """Test orchestrator setup."""
    
    def test_orchestrator_creation(self):
        """Orchestrator can be created with components."""
        orchestrator = ResearchOrchestrator(
            collector=SourceCollector(),
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer()
        )
        assert orchestrator is not None
    
    def test_orchestrator_with_event_bus(self):
        """Orchestrator accepts event bus."""
        event_bus = EventBus()
        orchestrator = ResearchOrchestrator(
            collector=SourceCollector(),
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer(),
            event_bus=event_bus
        )
        assert orchestrator.event_bus is event_bus


class TestResearchOrchestratorPipeline:
    """Test full pipeline execution."""
    
    @pytest.fixture
    def mock_collector(self):
        """Create mock collector with sample sources."""
        collector = MagicMock(spec=SourceCollector)
        collector.collect = AsyncMock(return_value=[
            Source(
                url="https://reuters.com/article",
                title="Reuters Article",
                snippet="This is a test snippet from Reuters.",
                reliability_score=0.95
            ),
            Source(
                url="https://bbc.com/news",
                title="BBC News",
                snippet="BBC reports similar findings.",
                reliability_score=0.90
            ),
        ])
        return collector
    
    @pytest.fixture
    def orchestrator(self, mock_collector):
        """Create orchestrator with mock collector."""
        return ResearchOrchestrator(
            collector=mock_collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer()
        )
    
    @pytest.mark.asyncio
    async def test_pipeline_returns_result(self, orchestrator):
        """Pipeline returns ResearchResult."""
        result = await orchestrator.research("test query")
        assert isinstance(result, ResearchResult)
    
    @pytest.mark.asyncio
    async def test_pipeline_has_query(self, orchestrator):
        """Result contains original query."""
        result = await orchestrator.research("test query")
        assert result.query == "test query"
    
    @pytest.mark.asyncio
    async def test_pipeline_has_sources(self, orchestrator):
        """Result contains sources."""
        result = await orchestrator.research("test query")
        assert len(result.sources) > 0
    
    @pytest.mark.asyncio
    async def test_pipeline_has_confidence(self, orchestrator):
        """Result contains confidence."""
        result = await orchestrator.research("test query")
        assert result.confidence is not None
        assert hasattr(result.confidence, "score")
        assert hasattr(result.confidence, "level")
    
    @pytest.mark.asyncio
    async def test_pipeline_has_contradiction(self, orchestrator):
        """Result contains contradiction info."""
        result = await orchestrator.research("test query")
        assert result.contradiction is not None
        assert hasattr(result.contradiction, "has_contradiction")
    
    @pytest.mark.asyncio
    async def test_pipeline_has_summary(self, orchestrator):
        """Result contains summary."""
        result = await orchestrator.research("test query")
        assert result.summary != ""
    
    @pytest.mark.asyncio
    async def test_pipeline_tracks_duration(self, orchestrator):
        """Result tracks execution duration."""
        result = await orchestrator.research("test query")
        assert result.duration_ms > 0


class TestResearchOrchestratorEvents:
    """Test event emission."""
    
    @pytest.fixture
    def mock_collector(self):
        """Create mock collector."""
        collector = MagicMock(spec=SourceCollector)
        collector.collect = AsyncMock(return_value=[
            Source(url="https://a.com", title="A", snippet="Test", reliability_score=0.8)
        ])
        return collector
    
    @pytest.mark.asyncio
    async def test_emits_found_event(self, mock_collector):
        """Pipeline emits FOUND event."""
        event_bus = EventBus()
        events = []
        
        def capture_event(event):
            events.append(event)
        
        event_bus.subscribe("found", capture_event)
        
        orchestrator = ResearchOrchestrator(
            collector=mock_collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer(),
            event_bus=event_bus
        )
        
        await orchestrator.research("test")
        
        found_events = [e for e in events if e.event_type == "found"]
        assert len(found_events) >= 1
    
    @pytest.mark.asyncio
    async def test_emits_progress_events(self, mock_collector):
        """Pipeline emits PROGRESS events."""
        event_bus = EventBus()
        events = []
        
        def capture_event(event):
            events.append(event)
        
        event_bus.subscribe("progress", capture_event)
        
        orchestrator = ResearchOrchestrator(
            collector=mock_collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer(),
            event_bus=event_bus
        )
        
        await orchestrator.research("test")
        
        progress_events = [e for e in events if e.event_type == "progress"]
        assert len(progress_events) >= 1
    
    @pytest.mark.asyncio
    async def test_emits_result_event(self, mock_collector):
        """Pipeline emits RESULT event."""
        event_bus = EventBus()
        events = []
        
        def capture_event(event):
            events.append(event)
        
        event_bus.subscribe("result", capture_event)
        
        orchestrator = ResearchOrchestrator(
            collector=mock_collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer(),
            event_bus=event_bus
        )
        
        await orchestrator.research("test")
        
        result_events = [e for e in events if e.event_type == "result"]
        assert len(result_events) >= 1


class TestResearchOrchestratorMinSources:
    """Test minimum sources behavior."""
    
    @pytest.mark.asyncio
    async def test_min_sources_target(self):
        """Orchestrator targets minimum 2 sources."""
        collector = MagicMock(spec=SourceCollector)
        collector.collect = AsyncMock(return_value=[
            Source(url="https://a.com", title="A", snippet="Test", reliability_score=0.1),
            Source(url="https://b.com", title="B", snippet="Test", reliability_score=0.1),
            Source(url="https://c.com", title="C", snippet="Test", reliability_score=0.9),
        ])
        
        orchestrator = ResearchOrchestrator(
            collector=collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer()
        )
        
        result = await orchestrator.research("test")
        
        # Should have at least MIN_SOURCES even after filtering
        assert len(result.sources) >= orchestrator.MIN_SOURCES


class TestResearchOrchestratorContradictionInResult:
    """Test contradiction detection integration."""
    
    @pytest.mark.asyncio
    async def test_contradiction_in_result(self):
        """Contradiction is included in result."""
        collector = MagicMock(spec=SourceCollector)
        collector.collect = AsyncMock(return_value=[
            Source(
                url="https://a.com",
                title="A",
                snippet="The company confirmed the merger.",
                reliability_score=0.8
            ),
            Source(
                url="https://b.com",
                title="B",
                snippet="The company denied the merger.",
                reliability_score=0.8
            ),
        ])
        
        orchestrator = ResearchOrchestrator(
            collector=collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer()
        )
        
        result = await orchestrator.research("merger news")
        
        # Contradiction should be detected
        assert result.contradiction is not None
        # Note: actual detection depends on snippet analysis


class TestResearchOrchestratorConfidenceInResult:
    """Test confidence scoring integration."""
    
    @pytest.mark.asyncio
    async def test_confidence_in_result(self):
        """Confidence is included in result."""
        collector = MagicMock(spec=SourceCollector)
        collector.collect = AsyncMock(return_value=[
            Source(
                url="https://reuters.com/article",
                title="Reuters",
                snippet="High quality source.",
                reliability_score=0.95
            ),
            Source(
                url="https://bbc.com/news",
                title="BBC",
                snippet="Another quality source.",
                reliability_score=0.90
            ),
        ])
        
        orchestrator = ResearchOrchestrator(
            collector=collector,
            ranker=SourceRanker(),
            contradiction_detector=ContradictionDetector(),
            confidence_scorer=ConfidenceScorer()
        )
        
        result = await orchestrator.research("test query")
        
        assert result.confidence is not None
        assert result.confidence.score >= 0.0
        assert result.confidence.score <= 1.0
        assert result.confidence.level in ["low", "medium", "high"]


class TestCreateResearchOrchestrator:
    """Test factory function."""
    
    def test_creates_orchestrator(self):
        """Factory creates orchestrator."""
        orchestrator = create_research_orchestrator()
        assert isinstance(orchestrator, ResearchOrchestrator)
    
    def test_creates_with_event_bus(self):
        """Factory accepts event bus."""
        event_bus = EventBus()
        orchestrator = create_research_orchestrator(event_bus=event_bus)
        assert orchestrator.event_bus is event_bus
    
    def test_creates_with_all_components(self):
        """Factory creates all required components."""
        orchestrator = create_research_orchestrator()
        assert orchestrator.collector is not None
        assert orchestrator.ranker is not None
        assert orchestrator.contradiction_detector is not None
        assert orchestrator.confidence_scorer is not None
