"""Compiles `BankruptcyCaseState` into a standard `CompiledBundle` (`L0 -> L1 -> L2+` DAG).

Bridges the deterministic Bankruptcy Case Workbench to `jd_screen`'s SVG cubic
Bezier traceability canvas so every official schedule line item (`Form 101`,
`Form 106Sum`, `Schedule A/B`, `Schedule C`, `Schedule D`, `Schedule E/F`,
`Schedules I/J`, `Form 122A/C`, `Form 107`, and District Ch. 13 Plans) in `L0`
mirrors the exact court PDF form layout and expands on click into `L1` math /
coordinate-stamped client PDF evidence and `L2+` controlling statutes/local rules.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from app.bankruptcy.models import (
    BankruptcyCaseState,
    ProvenanceField,
)
from app.bankruptcy.pdf_engine import FormPacketPlanner
from app.core.tables import StatutoryTableRegistry
from app.models import (
    ArtifactEnvelope,
    AuditSummary,
    CompiledBundle,
    GraphNode,
    NodeAudit,
    SectionObject,
    TensionObject,
)

ASSET_CATEGORY_LINE_MAP: Dict[str, tuple[str, str]] = {
    "real_estate": ("106A/B Pt. 1 · 1.1", "Real Estate"),
    "vehicle": ("106A/B Pt. 2 · 3.1", "Vehicle"),
    "bank_account": ("106A/B Pt. 4 · 17", "Financial Account"),
    "retirement": ("106A/B Pt. 4 · 21", "Retirement Plan"),
    "other": ("106A/B Pt. 3/7", "Personal Property"),
}

CLAIM_PRIORITY_LINE_MAP: Dict[str, tuple[str, str]] = {
    "secured": ("106D Pt. 1", "Secured"),
    "priority_dso": ("106E/F Pt. 1 · 6a", "Priority (DSO)"),
    "priority_tax": ("106E/F Pt. 1 · 6b", "Priority (Tax)"),
    "general_unsecured": ("106E/F Pt. 2 · 6f", "General Unsecured"),
}

VERIFICATION_LABELS: Dict[str, str] = {
    "verified": "Verified",
    "human_overridden": "Counsel Override",
    "contradicted": "Contradicted",
    "unverified": "Needs Proof",
}

INTENTION_LABELS: Dict[str, str] = {
    "retain_and_reaffirm": "Form 108: Retain & Reaffirm",
    "retain_and_redeem": "Form 108: Retain & Redeem",
    "surrender": "Form 108: Surrender",
}


def _audit_for_field(pf: ProvenanceField[object], label: str) -> NodeAudit:
    """Maps a `ProvenanceField` verification status to `jd_screen`'s `NodeAudit`.

    Args:
        pf: Provenance-wrapped field value.
        label: Human-readable field label for audit notes.

    Returns:
        Normalized `NodeAudit` status record.
    """
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
    """Deterministically compiles `BankruptcyCaseState` into an official-form-aligned `CompiledBundle`."""

    def __init__(self, registry: Optional[StatutoryTableRegistry] = None) -> None:
        """Initializes the bundle compiler.

        Args:
            registry: Optional table registry for enriching statutory `L2+` nodes.
        """
        self.registry = registry
        self.planner = FormPacketPlanner()

    def compile(self, state: BankruptcyCaseState) -> CompiledBundle:
        """Compiles `state` into a normalized `CompiledBundle` DAG aligned to Official Bankruptcy Forms.

        Args:
            state: Current `BankruptcyCaseState` with calculations, questions, and tensions.

        Returns:
            Normalized `CompiledBundle` ready for the `L0 -> L1 -> L2+` Bezier canvas.
        """
        graph = state.case_graph
        calcs = state.calculations
        nodes: Dict[str, GraphNode] = {}
        sections: List[SectionObject] = []
        planned_forms = self.planner.plan_required_forms(state)

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
                    title=f"Counsel Override: {pf.override.actor_name}",
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
        # Section 1: Form B 101 Voluntary Petition & Statutory Eligibility
        # -----------------------------------------------------------------
        sec1 = "sec_01_petition_b101"
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        elig = calcs.eligibility if calcs else None
        auth_elig = _add_authority(
            "aut_109e",
            "11 U.S.C. § 109(e) / § 109(b) & Form B 101 Instructions",
            (
                elig.authority_citation
                if elig
                else "11 U.S.C. § 109(e) sets Chapter 13 debt limits; § 109(b) governs Chapter 7."
            ),
            sec1,
        )

        sec1_rows: List[str] = [
            "| Form B 101 Line | Petition Field | Scheduled Entry | Verification |",
            "| :--- | :--- | :--- | :--- |",
        ]
        if debtor_1:
            c_name = "claim_sec01_debtor"
            nodes[c_name] = GraphNode(
                id=c_name,
                type="claim",
                title="Form B 101 Part 1, Line 1 — Debtor Name & Domicile",
                section_id=sec1,
                clause_text=f"{debtor_1.full_name.value} ({debtor_1.county_of_residence} County, {debtor_1.state})",
                direct_child_ids=[],
                audit=_audit_for_field(debtor_1.full_name, "Debtor Name"),
            )
            _attach_pf_evidence(c_name, sec1, "sec01_debtor", "Form B 101 Line 1 · Debtor Name", debtor_1.full_name, [auth_elig])
            dist_label = "Central District of CA (CACB)" if graph.district == "CACB" else "Eastern District of CA (CAEB)"
            sec1_rows.append(
                f"| B 101 Pt. 1 · 1 | Debtor 1 Legal Name | <ref id='{c_name}'>{debtor_1.full_name.value}</ref> | {VERIFICATION_LABELS.get(debtor_1.full_name.verification_status, 'Verified')} |"
            )
            sec1_rows.append(
                f"| B 101 Pt. 1 · 5 | Residence & Venue | {debtor_1.street_address}, {debtor_1.city}, {debtor_1.state} {debtor_1.zip_code} ({debtor_1.county_of_residence} County) | {dist_label} |"
            )
            sec1_rows.append(
                f"| B 101 · Caption | Chapter & Target Filing Date | Chapter {graph.chapter} · `{graph.expected_filing_date.isoformat()}` | Form B 121 SSN Isolated |"
            )

        if elig:
            c_elig = "claim_sec01_elig"
            status_label = "Eligible" if elig.eligible else "Over Cap (Ineligible)"
            nodes[c_elig] = GraphNode(
                id=c_elig,
                type="claim",
                title=f"Chapter {elig.target_chapter} Debt Limit Eligibility (§ 109)",
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
            limit_str = f"${elig.threshold_limit_applied:,.2f}" if elig.threshold_limit_applied else "No Statutory Cap"
            nodes[calc_elig] = GraphNode(
                id=calc_elig,
                type="calculation",
                title="Noncontingent Liquidated Debt Computation (11 U.S.C. § 109)",
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
            sec1_rows.append(
                f"| B 101 Pt. 6 · 19–20 | Chapter {elig.target_chapter} Debt Eligibility | <ref id='{c_elig}'>{status_label} (${elig.total_combined_qualifying_debt:,.2f} qualifying)</ref> | Limit: {limit_str} |"
            )

        sections.append(
            SectionObject(
                section_id=sec1,
                section_title="Form B 101 — Voluntary Petition & Chapter Eligibility",
                order=1,
                content="\n".join(sec1_rows),
            )
        )

        # -----------------------------------------------------------------
        # Section 2: Form B 106Sum — Official Summary of Assets & Liabilities
        # -----------------------------------------------------------------
        sec2 = "sec_02_summary_b106sum"
        auth_sum = _add_authority(
            "aut_frbp1007_sum",
            "FRBP 1007(b) & Official Form 106Sum Instructions",
            "Form 106Sum aggregates totals across Schedules A/B (Lines 55, 62, 63), D, E/F (Lines 6e, 6j), I (Line 12), J (Line 22c), and Form 122A/C CMI.",
            sec2,
        )
        re_sum = sum(
            (a.current_value.value for a in graph.assets if a.category == "real_estate"),
            Decimal("0.00"),
        )
        tot_assets = calcs.total_assets if calcs else sum((a.current_value.value for a in graph.assets), Decimal("0.00"))
        pp_sum = tot_assets - re_sum
        tot_sec = calcs.total_secured_debt if calcs else Decimal("0.00")
        tot_pri = calcs.total_priority_debt if calcs else Decimal("0.00")
        tot_unsec = calcs.total_general_unsecured_debt if calcs else Decimal("0.00")
        comb_liab = tot_sec + tot_pri + tot_unsec
        sched_i = calcs.schedule_i_monthly_gross if calcs else Decimal("0.00")
        sched_j = calcs.schedule_j_monthly_expenses if calcs else Decimal("0.00")

        c_sum_assets = "claim_b106sum_1c"
        nodes[c_sum_assets] = GraphNode(
            id=c_sum_assets,
            type="claim",
            title="Form 106Sum Line 1c — Total All Property (Schedule A/B Line 63)",
            section_id=sec2,
            clause_text=f"${tot_assets:,.2f}",
            direct_child_ids=[],
            audit=NodeAudit(status="verified", score=1.0, evaluator_type="deterministic", evaluator_note="Sum of Schedule A/B."),
        )
        calc_sum_assets = "calc_b106sum_1c"
        nodes[calc_sum_assets] = GraphNode(
            id=calc_sum_assets,
            type="calculation",
            title="Form 106Sum Part 1 Rollup (Line 1a + Line 1b = Line 1c)",
            section_id=sec2,
            formula=f"Line 1a Real Estate (${re_sum:,.2f}) + Line 1b Personal Property (${pp_sum:,.2f}) = ${tot_assets:,.2f}",
            body=f"Mirrors Official Form 106A/B Lines 55 + 62 into Form 106Sum Line 1c under <ref id='{auth_sum}'>FRBP 1007(b)</ref>.",
            direct_child_ids=[],
            parent_claim_ids=[c_sum_assets],
            audit=NodeAudit(status="verified", score=1.0, evaluator_type="deterministic", evaluator_note="Exact Decimal sum."),
        )
        _link(c_sum_assets, calc_sum_assets, c_sum_assets)
        _link(calc_sum_assets, auth_sum, c_sum_assets)

        c_sum_liab = "claim_b106sum_3c"
        nodes[c_sum_liab] = GraphNode(
            id=c_sum_liab,
            type="claim",
            title="Form 106Sum Line 3c — Combined Total Liabilities",
            section_id=sec2,
            clause_text=f"${comb_liab:,.2f}",
            direct_child_ids=[],
            audit=NodeAudit(status="verified", score=1.0, evaluator_type="deterministic", evaluator_note="Sum of Schedules D + E + F."),
        )
        calc_sum_liab = "calc_b106sum_3c"
        nodes[calc_sum_liab] = GraphNode(
            id=calc_sum_liab,
            type="calculation",
            title="Form 106Sum Part 2 Rollup (Line 2 + Line 3a + Line 3b = Line 3c)",
            section_id=sec2,
            formula=f"D (${tot_sec:,.2f}) + E Priority (${tot_pri:,.2f}) + F Unsecured (${tot_unsec:,.2f}) = ${comb_liab:,.2f}",
            body=f"Mirrors Schedule D Part 1 & Schedule E/F Lines 6e/6j into Form 106Sum Line 3c under <ref id='{auth_sum}'>FRBP 1007(b)</ref>.",
            direct_child_ids=[],
            parent_claim_ids=[c_sum_liab],
            audit=NodeAudit(status="verified", score=1.0, evaluator_type="deterministic", evaluator_note="Exact Decimal sum."),
        )
        _link(c_sum_liab, calc_sum_liab, c_sum_liab)
        _link(calc_sum_liab, auth_sum, c_sum_liab)

        cmi_val = calcs.means_test.current_monthly_income if calcs else Decimal("0.00")
        sum_rows = [
            "| Form 106Sum Line | Summary Schedule Description | Source Schedule | Form Amount |",
            "| :--- | :--- | :--- | ---: |",
            f"| 106Sum · 1a | Total Real Estate | Schedule A/B, Line 55 | ${re_sum:,.2f} |",
            f"| 106Sum · 1b | Total Personal Property | Schedule A/B, Line 62 | ${pp_sum:,.2f} |",
            f"| 106Sum · 1c | Total All Property | Schedule A/B, Line 63 | <ref id='{c_sum_assets}'>${tot_assets:,.2f}</ref> |",
            f"| 106Sum · 2 | Total Secured Claims | Schedule D, Part 1 | ${tot_sec:,.2f} |",
            f"| 106Sum · 3a | Priority Unsecured Claims | Schedule E/F, Line 6e | ${tot_pri:,.2f} |",
            f"| 106Sum · 3b | Nonpriority Unsecured Claims | Schedule E/F, Line 6j | ${tot_unsec:,.2f} |",
            f"| 106Sum · 3c | Total Liabilities | Schedules D + E/F | <ref id='{c_sum_liab}'>${comb_liab:,.2f}</ref> |",
            f"| 106Sum · 4 | Combined Monthly Income | Schedule I, Line 12 | ${sched_i:,.2f} |",
            f"| 106Sum · 5 | Monthly Expenses | Schedule J, Line 22c | ${sched_j:,.2f} |",
            f"| 106Sum · 8 | Current Monthly Income (CMI) | Form 122A-1 / 122C-1 | ${cmi_val:,.2f} |",
        ]
        sections.append(
            SectionObject(
                section_id=sec2,
                section_title="Form B 106Sum — Summary of Assets, Liabilities & Statistical Lines",
                order=2,
                content="\n".join(sum_rows),
            )
        )

        # -----------------------------------------------------------------
        # Section 3: Schedule A/B (B 106A/B) & Schedule C (B 106C)
        # -----------------------------------------------------------------
        sec3 = "sec_03_assets_exemptions"
        ex_opt = calcs.exemptions if calcs else None
        auth_ex = _add_authority(
            "aut_ca_exemptions",
            f"Exemption Regime: {ex_opt.recommended_display_name if ex_opt else 'California Exemptions'}",
            (
                f"{ex_opt.domicile_rule_note} Recommended election: {ex_opt.recommended_display_name} "
                f"(Table {ex_opt.table_version_id}, {ex_opt.table_sha256[:18]})."
                if ex_opt
                else "Cal. Civ. Proc. Code §§ 704 & 703.140; 11 U.S.C. § 522(p)."
            ),
            sec3,
        )

        sec3_lines: List[str] = []
        if ex_opt:
            rec_eval = next(
                (e for e in ex_opt.evaluations if e.regime_id == ex_opt.recommended_regime_id),
                ex_opt.evaluations[0],
            )
            c_rec = "claim_sec03_opt"
            nodes[c_rec] = GraphNode(
                id=c_rec,
                type="claim",
                title="Form 106C Line 1 — Optimal California Exemption System",
                section_id=sec3,
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
                f"{e.display_name}: Exempt ${e.total_exempt_equity:,.2f}, Non-Exempt ${e.total_non_exempt_equity:,.2f}"
                for e in ex_opt.evaluations
            )
            calc_opt = "calc_sec03_opt"
            nodes[calc_opt] = GraphNode(
                id=calc_opt,
                type="calculation",
                title="CCP § 704 vs § 703.140(b) Non-Exempt Equity Comparison",
                section_id=sec3,
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
            sec3_lines.append(
                f"**Form 106C Line 1 Election:** <ref id='{c_rec}'>{ex_opt.recommended_display_name} "
                f"(Non-Exempt Exposure: ${rec_eval.total_non_exempt_equity:,.2f})</ref>"
            )

        if graph.assets:
            sec3_lines.append("| Form Line | Property Description (B 106A/B) | Market Value | Net Equity | Exempt (B 106C) | Statute |")
            sec3_lines.append("| :--- | :--- | ---: | ---: | ---: | :--- |")
            alloc_map = {}
            if ex_opt:
                rec_eval = next(
                    (e for e in ex_opt.evaluations if e.regime_id == ex_opt.recommended_regime_id),
                    ex_opt.evaluations[0],
                )
                alloc_map = {a.asset_id: a for a in rec_eval.allocations}

            for idx, asset in enumerate(graph.assets, start=1):
                cid = f"claim_sec03_asset_{idx}"
                alloc = alloc_map.get(asset.asset_id)
                net_eq_str = f"${alloc.net_equity:,.2f}" if alloc else f"${asset.current_value.value:,.2f}"
                ex_str = f"${alloc.total_exempt:,.2f}" if alloc else "$0.00"
                statute_str = alloc.statute_cited if alloc else "Pending"
                form_line, cat_label = ASSET_CATEGORY_LINE_MAP.get(asset.category, ("106A/B", "Property"))

                nodes[cid] = GraphNode(
                    id=cid,
                    type="claim",
                    title=f"{form_line} · {asset.description}",
                    section_id=sec3,
                    clause_text=f"${asset.current_value.value:,.2f}",
                    direct_child_ids=[],
                    audit=_audit_for_field(asset.current_value, asset.description),
                )
                _attach_pf_evidence(
                    cid,
                    sec3,
                    f"sec03_asset_{idx}",
                    f"{form_line} · {asset.description}",
                    asset.current_value,
                    [auth_ex],
                )
                sec3_lines.append(
                    f"| {form_line} | {asset.description} ({cat_label}) | "
                    f"<ref id='{cid}'>${asset.current_value.value:,.2f}</ref> | "
                    f"{net_eq_str} | {ex_str} | {statute_str} |"
                )

        sections.append(
            SectionObject(
                section_id=sec3,
                section_title="Schedules A/B (B 106A/B) & C (B 106C) — Property & Exemptions",
                order=3,
                content="\n".join(sec3_lines) if sec3_lines else "No property items indexed yet.",
            )
        )

        # -----------------------------------------------------------------
        # Section 4: Schedules D (B 106D), E/F (B 106E/F) & Form B 108
        # -----------------------------------------------------------------
        sec4 = "sec_04_creditors"
        auth_claims = _add_authority(
            "aut_claims_506",
            "11 U.S.C. §§ 506, 507, 521(a)(2) & Schedules D / E/F / Form 108",
            "Secured claims scheduled on Form B 106D (with Form 108 Chapter 7 intention); priority & general unsecured claims on Form B 106E/F.",
            sec4,
        )
        sec4_lines: List[str] = []
        if graph.claims:
            sec4_lines.append("| Form Line | Creditor Name | Classification | Claim Amount | Collateral / Form 108 Intention | Audit |")
            sec4_lines.append("| :--- | :--- | :--- | ---: | :--- | :--- |")
            for idx, claim in enumerate(graph.claims, start=1):
                cid = f"claim_sec04_claim_{idx}"
                form_line, pri_label = CLAIM_PRIORITY_LINE_MAP.get(claim.priority_type, ("106E/F", "Unsecured"))
                nodes[cid] = GraphNode(
                    id=cid,
                    type="claim",
                    title=f"{form_line} · {claim.creditor_name}",
                    section_id=sec4,
                    clause_text=f"${claim.total_claim_amount.value:,.2f}",
                    direct_child_ids=[],
                    audit=_audit_for_field(claim.total_claim_amount, claim.creditor_name),
                )
                _attach_pf_evidence(
                    cid,
                    sec4,
                    f"sec04_claim_{idx}",
                    f"{form_line} · {claim.creditor_name}",
                    claim.total_claim_amount,
                    [auth_claims],
                )
                col_desc = claim.collateral_asset_id or "None (Unsecured)"
                if claim.statement_of_intention:
                    int_lbl = INTENTION_LABELS.get(claim.statement_of_intention, claim.statement_of_intention)
                    col_desc = f"{col_desc} · {int_lbl}"
                elif claim.priority_type == "secured" and graph.chapter == "7":
                    col_desc = f"{col_desc} · Form 108 Unset"
                ver_lbl = VERIFICATION_LABELS.get(claim.total_claim_amount.verification_status, "Needs Proof")
                sec4_lines.append(
                    f"| {form_line} | {claim.creditor_name} | {pri_label} | "
                    f"<ref id='{cid}'>${claim.total_claim_amount.value:,.2f}</ref> | "
                    f"{col_desc} | {ver_lbl} |"
                )
        else:
            sec4_lines.append("No creditor claims indexed yet.")

        sections.append(
            SectionObject(
                section_id=sec4,
                section_title="Schedules D (B 106D), E/F (B 106E/F) & Form B 108 — Creditors & Intentions",
                order=4,
                content="\n".join(sec4_lines),
            )
        )

        # -----------------------------------------------------------------
        # Section 5: Schedules I/J, Form 122A/C Means Test & Ch. 13 Plan
        # -----------------------------------------------------------------
        sec5 = "sec_05_means_test_budget"
        mt = calcs.means_test if calcs else None
        auth_mt = _add_authority(
            "aut_707b_ustp",
            "11 U.S.C. §§ 101(10A), 707(b), 1325(b) & USTP Means Test Standards",
            (
                f"6-month CMI window: {mt.lookback_start} to {mt.lookback_end}. "
                f"California median ({mt.household_size} person): ${mt.california_median_income:,.2f} "
                f"(Table {mt.table_version_id}, {mt.table_sha256[:18]})."
                if mt
                else "11 U.S.C. § 707(b)(2) Means Test & IRS Standards."
            ),
            sec5,
        )
        sec5_lines: List[str] = []
        if mt:
            c_cmi = "claim_sec05_cmi"
            nodes[c_cmi] = GraphNode(
                id=c_cmi,
                type="claim",
                title="Form 122A-1 / 122C-1 Line 11 — 6-Month CMI",
                section_id=sec5,
                clause_text=f"${mt.current_monthly_income:,.2f}/mo (${mt.annualized_cmi:,.2f}/yr)",
                direct_child_ids=[],
                audit=NodeAudit(
                    status="verified",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note=f"Window {mt.lookback_start}..{mt.lookback_end}",
                ),
            )
            calc_cmi = "calc_sec05_cmi"
            stub_terms = " + ".join(
                f"${ps.gross_pay.value:,.2f} ({ps.pay_date.isoformat()})"
                for ps in graph.paystubs
                if mt.lookback_start <= ps.pay_date <= mt.lookback_end
            ) or "$0.00"
            nodes[calc_cmi] = GraphNode(
                id=calc_cmi,
                type="calculation",
                title="Form 122A-1 / 122C-1 CMI 6-Month Average Formula",
                section_id=sec5,
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
                        sec5,
                        f"sec05_ps_{idx}",
                        f"Paystub {ps.employer} ({ps.pay_date})",
                        ps.gross_pay,
                        [auth_mt],
                    )

            c_disp = "claim_sec05_disposable"
            nodes[c_disp] = GraphNode(
                id=c_disp,
                type="claim",
                title="Form 122A-2 Line 39c / 122C-2 — Monthly Disposable Income",
                section_id=sec5,
                clause_text=f"${mt.monthly_disposable_income:,.2f}/mo",
                direct_child_ids=[],
                audit=NodeAudit(
                    status="verified" if not mt.presumption_of_abuse else "disputed",
                    score=1.0,
                    evaluator_type="deterministic",
                    evaluator_note=f"IRS + Tax + Secured Cure Deductions = ${mt.total_allowed_deductions:,.2f}/mo",
                ),
            )
            calc_disp = "calc_sec05_disposable"
            nodes[calc_disp] = GraphNode(
                id=calc_disp,
                type="calculation",
                title="Form 122A-2 / 122C-2 IRS Standard Deduction Breakdown",
                section_id=sec5,
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

            form_prefix = "122A" if graph.chapter == "7" else "122C"
            median_verdict = "Above CA Median" if mt.is_above_median else "Below CA Median"
            net_ij = (calcs.schedule_ij_monthly_net if calcs else Decimal("0.00"))
            sec5_lines.extend([
                "| Form Line | Means Test & Budget Item | Statutory Benchmark | Computed Value |",
                "| :--- | :--- | :--- | ---: |",
                f"| {form_prefix}-1 · 11 | 6-Month Average CMI ({mt.lookback_start} to {mt.lookback_end}) | 11 U.S.C. § 101(10A) | <ref id='{c_cmi}'>${mt.current_monthly_income:,.2f}</ref> |",
                f"| {form_prefix}-1 · 15–16 | Annualized CMI vs. CA {mt.household_size}-Person Median | {median_verdict} (${mt.california_median_income:,.2f}) | ${mt.annualized_cmi:,.2f} |",
                f"| {form_prefix}-2 · 24 | IRS Standards + Taxes + Secured Debt Deductions | Form {form_prefix}-2 Pt. 2 | ${mt.total_allowed_deductions:,.2f} |",
                f"| {form_prefix}-2 · 39c | Monthly Disposable Income | 60-Mo Pool: ${mt.sixty_month_disposable_income:,.2f} | <ref id='{c_disp}'>${mt.monthly_disposable_income:,.2f}</ref> |",
                f"| 106I · 12 / 106J · 23c | Schedule I Income / Schedule J Net (I - J) | Income ${sched_i:,.2f} - Exp ${sched_j:,.2f} | ${net_ij:,.2f} |",
            ])

            if calcs and calcs.ch13_plan:
                plan = calcs.ch13_plan
                plan_form = "F 3015-1.01" if graph.district == "CACB" else "EDC 3-080"
                sec5_lines.append(
                    f"| {plan_form} · Plan | Ch. 13 Plan ({plan.applicable_commitment_months} mos) · Floor ${plan.best_interests_liquidation_floor:,.2f} | Priority ${plan.priority_claims_total:,.2f} + Arrears ${plan.secured_arrears_total:,.2f} | ${plan.estimated_monthly_plan_payment:,.2f} |"
                )

            if graph.historical_transactions:
                inc_hist = "; ".join(
                    f"{h.tx_date.year if h.tx_date else 'SOFA'}: ${h.amount.value:,.2f}" if h.amount else h.description
                    for h in graph.historical_transactions[:3]
                )
                sec5_lines.append(
                    f"| Form 107 · Pt. 2 | Statement of Financial Affairs History | {len(graph.historical_transactions)} disclosure(s) | {inc_hist} |"
                )
        else:
            sec5_lines.append("No paystub income or budget records indexed yet.")

        sections.append(
            SectionObject(
                section_id=sec5,
                section_title="Schedules I/J, Form 122A/C Means Test & Plan Calculation",
                order=5,
                content="\n".join(sec5_lines),
            )
        )

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
            question=f"Bankruptcy Petition & Schedule Compilation — Chapter {graph.chapter} ({graph.district})",
            artifact=ArtifactEnvelope(
                title=f"Chapter {graph.chapter} Official Forms Audit Schedule — {graph.matter_id}",
                created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                metadata={
                    "application": "bankruptcy_workbench",
                    "chapter": graph.chapter,
                    "district": graph.district,
                    "expected_filing_date": graph.expected_filing_date.isoformat(),
                    "planned_pdf_forms": planned_forms,
                },
                summary=(
                    f"Official-form-aligned audit schedule covering {len(graph.assets)} property item(s), "
                    f"{len(graph.claims)} creditor claim(s), and {len(graph.paystubs)} paystub(s) across {len(planned_forms)} required court forms."
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
