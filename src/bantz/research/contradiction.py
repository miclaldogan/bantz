"""
Contradiction Detector (Issue #33 - V2-3).

Detects conflicting claims between sources using
text similarity and semantic analysis.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from bantz.research.source_collector import Source


@dataclass
class ContradictionResult:
    """
    Result of contradiction detection.
    
    Attributes:
        has_contradiction: True if contradictions found
        conflicting_claims: List of (source1, source2, description) tuples
        agreement_score: 0.0 = total conflict, 1.0 = total agreement
    """
    has_contradiction: bool
    conflicting_claims: list[tuple[Source, Source, str]] = field(default_factory=list)
    agreement_score: float = 1.0  # Default to full agreement


class ContradictionDetector:
    """
    Detects contradictions between sources.
    
    Uses text analysis to identify conflicting claims
    and calculates overall agreement scores.
    """
    
    # Negation words that indicate potential contradiction
    NEGATION_WORDS = {
        "not", "no", "never", "neither", "none", "nobody",
        "nothing", "nowhere", "hardly", "barely", "scarcely",
        "doesn't", "don't", "didn't", "won't", "wouldn't",
        "couldn't", "shouldn't", "isn't", "aren't", "wasn't",
        "weren't", "hasn't", "haven't", "hadn't", "cannot",
        "denied", "denies", "rejected", "false", "untrue",
        "incorrect", "wrong", "inaccurate", "misleading",
    }
    
    # Contradiction indicator phrases
    CONTRADICTION_PHRASES = [
        ("confirmed", "denied"),
        ("true", "false"),
        ("correct", "incorrect"),
        ("accurate", "inaccurate"),
        ("increased", "decreased"),
        ("rising", "falling"),
        ("up", "down"),
        ("yes", "no"),
        ("success", "failure"),
        ("approved", "rejected"),
        ("support", "oppose"),
        ("agree", "disagree"),
        ("accept", "reject"),
        ("win", "lose"),
        ("alive", "dead"),
    ]
    
    # Similarity threshold for claim matching
    SIMILARITY_THRESHOLD = 0.6
    
    def __init__(self, llm_client=None):
        """
        Initialize ContradictionDetector.
        
        Args:
            llm_client: Optional LLM client for semantic analysis.
                       If not provided, uses heuristic methods.
        """
        self.llm_client = llm_client
    
    def detect(
        self,
        sources: list[Source],
        summaries: list[str]
    ) -> ContradictionResult:
        """
        Detect contradictions between sources.
        
        Analyzes summaries from sources to find conflicting claims.
        
        Args:
            sources: List of sources
            summaries: Corresponding summaries for each source
        
        Returns:
            ContradictionResult with detection results
        """
        if len(sources) < 2 or len(summaries) < 2:
            return ContradictionResult(
                has_contradiction=False,
                conflicting_claims=[],
                agreement_score=1.0
            )
        
        # Ensure sources and summaries match in length
        min_len = min(len(sources), len(summaries))
        sources = sources[:min_len]
        summaries = summaries[:min_len]
        
        # Extract key claims from each summary
        source_claims: list[tuple[Source, list[str]]] = []
        for source, summary in zip(sources, summaries):
            claims = self.extract_key_claims(summary)
            source_claims.append((source, claims))
        
        # Compare claims pairwise
        conflicting_claims: list[tuple[Source, Source, str]] = []
        total_comparisons = 0
        agreements = 0
        
        for i in range(len(source_claims)):
            for j in range(i + 1, len(source_claims)):
                source1, claims1 = source_claims[i]
                source2, claims2 = source_claims[j]
                
                # Compare claims
                for claim1 in claims1:
                    for claim2 in claims2:
                        total_comparisons += 1
                        similarity = self.compare_claims(claim1, claim2)
                        
                        # Check for contradiction
                        if self._is_contradiction(claim1, claim2, similarity):
                            description = f"'{claim1}' vs '{claim2}'"
                            conflicting_claims.append(
                                (source1, source2, description)
                            )
                        elif similarity > self.SIMILARITY_THRESHOLD:
                            agreements += 1
        
        # Calculate agreement score
        if total_comparisons > 0:
            contradiction_count = len(conflicting_claims)
            agreement_ratio = (total_comparisons - contradiction_count) / total_comparisons
            agreement_score = max(0.0, min(1.0, agreement_ratio))
        else:
            agreement_score = 1.0
        
        return ContradictionResult(
            has_contradiction=len(conflicting_claims) > 0,
            conflicting_claims=conflicting_claims,
            agreement_score=agreement_score
        )
    
    def compare_claims(self, claim1: str, claim2: str) -> float:
        """
        Compare two claims for similarity.
        
        Uses word overlap and semantic heuristics.
        
        Args:
            claim1: First claim text
            claim2: Second claim text
        
        Returns:
            Similarity score between 0.0 and 1.0
        """
        # Normalize claims
        words1 = set(self._normalize_text(claim1).split())
        words2 = set(self._normalize_text(claim2).split())
        
        # Remove stopwords
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "under", "again", "further", "then", "once",
            "that", "this", "these", "those", "it", "its", "and", "but",
            "or", "nor", "so", "yet", "both", "each", "few", "more", "most",
        }
        words1 = words1 - stopwords
        words2 = words2 - stopwords
        
        if not words1 or not words2:
            return 0.0
        
        # Jaccard similarity
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    def extract_key_claims(self, text: str) -> list[str]:
        """
        Extract key claims from text.
        
        Splits text into sentences and extracts claims
        that contain factual assertions.
        
        Args:
            text: Text to extract claims from
        
        Returns:
            List of claim strings
        """
        if not text:
            return []
        
        # Split into sentences
        sentences = re.split(r'[.!?]+', text)
        
        claims = []
        for sentence in sentences:
            sentence = sentence.strip()
            
            # Skip short sentences
            if len(sentence.split()) < 3:
                continue
            
            # Skip questions
            if sentence.endswith("?"):
                continue
            
            # Check for factual indicators
            if self._is_factual_claim(sentence):
                claims.append(sentence)
        
        return claims
    
    def _is_factual_claim(self, sentence: str) -> bool:
        """Check if sentence contains a factual claim."""
        lower = sentence.lower()
        
        # Look for factual indicators
        factual_indicators = [
            "is", "are", "was", "were", "has", "have", "had",
            "will", "confirmed", "announced", "reported", "said",
            "stated", "according", "showed", "revealed", "found",
            "discovered", "proved", "demonstrated", "indicates",
            "percent", "%", "million", "billion", "thousand",
        ]
        
        return any(ind in lower for ind in factual_indicators)
    
    def _is_contradiction(
        self,
        claim1: str,
        claim2: str,
        similarity: float
    ) -> bool:
        """
        Check if two claims contradict each other.
        
        Looks for negation patterns and opposing terms.
        """
        lower1 = claim1.lower()
        lower2 = claim2.lower()
        
        # Check for negation asymmetry
        neg1 = any(neg in lower1 for neg in self.NEGATION_WORDS)
        neg2 = any(neg in lower2 for neg in self.NEGATION_WORDS)
        
        # If similar topics but different negation, likely contradiction
        if similarity > 0.3 and neg1 != neg2:
            return True
        
        # Check for opposing terms
        for term1, term2 in self.CONTRADICTION_PHRASES:
            if term1 in lower1 and term2 in lower2:
                return True
            if term2 in lower1 and term1 in lower2:
                return True
        
        return False
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        # Lowercase
        text = text.lower()
        # Remove punctuation
        text = re.sub(r'[^\w\s]', ' ', text)
        # Normalize whitespace
        text = ' '.join(text.split())
        return text
