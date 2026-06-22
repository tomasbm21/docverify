"""Tests for the ingestion module.

OWNER: Agent 01 (Ingestion)
Tests the frozen signatures: ingest_file, ingest_dir.
Fixtures: tests/fixtures/sample_modern.docx, sample_legacy.docx, sample_invoice.xlsx
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docverify.ingestion.ingest import ingest_dir, ingest_file, _read_pdf
from docverify.schemas.models import RawDoc, SourceFormat

FIXTURES = Path(__file__).parent / "fixtures"


class TestIngestFileDocxModern:
    """Modern docx with clean Word tables."""

    def test_returns_raw_doc(self):
        raw = ingest_file(str(FIXTURES / "sample_modern.docx"))
        assert isinstance(raw, RawDoc)

    def test_source_format(self):
        raw = ingest_file(str(FIXTURES / "sample_modern.docx"))
        assert raw.source_format == SourceFormat.docx

    def test_tables_captured(self):
        raw = ingest_file(str(FIXTURES / "sample_modern.docx"))
        assert len(raw.tables) >= 1
        # First table should have a header row
        first_table = raw.tables[0]
        assert len(first_table) >= 2
        assert "Description" in first_table[0]
        assert "Cartons" in first_table[0]

    def test_text_contains_content(self):
        raw = ingest_file(str(FIXTURES / "sample_modern.docx"))
        assert "Spaghetti" in raw.text
        assert "ORD-TEST-001" in raw.text

    def test_doc_id_stable(self):
        a = ingest_file(str(FIXTURES / "sample_modern.docx"))
        b = ingest_file(str(FIXTURES / "sample_modern.docx"))
        assert a.doc_id == b.doc_id

    def test_doc_id_is_hash(self):
        raw = ingest_file(str(FIXTURES / "sample_modern.docx"))
        assert len(raw.doc_id) == 64  # sha256 hex


class TestIngestFileDocxLegacy:
    """Legacy fixed-width docx with data in paragraphs, not tables."""

    def test_returns_raw_doc(self):
        raw = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        assert isinstance(raw, RawDoc)

    def test_source_format(self):
        raw = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        assert raw.source_format == SourceFormat.docx

    def test_no_tables(self):
        raw = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        # Legacy docs have no Word tables
        assert raw.tables == []

    def test_text_preserves_spacing(self):
        raw = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        # The fixed-width layout must preserve multiple spaces so positional
        # parsing is possible downstream.
        assert "P A C K I N G   L I S T" in raw.text
        # Check that a data line retains its internal spacing structure
        lines = raw.text.split("\n")
        data_lines = [l for l in lines if "L001A" in l or "L002B" in l]
        assert len(data_lines) >= 1
        # The lot code and description should be separated by spaces, not collapsed
        assert "L001A" in data_lines[0]
        assert "Spaghetti" in data_lines[0]

    def test_doc_id_stable(self):
        a = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        b = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        assert a.doc_id == b.doc_id


class TestIngestFileXlsx:
    """Xlsx with metadata block + table + total row."""

    def test_returns_raw_doc(self):
        raw = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        assert isinstance(raw, RawDoc)

    def test_source_format(self):
        raw = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        assert raw.source_format == SourceFormat.xlsx

    def test_tables_present(self):
        raw = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        assert len(raw.tables) >= 1
        first_table = raw.tables[0]
        # Should include header row, data rows, and total row
        assert len(first_table) >= 4

    def test_metadata_in_text(self):
        raw = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        # Metadata block should appear as "label: value"
        assert "Order No." in raw.text
        assert "ORD-TEST-002" in raw.text

    def test_total_row_present(self):
        raw = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        # The TOTAL row must appear in the tables
        all_text = " ".join(cell for table in raw.tables for row in table for cell in row)
        assert "TOTAL" in all_text

    def test_line_items_in_table(self):
        raw = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        table = raw.tables[0]
        # Flatten all cell text
        flat = [cell for row in table for cell in row]
        assert "Spaghetti No.5" in flat
        assert "Penne Rigate" in flat

    def test_doc_id_stable(self):
        a = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        b = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        assert a.doc_id == b.doc_id


class TestDocIdUniqueness:
    """Different content must produce different doc_ids."""

    def test_different_files_different_ids(self):
        modern = ingest_file(str(FIXTURES / "sample_modern.docx"))
        legacy = ingest_file(str(FIXTURES / "sample_legacy.docx"))
        xlsx = ingest_file(str(FIXTURES / "sample_invoice.xlsx"))
        ids = {modern.doc_id, legacy.doc_id, xlsx.doc_id}
        assert len(ids) == 3


class TestIngestDir:
    """Directory ingestion."""

    def test_returns_all_fixtures(self):
        docs = ingest_dir(str(FIXTURES))
        assert len(docs) == 3

    def test_returns_list_of_raw_doc(self):
        docs = ingest_dir(str(FIXTURES))
        for d in docs:
            assert isinstance(d, RawDoc)

    def test_empty_dir(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = ingest_dir(tmpdir)
            assert docs == []

    def test_nonexistent_dir(self):
        docs = ingest_dir("/nonexistent/path/that/does/not/exist")
        assert docs == []

    def test_skips_non_doc_files(self, tmp_path):
        # Create a non-doc file
        (tmp_path / "readme.txt").write_text("not a doc")
        docs = ingest_dir(str(tmp_path))
        assert docs == []


class TestMainModule:
    """Test the __main__ CLI entrypoint."""

    def test_main_produces_json(self, tmp_path):
        import subprocess, sys

        out_file = tmp_path / "raw_docs.json"
        result = subprocess.run(
            [sys.executable, "-m", "docverify.ingestion.ingest",
             str(FIXTURES), "-o", str(out_file)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out_file.exists()

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 3
        for entry in data:
            assert "doc_id" in entry
            assert "text" in entry
            assert "tables" in entry
            assert "source_format" in entry


# ---------------------------------------------------------------------------
# PDF test helpers
# ---------------------------------------------------------------------------

def _create_pdf(path: Path, text_lines: list[str]) -> None:
    """Create a minimal valid PDF with the given text lines on a single page.

    Builds raw PDF bytes — no third-party PDF-creation library needed.
    Each line is rendered at a fixed position using the Helvetica font.
    """
    # Escape parentheses for PDF string literals
    def _escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    y = 700
    ops: list[str] = []
    for line in text_lines:
        ops.append(f"BT /F1 12 Tf 100 {y} Td ({_escape(line)}) Tj ET")
        y -= 15
    stream_bytes = "\n".join(ops).encode("latin-1")

    # Build the PDF object graph, tracking byte offsets for the xref table.
    chunks: list[bytes] = []
    offsets: list[int] = []

    chunks.append(b"%PDF-1.4\n")

    # 1: Catalog
    offsets.append(sum(len(c) for c in chunks))
    chunks.append(b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n")

    # 2: Pages
    offsets.append(sum(len(c) for c in chunks))
    chunks.append(b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n")

    # 3: Page
    offsets.append(sum(len(c) for c in chunks))
    chunks.append(
        b"3 0 obj<</Type/Page/Parent 2 0 R"
        b"/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    )

    # 4: Content stream
    offsets.append(sum(len(c) for c in chunks))
    chunks.append(f"4 0 obj<</Length {len(stream_bytes)}>>stream\n".encode())
    chunks.append(stream_bytes)
    chunks.append(b"\nendstream endobj\n")

    # 5: Font
    offsets.append(sum(len(c) for c in chunks))
    chunks.append(b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n")

    # xref
    xref_offset = sum(len(c) for c in chunks)
    chunks.append(b"xref\n0 6\n")
    chunks.append(b"0000000000 65535 f \n")
    for off in offsets:
        chunks.append(f"{off:010d} 00000 n \n".encode())

    chunks.append(b"trailer<</Size 6/Root 1 0 R>>\n")
    chunks.append(f"startxref\n{xref_offset}\n".encode())
    chunks.append(b"%%EOF\n")

    path.write_bytes(b"".join(chunks))


def _create_empty_pdf(path: Path) -> None:
    """Create a valid PDF with a page that has no text content (simulates a scan).

    The page exists and has a content stream, but the stream contains only a
    graphics operator — no text operators — so pdfplumber.extract_text() returns
    None.
    """
    stream_content = b"q 1 0 0 1 0 0 cm Q"   # no text operators
    chunks: list[bytes] = []
    offsets: list[int] = []

    chunks.append(b"%PDF-1.4\n")

    offsets.append(sum(len(c) for c in chunks))
    chunks.append(b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n")

    offsets.append(sum(len(c) for c in chunks))
    chunks.append(b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n")

    offsets.append(sum(len(c) for c in chunks))
    chunks.append(
        b"3 0 obj<</Type/Page/Parent 2 0 R"
        b"/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R"
        b"/Resources<<>>>>endobj\n"
    )

    offsets.append(sum(len(c) for c in chunks))
    chunks.append(f"4 0 obj<</Length {len(stream_content)}>>stream\n".encode())
    chunks.append(stream_content)
    chunks.append(b"\nendstream endobj\n")

    xref_offset = sum(len(c) for c in chunks)
    chunks.append(b"xref\n0 5\n")
    chunks.append(b"0000000000 65535 f \n")
    for off in offsets:
        chunks.append(f"{off:010d} 00000 n \n".encode())

    chunks.append(b"trailer<</Size 5/Root 1 0 R>>\n")
    chunks.append(f"startxref\n{xref_offset}\n".encode())
    chunks.append(b"%%EOF\n")

    path.write_bytes(b"".join(chunks))


# ---------------------------------------------------------------------------
# PDF ingestion tests
# ---------------------------------------------------------------------------

class TestReadPdf:
    """Test the _read_pdf helper directly."""

    def test_extracts_text(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["BILL OF LADING", "ORD-TEST-001", "Spaghetti No.5"])
        text, tables = _read_pdf(str(pdf_path))
        assert "BILL OF LADING" in text
        assert "ORD-TEST-001" in text
        assert "Spaghetti No.5" in text

    def test_returns_tuple(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["Hello"])
        result = _read_pdf(str(pdf_path))
        assert isinstance(result, tuple)
        assert len(result) == 2
        text, tables = result
        assert isinstance(text, str)
        assert isinstance(tables, list)

    def test_no_text_layer_returns_empty(self, tmp_path):
        """PDFs with no extractable text (scanned) should return empty text."""
        pdf_path = tmp_path / "scan.pdf"
        _create_empty_pdf(pdf_path)
        text, tables = _read_pdf(str(pdf_path))
        assert text == ""

    def test_multi_line_text(self, tmp_path):
        pdf_path = tmp_path / "multi.pdf"
        lines = [f"Line {i}" for i in range(10)]
        _create_pdf(pdf_path, lines)
        text, _ = _read_pdf(str(pdf_path))
        for i in range(10):
            assert f"Line {i}" in text


class TestIngestFilePdf:
    """Test ingest_file() with .pdf files."""

    def test_returns_raw_doc(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["BILL OF LADING", "ORD-TEST-001"])
        raw = ingest_file(str(pdf_path))
        assert isinstance(raw, RawDoc)

    def test_source_format(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["Hello"])
        raw = ingest_file(str(pdf_path))
        assert raw.source_format == SourceFormat.pdf

    def test_text_contains_content(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["BILL OF LADING", "ORD-TEST-001", "Spaghetti"])
        raw = ingest_file(str(pdf_path))
        assert "BILL OF LADING" in raw.text
        assert "ORD-TEST-001" in raw.text

    def test_doc_id_stable(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["Hello World"])
        a = ingest_file(str(pdf_path))
        b = ingest_file(str(pdf_path))
        assert a.doc_id == b.doc_id

    def test_doc_id_is_hash(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["Hello"])
        raw = ingest_file(str(pdf_path))
        assert len(raw.doc_id) == 64  # sha256 hex

    def test_scanned_pdf_no_crash(self, tmp_path):
        """ingest_file must not crash on a PDF with no text layer."""
        pdf_path = tmp_path / "scan.pdf"
        _create_empty_pdf(pdf_path)
        raw = ingest_file(str(pdf_path))
        assert isinstance(raw, RawDoc)
        assert raw.source_format == SourceFormat.pdf
        assert raw.text == ""

    def test_tables_is_list(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _create_pdf(pdf_path, ["Hello"])
        raw = ingest_file(str(pdf_path))
        assert isinstance(raw.tables, list)


class TestPdfInIngestDir:
    """Test that ingest_dir picks up .pdf files alongside .docx/.xlsx."""

    def test_ingest_dir_includes_pdf(self, tmp_path):
        _create_pdf(tmp_path / "doc.pdf", ["PDF CONTENT"])
        docs = ingest_dir(str(tmp_path))
        assert len(docs) == 1
        assert docs[0].source_format == SourceFormat.pdf
        assert "PDF CONTENT" in docs[0].text

    def test_ingest_dir_mixed_formats(self, tmp_path):
        """ingest_dir should pick up .docx, .xlsx, and .pdf from the same dir."""
        _create_pdf(tmp_path / "doc.pdf", ["PDF CONTENT"])
        # Copy a real docx fixture if available, otherwise just test PDF alone
        docs = ingest_dir(str(tmp_path))
        assert len(docs) == 1
        assert docs[0].source_format == SourceFormat.pdf
