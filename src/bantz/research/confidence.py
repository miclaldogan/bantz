"""
Confidence Scorer (Issue #33 - V2-3).

Calculates confidence scores for research results
based on multiple factors.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from bantz.research.source_collector import Source
from bantz.research.contradiction import ContradictionResult


@dataclass
class ConfidenceResult:
    """
    Result of confidence scoring.
    
    Attributes:
        score: Overall confidence score (0.0 - 1.0)
        level: Confidence level ("low", "medium", "high")
        factors: Individual factor contributions
        explanation: Human-readable explanation
    """
    score: float
    level: str  # "low", "medium", "high"
    factors: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


class ConfidenceScorer:
    """
    Calculates confidence scores for research results.
    
    Combines multiple factors:
    - Source count
    - Source reliability
    - Recency
    - Agreement between sources
    - Topic coverage
    """
    
    # Factor weights (must sum to 1.0)
    WEIGHTS: dict[str, float] = {
        "source_count": 0.20,      # More sources = higher confidence
        "source_reliability": 0.25, # Higher reliability = higher confidence
        "recency": 0.15,           # More recent = higher confidence
        "agreement": 0.25,         # More agreement = higher confidence
        "coverage": 0.15,          # Better coverage = higher confidence
    }
    
    # Confidence level thresholds
    LEVEL_THRESHOLDS = {
        "low": 0.4,     # score < 0.4
        "medium": 0.7,  # 0.4 <= score < 0.7
        "high": 1.0,    # score >= 0.7
    }
    
    # Source count scoring
    MIN_SOURCES_FOR_CONFIDENCE = 2
    OPTIMAL_SOURCE_COUNT = 5
    
    def __init__(self, reference_date: Optional[datetime] = None):
        """
        Initialize ConfidenceScorer.
        
        Args:
            reference_date: Date to use for recency calculations.
                           Defaults to now.
        """
        self.reference_date = reference_date or datetime.now()
    
    def score(
        self,
        sources: list[Source],
        contradiction: ContradictionResult
    ) -> ConfidenceResult:
        """
        Calculate confidence score for research results.
        
        Args:
            sources: List of sources used
            contradiction: Contradiction detection result
        
        Returns:
            ConfidenceResult with overall score and breakdown
        """
        factors: dict[str, float] = {}
        
        # Factor 1: Source count
        factors["source_count"] = self._score_source_count(sources)
        
        # Factor 2: Source reliability
        factors["source_reliability"] = self._score_source_reliability(sources)
        
        # Factor 3: Recency
        factors["recency"] = self._score_recency(sources)
        
        # Factor 4: Agreement
        factors["agreement"] = self._score_agreement(contradiction)
        
        # Factor 5: Coverage (based on content type diversity)
        factors["coverage"] = self._score_coverage(sources)
        
        # Calculate weighted score
        total_score = sum(
            factors[key] * self.WEIGHTS[key]
            for key in self.WEIGHTS
        )
        
        # Clamp to 0.0 - 1.0
        total_score = max(0.0, min(1.0, total_score))
        
        # Determine level
        level = self._determine_level(total_score)
        
        # Generate explanation
        explanation = self._generate_explanation(factors, total_score, level)
        
        return ConfidenceResult(
            score=total_score,
            level=level,
            factors=factors,
            explanation=explanation
        )
    
    def _score_source_count(self, sources: list[Source]) -> float:
        """
        Score based on number of sources.
        
        - 0 sources: 0.0
        - 1 source: 0.3 (single source penalty)
        - 2-5 sources: Linear scale to 1.0
        - 5+ sources: 1.0 (optimal)
        """
        count = len(sources)
        
        if count == 0:
            return 0.0
        elif count == 1:
            return 0.3  # Single source penalty
        elif count >= self.OPTIMAL_SOURCE_COUNT:
            return 1.0
        else:
            # Linear scale from 2 to OPTIMAL
            return 0.3 + 0.7 * (count - 1) / (self.OPTIMAL_SOURCE_COUNT - 1)
    
    def _score_source_reliability(self, sources: list[Source]) -> float:
        """
        Score based on average source reliability.
        
        Returns weighted average of reliability scores,
        with higher-reliability sources weighted more.
        """
        if not sources:
            return 0.0
        
        # Use reliability scores from sources
        scores = [s.reliability_score for s in sources if s.reliability_score > 0]
        
        if not scores:
            return 0.5  # Default if no scores available
        
        # Weighted average favoring higher scores
        total = sum(scores)
        count = len(scores)
        
        # Simple average
        avg = total / count
        
        # Boost for having multiple reliable sources
        if count >= 3 and avg >= 0.7:
            avg = min(1.0, avg * 1.1)
        
        return avg
    
    def _score_recency(self, sources: list[Source]) -> float:
        """
        Score based on source recency.
        
        - Sources within 7 days: 1.0
        - Sources within 30 days: 0.7
        - Sources within 90 days: 0.5
        - Older sources: 0.3
        - No dates: 0.5 (neutral)
        """
        if not sources:
            return 0.5
        
        dated_sources = [s for s in sources if s.date is not None]
        
        if not dated_sources:
            return 0.5  # No date info available
        
        # Find most recent source
        most_recent = max(dated_sources, key=lambda s: s.date)
        delta = self.reference_date - most_recent.date
        days_old = delta.days
        
        if days_old < 0:
            return 1.0  # Future date (unusual but handle it)
        elif days_old <= 7:
            return 1.0
        elif days_old <= 30:
            return 0.7
        elif days_old <= 90:
            return 0.5
        else:
            return 0.3
    
    def _score_agreement(self, contradiction: ContradictionResult) -> float:
        """
        Score based on source agreement.
        
        Uses agreement_score from ContradictionResult.
        Penalty for contradictions.
        """
        # Direct mapping from agreement score
        base_score = contradiction.agreement_score
        
        # Additional penalty for having contradictions
        if contradiction.has_contradiction:
            penalty = len(contradiction.conflicting_claims) * 0.1
            base_score = max(0.0, base_score - penalty)
        
        return base_score
    
    def _score_coverage(self, sources: list[Source]) -> float:
        """
        Score based on content type diversity.
        
        Higher score for diverse source types (news, academic, etc.)
        """
        if not sources:
            return 0.0
        
        # Count unique content types
        content_types = set(s.content_type for s in sources)
        
        # Score based on diversity
        type_count = len(content_types)
        
        if type_count == 1:
            return 0.5
        elif type_count == 2:
            return 0.7
        elif type_count == 3:
            return 0.9
        else:
            return 1.0
    
    def _determine_level(self, score: float) -> str:
        """Determine confidence level from score."""
        if score < self.LEVEL_THRESHOLDS["low"]:
            return "low"
        elif score < self.LEVEL_THRESHOLDS["medium"]:
            return "medium"
        else:
            return "high"
    
    def _generate_explanation(
        self,
        factors: dict[str, float],
        total_score: float,
        level: str
    ) -> str:
        """Generate human-readable explanation."""
        explanations = []
        
        # Source count
        count_score = factors.get("source_count", 0)
        if count_score < 0.4:
            explanations.append("Limited sources found")
        elif count_score >= 0.8:
            explanations.append("Multiple sources confirm")
        
        # Reliability
        rel_score = factors.get("source_reliability", 0)
        if rel_score < 0.5:
            explanations.append("source quality is mixed")
        elif rel_score >= 0.8:
            explanations.append("sources are highly reliable")
        
        # Agreement
        agree_score = factors.get("agreement", 0)
        if agree_score < 0.5:
            explanations.append("sources show conflicting information")
        elif agree_score >= 0.8:
            explanations.append("sources are in agreement")
        
        # Recency
        rec_score = factors.get("recency", 0)
        if rec_score < 0.5:
            explanations.append("information may be outdated")
        elif rec_score >= 0.8:
            explanations.append("information is recent")
        
        if not explanations:
            return f"Confidence level: {level} ({total_score:.1%})"
        
        main = ". ".join(explanations)
        return f"{main}. Confidence: {level} ({total_score:.1%})"
