"""Uncategorized document classifier and entity-first harvester for Bankruptcy v1.

Reads PII-masked, coordinate-stamped blocks (`*.indexed.md`) produced by
`MatterIngestor` and populates a generalized `CanonicalCaseGraph` without
requiring the paralegal to manually assign uploaded PDFs to individual forms.
Every extracted `ProvenanceField` passes through `ObservationVerifier` before
joining the graph.
"""

from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.bankruptcy.models import (
    AssetItem,
    BankStatementPeriod,
    BankTransactionItem,
    BudgetLineItem,
    CanonicalCaseGraph,
    ChapterType,
    ClaimItem,
    DistrictCode,
    HistoricalTransaction,
    HumanOverrideRecord,
    MonthlyBudgetScheduleIJ,
    PartyEntity,
    PaystubRecord,
    ProvenanceField,
    TaxReturnSummary,
)
from app.bankruptcy.verifier import IndexedMatterCorpus, ObservationVerifier
from app.ingest import MatterIngestor
from app.llm import LLMProvider, MockLLMProvider
from app.models import SourceLocator


# =====================================================================
# Constrained LLM Extraction Wire Schema (Non-Recursive, Compact)
# =====================================================================

class ExtractedLocatorRef(BaseModel):
    """Reference linking an LLM observation back to a pre-indexed block."""

    file_name: str
    locator_key: str
    verbatim_quote: str


class ExtractedPaystubDraft(BaseModel):
    """Structured paystub candidate emitted by the LLM harvester."""

    employer: str
    pay_period_start: str
    pay_period_end: str
    pay_date: str
    gross_pay: str
    gross_ref: ExtractedLocatorRef
    net_pay: str
    net_ref: ExtractedLocatorRef
    tax_withheld: str
    tax_ref: ExtractedLocatorRef
    ytd_gross: Optional[str] = None
    ytd_ref: Optional[ExtractedLocatorRef] = None
    retirement_deduction: Optional[str] = None
    retirement_ref: Optional[ExtractedLocatorRef] = None
    garnishment_deduction: Optional[str] = None
    garnishment_ref: Optional[ExtractedLocatorRef] = None
    deposit_account_last4: Optional[str] = None


class ExtractedAssetDraft(BaseModel):
    """Structured asset candidate emitted by the LLM harvester."""

    asset_id: str
    category: str
    description: str
    current_value: str
    value_ref: ExtractedLocatorRef
    account_last4: Optional[str] = None
    acquisition_date: Optional[str] = None
    acq_ref: Optional[ExtractedLocatorRef] = None


class ExtractedClaimDraft(BaseModel):
    """Structured creditor claim candidate emitted by the LLM harvester."""

    claim_id: str
    creditor_name: str
    address_lines: List[str] = Field(default_factory=list)
    city: str = ""
    state: str = ""
    zip_code: str = ""
    priority_type: str = "general_unsecured"
    total_claim_amount: str
    amount_ref: ExtractedLocatorRef
    monthly_payment: Optional[str] = None
    monthly_ref: Optional[ExtractedLocatorRef] = None
    arrears_amount: Optional[str] = None
    arrears_ref: Optional[ExtractedLocatorRef] = None
    collateral_asset_id: Optional[str] = None
    contingent: bool = False
    unliquidated: bool = False
    disputed: bool = False
    is_insider_or_affiliate: bool = False
    commercial_business_pct: float = 0.0


class ExtractedBankStmtDraft(BaseModel):
    """Structured bank statement candidate emitted by the LLM harvester."""

    institution: str
    account_last4: str
    period_start: str
    period_end: str
    beginning_balance: str
    ending_balance: str
    total_deposits: str
    payroll_deposits: str
    ref: ExtractedLocatorRef


class ExtractedTaxReturnDraft(BaseModel):
    """Structured Form 1040 candidate emitted by the LLM harvester."""

    tax_year: int
    filing_status: str = "single"
    dependents_count: int
    agi: str
    total_tax: str
    refund_or_balance_due: Optional[str] = None
    schedule_b_institutions: List[str] = Field(default_factory=list)
    has_schedule_c_e_or_k1: bool = False
    ref: ExtractedLocatorRef


class CaseExtractionDraft(BaseModel):
    """Top-level structured draft harvested from a matter's indexed corpus."""

    debtor_name: Optional[str] = None
    debtor_name_ref: Optional[ExtractedLocatorRef] = None
    county_of_residence: Optional[str] = None
    household_size: Optional[int] = None
    household_ref: Optional[ExtractedLocatorRef] = None
    paystubs: List[ExtractedPaystubDraft] = Field(default_factory=list)
    assets: List[ExtractedAssetDraft] = Field(default_factory=list)
    claims: List[ExtractedClaimDraft] = Field(default_factory=list)
    bank_statements: List[ExtractedBankStmtDraft] = Field(default_factory=list)
    tax_returns: List[ExtractedTaxReturnDraft] = Field(default_factory=list)


# =====================================================================
# Deterministic Extraction & Fan-Out Engine
# =====================================================================

def _parse_dec(raw: str) -> Decimal:
    """Parses currency string such as `'$4,850.00'` into `Decimal`."""
    cleaned = re.sub(r"[,$\s]", "", raw or "")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def _parse_date_str(raw: str, fallback: datetime.date) -> datetime.date:
    """Parses ISO `YYYY-MM-DD` or `MM/DD/YYYY` date strings."""
    text = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return fallback


class BankruptcyCaseExtractor:
    """Harvests coordinate-grounded entities from uncategorized client files."""

    def __init__(self, verifier: Optional[ObservationVerifier] = None) -> None:
        """Initializes the case extractor.

        Args:
            verifier: Optional `ObservationVerifier` instance for post-harvest validation.
        """
        self.verifier = verifier or ObservationVerifier()

    @staticmethod
    def _field_from_block(
        value: Any, loc: SourceLocator, quote: str
    ) -> ProvenanceField[Any]:
        """Builds an initial `ProvenanceField` citing `loc` and `quote`."""
        return ProvenanceField[type(value)](
            value=value,
            verification_status="unverified",
            locators=[loc],
            verbatim_quotes=[quote],
        )

    _KV_BOUNDARY = (
        r"(?=\s+(?:Asset ID:|Category:|Description:|Fair Market Value:|Acquisition Date:|"
        r"Debtor Name:|Name:|SSN:|Tax ID:|Street Address:|City/State/Zip:|"
        r"County of Residence:|County:|Household Size:|CA Domicile Days:|Domicile Days:|"
        r"Employer:|Pay Date:|Gross Pay:|Net Pay:|Taxes? Withheld:|YTD Gross:|"
        r"401\(k\) Deduction:|Direct Deposit|Institution:|Account|Period Start:|Period End:|"
        r"Beginning Balance:|Ending Balance:|Total Deposits:|Payroll Deposits:|Lender:|"
        r"Creditor Address:|Principal Balance:|Monthly Payment:|Arrears(?: Due)?:|"
        r"Collateral Ref:|Creditor:|Balance Due:|Business Debt Pct:|Tax Year:|"
        r"Filing Status:|Dependents:|Adjusted Gross Income:|Total Tax:|Refund Due:|"
        r"Schedule B Institutions:|Monthly Gross Income:|Rent/Mortgage:|Utilities:|"
        r"Food/Housekeeping:|Auto Fuel/Insurance:|Clothing/Personal:|Budget Dependents:|"
        r"TX\s+\d{4}-)|\n|$)"
    )

    @classmethod
    def _find_line(cls, text: str, pattern: str) -> Optional[Tuple[str, str]]:
        """Matches regex `pattern` cleanly across newline- or space-joined PDF blocks."""
        bounded = (
            pattern[:-4] + r"(.+?)" + cls._KV_BOUNDARY
            if pattern.endswith("(.+)")
            else pattern
        )
        m = re.search(bounded, text, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(0).strip()
        return None

    def _apply_multi_form_fanout(self, graph: CanonicalCaseGraph) -> CanonicalCaseGraph:
        """Enriches the Case Graph with cross-form projections (e.g., Loan -> Schedule J, 1040 -> SOFA)."""
        existing_exp_descs = {e.description.lower() for e in graph.budget.expense_items}
        new_expenses = list(graph.budget.expense_items)

        # Auto/Mortgage loan statements fan out to Schedule J monthly debt payments.
        for claim in graph.claims:
            if (
                claim.priority_type == "secured"
                and claim.monthly_payment is not None
                and claim.statement_of_intention != "surrender"
            ):
                desc = f"{claim.creditor_name} monthly secured payment"
                if desc.lower() not in existing_exp_descs:
                    cat = (
                        "rent_or_mortgage"
                        if "mortgage" in claim.creditor_name.lower() or "home" in claim.creditor_name.lower()
                        else "vehicle_payment"
                    )
                    new_expenses.append(
                        BudgetLineItem(
                            item_id=f"exp_{claim.claim_id}",
                            category=cat,
                            description=desc,
                            monthly_amount=claim.monthly_payment,
                        )
                    )
                    existing_exp_descs.add(desc.lower())

        # Bank statements maintain/update Schedule A/B depository asset balances using latest closing date.
        existing_acct_last4 = {a.account_last4: i for i, a in enumerate(graph.assets) if a.account_last4}
        new_assets = list(graph.assets)
        latest_by_last4: Dict[str, BankStatementPeriod] = {}
        for stmt in graph.bank_statements:
            prev = latest_by_last4.get(stmt.account_last4)
            if prev is None or stmt.period_end > prev.period_end:
                latest_by_last4[stmt.account_last4] = stmt

        for last4, stmt in latest_by_last4.items():
            if last4 not in existing_acct_last4:
                new_assets.append(
                    AssetItem(
                        asset_id=f"bank_{last4}",
                        category="bank_account",
                        description=f"{stmt.institution} Account (...{last4})",
                        account_last4=last4,
                        current_value=stmt.ending_balance,
                    )
                )

        # Form 1040 Tax Return fans out to SOFA income history & IRS tax refund asset / priority debt.
        new_hist = list(graph.historical_transactions)
        existing_hist_ids = {h.tx_id for h in new_hist}
        new_claims = list(graph.claims)
        existing_claim_ids = {c.claim_id for c in new_claims}

        for tr in graph.tax_returns:
            sofa_id = f"sofa_inc_{tr.tax_year}"
            if sofa_id not in existing_hist_ids:
                new_hist.append(
                    HistoricalTransaction(
                        tx_id=sofa_id,
                        sofa_part="income_history",
                        description=f"Tax Year {tr.tax_year} Form 1040 Adjusted Gross Income",
                        tx_date=datetime.date(tr.tax_year, 12, 31),
                        amount=tr.agi,
                    )
                )
            if tr.refund_or_balance_due is not None:
                val = tr.refund_or_balance_due.value
                if val > Decimal("0.00"):
                    aid = f"tax_refund_{tr.tax_year}"
                    if not any(a.asset_id == aid for a in new_assets):
                        new_assets.append(
                            AssetItem(
                                asset_id=aid,
                                category="receivable",
                                description=f"Expected {tr.tax_year} Federal Tax Refund",
                                current_value=tr.refund_or_balance_due,
                            )
                        )
                elif val < Decimal("0.00"):
                    cid = f"irs_tax_{tr.tax_year}"
                    if cid not in existing_claim_ids:
                        abs_pf = tr.refund_or_balance_due.model_copy(update={"value": abs(val)})
                        new_claims.append(
                            ClaimItem(
                                claim_id=cid,
                                creditor_name=f"Internal Revenue Service ({tr.tax_year} Tax Due)",
                                creditor_address_lines=["PO Box 7346"],
                                city="Philadelphia",
                                state="PA",
                                zip_code="19101",
                                priority_type="priority_tax",
                                total_claim_amount=abs_pf,
                            )
                        )

        return graph.model_copy(
            update={
                "assets": new_assets,
                "claims": new_claims,
                "budget": graph.budget.model_copy(update={"expense_items": new_expenses}),
                "historical_transactions": new_hist,
            }
        )

    def _extract_deterministically(
        self,
        matter_id: str,
        corpus: IndexedMatterCorpus,
        base_graph: CanonicalCaseGraph,
    ) -> CanonicalCaseGraph:
        """Deterministically parses structured client PDFs/tables into `CanonicalCaseGraph`."""
        # Group indexed text blocks by filename so multi-block PDFs combine cleanly.
        blocks_by_file: Dict[str, List[Tuple[SourceLocator, str]]] = {}
        for (_, _), (loc, txt) in sorted(corpus.blocks_by_key.items()):
            blocks_by_file.setdefault(loc.file_name or "unknown", []).append((loc, txt))

        parties = list(base_graph.parties)
        assets = list(base_graph.assets)
        claims = list(base_graph.claims)
        paystubs = list(base_graph.paystubs)
        bank_statements = list(base_graph.bank_statements)
        tax_returns = list(base_graph.tax_returns)
        budget = base_graph.budget.model_copy()

        debtor_party: Optional[PartyEntity] = next(
            (p for p in parties if p.role == "debtor_1"), None
        )

        for fname, block_list in blocks_by_file.items():
            full_text = "\n".join(txt for _, txt in block_list)
            low = full_text.lower()

            def _locate(pattern: str) -> Optional[Tuple[str, str, SourceLocator]]:
                for loc, btxt in block_list:
                    res = self._find_line(btxt, pattern)
                    if res:
                        return res[0], res[1], loc
                return None

            # 1. Debtor Intake / Profile Summary
            if "debtor profile" in low or "intake summary" in low or "county of residence" in low:
                name_hit = _locate(r"(?:Debtor Name|Name):\s*(.+)")
                county_hit = _locate(r"County(?: of Residence)?:\s*([A-Za-z\s]+)")
                hh_hit = _locate(r"Household Size:\s*(\d+)")
                dom_hit = _locate(r"(?:CA )?Domicile Days:\s*(\d+)")
                addr_hit = _locate(r"Street Address:\s*(.+)")
                csz_hit = _locate(r"City/State/Zip:\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)")
                ssn_hit = _locate(r"(?:SSN|Tax ID):\s*(\[PII:SSN_\d+\]|\d{3}-\d{2}-\d{4})")
                if name_hit and debtor_party is None:
                    city, st, zp = "", "CA", ""
                    if csz_hit:
                        m_csz = re.search(
                            r"City/State/Zip:\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                            csz_hit[1],
                            re.IGNORECASE,
                        )
                        if m_csz:
                            city, st, zp = m_csz.group(1).strip(), m_csz.group(2).upper(), m_csz.group(3)
                    debtor_party = PartyEntity(
                        party_id="debtor_1",
                        role="debtor_1",
                        full_name=self._field_from_block(name_hit[0], name_hit[2], name_hit[1]),
                        ssn_token_or_ein=ssn_hit[0] if ssn_hit else None,
                        street_address=addr_hit[0] if addr_hit else "",
                        city=city,
                        state=st,
                        zip_code=zp,
                        county_of_residence=county_hit[0].strip() if county_hit else "Los Angeles",
                        ca_domicile_days_continuous=(
                            self._field_from_block(int(dom_hit[0]), dom_hit[2], dom_hit[1])
                            if dom_hit
                            else ProvenanceField[int](
                                value=1095,
                                verification_status="human_overridden",
                                override=HumanOverrideRecord(
                                    actor_name="System Default",
                                    actor_role="paralegal",
                                    rationale="Default domicile pending confirmation.",
                                ),
                            )
                        ),
                        household_size=(
                            self._field_from_block(int(hh_hit[0]), hh_hit[2], hh_hit[1])
                            if hh_hit
                            else ProvenanceField[int](value=1, verification_status="unverified")
                        ),
                    )
                    parties.append(debtor_party)

            # 2. Paystub / Earnings Statement
            if "paystub" in low or "earnings statement" in low or ("gross pay:" in low and "net pay:" in low):
                emp_hit = _locate(r"Employer:\s*(.+)")
                date_hit = _locate(r"Pay Date:\s*([0-9/-]+)")
                gross_hit = _locate(r"Gross Pay:\s*\$?([0-9,]+\.[0-9]{2})")
                net_hit = _locate(r"Net Pay:\s*\$?([0-9,]+\.[0-9]{2})")
                tax_hit = _locate(r"Tax(?:es)? Withheld:\s*\$?([0-9,]+\.[0-9]{2})")
                ytd_hit = _locate(r"YTD Gross:\s*\$?([0-9,]+\.[0-9]{2})")
                ret_hit = _locate(r"401\(k\) Deduction:\s*\$?([0-9,]+\.[0-9]{2})")
                dep_hit = _locate(r"Direct Deposit.*?(?:LAST4_|ending\s+)(\d{4})")
                if gross_hit and net_hit and date_hit:
                    p_date = _parse_date_str(date_hit[0], base_graph.expected_filing_date)
                    stub_id = f"ps_{re.sub(r'[^a-z0-9]+', '_', fname.lower())}"
                    if not any(p.paystub_id == stub_id for p in paystubs):
                        paystubs.append(
                            PaystubRecord(
                                paystub_id=stub_id,
                                employer=emp_hit[0] if emp_hit else "Employer",
                                pay_period_start=p_date.replace(day=1),
                                pay_period_end=p_date,
                                pay_date=p_date,
                                gross_pay=self._field_from_block(_parse_dec(gross_hit[0]), gross_hit[2], gross_hit[1]),
                                net_pay=self._field_from_block(_parse_dec(net_hit[0]), net_hit[2], net_hit[1]),
                                ytd_gross=(
                                    self._field_from_block(_parse_dec(ytd_hit[0]), ytd_hit[2], ytd_hit[1])
                                    if ytd_hit
                                    else None
                                ),
                                tax_withheld=(
                                    self._field_from_block(_parse_dec(tax_hit[0]), tax_hit[2], tax_hit[1])
                                    if tax_hit
                                    else self._field_from_block(Decimal("0.00"), net_hit[2], net_hit[1])
                                ),
                                retirement_deduction=(
                                    self._field_from_block(_parse_dec(ret_hit[0]), ret_hit[2], ret_hit[1])
                                    if ret_hit
                                    else None
                                ),
                                deposit_account_last4=dep_hit[0] if dep_hit else None,
                            )
                        )

            # 3. Auto Loan / Mortgage / Secured Loan Statement
            if ("loan statement" in low or "auto finance" in low or "mortgage statement" in low) and "principal balance:" in low:
                cred_hit = _locate(r"Lender:\s*(.+)")
                bal_hit = _locate(r"Principal Balance:\s*\$?([0-9,]+\.[0-9]{2})")
                pmt_hit = _locate(r"Monthly Payment:\s*\$?([0-9,]+\.[0-9]{2})")
                arr_hit = _locate(r"Arrears(?: Due)?:\s*\$?([0-9,]+\.[0-9]{2})")
                addr_hit = _locate(r"Creditor Address:\s*(.+)")
                col_hit = _locate(r"Collateral Ref:\s*(.+)")
                if cred_hit and bal_hit:
                    cid = f"claim_{re.sub(r'[^a-z0-9]+', '_', fname.lower())}"
                    if not any(c.claim_id == cid for c in claims):
                        addr_parts = [p.strip() for p in (addr_hit[0] if addr_hit else "").split(",") if p.strip()]
                        street = addr_parts[0] if len(addr_parts) >= 1 else "PO Box 1000"
                        city = addr_parts[1] if len(addr_parts) >= 2 else "Los Angeles"
                        st_zip = addr_parts[2].split() if len(addr_parts) >= 3 else ["CA", "90001"]
                        claims.append(
                            ClaimItem(
                                claim_id=cid,
                                creditor_name=cred_hit[0],
                                creditor_address_lines=[street],
                                city=city,
                                state=st_zip[0],
                                zip_code=st_zip[1] if len(st_zip) > 1 else "90001",
                                priority_type="secured",
                                total_claim_amount=self._field_from_block(_parse_dec(bal_hit[0]), bal_hit[2], bal_hit[1]),
                                monthly_payment=(
                                    self._field_from_block(_parse_dec(pmt_hit[0]), pmt_hit[2], pmt_hit[1])
                                    if pmt_hit
                                    else None
                                ),
                                arrears_amount=(
                                    self._field_from_block(_parse_dec(arr_hit[0]), arr_hit[2], arr_hit[1])
                                    if arr_hit
                                    else None
                                ),
                                collateral_asset_id=col_hit[0].strip() if col_hit else None,
                            )
                        )

            # 4. Unsecured Credit Card / Collection Statement
            if ("credit card statement" in low or "unsecured claim" in low or "collection notice" in low) and "balance due:" in low:
                cred_hit = _locate(r"Creditor:\s*(.+)")
                bal_hit = _locate(r"Balance Due:\s*\$?([0-9,]+\.[0-9]{2})")
                addr_hit = _locate(r"Creditor Address:\s*(.+)")
                biz_hit = _locate(r"Business Debt Pct:\s*([0-9.]+)")
                if cred_hit and bal_hit:
                    cid = f"claim_{re.sub(r'[^a-z0-9]+', '_', fname.lower())}"
                    if not any(c.claim_id == cid for c in claims):
                        addr_parts = [p.strip() for p in (addr_hit[0] if addr_hit else "").split(",") if p.strip()]
                        street = addr_parts[0] if len(addr_parts) >= 1 else "PO Box 2000"
                        city = addr_parts[1] if len(addr_parts) >= 2 else "Phoenix"
                        st_zip = addr_parts[2].split() if len(addr_parts) >= 3 else ["AZ", "85001"]
                        claims.append(
                            ClaimItem(
                                claim_id=cid,
                                creditor_name=cred_hit[0],
                                creditor_address_lines=[street],
                                city=city,
                                state=st_zip[0],
                                zip_code=st_zip[1] if len(st_zip) > 1 else "85001",
                                priority_type="general_unsecured",
                                total_claim_amount=self._field_from_block(_parse_dec(bal_hit[0]), bal_hit[2], bal_hit[1]),
                                commercial_business_pct=float(biz_hit[0]) if biz_hit else 0.0,
                            )
                        )

            # 5. Property / Vehicle Valuation or Appraisal
            if ("valuation" in low or "appraisal" in low or "asset schedule" in low) and "fair market value:" in low:
                id_hit = _locate(r"Asset ID:\s*(.+)")
                cat_hit = _locate(r"Category:\s*(.+)")
                desc_hit = _locate(r"Description:\s*(.+)")
                val_hit = _locate(r"Fair Market Value:\s*\$?([0-9,]+\.[0-9]{2})")
                acq_hit = _locate(r"Acquisition Date:\s*([0-9/-]+)")
                if desc_hit and val_hit:
                    aid = id_hit[0].strip() if id_hit else f"asset_{re.sub(r'[^a-z0-9]+', '_', fname.lower())}"
                    if not any(a.asset_id == aid for a in assets):
                        assets.append(
                            AssetItem(
                                asset_id=aid,
                                category=cat_hit[0].strip() if cat_hit else "other",  # type: ignore[arg-type]
                                description=desc_hit[0],
                                current_value=self._field_from_block(_parse_dec(val_hit[0]), val_hit[2], val_hit[1]),
                                acquisition_date=(
                                    self._field_from_block(
                                        _parse_date_str(acq_hit[0], datetime.date(2020, 1, 1)),
                                        acq_hit[2],
                                        acq_hit[1],
                                    )
                                    if acq_hit
                                    else None
                                ),
                            )
                        )

            # 6. Bank Statement
            if "bank statement" in low and "ending balance:" in low:
                inst_hit = _locate(r"Institution:\s*(.+)")
                last4_hit = _locate(r"Account.*?(?:LAST4_|ending\s+)(\d{4})")
                pstart_hit = _locate(r"Period Start:\s*([0-9-]+)")
                pend_hit = _locate(r"Period End:\s*([0-9-]+)")
                beg_hit = _locate(r"Beginning Balance:\s*\$?([0-9,]+\.[0-9]{2})")
                end_hit = _locate(r"Ending Balance:\s*\$?([0-9,]+\.[0-9]{2})")
                dep_tot_hit = _locate(r"Total Deposits:\s*\$?([0-9,]+\.[0-9]{2})")
                pay_dep_hit = _locate(r"Payroll Deposits:\s*\$?([0-9,]+\.[0-9]{2})")

                if inst_hit and end_hit and dep_tot_hit:
                    sid = f"stmt_{re.sub(r'[^a-z0-9]+', '_', fname.lower())}"
                    if not any(s.statement_id == sid for s in bank_statements):
                        flagged_txs: List[BankTransactionItem] = []
                        for loc, btxt in block_list:
                            tx_pattern = (
                                r"TX\s+([0-9-]+)\s+(DEBIT|CREDIT)\s+\$([0-9,]+\.[0-9]{2})\s+(.+?)"
                                r"(?=\s+TX\s+\d{4}-|\n|$)"
                            )
                            for idx_line, m_tx in enumerate(
                                re.finditer(tx_pattern, btxt, re.IGNORECASE), start=1
                            ):
                                if m_tx:
                                    tx_date = _parse_date_str(m_tx.group(1), datetime.date(2026, 8, 1))
                                    direction = m_tx.group(2).lower()
                                    amt = _parse_dec(m_tx.group(3))
                                    memo = m_tx.group(4).strip()
                                    hint = "other"
                                    t4 = None
                                    m_t4 = re.search(r"ACCT\s*(?:LAST4_|\.\.\.)?(\d{4})", memo, re.IGNORECASE)
                                    if m_t4:
                                        hint = "account_transfer"
                                        t4 = m_t4.group(1)
                                    elif any(k in memo.lower() for k in ("synchrony", "payment", "loan", "card", "finance")):
                                        hint = "debt_payment"
                                    elif any(k in memo.lower() for k in ("zelle", "venmo")):
                                        hint = "p2p_transfer"
                                    flagged_txs.append(
                                        BankTransactionItem(
                                            tx_id=f"{sid}_tx_{idx_line}",
                                            tx_date=tx_date,
                                            direction=direction,  # type: ignore[arg-type]
                                            payee_or_memo=memo,
                                            amount=amt,
                                            category_hint=hint,  # type: ignore[arg-type]
                                            target_account_last4=t4,
                                            locator=loc,
                                        )
                                    )

                        p_start = _parse_date_str(pstart_hit[0] if pstart_hit else "", datetime.date(2026, 8, 1))
                        p_end = _parse_date_str(pend_hit[0] if pend_hit else "", datetime.date(2026, 8, 31))
                        bank_statements.append(
                            BankStatementPeriod(
                                statement_id=sid,
                                institution=inst_hit[0],
                                account_last4=last4_hit[0] if last4_hit else "0000",
                                period_start=p_start,
                                period_end=p_end,
                                beginning_balance=(
                                    self._field_from_block(_parse_dec(beg_hit[0]), beg_hit[2], beg_hit[1])
                                    if beg_hit
                                    else self._field_from_block(_parse_dec(end_hit[0]), end_hit[2], end_hit[1])
                                ),
                                ending_balance=self._field_from_block(_parse_dec(end_hit[0]), end_hit[2], end_hit[1]),
                                total_deposits=self._field_from_block(_parse_dec(dep_tot_hit[0]), dep_tot_hit[2], dep_tot_hit[1]),
                                payroll_deposits=(
                                    self._field_from_block(_parse_dec(pay_dep_hit[0]), pay_dep_hit[2], pay_dep_hit[1])
                                    if pay_dep_hit
                                    else self._field_from_block(Decimal("0.00"), dep_tot_hit[2], dep_tot_hit[1])
                                ),
                                flagged_transactions=flagged_txs,
                            )
                        )

            # 7. Form 1040 Tax Return
            if "form 1040" in low and "adjusted gross income" in low:
                yr_hit = _locate(r"Tax Year:\s*(\d{4})")
                st_hit = _locate(r"Filing Status:\s*(\w+)")
                dep_hit = _locate(r"Dependents:\s*(\d+)")
                agi_hit = _locate(r"Adjusted Gross Income:\s*\$?([0-9,]+\.[0-9]{2})")
                tax_hit = _locate(r"Total Tax:\s*\$?([0-9,]+\.[0-9]{2})")
                ref_hit = _locate(r"Refund Due:\s*\$?(-?[0-9,]+\.[0-9]{2})")
                sched_b_hit = _locate(r"Schedule B Institutions:\s*(.+)")
                if yr_hit and agi_hit and tax_hit and dep_hit:
                    yr_val = int(yr_hit[0])
                    if not any(t.tax_year == yr_val for t in tax_returns):
                        insts = (
                            [i.strip() for i in sched_b_hit[0].split(",") if i.strip() and i.strip().lower() != "none"]
                            if sched_b_hit
                            else []
                        )
                        tax_returns.append(
                            TaxReturnSummary(
                                tax_year=yr_val,
                                filing_status=st_hit[0].lower() if st_hit else "single",  # type: ignore[arg-type]
                                dependents_count=self._field_from_block(int(dep_hit[0]), dep_hit[2], dep_hit[1]),
                                agi=self._field_from_block(_parse_dec(agi_hit[0]), agi_hit[2], agi_hit[1]),
                                total_tax=self._field_from_block(_parse_dec(tax_hit[0]), tax_hit[2], tax_hit[1]),
                                refund_or_balance_due=(
                                    self._field_from_block(_parse_dec(ref_hit[0]), ref_hit[2], ref_hit[1])
                                    if ref_hit
                                    else None
                                ),
                                schedule_b_institutions=insts,
                            )
                        )

            # 8. Monthly Budget Schedule I/J Worksheet
            if "monthly budget" in low or "schedule j expenses" in low:
                expense_patterns = [
                    ("rent_or_mortgage", r"Rent/Mortgage:\s*\$?([0-9,]+\.[0-9]{2})", "Monthly Rent/Mortgage"),
                    ("utilities", r"Utilities:\s*\$?([0-9,]+\.[0-9]{2})", "Electricity, Gas & Water"),
                    ("food_and_housekeeping", r"Food/Housekeeping:\s*\$?([0-9,]+\.[0-9]{2})", "Food & Housekeeping"),
                    ("transportation_fuel_insurance", r"Auto Fuel/Insurance:\s*\$?([0-9,]+\.[0-9]{2})", "Transportation & Auto Insurance"),
                    ("clothing_laundry", r"Clothing/Personal:\s*\$?([0-9,]+\.[0-9]{2})", "Clothing & Personal Care"),
                ]
                exp_items = list(budget.expense_items)
                for cat, pat, desc in expense_patterns:
                    hit = _locate(pat)
                    if hit and not any(e.category == cat for e in exp_items):
                        exp_items.append(
                            BudgetLineItem(
                                item_id=f"exp_{cat}",
                                category=cat,  # type: ignore[arg-type]
                                description=desc,
                                monthly_amount=self._field_from_block(_parse_dec(hit[0]), hit[2], hit[1]),
                            )
                        )
                inc_hit = _locate(r"Monthly Gross Income:\s*\$?([0-9,]+\.[0-9]{2})")
                inc_items = list(budget.income_items)
                if inc_hit and not inc_items:
                    inc_items.append(
                        BudgetLineItem(
                            item_id="inc_wages",
                            category="gross_wages",
                            description="Monthly Gross Wages",
                            monthly_amount=self._field_from_block(_parse_dec(inc_hit[0]), inc_hit[2], inc_hit[1]),
                        )
                    )
                dep_cnt_hit = _locate(r"Budget Dependents:\s*(\d+)")
                budget = MonthlyBudgetScheduleIJ(
                    income_items=inc_items,
                    expense_items=exp_items,
                    dependents_count=(
                        self._field_from_block(int(dep_cnt_hit[0]), dep_cnt_hit[2], dep_cnt_hit[1])
                        if dep_cnt_hit
                        else budget.dependents_count
                    ),
                )

        updated = base_graph.model_copy(
            update={
                "parties": parties,
                "assets": assets,
                "claims": claims,
                "paystubs": paystubs,
                "bank_statements": bank_statements,
                "tax_returns": tax_returns,
                "budget": budget,
            }
        )
        return self._apply_multi_form_fanout(updated)

    def _merge_llm_draft(
        self,
        draft: CaseExtractionDraft,
        corpus: IndexedMatterCorpus,
        base_graph: CanonicalCaseGraph,
    ) -> CanonicalCaseGraph:
        """Converts an LLM `CaseExtractionDraft` into `CanonicalCaseGraph` with real locators."""

        def _make_pf(value: Any, ref: Optional[ExtractedLocatorRef]) -> ProvenanceField[Any]:
            if ref is None:
                return ProvenanceField[type(value)](value=value, verification_status="unverified")
            entry = corpus.blocks_by_key.get((ref.file_name, ref.locator_key))
            if entry is None:
                return ProvenanceField[type(value)](
                    value=value,
                    verification_status="unverified",
                    locators=[
                        SourceLocator(
                            source_type="pdf",
                            file_name=ref.file_name,
                            locator_key=ref.locator_key,
                        )
                    ],
                    verbatim_quotes=[ref.verbatim_quote],
                )
            loc, _ = entry
            return ProvenanceField[type(value)](
                value=value,
                verification_status="unverified",
                locators=[loc],
                verbatim_quotes=[ref.verbatim_quote],
            )

        parties = list(base_graph.parties)
        if draft.debtor_name and not any(p.role == "debtor_1" for p in parties):
            parties.append(
                PartyEntity(
                    party_id="debtor_1",
                    role="debtor_1",
                    full_name=_make_pf(draft.debtor_name, draft.debtor_name_ref),
                    county_of_residence=draft.county_of_residence or "Los Angeles",
                    ca_domicile_days_continuous=ProvenanceField[int](
                        value=1095, verification_status="unverified"
                    ),
                    household_size=_make_pf(draft.household_size or 1, draft.household_ref),
                )
            )

        assets = list(base_graph.assets)
        for idx, a in enumerate(draft.assets, start=1):
            assets.append(
                AssetItem(
                    asset_id=a.asset_id or f"asset_{idx}",
                    category=a.category,  # type: ignore[arg-type]
                    description=a.description,
                    account_last4=a.account_last4,
                    current_value=_make_pf(_parse_dec(a.current_value), a.value_ref),
                )
            )

        claims = list(base_graph.claims)
        for idx, c in enumerate(draft.claims, start=1):
            claims.append(
                ClaimItem(
                    claim_id=c.claim_id or f"claim_{idx}",
                    creditor_name=c.creditor_name,
                    creditor_address_lines=c.address_lines,
                    city=c.city,
                    state=c.state,
                    zip_code=c.zip_code,
                    priority_type=c.priority_type,  # type: ignore[arg-type]
                    total_claim_amount=_make_pf(_parse_dec(c.total_claim_amount), c.amount_ref),
                    monthly_payment=(
                        _make_pf(_parse_dec(c.monthly_payment), c.monthly_ref)
                        if c.monthly_payment
                        else None
                    ),
                    collateral_asset_id=c.collateral_asset_id,
                    contingent=c.contingent,
                    unliquidated=c.unliquidated,
                    disputed=c.disputed,
                    is_insider_or_affiliate=c.is_insider_or_affiliate,
                    commercial_business_pct=c.commercial_business_pct,
                )
            )

        paystubs = list(base_graph.paystubs)
        for idx, ps in enumerate(draft.paystubs, start=1):
            p_date = _parse_date_str(ps.pay_date, base_graph.expected_filing_date)
            paystubs.append(
                PaystubRecord(
                    paystub_id=f"ps_llm_{idx}",
                    employer=ps.employer,
                    pay_period_start=_parse_date_str(ps.pay_period_start, p_date),
                    pay_period_end=_parse_date_str(ps.pay_period_end, p_date),
                    pay_date=p_date,
                    gross_pay=_make_pf(_parse_dec(ps.gross_pay), ps.gross_ref),
                    net_pay=_make_pf(_parse_dec(ps.net_pay), ps.net_ref),
                    ytd_gross=(
                        _make_pf(_parse_dec(ps.ytd_gross), ps.ytd_ref)
                        if ps.ytd_gross
                        else None
                    ),
                    tax_withheld=_make_pf(_parse_dec(ps.tax_withheld), ps.tax_ref),
                    retirement_deduction=(
                        _make_pf(_parse_dec(ps.retirement_deduction), ps.retirement_ref)
                        if ps.retirement_deduction
                        else None
                    ),
                    garnishment_or_support_deduction=(
                        _make_pf(_parse_dec(ps.garnishment_deduction), ps.garnishment_ref)
                        if ps.garnishment_deduction
                        else None
                    ),
                    deposit_account_last4=ps.deposit_account_last4,
                )
            )

        updated = base_graph.model_copy(
            update={
                "parties": parties,
                "assets": assets,
                "claims": claims,
                "paystubs": paystubs,
            }
        )
        return self._apply_multi_form_fanout(updated)

    def extract(
        self,
        matter_id: str,
        ingestor: MatterIngestor,
        chapter: ChapterType = "7",
        district: DistrictCode = "CACB",
        expected_filing_date: Optional[datetime.date] = None,
        llm_provider: Optional[LLMProvider] = None,
        existing_graph: Optional[CanonicalCaseGraph] = None,
    ) -> CanonicalCaseGraph:
        """Extracts and deterministically verifies a `CanonicalCaseGraph` from raw matter files.

        Args:
            matter_id: Matter identifier slug.
            ingestor: `MatterIngestor` managing the matter workspace.
            chapter: Target bankruptcy chapter (`"7"`, `"13"`, `"11_subv"`).
            district: California federal district (`"CACB"` or `"CAEB"`).
            expected_filing_date: Petition filing date driving 6-mo CMI & table versioning.
            llm_provider: Optional live `LLMProvider` (runs constrained extraction over
                PII-masked blocks; falls back cleanly to deterministic parser when `None`
                or `MockLLMProvider`).
            existing_graph: Optional existing case graph to preserve case metadata/overrides.

        Returns:
            Verified `CanonicalCaseGraph` with deterministic `verification_status` per field.
        """
        base_graph = existing_graph or CanonicalCaseGraph(
            matter_id=matter_id,
            chapter=chapter,
            district=district,
            expected_filing_date=expected_filing_date or datetime.date(2026, 11, 16),
        )
        corpus = IndexedMatterCorpus.load_for_matter(ingestor, matter_id)

        if llm_provider is not None and not isinstance(llm_provider, MockLLMProvider):
            prompt_blocks = [
                f"[{loc.file_name} | {loc.locator_key}]\n{txt}"
                for (_, _), (loc, txt) in sorted(corpus.blocks_by_key.items())
            ]
            context_str = "\n\n".join(prompt_blocks)
            draft = llm_provider.generate_structured(
                system_prompt=(
                    "You are a precision bankruptcy intake extractor. Extract only factual "
                    "observations explicitly stated in the PII-masked indexed blocks. Every "
                    "value MUST cite the exact file_name, locator_key, and verbatim_quote. "
                    "Never compute sums or averages."
                ),
                user_prompt=f"Extract bankruptcy entities from matter '{matter_id}':\n\n{context_str}",
                response_schema=CaseExtractionDraft,
            )
            graph = self._merge_llm_draft(draft, corpus, base_graph)
        else:
            graph = self._extract_deterministically(matter_id, corpus, base_graph)

        return self.verifier.verify_case_graph(graph, ingestor)
