"""
Tests for Confidence Scorer (Issue #33 - V2-3).

Test Scenarios:
- High confidence with multiple reliable sources
- Low confidence with single source
- Confidence reduced by contradictions
- Factor weights sum correctly
- Level thresholds: <0.4 low, 0.4-0.7 medium, >0.7 high
"""

import pytest
from datetime import datetime, timedelta

from bantz.research.source_collector import Source
from bantz.research.contradiction import ContradictionResult
from bantz.research.confidence import (
    ConfidenceResult,
    ConfidenceScorer,
)


class TestConfidenceResultDataclass:
    """Test ConfidenceResult dataclass."""
    
    def test_result_required_fields(self):
        """Result has required fields."""
        result = ConfidenceResult(
            score=0.75,
            level="high",
            factors={"source_count": 0.8},
            explanation="Test explanation"
        )
        assert result.score == 0.75
        assert result.level == "high"
        assert "source_count" in result.factors
        assert result.explanation == "Test explanation"
    
    def test_result_level_values(self):
        """Level can be low, medium, or high."""
        for level in ["low", "medium", "high"]:
            result = ConfidenceResult(score=0.5, level=level)
            assert result.level == level
    
    def test_result_factors_default(self):
        """Factors defaults to empty dict."""
        result = ConfidenceResult(score=0.5, level="medium")
        assert result.factors == {}


class TestConfidenceScorerWeights:
    """Test weight configuration."""
    
    def test_weights_sum_to_one(self):
        """Factor weights should sum to 1.0."""
        total = sum(ConfidenceScorer.WEIGHTS.values())
        assert abs(total - 1.0) < 0.001
    
    def test_all_weights_positive(self):
        """All weights should be positive."""
        for weight in ConfidenceScorer.WEIGHTS.values():
            assert weight > 0
    
    def test_expected_factors_present(self):
        """Expected factors are in weights."""
        expected = ["source_count", "source_reliability", "recency", "agreement", "coverage"]
        for factor in expected:
            assert factor in ConfidenceScorer.WEIGHTS


class TestConfidenceScorerLevels:
    """Test confidence level determination."""
    
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer()
    
    def test_level_low_threshold(self, scorer):
        """Score < 0.4 is low."""
        level = scorer._determine_level(0.3)
        assert level == "low"
    
    def test_level_medium_threshold(self, scorer):
        """Score 0.4-0.7 is medium."""
        level = scorer._determine_level(0.5)
        assert level == "medium"
    
    def test_level_high_threshold(self, scorer):
        """Score >= 0.7 is high."""
        level = scorer._determine_level(0.8)
        assert level == "high"
    
    def test_level_boundary_low_medium(self, scorer):
        """Boundary at 0.4."""
        assert scorer._determine_level(0.39) == "low"
        assert scorer._determine_level(0.40) == "medium"
    
    def test_level_boundary_medium_high(self, scorer):
        """Boundary at 0.7."""
        assert scorer._determine_level(0.69) == "medium"
        assert scorer._determine_level(0.70) == "high"


class TestConfidenceScorerSourceCount:
    """Test source count scoring."""
    
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer()
    
    def test_no_sources_zero_score(self, scorer):
        """Zero sources gives zero score."""
        score = scorer._score_source_count([])
        assert score == 0.0
    
    def test_single_source_low_score(self, scorer):
        """Single source gives low score (0.3)."""
        sources = [Source(url="https://a.com", title="A", snippet="")]
        score = scorer._score_source_count(sources)
        assert score == 0.3
    
    def test_optimal_sources_full_score(self, scorer):
        """Optimal source count gives full score."""
        sources = [
            Source(url=f"https://s{i}.com", title=f"S{i}", snippet="")
            for i in range(scorer.OPTIMAL_SOURCE_COUNT)
        ]
        score = scorer._score_source_count(sources)
        assert score == 1.0
    
    def test_sources_linear_scaling(self, scorer):
        """Score scales linearly between 1 and optimal."""
        sources_2 = [
            Source(url=f"https://s{i}.com", title=f"S{i}", snippet="")
            for i in range(2)
        ]
        sources_3 = [
            Source(url=f"https://s{i}.com", title=f"S{i}", snippet="")
            for i in range(3)
        ]
        
        score_2 = scorer._score_source_count(sources_2)
        score_3 = scorer._score_source_count(sources_3)
        
        assert score_3 > score_2


class TestConfidenceScorerAgreement:
    """Test agreement scoring."""
    
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer()
    
    def test_full_agreement_full_score(self, scorer):
        """Full agreement gives full score."""
        contradiction = ContradictionResult(
            has_contradiction=False,
            agreement_score=1.0
        )
        score = scorer._score_agreement(contradiction)
        assert score == 1.0
    
    def test_contradiction_reduces_score(self, scorer):
        """Contradiction reduces agreement score."""
        source1 = Source(url="https://a.com", title="A", snippet="")
        source2 = Source(url="https://b.com", title="B", snippet="")
        
        contradiction = ContradictionResult(
            has_contradiction=True,
            conflicting_claims=[(source1, source2, "conflict")],
            agreement_score=0.7
        )
        score = scorer._score_agreement(contradiction)
        
        # Should be less than agreement_score due to penalty
        assert score < 0.7
    
    def test_multiple_contradictions_more_penalty(self, scorer):
        """Multiple contradictions reduce score more."""
        source1 = Source(url="https://a.com", title="A", snippet="")
        source2 = Source(url="https://b.com", title="B", snippet="")
        
        single = ContradictionResult(
            has_contradiction=True,
            conflicting_claims=[(source1, source2, "conflict")],
            agreement_score=0.8
        )
        
        multiple = ContradictionResult(
            has_contradiction=True,
            conflicting_claims=[
                (source1, source2, "conflict1"),
                (source1, source2, "conflict2"),
                (source1, source2, "conflict3"),
            ],
            agreement_score=0.8
        )
        
        score_single = scorer._score_agreement(single)
        score_multiple = scorer._score_agreement(multiple)
        
        assert score_multiple < score_single


class TestConfidenceScorerRecency:
    """Test recency scoring."""
    
    def test_recent_sources_high_score(self):
        """Sources within 7 days get high score."""
        reference = datetime(2024, 1, 15)
        scorer = ConfidenceScorer(reference_date=reference)
        
        sources = [
            Source(
                url="https://a.com",
                title="A",
                snippet="",
                date=datetime(2024, 1, 14)  # 1 day ago
            )
        ]
        score = scorer._score_recency(sources)
        assert score == 1.0
    
    def test_month_old_sources_medium_score(self):
        """Sources within 30 days get medium score."""
        reference = datetime(2024, 1, 30)
        scorer = ConfidenceScorer(reference_date=reference)
        
        sources = [
            Source(
                url="https://a.com",
                title="A",
                snippet="",
                date=datetime(2024, 1, 10)  # ~20 days ago
            )
        ]
        score = scorer._score_recency(sources)
        assert score == 0.7
    
    def test_old_sources_low_score(self):
        """Sources over 90 days get low score."""
        reference = datetime(2024, 6, 1)
        scorer = ConfidenceScorer(reference_date=reference)
        
        sources = [
            Source(
                url="https://a.com",
                title="A",
                snippet="",
                date=datetime(2024, 1, 1)  # ~150 days ago
            )
        ]
        score = scorer._score_recency(sources)
        assert score == 0.3
    
    def test_no_dated_sources_neutral(self):
        """Sources without dates get neutral score."""
        scorer = ConfidenceScorer()
        
        sources = [
            Source(url="https://a.com", title="A", snippet="")
        ]
        score = scorer._score_recency(sources)
        assert score == 0.5


class TestConfidenceScorerFullScore:
    """Test full scoring method."""
    
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer(reference_date=datetime(2024, 1, 15))
    
    def test_high_confidence_reliable_sources(self, scorer):
        """Multiple reliable sources give high confidence."""
        sources = [
            Source(
                url="https://reuters.com/article",
                title="Reuters",
                snippet="",
                reliability_score=0.95,
                date=datetime(2024, 1, 14)
            ),
            Source(
                url="https://bbc.com/news",
                title="BBC",
                snippet="",
                reliability_score=0.90,
                date=datetime(2024, 1, 14)
            ),
            Source(
                url="https://nytimes.com/article",
                title="NYT",
                snippet="",
                reliability_score=0.90,
                date=datetime(2024, 1, 13),
                content_type="news"
            ),
        ]
        
        contradiction = ContradictionResult(
            has_contradiction=False,
            agreement_score=1.0
        )
        
        result = scorer.score(sources, contradiction)
        
        assert result.level == "high"
        assert result.score >= 0.7
    
    def test_low_confidence_single_source(self, scorer):
        """Single source gives low confidence."""
        sources = [
            Source(
                url="https://randomblog.com",
                title="Blog",
                snippet="",
                reliability_score=0.5
            )
        ]
        
        contradiction = ContradictionResult(
            has_contradiction=False,
            agreement_score=1.0
        )
        
        result = scorer.score(sources, contradiction)
        
        # Single low-reliability source should have low confidence
        assert result.score < 0.7
    
    def test_confidence_reduced_by_contradiction(self, scorer):
        """Contradiction reduces confidence."""
        sources = [
            Source(
                url="https://reuters.com/a",
                title="Reuters A",
                snippet="",
                reliability_score=0.95,
                date=datetime(2024, 1, 14)
            ),
            Source(
                url="https://bbc.com/b",
                title="BBC B",
                snippet="",
                reliability_score=0.90,
                date=datetime(2024, 1, 14)
            ),
        ]
        
        # With contradiction
        with_contradiction = ContradictionResult(
            has_contradiction=True,
            conflicting_claims=[(sources[0], sources[1], "conflict")],
            agreement_score=0.5
        )
        
        # Without contradiction
        without_contradiction = ContradictionResult(
            has_contradiction=False,
            agreement_score=1.0
        )
        
        score_with = scorer.score(sources, with_contradiction)
        score_without = scorer.score(sources, without_contradiction)
        
        assert score_with.score < score_without.score
    
    def test_factors_all_present(self, scorer):
        """All expected factors are in result."""
        sources = [
            Source(url="https://a.com", title="A", snippet="", reliability_score=0.7)
        ]
        contradiction = ContradictionResult(has_contradiction=False, agreement_score=1.0)
        
        result = scorer.score(sources, contradiction)
        
        for factor in ConfidenceScorer.WEIGHTS:
            assert factor in result.factors
    
    def test_explanation_generated(self, scorer):
        """Explanation is generated."""
        sources = [
            Source(url="https://a.com", title="A", snippet="", reliability_score=0.9)
        ]
        contradiction = ContradictionResult(has_contradiction=False, agreement_score=1.0)
        
        result = scorer.score(sources, contradiction)
        
        assert result.explanation != ""
        assert len(result.explanation) > 10
