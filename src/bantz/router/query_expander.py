"""Query Expander — LLM-based query expansion (Issue #21).

Expands queries based on context and suggests related queries.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from bantz.llm.base import LLMClientProtocol, LLMMessage


@dataclass
class ExpandedQuery:
    """Expanded query result."""
    original: str
    expanded: str
    additions: List[str]
    confidence: float


@dataclass
class QuerySuggestion:
    """Query suggestion."""
    query: str
    reason: str
    relevance: float


class QueryExpander:
    """LLM-based query expansion.
    
    Features:
    - Expand query based on context
    - Suggest related queries
    - Search optimization
    
    Usage:
        expander = QueryExpander(llm_client)
        
        # Expand query
        expanded = await expander.expand_query(
            "kaza haberleri",
            context={"location": "Kadıköy", "time": "bugün"}
        )
        # Result: "Kadıköy kaza haberleri bugün"
        
        # Get suggestions
        suggestions = await expander.suggest_related("deprem haberleri")
        # ["deprem son dakika", "deprem yardım", "deprem ölü sayısı"]
    """
    
    EXPAND_PROMPT = """Aşağıdaki arama sorgusunu daha spesifik hale getir.
Ekstra bilgi ekle ama anlamını değiştirme. Türkçe yaz.

Orijinal sorgu: {query}
Konum: {location}
Zaman: {time}
Ek bilgi: {extra}

Genişletilmiş sorgu (tek satır, sadece sorgu):"""

    SUGGEST_PROMPT = """Aşağıdaki sorguyla ilgili 3 alternatif arama öner.
Her satırda bir öneri olsun. Türkçe yaz.

Sorgu: {query}

Öneriler:"""

    OPTIMIZE_PROMPT = """Aşağıdaki arama sorgusunu arama motoru için optimize et.
Gereksiz kelimeleri çıkar, anahtar kelimeleri koru. Türkçe yaz.

Sorgu: {query}

Optimize edilmiş sorgu (tek satır):"""

    def __init__(self, llm_client: Optional[LLMClientProtocol] = None):
        """Initialize expander.
        
        Args:
            llm_client: LLM client instance (optional)
        """
        self._llm = llm_client
    
    @property
    def has_llm(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None
    
    # ─────────────────────────────────────────────────────────────
    # Sync Methods (no LLM)
    # ─────────────────────────────────────────────────────────────
    
    def expand_simple(self, query: str, context: Dict[str, str]) -> str:
        """Simple query expansion without LLM.
        
        Args:
            query: Original query
            context: Context dict with location, time, etc.
            
        Returns:
            Expanded query string
        """
        parts = [query]
        
        # Add location if provided and not already in query
        location = context.get("location", "")
        if location and location.lower() not in query.lower():
            parts.append(location)
        
        # Add time if provided and not already in query
        time = context.get("time", "")
        if time and time.lower() not in query.lower():
            parts.append(time)
        
        return " ".join(parts).strip()
    
    def suggest_simple(self, query: str) -> List[str]:
        """Simple query suggestions without LLM.
        
        Args:
            query: Original query
            
        Returns:
            List of related query suggestions
        """
        suggestions = []
        
        # Add "son dakika" variant
        if "son dakika" not in query.lower():
            suggestions.append(f"{query} son dakika")
        
        # Add "detay" variant
        suggestions.append(f"{query} detay")
        
        # Add "neden" variant
        suggestions.append(f"{query} neden")
        
        return suggestions[:3]
    
    def optimize_simple(self, query: str) -> str:
        """Simple query optimization without LLM.
        
        Removes filler words and optimizes for search.
        
        Args:
            query: Original query
            
        Returns:
            Optimized query
        """
        # Filler words to remove
        fillers = [
            "bir", "bu", "şu", "o", "bana", "bize", "lütfen",
            "acaba", "ya", "yani", "hani", "işte", "aslında",
            "neydi", "neymiş", "miydi", "midir", "mı", "mi",
            "haberlere", "haberlerine", "bak", "bakabilir misin",
            "göster", "gösterir misin", "ara", "arabilir misin",
            "ne var", "neler var", "neler olmuş",
        ]
        
        result = query.lower()
        
        for filler in fillers:
            # Word boundary replacement
            result = result.replace(f" {filler} ", " ")
            result = result.replace(f" {filler}", "")
            if result.startswith(f"{filler} "):
                result = result[len(filler) + 1:]
        
        # Clean up extra spaces
        result = " ".join(result.split())
        
        return result.strip()
    
    # ─────────────────────────────────────────────────────────────
    # Async Methods (with LLM)
    # ─────────────────────────────────────────────────────────────
    
    async def expand_query(
        self,
        query: str,
        context: Optional[Dict[str, str]] = None,
    ) -> ExpandedQuery:
        """Sorguyu bağlama göre genişlet.
        
        Args:
            query: Original query
            context: Context dict with location, time, etc.
            
        Returns:
            ExpandedQuery with expanded string
        """
        context = context or {}
        
        # Fallback to simple expansion if no LLM
        if not self._llm:
            expanded = self.expand_simple(query, context)
            return ExpandedQuery(
                original=query,
                expanded=expanded,
                additions=[v for v in context.values() if v],
                confidence=0.8,
            )
        
        # Use LLM for expansion
        prompt = self.EXPAND_PROMPT.format(
            query=query,
            location=context.get("location", "belirtilmedi"),
            time=context.get("time", "belirtilmedi"),
            extra=context.get("extra", "yok"),
        )
        
        try:
            response = self._llm.chat(
                [LLMMessage(role="user", content=prompt)],
                max_tokens=50,
                temperature=0.3,
            )
            
            expanded = response.strip()
            
            # Find what was added
            additions = []
            for word in expanded.split():
                if word.lower() not in query.lower():
                    additions.append(word)
            
            return ExpandedQuery(
                original=query,
                expanded=expanded,
                additions=additions,
                confidence=0.9,
            )
            
        except Exception:
            # Fallback to simple
            expanded = self.expand_simple(query, context)
            return ExpandedQuery(
                original=query,
                expanded=expanded,
                additions=[v for v in context.values() if v],
                confidence=0.7,
            )
    
    async def suggest_related(self, query: str, limit: int = 3) -> List[QuerySuggestion]:
        """İlgili sorgular öner.
        
        Args:
            query: Original query
            limit: Max suggestions
            
        Returns:
            List of QuerySuggestion
        """
        # Fallback to simple suggestions if no LLM
        if not self._llm:
            simple = self.suggest_simple(query)
            return [
                QuerySuggestion(query=s, reason="ilgili arama", relevance=0.7)
                for s in simple[:limit]
            ]
        
        prompt = self.SUGGEST_PROMPT.format(query=query)
        
        try:
            response = self._llm.chat(
                [LLMMessage(role="user", content=prompt)],
                max_tokens=100,
                temperature=0.5,
            )
            
            lines = [
                line.strip().lstrip("1234567890.-) ")
                for line in response.split("\n")
                if line.strip()
            ]
            
            suggestions = []
            for i, line in enumerate(lines[:limit]):
                suggestions.append(QuerySuggestion(
                    query=line,
                    reason="LLM önerisi",
                    relevance=0.9 - (i * 0.1),
                ))
            
            return suggestions
            
        except Exception:
            simple = self.suggest_simple(query)
            return [
                QuerySuggestion(query=s, reason="ilgili arama", relevance=0.6)
                for s in simple[:limit]
            ]
    
    async def optimize(self, query: str) -> str:
        """Sorguyu arama için optimize et.
        
        Args:
            query: Original query
            
        Returns:
            Optimized query string
        """
        if not self._llm:
            return self.optimize_simple(query)
        
        prompt = self.OPTIMIZE_PROMPT.format(query=query)
        
        try:
            response = self._llm.chat(
                [LLMMessage(role="user", content=prompt)],
                max_tokens=50,
                temperature=0.2,
            )
            
            return response.strip()
            
        except Exception:
            return self.optimize_simple(query)


# ─────────────────────────────────────────────────────────────────
# Mock Expander for Testing
# ─────────────────────────────────────────────────────────────────

class MockQueryExpander:
    """Mock expander for testing without LLM."""
    
    def __init__(self):
        self._expand_results: Dict[str, str] = {}
        self._suggestions: List[str] = ["öneri 1", "öneri 2", "öneri 3"]
    
    def set_expand_result(self, query: str, expanded: str) -> None:
        """Set mock expand result."""
        self._expand_results[query] = expanded
    
    def set_suggestions(self, suggestions: List[str]) -> None:
        """Set mock suggestions."""
        self._suggestions = suggestions
    
    def expand_simple(self, query: str, context: Dict[str, str]) -> str:
        if query in self._expand_results:
            return self._expand_results[query]
        
        parts = [query]
        if context.get("location"):
            parts.append(context["location"])
        return " ".join(parts)
    
    def suggest_simple(self, query: str) -> List[str]:
        return self._suggestions[:3]
    
    def optimize_simple(self, query: str) -> str:
        return query.strip()
    
    async def expand_query(
        self,
        query: str,
        context: Optional[Dict[str, str]] = None,
    ) -> ExpandedQuery:
        context = context or {}
        expanded = self.expand_simple(query, context)
        return ExpandedQuery(
            original=query,
            expanded=expanded,
            additions=[],
            confidence=1.0,
        )
    
    async def suggest_related(self, query: str, limit: int = 3) -> List[QuerySuggestion]:
        return [
            QuerySuggestion(query=s, reason="mock", relevance=0.8)
            for s in self._suggestions[:limit]
        ]
    
    async def optimize(self, query: str) -> str:
        return self.optimize_simple(query)

