"""Pure-Python deterministic statutory calculators for Bankruptcy v1.

Provides `Decimal`-exact calculations driven strictly by effective-dated JSON
reference tables (`StatutoryTableRegistry`), never LLM arithmetic.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.bankruptcy.calculators.ch13_plan import Chapter13PlanCalculator
from app.bankruptcy.calculators.eligibility import EligibilityEngine
from app.bankruptcy.calculators.exemptions import ExemptionOptimizer
from app.bankruptcy.calculators.means_test import CMIAndMeansTestEngine
from app.bankruptcy.models import CalculationSummary, CanonicalCaseGraph
from app.core.tables import StatutoryTableRegistry


def compute_case_calculations(
    graph: CanonicalCaseGraph, registry: StatutoryTableRegistry
) -> CalculationSummary:
    """Runs all statutory calculators deterministically against `graph`.

    Args:
        graph: Populated `CanonicalCaseGraph` for the matter.
        registry: Effective-dated `StatutoryTableRegistry`.

    Returns:
        Aggregated `CalculationSummary` containing Eligibility, Means Test,
        Universal Exemption Optimization, Chapter 13 Plan math (if Ch. 13),
        and schedule totals.
    """
    eligibility = EligibilityEngine(registry).evaluate(graph)
    means_test = CMIAndMeansTestEngine(registry).evaluate(graph)
    exemptions = ExemptionOptimizer(registry).optimize(graph)

    sched_i = sum(
        (item.monthly_amount.value for item in graph.budget.income_items),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sched_j = sum(
        (item.monthly_amount.value for item in graph.budget.expense_items),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sched_ij_net = (sched_i - sched_j).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    ch13_plan = None
    if graph.chapter == "13":
        ch13_plan = Chapter13PlanCalculator().calculate(
            graph=graph,
            means_test=means_test,
            exemptions=exemptions,
            schedule_ij_monthly_net=sched_ij_net,
        )

    total_assets = sum(
        (a.current_value.value for a in graph.assets), Decimal("0.00")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_secured = sum(
        (c.total_claim_amount.value for c in graph.claims if c.priority_type == "secured"),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_priority = sum(
        (
            c.total_claim_amount.value
            for c in graph.claims
            if c.priority_type in ("priority_tax", "priority_dso", "priority_wages")
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_unsecured = sum(
        (
            c.total_claim_amount.value
            for c in graph.claims
            if c.priority_type == "general_unsecured"
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return CalculationSummary(
        eligibility=eligibility,
        means_test=means_test,
        exemptions=exemptions,
        ch13_plan=ch13_plan,
        schedule_i_monthly_gross=sched_i,
        schedule_j_monthly_expenses=sched_j,
        schedule_ij_monthly_net=sched_ij_net,
        total_assets=total_assets,
        total_secured_debt=total_secured,
        total_priority_debt=total_priority,
        total_general_unsecured_debt=total_unsecured,
    )


__all__ = [
    "EligibilityEngine",
    "CMIAndMeansTestEngine",
    "ExemptionOptimizer",
    "Chapter13PlanCalculator",
    "compute_case_calculations",
]
