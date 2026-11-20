# Run: uv run pytest tests/test_bk_calculators.py -v
"""Deep deterministic tests for Eligibility, 6-Month CMI/Means Test, ExemptionOptimizer, and Ch. 13 Plan."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

from app.compilers.bankruptcy.calculators import (
    CMIAndMeansTestEngine,
    EligibilityEngine,
    ExemptionOptimizer,
    compute_case_calculations,
)
from app.compilers.bankruptcy.schema import (
    AssetItem,
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
    """Helper wrapping a test value in an audited `ProvenanceField`."""
    return ProvenanceField[type(val)](
        value=val,
        verification_status="human_overridden",
        override=HumanOverrideRecord(
            actor_name="Test Paralegal",
            actor_role="paralegal",
            rationale="Synthetic test fixture verified.",
        ),
    )


def _base_party(
    county: str = "Los Angeles",
    household: int = 1,
    domicile_days: int = 1500,
    prior_state: str | None = None,
    joint: bool = False,
) -> list[PartyEntity]:
    parties = [
        PartyEntity(
            party_id="debtor_1",
            role="debtor_1",
            full_name=_ov("Jordan Test"),
            county_of_residence=county,
            prior_state_180_days=prior_state,
            ca_domicile_days_continuous=_ov(domicile_days),
            household_size=_ov(household),
        )
    ]
    if joint:
        parties.append(
            PartyEntity(
                party_id="debtor_2",
                role="debtor_2_spouse",
                full_name=_ov("Taylor Test"),
                county_of_residence=county,
                prior_state_180_days=prior_state,
                ca_domicile_days_continuous=_ov(domicile_days),
                household_size=_ov(household),
            )
        )
    return parties


def test_eligibility_ch13_hr7730_and_subchapter_v_exclusions() -> None:
    """Tests unified $2.75M Ch. 13 limit and $7.5M SubV limit with contingent/insider exclusions."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    engine = EligibilityEngine(reg)

    # Case 1: $2.6M noncontingent liquidated debt + $500k contingent litigation claim -> qualifies under H.R. 7730!
    ch13_graph = CanonicalCaseGraph(
        matter_id="elig_1",
        chapter="13",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(),
        claims=[
            ClaimItem(
                claim_id="c1",
                creditor_name="First Mortgage",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("2100000.00")),
            ),
            ClaimItem(
                claim_id="c2",
                creditor_name="SBA Business Guaranty",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("500000.00")),
                commercial_business_pct=1.0,
            ),
            ClaimItem(
                claim_id="c3",
                creditor_name="Pending Tort Suit",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("500000.00")),
                contingent=True,
                unliquidated=True,
            ),
        ],
    )
    res_post = engine.evaluate(ch13_graph, target_chapter="13")
    assert res_post.eligible is True
    assert res_post.total_combined_qualifying_debt == Decimal("2600000.00")
    assert res_post.excluded_contingent_or_unliquidated_debt == Decimal("500000.00")

    # Under pre-H.R. 7730 date (Nov 9, 2026), $2.1M secured fails the $1,580,125 cap!
    pre_graph = ch13_graph.model_copy(update={"expected_filing_date": datetime.date(2026, 11, 9)})
    res_pre = engine.evaluate(pre_graph, target_chapter="13")
    assert res_pre.eligible is False

    # Case 2: Subchapter V with $7.2M commercial debt + $1.0M insider founder loan -> qualifies!
    subv_graph = CanonicalCaseGraph(
        matter_id="elig_2",
        chapter="11_subv",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(),
        claims=[
            ClaimItem(
                claim_id="s1",
                creditor_name="Equipment Lender",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("7200000.00")),
                commercial_business_pct=1.0,
            ),
            ClaimItem(
                claim_id="s2",
                creditor_name="Founder Note",
                priority_type="general_unsecured",
                total_claim_amount=_ov(Decimal("1000000.00")),
                is_insider_or_affiliate=True,
                commercial_business_pct=1.0,
            ),
        ],
    )
    res_subv = engine.evaluate(subv_graph, target_chapter="11_subv")
    assert res_subv.eligible is True
    assert res_subv.total_combined_qualifying_debt == Decimal("7200000.00")
    assert res_subv.excluded_insider_affiliate_debt == Decimal("1000000.00")


def test_cmi_6_month_lookback_and_surrender_flips_means_test() -> None:
    """Verifies exact 6-month lookback boundary and secured-surrender deduction impact."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    engine = CMIAndMeansTestEngine(reg)

    # Filing date 2026-11-16 -> strictly May 1..Oct 31, 2026.
    # Include an April 28 bonus and Nov 5 paycheck that MUST be excluded.
    paystubs = []
    for month in range(5, 11):
        paystubs.append(
            PaystubRecord(
                paystub_id=f"ps_{month}",
                employer="Tech Corp",
                pay_period_start=datetime.date(2026, month, 1),
                pay_period_end=datetime.date(2026, month, 28),
                pay_date=datetime.date(2026, month, 28),
                gross_pay=_ov(Decimal("8000.00")),
                net_pay=_ov(Decimal("5200.00")),
                tax_withheld=_ov(Decimal("2350.00")),
            )
        )
    paystubs.append(
        PaystubRecord(
            paystub_id="ps_excluded_apr",
            employer="Tech Corp",
            pay_period_start=datetime.date(2026, 4, 15),
            pay_period_end=datetime.date(2026, 4, 28),
            pay_date=datetime.date(2026, 4, 28),
            gross_pay=_ov(Decimal("25000.00")),
            net_pay=_ov(Decimal("18000.00")),
            tax_withheld=_ov(Decimal("5000.00")),
        )
    )
    paystubs.append(
        PaystubRecord(
            paystub_id="ps_excluded_nov",
            employer="Tech Corp",
            pay_period_start=datetime.date(2026, 11, 1),
            pay_period_end=datetime.date(2026, 11, 5),
            pay_date=datetime.date(2026, 11, 5),
            gross_pay=_ov(Decimal("10000.00")),
            net_pay=_ov(Decimal("7000.00")),
            tax_withheld=_ov(Decimal("2000.00")),
        )
    )

    graph = CanonicalCaseGraph(
        matter_id="cmi_1",
        chapter="7",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Fresno", household=1),
        assets=[
            AssetItem(
                asset_id="veh_1",
                category="vehicle",
                description="2024 BMW X5",
                current_value=_ov(Decimal("48000.00")),
            )
        ],
        claims=[
            ClaimItem(
                claim_id="loan_1",
                creditor_name="BMW Financial",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("144000.00")),
                monthly_payment=_ov(Decimal("2400.00")),
                collateral_asset_id="veh_1",
                statement_of_intention="retain_and_reaffirm",
            )
        ],
        paystubs=paystubs,
    )

    res_keep = engine.evaluate(graph)
    assert res_keep.lookback_start == datetime.date(2026, 5, 1)
    assert res_keep.lookback_end == datetime.date(2026, 10, 31)
    assert res_keep.total_6_month_gross_income == Decimal("48000.00")
    assert res_keep.current_monthly_income == Decimal("8000.00")
    assert res_keep.annualized_cmi == Decimal("96000.00")
    assert res_keep.is_above_median is True
    assert res_keep.presumption_of_abuse is False  # $1,600 car + IRS allowances absorb disposable income

    # Now switch vehicle intention to surrender -> loses $1,600 secured debt cure & vehicle ownership/operating!
    surrender_claim = graph.claims[0].model_copy(update={"statement_of_intention": "surrender"})
    graph_surrender = graph.model_copy(update={"claims": [surrender_claim]})
    res_surrender = engine.evaluate(graph_surrender)
    assert res_surrender.secured_debt_cure_monthly == Decimal("0.00")
    assert res_surrender.monthly_disposable_income > res_keep.monthly_disposable_income
    assert res_surrender.presumption_of_abuse is True


def test_universal_exemption_optimizer_704_vs_703_522p_and_federal() -> None:
    """Tests CA § 704 homestead win, CA § 703.140 wildcard win, § 522(p) cap, and § 522(d) routing."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    opt = ExemptionOptimizer(reg)

    # Case A: Orange County homeowner ($900k home, $420k mortgage -> $480k equity) -> § 704 wins!
    home_graph = CanonicalCaseGraph(
        matter_id="ex_home",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Orange", domicile_days=2000),
        assets=[
            AssetItem(
                asset_id="home_1",
                category="real_property",
                description="120 Ocean View, Irvine",
                current_value=_ov(Decimal("900000.00")),
                acquisition_date=_ov(datetime.date(2019, 1, 1)),  # > 1215 days
            ),
            AssetItem(
                asset_id="bank_1",
                category="bank_account",
                description="BofA Checking",
                current_value=_ov(Decimal("2000.00")),
            ),
        ],
        claims=[
            ClaimItem(
                claim_id="mtg_1",
                creditor_name="Wells Fargo Home Mortgage",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("420000.00")),
                collateral_asset_id="home_1",
            )
        ],
    )
    res_a = opt.optimize(home_graph)
    assert res_a.recommended_regime_id == "CA_CCP_704"
    ev_704 = next(e for e in res_a.evaluations if e.regime_id == "CA_CCP_704")
    assert ev_704.total_non_exempt_equity == Decimal("0.00")

    # Case B: Same home acquired only 600 days ago -> 11 U.S.C. § 522(p) clamps homestead to $214,000!
    recent_home = home_graph.assets[0].model_copy(
        update={"acquisition_date": _ov(datetime.date(2025, 3, 25))}
    )
    res_522p = opt.optimize(home_graph.model_copy(update={"assets": [recent_home, home_graph.assets[1]]}))
    ev_522p = next(e for e in res_522p.evaluations if e.regime_id == "CA_CCP_704")
    home_alloc = next(a for a in ev_522p.allocations if a.asset_id == "home_1")
    assert home_alloc.category_exempt_applied == Decimal("214000.00")
    assert home_alloc.non_exempt_equity == Decimal("266000.00")
    assert "522(p)" in (home_alloc.cap_notes or "")

    # Case C: Renter with $4k mobile home, $14k car equity, $22k cash, $8k stock -> § 703.140 wildcard wins!
    renter_graph = CanonicalCaseGraph(
        matter_id="ex_renter",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Los Angeles", domicile_days=1500),
        assets=[
            AssetItem(
                asset_id="mh_1",
                category="real_property",
                description="Mobile home equity",
                current_value=_ov(Decimal("4000.00")),
                acquisition_date=_ov(datetime.date(2020, 1, 1)),
            ),
            AssetItem(
                asset_id="car_1",
                category="vehicle",
                description="2021 Civic",
                current_value=_ov(Decimal("14000.00")),
            ),
            AssetItem(
                asset_id="cash_1",
                category="bank_account",
                description="Chase Checking",
                current_value=_ov(Decimal("22000.00")),
            ),
            AssetItem(
                asset_id="brok_1",
                category="other",
                description="Fidelity Brokerage",
                current_value=_ov(Decimal("8000.00")),
            ),
        ],
    )
    res_c = opt.optimize(renter_graph)
    assert res_c.recommended_regime_id == "CA_CCP_703_140"
    ev_703 = next(e for e in res_c.evaluations if e.regime_id == "CA_CCP_703_140")
    # $36,750 - $4,000 = $32,750 unused residence + $1,950 base = $34,700 wildcard.
    # Remaining exposed before wildcard = ($14,000-$8,625) + $22,000 + $8,000 = $35,375 -> $675 exposed.
    assert ev_703.wildcard_pool_available == Decimal("34700.00")
    assert ev_703.total_non_exempt_equity == Decimal("675.00")

    # Case D: Joint filer < 730 days in CA from non-opt-out state -> routes to FEDERAL_522D with joint doubling!
    mover_graph = renter_graph.model_copy(
        update={
            "parties": _base_party(
                county="Los Angeles", domicile_days=300, prior_state="TX", joint=True
            )
        }
    )
    res_d = opt.optimize(mover_graph)
    assert res_d.domicile_state_applied == "FEDERAL"
    assert res_d.recommended_regime_id == "FEDERAL_522D"


def test_ch13_plan_calculator_liquidation_floor_and_full_summary() -> None:
    """Verifies Ch. 13 plan calculation enforces Best Interests liquidation floor."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    graph = CanonicalCaseGraph(
        matter_id="ch13_1",
        chapter="13",
        district="CAEB",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Sacramento", domicile_days=2000),
        assets=[
            AssetItem(
                asset_id="home_1",
                category="real_property",
                description="Sacramento Home",
                current_value=_ov(Decimal("540000.00")),
                acquisition_date=_ov(datetime.date(2018, 1, 1)),
            ),
            AssetItem(
                asset_id="car_1",
                category="vehicle",
                description="2020 Subaru",
                current_value=_ov(Decimal("18625.00")),  # $10,000 non-exempt under § 704
            ),
        ],
        claims=[
            ClaimItem(
                claim_id="mtg_1",
                creditor_name="Caliber Home Loans",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("210000.00")),
                arrears_amount=_ov(Decimal("18000.00")),
                monthly_payment=_ov(Decimal("1800.00")),
                collateral_asset_id="home_1",
            ),
            ClaimItem(
                claim_id="irs_1",
                creditor_name="IRS Priority",
                priority_type="priority_tax",
                total_claim_amount=_ov(Decimal("6000.00")),
            ),
        ],
        budget=MonthlyBudgetScheduleIJ(
            income_items=[
                BudgetLineItem(
                    item_id="i1",
                    category="gross_wages",
                    description="Wages",
                    monthly_amount=_ov(Decimal("5000.00")),
                )
            ],
            expense_items=[
                BudgetLineItem(
                    item_id="e1",
                    category="rent_or_mortgage",
                    description="Mortgage",
                    monthly_amount=_ov(Decimal("1800.00")),
                )
            ],
        ),
    )
    summary = compute_case_calculations(graph, reg)
    assert summary.ch13_plan is not None
    # Non-exempt car equity = $10,000; priority = $6,000; mortgage arrears = $18,000 -> $34,000 over 36 mos.
    assert summary.ch13_plan.best_interests_liquidation_floor == Decimal("10000.00")
    assert summary.ch13_plan.total_minimum_plan_funding == Decimal("34000.00")
    assert summary.ch13_plan.applicable_commitment_months == 36
    assert summary.ch13_plan.estimated_monthly_plan_payment == Decimal("944.44")


def test_unknown_valuation_schwab_v_reilly_704_vs_703() -> None:
    """Verifies Unknown valuations, 53-line mapping, Schwab 100% FMV flag, and CCP § 704 unlimited PI win."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    opt = ExemptionOptimizer(reg)

    graph = CanonicalCaseGraph(
        matter_id="ex_schwab_pi",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Los Angeles", domicile_days=1800),
        assets=[
            AssetItem(
                asset_id="pi_claim_1",
                category="personal_injury",
                description="Pending Auto Accident Bodily Injury Lawsuit",
                valuation_state="unknown",
                current_value=_ov(Decimal("0.00")),
            ),
            AssetItem(
                asset_id="wc_claim_1",
                category="workers_comp",
                description="Open Workers Comp Award Claim",
                valuation_state="unknown",
                current_value=_ov(Decimal("0.00")),
            ),
            AssetItem(
                asset_id="wages_1",
                category="unpaid_wages",
                description="Earned Unpaid Commission",
                current_value=_ov(Decimal("2000.00")),
            ),
        ],
    )
    assert graph.assets[0].schedule_ab_line == "33"
    assert graph.assets[0].claim_100pct_fmv_exemption is True
    assert "21." in (graph.assets[0].best_case_alias or "")

    res = opt.optimize(graph)
    ev_704 = next(e for e in res.evaluations if e.regime_id == "CA_CCP_704")
    ev_703 = next(e for e in res.evaluations if e.regime_id == "CA_CCP_703_140")

    # Under CCP § 703.140(b)(11)(D), PI is dollar-capped ($36,750) -> unbounded unknown exposure!
    assert ev_703.has_unbounded_unknown_exposure is True
    pi_703 = next(a for a in ev_703.allocations if a.asset_id == "pi_claim_1")
    assert pi_703.unknown_value_exposed_risk is True
    assert pi_703.claim_100pct_fmv is True

    # Under CCP § 704.140 & § 704.160, both PI & Workers' Comp are unlimited_with_conditions -> no unbounded cap risk!
    assert ev_704.has_unbounded_unknown_exposure is False
    pi_704 = next(a for a in ev_704.allocations if a.asset_id == "pi_claim_1")
    assert pi_704.unknown_value_exposed_risk is False
    assert pi_704.claim_100pct_fmv is True
    wages_704 = next(a for a in ev_704.allocations if a.asset_id == "wages_1")
    assert wages_704.category_exempt_applied == Decimal("1500.00")  # 75% under CCP § 704.070

    # When numeric non-exempt equity ties ($0.00), CA_CCP_704 wins over CA_CCP_703_140 because PI is unlimited.
    pi_only_graph = graph.model_copy(update={"assets": graph.assets[:2]})
    res_unknown = opt.optimize(pi_only_graph)
    assert res_unknown.recommended_regime_id == "CA_CCP_704"


def test_federal_caps_522p_rollover_522n_ira_and_541b_529_lookback() -> None:
    """Verifies § 522(p)(2)(B) same-state rollover, § 522(n) IRA cap, and § 541(b)(5)-(6) 529 lookbacks."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    opt = ExemptionOptimizer(reg)

    graph = CanonicalCaseGraph(
        matter_id="fed_caps_1",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Orange", domicile_days=2000),
        assets=[
            AssetItem(
                asset_id="home_roll",
                category="real_property",
                description="Irvine Condo Bought With Prior CA Home Proceeds",
                current_value=_ov(Decimal("500000.00")),
                acquisition_date=_ov(datetime.date(2025, 4, 1)),  # < 1215 days
                prior_state_residence_rollover_amount=Decimal("120000.00"),
            ),
            AssetItem(
                asset_id="ira_big",
                category="ira_non_rollover",
                description="Non-Rollover Traditional IRA",
                current_value=_ov(Decimal("1800000.00")),
            ),
            AssetItem(
                asset_id="acct_529",
                category="education_529",
                description="ScholarShare 529 College Savings",
                current_value=_ov(Decimal("20000.00")),
                contributions_within_365_days=Decimal("3000.00"),  # 0% excluded
                contributions_365_to_720_days=Decimal("10000.00"),  # $7,575 max excluded
            ),
        ],
    )
    res = opt.optimize(graph)
    ev_704 = next(e for e in res.evaluations if e.regime_id == "CA_CCP_704")
    assert ev_704.homestead_acquired_within_1215_days is True
    assert ev_704.homestead_exceeds_522p_cap is True

    home_al = next(a for a in ev_704.allocations if a.asset_id == "home_roll")
    assert home_al.category_exempt_applied == Decimal("334000.00")  # $214,000 + $120,000 rollover
    assert home_al.non_exempt_equity == Decimal("166000.00")

    ira_al = next(a for a in ev_704.allocations if a.asset_id == "ira_big")
    assert ira_al.category_exempt_applied == Decimal("1711975.00")  # § 522(n) aggregate cap
    assert ira_al.non_exempt_equity == Decimal("88025.00")

    ed_al = next(a for a in ev_704.allocations if a.asset_id == "acct_529")
    # $7,000 (>720d) + $7,575 (capped 365-720d) = $14,575 excluded; $5,425 remains in estate.
    assert ed_al.excluded_from_estate_amount == Decimal("14575.00")
    assert ed_al.net_equity == Decimal("5425.00")


def test_married_filing_separately_marital_adjustment_deduction() -> None:
    """Verifies Column B non-filing spouse CMI and Form 122A-2 Line 3 Marital Adjustment deduction."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    engine = CMIAndMeansTestEngine(reg)

    paystubs = []
    for month in range(5, 11):
        paystubs.append(
            PaystubRecord(
                paystub_id=f"d1_{month}",
                party_id="debtor_1",
                employer="Debtor Co",
                pay_period_start=datetime.date(2026, month, 1),
                pay_period_end=datetime.date(2026, month, 28),
                pay_date=datetime.date(2026, month, 28),
                gross_pay=_ov(Decimal("4500.00")),
                net_pay=_ov(Decimal("3400.00")),
                tax_withheld=_ov(Decimal("900.00")),
            )
        )
        paystubs.append(
            PaystubRecord(
                paystub_id=f"sp_{month}",
                party_id="non_filing_spouse",
                employer="Spouse Co",
                pay_period_start=datetime.date(2026, month, 1),
                pay_period_end=datetime.date(2026, month, 28),
                pay_date=datetime.date(2026, month, 28),
                gross_pay=_ov(Decimal("4000.00")),
                net_pay=_ov(Decimal("3000.00")),
                tax_withheld=_ov(Decimal("800.00")),
            )
        )

    parties = _base_party(county="Los Angeles", household=2) + [
        PartyEntity(
            party_id="non_filing_spouse",
            role="non_filing_spouse",
            full_name=_ov("Riley Test"),
            county_of_residence="Los Angeles",
            ca_domicile_days_continuous=_ov(1500),
            household_size=_ov(2),
        )
    ]

    graph_together = CanonicalCaseGraph(
        matter_id="mfs_together",
        chapter="7",
        expected_filing_date=datetime.date(2026, 11, 16),
        marital_status="married_filing_separately_together",
        parties=parties,
        paystubs=paystubs,
        marital_adjustment_deductions=[
            BudgetLineItem(
                item_id="ma_car",
                category="vehicle_payment",
                description="Spouse Separate Car Note & Personal Expenses",
                monthly_amount=_ov(Decimal("1800.00")),
            )
        ],
    )
    mt_together = engine.evaluate(graph_together)
    assert mt_together.debtor_1_cmi == Decimal("4500.00")
    assert mt_together.spouse_cmi == Decimal("4000.00")
    assert mt_together.current_monthly_income == Decimal("8500.00")
    assert mt_together.marital_adjustment_deduction == Decimal("1800.00")
    assert mt_together.adjusted_cmi == Decimal("6700.00")
    assert mt_together.annualized_cmi == Decimal("80400.00")

    graph_apart = graph_together.model_copy(update={"marital_status": "married_filing_separately_apart"})
    mt_apart = engine.evaluate(graph_apart)
    assert mt_apart.spouse_cmi == Decimal("0.00")
    assert mt_apart.adjusted_cmi == Decimal("4500.00")


def test_ch13_910_day_vehicle_cramdown_and_junior_lien_strip_and_feasibility() -> None:
    """Verifies Ch. 13 910-day cramdown, Zimmer/Lam 2nd mortgage strip, trustee fee, and feasibility gate."""
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    graph = CanonicalCaseGraph(
        matter_id="ch13_cram_1",
        chapter="13",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
        parties=_base_party(county="Los Angeles", domicile_days=2000),
        ch13_trustee_fee_pct=Decimal("0.08"),
        ch13_attorney_fee_in_plan=Decimal("4000.00"),
        assets=[
            AssetItem(
                asset_id="home_underwater",
                category="real_property",
                description="Underwater Residence",
                current_value=_ov(Decimal("400000.00")),
                acquisition_date=_ov(datetime.date(2019, 1, 1)),
            ),
            AssetItem(
                asset_id="car_old",
                category="vehicle",
                description="2019 Ford Escape",
                current_value=_ov(Decimal("13000.00")),
            ),
        ],
        claims=[
            ClaimItem(
                claim_id="mtg_1st",
                creditor_name="First Mortgage",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("420000.00")),
                arrears_amount=_ov(Decimal("0.00")),
                collateral_asset_id="home_underwater",
                lien_rank=1,
            ),
            ClaimItem(
                claim_id="mtg_2nd",
                creditor_name="Wholly Unsecured 2nd HELOC",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("65000.00")),
                arrears_amount=_ov(Decimal("12000.00")),
                collateral_asset_id="home_underwater",
                lien_rank=2,
            ),
            ClaimItem(
                claim_id="auto_old",
                creditor_name="Santander Auto Loan",
                priority_type="secured",
                total_claim_amount=_ov(Decimal("22000.00")),
                collateral_asset_id="car_old",
                origination_date=datetime.date(2022, 1, 10),  # > 910 days before 2026-11-16
            ),
        ],
        budget=MonthlyBudgetScheduleIJ(
            income_items=[
                BudgetLineItem(
                    item_id="i1",
                    category="gross_wages",
                    description="Wages",
                    monthly_amount=_ov(Decimal("3000.00")),
                )
            ],
            expense_items=[
                BudgetLineItem(
                    item_id="e1",
                    category="rent_or_mortgage",
                    description="First Mortgage",
                    monthly_amount=_ov(Decimal("2800.00")),
                )
            ],
        ),
    )
    summary = compute_case_calculations(graph, reg)
    plan = summary.ch13_plan
    assert plan is not None
    assert plan.junior_liens_stripped_total == Decimal("65000.00")
    assert plan.cramdown_savings_total == Decimal("9000.00")
    # Secured cure = $13,000 car cramdown + $0 stripped 2nd + $0 1st arrears; Atty fee = $4,000 -> base $17,000 * 1.08 = $18,360
    assert plan.secured_arrears_total == Decimal("13000.00")
    assert plan.attorney_fee_in_plan == Decimal("4000.00")
    assert plan.trustee_fee_total == Decimal("1360.00")
    assert plan.total_minimum_plan_funding == Decimal("18360.00")
    assert plan.estimated_monthly_plan_payment == Decimal("510.00")
    # Schedule I-J net = $200/mo < $510/mo -> infeasible with $310/mo shortfall!
    assert plan.plan_is_feasible is False
    assert plan.feasibility_shortfall_monthly == Decimal("310.00")
