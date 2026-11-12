# Run test: uv run pytest tests/test_ingest.py -v
"""Unit tests for canonical corpus routing and deterministic matter input ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
import openpyxl

from app.ingest import CanonicalRouter, MatterIngestor


def _create_minimal_pdf(path: Path, lines: List[str]) -> None:
    """Writes a minimal valid single-page PDF readable by `pdfplumber` without external deps."""
    text_ops = ["BT", "/F1 12 Tf", "72 720 Td"]
    for idx, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if idx > 0:
            text_ops.append("0 -18 Td")
        text_ops.append(f"({escaped}) Tj")
    text_ops.append("ET")
    stream_bytes = "\n".join(text_ops).encode("latin-1")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
        + stream_bytes
        + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    pdf_chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for obj in objects:
        offsets.append(sum(len(c) for c in pdf_chunks))
        pdf_chunks.append(obj)

    xref_offset = sum(len(c) for c in pdf_chunks)
    xref_lines = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")]
    for off in offsets[1:]:
        xref_lines.append(f"{off:010d} 00000 n \n".encode("latin-1"))
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin-1")

    path.write_bytes(b"".join(pdf_chunks + xref_lines + [trailer]))


def test_canonical_router_loads_index_and_auth_blocks(tmp_path: Path) -> None:
    """Verifies `CanonicalRouter` parses `INDEX.md` and extracts `[AUTH:...]` sections."""
    canonical_dir = tmp_path / "canonical"
    (canonical_dir / "legal").mkdir(parents=True)
    (canonical_dir / "INDEX.md").write_text(
        "# Canonical Index\n- `[AUTH:HERTZ-2010]`: Nerve center citizenship rule.\n",
        encoding="utf-8",
    )
    (canonical_dir / "legal" / "jurisdiction.md").write_text(
        "## [AUTH:HERTZ-2010] Hertz Corp. v. Friend, 559 U.S. 77 (2010)\n"
        "- **Title:** Hertz Corp. v. Friend, 559 U.S. 77 (2010)\n"
        "- **URL:** https://supreme.justia.com/cases/federal/us/559/77/\n"
        "- **Verbatim Holding:** Principal place of business refers to the nerve center.\n",
        encoding="utf-8",
    )

    router = CanonicalRouter(canonical_dir)
    assert "HERTZ-2010" in router.get_index_markdown()
    auth = router.get_authority("AUTH:HERTZ-2010")
    assert auth is not None
    assert auth.auth_id == "AUTH:HERTZ-2010"
    assert "nerve center" in auth.verbatim_quote
    assert auth.url == "https://supreme.justia.com/cases/federal/us/559/77/"


def test_matter_ingestor_indexes_spreadsheet_formulas_and_values(tmp_path: Path) -> None:
    """Verifies dual-pass openpyxl extraction captures both formula and raw_value."""
    matters_root = tmp_path / "matters"
    raw_dir = matters_root / "m1" / "inputs" / "raw"
    raw_dir.mkdir(parents=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Aging_Summary"
    ws["A1"] = "Line Item"
    ws["B1"] = "Amount"
    ws["A2"] = "Invoice 1"
    ws["B2"] = 20000.0
    ws["A3"] = "Invoice 2"
    ws["B3"] = 22150.0
    ws["A4"] = "Total Unpaid"
    ws["B4"] = "=SUM(B2:B3)"
    wb.save(raw_dir / "Invoices_2026.xlsx")

    ingestor = MatterIngestor(matters_root)
    manifest = ingestor.ingest_matter("m1")

    assert manifest["matter_id"] == "m1"
    assert manifest["spreadsheet_cells_indexed"] >= 4

    index_path = matters_root / "m1" / "inputs" / "indexed" / "sheets_index.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    b4_rows = [r for r in rows if r["cell_range"] == "B4"]
    assert len(b4_rows) == 1
    assert b4_rows[0]["formula"] == "=SUM(B2:B3)"
    assert b4_rows[0]["line_item"] == "Total Unpaid"
    assert b4_rows[0]["locator"]["source_type"] == "spreadsheet"
    assert b4_rows[0]["locator"]["sheet"] == "Aging_Summary"


def test_matter_ingestor_indexes_pdf_bounding_boxes_and_markdown(tmp_path: Path) -> None:
    """Verifies PDF `pdfplumber` bbox stamping and Markdown block locator stamping."""
    matters_root = tmp_path / "matters"
    raw_dir = matters_root / "m2" / "inputs" / "raw"
    raw_dir.mkdir(parents=True)

    _create_minimal_pdf(
        raw_dir / "Exhibit_B.pdf",
        ["Principal place of business registered at 1209 North Orange St, Wilmington, DE."],
    )
    (raw_dir / "Board_Notes.md").write_text(
        "# Q3 Board Minutes\n\nAll treasury approvals were executed in Wilmington headquarters.\n",
        encoding="utf-8",
    )

    ingestor = MatterIngestor(matters_root)
    manifest = ingestor.ingest_matter("m2")

    assert manifest["files_processed"] == 2
    indexed_dir = matters_root / "m2" / "inputs" / "indexed"
    pdf_indexed = (indexed_dir / "Exhibit_B.pdf.indexed.md").read_text(encoding="utf-8")
    assert "<!-- LOCATOR:" in pdf_indexed
    assert '"source_type":"pdf"' in pdf_indexed
    assert '"page":1' in pdf_indexed
    assert '"bounding_box":[72,' in pdf_indexed
    assert "1209 North Orange St" in pdf_indexed

    md_indexed = (indexed_dir / "Board_Notes.md.indexed.md").read_text(encoding="utf-8")
    assert "<!-- LOCATOR:" in md_indexed
    assert "Wilmington headquarters" in md_indexed


def test_stage2_tools_search_and_read_exact_locators(tmp_path: Path) -> None:
    """Verifies deterministic grep, block read, and spreadsheet search tools for Stage 2."""
    matters_root = tmp_path / "matters"
    raw_dir = matters_root / "m3" / "inputs" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "Memo.md").write_text(
        "# Findings\n\nMonthly enterprise churn held steady at 3.2% in EMEA during Q3.\n",
        encoding="utf-8",
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws["A1"] = "Gross Margin"
    ws["B1"] = 0.7142
    wb.save(raw_dir / "Actuals.xlsx")

    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("m3")
    tools = {t.name: t for t in ingestor.build_stage2_tools("m3")}

    assert set(tools.keys()) == {
        "list_matter_files",
        "grep_indexed_inputs",
        "read_locator_context",
        "search_spreadsheet_cells",
    }

    files_out = tools["list_matter_files"].handler()
    assert any("Memo.md" in f["raw_file"] for f in files_out["files"])

    grep_out = tools["grep_indexed_inputs"].handler(pattern="3.2%")
    assert len(grep_out["matches"]) == 1
    assert grep_out["matches"][0]["locator"]["file_name"] == "Memo.md"
    locator_key = grep_out["matches"][0]["locator"]["locator_key"]

    ctx_out = tools["read_locator_context"].handler(locator_key=locator_key)
    assert "3.2% in EMEA" in ctx_out["block_text"]

    sheet_out = tools["search_spreadsheet_cells"].handler(query="Gross Margin")
    assert len(sheet_out["cells"]) >= 1
    assert any(
        c["cell_range"] == "B1" and c["raw_value"] == 0.7142
        for c in sheet_out["cells"]
    )
