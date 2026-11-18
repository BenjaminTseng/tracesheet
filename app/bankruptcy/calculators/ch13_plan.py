"""Deterministic Chapter 13 Plan math calculator with cramdown, lien strip, and feasibility."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict

from app.bankruptcy.models import (
    AssetItem,
    CanonicalCaseGraph,
    Chapter13PlanResult,
    ExemptionOptimizationResult,
    MeansTestResult,
)


class Chapter13PlanCalculator:
    """Computes minimum Chapter 13 plan funding, cramdowns, lien strips, and feasibility."""

    def calculate(
        self,
        graph: CanonicalCaseGraph,
        means_test: MeansTestResult,
        exemptions: ExemptionOptimizationResult,
        schedule_ij_monthly_net: Decimal,
    ) -> Chapter13PlanResult:
        """Computes Chapter 13 commitment period, liquidation floor, cramdown, and monthly payment.

        Args:
            graph: Populated `CanonicalCaseGraph`.
            means_test: Pre-computed `MeansTestResult` (`122C`).
            exemptions: Pre-computed `ExemptionOptimizationResult`.
            schedule_ij_monthly_net: Projected monthly net income from Schedule I - J.

        Returns:
            Deterministic `Chapter13PlanResult` including feasibility verdict.
        """
        months = means_test.applicable_commitment_months
        disposable_pool = (
            max(Decimal("0.00"), means_test.monthly_disposable_income) * Decimal(months)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        best_eval = next(
            (
                e
                for e in exemptions.evaluations
                if e.regime_id == exemptions.recommended_regime_id
            ),
            exemptions.evaluations[0],
        )
        liquidation_floor = best_eval.total_non_exempt_equity.quantize(Decimal("0.01"))

        priority_total = Decimal("0.00")
        secured_arrears = Decimal("0.00")
        cramdown_savings_total = Decimal("0.00")
        junior_liens_stripped_total = Decimal("0.00")
        asset_map: Dict[str, AssetItem] = {a.asset_id: a for a in graph.assets}

        for claim in graph.claims:
            if claim.priority_type in ("priority_tax", "priority_dso", "priority_wages"):
                priority_total += claim.total_claim_amount.value
            elif claim.priority_type == "secured":
                if claim.statement_of_intention == "surrender":
                    continue
                collat = asset_map.get(claim.collateral_asset_id or "")

                # Wholly unsecured junior mortgage lien strip (In re Zimmer / Lam).
                if collat is not None and collat.category == "real_property" and claim.lien_rank >= 2:
                    senior_total = sum(
                        (
                            sc.total_claim_amount.value
                            for sc in graph.claims
                            if sc.priority_type == "secured"
                            and sc.collateral_asset_id == collat.asset_id
                            and sc.lien_rank < claim.lien_rank
                        ),
                        Decimal("0.00"),
                    )
                    if senior_total >= collat.current_value.value:
                        junior_liens_stripped_total += claim.total_claim_amount.value
                        continue

                # 910-day PMSI vehicle cramdown (11 U.S.C. § 1325(a) hanging paragraph).
                if (
                    collat is not None
                    and collat.category == "vehicle"
                    and claim.origination_date is not None
                ):
                    days_since_loan = (graph.expected_filing_date - claim.origination_date).days
                    if days_since_loan > 910 and claim.total_claim_amount.value > collat.current_value.value:
                        secured_arrears += collat.current_value.value
                        cramdown_savings_total += (
                            claim.total_claim_amount.value - collat.current_value.value
                        )
                        continue

                if claim.arrears_amount is not None:
                    secured_arrears += claim.arrears_amount.value

        priority_total = priority_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        secured_arrears = secured_arrears.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cramdown_savings_total = cramdown_savings_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        junior_liens_stripped_total = junior_liens_stripped_total.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Best Interests of Creditors test (11 U.S.C. § 1325(a)(4)) vs Disposable Income (§ 1325(b)).
        unsecured_floor = max(disposable_pool, liquidation_floor)
        attorney_fee_in_plan = graph.ch13_attorney_fee_in_plan.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        base_funding = (
            unsecured_floor + priority_total + secured_arrears + attorney_fee_in_plan
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if graph.ch13_trustee_fee_pct > Decimal("0.00"):
            trustee_fee_total = (base_funding * graph.ch13_trustee_fee_pct).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            total_funding = (base_funding + trustee_fee_total).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            trustee_fee_total = Decimal("0.00")
            total_funding = base_funding

        monthly_payment = (total_funding / Decimal(months)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        gross_8pct_monthly = ((base_funding * Decimal("1.08")) / Decimal(months)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        has_budget = bool(graph.budget.income_items or graph.budget.expense_items)
        if has_budget and schedule_ij_monthly_net < monthly_payment:
            plan_is_feasible = False
            feasibility_shortfall = (monthly_payment - schedule_ij_monthly_net).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            plan_is_feasible = True
            feasibility_shortfall = Decimal("0.00")

        return Chapter13PlanResult(
            applicable_commitment_months=months,
            monthly_disposable_income_122c=means_test.monthly_disposable_income,
            schedule_ij_monthly_net=schedule_ij_monthly_net,
            unsecured_pool_via_disposable_income=disposable_pool,
            best_interests_liquidation_floor=liquidation_floor,
            priority_claims_total=priority_total,
            secured_arrears_total=secured_arrears,
            total_minimum_plan_funding=total_funding,
            estimated_monthly_plan_payment=monthly_payment,
            cramdown_savings_total=cramdown_savings_total,
            junior_liens_stripped_total=junior_liens_stripped_total,
            trustee_fee_total=trustee_fee_total,
            attorney_fee_in_plan=attorney_fee_in_plan,
            gross_monthly_payment_with_8pct_trustee_fee=gross_8pct_monthly,
            plan_is_feasible=plan_is_feasible,
            feasibility_shortfall_monthly=feasibility_shortfall,
        )
