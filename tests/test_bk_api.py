# Run: uv run pytest tests/test_bk_api.py -v
"""End-to-end FastAPI TestClient lifecycle tests for the standalone Bankruptcy Workbench."""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.compilers.bankruptcy.routes import create_bankruptcy_app


def _make_pdf_bytes(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    pg = doc.new_page(width=612, height=792)
    y = 72
    for ln in lines:
        pg.insert_text((56, y), ln, fontsize=10.5)
        y += 16
    raw = doc.tobytes()
    doc.close()
    return raw


def _setup_workspace(tmp_path: Path) -> Path:
    """Creates an isolated temporary workspace copying tables and templates dir."""
    ws = tmp_path / "ws"
    (ws / "canonical" / "tables" / "bankruptcy").mkdir(parents=True)
    shutil.copytree(
        Path("canonical/tables/bankruptcy"),
        ws / "canonical" / "tables" / "bankruptcy",
        dirs_exist_ok=True,
    )
    (ws / "templates").mkdir(parents=True)
    (ws / "templates" / "bankruptcy.html").write_text("<html><body>BK UI</body></html>", encoding="utf-8")
    (ws / "static").mkdir(parents=True)
    return ws


def test_full_bankruptcy_api_lifecycle_upload_resolve_compile_submit(tmp_path: Path) -> None:
    """Exercises init -> upload -> extract -> 409 gate -> resolve -> compile -> B121/matrix -> Rule 9011 submit."""
    ws = _setup_workspace(tmp_path)
    app = create_bankruptcy_app(base_dir=ws, seed_samples=True)
    client = TestClient(app)

    # 1. Verify pre-seeded sample cases + reference tables list.
    tables_res = client.get("/api/v1/bankruptcy/tables")
    assert tables_res.status_code == 200
    assert len(tables_res.json()["tables"]) >= 4

    matters_res = client.get("/api/v1/bankruptcy/matters")
    assert matters_res.status_code == 200
    matter_ids = {m["matter_id"] for m in matters_res.json()["matters"]}
    assert "bk_ch7_cacb_martinez" in matter_ids
    assert "bk_ch13_caeb_chen" in matter_ids

    # 2. Verify Martinez Ch. 7 starts BLOCKED due to Toyota auto loan + Synchrony ACH + Zelle deposit.
    m1 = client.get("/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/case").json()
    assert m1["readiness"]["status"] == "BLOCKED"
    assert len(m1["emerging_questions"]) >= 2
    assert len(m1["tensions"]) >= 1

    # Strict gate MUST return 409 Conflict when trying to compile final packet while BLOCKED.
    blocked_pkt = client.post("/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/compile-packet")
    assert blocked_pkt.status_code == 409

    # 3. Create a fresh case via API, upload raw PDFs, extract, resolve blockers, compile, and submit.
    init_res = client.post(
        "/api/v1/bankruptcy/matters",
        json={
            "matter_id": "api_live_test",
            "chapter": "7",
            "district": "CACB",
            "expected_filing_date": "2026-11-16",
        },
    )
    assert init_res.status_code == 200

    files_payload = [
        (
            "files",
            (
                "01_intake.pdf",
                _make_pdf_bytes(
                    [
                        "Debtor Profile & Intake Summary",
                        "Debtor Name: Jordan Alvarez",
                        "SSN: 321-54-9876",
                        "Street Address: 500 Grand Ave",
                        "City/State/Zip: Los Angeles, CA 90071",
                        "County of Residence: Los Angeles",
                        "Household Size: 1",
                        "CA Domicile Days: 2000",
                    ]
                ),
                "application/pdf",
            ),
        ),
        (
            "files",
            (
                "02_auto_loan.pdf",
                _make_pdf_bytes(
                    [
                        "Auto Finance Loan Statement",
                        "Lender: Ally Auto Finance",
                        "Creditor Address: PO Box 380901, Bloomington, MN 55438",
                        "Principal Balance: $12,000.00",
                        "Monthly Payment: $350.00",
                    ]
                ),
                "application/pdf",
            ),
        ),
    ]
    for m in range(5, 11):
        files_payload.append(
            (
                "files",
                (
                    f"ps_{m:02d}.pdf",
                    _make_pdf_bytes(
                        [
                            "ADP Earnings Statement",
                            "Employer: Pacific Health",
                            f"Pay Date: 2026-{m:02d}-28",
                            "Gross Pay: $4,600.00",
                            "Net Pay: $3,400.00",
                            "Tax Withheld: $950.00",
                            f"YTD Gross: ${4600 * m:,.2f}",
                        ]
                    ),
                    "application/pdf",
                ),
            )
        )

    up_res = client.post("/api/v1/bankruptcy/matters/api_live_test/upload", files=files_payload)
    assert up_res.status_code == 200
    assert len(up_res.json()["uploaded"]) == 8

    ext_res = client.post("/api/v1/bankruptcy/matters/api_live_test/extract")
    assert ext_res.status_code == 200
    case_json = ext_res.json()
    assert case_json["readiness"]["status"] == "BLOCKED"

    # Answer every open critical EmergingQuestionItem (car loan -> collateral + Form 108 intention).
    for q in case_json["emerging_questions"]:
        if q["status"] != "open":
            continue
        if q["rule_id"] == "SECURED_LOAN_MISSING_COLLATERAL_VALUE":
            client.post(
                f"/api/v1/bankruptcy/matters/api_live_test/questions/{q['question_id']}/answer",
                json={
                    "selected_option": "add_or_link_collateral_asset",
                    "actor_name": "Alex Paralegal",
                    "actor_role": "paralegal",
                    "rationale": "Verified KBB value for 2020 Honda Civic.",
                    "payload": {
                        "description": "2020 Honda Civic",
                        "category": "vehicle",
                        "current_value": "15500.00",
                    },
                },
            )
        elif q["rule_id"] == "SECURED_CLAIM_MISSING_INTENTION":
            client.post(
                f"/api/v1/bankruptcy/matters/api_live_test/questions/{q['question_id']}/answer",
                json={
                    "selected_option": "set_statement_of_intention",
                    "actor_name": "Alex Paralegal",
                    "actor_role": "paralegal",
                    "rationale": "Client elects to retain and reaffirm.",
                    "payload": {"statement_of_intention": "retain_and_reaffirm"},
                },
            )

    # Check readiness is now READY in <100ms!
    ready_case = client.get("/api/v1/bankruptcy/matters/api_live_test/case").json()
    assert ready_case["readiness"]["status"] == "READY"

    # Compile packet -> download Form_B121_RESTRICTED.pdf, B101.pdf, creditor_matrix.txt, field_lineage.json
    pkt_res = client.post("/api/v1/bankruptcy/matters/api_live_test/compile-packet")
    assert pkt_res.status_code == 200
    pkt_files = set(pkt_res.json()["files"])
    assert "B101.pdf" in pkt_files
    assert "Form_B121_RESTRICTED.pdf" in pkt_files
    assert "creditor_matrix.txt" in pkt_files
    assert "debtor.txt" in pkt_files
    assert "field_lineage.json" in pkt_files

    b101_dl = client.get("/api/v1/bankruptcy/matters/api_live_test/packet/files/B101.pdf")
    assert b101_dl.status_code == 200 and b101_dl.content.startswith(b"%PDF")

    # Submitting without signed declaration MUST be rejected (403 Forbidden)!
    no_decl_sub = client.post(
        "/api/v1/bankruptcy/matters/api_live_test/submit",
        json={
            "submission_mode": "ecf_train",
            "attorney_name": "Elena Counsel, Esq.",
            "attorney_bar_number": "CA-310044",
            "attested": True,
        },
    )
    assert no_decl_sub.status_code == 403

    # Upload signed F 5005-4 declaration -> Rule 9011 submit succeeds!
    decl_res = client.post(
        "/api/v1/bankruptcy/matters/api_live_test/declaration",
        files={"file": ("F5005_signed.pdf", _make_pdf_bytes(["/s/ Jordan Alvarez"]), "application/pdf")},
    )
    assert decl_res.status_code == 200

    sub_res = client.post(
        "/api/v1/bankruptcy/matters/api_live_test/submit",
        json={
            "submission_mode": "ecf_train",
            "attorney_name": "Elena Counsel, Esq.",
            "attorney_bar_number": "CA-310044",
            "attested": True,
        },
    )
    assert sub_res.status_code == 200
    receipt = sub_res.json()
    assert receipt["district"] == "CACB"
    assert receipt["assigned_case_number"]
    assert len(receipt["step_log"]) >= 4
