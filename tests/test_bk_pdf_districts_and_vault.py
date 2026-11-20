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

from app.compilers.bankruptcy.calculators import compute_case_calculations
from app.compilers.bankruptcy.districts import CACBDistrictAdapter, CAEBDistrictAdapter
from app.compilers.bankruptcy.form_binder import AcroFormFillerAndBaker
from app.compilers.bankruptcy.schema import (
    AssetItem,
    BankruptcyCaseState,
    BudgetLineItem,
    CanonicalCaseGraph,
    ClaimItem,
    FilingReadinessReport,
    HumanOverrideRecord,
    PartyEntity,
    PaystubRecord,
    ProvenanceField,
)
from app.compilers.bankruptcy.vault import CredentialAndTOTPVault, Rule9011SignOffGate
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


def test_real_official_pdf_templates_and_canonical_corpus(tmp_path: Path) -> None:
    """Verifies real downloaded official U.S. Courts/CACB/CAEB AcroForm templates, baking, and canonical rules."""
    # 1. Confirm real canonical bankruptcy authorities exist with [AUTH:...] markers.
    canon_dir = Path("canonical/bankruptcy")
    expected_authorities = [
        "ca_exemptions_and_title11_statutes.md",
        "cacb_lbr_1001_1_through_1073_1.md",
        "cacb_cmecf_procedures_5005_4.md",
        "caeb_local_bankruptcy_rules_2026_04.md",
        "uscourts_instructions_individuals_2025_04.md",
    ]
    for fname in expected_authorities:
        fpath = canon_dir / fname
        assert fpath.exists(), f"Missing ingested canonical file: {fpath}"
        assert "[AUTH:" in fpath.read_text(encoding="utf-8")

    # 2. Fill & bake real official templates from `canonical/tables/bankruptcy/templates/`.
    matters_root = tmp_path / "matters_real"
    tokenizer = PIITokenizer(matters_root)
    ssn_token = tokenizer.register_raw_value("bk_real_1", "ssn", "555-44-3322")

    graph = CanonicalCaseGraph(
        matter_id="bk_real_1",
        chapter="7",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Elena Maria Navarro"),
                ssn_token_or_ein=ssn_token,
                street_address="420 S Spring St",
                city="Los Angeles",
                state="CA",
                zip_code="90013",
                county_of_residence="Los Angeles",
                ca_domicile_days_continuous=_ov(2500),
                household_size=_ov(1),
            )
        ],
        assets=[
            AssetItem(
                asset_id="veh_1",
                category="vehicle",
                description="2020 Honda Civic",
                current_value=_ov(Decimal("14000.00")),
                owned_free_and_clear=True,
            ),
            AssetItem(
                asset_id="bank_1",
                category="bank_account",
                description="Chase Checking (...4812)",
                current_value=_ov(Decimal("3200.00")),
            ),
        ],
        claims=[
            ClaimItem(
                claim_id="cl_1",
                creditor_name="Capital One Bank",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("4800.00")),
            )
        ],
    )
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    calcs = compute_case_calculations(graph, reg)
    state = BankruptcyCaseState(
        case_graph=graph,
        calculations=calcs,
        readiness=FilingReadinessReport(status="READY"),
    )

    real_templates_dir = Path("canonical/tables/bankruptcy/templates")
    packet_dir = tmp_path / "packet_real"
    baker = AcroFormFillerAndBaker(templates_dir=real_templates_dir, tokenizer=tokenizer)
    pdfs, _lineage_path, lineage = baker.compile_forms(state, packet_dir)

    # All real templates must bake cleanly with 0 active widgets remaining.
    for p in pdfs:
        with pymupdf.open(str(p)) as doc:
            for page in doc:
                assert list(page.widgets() or []) == []

    # Official B106Sum line 1c widget must have baked $17,200.00 and line ref in field_lineage.
    assert any(
        e.form_id == "B106Sum"
        and e.pdf_field_name == "1c"
        and e.form_line_ref == "Form 106Sum · Line 1c"
        and e.rendered_value == "$17,200.00"
        for e in lineage
    )
    # Restricted B121 unmasked SSN never appears on any public PDF lineage entry.
    assert any(
        e.form_id == "B121" and e.pdf_field_name == "Debtor1a.SSNum" and "555-44-3322" in e.rendered_value
        for e in lineage
    )
    assert all(
        "555-44-3322" not in e.rendered_value
        for e in lineage
        if e.form_id != "B121"
    )


def test_b106c_schwab_100pct_fmv_and_line3_homestead_checkboxes_in_pdf(tmp_path: Path) -> None:
    """Verifies Official B106C 100% FMV & Line 3 checkboxes plus B122A spouse/marital adjustment widgets."""
    matters_root = tmp_path / "matters_schwab"
    tokenizer = PIITokenizer(matters_root)
    ssn_token = tokenizer.register_raw_value("bk_schwab_1", "ssn", "222-33-4444")

    paystubs = []
    for m in range(5, 11):
        paystubs.append(
            PaystubRecord(
                paystub_id=f"d1_{m}",
                party_id="d1",
                employer="NorthStar Inc",
                pay_period_start=datetime.date(2026, m, 1),
                pay_period_end=datetime.date(2026, m, 28),
                pay_date=datetime.date(2026, m, 28),
                gross_pay=_ov(Decimal("5000.00")),
                net_pay=_ov(Decimal("3800.00")),
                tax_withheld=_ov(Decimal("900.00")),
            )
        )
        paystubs.append(
            PaystubRecord(
                paystub_id=f"sp_{m}",
                party_id="non_filing_spouse",
                employer="Spouse LLC",
                pay_period_start=datetime.date(2026, m, 1),
                pay_period_end=datetime.date(2026, m, 28),
                pay_date=datetime.date(2026, m, 28),
                gross_pay=_ov(Decimal("4500.00")),
                net_pay=_ov(Decimal("3400.00")),
                tax_withheld=_ov(Decimal("800.00")),
            )
        )

    graph = CanonicalCaseGraph(
        matter_id="bk_schwab_1",
        chapter="7",
        district="CACB",
        marital_status="married_filing_separately_together",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Jordan Case"),
                ssn_token_or_ein=ssn_token,
                street_address="777 Main St",
                city="Los Angeles",
                state="CA",
                zip_code="90012",
                county_of_residence="Los Angeles",
                ca_domicile_days_continuous=_ov(2000),
                household_size=_ov(2),
            ),
            PartyEntity(
                party_id="non_filing_spouse",
                role="non_filing_spouse",
                full_name=_ov("Alex Case"),
                ca_domicile_days_continuous=_ov(2000),
                household_size=_ov(2),
            ),
        ],
        assets=[
            AssetItem(
                asset_id="home_roll",
                category="real_property",
                description="777 Main St Residence",
                current_value=_ov(Decimal("600000.00")),
                acquisition_date=_ov(datetime.date(2025, 4, 1)),  # < 1215 days
                prior_state_residence_rollover_amount=Decimal("100000.00"),  # > $214k exempt
                owned_free_and_clear=True,
            ),
            AssetItem(
                asset_id="pi_1",
                category="personal_injury",
                description="Auto Accident Claim",
                valuation_state="unknown",
                current_value=_ov(Decimal("0.00")),
            ),
        ],
        paystubs=paystubs,
        marital_adjustment_deductions=[
            BudgetLineItem(
                item_id="ma_1",
                category="vehicle_payment",
                description="Spouse Car Note",
                monthly_amount=_ov(Decimal("750.00")),
            )
        ],
    )
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    calcs = compute_case_calculations(graph, reg)
    state = BankruptcyCaseState(
        case_graph=graph,
        calculations=calcs,
        readiness=FilingReadinessReport(status="READY"),
    )

    real_templates_dir = Path("canonical/tables/bankruptcy/templates")
    packet_dir = tmp_path / "packet_schwab"
    baker = AcroFormFillerAndBaker(templates_dir=real_templates_dir, tokenizer=tokenizer)
    _pdfs, _lineage_path, lineage = baker.compile_forms(state, packet_dir)

    # Verify B106C 100% of FMV checkbox and Line 3 (>214k + <1215d) checkboxes fired in lineage & PDF!
    assert any(
        e.form_id == "B106C" and e.pdf_field_name == "check 2.2" and "100% of FMV" in (e.form_line_ref or "")
        for e in lineage
    )
    assert any(
        e.form_id == "B106C" and e.pdf_field_name == "check 3" and "Yes" in (e.form_line_ref or "")
        for e in lineage
    )
    assert any(
        e.form_id == "B106C" and e.pdf_field_name == "check 3-1" and "Yes" in (e.form_line_ref or "")
        for e in lineage
    )
    assert any(
        e.form_id == "B122A1" and e.pdf_field_name == "Debto2.Quest2.0" and e.rendered_value == "$4,500.00"
        for e in lineage
    )
    assert any(
        e.form_id == "B122A2" and e.pdf_field_name == "Quest3" and e.rendered_value == "$750.00"
        for e in lineage
    )
    with pymupdf.open(str(packet_dir / "B106C.pdf")) as doc:
        assert all(list(pg.widgets() or []) == [] for pg in doc)
        c_txt = "\n".join(pg.get_text() or "" for pg in doc)
        assert "777 Main St" in c_txt
        assert "Auto Accident Claim" in c_txt
        assert "Unknown" in c_txt
        assert "704.730" in c_txt
        assert "704.140" in c_txt
        assert "100% of fair market value" in c_txt
