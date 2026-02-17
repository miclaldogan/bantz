"""PDF Tools — Issue #1211.

Provides PDF text extraction and summarization for email attachments.
Uses PyMuPDF (fitz) for fast, Unicode-aware text extraction.

Tools:
- pdf.extract_text: Extract text content from a PDF file
- pdf.summarize: Extract text and generate a summary via LLM
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Limits
_MAX_PDF_SIZE_MB = 50
_MAX_PAGES = 200
_MAX_TEXT_CHARS = 100_000  # ~25k tokens


def _validate_pdf_path(path: str) -> tuple[bool, str]:
    """Validate a PDF file path for safety and existence."""
    if not path:
        return False, "path_required"

    p = Path(path).resolve()
    if not p.exists():
        return False, "file_not_found"
    if not p.is_file():
        return False, "not_a_file"
    if p.suffix.lower() != ".pdf":
        return False, "not_a_pdf"

    size_mb = p.stat().st_size / (1024 * 1024)
    if size_mb > _MAX_PDF_SIZE_MB:
        return False, f"file_too_large ({size_mb:.1f}MB > {_MAX_PDF_SIZE_MB}MB)"

    return True, ""


def _extract_text_from_pdf(path: str, max_pages: int = _MAX_PAGES) -> Dict[str, Any]:
    """Extract text from a PDF file using PyMuPDF.

    Returns:
        Dict with ok, text, page_count, char_count, truncated fields.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {
            "ok": False,
            "error": "pymupdf_not_installed",
            "hint": "pip install PyMuPDF",
        }

    valid, error = _validate_pdf_path(path)
    if not valid:
        return {"ok": False, "error": error}

    try:
        doc = fitz.open(path)
        total_pages = len(doc)
        pages_to_read = min(total_pages, max_pages)
        truncated = total_pages > max_pages

        text_parts: list[str] = []
        total_chars = 0

        for i in range(pages_to_read):
            page = doc[i]
            page_text = page.get_text("text")
            text_parts.append(page_text)
            total_chars += len(page_text)

            if total_chars > _MAX_TEXT_CHARS:
                truncated = True
                break

        doc.close()

        full_text = "\n".join(text_parts)
        if len(full_text) > _MAX_TEXT_CHARS:
            full_text = full_text[:_MAX_TEXT_CHARS]
            truncated = True

        return {
            "ok": True,
            "text": full_text,
            "page_count": total_pages,
            "pages_read": min(pages_to_read, len(text_parts)),
            "char_count": len(full_text),
            "truncated": truncated,
            "filename": Path(path).name,
        }

    except Exception as e:
        logger.error("[PDF] Extraction failed: %s", e)
        return {"ok": False, "error": f"extraction_failed: {e}"}


# ── Tool Handlers ────────────────────────────────────────────────


def pdf_extract_text_tool(
    *, path: str = "", max_pages: int = _MAX_PAGES, **_: Any
) -> Dict[str, Any]:
    """Extract text content from a PDF file.

    Args:
        path: Absolute path to the PDF file.
        max_pages: Maximum pages to extract (default 200).

    Returns:
        Dict with extracted text, page count, and metadata.
    """
    if not path:
        return {"ok": False, "error": "path_required"}

    max_pages = max(1, min(max_pages, _MAX_PAGES))
    return _extract_text_from_pdf(path, max_pages)


def pdf_summarize_tool(
    *, path: str = "", max_pages: int = 50, language: str = "tr", **_: Any
) -> Dict[str, Any]:
    """Extract text from a PDF and provide a structured summary.

    This tool extracts the text and returns it with metadata.
    The LLM finalizer handles the actual summarization.

    Args:
        path: Absolute path to the PDF file.
        max_pages: Maximum pages to process (default 50, max 200).
        language: Summary language hint (default "tr" for Turkish).

    Returns:
        Dict with extracted text ready for LLM summarization.
    """
    if not path:
        return {"ok": False, "error": "path_required"}

    max_pages = max(1, min(max_pages, _MAX_PAGES))
    result = _extract_text_from_pdf(path, max_pages)

    if not result["ok"]:
        return result

    # Add summarization hints for the finalizer
    result["summary_hint"] = (
        f"Bu PDF dosyasından ({result['filename']}, {result['page_count']} sayfa) "
        f"metin çıkarıldı. Lütfen içeriği {'Türkçe' if language == 'tr' else language} "
        f"olarak özetle."
    )
    result["language"] = language

    return result


def pdf_from_attachment_tool(
    *,
    message_id: str = "",
    attachment_id: str = "",
    filename: str = "",
    **_: Any,
) -> Dict[str, Any]:
    """Download a Gmail PDF attachment and extract its text.

    Combines gmail.download_attachment + pdf.extract_text in one step.

    Args:
        message_id: Gmail message ID containing the attachment.
        attachment_id: Gmail attachment ID.
        filename: Original filename (for display).

    Returns:
        Dict with extracted text and download metadata.
    """
    if not message_id or not attachment_id:
        return {"ok": False, "error": "message_id and attachment_id required"}

    # Download to temp directory
    tmp_dir = Path(tempfile.mkdtemp(prefix="bantz_pdf_"))
    save_name = filename or f"attachment_{attachment_id[:8]}.pdf"
    save_path = str(tmp_dir / save_name)

    try:
        from bantz.google.gmail import gmail_download_attachment

        dl_result = gmail_download_attachment(
            message_id=message_id,
            attachment_id=attachment_id,
            save_path=save_path,
        )

        if not dl_result.get("ok"):
            return {
                "ok": False,
                "error": f"download_failed: {dl_result.get('error', 'unknown')}",
            }

        # Extract text from downloaded PDF
        extract_result = _extract_text_from_pdf(save_path)

        if extract_result["ok"]:
            extract_result["source"] = "gmail_attachment"
            extract_result["message_id"] = message_id
            extract_result["original_filename"] = filename or dl_result.get("filename", save_name)

        return extract_result

    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    except Exception as e:
        logger.error("[PDF] Attachment extraction failed: %s", e)
        return {"ok": False, "error": f"attachment_extraction_failed: {e}"}
    finally:
        # Cleanup temp files
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
