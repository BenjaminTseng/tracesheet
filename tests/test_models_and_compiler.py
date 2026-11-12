# Run test: uv run pytest tests/test_models_and_compiler.py -v
"""Unit tests for Tier-1/Tier-2 Pydantic schemas, validators, and DAG compiler."""

from __future__ import annotations

from app.models import (
    CompiledGraphBuilder,
    SectionOutput,
    SectionValidator,
    StitchInvariantGate,
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
