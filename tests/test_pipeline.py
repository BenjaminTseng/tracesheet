# Run test: uv run pytest tests/test_pipeline.py -v
"""Unit tests for the 4-stage agentic pipeline and smart feedback regenerator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import MockLLMProvider
from app.models import AuditStatus, NodeAudit, ReviewComment
from app.pipeline import (
    AuditPipelineRunner,
    CrossSectionAuditOutput,
    FeedbackTriageDecision,
    StitchedDocumentOutput,
)


def _setup_workspace(tmp_path: Path) -> tuple[CanonicalRouter, MatterIngestor]:
    """Creates isolated canonical corpus `(b)` and matter `(a)` fixtures."""
    canonical_dir = tmp_path / "canonical"
    (canonical_dir / "legal").mkdir(parents=True)
    (canonical_dir / "INDEX.md").write_text(
        "# Index\n- `[AUTH:HERTZ-2010]` — Nerve center citizenship test.\n",
        encoding="utf-8",
    )
    (canonical_dir / "legal" / "jurisdiction.md").write_text(
        "## [AUTH:HERTZ-2010] Hertz Corp. v. Friend, 559 U.S. 77 (2010)\n"
        "- **Title:** Hertz Corp. v. Friend, 559 U.S. 77 (2010)\n"
        "- **URL:** https://supreme.justia.com/cases/federal/us/559/77/\n"
        "- **Verbatim Holding:** Principal place of business is the nerve center.\n",
        encoding="utf-8",
    )

    matters_root = tmp_path / "matters"
    raw_dir = matters_root / "m_test" / "inputs" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "Exhibit_B.md").write_text(
        "Principal place of business registered at 1209 North Orange St, Wilmington, DE.\n\n"
        "Board treasury approvals are executed in Wilmington.\n",
        encoding="utf-8",
    )
    (raw_dir / "Ledger.csv").write_text(
        "Item,Amount\nUnpaid Invoices,42150.0\n",
        encoding="utf-8",
    )

    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("m_test")
    return CanonicalRouter(canonical_dir), ingestor


def test_full_4stage_pipeline_compiles_and_persists_bundle(tmp_path: Path) -> None:
    """Verifies Stages 1->2->3->4 run end-to-end and persist stage_artifacts."""
    router, ingestor = _setup_workspace(tmp_path)

    mock_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Jurisdiction Assessment Memo",
                "executive_summary_intent": "Evaluate complete diversity and damages.",
                "sections": [
                    {
                        "section_id": "sec_01_diversity",
                        "section_title": "I. Corporate Citizenship",
                        "stated_intention": "Determine whether complete diversity exists.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:HERTZ-2010",
                                "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
                                "verbatim_quote": "Place holder that should be hydrated.",
                            }
                        ],
                        "required_fact_queries": ["Where is executive headquarters?"],
                    },
                    {
                        "section_id": "sec_02_damages",
                        "section_title": "II. Damages",
                        "stated_intention": "Check unpaid invoice total.",
                        "governing_authorities": [],
                        "required_fact_queries": ["What is the unpaid invoice balance?"],
                    },
                ],
            },
            "VerifiedFactLedger": [
                {
                    "section_id": "sec_01_diversity",
                    "verified_facts": [
                        {
                            "fact_id": "f1",
                            "query_addressed": "Where is executive headquarters?",
                            "title": "Delaware Corporate Filing",
                            "quote": "1209 North Orange St, Wilmington, DE.",
                            "locator": {
                                "source_type": "markdown",
                                "file_name": "Exhibit_B.md",
                                "locator_key": "EXHIBIT_B-SEC-1",
                            },
                        }
                    ],
                    "unresolved_gaps": [],
                },
                {
                    "section_id": "sec_02_damages",
                    "verified_facts": [
                        {
                            "fact_id": "f2",
                            "query_addressed": "What is the unpaid invoice balance?",
                            "title": "Unpaid Invoices CSV",
                            "quote": "$42,150.00",
                            "locator": {
                                "source_type": "spreadsheet",
                                "file_name": "Ledger.csv",
                                "sheet": "CSV",
                                "cell_range": "B2",
                                "raw_value": 42150.0,
                            },
                        }
                    ],
                    "unresolved_gaps": [],
                },
            ],
            "SectionOutput": [
                {
                    "section_id": "sec_01_diversity",
                    "section_title": "I. Corporate Citizenship",
                    "text": "Diversity fails because <ref n='1'>HQ is in Wilmington, DE</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "Wilmington HQ",
                            "items": [
                                {
                                    "type": "evidence",
                                    "title": "Delaware Corporate Filing",
                                    "quote": "1209 North Orange St, Wilmington, DE.",
                                    "locator": {
                                        "source_type": "markdown",
                                        "file_name": "Exhibit_B.md",
                                        "locator_key": "EXHIBIT_B-SEC-1",
                                    },
                                },
                                {
                                    "type": "reasoning",
                                    "title": "Nerve Center Application",
                                    "body": "Applies the <ref n='101'>nerve center test</ref>.",
                                    "sub_supports": [
                                        {
                                            "n": 101,
                                            "type": "authority",
                                            "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
                                            "quote": "Principal place of business is the nerve center.",
                                            "url": "https://supreme.justia.com/cases/federal/us/559/77/",
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                },
                {
                    "section_id": "sec_02_damages",
                    "section_title": "II. Damages",
                    "text": "Unpaid balances <ref n='1'>total $42,150</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "Invoice Balance",
                            "items": [
                                {
                                    "type": "evidence",
                                    "title": "Unpaid Invoices CSV",
                                    "quote": "$42,150.00",
                                    "locator": {
                                        "source_type": "spreadsheet",
                                        "file_name": "Ledger.csv",
                                        "sheet": "CSV",
                                        "cell_range": "B2",
                                        "raw_value": 42150.0,
                                    },
                                }
                            ],
                        }
                    ],
                },
            ],
            "SectionAuditResult": [
                {
                    "section_id": "sec_01_diversity",
                    "check_a_relevance": True,
                    "check_b_congruence": True,
                    "check_c_intent": True,
                    "passed": True,
                },
                {
                    "section_id": "sec_02_damages",
                    "check_a_relevance": True,
                    "check_b_congruence": True,
                    "check_c_intent": True,
                    "passed": True,
                },
            ],
            "CrossSectionAuditOutput": CrossSectionAuditOutput(tensions=[]),
            "StitchedDocumentOutput": StitchedDocumentOutput(
                sections=[
                    {
                        "section_id": "sec_01_diversity",
                        "smoothed_text": "At the threshold, diversity fails because <ref n='sec_01_diversity:1'>HQ is in Wilmington, DE</ref>.",
                    },
                    {
                        "section_id": "sec_02_damages",
                        "smoothed_text": "Turning to damages, unpaid balances <ref n='sec_02_damages:1'>total $42,150</ref>.",
                    },
                ]
            ),
        },
        tool_invocations=[
            {"name": "grep_indexed_inputs", "arguments": {"pattern": "Wilmington"}}
        ],
    )

    runner = AuditPipelineRunner(mock_llm, router, ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="m_test",
        question="Should the complaint be dismissed under Rule 12(b)(1)?",
        bundle_id="test_memo",
    )

    assert bundle.bundle_id == "test_memo"
    assert bundle.matter_id == "m_test"
    assert bundle.audit_summary.total_claims == 2
    assert len(bundle.artifact.sections) == 2
    assert "<ref id='claim_sec_01_diversity_1'>" in bundle.artifact.sections[0].content
    assert "<ref id='claim_sec_02_damages_1'>" in bundle.artifact.sections[1].content
    assert "sections" in bundle.stage_artifacts
    assert "ledgers" in bundle.stage_artifacts

    # Check canonical authority quote was hydrated verbatim from canonical/
    plan_auth = bundle.stage_artifacts["outline_plan"]["sections"][0]["governing_authorities"][0]
    assert plan_auth["verbatim_quote"] == "Principal place of business is the nerve center."

    saved_path = tmp_path / "matters" / "m_test" / "bundles" / "test_memo.json"
    assert saved_path.exists()
    persisted = json.loads(saved_path.read_text(encoding="utf-8"))
    assert persisted["bundle_id"] == "test_memo"


def test_smart_feedback_regeneration_skips_stage2_for_prose_edits_and_runs_stage2_for_new_facts(
    tmp_path: Path,
) -> None:
    """Verifies triage skips Stage 2 for prose/caveat comments and triggers Stage 2 for fact requests."""
    router, ingestor = _setup_workspace(tmp_path)

    # First produce an initial compiled bundle via run_full_pipeline
    initial_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Memo",
                "executive_summary_intent": "Summary",
                "sections": [
                    {
                        "section_id": "sec_01",
                        "section_title": "I. HQ",
                        "stated_intention": "Locate HQ.",
                        "governing_authorities": [],
                        "required_fact_queries": ["HQ address?"],
                    },
                    {
                        "section_id": "sec_02",
                        "section_title": "II. Ledger",
                        "stated_intention": "Check invoices.",
                        "governing_authorities": [],
                        "required_fact_queries": ["Invoice total?"],
                    },
                ],
            },
            "VerifiedFactLedger": [
                {
                    "section_id": "sec_01",
                    "verified_facts": [
                        {
                            "fact_id": "f1",
                            "query_addressed": "HQ address?",
                            "title": "Exhibit B",
                            "quote": "1209 North Orange St, Wilmington, DE.",
                            "locator": {
                                "source_type": "markdown",
                                "file_name": "Exhibit_B.md",
                                "locator_key": "EXHIBIT_B-SEC-1",
                            },
                        }
                    ],
                    "unresolved_gaps": [],
                },
                {
                    "section_id": "sec_02",
                    "verified_facts": [
                        {
                            "fact_id": "f2",
                            "query_addressed": "Invoice total?",
                            "title": "Ledger CSV",
                            "quote": "42150.0",
                            "locator": {
                                "source_type": "spreadsheet",
                                "file_name": "Ledger.csv",
                                "sheet": "CSV",
                                "cell_range": "B2",
                                "raw_value": 42150.0,
                            },
                        }
                    ],
                    "unresolved_gaps": [],
                },
            ],
            "SectionOutput": [
                {
                    "section_id": "sec_01",
                    "section_title": "I. HQ",
                    "text": "The company is <ref n='1'>headquartered in Wilmington</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "items": [
                                {
                                    "type": "evidence",
                                    "title": "Exhibit B",
                                    "quote": "1209 North Orange St, Wilmington, DE.",
                                    "locator": {
                                        "source_type": "markdown",
                                        "file_name": "Exhibit_B.md",
                                        "locator_key": "EXHIBIT_B-SEC-1",
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "section_id": "sec_02",
                    "section_title": "II. Ledger",
                    "text": "Invoices <ref n='1'>total $42,150</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "items": [
                                {
                                    "type": "evidence",
                                    "title": "Ledger CSV",
                                    "quote": "42150.0",
                                    "locator": {
                                        "source_type": "spreadsheet",
                                        "file_name": "Ledger.csv",
                                        "sheet": "CSV",
                                        "cell_range": "B2",
                                        "raw_value": 42150.0,
                                    },
                                }
                            ],
                        }
                    ],
                },
            ],
            "SectionAuditResult": [
                {
                    "section_id": "sec_01",
                    "check_a_relevance": True,
                    "check_b_congruence": True,
                    "check_c_intent": True,
                    "passed": True,
                },
                {
                    "section_id": "sec_02",
                    "check_a_relevance": True,
                    "check_b_congruence": True,
                    "check_c_intent": True,
                    "passed": True,
                },
            ],
            "CrossSectionAuditOutput": CrossSectionAuditOutput(tensions=[]),
            "StitchedDocumentOutput": StitchedDocumentOutput(
                sections=[
                    {"section_id": "sec_01", "smoothed_text": "The company is <ref n='sec_01:1'>headquartered in Wilmington</ref>."},
                    {"section_id": "sec_02", "smoothed_text": "Invoices <ref n='sec_02:1'>total $42,150</ref>."},
                ]
            ),
        }
    )
    bundle = AuditPipelineRunner(initial_llm, router, ingestor).run_full_pipeline(
        matter_id="m_test",
        question="Analyze jurisdiction",
        bundle_id="regen_test",
        smooth_transitions=False,
    )

    # Case A: Prose/status-only comment on sec_01 -> should NOT re-run Stage 2
    prose_llm = MockLLMProvider(
        structured_responses={
            "FeedbackTriageDecision": FeedbackTriageDecision(
                needs_stage2_reharvest=False,
                rationale="Reviewer only wants wording softened to an extrapolation.",
                additional_fact_queries=[],
            ),
            "SectionOutput": {
                "section_id": "sec_01",
                "section_title": "I. HQ",
                "text": "Available filings indicate the company is <ref n='1'>likely headquartered in Wilmington</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "items": [
                            {
                                "type": "evidence",
                                "title": "Exhibit B",
                                "quote": "1209 North Orange St, Wilmington, DE.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Exhibit_B.md",
                                    "locator_key": "EXHIBIT_B-SEC-1",
                                },
                            }
                        ],
                    }
                ],
            },
            "SectionAuditResult": {
                "section_id": "sec_01",
                "check_a_relevance": True,
                "check_b_congruence": True,
                "check_c_intent": True,
                "passed": True,
            },
            "CrossSectionAuditOutput": CrossSectionAuditOutput(tensions=[]),
        }
    )
    comment_prose = ReviewComment(
        comment_id="c1",
        node_id="claim_sec_01_1",
        section_id="sec_01",
        comment_text="Soften tone and mark as extrapolation until LLC member list is checked.",
        suggested_status="extrapolation",
    )
    updated_a = AuditPipelineRunner(prose_llm, router, ingestor).apply_comments_and_recompile(
        bundle=bundle,
        new_comments=[comment_prose],
        smooth_transitions=False,
    )
    assert all(c["model"] != "VerifiedFactLedger" for c in prose_llm.call_log)
    assert "likely headquartered in Wilmington" in updated_a.artifact.sections[0].content
    assert updated_a.nodes["claim_sec_01_1"].audit.status == "extrapolation"
    assert updated_a.comments[0].resolved is True
    # Section 2 untouched
    assert "total $42,150" in updated_a.artifact.sections[1].content

    # Case B: New-fact comment on sec_01 -> MUST trigger Stage 2 reharvest
    fact_llm = MockLLMProvider(
        structured_responses={
            "FeedbackTriageDecision": FeedbackTriageDecision(
                needs_stage2_reharvest=True,
                rationale="Reviewer asks to verify board treasury approvals in Wilmington.",
                additional_fact_queries=["Where are board treasury approvals executed?"],
            ),
            "VerifiedFactLedger": {
                "section_id": "sec_01",
                "verified_facts": [
                    {
                        "fact_id": "f_new",
                        "query_addressed": "Where are board treasury approvals executed?",
                        "title": "Board Treasury Minutes",
                        "quote": "Board treasury approvals are executed in Wilmington.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Exhibit_B.md",
                            "locator_key": "EXHIBIT_B-SEC-2",
                        },
                    }
                ],
                "unresolved_gaps": [],
            },
            "SectionOutput": {
                "section_id": "sec_01",
                "section_title": "I. HQ",
                "text": "Both registration and <ref n='1'>Wilmington treasury approvals confirm HQ</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "items": [
                            {
                                "type": "evidence",
                                "title": "Board Treasury Minutes",
                                "quote": "Board treasury approvals are executed in Wilmington.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Exhibit_B.md",
                                    "locator_key": "EXHIBIT_B-SEC-2",
                                },
                            }
                        ],
                    }
                ],
            },
            "SectionAuditResult": {
                "section_id": "sec_01",
                "check_a_relevance": True,
                "check_b_congruence": True,
                "check_c_intent": True,
                "passed": True,
            },
            "CrossSectionAuditOutput": CrossSectionAuditOutput(tensions=[]),
        },
        tool_invocations=[
            {"name": "grep_indexed_inputs", "arguments": {"pattern": "treasury"}}
        ],
    )
    comment_fact = ReviewComment(
        comment_id="c2",
        node_id="claim_sec_01_1",
        section_id="sec_01",
        comment_text="Check the exhibits for where board treasury approvals happen.",
    )
    updated_b = AuditPipelineRunner(fact_llm, router, ingestor).apply_comments_and_recompile(
        bundle=updated_a,
        new_comments=[comment_fact],
        smooth_transitions=False,
    )
    assert any(c["model"] == "VerifiedFactLedger" for c in fact_llm.call_log)
    assert "Wilmington treasury approvals" in updated_b.artifact.sections[0].content
    assert len(updated_b.stage_artifacts["ledgers"]["sec_01"]["verified_facts"]) == 2


def test_stage1_catalog_isolation_stage2_canonical_discovery_and_trace_artifacts(
    tmp_path: Path,
) -> None:
    """Verifies Stage 1 reads only INDEX.md, Stage 2 discovers extra rules, and explanations/audits persist."""
    canonical_dir = tmp_path / "canonical"
    raw_legal = canonical_dir / "raw" / "legal"
    raw_legal.mkdir(parents=True)
    (raw_legal / "bankruptcy_code.md").write_text(
        "# Bankruptcy Code\n\n"
        "## 11 U.S.C. § 362 — Automatic Stay\n"
        "Filing a petition operates as an immediate automatic stay of collection actions.\n\n"
        "## 11 U.S.C. § 547 — Preference Clawback\n"
        "Transfers made within 90 days before filing while insolvent may be avoided.\n",
        encoding="utf-8",
    )
    CanonicalIngestor(canonical_dir).ingest_corpus(purge_encoded=True)
    router = CanonicalRouter(canonical_dir)

    matters_root = tmp_path / "matters"
    raw_matter = matters_root / "m_bankruptcy" / "inputs" / "raw"
    raw_matter.mkdir(parents=True)
    (raw_matter / "Docket.md").write_text(
        "Debtor filed a voluntary Chapter 11 petition on March 1, 2026.\n\n"
        "Vendor X received a $50,000 payment 45 days before filing.\n",
        encoding="utf-8",
    )
    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("m_bankruptcy")

    mock_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Petition Timing & Transfer Check",
                "executive_summary_intent": "Assess stay applicability and simple date arithmetic.",
                "sections": [
                    {
                        "section_id": "sec_01_stay",
                        "section_title": "I. Petition & Transfer Review",
                        "stated_intention": "Determine filing stay trigger and days elapsed before filing.",
                        "routing_rationale": "Selected 11 U.S.C. § 362 from catalog; transfer arithmetic uses L1 dates.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:LEGAL-BANKRUPTCY-CODE-001",
                                "title": "11 U.S.C. § 362 — Automatic Stay",
                                "verbatim_quote": "Placeholder",
                            }
                        ],
                        "required_fact_queries": ["When was the petition filed and what payments occurred?"],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_01_stay",
                "harvest_summary": "Verified filing date and 45-day payment in Docket.md; discovered § 547 clawback rule.",
                "verified_facts": [
                    {
                        "fact_id": "f_petition",
                        "query_addressed": "When was the petition filed?",
                        "title": "Chapter 11 Filing",
                        "quote": "Debtor filed a voluntary Chapter 11 petition on March 1, 2026.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Docket.md",
                            "locator_key": "DOCKET-SEC-1",
                        },
                    },
                    {
                        "fact_id": "f_transfer",
                        "query_addressed": "What payments occurred?",
                        "title": "Pre-Petition Transfer",
                        "quote": "Vendor X received a $50,000 payment 45 days before filing.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Docket.md",
                            "locator_key": "DOCKET-SEC-2",
                        },
                    },
                ],
                "additional_authorities": [
                    {
                        "auth_id": "AUTH:LEGAL-BANKRUPTCY-CODE-002",
                        "title": "11 U.S.C. § 547 — Preference Clawback",
                        "verbatim_quote": "Placeholder hydrated from disk",
                    }
                ],
                "unresolved_gaps": [],
            },
            "SectionOutput": {
                "section_id": "sec_01_stay",
                "section_title": "I. Petition & Transfer Review",
                "drafting_notes": "Combined Docket dates with Stage 2-discovered § 547 authority and 45<90 arithmetic.",
                "text": (
                    "The <ref n='1'>Chapter 11 petition stays collections</ref> and "
                    "<ref n='2'>the 45-day transfer falls within the 90-day window</ref>."
                ),
                "supports": [
                    {
                        "n": 1,
                        "title": "Automatic Stay",
                        "items": [
                            {
                                "type": "evidence",
                                "title": "Docket Entry 1",
                                "quote": "Debtor filed a voluntary Chapter 11 petition on March 1, 2026.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Docket.md",
                                    "locator_key": "DOCKET-SEC-1",
                                },
                            },
                            {
                                "type": "reasoning",
                                "title": "Stay Activation",
                                "body": "Filing activates <ref n='101'>the statutory automatic stay</ref>.",
                                "sub_supports": [
                                    {
                                        "n": 101,
                                        "type": "authority",
                                        "title": "[AUTH:LEGAL-BANKRUPTCY-CODE-001] 11 U.S.C. § 362",
                                        "quote": "Filing a petition operates as an immediate automatic stay of collection actions.",
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "n": 2,
                        "title": "90-Day Preference Window Arithmetic",
                        "items": [
                            {
                                "type": "evidence",
                                "title": "Docket Entry 2",
                                "quote": "Vendor X received a $50,000 payment 45 days before filing.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Docket.md",
                                    "locator_key": "DOCKET-SEC-2",
                                },
                            },
                            {
                                "type": "calculation",
                                "title": "Elapsed Lookback Comparison",
                                "formula": "45 < 90",
                                "body": "Because 45 days is strictly less than 90 days, the transfer sits inside the lookback window under <ref n='102'>11 U.S.C. § 547</ref>.",
                                "sub_supports": [
                                    {
                                        "n": 102,
                                        "type": "authority",
                                        "title": "[AUTH:LEGAL-BANKRUPTCY-CODE-002] 11 U.S.C. § 547",
                                        "quote": "Transfers made within 90 days before filing while insolvent may be avoided.",
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
            "SectionAuditResult": {
                "section_id": "sec_01_stay",
                "check_a_relevance": True,
                "check_b_congruence": True,
                "check_c_intent": True,
                "audit_rationale": "All dates match Docket.md verbatim; § 362 and Stage-2-discovered § 547 are quoted accurately.",
                "passed": True,
            },
            "CrossSectionAuditOutput": CrossSectionAuditOutput(tensions=[]),
        },
        tool_invocations=[
            {"name": "browse_canonical_toc", "arguments": {"doc_id": "legal/bankruptcy_code.md"}},
            {"name": "grep_indexed_inputs", "arguments": {"pattern": "Chapter 11"}},
        ],
    )

    bundle = AuditPipelineRunner(mock_llm, router, ingestor).run_full_pipeline(
        matter_id="m_bankruptcy",
        question="Does the automatic stay apply and is the Vendor X transfer in the 90-day window?",
        bundle_id="bankruptcy_trace_test",
        smooth_transitions=False,
    )

    # Verify Stage 1 received compact INDEX.md catalog, NOT full raw verbatim bodies
    stage1_call = next(c for c in mock_llm.call_log if c["model"] == "OutlinePlan")
    assert "Canonical Knowledge Catalog" in stage1_call["prompt"]
    assert "AUTH:LEGAL-BANKRUPTCY-CODE-002" not in stage1_call["prompt"]

    # Verify Stage 1-4 rationales & Stage 2 discovered rule persisted cleanly
    sa = bundle.stage_artifacts
    assert sa["outline_plan"]["sections"][0]["routing_rationale"].startswith("Selected 11 U.S.C. § 362")
    assert len(sa["outline_plan"]["sections"][0]["governing_authorities"]) == 2
    assert sa["ledgers"]["sec_01_stay"]["harvest_summary"].startswith("Verified filing date")
    assert "Transfers made within 90 days" in sa["ledgers"]["sec_01_stay"]["additional_authorities"][0]["verbatim_quote"]
    assert sa["sections"][0]["drafting_notes"].startswith("Combined Docket dates")
    assert sa["audits"]["sec_01_stay"]["audit_rationale"].startswith("All dates match")
