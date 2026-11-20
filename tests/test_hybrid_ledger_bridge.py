# Run: uv run pytest tests/test_hybrid_ledger_bridge.py -v
"""Cross-compiler integration test verifying hybrid `bankruptcy -> research` ledger citations."""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path

from app.compilers.bankruptcy.service import BankruptcyCaseService
from app.compilers.research.pipeline import AuditPipelineRunner
from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.core.llm import MockLLMProvider
from app.core.workspace import MatterWorkspace


def test_bankruptcy_publishes_verified_ledger_and_research_cites_it(tmp_path: Path) -> None:
    """Verifies BankruptcyCaseService emits `ledgers/bankruptcy.json` and Research cites it."""
    canonical_dir = tmp_path / "canonical"
    (canonical_dir / "raw" / "legal").mkdir(parents=True)
    shutil.copytree(Path("canonical/tables/bankruptcy"), canonical_dir / "tables" / "bankruptcy")
    (canonical_dir / "raw" / "legal" / "ch11_wages.md").write_text(
        "# Pre-Petition Wages\n\n## Statutory Priority Cap\nEmployees hold priority claims up to $15,150 under 11 U.S.C. § 507(a)(4).\n",
        encoding="utf-8",
    )
    CanonicalIngestor(canonical_dir).ingest_corpus(llm=MockLLMProvider())

    bk_service = BankruptcyCaseService(base_dir=tmp_path)
    state = bk_service.init_case(
        matter_id="hybrid_ch11_case",
        chapter="7",
        district="CACB",
        expected_filing_date=datetime.date(2026, 11, 16),
    )

    ws = MatterWorkspace(tmp_path / "matters", "hybrid_ch11_case")
    snapshot = ws.read_ledger("bankruptcy", verify_hash=True)
    assert snapshot is not None
    assert snapshot.app_id == "bankruptcy"
    assert snapshot.facts["matter_id"] == "hybrid_ch11_case"
    assert snapshot.facts["total_assets"] == "0.00"

    # Stage 2 on the research compiler auto-reindexes `ledgers/bankruptcy.json` incrementally.
    router = CanonicalRouter(canonical_dir)
    ingestor = MatterIngestor(tmp_path / "matters")
    ingestor.ingest_matter("hybrid_ch11_case")

    ledger_blocks_md = (ws.indexed_dir / "ledger__bankruptcy.indexed.md").read_text(encoding="utf-8")
    assert "calculation_ledger" in ledger_blocks_md

    # Locate the exact locator_key for facts.total_assets from indexed ledger.
    total_assets_loc_key = None
    for line in ledger_blocks_md.splitlines():
        if "facts.total_assets" in line and line.startswith("<!-- LOCATOR:"):
            raw_json = line.removeprefix("<!-- LOCATOR:").removesuffix("-->").strip()
            total_assets_loc_key = json.loads(raw_json)["locator_key"]
            break
    assert total_assets_loc_key is not None

    mock_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Hybrid Chapter 11 Motion Brief",
                "executive_summary_intent": "Cite deterministic bankruptcy ledger summary.",
                "sections": [
                    {
                        "section_id": "sec_ledger",
                        "section_title": "Verified Asset Baseline",
                        "stated_intention": "State deterministic asset baseline.",
                        "required_fact_queries": ["Total bankruptcy assets"],
                        "governing_authorities": [],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_ledger",
                "harvest_summary": "Read verified bankruptcy calculation ledger.",
                "verified_facts": [
                    {
                        "fact_id": "f_assets",
                        "query_addressed": "Total bankruptcy assets",
                        "title": "Total Scheduled Assets",
                        "quote": "0.00",
                        "locator": {
                            "source_type": "calculation_ledger",
                            "file_name": "ledgers/bankruptcy.json",
                            "locator_key": total_assets_loc_key,
                            "json_path": "facts.total_assets",
                        },
                    }
                ],
                "unresolved_gaps": [],
                "additional_authorities": [],
            },
            "SectionOutput": {
                "section_id": "sec_ledger",
                "section_title": "Verified Asset Baseline",
                "drafting_notes": "Cited deterministic ledger.",
                "text": "The verified schedule reports total assets of <ref n=\"1\">$0.00</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "title": "Total Assets Claim",
                        "items": [
                            {
                                "type": "evidence",
                                "fact_id": "f_assets",
                                "title": "Bankruptcy Ledger Total Assets",
                                "quote": "0.00",
                            }
                        ],
                    }
                ],
            },
            "SectionAuditResult": {
                "section_id": "sec_ledger",
                "check_a_relevance": True,
                "check_b_congruence": True,
                "check_c_intent": True,
                "passed": True,
                "audit_rationale": "Exact ledger match.",
            },
            "CrossSectionAuditOutput": {"tensions": []},
        }
    )

    runner = AuditPipelineRunner(mock_llm, router, ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="hybrid_ch11_case",
        question="Summarize deterministic asset baseline from the bankruptcy ledger.",
        bundle_id="hybrid_motion_test",
        smooth_transitions=False,
    )

    ev_nodes = [n for n in bundle.nodes.values() if n.type == "evidence"]
    assert len(ev_nodes) == 1
    assert ev_nodes[0].locator is not None
    assert ev_nodes[0].locator.source_type == "calculation_ledger"
    assert ev_nodes[0].locator.file_name == "ledgers/bankruptcy.json"
    assert ev_nodes[0].locator.json_path == "facts.total_assets"
