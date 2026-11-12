"""FastAPI routes for serving the bounded spatial canvas and bundle validation APIs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from app.models import (
    CompiledBundle,
    CompiledGraphBuilder,
    SectionOutput,
    SectionValidator,
    StitchInvariantGate,
    TensionObject,
)
from app.sample_data import get_sample_bundles

logger = logging.getLogger("jd_screen")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# In-memory store initialized with verified sample bundles
BUNDLE_STORE: Dict[str, CompiledBundle] = get_sample_bundles()


class BundleSummaryItem(BaseModel):
    """Compact summary metadata for the bundle selector dropdown.

    Attributes:
        bundle_id: Unique slug identifier for the bundle.
        title: Document title.
        document_type: Classification from artifact metadata.
        total_claims: Count of claim nodes.
        verified_count: Count of verified claims.
        extrapolation_count: Count of extrapolated claims.
        assumption_count: Count of assumption claims.
        tension_count: Count of cross-section tensions.
    """

    bundle_id: str
    title: str
    document_type: str
    total_claims: int
    verified_count: int
    extrapolation_count: int
    assumption_count: int
    tension_count: int


class CompilePipelineRequest(BaseModel):
    """Payload for compiling Tier 1 intermediate sections into a Tier 2 bundle.

    Attributes:
        bundle_id: Target identifier for storing the compiled bundle.
        title: Document title.
        summary: Optional executive summary.
        metadata: Optional document metadata dictionary.
        sections: Ordered list of Tier 1 `SectionOutput` objects.
        smoothed_text: Optional post-editorial unified markdown string.
        tensions: Optional cross-section tension alerts.
    """

    bundle_id: str = "custom_compiled_bundle"
    title: str
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sections: List[SectionOutput] = Field(min_length=1)
    smoothed_text: Optional[str] = None
    tensions: List[TensionObject] = Field(default_factory=list)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Renders the main Bounded Spatial Canvas workspace interface.

    Args:
        request: Incoming FastAPI HTTP request.

    Returns:
        Rendered HTML response containing the application shell.
    """
    logger.info("Rendering Bounded Spatial Canvas index view.")
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/api/bundles", response_model=List[BundleSummaryItem])
async def list_bundles() -> List[BundleSummaryItem]:
    """Lists all available audit bundles with summary verification metrics.

    Returns:
        List of `BundleSummaryItem` objects.
    """
    items: List[BundleSummaryItem] = []
    for b_id, bundle in BUNDLE_STORE.items():
        doc_type = str(
            bundle.artifact.metadata.get("document_type", "Audit-Grounded Artifact")
        )
        items.append(
            BundleSummaryItem(
                bundle_id=b_id,
                title=bundle.artifact.title,
                document_type=doc_type,
                total_claims=bundle.audit_summary.total_claims,
                verified_count=bundle.audit_summary.verified_count,
                extrapolation_count=bundle.audit_summary.extrapolation_count,
                assumption_count=bundle.audit_summary.assumption_count,
                tension_count=len(bundle.audit_summary.cross_section_tensions),
            )
        )
    return items


@router.get("/api/bundles/{bundle_id}", response_model=CompiledBundle)
async def get_bundle(bundle_id: str) -> CompiledBundle:
    """Retrieves a specific compiled audit bundle by its identifier.

    Args:
        bundle_id: Unique slug of the bundle to fetch.

    Returns:
        Full `CompiledBundle` payload.

    Raises:
        HTTPException: 404 if the bundle_id is not registered.
    """
    if bundle_id not in BUNDLE_STORE:
        logger.warning("Requested unknown bundle_id=%s", bundle_id)
        raise HTTPException(
            status_code=404, detail=f"Bundle '{bundle_id}' was not found."
        )
    logger.info("Serving compiled bundle_id=%s", bundle_id)
    return BUNDLE_STORE[bundle_id]


@router.post("/api/bundles", response_model=CompiledBundle)
async def upload_compiled_bundle(payload: Dict[str, Any]) -> CompiledBundle:
    """Validates and registers a custom Tier 2 `CompiledBundle` JSON payload.

    Args:
        payload: Raw JSON dictionary conforming to `CompiledBundle`.

    Returns:
        Validated `CompiledBundle` stored in the active session registry.

    Raises:
        HTTPException: 422 if schema validation or node reference integrity fails.
    """
    try:
        bundle = CompiledBundle.model_validate(payload)
    except ValidationError as exc:
        logger.error("Custom bundle schema validation failed: %s", exc)
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    # Verify that all direct_child_ids resolve to existing keys in bundle.nodes
    missing_targets: List[str] = []
    for node_id, node in bundle.nodes.items():
        for child_id in node.direct_child_ids:
            if child_id not in bundle.nodes:
                missing_targets.append(f"{node_id} -> {child_id}")

    if missing_targets:
        raise HTTPException(
            status_code=422,
            detail=f"Broken graph edges detected (missing target nodes): {missing_targets}",
        )

    bundle_id = bundle.bundle_id or f"custom_{len(BUNDLE_STORE) + 1}"
    bundle.bundle_id = bundle_id
    BUNDLE_STORE[bundle_id] = bundle
    logger.info("Registered custom compiled bundle_id=%s", bundle_id)
    return bundle


@router.post("/api/compile", response_model=CompiledBundle)
async def compile_intermediate_sections(
    req: CompilePipelineRequest,
) -> CompiledBundle:
    """Validates Tier 1 sections, checks stitch invariants, and compiles a DAG bundle.

    Args:
        req: `CompilePipelineRequest` containing intermediate sections and optional
            smoothed document text.

    Returns:
        Newly compiled and registered `CompiledBundle`.

    Raises:
        HTTPException: 422 if `SectionValidator` or `StitchInvariantGate` fails.
    """
    all_errors: List[str] = []
    for sec in req.sections:
        is_valid, sec_errors = SectionValidator.validate_section(sec)
        if not is_valid:
            for err in sec_errors:
                all_errors.append(f"[{sec.section_id}] {err}")

    if all_errors:
        logger.warning("Section validation failed during compile: %s", all_errors)
        raise HTTPException(status_code=422, detail={"validation_errors": all_errors})

    if req.smoothed_text:
        pre_stitched = "\n\n".join(s.text for s in req.sections)
        passed_stitch, stitch_violations = StitchInvariantGate.verify_stitch(
            pre_stitched, req.smoothed_text
        )
        if not passed_stitch:
            logger.warning("Stitch invariant gate failed: %s", stitch_violations)
            raise HTTPException(
                status_code=422, detail={"stitch_violations": stitch_violations}
            )

    builder = CompiledGraphBuilder(
        document_title=req.title,
        summary=req.summary,
        metadata=req.metadata,
    )
    compiled = builder.compile_sections(
        sections=req.sections,
        final_smoothed_text=req.smoothed_text,
        tensions=req.tensions,
    )
    compiled.bundle_id = req.bundle_id
    BUNDLE_STORE[req.bundle_id] = compiled
    logger.info("Successfully compiled intermediate sections into bundle_id=%s", req.bundle_id)
    return compiled
