"""Chapter-dispatched calculator pipeline registry (Ch. 7, Ch. 13, extensible to Ch. 11 SubV)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Dict

from app.compilers.bankruptcy.calculators.ch13_plan import Chapter13PlanCalculator
from app.compilers.bankruptcy.calculators.eligibility import EligibilityEngine
from app.compilers.bankruptcy.calculators.exemptions import ExemptionOptimizer
from app.compilers.bankruptcy.calculators.means_test import CMIAndMeansTestEngine
from app.compilers.bankruptcy.schema import (
    CalculationSummary,
    CanonicalCaseGraph,
    ChapterType,
)
from app.core.tables import StatutoryTableRegistry


ChapterPipelineFn = Callable[[CanonicalCaseGraph, StatutoryTableRegistry], CalculationSummary]


def _compute_common(
    graph: CanonicalCaseGraph,
    registry: StatutoryTableRegistry,
    include_ch13_plan: bool = False,
) -> CalculationSummary:
    """Computes Eligibility, Means Test, Exemptions, Schedule I/J totals, and optional Ch. 13 plan."""
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

    ch13_plan = (
        Chapter13PlanCalculator().calculate(
            graph=graph,
            means_test=means_test,
            exemptions=exemptions,
            schedule_ij_monthly_net=sched_ij_net,
        )
        if include_ch13_plan
        else None
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


class ChapterCalculatorDispatch:
    """Dispatches statutory calculator pipelines by target bankruptcy chapter (`7`, `13`, `11_subv`)."""

    def __init__(self) -> None:
        self._pipelines: Dict[ChapterType, ChapterPipelineFn] = {
            "7": lambda g, r: _compute_common(g, r, include_ch13_plan=False),
            "13": lambda g, r: _compute_common(g, r, include_ch13_plan=True),
            "11_subv": lambda g, r: _compute_common(g, r, include_ch13_plan=False),
        }

    def register(self, chapter: ChapterType, fn: ChapterPipelineFn) -> None:
        """Registers or overrides a chapter-specific statutory calculation pipeline."""
        self._pipelines[chapter] = fn

    def compute(
        self, graph: CanonicalCaseGraph, registry: StatutoryTableRegistry
    ) -> CalculationSummary:
        """Executes the deterministic calculator pipeline registered for `graph.chapter`."""
        handler = self._pipelines.get(graph.chapter)
        if handler is None:
            raise ValueError(f"Unsupported bankruptcy chapter for calculation: {graph.chapter}")
        return handler(graph, registry)


DEFAULT_CHAPTER_DISPATCH = ChapterCalculatorDispatch()
