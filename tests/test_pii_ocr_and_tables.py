# Run: uv run pytest tests/test_pii_ocr_and_tables.py -v
"""Deep tests for PII vault masking/isolation, OCR PDF ingestion, and effective-dated tables."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pymupdf
import pytest

from app.core.ocr import LocalOCRProvider, MockOCRProvider, OCRBlock
from app.core.pii import PIITokenizer
from app.core.tables import StatutoryTableRegistry, TableIntegrityError
from app.ingest import MatterIngestor


def _create_raster_only_pdf(path: Path) -> None:
    """Creates a PDF containing an embedded raster image with zero text layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pix.set_rect(pix.irect, (240, 240, 240))
    page.insert_image(pymupdf.Rect(72, 72, 272, 172), pixmap=pix)
    doc.save(str(path))
    doc.close()


def _create_digital_pii_pdf(path: Path) -> None:
    """Creates a text-layer PDF containing an SSN and bank account number."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(
        (72, 100),
        "Debtor Tax ID SSN: 123-45-6789\nChecking Account No: 98765432104829 Balance: $4,120.50",
        fontsize=11,
    )
    doc.save(str(path))
    doc.close()


def test_pii_tokenizer_masks_consistently_and_blocks_public_unmask(tmp_path: Path) -> None:
    """Verifies SSNs and account numbers mask deterministically and enforce Form B121 isolation."""
    tokenizer = PIITokenizer(tmp_path)
    raw_1 = "Employee SSN 123-45-6789 paid into Account # 98765432104829."
    raw_2 = "Second paystub for SSN: 123-45-6789 and account number 98765432104829."

    masked_1 = tokenizer.mask_text("case_alpha", raw_1)
    masked_2 = tokenizer.mask_text("case_alpha", raw_2)

    assert "123-45-6789" not in masked_1
    assert "98765432104829" not in masked_1
    assert "[PII:SSN_001]" in masked_1
    assert "[PII:ACCT_001_LAST4_4829]" in masked_1
    # Re-masking in another file reuses exact same deterministic tokens.
    assert "[PII:SSN_001]" in masked_2
    assert "[PII:ACCT_001_LAST4_4829]" in masked_2

    # Public form unmasking MUST raise PermissionError.
    for public_form in ("B101", "B106AB", "B107", "B122A1", "CACB_F3015"):
        with pytest.raises(PermissionError):
            tokenizer.unmask_for_restricted_form("case_alpha", masked_1, public_form)

    # Restricted forms B121 and debtor.txt may unmask.
    unmasked_b121 = tokenizer.unmask_for_restricted_form("case_alpha", masked_1, "B121")
    assert "123-45-6789" in unmasked_b121
    assert "98765432104829" in unmasked_b121

    # Public FRBP 9037 redaction strips tokens to XXX-XX-XXXX and ****4829.
    redacted = tokenizer.redact_for_public_form(masked_1)
    assert "123-45-6789" not in redacted
    assert "XXX-XX-XXXX" in redacted
    assert "****4829" in redacted


def test_matter_ingestor_ocr_and_pii_pipeline_on_scanned_and_digital_pdfs(tmp_path: Path) -> None:
    """Tests OCR fallback with [x1,y1,x2,y2] bounding boxes plus pre-LLM PII masking."""
    matters_root = tmp_path / "matters"
    tokenizer = PIITokenizer(matters_root)
    mock_ocr = MockOCRProvider(
        page_map={
            ("scanned_paystub.pdf", 1): [
                OCRBlock(
                    text="ADP Paystub Gross Pay: $3,250.00 SSN: 555-66-7777",
                    page=1,
                    bounding_box=[80, 120, 480, 160],
                ),
                OCRBlock(
                    text="Direct Deposit Account No: 4411223344559988",
                    page=1,
                    bounding_box=[80, 170, 450, 200],
                ),
            ]
        }
    )
    ingestor = MatterIngestor(
        matters_root=matters_root, ocr_provider=mock_ocr, pii_tokenizer=tokenizer
    )
    matter_dir = ingestor.create_matter("bk_test_case")
    raw_dir = matter_dir / "inputs" / "raw"

    _create_raster_only_pdf(raw_dir / "scanned_paystub.pdf")
    _create_digital_pii_pdf(raw_dir / "digital_stmt.pdf")

    manifest = ingestor.ingest_matter("bk_test_case")
    assert manifest["files_processed"] == 2

    scanned_idx = (matter_dir / "inputs" / "indexed" / "scanned_paystub.pdf.indexed.md").read_text(
        encoding="utf-8"
    )
    digital_idx = (matter_dir / "inputs" / "indexed" / "digital_stmt.pdf.indexed.md").read_text(
        encoding="utf-8"
    )

    assert "555-66-7777" not in scanned_idx
    assert "4411223344559988" not in scanned_idx
    assert "[80,120,480,160]" in scanned_idx or "[80, 120, 480, 160]" in scanned_idx
    assert "LAST4_9988" in scanned_idx

    assert "123-45-6789" not in digital_idx
    assert "98765432104829" not in digital_idx
    assert "LAST4_4829" in digital_idx


def test_local_ocr_provider_extracts_text_blocks_with_coordinates(tmp_path: Path) -> None:
    """Verifies LocalOCRProvider returns bounding boxes on digital PDFs and handles raster pages cleanly."""
    digital_pdf = tmp_path / "digital.pdf"
    _create_digital_pii_pdf(digital_pdf)
    raster_pdf = tmp_path / "raster.pdf"
    _create_raster_only_pdf(raster_pdf)

    provider = LocalOCRProvider()
    blocks = provider.extract_page_blocks(digital_pdf, 1)
    assert len(blocks) >= 1
    assert any("Debtor Tax ID" in blk.text for blk in blocks)
    assert all(len(blk.bounding_box) == 4 for blk in blocks)

    # Should cleanly handle out-of-range page and raster page without raising.
    assert provider.extract_page_blocks(digital_pdf, 99) == []
    raster_blocks = provider.extract_page_blocks(raster_pdf, 1)
    assert isinstance(raster_blocks, list)


def test_statutory_table_registry_effective_dates_and_checksum(tmp_path: Path) -> None:
    """Verifies effective-dated threshold routing (pre vs. post H.R. 7730) and tamper checks."""
    tables_dir = Path("canonical/tables/bankruptcy")
    registry = StatutoryTableRegistry(tables_dir)

    meta = registry.list_metadata()
    filenames = {item["filename"] for item in meta}
    assert {
        "federal_thresholds_2026.json",
        "ustp_ca_means_test_2026.json",
        "exemptions_2026.json",
        "dependency_rules.json",
    }.issubset(filenames)

    # Pre-H.R. 7730 filing date uses April 1, 2025 bifurcated Ch. 13 limits.
    pre_hr7730 = registry.get_federal_thresholds(datetime.date(2026, 11, 9))
    assert pre_hr7730["version_id"] == "fed_2025_04_01"
    assert pre_hr7730["chapter_13_eligibility"]["mode"] == "bifurcated"
    assert pre_hr7730["subchapter_v_eligibility"]["debt_limit"] == "3424000.00"

    # On/after Nov 10, 2026 uses H.R. 7730 unified $2.75M Ch. 13 and permanent $7.5M SubV.
    post_hr7730 = registry.get_federal_thresholds(datetime.date(2026, 11, 16))
    assert post_hr7730["version_id"] == "fed_2026_11_10_hr7730"
    assert post_hr7730["chapter_13_eligibility"]["mode"] == "unified"
    assert post_hr7730["chapter_13_eligibility"]["combined_limit"] == "2750000.00"
    assert post_hr7730["subchapter_v_eligibility"]["debt_limit"] == "7500000.00"

    # Tamper detection check via copied JSON.
    bad_dir = tmp_path / "tables"
    bad_dir.mkdir()
    orig = json.loads((tables_dir / "federal_thresholds_2026.json").read_text(encoding="utf-8"))
    (bad_dir / "federal_thresholds_2026.json").write_text(json.dumps(orig), encoding="utf-8")
    bad_reg = StatutoryTableRegistry(bad_dir)
    with pytest.raises(TableIntegrityError):
        bad_reg.load_table("federal_thresholds_2026.json", expected_sha256="sha256:0000deadbeef")
