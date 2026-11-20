# Run test: uv run pytest tests/test_api.py -v
"""Integration tests for FastAPI routes and compilation endpoints."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.core.llm import MockLLMProvider
from app.compilers.research.pipeline import CrossSectionAuditOutput, FeedbackTriageDecision, StitchedDocumentOutput
from app.server import create_platform_app
from main import app, parse_args

client = TestClient(app)


def test_index_renders_html() -> None:
    """Verifies root redirect -> /bankruptcy, /research shell, and static ESM vendor assets."""
    redir = client.get("/", follow_redirects=False)
    assert redir.status_code == 307
    assert redir.headers.get("location") == "/bankruptcy"

    bk_res = client.get("/bankruptcy")
    assert bk_res.status_code == 200
    assert "/static/apps/bankruptcy/app.js" in bk_res.text

    rs_res = client.get("/research")
    assert rs_res.status_code == 200
    assert "Audit-Grounded Spatial Document Canvas" in rs_res.text
    assert "/static/vendor/preact.mjs" in rs_res.text
    assert "/static/apps/research/app.js" in rs_res.text

    for asset in (
        "/static/vendor/preact.mjs",
        "/static/vendor/hooks.mjs",
        "/static/vendor/htm.mjs",
        "/static/core/shell.js",
        "/static/core/canvas.js",
        "/static/core/inspector.js",
        "/static/core/stepper.js",
        "/static/apps/research/app.js",
        "/static/apps/bankruptcy/app.js",
        "/static/styles.css",
    ):
        asset_res = client.get(asset)
        assert asset_res.status_code == 200, f"Failed to serve {asset}"


def test_list_and_fetch_bundles() -> None:
    """Verifies GET /api/v1/research/bundles and GET /api/v1/research/bundles/{id}."""
    list_res = client.get("/api/v1/research/bundles")
    assert list_res.status_code == 200
    bundles = list_res.json()
    assert len(bundles) >= 2
    bundle_ids = {b["bundle_id"] for b in bundles}
    assert "legal_motion_1332" in bundle_ids
    assert "candidate_exec_screen" in bundle_ids

    detail_res = client.get("/api/v1/research/bundles/legal_motion_1332")
    assert detail_res.status_code == 200
    payload = detail_res.json()
    assert payload["artifact"]["title"].startswith("Motion to Dismiss")
    assert "claim_sec01_1" in payload["nodes"]


def test_compile_endpoint_validates_and_registers_bundle() -> None:
    """Verifies POST /api/v1/research/compile validates Tier-1 sections into a Tier-2 bundle."""
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

    res = client.post("/api/v1/research/compile", json=compile_req)
    assert res.status_code == 200
    compiled = res.json()
    assert compiled["bundle_id"] == "test_compiled_api"
    assert "claim_sec_01_1" in compiled["nodes"]
    assert "evi_sec_01_1_1" in compiled["nodes"]

    # Confirm rejecting broken stitch invariants (e.g. missing <ref n='1'>)
    bad_req = dict(compile_req)
    bad_req["smoothed_text"] = "Following the Q3 rollout, system latency dropped."
    bad_res = client.post("/api/v1/research/compile", json=bad_req)
    assert bad_res.status_code == 422
    app.state.research_service.bundle_store.pop("test_compiled_api", None)


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
        create_res = client.post("/api/v1/matters", json={"matter_id": "notice_case"})
        assert create_res.status_code == 200

        upload_res = client.post(
            "/api/v1/matters/notice_case/upload",
            files={"file": ("Notice.md", b"Written notice delivered October 12, 2026.\n", "text/markdown")},
        )
        assert upload_res.status_code == 200
        assert upload_res.json()["manifest"]["files_processed"] == 1

        matters_res = client.get("/api/v1/matters")
        assert matters_res.status_code == 200
        assert any(m["matter_id"] == "notice_case" for m in matters_res.json()["matters"])

        # 2. Ask a question -> runs 4-stage pipeline
        ask_res = client.post(
            "/api/v1/research/matters/notice_case/ask",
            json={"question": "Was written notice satisfied?", "bundle_id": "notice_bundle_api"},
        )
        assert ask_res.status_code == 200
        bundle_json = ask_res.json()
        assert bundle_json["bundle_id"] == "notice_bundle_api"
        assert "claim_sec_01_notice_1" in bundle_json["nodes"]

        # 3. Queue inline node, logical-link, and document comments
        cmt_res = client.post(
            "/api/v1/research/bundles/notice_bundle_api/comments",
            json={
                "scope": "node",
                "node_id": "claim_sec_01_notice_1",
                "section_id": "sec_01_notice",
                "comment_text": "Spell out the full date October 12, 2026.",
            },
        )
        assert cmt_res.status_code == 200

        link_cmt_res = client.post(
            "/api/v1/research/bundles/notice_bundle_api/comments",
            json={
                "scope": "link",
                "node_id": "evi_sec_01_notice_1_1",
                "target_label": "Claim -> Agreement § 12",
                "comment_text": "Clarify why written notice applies to email termination.",
            },
        )
        assert link_cmt_res.status_code == 200

        doc_cmt_res = client.post(
            "/api/v1/research/bundles/notice_bundle_api/comments",
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
            "/api/v1/research/bundles/notice_bundle_api/regenerate",
            json={"smooth_transitions": False},
        )
        assert regen_res.status_code == 200
        regen_json = regen_res.json()
        assert "October 12, 2026" in regen_json["artifact"]["sections"][0]["content"]
        assert all(c["resolved"] is True for c in regen_json["comments"])
    finally:
        app.state.research_service.bundle_store.pop("notice_bundle_api", None)
        app.state.canonical_router = None
        app.state.matter_ingestor = None
        app.state.llm_provider = None


def test_cli_parse_args_supports_provider_ingest_and_ask() -> None:
    """Verifies CLI flags for `--apps`, `--default-app`, `--sync-tables`, `--provider`, `--ingest`, and `--ask`."""
    ns = parse_args(
        [
            "--apps",
            "bankruptcy",
            "--default-app",
            "bankruptcy",
            "--sync-tables",
            "bankruptcy",
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
    assert ns.apps == "bankruptcy"
    assert ns.default_app == "bankruptcy"
    assert ns.sync_tables == "bankruptcy"
    assert ns.provider == "gemini"
    assert ns.model == "gemini-4-argon"
    assert ns.matter == "legal_motion_1332"
    assert ns.ask == "Evaluate complete diversity"
    assert ns.ingest_canonical is True
    assert ns.purge_canonical is True


def test_canonical_upload_and_rebuild_endpoints(tmp_path: Path) -> None:
    """Verifies `GET /api/v1/canonical`, `POST /api/v1/canonical/upload`, and `POST /api/v1/canonical/ingest`."""
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir(parents=True)
    app.state.canonical_router = CanonicalRouter(canonical_dir)
    app.state.canonical_ingestor = CanonicalIngestor(canonical_dir)

    try:
        upload_res = client.post(
            "/api/v1/canonical/upload",
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

        status_res = client.get("/api/v1/canonical")
        assert status_res.status_code == 200
        assert status_res.json()["total_authorities"] == 1

        rebuild_res = client.post("/api/v1/canonical/ingest", json={"purge_encoded": True})
        assert rebuild_res.status_code == 200
        assert rebuild_res.json()["total_authorities"] == 1
        assert (canonical_dir / "INDEX.md").exists()
    finally:
        app.state.canonical_router = None
        app.state.canonical_ingestor = None


def _parse_sse_events(body: str) -> list[dict]:
    """Parses `data: {...}` frames from a `text/event-stream` response body."""
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_corpus_file_management_streaming_and_checkpoint_runs(tmp_path: Path) -> None:
    """Verifies canonical/matter file inspection, delete, streaming ingest, and Stage 1/2 checkpoints."""
    canonical_dir = tmp_path / "canonical"
    matters_root = tmp_path / "matters"
    canonical_dir.mkdir(parents=True)
    matters_root.mkdir(parents=True)

    mock_llm = MockLLMProvider(
        structured_responses={
            "CanonicalDocumentSynopsisDraft": {
                "title": "Jurisdiction Rules",
                "authority_tier": "controlling",
                "jurisdiction_scope": "Federal diversity rules",
                "scope_synopsis": "Statutory diversity rules.",
            },
            "OutlinePlan": {
                "document_title": "API Checkpoint Brief",
                "executive_summary_intent": "Verify Delaware notice.",
                "sections": [
                    {
                        "section_id": "sec_notice",
                        "section_title": "I. Written Notice",
                        "stated_intention": "Check written notice.",
                        "governing_authorities": [
                            {
                                "auth_id": "AUTH:STATUTES-1",
                                "title": "Written Notice Rule",
                                "verbatim_quote": "Written notice is mandatory.",
                            }
                        ],
                        "required_fact_queries": ["Was notice delivered in writing?"],
                    }
                ],
            },
            "VerifiedFactLedger": {
                "section_id": "sec_notice",
                "harvest_summary": "Found Exhibit A quote.",
                "verified_facts": [
                    {
                        "fact_id": "f1",
                        "query_addressed": "Was notice delivered in writing?",
                        "title": "Exhibit A",
                        "quote": "Delivered signed notice on October 12, 2026.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Exhibit_A.md",
                            "locator_key": "EXHIBIT_A-SEC-1",
                        },
                    }
                ],
                "unresolved_gaps": [],
            },
            "SectionOutput": {
                "section_id": "sec_notice",
                "section_title": "I. Written Notice",
                "text": "Written notice was <ref n='1'>delivered October 12, 2026</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "reasoning": "Signed written delivery satisfies the notice rule.",
                        "items": [
                            {
                                "ref_id": "f1",
                                "type": "evidence",
                                "title": "Exhibit A",
                                "quote": "Delivered signed notice on October 12, 2026.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Exhibit_A.md",
                                    "locator_key": "EXHIBIT_A-SEC-1",
                                },
                            }
                        ],
                    }
                ],
            },
            "SectionAuditResult": {
                "section_id": "sec_notice",
                "check_a_relevance": True,
                "check_b_congruence": True,
                "check_c_intent": True,
                "passed": True,
            },
            "StitchedDocumentOutput": {
                "sections": [
                    {
                        "section_id": "sec_notice",
                        "smoothed_text": "Written notice was <ref n='sec_notice:1'>delivered October 12, 2026</ref>.",
                    }
                ]
            },
        }
    )

    app.state.canonical_router = CanonicalRouter(canonical_dir)
    app.state.canonical_ingestor = CanonicalIngestor(canonical_dir)
    app.state.matter_ingestor = MatterIngestor(matters_root)
    app.state.llm_provider = mock_llm

    try:
        # 1. Stream canonical upload, inspect detail, upload + delete a temp rule file
        stream_up = client.post(
            "/api/v1/canonical/upload/stream",
            data={"domain": "legal"},
            files={
                "file": (
                    "statutes.md",
                    b"# Jurisdiction Rules\n\n## Notice Rule\nWritten notice is mandatory.\n",
                    "text/markdown",
                )
            },
        )
        assert stream_up.status_code == 200
        up_events = _parse_sse_events(stream_up.text)
        assert any(e.get("event") == "progress" for e in up_events)
        assert up_events[-1]["event"] == "complete"
        assert up_events[-1]["total_authorities"] == 1

        detail_res = client.get("/api/v1/canonical/documents/legal/statutes.md")
        assert detail_res.status_code == 200
        assert len(detail_res.json()["authorities"]) == 1
        assert "Written notice is mandatory" in detail_res.json()["toc_markdown"]

        extra_up = client.post(
            "/api/v1/canonical/upload",
            data={"domain": "legal"},
            files={"file": ("temp_rule.md", b"# Temp\n\n## Rule\nTemporary.\n", "text/markdown")},
        )
        assert extra_up.status_code == 200
        del_can = client.delete("/api/v1/canonical/files/legal/temp_rule.md")
        assert del_can.status_code == 200
        assert del_can.json()["total_authorities"] == 1

        # 2. Matter upload, file listing, delete, and streaming ingest
        client.post("/api/v1/matters", json={"matter_id": "m_api_ckpt"})
        client.post(
            "/api/v1/matters/m_api_ckpt/upload",
            files={"file": ("Exhibit_A.md", b"Delivered signed notice on October 12, 2026.\n", "text/markdown")},
        )
        client.post(
            "/api/v1/matters/m_api_ckpt/upload",
            files={"file": ("Noise.md", b"Unneeded file.\n", "text/markdown")},
        )
        files_res = client.get("/api/v1/matters/m_api_ckpt/files")
        assert files_res.status_code == 200
        assert {f["filename"] for f in files_res.json()["files"]} == {"Exhibit_A.md", "Noise.md"}

        del_matter_res = client.delete("/api/v1/matters/m_api_ckpt/files/Noise.md")
        assert del_matter_res.status_code == 200
        assert [f["filename"] for f in del_matter_res.json()["files"]] == ["Exhibit_A.md"]

        ingest_stream_res = client.post("/api/v1/matters/m_api_ckpt/ingest/stream")
        assert ingest_stream_res.status_code == 200
        ing_events = _parse_sse_events(ingest_stream_res.text)
        assert any(e.get("event") == "progress" for e in ing_events)
        assert ing_events[-1]["event"] == "complete"

        # 3. Start checkpointed streaming run -> Stage 1 pause -> GET /runs/{id}/stream replay
        ask_stream = client.post(
            "/api/v1/research/matters/m_api_ckpt/ask/stream",
            json={
                "question": "Check written notice compliance.",
                "bundle_id": "api_ckpt_bundle",
                "checkpoint_mode": True,
            },
        )
        assert ask_stream.status_code == 200
        s1_events = _parse_sse_events(ask_stream.text)
        assert s1_events[0]["event"] == "run_started"
        run_id = s1_events[0]["run"]["run_id"]
        assert s1_events[-1]["event"] == "checkpoint"
        assert s1_events[-1]["run"]["status"] == "awaiting_stage1_approval"

        list_runs_res = client.get("/api/v1/research/matters/m_api_ckpt/runs")
        assert list_runs_res.status_code == 200
        assert list_runs_res.json()[0]["run_id"] == run_id

        replay_res = client.get(f"/api/v1/research/runs/{run_id}/stream")
        assert replay_res.status_code == 200
        replay_events = _parse_sse_events(replay_res.text)
        assert replay_events[-1]["event"] == "checkpoint"

        # 4. Resume Stage 1 -> Stage 2 pause via /resume/stream
        resume_s2 = client.post(f"/api/v1/research/runs/{run_id}/resume/stream", json={})
        assert resume_s2.status_code == 200
        s2_events = _parse_sse_events(resume_s2.text)
        assert s2_events[-1]["event"] == "checkpoint"
        assert s2_events[-1]["run"]["status"] == "awaiting_stage2_approval"

        # 5. Resume Stage 2 -> Completed bundle via /resume
        resume_final = client.post(f"/api/v1/research/runs/{run_id}/resume", json={})
        assert resume_final.status_code == 200
        assert resume_final.json()["bundle_id"] == "api_ckpt_bundle"
        assert "api_ckpt_bundle" in app.state.research_service.bundle_store
    finally:
        app.state.research_service.bundle_store.pop("api_ckpt_bundle", None)
        app.state.canonical_router = None
        app.state.canonical_ingestor = None
        app.state.matter_ingestor = None
        app.state.llm_provider = None


def test_file_reliability_metadata_blueprints_and_domain_ask_endpoints(tmp_path: Path) -> None:
    """Verifies reliability metadata upload/PATCH, blueprint CRUD, canonical domains, and strict ask."""
    from fastapi.testclient import TestClient
    from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
    from app.core.llm import MockLLMProvider
    from app.compilers.research.pipeline import BlueprintStore

    canonical_dir = tmp_path / "canonical"
    (canonical_dir / "raw" / "legal").mkdir(parents=True)
    (canonical_dir / "raw" / "legal" / "rules.md").write_text(
        "# Rules\n\n## Cap\nLimit is $15,150.\n", encoding="utf-8"
    )
    c_ing = CanonicalIngestor(canonical_dir)
    c_ing.ingest_corpus(llm=MockLLMProvider())
    router = CanonicalRouter(canonical_dir)
    m_ing = MatterIngestor(tmp_path / "matters")
    bp_store = BlueprintStore(tmp_path / "blueprints")

    mock_llm = MockLLMProvider(
        structured_responses={
            "VerifiedFactLedger": {
                "section_id": "sec_01",
                "verified_facts": [
                    {
                        "fact_id": "f1",
                        "query_addressed": "Survey balance",
                        "title": "Survey",
                        "quote": "Reported payroll is $10,000.",
                        "locator": {
                            "source_type": "markdown",
                            "file_name": "Survey.md",
                            "locator_key": "SURVEY-SEC-1",
                        },
                    }
                ],
            },
            "SectionOutput": {
                "section_id": "sec_01",
                "section_title": "Payroll Check",
                "text": "Owner reported <ref n='1'>$10,000 payroll</ref>.",
                "supports": [
                    {
                        "n": 1,
                        "reasoning": "From Survey.md",
                        "items": [
                            {
                                "ref_id": "f1",
                                "type": "evidence",
                                "title": "Survey.md",
                                "quote": "Reported payroll is $10,000.",
                                "locator": {
                                    "source_type": "markdown",
                                    "file_name": "Survey.md",
                                    "locator_key": "SURVEY-SEC-1",
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
        }
    )

    app.state.canonical_router = router
    app.state.canonical_ingestor = c_ing
    app.state.matter_ingestor = m_ing
    app.state.llm_provider = mock_llm
    app.state.blueprint_store = bp_store

    try:
        test_client = TestClient(app)

        # 1. Canonical status exposes domain summaries
        can_res = test_client.get("/api/v1/canonical")
        assert can_res.status_code == 200
        assert [d["domain"] for d in can_res.json()["canonical_domains"]] == ["legal"]

        # 2. Upload matter file with reliability_tier & origin_description, then PATCH metadata
        test_client.post("/api/v1/matters", json={"matter_id": "m_api_rel"})
        up_res = test_client.post(
            "/api/v1/matters/m_api_rel/upload",
            data={
                "reliability_tier": "self_reported",
                "origin_description": "Client intake questionnaire",
            },
            files={"file": ("Survey.md", b"Reported payroll is $10,000.\n", "text/markdown")},
        )
        assert up_res.status_code == 200
        assert up_res.json()["files"][0]["reliability_tier"] == "self_reported"
        assert up_res.json()["files"][0]["origin_description"] == "Client intake questionnaire"

        patch_res = test_client.patch(
            "/api/v1/matters/m_api_rel/files/Survey.md/metadata",
            json={"reliability_tier": "self_reported", "origin_description": "Signed intake PDF"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["files"][0]["origin_description"] == "Signed intake PDF"

        # 3. Blueprint CRUD + strict ask execution
        bp_list = test_client.get("/api/v1/research/blueprints")
        assert bp_list.status_code == 200
        assert len(bp_list.json()) >= 2

        create_bp = test_client.post(
            "/api/v1/research/blueprints",
            json={
                "blueprint_id": "api_custom_bp",
                "title": "API Custom Blueprint",
                "domain": "legal",
                "default_domains": ["legal"],
                "outline_plan": {
                    "document_title": "Strict API Memo",
                    "executive_summary_intent": "Verify survey payroll under reliability floor.",
                    "sections": [
                        {
                            "section_id": "sec_01",
                            "section_title": "Payroll Check",
                            "stated_intention": "Check payroll claim.",
                            "required_fact_queries": ["Survey balance"],
                        }
                    ],
                },
            },
        )
        assert create_bp.status_code == 200
        assert create_bp.json()["blueprint_id"] == "api_custom_bp"

        ask_res = test_client.post(
            "/api/v1/research/matters/m_api_rel/ask",
            json={
                "question": "Check payroll liability.",
                "bundle_id": "api_bp_bundle",
                "smooth_transitions": False,
                "canonical_domains": ["legal"],
                "blueprint_id": "api_custom_bp",
                "blueprint_mode": "strict",
            },
        )
        assert ask_res.status_code == 200
        claim = ask_res.json()["nodes"]["claim_sec_01_1"]
        # Uncorroborated self_reported survey evidence deterministically downgraded to assumption
        assert claim["audit"]["status"] == "assumption"

        del_bp = test_client.delete("/api/v1/research/blueprints/api_custom_bp")
        assert del_bp.status_code == 200
    finally:
        app.state.research_service.bundle_store.pop("api_bp_bundle", None)
        app.state.canonical_router = None
        app.state.canonical_ingestor = None
        app.state.matter_ingestor = None
        app.state.llm_provider = None
        app.state.blueprint_store = None


def test_raw_file_serving_and_bundle_available_files_metadata(tmp_path: Path) -> None:
    """Verifies raw file serving for matters/canonical sources and bundle raw-file metadata."""
    from fastapi.testclient import TestClient
    from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
    from app.core.llm import MockLLMProvider

    canonical_dir = tmp_path / "canonical"
    matters_root = tmp_path / "matters"
    test_client = TestClient(app)

    app.state.canonical_router = CanonicalRouter(canonical_dir)
    app.state.canonical_ingestor = CanonicalIngestor(canonical_dir)
    app.state.matter_ingestor = MatterIngestor(matters_root)
    app.state.llm_provider = MockLLMProvider()

    try:
        test_client.post("/api/v1/matters", json={"matter_id": "m_raw_serve"})
        matter_bytes = b"# Exhibit A\n\nSigned statement from CFO confirming wire amount.\n"
        up_matter = test_client.post(
            "/api/v1/matters/m_raw_serve/upload",
            files={"file": ("Exhibit_A.md", matter_bytes, "text/markdown")},
        )
        assert up_matter.status_code == 200

        raw_matter_res = test_client.get("/api/v1/matters/m_raw_serve/files/Exhibit_A.md/raw")
        assert raw_matter_res.status_code == 200
        assert "inline" in raw_matter_res.headers.get("content-disposition", "").lower()
        assert raw_matter_res.headers.get("content-type", "").startswith("text/plain")
        assert raw_matter_res.content == matter_bytes

        missing_matter_res = test_client.get("/api/v1/matters/m_raw_serve/files/Missing.pdf/raw")
        assert missing_matter_res.status_code == 404

        canonical_bytes = b"# Jurisdiction Statute\n\n## Section 1332\nDiversity threshold applies.\n"
        up_canonical = test_client.post(
            "/api/v1/canonical/upload",
            data={"domain": "legal"},
            files={"file": ("statutes.md", canonical_bytes, "text/markdown")},
        )
        assert up_canonical.status_code == 200

        raw_canonical_res = test_client.get("/api/v1/canonical/files/legal/statutes.md/raw")
        assert raw_canonical_res.status_code == 200
        assert "inline" in raw_canonical_res.headers.get("content-disposition", "").lower()
        assert raw_canonical_res.content == canonical_bytes

        missing_canonical_res = test_client.get("/api/v1/canonical/files/legal/missing.pdf/raw")
        assert missing_canonical_res.status_code == 404

        bundle_res = test_client.get("/api/v1/research/bundles/legal_motion_1332")
        assert bundle_res.status_code == 200
        available = bundle_res.json()["artifact"]["metadata"].get("available_raw_files")
        assert isinstance(available, list)
    finally:
        app.state.canonical_router = None
        app.state.canonical_ingestor = None
        app.state.matter_ingestor = None
        app.state.llm_provider = None


def test_unified_platform_apps_isolation_tables_and_ledgers(tmp_path: Path) -> None:
    """Verifies `/api/v1/apps`, `--apps bankruptcy` hiding `/research`, tables, and ledgers."""
    ws = tmp_path / "ws"
    shutil.copytree(Path("canonical/tables/bankruptcy"), ws / "canonical" / "tables" / "bankruptcy")
    shutil.copytree(Path("templates"), ws / "templates")
    shutil.copytree(Path("static"), ws / "static")

    # 1. Both apps co-mounted
    both_app = create_platform_app(base_dir=ws, enabled_apps=["bankruptcy", "research"], seed_samples=True)
    c_both = TestClient(both_app)
    apps_res = c_both.get("/api/v1/apps")
    assert apps_res.status_code == 200
    assert apps_res.json()["default_app"] == "bankruptcy"
    assert [a["app_id"] for a in apps_res.json()["apps"]] == ["bankruptcy", "research"]

    cases_res = c_both.get("/api/v1/apps/cases")
    assert cases_res.status_code == 200
    assert any(r["app_id"] == "bankruptcy" for r in cases_res.json()["cases"])
    assert any(r["app_id"] == "research" for r in cases_res.json()["cases"])

    tbl_sync = c_both.post("/api/v1/tables/bankruptcy/sync")
    assert tbl_sync.status_code == 200
    assert tbl_sync.json()["domain"] == "bankruptcy"
    assert len(tbl_sync.json()["tables_verified"]) >= 4

    ledgers_res = c_both.get("/api/v1/matters/bk_ch7_cacb_martinez/ledgers")
    assert ledgers_res.status_code == 200
    assert len(ledgers_res.json()["ledgers"]) == 1
    assert ledgers_res.json()["ledgers"][0]["app_id"] == "bankruptcy"

    # 2. Bankruptcy-only partner launcher hides /research completely
    bk_only = create_platform_app(base_dir=ws, enabled_apps=["bankruptcy"], seed_samples=True)
    c_bk = TestClient(bk_only)
    apps_only = c_bk.get("/api/v1/apps").json()
    assert [a["app_id"] for a in apps_only["apps"]] == ["bankruptcy"]
    assert c_bk.get("/bankruptcy").status_code == 200
    assert c_bk.get("/research").status_code == 404
    assert c_bk.get("/api/v1/research/bundles").status_code == 404


