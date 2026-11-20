# Run live eval: RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -v -s
"""Opt-in live Gemini evaluation suite testing canonical ingestion, 4-stage pipeline, and feedback triage."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from dotenv import find_dotenv, load_dotenv

from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.core.llm import create_llm_provider
from app.core.bundle import ReviewComment, SectionOutput, SectionValidator
from app.compilers.research.pipeline import AuditPipelineRunner

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


def _copy_sample_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Copies standing raw canonical corpus and `legal_motion_1332` raw inputs into an isolated temp workspace."""
    repo_root = Path(__file__).resolve().parent.parent
    canonical_dir = tmp_path / "canonical"
    shutil.copytree(repo_root / "canonical" / "raw", canonical_dir / "raw")

    matters_root = tmp_path / "matters"
    shutil.copytree(
        repo_root / "matters" / "legal_motion_1332" / "inputs" / "raw",
        matters_root / "legal_motion_1332" / "inputs" / "raw",
    )
    return canonical_dir, matters_root


def test_live_canonical_ingest_and_4stage_pipeline_grounding(tmp_path: Path) -> None:
    """Runs live Gemini (configured via .env) across CanonicalIngestor -> Stage 1..4 on `legal_motion_1332`."""
    canonical_dir, matters_root = _copy_sample_workspace(tmp_path)
    llm = create_llm_provider("gemini")

    CanonicalIngestor(canonical_dir).ingest_corpus(purge_encoded=True, llm=llm)
    assert (canonical_dir / "INDEX.md").exists()
    assert (canonical_dir / "catalog.json").exists()

    router = CanonicalRouter(canonical_dir)
    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("legal_motion_1332")

    raw_filenames = {
        p.name for p in (matters_root / "legal_motion_1332" / "inputs" / "raw").iterdir() if p.is_file()
    }

    runner = AuditPipelineRunner(llm, router, ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="legal_motion_1332",
        question=(
            "Evaluate whether complete diversity and the $75,000 amount-in-controversy "
            "requirement under 28 U.S.C. § 1332(a) are satisfied."
        ),
        bundle_id="live_eval_1332",
        progress_callback=lambda st, msg: print(f"[LIVE:{st}] {msg}"),
    )

    assert bundle.audit_summary.total_claims >= 2
    evidence_nodes = [n for n in bundle.nodes.values() if n.type == "evidence"]
    assert len(evidence_nodes) >= 1
    for ev in evidence_nodes:
        assert ev.locator is not None
        assert ev.locator.file_name in raw_filenames

    combined_text = " ".join(s.content for s in bundle.artifact.sections)
    assert ("Wilmington" in combined_text or "Delaware" in combined_text)
    assert ("42,150" in combined_text or "42150" in combined_text)
    assert bundle.stage_artifacts.get("outline_plan")
    assert bundle.stage_artifacts.get("audits")


def test_live_feedback_regeneration_resolves_reviewer_comment(tmp_path: Path) -> None:
    """Tests live Decisions API triage + selective Stage 2/3/4 comment resolution."""
    canonical_dir, matters_root = _copy_sample_workspace(tmp_path)
    llm = create_llm_provider("gemini")

    CanonicalIngestor(canonical_dir).ingest_corpus(purge_encoded=True, llm=llm)
    router = CanonicalRouter(canonical_dir)
    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("legal_motion_1332")

    runner = AuditPipelineRunner(llm, router, ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="legal_motion_1332",
        question="Analyze diversity jurisdiction and recoverable damages for the dispute.",
        bundle_id="live_feedback_1332",
    )

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
        progress_callback=lambda st, msg: print(f"[LIVE_REGEN:{st}] {msg}"),
    )
    assert any(c.comment_id == "cmt_live_1" and c.resolved for c in updated.comments)
    for raw_sec in updated.stage_artifacts.get("sections", []):
        ok, errs = SectionValidator.validate_section(SectionOutput.model_validate(raw_sec))
        assert ok, f"Regenerated section failed validator: {errs}"
