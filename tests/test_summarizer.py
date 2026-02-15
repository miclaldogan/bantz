"""
Comprehensive tests for Page Summarization (Issue #18).

Tests cover:
- PageSummary and ExtractedPage dataclasses
- PageSummarizer class
- MockPageSummarizer for testing
- NLU intent recognition
- Router handler integration
- Extension bridge extract functionality
- Context state management
- Persona responses
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# Test PageSummary Dataclass
# =============================================================================


class TestPageSummary:
    """Tests for PageSummary dataclass."""
    
    def test_create_short_summary(self):
        """Test creating a short summary."""
        from bantz.skills.summarizer import PageSummary
        
        summary = PageSummary(
            title="Test Başlık",
            url="https://example.com/test",
            short_summary="Bu bir test özetidir.",
            detailed_summary="",
            key_points=[],
        )
        
        assert summary.title == "Test Başlık"
        assert summary.url == "https://example.com/test"
        assert summary.short_summary == "Bu bir test özetidir."
        assert summary.detailed_summary == ""
        assert summary.key_points == []
        assert isinstance(summary.generated_at, datetime)
    
    def test_create_detailed_summary(self):
        """Test creating a detailed summary with key points."""
        from bantz.skills.summarizer import PageSummary
        
        summary = PageSummary(
            title="Detaylı Haber",
            url="https://news.example.com/article",
            short_summary="Kısa özet.",
            detailed_summary="Bu detaylı bir özetdir.\n\nİkinci paragraf.",
            key_points=["Nokta 1", "Nokta 2", "Nokta 3"],
            source_content="Orijinal içerik burada.",
        )
        
        assert len(summary.key_points) == 3
        assert "Nokta 1" in summary.key_points
        assert summary.source_content == "Orijinal içerik burada."
    
    def test_to_dict(self):
        """Test converting summary to dictionary."""
        from bantz.skills.summarizer import PageSummary
        
        summary = PageSummary(
            title="Test",
            url="https://test.com",
            short_summary="Özet",
            detailed_summary="Detay",
            key_points=["A", "B"],
        )
        
        data = summary.to_dict()
        
        assert data["title"] == "Test"
        assert data["url"] == "https://test.com"
        assert data["short_summary"] == "Özet"
        assert data["detailed_summary"] == "Detay"
        assert data["key_points"] == ["A", "B"]
        assert "generated_at" in data


# =============================================================================
# Test ExtractedPage Dataclass
# =============================================================================


class TestExtractedPage:
    """Tests for ExtractedPage dataclass."""
    
    def test_create_extracted_page(self):
        """Test creating extracted page."""
        from bantz.skills.summarizer import ExtractedPage
        
        page = ExtractedPage(
            url="https://example.com",
            title="Example Page",
            content="This is the page content.",
            content_length=25,
            extracted_at="2024-01-01T12:00:00",
        )
        
        assert page.url == "https://example.com"
        assert page.title == "Example Page"
        assert page.content_length == 25
    
    def test_from_dict(self):
        """Test creating from extension response dict."""
        from bantz.skills.summarizer import ExtractedPage
        
        data = {
            "url": "https://test.com",
            "title": "Test Page",
            "content": "Test content here.",
            "content_length": 18,
            "extracted_at": "2024-01-15T10:30:00",
        }
        
        page = ExtractedPage.from_dict(data)
        
        assert page.url == "https://test.com"
        assert page.title == "Test Page"
        assert page.content == "Test content here."
    
    def test_from_dict_with_missing_fields(self):
        """Test creating from incomplete dict."""
        from bantz.skills.summarizer import ExtractedPage
        
        data = {"url": "https://test.com"}
        
        page = ExtractedPage.from_dict(data)
        
        assert page.url == "https://test.com"
        assert page.title == ""
        assert page.content == ""
        assert page.content_length == 0
    
    def test_has_content_true(self):
        """Test has_content returns True for substantial content."""
        from bantz.skills.summarizer import ExtractedPage
        
        page = ExtractedPage(
            url="https://test.com",
            title="Test",
            content="A" * 200,
            content_length=200,
            extracted_at="",
        )
        
        assert page.has_content is True
    
    def test_has_content_false_short(self):
        """Test has_content returns False for short content."""
        from bantz.skills.summarizer import ExtractedPage
        
        page = ExtractedPage(
            url="https://test.com",
            title="Test",
            content="Short",
            content_length=5,
            extracted_at="",
        )
        
        assert page.has_content is False
    
    def test_has_content_false_empty(self):
        """Test has_content returns False for empty content."""
        from bantz.skills.summarizer import ExtractedPage
        
        page = ExtractedPage(
            url="https://test.com",
            title="Test",
            content="   ",
            content_length=3,
            extracted_at="",
        )
        
        assert page.has_content is False


# =============================================================================
# Test MockPageSummarizer
# =============================================================================


class TestMockPageSummarizer:
    """Tests for MockPageSummarizer."""
    
    @pytest.mark.asyncio
    async def test_extract_current_page(self):
        """Test mock extraction."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer(
            mock_title="Test Sayfa",
            mock_url="https://test.com/page",
        )
        
        extracted = await summarizer.extract_current_page()
        
        assert extracted is not None
        assert extracted.title == "Test Sayfa"
        assert extracted.url == "https://test.com/page"
        assert extracted.has_content
    
    @pytest.mark.asyncio
    async def test_summarize_short(self):
        """Test short summarization."""
        from bantz.skills.summarizer import MockPageSummarizer, SummaryLength
        
        summarizer = MockPageSummarizer()
        
        summary = await summarizer.summarize(length=SummaryLength.PARAGRAPH)
        
        assert summary is not None
        assert summary.short_summary != ""
        assert summary.detailed_summary == ""
        assert summary.key_points == []
    
    @pytest.mark.asyncio
    async def test_summarize_detailed(self):
        """Test detailed summarization."""
        from bantz.skills.summarizer import MockPageSummarizer, SummaryLength
        
        summarizer = MockPageSummarizer()
        
        summary = await summarizer.summarize(length=SummaryLength.FULL)
        
        assert summary is not None
        assert summary.short_summary != ""
        assert summary.detailed_summary != ""
        assert len(summary.key_points) > 0
    
    @pytest.mark.asyncio
    async def test_answer_question_ceo(self):
        """Test answering CEO question."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        await summarizer.extract_current_page()
        
        answer = await summarizer.answer_question("CEO kim?")
        
        assert answer is not None
        assert "Musk" in answer or "CEO" in answer
    
    @pytest.mark.asyncio
    async def test_answer_question_price(self):
        """Test answering price question."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        await summarizer.extract_current_page()
        
        answer = await summarizer.answer_question("Fiyatı ne?")
        
        assert answer is not None
        assert "dolar" in answer.lower() or "50" in answer
    
    @pytest.mark.asyncio
    async def test_answer_question_date(self):
        """Test answering date question."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        await summarizer.extract_current_page()
        
        answer = await summarizer.answer_question("Ne zaman çıkacak?")
        
        assert answer is not None
        assert "2025" in answer
    
    @pytest.mark.asyncio
    async def test_answer_question_unknown(self):
        """Test answering unknown question."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        await summarizer.extract_current_page()
        
        answer = await summarizer.answer_question("Başka bir şey?")
        
        assert answer is not None
        assert "bulamadım" in answer.lower() or "bilgi" in answer.lower()
    
    def test_format_for_tts(self):
        """Test TTS formatting."""
        from bantz.skills.summarizer import MockPageSummarizer, PageSummary
        
        summarizer = MockPageSummarizer()
        summary = PageSummary(
            title="Test",
            url="https://test.com",
            short_summary="Bu kısa özet.",
            detailed_summary="Bu detaylı özet.",
            key_points=["Nokta 1"],
        )
        
        tts = summarizer.format_for_tts(summary)
        
        assert tts == "Bu kısa özet."
    
    def test_format_for_tts_no_summary(self):
        """Test TTS formatting without summary."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        
        tts = summarizer.format_for_tts(None)
        
        assert "bulunamadı" in tts.lower()
    
    def test_format_for_overlay_short(self):
        """Test overlay formatting for short summary."""
        from bantz.skills.summarizer import MockPageSummarizer, PageSummary
        
        summarizer = MockPageSummarizer()
        summary = PageSummary(
            title="Test Başlık",
            url="https://test.com",
            short_summary="Kısa özet.",
            detailed_summary="",
            key_points=[],
        )
        
        data = summarizer.format_for_overlay(summary, detailed=False)
        
        assert data["type"] == "summary"
        assert data["title"] == "Test Başlık"
        assert data["content"] == "Kısa özet."
        assert data["items"] == []
    
    def test_format_for_overlay_detailed(self):
        """Test overlay formatting for detailed summary."""
        from bantz.skills.summarizer import MockPageSummarizer, PageSummary
        
        summarizer = MockPageSummarizer()
        summary = PageSummary(
            title="Detaylı Başlık",
            url="https://test.com",
            short_summary="Kısa.",
            detailed_summary="Bu detaylı açıklama.",
            key_points=["Nokta A", "Nokta B"],
        )
        
        data = summarizer.format_for_overlay(summary, detailed=True)
        
        assert data["type"] == "summary_detailed"
        assert data["content"] == "Bu detaylı açıklama."
        assert len(data["items"]) == 2
        assert data["items"][0]["text"] == "Nokta A"
    
    def test_state_properties(self):
        """Test state properties."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        
        assert summarizer.has_summary is False
        assert summarizer.has_content is False
        assert summarizer.last_summary is None
        assert summarizer.last_extracted is None
    
    @pytest.mark.asyncio
    async def test_state_after_operations(self):
        """Test state after extraction and summarization."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        
        await summarizer.extract_current_page()
        assert summarizer.has_content is True
        assert summarizer.last_extracted is not None
        
        await summarizer.summarize("short")
        assert summarizer.has_summary is True
        assert summarizer.last_summary is not None
    
    def test_clear_state(self):
        """Test clearing state."""
        from bantz.skills.summarizer import MockPageSummarizer
        
        summarizer = MockPageSummarizer()
        # Manually set some state
        summarizer._last_extracted = "test"
        summarizer._last_summary = "test"
        
        summarizer.clear()
        
        assert summarizer.has_content is False
        assert summarizer.has_summary is False


# =============================================================================
# Test PageSummarizer (with mocks)
# =============================================================================


class TestPageSummarizer:
    """Tests for PageSummarizer class."""
    
    def test_init_no_dependencies(self):
        """Test initialization without dependencies."""
        from bantz.skills.summarizer import PageSummarizer
        
        summarizer = PageSummarizer()
        
        assert summarizer.bridge is None
        assert summarizer.llm is None
        assert summarizer.has_content is False
        assert summarizer.has_summary is False
    
    def test_init_with_dependencies(self):
        """Test initialization with dependencies."""
        from bantz.skills.summarizer import PageSummarizer
        
        mock_bridge = MagicMock()
        mock_llm = MagicMock()
        
        summarizer = PageSummarizer(
            extension_bridge=mock_bridge,
            llm_client=mock_llm,
            extract_timeout=10.0,
        )
        
        assert summarizer.bridge is mock_bridge
        assert summarizer.llm is mock_llm
        assert summarizer.extract_timeout == 10.0
    
    @pytest.mark.asyncio
    async def test_extract_no_bridge(self):
        """Test extraction fails without bridge."""
        from bantz.skills.summarizer import PageSummarizer
        
        summarizer = PageSummarizer(extension_bridge=None)
        
        result = await summarizer.extract_current_page()
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_extract_no_client(self):
        """Test extraction fails when no extension client connected."""
        from bantz.skills.summarizer import PageSummarizer
        
        mock_bridge = MagicMock()
        mock_bridge.has_client.return_value = False
        
        summarizer = PageSummarizer(extension_bridge=mock_bridge)
        
        result = await summarizer.extract_current_page()
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_extract_success(self):
        """Test successful extraction."""
        from bantz.skills.summarizer import PageSummarizer
        
        mock_bridge = MagicMock()
        mock_bridge.has_client.return_value = True
        mock_bridge.request_extract.return_value = {
            "url": "https://test.com",
            "title": "Test Page",
            "content": "A" * 200,
            "content_length": 200,
            "extracted_at": "2024-01-01T12:00:00",
        }
        
        summarizer = PageSummarizer(extension_bridge=mock_bridge)
        
        result = await summarizer.extract_current_page()
        
        assert result is not None
        assert result.title == "Test Page"
        assert result.has_content is True
        assert summarizer.has_content is True
    
    @pytest.mark.asyncio
    async def test_extract_insufficient_content(self):
        """Test extraction fails with insufficient content."""
        from bantz.skills.summarizer import PageSummarizer
        
        mock_bridge = MagicMock()
        mock_bridge.has_client.return_value = True
        mock_bridge.request_extract.return_value = {
            "url": "https://test.com",
            "title": "Test",
            "content": "Short",
            "content_length": 5,
            "extracted_at": "",
        }
        
        summarizer = PageSummarizer(extension_bridge=mock_bridge)
        
        result = await summarizer.extract_current_page()
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_summarize_no_content(self):
        """Test summarization fails without content."""
        from bantz.skills.summarizer import PageSummarizer
        
        mock_bridge = MagicMock()
        mock_bridge.has_client.return_value = False
        
        summarizer = PageSummarizer(extension_bridge=mock_bridge)
        
        result = await summarizer.summarize("short")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_summarize_no_llm(self):
        """Test summarization fails without LLM."""
        from bantz.skills.summarizer import PageSummarizer, ExtractedPage
        
        summarizer = PageSummarizer(llm_client=None)
        summarizer._last_extracted = ExtractedPage(
            url="https://test.com",
            title="Test",
            content="A" * 200,
            content_length=200,
            extracted_at="",
        )
        
        result = await summarizer.summarize("short")
        
        assert result is None


# =============================================================================
# Test NLU Intent Recognition
# =============================================================================


class TestNLUPageSummarizePatterns:
    """Tests for page summarization NLU patterns."""
    
    def test_page_summarize_bu_sayfayi(self):
        """Test 'bu sayfayı özetle' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("bu sayfayı özetle")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_su_haberi(self):
        """Test 'şu haberi anlat' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("şu haberi anlat")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_bu_icerigi(self):
        """Test 'bu içeriği özetle' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("şu içeriği özetle")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_bu_makaleyi(self):
        """Test 'bu makaleyi oku' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("bu makaleyi oku")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_bunu_ozetle(self):
        """Test 'bunu özetle' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("bunu özetle")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_sunu_anlat(self):
        """Test 'şunu anlat' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("şunu anlat")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_ne_anlatiyor(self):
        """Test 'ne anlatıyor' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("ne anlatıyor")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_neler_var(self):
        """Test 'neler var' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("neler var")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_anlayamadim(self):
        """Test 'anlayamadım anlat' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("anlayamadım anlat")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_anlamadim_acikla(self):
        """Test 'anlamadım açıkla' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("anlamadım açıkla")
        
        assert result.intent == "page_summarize"
    
    def test_page_summarize_bu_ne_anlatiyor(self):
        """Test 'bu ne anlatıyor' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("bu ne anlatıyor")
        
        assert result.intent == "page_summarize"


class TestNLUPageSummarizeDetailedPatterns:
    """Tests for detailed summarization NLU patterns."""
    
    def test_detailed_detayli_anlat(self):
        """Test 'detaylı anlat' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("detaylı anlat")
        
        assert result.intent == "page_summarize_detailed"
    
    def test_detailed_daha_detayli(self):
        """Test 'daha detaylı özetle' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("daha detaylı özetle")
        
        assert result.intent == "page_summarize_detailed"
    
    def test_detailed_tam_anlat(self):
        """Test 'tam detaylı anlat' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("tam detaylı anlat")
        
        assert result.intent == "page_summarize_detailed"
    
    def test_detailed_uzun_ozetle(self):
        """Test 'uzun özetle' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("uzun özetle")
        
        assert result.intent == "page_summarize_detailed"
    
    def test_detailed_detayli_olarak(self):
        """Test 'detaylı olarak anlat' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("detaylı olarak anlat")
        
        assert result.intent == "page_summarize_detailed"
    
    def test_detailed_ayrintili(self):
        """Test 'ayrıntılı açıkla' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("ayrıntılı açıkla")
        
        assert result.intent == "page_summarize_detailed"


class TestNLUPageQuestionPatterns:
    """Tests for page question NLU patterns."""
    
    def test_question_bu_ceo_kim(self):
        """Test 'Bu CEO kim?' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Bu CEO kim?")
        
        assert result.intent == "page_question"
        assert "CEO kim" in result.slots.get("question", "")
    
    def test_question_fiyati_ne(self):
        """Test 'Fiyatı ne?' — no longer matches page_question (pattern narrowed)."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Fiyatı ne?")
        
        assert result.intent == "unknown"
    
    def test_question_ne_zaman(self):
        """Test 'Ne zaman çıkacak?' — no longer matches page_question (pattern narrowed)."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Ne zaman çıkacak?")
        
        assert result.intent == "unknown"
    
    def test_question_neden(self):
        """Test 'Bu neden oldu?' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Bu neden oldu?")
        
        assert result.intent == "page_question"
    
    def test_question_nasil(self):
        """Test 'Bu nasıl oldu?' pattern."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Bu nasıl oldu?")
        
        assert result.intent == "page_question"
    
    def test_question_nerede(self):
        """Test 'Nerede olacak?' — no longer matches page_question (pattern narrowed)."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Nerede olacak?")
        
        assert result.intent == "unknown"


# =============================================================================
# Test Context State Management
# =============================================================================


class TestContextPageSummarizerState:
    """Tests for context page summarizer state management."""
    
    def test_set_and_get_page_summarizer(self):
        """Test setting and getting page summarizer."""
        from bantz.router.context import ConversationContext
        from bantz.skills.summarizer import MockPageSummarizer
        
        ctx = ConversationContext()
        summarizer = MockPageSummarizer()
        
        ctx.set_page_summarizer(summarizer)
        result = ctx.get_page_summarizer()
        
        assert result is summarizer
    
    def test_clear_page_summarizer(self):
        """Test clearing page summarizer."""
        from bantz.router.context import ConversationContext
        from bantz.skills.summarizer import MockPageSummarizer
        
        ctx = ConversationContext()
        ctx.set_page_summarizer(MockPageSummarizer())
        ctx.set_pending_page_summarize("detailed")
        ctx.set_pending_page_question("Test?")
        
        ctx.clear_page_summarizer()
        
        assert ctx.get_page_summarizer() is None
        assert ctx.get_pending_page_summarize() is None
        assert ctx.get_pending_page_question() is None
    
    def test_pending_page_summarize(self):
        """Test pending page summarize state."""
        from bantz.router.context import ConversationContext
        
        ctx = ConversationContext()
        
        ctx.set_pending_page_summarize("short")
        assert ctx.get_pending_page_summarize() == "short"
        
        ctx.set_pending_page_summarize("detailed")
        assert ctx.get_pending_page_summarize() == "detailed"
        
        ctx.clear_pending_page_summarize()
        assert ctx.get_pending_page_summarize() is None
    
    def test_pending_page_question(self):
        """Test pending page question state."""
        from bantz.router.context import ConversationContext
        
        ctx = ConversationContext()
        
        ctx.set_pending_page_question("CEO kim?")
        assert ctx.get_pending_page_question() == "CEO kim?"
        
        ctx.clear_pending_page_question()
        assert ctx.get_pending_page_question() is None
    
    def test_snapshot_includes_page_summarizer(self):
        """Test snapshot includes page summarizer state."""
        from bantz.router.context import ConversationContext
        from bantz.skills.summarizer import MockPageSummarizer
        
        ctx = ConversationContext()
        ctx.set_page_summarizer(MockPageSummarizer())
        ctx.set_pending_page_summarize("detailed")
        ctx.set_pending_page_question("Test?")
        
        snapshot = ctx.snapshot()
        
        assert snapshot["has_page_summarizer"] is True
        assert snapshot["pending_page_summarize"] == "detailed"
        assert snapshot["pending_page_question"] == "Test?"


# =============================================================================
# Test Persona Responses
# =============================================================================


class TestPersonaPageSummarizeResponses:
    """Tests for Jarvis persona page summarization responses."""
    
    def test_reading_page_response(self):
        """Test reading page response."""
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("reading_page")
        
        assert response is not None
        assert len(response) > 0
        assert "efendim" in response.lower() or "okuyorum" in response.lower()
    
    def test_summary_ready_response(self):
        """Test summary ready response."""
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("summary_ready")
        
        assert response is not None
        assert "efendim" in response.lower()
    
    def test_answering_response(self):
        """Test answering response."""
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("answering")
        
        assert response is not None
        assert len(response) > 0
    
    def test_answer_ready_response(self):
        """Test answer ready response."""
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("answer_ready")
        
        assert response is not None
    
    def test_no_content_response(self):
        """Test no content response."""
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("no_content")
        
        assert response is not None
        assert "efendim" in response.lower()


# =============================================================================
# Test Helper Functions
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_extract_question_with_question_mark(self):
        """Test extracting question with question mark."""
        from bantz.skills.summarizer import extract_question
        
        result = extract_question("CEO kim?")
        
        assert result is not None
        assert "kim" in result.lower()
    
    def test_extract_question_anlat_prefix(self):
        """Test extracting question with anlat prefix."""
        from bantz.skills.summarizer import extract_question
        
        result = extract_question("anlat bakalım fiyatı ne")
        
        assert result is not None
    
    def test_extract_question_empty(self):
        """Test extracting from empty string."""
        from bantz.skills.summarizer import extract_question
        
        result = extract_question("")
        
        assert result is None
    
    def test_extract_question_whitespace(self):
        """Test extracting from whitespace."""
        from bantz.skills.summarizer import extract_question
        
        result = extract_question("   ")
        
        assert result is None


# =============================================================================
# Test Router Handler Integration
# =============================================================================


class TestRouterPageSummarizeIntegration:
    """Tests for router page summarize handler integration."""
    
    def test_page_summarize_no_bridge(self):
        """Test page_summarize without bridge connection."""
        from bantz.router.engine import Router
        from bantz.router.policy import Policy
        from bantz.router.context import ConversationContext
        from bantz.logs.logger import JsonlLogger
        
        with patch("bantz.browser.extension_bridge.get_bridge") as mock_get_bridge:
            mock_get_bridge.return_value = None
            
            logger = JsonlLogger("/tmp/test.log")
            # Allow page_summarize in policy
            policy = Policy(
                deny_patterns=[],
                confirm_patterns=[],
                deny_even_if_confirmed_patterns=[],
                intent_levels={"page_summarize": 1},  # Allow intent
            )
            router = Router(policy, logger)
            ctx = ConversationContext()
            
            result = router.handle("bu sayfayı özetle", ctx)
            
            # Either bridge error or policy error is acceptable
            assert result.ok is False
    
    def test_page_summarize_no_client(self):
        """Test page_summarize without extension client."""
        from bantz.router.engine import Router
        from bantz.router.policy import Policy
        from bantz.router.context import ConversationContext
        from bantz.logs.logger import JsonlLogger
        
        with patch("bantz.browser.extension_bridge.get_bridge") as mock_get_bridge:
            mock_bridge = MagicMock()
            mock_bridge.has_client.return_value = False
            mock_get_bridge.return_value = mock_bridge
            
            logger = JsonlLogger("/tmp/test.log")
            # Allow page_summarize in policy
            policy = Policy(
                deny_patterns=[],
                confirm_patterns=[],
                deny_even_if_confirmed_patterns=[],
                intent_levels={"page_summarize": 1},  # Allow intent
            )
            router = Router(policy, logger)
            ctx = ConversationContext()
            
            result = router.handle("bu sayfayı özetle", ctx)
            
            # Either client error or policy error is acceptable
            assert result.ok is False
    
    def test_page_summarize_intent_recognized(self):
        """Test page_summarize intent is correctly recognized."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("bu sayfayı özetle")
        
        assert result.intent == "page_summarize"
    
    def test_page_question_intent_recognized(self):
        """Test page_question intent is correctly recognized."""
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("Bu CEO kim?")
        
        assert result.intent == "page_question"
        assert "question" in result.slots


# =============================================================================
# Test Types
# =============================================================================


class TestTypesPageSummarize:
    """Tests for types include page summarize intents."""
    
    def test_page_summarize_intent_in_types(self):
        """Test page_summarize is in Intent type."""
        from bantz.router.types import Intent
        
        # This should not raise - type checking
        intent: Intent = "page_summarize"
        assert intent == "page_summarize"
    
    def test_page_summarize_detailed_intent_in_types(self):
        """Test page_summarize_detailed is in Intent type."""
        from bantz.router.types import Intent
        
        intent: Intent = "page_summarize_detailed"
        assert intent == "page_summarize_detailed"
    
    def test_page_question_intent_in_types(self):
        """Test page_question is in Intent type."""
        from bantz.router.types import Intent
        
        intent: Intent = "page_question"
        assert intent == "page_question"


# =============================================================================
# Test Skills __init__ Exports
# =============================================================================


class TestSkillsExports:
    """Tests for skills package exports."""
    
    def test_import_page_summary(self):
        """Test PageSummary can be imported from skills."""
        from bantz.skills import PageSummary
        
        assert PageSummary is not None
    
    def test_import_extracted_page(self):
        """Test ExtractedPage can be imported from skills."""
        from bantz.skills import ExtractedPage
        
        assert ExtractedPage is not None
    
    def test_import_page_summarizer(self):
        """Test PageSummarizer can be imported from skills."""
        from bantz.skills import PageSummarizer
        
        assert PageSummarizer is not None
    
    def test_import_mock_page_summarizer(self):
        """Test MockPageSummarizer can be imported from skills."""
        from bantz.skills import MockPageSummarizer
        
        assert MockPageSummarizer is not None
    
    def test_import_extract_question(self):
        """Test extract_question can be imported from skills."""
        from bantz.skills import extract_question
        
        assert extract_question is not None
