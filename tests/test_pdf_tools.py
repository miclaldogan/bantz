"""Tests for PDF tools — Issue #1211.

Covers:
- pdf_extract_text_tool (happy path, errors, limits)
- pdf_summarize_tool (summary hints, language)
- pdf_from_attachment_tool (download + extract, errors)
- Path validation (missing, not PDF, too large)
- Tool registration and metadata
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────
# Helpers — create minimal PDF files
# ─────────────────────────────────────────────────────────────────


def _create_test_pdf(tmp_path: Path, text: str = "Merhaba dünya", pages: int = 1) -> str:
    """Create a minimal PDF file for testing using fitz."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} — Sayfa {i + 1}", fontsize=12)
    
    pdf_path = str(tmp_path / "test.pdf")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _create_large_text_pdf(tmp_path: Path, char_count: int = 110_000) -> str:
    """Create a PDF with lots of text to test truncation."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    doc = fitz.open()
    # Each page gets a chunk of text
    chunk_size = 2000
    pages_needed = (char_count // chunk_size) + 1
    
    for i in range(min(pages_needed, 50)):  # cap at 50 pages
        page = doc.new_page()
        text = f"Test content page {i}. " * 100
        page.insert_text((72, 72), text[:chunk_size], fontsize=8)
    
    pdf_path = str(tmp_path / "large.pdf")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


# ─────────────────────────────────────────────────────────────────
# pdf.extract_text
# ─────────────────────────────────────────────────────────────────


class TestPdfExtractText:
    def test_extract_simple_pdf(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        pdf_path = _create_test_pdf(tmp_path, "Türkçe içerik testi")
        result = pdf_extract_text_tool(path=pdf_path)
        assert result["ok"] is True
        assert "Türkçe içerik testi" in result["text"]
        assert result["page_count"] == 1
        assert result["char_count"] > 0
        assert result["truncated"] is False

    def test_extract_multipage(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        pdf_path = _create_test_pdf(tmp_path, "Sayfa içeriği", pages=5)
        result = pdf_extract_text_tool(path=pdf_path)
        assert result["ok"] is True
        assert result["page_count"] == 5
        assert result["pages_read"] == 5

    def test_extract_with_max_pages(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        pdf_path = _create_test_pdf(tmp_path, "Kısa", pages=10)
        result = pdf_extract_text_tool(path=pdf_path, max_pages=3)
        assert result["ok"] is True
        assert result["pages_read"] == 3
        assert result["page_count"] == 10
        assert result["truncated"] is True

    def test_extract_no_path(self):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        result = pdf_extract_text_tool()
        assert result["ok"] is False
        assert result["error"] == "path_required"

    def test_extract_nonexistent_file(self):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        result = pdf_extract_text_tool(path="/tmp/nonexistent_file.pdf")
        assert result["ok"] is False
        assert result["error"] == "file_not_found"

    def test_extract_not_pdf(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Not a PDF")
        result = pdf_extract_text_tool(path=str(txt_file))
        assert result["ok"] is False
        assert result["error"] == "not_a_pdf"

    def test_extract_directory_path(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        result = pdf_extract_text_tool(path=str(tmp_path))
        assert result["ok"] is False
        assert result["error"] == "not_a_file"

    def test_filename_in_result(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_extract_text_tool
        pdf_path = _create_test_pdf(tmp_path)
        result = pdf_extract_text_tool(path=pdf_path)
        assert result["ok"] is True
        assert result["filename"] == "test.pdf"


# ─────────────────────────────────────────────────────────────────
# pdf.summarize
# ─────────────────────────────────────────────────────────────────


class TestPdfSummarize:
    def test_summarize_adds_hint(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_summarize_tool
        pdf_path = _create_test_pdf(tmp_path, "Özet testi")
        result = pdf_summarize_tool(path=pdf_path)
        assert result["ok"] is True
        assert "summary_hint" in result
        assert "Türkçe" in result["summary_hint"]
        assert result["language"] == "tr"

    def test_summarize_english(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_summarize_tool
        pdf_path = _create_test_pdf(tmp_path, "English summary test")
        result = pdf_summarize_tool(path=pdf_path, language="en")
        assert result["ok"] is True
        assert result["language"] == "en"

    def test_summarize_no_path(self):
        from bantz.tools.pdf_tools import pdf_summarize_tool
        result = pdf_summarize_tool()
        assert result["ok"] is False

    def test_summarize_max_pages_limited(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_summarize_tool
        pdf_path = _create_test_pdf(tmp_path, "Test", pages=10)
        result = pdf_summarize_tool(path=pdf_path, max_pages=3)
        assert result["ok"] is True
        assert result["pages_read"] == 3


# ─────────────────────────────────────────────────────────────────
# pdf.from_attachment
# ─────────────────────────────────────────────────────────────────


class TestPdfFromAttachment:
    def test_missing_params(self):
        from bantz.tools.pdf_tools import pdf_from_attachment_tool
        result = pdf_from_attachment_tool()
        assert result["ok"] is False
        assert "required" in result["error"]

    def test_missing_attachment_id(self):
        from bantz.tools.pdf_tools import pdf_from_attachment_tool
        result = pdf_from_attachment_tool(message_id="msg123")
        assert result["ok"] is False

    def test_download_failure(self):
        from bantz.tools.pdf_tools import pdf_from_attachment_tool

        with patch("bantz.google.gmail.gmail_download_attachment") as mock_dl:
            mock_dl.return_value = {"ok": False, "error": "not_found"}
            result = pdf_from_attachment_tool(
                message_id="msg123",
                attachment_id="att456",
            )
        assert result["ok"] is False
        assert "download_failed" in result["error"]

    def test_successful_download_and_extract(self, tmp_path):
        from bantz.tools.pdf_tools import pdf_from_attachment_tool

        # Create a test PDF to simulate download
        pdf_path = _create_test_pdf(tmp_path, "Gmail attachment content")

        def _mock_download(*, message_id, attachment_id, save_path, **kw):
            # Copy test PDF to save_path
            import shutil
            shutil.copy(pdf_path, save_path)
            return {
                "ok": True,
                "saved_path": save_path,
                "filename": "rapor.pdf",
                "mimeType": "application/pdf",
                "size_bytes": os.path.getsize(pdf_path),
            }

        with patch("bantz.google.gmail.gmail_download_attachment", side_effect=_mock_download):
            result = pdf_from_attachment_tool(
                message_id="msg123",
                attachment_id="att456",
                filename="rapor.pdf",
            )

        assert result["ok"] is True
        assert "Gmail attachment content" in result["text"]
        assert result["source"] == "gmail_attachment"
        assert result["message_id"] == "msg123"
        assert result["original_filename"] == "rapor.pdf"


# ─────────────────────────────────────────────────────────────────
# Path Validation
# ─────────────────────────────────────────────────────────────────


class TestPathValidation:
    def test_empty_path(self):
        from bantz.tools.pdf_tools import _validate_pdf_path
        ok, error = _validate_pdf_path("")
        assert ok is False
        assert error == "path_required"

    def test_nonexistent(self):
        from bantz.tools.pdf_tools import _validate_pdf_path
        ok, error = _validate_pdf_path("/tmp/does_not_exist.pdf")
        assert ok is False
        assert error == "file_not_found"

    def test_not_pdf_extension(self, tmp_path):
        from bantz.tools.pdf_tools import _validate_pdf_path
        txt = tmp_path / "file.txt"
        txt.write_text("hi")
        ok, error = _validate_pdf_path(str(txt))
        assert ok is False
        assert error == "not_a_pdf"

    def test_valid_pdf(self, tmp_path):
        from bantz.tools.pdf_tools import _validate_pdf_path
        pdf_path = _create_test_pdf(tmp_path)
        ok, error = _validate_pdf_path(pdf_path)
        assert ok is True
        assert error == ""


# ─────────────────────────────────────────────────────────────────
# Tool Registration & Metadata
# ─────────────────────────────────────────────────────────────────


class TestPdfToolRegistration:
    def test_all_handlers_callable(self):
        from bantz.tools.pdf_tools import (
            pdf_extract_text_tool,
            pdf_summarize_tool,
            pdf_from_attachment_tool,
        )
        assert callable(pdf_extract_text_tool)
        assert callable(pdf_summarize_tool)
        assert callable(pdf_from_attachment_tool)

    def test_extract_text_is_safe(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("pdf.extract_text") == ToolRisk.SAFE

    def test_summarize_is_safe(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("pdf.summarize") == ToolRisk.SAFE

    def test_from_attachment_is_moderate(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("pdf.from_attachment") == ToolRisk.MODERATE
