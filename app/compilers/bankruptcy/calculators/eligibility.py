"""Deterministic Chapter 7, Chapter 13 (11 U.S.C. § 109(e)), and Subchapter V (§ 1182) eligibility engine."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List

from app.compilers.bankruptcy.schema import CanonicalCaseGraph, ChapterType, EligibilityResult
from app.core.tables import StatutoryTableRegistry


class EligibilityEngine:
    """Evaluates statutory debt thresholds against effective-dated federal limits.

    Supports both pre-H.R. 7730 bifurcated Chapter 13 caps and post-Nov 10, 2026
    H.R. 7730 unified `$2,750,000` Chapter 13 and `$7,500,000` Subchapter V caps.
    """

    def __init__(self, registry: StatutoryTableRegistry) -> None:
        """Initializes the eligibility engine with a table registry.

        Args:
            registry: Effective-dated `StatutoryTableRegistry`.
        """
        self.registry = registry

    def evaluate(
        self,
        graph: CanonicalCaseGraph,
        target_chapter: ChapterType | None = None,
    ) -> EligibilityResult:
        """Evaluates eligibility for `target_chapter` (defaults to `graph.chapter`).

        Args:
            graph: Case graph containing claims and expected filing date.
            target_chapter: Optional chapter override (`"7"`, `"13"`, or `"11_subv"`).

        Returns:
            Deterministic `EligibilityResult` citing table version and SHA-256 checksum.
        """
        chapter = target_chapter or graph.chapter
        thresholds = self.registry.get_federal_thresholds(graph.expected_filing_date)
        version_id = thresholds["version_id"]
        table_sha = thresholds["_table_sha256"]

        qualifying_secured = Decimal("0.00")
        qualifying_unsecured = Decimal("0.00")
        excluded_contingent_unliq = Decimal("0.00")
        excluded_insider = Decimal("0.00")
        commercial_qualifying = Decimal("0.00")
        non_insider_qualifying = Decimal("0.00")

        for claim in graph.claims:
            amt = claim.total_claim_amount.value
            if claim.contingent or claim.unliquidated:
                excluded_contingent_unliq += amt
                continue

            if claim.priority_type == "secured":
                qualifying_secured += amt
            else:
                qualifying_unsecured += amt

            if claim.is_insider_or_affiliate:
                excluded_insider += amt
            else:
                non_insider_qualifying += amt
                commercial_qualifying += (amt * Decimal(str(claim.commercial_business_pct)))

        combined_qualifying = (qualifying_secured + qualifying_unsecured).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        commercial_ratio = (
            (commercial_qualifying / non_insider_qualifying).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            if non_insider_qualifying > Decimal("0.00")
            else Decimal("0.0000")
        )

        notes: List[str] = []
        if chapter == "7":
            return EligibilityResult(
                target_chapter="7",
                eligible=True,
                total_secured_noncontingent_liquidated=qualifying_secured.quantize(Decimal("0.01")),
                total_unsecured_noncontingent_liquidated=qualifying_unsecured.quantize(Decimal("0.01")),
                total_combined_qualifying_debt=combined_qualifying,
                excluded_contingent_or_unliquidated_debt=excluded_contingent_unliq.quantize(Decimal("0.01")),
                excluded_insider_affiliate_debt=excluded_insider.quantize(Decimal("0.01")),
                commercial_debt_ratio=commercial_ratio,
                threshold_limit_applied=None,
                table_version_id=version_id,
                table_sha256=table_sha,
                authority_citation="11 U.S.C. § 109(b) (Chapter 7 imposes no debt ceiling; subject to § 707(b) Means Test)",
                notes=["Chapter 7 has no maximum debt ceiling."],
            )

        if chapter == "13":
            cfg = thresholds["chapter_13_eligibility"]
            mode = cfg["mode"]
            if mode == "unified":
                limit = Decimal(cfg["combined_limit"])
                eligible = combined_qualifying < limit
                if not eligible:
                    notes.append(
                        f"Combined noncontingent liquidated debt ${combined_qualifying:,.2f} reaches/exceeds unified limit ${limit:,.2f}."
                    )
                else:
                    notes.append(
                        f"Qualifies under unified H.R. 7730 cap (${combined_qualifying:,.2f} < ${limit:,.2f})."
                    )
                return EligibilityResult(
                    target_chapter="13",
                    eligible=eligible,
                    total_secured_noncontingent_liquidated=qualifying_secured.quantize(Decimal("0.01")),
                    total_unsecured_noncontingent_liquidated=qualifying_unsecured.quantize(Decimal("0.01")),
                    total_combined_qualifying_debt=combined_qualifying,
                    excluded_contingent_or_unliquidated_debt=excluded_contingent_unliq.quantize(Decimal("0.01")),
                    excluded_insider_affiliate_debt=excluded_insider.quantize(Decimal("0.01")),
                    commercial_debt_ratio=commercial_ratio,
                    threshold_limit_applied=limit,
                    table_version_id=version_id,
                    table_sha256=table_sha,
                    authority_citation=cfg["authority_citation"],
                    notes=notes,
                )
            else:
                sec_limit = Decimal(cfg["secured_limit"])
                unsec_limit = Decimal(cfg["unsecured_limit"])
                eligible = qualifying_secured < sec_limit and qualifying_unsecured < unsec_limit
                if qualifying_secured >= sec_limit:
                    notes.append(f"Secured debt ${qualifying_secured:,.2f} >= ${sec_limit:,.2f}.")
                if qualifying_unsecured >= unsec_limit:
                    notes.append(f"Unsecured debt ${qualifying_unsecured:,.2f} >= ${unsec_limit:,.2f}.")
                return EligibilityResult(
                    target_chapter="13",
                    eligible=eligible,
                    total_secured_noncontingent_liquidated=qualifying_secured.quantize(Decimal("0.01")),
                    total_unsecured_noncontingent_liquidated=qualifying_unsecured.quantize(Decimal("0.01")),
                    total_combined_qualifying_debt=combined_qualifying,
                    excluded_contingent_or_unliquidated_debt=excluded_contingent_unliq.quantize(Decimal("0.01")),
                    excluded_insider_affiliate_debt=excluded_insider.quantize(Decimal("0.01")),
                    commercial_debt_ratio=commercial_ratio,
                    threshold_limit_applied=sec_limit + unsec_limit,
                    table_version_id=version_id,
                    table_sha256=table_sha,
                    authority_citation=cfg["authority_citation"],
                    notes=notes,
                )

        # Subchapter V (11 U.S.C. § 1182)
        subv_cfg = thresholds["subchapter_v_eligibility"]
        subv_limit = Decimal(subv_cfg["debt_limit"])
        min_ratio = Decimal(subv_cfg["min_commercial_debt_ratio"])
        non_insider_rounded = non_insider_qualifying.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        debt_ok = non_insider_rounded <= subv_limit
        ratio_ok = commercial_ratio >= min_ratio
        eligible = debt_ok and ratio_ok
        if not debt_ok:
            notes.append(
                f"Non-insider noncontingent liquidated debt ${non_insider_rounded:,.2f} exceeds ${subv_limit:,.2f}."
            )
        if not ratio_ok:
            notes.append(
                f"Commercial debt ratio {commercial_ratio:.2%} is below required {min_ratio:.0%}."
            )
        if eligible:
            notes.append(
                f"Qualifies for Subchapter V (${non_insider_rounded:,.2f} <= ${subv_limit:,.2f}, {commercial_ratio:.1%} business debt)."
            )

        return EligibilityResult(
            target_chapter="11_subv",
            eligible=eligible,
            total_secured_noncontingent_liquidated=qualifying_secured.quantize(Decimal("0.01")),
            total_unsecured_noncontingent_liquidated=qualifying_unsecured.quantize(Decimal("0.01")),
            total_combined_qualifying_debt=non_insider_rounded,
            excluded_contingent_or_unliquidated_debt=excluded_contingent_unliq.quantize(Decimal("0.01")),
            excluded_insider_affiliate_debt=excluded_insider.quantize(Decimal("0.01")),
            commercial_debt_ratio=commercial_ratio,
            threshold_limit_applied=subv_limit,
            table_version_id=version_id,
            table_sha256=table_sha,
            authority_citation=subv_cfg["authority_citation"],
            notes=notes,
        )
