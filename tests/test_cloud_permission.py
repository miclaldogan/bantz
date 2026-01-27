"""
Tests for V2-7 Cloud Permission Flow (Issue #39).
"""

import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from bantz.document.cloud_permission import (
    ProcessingLocation,
    SensitivityCategory,
    CloudPermissionRequest,
    CloudPermissionFlow,
    create_cloud_permission_flow,
)
from bantz.document.ingestion import (
    DocumentType,
    DocumentMetadata,
    IngestedDocument,
)


def create_test_document(text: str, filename: str = "test.txt") -> IngestedDocument:
    """Helper to create test document."""
    metadata = DocumentMetadata(
        filename=filename,
        doc_type=DocumentType.TXT,
        page_count=1,
        word_count=len(text.split()),
    )
    return IngestedDocument(
        id="doc-test",
        metadata=metadata,
        raw_text=text,
    )


class TestProcessingLocation:
    """Tests for ProcessingLocation enum."""
    
    def test_locations_exist(self):
        """Test processing locations exist."""
        assert ProcessingLocation.LOCAL.value == "local"
        assert ProcessingLocation.CLOUD.value == "cloud"
        assert ProcessingLocation.HYBRID.value == "hybrid"


class TestCloudPermissionRequest:
    """Tests for CloudPermissionRequest."""
    
    def test_create_request(self):
        """Test creating permission request."""
        request = CloudPermissionRequest(
            id="req-1",
            document_id="doc-1",
            document_name="test.pdf",
            processing_type=ProcessingLocation.CLOUD,
            reason="Document analysis",
        )
        
        assert request.id == "req-1"
        assert request.document_id == "doc-1"
        assert request.processing_type == ProcessingLocation.CLOUD
    
    def test_request_to_dict(self):
        """Test request to_dict."""
        request = CloudPermissionRequest(
            id="req-1",
            document_id="doc-1",
            document_name="test.pdf",
            processing_type=ProcessingLocation.CLOUD,
            reason="Analysis",
        )
        
        data = request.to_dict()
        
        assert data["id"] == "req-1"
        assert data["processing_type"] == "cloud"


class TestCloudPermissionFlow:
    """Tests for CloudPermissionFlow."""
    
    def test_classify_financial_iban(self):
        """Test financial classification for IBAN."""
        flow = CloudPermissionFlow()
        doc = create_test_document("IBAN: TR123456789012345678901234")
        
        categories = flow.classify_sensitivity(doc)
        
        assert "financial" in categories
    
    def test_classify_financial_bank(self):
        """Test financial classification for bank terms."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Banka hesabı bilgileri")
        
        categories = flow.classify_sensitivity(doc)
        
        assert "financial" in categories
    
    def test_classify_personal_tc(self):
        """Test personal classification for TC kimlik."""
        flow = CloudPermissionFlow()
        doc = create_test_document("TC kimlik numarası: 12345678901")
        
        categories = flow.classify_sensitivity(doc)
        
        assert "personal" in categories
    
    def test_classify_medical(self):
        """Test medical classification."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Tanı: Grip. Tedavi: İstirahat ve ilaç.")
        
        categories = flow.classify_sensitivity(doc)
        
        assert "medical" in categories
    
    def test_classify_legal(self):
        """Test legal classification."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Mahkeme kararı ve dava dosyası")
        
        categories = flow.classify_sensitivity(doc)
        
        assert "legal" in categories
    
    def test_classify_confidential(self):
        """Test confidential classification."""
        flow = CloudPermissionFlow()
        doc = create_test_document("CONFIDENTIAL: Internal only information")
        
        categories = flow.classify_sensitivity(doc)
        
        assert "confidential" in categories
    
    def test_classify_no_sensitivity(self):
        """Test no sensitivity detected."""
        flow = CloudPermissionFlow()
        doc = create_test_document("This is a public document with no sensitive info.")
        
        categories = flow.classify_sensitivity(doc)
        
        assert len(categories) == 0
    
    def test_recommend_local_for_financial(self):
        """Test local recommendation for financial docs."""
        flow = CloudPermissionFlow()
        doc = create_test_document("IBAN: TR123456789012345678901234")
        
        location = flow.get_recommended_location(doc)
        
        assert location == ProcessingLocation.LOCAL
    
    def test_recommend_local_for_personal(self):
        """Test local recommendation for personal docs."""
        flow = CloudPermissionFlow()
        doc = create_test_document("TC kimlik numarası bilgileri")
        
        location = flow.get_recommended_location(doc)
        
        assert location == ProcessingLocation.LOCAL
    
    def test_recommend_hybrid_for_confidential(self):
        """Test hybrid recommendation for confidential docs."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Gizli: Şirket içi doküman")
        
        location = flow.get_recommended_location(doc)
        
        assert location == ProcessingLocation.HYBRID
    
    def test_recommend_cloud_for_public(self):
        """Test cloud recommendation for public docs."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Public announcement about the event.")
        
        location = flow.get_recommended_location(doc)
        
        assert location == ProcessingLocation.CLOUD
    
    @pytest.mark.asyncio
    async def test_local_no_permission_needed(self):
        """Test local processing needs no permission."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Any content")
        
        result = await flow.request_permission(doc, ProcessingLocation.LOCAL)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cloud_auto_denied_for_sensitive(self):
        """Test cloud auto-denied for sensitive content."""
        flow = CloudPermissionFlow(auto_local_for_sensitive=True)
        doc = create_test_document("TC kimlik: 12345678901")
        
        result = await flow.request_permission(doc, ProcessingLocation.CLOUD)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_cloud_auto_granted_for_public(self):
        """Test cloud auto-granted for public content."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Public information only")
        
        result = await flow.request_permission(doc, ProcessingLocation.CLOUD)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_permission_with_engine(self):
        """Test permission request with engine."""
        engine = Mock()
        engine.request = AsyncMock(return_value=True)
        
        flow = CloudPermissionFlow(
            permission_engine=engine,
            auto_local_for_sensitive=False,
        )
        doc = create_test_document("Some content")
        
        result = await flow.request_permission(doc, ProcessingLocation.CLOUD)
        
        assert result is True
        engine.request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_check_permission_local(self):
        """Test check permission for local."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Any content")
        
        result = await flow.check_permission(doc, ProcessingLocation.LOCAL)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_request_history(self):
        """Test request history is tracked."""
        flow = CloudPermissionFlow()
        doc = create_test_document("Public content")
        
        await flow.request_permission(doc, ProcessingLocation.CLOUD)
        
        history = flow.get_request_history()
        
        assert len(history) == 1
        assert history[0].document_id == doc.id
    
    @pytest.mark.asyncio
    async def test_request_history_filtered(self):
        """Test filtered request history."""
        flow = CloudPermissionFlow()
        doc1 = create_test_document("Content 1")
        doc1.id = "doc-1"
        doc2 = create_test_document("Content 2")
        doc2.id = "doc-2"
        
        await flow.request_permission(doc1, ProcessingLocation.CLOUD)
        await flow.request_permission(doc2, ProcessingLocation.CLOUD)
        
        history = flow.get_request_history(document_id="doc-1")
        
        assert len(history) == 1
        assert history[0].document_id == "doc-1"
    
    def test_get_stats(self):
        """Test getting statistics."""
        flow = CloudPermissionFlow()
        
        stats = flow.get_stats()
        
        assert "total_requests" in stats
        assert "granted" in stats
        assert "denied" in stats
        assert "pending" in stats
    
    @pytest.mark.asyncio
    async def test_stats_after_requests(self):
        """Test stats after processing requests."""
        flow = CloudPermissionFlow(auto_local_for_sensitive=False)
        doc1 = create_test_document("Public content")
        doc2 = create_test_document("Public info only")
        
        await flow.request_permission(doc1, ProcessingLocation.CLOUD)
        await flow.request_permission(doc2, ProcessingLocation.CLOUD)
        
        stats = flow.get_stats()
        
        assert stats["total_requests"] == 2
        assert stats["granted"] == 2
    
    def test_factory_function(self):
        """Test create_cloud_permission_flow factory."""
        flow = create_cloud_permission_flow(auto_local_for_sensitive=False)
        
        assert isinstance(flow, CloudPermissionFlow)
        assert flow._auto_local_for_sensitive is False
