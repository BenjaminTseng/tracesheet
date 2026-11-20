"""Pure-Python deterministic statutory calculators for Bankruptcy v1.

Provides `Decimal`-exact calculations driven strictly by effective-dated JSON
reference tables (`StatutoryTableRegistry`), dispatched per chapter via
`ChapterCalculatorDispatch`.
"""

from __future__ import annotations

from app.compilers.bankruptcy.calculators.ch13_plan import Chapter13PlanCalculator
from app.compilers.bankruptcy.calculators.eligibility import EligibilityEngine
from app.compilers.bankruptcy.calculators.exemptions import ExemptionOptimizer
from app.compilers.bankruptcy.calculators.means_test import CMIAndMeansTestEngine
from app.compilers.bankruptcy.calculators.registry import (
    ChapterCalculatorDispatch,
    DEFAULT_CHAPTER_DISPATCH,
)
from app.compilers.bankruptcy.schema import CalculationSummary, CanonicalCaseGraph
from app.core.tables import StatutoryTableRegistry


def compute_case_calculations(
    graph: CanonicalCaseGraph, registry: StatutoryTableRegistry
) -> CalculationSummary:
    """Runs all statutory calculators deterministically via `DEFAULT_CHAPTER_DISPATCH`."""
    return DEFAULT_CHAPTER_DISPATCH.compute(graph, registry)


__all__ = [
    "EligibilityEngine",
    "CMIAndMeansTestEngine",
    "ExemptionOptimizer",
    "Chapter13PlanCalculator",
    "ChapterCalculatorDispatch",
    "DEFAULT_CHAPTER_DISPATCH",
    "compute_case_calculations",
]
