# Run test: uv run pytest tests/test_models_and_compiler.py -v
"""Unit tests for Tier-1/Tier-2 Pydantic schemas, validators, and DAG compiler."""

from __future__ import annotations

from app.models import (
    CompiledBundle,
    CompiledGraphBuilder,
    OutlinePlan,
    ReviewComment,
    SectionAuditResult,
    SectionOutput,
    SectionValidator,
    StitchInvariantGate,
    VerifiedFactLedger,
)
from app.sample_data import get_sample_bundles


def test_sample_bundles_deserialize_cleanly() -> None:
    """Verifies that all built-in sample bundles conform to `CompiledBundle`."""
    bundles = get_sample_bundles()
    assert "legal_motion_1332" in bundles
    assert "candidate_exec_screen" in bundles

    legal = bundles["legal_motion_1332"]
    assert legal.audit_summary.total_claims == 7
    assert legal.audit_summary.verified_count == 5
    assert len(legal.audit_summary.cross_section_tensions) == 1

    # Verify all direct_child_ids resolve to existing nodes in the DAG
    for node_id, node in legal.nodes.items():
        for child_id in node.direct_child_ids:
            assert child_id in legal.nodes, f"Broken edge {node_id} -> {child_id}"


def test_section_validator_passes_valid_section() -> None:
    """Verifies that `SectionValidator` approves a well-formed section with sub-supports."""
    raw = {
        "section_id": "sec_02_jurisdiction",
        "text": (
            "The Court must dismiss because <ref n='1'>complete diversity is destroyed</ref> "
            "under 28 U.S.C. § 1332."
        ),
        "supports": [
            {
                "n": 1,
                "items": [
                    {
                        "type": "evidence",
                        "title": "DE Corp Registry",
                        "quote": "Principal place in DE.",
                        "locator": {
                            "source_type": "pdf",
                            "file_name": "Exhibit_B.pdf",
                            "page": 2,
                            "bounding_box": [100, 200, 300, 400],
                        },
                    },
                    {
                        "type": "reasoning",
                        "title": "Headquarters Analysis",
                        "body": "Applies the <ref n='101'>nerve center test</ref>.",
                        "sub_supports": [
                            {
                                "n": 101,
                                "type": "authority",
                                "title": "Hertz Corp. v. Friend",
                                "quote": "Where executive officers direct activities.",
                                "url": "https://supreme.justia.com/cases/federal/us/559/77/",
                            }
                        ],
                    },
                ],
            }
        ],
    }
    section = SectionOutput.model_validate(raw)
    is_valid, errors = SectionValidator.validate_section(section)
    assert is_valid is True
    assert errors == []


def test_section_validator_catches_orphans_and_missing_subrefs() -> None:
    """Verifies that `SectionValidator` detects orphaned inline tags and missing sub-refs."""
    raw = {
        "section_id": "sec_broken",
        "text": "Claim one <ref n='1'>has support</ref> and claim two <ref n='2'>is orphaned</ref>.",
        "supports": [
            {
                "n": 1,
                "items": [
                    {
                        "type": "reasoning",
                        "title": "Broken Reasoning",
                        "body": "Cites missing <ref n='999'>sub-authority</ref>.",
                        "sub_supports": [],
                    }
                ],
            },
            {
                "n": 3,
                "items": [
                    {
                        "type": "assumption",
                        "title": "Unused support group",
                        "body": "Never cited in text.",
                    }
                ],
            },
        ],
    }
    section = SectionOutput.model_validate(raw)
    is_valid, errors = SectionValidator.validate_section(section)
    assert is_valid is False
    assert len(errors) == 3
    assert any("Inline tags lack support definitions: [2]" in e for e in errors)
    assert any("Support items never referenced in text: [3]" in e for e in errors)
    assert any("missing from sub_supports" in e for e in errors)


def test_stitch_invariant_gate_enforces_tag_preservation() -> None:
    """Verifies that `StitchInvariantGate` passes valid edits and rejects dropped tags."""
    original = "First <ref n='1'>complete diversity fails</ref> and <ref n='2'>damages are low</ref>."
    smoothed_ok = (
        "Initially, <ref n='1'>complete diversity fails</ref>; moreover, "
        "<ref n='2'>damages are low</ref>."
    )
    passed, violations = StitchInvariantGate.verify_stitch(original, smoothed_ok)
    assert passed is True
    assert violations == []

    smoothed_dropped = "Initially, <ref n='1'>complete diversity fails</ref>."
    passed_drop, violations_drop = StitchInvariantGate.verify_stitch(
        original, smoothed_dropped
    )
    assert passed_drop is False
    assert any("removed citations with n=[2]" in v for v in violations_drop)


def test_compiled_graph_builder_flattens_and_namespaces() -> None:
    """Verifies that `CompiledGraphBuilder` produces a flat DAG with rewritten global IDs."""
    raw = {
        "section_id": "sec_test",
        "section_title": "Test Section",
        "text": "Margin expanded to <ref n='1'>71.4% in Q3</ref>.",
        "supports": [
            {
                "n": 1,
                "title": "Q3 Margin Expansion",
                "items": [
                    {
                        "type": "calculation",
                        "title": "Margin Formula",
                        "formula": "=E26/E14",
                        "body": "Backed by <ref n='101'>audited ledger</ref>.",
                        "sub_supports": [
                            {
                                "n": 101,
                                "type": "evidence",
                                "title": "P&L Sheet",
                                "quote": "71.42%",
                                "locator": {
                                    "source_type": "spreadsheet",
                                    "file_name": "P&L.xlsx",
                                    "sheet": "Summary",
                                    "cell_range": "E28",
                                    "raw_value": 0.7142,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    section = SectionOutput.model_validate(raw)
    builder = CompiledGraphBuilder(document_title="Test Artifact")
    bundle = builder.compile_sections([section])

    assert bundle.audit_summary.total_claims == 1
    assert "claim_sec_test_1" in bundle.nodes
    assert "cal_sec_test_1_1" in bundle.nodes
    assert "evi_sec_test_1_1_sub101" in bundle.nodes

    sec_content = bundle.artifact.sections[0].content
    assert "<ref id='claim_sec_test_1'>71.4% in Q3</ref>" in sec_content

    calc_node = bundle.nodes["cal_sec_test_1_1"]
    assert "<ref id='evi_sec_test_1_1_sub101'>audited ledger</ref>" in (calc_node.body or "")


def test_multi_section_stitch_and_compile_avoids_local_n_collision() -> None:
    """Verifies that two sections both using local n=1 do not collide during global stitch/compile."""
    sec1 = SectionOutput.model_validate(
        {
            "section_id": "sec_01",
            "section_title": "I. Standing",
            "text": "Standing fails because <ref n='1'>diversity is absent</ref>.",
            "supports": [
                {
                    "n": 1,
                    "title": "Diversity Absent",
                    "items": [
                        {
                            "type": "evidence",
                            "title": "DE Filing",
                            "quote": "Wilmington HQ.",
                            "locator": {"source_type": "pdf", "file_name": "ExA.pdf", "page": 1},
                        }
                    ],
                }
            ],
        }
    )
    sec2 = SectionOutput.model_validate(
        {
            "section_id": "sec_02",
            "section_title": "II. Damages",
            "text": "Damages fail because <ref n='1'>invoices total $42,150</ref>.",
            "supports": [
                {
                    "n": 1,
                    "title": "Invoice Balance",
                    "items": [
                        {
                            "type": "evidence",
                            "title": "AR Ledger",
                            "quote": "$42,150.00",
                            "locator": {
                                "source_type": "spreadsheet",
                                "file_name": "AR.xlsx",
                                "sheet": "Summary",
                                "cell_range": "G14",
                                "raw_value": 42150.0,
                            },
                        }
                    ],
                }
            ],
        }
    )

    pre_stitched = StitchInvariantGate.prepare_for_stitch([sec1, sec2])
    assert "<ref n='sec_01:1'>" in pre_stitched
    assert "<ref n='sec_02:1'>" in pre_stitched

    smoothed = (
        "First, standing fails because <ref n='sec_01:1'>diversity is absent</ref>.\n\n"
        "Second, damages fail because <ref n='sec_02:1'>invoices total $42,150</ref>."
    )
    passed, violations = StitchInvariantGate.verify_stitch(pre_stitched, smoothed)
    assert passed is True, f"Unexpected violations: {violations}"

    builder = CompiledGraphBuilder(document_title="Multi-Section Stitch Test")
    bundle = builder.compile_sections([sec1, sec2], final_smoothed_text=smoothed)

    assert "claim_sec_01_1" in bundle.nodes
    assert "claim_sec_02_1" in bundle.nodes
    unified_content = bundle.artifact.sections[0].content
    assert "<ref id='claim_sec_01_1'>diversity is absent</ref>" in unified_content
    assert "<ref id='claim_sec_02_1'>invoices total $42,150</ref>" in unified_content


def test_compiled_graph_builder_supports_per_section_smoothed_texts() -> None:
    """Verifies that `smoothed_sections` preserves section boundaries while rewriting namespaced tags."""
    sec1 = SectionOutput.model_validate(
        {
            "section_id": "sec_01",
            "section_title": "I. Standing",
            "text": "Standing fails because <ref n='1'>diversity is absent</ref>.",
            "supports": [
                {
                    "n": 1,
                    "items": [
                        {
                            "type": "evidence",
                            "title": "DE Filing",
                            "quote": "Wilmington HQ.",
                            "locator": {"source_type": "pdf", "file_name": "ExA.pdf", "page": 1},
                        }
                    ],
                }
            ],
        }
    )
    sec2 = SectionOutput.model_validate(
        {
            "section_id": "sec_02",
            "section_title": "II. Damages",
            "text": "Damages fail because <ref n='1'>invoices total $42,150</ref>.",
            "supports": [
                {
                    "n": 1,
                    "items": [
                        {
                            "type": "evidence",
                            "title": "AR Ledger",
                            "quote": "$42,150.00",
                            "locator": {"source_type": "spreadsheet", "file_name": "AR.xlsx", "sheet": "Summary", "cell_range": "G14", "raw_value": 42150.0},
                        }
                    ],
                }
            ],
        }
    )

    builder = CompiledGraphBuilder(document_title="Per-Section Smoothed Test")
    bundle = builder.compile_sections(
        [sec1, sec2],
        smoothed_sections={
            "sec_01": "At the outset, standing fails because <ref n='sec_01:1'>diversity is absent</ref>.",
            "sec_02": "Turning to damages, they fail because <ref n='sec_02:1'>invoices total $42,150</ref>.",
        },
    )

    assert len(bundle.artifact.sections) == 2
    assert bundle.artifact.sections[0].section_id == "sec_01"
    assert "<ref id='claim_sec_01_1'>diversity is absent</ref>" in bundle.artifact.sections[0].content
    assert bundle.artifact.sections[1].section_id == "sec_02"
    assert "<ref id='claim_sec_02_1'>invoices total $42,150</ref>" in bundle.artifact.sections[1].content


def test_pipeline_and_review_comment_schemas() -> None:
    """Verifies serialization of stage contracts (`OutlinePlan`, `VerifiedFactLedger`, `ReviewComment`)."""
    plan = OutlinePlan.model_validate(
        {
            "document_title": "Jurisdiction Memo",
            "executive_summary_intent": "Assess diversity and amount in controversy.",
            "sections": [
                {
                    "section_id": "sec_01",
                    "section_title": "I. Diversity",
                    "stated_intention": "Determine corporate citizenship.",
                    "governing_authorities": [
                        {
                            "auth_id": "AUTH:HERTZ-2010",
                            "title": "Hertz Corp. v. Friend",
                            "url": "https://supreme.justia.com/cases/federal/us/559/77/",
                            "verbatim_quote": "Principal place of business is the nerve center.",
                        }
                    ],
                    "required_fact_queries": ["Where is corporate HQ located?"],
                }
            ],
        }
    )
    ledger = VerifiedFactLedger.model_validate(
        {
            "section_id": "sec_01",
            "verified_facts": [
                {
                    "fact_id": "f1",
                    "query_addressed": "Where is corporate HQ located?",
                    "title": "DE Registry",
                    "quote": "1209 North Orange St, Wilmington, DE.",
                    "locator": {"source_type": "pdf", "file_name": "ExB.pdf", "page": 2},
                }
            ],
            "unresolved_gaps": [],
        }
    )
    audit_res = SectionAuditResult(
        section_id="sec_01",
        check_a_relevance=True,
        check_b_congruence=True,
        check_c_intent=True,
        passed=True,
    )
    comment = ReviewComment(
        comment_id="cmt_1",
        node_id="claim_sec_01_1",
        section_id="sec_01",
        comment_text="Clarify whether LLC members are also in Delaware.",
        suggested_status="extrapolation",
    )
    assert plan.sections[0].governing_authorities[0].auth_id == "AUTH:HERTZ-2010"
    assert ledger.verified_facts[0].locator.page == 2
    assert audit_res.passed is True
    assert comment.resolved is False
    assert CompiledBundle.model_fields["comments"] is not None
