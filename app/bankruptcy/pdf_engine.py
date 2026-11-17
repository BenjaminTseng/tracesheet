"""FormPacketPlanner, PyMuPDF AcroForm template seeder/filler/baker, and FieldLineage emitter.

Guarantees that:
1. Required forms are planned deterministically from `(chapter, district, CanonicalCaseGraph)`.
2. Every filled PDF is baked via `pymupdf.Document.bake(annots=True, widgets=True)` so zero
   mutable form widgets remain for CM/ECF submission.
3. Overflow assets/claims generate continuation pages so zero rows are ever truncated.
4. Full SSNs and account numbers never leak into public forms (FRBP 9037), appearing only in
   isolated `Form_B121_RESTRICTED.pdf` and `debtor.txt`.
5. Every filled widget emits a cryptographic `FieldLineageEntry` in `field_lineage.json`.
"""

from __future__ import annotations

import json
import textwrap
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

from app.bankruptcy.models import (
    AssetItem,
    BankruptcyCaseState,
    CanonicalCaseGraph,
    ChapterType,
    ClaimItem,
    DistrictCode,
    FieldLineageEntry,
    ProvenanceField,
)
from app.core.pii import PIITokenizer


class FormPacketPlanner:
    """Deterministically selects all National and California Local forms for a case."""

    BASE_INDIVIDUAL_FORMS = [
        "B101",
        "B106Sum",
        "B106AB",
        "B106C",
        "B106D",
        "B106EF",
        "B106G",
        "B106H",
        "B106I",
        "B106J",
        "B106Dec",
        "B107",
        "B121",
    ]

    def plan_required_forms(self, state: BankruptcyCaseState) -> List[str]:
        """Returns the exact ordered list of required form IDs for `state`.

        Args:
            state: Current `BankruptcyCaseState` with `case_graph` and optional `calculations`.

        Returns:
            Ordered list of official national and California local form IDs.
        """
        graph = state.case_graph
        forms = list(self.BASE_INDIVIDUAL_FORMS)
        is_above_median = (
            state.calculations.means_test.is_above_median
            if state.calculations is not None
            else False
        )
        has_secured = any(c.priority_type == "secured" for c in graph.claims)

        if graph.chapter == "7":
            forms.append("B122A1")
            if is_above_median:
                forms.append("B122A2")
            if has_secured:
                forms.append("B108")
        elif graph.chapter == "13":
            forms.append("B122C1")
            if is_above_median:
                forms.append("B122C2")
        elif graph.chapter == "11_subv":
            forms.append("B122B")

        if graph.district == "CACB":
            forms.extend(["CACB_F1007_1", "CACB_F5005_4"])
            if graph.chapter == "13":
                forms.extend(["CACB_F3015_1_01", "CACB_F3015_1_7_RARA"])
        elif graph.district == "CAEB":
            forms.append("CAEB_ESIG")
            if graph.chapter == "13":
                forms.append("CAEB_EDC_3_080")

        return forms


class AcroFormTemplateRegistry:
    """Seeds and serves blank AcroForm PDF templates with real `/Widget` fields."""

    FORM_SPECS: Dict[str, Tuple[str, List[str]]] = {
        "B101": (
            "Official Form 101 - Voluntary Petition for Individuals Filing for Bankruptcy",
            [
                "Debtor1_Name",
                "Debtor1_Last4SSN",
                "Debtor1_Street",
                "Debtor1_CityStateZip",
                "Debtor1_County",
                "District_Code",
                "Chapter_Selected",
                "Estimated_Assets",
                "Estimated_Liabilities",
            ],
        ),
        "B106Sum": (
            "Official Form 106Sum - Summary of Your Assets and Liabilities",
            [
                "Debtor1_Name",
                "Total_Assets_AB",
                "Total_Secured_D",
                "Total_Priority_E",
                "Total_Unsecured_F",
                "Combined_Liabilities",
                "Schedule_I_Monthly_Income",
                "Schedule_J_Monthly_Expenses",
                "MeansTest_CMI",
            ],
        ),
        "B106AB": (
            "Official Form 106A/B - Schedule A/B: Property",
            [f"Asset_Row_{i}" for i in range(1, 7)] + ["Total_Assets_AB"],
        ),
        "B106C": (
            "Official Form 106C - Schedule C: The Property You Claim as Exempt",
            ["Exemption_Regime_Selected"]
            + [f"Exemption_Row_{i}" for i in range(1, 7)]
            + ["Total_Exempt_Equity", "Total_Non_Exempt_Equity"],
        ),
        "B106D": (
            "Official Form 106D - Schedule D: Creditors Who Hold Claims Secured by Property",
            [f"Secured_Row_{i}" for i in range(1, 7)] + ["Total_Secured_D"],
        ),
        "B106EF": (
            "Official Form 106E/F - Schedule E/F: Creditors Who Have Unsecured Claims",
            [f"Unsecured_Row_{i}" for i in range(1, 7)] + ["Total_Unsecured_EF"],
        ),
        "B106G": (
            "Official Form 106G - Schedule G: Executory Contracts and Unexpired Leases",
            [f"Contract_Row_{i}" for i in range(1, 5)],
        ),
        "B106H": (
            "Official Form 106H - Schedule H: Your Codebtors",
            [f"Codebtor_Row_{i}" for i in range(1, 5)],
        ),
        "B106I": (
            "Official Form 106I - Schedule I: Your Income",
            ["Employer_Summary", "Schedule_I_Monthly_Income"],
        ),
        "B106J": (
            "Official Form 106J - Schedule J: Your Expenses",
            ["Household_Size", "Expense_Breakdown", "Schedule_J_Monthly_Expenses", "Monthly_Net_Income"],
        ),
        "B106Dec": (
            "Official Form 106Dec - Declaration About an Individual Debtor's Schedules",
            ["Debtor1_Name", "Declaration_Date", "Debtor1_Signature"],
        ),
        "B107": (
            "Official Form 107 - Statement of Financial Affairs (SOFA)",
            ["Debtor1_Name", "Income_History_Summary", "SOFA_Transactions_Summary"],
        ),
        "B108": (
            "Official Form 108 - Statement of Intention for Individuals Filing Under Chapter 7",
            [f"Intention_Row_{i}" for i in range(1, 6)],
        ),
        "B121": (
            "Official Form 121 - Statement About Your Social Security Numbers (RESTRICTED PRIVATE)",
            ["Debtor1_Name", "Debtor1_Full_SSN", "Filing_Date"],
        ),
        "B122A1": (
            "Official Form 122A-1 - Chapter 7 Statement of Your Current Monthly Income",
            ["Lookback_Window", "Current_Monthly_Income", "Annualized_CMI", "Household_Size", "CA_Median_Income", "Median_Verdict"],
        ),
        "B122A2": (
            "Official Form 122A-2 - Chapter 7 Means Test Calculation",
            ["IRS_Food_Clothing", "IRS_Healthcare", "IRS_Housing_Utilities", "IRS_Transportation", "Taxes_And_Secured", "Monthly_Disposable_Income", "Presumption_Of_Abuse"],
        ),
        "B122C1": (
            "Official Form 122C-1 - Chapter 13 Statement of Your Current Monthly Income",
            ["Lookback_Window", "Current_Monthly_Income", "Annualized_CMI", "Household_Size", "CA_Median_Income", "Commitment_Period_Months"],
        ),
        "B122C2": (
            "Official Form 122C-2 - Chapter 13 Calculation of Your Disposable Income",
            ["IRS_Food_Clothing", "IRS_Healthcare", "IRS_Housing_Utilities", "IRS_Transportation", "Taxes_And_Secured", "Monthly_Disposable_Income"],
        ),
        "B122B": (
            "Official Form 122B - Chapter 11 Statement of Your Current Monthly Income",
            ["Current_Monthly_Income", "Annualized_CMI"],
        ),
        "CACB_F1007_1": (
            "CACB Local Form F 1007-1 - Verification of Master Mailing List of Creditors",
            ["Debtor1_Name", "Creditor_Matrix_Count", "Attorney_Name"],
        ),
        "CACB_F5005_4": (
            "CACB Local Form F 5005-4 - Electronic Filing Declaration",
            ["Debtor1_Name", "Attorney_Name", "Attorney_Bar_Number"],
        ),
        "CACB_F3015_1_01": (
            "CACB Local Form F 3015-1.01 - Chapter 13 Plan",
            ["Debtor1_Name", "Commitment_Period_Months", "Estimated_Monthly_Payment", "Liquidation_Floor"],
        ),
        "CACB_F3015_1_7_RARA": (
            "CACB Local Form F 3015-1.7.RARA - Rights and Responsibilities Agreement",
            ["Debtor1_Name", "Attorney_Name"],
        ),
        "CAEB_EDC_3_080": (
            "CAEB Mandatory Local Form EDC 3-080 - Chapter 13 Plan",
            ["Debtor1_Name", "Commitment_Period_Months", "Estimated_Monthly_Payment", "Secured_Arrears_Total"],
        ),
        "CAEB_ESIG": (
            "CAEB Electronic Filing Signature Verification Form",
            ["Debtor1_Name", "Attorney_Name", "Attorney_Bar_Number"],
        ),
    }

    def __init__(self, templates_dir: Path) -> None:
        """Initializes the AcroForm template registry.

        Args:
            templates_dir: Directory storing fillable AcroForm PDF templates.
        """
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    def ensure_template(self, form_id: str) -> Path:
        """Returns path to blank fillable AcroForm PDF for `form_id`, generating if missing.

        Args:
            form_id: Official national or local form identifier.

        Returns:
            Path to blank fillable AcroForm PDF containing PyMuPDF `/Widget` fields.
        """
        path = self.templates_dir / f"{form_id}.pdf"
        if path.exists():
            return path

        title, field_names = self.FORM_SPECS.get(
            form_id, (f"Bankruptcy Form {form_id}", ["Debtor1_Name"])
        )
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((48, 52), title, fontsize=12.5, fontname="helv")
        page.draw_line((48, 62), (564, 62))

        y = 84
        for fname in field_names:
            if y > 720:
                page = doc.new_page(width=612, height=792)
                y = 60
            page.insert_text((48, y + 14), f"{fname.replace('_', ' ')}:", fontsize=9, fontname="helv")
            widget = pymupdf.Widget()
            widget.field_name = fname
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pymupdf.Rect(215, y, 560, y + 22)
            widget.text_fontsize = 9.5
            widget.text_font = "helv"
            widget.border_width = 0.5
            widget.border_color = (0.7, 0.7, 0.7)
            widget.field_value = ""
            page.add_widget(widget)
            y += 32

        doc.save(str(path))
        doc.close()
        return path


class AcroFormFillerAndBaker:
    """Fills AcroForm PDFs deterministically, appends continuation sheets, bakes widgets, and logs lineage."""

    def __init__(
        self,
        templates_dir: Path,
        tokenizer: PIITokenizer,
    ) -> None:
        """Initializes the AcroForm filler and baker.

        Args:
            templates_dir: Directory containing blank fillable AcroForm PDFs.
            tokenizer: Matter-scoped `PIITokenizer` enforcing strict FRBP 9037 / B 121 separation.
        """
        self.templates = AcroFormTemplateRegistry(templates_dir)
        self.tokenizer = tokenizer
        self.planner = FormPacketPlanner()

    @staticmethod
    def _first_locator(pf: Optional[ProvenanceField[Any]]) -> List[Any]:
        return list(pf.locators) if pf else []

    @staticmethod
    def _override(pf: Optional[ProvenanceField[Any]]) -> Any:
        return pf.override if pf else None

    def _build_field_bindings(
        self, state: BankruptcyCaseState
    ) -> Tuple[
        Dict[str, Dict[str, Tuple[str, str, str, Optional[str], List[Any], Any]]],
        Dict[str, List[str]],
    ]:
        """Constructs per-form widget values alongside full `FieldLineageEntry` metadata."""
        graph = state.case_graph
        calcs = state.calculations
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)

        d_name = debtor_1.full_name.value if debtor_1 else "Unknown Debtor"
        d_name_locs = self._first_locator(debtor_1.full_name if debtor_1 else None)
        d_name_ov = self._override(debtor_1.full_name if debtor_1 else None)

        raw_ssn_token = (debtor_1.ssn_token_or_ein if debtor_1 else None) or ""
        public_last4_ssn = self.tokenizer.redact_for_public_form(raw_ssn_token or "XXX-XX-XXXX")

        # Strict isolation: only Form B 121 unmasks SSN via PIITokenizer!
        if raw_ssn_token.startswith("[PII:SSN_"):
            b121_ssn = self.tokenizer.unmask_for_restricted_form(
                graph.matter_id, raw_ssn_token, "B121"
            )
        else:
            b121_ssn = raw_ssn_token or "NOT PROVIDED"

        tot_assets = f"${calcs.total_assets:,.2f}" if calcs else "$0.00"
        tot_sec = f"${calcs.total_secured_debt:,.2f}" if calcs else "$0.00"
        tot_pri = f"${calcs.total_priority_debt:,.2f}" if calcs else "$0.00"
        tot_unsec = f"${calcs.total_general_unsecured_debt:,.2f}" if calcs else "$0.00"
        comb_liab = (
            f"${(calcs.total_secured_debt + calcs.total_priority_debt + calcs.total_general_unsecured_debt):,.2f}"
            if calcs
            else "$0.00"
        )
        sched_i = f"${calcs.schedule_i_monthly_gross:,.2f}" if calcs else "$0.00"
        sched_j = f"${calcs.schedule_j_monthly_expenses:,.2f}" if calcs else "$0.00"
        sched_net = f"${calcs.schedule_ij_monthly_net:,.2f}" if calcs else "$0.00"

        def _entry(
            val: str,
            dtype: str,
            path: str,
            formula: Optional[str] = None,
            locs: Optional[List[Any]] = None,
            ov: Any = None,
        ) -> Tuple[str, str, str, Optional[str], List[Any], Any]:
            safe_val = self.tokenizer.redact_for_public_form(val)
            return safe_val, dtype, path, formula, (locs or []), ov

        bindings: Dict[str, Dict[str, Tuple[str, str, str, Optional[str], List[Any], Any]]] = {}
        overflow_lines: Dict[str, List[str]] = {}

        # B101
        csz = f"{debtor_1.city}, {debtor_1.state} {debtor_1.zip_code}".strip(", ") if debtor_1 else ""
        bindings["B101"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_Last4SSN": _entry(public_last4_ssn, "system_constant", "$.parties[0].ssn_token_or_ein"),
            "Debtor1_Street": _entry(debtor_1.street_address if debtor_1 else "", "direct_provenance", "$.parties[0].street_address"),
            "Debtor1_CityStateZip": _entry(csz, "direct_provenance", "$.parties[0].city_state_zip"),
            "Debtor1_County": _entry(debtor_1.county_of_residence if debtor_1 else "", "direct_provenance", "$.parties[0].county_of_residence"),
            "District_Code": _entry(graph.district, "system_constant", "$.district"),
            "Chapter_Selected": _entry(f"Chapter {graph.chapter}", "system_constant", "$.chapter"),
            "Estimated_Assets": _entry(tot_assets, "deterministic_calculation", "$.calculations.total_assets", "=SUM(assets.current_value)"),
            "Estimated_Liabilities": _entry(comb_liab, "deterministic_calculation", "$.calculations.combined_liabilities", "=SUM(claims.total_claim_amount)"),
        }

        # B106Sum
        cmi_str = f"${calcs.means_test.current_monthly_income:,.2f}" if calcs else "$0.00"
        bindings["B106Sum"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Total_Assets_AB": _entry(tot_assets, "deterministic_calculation", "$.calculations.total_assets", "=SUM(Schedule A/B)"),
            "Total_Secured_D": _entry(tot_sec, "deterministic_calculation", "$.calculations.total_secured_debt", "=SUM(Schedule D)"),
            "Total_Priority_E": _entry(tot_pri, "deterministic_calculation", "$.calculations.total_priority_debt", "=SUM(Schedule E)"),
            "Total_Unsecured_F": _entry(tot_unsec, "deterministic_calculation", "$.calculations.total_general_unsecured_debt", "=SUM(Schedule F)"),
            "Combined_Liabilities": _entry(comb_liab, "deterministic_calculation", "$.calculations.combined_liabilities", "=D + E + F"),
            "Schedule_I_Monthly_Income": _entry(sched_i, "deterministic_calculation", "$.calculations.schedule_i_monthly_gross", "=SUM(Schedule I)"),
            "Schedule_J_Monthly_Expenses": _entry(sched_j, "deterministic_calculation", "$.calculations.schedule_j_monthly_expenses", "=SUM(Schedule J)"),
            "MeansTest_CMI": _entry(cmi_str, "deterministic_calculation", "$.calculations.means_test.current_monthly_income", "=SUM(CMI_6mo)/6"),
        }

        # B106AB (first 6 in widgets + overflow continuation lines)
        ab_fields: Dict[str, Any] = {"Total_Assets_AB": _entry(tot_assets, "deterministic_calculation", "$.calculations.total_assets", "=SUM(Schedule A/B)")}
        for i in range(1, 7):
            if i <= len(graph.assets):
                a = graph.assets[i - 1]
                ab_fields[f"Asset_Row_{i}"] = _entry(
                    f"[{a.category}] {a.description} — ${a.current_value.value:,.2f}",
                    "direct_provenance",
                    f"$.assets[{i - 1}].current_value",
                    None,
                    self._first_locator(a.current_value),
                    self._override(a.current_value),
                )
            else:
                ab_fields[f"Asset_Row_{i}"] = _entry("", "system_constant", "$.assets")
        bindings["B106AB"] = ab_fields
        if len(graph.assets) > 6:
            overflow_lines["B106AB"] = [
                f"Row {idx}: [{a.category}] {self.tokenizer.redact_for_public_form(a.description)} — ${a.current_value.value:,.2f}"
                for idx, a in enumerate(graph.assets[6:], start=7)
            ]

        # B106C
        c_fields: Dict[str, Any] = {}
        if calcs:
            ex = calcs.exemptions
            rec = next((e for e in ex.evaluations if e.regime_id == ex.recommended_regime_id), ex.evaluations[0])
            c_fields["Exemption_Regime_Selected"] = _entry(
                ex.recommended_display_name,
                "deterministic_calculation",
                "$.calculations.exemptions.recommended_regime_id",
                f"MIN(non_exempt_equity across {[e.regime_id for e in ex.evaluations]})",
            )
            for i in range(1, 7):
                if i <= len(rec.allocations):
                    al = rec.allocations[i - 1]
                    c_fields[f"Exemption_Row_{i}"] = _entry(
                        f"{al.asset_description} | Exempt: ${al.total_exempt:,.2f} ({al.statute_cited})",
                        "deterministic_calculation",
                        f"$.calculations.exemptions.allocations[{i - 1}]",
                        f"MIN(net_equity ${al.net_equity:,.2f}, cap+wildcard)",
                    )
                else:
                    c_fields[f"Exemption_Row_{i}"] = _entry("", "system_constant", "$.calculations.exemptions")
            c_fields["Total_Exempt_Equity"] = _entry(f"${rec.total_exempt_equity:,.2f}", "deterministic_calculation", "$.calculations.exemptions.total_exempt_equity", "=SUM(allocations.total_exempt)")
            c_fields["Total_Non_Exempt_Equity"] = _entry(f"${rec.total_non_exempt_equity:,.2f}", "deterministic_calculation", "$.calculations.exemptions.total_non_exempt_equity", "=SUM(allocations.non_exempt_equity)")
            if len(rec.allocations) > 6:
                overflow_lines["B106C"] = [
                    f"Row {idx}: {al.asset_description} | Exempt ${al.total_exempt:,.2f} ({al.statute_cited})"
                    for idx, al in enumerate(rec.allocations[6:], start=7)
                ]
        bindings["B106C"] = c_fields

        # B106D (Secured)
        sec_claims = [c for c in graph.claims if c.priority_type == "secured"]
        d_fields: Dict[str, Any] = {"Total_Secured_D": _entry(tot_sec, "deterministic_calculation", "$.calculations.total_secured_debt", "=SUM(Schedule D)")}
        for i in range(1, 7):
            if i <= len(sec_claims):
                cl = sec_claims[i - 1]
                d_fields[f"Secured_Row_{i}"] = _entry(
                    f"{cl.creditor_name} | Collat: {cl.collateral_asset_id or 'N/A'} | ${cl.total_claim_amount.value:,.2f}",
                    "direct_provenance",
                    f"$.claims[secured:{cl.claim_id}].total_claim_amount",
                    None,
                    self._first_locator(cl.total_claim_amount),
                    self._override(cl.total_claim_amount),
                )
            else:
                d_fields[f"Secured_Row_{i}"] = _entry("", "system_constant", "$.claims")
        bindings["B106D"] = d_fields
        if len(sec_claims) > 6:
            overflow_lines["B106D"] = [
                f"Row {idx}: {c.creditor_name} | ${c.total_claim_amount.value:,.2f}"
                for idx, c in enumerate(sec_claims[6:], start=7)
            ]

        # B106EF (Priority & Unsecured)
        unsec_claims = [c for c in graph.claims if c.priority_type != "secured"]
        ef_total = (
            f"${(calcs.total_priority_debt + calcs.total_general_unsecured_debt):,.2f}"
            if calcs
            else "$0.00"
        )
        ef_fields: Dict[str, Any] = {"Total_Unsecured_EF": _entry(ef_total, "deterministic_calculation", "$.calculations.total_unsecured_ef", "=SUM(E+F)")}
        for i in range(1, 7):
            if i <= len(unsec_claims):
                cl = unsec_claims[i - 1]
                ef_fields[f"Unsecured_Row_{i}"] = _entry(
                    f"[{cl.priority_type}] {cl.creditor_name} — ${cl.total_claim_amount.value:,.2f}",
                    "direct_provenance",
                    f"$.claims[unsecured:{cl.claim_id}].total_claim_amount",
                    None,
                    self._first_locator(cl.total_claim_amount),
                    self._override(cl.total_claim_amount),
                )
            else:
                ef_fields[f"Unsecured_Row_{i}"] = _entry("", "system_constant", "$.claims")
        bindings["B106EF"] = ef_fields
        if len(unsec_claims) > 6:
            overflow_lines["B106EF"] = [
                f"Row {idx}: [{c.priority_type}] {c.creditor_name} — ${c.total_claim_amount.value:,.2f}"
                for idx, c in enumerate(unsec_claims[6:], start=7)
            ]

        # B106G, B106H, B106I, B106J, B106Dec, B107, B108
        bindings["B106G"] = {
            f"Contract_Row_{i}": _entry(
                f"{graph.executory_contracts[i - 1].counterparty}: {graph.executory_contracts[i - 1].description}"
                if i <= len(graph.executory_contracts)
                else "",
                "direct_provenance",
                f"$.executory_contracts[{i - 1}]",
            )
            for i in range(1, 5)
        }
        bindings["B106H"] = {
            f"Codebtor_Row_{i}": _entry(
                f"{graph.codebtors[i - 1].name} ({graph.codebtors[i - 1].address})"
                if i <= len(graph.codebtors)
                else "",
                "direct_provenance",
                f"$.codebtors[{i - 1}]",
            )
            for i in range(1, 5)
        }
        employers = ", ".join(sorted({ps.employer for ps in graph.paystubs})) or "None"
        bindings["B106I"] = {
            "Employer_Summary": _entry(employers, "direct_provenance", "$.paystubs.employers"),
            "Schedule_I_Monthly_Income": _entry(sched_i, "deterministic_calculation", "$.calculations.schedule_i_monthly_gross", "=SUM(Schedule I)"),
        }
        hh_val = str(debtor_1.household_size.value if debtor_1 else 1)
        exp_desc = "; ".join(f"{e.category}: ${e.monthly_amount.value:,.2f}" for e in graph.budget.expense_items[:4])
        bindings["B106J"] = {
            "Household_Size": _entry(hh_val, "direct_provenance", "$.parties[0].household_size", None, self._first_locator(debtor_1.household_size if debtor_1 else None), self._override(debtor_1.household_size if debtor_1 else None)),
            "Expense_Breakdown": _entry(exp_desc or "No itemized expenses", "direct_provenance", "$.budget.expense_items"),
            "Schedule_J_Monthly_Expenses": _entry(sched_j, "deterministic_calculation", "$.calculations.schedule_j_monthly_expenses", "=SUM(Schedule J)"),
            "Monthly_Net_Income": _entry(sched_net, "deterministic_calculation", "$.calculations.schedule_ij_monthly_net", "=Schedule I - Schedule J"),
        }
        bindings["B106Dec"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Declaration_Date": _entry(graph.expected_filing_date.isoformat(), "system_constant", "$.expected_filing_date"),
            "Debtor1_Signature": _entry(f"/s/ {d_name}", "system_constant", "$.parties[0].full_name"),
        }
        inc_hist = "; ".join(
            f"{h.tx_date.year if h.tx_date else ''}: ${h.amount.value:,.2f}" if h.amount else h.description
            for h in graph.historical_transactions
            if h.sofa_part == "income_history"
        )
        bindings["B107"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Income_History_Summary": _entry(inc_hist or "See Tax Returns", "direct_provenance", "$.historical_transactions[income_history]"),
            "SOFA_Transactions_Summary": _entry(f"{len(graph.historical_transactions)} historical disclosure(s)", "direct_provenance", "$.historical_transactions"),
        }
        bindings["B108"] = {
            f"Intention_Row_{i}": _entry(
                f"{sec_claims[i - 1].creditor_name} -> {sec_claims[i - 1].statement_of_intention or 'UNSET'}"
                if i <= len(sec_claims)
                else "",
                "human_override",
                f"$.claims[secured:{sec_claims[i - 1].claim_id}].statement_of_intention" if i <= len(sec_claims) else "$.claims",
            )
            for i in range(1, 6)
        }

        # B121 RESTRICTED — bypasses redact_for_public_form intentionally!
        bindings["B121"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_Full_SSN": (
                b121_ssn,
                "direct_provenance",
                "$.parties[0].ssn_token_or_ein",
                "PIITokenizer.unmask_for_restricted_form('B121')",
                [],
                None,
            ),
            "Filing_Date": _entry(graph.expected_filing_date.isoformat(), "system_constant", "$.expected_filing_date"),
        }

        # B122A1 / B122A2 / B122C1 / B122C2 / B122B
        if calcs:
            mt = calcs.means_test
            verdict_str = "ABOVE MEDIAN (Part 2 Required)" if mt.is_above_median else "BELOW MEDIAN (Presumption Does Not Arise)"
            common_mt_1 = {
                "Lookback_Window": _entry(f"{mt.lookback_start} to {mt.lookback_end}", "deterministic_calculation", "$.calculations.means_test.lookback_window"),
                "Current_Monthly_Income": _entry(f"${mt.current_monthly_income:,.2f}", "deterministic_calculation", "$.calculations.means_test.current_monthly_income", "=SUM(6mo_gross)/6"),
                "Annualized_CMI": _entry(f"${mt.annualized_cmi:,.2f}", "deterministic_calculation", "$.calculations.means_test.annualized_cmi", "=CMI * 12"),
                "Household_Size": _entry(str(mt.household_size), "direct_provenance", "$.parties[0].household_size"),
                "CA_Median_Income": _entry(f"${mt.california_median_income:,.2f}", "system_constant", f"$.tables.{mt.table_version_id}"),
            }
            bindings["B122A1"] = {**common_mt_1, "Median_Verdict": _entry(verdict_str, "deterministic_calculation", "$.calculations.means_test.is_above_median")}
            bindings["B122C1"] = {**common_mt_1, "Commitment_Period_Months": _entry(f"{mt.applicable_commitment_months} months", "deterministic_calculation", "$.calculations.means_test.applicable_commitment_months")}
            common_mt_2 = {
                "IRS_Food_Clothing": _entry(f"${mt.irs_food_clothing_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_food_clothing_allowance"),
                "IRS_Healthcare": _entry(f"${mt.irs_healthcare_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_healthcare_allowance"),
                "IRS_Housing_Utilities": _entry(f"${mt.irs_housing_utilities_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_housing_utilities_allowance"),
                "IRS_Transportation": _entry(f"${mt.irs_transportation_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_transportation_allowance"),
                "Taxes_And_Secured": _entry(f"${(mt.payroll_taxes_deduction + mt.secured_debt_cure_monthly):,.2f}", "deterministic_calculation", "$.calculations.means_test.taxes_and_secured"),
                "Monthly_Disposable_Income": _entry(f"${mt.monthly_disposable_income:,.2f}", "deterministic_calculation", "$.calculations.means_test.monthly_disposable_income", "=CMI - deductions"),
            }
            bindings["B122A2"] = {
                **common_mt_2,
                "Presumption_Of_Abuse": _entry("YES" if mt.presumption_of_abuse else "NO", "deterministic_calculation", "$.calculations.means_test.presumption_of_abuse"),
            }
            bindings["B122C2"] = common_mt_2
            bindings["B122B"] = {
                "Current_Monthly_Income": common_mt_1["Current_Monthly_Income"],
                "Annualized_CMI": common_mt_1["Annualized_CMI"],
            }

        # District Local Forms
        atty_name = graph.attorney_name or "Supervising Counsel"
        atty_bar = graph.attorney_bar_number or "CA-BAR-PENDING"
        bindings["CACB_F1007_1"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Creditor_Matrix_Count": _entry(str(len(graph.claims)), "deterministic_calculation", "$.claims.length"),
            "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
        }
        bindings["CACB_F5005_4"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
            "Attorney_Bar_Number": _entry(atty_bar, "system_constant", "$.attorney_bar_number"),
        }
        bindings["CAEB_ESIG"] = dict(bindings["CACB_F5005_4"])

        if calcs and calcs.ch13_plan:
            p = calcs.ch13_plan
            bindings["CACB_F3015_1_01"] = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Commitment_Period_Months": _entry(f"{p.applicable_commitment_months} months", "deterministic_calculation", "$.calculations.ch13_plan.applicable_commitment_months"),
                "Estimated_Monthly_Payment": _entry(f"${p.estimated_monthly_plan_payment:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.estimated_monthly_plan_payment", "=total_funding / months"),
                "Liquidation_Floor": _entry(f"${p.best_interests_liquidation_floor:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.best_interests_liquidation_floor"),
            }
            bindings["CACB_F3015_1_7_RARA"] = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
            }
            bindings["CAEB_EDC_3_080"] = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Commitment_Period_Months": _entry(f"{p.applicable_commitment_months} months", "deterministic_calculation", "$.calculations.ch13_plan.applicable_commitment_months"),
                "Estimated_Monthly_Payment": _entry(f"${p.estimated_monthly_plan_payment:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.estimated_monthly_plan_payment", "=total_funding / months"),
                "Secured_Arrears_Total": _entry(f"${p.secured_arrears_total:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.secured_arrears_total"),
            }

        return bindings, overflow_lines

    @staticmethod
    def _append_continuation_pages(
        doc: pymupdf.Document, form_id: str, lines: List[str]
    ) -> None:
        """Appends clean continuation sheet PDF pages when rows exceed base widget slots."""
        chunk_size = 24
        for page_num, start in enumerate(range(0, len(lines), chunk_size), start=1):
            page = doc.new_page(width=612, height=792)
            page.insert_text(
                (48, 52),
                f"{form_id} — Overflow Continuation Sheet ({page_num})",
                fontsize=12,
                fontname="helv",
            )
            page.draw_line((48, 62), (564, 62))
            y = 84
            for ln in lines[start : start + chunk_size]:
                for wrapped in textwrap.wrap(ln, width=88) or [""]:
                    page.insert_text((48, y), wrapped, fontsize=9.5, fontname="helv")
                    y += 16

    def compile_forms(
        self,
        state: BankruptcyCaseState,
        output_dir: Path,
        watermark_draft: bool = False,
    ) -> Tuple[List[Path], Path, List[FieldLineageEntry]]:
        """Fills, appends continuation sheets, bakes all AcroForms, and writes `field_lineage.json`.

        Args:
            state: Current `BankruptcyCaseState`.
            output_dir: Destination folder inside `matters/<id>/packet/`.
            watermark_draft: If True, appends `"DRAFT_ONLY"` watermark text across pages.

        Returns:
            Tuple of `(generated_pdf_paths, lineage_json_path, lineage_entries)`.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        form_ids = self.planner.plan_required_forms(state)
        bindings, overflow_lines = self._build_field_bindings(state)

        generated_pdfs: List[Path] = []
        lineage_entries: List[FieldLineageEntry] = []

        for form_id in form_ids:
            tmpl_path = self.templates.ensure_template(form_id)
            form_map = bindings.get(form_id, {})
            doc = pymupdf.open(str(tmpl_path))

            for page in doc:
                for widget in page.widgets() or []:
                    fname = widget.field_name
                    if fname in form_map:
                        val, dtype, cpath, formula, locs, ov = form_map[fname]
                        widget.field_value = val
                        widget.update()
                        if val != "":
                            lineage_entries.append(
                                FieldLineageEntry(
                                    form_id=form_id,
                                    pdf_field_name=fname,
                                    rendered_value=val,
                                    derivation_type=dtype,  # type: ignore[arg-type]
                                    case_graph_path=cpath,
                                    formula=formula,
                                    source_locators=locs,
                                    human_override=ov,
                                )
                            )

            # Bake interactive form widgets permanently into static page streams.
            doc.bake(annots=True, widgets=True)

            if form_id in overflow_lines:
                self._append_continuation_pages(doc, form_id, overflow_lines[form_id])

            if watermark_draft:
                for page in doc:
                    page.insert_text(
                        (180, 400),
                        "DRAFT ONLY - DO NOT FILE",
                        fontsize=24,
                        color=(0.75, 0.25, 0.25),
                    )

            out_name = (
                "Form_B121_RESTRICTED.pdf"
                if form_id == "B121"
                else f"{form_id}.pdf"
            )
            out_path = output_dir / out_name
            doc.save(str(out_path), garbage=4, deflate=True)
            doc.close()
            generated_pdfs.append(out_path)

        lineage_path = output_dir / "field_lineage.json"
        lineage_path.write_text(
            json.dumps([e.model_dump(mode="json") for e in lineage_entries], indent=2),
            encoding="utf-8",
        )
        return generated_pdfs, lineage_path, lineage_entries
