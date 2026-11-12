# Run test: uv run pytest tests/test_api.py -v
"""Integration tests for FastAPI routes and compilation endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app

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
