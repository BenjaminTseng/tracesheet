"""Deterministic 6-month Current Monthly Income (CMI) & Form 122A/122C Means Test calculator."""

from __future__ import annotations

import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple

from app.bankruptcy.models import CanonicalCaseGraph, MeansTestResult
from app.core.tables import StatutoryTableRegistry


def compute_six_month_lookback_window(
    filing_date: datetime.date,
) -> Tuple[datetime.date, datetime.date, List[str]]:
    """Computes the exact 6 full calendar months prior to `filing_date` (11 U.S.C. § 101(10A)).

    For example, a petition filed on `2026-11-16` inspects `2026-05-01` through `2026-10-31`.

    Args:
        filing_date: Expected or actual petition filing date.

    Returns:
        Tuple of `(lookback_start, lookback_end, list_of_YYYY_MM_labels)`.
    """
    end_year = filing_date.year
    end_month = filing_date.month - 1
    if end_month == 0:
        end_month = 12
        end_year -= 1
    last_day = calendar.monthrange(end_year, end_month)[1]
    lookback_end = datetime.date(end_year, end_month, last_day)

    months: List[str] = []
    cur_y, cur_m = end_year, end_month
    for _ in range(6):
        months.append(f"{cur_y:04d}-{cur_m:02d}")
        cur_m -= 1
        if cur_m == 0:
            cur_m = 12
            cur_y -= 1
    months.reverse()

    start_y, start_m = map(int, months[0].split("-"))
    lookback_start = datetime.date(start_y, start_m, 1)
    return lookback_start, lookback_end, months


class CMIAndMeansTestEngine:
    """Calculates 6-Month CMI, Median Comparison, and IRS Means Test deductions (`122A/122C`)."""

    def __init__(self, registry: StatutoryTableRegistry) -> None:
        """Initializes the Means Test engine.

        Args:
            registry: Effective-dated `StatutoryTableRegistry`.
        """
        self.registry = registry

    @staticmethod
    def _lookup_bracket_value(table: Dict[str, str], household_size: int, max_key: str = "5_plus") -> Decimal:
        """Looks up a household-size keyed allowance, clamping or extrapolating above 4."""
        if str(household_size) in table:
            return Decimal(table[str(household_size)])
        if max_key in table and household_size >= 5:
            return Decimal(table[max_key])
        if "4" in table and "additional_person_annual" in table:
            extra = max(0, household_size - 4)
            return Decimal(table["4"]) + Decimal(table["additional_person_annual"]) * extra
        if "4" in table and "additional_person_monthly" in table:
            extra = max(0, household_size - 4)
            return Decimal(table["4"]) + Decimal(table["additional_person_monthly"]) * extra
        return Decimal(table["1"])

    def evaluate(self, graph: CanonicalCaseGraph) -> MeansTestResult:
        """Evaluates Form 122A-1/2 or 122C-1/2 over `graph`.

        Args:
            graph: Case graph with debtor demographics, paystubs, vehicles, and secured claims.

        Returns:
            Deterministic `MeansTestResult` anchored to USTP & § 707(b) table checksums.
        """
        ustp = self.registry.get_ustp_ca_means_test(graph.expected_filing_date)
        fed = self.registry.get_federal_thresholds(graph.expected_filing_date)

        lookback_start, lookback_end, lookback_months = compute_six_month_lookback_window(
            graph.expected_filing_date
        )

        # Sum only verified/present paystubs strictly inside the 6 full calendar months.
        six_mo_gross = Decimal("0.00")
        six_mo_taxes = Decimal("0.00")
        for ps in graph.paystubs:
            if lookback_start <= ps.pay_date <= lookback_end:
                six_mo_gross += ps.gross_pay.value
                six_mo_taxes += ps.tax_withheld.value

        six_mo_gross = six_mo_gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cmi = (six_mo_gross / Decimal("6")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        annualized_cmi = (cmi * Decimal("12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        household_size = debtor_1.household_size.value if debtor_1 else 1
        household_size = max(1, household_size)
        county = debtor_1.county_of_residence if debtor_1 else "Los Angeles"

        ca_median = self._lookup_bracket_value(
            ustp["california_median_annual_income"], household_size
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        is_above_median = annualized_cmi > ca_median
        commitment_months = 60 if is_above_median else 36

        # Compute IRS National & Local Standards deductions (always computed for
        # transparency; formally mandatory when `is_above_median` is True).
        nat = ustp["irs_national_standards"]
        food_clothing = self._lookup_bracket_value(
            nat["food_clothing_other_monthly"], household_size
        )

        # Healthcare allowance per household member using 65+ rate for any party age 65+.
        hc_rates = nat["out_of_pocket_healthcare_per_person_monthly"]
        over_65_count = sum(
            1 for p in graph.parties if p.role in ("debtor_1", "debtor_2_spouse") and p.age_65_or_older
        )
        under_65_count = max(0, household_size - over_65_count)
        healthcare = (
            Decimal(hc_rates["65_and_over"]) * over_65_count
            + Decimal(hc_rates["under_65"]) * under_65_count
        )

        county_map = ustp["ca_county_housing_and_utilities_monthly"]
        county_std = county_map.get(county, county_map["DEFAULT_CA_COUNTY"])
        housing_mortgage = self._lookup_bracket_value(county_std["mortgage_or_rent"], household_size)
        housing_utilities = self._lookup_bracket_value(county_std["utilities"], household_size)
        housing_total = (housing_mortgage + housing_utilities).quantize(Decimal("0.01"))

        # Transportation operating + ownership allowances, excluding surrendered vehicles.
        surrendered_asset_ids = {
            c.collateral_asset_id
            for c in graph.claims
            if c.priority_type == "secured"
            and c.statement_of_intention == "surrender"
            and c.collateral_asset_id
        }
        active_vehicles = [
            a
            for a in graph.assets
            if a.category == "vehicle" and a.asset_id not in surrendered_asset_ids
        ]
        financed_vehicle_ids = {
            c.collateral_asset_id
            for c in graph.claims
            if c.priority_type == "secured"
            and c.statement_of_intention != "surrender"
            and c.collateral_asset_id in {v.asset_id for v in active_vehicles}
        }

        trans_cfg = ustp["irs_local_transportation"]
        op_rates = trans_cfg["west_region_operating_costs_monthly"]
        if len(active_vehicles) == 0:
            op_cost = Decimal(op_rates["0_vehicles"])
        elif len(active_vehicles) == 1:
            op_cost = Decimal(op_rates["1_vehicle"])
        else:
            op_cost = Decimal(op_rates["2_plus_vehicles"])

        max_own = int(trans_cfg["max_vehicles_ownership"])
        own_count = min(max_own, len(financed_vehicle_ids))
        gross_own_cost = Decimal(trans_cfg["national_ownership_cost_per_vehicle_monthly"]) * own_count

        # Form 122A-2 Line 13b: IRS vehicle ownership allowance is reduced by
        # average monthly secured debt payments on the financed vehicle(s) to
        # avoid double-counting against Line 33 secured debt cure.
        vehicle_secured_monthly = Decimal("0.00")
        for claim in graph.claims:
            if (
                claim.priority_type == "secured"
                and claim.statement_of_intention != "surrender"
                and claim.collateral_asset_id in financed_vehicle_ids
            ):
                if claim.monthly_payment is not None:
                    vehicle_secured_monthly += claim.monthly_payment.value
                else:
                    vehicle_secured_monthly += claim.total_claim_amount.value / Decimal("60")
        net_own_cost = max(Decimal("0.00"), gross_own_cost - vehicle_secured_monthly)
        transportation_total = (op_cost + net_own_cost).quantize(Decimal("0.01"))

        avg_monthly_taxes = (six_mo_taxes / Decimal("6")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Secured debt cure (average monthly payment / balance over 60) excluding surrendered collateral.
        secured_monthly = Decimal("0.00")
        for claim in graph.claims:
            if claim.priority_type != "secured":
                continue
            if claim.statement_of_intention == "surrender":
                continue
            if claim.monthly_payment is not None:
                secured_monthly += claim.monthly_payment.value
            else:
                secured_monthly += (claim.total_claim_amount.value / Decimal("60"))
        secured_monthly = secured_monthly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_deductions = (
            food_clothing
            + healthcare
            + housing_total
            + transportation_total
            + avg_monthly_taxes
            + secured_monthly
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        monthly_disposable = max(Decimal("0.00"), cmi - total_deductions).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        sixty_month_disposable = (monthly_disposable * Decimal("60")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        presumption_of_abuse: bool | None = False
        if not is_above_median:
            presumption_of_abuse = False
        elif graph.chapter == "7":
            abuse_cfg = fed["means_test_707b_abuse"]
            floor_amt = Decimal(abuse_cfg["floor_60_month_disposable"])
            ceil_amt = Decimal(abuse_cfg["ceiling_60_month_disposable"])
            pct = Decimal(abuse_cfg["unsecured_debt_pct"])
            unsecured_total = sum(
                (
                    c.total_claim_amount.value
                    for c in graph.claims
                    if c.priority_type == "general_unsecured"
                ),
                Decimal("0.00"),
            )
            if sixty_month_disposable < floor_amt:
                presumption_of_abuse = False
            elif sixty_month_disposable >= ceil_amt:
                presumption_of_abuse = True
            else:
                presumption_of_abuse = sixty_month_disposable >= (unsecured_total * pct)
        else:
            presumption_of_abuse = None

        return MeansTestResult(
            lookback_start=lookback_start,
            lookback_end=lookback_end,
            lookback_months=lookback_months,
            total_6_month_gross_income=six_mo_gross,
            current_monthly_income=cmi,
            annualized_cmi=annualized_cmi,
            household_size=household_size,
            california_median_income=ca_median,
            is_above_median=is_above_median,
            requires_full_means_test=is_above_median,
            irs_food_clothing_allowance=food_clothing.quantize(Decimal("0.01")),
            irs_healthcare_allowance=healthcare.quantize(Decimal("0.01")),
            irs_housing_utilities_allowance=housing_total,
            irs_transportation_allowance=transportation_total,
            payroll_taxes_deduction=avg_monthly_taxes,
            secured_debt_cure_monthly=secured_monthly,
            total_allowed_deductions=total_deductions,
            monthly_disposable_income=monthly_disposable,
            sixty_month_disposable_income=sixty_month_disposable,
            presumption_of_abuse=presumption_of_abuse,
            applicable_commitment_months=commitment_months,
            table_version_id=ustp["version_id"],
            table_sha256=ustp["_table_sha256"],
        )
