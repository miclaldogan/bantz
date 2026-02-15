"""Semantic File Search skill — local file indexing and semantic retrieval.

Issue #1299: Gelecek Yetenekler — Faz G+

Status: PLANNED — skeleton only.
Dependencies: Ingest Store (EPIC 1).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Supported file types for content extraction
SUPPORTED_TYPES = {".pdf", ".docx", ".txt", ".md", ".rst", ".csv"}

# Default directories to index
DEFAULT_DIRS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Downloads",
]


@dataclass
class FileResult:
    """Search result entry."""

    path: str
    filename: str
    score: float          # Similarity score 0-1
    snippet: str = ""     # Relevant text snippet
    file_type: str = ""
    modified: Optional[datetime] = None
    size_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "path": self.path,
            "filename": self.filename,
            "score": round(self.score, 3),
            "file_type": self.file_type,
        }
        if self.snippet:
            d["snippet"] = self.snippet[:200]
        if self.modified:
            d["modified"] = self.modified.isoformat()
        if self.size_bytes:
            d["size_kb"] = round(self.size_bytes / 1024, 1)
        return d


@dataclass
class IndexStats:
    """File index statistics."""

    total_files: int = 0
    indexed_files: int = 0
    total_size_mb: float = 0.0
    last_indexed: Optional[datetime] = None
    directories: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "total_size_mb": round(self.total_size_mb, 1),
            "last_indexed": (
                self.last_indexed.isoformat() if self.last_indexed else None
            ),
            "directories": self.directories,
        }


class FileSearchEngine(ABC):
    """Abstract base for semantic file search.

    Concrete implementation will be activated when
    Ingest Store EPIC is complete.
    """

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        file_types: Optional[List[str]] = None,
        directory: Optional[str] = None,
        limit: int = 10,
    ) -> List[FileResult]:
        """Semantic search across indexed files."""
        ...

    @abstractmethod
    def index_directory(
        self,
        directory: str,
        *,
        force: bool = False,
    ) -> IndexStats:
        """Index files in a directory for search."""
        ...

    @abstractmethod
    def get_stats(self) -> IndexStats:
        """Get current index statistics."""
        ...


class PlaceholderFileSearch(FileSearchEngine):
    """Placeholder — returns stub data until Ingest Store is ready."""

    def search(
        self,
        query: str,
        *,
        file_types: Optional[List[str]] = None,
        directory: Optional[str] = None,
        limit: int = 10,
    ) -> List[FileResult]:
        logger.info("[FileSearch] search called — stub mode: %s", query)
        return []

    def index_directory(
        self,
        directory: str,
        *,
        force: bool = False,
    ) -> IndexStats:
        return IndexStats(
            directories=[directory],
        )

    def get_stats(self) -> IndexStats:
        return IndexStats()
