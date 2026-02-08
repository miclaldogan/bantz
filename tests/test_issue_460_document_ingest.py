"""Tests for issue #460 — Document ingest v0."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from bantz.document.ingest_v0 import (
    Chunk,
    Document,
    DocumentIngester,
    IngestConfig,
)


# ── fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dir():
    """Temp directory that's in allowed_dirs."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def ingester(tmp_dir):
    """Ingester with tmp_dir as only allowed dir."""
    config = IngestConfig(
        chunk_size=50,
        chunk_overlap=10,
        allowed_dirs=[str(tmp_dir)],
    )
    return DocumentIngester(config=config)


def _write(tmp_dir: Path, name: str, content: str) -> Path:
    p = tmp_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# ── TXT ingest ────────────────────────────────────────────────────────

class TestTXTIngest:
    def test_basic_txt(self, tmp_dir, ingester):
        f = _write(tmp_dir, "hello.txt", "Merhaba dünya! Bu bir test dosyasıdır.")
        doc = ingester.ingest(str(f))
        assert doc.format == "txt"
        assert "Merhaba" in doc.content
        assert doc.title == "hello"

    def test_empty_txt(self, tmp_dir, ingester):
        f = _write(tmp_dir, "empty.txt", "")
        doc = ingester.ingest(str(f))
        assert doc.content == ""
        assert doc.chunks == []


# ── Markdown ingest ───────────────────────────────────────────────────

class TestMarkdownIngest:
    def test_md(self, tmp_dir, ingester):
        f = _write(tmp_dir, "doc.md", "# Başlık\n\nİçerik burada.")
        doc = ingester.ingest(str(f))
        assert doc.format == "md"
        assert "Başlık" in doc.content


# ── HTML ingest ───────────────────────────────────────────────────────

class TestHTMLIngest:
    def test_html_strips_tags(self, tmp_dir, ingester):
        html = "<html><body><h1>Test</h1><p>Hello &amp; world</p></body></html>"
        f = _write(tmp_dir, "page.html", html)
        doc = ingester.ingest(str(f))
        assert doc.format == "html"
        assert "<h1>" not in doc.content
        assert "Test" in doc.content
        assert "Hello & world" in doc.content

    def test_htm_extension(self, tmp_dir, ingester):
        f = _write(tmp_dir, "page.htm", "<p>text</p>")
        doc = ingester.ingest(str(f))
        assert doc.format == "html"


# ── Chunking ──────────────────────────────────────────────────────────

class TestChunking:
    def test_chunks_created(self, tmp_dir, ingester):
        text = "word " * 500  # ~2500 chars
        f = _write(tmp_dir, "big.txt", text)
        doc = ingester.ingest(str(f))
        assert len(doc.chunks) > 1

    def test_chunk_overlap(self, tmp_dir, ingester):
        text = "A" * 1000
        f = _write(tmp_dir, "long.txt", text)
        doc = ingester.ingest(str(f))
        if len(doc.chunks) >= 2:
            c0_end = doc.chunks[0].end_char
            c1_start = doc.chunks[1].start_char
            assert c1_start < c0_end  # overlap

    def test_small_doc_single_chunk(self, tmp_dir, ingester):
        f = _write(tmp_dir, "small.txt", "kısa metin")
        doc = ingester.ingest(str(f))
        assert len(doc.chunks) == 1

    def test_custom_chunk_size(self, tmp_dir):
        config = IngestConfig(chunk_size=10, chunk_overlap=2, allowed_dirs=[str(tmp_dir)])
        ing = DocumentIngester(config=config)
        f = _write(tmp_dir, "t.txt", "word " * 100)
        doc = ing.ingest(str(f))
        for chunk in doc.chunks:
            assert chunk.estimated_tokens <= 15  # some tolerance


# ── Sandbox ───────────────────────────────────────────────────────────

class TestSandbox:
    def test_outside_allowed_dirs_denied(self, tmp_dir):
        config = IngestConfig(allowed_dirs=["/nonexistent/path"])
        ing = DocumentIngester(config=config)
        f = _write(tmp_dir, "secret.txt", "data")
        with pytest.raises(PermissionError, match="outside allowed"):
            ing.ingest(str(f))

    def test_allowed_dir_ok(self, tmp_dir, ingester):
        f = _write(tmp_dir, "ok.txt", "safe")
        doc = ingester.ingest(str(f))
        assert doc.content == "safe"


# ── File not found ────────────────────────────────────────────────────

class TestFileNotFound:
    def test_missing_file(self, tmp_dir, ingester):
        with pytest.raises(FileNotFoundError):
            ingester.ingest(str(tmp_dir / "nope.txt"))


# ── Unsupported format ────────────────────────────────────────────────

class TestUnsupportedFormat:
    def test_unsupported_ext(self, tmp_dir, ingester):
        f = _write(tmp_dir, "data.xyz", "content")
        with pytest.raises(ValueError, match="Unsupported"):
            ingester.ingest(str(f))


# ── Summarize ─────────────────────────────────────────────────────────

class TestSummarize:
    def test_short_text(self, tmp_dir, ingester):
        f = _write(tmp_dir, "s.txt", "Kısa metin.")
        doc = ingester.ingest(str(f))
        summary = ingester.summarize(doc)
        assert summary == "Kısa metin."

    def test_long_text_truncated(self, tmp_dir, ingester):
        text = "X" * 1000
        f = _write(tmp_dir, "l.txt", text)
        doc = ingester.ingest(str(f))
        summary = ingester.summarize(doc)
        assert summary.endswith("...")
        assert len(summary) == 503  # 500 + "..."

    def test_custom_summarizer(self, tmp_dir):
        config = IngestConfig(allowed_dirs=[str(tmp_dir)])
        ing = DocumentIngester(config=config, summarizer=lambda t: "ÖZET")
        f = _write(tmp_dir, "c.txt", "content")
        doc = ing.ingest(str(f))
        assert ing.summarize(doc) == "ÖZET"


# ── Query ─────────────────────────────────────────────────────────────

class TestQuery:
    def test_query_returns_string(self, tmp_dir, ingester):
        f = _write(tmp_dir, "q.txt", "Python bir programlama dilidir. Java da bir dildir.")
        doc = ingester.ingest(str(f))
        answer = ingester.query(doc, "Python nedir?")
        assert isinstance(answer, str)
        assert len(answer) > 0


# ── Document metadata ────────────────────────────────────────────────

class TestDocumentMeta:
    def test_metadata_includes_size(self, tmp_dir, ingester):
        f = _write(tmp_dir, "m.txt", "test content")
        doc = ingester.ingest(str(f))
        assert "size_bytes" in doc.metadata
        assert doc.metadata["size_bytes"] > 0
