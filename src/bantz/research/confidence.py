"""
Confidence Scorer (Issue #33 - V2-3, enhanced #863).

Calculates confidence scores for research results
based on multiple factors including per-source aging,
cross-reference scoring, and bias detection.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from bantz.research.source_collector import Source
from bantz.research.contradiction import ContradictionResult

logger = logging.getLogger(__name__)


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
    
    Combines 7 weighted factors:
    - Source count
    - Source reliability
    - Per-source recency (date aging per source, not just most-recent)
    - Agreement between sources
    - Topic coverage (content type diversity)
    - Cross-reference (independent sources corroborating claims)
    - Bias detection (domain concentration penalty)
    """
    
    # Factor weights (must sum to 1.0)
    WEIGHTS: dict[str, float] = {
        "source_count": 0.15,
        "source_reliability": 0.20,
        "recency": 0.15,
        "agreement": 0.20,
        "coverage": 0.10,
        "cross_reference": 0.10,
        "bias": 0.10,
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

    # Recency aging brackets (days → per-source score)
    RECENCY_BRACKETS = [
        (7, 1.0),
        (30, 0.8),
        (90, 0.6),
        (365, 0.4),
    ]
    RECENCY_DEFAULT = 0.25  # older than 365 days

    # Bias thresholds
    BIAS_SINGLE_DOMAIN_THRESHOLD = 0.75  # flag if ≥ 75% from one domain
    
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
        
        # Factor 3: Per-source recency (date aging)
        factors["recency"] = self._score_recency(sources)
        
        # Factor 4: Agreement
        factors["agreement"] = self._score_agreement(contradiction)
        
        # Factor 5: Coverage (content type diversity)
        factors["coverage"] = self._score_coverage(sources)

        # Factor 6: Cross-reference (independent corroboration)
        factors["cross_reference"] = self._score_cross_reference(sources)

        # Factor 7: Bias detection (domain concentration)
        factors["bias"] = self._score_bias(sources)
        
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
        Per-source date aging — each source ages independently.

        Every dated source gets a recency score based on how old it is:
        - ≤7 days: 1.0
        - ≤30 days: 0.8
        - ≤90 days: 0.6
        - ≤365 days: 0.4
        - >365 days: 0.25

        The final recency score is the weighted average of all sources,
        where higher-reliability sources count more.  Undated sources
        receive a neutral 0.5.
        """
        if not sources:
            return 0.5

        total_weight = 0.0
        weighted_sum = 0.0

        for src in sources:
            weight = max(src.reliability_score, 0.1)  # floor avoids 0-weight
            if src.date is None:
                src_score = 0.5
            else:
                days_old = (self.reference_date - src.date).days
                if days_old < 0:
                    src_score = 1.0
                else:
                    src_score = self.RECENCY_DEFAULT
                    for bracket_days, bracket_score in self.RECENCY_BRACKETS:
                        if days_old <= bracket_days:
                            src_score = bracket_score
                            break
            weighted_sum += src_score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.5

        return weighted_sum / total_weight
    
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

    def _score_cross_reference(self, sources: list[Source]) -> float:
        """
        Cross-reference scoring — independent sources corroborating claims.

        Sources from *different* domains that share overlapping snippets
        (keyword-level) are more trustworthy.  Score rises with the
        number of distinct corroborating domain pairs.

        - 0 pairs: 0.3
        - 1 pair:  0.6
        - 2 pairs: 0.8
        - 3+ pairs: 1.0
        """
        if len(sources) < 2:
            return 0.3

        # Build keyword sets per source (cheap token overlap)
        def _keywords(text: str) -> set[str]:
            words = text.lower().split()
            # Keep words > 4 chars to filter stopwords
            return {w for w in words if len(w) > 4}

        snippets = [
            (s.domain or s.url, _keywords(s.snippet or ""))
            for s in sources
        ]

        corroborating_pairs = 0
        seen_pairs: set[tuple[str, str]] = set()

        for i in range(len(snippets)):
            for j in range(i + 1, len(snippets)):
                d1, kw1 = snippets[i]
                d2, kw2 = snippets[j]
                # Same domain → not cross-reference
                if d1 == d2:
                    continue
                pair_key = tuple(sorted((d1, d2)))
                if pair_key in seen_pairs:
                    continue
                # Overlap ratio
                if not kw1 or not kw2:
                    continue
                overlap = len(kw1 & kw2) / min(len(kw1), len(kw2))
                if overlap >= 0.15:  # 15% keyword overlap
                    corroborating_pairs += 1
                    seen_pairs.add(pair_key)

        if corroborating_pairs == 0:
            return 0.3
        elif corroborating_pairs == 1:
            return 0.6
        elif corroborating_pairs == 2:
            return 0.8
        else:
            return 1.0

    def _score_bias(self, sources: list[Source]) -> float:
        """
        Bias detection — domain concentration penalty.

        If all or most sources come from the same domain, the
        confidence should be lower since there's no independent
        verification.

        - All from 1 domain: 0.2
        - ≥75% from 1 domain: 0.4
        - ≥50% from 1 domain: 0.6
        - Well-distributed: 1.0
        """
        if not sources:
            return 0.5

        domains = [s.domain or s.url for s in sources]
        total = len(domains)

        if total <= 1:
            return 0.5  # Single source — neutral (count factor handles it)

        counter = Counter(domains)
        most_common_count = counter.most_common(1)[0][1]
        concentration = most_common_count / total

        if concentration >= 1.0:
            return 0.2  # All from one domain
        elif concentration >= self.BIAS_SINGLE_DOMAIN_THRESHOLD:
            return 0.4
        elif concentration >= 0.5:
            return 0.6
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

        # Cross-reference
        xref_score = factors.get("cross_reference", 0)
        if xref_score >= 0.8:
            explanations.append("multiple independent sources corroborate")
        elif xref_score <= 0.3:
            explanations.append("no cross-referencing between sources")

        # Bias
        bias_score = factors.get("bias", 0)
        if bias_score <= 0.4:
            explanations.append("sources are concentrated in few domains")
        elif bias_score >= 0.9:
            explanations.append("sources are well-distributed across domains")
        
        if not explanations:
            return f"Confidence level: {level} ({total_score:.1%})"
        
        main = ". ".join(explanations)
        return f"{main}. Confidence: {level} ({total_score:.1%})"
