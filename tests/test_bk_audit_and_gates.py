# Run: uv run pytest tests/test_bk_audit_and_gates.py -v
"""Deep tests for declarative dependencies, bank outflow forensics, plausibility checks, and strict gate."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

from app.bankruptcy.audit import (
    DeclarativeDependencyAuditor,
    FilingReadinessGate,
    PlausibilityAuditEngine,
    QuantitativeForensicAuditor,
)
from app.bankruptcy.calculators import compute_case_calculations
from app.bankruptcy.models import (
    AssetItem,
    BankStatementPeriod,
    BankTransactionItem,
    BankruptcyCaseState,
    BudgetLineItem,
    CanonicalCaseGraph,
    ClaimItem,
    HistoricalTransaction,
    HumanOverrideRecord,
    MonthlyBudgetScheduleIJ,
    PartyEntity,
    PaystubRecord,
    ProvenanceField,
)
from app.bankruptcy.service import BankruptcyCaseService
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


def _complete_paystubs() -> list[PaystubRecord]:
    stubs = []
    for m in range(5, 11):
        stubs.append(
            PaystubRecord(
                paystub_id=f"ps_{m}",
                employer="Acme Co",
                pay_period_start=datetime.date(2026, m, 1),
                pay_period_end=datetime.date(2026, m, 28),
                pay_date=datetime.date(2026, m, 28),
                gross_pay=_ov(Decimal("5500.00")),
                net_pay=_ov(Decimal("4100.00")),
                ytd_gross=_ov(Decimal(str(5500 * m))),
                tax_withheld=_ov(Decimal("1100.00")),
                deposit_account_last4="4829",
            )
        )
    return stubs


def test_bidirectional_car_and_loan_dependency_and_paystub_401k_rules() -> None:
    """Tests car<->car-loan emergence, 401(k) omission, and CMI gap detection."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    auditor = DeclarativeDependencyAuditor(reg)

    # 1. Vehicle on A/B with no loan + Auto loan on D with no collateral + Paystub w/ 401(k) + missing CMI months
    graph = CanonicalCaseGraph(
        matter_id="dep_1",
        chapter="7",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Alex Rivera"),
                ca_domicile_days_continuous=_ov(1500),
                household_size=_ov(1),
            )
        ],
        assets=[
            AssetItem(
                asset_id="car_free",
                category="vehicle",
                description="2021 Honda Civic",
                current_value=_ov(Decimal("18500.00")),
                owned_free_and_clear=None,
            ),
            AssetItem(
                asset_id="acct_1",
                category="bank_account",
                description="Chase Checking",
                account_last4="4829",
                current_value=_ov(Decimal("1200.00")),
            ),
        ],
        claims=[
            ClaimItem(
                claim_id="loan_toyota",
                creditor_name="Toyota Financial Services",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("14200.00")),
                collateral_asset_id=None,
                statement_of_intention=None,
            )
        ],
        paystubs=[
            PaystubRecord(
                paystub_id="ps_may",
                employer="Acme Co",
                pay_period_start=datetime.date(2026, 5, 1),
                pay_period_end=datetime.date(2026, 5, 31),
                pay_date=datetime.date(2026, 5, 31),
                gross_pay=_ov(Decimal("5500.00")),
                net_pay=_ov(Decimal("4100.00")),
                tax_withheld=_ov(Decimal("1100.00")),
                retirement_deduction=_ov(Decimal("250.00")),
                deposit_account_last4="4829",
            )
        ],
    )
    calcs = compute_case_calculations(graph, reg)
    qs = auditor.audit(graph, calcs)
    rules_fired = {q.rule_id for q in qs}

    assert "ASSET_MISSING_LIEN_STATUS" in rules_fired
    assert "SECURED_LOAN_MISSING_COLLATERAL_VALUE" in rules_fired
    assert "SECURED_CLAIM_MISSING_INTENTION" in rules_fired
    assert "PAYSTUB_RETIREMENT_MISSING_ON_AB" in rules_fired
    assert "CMI_WINDOW_GAP" in rules_fired

    # Resolve car free-and-clear, link Toyota loan to a new asset, add 401k, set intention, fill CMI months.
    resolved_graph = graph.model_copy(
        update={
            "assets": [
                graph.assets[0].model_copy(update={"owned_free_and_clear": True}),
                graph.assets[1],
                AssetItem(
                    asset_id="car_toyota",
                    category="vehicle",
                    description="2022 Toyota RAV4",
                    current_value=_ov(Decimal("24000.00")),
                ),
                AssetItem(
                    asset_id="ret_401k",
                    category="retirement",
                    description="Acme 401(k)",
                    current_value=_ov(Decimal("15000.00")),
                ),
            ],
            "claims": [
                graph.claims[0].model_copy(
                    update={
                        "collateral_asset_id": "car_toyota",
                        "statement_of_intention": "retain_and_reaffirm",
                    }
                )
            ],
            "paystubs": _complete_paystubs(),
        }
    )
    calcs2 = compute_case_calculations(resolved_graph, reg)
    qs2 = auditor.audit(resolved_graph, calcs2)
    assert [q for q in qs2 if q.severity == "critical"] == []


def test_forensic_bank_outflow_matcher_ytd_mismatch_and_strict_gate() -> None:
    """Tests bank ACH unlisted creditor detection, unexplained deposits, plausibility, and gate blocking."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    dep_auditor = DeclarativeDependencyAuditor(reg)
    forensic = QuantitativeForensicAuditor()
    plaus = PlausibilityAuditEngine()
    gate = FilingReadinessGate()

    stubs = _complete_paystubs()
    # Corrupt August YTD so YTD delta diverges from summed paystubs!
    stubs[3] = stubs[3].model_copy(update={"ytd_gross": _ov(Decimal("31000.00"))})

    graph = CanonicalCaseGraph(
        matter_id="forensic_1",
        chapter="7",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Elena Martinez"),
                ca_domicile_days_continuous=_ov(1500),
                household_size=_ov(1),
            )
        ],
        assets=[
            AssetItem(
                asset_id="acct_4829",
                category="bank_account",
                description="Chase Checking",
                account_last4="4829",
                current_value=_ov(Decimal("1400.00")),
            ),
            AssetItem(
                asset_id="unverified_watch",
                category="jewelry",
                description="Watch",
                # Intentionally unverified field!
                current_value=ProvenanceField[Decimal](
                    value=Decimal("900.00"),
                    verification_status="unverified",
                ),
            ),
        ],
        claims=[],
        paystubs=stubs,
        bank_statements=[
            BankStatementPeriod(
                statement_id="stmt_aug",
                institution="Chase",
                account_last4="4829",
                period_start=datetime.date(2026, 8, 1),
                period_end=datetime.date(2026, 8, 31),
                beginning_balance=_ov(Decimal("1200.00")),
                ending_balance=_ov(Decimal("1400.00")),
                total_deposits=_ov(Decimal("5900.00")),
                payroll_deposits=_ov(Decimal("4100.00")),  # $1,800 unexplained deposit!
                flagged_transactions=[
                    BankTransactionItem(
                        tx_id="tx_sync",
                        tx_date=datetime.date(2026, 8, 12),
                        direction="debit",
                        payee_or_memo="SYNCHRONY BANK ACH PAYMENT",
                        amount=Decimal("340.00"),
                        category_hint="debt_payment",
                    ),
                    BankTransactionItem(
                        tx_id="tx_xfer",
                        tx_date=datetime.date(2026, 8, 15),
                        direction="debit",
                        payee_or_memo="ACH TRANSFER TO CHIME",
                        amount=Decimal("400.00"),
                        category_hint="account_transfer",
                        target_account_last4="9912",
                    ),
                ],
            )
        ],
        budget=MonthlyBudgetScheduleIJ(
            expense_items=[
                BudgetLineItem(
                    item_id="e_rent",
                    category="rent_or_mortgage",
                    description="Rent",
                    monthly_amount=_ov(Decimal("2200.00")),
                )
            ]
        ),
    )

    calcs = compute_case_calculations(graph, reg)
    dep_qs = dep_auditor.audit(graph, calcs)
    forensic_qs, tensions = forensic.audit(graph, calcs)
    plaus_warnings = plaus.audit(graph, calcs)

    all_qs = dep_qs + forensic_qs
    q_rules = {q.rule_id for q in all_qs}
    t_ids = {t.tension_id for t in tensions}
    p_ids = {p.tension_id for p in plaus_warnings}

    assert "UNLISTED_CREDITOR_FROM_BANK_OUTFLOW" in q_rules
    assert "UNDISCLOSED_ACCOUNT_TRANSFER" in q_rules
    assert any(tid.startswith("tension_cmi_vs_ytd") for tid in t_ids)
    assert "tension_unexplained_bank_deposits" in t_ids
    assert "plaus_zero_food" in p_ids
    assert "plaus_anomalously_low_debt" in p_ids

    # Gate MUST block because of unverified watch, open critical questions, and unresolved blockers.
    state = BankruptcyCaseState(
        case_graph=graph,
        calculations=calcs,
        emerging_questions=all_qs,
        tensions=tensions,
        plausibility_warnings=plaus_warnings,
    )
    report = gate.evaluate(state)
    assert report.status == "BLOCKED"
    assert any("unverified_watch" in p or "assets[1].current_value" in p for p in report.unverified_field_paths)
    assert len(report.unresolved_critical_questions) >= 2
    assert len(report.unresolved_critical_tensions) >= 2


def test_hidden_injury_claim_and_bidirectional_sofa_sync_and_paystub_gap(tmp_path: Path) -> None:
    """Verifies trauma PI detector, bidirectional SOFA Line 9 sync, 60d paystub gap, spousal waiver, and resolutions."""
    import shutil

    ws = tmp_path / "ws_audit"
    shutil.copytree(Path("canonical/tables/bankruptcy"), ws / "canonical" / "tables" / "bankruptcy")
    svc = BankruptcyCaseService(base_dir=ws)

    graph = CanonicalCaseGraph(
        matter_id="audit_partner_1",
        chapter="7",
        marital_status="married_filing_separately_together",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=[
            PartyEntity(
                party_id="d1",
                role="debtor_1",
                full_name=_ov("Jordan Lane"),
                ca_domicile_days_continuous=_ov(2000),
                household_size=_ov(1),
            )
        ],
        assets=[
            AssetItem(
                asset_id="cash_1",
                category="bank_account",
                description="Checking Account",
                current_value=_ov(Decimal("5000.00")),
            )
        ],
        claims=[
            ClaimItem(
                claim_id="med_trauma",
                creditor_name="Riverside Trauma & Emergency Physicians",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("4200.00")),
                is_trauma_or_medical_creditor=True,
            )
        ],
        # Latest paystub is Sept 25 -> > 45 days before Nov 16 -> 60-day payment advice gap!
        paystubs=[
            PaystubRecord(
                paystub_id=f"ps_{m}",
                employer="Pacific Co",
                pay_period_start=datetime.date(2026, m, 1),
                pay_period_end=datetime.date(2026, m, 25),
                pay_date=datetime.date(2026, m, 25),
                gross_pay=_ov(Decimal("3000.00")),
                net_pay=_ov(Decimal("2400.00")),
                tax_withheld=_ov(Decimal("500.00")),
            )
            for m in range(5, 10)
        ],
        budget=MonthlyBudgetScheduleIJ(
            expense_items=[
                BudgetLineItem(
                    item_id="rent_1",
                    category="rent_or_mortgage",
                    description="Apartment Rent",
                    monthly_amount=_ov(Decimal("2000.00")),
                )
            ]
        ),
        historical_transactions=[
            HistoricalTransaction(
                tx_id="tx_pl",
                sofa_part="lawsuit_garnishment",
                description="Slip and fall claim v. Retail Store",
                party_role="plaintiff",
                amount=_ov(Decimal("0.00")),
            ),
            HistoricalTransaction(
                tx_id="tx_def",
                sofa_part="lawsuit_garnishment",
                description="Portfolio Recovery Collection Action",
                party_role="defendant",
                amount=_ov(Decimal("3100.00")),
            ),
        ],
    )
    state = svc.recompute_state(BankruptcyCaseState(case_graph=graph))
    fired_rules = {q.rule_id for q in state.emerging_questions if q.status == "open"}
    assert "POTENTIAL_PERSONAL_INJURY_OR_WORKERS_COMP_CLAIM" in fired_rules
    assert "SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB" in fired_rules
    assert "SOFA_LAWSUIT_DEFENDANT_MISSING_ON_EF" in fired_rules
    assert "RENTER_MISSING_SECURITY_DEPOSIT_LINE_28" in fired_rules
    assert "PAYSTUB_60_DAY_CONTINUITY_GAP" in fired_rules
    assert "MARRIED_SEPARATE_703_SPOUSAL_WAIVER" in fired_rules
    assert "MANDATORY_ASSET_AND_WINDFALL_SWEEP" in fired_rules

    # Resolve SOFA plaintiff sync -> creates Schedule A/B Unknown claim asset & re-audits cleanly.
    q_pl = next(q for q in state.emerging_questions if q.rule_id == "SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB")
    state = svc.answer_question(
        "audit_partner_1",
        q_pl.question_id,
        "sync_lawsuit_to_schedule_ab",
        "Paralegal Test",
        "paralegal",
        "Synced SOFA plaintiff suit as Unknown FMV asset on Line 33.",
        {"category": "personal_injury", "description": "Slip and fall bodily injury claim", "valuation_state": "unknown"},
    )
    assert any(a.category == "personal_injury" and a.valuation_state == "unknown" for a in state.case_graph.assets)

    # Resolve SOFA defendant sync -> adds disputed claim on Schedule E/F for automatic stay notice.
    q_def = next(q for q in state.emerging_questions if q.rule_id == "SOFA_LAWSUIT_DEFENDANT_MISSING_ON_EF")
    state = svc.answer_question(
        "audit_partner_1",
        q_def.question_id,
        "sync_lawsuit_to_schedule_ef",
        "Paralegal Test",
        "paralegal",
        "Scheduled disputed collection defendant action for automatic stay notice.",
        {"creditor_name": "Portfolio Recovery Associates", "total_claim_amount": "3100.00"},
    )
    assert any(c.creditor_name == "Portfolio Recovery Associates" and c.disputed for c in state.case_graph.claims)


def test_statutory_table_staleness_and_sync(tmp_path: Path) -> None:
    """Verifies StatutoryTableRegistry staleness detection, CLI/API table sync, and gate blocking."""
    import shutil
    from app.bankruptcy.routes import create_bankruptcy_app
    from fastapi.testclient import TestClient

    ws = tmp_path / "ws_sync"
    shutil.copytree(Path("canonical/tables/bankruptcy"), ws / "canonical" / "tables" / "bankruptcy")
    (ws / "templates").mkdir(parents=True)
    (ws / "templates" / "bankruptcy.html").write_text("<html></html>", encoding="utf-8")
    (ws / "static").mkdir(parents=True)

    reg = StatutoryTableRegistry(ws / "canonical" / "tables" / "bankruptcy")
    assert reg.check_staleness(datetime.date(2026, 11, 16)) == []
    stale_msgs = reg.check_staleness(datetime.date(2029, 1, 1))
    assert len(stale_msgs) >= 3

    sync_res = reg.sync_statutory_tables(reference_date=datetime.date(2026, 11, 16))
    assert len(sync_res["tables_verified"]) >= 5
    assert (ws / "canonical" / "tables" / "bankruptcy" / ".sync_status.json").exists()

    # Gate MUST block when expected_filing_date is past stale_after!
    gate = FilingReadinessGate(reg)
    stale_graph = CanonicalCaseGraph(
        matter_id="stale_case",
        chapter="7",
        expected_filing_date=datetime.date(2029, 1, 1),
    )
    stale_rep = gate.evaluate(BankruptcyCaseState(case_graph=stale_graph))
    assert stale_rep.status == "BLOCKED"
    assert any("expired after" in r for r in stale_rep.blocking_reasons)

    app = create_bankruptcy_app(base_dir=ws, seed_samples=False)
    client = TestClient(app)
    api_sync = client.post("/api/v1/bankruptcy/tables/sync")
    assert api_sync.status_code == 200
    assert len(api_sync.json()["tables_verified"]) >= 5
    tax_res = client.get("/api/v1/bankruptcy/tables/taxonomy")
    assert tax_res.status_code == 200
    assert len(tax_res.json()["lines"]) >= 45
