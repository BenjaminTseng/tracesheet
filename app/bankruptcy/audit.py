"""Declarative dependency graph, quantitative forensic auditor, plausibility checks, and strict gate.

Combines three deterministic audit passes over `CanonicalCaseGraph` and
`CalculationSummary`:
1. `DeclarativeDependencyAuditor`: Evaluates cross-schedule rules in
   `dependency_rules.json` to emit `EmergingQuestionItem` prompts.
2. `QuantitativeForensicAuditor`: Detects unlisted creditors from bank statement
   ACH/debit outflows, undisclosed accounts from P2P/bank transfers, and
   cross-document numerical contradictions (`TensionObject`s).
3. `PlausibilityAuditEngine`: Flags statistical/qualitative anomalies (e.g., `$0`
   food/utilities on Schedule J, vehicle without insurance, anomalously low debt).
4. `FilingReadinessGate`: Enforces the strict zero-doubt gate (`READY` vs `BLOCKED`)
   before Official Filing Packet compilation.
"""

from __future__ import annotations

import datetime
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel

from app.bankruptcy.models import (
    BankruptcyCaseState,
    CalculationSummary,
    CanonicalCaseGraph,
    EmergingQuestionItem,
    FilingReadinessReport,
    HumanOverrideRecord,
    ProvenanceField,
)
from app.core.tables import StatutoryTableRegistry
from app.llm import LLMProvider
from app.models import TensionObject


DEBT_PAYEE_KEYWORDS = (
    "synchrony",
    "amex",
    "american express",
    "capital one",
    "discover",
    "chase card",
    "citi",
    "barclays",
    "toyota",
    "honda fin",
    "ally",
    "santander",
    "affirm",
    "klarna",
    "sofi",
    "navient",
    "nelnet",
    "portfolio recovery",
    "midland",
    "lending",
    "finance",
    "loan",
    "credit",
)

TRAUMA_MEDICAL_KEYWORDS = (
    "trauma",
    "emergency",
    "radiology",
    "orthopedic",
    "chiropract",
    "ambulance",
    "surgical",
    "accident",
    "medical center",
    "hospital",
)


def _slug(val: str) -> str:
    """Normalizes a label into a safe deterministic identifier slug."""
    return re.sub(r"[^a-z0-9]+", "_", (val or "").lower()).strip("_") or "item"


def _normalize_payee(text: str) -> str:
    """Strips common ACH suffixes to compare bank statement payees against Schedule D/E/F."""
    cleaned = re.sub(r"\b(ach|epayment|pmt|payment|autopay|web|pos|debit)\b", "", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


class DeclarativeDependencyAuditor:
    """Evaluates closed-world cross-schedule dependency rules (`dependency_rules.json`)."""

    def __init__(self, registry: StatutoryTableRegistry) -> None:
        """Initializes the dependency auditor.

        Args:
            registry: Statutory table registry holding `dependency_rules.json`.
        """
        self.registry = registry

    def audit(
        self,
        graph: CanonicalCaseGraph,
        calculations: CalculationSummary,
        existing_questions: Optional[List[EmergingQuestionItem]] = None,
    ) -> List[EmergingQuestionItem]:
        """Evaluates all cross-schedule dependencies and emits `EmergingQuestionItem`s.

        Args:
            graph: Populated `CanonicalCaseGraph`.
            calculations: Deterministic `CalculationSummary` (supplies 6-month lookback).
            existing_questions: Previously recorded questions to preserve `"answered"` state.

        Returns:
            Deduplicated list of `EmergingQuestionItem`s ordered by severity.
        """
        rules_doc = self.registry.get_dependency_rules()
        rule_meta: Dict[str, Dict[str, Any]] = {
            r["rule_id"]: r for r in rules_doc.get("rules", [])
        }
        prior_answered: Dict[str, EmergingQuestionItem] = {
            q.question_id: q
            for q in (existing_questions or [])
            if q.status == "answered" and q.override is not None
        }

        emitted: List[EmergingQuestionItem] = []

        def _add_question(
            question_id: str,
            rule_id: str,
            prompt_kwargs: Dict[str, Any],
            entity_id: Optional[str] = None,
            severity_override: Optional[str] = None,
        ) -> None:
            meta = rule_meta.get(rule_id, {})
            template = meta.get("prompt_template", "{detail}")
            try:
                prompt = template.format(**prompt_kwargs)
            except KeyError:
                prompt = template
            if question_id in prior_answered:
                emitted.append(prior_answered[question_id])
                return
            emitted.append(
                EmergingQuestionItem(
                    question_id=question_id,
                    rule_id=rule_id,
                    severity=severity_override or meta.get("severity", "critical"),
                    trigger_forms=list(meta.get("trigger_forms", [])),
                    prompt=prompt,
                    entity_id=entity_id,
                    resolution_options=list(meta.get("resolution_options", [])),
                    status="open",
                )
            )

        linked_asset_ids = {
            c.collateral_asset_id
            for c in graph.claims
            if c.priority_type == "secured" and c.collateral_asset_id
        }
        assets_by_id = {a.asset_id: a for a in graph.assets}

        # 1. Asset -> Loan check (Real property / Vehicle without loan or free-and-clear).
        for asset in graph.assets:
            if asset.category in ("real_property", "vehicle"):
                if asset.asset_id not in linked_asset_ids and asset.owned_free_and_clear is not True:
                    _add_question(
                        question_id=f"q_asset_lien_{asset.asset_id}",
                        rule_id="ASSET_MISSING_LIEN_STATUS",
                        prompt_kwargs={
                            "description": asset.description,
                            "value": f"{asset.current_value.value:,.2f}",
                        },
                        entity_id=asset.asset_id,
                    )

        # 2. Secured Loan -> Asset/Value check & Ch. 7 Form 108 Intention check.
        for claim in graph.claims:
            if claim.priority_type != "secured":
                continue
            collat = assets_by_id.get(claim.collateral_asset_id or "")
            if collat is None or collat.current_value.value <= Decimal("0.00"):
                _add_question(
                    question_id=f"q_loan_collat_{claim.claim_id}",
                    rule_id="SECURED_LOAN_MISSING_COLLATERAL_VALUE",
                    prompt_kwargs={
                        "creditor_name": claim.creditor_name,
                        "amount": f"{claim.total_claim_amount.value:,.2f}",
                    },
                    entity_id=claim.claim_id,
                )
            if graph.chapter == "7" and claim.statement_of_intention is None:
                _add_question(
                    question_id=f"q_b108_{claim.claim_id}",
                    rule_id="SECURED_CLAIM_MISSING_INTENTION",
                    prompt_kwargs={"creditor_name": claim.creditor_name},
                    entity_id=claim.claim_id,
                )

        # 3. Paystub deductions -> Retirement asset, Garnishment SOFA, Direct Deposit account.
        has_retirement_asset = any(a.category == "retirement" for a in graph.assets)
        has_garnishment_disclosure = any(
            h.sofa_part == "lawsuit_garnishment" for h in graph.historical_transactions
        ) or any(c.priority_type == "priority_dso" for c in graph.claims)
        known_acct_last4s = {a.account_last4 for a in graph.assets if a.account_last4}
        closed_acct_texts = " ".join(
            h.description.lower()
            for h in graph.historical_transactions
            if h.sofa_part == "closed_account"
        )

        seen_retire_emp: Set[str] = set()
        seen_garn_emp: Set[str] = set()
        seen_dep_last4: Set[str] = set()

        for ps in graph.paystubs:
            if (
                ps.retirement_deduction is not None
                and ps.retirement_deduction.value > Decimal("0.00")
                and not has_retirement_asset
                and ps.employer not in seen_retire_emp
            ):
                seen_retire_emp.add(ps.employer)
                _add_question(
                    question_id=f"q_retire_{_slug(ps.employer)}",
                    rule_id="PAYSTUB_RETIREMENT_MISSING_ON_AB",
                    prompt_kwargs={
                        "employer": ps.employer,
                        "amount": f"{ps.retirement_deduction.value:,.2f}",
                    },
                    entity_id=ps.paystub_id,
                )

            if (
                ps.garnishment_or_support_deduction is not None
                and ps.garnishment_or_support_deduction.value > Decimal("0.00")
                and not has_garnishment_disclosure
                and ps.employer not in seen_garn_emp
            ):
                seen_garn_emp.add(ps.employer)
                _add_question(
                    question_id=f"q_garn_{_slug(ps.employer)}",
                    rule_id="PAYSTUB_GARNISHMENT_MISSING_ON_SOFA",
                    prompt_kwargs={
                        "employer": ps.employer,
                        "amount": f"{ps.garnishment_or_support_deduction.value:,.2f}",
                    },
                    entity_id=ps.paystub_id,
                )

            if (
                ps.deposit_account_last4
                and ps.deposit_account_last4 not in known_acct_last4s
                and ps.deposit_account_last4 not in closed_acct_texts
                and ps.deposit_account_last4 not in seen_dep_last4
            ):
                seen_dep_last4.add(ps.deposit_account_last4)
                _add_question(
                    question_id=f"q_dep_acct_{ps.deposit_account_last4}",
                    rule_id="PAYSTUB_DEPOSIT_ACCOUNT_MISSING",
                    prompt_kwargs={"last4": ps.deposit_account_last4},
                    entity_id=ps.deposit_account_last4,
                )

        # 4. Tax return Schedule B & Schedule C/E/K-1 traces.
        asset_descs_lower = " ".join(a.description.lower() for a in graph.assets)
        has_biz_disclosure = any(a.category == "business_interest" for a in graph.assets) or any(
            h.sofa_part == "business_interest" for h in graph.historical_transactions
        )
        for tr in graph.tax_returns:
            for inst in tr.schedule_b_institutions:
                inst_low = inst.lower()
                if inst_low not in asset_descs_lower and inst_low not in closed_acct_texts:
                    _add_question(
                        question_id=f"q_tax_b_{_slug(inst)}",
                        rule_id="TAX_SCHED_B_ACCOUNT_MISSING",
                        prompt_kwargs={"institution": inst},
                        entity_id=inst,
                    )
            if tr.has_schedule_c_e_or_k1 and not has_biz_disclosure:
                _add_question(
                    question_id="q_tax_c_business",
                    rule_id="TAX_SCHED_C_BUSINESS_MISSING",
                    prompt_kwargs={},
                    entity_id=str(tr.tax_year),
                )

        # 5. Rent expense -> Schedule G unexpired lease.
        has_real_prop = any(a.category == "real_property" for a in graph.assets)
        rent_amt = sum(
            (
                item.monthly_amount.value
                for item in graph.budget.expense_items
                if item.category == "rent_or_mortgage"
            ),
            Decimal("0.00"),
        )
        has_res_lease = any(
            c.contract_type == "residential_lease" for c in graph.executory_contracts
        )
        if not has_real_prop and rent_amt > Decimal("0.00") and not has_res_lease and not graph.month_to_month_lease_attested:
            _add_question(
                question_id="q_rent_sched_g",
                rule_id="RENT_MISSING_SCHEDULE_G",
                prompt_kwargs={"amount": f"{rent_amt:,.2f}"},
                entity_id="schedule_g",
            )

        # 6. Joint assets / cosigned claims -> Schedule H Codebtors.
        linked_codebtor_claims = {c.linked_claim_id for c in graph.codebtors if c.linked_claim_id}
        linked_codebtor_assets = {c.linked_asset_id for c in graph.codebtors if c.linked_asset_id}
        for claim in graph.claims:
            if claim.is_cosigned and claim.claim_id not in linked_codebtor_claims:
                _add_question(
                    question_id=f"q_codebtor_claim_{claim.claim_id}",
                    rule_id="CODEBTOR_MISSING_SCHEDULE_H",
                    prompt_kwargs={"creditor_name": claim.creditor_name},
                    entity_id=claim.claim_id,
                )
        for asset in graph.assets:
            if asset.joint_with_non_filing and asset.asset_id not in linked_codebtor_assets:
                _add_question(
                    question_id=f"q_codebtor_asset_{asset.asset_id}",
                    rule_id="CODEBTOR_MISSING_SCHEDULE_H",
                    prompt_kwargs={"creditor_name": asset.description},
                    entity_id=asset.asset_id,
                )

        # 7. Mandatory 6-month CMI lookback completeness.
        covered_months = {
            f"{ps.pay_date.year:04d}-{ps.pay_date.month:02d}" for ps in graph.paystubs
        }
        attested_months = set(graph.zero_income_attested_months)
        for ym in calculations.means_test.lookback_months:
            if ym not in covered_months and ym not in attested_months:
                _add_question(
                    question_id=f"q_cmi_gap_{ym}",
                    rule_id="CMI_WINDOW_GAP",
                    prompt_kwargs={"month_label": ym},
                    entity_id=ym,
                )

        # 8. Homestead 1,215-day & 730-day domicile prerequisites.
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        domicile_ok = (
            debtor_1 is not None
            and (
                debtor_1.ca_domicile_days_continuous.value >= 730
                or bool(debtor_1.prior_state_180_days)
            )
        )
        for asset in graph.assets:
            if asset.category == "real_property" and (asset.acquisition_date is None or not domicile_ok):
                _add_question(
                    question_id=f"q_homestead_{asset.asset_id}",
                    rule_id="HOMESTEAD_PREREQUISITE_GAP",
                    prompt_kwargs={"description": asset.description},
                    entity_id=asset.asset_id,
                )

        # 9. Hidden personal injury / workers' comp detector from trauma creditors.
        has_injury_asset = any(
            a.category in ("personal_injury", "workers_comp", "legal_claims")
            for a in graph.assets
        )
        if not has_injury_asset and not graph.no_injury_or_wc_claim_attested:
            for claim in graph.claims:
                cname_low = claim.creditor_name.lower()
                if claim.is_trauma_or_medical_creditor or any(
                    kw in cname_low for kw in TRAUMA_MEDICAL_KEYWORDS
                ):
                    _add_question(
                        question_id=f"q_injury_wc_{claim.claim_id}",
                        rule_id="POTENTIAL_PERSONAL_INJURY_OR_WORKERS_COMP_CLAIM",
                        prompt_kwargs={"creditor_name": claim.creditor_name},
                        entity_id=claim.claim_id,
                    )
                    break

        # 10. Bidirectional SOFA Line 9 <-> Schedule A/B <-> Schedule E/F lawsuit sync.
        claims_by_id = {c.claim_id: c for c in graph.claims}
        all_claim_names_low = " ".join(c.creditor_name.lower() for c in graph.claims)
        for tx in graph.historical_transactions:
            if tx.sofa_part != "lawsuit_garnishment":
                continue
            if tx.party_role == "plaintiff":
                linked_ok = bool(tx.linked_asset_id and tx.linked_asset_id in assets_by_id)
                desc_tokens = [w for w in re.split(r"\W+", tx.description.lower()) if len(w) >= 4]
                text_match = has_injury_asset and any(tok in asset_descs_lower for tok in desc_tokens)
                if not linked_ok and not text_match:
                    _add_question(
                        question_id=f"q_sofa_plaintiff_{tx.tx_id}",
                        rule_id="SOFA_LAWSUIT_PLAINTIFF_MISSING_ON_AB",
                        prompt_kwargs={"description": tx.description},
                        entity_id=tx.tx_id,
                    )
            elif tx.party_role == "defendant":
                linked_ok = bool(tx.linked_claim_id and tx.linked_claim_id in claims_by_id)
                desc_tokens = [w for w in re.split(r"\W+", tx.description.lower()) if len(w) >= 4]
                text_match = any(tok in all_claim_names_low for tok in desc_tokens)
                if not linked_ok and not text_match:
                    _add_question(
                        question_id=f"q_sofa_def_{tx.tx_id}",
                        rule_id="SOFA_LAWSUIT_DEFENDANT_MISSING_ON_EF",
                        prompt_kwargs={"description": tx.description},
                        entity_id=tx.tx_id,
                    )

        # 11. Renter missing security deposit (Line 22/28, warning tier).
        has_sec_dep = any(a.category == "security_deposit" for a in graph.assets)
        if not has_real_prop and rent_amt > Decimal("0.00") and not has_sec_dep and not graph.no_security_deposit_attested:
            _add_question(
                question_id="q_renter_sec_dep",
                rule_id="RENTER_MISSING_SECURITY_DEPOSIT_LINE_28",
                prompt_kwargs={"amount": f"{rent_amt:,.2f}"},
                entity_id="security_deposit",
            )

        # 12. 60-day pre-petition paystub continuity gap (11 U.S.C. § 521(a)(1)(B)(iv)).
        if graph.paystubs and not graph.payment_advices_exception_attested:
            win60_start = graph.expected_filing_date - datetime.timedelta(days=60)
            sorted_all = sorted(graph.paystubs, key=lambda p: p.pay_date)
            latest_stub_date = sorted_all[-1].pay_date
            days_since_latest = (graph.expected_filing_date - latest_stub_date).days
            in_60d = [p for p in sorted_all if win60_start <= p.pay_date <= graph.expected_filing_date]
            gap_detail: Optional[str] = None
            if not in_60d or days_since_latest > 45:
                gap_detail = f"no paystub within 45 days before {graph.expected_filing_date.isoformat()} (latest: {latest_stub_date.isoformat()})"
            else:
                for idx in range(len(in_60d) - 1):
                    delta_days = (in_60d[idx + 1].pay_date - in_60d[idx].pay_date).days
                    if delta_days > 35:
                        gap_detail = f"{delta_days}-day gap between {in_60d[idx].pay_date.isoformat()} and {in_60d[idx + 1].pay_date.isoformat()}"
                        break
            if gap_detail is not None:
                _add_question(
                    question_id="q_paystub_60d_gap",
                    rule_id="PAYSTUB_60_DAY_CONTINUITY_GAP",
                    prompt_kwargs={"detail": gap_detail},
                    entity_id="paystubs_60d",
                )

        # 13. 11 U.S.C. § 522(p)(2)(B) same-state rollover inquiry on recent homestead > $214,000.
        if not graph.homestead_rollover_reviewed:
            for asset in graph.assets:
                if asset.category != "real_property" or asset.acquisition_date is None:
                    continue
                held_days = (graph.expected_filing_date - asset.acquisition_date.value).days
                liens = sum(
                    (
                        c.total_claim_amount.value
                        for c in graph.claims
                        if c.priority_type == "secured" and c.collateral_asset_id == asset.asset_id
                    ),
                    Decimal("0.00"),
                )
                equity = max(Decimal("0.00"), asset.current_value.value - liens)
                if (
                    held_days < 1215
                    and equity > Decimal("214000.00")
                    and asset.prior_state_residence_rollover_amount == Decimal("0.00")
                ):
                    _add_question(
                        question_id=f"q_522p_rollover_{asset.asset_id}",
                        rule_id="HOMESTEAD_522P_ROLLOVER_INQUIRY",
                        prompt_kwargs={
                            "description": asset.description,
                            "equity": f"{equity:,.2f}",
                        },
                        entity_id=asset.asset_id,
                    )

        # 14. Married filing separately CCP § 703.140(a)(2) written spousal waiver check.
        ex_opt = calculations.exemptions
        rec_eval = next(
            (e for e in ex_opt.evaluations if e.regime_id == ex_opt.recommended_regime_id),
            ex_opt.evaluations[0],
        )
        if (
            graph.marital_status in ("married_filing_separately_together", "married_filing_separately_apart")
            and rec_eval.regime_id == "CA_CCP_703_140"
            and not graph.spousal_703_waiver_signed
        ):
            _add_question(
                question_id="q_spousal_703_waiver",
                rule_id="MARRIED_SEPARATE_703_SPOUSAL_WAIVER",
                prompt_kwargs={},
                entity_id="CA_CCP_703_140",
            )

        # 15. Unknown valuation under capped exemption regime (Schwab v. Reilly windfall trap).
        if not graph.unknown_valuation_cap_reviewed:
            for alloc in rec_eval.allocations:
                if alloc.unknown_value_exposed_risk:
                    _add_question(
                        question_id=f"q_unknown_cap_{alloc.asset_id}",
                        rule_id="UNKNOWN_VALUATION_CAPPED_EXEMPTION_RISK",
                        prompt_kwargs={
                            "description": alloc.asset_description,
                            "regime": rec_eval.display_name,
                        },
                        entity_id=alloc.asset_id,
                    )

        # 16. Chapter 13 four-year tax return compliance (11 U.S.C. § 1308).
        if graph.chapter == "13" and (graph.tax_returns or graph.tax_years_filed_4yr):
            req_years = [graph.expected_filing_date.year - i for i in range(1, 5)]
            confirmed_years = {t.tax_year for t in graph.tax_returns} | set(graph.tax_years_filed_4yr)
            missing_years = [y for y in req_years if y not in confirmed_years]
            if missing_years:
                _add_question(
                    question_id="q_ch13_4yr_tax",
                    rule_id="CH13_FOUR_YEAR_TAX_RETURN_MISSING",
                    prompt_kwargs={"missing_years": ", ".join(str(y) for y in missing_years)},
                    entity_id="tax_returns",
                )

        # 17. Tier-2 grouped mandatory asset & 180-day windfall sweep (warning tier).
        if not graph.mandatory_asset_sweep_attested or not graph.windfall_180_day_attested:
            _add_question(
                question_id="q_mandatory_sweep_and_windfall",
                rule_id="MANDATORY_ASSET_AND_WINDFALL_SWEEP",
                prompt_kwargs={},
                entity_id="case_sweep",
            )

        return emitted


class QuantitativeForensicAuditor:
    """Detects unlisted accounts/creditors from bank cash flows and cross-doc contradictions."""

    @staticmethod
    def _is_debt_outflow(payee: str, category_hint: str) -> bool:
        """Returns True if a bank debit looks like debt service or credit repayment."""
        if category_hint == "debt_payment":
            return True
        low = payee.lower()
        return any(kw in low for kw in DEBT_PAYEE_KEYWORDS)

    def audit(
        self,
        graph: CanonicalCaseGraph,
        calculations: CalculationSummary,
        existing_questions: Optional[List[EmergingQuestionItem]] = None,
    ) -> Tuple[List[EmergingQuestionItem], List[TensionObject]]:
        """Runs bank outflow matching, transfer tracing, and cross-document triangulation.

        Args:
            graph: Populated `CanonicalCaseGraph`.
            calculations: Computed `CalculationSummary`.
            existing_questions: Previously recorded questions to preserve answered overrides.

        Returns:
            Tuple of `(forensic_emerging_questions, contradiction_tensions)`.
        """
        prior_answered: Dict[str, EmergingQuestionItem] = {
            q.question_id: q
            for q in (existing_questions or [])
            if q.status == "answered" and q.override is not None
        }
        forensic_questions: List[EmergingQuestionItem] = []
        tensions: List[TensionObject] = []

        # 1. Bank Statement Debt-Service Outflow Matcher -> finds unlisted creditors.
        creditor_names_norm = [_normalize_payee(c.creditor_name) for c in graph.claims]
        outflows_by_payee: Dict[str, List[Decimal]] = {}
        for stmt in graph.bank_statements:
            for tx in stmt.flagged_transactions:
                if tx.direction == "debit" and self._is_debt_outflow(
                    tx.payee_or_memo, tx.category_hint
                ):
                    norm = _normalize_payee(tx.payee_or_memo)
                    if not norm:
                        continue
                    outflows_by_payee.setdefault(tx.payee_or_memo, []).append(tx.amount)

        for raw_payee, amounts in sorted(outflows_by_payee.items()):
            norm = _normalize_payee(raw_payee)
            matched = any(
                c_norm and (c_norm in norm or norm in c_norm or any(tok in c_norm for tok in norm.split() if len(tok) >= 4))
                for c_norm in creditor_names_norm
            )
            if not matched:
                qid = f"q_unlisted_cred_{_slug(raw_payee)}"
                if qid in prior_answered:
                    forensic_questions.append(prior_answered[qid])
                else:
                    total_out = sum(amounts, Decimal("0.00"))
                    forensic_questions.append(
                        EmergingQuestionItem(
                            question_id=qid,
                            rule_id="UNLISTED_CREDITOR_FROM_BANK_OUTFLOW",
                            severity="critical",
                            trigger_forms=["B106D", "B106EF"],
                            prompt=(
                                f"Bank statements show {len(amounts)} recurring debt outflow(s) totaling "
                                f"${total_out:,.2f} to '{raw_payee}', which is missing from Schedules D/E/F. "
                                "Add this creditor or confirm the payment is non-debt."
                            ),
                            entity_id=raw_payee,
                            resolution_options=["add_creditor_claim", "confirm_non_debt_payee"],
                            status="open",
                        )
                    )

        # 2. Inter-Account Transfer Tracer -> finds undisclosed bank/crypto accounts.
        known_last4s = {a.account_last4 for a in graph.assets if a.account_last4}
        closed_text = " ".join(
            h.description.lower()
            for h in graph.historical_transactions
            if h.sofa_part == "closed_account"
        )
        seen_transfer_accts: Set[str] = set()
        for stmt in graph.bank_statements:
            for tx in stmt.flagged_transactions:
                t4 = tx.target_account_last4
                if (
                    t4
                    and t4 not in known_last4s
                    and t4 not in closed_text
                    and t4 not in seen_transfer_accts
                ):
                    seen_transfer_accts.add(t4)
                    qid = f"q_undisclosed_acct_{t4}"
                    if qid in prior_answered:
                        forensic_questions.append(prior_answered[qid])
                    else:
                        forensic_questions.append(
                            EmergingQuestionItem(
                                question_id=qid,
                                rule_id="UNDISCLOSED_ACCOUNT_TRANSFER",
                                severity="critical",
                                trigger_forms=["B106AB", "B107"],
                                prompt=(
                                    f"Bank statement ({stmt.institution} ...{stmt.account_last4}) shows "
                                    f"transfer '{tx.payee_or_memo}' (${tx.amount:,.2f}) involving account "
                                    f"ending '{t4}', which is missing from Schedule A/B or SOFA."
                                ),
                                entity_id=t4,
                                resolution_options=["add_bank_account", "confirm_third_party_transfer"],
                                status="open",
                            )
                        )

        # 3. Gross vs Net check & YTD consistency across paystubs.
        by_emp_year: Dict[Tuple[str, int], List[Any]] = {}
        for ps in graph.paystubs:
            if ps.gross_pay.value < ps.net_pay.value:
                tensions.append(
                    TensionObject(
                        tension_id=f"tension_gross_lt_net_{ps.paystub_id}",
                        involved_claim_ids=[ps.paystub_id],
                        severity="blocker",
                        description=(
                            f"Paystub {ps.paystub_id} ({ps.employer}) reports gross pay "
                            f"${ps.gross_pay.value:,.2f} < net pay ${ps.net_pay.value:,.2f}."
                        ),
                    )
                )
            by_emp_year.setdefault((ps.employer, ps.pay_date.year), []).append(ps)

        for (emp, yr), stubs in by_emp_year.items():
            ytd_stubs = sorted(
                (s for s in stubs if s.ytd_gross is not None),
                key=lambda s: s.pay_date,
            )
            for idx in range(len(ytd_stubs) - 1):
                prev_s, curr_s = ytd_stubs[idx], ytd_stubs[idx + 1]
                ytd_delta = curr_s.ytd_gross.value - prev_s.ytd_gross.value  # type: ignore[union-attr]
                intervening_sum = sum(
                    (
                        s.gross_pay.value
                        for s in stubs
                        if prev_s.pay_date < s.pay_date <= curr_s.pay_date
                    ),
                    Decimal("0.00"),
                )
                if abs(ytd_delta - intervening_sum) > Decimal("50.00"):
                    tensions.append(
                        TensionObject(
                            tension_id=f"tension_cmi_vs_ytd_{_slug(emp)}_{yr}_{curr_s.paystub_id}",
                            involved_claim_ids=[prev_s.paystub_id, curr_s.paystub_id],
                            severity="blocker",
                            description=(
                                f"YTD progression for {emp} ({yr}) changed by ${ytd_delta:,.2f} "
                                f"between {prev_s.pay_date} and {curr_s.pay_date}, but intervening "
                                f"paystubs sum to ${intervening_sum:,.2f} (missing stub or misread gross)."
                            ),
                        )
                    )
                    break

        # 4. Unexplained non-payroll deposits in bank statements during 6-month window.
        lb_start = calculations.means_test.lookback_start
        lb_end = calculations.means_test.lookback_end
        non_payroll_total = Decimal("0.00")
        stmt_ids: List[str] = []
        for stmt in graph.bank_statements:
            if stmt.period_end >= lb_start and stmt.period_start <= lb_end:
                diff = stmt.total_deposits.value - stmt.payroll_deposits.value
                if diff > Decimal("0.00"):
                    non_payroll_total += diff
                    stmt_ids.append(stmt.statement_id)
        if non_payroll_total > Decimal("1500.00"):
            tensions.append(
                TensionObject(
                    tension_id="tension_unexplained_bank_deposits",
                    involved_claim_ids=stmt_ids,
                    severity="blocker",
                    description=(
                        f"Bank statements show ${non_payroll_total:,.2f} in non-payroll deposits "
                        f"during the 6-month CMI window ({lb_start} to {lb_end}). Explain source "
                        "(side-gig income, transfers, or reimbursements) before Form 122A/C lock."
                    ),
                )
            )

        # 5. Household size conflict (Form 122A-1 vs Tax Return vs Schedule J dependents).
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        filer_adults = sum(
            1 for p in graph.parties if p.role in ("debtor_1", "debtor_2_spouse")
        )
        if debtor_1 is not None:
            hh = debtor_1.household_size.value
            if graph.budget.dependents_count is not None:
                budget_hh = filer_adults + graph.budget.dependents_count.value
                if budget_hh != hh:
                    tensions.append(
                        TensionObject(
                            tension_id="tension_household_vs_budget",
                            involved_claim_ids=["party_debtor_1", "budget_dependents"],
                            severity="blocker",
                            description=(
                                f"Form 122 household size ({hh}) conflicts with Schedule I/J "
                                f"household count ({budget_hh}: {filer_adults} filer(s) + "
                                f"{graph.budget.dependents_count.value} dependent(s))."
                            ),
                        )
                    )
            if graph.tax_returns:
                latest_tr = max(graph.tax_returns, key=lambda t: t.tax_year)
                tax_adults = 2 if latest_tr.filing_status == "mfj" else 1
                tax_hh = tax_adults + latest_tr.dependents_count.value
                if tax_hh != hh:
                    tensions.append(
                        TensionObject(
                            tension_id="tension_household_vs_tax",
                            involved_claim_ids=["party_debtor_1", f"tax_{latest_tr.tax_year}"],
                            severity="blocker",
                            description=(
                                f"Means Test household size ({hh}) differs from {latest_tr.tax_year} "
                                f"Form 1040 filing size ({tax_hh}). Reconcile dependents or household change."
                            ),
                        )
                    )

        # 6. Schedule I/J vs Means Test divergence (non-blocking warning unless extreme).
        ij_net = calculations.schedule_ij_monthly_net
        mt_disp = calculations.means_test.monthly_disposable_income
        if (
            (graph.budget.income_items or graph.budget.expense_items)
            and abs(ij_net - mt_disp) > Decimal("750.00")
        ):
            tensions.append(
                TensionObject(
                    tension_id="tension_schedule_ij_vs_means_test",
                    involved_claim_ids=["schedule_ij", "means_test"],
                    severity="warning",
                    description=(
                        f"Schedule I - J monthly net (${ij_net:,.2f}) diverges from Means Test "
                        f"disposable income (${mt_disp:,.2f}) by > $750/mo; document IRS standard variance."
                    ),
                )
            )

        # 7. Chapter 13 feasibility gate (11 U.S.C. § 1325(a)(6)).
        if (
            graph.chapter == "13"
            and calculations.ch13_plan is not None
            and not calculations.ch13_plan.plan_is_feasible
        ):
            tensions.append(
                TensionObject(
                    tension_id="tension_ch13_plan_infeasible",
                    involved_claim_ids=["schedule_ij", "ch13_plan"],
                    severity="blocker",
                    description=(
                        f"Chapter 13 Plan infeasible under 11 U.S.C. § 1325(a)(6): minimum monthly "
                        f"plan payment (${calculations.ch13_plan.estimated_monthly_plan_payment:,.2f}) "
                        f"exceeds Schedule I - J net income (${calculations.ch13_plan.schedule_ij_monthly_net:,.2f}) "
                        f"by ${calculations.ch13_plan.feasibility_shortfall_monthly:,.2f}/mo."
                    ),
                )
            )

        # 8. 180-day windfall check (11 U.S.C. § 541(a)(5)).
        for hist in graph.historical_transactions:
            if hist.sofa_part == "windfall_180_day" and not hist.linked_asset_id and not any(
                a.category in ("trust_inheritance", "life_insurance_csv") for a in graph.assets
            ):
                tensions.append(
                    TensionObject(
                        tension_id=f"tension_180_day_windfall_{hist.tx_id}",
                        involved_claim_ids=[hist.tx_id],
                        severity="warning",
                        description=(
                            f"180-day post-petition windfall item ('{hist.description}') may become "
                            "estate property under 11 U.S.C. § 541(a)(5) unless scheduled and exempted."
                        ),
                    )
                )

        return forensic_questions, tensions


class PlausibilityAuditEngine:
    """Statistical & qualitative sanity auditor (plus optional LLM Decisions API review)."""

    def audit(
        self,
        graph: CanonicalCaseGraph,
        calculations: CalculationSummary,
        llm_provider: Optional[LLMProvider] = None,
    ) -> List[TensionObject]:
        """Evaluates baseline plausibility heuristics across budgets and total debt.

        Args:
            graph: Populated `CanonicalCaseGraph`.
            calculations: Deterministic `CalculationSummary`.
            llm_provider: Optional provider for calibrated rubric decision checks.

        Returns:
            List of non-blocking `TensionObject` (`severity="warning"`) advisories.
        """
        warnings: List[TensionObject] = []

        if graph.budget.expense_items:
            exp_by_cat: Dict[str, Decimal] = {}
            for item in graph.budget.expense_items:
                exp_by_cat[item.category] = (
                    exp_by_cat.get(item.category, Decimal("0.00")) + item.monthly_amount.value
                )
            if exp_by_cat.get("food_and_housekeeping", Decimal("0.00")) <= Decimal("0.00"):
                warnings.append(
                    TensionObject(
                        tension_id="plaus_zero_food",
                        involved_claim_ids=["schedule_j"],
                        severity="warning",
                        description="Schedule J lists $0.00 for food & housekeeping supplies.",
                    )
                )
            if exp_by_cat.get("utilities", Decimal("0.00")) <= Decimal("0.00"):
                warnings.append(
                    TensionObject(
                        tension_id="plaus_zero_utilities",
                        involved_claim_ids=["schedule_j"],
                        severity="warning",
                        description="Schedule J lists $0.00 for electricity/water/utilities.",
                    )
                )
            has_vehicle = any(a.category == "vehicle" for a in graph.assets)
            if has_vehicle and exp_by_cat.get("transportation_fuel_insurance", Decimal("0.00")) <= Decimal("0.00"):
                warnings.append(
                    TensionObject(
                        tension_id="plaus_vehicle_no_insurance",
                        involved_claim_ids=["schedule_ab", "schedule_j"],
                        severity="warning",
                        description="Vehicle listed on Schedule A/B, but Schedule J lists $0.00 for auto insurance/fuel.",
                    )
                )

        # Anomalously low unsecured debt relative to income suggests missing credit report / bills.
        total_debt = (
            calculations.total_secured_debt
            + calculations.total_priority_debt
            + calculations.total_general_unsecured_debt
        )
        if (
            graph.chapter == "7"
            and calculations.means_test.annualized_cmi >= Decimal("60000.00")
            and total_debt < Decimal("10000.00")
        ):
            warnings.append(
                TensionObject(
                    tension_id="plaus_anomalously_low_debt",
                    involved_claim_ids=["schedule_ef", "means_test"],
                    severity="warning",
                    description=(
                        f"Annualized CMI is ${calculations.means_test.annualized_cmi:,.2f} while total "
                        f"scheduled debt is only ${total_debt:,.2f}; verify whether credit report, "
                        "medical bills, or collection accounts were omitted."
                    ),
                )
            )

        # Optional calibrated LLM plausibility score via Decisions API (non-blocking).
        if llm_provider is not None and type(llm_provider).__name__ != "MockLLMProvider":
            try:
                summary_prompt = (
                    f"Chapter {graph.chapter}, CMI ${calculations.means_test.current_monthly_income}, "
                    f"Assets={len(graph.assets)}, Claims={len(graph.claims)}, "
                    f"Total Debt=${total_debt}"
                )
                batch = llm_provider.evaluate_decisions(
                    context=summary_prompt,
                    questions=[
                        {
                            "question_id": "missing_accounts_likelihood",
                            "question_type": "noul",
                            "question": "Is it likely key accounts or debts are omitted from this case?",
                        }
                    ],
                )
                ans = batch.answers.get("missing_accounts_likelihood")
                if ans and ans.noul is not None and ans.noul >= 0.70:
                    warnings.append(
                        TensionObject(
                            tension_id="plaus_llm_missing_accounts",
                            involved_claim_ids=["case_graph"],
                            severity="warning",
                            description=(
                                f"Calibrated plausibility check flagged high omission likelihood "
                                f"(p={ans.noul:.2f}). Double-check credit report and closed accounts."
                            ),
                        )
                    )
            except Exception:
                # Non-blocking diagnostic check; never breaks deterministic pipeline.
                pass

        return warnings


class FilingReadinessGate:
    """Enforces the strict zero-doubt compiler gate (`READY` vs `BLOCKED`)."""

    def __init__(self, registry: Optional[StatutoryTableRegistry] = None) -> None:
        """Initializes the readiness gate with optional statutory table staleness checks.

        Args:
            registry: Optional `StatutoryTableRegistry` for effective-date staleness enforcement.
        """
        self.registry = registry

    @staticmethod
    def find_unverified_field_paths(graph: CanonicalCaseGraph) -> List[str]:
        """Recursively locates all `ProvenanceField` paths lacking verified or overridden status.

        Args:
            graph: `CanonicalCaseGraph` to inspect.

        Returns:
            Sorted list of dotted paths to unverified or contradicted `ProvenanceField`s.
        """
        unverified: List[str] = []

        def _walk(obj: Any, prefix: str) -> None:
            if isinstance(obj, ProvenanceField):
                if obj.verification_status not in ("verified", "human_overridden"):
                    unverified.append(f"{prefix} ({obj.verification_status})")
                return
            if isinstance(obj, list):
                for idx, item in enumerate(obj):
                    _walk(item, f"{prefix}[{idx}]")
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _walk(v, f"{prefix}.{k}" if prefix else str(k))
                return
            if isinstance(obj, BaseModel):
                for fname in type(obj).model_fields:
                    val = getattr(obj, fname)
                    if val is not None:
                        next_prefix = f"{prefix}.{fname}" if prefix else fname
                        _walk(val, next_prefix)

        _walk(graph, "")
        return sorted(unverified)

    def evaluate(
        self,
        state: BankruptcyCaseState,
        required_forms: Optional[List[str]] = None,
        packet_validation_errors: Optional[List[str]] = None,
    ) -> FilingReadinessReport:
        """Evaluates whether `state` meets every strict zero-doubt filing invariant.

        Args:
            state: Current `BankruptcyCaseState`.
            required_forms: Form IDs planned by `FormPacketPlanner`.
            packet_validation_errors: Optional PDF/matrix validation failures.

        Returns:
            `FilingReadinessReport` with `status == "READY"` only when zero blockers exist.
        """
        unverified_paths = self.find_unverified_field_paths(state.case_graph)
        open_critical_qs = [
            f"{q.question_id}: {q.prompt}"
            for q in state.emerging_questions
            if q.severity == "critical" and q.status != "answered"
        ]
        unresolved_blockers = [
            f"{t.tension_id}: {t.description}"
            for t in state.tensions
            if t.severity == "blocker" and t.tension_id not in state.resolved_tension_records
        ]
        pkt_errors = list(packet_validation_errors or [])

        # District/Chapter capability check (validated CACB Case Upload constraint).
        if state.case_graph.chapter == "11_subv" and state.case_graph.district == "CACB":
            pkt_errors.append(
                "CACB CM/ECF Case Upload supports complete Chapter 7 and Chapter 13 only (not Chapter 11)."
            )

        blocking_reasons: List[str] = []
        if unverified_paths:
            blocking_reasons.append(
                f"{len(unverified_paths)} unverified/contradicted field(s) lack provenance or human override."
            )
        if open_critical_qs:
            blocking_reasons.append(
                f"{len(open_critical_qs)} critical emerging/completeness question(s) remain open."
            )
        if unresolved_blockers:
            blocking_reasons.append(
                f"{len(unresolved_blockers)} critical contradiction(s) remain unresolved."
            )
        if pkt_errors:
            blocking_reasons.append(
                f"{len(pkt_errors)} district packet validation error(s) detected."
            )
        if self.registry is not None:
            stale_warnings = self.registry.check_staleness(state.case_graph.expected_filing_date)
            for sw in stale_warnings:
                blocking_reasons.append(sw)

        status = "READY" if not blocking_reasons else "BLOCKED"
        return FilingReadinessReport(
            status=status,
            unverified_field_paths=unverified_paths,
            unresolved_critical_questions=open_critical_qs,
            unresolved_critical_tensions=unresolved_blockers,
            packet_validation_errors=pkt_errors,
            required_forms=list(required_forms or []),
            blocking_reasons=blocking_reasons,
        )
