"""Orchestration service for the standalone Bankruptcy Case Workbench application."""

from __future__ import annotations

import datetime
import hashlib
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from app.compilers.bankruptcy.bundle_adapter import (
    BankruptcyBundleCompiler,
    build_ledger_snapshot,
)
from app.compilers.bankruptcy.calculators import compute_case_calculations
from app.compilers.bankruptcy.districts import get_district_adapter
from app.compilers.bankruptcy.extractor import BankruptcyCaseExtractor
from app.compilers.bankruptcy.form_binder import AcroFormFillerAndBaker, FormPacketPlanner
from app.compilers.bankruptcy.rules_auditor import (
    DeclarativeDependencyAuditor,
    FilingReadinessGate,
    PlausibilityAuditEngine,
    QuantitativeForensicAuditor,
)
from app.compilers.bankruptcy.schema import (
    AssetItem,
    BankruptcyCaseState,
    CanonicalCaseGraph,
    ChapterType,
    ClaimItem,
    CodebtorItem,
    CourtFilingReceipt,
    DistrictCode,
    ExecutoryContractItem,
    HistoricalTransaction,
    HumanOverrideRecord,
    ProvenanceField,
)
from app.compilers.bankruptcy.vault import (
    CredentialAndTOTPVault,
    Rule9011SignOffGate,
    SubmissionMode,
)
from app.core.compiler import AppDescriptor, PlatformContext
from app.core.ingest import MatterIngestor
from app.core.llm import LLMProvider
from app.core.ocr import LocalOCRProvider, OCRProvider
from app.core.pii import PIITokenizer
from app.core.provenance import CaseSummaryRow
from app.core.tables import StatutoryTableRegistry
from app.core.workspace import MatterWorkspace


class BankruptcyCaseService:
    """High-level coordinator for bankruptcy intake, auditing, PDF baking, and submission."""

    def __init__(
        self,
        base_dir: Path,
        ocr_provider: Optional[OCRProvider] = None,
        llm_provider: Optional[LLMProvider] = None,
    ) -> None:
        """Initializes all bankruptcy platform services anchored to `base_dir`.

        Args:
            base_dir: Workspace root directory (contains `matters/`, `canonical/`).
            ocr_provider: Optional OCR implementation (defaults to `LocalOCRProvider`).
            llm_provider: Optional LLM provider for extraction & calibrated decisions.
        """
        self.base_dir = base_dir
        self.matters_root = base_dir / "matters"
        self.tables_dir = base_dir / "canonical" / "tables" / "bankruptcy"
        self.templates_dir = self.tables_dir / "templates"

        self.tokenizer = PIITokenizer(self.matters_root)
        self.ocr_provider = ocr_provider or LocalOCRProvider()
        self.ingestor = MatterIngestor(
            matters_root=self.matters_root,
            ocr_provider=self.ocr_provider,
            pii_tokenizer=self.tokenizer,
        )
        self.registry = StatutoryTableRegistry(self.tables_dir)
        self.llm_provider = llm_provider
        self.extractor = BankruptcyCaseExtractor()
        self.dep_auditor = DeclarativeDependencyAuditor(self.registry)
        self.forensic_auditor = QuantitativeForensicAuditor()
        self.plaus_auditor = PlausibilityAuditEngine()
        self.gate = FilingReadinessGate(self.registry)
        self.planner = FormPacketPlanner()
        self.bundle_compiler = BankruptcyBundleCompiler(self.registry)
        self.pdf_baker = AcroFormFillerAndBaker(self.templates_dir, self.tokenizer)
        self.vault = CredentialAndTOTPVault(self.matters_root / "_vault" / "credentials.json")
        self.rule9011 = Rule9011SignOffGate()

    def _case_path(self, matter_id: str) -> Path:
        return self.matters_root / matter_id / "bankruptcy_case.json"

    def _packet_dir(self, matter_id: str) -> Path:
        return self.matters_root / matter_id / "packet"

    def list_cases(self) -> List[Dict[str, Any]]:
        """Lists all bankruptcy case matters on disk with status summaries."""
        if not self.matters_root.exists():
            return []
        items: List[Dict[str, Any]] = []
        for entry in sorted(self.matters_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            cpath = entry / "bankruptcy_case.json"
            if not cpath.exists():
                continue
            try:
                state = BankruptcyCaseState.model_validate_json(cpath.read_text(encoding="utf-8"))
                items.append(
                    {
                        "matter_id": state.case_graph.matter_id,
                        "chapter": state.case_graph.chapter,
                        "district": state.case_graph.district,
                        "expected_filing_date": state.case_graph.expected_filing_date.isoformat(),
                        "readiness_status": state.readiness.status if state.readiness else "BLOCKED",
                        "open_questions": sum(
                            1 for q in state.emerging_questions if q.status == "open"
                        ),
                        "open_tensions": sum(
                            1
                            for t in state.tensions
                            if t.severity == "blocker"
                            and t.tension_id not in state.resolved_tension_records
                        ),
                        "updated_at": state.updated_at,
                    }
                )
            except Exception:
                continue
        return items

    def load_case(self, matter_id: str) -> BankruptcyCaseState:
        """Loads persisted `BankruptcyCaseState` or raises 404 if missing."""
        cpath = self._case_path(matter_id)
        if not cpath.exists():
            raise HTTPException(
                status_code=404, detail=f"Bankruptcy case '{matter_id}' not initialized."
            )
        return BankruptcyCaseState.model_validate_json(cpath.read_text(encoding="utf-8"))

    def save_case(self, state: BankruptcyCaseState) -> BankruptcyCaseState:
        """Persists `BankruptcyCaseState` atomically to `bankruptcy_case.json`."""
        cpath = self._case_path(state.case_graph.matter_id)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        updated = state.model_copy(
            update={"updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        )
        cpath.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        return updated

    def init_case(
        self,
        matter_id: str,
        chapter: ChapterType = "7",
        district: DistrictCode = "CACB",
        expected_filing_date: Optional[datetime.date] = None,
    ) -> BankruptcyCaseState:
        """Creates a new bankruptcy matter workspace and persists initial state."""
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", matter_id.strip())
        if not safe_id:
            raise HTTPException(status_code=400, detail="Invalid matter_id.")
        self.ingestor.create_matter(safe_id)
        graph = CanonicalCaseGraph(
            matter_id=safe_id,
            chapter=chapter,
            district=district,
            expected_filing_date=expected_filing_date or datetime.date(2026, 11, 16),
        )
        state = BankruptcyCaseState(case_graph=graph)
        return self.recompute_state(state)

    def recompute_state(
        self,
        state: BankruptcyCaseState,
        packet_validation_errors: Optional[List[str]] = None,
    ) -> BankruptcyCaseState:
        """Re-runs all deterministic calculators, auditors, readiness gate, and Bezier DAG."""
        calcs = compute_case_calculations(state.case_graph, self.registry)
        dep_qs = self.dep_auditor.audit(
            state.case_graph, calcs, existing_questions=state.emerging_questions
        )
        for_qs, tensions = self.forensic_auditor.audit(
            state.case_graph, calcs, existing_questions=state.emerging_questions
        )
        all_qs = dep_qs + for_qs
        plaus_warnings = self.plaus_auditor.audit(
            state.case_graph, calcs, llm_provider=self.llm_provider
        )

        interim = state.model_copy(
            update={
                "calculations": calcs,
                "emerging_questions": all_qs,
                "tensions": tensions,
                "plausibility_warnings": plaus_warnings,
            }
        )
        req_forms = self.planner.plan_required_forms(interim)
        readiness = self.gate.evaluate(
            interim,
            required_forms=req_forms,
            packet_validation_errors=packet_validation_errors,
        )
        interim = interim.model_copy(update={"readiness": readiness})
        bundle = self.bundle_compiler.compile(interim)
        final_state = interim.model_copy(update={"compiled_bundle": bundle})
        saved = self.save_case(final_state)
        MatterWorkspace(self.matters_root, saved.case_graph.matter_id).write_ledger(
            "bankruptcy", build_ledger_snapshot(saved)
        )
        return saved

    def extract_matter(
        self,
        matter_id: str,
        chapter: Optional[ChapterType] = None,
        district: Optional[DistrictCode] = None,
        expected_filing_date: Optional[datetime.date] = None,
    ) -> BankruptcyCaseState:
        """Ingests raw files and extracts/verifies entities into `BankruptcyCaseState`."""
        self.ingestor.ingest_matter(matter_id)
        try:
            existing = self.load_case(matter_id)
            base_graph = existing.case_graph.model_copy(
                update={
                    "chapter": chapter or existing.case_graph.chapter,
                    "district": district or existing.case_graph.district,
                    "expected_filing_date": expected_filing_date
                    or existing.case_graph.expected_filing_date,
                }
            )
        except HTTPException:
            existing = BankruptcyCaseState(
                case_graph=CanonicalCaseGraph(
                    matter_id=matter_id,
                    chapter=chapter or "7",
                    district=district or "CACB",
                    expected_filing_date=expected_filing_date or datetime.date(2026, 11, 16),
                )
            )
            base_graph = None

        graph = self.extractor.extract(
            matter_id=matter_id,
            ingestor=self.ingestor,
            chapter=chapter or existing.case_graph.chapter,
            district=district or existing.case_graph.district,
            expected_filing_date=expected_filing_date or existing.case_graph.expected_filing_date,
            llm_provider=self.llm_provider,
            existing_graph=base_graph,
        )
        updated = existing.model_copy(update={"case_graph": graph})
        return self.recompute_state(updated)

    def override_field(
        self,
        matter_id: str,
        field_path: str,
        new_value: Any,
        actor_name: str,
        actor_role: str,
        rationale: str,
    ) -> BankruptcyCaseState:
        """Applies an audited `HumanOverrideRecord` to a dotted `ProvenanceField` path."""
        state = self.load_case(matter_id)
        tokens = [t for t in re.split(r"\.|\[(\d+)\]", field_path) if t is not None and t != ""]
        if not tokens:
            raise HTTPException(status_code=400, detail="Empty field_path.")

        # Walk down root dict representation, locate target ProvenanceField, and rebuild.
        curr: Any = state.case_graph
        trail: List[Tuple[Any, Any]] = []
        for tok in tokens:
            if isinstance(curr, list):
                idx = int(tok)
                if idx < 0 or idx >= len(curr):
                    raise HTTPException(status_code=404, detail=f"Index {idx} out of range in {field_path}")
                trail.append((curr, idx))
                curr = curr[idx]
            elif hasattr(curr, tok):
                trail.append((curr, tok))
                curr = getattr(curr, tok)
            else:
                raise HTTPException(status_code=404, detail=f"Unknown path segment '{tok}' in {field_path}")

        if not isinstance(curr, ProvenanceField):
            raise HTTPException(status_code=400, detail=f"Target '{field_path}' is not a ProvenanceField.")

        coerced_val: Any = new_value
        if isinstance(curr.value, Decimal):
            coerced_val = Decimal(str(new_value)).quantize(Decimal("0.01"))
        elif isinstance(curr.value, int) and not isinstance(curr.value, bool):
            coerced_val = int(new_value)
        elif isinstance(curr.value, datetime.date):
            coerced_val = datetime.date.fromisoformat(str(new_value))

        new_pf = curr.model_copy(
            update={
                "value": coerced_val,
                "verification_status": "human_overridden",
                "override": HumanOverrideRecord(
                    actor_name=actor_name,
                    actor_role=actor_role,  # type: ignore[arg-type]
                    rationale=rationale,
                ),
            }
        )

        # Propagate immutable Pydantic model updates bottom-up.
        rebuilt: Any = new_pf
        for parent, key in reversed(trail):
            if isinstance(parent, list):
                copy_list = list(parent)
                copy_list[int(key)] = rebuilt
                rebuilt = copy_list
            else:
                rebuilt = parent.model_copy(update={str(key): rebuilt})

        return self.recompute_state(state.model_copy(update={"case_graph": rebuilt}))

    def answer_question(
        self,
        matter_id: str,
        question_id: str,
        selected_option: str,
        actor_name: str,
        actor_role: str,
        rationale: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> BankruptcyCaseState:
        """Resolves an `EmergingQuestionItem`, mutating `CanonicalCaseGraph` as needed."""
        state = self.load_case(matter_id)
        q = next((item for item in state.emerging_questions if item.question_id == question_id), None)
        if q is None:
            raise HTTPException(status_code=404, detail=f"Question '{question_id}' not found.")

        payload = payload or {}
        override = HumanOverrideRecord(
            actor_name=actor_name,
            actor_role=actor_role,  # type: ignore[arg-type]
            rationale=rationale,
        )
        graph = state.case_graph

        if selected_option == "confirm_free_and_clear" and q.entity_id:
            new_assets = [
                a.model_copy(update={"owned_free_and_clear": True, "attestation_note": rationale})
                if a.asset_id == q.entity_id
                else a
                for a in graph.assets
            ]
            graph = graph.model_copy(update={"assets": new_assets})
        elif selected_option == "add_or_link_collateral_asset":
            val = Decimal(str(payload.get("current_value", "0.00"))).quantize(Decimal("0.01"))
            desc = str(payload.get("description", "Collateral Vehicle/Property"))
            cat = str(payload.get("category", "vehicle"))
            aid = f"asset_collat_{len(graph.assets) + 1}"
            new_asset = AssetItem(
                asset_id=aid,
                category=cat,  # type: ignore[arg-type]
                description=desc,
                current_value=ProvenanceField[Decimal](
                    value=val,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            new_claims = [
                c.model_copy(update={"collateral_asset_id": aid})
                if c.claim_id == q.entity_id
                else c
                for c in graph.claims
            ]
            graph = graph.model_copy(
                update={"assets": list(graph.assets) + [new_asset], "claims": new_claims}
            )
        elif selected_option == "set_statement_of_intention":
            intent = str(payload.get("statement_of_intention", "retain_and_reaffirm"))
            new_claims = [
                c.model_copy(update={"statement_of_intention": intent})  # type: ignore[arg-type]
                if c.claim_id == q.entity_id
                else c
                for c in graph.claims
            ]
            graph = graph.model_copy(update={"claims": new_claims})
        elif selected_option == "add_creditor_claim":
            amt = Decimal(str(payload.get("total_claim_amount", "0.00"))).quantize(Decimal("0.01"))
            cname = str(payload.get("creditor_name", q.entity_id or "Added Creditor"))
            cid = f"claim_added_{len(graph.claims) + 1}"
            new_claim = ClaimItem(
                claim_id=cid,
                creditor_name=cname,
                creditor_address_lines=[str(payload.get("street", "PO Box 1000"))],
                city=str(payload.get("city", "Los Angeles")),
                state=str(payload.get("state", "CA")),
                zip_code=str(payload.get("zip_code", "90012")),
                priority_type=str(payload.get("priority_type", "general_unsecured")),  # type: ignore[arg-type]
                total_claim_amount=ProvenanceField[Decimal](
                    value=amt,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            graph = graph.model_copy(update={"claims": list(graph.claims) + [new_claim]})
        elif selected_option in ("add_bank_account", "add_financial_account"):
            val = Decimal(str(payload.get("current_value", "0.00"))).quantize(Decimal("0.01"))
            desc = str(payload.get("description", f"Account ({q.entity_id or 'Added'})"))
            last4 = str(payload.get("account_last4") or (q.entity_id if q.entity_id and q.entity_id.isdigit() else "")) or None
            new_asset = AssetItem(
                asset_id=f"asset_acct_{len(graph.assets) + 1}",
                category="bank_account",
                description=desc,
                account_last4=last4,
                current_value=ProvenanceField[Decimal](
                    value=val,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            graph = graph.model_copy(update={"assets": list(graph.assets) + [new_asset]})
        elif selected_option == "add_retirement_asset":
            val = Decimal(str(payload.get("current_value", "0.00"))).quantize(Decimal("0.01"))
            new_asset = AssetItem(
                asset_id=f"asset_ret_{len(graph.assets) + 1}",
                category="retirement",
                description=str(payload.get("description", "Employer 401(k) Plan")),
                current_value=ProvenanceField[Decimal](
                    value=val,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            graph = graph.model_copy(update={"assets": list(graph.assets) + [new_asset]})
        elif selected_option == "confirm_closed_account":
            graph = graph.model_copy(
                update={
                    "historical_transactions": list(graph.historical_transactions)
                    + [
                        HistoricalTransaction(
                            tx_id=f"sofa_closed_{len(graph.historical_transactions) + 1}",
                            sofa_part="closed_account",
                            description=f"Closed account {q.entity_id or ''} — {rationale}",
                        )
                    ]
                }
            )
        elif selected_option == "confirm_zero_income_month" and q.entity_id:
            if q.entity_id not in graph.zero_income_attested_months:
                graph = graph.model_copy(
                    update={
                        "zero_income_attested_months": list(graph.zero_income_attested_months)
                        + [q.entity_id]
                    }
                )
        elif selected_option == "confirm_month_to_month":
            graph = graph.model_copy(update={"month_to_month_lease_attested": True})
        elif selected_option == "add_lease_on_g":
            graph = graph.model_copy(
                update={
                    "executory_contracts": list(graph.executory_contracts)
                    + [
                        ExecutoryContractItem(
                            contract_id=f"lease_{len(graph.executory_contracts) + 1}",
                            counterparty=str(payload.get("counterparty", "Residential Landlord")),
                            description=str(payload.get("description", "Residential Apartment Lease")),
                            contract_type="residential_lease",
                        )
                    ]
                }
            )
        elif selected_option == "add_codebtor_on_h":
            graph = graph.model_copy(
                update={
                    "codebtors": list(graph.codebtors)
                    + [
                        CodebtorItem(
                            codebtor_id=f"codeb_{len(graph.codebtors) + 1}",
                            name=str(payload.get("name", "Co-Signer")),
                            address=str(payload.get("address", "California")),
                            linked_claim_id=q.entity_id,
                        )
                    ]
                }
            )
        elif selected_option == "supply_homestead_dates":
            acq = datetime.date.fromisoformat(str(payload.get("acquisition_date", "2019-01-01")))
            dom_days = int(payload.get("domicile_days", 1500))
            new_assets = [
                a.model_copy(
                    update={
                        "acquisition_date": ProvenanceField[datetime.date](
                            value=acq,
                            verification_status="human_overridden",
                            override=override,
                        )
                    }
                )
                if a.asset_id == q.entity_id
                else a
                for a in graph.assets
            ]
            new_parties = [
                p.model_copy(
                    update={
                        "ca_domicile_days_continuous": ProvenanceField[int](
                            value=dom_days,
                            verification_status="human_overridden",
                            override=override,
                        )
                    }
                )
                if p.role == "debtor_1"
                else p
                for p in graph.parties
            ]
            graph = graph.model_copy(update={"assets": new_assets, "parties": new_parties})
        elif selected_option == "add_unliquidated_claim_asset":
            claim_cat = str(payload.get("category", "personal_injury"))
            is_unk = str(payload.get("valuation_state", "unknown")).lower() == "unknown" or str(payload.get("current_value", "")).strip().lower() in ("", "unknown")
            val = Decimal("0.00") if is_unk else Decimal(str(payload.get("current_value", "0.00"))).quantize(Decimal("0.01"))
            desc = str(payload.get("description", f"Unliquidated Injury / Workers Comp Claim ({q.entity_id or 'Schedule A/B Line 33'})"))
            new_asset = AssetItem(
                asset_id=f"asset_claim_{len(graph.assets) + 1}",
                category=claim_cat,  # type: ignore[arg-type]
                description=desc,
                valuation_state="unknown" if is_unk else "estimated",
                claim_100pct_fmv_exemption=True,
                current_value=ProvenanceField[Decimal](
                    value=val,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            graph = graph.model_copy(update={"assets": list(graph.assets) + [new_asset]})
        elif selected_option == "confirm_no_injury_claim":
            graph = graph.model_copy(update={"no_injury_or_wc_claim_attested": True})
        elif selected_option == "sync_lawsuit_to_schedule_ab":
            tx = next((h for h in graph.historical_transactions if h.tx_id == q.entity_id), None)
            claim_cat = str(payload.get("category", "legal_claims"))
            aid = f"asset_sofa_{len(graph.assets) + 1}"
            is_unk = str(payload.get("valuation_state", "unknown")).lower() == "unknown"
            val = Decimal("0.00") if is_unk else Decimal(str(payload.get("current_value", "0.00"))).quantize(Decimal("0.01"))
            new_asset = AssetItem(
                asset_id=aid,
                category=claim_cat,  # type: ignore[arg-type]
                description=str(payload.get("description") or (tx.description if tx else "SOFA Plaintiff Action")),
                valuation_state="unknown" if is_unk else "estimated",
                claim_100pct_fmv_exemption=True,
                current_value=ProvenanceField[Decimal](
                    value=val,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            new_hist = [
                h.model_copy(update={"linked_asset_id": aid}) if h.tx_id == q.entity_id else h
                for h in graph.historical_transactions
            ]
            graph = graph.model_copy(
                update={"assets": list(graph.assets) + [new_asset], "historical_transactions": new_hist}
            )
        elif selected_option == "sync_lawsuit_to_schedule_ef":
            tx = next((h for h in graph.historical_transactions if h.tx_id == q.entity_id), None)
            cid = f"claim_sofa_{len(graph.claims) + 1}"
            amt = Decimal(
                str(payload.get("total_claim_amount") or (tx.amount.value if tx and tx.amount else "0.00"))
            ).quantize(Decimal("0.01"))
            new_claim = ClaimItem(
                claim_id=cid,
                creditor_name=str(payload.get("creditor_name") or (tx.description if tx else "Lawsuit Plaintiff")),
                priority_type="general_unsecured",
                disputed=True,
                contingent=bool(payload.get("contingent", True)),
                unliquidated=bool(payload.get("unliquidated", True)),
                total_claim_amount=ProvenanceField[Decimal](
                    value=amt,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            new_hist = [
                h.model_copy(update={"linked_claim_id": cid}) if h.tx_id == q.entity_id else h
                for h in graph.historical_transactions
            ]
            graph = graph.model_copy(
                update={"claims": list(graph.claims) + [new_claim], "historical_transactions": new_hist}
            )
        elif selected_option == "add_security_deposit_asset":
            val = Decimal(str(payload.get("current_value", "1500.00"))).quantize(Decimal("0.01"))
            new_asset = AssetItem(
                asset_id=f"asset_dep_{len(graph.assets) + 1}",
                category="security_deposit",
                description=str(payload.get("description", "Residential Landlord / Utility Security Deposit")),
                current_value=ProvenanceField[Decimal](
                    value=val,
                    verification_status="human_overridden",
                    override=override,
                ),
            )
            graph = graph.model_copy(update={"assets": list(graph.assets) + [new_asset]})
        elif selected_option == "confirm_no_security_deposit":
            graph = graph.model_copy(update={"no_security_deposit_attested": True})
        elif selected_option == "attest_payment_advices_exception":
            graph = graph.model_copy(update={"payment_advices_exception_attested": True})
        elif selected_option == "apply_522p_rollover":
            roll_amt = Decimal(str(payload.get("rollover_amount", "0.00"))).quantize(Decimal("0.01"))
            new_assets = [
                a.model_copy(update={"prior_state_residence_rollover_amount": roll_amt})
                if a.asset_id == q.entity_id
                else a
                for a in graph.assets
            ]
            graph = graph.model_copy(update={"assets": new_assets, "homestead_rollover_reviewed": True})
        elif selected_option == "confirm_no_rollover":
            graph = graph.model_copy(update={"homestead_rollover_reviewed": True})
        elif selected_option == "confirm_spousal_waiver_signed":
            graph = graph.model_copy(update={"spousal_703_waiver_signed": True})
        elif selected_option == "switch_to_704_regime":
            graph = graph.model_copy(update={"selected_exemption_regime": "CA_CCP_704"})
        elif selected_option == "confirm_unknown_within_cap":
            graph = graph.model_copy(update={"unknown_valuation_cap_reviewed": True})
        elif selected_option == "confirm_mandatory_asset_and_windfall_sweep":
            graph = graph.model_copy(
                update={"mandatory_asset_sweep_attested": True, "windfall_180_day_attested": True}
            )
        elif selected_option == "confirm_4yr_tax_returns":
            years = [graph.expected_filing_date.year - i for i in range(1, 5)]
            graph = graph.model_copy(update={"tax_years_filed_4yr": years})

        # Mark question answered with audit record (preserves decision even for attestations).
        updated_qs = [
            item.model_copy(
                update={
                    "status": "answered",
                    "selected_option": selected_option,
                    "override": override,
                }
            )
            if item.question_id == question_id
            else item
            for item in state.emerging_questions
        ]
        return self.recompute_state(
            state.model_copy(update={"case_graph": graph, "emerging_questions": updated_qs})
        )

    def resolve_tension(
        self,
        matter_id: str,
        tension_id: str,
        actor_name: str,
        actor_role: str,
        rationale: str,
    ) -> BankruptcyCaseState:
        """Marks a `TensionObject` resolved with an audited `HumanOverrideRecord`."""
        state = self.load_case(matter_id)
        records = dict(state.resolved_tension_records)
        records[tension_id] = HumanOverrideRecord(
            actor_name=actor_name,
            actor_role=actor_role,  # type: ignore[arg-type]
            rationale=rationale,
        )
        return self.recompute_state(
            state.model_copy(update={"resolved_tension_records": records})
        )

    def compile_packet(
        self, matter_id: str, allow_draft: bool = False
    ) -> Dict[str, Any]:
        """Compiles court-ready baked PDFs, matrices, and `field_lineage.json` under strict gates."""
        state = self.recompute_state(self.load_case(matter_id))
        if state.readiness and state.readiness.status != "READY" and not allow_draft:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "FilingReadinessGate BLOCKED packet compilation.",
                    "readiness": state.readiness.model_dump(mode="json"),
                },
            )

        packet_dir = self._packet_dir(matter_id)
        if packet_dir.exists():
            for stale in packet_dir.iterdir():
                if stale.is_file():
                    stale.unlink()
        packet_dir.mkdir(parents=True, exist_ok=True)

        pdfs, lineage_path, lineage = self.pdf_baker.compile_forms(
            state, packet_dir, watermark_draft=(state.readiness.status != "READY" if state.readiness else True)
        )
        adapter = get_district_adapter(state.case_graph.district)
        matrix_txt, matrix_notes = adapter.format_creditor_matrix(state.case_graph)
        matrix_path = packet_dir / "creditor_matrix.txt"
        matrix_path.write_text(matrix_txt, encoding="utf-8")

        debtor_txt = adapter.format_debtor_txt(state.case_graph, self.tokenizer)
        debtor_path = packet_dir / "debtor.txt"
        debtor_path.write_text(debtor_txt, encoding="utf-8")

        packaged_pdfs, pkg_errors = adapter.package_pdfs(
            packet_dir, pdfs, state.case_graph.chapter
        )
        all_files = packaged_pdfs + [matrix_path, debtor_path, lineage_path]
        final_state = self.recompute_state(
            state.model_copy(update={"last_packet_files": [p.name for p in all_files]}),
            packet_validation_errors=pkg_errors,
        )
        if pkg_errors and not allow_draft:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "District packet validation failed.",
                    "errors": pkg_errors,
                },
            )

        return {
            "matter_id": matter_id,
            "district": state.case_graph.district,
            "readiness": final_state.readiness.model_dump(mode="json") if final_state.readiness else None,
            "files": final_state.last_packet_files,
            "matrix_notes": matrix_notes,
            "lineage_count": len(lineage),
        }

    def record_signed_declaration(
        self, matter_id: str, raw_bytes: bytes
    ) -> BankruptcyCaseState:
        """Records uploaded wet-signed Electronic Filing Declaration SHA-256 on the case."""
        state = self.load_case(matter_id)
        digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
        decl_path = self.matters_root / matter_id / "inputs" / "raw" / "signed_declaration.pdf"
        decl_path.parent.mkdir(parents=True, exist_ok=True)
        decl_path.write_bytes(raw_bytes)
        new_graph = state.case_graph.model_copy(
            update={
                "signed_declaration_uploaded": True,
                "signed_declaration_sha256": digest,
            }
        )
        return self.recompute_state(state.model_copy(update={"case_graph": new_graph}))

    def submit_to_court(
        self,
        matter_id: str,
        submission_mode: SubmissionMode,
        attorney_name: str,
        attorney_bar_number: str,
        attested: bool,
    ) -> CourtFilingReceipt:
        """Validates Rule 9011 gate & TOTP vault, then executes district filing driver."""
        state = self.load_case(matter_id)
        packet_dir = self._packet_dir(matter_id)
        if not state.last_packet_files or not packet_dir.exists():
            raise HTTPException(
                status_code=400, detail="Compile Official Filing Packet before submitting."
            )
        packet_files = [packet_dir / fn for fn in state.last_packet_files if (packet_dir / fn).exists()]

        # Ensure attorney metadata is synced onto graph before token minting.
        updated_graph = state.case_graph.model_copy(
            update={
                "attorney_name": attorney_name,
                "attorney_bar_number": attorney_bar_number,
            }
        )
        state = state.model_copy(update={"case_graph": updated_graph})

        try:
            token = self.rule9011.mint_token(
                state=state,
                packet_files=packet_files,
                attorney_name=attorney_name,
                attorney_bar_number=attorney_bar_number,
                attested=attested,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        if submission_mode == "ecf_train":
            try:
                totp = self.vault.generate_totp_code("ecf_train")
            except KeyError:
                self.vault.save_credential(
                    "ecf_train",
                    "ca_train_student",
                    "TrainOnlyPass!",
                    "JBSWY3DPEHPK3PXP",
                    sponsoring_bar_number=attorney_bar_number,
                )
                totp = self.vault.generate_totp_code("ecf_train")
        else:
            try:
                totp = self.vault.generate_totp_code(submission_mode)
            except KeyError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Credential mode '{submission_mode}' is not configured in vault.",
                ) from exc

        adapter = get_district_adapter(state.case_graph.district)
        receipt = adapter.submit_packet(
            state=state,
            packet_files=packet_files,
            submission_mode=submission_mode,
            attorney_name=token.attorney_name,
            attorney_bar_number=token.attorney_bar_number,
            totp_code=totp,
        )
        final_state = state.model_copy(
            update={"filing_receipts": list(state.filing_receipts) + [receipt]}
        )
        self.save_case(final_state)
        return receipt


class BankruptcyCompilerApp:
    """`CompilerApp` adapter registering Bankruptcy Case Workbench into `app.server`."""

    descriptor = AppDescriptor(
        app_id="bankruptcy",
        label="Bankruptcy Workbench",
        description="Chapter 7 & 13 statutory calculators, exemptions, means test, and baked court PDFs.",
        ui_route="/bankruptcy",
        api_prefix="/api/v1/bankruptcy",
        gate_mode="strict_blocking",
    )

    def __init__(self, service: BankruptcyCaseService) -> None:
        self.service = service

    def list_cases(self) -> List[CaseSummaryRow]:
        """Returns standardized `CaseSummaryRow` items for all bankruptcy cases."""
        rows: List[CaseSummaryRow] = []
        for item in self.service.list_cases():
            rows.append(
                CaseSummaryRow(
                    matter_id=item["matter_id"],
                    app_id="bankruptcy",
                    title=f"{item['matter_id']} — Ch. {item['chapter']} ({item['district']})",
                    status=item["readiness_status"],
                    open_blockers=int(item.get("open_questions", 0)) + int(item.get("open_tensions", 0)),
                    metrics={
                        "chapter": str(item["chapter"]),
                        "district": str(item["district"]),
                        "filing_date": str(item["expected_filing_date"]),
                    },
                    updated_at=str(item.get("updated_at", "")),
                )
            )
        return rows

    def build_router(self, ctx: PlatformContext) -> APIRouter:
        """Builds the `/api/v1/bankruptcy` router mounted on the shared platform app."""
        from app.compilers.bankruptcy.routes import build_bankruptcy_router

        return build_bankruptcy_router(self.service)
