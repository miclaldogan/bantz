"""
Research Pipeline Module (Issue #33 - V2-3).

Cite-first research pipeline with source collection,
contradiction detection, and confidence scoring.

Components:
- SourceCollector: Collect and extract sources
- SourceRanker: Rank sources by reliability
- ContradictionDetector: Detect conflicting claims
- ConfidenceScorer: Calculate confidence scores
- ResearchOrchestrator: Full pipeline orchestration
"""

from bantz.research.source_collector import (
    Source,
    SourceCollector,
)
from bantz.research.source_ranker import (
    SourceRanker,
)
from bantz.research.contradiction import (
    ContradictionResult,
    ContradictionDetector,
)
from bantz.research.confidence import (
    ConfidenceResult,
    ConfidenceScorer,
)
from bantz.research.orchestrator import (
    ResearchResult,
    ResearchOrchestrator,
)

__all__ = [
    # Source Collection
    "Source",
    "SourceCollector",
    # Ranking
    "SourceRanker",
    # Contradiction Detection
    "ContradictionResult",
    "ContradictionDetector",
    # Confidence Scoring
    "ConfidenceResult",
    "ConfidenceScorer",
    # Orchestration
    "ResearchResult",
    "ResearchOrchestrator",
]
