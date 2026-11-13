# Run test: uv run pytest tests/test_pipeline.py -v
"""Unit tests for the 4-stage agentic pipeline and smart feedback regenerator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import MockLLMProvider
from app.models import (
    AuditStatus,
    NodeAudit,
    PipelineRunRecord,
    ReviewComment,
    SectionPlan,
    VerifiedFactLedger,
)
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

    # Check Stage 4 cross-section tension prompt deduplicates section prose
    tension_calls = [c for c in mock_llm.call_log if c.get("model") == "CrossSectionAuditOutput"]
    assert len(tension_calls) == 1
    assert "Sections context:" in tension_calls[0]["prompt"]
    assert '"full_section_text"' not in tension_calls[0]["prompt"]

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


def test_stage4_auditor_and_triage_use_decisions_api_zero_token_fast_path(
    tmp_path: Path,
) -> None:
    """Verifies Decisions API clears Stage 4 audit and stage_3_redraft triage with zero structured output calls."""
    router, ingestor = _setup_workspace(tmp_path)

    mock_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Fast Gate Memo",
                "executive_summary_intent": "Verify HQ.",
                "sections": [
                    {
                        "section_id": "sec_01",
                        "section_title": "I. HQ",
                        "stated_intention": "Locate corporate HQ.",
                        "routing_rationale": "Uses Exhibit_B with Hertz nerve center test.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:HERTZ-2010",
                                "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
                                "verbatim_quote": "Placeholder",
                            }
                        ],
                        "required_fact_queries": ["Where is HQ registered?"],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_01",
                "harvest_summary": "Found registered Wilmington office in Exhibit_B.",
                "verified_facts": [
                    {
                        "fact_id": "f1",
                        "query_addressed": "Where is HQ registered?",
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
            "SectionOutput": [
                {
                    "section_id": "sec_01",
                    "section_title": "I. HQ",
                    "drafting_notes": "Initial draft.",
                    "text": "The company is <ref n='1'>headquartered in Wilmington</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "HQ Fact",
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
                    "section_id": "sec_01",
                    "section_title": "I. HQ",
                    "drafting_notes": "Edited prose to include full street address.",
                    "text": "The company is <ref n='1'>headquartered at 1209 North Orange St, Wilmington, DE</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "HQ Fact",
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
            ],
            # Deliberately omit SectionAuditResult & FeedbackTriageDecision to prove zero-token Decisions fast path!
        },
        decision_responses=[
            # Call 1: Stage 4 initial audit
            {
                "check_a_relevance": {"question_id": "check_a_relevance", "question_type": "noul", "noul": 0.96, "confidence": 0.96},
                "check_b_congruence": {"question_id": "check_b_congruence", "question_type": "noul", "noul": 0.97, "confidence": 0.97},
                "check_c_intent": {"question_id": "check_c_intent", "question_type": "noul", "noul": 0.95, "confidence": 0.95},
                "claim_1_entailment": {"question_id": "claim_1_entailment", "question_type": "noul", "noul": 0.98, "confidence": 0.98},
                "claim_1_status": {"question_id": "claim_1_status", "question_type": "choice", "choice": "verified", "probabilities": {"verified": 0.94}, "confidence": 0.94},
            },
            # Call 2: Feedback triage -> stage_3_redraft
            {
                "route": {"question_id": "route", "question_type": "choice", "choice": "stage_3_redraft", "probabilities": {"stage_3_redraft": 0.92, "stage_2_reharvest": 0.08}, "confidence": 0.92},
            },
            # Call 3: Stage 4 re-audit after regeneration
            {
                "check_a_relevance": {"question_id": "check_a_relevance", "question_type": "noul", "noul": 0.97, "confidence": 0.97},
                "check_b_congruence": {"question_id": "check_b_congruence", "question_type": "noul", "noul": 0.98, "confidence": 0.98},
                "check_c_intent": {"question_id": "check_c_intent", "question_type": "noul", "noul": 0.96, "confidence": 0.96},
                "claim_1_entailment": {"question_id": "claim_1_entailment", "question_type": "noul", "noul": 0.99, "confidence": 0.99},
                "claim_1_status": {"question_id": "claim_1_status", "question_type": "choice", "choice": "verified", "probabilities": {"verified": 0.96}, "confidence": 0.96},
            },
        ],
    )

    runner = AuditPipelineRunner(mock_llm, router, ingestor)
    bundle = runner.run_full_pipeline(
        matter_id="m_test",
        question="Where is HQ?",
        bundle_id="fast_gate_bundle",
        smooth_transitions=False,
    )
    assert bundle.nodes["claim_sec_01_1"].audit.status == "verified"
    assert "Decisions API" in bundle.nodes["claim_sec_01_1"].audit.evaluator_note
    assert bundle.stage_artifacts["audits"]["sec_01"]["decision_probabilities"]["check_b_congruence"] == 0.97

    updated = runner.apply_comments_and_recompile(
        bundle=bundle,
        new_comments=[
            ReviewComment(
                comment_id="c_fast",
                node_id="claim_sec_01_1",
                section_id="sec_01",
                comment_text="Include the full street address.",
            )
        ],
        smooth_transitions=False,
    )
    assert "1209 North Orange St" in updated.artifact.sections[0].content
    assert not any(c.get("model") in ("SectionAuditResult", "FeedbackTriageDecision") for c in mock_llm.call_log)
    assert sum(1 for c in mock_llm.call_log if c.get("method") == "evaluate_decisions") == 3


def test_stage3_retries_on_section_validator_failure_and_injects_errors_into_prompt(
    tmp_path: Path,
) -> None:
    """Verifies Stage 3 retries when `SectionValidator` fails and injects errors into the retry prompt."""
    router, ingestor = _setup_workspace(tmp_path)
    section_plan = SectionPlan.model_validate(
        {
            "section_id": "sec_retry",
            "section_title": "I. Headquarters",
            "stated_intention": "Confirm Delaware headquarters.",
            "routing_rationale": "Uses Exhibit_B with Hertz nerve center test.",
            "governing_authorities": [router.get_authority("AUTH:HERTZ-2010").model_dump()],
            "required_fact_queries": ["Where is HQ?"],
        }
    )
    ledger = VerifiedFactLedger.model_validate(
        {
            "section_id": "sec_retry",
            "harvest_summary": "Verified Exhibit_B registration.",
            "verified_facts": [
                {
                    "fact_id": "f1",
                    "query_addressed": "Where is HQ?",
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
        }
    )

    mock_llm = MockLLMProvider(
        structured_responses={
            "SectionOutput": [
                # Attempt 1: orphaned <ref n='2'> tag triggers SectionValidator failure
                {
                    "section_id": "sec_retry",
                    "section_title": "I. Headquarters",
                    "drafting_notes": "Attempt 1 with orphan ref.",
                    "text": "Claim <ref n='1'>one</ref> and orphan <ref n='2'>two</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "HQ Fact",
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
                # Attempt 2: clean parity passes validation
                {
                    "section_id": "sec_retry",
                    "section_title": "I. Headquarters",
                    "drafting_notes": "Removed orphaned tag and verified parity.",
                    "text": "Claim <ref n='1'>one</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "HQ Fact",
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
            ]
        }
    )

    draft = AuditPipelineRunner(mock_llm, router, ingestor).run_stage3_section_drafter(
        section_plan, ledger
    )
    assert draft.text == "Claim <ref n='1'>one</ref>."
    assert len(mock_llm.call_log) == 2
    assert "Structural & Citation Verification Errors to Fix" in mock_llm.call_log[1]["prompt"]
    assert "Inline tags lack support definitions: [2]" in mock_llm.call_log[1]["prompt"]


def test_stage4_decisions_rejection_triggers_critique_and_stage3_redraft(
    tmp_path: Path,
) -> None:
    """Verifies a low Decisions API score triggers structured critique and Stage 3 corrective redraft."""
    router, ingestor = _setup_workspace(tmp_path)
    section_plan = SectionPlan.model_validate(
        {
            "section_id": "sec_damages",
            "section_title": "II. Damages",
            "stated_intention": "Verify unpaid invoice total.",
            "routing_rationale": "Pure L1 ledger arithmetic.",
            "governing_authorities": [],
            "required_fact_queries": ["What is the unpaid invoice total?"],
        }
    )
    ledger = VerifiedFactLedger.model_validate(
        {
            "section_id": "sec_damages",
            "harvest_summary": "Verified $42,150.00 in Ledger.csv!B2.",
            "verified_facts": [
                {
                    "fact_id": "f_inv",
                    "query_addressed": "What is the unpaid invoice total?",
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
        }
    )

    critique_msg = "Claim 1 states $90,000 but Ledger.csv shows $42,150."
    mock_llm = MockLLMProvider(
        structured_responses={
            "SectionOutput": [
                # Attempt 1: inaccurate dollar figure in L0 clause prose
                {
                    "section_id": "sec_damages",
                    "section_title": "II. Damages",
                    "drafting_notes": "Initial damages draft.",
                    "text": "Unpaid invoices <ref n='1'>total $90,000</ref>.",
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
                # Attempt 2: corrected to match Ledger.csv
                {
                    "section_id": "sec_damages",
                    "section_title": "II. Damages",
                    "drafting_notes": "Corrected figure to $42,150 per Stage 4 critique.",
                    "text": "Unpaid invoices <ref n='1'>total $42,150</ref>.",
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
            "SectionAuditResult": {
                "section_id": "sec_damages",
                "check_a_relevance": True,
                "check_b_congruence": False,
                "check_c_intent": True,
                "audit_rationale": "Drafted figure contradicts Ledger.csv!B2.",
                "critique_for_retry": critique_msg,
                "passed": False,
            },
        },
        decision_responses=[
            # Attempt 1 fails congruence gate (< 0.80)
            {
                "check_a_relevance": {"question_id": "check_a_relevance", "question_type": "noul", "noul": 0.92, "confidence": 0.92},
                "check_b_congruence": {"question_id": "check_b_congruence", "question_type": "noul", "noul": 0.15, "confidence": 0.85},
                "check_c_intent": {"question_id": "check_c_intent", "question_type": "noul", "noul": 0.90, "confidence": 0.90},
                "claim_1_entailment": {"question_id": "claim_1_entailment", "question_type": "noul", "noul": 0.12, "confidence": 0.88},
                "claim_1_status": {"question_id": "claim_1_status", "question_type": "choice", "choice": "disputed", "probabilities": {"disputed": 0.88}, "confidence": 0.88},
            },
            # Attempt 2 clears every gate
            {
                "check_a_relevance": {"question_id": "check_a_relevance", "question_type": "noul", "noul": 0.96, "confidence": 0.96},
                "check_b_congruence": {"question_id": "check_b_congruence", "question_type": "noul", "noul": 0.95, "confidence": 0.95},
                "check_c_intent": {"question_id": "check_c_intent", "question_type": "noul", "noul": 0.97, "confidence": 0.97},
                "claim_1_entailment": {"question_id": "claim_1_entailment", "question_type": "noul", "noul": 0.94, "confidence": 0.94},
                "claim_1_status": {"question_id": "claim_1_status", "question_type": "choice", "choice": "verified", "probabilities": {"verified": 0.94}, "confidence": 0.94},
            },
        ],
    )

    draft, audit_res = AuditPipelineRunner(mock_llm, router, ingestor)._draft_and_audit_section(
        "m_test", section_plan, ledger
    )
    assert "$42,150" in draft.text
    assert audit_res.passed is True
    assert draft.supports[0].audit is not None
    assert draft.supports[0].audit.status == "verified"

    section_calls = [c for c in mock_llm.call_log if c.get("model") == "SectionOutput"]
    assert len(section_calls) == 2
    assert critique_msg in section_calls[1]["prompt"]


def test_stage4_stitch_invariant_violation_falls_back_to_unsmoothed_sections(
    tmp_path: Path,
) -> None:
    """Verifies StitchInvariantGate rejects broken stitch edits and falls back to raw sections."""
    router, ingestor = _setup_workspace(tmp_path)
    mock_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Stitch Guard Memo",
                "executive_summary_intent": "Verify stitch fallback.",
                "sections": [
                    {
                        "section_id": "sec_01",
                        "section_title": "I. HQ",
                        "stated_intention": "Check HQ.",
                        "routing_rationale": "Uses Exhibit_B.",
                        "governing_authorities": [],
                        "required_fact_queries": ["Where is HQ?"],
                    },
                    {
                        "section_id": "sec_02",
                        "section_title": "II. Damages",
                        "stated_intention": "Check invoice.",
                        "routing_rationale": "Uses Ledger.csv.",
                        "governing_authorities": [],
                        "required_fact_queries": ["What is unpaid invoice balance?"],
                    },
                ],
            },
            "VerifiedFactLedger": [
                {
                    "section_id": "sec_01",
                    "verified_facts": [
                        {
                            "fact_id": "f1",
                            "query_addressed": "Where is HQ?",
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
                            "query_addressed": "What is unpaid invoice balance?",
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
                    "text": "HQ is <ref n='1'>located in Wilmington</ref>.",
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
                    "section_title": "II. Damages",
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
            # Corrupt StitchedDocumentOutput deliberately drops <ref n='sec_01:1'> tag!
            "StitchedDocumentOutput": StitchedDocumentOutput(
                sections=[
                    {"section_id": "sec_01", "smoothed_text": "HQ is located in Wilmington without ref tag."},
                    {"section_id": "sec_02", "smoothed_text": "Invoices <ref n='sec_02:1'>total $42,150</ref>."},
                ]
            ),
        }
    )

    bundle = AuditPipelineRunner(mock_llm, router, ingestor).run_full_pipeline(
        matter_id="m_test",
        question="Verify diversity and damages",
        bundle_id="stitch_fallback_test",
        smooth_transitions=True,
    )
    assert "<ref id='claim_sec_01_1'>located in Wilmington</ref>" in bundle.artifact.sections[0].content
    assert "<ref id='claim_sec_02_1'>total $42,150</ref>" in bundle.artifact.sections[1].content


def test_persisted_run_with_stage1_and_stage2_checkpoints_and_granular_progress(
    tmp_path: Path,
) -> None:
    """Verifies disk-persisted runs pause at Stage 1 & Stage 2 checkpoints and emit tool-call progress."""
    router, ingestor = _setup_workspace(tmp_path)

    mock_llm = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Checkpoint Memo",
                "executive_summary_intent": "Verify headquarters and unpaid invoice total.",
                "sections": [
                    {
                        "section_id": "sec_01",
                        "section_title": "I. Nerve Center",
                        "stated_intention": "Check HQ.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:HERTZ-2010",
                                "title": "Hertz",
                                "verbatim_quote": "Principal place of business is the nerve center.",
                            }
                        ],
                        "required_fact_queries": ["Where is HQ?"],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_01",
                "harvest_summary": "Verified Wilmington headquarters.",
                "verified_facts": [
                    {
                        "fact_id": "f1",
                        "query_addressed": "Where is HQ?",
                        "title": "Exhibit B",
                        "quote": "1209 North Orange St, Wilmington, DE.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Exhibit_B.md",
                            "locator_key": "EXHIBIT_B-SEC-1",
                        },
                    }
                ],
                "unresolved_gaps": [
                    {
                        "query": "Where are federal tax returns filed?",
                        "recommended_handling": "assumption",
                        "rationale": "Tax return exhibit not yet uploaded.",
                    }
                ],
            },
            "SectionOutput": {
                "section_id": "sec_01",
                "section_title": "I. Nerve Center",
                "text": "Operations are anchored in <ref n='1'>Wilmington, DE</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "reasoning": "Principal executive offices establish corporate citizenship.",
                        "items": [
                            {
                                "ref_id": "f1",
                                "type": "evidence",
                                "title": "Exhibit B",
                                "quote": "1209 North Orange St, Wilmington, DE.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Exhibit_B.md",
                                    "locator_key": "EXHIBIT_B-SEC-1",
                                },
                            },
                            {
                                "ref_id": "AUTH:HERTZ-2010",
                                "type": "authority",
                                "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
                            },
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
            "StitchedDocumentOutput": StitchedDocumentOutput(
                sections=[
                    {
                        "section_id": "sec_01",
                        "smoothed_text": "Operations are anchored in <ref n='sec_01:1'>Wilmington, DE</ref>.",
                    }
                ]
            ),
        },
        tool_invocations=[
            {"name": "browse_canonical_toc", "arguments": {"doc_id": "legal/jurisdiction.md"}},
            {"name": "grep_indexed_inputs", "arguments": {"pattern": "Wilmington"}},
        ],
    )

    runner = AuditPipelineRunner(mock_llm, router, ingestor)
    seen_events: list[tuple[str, str]] = []
    run = PipelineRunRecord(
        run_id="run_ckpt_01",
        matter_id="m_test",
        question="Analyze corporate citizenship",
        bundle_id="ckpt_bundle",
        checkpoint_mode=True,
    )

    # 1. Stage 1 checkpoint pause
    paused_s1, bundle_s1 = runner.execute_run(
        run, progress_callback=lambda s, m: seen_events.append((s, m))
    )
    assert bundle_s1 is None
    assert paused_s1.status == "awaiting_stage1_approval"
    assert paused_s1.outline_plan is not None
    assert (tmp_path / "matters" / "m_test" / "runs" / "run_ckpt_01.json").exists()
    assert any("Tool browse_canonical_toc" in msg for _, msg in seen_events)

    # Human edits outline before approving Stage 1 -> Stage 2
    paused_s1.outline_plan.sections[0].stated_intention = "Confirm Wilmington HQ under Hertz."
    paused_s2, bundle_s2 = runner.execute_run(
        paused_s1, progress_callback=lambda s, m: seen_events.append((s, m))
    )
    assert bundle_s2 is None
    assert paused_s2.status == "awaiting_stage2_approval"
    assert "sec_01" in paused_s2.ledgers
    assert len(paused_s2.ledgers["sec_01"].unresolved_gaps) == 1
    assert paused_s2.ledgers["sec_01"].unresolved_gaps[0].rationale == "Tax return exhibit not yet uploaded."
    assert any("[1/1]" in msg and "Harvesting coordinate-stamped facts" in msg for _, msg in seen_events)
    assert any("Tool grep_indexed_inputs" in msg for _, msg in seen_events)

    # Human inspects ledger and approves -> completes Stages 3 & 4
    reloaded = runner.find_run("run_ckpt_01")
    assert reloaded is not None
    assert reloaded.status == "awaiting_stage2_approval"

    completed_run, final_bundle = runner.execute_run(
        reloaded, progress_callback=lambda s, m: seen_events.append((s, m))
    )
    assert final_bundle is not None
    assert completed_run.status == "completed"
    assert completed_run.result_bundle_id == "ckpt_bundle"
    assert len(runner.list_runs("m_test")) == 1
    assert any("attempt 1/3" in msg for _, msg in seen_events)


def test_canonical_domain_selection_explicit_and_auto_decision_routing(tmp_path: Path) -> None:
    """Verifies explicit `canonical_domains` and auto-select Decisions API domain routing."""
    canonical_dir = tmp_path / "canonical"
    (canonical_dir / "legal").mkdir(parents=True)
    (canonical_dir / "medical").mkdir(parents=True)
    (canonical_dir / "legal" / "bankruptcy.md").write_text(
        "## [AUTH:11USC-507] Wage Priority\n"
        "- **Title:** Wage Priority\n"
        "- **Verbatim Holding:** Pre-petition wages qualify for fourth-priority status.\n",
        encoding="utf-8",
    )
    (canonical_dir / "medical" / "sepsis.md").write_text(
        "## [AUTH:SSC-2021] Sepsis Care\n"
        "- **Title:** Sepsis Care\n"
        "- **Verbatim Holding:** Early fluid resuscitation improves sepsis survival.\n",
        encoding="utf-8",
    )
    (canonical_dir / "INDEX.md").write_text(
        "# Canonical Index\n"
        "- **`[legal]`**: `legal/bankruptcy.md` (`AUTH:11USC-507`)\n"
        "- **`[medical]`**: `medical/sepsis.md` (`AUTH:SSC-2021`)\n",
        encoding="utf-8",
    )
    router = CanonicalRouter(canonical_dir)
    ingestor = MatterIngestor(tmp_path / "matters")
    ingestor.create_matter("m_dom")
    _, m_raw, _, _ = ingestor._matter_dirs("m_dom")
    (m_raw / "Payroll.md").write_text("# Payroll\n\nAccrued employee wages equal $12,000.\n", encoding="utf-8")
    ingestor.ingest_matter("m_dom")

    mock_llm = MockLLMProvider(
        decision_responses={
            "answers": {
                "domain_legal": {
                    "question_id": "domain_legal",
                    "question_type": "choice",
                    "choice": "include",
                    "confidence": 0.96,
                    "reasoning": "Bankruptcy wage motion directly requires legal domain.",
                },
                "domain_medical": {
                    "question_id": "domain_medical",
                    "question_type": "choice",
                    "choice": "exclude",
                    "confidence": 0.94,
                    "reasoning": "Clinical sepsis rules are unrelated to payroll motion.",
                },
            }
        },
        structured_responses={
            "OutlinePlan": {
                "document_title": "Pre-Petition Wage Priority Analysis",
                "executive_summary_intent": "Assess wage priority obligations.",
                "sections": [
                    {
                        "section_id": "sec_01",
                        "section_title": "Wage Priority",
                        "stated_intention": "Assess statutory priority for accrued wages.",
                        "routing_rationale": "Uses 11 U.S.C. § 507.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:11USC-507",
                                "title": "Wage Priority",
                                "verbatim_quote": "Pre-petition wages qualify for fourth-priority status.",
                            }
                        ],
                        "required_fact_queries": ["Accrued wages"],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_01",
                "verified_facts": [
                    {
                        "fact_id": "f1",
                        "query_addressed": "Accrued wages",
                        "title": "Accrued Employee Wages",
                        "quote": "Accrued employee wages equal $12,000.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Payroll.md",
                            "locator_key": "PAYROLL-SEC-2",
                        },
                    }
                ],
            },
            "SectionOutput": {
                "section_id": "sec_01",
                "section_title": "Wage Priority",
                "text": "Debtor owes <ref n='1'>$12,000 in wages</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "reasoning": "Direct payroll ledger entry.",
                        "items": [
                            {
                                "ref_id": "f1",
                                "type": "evidence",
                                "title": "Payroll.md",
                                "quote": "Accrued employee wages equal $12,000.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Payroll.md",
                                    "locator_key": "PAYROLL-SEC-2",
                                },
                            },
                            {
                                "ref_id": "AUTH:11USC-507",
                                "type": "authority",
                                "title": "Wage Priority",
                            },
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
            "StitchedDocumentOutput": StitchedDocumentOutput(
                sections=[{"section_id": "sec_01", "smoothed_text": "Debtor owes <ref n='sec_01:1'>$12,000 in wages</ref>."}]
            ),
        },
    )

    runner = AuditPipelineRunner(mock_llm, router, ingestor)
    # 1. Explicit selection
    assert runner.resolve_canonical_domains("Analyze wages", ["medical"]) == ["medical"]
    # 2. Auto-selection via evaluate_decisions
    run = PipelineRunRecord(
        run_id="run_dom_auto",
        matter_id="m_dom",
        question="Analyze pre-petition payroll obligations",
        bundle_id="dom_bundle",
        canonical_domains=None,
    )
    completed, bundle = runner.execute_run(run)
    assert bundle is not None
    assert completed.selected_domains == ["legal"]
    # Stage 1 prompt should contain legal index and NOT medical index
    stage1_calls = [c for c in mock_llm.call_log if c.get("model") == "OutlinePlan"]
    assert stage1_calls
    assert "AUTH:11USC-507" in stage1_calls[0]["prompt"]
    assert "AUTH:SSC-2021" not in stage1_calls[0]["prompt"]
    # Decisions API call explicitly evaluated both domain_legal and domain_medical
    dec_calls = [c for c in mock_llm.call_log if c.get("method") == "evaluate_decisions"]
    assert len(dec_calls) >= 1
    assert set(dec_calls[0]["questions"].keys()) == {"domain_legal", "domain_medical"}
