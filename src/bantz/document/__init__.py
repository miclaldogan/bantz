"""
V2-7: Document/PDF/DOC understanding pipeline + hybrid cloud gate.

This module provides document ingestion, parsing, structure extraction,
checklist generation, and cloud permission flow.
"""

from bantz.document.ingestion import (
    DocumentType,
    DocumentMetadata,
    IngestedDocument,
    DocumentIngester,
    create_document_ingester,
)

from bantz.document.structure import (
    StructureType,
    StructureElement,
    TableData,
    DocumentStructure,
    StructureExtractor,
    create_structure_extractor,
)

from bantz.document.checklist import (
    ChecklistItem,
    Checklist,
    ChecklistGenerator,
    create_checklist_generator,
)

from bantz.document.cloud_permission import (
    ProcessingLocation,
    CloudPermissionRequest,
    CloudPermissionFlow,
    create_cloud_permission_flow,
)

from bantz.document.parsers import (
    DocumentParser,
    PDFParser,
    DOCXParser,
    TXTParser,
    MDParser,
)

__all__ = [
    # Ingestion
    "DocumentType",
    "DocumentMetadata",
    "IngestedDocument",
    "DocumentIngester",
    "create_document_ingester",
    # Structure
    "StructureType",
    "StructureElement",
    "TableData",
    "DocumentStructure",
    "StructureExtractor",
    "create_structure_extractor",
    # Checklist
    "ChecklistItem",
    "Checklist",
    "ChecklistGenerator",
    "create_checklist_generator",
    # Cloud Permission
    "ProcessingLocation",
    "CloudPermissionRequest",
    "CloudPermissionFlow",
    "create_cloud_permission_flow",
    # Parsers
    "DocumentParser",
    "PDFParser",
    "DOCXParser",
    "TXTParser",
    "MDParser",
]
