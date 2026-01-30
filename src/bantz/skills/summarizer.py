"""
Page Content Summarization Skill.

Jarvis-style page summarization using LLM:
- Extract page content via extension
- Generate short/detailed summaries
- Answer questions about page content
- Format for TTS and overlay display

Enhanced Features (Issue #61):
- Caching: Avoid duplicate LLM calls for same URL
- Progress Indicator: "Sayfa okunuyor... Özetleniyor..."
- Summary History: Keep last N summaries
- Summary Length: tweet-size, paragraph, full
- Rate Limiting: Prevent overload
- Error Recovery: Retry mechanism

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
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import hashlib
import logging
import re
import time

if TYPE_CHECKING:
    from bantz.browser.extension_bridge import ExtensionBridge
    from bantz.llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Types
# =============================================================================


class SummaryLength(Enum):
    """Summary length options."""
    
    TWEET = "tweet"          # 280 characters (Twitter-style)
    PARAGRAPH = "paragraph"  # 1-2 paragraphs
    FULL = "full"            # Complete detailed summary
    
    @classmethod
    def from_str(cls, value: str) -> "SummaryLength":
        """Parse from string (Turkish or English)."""
        value_lower = value.lower().strip()
        
        # Turkish mappings
        turkish_map = {
            "kısa": cls.TWEET,
            "kisa": cls.TWEET,
            "tweet": cls.TWEET,
            "orta": cls.PARAGRAPH,
            "paragraf": cls.PARAGRAPH,
            "paragraph": cls.PARAGRAPH,
            "uzun": cls.FULL,
            "detaylı": cls.FULL,
            "detayli": cls.FULL,
            "full": cls.FULL,
            "tam": cls.FULL,
        }
        
        return turkish_map.get(value_lower, cls.PARAGRAPH)


class ProgressStage(Enum):
    """Summary generation progress stages."""
    
    STARTED = "started"
    EXTRACTING = "extracting"       # "Sayfa okunuyor..."
    EXTRACTED = "extracted"         # "İçerik çıkarıldı"
    SUMMARIZING = "summarizing"     # "Özetleniyor..."
    COMPLETED = "completed"         # "Tamamlandı"
    CACHED = "cached"               # "Önbellekten alındı"
    FAILED = "failed"               # "Hata oluştu"


# Type alias for progress callback
ProgressCallback = Callable[[ProgressStage, str], None]


# =============================================================================
# Cache Entry
# =============================================================================


@dataclass
class CacheEntry:
    """Cached summary entry."""
    
    url_hash: str
    summary: "PageSummary"
    created_at: datetime
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    
    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """Check if cache entry is expired."""
        age = datetime.now() - self.created_at
        return age.total_seconds() > ttl_seconds
    
    def touch(self) -> None:
        """Update access statistics."""
        self.access_count += 1
        self.last_accessed = datetime.now()


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
    length_type: SummaryLength = SummaryLength.PARAGRAPH  # Summary length type
    from_cache: bool = False  # Whether loaded from cache
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for overlay/serialization."""
        return {
            "title": self.title,
            "url": self.url,
            "short_summary": self.short_summary,
            "detailed_summary": self.detailed_summary,
            "key_points": self.key_points,
            "generated_at": self.generated_at.isoformat(),
            "length_type": self.length_type.value,
            "from_cache": self.from_cache,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageSummary":
        """Create from dictionary."""
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            short_summary=data.get("short_summary", ""),
            detailed_summary=data.get("detailed_summary", ""),
            key_points=data.get("key_points", []),
            source_content=data.get("source_content", ""),
            generated_at=datetime.fromisoformat(data["generated_at"]) 
                if "generated_at" in data else datetime.now(),
            length_type=SummaryLength(data.get("length_type", "paragraph")),
            from_cache=data.get("from_cache", False),
        )


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

TWEET_SUMMARY_PROMPT = """Aşağıdaki web sayfası içeriğini tweet formatında (maksimum 280 karakter) özetle.
Sadece en kritik bilgiyi ver.

Başlık: {title}

İçerik:
{content}

Tweet özet (max 280 karakter):"""

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
# Summary Cache
# =============================================================================


class SummaryCache:
    """
    LRU cache for page summaries.
    
    Prevents duplicate LLM calls for the same URL within TTL period.
    """
    
    def __init__(
        self,
        max_size: int = 100,
        ttl_seconds: int = 3600,  # 1 hour default
    ):
        """
        Initialize cache.
        
        Args:
            max_size: Maximum number of cached entries
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
    
    @staticmethod
    def _hash_url(url: str) -> str:
        """Generate hash for URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]
    
    async def get(self, url: str) -> Optional[PageSummary]:
        """
        Get cached summary for URL.
        
        Args:
            url: Page URL
            
        Returns:
            Cached PageSummary or None if not found/expired
        """
        async with self._lock:
            url_hash = self._hash_url(url)
            entry = self._cache.get(url_hash)
            
            if entry is None:
                return None
            
            if entry.is_expired(self.ttl_seconds):
                del self._cache[url_hash]
                logger.debug(f"[Cache] Expired entry removed: {url_hash}")
                return None
            
            entry.touch()
            summary = entry.summary
            summary.from_cache = True
            logger.info(f"[Cache] Hit for {url_hash} (access #{entry.access_count})")
            return summary
    
    async def set(self, url: str, summary: PageSummary) -> None:
        """
        Cache summary for URL.
        
        Args:
            url: Page URL
            summary: PageSummary to cache
        """
        async with self._lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self.max_size:
                await self._evict_oldest()
            
            url_hash = self._hash_url(url)
            entry = CacheEntry(
                url_hash=url_hash,
                summary=summary,
                created_at=datetime.now(),
            )
            self._cache[url_hash] = entry
            logger.info(f"[Cache] Stored: {url_hash} ({len(self._cache)}/{self.max_size})")
    
    async def _evict_oldest(self) -> None:
        """Evict least recently accessed entry."""
        if not self._cache:
            return
        
        oldest_hash = min(
            self._cache.keys(),
            key=lambda h: self._cache[h].last_accessed
        )
        del self._cache[oldest_hash]
        logger.debug(f"[Cache] Evicted: {oldest_hash}")
    
    async def clear(self) -> None:
        """Clear all cached entries."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"[Cache] Cleared {count} entries")
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds,
            "entries": [
                {
                    "hash": h,
                    "access_count": e.access_count,
                    "age_seconds": (datetime.now() - e.created_at).total_seconds(),
                }
                for h, e in self._cache.items()
            ]
        }


# =============================================================================
# Summary History
# =============================================================================


class SummaryHistory:
    """
    Keeps track of recent summaries for easy access.
    """
    
    def __init__(self, max_size: int = 10):
        """
        Initialize history.
        
        Args:
            max_size: Maximum number of summaries to keep
        """
        self.max_size = max_size
        self._history: List[PageSummary] = []
    
    def add(self, summary: PageSummary) -> None:
        """
        Add summary to history.
        
        Args:
            summary: PageSummary to add
        """
        # Remove if same URL already exists
        self._history = [s for s in self._history if s.url != summary.url]
        
        # Add to front
        self._history.insert(0, summary)
        
        # Trim to max size
        if len(self._history) > self.max_size:
            self._history = self._history[:self.max_size]
    
    def get_recent(self, count: int = 5) -> List[PageSummary]:
        """Get most recent summaries."""
        return self._history[:count]
    
    def get_by_url(self, url: str) -> Optional[PageSummary]:
        """Find summary by URL."""
        for summary in self._history:
            if summary.url == url:
                return summary
        return None
    
    def get_by_index(self, index: int) -> Optional[PageSummary]:
        """Get summary by index (0 = most recent)."""
        if 0 <= index < len(self._history):
            return self._history[index]
        return None
    
    def clear(self) -> None:
        """Clear history."""
        self._history.clear()
    
    @property
    def count(self) -> int:
        """Number of summaries in history."""
        return len(self._history)
    
    def to_list(self) -> List[Dict[str, Any]]:
        """Convert history to list of dicts."""
        return [
            {
                "index": i,
                "title": s.title,
                "url": s.url,
                "short_summary": s.short_summary[:100] + "..." if len(s.short_summary) > 100 else s.short_summary,
                "generated_at": s.generated_at.isoformat(),
            }
            for i, s in enumerate(self._history)
        ]


# =============================================================================
# Rate Limiter
# =============================================================================


class RateLimiter:
    """
    Simple rate limiter for LLM calls.
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: float = 60.0,
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: List[float] = []
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """
        Try to acquire a slot.
        
        Returns:
            True if allowed, False if rate limited
        """
        async with self._lock:
            now = time.time()
            
            # Remove old requests outside window
            self._requests = [
                t for t in self._requests 
                if now - t < self.window_seconds
            ]
            
            if len(self._requests) >= self.max_requests:
                logger.warning(f"[RateLimiter] Rate limited: {len(self._requests)}/{self.max_requests}")
                return False
            
            self._requests.append(now)
            return True
    
    async def wait_if_needed(self, timeout: float = 30.0) -> bool:
        """
        Wait until a slot is available.
        
        Args:
            timeout: Maximum time to wait
            
        Returns:
            True if acquired, False if timeout
        """
        start = time.time()
        
        while time.time() - start < timeout:
            if await self.acquire():
                return True
            await asyncio.sleep(0.5)
        
        return False
    
    @property
    def current_usage(self) -> int:
        """Current number of requests in window."""
        now = time.time()
        return len([
            t for t in self._requests 
            if now - t < self.window_seconds
        ])


# =============================================================================
# Page Summarizer
# =============================================================================


class PageSummarizer:
    """
    Jarvis-style page summarization system.
    
    Extracts content from current page via extension, generates summaries
    using LLM, and formats for TTS and overlay display.
    
    Enhanced features:
    - Caching: Avoid duplicate LLM calls for same URL
    - Progress: Real-time progress callbacks
    - History: Keep last N summaries
    - Length options: tweet/paragraph/full
    - Rate limiting: Prevent overload
    - Error recovery: Retry mechanism
    
    Example:
        summarizer = PageSummarizer(extension_bridge, llm_client)
        
        # Progress callback
        def on_progress(stage, message):
            print(f"[{stage.value}] {message}")
        
        # Extract and summarize with caching
        summary = await summarizer.summarize(
            length=SummaryLength.PARAGRAPH,
            use_cache=True,
            progress_callback=on_progress
        )
        
        # Get history
        recent = summarizer.history.get_recent(5)
        
        # Answer question
        answer = await summarizer.answer_question("CEO kim?")
    """
    
    def __init__(
        self,
        extension_bridge: Optional["ExtensionBridge"] = None,
        llm_client: Optional["OllamaClient"] = None,
        extract_timeout: float = 5.0,
        llm_timeout: float = 60.0,
        cache_ttl: int = 3600,
        cache_size: int = 100,
        history_size: int = 10,
        max_retries: int = 3,
        rate_limit: int = 10,
    ):
        """
        Initialize page summarizer.
        
        Args:
            extension_bridge: Browser extension bridge for content extraction
            llm_client: LLM client for summarization
            extract_timeout: Timeout for extraction
            llm_timeout: Timeout for LLM calls
            cache_ttl: Cache time-to-live in seconds
            cache_size: Maximum cache entries
            history_size: Maximum history entries
            max_retries: Maximum retry attempts on failure
            rate_limit: Maximum requests per minute
        """
        self.bridge = extension_bridge
        self.llm = llm_client
        self.extract_timeout = extract_timeout
        self.llm_timeout = llm_timeout
        self.max_retries = max_retries
        
        # State
        self._last_extracted: Optional[ExtractedPage] = None
        self._last_summary: Optional[PageSummary] = None
        
        # Cache and history
        self._cache = SummaryCache(max_size=cache_size, ttl_seconds=cache_ttl)
        self._history = SummaryHistory(max_size=history_size)
        self._rate_limiter = RateLimiter(max_requests=rate_limit, window_seconds=60.0)
    
    @property
    def cache(self) -> SummaryCache:
        """Access to summary cache."""
        return self._cache
    
    @property
    def history(self) -> SummaryHistory:
        """Access to summary history."""
        return self._history
    
    # =========================================================================
    # Progress Helpers
    # =========================================================================
    
    def _notify_progress(
        self,
        callback: Optional[ProgressCallback],
        stage: ProgressStage,
        message: str,
    ) -> None:
        """Safely notify progress callback."""
        if callback:
            try:
                callback(stage, message)
            except Exception as e:
                logger.warning(f"[Summarizer] Progress callback error: {e}")
    
    # =========================================================================
    # Extraction
    # =========================================================================
    
    async def extract_current_page(
        self,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[ExtractedPage]:
        """
        Extract content from current browser page.
        
        Args:
            progress_callback: Optional callback for progress updates
        
        Returns:
            ExtractedPage with content or None if extraction failed
        """
        self._notify_progress(progress_callback, ProgressStage.EXTRACTING, "Sayfa okunuyor...")
        
        if not self.bridge:
            logger.warning("[Summarizer] No extension bridge configured")
            self._notify_progress(progress_callback, ProgressStage.FAILED, "Extension bridge yok")
            return None
        
        if not self.bridge.has_client():
            logger.warning("[Summarizer] No extension client connected")
            self._notify_progress(progress_callback, ProgressStage.FAILED, "Extension bağlı değil")
            return None
        
        # Request extraction from extension
        result = self.bridge.request_extract()
        
        if not result:
            logger.warning("[Summarizer] Extraction returned no result")
            self._notify_progress(progress_callback, ProgressStage.FAILED, "İçerik çıkarılamadı")
            return None
        
        extracted = ExtractedPage.from_dict(result)
        
        if not extracted.has_content:
            logger.warning(f"[Summarizer] Insufficient content: {extracted.content_length} chars")
            self._notify_progress(progress_callback, ProgressStage.FAILED, "Yetersiz içerik")
            return None
        
        self._last_extracted = extracted
        logger.info(f"[Summarizer] Extracted: {extracted.title[:50]}... ({extracted.content_length} chars)")
        self._notify_progress(
            progress_callback, 
            ProgressStage.EXTRACTED, 
            f"İçerik çıkarıldı ({extracted.content_length} karakter)"
        )
        
        return extracted
    
    # =========================================================================
    # Summarization
    # =========================================================================
    
    async def summarize(
        self,
        length: SummaryLength = SummaryLength.PARAGRAPH,
        extracted: Optional[ExtractedPage] = None,
        use_cache: bool = True,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[PageSummary]:
        """
        Generate summary of page content.
        
        Args:
            length: Summary length type (TWEET, PARAGRAPH, FULL)
            extracted: Pre-extracted content (uses last extracted if None)
            use_cache: Whether to check cache first
            progress_callback: Optional callback for progress updates
            
        Returns:
            PageSummary or None if summarization failed
        """
        self._notify_progress(progress_callback, ProgressStage.STARTED, "Özet oluşturuluyor...")
        
        # Use provided or last extracted content
        page = extracted or self._last_extracted
        
        if not page:
            # Try to extract first
            page = await self.extract_current_page(progress_callback)
            if not page:
                logger.warning("[Summarizer] No content to summarize")
                self._notify_progress(progress_callback, ProgressStage.FAILED, "İçerik bulunamadı")
                return None
        
        # Check cache first
        if use_cache:
            cached = await self._cache.get(page.url)
            if cached:
                logger.info(f"[Summarizer] Cache hit for: {page.url[:50]}")
                self._notify_progress(progress_callback, ProgressStage.CACHED, "Önbellekten alındı")
                self._last_summary = cached
                self._history.add(cached)
                return cached
        
        if not self.llm:
            logger.warning("[Summarizer] No LLM client configured")
            self._notify_progress(progress_callback, ProgressStage.FAILED, "LLM yapılandırılmamış")
            return None
        
        # Check rate limit
        if not await self._rate_limiter.wait_if_needed(timeout=30.0):
            logger.warning("[Summarizer] Rate limited, request dropped")
            self._notify_progress(progress_callback, ProgressStage.FAILED, "Çok fazla istek, lütfen bekleyin")
            return None
        
        self._notify_progress(progress_callback, ProgressStage.SUMMARIZING, "Özetleniyor...")
        
        # Retry mechanism
        last_error = None
        for attempt in range(self.max_retries):
            try:
                summary = await self._generate_summary_with_length(page, length)
                
                # Cache the result
                if use_cache:
                    await self._cache.set(page.url, summary)
                
                # Add to history
                self._history.add(summary)
                
                self._last_summary = summary
                logger.info(f"[Summarizer] Generated summary: {len(summary.short_summary)} chars")
                self._notify_progress(progress_callback, ProgressStage.COMPLETED, "Tamamlandı")
                
                return summary
                
            except Exception as e:
                last_error = e
                logger.warning(f"[Summarizer] Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))  # Exponential backoff
        
        logger.error(f"[Summarizer] All {self.max_retries} attempts failed: {last_error}")
        self._notify_progress(progress_callback, ProgressStage.FAILED, f"Hata: {last_error}")
        return None
    
    async def _generate_summary_with_length(
        self,
        page: ExtractedPage,
        length: SummaryLength,
    ) -> PageSummary:
        """Generate summary based on requested length."""
        from bantz.llm.ollama_client import LLMMessage
        
        if length == SummaryLength.TWEET:
            # Tweet-size summary (max 280 chars)
            short_summary = await self._generate_tweet_summary(page)
            detailed_summary = ""
            key_points = []
        elif length == SummaryLength.PARAGRAPH:
            # Normal short summary
            short_summary = await self._generate_short_summary(page)
            detailed_summary = ""
            key_points = []
        else:  # FULL
            # Full detailed summary
            short_summary = await self._generate_short_summary(page)
            detailed_summary, key_points = await self._generate_detailed_summary(page)
        
        return PageSummary(
            title=page.title,
            url=page.url,
            short_summary=short_summary,
            detailed_summary=detailed_summary,
            key_points=key_points,
            source_content=page.content,
            length_type=length,
        )
    
    async def _generate_tweet_summary(self, page: ExtractedPage) -> str:
        """Generate tweet-size summary (max 280 chars)."""
        from bantz.llm.ollama_client import LLMMessage
        
        prompt = TWEET_SUMMARY_PROMPT.format(
            title=page.title,
            content=page.content[:4000],  # Limit content for tweet
        )
        
        messages = [
            LLMMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ]
        
        response = self.llm.chat(messages, temperature=0.3, max_tokens=100)
        summary = response.strip()
        
        # Ensure max 280 chars
        if len(summary) > 280:
            summary = summary[:277] + "..."
        
        return summary
    
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
                "from_cache": s.from_cache,
                "length_type": s.length_type.value,
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
                "from_cache": s.from_cache,
                "length_type": s.length_type.value,
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
        """Clear all state (not cache or history)."""
        self._last_extracted = None
        self._last_summary = None
    
    async def clear_all(self) -> None:
        """Clear all state including cache and history."""
        self._last_extracted = None
        self._last_summary = None
        await self._cache.clear()
        self._history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get summarizer statistics."""
        return {
            "cache": self._cache.stats(),
            "history_count": self._history.count,
            "rate_limiter_usage": self._rate_limiter.current_usage,
            "has_summary": self.has_summary,
            "has_content": self.has_content,
        }


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
    
    async def extract_current_page(
        self,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[ExtractedPage]:
        """Return mock extracted page."""
        self._notify_progress(progress_callback, ProgressStage.EXTRACTING, "Sayfa okunuyor...")
        
        extracted = ExtractedPage(
            url=self._mock_url,
            title=self._mock_title,
            content=self._mock_content,
            content_length=len(self._mock_content),
            extracted_at=datetime.now().isoformat(),
        )
        self._last_extracted = extracted
        
        self._notify_progress(progress_callback, ProgressStage.EXTRACTED, "İçerik çıkarıldı")
        return extracted
    
    async def summarize(
        self,
        length: SummaryLength = SummaryLength.PARAGRAPH,
        extracted: Optional[ExtractedPage] = None,
        use_cache: bool = True,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[PageSummary]:
        """Return mock summary."""
        self._notify_progress(progress_callback, ProgressStage.STARTED, "Özet oluşturuluyor...")
        
        page = extracted or self._last_extracted
        if not page:
            page = await self.extract_current_page(progress_callback)
        
        if not page:
            return None
        
        # Check cache
        if use_cache:
            cached = await self._cache.get(page.url)
            if cached:
                self._notify_progress(progress_callback, ProgressStage.CACHED, "Önbellekten alındı")
                return cached
        
        self._notify_progress(progress_callback, ProgressStage.SUMMARIZING, "Özetleniyor...")
        
        # Generate based on length
        if length == SummaryLength.TWEET:
            short_summary = "Tesla Model Z 2025'te 50K$'a geliyor. Musk: 'Pazarı değiştirecek'"
            detailed_summary = ""
            key_points = []
        elif length == SummaryLength.FULL:
            short_summary = "Tesla yeni Model Z'yi 2025'te piyasaya sürecek, fiyatı 50.000 dolar olacak."
            detailed_summary = (
                "Tesla CEO'su Elon Musk, şirketin yeni elektrikli araç modeli Model Z'yi duyurdu. "
                "Araç 2025 yılında piyasaya çıkacak ve yaklaşık 50.000 dolar fiyat etiketiyle satışa sunulacak.\n\n"
                "Musk, Model Z'nin elektrikli araç pazarını köklü bir şekilde değiştireceğini belirtti. "
                "Yeni model, daha uzun menzil ve gelişmiş otonom sürüş özellikleriyle dikkat çekiyor."
            )
            key_points = [
                "Tesla Model Z 2025'te çıkacak",
                "Fiyatı 50.000 dolar civarında",
                "Elektrikli araç pazarını değiştirecek",
                "Gelişmiş otonom sürüş özellikleri var",
            ]
        else:  # PARAGRAPH
            short_summary = "Tesla yeni Model Z'yi 2025'te piyasaya sürecek, fiyatı 50.000 dolar olacak."
            detailed_summary = ""
            key_points = []
        
        summary = PageSummary(
            title=page.title,
            url=page.url,
            short_summary=short_summary,
            detailed_summary=detailed_summary,
            key_points=key_points,
            source_content=page.content,
            length_type=length,
        )
        
        self._last_summary = summary
        self._history.add(summary)
        
        if use_cache:
            await self._cache.set(page.url, summary)
        
        self._notify_progress(progress_callback, ProgressStage.COMPLETED, "Tamamlandı")
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


def parse_summary_length(text: str) -> SummaryLength:
    """
    Parse summary length from user utterance.
    
    Examples:
        "kısa özetle" -> TWEET
        "detaylı anlat" -> FULL
        "özetle" -> PARAGRAPH (default)
    """
    text_lower = text.lower()
    
    # Short/tweet indicators
    if any(w in text_lower for w in ["kısa", "kisa", "tweet", "çok kısa", "cok kisa"]):
        return SummaryLength.TWEET
    
    # Full/detailed indicators
    if any(w in text_lower for w in ["detaylı", "detayli", "uzun", "tam", "full"]):
        return SummaryLength.FULL
    
    # Default to paragraph
    return SummaryLength.PARAGRAPH
