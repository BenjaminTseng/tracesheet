# Run test: uv run pytest tests/test_ingest.py -v
"""Unit tests for canonical corpus routing and deterministic matter input ingestion."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import List
import openpyxl

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import MockLLMProvider
from app.models import (
    CanonicalAuthorityRef,
    CanonicalDocumentSynopsisDraft,
    SectionOutput,
    VerifiedFactLedger,
)


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


def _create_minimal_docx(path: Path, heading: str, body: str) -> None:
    """Creates a minimal valid `.docx` ZIP containing a heading and rule paragraph."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{heading}</w:t></w:r></w:p>'
        f"<w:p><w:r><w:t>{body}</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)


def test_canonical_ingestor_encodes_raw_corpus_and_rebuilds_index(tmp_path: Path) -> None:
    """Verifies `CanonicalIngestor` encodes raw MD, PDF, DOCX, and CSV files and supports purge+rebuild."""
    canonical_dir = tmp_path / "canonical"
    raw_legal = canonical_dir / "raw" / "legal"
    raw_policy = canonical_dir / "raw" / "policy"
    raw_legal.mkdir(parents=True)
    raw_policy.mkdir(parents=True)

    (raw_legal / "venue_statute.md").write_text(
        "# Venue Statutes\n\n"
        "## 28 U.S.C. § 1391(b) — General Venue\n"
        "A civil action may be brought in a judicial district in which any defendant resides.\n\n"
        "## Forum Selection Clauses\n"
        "Contractual forum selection clauses are prima facie valid unless unreasonable.\n",
        encoding="utf-8",
    )
    _create_minimal_pdf(
        raw_legal / "Removal_Rules.pdf",
        ["28 U.S.C. 1441 permits removal within 30 days of service."],
    )
    _create_minimal_docx(
        raw_policy / "Procurement_Policy.docx",
        "Dual Approval Threshold",
        "All vendor contracts exceeding $50,000 require CFO and GC sign-off.",
    )
    (raw_policy / "Rubric_Table.csv").write_text(
        "Competency,Threshold,Notes\n"
        "FINOPS_L5,>=25% unit-cost gain,Measured over trailing 4 quarters\n",
        encoding="utf-8",
    )

    # Simulate an old stale encoded file that should be wiped on purge
    stale_dir = canonical_dir / "obsolete"
    stale_dir.mkdir(parents=True)
    (stale_dir / "old_rules.md").write_text(
        "## [AUTH:OLD-999] Obsolete Rule\n- **Title:** Old\n- **Verbatim Rule:** Outdated.\n",
        encoding="utf-8",
    )

    ingestor = CanonicalIngestor(canonical_dir)
    summary = ingestor.ingest_corpus(purge_encoded=True)

    assert "obsolete/old_rules.md" in summary["purged_files"]
    assert summary["files_processed"] == 4
    assert summary["total_authorities"] >= 5

    # Tier 1 compact catalog & JSON card verification
    index_text = (canonical_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "Canonical Knowledge Catalog" in index_text
    assert "legal/venue_statute.toc.md" in index_text
    assert "[AUTH:LEGAL-VENUE-STATUTE-001]" not in index_text
    assert "OLD-999" not in index_text

    catalog_data = json.loads((canonical_dir / "catalog.json").read_text(encoding="utf-8"))
    assert catalog_data["document_count"] == 4
    assert any(d["doc_id"] == "legal/venue_statute.md" for d in catalog_data["documents"])

    # Tier 2 per-document TOC verification
    toc_text = (canonical_dir / "legal" / "venue_statute.toc.md").read_text(encoding="utf-8")
    assert "[AUTH:LEGAL-VENUE-STATUTE-001]" in toc_text

    router = CanonicalRouter(canonical_dir)
    auths = router.list_authorities()
    assert "AUTH:OLD-999" not in auths
    assert "AUTH:LEGAL-VENUE-STATUTE-001" in auths
    assert "judicial district in which any defendant resides" in auths["AUTH:LEGAL-VENUE-STATUTE-001"].verbatim_quote
    assert any("1441" in a.verbatim_quote for a in auths.values())
    assert any("$50,000" in a.verbatim_quote for a in auths.values())
    assert any("FINOPS_L5" in a.verbatim_quote for a in auths.values())
    # Ensure raw directory files still exist after purge
    assert (raw_legal / "venue_statute.md").exists()


def test_canonical_ingestor_handles_direct_unanchored_markdown(tmp_path: Path) -> None:
    """Verifies un-anchored `.md` files placed directly under `canonical/<domain>/` get encoded safely."""
    canonical_dir = tmp_path / "canonical"
    finance_dir = canonical_dir / "finance"
    finance_dir.mkdir(parents=True)
    raw_file = finance_dir / "rev_rec_playbook.md"
    raw_file.write_text(
        "# ASC 606 Revenue Playbook\n\n"
        "## Five-Step Model\n"
        "Recognize revenue when control of promised goods or services transfers to the customer.\n",
        encoding="utf-8",
    )

    ingestor = CanonicalIngestor(canonical_dir)
    summary = ingestor.ingest_corpus(purge_encoded=False)
    assert summary["files_processed"] == 1
    assert (finance_dir / "rev_rec_playbook.authorities.md").exists()
    assert raw_file.exists()

    # Re-running with purge_encoded=True preserves the direct raw .md while rebuilding .authorities.md
    rebuilt = ingestor.ingest_corpus(purge_encoded=True)
    assert rebuilt["total_authorities"] == 1
    assert raw_file.exists()


def test_canonical_ingestor_llm_synopsis_and_stage1_tools(tmp_path: Path) -> None:
    """Verifies LLM catalog card synthesis and Stage 1 browse/search/read tools."""
    canonical_dir = tmp_path / "canonical"
    raw_legal = canonical_dir / "raw" / "legal"
    raw_legal.mkdir(parents=True)
    (raw_legal / "bankruptcy_rules.md").write_text(
        "# Federal Bankruptcy Rules\n\n"
        "## Automatic Stay Scope\n"
        "Filing stays all creditor collection actions against the estate.\n\n"
        "## Cash Collateral\n"
        "Debtor may not use cash collateral without consent or court order.\n",
        encoding="utf-8",
    )

    mock_llm = MockLLMProvider(
        structured_responses={
            "CanonicalDocumentSynopsisDraft": CanonicalDocumentSynopsisDraft(
                title="Federal Bankruptcy Rules Manual",
                authority_tier="statute_regulation",
                jurisdiction_scope="Federal Bankruptcy Courts",
                scope_synopsis="Governs automatic stay protections and post-petition cash collateral restrictions.",
            )
        }
    )
    ingestor = CanonicalIngestor(canonical_dir)
    ingestor.ingest_corpus(purge_encoded=True, llm=mock_llm)

    index_text = (canonical_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "Federal Bankruptcy Rules Manual" in index_text
    assert "Governs automatic stay protections" in index_text

    router = CanonicalRouter(canonical_dir)
    tools = {t.name: t for t in router.build_stage1_tools()}
    assert {"browse_canonical_toc", "search_canonical_authorities", "read_canonical_authority"} <= set(tools)

    toc_res = tools["browse_canonical_toc"].handler(doc_id="legal/bankruptcy_rules.md")
    assert "Automatic Stay Scope" in toc_res["content"]

    search_res = tools["search_canonical_authorities"].handler(query="cash collateral", domain="legal")
    assert len(search_res["matches"]) == 1
    matched_id = search_res["matches"][0]["auth_id"]

    read_res = tools["read_canonical_authority"].handler(auth_id=matched_id)
    assert "consent or court order" in read_res["verbatim_quote"]


def test_verify_and_hydrate_ledger_and_section_citations(tmp_path: Path) -> None:
    """Verifies programmatic Stage 2 ledger grounding and Stage 3 citation/quote checking."""
    matters_root = tmp_path / "matters"
    raw_dir = matters_root / "m_check" / "inputs" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "Contract.md").write_text(
        "Section 4.1 Termination requires 30 days advance written notice.\n",
        encoding="utf-8",
    )
    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("m_check")

    ledger = VerifiedFactLedger.model_validate(
        {
            "section_id": "sec_01",
            "verified_facts": [
                {
                    "fact_id": "f_real",
                    "query_addressed": "Notice window?",
                    "title": "Notice Clause",
                    "quote": "requires 30 days advance written notice.",
                    "locator": {
                        "source_type": "markdown",
                        "file_name": "Contract.md",
                        "locator_key": "CONTRACT-SEC-1",
                    },
                },
                {
                    "fact_id": "f_fake_loc",
                    "query_addressed": "Fee cap?",
                    "title": "Imaginary Clause",
                    "quote": "Liability capped at $10.",
                    "locator": {
                        "source_type": "markdown",
                        "file_name": "Contract.md",
                        "locator_key": "CONTRACT-SEC-999",
                    },
                },
            ],
            "unresolved_gaps": [],
        }
    )

    verified_ledger, warnings = ingestor.verify_and_hydrate_ledger("m_check", ledger)
    assert len(verified_ledger.verified_facts) == 1
    assert verified_ledger.verified_facts[0].fact_id == "f_real"
    assert verified_ledger.verified_facts[0].locator.payload_hash is not None
    assert len(warnings) == 1
    assert "CONTRACT-SEC-999" in verified_ledger.unresolved_gaps[0].rationale

    auth = CanonicalAuthorityRef(
        auth_id="AUTH:NOTICE-01",
        title="Notice Enforceability",
        verbatim_quote="Written notice deadlines are strictly enforced.",
        source_file="legal/contracts.md",
    )

    bad_section = SectionOutput.model_validate(
        {
            "section_id": "sec_01",
            "section_title": "Notice",
            "text": "Notice <ref n='1'>requires 30 days</ref>.",
            "supports": [
                {
                    "n": 1,
                    "items": [
                        {
                            "type": "evidence",
                            "title": "Wrong Quote",
                            "quote": "Completely fabricated sentence not in file.",
                            "locator": {
                                "source_type": "markdown",
                                "file_name": "Contract.md",
                                "locator_key": "CONTRACT-SEC-1",
                            },
                        },
                        {
                            "type": "reasoning",
                            "title": "Rule Application",
                            "body": "Applies <ref n='101'>the notice rule</ref>.",
                            "sub_supports": [
                                {
                                    "n": 101,
                                    "type": "authority",
                                    "title": "[AUTH:UNKNOWN-999] Bogus",
                                    "quote": "Fabricated holding never seen before.",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )
    cit_errors = ingestor.verify_section_citations(bad_section, verified_ledger, [auth])
    assert any("does not match verified ledger text" in e for e in cit_errors)
    assert any("AUTH:UNKNOWN-999" in e for e in cit_errors)
    assert any("does not match canonical verbatim text" in e for e in cit_errors)

    good_commonsense_section = SectionOutput.model_validate(
        {
            "section_id": "sec_01",
            "section_title": "Notice",
            "text": "Notice <ref n='1'>requires 30 days</ref>.",
            "supports": [
                {
                    "n": 1,
                    "items": [
                        {
                            "type": "evidence",
                            "title": "Notice Clause",
                            "quote": "requires 30 days advance written notice.",
                            "locator": {
                                "source_type": "markdown",
                                "file_name": "Contract.md",
                                "locator_key": "CONTRACT-SEC-1",
                            },
                        },
                        {
                            "type": "reasoning",
                            "title": "Commonsense Day Count",
                            "body": "Sending notice only 10 days ahead fails a 30-day requirement.",
                        },
                    ],
                }
            ],
        }
    )
    clean_errors = ingestor.verify_section_citations(
        good_commonsense_section, verified_ledger, []
    )
    assert clean_errors == []
