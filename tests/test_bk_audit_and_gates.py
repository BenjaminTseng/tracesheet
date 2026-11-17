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
    HumanOverrideRecord,
    MonthlyBudgetScheduleIJ,
    PartyEntity,
    PaystubRecord,
    ProvenanceField,
)
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
