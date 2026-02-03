"""
Tests for Source Ranker (Issue #33 - V2-3).

Test Scenarios:
- Sources ranked by reliability (highest first)
- Known domains get correct scores
- Unknown domains get default score
- Recency boost for new content
- Low quality filtering
"""

import pytest
from datetime import datetime, timedelta

from bantz.research.source_collector import Source
from bantz.research.source_ranker import SourceRanker


class TestSourceRankerDomainScores:
    """Test domain score lookup."""
    
    @pytest.fixture
    def ranker(self):
        return SourceRanker()
    
    def test_known_domain_reuters(self, ranker):
        """Reuters has high reliability score."""
        score = ranker.get_domain_score("reuters.com")
        assert score == 0.95
    
    def test_known_domain_bbc(self, ranker):
        """BBC has high reliability score."""
        score = ranker.get_domain_score("bbc.com")
        assert score == 0.90
    
    def test_known_domain_wikipedia(self, ranker):
        """Wikipedia has moderate reliability score."""
        score = ranker.get_domain_score("wikipedia.org")
        assert score == 0.80
    
    def test_known_domain_twitter(self, ranker):
        """Twitter has lower reliability score."""
        score = ranker.get_domain_score("twitter.com")
        assert score == 0.40
    
    def test_unknown_domain_default(self, ranker):
        """Unknown domains get default score."""
        score = ranker.get_domain_score("unknownsite.com")
        assert score == ranker.DEFAULT_DOMAIN_SCORE
    
    def test_domain_case_insensitive(self, ranker):
        """Domain lookup is case insensitive."""
        score = ranker.get_domain_score("REUTERS.COM")
        assert score == 0.95


class TestSourceRankerCalculateReliability:
    """Test reliability calculation."""
    
    @pytest.fixture
    def ranker(self):
        return SourceRanker(reference_date=datetime(2024, 1, 15))
    
    def test_reliability_from_domain(self, ranker):
        """Reliability includes domain score."""
        source = Source(
            url="https://reuters.com/article",
            title="Test",
            snippet=""
        )
        score = ranker.calculate_reliability(source)
        assert score >= 0.90  # Reuters base score
    
    def test_reliability_academic_boost(self, ranker):
        """Academic content gets boost."""
        source = Source(
            url="https://unknownsite.com",
            title="Test",
            snippet="",
            content_type="academic"
        )
        base = ranker.DEFAULT_DOMAIN_SCORE
        score = ranker.calculate_reliability(source)
        assert score > base  # Should be boosted
    
    def test_reliability_social_penalty(self, ranker):
        """Social content gets penalty."""
        source = Source(
            url="https://unknownsite.com",
            title="Test",
            snippet="",
            content_type="social"
        )
        base = ranker.DEFAULT_DOMAIN_SCORE
        score = ranker.calculate_reliability(source)
        assert score < base  # Should be penalized
    
    def test_reliability_recency_bonus(self, ranker):
        """Recent content gets bonus."""
        recent_date = datetime(2024, 1, 10)  # 5 days before reference
        source = Source(
            url="https://unknownsite.com",
            title="Test",
            snippet="",
            date=recent_date
        )
        score_with_date = ranker.calculate_reliability(source)
        
        source_no_date = Source(
            url="https://unknownsite.com",
            title="Test",
            snippet=""
        )
        score_no_date = ranker.calculate_reliability(source_no_date)
        
        assert score_with_date > score_no_date
    
    def test_reliability_clamped_to_1(self, ranker):
        """Reliability score is clamped to 1.0."""
        # Create a source with maximum bonuses
        recent_date = datetime(2024, 1, 14)  # Very recent
        source = Source(
            url="https://nature.com/article",  # High score domain
            title="Test",
            snippet="",
            date=recent_date,
            content_type="academic"  # Bonus
        )
        score = ranker.calculate_reliability(source)
        assert score <= 1.0
    
    def test_reliability_clamped_to_0(self, ranker):
        """Reliability score is clamped to 0.0."""
        # Create a source with maximum penalties
        source = Source(
            url="https://instagram.com/post",  # Low score domain
            title="Test",
            snippet="",
            content_type="social"  # Penalty
        )
        score = ranker.calculate_reliability(source)
        assert score >= 0.0


class TestSourceRankerRecencyBonus:
    """Test recency bonus calculation."""
    
    def test_recency_bonus_very_recent(self):
        """Very recent sources get full bonus."""
        reference = datetime(2024, 1, 15)
        ranker = SourceRanker(reference_date=reference)
        
        recent_date = datetime(2024, 1, 14)  # 1 day ago
        source = Source(url="https://example.com", title="", snippet="", date=recent_date)
        
        bonus = ranker._calculate_recency_bonus(source.date)
        assert bonus > 0.08  # Near max bonus
    
    def test_recency_bonus_old_source(self):
        """Old sources get no bonus."""
        reference = datetime(2024, 1, 15)
        ranker = SourceRanker(reference_date=reference)
        
        old_date = datetime(2023, 1, 1)  # Over a year ago
        bonus = ranker._calculate_recency_bonus(old_date)
        assert bonus == 0.0
    
    def test_recency_bonus_30_days(self):
        """Sources at 30 days get no bonus."""
        reference = datetime(2024, 1, 30)
        ranker = SourceRanker(reference_date=reference)
        
        date = datetime(2024, 1, 1)  # ~30 days ago
        bonus = ranker._calculate_recency_bonus(date)
        # Should be at or near 0
        assert bonus < 0.02
    
    def test_recency_bonus_no_date(self):
        """No date means no bonus."""
        ranker = SourceRanker()
        bonus = ranker._calculate_recency_bonus(None)
        assert bonus == 0.0


class TestSourceRankerRank:
    """Test source ranking."""
    
    @pytest.fixture
    def ranker(self):
        return SourceRanker()
    
    def test_rank_orders_by_reliability(self, ranker):
        """Sources are ordered by reliability (highest first)."""
        sources = [
            Source(url="https://twitter.com/post", title="Twitter", snippet=""),
            Source(url="https://reuters.com/article", title="Reuters", snippet=""),
            Source(url="https://example.com/article", title="Unknown", snippet=""),
        ]
        
        ranked = ranker.rank(sources)
        
        assert ranked[0].domain == "reuters.com"
        assert ranked[-1].domain == "twitter.com"
    
    def test_rank_sets_reliability_scores(self, ranker):
        """Ranking sets reliability scores on sources."""
        sources = [
            Source(url="https://bbc.com/news", title="BBC", snippet=""),
        ]
        
        ranked = ranker.rank(sources)
        
        assert ranked[0].reliability_score > 0
    
    def test_rank_preserves_all_sources(self, ranker):
        """Ranking preserves all input sources."""
        sources = [
            Source(url="https://a.com", title="A", snippet=""),
            Source(url="https://b.com", title="B", snippet=""),
            Source(url="https://c.com", title="C", snippet=""),
        ]
        
        ranked = ranker.rank(sources)
        
        assert len(ranked) == len(sources)


class TestSourceRankerFilterLowQuality:
    """Test low quality filtering."""
    
    @pytest.fixture
    def ranker(self):
        return SourceRanker()
    
    def test_filter_removes_low_quality(self, ranker):
        """Low quality sources are filtered out."""
        sources = [
            Source(url="https://reuters.com/article", title="Reuters", snippet=""),
            Source(url="https://instagram.com/post", title="Instagram", snippet="", content_type="social"),
        ]
        
        # First rank to set scores
        ranked = ranker.rank(sources)
        
        # Filter with moderate threshold
        filtered = ranker.filter_low_quality(ranked, threshold=0.3)
        
        # Instagram with social penalty should be filtered
        # Use exact domain match instead of substring (Security Alert #15)
        domains = [s.domain for s in filtered]
        assert any(domain == "reuters.com" for domain in domains)
    
    def test_filter_keeps_high_quality(self, ranker):
        """High quality sources pass filter."""
        sources = [
            Source(url="https://reuters.com/article", title="Reuters", snippet=""),
            Source(url="https://bbc.com/news", title="BBC", snippet=""),
        ]
        
        ranked = ranker.rank(sources)
        filtered = ranker.filter_low_quality(ranked, threshold=0.5)
        
        assert len(filtered) == 2
    
    def test_filter_custom_threshold(self, ranker):
        """Custom threshold is respected."""
        sources = [
            Source(url="https://reuters.com/article", title="Reuters", snippet=""),  # ~0.95
            Source(url="https://medium.com/post", title="Medium", snippet=""),  # ~0.50
        ]
        
        ranked = ranker.rank(sources)
        
        # High threshold should filter medium
        filtered = ranker.filter_low_quality(ranked, threshold=0.8)
        assert len(filtered) == 1
        assert filtered[0].domain == "reuters.com"
