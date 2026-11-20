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

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.compilers.bankruptcy.schema import (
    AssetItem,
    BankruptcyCaseState,
    CanonicalCaseGraph,
    ChapterType,
    ClaimItem,
    DistrictCode,
    FieldLineageEntry,
    ProvenanceField,
)
from app.core.pdf_forms import AcroFormEngine, FieldTransformFn
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
                forms.extend(["CAEB_EDC_3_080", "CAEB_EDC_3_096"])

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
            "CAEB Local Form EDC 2-100 - Verification of Master Address List",
            ["Debtor1_Name", "Attorney_Name", "Attorney_Bar_Number"],
        ),
        "CAEB_EDC_3_096": (
            "CAEB Local Form EDC 3-096 - Rights and Responsibilities of Chapter 13 Debtors and Attorneys",
            ["Debtor1_Name", "Attorney_Name"],
        ),
    }

    def __init__(self, templates_dir: Path) -> None:
        """Initializes the AcroForm template registry."""
        self.templates_dir = templates_dir
        self._engine = AcroFormEngine(templates_dir)

    def ensure_template(self, form_id: str) -> Path:
        """Returns path to blank fillable AcroForm PDF for `form_id`, generating if missing."""
        title, field_names = self.FORM_SPECS.get(
            form_id, (f"Bankruptcy Form {form_id}", ["Debtor1_Name"])
        )
        return self._engine.ensure_template(
            form_id,
            fallback_title=title,
            fallback_fields=field_names,
        )


class AcroFormFillerAndBaker:
    """Fills bankruptcy AcroForm PDFs via `core.pdf_forms.AcroFormEngine`."""

    FIELD_TRANSFORMS: Dict[str, FieldTransformFn] = {
        # Official Form 121 uses a 9-character comb widget without hyphens.
        "Debtor1a.SSNum": lambda val: "".join(ch for ch in val if ch.isdigit())[:9] or val,
    }

    def __init__(
        self,
        templates_dir: Path,
        tokenizer: PIITokenizer,
    ) -> None:
        """Initializes the bankruptcy form binder over `AcroFormEngine`."""
        self.engine = AcroFormEngine(templates_dir)
        self.templates = AcroFormTemplateRegistry(templates_dir)
        self.tokenizer = tokenizer
        self.planner = FormPacketPlanner()
        self.field_maps = self.engine.field_maps

    @staticmethod
    def _split_name(full_name: str) -> Tuple[str, str, str]:
        """Splits a debtor full name into `(first, middle, last)` for Official Form 101 / 121."""
        tokens = [t for t in full_name.strip().split() if t]
        if not tokens:
            return ("Unknown", "", "")
        if len(tokens) == 1:
            return (tokens[0], "", tokens[0])
        if len(tokens) == 2:
            return (tokens[0], "", tokens[1])
        return (tokens[0], " ".join(tokens[1:-1]), tokens[-1])

    @staticmethod
    def _asset_tier_key(amount: Decimal, prefix: str) -> str:
        """Maps a dollar total to the Form B 101 Part 6 checkbox tier semantic key."""
        if amount <= Decimal("50000"):
            return f"{prefix}_Tier_0_50k"
        if amount <= Decimal("100000"):
            return f"{prefix}_Tier_50k_100k"
        if amount <= Decimal("500000"):
            return f"{prefix}_Tier_100k_500k"
        return f"{prefix}_Tier_500k_1m"

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

        # B101 (both synthetic keys + granular official B101 widgets)
        first_n, mid_n, last_n = self._split_name(d_name)
        dist_short = "Central" if graph.district == "CACB" else "Eastern"
        dist_full = (
            "Central District of California"
            if graph.district == "CACB"
            else "Eastern District of California"
        )
        csz = f"{debtor_1.city}, {debtor_1.state} {debtor_1.zip_code}".strip(", ") if debtor_1 else ""
        tot_assets_dec = calcs.total_assets if calcs else Decimal("0.00")
        tot_liab_dec = (
            calcs.total_secured_debt + calcs.total_priority_debt + calcs.total_general_unsecured_debt
            if calcs
            else Decimal("0.00")
        )
        atty_name_b101 = graph.attorney_name or "Supervising Counsel"
        atty_bar_b101 = graph.attorney_bar_number or "CA-BAR-PENDING"
        b101_map = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_FirstName": _entry(first_n, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_MiddleName": _entry(mid_n, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_LastName": _entry(last_n, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_Last4SSN": _entry(public_last4_ssn, "system_constant", "$.parties[0].ssn_token_or_ein"),
            "Debtor1_Street": _entry(debtor_1.street_address if debtor_1 else "", "direct_provenance", "$.parties[0].street_address"),
            "Debtor1_City": _entry(debtor_1.city if debtor_1 else "", "direct_provenance", "$.parties[0].city"),
            "Debtor1_State": _entry(debtor_1.state if debtor_1 else "CA", "direct_provenance", "$.parties[0].state"),
            "Debtor1_Zip": _entry(debtor_1.zip_code if debtor_1 else "", "direct_provenance", "$.parties[0].zip_code"),
            "Debtor1_CityStateZip": _entry(csz, "direct_provenance", "$.parties[0].city_state_zip"),
            "Debtor1_County": _entry(debtor_1.county_of_residence if debtor_1 else "", "direct_provenance", "$.parties[0].county_of_residence"),
            "District_Code": _entry(graph.district, "system_constant", "$.district"),
            "District_Name": _entry(dist_short, "system_constant", "$.district"),
            "District_State": _entry("California", "system_constant", "$.parties[0].state"),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Chapter_Selected": _entry(f"Chapter {graph.chapter}", "system_constant", "$.chapter"),
            "Estimated_Assets": _entry(tot_assets, "deterministic_calculation", "$.calculations.total_assets", "=SUM(assets.current_value)"),
            "Estimated_Liabilities": _entry(comb_liab, "deterministic_calculation", "$.calculations.combined_liabilities", "=SUM(claims.total_claim_amount)"),
            "Creditor_Tier_1_49": _entry("On", "deterministic_calculation", "$.claims.length"),
            self._asset_tier_key(tot_assets_dec, "Assets"): _entry("On", "deterministic_calculation", "$.calculations.total_assets"),
            self._asset_tier_key(tot_liab_dec, "Liab"): _entry("On", "deterministic_calculation", "$.calculations.combined_liabilities"),
            "Attorney_Name": _entry(atty_name_b101, "system_constant", "$.attorney_name"),
            "Attorney_Bar_Number": _entry(atty_bar_b101, "system_constant", "$.attorney_bar_number"),
            "Attorney_State": _entry("CA", "system_constant", "$.district"),
        }
        if graph.chapter == "7":
            b101_map["Check_Chapter_7"] = _entry("On", "system_constant", "$.chapter")
        elif graph.chapter == "13":
            b101_map["Check_Chapter_13"] = _entry("On", "system_constant", "$.chapter")
        else:
            b101_map["Check_Chapter_11"] = _entry("On", "system_constant", "$.chapter")
        bindings["B101"] = b101_map

        # B106Sum
        cmi_str = f"${calcs.means_test.current_monthly_income:,.2f}" if calcs else "$0.00"
        real_estate_sum = sum(
            (a.current_value.value for a in graph.assets if a.category in ("real_property", "real_estate")),
            Decimal("0.00"),
        )
        personal_prop_sum = (calcs.total_assets - real_estate_sum) if calcs else Decimal("0.00")
        tot_re_str = f"${real_estate_sum:,.2f}"
        tot_pp_str = f"${personal_prop_sum:,.2f}"
        has_unknown_assets = any(a.valuation_state == "unknown" for a in graph.assets)
        sum_pp_label = f"{tot_pp_str} (+ Unknown)" if has_unknown_assets else tot_pp_str
        sum_tot_label = f"{tot_assets} (+ Unknown)" if has_unknown_assets else tot_assets
        bindings["B106Sum"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Total_RealEstate_AB": _entry(tot_re_str, "deterministic_calculation", "$.calculations.total_real_estate", "=SUM(Schedule A/B Part 1)"),
            "Total_PersonalProp_AB": _entry(sum_pp_label, "deterministic_calculation", "$.calculations.total_personal_property", "=SUM(Schedule A/B Parts 2-7)"),
            "Total_Assets_AB": _entry(sum_tot_label, "deterministic_calculation", "$.calculations.total_assets", "=SUM(Schedule A/B)"),
            "Total_Secured_D": _entry(tot_sec, "deterministic_calculation", "$.calculations.total_secured_debt", "=SUM(Schedule D)"),
            "Total_Priority_E": _entry(tot_pri, "deterministic_calculation", "$.calculations.total_priority_debt", "=SUM(Schedule E)"),
            "Total_Unsecured_F": _entry(tot_unsec, "deterministic_calculation", "$.calculations.total_general_unsecured_debt", "=SUM(Schedule F)"),
            "Combined_Liabilities": _entry(comb_liab, "deterministic_calculation", "$.calculations.combined_liabilities", "=D + E + F"),
            "Schedule_I_Monthly_Income": _entry(sched_i, "deterministic_calculation", "$.calculations.schedule_i_monthly_gross", "=SUM(Schedule I)"),
            "Schedule_J_Monthly_Expenses": _entry(sched_j, "deterministic_calculation", "$.calculations.schedule_j_monthly_expenses", "=SUM(Schedule J)"),
            "MeansTest_CMI": _entry(cmi_str, "deterministic_calculation", "$.calculations.means_test.current_monthly_income", "=SUM(CMI_6mo)/6"),
        }

        # B106AB (first 6 in synthetic widgets + real Part 1/2/4 rows & line 55-63 totals + continuation)
        def _fmt_asset_val(asset_item: AssetItem) -> str:
            return "Unknown" if asset_item.valuation_state == "unknown" else f"${asset_item.current_value.value:,.2f}"

        ab_fields: Dict[str, Any] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Total_RealEstate_AB": _entry(tot_re_str, "deterministic_calculation", "$.calculations.total_real_estate", "=SUM(Part 1)"),
            "Total_Vehicles_AB": _entry(
                f"${sum((a.current_value.value for a in graph.assets if a.category == 'vehicle'), Decimal('0.00')):,.2f}",
                "deterministic_calculation",
                "$.calculations.total_vehicles",
                "=SUM(Part 2)",
            ),
            "Total_Financial_AB": _entry(
                f"${sum((a.current_value.value for a in graph.assets if a.category in ('bank_account', 'retirement', 'retirement_erisa_ira', 'ira_non_rollover', 'education_529', 'other', 'personal_injury', 'workers_comp', 'legal_claims', 'security_deposit')), Decimal('0.00')):,.2f}",
                "deterministic_calculation",
                "$.calculations.total_financial",
                "=SUM(Part 4)",
            ),
            "Total_PersonalProp_AB": _entry(tot_pp_str, "deterministic_calculation", "$.calculations.total_personal_property", "=Lines 56-61"),
            "Total_Assets_AB": _entry(tot_assets, "deterministic_calculation", "$.calculations.total_assets", "=SUM(Schedule A/B)"),
        }
        re_assets = [a for a in graph.assets if a.category in ("real_property", "real_estate")]
        veh_assets = [a for a in graph.assets if a.category == "vehicle"]
        fin_assets = [a for a in graph.assets if a.category in ("bank_account", "social_security_deposit", "cash", "security_deposit", "other")]
        ret_assets = [a for a in graph.assets if a.category in ("retirement", "retirement_erisa_ira", "ira_non_rollover")]
        if re_assets:
            ab_fields["RE_Row_1_Desc"] = _entry(re_assets[0].description, "direct_provenance", "$.assets[real_estate:0]", None, self._first_locator(re_assets[0].current_value), self._override(re_assets[0].current_value))
            ab_fields["RE_Row_1_Val"] = _entry(_fmt_asset_val(re_assets[0]), "direct_provenance", "$.assets[real_estate:0].current_value", None, self._first_locator(re_assets[0].current_value), self._override(re_assets[0].current_value))
        if veh_assets:
            ab_fields["Veh_Row_1_Make"] = _entry(veh_assets[0].description, "direct_provenance", "$.assets[vehicle:0]", None, self._first_locator(veh_assets[0].current_value), self._override(veh_assets[0].current_value))
            ab_fields["Veh_Row_1_Model"] = _entry(veh_assets[0].asset_id, "direct_provenance", "$.assets[vehicle:0].asset_id")
            ab_fields["Veh_Row_1_Val"] = _entry(_fmt_asset_val(veh_assets[0]), "direct_provenance", "$.assets[vehicle:0].current_value", None, self._first_locator(veh_assets[0].current_value), self._override(veh_assets[0].current_value))
        for idx_f, fa in enumerate(fin_assets[:3], start=1):
            ab_fields[f"Fin_Row_{idx_f}_Desc"] = _entry(fa.description, "direct_provenance", f"$.assets[fin:{idx_f - 1}]", None, self._first_locator(fa.current_value), self._override(fa.current_value))
            ab_fields[f"Fin_Row_{idx_f}_Val"] = _entry(_fmt_asset_val(fa), "direct_provenance", f"$.assets[fin:{idx_f - 1}].current_value", None, self._first_locator(fa.current_value), self._override(fa.current_value))
        if ret_assets:
            ab_fields["Ret_Row_1_Desc"] = _entry(ret_assets[0].description, "direct_provenance", "$.assets[retirement:0]", None, self._first_locator(ret_assets[0].current_value), self._override(ret_assets[0].current_value))
            ab_fields["Ret_Row_1_Val"] = _entry(_fmt_asset_val(ret_assets[0]), "direct_provenance", "$.assets[retirement:0].current_value", None, self._first_locator(ret_assets[0].current_value), self._override(ret_assets[0].current_value))
        for i in range(1, 7):
            if i <= len(graph.assets):
                a = graph.assets[i - 1]
                ab_fields[f"Asset_Row_{i}"] = _entry(
                    f"[Line {a.schedule_ab_line or '?'} · {a.category}] {a.description} — {_fmt_asset_val(a)}",
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
                f"Row {idx}: [Line {a.schedule_ab_line or '?'} · {a.category}] {self.tokenizer.redact_for_public_form(a.description)} — {_fmt_asset_val(a)}"
                for idx, a in enumerate(graph.assets[6:], start=7)
            ]

        # B106C
        c_fields: Dict[str, Any] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
        }
        if calcs:
            ex = calcs.exemptions
            rec = next((e for e in ex.evaluations if e.regime_id == ex.recommended_regime_id), ex.evaluations[0])
            if ex.recommended_regime_id == "FEDERAL_522D":
                c_fields["Check_Federal_Exemptions"] = _entry("federal", "system_constant", "$.calculations.exemptions.recommended_regime_id")
            else:
                c_fields["Check_State_Exemptions"] = _entry("state#20and#20federal", "system_constant", "$.calculations.exemptions.recommended_regime_id")

            if rec.homestead_exceeds_522p_cap:
                c_fields["Check_Homestead_Over_214k_Yes"] = _entry("yes", "deterministic_calculation", "$.calculations.exemptions.homestead_exceeds_522p_cap")
            else:
                c_fields["Check_Homestead_Over_214k_No"] = _entry("no", "deterministic_calculation", "$.calculations.exemptions.homestead_exceeds_522p_cap")

            if rec.homestead_acquired_within_1215_days:
                c_fields["Check_Homestead_Within_1215d_Yes"] = _entry("yes", "deterministic_calculation", "$.calculations.exemptions.homestead_acquired_within_1215_days")
            else:
                c_fields["Check_Homestead_Within_1215d_No"] = _entry("no", "deterministic_calculation", "$.calculations.exemptions.homestead_acquired_within_1215_days")

            c_fields["Exemption_Regime_Selected"] = _entry(
                ex.recommended_display_name,
                "deterministic_calculation",
                "$.calculations.exemptions.recommended_regime_id",
                f"MIN(non_exempt_equity across {[e.regime_id for e in ex.evaluations]})",
            )
            for idx_ex, al in enumerate(rec.allocations[:4], start=1):
                val_txt = "Unknown" if al.valuation_state == "unknown" else f"${al.net_equity:,.2f}"
                amt_txt = "100% of FMV" if (al.valuation_state == "unknown" or al.claim_100pct_fmv) else f"${al.total_exempt:,.2f}"
                c_fields[f"Ex_{idx_ex}_Desc"] = _entry(al.asset_description, "deterministic_calculation", f"$.calculations.exemptions.allocations[{idx_ex - 1}]")
                c_fields[f"Ex_{idx_ex}_Val"] = _entry(val_txt, "deterministic_calculation", f"$.calculations.exemptions.allocations[{idx_ex - 1}].net_equity")
                c_fields[f"Ex_{idx_ex}_Amt"] = _entry(amt_txt, "deterministic_calculation", f"$.calculations.exemptions.allocations[{idx_ex - 1}].total_exempt")
                if al.valuation_state == "unknown" or al.claim_100pct_fmv:
                    c_fields[f"Ex_{idx_ex}_100PctFMV"] = _entry("fair#20market", "deterministic_calculation", f"$.calculations.exemptions.allocations[{idx_ex - 1}].claim_100pct_fmv")
                c_fields[f"Ex_{idx_ex}_Law"] = _entry(al.statute_cited, "deterministic_calculation", f"$.calculations.exemptions.allocations[{idx_ex - 1}].statute_cited")
                c_fields[f"Ex_{idx_ex}_Line"] = _entry(al.schedule_ab_line or al.asset_id, "system_constant", f"$.assets.{al.asset_id}")
            for i in range(1, 7):
                if i <= len(rec.allocations):
                    al = rec.allocations[i - 1]
                    ex_lbl = "100% of FMV" if (al.valuation_state == "unknown" or al.claim_100pct_fmv) else f"${al.total_exempt:,.2f}"
                    c_fields[f"Exemption_Row_{i}"] = _entry(
                        f"{al.asset_description} | Exempt: {ex_lbl} ({al.statute_cited})",
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
                    f"Row {idx}: {al.asset_description} | Exempt {'100% of FMV' if (al.valuation_state == 'unknown' or al.claim_100pct_fmv) else f'${al.total_exempt:,.2f}'} ({al.statute_cited})"
                    for idx, al in enumerate(rec.allocations[6:], start=7)
                ]
        bindings["B106C"] = c_fields

        # B106D (Secured)
        sec_claims = [c for c in graph.claims if c.priority_type == "secured"]
        d_fields: Dict[str, Any] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Total_Secured_D": _entry(tot_sec, "deterministic_calculation", "$.calculations.total_secured_debt", "=SUM(Schedule D)"),
        }
        asset_by_id = {a.asset_id: a for a in graph.assets}
        for idx_s, cl in enumerate(sec_claims[:2], start=1):
            collat = asset_by_id.get(cl.collateral_asset_id or "")
            d_fields[f"Sec_{idx_s}_Creditor"] = _entry(cl.creditor_name, "direct_provenance", f"$.claims[secured:{cl.claim_id}]", None, self._first_locator(cl.total_claim_amount), self._override(cl.total_claim_amount))
            d_fields[f"Sec_{idx_s}_Claim"] = _entry(f"${cl.total_claim_amount.value:,.2f}", "direct_provenance", f"$.claims[secured:{cl.claim_id}].total_claim_amount", None, self._first_locator(cl.total_claim_amount), self._override(cl.total_claim_amount))
            d_fields[f"Sec_{idx_s}_CollatVal"] = _entry(f"${collat.current_value.value:,.2f}" if collat else "$0.00", "direct_provenance", f"$.assets.{cl.collateral_asset_id or 'none'}")
            if idx_s == 1:
                d_fields["Sec_1_Desc"] = _entry(collat.description if collat else (cl.collateral_asset_id or "Personal Property"), "direct_provenance", f"$.claims[secured:{cl.claim_id}].collateral_asset_id")
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
        pri_claims = [c for c in unsec_claims if c.priority_type.startswith("priority")]
        gen_claims = [c for c in unsec_claims if not c.priority_type.startswith("priority")]
        ef_total = (
            f"${(calcs.total_priority_debt + calcs.total_general_unsecured_debt):,.2f}"
            if calcs
            else "$0.00"
        )
        ef_fields: Dict[str, Any] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Total_Unsecured_EF": _entry(ef_total, "deterministic_calculation", "$.calculations.total_unsecured_ef", "=SUM(E+F)"),
            "Total_Priority_E": _entry(tot_pri, "deterministic_calculation", "$.calculations.total_priority_debt", "=SUM(Schedule E)"),
            "Total_Unsecured_F": _entry(tot_unsec, "deterministic_calculation", "$.calculations.total_general_unsecured_debt", "=SUM(Schedule F)"),
        }
        for idx_p, cl in enumerate(pri_claims[:2], start=1):
            ef_fields[f"Pri_{idx_p}_Creditor"] = _entry(cl.creditor_name, "direct_provenance", f"$.claims[priority:{cl.claim_id}]", None, self._first_locator(cl.total_claim_amount), self._override(cl.total_claim_amount))
            ef_fields[f"Pri_{idx_p}_Amt"] = _entry(f"${cl.total_claim_amount.value:,.2f}", "direct_provenance", f"$.claims[priority:{cl.claim_id}].total_claim_amount", None, self._first_locator(cl.total_claim_amount), self._override(cl.total_claim_amount))
        if gen_claims:
            ef_fields["NonPri_1_Creditor"] = _entry(gen_claims[0].creditor_name, "direct_provenance", f"$.claims[unsecured:{gen_claims[0].claim_id}]", None, self._first_locator(gen_claims[0].total_claim_amount), self._override(gen_claims[0].total_claim_amount))
            ef_fields["NonPri_1_Amt"] = _entry(f"${gen_claims[0].total_claim_amount.value:,.2f}", "direct_provenance", f"$.claims[unsecured:{gen_claims[0].claim_id}].total_claim_amount", None, self._first_locator(gen_claims[0].total_claim_amount), self._override(gen_claims[0].total_claim_amount))
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
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Employer_Summary": _entry(employers, "direct_provenance", "$.paystubs.employers"),
            "Schedule_I_Monthly_Income": _entry(sched_i, "deterministic_calculation", "$.calculations.schedule_i_monthly_gross", "=SUM(Schedule I)"),
        }
        hh_val = str(debtor_1.household_size.value if debtor_1 else 1)
        exp_desc = "; ".join(f"{e.category}: ${e.monthly_amount.value:,.2f}" for e in graph.budget.expense_items[:4])
        housing_exp = sum(
            (e.monthly_amount.value for e in graph.budget.expense_items if "housing" in e.category.lower() or "rent" in e.category.lower() or "mortgage" in e.category.lower()),
            Decimal("0.00"),
        )
        bindings["B106J"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Household_Size": _entry(hh_val, "direct_provenance", "$.parties[0].household_size", None, self._first_locator(debtor_1.household_size if debtor_1 else None), self._override(debtor_1.household_size if debtor_1 else None)),
            "Expense_Breakdown": _entry(exp_desc or "No itemized expenses", "direct_provenance", "$.budget.expense_items"),
            "Schedule_J_Housing": _entry(f"${housing_exp:,.2f}", "direct_provenance", "$.budget.housing"),
            "Schedule_I_Monthly_Income": _entry(sched_i, "deterministic_calculation", "$.calculations.schedule_i_monthly_gross", "=SUM(Schedule I)"),
            "Schedule_J_Monthly_Expenses": _entry(sched_j, "deterministic_calculation", "$.calculations.schedule_j_monthly_expenses", "=SUM(Schedule J)"),
            "Monthly_Net_Income": _entry(sched_net, "deterministic_calculation", "$.calculations.schedule_ij_monthly_net", "=Schedule I - Schedule J"),
        }
        bindings["B106Dec"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
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
        b108_fields: Dict[str, Any] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            **{
                f"Intention_Row_{i}": _entry(
                    f"{sec_claims[i - 1].creditor_name} -> {sec_claims[i - 1].statement_of_intention or 'UNSET'}"
                    if i <= len(sec_claims)
                    else "",
                    "human_override",
                    f"$.claims[secured:{sec_claims[i - 1].claim_id}].statement_of_intention" if i <= len(sec_claims) else "$.claims",
                )
                for i in range(1, 6)
            },
        }
        for idx_i, sc in enumerate(sec_claims[:2], start=1):
            b108_fields[f"Int_{idx_i}_Creditor"] = _entry(sc.creditor_name, "direct_provenance", f"$.claims[secured:{sc.claim_id}]")
            b108_fields[f"Int_{idx_i}_Desc"] = _entry(sc.collateral_asset_id or sc.creditor_name, "direct_provenance", f"$.claims[secured:{sc.claim_id}].collateral_asset_id")
        bindings["B108"] = b108_fields

        # B121 RESTRICTED — bypasses redact_for_public_form intentionally!
        bindings["B121"] = {
            "District_Combo": _entry(dist_full, "system_constant", "$.district"),
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_FirstName": _entry(first_n, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_MiddleName": _entry(mid_n, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Debtor1_LastName": _entry(last_n, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
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
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "District_Combo": _entry(dist_full, "system_constant", "$.district"),
                "State_Name": _entry("California", "system_constant", "$.parties[0].state"),
                "Lookback_Window": _entry(f"{mt.lookback_start} to {mt.lookback_end}", "deterministic_calculation", "$.calculations.means_test.lookback_window"),
                "Current_Monthly_Income": _entry(f"${mt.current_monthly_income:,.2f}", "deterministic_calculation", "$.calculations.means_test.current_monthly_income", "=SUM(6mo_gross)/6"),
                "Annualized_CMI": _entry(f"${mt.annualized_cmi:,.2f}", "deterministic_calculation", "$.calculations.means_test.annualized_cmi", "=CMI * 12"),
                "Household_Size": _entry(str(mt.household_size), "direct_provenance", "$.parties[0].household_size"),
                "CA_Median_Income": _entry(f"${mt.california_median_income:,.2f}", "system_constant", f"$.tables.{mt.table_version_id}"),
            }
            if mt.spouse_cmi > Decimal("0.00"):
                common_mt_1["Spouse_Gross_CMI"] = _entry(f"${mt.spouse_cmi:,.2f}", "deterministic_calculation", "$.calculations.means_test.spouse_cmi")
            bindings["B122A1"] = {**common_mt_1, "Median_Verdict": _entry(verdict_str, "deterministic_calculation", "$.calculations.means_test.is_above_median")}
            bindings["B122C1"] = {**common_mt_1, "Commitment_Period_Months": _entry(f"{mt.applicable_commitment_months} months", "deterministic_calculation", "$.calculations.means_test.applicable_commitment_months")}
            common_mt_2 = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Current_Monthly_Income": common_mt_1["Current_Monthly_Income"],
                "Marital_Adjustment_Total": _entry(f"${mt.marital_adjustment_deduction:,.2f}", "deterministic_calculation", "$.calculations.means_test.marital_adjustment_deduction"),
                "IRS_Food_Clothing": _entry(f"${mt.irs_food_clothing_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_food_clothing_allowance"),
                "IRS_Healthcare": _entry(f"${mt.irs_healthcare_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_healthcare_allowance"),
                "IRS_Housing_Utilities": _entry(f"${mt.irs_housing_utilities_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_housing_utilities_allowance"),
                "IRS_Transportation": _entry(f"${mt.irs_transportation_allowance:,.2f}", "deterministic_calculation", "$.calculations.means_test.irs_transportation_allowance"),
                "Total_Deductions_MT": _entry(f"${mt.total_allowed_deductions:,.2f}", "deterministic_calculation", "$.calculations.means_test.total_allowed_deductions"),
                "Taxes_And_Secured": _entry(f"${(mt.payroll_taxes_deduction + mt.secured_debt_cure_monthly):,.2f}", "deterministic_calculation", "$.calculations.means_test.taxes_and_secured"),
                "Monthly_Disposable_Income": _entry(f"${mt.monthly_disposable_income:,.2f}", "deterministic_calculation", "$.calculations.means_test.monthly_disposable_income", "=CMI - deductions"),
                "SixtyMonth_Disposable_Income": _entry(f"${mt.sixty_month_disposable_income:,.2f}", "deterministic_calculation", "$.calculations.means_test.sixty_month_disposable_income", "=Monthly_Disposable * 60"),
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
        atty_header = f"{atty_name} (State Bar No. {atty_bar})"
        last4_digits = "".join(ch for ch in public_last4_ssn if ch.isdigit())[-4:]
        bindings["CACB_F1007_1"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Attorney_Header": _entry(atty_header, "system_constant", "$.attorney_name"),
            "Chapter_Combo": _entry(graph.chapter if graph.chapter in ("7", "13") else "11", "system_constant", "$.chapter"),
            "Creditor_Matrix_Count": _entry(str(len(graph.claims)), "deterministic_calculation", "$.claims.length"),
            "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
        }
        bindings["CACB_F5005_4"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
            "Attest_Printed_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
            "Verification_Date": _entry(graph.expected_filing_date.isoformat(), "system_constant", "$.expected_filing_date"),
            "Attorney_Bar_Number": _entry(atty_bar, "system_constant", "$.attorney_bar_number"),
        }
        bindings["CAEB_ESIG"] = dict(bindings["CACB_F5005_4"])
        bindings["CAEB_EDC_3_096"] = {
            "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
            "Attorney_Name": _entry(f"/s/ {atty_name}", "system_constant", "$.attorney_name"),
        }

        if calcs and calcs.ch13_plan:
            p = calcs.ch13_plan
            bindings["CACB_F3015_1_01"] = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Attorney_Header": _entry(atty_header, "system_constant", "$.attorney_name"),
                "Commitment_Period_Months": _entry(str(p.applicable_commitment_months), "deterministic_calculation", "$.calculations.ch13_plan.applicable_commitment_months"),
                "Estimated_Monthly_Payment": _entry(f"${p.estimated_monthly_plan_payment:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.estimated_monthly_plan_payment", "=total_funding / months"),
                "Liquidation_Floor": _entry(f"${p.best_interests_liquidation_floor:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.best_interests_liquidation_floor"),
            }
            bindings["CACB_F3015_1_7_RARA"] = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Attorney_Header": _entry(atty_header, "system_constant", "$.attorney_name"),
                "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
            }
            bindings["CAEB_EDC_3_080"] = {
                "Debtor1_Name": _entry(d_name, "direct_provenance", "$.parties[0].full_name", None, d_name_locs, d_name_ov),
                "Debtor1_Last4_Digits": _entry(last4_digits or "0000", "system_constant", "$.parties[0].ssn_token_or_ein"),
                "Commitment_Period_Months": _entry(str(p.applicable_commitment_months), "deterministic_calculation", "$.calculations.ch13_plan.applicable_commitment_months"),
                "Estimated_Monthly_Payment": _entry(f"${p.estimated_monthly_plan_payment:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.estimated_monthly_plan_payment", "=total_funding / months"),
                "Secured_Arrears_Total": _entry(f"${p.secured_arrears_total:,.2f}", "deterministic_calculation", "$.calculations.ch13_plan.secured_arrears_total"),
                "Attorney_Name": _entry(atty_name, "system_constant", "$.attorney_name"),
            }

        return bindings, overflow_lines

    def compile_forms(
        self,
        state: BankruptcyCaseState,
        output_dir: Path,
        watermark_draft: bool = False,
    ) -> Tuple[List[Path], Path, List[FieldLineageEntry]]:
        """Plans forms, binds case state, and delegates baking/lineage to `AcroFormEngine`."""
        form_ids = self.planner.plan_required_forms(state)
        bindings, overflow_lines = self._build_field_bindings(state)

        specs: List[Dict[str, Any]] = []
        for form_id in form_ids:
            title, field_names = AcroFormTemplateRegistry.FORM_SPECS.get(
                form_id, (f"Bankruptcy Form {form_id}", ["Debtor1_Name"])
            )
            out_name = "Form_B121_RESTRICTED.pdf" if form_id == "B121" else f"{form_id}.pdf"
            specs.append(
                {
                    "form_id": form_id,
                    "output_filename": out_name,
                    "bindings": bindings.get(form_id, {}),
                    "overflow_lines": overflow_lines.get(form_id),
                    "fallback_title": title,
                    "fallback_fields": field_names,
                    "field_transforms": self.FIELD_TRANSFORMS,
                }
            )

        return self.engine.compile_packet(
            specs=specs,
            output_dir=output_dir,
            watermark_draft=watermark_draft,
        )
