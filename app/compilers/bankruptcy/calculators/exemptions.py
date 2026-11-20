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

from app.compilers.bankruptcy.schema import (
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
        ira_cap_522n_amt: Decimal = Decimal("1711975.00"),
        ed_529_cfg: Optional[Dict[str, Any]] = None,
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

        # Index rules by asset category/pool and prepare per-category remaining cap pools.
        rules_by_cat: Dict[str, Dict[str, Any]] = {
            r["category"]: r for r in regime_spec.get("rules", [])
        }
        remaining_pool_by_cat: Dict[str, Optional[Decimal]] = {}
        statute_by_cat: Dict[str, str] = {}

        for cat, rule in rules_by_cat.items():
            statute_by_cat[cat] = rule["statute"]
            rtype = rule["rule_type"]
            if rtype in ("unlimited_with_conditions", "percentage_of_value"):
                remaining_pool_by_cat[cat] = None  # Unlimited or value-relative %
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

        # Pass 1: Apply primary category-specific exemptions (enforcing §§ 522(p), 522(o), 522(n), 541(b)(6)).
        allocations: List[ExemptionAllocation] = []
        cap_522p = Decimal(homestead_522p_cfg["cap_amount"]) * multiplier
        lookback_522p_days = int(homestead_522p_cfg["lookback_days"])
        ed_529_cap_mid = Decimal(str((ed_529_cfg or {}).get("cap_365_to_720_days", "7575.00")))
        ira_522n_remaining = ira_cap_522n_amt
        homestead_exceeds_522p_cap = False
        homestead_acquired_within_1215_days = False
        has_unbounded_unknown_exposure = False

        for asset in graph.assets:
            cur_val = asset.current_value.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            liens = liens_by_asset.get(asset.asset_id, Decimal("0.00")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            cat = asset.category
            excluded_from_estate = Decimal("0.00")
            cap_notes_parts: List[str] = []

            if cat == "education_529":
                within_365 = max(Decimal("0.00"), asset.contributions_within_365_days)
                mid_window = max(Decimal("0.00"), asset.contributions_365_to_720_days)
                older_than_720 = max(Decimal("0.00"), cur_val - within_365 - mid_window)
                excluded_mid = min(mid_window, ed_529_cap_mid)
                excluded_from_estate = (older_than_720 + excluded_mid).quantize(Decimal("0.01"))
                estate_val = max(Decimal("0.00"), cur_val - excluded_from_estate)
                net_eq = max(Decimal("0.00"), estate_val - liens).quantize(Decimal("0.01"))
                if excluded_from_estate > Decimal("0.00"):
                    cap_notes_parts.append(
                        f"${excluded_from_estate:,.2f} excluded from estate under 11 U.S.C. § 541(b)(5)-(6) "
                        f"(${within_365:,.2f} within 365d non-excluded)."
                    )
            else:
                net_eq = max(Decimal("0.00"), cur_val - liens).quantize(Decimal("0.01"))

            # Route via orthogonal exemption_pool first, falling back to granular category.
            pool_key = asset.category if asset.category in rules_by_cat else (asset.exemption_pool or asset.category)
            rule = rules_by_cat.get(pool_key)
            is_unknown = asset.valuation_state == "unknown"
            claim_100pct = is_unknown or asset.claim_100pct_fmv_exemption
            unknown_risk = False

            if rule is None:
                cat_exempt = Decimal("0.00")
                statute = "No specific category exemption (candidate for Wildcard)"
                if is_unknown:
                    unknown_risk = True
                    has_unbounded_unknown_exposure = True
                    cap_notes_parts.append(
                        "Schwab v. Reilly 100% FMV checked; unliquidated claim exceeds fixed/wildcard ceiling if any."
                    )
            else:
                statute = rule["statute"]
                rtype = rule["rule_type"]
                pool = remaining_pool_by_cat[pool_key]
                if rtype == "unlimited_with_conditions":
                    cat_exempt = net_eq
                    unknown_risk = False
                    if is_unknown:
                        cap_notes_parts.append(
                            "100% of FMV exempt under statutory cause-of-action/support protection."
                        )
                elif rtype == "percentage_of_value":
                    pct = Decimal(str(rule.get("percentage", "0.75")))
                    cat_exempt = (net_eq * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if is_unknown:
                        unknown_risk = True
                        has_unbounded_unknown_exposure = True
                else:
                    assert pool is not None
                    effective_pool = pool
                    if cat == "ira_non_rollover":
                        effective_pool = min(effective_pool, ira_522n_remaining)
                    if cat == "real_property" and asset.fraudulent_addition_522o_amount > Decimal("0.00"):
                        effective_pool = max(
                            Decimal("0.00"),
                            effective_pool - asset.fraudulent_addition_522o_amount,
                        )
                        cap_notes_parts.append(
                            f"Homestead reduced by ${asset.fraudulent_addition_522o_amount:,.2f} under 11 U.S.C. § 522(o)."
                        )
                    if cat == "real_property" and asset.acquisition_date is not None:
                        held_days = (graph.expected_filing_date - asset.acquisition_date.value).days
                        if held_days < lookback_522p_days:
                            homestead_acquired_within_1215_days = True
                            if bool(rule.get("subject_to_522p_1215_day_cap", False)):
                                effective_522p_cap = (
                                    cap_522p + asset.prior_state_residence_rollover_amount
                                ).quantize(Decimal("0.01"))
                                if effective_pool > effective_522p_cap:
                                    effective_pool = effective_522p_cap
                                    if asset.prior_state_residence_rollover_amount > Decimal("0.00"):
                                        cap_notes_parts.append(
                                            f"Capped at ${effective_522p_cap:,.2f} (${cap_522p:,.2f} 522(p) + "
                                            f"${asset.prior_state_residence_rollover_amount:,.2f} § 522(p)(2)(B) same-state rollover; "
                                            f"held {held_days}d < {lookback_522p_days}d)."
                                        )
                                    else:
                                        cap_notes_parts.append(
                                            f"Capped at ${cap_522p:,.2f} under 11 U.S.C. § 522(p) "
                                            f"(property held {held_days} days < {lookback_522p_days} days)."
                                        )

                    cat_exempt = min(net_eq, effective_pool).quantize(Decimal("0.01"))
                    if cat == "real_property" and cat_exempt > cap_522p:
                        homestead_exceeds_522p_cap = True
                    if cat == "ira_non_rollover":
                        ira_522n_remaining = max(Decimal("0.00"), ira_522n_remaining - cat_exempt)
                        if net_eq > cat_exempt:
                            cap_notes_parts.append(
                                f"Capped at ${ira_cap_522n_amt:,.2f} aggregate under 11 U.S.C. § 522(n)."
                            )
                    if is_unknown:
                        unknown_risk = True
                        has_unbounded_unknown_exposure = True
                        cap_notes_parts.append(
                            f"Unknown FMV with dollar cap (${effective_pool:,.2f}) creates trustee excess risk above cap."
                        )
                    remaining_pool_by_cat[pool_key] = max(Decimal("0.00"), pool - cat_exempt)

            allocations.append(
                ExemptionAllocation(
                    asset_id=asset.asset_id,
                    asset_description=asset.description,
                    category=cat,
                    schedule_ab_line=asset.schedule_ab_line,
                    current_value=cur_val,
                    valuation_state=asset.valuation_state,
                    claim_100pct_fmv=claim_100pct,
                    unknown_value_exposed_risk=unknown_risk,
                    excluded_from_estate_amount=excluded_from_estate,
                    linked_liens=liens,
                    net_equity=net_eq,
                    statute_cited=statute,
                    category_exempt_applied=cat_exempt,
                    wildcard_exempt_applied=Decimal("0.00"),
                    total_exempt=cat_exempt,
                    non_exempt_equity=(net_eq - cat_exempt).quantize(Decimal("0.01")),
                    cap_notes=" ".join(cap_notes_parts) if cap_notes_parts else None,
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
            homestead_exceeds_522p_cap=homestead_exceeds_522p_cap,
            homestead_acquired_within_1215_days=homestead_acquired_within_1215_days,
            has_unbounded_unknown_exposure=has_unbounded_unknown_exposure,
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
        ira_522n = Decimal(str(fed_cfg.get("ira_cap_522n", {}).get("cap_amount", "1711975.00")))
        ed_529_cfg = fed_cfg.get("education_529_exclusion_541b")

        domicile_state, regime_ids, domicile_note = self._resolve_domicile_policy(
            graph, exemptions_cfg
        )
        regimes_map = exemptions_cfg["regimes"]
        evaluations = [
            self._evaluate_regime(
                graph,
                regimes_map[rid],
                homestead_522p,
                ira_cap_522n_amt=ira_522n,
                ed_529_cfg=ed_529_cfg,
            )
            for rid in regime_ids
            if rid in regimes_map
        ]

        # Honor explicit counsel regime override if valid; otherwise pick minimum exposure,
        # avoiding unbounded unknown-value exposure on ties.
        explicit = (
            next((ev for ev in evaluations if ev.regime_id == graph.selected_exemption_regime), None)
            if graph.selected_exemption_regime
            else None
        )
        best = explicit or min(
            evaluations,
            key=lambda ev: (
                ev.total_non_exempt_equity,
                1 if ev.has_unbounded_unknown_exposure else 0,
                -ev.total_exempt_equity,
            ),
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
