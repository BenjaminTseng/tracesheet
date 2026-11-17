"""Generalized Canonical Case Graph and provenance contracts for Bankruptcy v1.

Every substantive field that feeds an official schedule, statutory calculator,
or PDF form is wrapped in `ProvenanceField[T]`, enforcing either verified
cryptographic/coordinate grounding (`SourceLocator`) or an explicit audited
`HumanOverrideRecord`. The entity/claim/cash-flow ontology supports Chapter 7
and Chapter 13 in v1 while remaining natively compatible with Chapter 11 and
Subchapter V (`contingent`, `unliquidated`, `is_insider_or_affiliate`,
`commercial_business_pct`, and `entity_type`).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.models import CompiledBundle, SourceLocator, TensionObject


T = TypeVar("T")

ChapterType = Literal["7", "13", "11_subv"]
DistrictCode = Literal["CACB", "CAEB"]
VerificationStatus = Literal["verified", "human_overridden", "unverified", "contradicted"]


class HumanOverrideRecord(BaseModel):
    """Audited human attestation or override attached to a `ProvenanceField`.

    Attributes:
        actor_name: Full name of the paralegal or supervising attorney.
        actor_role: Role performing the override (`"paralegal"` or `"attorney"`).
        rationale: Substantive explanation justifying the value or confirmation.
        supporting_locator: Optional client source coordinate backing the override.
        overridden_at: ISO-8601 UTC timestamp when recorded.
    """

    actor_name: str = Field(min_length=1)
    actor_role: Literal["paralegal", "attorney"]
    rationale: str = Field(min_length=5)
    supporting_locator: Optional[SourceLocator] = None
    overridden_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class ProvenanceField(BaseModel, Generic[T]):
    """Wraps a typed domain value with mandatory coordinate and audit provenance.

    Attributes:
        value: Typed primitive value (`Decimal`, `str`, `int`, `datetime.date`, etc.).
        verification_status: Current deterministic verification state.
        locators: Non-empty coordinate references for AI-extracted observations.
        verbatim_quotes: Exact source text snippets grounding `value`.
        override: Mandatory audit record whenever `verification_status == "human_overridden"`.
    """

    value: T
    verification_status: VerificationStatus = "unverified"
    locators: List[SourceLocator] = Field(default_factory=list)
    verbatim_quotes: List[str] = Field(default_factory=list)
    override: Optional[HumanOverrideRecord] = None

    @model_validator(mode="after")
    def _enforce_override_invariant(self) -> "ProvenanceField[T]":
        """Ensures `"human_overridden"` fields carry a valid `HumanOverrideRecord`."""
        if self.verification_status == "human_overridden" and self.override is None:
            raise ValueError(
                "ProvenanceField with verification_status='human_overridden' requires a non-null override."
            )
        return self


class PartyEntity(BaseModel):
    """Represents a debtor, spouse, business entity, insider, or codebtor.

    Attributes:
        party_id: Unique entity slug within the case graph.
        role: Relationship role (`debtor_1`, `debtor_2_spouse`, `business_entity`, etc.).
        entity_type: Legal form (`individual`, `llc`, `corporation`, `partnership`).
        full_name: Legal name used on petitions and matrices.
        ssn_token_or_ein: Vaulted `[PII:SSN_...]` token or EIN string.
        street_address: Primary street address line.
        city: Municipality name.
        state: Two-letter state postal abbreviation.
        zip_code: 5- or 9-digit ZIP code.
        county_of_residence: California county name for Means Test & `§ 704.730` lookup.
        prior_state_180_days: Prior domicile state if `< 730` continuous days in current state.
        ca_domicile_days_continuous: Verified continuous days domiciled in current state.
        household_size: Number of persons in the economic household (`Form 122A-1` / `I`).
        age_65_or_older: Whether party is 65+ (drives IRS healthcare standard).
    """

    party_id: str
    role: Literal[
        "debtor_1",
        "debtor_2_spouse",
        "non_filing_spouse",
        "business_entity",
        "insider_affiliate",
        "codebtor",
    ]
    entity_type: Literal["individual", "llc", "corporation", "partnership"] = "individual"
    full_name: ProvenanceField[str]
    ssn_token_or_ein: Optional[str] = None
    street_address: str = ""
    city: str = ""
    state: str = "CA"
    zip_code: str = ""
    county_of_residence: str = "Los Angeles"
    prior_state_180_days: Optional[str] = None
    ca_domicile_days_continuous: ProvenanceField[int]
    household_size: ProvenanceField[int]
    age_65_or_older: bool = False


AssetCategory = Literal[
    "real_property",
    "vehicle",
    "bank_account",
    "retirement",
    "household_goods",
    "tools_of_trade",
    "jewelry",
    "business_interest",
    "receivable",
    "other",
]


class AssetItem(BaseModel):
    """Property item scheduled on Official Form B 106A/B and exempted on Form B 106C.

    Attributes:
        asset_id: Unique asset identifier within the case.
        category: Normalized Schedule A/B asset classification.
        description: Human-readable asset description (address, year/make/model, institution).
        ownership: Ownership attribution (`debtor_1`, `debtor_2`, `community`, `business`).
        joint_with_non_filing: True if co-owned with a non-filing third party (triggers Schedule H).
        account_last4: Trailing 4 digits for financial accounts (FRBP 9037).
        current_value: Verified fair-market value (`Schedule A/B`).
        acquisition_date: Acquisition date for `11 U.S.C. § 522(p)` 1,215-day homestead cap.
        owned_free_and_clear: Explicit confirmation when no lien encumbers real property/vehicle.
        attestation_note: Optional explanatory note for free-and-clear or closed status.
    """

    asset_id: str
    category: AssetCategory
    description: str
    ownership: Literal["debtor_1", "debtor_2", "community", "business"] = "debtor_1"
    joint_with_non_filing: bool = False
    account_last4: Optional[str] = None
    current_value: ProvenanceField[Decimal]
    acquisition_date: Optional[ProvenanceField[datetime.date]] = None
    owned_free_and_clear: Optional[bool] = None
    attestation_note: Optional[str] = None


class ClaimItem(BaseModel):
    """Creditor claim scheduled on Form B 106D (Secured) or B 106E/F (Priority/Unsecured).

    Attributes:
        claim_id: Unique claim identifier within the case.
        creditor_name: Legal creditor name for schedules and creditor matrix.
        creditor_address_lines: Mailing street lines (`<= 40` chars each recommended).
        city: Creditor city.
        state: Two-letter state code.
        zip_code: Creditor ZIP code.
        account_token: Vaulted `[PII:ACCT_..._LAST4_XXXX]` token or masked last-4.
        priority_type: Claim priority classification.
        total_claim_amount: Verified total balance owed as of petition date.
        monthly_payment: Contractual monthly payment (for Schedule J / Form 122A-2 cure).
        arrears_amount: Pre-petition arrears cure amount (for Ch. 13 plan calculation).
        collateral_asset_id: Foreign key to `AssetItem.asset_id` for secured claims.
        statement_of_intention: Ch. 7 Form B 108 intention (`surrender`, `retain_and_redeem`, `retain_and_reaffirm`).
        is_cosigned: True if co-signed with a non-filing codebtor.
        codebtor_name: Name of co-obligor if `is_cosigned` is True.
        contingent: True if liability depends on a future extrinsic event (`§ 109(e)` / `§ 1182` filter).
        unliquidated: True if debt amount is not readily ascertainable (`§ 109(e)` / `§ 1182` filter).
        disputed: True if debtor disputes liability or amount.
        is_insider_or_affiliate: True for insider/affiliate debt excluded under `11 U.S.C. § 1182`.
        commercial_business_pct: Fraction `[0.0, 1.0]` arising from commercial/business activities.
    """

    claim_id: str
    creditor_name: str
    creditor_address_lines: List[str] = Field(default_factory=list)
    city: str = ""
    state: str = ""
    zip_code: str = ""
    account_token: Optional[str] = None
    priority_type: Literal[
        "secured",
        "priority_tax",
        "priority_dso",
        "priority_wages",
        "general_unsecured",
    ]
    total_claim_amount: ProvenanceField[Decimal]
    monthly_payment: Optional[ProvenanceField[Decimal]] = None
    arrears_amount: Optional[ProvenanceField[Decimal]] = None
    collateral_asset_id: Optional[str] = None
    statement_of_intention: Optional[
        Literal["surrender", "retain_and_redeem", "retain_and_reaffirm"]
    ] = None
    is_cosigned: bool = False
    codebtor_name: Optional[str] = None
    contingent: bool = False
    unliquidated: bool = False
    disputed: bool = False
    is_insider_or_affiliate: bool = False
    commercial_business_pct: float = Field(default=0.0, ge=0.0, le=1.0)


class PaystubRecord(BaseModel):
    """Single pay period observation supporting Form 122A-1/C-1 CMI and cross-audits.

    Attributes:
        paystub_id: Unique paystub identifier.
        party_id: Reference to earning `PartyEntity.party_id`.
        employer: Employer legal name.
        pay_period_start: Start date of pay period.
        pay_period_end: End date of pay period.
        pay_date: Actual payment receipt date (governs 6-calendar-month CMI inclusion).
        gross_pay: Verified gross earnings before deductions.
        net_pay: Verified net take-home pay.
        ytd_gross: Optional cumulative year-to-date gross pay for YTD consistency check.
        tax_withheld: Total income/payroll taxes withheld in period.
        retirement_deduction: 401(k)/403(b)/HSA deduction triggering `Schedule A/B` asset check.
        garnishment_or_support_deduction: Wage garnishment or DSO deduction triggering SOFA/E/F check.
        deposit_account_last4: Direct-deposit account last-4 digits if printed on stub.
    """

    paystub_id: str
    party_id: str = "debtor_1"
    employer: str
    pay_period_start: datetime.date
    pay_period_end: datetime.date
    pay_date: datetime.date
    gross_pay: ProvenanceField[Decimal]
    net_pay: ProvenanceField[Decimal]
    ytd_gross: Optional[ProvenanceField[Decimal]] = None
    tax_withheld: ProvenanceField[Decimal]
    retirement_deduction: Optional[ProvenanceField[Decimal]] = None
    garnishment_or_support_deduction: Optional[ProvenanceField[Decimal]] = None
    deposit_account_last4: Optional[str] = None


class BankTransactionItem(BaseModel):
    """Individual flagged bank transaction for quantitative forensic auditing.

    Attributes:
        tx_id: Unique transaction ID.
        tx_date: Posted date.
        direction: `"credit"` (deposit) or `"debit"` (withdrawal/ACH outflow).
        payee_or_memo: Raw payee or memo string (e.g., `"SYNCHRONY BANK ACH"`, `"ZELLE TRANSFER"`).
        amount: Transaction dollar amount (positive `Decimal`).
        category_hint: Optional classifier hint (`"debt_payment"`, `"p2p_transfer"`, `"account_transfer"`, `"other"`).
        target_account_last4: Trailing 4 digits if transaction transfers to another account.
        locator: Exact coordinate locator on the bank statement PDF.
    """

    tx_id: str
    tx_date: datetime.date
    direction: Literal["credit", "debit"]
    payee_or_memo: str
    amount: Decimal
    category_hint: Literal["debt_payment", "p2p_transfer", "account_transfer", "other"] = "other"
    target_account_last4: Optional[str] = None
    locator: Optional[SourceLocator] = None


class BankStatementPeriod(BaseModel):
    """Monthly statement summary for a bank/depository account.

    Attributes:
        statement_id: Unique statement period ID.
        institution: Bank or credit union name.
        account_last4: Trailing 4 digits of account number.
        period_start: Statement cycle start date.
        period_end: Statement cycle end date.
        beginning_balance: Opening statement balance.
        ending_balance: Verified closing statement balance.
        total_deposits: Verified sum of credits/deposits.
        payroll_deposits: Portion of deposits attributable to disclosed payroll.
        total_withdrawals: Verified sum of debits/withdrawals.
        flagged_transactions: Non-payroll deposits, recurring debt outflows, and transfers.
    """

    statement_id: str
    institution: str
    account_last4: str
    period_start: datetime.date
    period_end: datetime.date
    beginning_balance: ProvenanceField[Decimal]
    ending_balance: ProvenanceField[Decimal]
    total_deposits: ProvenanceField[Decimal]
    payroll_deposits: ProvenanceField[Decimal]
    total_withdrawals: Optional[ProvenanceField[Decimal]] = None
    flagged_transactions: List[BankTransactionItem] = Field(default_factory=list)


class TaxReturnSummary(BaseModel):
    """Extracted Form 1040 summary used for SOFA, Means Test household checks, and missing-asset audits.

    Attributes:
        tax_year: Calendar tax year (e.g., `2025`).
        filing_status: IRS filing status.
        dependents_count: Verified number of dependents claimed on return.
        agi: Verified Adjusted Gross Income (`Form 1040 Line 11`).
        total_tax: Verified total tax liability (`Form 1040 Line 24`).
        refund_or_balance_due: Positive for refund owed, negative for tax due.
        schedule_b_institutions: Financial institutions reporting interest/dividends on Schedule B.
        has_schedule_c_e_or_k1: True if return reports self-employment, rental, or entity income.
    """

    tax_year: int
    filing_status: Literal["single", "mfj", "mfs", "hoh", "qw"] = "single"
    dependents_count: ProvenanceField[int]
    agi: ProvenanceField[Decimal]
    total_tax: ProvenanceField[Decimal]
    refund_or_balance_due: Optional[ProvenanceField[Decimal]] = None
    schedule_b_institutions: List[str] = Field(default_factory=list)
    has_schedule_c_e_or_k1: bool = False


class BudgetLineItem(BaseModel):
    """Single monthly income or living expense row on Schedule I or Schedule J."""

    item_id: str
    category: Literal[
        "gross_wages",
        "payroll_taxes",
        "business_income",
        "rent_or_mortgage",
        "property_tax_insurance",
        "utilities",
        "food_and_housekeeping",
        "clothing_laundry",
        "medical_dental",
        "transportation_fuel_insurance",
        "vehicle_payment",
        "childcare_education",
        "dso_support",
        "other",
    ]
    description: str
    monthly_amount: ProvenanceField[Decimal]


class MonthlyBudgetScheduleIJ(BaseModel):
    """Current monthly income (Schedule I) and living expenses (Schedule J)."""

    income_items: List[BudgetLineItem] = Field(default_factory=list)
    expense_items: List[BudgetLineItem] = Field(default_factory=list)
    dependents_count: Optional[ProvenanceField[int]] = None


class ExecutoryContractItem(BaseModel):
    """Executory contract or unexpired lease scheduled on Form B 106G."""

    contract_id: str
    counterparty: str
    description: str
    contract_type: Literal["residential_lease", "vehicle_lease", "service_contract", "other"]
    intend_to_assume: bool = True


class CodebtorItem(BaseModel):
    """Codebtor scheduled on Form B 106H."""

    codebtor_id: str
    name: str
    address: str
    linked_claim_id: Optional[str] = None
    linked_asset_id: Optional[str] = None


class HistoricalTransaction(BaseModel):
    """Historical financial disclosure scheduled on Form B 107 (SOFA)."""

    tx_id: str
    sofa_part: Literal["income_history", "preferential_transfer", "lawsuit_garnishment", "closed_account", "business_interest"]
    description: str
    tx_date: Optional[datetime.date] = None
    amount: Optional[ProvenanceField[Decimal]] = None


class EmergingQuestionItem(BaseModel):
    """Relational or completeness gap surfaced by `DeclarativeDependencyAuditor`.

    Attributes:
        question_id: Unique question ID inside the case.
        rule_id: Dependency rule ID from `dependency_rules.json`.
        severity: `"critical"` (blocks filing) or `"warning"`.
        trigger_forms: Official form IDs impacted by this gap.
        prompt: Plain-English question explaining what is missing and why.
        entity_id: Related asset/claim/month identifier if applicable.
        resolution_options: Allowed UI action keys.
        status: `"open"` or `"answered"`.
        selected_option: Action chosen by paralegal/attorney when answered.
        override: Audit trail attached when answered.
    """

    question_id: str
    rule_id: str
    severity: Literal["critical", "warning"] = "critical"
    trigger_forms: List[str] = Field(default_factory=list)
    prompt: str
    entity_id: Optional[str] = None
    resolution_options: List[str] = Field(default_factory=list)
    status: Literal["open", "answered"] = "open"
    selected_option: Optional[str] = None
    override: Optional[HumanOverrideRecord] = None


class CanonicalCaseGraph(BaseModel):
    """Complete generalized case state feeding calculators, audits, and form generation."""

    matter_id: str
    chapter: ChapterType = "7"
    district: DistrictCode = "CACB"
    expected_filing_date: datetime.date = Field(
        default_factory=lambda: datetime.date(2026, 11, 16)
    )
    parties: List[PartyEntity] = Field(default_factory=list)
    assets: List[AssetItem] = Field(default_factory=list)
    claims: List[ClaimItem] = Field(default_factory=list)
    paystubs: List[PaystubRecord] = Field(default_factory=list)
    bank_statements: List[BankStatementPeriod] = Field(default_factory=list)
    tax_returns: List[TaxReturnSummary] = Field(default_factory=list)
    budget: MonthlyBudgetScheduleIJ = Field(default_factory=MonthlyBudgetScheduleIJ)
    executory_contracts: List[ExecutoryContractItem] = Field(default_factory=list)
    codebtors: List[CodebtorItem] = Field(default_factory=list)
    historical_transactions: List[HistoricalTransaction] = Field(default_factory=list)
    zero_income_attested_months: List[str] = Field(default_factory=list)
    month_to_month_lease_attested: bool = False
    signed_declaration_uploaded: bool = False
    signed_declaration_sha256: Optional[str] = None
    attorney_name: str = ""
    attorney_bar_number: str = ""


# =====================================================================
# Calculator, Audit, Readiness, and Lineage Outputs
# =====================================================================

class EligibilityResult(BaseModel):
    """Statutory eligibility verdict for Chapter 7, Chapter 13, and Subchapter V."""

    target_chapter: ChapterType
    eligible: bool
    total_secured_noncontingent_liquidated: Decimal
    total_unsecured_noncontingent_liquidated: Decimal
    total_combined_qualifying_debt: Decimal
    excluded_contingent_or_unliquidated_debt: Decimal
    excluded_insider_affiliate_debt: Decimal
    commercial_debt_ratio: Decimal
    threshold_limit_applied: Optional[Decimal] = None
    table_version_id: str
    table_sha256: str
    authority_citation: str
    notes: List[str] = Field(default_factory=list)


class MeansTestResult(BaseModel):
    """6-Month CMI lookback and Form 122A/122C calculation output."""

    lookback_start: datetime.date
    lookback_end: datetime.date
    lookback_months: List[str]
    total_6_month_gross_income: Decimal
    current_monthly_income: Decimal
    annualized_cmi: Decimal
    household_size: int
    california_median_income: Decimal
    is_above_median: bool
    requires_full_means_test: bool
    irs_food_clothing_allowance: Decimal = Decimal("0.00")
    irs_healthcare_allowance: Decimal = Decimal("0.00")
    irs_housing_utilities_allowance: Decimal = Decimal("0.00")
    irs_transportation_allowance: Decimal = Decimal("0.00")
    payroll_taxes_deduction: Decimal = Decimal("0.00")
    secured_debt_cure_monthly: Decimal = Decimal("0.00")
    total_allowed_deductions: Decimal = Decimal("0.00")
    monthly_disposable_income: Decimal = Decimal("0.00")
    sixty_month_disposable_income: Decimal = Decimal("0.00")
    presumption_of_abuse: Optional[bool] = None
    applicable_commitment_months: int = 36
    table_version_id: str
    table_sha256: str


class ExemptionAllocation(BaseModel):
    """Line-item exemption assignment for one `AssetItem` under one regime."""

    asset_id: str
    asset_description: str
    category: AssetCategory
    current_value: Decimal
    linked_liens: Decimal
    net_equity: Decimal
    statute_cited: str
    category_exempt_applied: Decimal
    wildcard_exempt_applied: Decimal
    total_exempt: Decimal
    non_exempt_equity: Decimal
    cap_notes: Optional[str] = None


class ExemptionRegimeEvaluation(BaseModel):
    """Full Schedule C evaluation across all assets under one exemption regime."""

    regime_id: str
    display_name: str
    total_net_equity: Decimal
    total_exempt_equity: Decimal
    total_non_exempt_equity: Decimal
    wildcard_pool_available: Decimal
    wildcard_pool_used: Decimal
    allocations: List[ExemptionAllocation] = Field(default_factory=list)


class ExemptionOptimizationResult(BaseModel):
    """Comparison across all eligible state/federal regimes recommending optimal election."""

    domicile_state_applied: str
    domicile_rule_note: str
    recommended_regime_id: str
    recommended_display_name: str
    evaluations: List[ExemptionRegimeEvaluation] = Field(default_factory=list)
    table_version_id: str
    table_sha256: str


class Chapter13PlanResult(BaseModel):
    """Deterministic Chapter 13 repayment floor and monthly plan computation."""

    applicable_commitment_months: int
    monthly_disposable_income_122c: Decimal
    schedule_ij_monthly_net: Decimal
    unsecured_pool_via_disposable_income: Decimal
    best_interests_liquidation_floor: Decimal
    priority_claims_total: Decimal
    secured_arrears_total: Decimal
    total_minimum_plan_funding: Decimal
    estimated_monthly_plan_payment: Decimal


class CalculationSummary(BaseModel):
    """Aggregated deterministic calculator outputs for a bankruptcy case."""

    eligibility: EligibilityResult
    means_test: MeansTestResult
    exemptions: ExemptionOptimizationResult
    ch13_plan: Optional[Chapter13PlanResult] = None
    schedule_i_monthly_gross: Decimal = Decimal("0.00")
    schedule_j_monthly_expenses: Decimal = Decimal("0.00")
    schedule_ij_monthly_net: Decimal = Decimal("0.00")
    total_assets: Decimal = Decimal("0.00")
    total_secured_debt: Decimal = Decimal("0.00")
    total_priority_debt: Decimal = Decimal("0.00")
    total_general_unsecured_debt: Decimal = Decimal("0.00")


class FieldLineageEntry(BaseModel):
    """Cryptographic provenance record emitted for every filled PDF widget."""

    form_id: str
    pdf_field_name: str
    form_line_ref: Optional[str] = None
    rendered_value: str
    derivation_type: Literal["direct_provenance", "deterministic_calculation", "human_override", "system_constant"]
    case_graph_path: str
    formula: Optional[str] = None
    source_locators: List[SourceLocator] = Field(default_factory=list)
    human_override: Optional[HumanOverrideRecord] = None


class FilingReadinessReport(BaseModel):
    """Strict zero-doubt compiler gate verdict for a bankruptcy matter."""

    status: Literal["READY", "BLOCKED"]
    unverified_field_paths: List[str] = Field(default_factory=list)
    unresolved_critical_questions: List[str] = Field(default_factory=list)
    unresolved_critical_tensions: List[str] = Field(default_factory=list)
    packet_validation_errors: List[str] = Field(default_factory=list)
    required_forms: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)


class CourtFilingReceipt(BaseModel):
    """Submission receipt returned by a `CourtSubmissionDriver` (`CACB` or `CAEB`)."""

    receipt_id: str
    matter_id: str
    district: DistrictCode
    chapter: ChapterType
    submission_mode: Literal["ecf_train", "filing_agent", "firm_attorney"]
    assigned_case_number: str
    submitted_at: str
    rule_9011_attorney: str
    attorney_bar_number: str
    submitted_files: List[str] = Field(default_factory=list)
    step_log: List[str] = Field(default_factory=list)
    receipt_sha256: str


class BankruptcyCaseState(BaseModel):
    """Top-level persisted bankruptcy workbench state (`matters/<id>/bankruptcy_case.json`)."""

    case_graph: CanonicalCaseGraph
    calculations: Optional[CalculationSummary] = None
    emerging_questions: List[EmergingQuestionItem] = Field(default_factory=list)
    tensions: List[TensionObject] = Field(default_factory=list)
    resolved_tension_records: Dict[str, HumanOverrideRecord] = Field(default_factory=dict)
    plausibility_warnings: List[TensionObject] = Field(default_factory=list)
    readiness: Optional[FilingReadinessReport] = None
    compiled_bundle: Optional[CompiledBundle] = None
    last_packet_files: List[str] = Field(default_factory=list)
    filing_receipts: List[CourtFilingReceipt] = Field(default_factory=list)
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
