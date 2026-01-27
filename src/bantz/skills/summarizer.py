"""
Page Content Summarization Skill.

Jarvis-style page summarization using LLM:
- Extract page content via extension
- Generate short/detailed summaries
- Answer questions about page content
- Format for TTS and overlay display

Example:
    User: [on news page] "Bu haberi özetle"
    Bantz: "Okuyorum efendim..."
           [extracts content, sends to LLM]
    Bantz: "Buyurun efendim."
           [shows summary in overlay]
    Bantz: [TTS] "Bu haberde Tesla'nın yeni modeli tanıtılıyor..."
    User: "Daha detaylı anlat"
    Bantz: [detailed version with key points]
    User: "Bu CEO kim?"
    Bantz: [answers from context]
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
import logging
import re

if TYPE_CHECKING:
    from bantz.browser.extension_bridge import ExtensionBridge
    from bantz.llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class PageSummary:
    """Summary of a web page."""
    
    title: str
    url: str
    short_summary: str       # 1-2 sentences
    detailed_summary: str    # 3-5 paragraphs
    key_points: List[str]    # Bullet points
    source_content: str = "" # Original content (for Q&A)
    generated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for overlay/serialization."""
        return {
            "title": self.title,
            "url": self.url,
            "short_summary": self.short_summary,
            "detailed_summary": self.detailed_summary,
            "key_points": self.key_points,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class ExtractedPage:
    """Raw extracted page content."""
    
    url: str
    title: str
    content: str
    content_length: int
    extracted_at: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractedPage":
        """Create from extension response dict."""
        return cls(
            url=data.get("url", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            content_length=data.get("content_length", 0),
            extracted_at=data.get("extracted_at", ""),
        )
    
    @property
    def has_content(self) -> bool:
        """Check if extraction has meaningful content."""
        return len(self.content.strip()) > 100


# =============================================================================
# LLM Prompts
# =============================================================================


SUMMARY_SYSTEM_PROMPT = """Sen Jarvis tarzında çalışan bir asistansın. Görevin verilen web sayfası içeriğini analiz edip özetlemek.

Kurallar:
- Türkçe yanıt ver
- Objektif ve bilgilendirici ol
- İçeriğin ana fikrini yakala
- Gereksiz detayları atla
- Reklam veya navigasyon elementlerini görmezden gel
"""

SHORT_SUMMARY_PROMPT = """Aşağıdaki web sayfası içeriğini 1-2 cümleyle özetle.
Sadece ana konuyu ve en önemli bilgiyi içer.
Çok kısa ve öz ol.

Başlık: {title}
URL: {url}

İçerik:
{content}

Kısa özet:"""

DETAILED_SUMMARY_PROMPT = """Aşağıdaki web sayfası içeriğini detaylı olarak özetle.

3-5 paragraf olsun:
1. Ana konu ve bağlam
2. Önemli detaylar
3. Sonuç veya etkileri

Ayrıca 3-5 maddelik "Önemli Noktalar" listesi hazırla.

Başlık: {title}
URL: {url}

İçerik:
{content}

Detaylı özet:"""

QUESTION_ANSWER_PROMPT = """Aşağıdaki web sayfası içeriğine dayanarak soruyu cevapla.
Sadece içerikte bulunan bilgileri kullan.
Eğer bilgi yoksa "Bu konuda sayfada bilgi bulamadım" de.

Başlık: {title}
İçerik:
{content}

Soru: {question}

Cevap:"""


# =============================================================================
# Page Summarizer
# =============================================================================


class PageSummarizer:
    """
    Jarvis-style page summarization system.
    
    Extracts content from current page via extension, generates summaries
    using LLM, and formats for TTS and overlay display.
    
    Example:
        summarizer = PageSummarizer(extension_bridge, llm_client)
        
        # Extract and summarize
        summary = await summarizer.summarize("short")
        
        # Format for TTS
        tts_text = summarizer.format_for_tts(summary)
        
        # Format for overlay
        overlay_data = summarizer.format_for_overlay(summary)
        
        # Answer question
        answer = await summarizer.answer_question("CEO kim?")
    """
    
    def __init__(
        self,
        extension_bridge: Optional["ExtensionBridge"] = None,
        llm_client: Optional["OllamaClient"] = None,
        extract_timeout: float = 5.0,
        llm_timeout: float = 60.0,
    ):
        """
        Initialize page summarizer.
        
        Args:
            extension_bridge: Browser extension bridge for content extraction
            llm_client: LLM client for summarization
            extract_timeout: Timeout for extraction
            llm_timeout: Timeout for LLM calls
        """
        self.bridge = extension_bridge
        self.llm = llm_client
        self.extract_timeout = extract_timeout
        self.llm_timeout = llm_timeout
        
        # State
        self._last_extracted: Optional[ExtractedPage] = None
        self._last_summary: Optional[PageSummary] = None
    
    # =========================================================================
    # Extraction
    # =========================================================================
    
    async def extract_current_page(self) -> Optional[ExtractedPage]:
        """
        Extract content from current browser page.
        
        Returns:
            ExtractedPage with content or None if extraction failed
        """
        if not self.bridge:
            logger.warning("[Summarizer] No extension bridge configured")
            return None
        
        if not self.bridge.has_client():
            logger.warning("[Summarizer] No extension client connected")
            return None
        
        # Request extraction from extension
        result = self.bridge.request_extract()
        
        if not result:
            logger.warning("[Summarizer] Extraction returned no result")
            return None
        
        extracted = ExtractedPage.from_dict(result)
        
        if not extracted.has_content:
            logger.warning(f"[Summarizer] Insufficient content: {extracted.content_length} chars")
            return None
        
        self._last_extracted = extracted
        logger.info(f"[Summarizer] Extracted: {extracted.title[:50]}... ({extracted.content_length} chars)")
        
        return extracted
    
    # =========================================================================
    # Summarization
    # =========================================================================
    
    async def summarize(
        self,
        detail_level: str = "short",
        extracted: Optional[ExtractedPage] = None,
    ) -> Optional[PageSummary]:
        """
        Generate summary of page content.
        
        Args:
            detail_level: "short" for 1-2 sentences, "detailed" for full analysis
            extracted: Pre-extracted content (uses last extracted if None)
            
        Returns:
            PageSummary or None if summarization failed
        """
        # Use provided or last extracted content
        page = extracted or self._last_extracted
        
        if not page:
            # Try to extract first
            page = await self.extract_current_page()
            if not page:
                logger.warning("[Summarizer] No content to summarize")
                return None
        
        if not self.llm:
            logger.warning("[Summarizer] No LLM client configured")
            return None
        
        try:
            # Generate short summary
            short_summary = await self._generate_short_summary(page)
            
            # Generate detailed summary if requested
            if detail_level == "detailed":
                detailed_summary, key_points = await self._generate_detailed_summary(page)
            else:
                detailed_summary = ""
                key_points = []
            
            summary = PageSummary(
                title=page.title,
                url=page.url,
                short_summary=short_summary,
                detailed_summary=detailed_summary,
                key_points=key_points,
                source_content=page.content,
            )
            
            self._last_summary = summary
            logger.info(f"[Summarizer] Generated summary: {len(short_summary)} chars short, {len(detailed_summary)} chars detailed")
            
            return summary
            
        except Exception as e:
            logger.error(f"[Summarizer] Summarization failed: {e}")
            return None
    
    async def _generate_short_summary(self, page: ExtractedPage) -> str:
        """Generate short 1-2 sentence summary."""
        from bantz.llm.ollama_client import LLMMessage
        
        prompt = SHORT_SUMMARY_PROMPT.format(
            title=page.title,
            url=page.url,
            content=page.content[:6000],  # Limit content for short summary
        )
        
        messages = [
            LLMMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ]
        
        response = self.llm.chat(messages, temperature=0.3, max_tokens=200)
        return response.strip()
    
    async def _generate_detailed_summary(
        self, page: ExtractedPage
    ) -> tuple[str, List[str]]:
        """Generate detailed summary with key points."""
        from bantz.llm.ollama_client import LLMMessage
        
        prompt = DETAILED_SUMMARY_PROMPT.format(
            title=page.title,
            url=page.url,
            content=page.content,
        )
        
        messages = [
            LLMMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ]
        
        response = self.llm.chat(messages, temperature=0.4, max_tokens=800)
        
        # Parse response to extract key points
        detailed_summary, key_points = self._parse_detailed_response(response)
        
        return detailed_summary, key_points
    
    def _parse_detailed_response(self, response: str) -> tuple[str, List[str]]:
        """Parse LLM response to separate summary and key points."""
        key_points = []
        
        # Try to find "Önemli Noktalar" section
        patterns = [
            r"(?:Önemli\s+Noktalar|Ana\s+Noktalar|Maddeler|Özet\s+Noktaları)[\s:]*\n((?:[-•*]\s*.+\n?)+)",
            r"\n((?:[-•*]\s*.+\n){3,})",  # Fallback: any bullet list with 3+ items
        ]
        
        detailed_text = response
        
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                bullets_text = match.group(1)
                # Extract individual points
                for line in bullets_text.split('\n'):
                    line = line.strip()
                    if line and line[0] in '-•*':
                        point = line.lstrip('-•* ').strip()
                        if point:
                            key_points.append(point)
                
                if key_points:
                    # Remove key points section from detailed text
                    detailed_text = response[:match.start()].strip()
                    break
        
        # Limit to 5 key points
        key_points = key_points[:5]
        
        return detailed_text, key_points
    
    # =========================================================================
    # Question Answering
    # =========================================================================
    
    async def answer_question(self, question: str) -> Optional[str]:
        """
        Answer a question about the current page content.
        
        Args:
            question: User's question about the page
            
        Returns:
            Answer string or None if cannot answer
        """
        # Get content (from last summary or extracted)
        content = None
        title = ""
        
        if self._last_summary and self._last_summary.source_content:
            content = self._last_summary.source_content
            title = self._last_summary.title
        elif self._last_extracted:
            content = self._last_extracted.content
            title = self._last_extracted.title
        else:
            # Try to extract first
            extracted = await self.extract_current_page()
            if extracted:
                content = extracted.content
                title = extracted.title
        
        if not content:
            logger.warning("[Summarizer] No content available for Q&A")
            return None
        
        if not self.llm:
            logger.warning("[Summarizer] No LLM client configured")
            return None
        
        try:
            from bantz.llm.ollama_client import LLMMessage
            
            prompt = QUESTION_ANSWER_PROMPT.format(
                title=title,
                content=content[:6000],  # Limit for context
                question=question,
            )
            
            messages = [
                LLMMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ]
            
            response = self.llm.chat(messages, temperature=0.3, max_tokens=300)
            return response.strip()
            
        except Exception as e:
            logger.error(f"[Summarizer] Q&A failed: {e}")
            return None
    
    # =========================================================================
    # Formatting
    # =========================================================================
    
    def format_for_tts(self, summary: Optional[PageSummary] = None) -> str:
        """
        Format summary for text-to-speech.
        Uses short summary for TTS to keep it concise.
        
        Args:
            summary: PageSummary to format (uses last summary if None)
            
        Returns:
            TTS-friendly text string
        """
        s = summary or self._last_summary
        
        if not s:
            return "Özet bulunamadı."
        
        # Use short summary for TTS
        if s.short_summary:
            return s.short_summary
        elif s.detailed_summary:
            # Truncate detailed for TTS
            return s.detailed_summary[:200] + "..."
        else:
            return f"{s.title} sayfası analiz edildi."
    
    def format_for_overlay(
        self, summary: Optional[PageSummary] = None, detailed: bool = False
    ) -> Dict[str, Any]:
        """
        Format summary for overlay display.
        
        Args:
            summary: PageSummary to format (uses last summary if None)
            detailed: Whether to include detailed summary and key points
            
        Returns:
            Dict formatted for overlay widget
        """
        s = summary or self._last_summary
        
        if not s:
            return {
                "type": "summary",
                "title": "Özet Yok",
                "content": "Henüz içerik özetlenmedi.",
                "items": [],
            }
        
        if detailed and (s.detailed_summary or s.key_points):
            # Detailed view with key points
            items = []
            for i, point in enumerate(s.key_points, 1):
                items.append({
                    "index": i,
                    "text": point,
                    "type": "point",
                })
            
            return {
                "type": "summary_detailed",
                "title": s.title,
                "url": s.url,
                "content": s.detailed_summary or s.short_summary,
                "items": items,
                "generated_at": s.generated_at.isoformat(),
            }
        else:
            # Short view
            return {
                "type": "summary",
                "title": s.title,
                "url": s.url,
                "content": s.short_summary,
                "items": [],
                "generated_at": s.generated_at.isoformat(),
            }
    
    # =========================================================================
    # State Access
    # =========================================================================
    
    @property
    def has_summary(self) -> bool:
        """Check if we have a generated summary."""
        return self._last_summary is not None
    
    @property
    def has_content(self) -> bool:
        """Check if we have extracted content."""
        return self._last_extracted is not None
    
    @property
    def last_summary(self) -> Optional[PageSummary]:
        """Get the last generated summary."""
        return self._last_summary
    
    @property
    def last_extracted(self) -> Optional[ExtractedPage]:
        """Get the last extracted content."""
        return self._last_extracted
    
    def clear(self) -> None:
        """Clear all state."""
        self._last_extracted = None
        self._last_summary = None


# =============================================================================
# Mock Summarizer for Testing
# =============================================================================


class MockPageSummarizer(PageSummarizer):
    """Mock summarizer for testing without real extension/LLM."""
    
    def __init__(
        self,
        mock_content: Optional[str] = None,
        mock_title: str = "Test Sayfası",
        mock_url: str = "https://example.com/test",
    ):
        super().__init__(extension_bridge=None, llm_client=None)
        
        self._mock_content = mock_content or (
            "Bu bir test içeriğidir. Tesla CEO'su Elon Musk yeni bir açıklama yaptı. "
            "Şirketin yeni modeli Model Z, 2025'te piyasaya çıkacak. "
            "Fiyatı 50.000 dolar civarında olacak. "
            "Musk, bu modelin elektrikli araç pazarını değiştireceğini söyledi."
        )
        self._mock_title = mock_title
        self._mock_url = mock_url
    
    async def extract_current_page(self) -> Optional[ExtractedPage]:
        """Return mock extracted page."""
        extracted = ExtractedPage(
            url=self._mock_url,
            title=self._mock_title,
            content=self._mock_content,
            content_length=len(self._mock_content),
            extracted_at=datetime.now().isoformat(),
        )
        self._last_extracted = extracted
        return extracted
    
    async def summarize(
        self,
        detail_level: str = "short",
        extracted: Optional[ExtractedPage] = None,
    ) -> Optional[PageSummary]:
        """Return mock summary."""
        page = extracted or self._last_extracted
        if not page:
            page = await self.extract_current_page()
        
        if not page:
            return None
        
        summary = PageSummary(
            title=page.title,
            url=page.url,
            short_summary="Tesla yeni Model Z'yi 2025'te piyasaya sürecek, fiyatı 50.000 dolar olacak.",
            detailed_summary=(
                "Tesla CEO'su Elon Musk, şirketin yeni elektrikli araç modeli Model Z'yi duyurdu. "
                "Araç 2025 yılında piyasaya çıkacak ve yaklaşık 50.000 dolar fiyat etiketiyle satışa sunulacak.\n\n"
                "Musk, Model Z'nin elektrikli araç pazarını köklü bir şekilde değiştireceğini belirtti. "
                "Yeni model, daha uzun menzil ve gelişmiş otonom sürüş özellikleriyle dikkat çekiyor."
            ) if detail_level == "detailed" else "",
            key_points=[
                "Tesla Model Z 2025'te çıkacak",
                "Fiyatı 50.000 dolar civarında",
                "Elektrikli araç pazarını değiştirecek",
                "Gelişmiş otonom sürüş özellikleri var",
            ] if detail_level == "detailed" else [],
            source_content=page.content,
        )
        
        self._last_summary = summary
        return summary
    
    async def answer_question(self, question: str) -> Optional[str]:
        """Return mock answer based on question keywords."""
        q_lower = question.lower()
        
        if "ceo" in q_lower or "musk" in q_lower:
            return "Tesla'nın CEO'su Elon Musk'tır."
        elif "fiyat" in q_lower or "kaç" in q_lower:
            return "Model Z'nin fiyatı yaklaşık 50.000 dolar olacak."
        elif "ne zaman" in q_lower or "tarih" in q_lower:
            return "Model Z 2025 yılında piyasaya çıkacak."
        else:
            return "Bu konuda sayfada detaylı bilgi bulamadım."


# =============================================================================
# Helper Functions
# =============================================================================


def extract_question(text: str) -> Optional[str]:
    """
    Extract question from user utterance.
    
    Examples:
        "Bu CEO kim?" -> "Bu CEO kim?"
        "Bana şunu anlat: fiyatı ne?" -> "fiyatı ne?"
        "Anlat bakalım ne olmuş" -> "ne olmuş"
    """
    # Direct question patterns
    question_markers = [
        r"^(.+\?)\s*$",                              # Ends with ?
        r"(?:anlat|söyle|açıkla)\s*(?:bakalım\s*)?(.+)",  # "anlat X"
        r"(?:bu|şu)\s+(.+)",                         # "bu X kim"
        r"(?:ne|kim|neden|nasıl|nerede|kaç)\s+(.+)", # Question words
    ]
    
    for pattern in question_markers:
        match = re.search(pattern, text.strip(), re.IGNORECASE)
        if match:
            return match.group(0).strip()
    
    return text.strip() if text.strip() else None
