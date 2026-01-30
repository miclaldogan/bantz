"""
Source Ranker (Issue #33 - V2-3).

Ranks sources by reliability using domain reputation,
recency, and content type heuristics.
"""

from datetime import datetime, timedelta
from typing import Optional

from bantz.research.source_collector import Source


class SourceRanker:
    """
    Ranks sources by reliability and quality.
    
    Uses domain reputation, recency, and content type
    to calculate reliability scores.
    """
    
    # Domain reliability scores (0.0 - 1.0)
    DOMAIN_SCORES: dict[str, float] = {
        # Tier 1: Wire services & major outlets (0.90-0.95)
        "reuters.com": 0.95,
        "apnews.com": 0.95,
        "bbc.com": 0.90,
        "bbc.co.uk": 0.90,
        "nytimes.com": 0.90,
        "theguardian.com": 0.88,
        "washingtonpost.com": 0.88,
        "economist.com": 0.90,
        
        # Tier 2: Quality news (0.80-0.89)
        "cnn.com": 0.82,
        "bloomberg.com": 0.85,
        "ft.com": 0.88,
        "wsj.com": 0.85,
        "npr.org": 0.85,
        "pbs.org": 0.85,
        
        # Tier 3: Reference & academic (0.75-0.85)
        "wikipedia.org": 0.80,
        "britannica.com": 0.85,
        "arxiv.org": 0.85,
        "nature.com": 0.90,
        "science.org": 0.90,
        "pubmed.ncbi.nlm.nih.gov": 0.90,
        
        # Tier 4: Tech & specialized (0.70-0.80)
        "techcrunch.com": 0.75,
        "wired.com": 0.78,
        "arstechnica.com": 0.78,
        "theverge.com": 0.72,
        
        # Tier 5: Social & user-generated (0.30-0.50)
        "twitter.com": 0.40,
        "x.com": 0.40,
        "reddit.com": 0.45,
        "facebook.com": 0.35,
        "instagram.com": 0.30,
        "tiktok.com": 0.30,
        "youtube.com": 0.50,
        
        # Tier 6: Blogs & medium (0.40-0.60)
        "medium.com": 0.50,
        "substack.com": 0.55,
        "blogspot.com": 0.40,
        "wordpress.com": 0.40,
    }
    
    # Default score for unknown domains
    DEFAULT_DOMAIN_SCORE: float = 0.50
    
    # Content type score modifiers
    CONTENT_TYPE_MODIFIERS: dict[str, float] = {
        "academic": 0.10,   # Boost academic content
        "news": 0.05,       # Slight boost for news
        "article": 0.0,     # Neutral
        "social": -0.15,    # Penalty for social media
    }
    
    # Recency bonus configuration
    RECENCY_BONUS_MAX: float = 0.10  # Max bonus for very recent
    RECENCY_DECAY_DAYS: int = 30     # Days until no bonus
    
    def __init__(self, reference_date: Optional[datetime] = None):
        """
        Initialize SourceRanker.
        
        Args:
            reference_date: Date to use for recency calculations.
                           Defaults to now.
        """
        self.reference_date = reference_date or datetime.now()
    
    def rank(self, sources: list[Source]) -> list[Source]:
        """
        Rank sources by reliability score.
        
        Calculates reliability for each source and returns
        them sorted in descending order (highest first).
        
        Args:
            sources: List of sources to rank
        
        Returns:
            Sources sorted by reliability (highest first)
        """
        # Calculate reliability for each source
        for source in sources:
            source.reliability_score = self.calculate_reliability(source)
        
        # Sort by reliability (descending)
        return sorted(
            sources,
            key=lambda s: s.reliability_score,
            reverse=True
        )
    
    def calculate_reliability(self, source: Source) -> float:
        """
        Calculate reliability score for a source.
        
        Factors:
        - Domain reputation (base score)
        - Content type modifier
        - Recency bonus
        
        Args:
            source: Source to calculate reliability for
        
        Returns:
            Reliability score between 0.0 and 1.0
        """
        # Base score from domain
        domain = source.domain.lower()
        base_score = self.DOMAIN_SCORES.get(domain, self.DEFAULT_DOMAIN_SCORE)
        
        # Content type modifier
        content_modifier = self.CONTENT_TYPE_MODIFIERS.get(
            source.content_type, 0.0
        )
        
        # Recency bonus
        recency_bonus = self._calculate_recency_bonus(source.date)
        
        # Combine scores
        total_score = base_score + content_modifier + recency_bonus
        
        # Clamp to 0.0 - 1.0 range
        return max(0.0, min(1.0, total_score))
    
    def filter_low_quality(
        self,
        sources: list[Source],
        threshold: float = 0.3
    ) -> list[Source]:
        """
        Filter out low quality sources.
        
        Args:
            sources: List of sources to filter
            threshold: Minimum reliability score (default 0.3)
        
        Returns:
            Sources with reliability >= threshold
        """
        # Ensure scores are calculated
        for source in sources:
            if source.reliability_score == 0.0 and source.domain:
                source.reliability_score = self.calculate_reliability(source)
        
        return [s for s in sources if s.reliability_score >= threshold]
    
    def _calculate_recency_bonus(self, date: Optional[datetime]) -> float:
        """
        Calculate recency bonus for a source.
        
        Sources within RECENCY_DECAY_DAYS get a linear bonus
        up to RECENCY_BONUS_MAX for very recent content.
        
        Args:
            date: Publication date of source
        
        Returns:
            Recency bonus (0.0 to RECENCY_BONUS_MAX)
        """
        if not date:
            return 0.0
        
        # Calculate days since publication
        delta = self.reference_date - date
        days_old = delta.days
        
        # Future dates get no bonus
        if days_old < 0:
            return 0.0
        
        # Calculate linear decay
        if days_old >= self.RECENCY_DECAY_DAYS:
            return 0.0
        
        # Linear interpolation: newer = higher bonus
        decay_factor = 1.0 - (days_old / self.RECENCY_DECAY_DAYS)
        return self.RECENCY_BONUS_MAX * decay_factor
    
    def get_domain_score(self, domain: str) -> float:
        """
        Get the base reliability score for a domain.
        
        Args:
            domain: Domain name (e.g., "reuters.com")
        
        Returns:
            Domain reliability score
        """
        return self.DOMAIN_SCORES.get(
            domain.lower(),
            self.DEFAULT_DOMAIN_SCORE
        )
