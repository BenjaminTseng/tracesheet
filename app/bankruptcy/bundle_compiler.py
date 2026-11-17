"""Compiles `BankruptcyCaseState` into a standard `CompiledBundle` (`L0 -> L1 -> L2+` DAG).

Bridges the deterministic Bankruptcy Case Workbench to `jd_screen`'s SVG cubic
Bezier traceability canvas so every dollar figure, asset, creditor claim, and
statutory conclusion in `L0` expands on click into `L1` deterministic math /
coordinate-stamped PDF evidence and `L2+` controlling statutory authorities.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional

from app.bankruptcy.models import (
    BankruptcyCaseState,
    ProvenanceField,
)
from app.core.tables import StatutoryTableRegistry
from app.models import (
    ArtifactEnvelope,
    AuditStatus,
    AuditSummary,
    CompiledBundle,
    GraphNode,
    NodeAudit,
    SectionObject,
    SourceLocator,
    TensionObject,
)


def _audit_for_field(pf: ProvenanceField[object], label: str) -> NodeAudit:
    """Maps a `ProvenanceField` verification status to `jd_screen`'s `NodeAudit`."""
    if pf.verification_status == "verified":
        return NodeAudit(
            status="verified",
            score=1.0,
            evaluator_type="deterministic",
            evaluator_note=f"{label}: verified against SHA-256 coordinate locator.",
        )
    if pf.verification_status == "human_overridden" and pf.override is not None:
        return NodeAudit(
            status="verified",
            score=1.0,
            evaluator_type="human",
            evaluator_note=(
                f"{label}: overridden by {pf.override.actor_name} ({pf.override.actor_role}): "
                f"{pf.override.rationale}"
            ),
        )
    if pf.verification_status == "contradicted":
        return NodeAudit(
            status="disputed",
            score=0.25,
            evaluator_type="deterministic",
            evaluator_note=f"{label}: flagged in cross-document contradiction.",
        )
    return NodeAudit(
        status="unverified",
        score=0.0,
        evaluator_type="deterministic",
        evaluator_note=f"{label}: unverified — requires source verification or human override.",
    )


class BankruptcyBundleCompiler:
    """Deterministically compiles `BankruptcyCaseState` into an `L0 -> L1 -> L2+` `CompiledBundle`."""

    def __init__(self, registry: Optional[StatutoryTableRegistry] = None) -> None:
        """Initializes the bundle compiler.

        Args:
            registry: Optional table registry for enriching statutory `L2+` nodes.
        """
        self.registry = registry

    def compile(self, state: BankruptcyCaseState) -> CompiledBundle:
        """Compiles `state` into a normalized `CompiledBundle` DAG.

        Args:
            state: Current `BankruptcyCaseState` with calculations, questions, and tensions.

        Returns:
            Normalized `CompiledBundle` ready for the `L0 -> L1 -> L2+` Bezier canvas.
        """
        graph = state.case_graph
        calcs = state.calculations
        nodes: Dict[str, GraphNode] = {}
        sections: List[SectionObject] = []

        def _add_authority(
            auth_id: str, title: str, quote: str, section_id: str, url: Optional[str] = None
        ) -> str:
            if auth_id not in nodes:
                nodes[auth_id] = GraphNode(
                    id=auth_id,
                    type="authority",
                    title=title,
                    section_id=section_id,
                    quote=quote,
                    url=url,
                    direct_child_ids=[],
                    parent_claim_ids=[],
                    audit=NodeAudit(
                        status="verified",
                        score=1.0,
                        evaluator_type="deterministic",
                        evaluator_note="Controlling statutory rule / effective-dated reference table.",
                    ),
                )
            return auth_id

        def _link(parent_id: str, child_id: str, root_claim_id: str) -> None:
            if child_id not in nodes[parent_id].direct_child_ids:
                nodes[parent_id].direct_child_ids.append(child_id)
            if root_claim_id not in nodes[child_id].parent_claim_ids:
                nodes[child_id].parent_claim_ids.append(root_claim_id)

        def _attach_pf_evidence(
            claim_id: str,
            section_id: str,
            prefix: str,
            title: str,
            pf: ProvenanceField[object],
            authority_ids: Optional[List[str]] = None,
        ) -> None:
            if pf.locators:
                for idx, loc in enumerate(pf.locators, start=1):
                    ev_id = f"evi_{prefix}_{idx}"
                    quote = pf.verbatim_quotes[idx - 1] if idx - 1 < len(pf.verbatim_quotes) else str(pf.value)
                    nodes[ev_id] = GraphNode(
                        id=ev_id,
                        type="evidence",
                        title=f"{title} ({loc.file_name or 'source'})",
                        section_id=section_id,
                        quote=quote,
                        locator=loc,
                        direct_child_ids=[],
                        parent_claim_ids=[claim_id],
                        audit=_audit_for_field(pf, title),
                    )
                    _link(claim_id, ev_id, claim_id)
                    for aid in authority_ids or []:
                        _link(ev_id, aid, claim_id)
            elif pf.override is not None:
                ov_id = f"ov_{prefix}"
                nodes[ov_id] = GraphNode(
                    id=ov_id,
                    type="reasoning",
                    title=f"Human Override: {pf.override.actor_name}",
                    section_id=section_id,
                    body=(
                        f"{pf.override.actor_role.title()} attestation: {pf.override.rationale} "
                        f"(Recorded {pf.override.overridden_at})."
                    ),
                    locator=pf.override.supporting_locator,
                    direct_child_ids=[],
                    parent_claim_ids=[claim_id],
                    audit=_audit_for_field(pf, title),
                )
                _link(claim_id, ov_id, claim_id)
                for aid in authority_ids or []:
                    _link(ov_id, aid, claim_id)
            else:
                gap_id = f"gap_{prefix}"
                nodes[gap_id] = GraphNode(
                    id=gap_id,
                    type="assumption",
                    title=f"Unverified Field: {title}",
                    section_id=section_id,
                    body=f"Value '{pf.value}' lacks verified source coordinates or human override.",
                    direct_child_ids=[],
                    parent_claim_ids=[claim_id],
                    audit=NodeAudit(
                        status="unverified",
                        score=0.0,
                        evaluator_type="deterministic",
                        evaluator_note="Blocked by strict zero-doubt gate until verified.",
                    ),
                )
                _link(claim_id, gap_id, claim_id)

        # -----------------------------------------------------------------
        # Section 1: Voluntary Petition & Statutory Eligibility (B 101)
        # -----------------------------------------------------------------
        sec1 = "sec_01_petition_eligibility"
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        elig = calcs.eligibility if calcs else None
        auth_elig = _add_authority(
            "aut_109e",
            "11 U.S.C. § 109(e) / H.R. 7730 Eligibility",
            (
                elig.authority_citation
                if elig
                else "11 U.S.C. § 109(e) sets Chapter 13 debt limits; § 109(b) governs Chapter 7."
            ),
            sec1,
        )

        sec1_lines: List[str] = []
        if debtor_1:
            c_name = "claim_sec01_debtor"
            nodes[c_name] = GraphNode(
                id=c_name,
                type="claim",
                title="Debtor Identity & Domicile",
                section_id=sec1,
                clause_text=f"{debtor_1.full_name.value} ({debtor_1.county_of_residence} County, {debtor_1.state})",
                direct_child_ids=[],
                audit=_audit_for_field(debtor_1.full_name, "Debtor Name"),
            )
            _attach_pf_evidence(c_name, sec1, "sec01_debtor", "Debtor Name", debtor_1.full_name, [auth_elig])
            sec1_lines.append(
                f"**Primary Debtor:** <ref id='{c_name}'>{debtor_1.full_name.value}</ref> · "
                f"County: **{debtor_1.county_of_residence}** · Filing Date: `{graph.expected_filing_date.isoformat()}` · "
                f"District: **`{graph.district}`**"
            )

        if elig:
            c_elig = "claim_sec01_elig"
            status_label = "ELIGIBLE" if elig.eligible else "INELIGIBLE"
            nodes[c_elig] = GraphNode(
                id=c_elig,
                type="claim",
                title=f"Chapter {elig.target_chapter} Debt Eligibility",
                section_id=sec1,
                clause_text=f"{status_label}: ${elig.total_combined_qualifying_debt:,.2f}",
                direct_child_ids=[],
                audit=NodeAudit(
                    status="verified" if elig.eligible else "disputed",
                    score=1.0 if elig.eligible else 0.0,
                    evaluator_type="deterministic",
                    evaluator_note=f"Table {elig.table_version_id} ({elig.table_sha256[:18]}).",
                ),
            )
            calc_elig = "calc_sec01_elig"
            limit_str = f"${elig.threshold_limit_applied:,.2f}" if elig.threshold_limit_applied else "No Cap"
            nodes[calc_elig] = GraphNode(
                id=calc_elig,
                type="calculation",
                title="Noncontingent Liquidated Debt Computation",
                section_id=sec1,
                formula=(
                    f"Qualifying = Secured (${elig.total_secured_noncontingent_liquidated:,.2f}) + "
                    f"Unsecured (${elig.total_unsecured_noncontingent_liquidated:,.2f}) = "
                    f"${elig.total_combined_qualifying_debt:,.2f} vs Limit {limit_str}"
                ),
                body=(
                    f"Excluded ${elig.excluded_contingent_or_unliquidated_debt:,.2f} contingent/unliquidated "
                    f"and ${elig.excluded_insider_affiliate_debt:,.2f} insider debt under <ref id='{auth_elig}'>{elig.authority_citation}</ref>."
                ),
                direct_child_ids=[],
                parent_claim_ids=[c_elig],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note="Pure-Python Decimal debt sum.",
                ),
            )
            _link(c_elig, calc_elig, c_elig)
            _link(calc_elig, auth_elig, c_elig)
            sec1_lines.append(
                f"**Chapter {elig.target_chapter} Eligibility:** <ref id='{c_elig}'>{status_label} — "
                f"${elig.total_combined_qualifying_debt:,.2f} qualifying debt</ref> (Limit: {limit_str})"
            )

        sections.append(
            SectionObject(
                section_id=sec1,
                section_title="1. Voluntary Petition (B 101) & Statutory Eligibility",
                order=1,
                content="\n\n".join(sec1_lines) or "No debtor profile loaded yet.",
            )
        )

        # -----------------------------------------------------------------
        # Section 2: Schedule A/B (Assets) & Schedule C (Exemption Optimizer)
        # -----------------------------------------------------------------
        sec2 = "sec_02_assets_exemptions"
        ex_opt = calcs.exemptions if calcs else None
        auth_ex = _add_authority(
            "aut_ca_exemptions",
            f"Exemption Regime: {ex_opt.recommended_display_name if ex_opt else 'CA Exemptions'}",
            (
                f"{ex_opt.domicile_rule_note} Recommended election: {ex_opt.recommended_display_name} "
                f"(Table {ex_opt.table_version_id}, {ex_opt.table_sha256[:18]})."
                if ex_opt
                else "Cal. Civ. Proc. Code §§ 704 & 703.140; 11 U.S.C. § 522(p)."
            ),
            sec2,
        )

        sec2_lines: List[str] = []
        if ex_opt:
            rec_eval = next(
                (e for e in ex_opt.evaluations if e.regime_id == ex_opt.recommended_regime_id),
                ex_opt.evaluations[0],
            )
            c_rec = "claim_sec02_opt"
            nodes[c_rec] = GraphNode(
                id=c_rec,
                type="claim",
                title="Optimal Exemption Regime Selection",
                section_id=sec2,
                clause_text=f"{ex_opt.recommended_display_name} (${rec_eval.total_non_exempt_equity:,.2f} exposed)",
                direct_child_ids=[],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note=f"Evaluated {len(ex_opt.evaluations)} eligible regimes.",
                ),
            )
            comp_str = " | ".join(
                f"{e.regime_id}: Exempt ${e.total_exempt_equity:,.2f}, Non-Exempt ${e.total_non_exempt_equity:,.2f}"
                for e in ex_opt.evaluations
            )
            calc_opt = "calc_sec02_opt"
            nodes[calc_opt] = GraphNode(
                id=calc_opt,
                type="calculation",
                title="Multi-Regime Non-Exempt Equity Comparison",
                section_id=sec2,
                formula=comp_str,
                body=(
                    f"Compared all eligible regimes under <ref id='{auth_ex}'>{ex_opt.domicile_rule_note}</ref>. "
                    f"Wildcard pool available: ${rec_eval.wildcard_pool_available:,.2f}; "
                    f"used: ${rec_eval.wildcard_pool_used:,.2f}."
                ),
                direct_child_ids=[],
                parent_claim_ids=[c_rec],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note="Deterministic greedy wildcard allocation.",
                ),
            )
            _link(c_rec, calc_opt, c_rec)
            _link(calc_opt, auth_ex, c_rec)
            sec2_lines.append(
                f"**Recommended Exemption System:** <ref id='{c_rec}'>{ex_opt.recommended_display_name} "
                f"(Non-Exempt Equity: ${rec_eval.total_non_exempt_equity:,.2f})</ref>"
            )

        if graph.assets:
            sec2_lines.append("| Asset (Schedule A/B) | Category | Market Value | Net Equity | Exempt (Schedule C) | Statute |")
            sec2_lines.append("| :--- | :--- | ---: | ---: | ---: | :--- |")
            alloc_map = {}
            if ex_opt:
                rec_eval = next(
                    (e for e in ex_opt.evaluations if e.regime_id == ex_opt.recommended_regime_id),
                    ex_opt.evaluations[0],
                )
                alloc_map = {a.asset_id: a for a in rec_eval.allocations}

            for idx, asset in enumerate(graph.assets, start=1):
                cid = f"claim_sec02_asset_{idx}"
                alloc = alloc_map.get(asset.asset_id)
                net_eq_str = f"${alloc.net_equity:,.2f}" if alloc else f"${asset.current_value.value:,.2f}"
                ex_str = f"${alloc.total_exempt:,.2f}" if alloc else "$0.00"
                statute_str = alloc.statute_cited if alloc else "Pending"

                nodes[cid] = GraphNode(
                    id=cid,
                    type="claim",
                    title=f"Asset: {asset.description}",
                    section_id=sec2,
                    clause_text=f"${asset.current_value.value:,.2f}",
                    direct_child_ids=[],
                    audit=_audit_for_field(asset.current_value, asset.description),
                )
                _attach_pf_evidence(
                    cid,
                    sec2,
                    f"sec02_asset_{idx}",
                    asset.description,
                    asset.current_value,
                    [auth_ex],
                )
                sec2_lines.append(
                    f"| {asset.description} | `{asset.category}` | "
                    f"<ref id='{cid}'>${asset.current_value.value:,.2f}</ref> | "
                    f"{net_eq_str} | {ex_str} | {statute_str} |"
                )

        sections.append(
            SectionObject(
                section_id=sec2,
                section_title="2. Schedule A/B (Property) & Schedule C (Exemption Optimizer)",
                order=2,
                content="\n".join(sec2_lines) if sec2_lines else "No assets indexed yet.",
            )
        )

        # -----------------------------------------------------------------
        # Section 3: Schedules D & E/F (Creditors) & Form B 108
        # -----------------------------------------------------------------
        sec3 = "sec_03_creditors"
        auth_claims = _add_authority(
            "aut_claims_506",
            "11 U.S.C. §§ 506, 507 & FRBP 1007(b) Schedules D/E/F",
            "Secured claims scheduled on Form B 106D up to collateral value; priority & general unsecured claims on Form B 106E/F.",
            sec3,
        )
        sec3_lines: List[str] = []
        if graph.claims:
            sec3_lines.append("| Creditor | Priority | Claim Amount | Collateral / Intention | Status |")
            sec3_lines.append("| :--- | :--- | ---: | :--- | :--- |")
            for idx, claim in enumerate(graph.claims, start=1):
                cid = f"claim_sec03_claim_{idx}"
                nodes[cid] = GraphNode(
                    id=cid,
                    type="claim",
                    title=f"Creditor: {claim.creditor_name}",
                    section_id=sec3,
                    clause_text=f"${claim.total_claim_amount.value:,.2f}",
                    direct_child_ids=[],
                    audit=_audit_for_field(claim.total_claim_amount, claim.creditor_name),
                )
                _attach_pf_evidence(
                    cid,
                    sec3,
                    f"sec03_claim_{idx}",
                    claim.creditor_name,
                    claim.total_claim_amount,
                    [auth_claims],
                )
                col_desc = claim.collateral_asset_id or "Unsecured"
                if claim.statement_of_intention:
                    col_desc = f"{col_desc} ({claim.statement_of_intention})"
                sec3_lines.append(
                    f"| {claim.creditor_name} | `{claim.priority_type}` | "
                    f"<ref id='{cid}'>${claim.total_claim_amount.value:,.2f}</ref> | "
                    f"{col_desc} | `{claim.total_claim_amount.verification_status}` |"
                )
        else:
            sec3_lines.append("No creditor claims indexed yet.")

        sections.append(
            SectionObject(
                section_id=sec3,
                section_title="3. Schedules D & E/F (Secured, Priority, & Unsecured Claims)",
                order=3,
                content="\n".join(sec3_lines),
            )
        )

        # -----------------------------------------------------------------
        # Section 4: Form 122A/C (6-Month CMI, Means Test, & Budget I/J)
        # -----------------------------------------------------------------
        sec4 = "sec_04_means_test_budget"
        mt = calcs.means_test if calcs else None
        auth_mt = _add_authority(
            "aut_707b_ustp",
            "11 U.S.C. §§ 101(10A), 707(b) & USTP Means Test Tables",
            (
                f"6-month CMI window: {mt.lookback_start} to {mt.lookback_end}. "
                f"California median ({mt.household_size} person): ${mt.california_median_income:,.2f} "
                f"(Table {mt.table_version_id}, {mt.table_sha256[:18]})."
                if mt
                else "11 U.S.C. § 707(b)(2) Means Test & IRS Standards."
            ),
            sec4,
        )
        sec4_lines: List[str] = []
        if mt:
            c_cmi = "claim_sec04_cmi"
            nodes[c_cmi] = GraphNode(
                id=c_cmi,
                type="claim",
                title="6-Month Current Monthly Income (CMI)",
                section_id=sec4,
                clause_text=f"${mt.current_monthly_income:,.2f}/mo (${mt.annualized_cmi:,.2f}/yr)",
                direct_child_ids=[],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note=f"Window {mt.lookback_start}..{mt.lookback_end}",
                ),
            )
            calc_cmi = "calc_sec04_cmi"
            stub_terms = " + ".join(
                f"${ps.gross_pay.value:,.2f} ({ps.pay_date.isoformat()})"
                for ps in graph.paystubs
                if mt.lookback_start <= ps.pay_date <= mt.lookback_end
            ) or "$0.00"
            nodes[calc_cmi] = GraphNode(
                id=calc_cmi,
                type="calculation",
                title="CMI 6-Month Average Formula",
                section_id=sec4,
                formula=f"CMI = ({stub_terms}) / 6 = ${mt.current_monthly_income:,.2f}",
                body=(
                    f"Annualized CMI ${mt.annualized_cmi:,.2f} vs CA Median ${mt.california_median_income:,.2f} "
                    f"({'Above Median' if mt.is_above_median else 'Below Median'}) under "
                    f"<ref id='{auth_mt}'>11 U.S.C. § 101(10A) & USTP Standards</ref>."
                ),
                direct_child_ids=[],
                parent_claim_ids=[c_cmi],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note="Exact 6-month lookback arithmetic.",
                ),
            )
            _link(c_cmi, calc_cmi, c_cmi)
            _link(calc_cmi, auth_mt, c_cmi)
            for idx, ps in enumerate(graph.paystubs, start=1):
                if mt.lookback_start <= ps.pay_date <= mt.lookback_end:
                    _attach_pf_evidence(
                        c_cmi,
                        sec4,
                        f"sec04_ps_{idx}",
                        f"Paystub {ps.employer} ({ps.pay_date})",
                        ps.gross_pay,
                        [auth_mt],
                    )

            c_disp = "claim_sec04_disposable"
            nodes[c_disp] = GraphNode(
                id=c_disp,
                type="claim",
                title="Means Test Monthly Disposable Income",
                section_id=sec4,
                clause_text=f"${mt.monthly_disposable_income:,.2f}/mo",
                direct_child_ids=[],
                audit=NodeAudit(
                    status="verified" if not mt.presumption_of_abuse else "disputed",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note=f"IRS + Tax + Secured Cure Deductions = ${mt.total_allowed_deductions:,.2f}/mo",
                ),
            )
            calc_disp = "calc_sec04_disposable"
            nodes[calc_disp] = GraphNode(
                id=calc_disp,
                type="calculation",
                title="Form 122A-2 / 122C-2 IRS Deduction Breakdown",
                section_id=sec4,
                formula=(
                    f"CMI ${mt.current_monthly_income:,.2f} - (Food/Cloth ${mt.irs_food_clothing_allowance:,.2f} + "
                    f"Health ${mt.irs_healthcare_allowance:,.2f} + Housing ${mt.irs_housing_utilities_allowance:,.2f} + "
                    f"Transport ${mt.irs_transportation_allowance:,.2f} + Taxes ${mt.payroll_taxes_deduction:,.2f} + "
                    f"Secured ${mt.secured_debt_cure_monthly:,.2f}) = ${mt.monthly_disposable_income:,.2f}/mo"
                ),
                body=f"60-Month Disposable Pool: ${mt.sixty_month_disposable_income:,.2f} under <ref id='{auth_mt}'>11 U.S.C. § 707(b)</ref>.",
                direct_child_ids=[],
                parent_claim_ids=[c_disp],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note="Deterministic IRS Means Test calculation.",
                ),
            )
            _link(c_disp, calc_disp, c_disp)
            _link(calc_disp, auth_mt, c_disp)

            sec4_lines.append(
                f"**6-Month CMI:** <ref id='{c_cmi}'>${mt.current_monthly_income:,.2f}/mo "
                f"(${mt.annualized_cmi:,.2f}/yr)</ref> · CA Median: **${mt.california_median_income:,.2f}** "
                f"({'ABOVE MEDIAN' if mt.is_above_median else 'BELOW MEDIAN'})"
            )
            sec4_lines.append(
                f"**Means Test Disposable Income:** <ref id='{c_disp}'>${mt.monthly_disposable_income:,.2f}/mo</ref> "
                f"· IRS + Secured Deductions: **${mt.total_allowed_deductions:,.2f}/mo**"
            )
            if calcs and calcs.ch13_plan:
                plan = calcs.ch13_plan
                sec4_lines.append(
                    f"**Chapter 13 Plan ({plan.applicable_commitment_months} mos):** "
                    f"Liquidation Floor `${plan.best_interests_liquidation_floor:,.2f}` · "
                    f"Priority `${plan.priority_claims_total:,.2f}` · Arrears `${plan.secured_arrears_total:,.2f}` · "
                    f"Est. Payment **`${plan.estimated_monthly_plan_payment:,.2f}/mo`**"
                )

        sections.append(
            SectionObject(
                section_id=sec4,
                section_title="4. Form 122A/C (6-Month CMI, Means Test, & Chapter 13 Plan)",
                order=4,
                content="\n\n".join(sec4_lines) or "No paystub income indexed yet.",
            )
        )

        # Build AuditSummary across all claim nodes.
        claim_nodes = [n for n in nodes.values() if n.type == "claim"]
        verified_claims = sum(1 for n in claim_nodes if n.audit.status == "verified")
        all_tensions: List[TensionObject] = [
            t
            for t in (state.tensions + state.plausibility_warnings)
            if t.tension_id not in state.resolved_tension_records
        ]

        return CompiledBundle(
            bundle_id=f"bk_{graph.matter_id}",
            matter_id=graph.matter_id,
            question=f"Bankruptcy Case Graph Compilation — Chapter {graph.chapter} ({graph.district})",
            artifact=ArtifactEnvelope(
                title=f"Chapter {graph.chapter} Petition Audit Canvas — {graph.matter_id}",
                created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                metadata={
                    "application": "bankruptcy_workbench",
                    "chapter": graph.chapter,
                    "district": graph.district,
                    "expected_filing_date": graph.expected_filing_date.isoformat(),
                },
                summary=(
                    f"Audit-grounded Toulmin DAG covering {len(graph.assets)} asset(s), "
                    f"{len(graph.claims)} claim(s), and {len(graph.paystubs)} paystub(s)."
                ),
                sections=sections,
            ),
            audit_summary=AuditSummary(
                total_claims=len(claim_nodes),
                verified_count=verified_claims,
                extrapolation_count=sum(1 for n in claim_nodes if n.audit.status == "extrapolation"),
                assumption_count=sum(1 for n in claim_nodes if n.audit.status in ("assumption", "unverified")),
                cross_section_tensions=all_tensions,
            ),
            nodes=nodes,
        )
