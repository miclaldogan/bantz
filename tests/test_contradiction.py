"""
Tests for Contradiction Detector (Issue #33 - V2-3).

Test Scenarios:
- No contradiction when sources agree
- Contradiction detected when conflicting
- Conflicting source pairs are listed
- Agreement score in 0-1 range
- Key claims extraction
"""

import pytest

from bantz.research.source_collector import Source
from bantz.research.contradiction import (
    ContradictionResult,
    ContradictionDetector,
)


class TestContradictionResultDataclass:
    """Test ContradictionResult dataclass."""
    
    def test_result_no_contradiction(self):
        """Result with no contradiction."""
        result = ContradictionResult(
            has_contradiction=False,
            conflicting_claims=[],
            agreement_score=1.0
        )
        assert result.has_contradiction is False
        assert result.agreement_score == 1.0
        assert len(result.conflicting_claims) == 0
    
    def test_result_with_contradiction(self):
        """Result with contradiction."""
        source1 = Source(url="https://a.com", title="A", snippet="")
        source2 = Source(url="https://b.com", title="B", snippet="")
        
        result = ContradictionResult(
            has_contradiction=True,
            conflicting_claims=[(source1, source2, "claim vs claim")],
            agreement_score=0.5
        )
        assert result.has_contradiction is True
        assert len(result.conflicting_claims) == 1
    
    def test_result_agreement_score_range(self):
        """Agreement score should be 0.0 to 1.0."""
        result = ContradictionResult(
            has_contradiction=False,
            agreement_score=0.75
        )
        assert 0.0 <= result.agreement_score <= 1.0


class TestContradictionDetectorCompareClaims:
    """Test claim comparison."""
    
    @pytest.fixture
    def detector(self):
        return ContradictionDetector()
    
    def test_compare_identical_claims(self, detector):
        """Identical claims have high similarity."""
        claim = "The temperature is 20 degrees"
        similarity = detector.compare_claims(claim, claim)
        assert similarity == 1.0
    
    def test_compare_similar_claims(self, detector):
        """Similar claims have moderate similarity."""
        claim1 = "The temperature increased to 20 degrees"
        claim2 = "The temperature rose to 20 degrees"
        similarity = detector.compare_claims(claim1, claim2)
        assert similarity > 0.3
    
    def test_compare_different_claims(self, detector):
        """Different claims have low similarity."""
        claim1 = "The economy is growing"
        claim2 = "The weather is sunny today"
        similarity = detector.compare_claims(claim1, claim2)
        assert similarity < 0.5
    
    def test_compare_empty_claims(self, detector):
        """Empty claims have zero similarity."""
        similarity = detector.compare_claims("", "test")
        assert similarity == 0.0


class TestContradictionDetectorExtractClaims:
    """Test key claim extraction."""
    
    @pytest.fixture
    def detector(self):
        return ContradictionDetector()
    
    def test_extract_claims_from_text(self, detector):
        """Claims are extracted from text."""
        text = "The company reported record profits. Sales increased by 20%. The CEO confirmed the expansion."
        claims = detector.extract_key_claims(text)
        assert len(claims) >= 2
    
    def test_extract_claims_filters_short(self, detector):
        """Short sentences are filtered out."""
        text = "Yes. No. Maybe. The company reported significant growth in Q4."
        claims = detector.extract_key_claims(text)
        # Only the longer sentence should be included
        assert all(len(c.split()) >= 3 for c in claims)
    
    def test_extract_claims_empty_text(self, detector):
        """Empty text returns empty list."""
        claims = detector.extract_key_claims("")
        assert claims == []
    
    def test_extract_claims_factual_content(self, detector):
        """Factual statements are identified."""
        text = "The study showed that exercise improves health. Researchers found a correlation."
        claims = detector.extract_key_claims(text)
        assert len(claims) >= 1


class TestContradictionDetectorDetect:
    """Test contradiction detection."""
    
    @pytest.fixture
    def detector(self):
        return ContradictionDetector()
    
    def test_detect_no_contradiction_agreement(self, detector):
        """Sources in agreement show no contradiction."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
            Source(url="https://b.com", title="B", snippet=""),
        ]
        summaries = [
            "The company reported increased profits this quarter.",
            "The company showed profit growth in the recent quarter.",
        ]
        
        result = detector.detect(sources, summaries)
        
        # Should show agreement or minimal contradiction
        assert result.agreement_score >= 0.5
    
    def test_detect_contradiction_negation(self, detector):
        """Negation patterns indicate contradiction."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
            Source(url="https://b.com", title="B", snippet=""),
        ]
        summaries = [
            "The company confirmed the merger will proceed.",
            "The company denied the merger will proceed.",
        ]
        
        result = detector.detect(sources, summaries)
        
        assert result.has_contradiction is True
        assert len(result.conflicting_claims) >= 1
    
    def test_detect_contradiction_opposites(self, detector):
        """Opposite terms indicate contradiction."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
            Source(url="https://b.com", title="B", snippet=""),
        ]
        summaries = [
            "Stock prices are rising sharply today.",
            "Stock prices are falling sharply today.",
        ]
        
        result = detector.detect(sources, summaries)
        
        assert result.has_contradiction is True
    
    def test_detect_single_source_no_contradiction(self, detector):
        """Single source cannot have contradiction."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
        ]
        summaries = [
            "The company reported increased profits.",
        ]
        
        result = detector.detect(sources, summaries)
        
        assert result.has_contradiction is False
        assert result.agreement_score == 1.0
    
    def test_detect_empty_sources(self, detector):
        """Empty sources return no contradiction."""
        result = detector.detect([], [])
        
        assert result.has_contradiction is False
        assert result.agreement_score == 1.0
    
    def test_detect_conflicting_pairs_listed(self, detector):
        """Conflicting pairs are included in result."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
            Source(url="https://b.com", title="B", snippet=""),
        ]
        summaries = [
            "The CEO confirmed the deal is approved.",
            "The CEO denied the deal is approved.",
        ]
        
        result = detector.detect(sources, summaries)
        
        if result.has_contradiction:
            assert len(result.conflicting_claims) >= 1
            # Each claim is a tuple of (source1, source2, description)
            for claim in result.conflicting_claims:
                assert len(claim) == 3
                assert isinstance(claim[0], Source)
                assert isinstance(claim[1], Source)
                assert isinstance(claim[2], str)
    
    def test_detect_agreement_score_range(self, detector):
        """Agreement score is between 0 and 1."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
            Source(url="https://b.com", title="B", snippet=""),
        ]
        summaries = [
            "The economy is strong according to reports.",
            "The economy is weak according to reports.",
        ]
        
        result = detector.detect(sources, summaries)
        
        assert 0.0 <= result.agreement_score <= 1.0


class TestContradictionDetectorNegation:
    """Test negation word detection."""
    
    def test_negation_words_exist(self):
        """Negation words set is populated."""
        assert len(ContradictionDetector.NEGATION_WORDS) > 10
    
    def test_common_negations_included(self):
        """Common negation words are in the set."""
        negations = ContradictionDetector.NEGATION_WORDS
        assert "not" in negations
        assert "denied" in negations
        assert "false" in negations


class TestContradictionPhrases:
    """Test contradiction phrase pairs."""
    
    def test_contradiction_phrases_exist(self):
        """Contradiction phrase pairs are defined."""
        assert len(ContradictionDetector.CONTRADICTION_PHRASES) > 5
    
    def test_common_pairs_included(self):
        """Common opposing pairs are included."""
        phrases = ContradictionDetector.CONTRADICTION_PHRASES
        pair_strings = [(p[0], p[1]) for p in phrases]
        
        assert ("true", "false") in pair_strings
        assert ("confirmed", "denied") in pair_strings
