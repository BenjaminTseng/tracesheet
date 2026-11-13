# Run test: uv run pytest tests/test_api.py -v
"""Integration tests for FastAPI routes and compilation endpoints."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import MockLLMProvider
from app.pipeline import CrossSectionAuditOutput, FeedbackTriageDecision, StitchedDocumentOutput
from app.routes import BUNDLE_STORE
from main import app, parse_args

client = TestClient(app)


def test_index_renders_html() -> None:
    """Verifies that GET / and static vendor ESM modules return 200 OK."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Audit-Grounded Spatial Document Canvas" in response.text
    assert "/static/vendor/preact.mjs" in response.text
    assert "/static/app.js" in response.text

    for asset in (
        "/static/vendor/preact.mjs",
        "/static/vendor/hooks.mjs",
        "/static/vendor/htm.mjs",
        "/static/app.js",
        "/static/styles.css",
    ):
        asset_res = client.get(asset)
        assert asset_res.status_code == 200, f"Failed to serve {asset}"


def test_list_and_fetch_bundles() -> None:
    """Verifies that GET /api/bundles and GET /api/bundles/{id} return valid data."""
    list_res = client.get("/api/bundles")
    assert list_res.status_code == 200
    bundles = list_res.json()
    assert len(bundles) >= 2
    bundle_ids = {b["bundle_id"] for b in bundles}
    assert "legal_motion_1332" in bundle_ids
    assert "candidate_exec_screen" in bundle_ids

    detail_res = client.get("/api/bundles/legal_motion_1332")
    assert detail_res.status_code == 200
    payload = detail_res.json()
    assert payload["artifact"]["title"].startswith("Motion to Dismiss")
    assert "claim_sec01_1" in payload["nodes"]


def test_compile_endpoint_validates_and_registers_bundle() -> None:
    """Verifies that POST /api/compile compiles Tier-1 sections into a Tier-2 bundle."""
    compile_req = {
        "bundle_id": "test_compiled_api",
        "title": "API Compilation Test Artifact",
        "summary": "Integration test summary.",
        "sections": [
            {
                "section_id": "sec_01",
                "section_title": "I. Overview",
                "text": "System latency dropped by <ref n='1'>42% in production</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "items": [
                            {
                                "type": "evidence",
                                "title": "Prometheus Telemetry API",
                                "quote": "p99 latency reduced from 120ms to 69.6ms.",
                                "locator": {
                                    "source_type": "api",
                                    "endpoint": "GET /api/v1/query",
                                    "method": "GET",
                                    "json_path": "$.data.p99_ms",
                                    "raw_value": 69.6,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
        "smoothed_text": (
            "Following the Q3 rollout, system latency dropped by "
            "<ref n='1'>42% in production</ref>."
        ),
    }

    res = client.post("/api/compile", json=compile_req)
    assert res.status_code == 200
    compiled = res.json()
    assert compiled["bundle_id"] == "test_compiled_api"
    assert "claim_sec_01_1" in compiled["nodes"]
    assert "evi_sec_01_1_1" in compiled["nodes"]

    # Confirm it rejecting broken stitch invariants (e.g. missing <ref n='1'>)
    bad_req = dict(compile_req)
    bad_req["smoothed_text"] = "Following the Q3 rollout, system latency dropped."
    bad_res = client.post("/api/compile", json=bad_req)
    assert bad_res.status_code == 422


def test_matters_upload_ingest_ask_and_comment_regeneration_flow(tmp_path: Path) -> None:
    """Verifies matter creation, file upload, ingest, 4-stage /ask, and batched /regenerate."""
    canonical_dir = tmp_path / "canonical"
    (canonical_dir / "legal").mkdir(parents=True)
    (canonical_dir / "INDEX.md").write_text(
        "# Index\n- `[AUTH:RULE-1]` — Test governing rule.\n", encoding="utf-8"
    )
    (canonical_dir / "legal" / "rules.md").write_text(
        "## [AUTH:RULE-1] Governing Rule\n"
        "- **Title:** Governing Rule\n"
        "- **Verbatim Rule:** Contracts require written notice.\n",
        encoding="utf-8",
    )

    matters_root = tmp_path / "matters"
    app.state.canonical_router = CanonicalRouter(canonical_dir)
    app.state.matter_ingestor = MatterIngestor(matters_root)
    app.state.llm_provider = MockLLMProvider(
        structured_responses={
            "OutlinePlan": {
                "document_title": "Notice Compliance Memo",
                "executive_summary_intent": "Verify written notice compliance.",
                "sections": [
                    {
                        "section_id": "sec_01_notice",
                        "section_title": "I. Written Notice",
                        "stated_intention": "Confirm notice date.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:RULE-1",
                                "title": "Governing Rule",
                                "verbatim_quote": "Contracts require written notice.",
                            }
                        ],
                        "required_fact_queries": ["When was notice sent?"],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_01_notice",
                "verified_facts": [
                    {
                        "fact_id": "f1",
                        "query_addressed": "When was notice sent?",
                        "title": "Notice Letter",
                        "quote": "Written notice delivered October 12, 2026.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Notice.md",
                            "locator_key": "NOTICE-SEC-1",
                        },
                    }
                ],
                "unresolved_gaps": [],
            },
            "SectionOutput": [
                {
                    "section_id": "sec_01_notice",
                    "section_title": "I. Written Notice",
                    "text": "Plaintiff <ref n='1'>delivered written notice on Oct 12</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "October 12 Written Notice",
                            "items": [
                                {
                                    "type": "evidence",
                                    "title": "Notice Letter",
                                    "quote": "Written notice delivered October 12, 2026.",
                                    "locator": {
                                        "source_type": "markdown",
                                        "file_name": "Notice.md",
                                        "locator_key": "NOTICE-SEC-1",
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "section_id": "sec_01_notice",
                    "section_title": "I. Written Notice",
                    "text": "Plaintiff <ref n='1'>timely delivered written notice on October 12, 2026</ref>.",
                    "supports": [
                        {
                            "n": 1,
                            "title": "Timely Notice Confirmed",
                            "items": [
                                {
                                    "type": "evidence",
                                    "title": "Notice Letter",
                                    "quote": "Written notice delivered October 12, 2026.",
                                    "locator": {
                                        "source_type": "markdown",
                                        "file_name": "Notice.md",
                                        "locator_key": "NOTICE-SEC-1",
                                    },
                                }
                            ],
                        }
                    ],
                },
            ],
            "SectionAuditResult": [
                {
                    "section_id": "sec_01_notice",
                    "check_a_relevance": True,
                    "check_b_congruence": True,
                    "check_c_intent": True,
                    "passed": True,
                },
                {
                    "section_id": "sec_01_notice",
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
                        "section_id": "sec_01_notice",
                        "smoothed_text": "Plaintiff <ref n='sec_01_notice:1'>delivered written notice on Oct 12</ref>.",
                    }
                ]
            ),
            "FeedbackTriageDecision": FeedbackTriageDecision(
                needs_stage2_reharvest=False,
                rationale="Reviewer wants full year included in the claim clause.",
                additional_fact_queries=[],
            ),
        }
    )

    try:
        # 1. Create matter & upload a markdown file
        create_res = client.post("/api/matters", json={"matter_id": "notice_case"})
        assert create_res.status_code == 200

        upload_res = client.post(
            "/api/matters/notice_case/upload",
            files={"file": ("Notice.md", b"Written notice delivered October 12, 2026.\n", "text/markdown")},
        )
        assert upload_res.status_code == 200
        assert upload_res.json()["manifest"]["files_processed"] == 1

        matters_res = client.get("/api/matters")
        assert matters_res.status_code == 200
        assert any(m["matter_id"] == "notice_case" for m in matters_res.json()["matters"])

        # 2. Ask a question -> runs 4-stage pipeline
        ask_res = client.post(
            "/api/matters/notice_case/ask",
            json={"question": "Was written notice satisfied?", "bundle_id": "notice_bundle_api"},
        )
        assert ask_res.status_code == 200
        bundle_json = ask_res.json()
        assert bundle_json["bundle_id"] == "notice_bundle_api"
        assert "claim_sec_01_notice_1" in bundle_json["nodes"]

        # 3. Queue an inline claim comment, a logical-link comment, a section comment, and an overall document comment
        cmt_res = client.post(
            "/api/bundles/notice_bundle_api/comments",
            json={
                "scope": "node",
                "node_id": "claim_sec_01_notice_1",
                "section_id": "sec_01_notice",
                "comment_text": "Spell out the full date October 12, 2026.",
            },
        )
        assert cmt_res.status_code == 200

        link_cmt_res = client.post(
            "/api/bundles/notice_bundle_api/comments",
            json={
                "scope": "link",
                "node_id": "evi_sec_01_notice_1_1",
                "target_label": "Claim -> Agreement § 12",
                "comment_text": "Clarify why written notice applies to email termination.",
            },
        )
        assert link_cmt_res.status_code == 200

        doc_cmt_res = client.post(
            "/api/bundles/notice_bundle_api/comments",
            json={
                "scope": "document",
                "comment_text": "Keep conclusion direct and state October 12, 2026 clearly.",
            },
        )
        assert doc_cmt_res.status_code == 200
        comments_payload = doc_cmt_res.json()["comments"]
        assert len(comments_payload) == 3
        assert {c["scope"] for c in comments_payload} == {"node", "link", "document"}
        doc_comment = next(c for c in comments_payload if c["scope"] == "document")
        assert doc_comment["node_id"] == "__document__"
        assert doc_comment["section_id"] == "__document__"

        regen_res = client.post(
            "/api/bundles/notice_bundle_api/regenerate",
            json={"smooth_transitions": False},
        )
        assert regen_res.status_code == 200
        regen_json = regen_res.json()
        assert "October 12, 2026" in regen_json["artifact"]["sections"][0]["content"]
        assert all(c["resolved"] is True for c in regen_json["comments"])
    finally:
        BUNDLE_STORE.pop("notice_bundle_api", None)
        app.state.canonical_router = None
        app.state.matter_ingestor = None
        app.state.llm_provider = None


def test_cli_parse_args_supports_provider_ingest_and_ask() -> None:
    """Verifies CLI flags for `--provider`, `--model`, `--ingest-matter`, `--ingest-canonical`, and `--ask`."""
    ns = parse_args(
        [
            "--provider",
            "gemini",
            "--model",
            "gemini-4-argon",
            "--matter",
            "legal_motion_1332",
            "--ask",
            "Evaluate complete diversity",
            "--ingest-canonical",
            "--purge-canonical",
        ]
    )
    assert ns.provider == "gemini"
    assert ns.model == "gemini-4-argon"
    assert ns.matter == "legal_motion_1332"
    assert ns.ask == "Evaluate complete diversity"
    assert ns.ingest_canonical is True
    assert ns.purge_canonical is True


def test_canonical_upload_and_rebuild_endpoints(tmp_path: Path) -> None:
    """Verifies `GET /api/canonical`, `POST /api/canonical/upload`, and `POST /api/canonical/ingest`."""
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir(parents=True)
    app.state.canonical_router = CanonicalRouter(canonical_dir)
    app.state.canonical_ingestor = CanonicalIngestor(canonical_dir)

    try:
        upload_res = client.post(
            "/api/canonical/upload",
            data={"domain": "compliance"},
            files={
                "file": (
                    "soc2_controls.md",
                    b"# SOC2 Controls\n\n## Access Review\nQuarterly privileged access reviews are mandatory.\n",
                    "text/markdown",
                )
            },
        )
        assert upload_res.status_code == 200
        payload = upload_res.json()
        assert payload["domain"] == "compliance"
        assert payload["total_authorities"] == 1
        assert "compliance" in payload["raw_domains"]
        assert "Quarterly privileged access reviews" in payload["authorities"][0]["verbatim_quote"]

        status_res = client.get("/api/canonical")
        assert status_res.status_code == 200
        assert status_res.json()["total_authorities"] == 1

        rebuild_res = client.post("/api/canonical/ingest", json={"purge_encoded": True})
        assert rebuild_res.status_code == 200
        assert rebuild_res.json()["total_authorities"] == 1
        assert (canonical_dir / "INDEX.md").exists()
    finally:
        app.state.canonical_router = None
        app.state.canonical_ingestor = None

