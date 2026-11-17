"""Universal multi-jurisdiction ExemptionOptimizer driven by `exemptions_2026.json`.

Evaluates all selectable state or federal exemption regimes (`CA_CCP_704`,
`CA_CCP_703_140`, `FEDERAL_522D`, etc.), enforces 730-day domicile routing
(`11 U.S.C. § 522(b)(3)(A)`) and the 1,215-day homestead cap (`§ 522(p)`),
greedily allocates wildcard spillover across otherwise unprotected assets, and
selects the regime minimizing total non-exempt equity.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from app.bankruptcy.models import (
    AssetItem,
    CanonicalCaseGraph,
    ExemptionAllocation,
    ExemptionOptimizationResult,
    ExemptionRegimeEvaluation,
)
from app.core.tables import StatutoryTableRegistry


class ExemptionOptimizer:
    """Evaluates all eligible exemption regimes and optimizes Schedule C allocations."""

    def __init__(self, registry: StatutoryTableRegistry) -> None:
        """Initializes the universal exemption optimizer.

        Args:
            registry: Effective-dated `StatutoryTableRegistry`.
        """
        self.registry = registry

    def _resolve_domicile_policy(
        self, graph: CanonicalCaseGraph, exemptions_cfg: Dict[str, Any]
    ) -> Tuple[str, List[str], str]:
        """Determines controlling state policy and selectable regimes per 11 U.S.C. § 522(b)(3)(A)."""
        policies = exemptions_cfg["state_policies"]
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        state = debtor_1.state if debtor_1 else "CA"
        days = debtor_1.ca_domicile_days_continuous.value if debtor_1 else 730
        prior_state = debtor_1.prior_state_180_days if debtor_1 else None

        policy = policies.get(state, policies["DEFAULT_DUAL_ELECTION"])
        req_days = int(policy.get("required_domicile_days", 730))

        if days >= req_days:
            return (
                state,
                list(policy["selectable_regimes"]),
                f"Debtor domiciled in {state} for {days} days (>= {req_days} days required under 11 U.S.C. § 522(b)(3)(A)).",
            )

        # Under 730 days: fall back to prior 180-day domicile state if configured,
        # otherwise use federal § 522(d) savings clause.
        if prior_state and prior_state in policies:
            prior_policy = policies[prior_state]
            return (
                prior_state,
                list(prior_policy["selectable_regimes"]),
                f"Domiciled < {req_days} days ({days}d); 180-day lookback routes to prior domicile '{prior_state}'.",
            )

        fallback_policy = policies["DEFAULT_DUAL_ELECTION"]
        return (
            "FEDERAL",
            list(fallback_policy["selectable_regimes"]),
            f"Domiciled < {req_days} days ({days}d) with prior non-opt-out/unknown state; § 522(b)(3) savings clause enables Federal § 522(d).",
        )

    def _evaluate_regime(
        self,
        graph: CanonicalCaseGraph,
        regime_spec: Dict[str, Any],
        homestead_522p_cfg: Dict[str, Any],
    ) -> ExemptionRegimeEvaluation:
        """Evaluates all assets under a single `ExemptionRegimeSpec`."""
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        has_joint_debtor = any(p.role == "debtor_2_spouse" for p in graph.parties)
        county = debtor_1.county_of_residence if debtor_1 else "Los Angeles"

        multiplier = (
            Decimal("2")
            if (has_joint_debtor and bool(regime_spec.get("allow_joint_doubling", False)))
            else Decimal("1")
        )

        # Index rules by asset category and prepare per-category remaining cap pools.
        rules_by_cat: Dict[str, Dict[str, Any]] = {
            r["category"]: r for r in regime_spec.get("rules", [])
        }
        remaining_pool_by_cat: Dict[str, Optional[Decimal]] = {}
        statute_by_cat: Dict[str, str] = {}

        for cat, rule in rules_by_cat.items():
            statute_by_cat[cat] = rule["statute"]
            rtype = rule["rule_type"]
            if rtype == "unlimited_with_conditions":
                remaining_pool_by_cat[cat] = None  # Unlimited
            elif rtype == "locality_lookup":
                county_map = rule.get("county_amounts", {})
                raw_amt = Decimal(county_map.get(county, county_map.get("DEFAULT_CA_COUNTY", rule["floor"])))
                remaining_pool_by_cat[cat] = (raw_amt * multiplier).quantize(Decimal("0.01"))
            else:
                remaining_pool_by_cat[cat] = (Decimal(rule["cap"]) * multiplier).quantize(
                    Decimal("0.01")
                )

        # Pre-compute linked secured liens per asset.
        liens_by_asset: Dict[str, Decimal] = {}
        for claim in graph.claims:
            if claim.priority_type == "secured" and claim.collateral_asset_id:
                liens_by_asset[claim.collateral_asset_id] = (
                    liens_by_asset.get(claim.collateral_asset_id, Decimal("0.00"))
                    + claim.total_claim_amount.value
                )

        # Pass 1: Apply primary category-specific exemptions (enforcing § 522(p) 1,215-day cap).
        allocations: List[ExemptionAllocation] = []
        cap_522p = Decimal(homestead_522p_cfg["cap_amount"]) * multiplier
        lookback_522p_days = int(homestead_522p_cfg["lookback_days"])

        for asset in graph.assets:
            cur_val = asset.current_value.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            liens = liens_by_asset.get(asset.asset_id, Decimal("0.00")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            net_eq = max(Decimal("0.00"), cur_val - liens).quantize(Decimal("0.01"))
            cat = asset.category
            rule = rules_by_cat.get(cat)
            cap_notes: Optional[str] = None

            if rule is None:
                cat_exempt = Decimal("0.00")
                statute = "No specific category exemption (candidate for Wildcard)"
            else:
                statute = rule["statute"]
                pool = remaining_pool_by_cat[cat]
                if pool is None:
                    cat_exempt = net_eq
                else:
                    effective_pool = pool
                    if (
                        bool(rule.get("subject_to_522p_1215_day_cap", False))
                        and asset.acquisition_date is not None
                    ):
                        held_days = (graph.expected_filing_date - asset.acquisition_date.value).days
                        if held_days < lookback_522p_days and effective_pool > cap_522p:
                            effective_pool = cap_522p
                            cap_notes = (
                                f"Capped at ${cap_522p:,.2f} under 11 U.S.C. § 522(p) "
                                f"(property held {held_days} days < {lookback_522p_days} days)."
                            )
                    cat_exempt = min(net_eq, effective_pool).quantize(Decimal("0.01"))
                    # Deduct applied amount from category pool (tracking against original pool).
                    remaining_pool_by_cat[cat] = max(Decimal("0.00"), pool - cat_exempt)

            allocations.append(
                ExemptionAllocation(
                    asset_id=asset.asset_id,
                    asset_description=asset.description,
                    category=cat,
                    current_value=cur_val,
                    linked_liens=liens,
                    net_equity=net_eq,
                    statute_cited=statute,
                    category_exempt_applied=cat_exempt,
                    wildcard_exempt_applied=Decimal("0.00"),
                    total_exempt=cat_exempt,
                    non_exempt_equity=(net_eq - cat_exempt).quantize(Decimal("0.01")),
                    cap_notes=cap_notes,
                )
            )

        # Pass 2: Compute wildcard spillover pool and allocate greedily to exposed equity.
        wildcard_cfg = regime_spec.get("wildcard")
        wildcard_avail = Decimal("0.00")
        wildcard_used = Decimal("0.00")

        if wildcard_cfg:
            base_wc = Decimal(wildcard_cfg["base_amount"]) * multiplier
            src_cat = wildcard_cfg["spillover_source_category"]
            unused_src = remaining_pool_by_cat.get(src_cat) or Decimal("0.00")
            max_spill = Decimal(wildcard_cfg["max_spillover_amount"]) * multiplier
            ratio = Decimal(wildcard_cfg["spillover_ratio"])
            spillover = min(max_spill, (unused_src * ratio).quantize(Decimal("0.01")))
            wildcard_avail = (base_wc + spillover).quantize(Decimal("0.01"))

            wc_remaining = wildcard_avail
            # Allocate to assets with remaining non-exempt equity (largest exposure first).
            indexed_exposed = sorted(
                range(len(allocations)),
                key=lambda i: allocations[i].non_exempt_equity,
                reverse=True,
            )
            for idx in indexed_exposed:
                if wc_remaining <= Decimal("0.00"):
                    break
                alloc = allocations[idx]
                if alloc.non_exempt_equity <= Decimal("0.00"):
                    continue
                take = min(alloc.non_exempt_equity, wc_remaining).quantize(Decimal("0.01"))
                if take > Decimal("0.00"):
                    wc_remaining -= take
                    wildcard_used += take
                    new_total = (alloc.total_exempt + take).quantize(Decimal("0.01"))
                    new_exposed = (alloc.net_equity - new_total).quantize(Decimal("0.01"))
                    wc_statute = wildcard_cfg["statute"]
                    cited = (
                        wc_statute
                        if alloc.category_exempt_applied == Decimal("0.00")
                        else f"{alloc.statute_cited} + {wc_statute}"
                    )
                    allocations[idx] = alloc.model_copy(
                        update={
                            "wildcard_exempt_applied": take,
                            "total_exempt": new_total,
                            "non_exempt_equity": new_exposed,
                            "statute_cited": cited,
                        }
                    )

        total_net = sum((a.net_equity for a in allocations), Decimal("0.00")).quantize(
            Decimal("0.01")
        )
        total_ex = sum((a.total_exempt for a in allocations), Decimal("0.00")).quantize(
            Decimal("0.01")
        )
        total_non_ex = sum(
            (a.non_exempt_equity for a in allocations), Decimal("0.00")
        ).quantize(Decimal("0.01"))

        return ExemptionRegimeEvaluation(
            regime_id=regime_spec["regime_id"],
            display_name=regime_spec["display_name"],
            total_net_equity=total_net,
            total_exempt_equity=total_ex,
            total_non_exempt_equity=total_non_ex,
            wildcard_pool_available=wildcard_avail,
            wildcard_pool_used=wildcard_used.quantize(Decimal("0.01")),
            allocations=allocations,
        )

    def optimize(self, graph: CanonicalCaseGraph) -> ExemptionOptimizationResult:
        """Evaluates all eligible regimes and recommends the minimum-exposure election.

        Args:
            graph: Case graph with parties, assets, and secured claims.

        Returns:
            `ExemptionOptimizationResult` comparing all eligible regimes.
        """
        exemptions_cfg = self.registry.get_exemption_regimes(graph.expected_filing_date)
        fed_cfg = self.registry.get_federal_thresholds(graph.expected_filing_date)
        homestead_522p = fed_cfg["homestead_1215_day_cap_522p"]

        domicile_state, regime_ids, domicile_note = self._resolve_domicile_policy(
            graph, exemptions_cfg
        )
        regimes_map = exemptions_cfg["regimes"]
        evaluations = [
            self._evaluate_regime(graph, regimes_map[rid], homestead_522p)
            for rid in regime_ids
            if rid in regimes_map
        ]

        # Select regime leaving minimal non-exempt equity; tie-break by total exempt.
        best = min(
            evaluations,
            key=lambda ev: (ev.total_non_exempt_equity, -ev.total_exempt_equity),
        )
        return ExemptionOptimizationResult(
            domicile_state_applied=domicile_state,
            domicile_rule_note=domicile_note,
            recommended_regime_id=best.regime_id,
            recommended_display_name=best.display_name,
            evaluations=evaluations,
            table_version_id=exemptions_cfg["version_id"],
            table_sha256=exemptions_cfg["_table_sha256"],
        )
