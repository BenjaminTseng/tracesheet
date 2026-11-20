# Run all live evals: RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -v -s
# Run one sub-test:  RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -k test_live_02 -v -s
# Retry only failed: RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py --lf -v -s
"""Opt-in, token-disciplined live Gemini evaluation suite across 5 granular sub-tests."""

from __future__ import annotations

import datetime
import os
import shutil
from pathlib import Path

import pytest
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

from app.compilers.bankruptcy.extractor import BankruptcyCaseExtractor
from app.compilers.bankruptcy.service import BankruptcyCaseService
from app.compilers.research.pipeline import AuditPipelineRunner
from app.core.bundle import CompiledBundle, ReviewComment, SectionOutput, SectionValidator
from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.core.llm import create_llm_provider
from app.core.pii import PIITokenizer

dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path=dotenv_path, override=False)
else:
    load_dotenv(override=False)

LIVE_ENABLED = os.getenv("RUN_LIVE_API_TESTS") == "1" and bool(os.getenv("GEMINI_API_KEY"))

pytestmark = pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="Set RUN_LIVE_API_TESTS=1 and GEMINI_API_KEY (in .env or env) to run live Gemini evaluation tests.",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_CACHE_PATH = REPO_ROOT / ".pytest_cache" / "live_eval_bundle_1332.json"


class _SmokeEntitySummary(BaseModel):
    """Compact structured schema for verifying live Gemini JSON generation."""

    employer_name: str
    monthly_gross_usd: int


def _prepare_canonical_workspace(tmp_path: Path, llm: object) -> Path:
    """Copies pre-encoded canonical corpus into `tmp_path/canonical` to avoid wasting tokens."""
    src_canonical = REPO_ROOT / "canonical"
    dst_canonical = tmp_path / "canonical"
    shutil.copytree(src_canonical, dst_canonical)
    if not (dst_canonical / "INDEX.md").exists() or not (dst_canonical / "catalog.json").exists():
        CanonicalIngestor(dst_canonical).ingest_corpus(purge_encoded=True, llm=llm)
    return dst_canonical


def _prepare_motion_1332_matter(tmp_path: Path) -> Path:
    """Copies standing raw fixtures for `legal_motion_1332` and runs deterministic indexing."""
    matters_root = tmp_path / "matters"
    shutil.copytree(
        REPO_ROOT / "matters" / "legal_motion_1332" / "inputs" / "raw",
        matters_root / "legal_motion_1332" / "inputs" / "raw",
    )
    MatterIngestor(matters_root).ingest_matter("legal_motion_1332")
    return matters_root


def test_live_01_gateway_structured_and_decisions() -> None:
    """Verifies Gemini Interactions structured output and Decisions API (`noul` + `choice`)."""
    llm = create_llm_provider("gemini")

    res = llm.generate_structured(
        prompt=(
            "Extract the employer and integer monthly gross USD from this statement:\n"
            "Employee Jordan Vance earned $4,200 gross per month at Pacific Grid Logistics."
        ),
        system_instruction="Return only the factual values matching the JSON schema.",
        response_model=_SmokeEntitySummary,
    )
    assert "Pacific" in res.employer_name
    assert res.monthly_gross_usd == 4200

    batch = llm.evaluate_decisions(
        input_text=(
            "The plaintiff (Acme Corp., incorporated in Delaware) seeks $140,000 in "
            "unpaid invoices against a citizen of California under a signed Written MSA."
        ),
        questions={
            "exceeds_75k": {
                "type": "noul",
                "instructions": "Does the amount in controversy exceed $75,000?",
            },
            "subject_matter_basis": {
                "type": "choice",
                "instructions": "Choose the strongest primary federal subject-matter basis.",
                "criteria": {
                    "diversity_1332": "Complete state diversity and amount in controversy > $75,000.",
                    "state_only": "No federal basis present.",
                },
            },
        },
    )
    assert "exceeds_75k" in batch.answers
    assert batch.answers["exceeds_75k"].noul is not None
    assert batch.answers["exceeds_75k"].noul >= 0.65
    assert "subject_matter_basis" in batch.answers
    assert batch.answers["subject_matter_basis"].choice == "diversity_1332"


def test_live_02_bankruptcy_extractor_and_verifier(tmp_path: Path) -> None:
    """Verifies PII masking before LLM send, live CaseExtractionDraft wiring, and ObservationVerifier."""
    llm = create_llm_provider("gemini")
    matters_root = tmp_path / "matters"
    raw_dir = matters_root / "live_bk_case" / "inputs" / "raw"
    raw_dir.mkdir(parents=True)

    (raw_dir / "debtor_intake.md").write_text(
        "# Client Bankruptcy Intake\n\n"
        "- Debtor Name: Jordan Vance\n"
        "- SSN: 123-45-6789\n"
        "- Street Address: 742 Harbor View Ave\n"
        "- City/State/Zip: Los Angeles, CA 90017\n"
        "- County of Residence: Los Angeles\n"
        "- Household Size: 1\n"
        "- CA Domicile Days: 1500\n"
        "- Asset ID: veh_1 | Category: vehicle | Description: 2020 Honda Civic EX | "
        "Fair Market Value: $14,500.00 | Acquisition Date: 2020-05-10\n",
        encoding="utf-8",
    )
    (raw_dir / "paystub_2026_10.md").write_text(
        "# Earnings Statement\n\n"
        "- Employer: Pacific Grid Logistics Inc\n"
        "- Period Start: 2026-10-01 | Period End: 2026-10-31 | Pay Date: 2026-10-31\n"
        "- Gross Pay: $4,200.00 | Net Pay: $3,150.00 | Taxes Withheld: $850.00\n"
        "- Direct Deposit Account: ...4829\n",
        encoding="utf-8",
    )

    ingestor = MatterIngestor(matters_root, pii_tokenizer=PIITokenizer(matters_root))
    ingestor.ingest_matter("live_bk_case")

    intake_indexed = (matters_root / "live_bk_case" / "inputs" / "indexed" / "debtor_intake.md.indexed.md").read_text(
        encoding="utf-8"
    )
    assert "[PII:SSN_001]" in intake_indexed
    assert "123-45-6789" not in intake_indexed

    extractor = BankruptcyCaseExtractor()
    graph = extractor.extract(
        matter_id="live_bk_case",
        ingestor=ingestor,
        chapter="7",
        district="CACB",
        llm_provider=llm,
    )

    assert len(graph.parties) >= 1
    assert any(p.full_name.verification_status == "verified" for p in graph.parties)
    assert len(graph.assets) >= 1
    assert any(a.current_value.verification_status == "verified" for a in graph.assets)
    assert len(graph.paystubs) >= 1
    assert any(ps.gross_pay.verification_status == "verified" for ps in graph.paystubs)


def test_live_03_research_4stage_grounding(tmp_path: Path) -> None:
    """Runs live 4-stage pipeline on `legal_motion_1332`, reusing pre-encoded `canonical/`."""
    llm = create_llm_provider("gemini")
    canonical_dir = _prepare_canonical_workspace(tmp_path, llm)
    matters_root = _prepare_motion_1332_matter(tmp_path)

    raw_filenames = {
        p.name for p in (matters_root / "legal_motion_1332" / "inputs" / "raw").iterdir() if p.is_file()
    }

    router = CanonicalRouter(canonical_dir)
    ingestor = MatterIngestor(matters_root)
    runner = AuditPipelineRunner(llm, router, ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="legal_motion_1332",
        question=(
            "Evaluate whether complete diversity and the $75,000 amount-in-controversy "
            "requirement under 28 U.S.C. § 1332(a) are satisfied."
        ),
        bundle_id="live_eval_1332",
        progress_callback=lambda st, msg: print(f"[LIVE_03:{st}] {msg}"),
    )

    assert bundle.audit_summary.total_claims >= 2
    evidence_nodes = [n for n in bundle.nodes.values() if n.type == "evidence"]
    assert len(evidence_nodes) >= 1
    for ev in evidence_nodes:
        assert ev.locator is not None
        assert ev.locator.file_name in raw_filenames

    combined_text = " ".join(s.content for s in bundle.artifact.sections)
    assert "Wilmington" in combined_text or "Delaware" in combined_text
    assert "42,150" in combined_text or "42150" in combined_text
    assert bundle.stage_artifacts.get("outline_plan")
    assert bundle.stage_artifacts.get("audits")

    BUNDLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_CACHE_PATH.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")


def test_live_04_research_feedback_regeneration(tmp_path: Path) -> None:
    """Tests live Decisions API comment triage + selective Stage 2/3/4 regeneration."""
    llm = create_llm_provider("gemini")
    canonical_dir = _prepare_canonical_workspace(tmp_path, llm)
    matters_root = _prepare_motion_1332_matter(tmp_path)

    router = CanonicalRouter(canonical_dir)
    ingestor = MatterIngestor(matters_root)
    runner = AuditPipelineRunner(llm, router, ingestor)

    if BUNDLE_CACHE_PATH.exists():
        bundle = CompiledBundle.model_validate_json(BUNDLE_CACHE_PATH.read_text(encoding="utf-8"))
    else:
        bundle = runner.run_full_pipeline(
            matter_id="legal_motion_1332",
            question="Analyze diversity jurisdiction and recoverable damages for the dispute.",
            bundle_id="live_feedback_1332",
        )
        BUNDLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUNDLE_CACHE_PATH.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")

    claim_nodes = [n for n in bundle.nodes.values() if n.type == "claim"]
    assert claim_nodes
    target_claim = claim_nodes[0]

    comment = ReviewComment(
        comment_id="cmt_live_1",
        node_id=target_claim.id,
        section_id=target_claim.section_id,
        comment_text=(
            "Explicitly state that consequential damages and lost profits are barred "
            "under Master Services Agreement § 11.4 in Exhibit A."
        ),
    )

    updated = runner.apply_comments_and_recompile(
        bundle=bundle,
        new_comments=[comment],
        progress_callback=lambda st, msg: print(f"[LIVE_04:{st}] {msg}"),
    )
    assert any(c.comment_id == "cmt_live_1" and c.resolved for c in updated.comments)
    for raw_sec in updated.stage_artifacts.get("sections", []):
        ok, errs = SectionValidator.validate_section(SectionOutput.model_validate(raw_sec))
        assert ok, f"Regenerated section failed validator: {errs}"


def test_live_05_hybrid_ledger_citation(tmp_path: Path) -> None:
    """Verifies live Research compiler cites a Bankruptcy `VerifiedLedgerSnapshot` (`calculation_ledger`)."""
    llm = create_llm_provider("gemini")
    canonical_dir = _prepare_canonical_workspace(tmp_path, llm)

    # Build one focused Chapter 7 CACB matter and publish its deterministic `ledgers/bankruptcy.json`.
    bk_base = tmp_path / "bk_workspace"
    shutil.copytree(canonical_dir, bk_base / "canonical")
    bk_service = BankruptcyCaseService(base_dir=bk_base)
    bk_service.init_case(
        matter_id="live_hybrid_ch7_case",
        chapter="7",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
    )

    raw_dir = bk_base / "matters" / "live_hybrid_ch7_case" / "inputs" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "debtor_intake.md").write_text(
        "# Client Bankruptcy Intake\n\n"
        "- Debtor Name: Jordan Vance\n"
        "- Street Address: 742 Harbor View Ave\n"
        "- City/State/Zip: Los Angeles, CA 90017\n"
        "- County of Residence: Los Angeles\n"
        "- Household Size: 1\n"
        "- CA Domicile Days: 1500\n"
        "- Asset ID: veh_1 | Category: vehicle | Description: 2020 Honda Civic EX | "
        "Fair Market Value: $14,500.00 | Acquisition Date: 2020-05-10\n",
        encoding="utf-8",
    )
    (raw_dir / "paystub_2026_10.md").write_text(
        "# Earnings Statement\n\n"
        "- Employer: Pacific Grid Logistics Inc\n"
        "- Period Start: 2026-10-01 | Period End: 2026-10-31 | Pay Date: 2026-10-31\n"
        "- Gross Pay: $4,200.00 | Net Pay: $3,150.00 | Taxes Withheld: $850.00\n"
        "- Direct Deposit Account: ...4829\n",
        encoding="utf-8",
    )

    ingestor = MatterIngestor(bk_base / "matters", pii_tokenizer=PIITokenizer(bk_base / "matters"))
    ingestor.ingest_matter("live_hybrid_ch7_case")
    bk_service.extract_matter(
        "live_hybrid_ch7_case",
        chapter="7",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
    )

    ledger_file = bk_base / "matters" / "live_hybrid_ch7_case" / "ledgers" / "bankruptcy.json"
    assert ledger_file.exists(), "Expected BankruptcyCaseService to publish ledgers/bankruptcy.json"

    ingestor.ingest_matter("live_hybrid_ch7_case")
    indexed_ledger = (
        bk_base
        / "matters"
        / "live_hybrid_ch7_case"
        / "inputs"
        / "indexed"
        / "ledger__bankruptcy.indexed.md"
    )
    assert indexed_ledger.exists()

    runner = AuditPipelineRunner(llm, CanonicalRouter(canonical_dir), ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="live_hybrid_ch7_case",
        question=(
            "Write a concise 1-section summary reporting ONLY from the verified bankruptcy calculation ledger "
            "`ledgers/bankruptcy.json`: the debtor's 6-month Current Monthly Income (cmi), total_assets, "
            "readiness_status, and recommended California exemption regime. "
            "Cite `ledgers/bankruptcy.json` (`source_type='calculation_ledger'`) directly as `type='evidence'`."
        ),
        bundle_id="live_hybrid_ledger_test",
        progress_callback=lambda st, msg: print(f"[LIVE_05:{st}] {msg}"),
    )

    assert bundle.audit_summary.total_claims >= 1
    ledger_ev_nodes = [
        n
        for n in bundle.nodes.values()
        if n.type == "evidence"
        and n.locator is not None
        and n.locator.source_type == "calculation_ledger"
        and n.locator.file_name == "ledgers/bankruptcy.json"
    ]
    assert len(ledger_ev_nodes) >= 1, (
        f"Expected at least one grounded calculation_ledger evidence node; "
        f"got locators: {[n.locator.model_dump(exclude_none=True) for n in bundle.nodes.values() if n.locator]}"
    )
