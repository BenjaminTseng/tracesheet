"""Deterministic Chapter 13 Plan math calculator."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.bankruptcy.models import (
    CanonicalCaseGraph,
    Chapter13PlanResult,
    ExemptionOptimizationResult,
    MeansTestResult,
)


class Chapter13PlanCalculator:
    """Computes minimum Chapter 13 plan funding and monthly payments."""

    def calculate(
        self,
        graph: CanonicalCaseGraph,
        means_test: MeansTestResult,
        exemptions: ExemptionOptimizationResult,
        schedule_ij_monthly_net: Decimal,
    ) -> Chapter13PlanResult:
        """Computes Chapter 13 commitment period, liquidation floor, and monthly payment.

        Args:
            graph: Populated `CanonicalCaseGraph`.
            means_test: Pre-computed `MeansTestResult` (`122C`).
            exemptions: Pre-computed `ExemptionOptimizationResult`.
            schedule_ij_monthly_net: Projected monthly net income from Schedule I - J.

        Returns:
            Deterministic `Chapter13PlanResult`.
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

        priority_total = sum(
            (
                c.total_claim_amount.value
                for c in graph.claims
                if c.priority_type in ("priority_tax", "priority_dso", "priority_wages")
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        secured_arrears = sum(
            (
                c.arrears_amount.value
                for c in graph.claims
                if c.priority_type == "secured"
                and c.arrears_amount is not None
                and c.statement_of_intention != "surrender"
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Best Interests of Creditors test (11 U.S.C. § 1325(a)(4)) vs Disposable Income (§ 1325(b)).
        unsecured_floor = max(disposable_pool, liquidation_floor)
        total_funding = (unsecured_floor + priority_total + secured_arrears).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        monthly_payment = (total_funding / Decimal(months)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

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
        )
