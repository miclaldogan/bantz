"""
Cloud permission flow for document processing.

Manages permission requests for cloud-based document analysis.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from bantz.document.ingestion import IngestedDocument


class PermissionEngine(Protocol):
    """Protocol for permission engines."""
    
    async def request(self, category: str, reason: str) -> bool:
        """Request permission for an action."""
        ...
    
    async def check(self, category: str) -> bool:
        """Check if permission is already granted."""
        ...


class ProcessingLocation(Enum):
    """Where document processing should occur."""
    
    LOCAL = "local"       # Tamamen local işleme
    CLOUD = "cloud"       # Cloud API kullanımı (GPT-4, Claude, etc.)
    HYBRID = "hybrid"     # Extraction local, understanding cloud


class SensitivityCategory(Enum):
    """Document sensitivity categories."""
    
    FINANCIAL = "financial"
    PERSONAL = "personal"
    MEDICAL = "medical"
    LEGAL = "legal"
    CONFIDENTIAL = "confidential"
    PUBLIC = "public"


@dataclass
class CloudPermissionRequest:
    """A request for cloud processing permission."""
    
    id: str
    """Request ID."""
    
    document_id: str
    """Document being processed."""
    
    document_name: str
    """Document filename."""
    
    processing_type: ProcessingLocation
    """Requested processing location."""
    
    reason: str
    """Why cloud processing is needed."""
    
    data_categories: list[str] = field(default_factory=list)
    """Detected sensitivity categories."""
    
    created_at: datetime = field(default_factory=datetime.now)
    """When the request was created."""
    
    granted: Optional[bool] = None
    """Whether permission was granted."""
    
    granted_at: Optional[datetime] = None
    """When permission was granted/denied."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "processing_type": self.processing_type.value,
            "reason": self.reason,
            "data_categories": self.data_categories,
            "created_at": self.created_at.isoformat(),
            "granted": self.granted,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
        }


class CloudPermissionFlow:
    """
    Manages permission flow for cloud document processing.
    
    Classifies document sensitivity and requests appropriate
    permissions before sending data to cloud services.
    """
    
    # Sensitivity detection patterns
    SENSITIVE_PATTERNS: dict[str, list[str]] = {
        "financial": [
            r"\bIBAN\b",
            r"\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b",  # Turkish IBAN
            r"\bbanka\b",
            r"\bkredi\b",
            r"\bfatura\b",
            r"\bödeme\b",
            r"\bbakiye\b",
            r"\bhesap\s*no\b",
            r"\bvisa\b",
            r"\bmastercard\b",
            r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # Credit card
        ],
        "personal": [
            r"\bTC\s*kimlik\b",
            r"\b\d{11}\b",  # TC Kimlik No
            r"\bdoğum\s*tarihi\b",
            r"\bev\s*adresi\b",
            r"\bcep\s*telefon[u]?\b",
            r"\be-?posta\b",
            r"\bSSN\b",
            r"\bpassport\b",
            r"\bpasaport\b",
        ],
        "medical": [
            r"\btanı\b",
            r"\bilaç\b",
            r"\btedavi\b",
            r"\bhastane\b",
            r"\bdoktor\b",
            r"\breçete\b",
            r"\bteşhis\b",
            r"\bmuayene\b",
            r"\brapor\b",
            r"\bsağlık\b",
        ],
        "legal": [
            r"\bdava\b",
            r"\bmahkeme\b",
            r"\bavukat\b",
            r"\bsözleşme\b",
            r"\bvekaletname\b",
            r"\bnoter\b",
            r"\byargı\b",
            r"\bhukuk\b",
        ],
        "confidential": [
            r"\bgizli\b",
            r"\bconfidential\b",
            r"\bprivate\b",
            r"\binternal\s*only\b",
            r"\bsadece\s*iç\s*kullanım\b",
            r"\bşirket\s*sırrı\b",
            r"\btrade\s*secret\b",
        ],
    }
    
    def __init__(
        self,
        permission_engine: Optional[PermissionEngine] = None,
        auto_local_for_sensitive: bool = True,
    ):
        """
        Initialize the cloud permission flow.
        
        Args:
            permission_engine: Engine for requesting user permissions.
            auto_local_for_sensitive: Auto-recommend local for sensitive docs.
        """
        self._permission_engine = permission_engine
        self._auto_local_for_sensitive = auto_local_for_sensitive
        self._pending_requests: dict[str, CloudPermissionRequest] = {}
        self._request_history: list[CloudPermissionRequest] = []
        
        # Compile patterns
        self._patterns: dict[str, list[re.Pattern]] = {
            category: [re.compile(p, re.IGNORECASE) for p in patterns]
            for category, patterns in self.SENSITIVE_PATTERNS.items()
        }
    
    def classify_sensitivity(
        self,
        document: "IngestedDocument",
    ) -> list[str]:
        """
        Classify document sensitivity categories.
        
        Args:
            document: Document to analyze.
            
        Returns:
            List of detected sensitivity categories.
        """
        categories = []
        text = document.raw_text
        
        for category, patterns in self._patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    categories.append(category)
                    break  # One match per category is enough
        
        return categories
    
    def get_recommended_location(
        self,
        document: "IngestedDocument",
    ) -> ProcessingLocation:
        """
        Get recommended processing location based on sensitivity.
        
        Args:
            document: Document to analyze.
            
        Returns:
            Recommended processing location.
        """
        categories = self.classify_sensitivity(document)
        
        # High sensitivity → local only
        high_sensitivity = {"financial", "personal", "medical", "legal"}
        if any(cat in high_sensitivity for cat in categories):
            return ProcessingLocation.LOCAL
        
        # Medium sensitivity → hybrid
        if "confidential" in categories:
            return ProcessingLocation.HYBRID
        
        # No sensitivity detected → cloud ok
        return ProcessingLocation.CLOUD
    
    async def request_permission(
        self,
        document: "IngestedDocument",
        processing: ProcessingLocation,
        reason: str = "Advanced document analysis",
    ) -> bool:
        """
        Request permission for cloud processing.
        
        Args:
            document: Document to process.
            processing: Requested processing location.
            reason: Why cloud processing is needed.
            
        Returns:
            True if permission is granted.
        """
        import uuid
        
        # Local processing doesn't need permission
        if processing == ProcessingLocation.LOCAL:
            return True
        
        # Classify sensitivity
        categories = self.classify_sensitivity(document)
        
        # Auto-deny for very sensitive documents if configured
        if self._auto_local_for_sensitive:
            high_sensitivity = {"financial", "personal", "medical"}
            if any(cat in high_sensitivity for cat in categories):
                return False
        
        # Create permission request
        request = CloudPermissionRequest(
            id=str(uuid.uuid4()),
            document_id=document.id,
            document_name=document.metadata.filename,
            processing_type=processing,
            reason=reason,
            data_categories=categories,
        )
        
        self._pending_requests[request.id] = request
        
        # Request from permission engine
        if self._permission_engine:
            category = f"cloud_processing:{processing.value}"
            full_reason = (
                f"{reason}\n"
                f"Document: {document.metadata.filename}\n"
                f"Detected categories: {', '.join(categories) or 'none'}"
            )
            
            granted = await self._permission_engine.request(category, full_reason)
        else:
            # No permission engine - auto-grant for non-sensitive
            granted = len(categories) == 0
        
        # Update request
        request.granted = granted
        request.granted_at = datetime.now()
        
        # Move to history
        del self._pending_requests[request.id]
        self._request_history.append(request)
        
        return granted
    
    async def check_permission(
        self,
        document: "IngestedDocument",
        processing: ProcessingLocation,
    ) -> bool:
        """
        Check if permission is already granted.
        
        Args:
            document: Document to check.
            processing: Processing location to check.
            
        Returns:
            True if permission is already granted.
        """
        if processing == ProcessingLocation.LOCAL:
            return True
        
        if self._permission_engine:
            category = f"cloud_processing:{processing.value}"
            return await self._permission_engine.check(category)
        
        # Check history
        for request in reversed(self._request_history):
            if (request.document_id == document.id and
                request.processing_type == processing and
                request.granted is True):
                return True
        
        return False
    
    def get_pending_requests(self) -> list[CloudPermissionRequest]:
        """Get pending permission requests."""
        return list(self._pending_requests.values())
    
    def get_request_history(
        self,
        document_id: Optional[str] = None,
    ) -> list[CloudPermissionRequest]:
        """
        Get permission request history.
        
        Args:
            document_id: Filter by document ID.
            
        Returns:
            List of historical requests.
        """
        if document_id:
            return [r for r in self._request_history if r.document_id == document_id]
        return list(self._request_history)
    
    def get_stats(self) -> dict:
        """Get permission flow statistics."""
        total = len(self._request_history)
        granted = sum(1 for r in self._request_history if r.granted)
        denied = sum(1 for r in self._request_history if r.granted is False)
        
        return {
            "total_requests": total,
            "granted": granted,
            "denied": denied,
            "pending": len(self._pending_requests),
            "grant_rate": (granted / total * 100) if total > 0 else 0,
        }


def create_cloud_permission_flow(
    permission_engine: Optional[PermissionEngine] = None,
    auto_local_for_sensitive: bool = True,
) -> CloudPermissionFlow:
    """
    Factory function to create a cloud permission flow.
    
    Args:
        permission_engine: Engine for requesting user permissions.
        auto_local_for_sensitive: Auto-recommend local for sensitive docs.
        
    Returns:
        Configured CloudPermissionFlow instance.
    """
    return CloudPermissionFlow(
        permission_engine=permission_engine,
        auto_local_for_sensitive=auto_local_for_sensitive,
    )
