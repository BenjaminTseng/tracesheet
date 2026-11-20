# Run: uv run pytest tests/test_bk_extractor_and_bundle.py -v
"""Deep tests for uncategorized multi-form PDF extraction and Bezier CompiledBundle DAG."""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pymupdf

from app.compilers.bankruptcy.calculators import compute_case_calculations
from app.compilers.bankruptcy.extractor import (
    BankruptcyCaseExtractor,
    CaseExtractionDraft,
    ExtractedClaimDraft,
    ExtractedLocatorRef,
    ExtractedPaystubDraft,
)
from app.compilers.bankruptcy.bundle_adapter import BankruptcyBundleCompiler
from app.compilers.bankruptcy.rules_auditor import (
    DeclarativeDependencyAuditor,
    QuantitativeForensicAuditor,
)
from app.compilers.bankruptcy.schema import BankruptcyCaseState
from app.core.ingest import MatterIngestor
from app.core.ocr import LocalOCRProvider
from app.core.pii import PIITokenizer
from app.core.tables import StatutoryTableRegistry


def _write_pdf(path: Path, lines: list[str]) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 72
    for ln in lines:
        page.insert_text((72, y), ln, fontsize=10.5)
        y += 16
    doc.save(str(path))
    doc.close()


def test_uncategorized_multi_form_fanout_and_compiled_bundle_dag(tmp_path: Path) -> None:
    """Verifies raw PDFs fan out to multiple schedules and compile into a valid L0->L1->L2+ DAG."""
    matters_root = tmp_path / "matters"
    tokenizer = PIITokenizer(matters_root)
    ingestor = MatterIngestor(
        matters_root=matters_root,
        ocr_provider=LocalOCRProvider(),
        pii_tokenizer=tokenizer,
    )
    matter_dir = ingestor.create_matter("bk_fanout")
    raw_dir = matter_dir / "inputs" / "raw"

    _write_pdf(
        raw_dir / "01_intake.pdf",
        [
            "Debtor Profile & Intake Summary",
            "Debtor Name: Elena Martinez",
            "SSN: 123-45-6789",
            "Street Address: 410 Wilshire Blvd",
            "City/State/Zip: Los Angeles, CA 90010",
            "County of Residence: Los Angeles",
            "Household Size: 1",
            "CA Domicile Days: 2200",
        ],
    )
    _write_pdf(
        raw_dir / "02_toyota_auto_loan.pdf",
        [
            "Auto Finance Loan Statement",
            "Lender: Toyota Financial Services",
            "Creditor Address: PO Box 5855, Carol Stream, IL 60197",
            "Principal Balance: $14,200.00",
            "Monthly Payment: $410.00",
        ],
    )
    _write_pdf(
        raw_dir / "03_form_1040_2025.pdf",
        [
            "Form 1040 Individual Income Tax Return",
            "Tax Year: 2025",
            "Filing Status: single",
            "Dependents: 0",
            "Adjusted Gross Income: $68,400.00",
            "Total Tax: $8,120.00",
            "Refund Due: $1,250.00",
            "Schedule B Institutions: Chase",
        ],
    )
    _write_pdf(
        raw_dir / "04_paystub_oct_2026.pdf",
        [
            "ADP Earnings Statement",
            "Employer: Metro Logistics",
            "Pay Date: 2026-10-30",
            "Gross Pay: $5,400.00",
            "Net Pay: $4,050.00",
            "Tax Withheld: $1,100.00",
            "YTD Gross: $54,000.00",
        ],
    )

    ingestor.ingest_matter("bk_fanout")

    extractor = BankruptcyCaseExtractor()
    graph = extractor.extract(
        matter_id="bk_fanout",
        ingestor=ingestor,
        chapter="7",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
    )

    # Check multi-form fan-out without any manual form assignment:
    assert len(graph.parties) == 1
    assert graph.parties[0].full_name.verification_status == "verified"
    assert len(graph.claims) == 1  # Toyota auto loan
    assert graph.claims[0].total_claim_amount.verification_status == "verified"
    assert any(e.category == "vehicle_payment" for e in graph.budget.expense_items)  # Schedule J fan-out
    assert any(h.sofa_part == "income_history" for h in graph.historical_transactions)  # 1040 -> SOFA
    assert any(a.asset_id == "tax_refund_2025" for a in graph.assets)  # 1040 refund -> Schedule A/B

    # Run calculators + dependency audit + bundle compilation.
    reg = StatutoryTableRegistry(Path("canonical/tables/bankruptcy"))
    calcs = compute_case_calculations(graph, reg)
    dep_qs = DeclarativeDependencyAuditor(reg).audit(graph, calcs)
    for_qs, tensions = QuantitativeForensicAuditor().audit(graph, calcs)

    # Toyota auto loan had no Collateral Ref -> must trigger SECURED_LOAN_MISSING_COLLATERAL_VALUE!
    assert any(q.rule_id == "SECURED_LOAN_MISSING_COLLATERAL_VALUE" for q in dep_qs)

    state = BankruptcyCaseState(
        case_graph=graph,
        calculations=calcs,
        emerging_questions=dep_qs + for_qs,
        tensions=tensions,
    )
    bundle = BankruptcyBundleCompiler(reg).compile(state)

    # Verify CompiledBundle L0 -> L1 -> L2+ DAG integrity.
    ref_ids = set()
    for sec in bundle.artifact.sections:
        for match in re.findall(r"<ref\s+id=['\"]([^'\"]+)['\"]>", sec.content):
            ref_ids.add(match)
            assert match in bundle.nodes, f"Orphan <ref id='{match}'> in {sec.section_id}"
            assert bundle.nodes[match].type == "claim"

    assert len(ref_ids) >= 4
    # Every L0 claim node must trace down to at least one L1/L2+ child node with matching backlink.
    for cid in ref_ids:
        claim_node = bundle.nodes[cid]
        assert len(claim_node.direct_child_ids) >= 1
        for child_id in claim_node.direct_child_ids:
            assert cid in bundle.nodes[child_id].parent_claim_ids


def test_llm_extractor_wire_contract_pii_masking_and_enum_normalization(tmp_path: Path) -> None:
    """Spy-provider offline test verifying `BankruptcyCaseExtractor` LLM wire contract and normalization."""
    matters_root = tmp_path / "matters"
    tokenizer = PIITokenizer(matters_root)
    ingestor = MatterIngestor(
        matters_root=matters_root,
        ocr_provider=LocalOCRProvider(),
        pii_tokenizer=tokenizer,
    )
    matter_dir = ingestor.create_matter("bk_spy_llm")
    raw_dir = matter_dir / "inputs" / "raw"

    _write_pdf(
        raw_dir / "paystub_spy.pdf",
        [
            "Acme Payroll Statement",
            "Debtor Name: Jordan Lee",
            "SSN: 123-45-6789",
            "Employer: Acme Robotics",
            "Pay Date: 2026-10-15",
            "Gross Pay: $4,200.00 Net Pay: $3,100.00 Tax Withheld: $800.00",
        ],
    )
    ingestor.ingest_matter("bk_spy_llm")
    from app.core.verifier import IndexedMatterCorpus

    corpus = IndexedMatterCorpus.load_for_matter(ingestor, "bk_spy_llm")
    (fname, lkey), _ = next(iter(corpus.blocks_by_key.items()))

    captured_calls = []

    class SpyLLMProvider:
        def generate_structured(self, prompt: str, system_instruction: str, response_model):
            captured_calls.append(
                {
                    "prompt": prompt,
                    "system_instruction": system_instruction,
                    "response_model": response_model,
                }
            )
            ref = ExtractedLocatorRef(
                file_name=fname,
                locator_key=lkey,
                verbatim_quote="Gross Pay: $4,200.00 Net Pay: $3,100.00 Tax Withheld: $800.00",
            )
            name_ref = ExtractedLocatorRef(
                file_name=fname,
                locator_key=lkey,
                verbatim_quote="Debtor Name: Jordan Lee",
            )
            return CaseExtractionDraft(
                debtor_name="Jordan Lee",
                debtor_name_ref=name_ref,
                county_of_residence="Los Angeles",
                household_size=1,
                paystubs=[
                    ExtractedPaystubDraft(
                        employer="Acme Robotics",
                        pay_period_start="2026-10-01",
                        pay_period_end="2026-10-15",
                        pay_date="2026-10-15",
                        gross_pay="$4,200.00",
                        gross_ref=ref,
                        net_pay="$3,100.00",
                        net_ref=ref,
                        tax_withheld="$800.00",
                        tax_ref=ref,
                    )
                ],
                claims=[
                    ExtractedClaimDraft(
                        claim_id="c_spy_1",
                        creditor_name="Pacific Auto Finance",
                        priority_type="auto_loan",
                        total_claim_amount="3100.00",
                        amount_ref=ref,
                    )
                ],
            )

    graph = BankruptcyCaseExtractor().extract(
        matter_id="bk_spy_llm",
        ingestor=ingestor,
        chapter="7",
        district="CACB",
        llm_provider=SpyLLMProvider(),  # type: ignore[arg-type]
    )

    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["response_model"] is CaseExtractionDraft
    assert "[PII:SSN_" in call["prompt"]
    assert "123-45-6789" not in call["prompt"]
    assert graph.parties[0].full_name.verification_status == "verified"
    assert graph.paystubs[0].gross_pay.verification_status == "verified"
    assert graph.claims[0].priority_type == "secured"

