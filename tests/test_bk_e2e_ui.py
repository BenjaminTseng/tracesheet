# Run: uv run pytest tests/test_bk_e2e_ui.py -v
"""End-to-end UI shell, static asset, and dual-district (CACB + CAEB) verification tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.compilers.bankruptcy.routes import create_bankruptcy_app


def _copy_real_ui_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    shutil.copytree(Path("canonical/tables/bankruptcy"), ws / "canonical" / "tables" / "bankruptcy")
    shutil.copytree(Path("templates"), ws / "templates")
    shutil.copytree(Path("static"), ws / "static")
    return ws


def test_bankruptcy_ui_shell_assets_and_both_ca_districts_e2e(tmp_path: Path) -> None:
    """Verifies standalone UI shell, static JS/CSS, Martinez (CACB Ch.7) and Chen (CAEB Ch.13)."""
    ws = _copy_real_ui_workspace(tmp_path)
    app = create_bankruptcy_app(base_dir=ws, seed_samples=True)
    client = TestClient(app)

    # 1. Verify HTML & JS/CSS static serving.
    html_res = client.get("/")
    assert html_res.status_code == 200
    assert "/static/apps/bankruptcy/app.js" in html_res.text
    assert "/static/vendor/preact.mjs" in html_res.text

    js_res = client.get("/static/apps/bankruptcy/app.js")
    assert js_res.status_code == 200
    core_texts = [js_res.text]
    for core_asset in (
        "/static/core/shell.js",
        "/static/core/canvas.js",
        "/static/core/inspector.js",
        "/static/core/stepper.js",
    ):
        core_res = client.get(core_asset)
        assert core_res.status_code == 200, f"Failed to serve {core_asset}"
        core_texts.append(core_res.text)
    combined_js = "\n".join(core_texts)

    assert "FilingPacketDrawer" in js_res.text
    assert "NextBlockerStepper" in js_res.text
    assert "PlatformShell" in combined_js
    assert "TraceabilityCanvas" in combined_js
    assert "SourceInspectorDrawer" in combined_js
    assert "TriageStepperFrame" in combined_js
    assert "column-lane" in combined_js
    assert "artifact-sheet" in combined_js
    assert "sheet-table" in combined_js
    assert 'aria-modal="true"' in combined_js
    # Ensure P0 fake defaults were removed from static JS UI state initializers.
    assert "Elena Counsel" not in combined_js
    assert "useState('2021 Toyota Camry')" not in combined_js
    assert "[attested, setAttested] = useState(false)" in js_res.text

    # 2. Complete Case 1: bk_ch7_cacb_martinez (Resolve all Emerging Questions + Contradictions -> CACB Submit).
    m1 = client.get("/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/case").json()
    section_titles = [s["section_title"] for s in m1["compiled_bundle"]["artifact"]["sections"]]
    assert any("Form B 101" in t for t in section_titles)
    assert any("Form B 106Sum" in t for t in section_titles)
    assert any("Schedules A/B" in t for t in section_titles)
    assert "106Sum · 1c" in m1["compiled_bundle"]["artifact"]["sections"][1]["content"]
    assert m1["readiness"]["status"] == "BLOCKED"
    assert m1["calculations"]["exemptions"]["recommended_regime_id"] == "CA_CCP_703_140"

    for q in m1["emerging_questions"]:
        if q["status"] != "open":
            continue
        if q["rule_id"] == "SECURED_LOAN_MISSING_COLLATERAL_VALUE":
            client.post(
                f"/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/questions/{q['question_id']}/answer",
                json={
                    "selected_option": "add_or_link_collateral_asset",
                    "actor_name": "Paralegal UI",
                    "actor_role": "paralegal",
                    "rationale": "Added 2021 Toyota Camry valuation.",
                    "payload": {
                        "description": "2021 Toyota Camry",
                        "category": "vehicle",
                        "current_value": "16500.00",
                    },
                },
            )
        elif q["rule_id"] == "SECURED_CLAIM_MISSING_INTENTION":
            client.post(
                f"/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/questions/{q['question_id']}/answer",
                json={
                    "selected_option": "set_statement_of_intention",
                    "actor_name": "Paralegal UI",
                    "actor_role": "paralegal",
                    "rationale": "Reaffirm auto loan.",
                    "payload": {"statement_of_intention": "retain_and_reaffirm"},
                },
            )
        elif q["rule_id"] == "UNLISTED_CREDITOR_FROM_BANK_OUTFLOW":
            client.post(
                f"/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/questions/{q['question_id']}/answer",
                json={
                    "selected_option": "add_creditor_claim",
                    "actor_name": "Paralegal UI",
                    "actor_role": "paralegal",
                    "rationale": "Added Synchrony card from Chase ACH statement.",
                    "payload": {
                        "creditor_name": "Synchrony Bank",
                        "total_claim_amount": "2400.00",
                        "priority_type": "general_unsecured",
                    },
                },
            )

    m1_after_qs = client.get("/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/case").json()
    for t in m1_after_qs["tensions"]:
        if t["severity"] == "blocker":
            client.post(
                f"/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/tensions/{t['tension_id']}/resolve",
                json={
                    "actor_name": "Paralegal UI",
                    "actor_role": "paralegal",
                    "rationale": "Zelle $1,800 verified as family gift reimbursement.",
                },
            )

    m1_ready = client.get("/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/case").json()
    assert m1_ready["readiness"]["status"] == "READY"
    pkt1 = client.post("/api/v1/bankruptcy/matters/bk_ch7_cacb_martinez/compile-packet")
    assert pkt1.status_code == 200
    assert "CACB_F5005_4.pdf" in pkt1.json()["files"]

    # 3. Verify Case 2: bk_ch13_caeb_chen (CAEB Ch. 13 with CA_CCP_704 homestead & EDC 3-080 plan).
    m2 = client.get("/api/v1/bankruptcy/matters/bk_ch13_caeb_chen/case").json()
    assert m2["calculations"]["exemptions"]["recommended_regime_id"] == "CA_CCP_704"
    assert m2["calculations"]["eligibility"]["eligible"] is True
    assert m2["calculations"]["ch13_plan"] is not None

    # Resolve open critical questions (4-year tax returns / homestead acquisition if needed) and compile CAEB packet.
    for q in m2["emerging_questions"]:
        if q["status"] != "open" or q["severity"] != "critical":
            continue
        if q["rule_id"] == "CH13_FOUR_YEAR_TAX_RETURN_MISSING":
            client.post(
                f"/api/v1/bankruptcy/matters/bk_ch13_caeb_chen/questions/{q['question_id']}/answer",
                json={
                    "selected_option": "confirm_4yr_tax_returns",
                    "actor_name": "Paralegal UI",
                    "actor_role": "paralegal",
                    "rationale": "Verified 2022-2025 federal and California returns filed under § 1308.",
                    "payload": {},
                },
            )
    m2_ready = client.get("/api/v1/bankruptcy/matters/bk_ch13_caeb_chen/case").json()
    assert m2_ready["readiness"]["status"] == "READY"
    pkt2 = client.post("/api/v1/bankruptcy/matters/bk_ch13_caeb_chen/compile-packet")
    assert pkt2.status_code == 200
    assert "CAEB_EDC_3_080.pdf" in pkt2.json()["files"]
    assert "CAEB_EDC_3_096.pdf" in pkt2.json()["files"]
    assert "CAEB_ESIG.pdf" in pkt2.json()["files"]
    assert "field_lineage.json" in pkt2.json()["files"]
