# Run: uv run pytest tests/test_bk_pdf_districts_and_vault.py -v
"""Deep tests for PyMuPDF baking, B121/FRBP 9037 isolation, overflow sheets, CACB/CAEB, and Rule 9011."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pymupdf
import pytest

from app.bankruptcy.calculators import compute_case_calculations
from app.bankruptcy.districts import CACBDistrictAdapter, CAEBDistrictAdapter
from app.bankruptcy.models import (
    AssetItem,
    BankruptcyCaseState,
    CanonicalCaseGraph,
    ClaimItem,
    FilingReadinessReport,
    HumanOverrideRecord,
    PartyEntity,
    ProvenanceField,
)
from app.bankruptcy.pdf_engine import AcroFormFillerAndBaker
from app.bankruptcy.vault import CredentialAndTOTPVault, Rule9011SignOffGate
from app.core.pii import PIITokenizer
from app.core.tables import StatutoryTableRegistry


def _ov(val):
    return ProvenanceField[type(val)](
        value=val,
        verification_status="human_overridden",
        override=HumanOverrideRecord(
            actor_name="Paralegal Test",
            actor_role="paralegal",
            rationale="Verified fixture value.",
        ),
    )


def test_baked_pdfs_pii_isolation_overflow_sheets_and_lineage(tmp_path: Path) -> None:
    """Verifies zero unbaked widgets, strict B121 SSN isolation, overflow sheets, and field_lineage.json."""
    matters_root = tmp_path / "matters"
    tokenizer = PIITokenizer(matters_root)
    ssn_token = tokenizer.register_raw_value("bk_pdf_1", "ssn", "987-65-4321")
    acct_token = tokenizer.register_raw_value("bk_pdf_1", "account", "4455667788991234")

    # 10 assets and 10 unsecured claims -> forces continuation pages on B106AB and B106EF!
    assets = [
        AssetItem(
            asset_id=f"asset_{i}",
            category="other" if i > 1 else "bank_account",
            description=f"Asset Item {i} ({acct_token if i == 1 else 'Item'})",
            current_value=_ov(Decimal("1000.00")),
        )
        for i in range(1, 11)
    ]
    claims = [
        ClaimItem(
            claim_id=f"claim_{i}",
            creditor_name=f"Creditor Number {i}",
            creditor_address_lines=[f"{i}00 Market Street"],
            city="Los Angeles",
            state="CA",
            zip_code="90012",
            priority_type="general_unsecured",
            total_claim_amount=_ov(Decimal("500.00")),
        )
        for i in range(1, 11)
    ]
    claims.append(
        ClaimItem(
            claim_id="claim_irs",
            creditor_name="Internal Revenue Service",
            creditor_address_lines=["PO Box 7346"],
            city="Philadelphia",
            state="PA",
            zip_code="19101",
            priority_type="priority_tax",
            total_claim_amount=_ov(Decimal("2500.00")),
        )
    )

    graph = CanonicalCaseGraph(
        matter_id="bk_pdf_1",
        chapter="7",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Carlos Mendez"),
                ssn_token_or_ein=ssn_token,
                street_address="100 Main St",
                city="Los Angeles",
                state="CA",
                zip_code="90012",
                county_of_residence="Los Angeles",
                ca_domicile_days_continuous=_ov(2000),
                household_size=_ov(1),
            )
        ],
        assets=assets,
        claims=claims,
    )
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    calcs = compute_case_calculations(graph, reg)
    state = BankruptcyCaseState(
        case_graph=graph,
        calculations=calcs,
        readiness=FilingReadinessReport(status="READY"),
    )

    templates_dir = tmp_path / "templates"
    packet_dir = tmp_path / "packet"
    baker = AcroFormFillerAndBaker(templates_dir=templates_dir, tokenizer=tokenizer)
    pdfs, lineage_path, lineage = baker.compile_forms(state, packet_dir)

    pdf_names = {p.name for p in pdfs}
    assert "B101.pdf" in pdf_names
    assert "B106AB.pdf" in pdf_names
    assert "B106EF.pdf" in pdf_names
    assert "Form_B121_RESTRICTED.pdf" in pdf_names
    assert "CACB_F5005_4.pdf" in pdf_names

    # Verify zero interactive widgets remain & FRBP 9037 SSN isolation holds across ALL public PDFs.
    for p in pdfs:
        with pymupdf.open(str(p)) as doc:
            for page in doc:
                assert list(page.widgets() or []) == []

        with pdfplumber.open(str(p)) as plum:
            extracted_txt = "\n".join(pg.extract_text() or "" for pg in plum.pages)
            if p.name == "Form_B121_RESTRICTED.pdf":
                assert "987-65-4321" in extracted_txt
            else:
                assert "987-65-4321" not in extracted_txt
                assert "4455667788991234" not in extracted_txt
                if p.name == "B106AB.pdf":
                    assert "****1234" in extracted_txt
                    assert "Continuation Sheet" in extracted_txt
                    assert "Asset Item 10" in extracted_txt
                if p.name == "B106EF.pdf":
                    assert "Continuation Sheet" in extracted_txt
                    assert "Creditor Number 10" in extracted_txt

    # Verify field_lineage.json maps filled widgets.
    parsed_lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert len(parsed_lineage) == len(lineage) and len(lineage) > 20
    assert any(
        e["form_id"] == "B106Sum" and e["rendered_value"] == "$10,000.00"
        for e in parsed_lineage
    )


def test_cacb_and_caeb_matrix_rules_8mb_splitter_and_rule9011_vault(tmp_path: Path) -> None:
    """Tests CACB IRS/FTB/Debtor exclusions, CAEB PDF chunking, TOTP generation, and Rule 9011 gate."""
    matters_root = tmp_path / "matters"
    tokenizer = PIITokenizer(matters_root)
    ssn_tok = tokenizer.register_raw_value("bk_dist_1", "ssn", "111-22-3333")

    graph = CanonicalCaseGraph(
        matter_id="bk_dist_1",
        chapter="13",
        district="CACB",
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Sandra Lin"),
                ssn_token_or_ein=ssn_tok,
                street_address="200 Pine St",
                city="Los Angeles",
                state="CA",
                zip_code="90015",
                ca_domicile_days_continuous=_ov(1500),
                household_size=_ov(1),
            )
        ],
        claims=[
            ClaimItem(
                claim_id="c_debtor",
                creditor_name="Sandra Lin",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("100.00")),
            ),
            ClaimItem(
                claim_id="c_irs",
                creditor_name="Internal Revenue Service",
                priority_type="priority_tax",
                total_claim_amount=_ov(Decimal("4000.00")),
            ),
            ClaimItem(
                claim_id="c_ftb",
                creditor_name="Franchise Tax Board",
                priority_type="priority_tax",
                total_claim_amount=_ov(Decimal("1200.00")),
            ),
            ClaimItem(
                claim_id="c_chase",
                creditor_name="Chase Card Services~^ Very Long Creditor Name Exceeding Fifty Characters Here",
                creditor_address_lines=["   PO Box 15298 Very Long Suite Line Exceeding Forty Chars"],
                city="Wilmington",
                state="DE",
                zip_code="19850",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("8500.00")),
            ),
        ],
        signed_declaration_uploaded=True,
        signed_declaration_sha256="sha256:decl_1234",
        attorney_name="David Counsel, Esq.",
        attorney_bar_number="CA-299100",
    )

    # 1. CACB matrix strips Debtor, IRS, FTB and enforces line lengths; Ch. 11 Case Upload fails.
    cacb = CACBDistrictAdapter()
    matrix_txt, notes = cacb.format_creditor_matrix(graph)
    assert "Internal Revenue Service" not in matrix_txt
    assert "Franchise Tax Board" not in matrix_txt
    assert "Sandra Lin" not in matrix_txt
    assert "Chase Card Services" in matrix_txt
    assert "~" not in matrix_txt and "^" not in matrix_txt
    assert len(notes) == 3

    for block in matrix_txt.strip().split("\n\n"):
        lines = block.splitlines()
        assert len(lines) <= 5
        assert len(lines[0]) <= 50
        for addr_line in lines[1:]:
            assert len(addr_line) <= 40

    debtor_txt = cacb.format_debtor_txt(graph, tokenizer)
    assert "111-22-3333" in debtor_txt
    with pytest.raises(ValueError):
        cacb.format_debtor_txt(graph.model_copy(update={"chapter": "11_subv"}), tokenizer)

    # 2. CAEB 8MB splitter (tested with small chunk limit on a multi-page PDF!).
    pkt_dir = tmp_path / "caeb_pkt"
    pkt_dir.mkdir()
    b121_dummy = pkt_dir / "Form_B121_RESTRICTED.pdf"
    doc_b121 = pymupdf.open()
    doc_b121.new_page().insert_text((50, 50), "Form B121 Restricted")
    doc_b121.save(str(b121_dummy))
    doc_b121.close()

    big_pdf = pkt_dir / "Schedules_Combined.pdf"
    doc_big = pymupdf.open()
    for pno in range(1, 7):
        pg = doc_big.new_page()
        for row_idx in range(25):
            pg.insert_text(
                (50, 40 + row_idx * 24),
                f"Page {pno} Row {row_idx}: Exhibit Claim Ref #{pno * 1000 + row_idx * 37} Value ${row_idx * 123 + pno}.00",
            )
    doc_big.save(str(big_pdf))
    doc_big.close()

    total_size = big_pdf.stat().st_size
    caeb = CAEBDistrictAdapter(max_pdf_bytes=int(total_size * 0.55))
    packaged, errs = caeb.package_pdfs(pkt_dir, [b121_dummy, big_pdf], chapter="13")
    assert errs == []
    split_parts = [p for p in packaged if p.name.startswith("Schedules_Combined_part")]
    assert len(split_parts) >= 2
    assert all(p.stat().st_size <= int(total_size * 0.55) for p in split_parts)

    # 3. Credential Vault TOTP + Rule 9011 Gate
    vault = CredentialAndTOTPVault(tmp_path / "vault" / "creds.json")
    vault.save_credential("ecf_train", "train_user", "secret_pw", "JBSWY3DPEHPK3PXP")
    totp = vault.generate_totp_code("ecf_train", timestamp=1700000000)
    assert len(totp) == 6 and totp.isdigit()

    gate = Rule9011SignOffGate()
    blocked_state = BankruptcyCaseState(
        case_graph=graph,
        readiness=FilingReadinessReport(status="BLOCKED", blocking_reasons=["Open question"]),
    )
    with pytest.raises(PermissionError):
        gate.mint_token(blocked_state, packaged, "David Counsel, Esq.", "CA-299100", True)

    ready_state = BankruptcyCaseState(
        case_graph=graph,
        readiness=FilingReadinessReport(status="READY"),
    )
    token = gate.mint_token(ready_state, packaged, "David Counsel, Esq.", "CA-299100", True)
    assert gate.verify_token(token, ready_state, packaged) is True

    receipt = caeb.submit_packet(
        ready_state,
        packaged,
        submission_mode="ecf_train",
        attorney_name=token.attorney_name,
        attorney_bar_number=token.attorney_bar_number,
        totp_code=totp,
    )
    assert receipt.district == "CAEB"
    assert receipt.assigned_case_number
