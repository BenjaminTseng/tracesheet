"""FastAPI routes for serving the bounded spatial canvas, ingestion, agentic Q&A, and review loops."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import LLMProvider, create_llm_provider
from app.models import (
    AuditStatus,
    CompiledBundle,
    CompiledGraphBuilder,
    ReviewComment,
    SectionOutput,
    SectionValidator,
    StitchInvariantGate,
    TensionObject,
)
from app.pipeline import AuditPipelineRunner
from app.sample_data import get_sample_bundles

logger = logging.getLogger("jd_screen")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _load_initial_bundle_store() -> Dict[str, CompiledBundle]:
    """Initializes `BUNDLE_STORE` with sample bundles plus any persisted matter bundles."""
    store: Dict[str, CompiledBundle] = get_sample_bundles()
    matters_dir = BASE_DIR / "matters"
    if matters_dir.exists():
        for bundle_path in sorted(matters_dir.glob("*/bundles/*.json")):
            try:
                loaded = CompiledBundle.model_validate_json(
                    bundle_path.read_text(encoding="utf-8")
                )
                b_id = loaded.bundle_id or bundle_path.stem
                loaded.bundle_id = b_id
                store[b_id] = loaded
            except Exception as exc:
                logger.warning("Failed to load persisted bundle %s: %s", bundle_path, exc)
    return store


BUNDLE_STORE: Dict[str, CompiledBundle] = _load_initial_bundle_store()

router = APIRouter()


# =====================================================================
# Request / Response Schemas
# =====================================================================

class BundleSummaryItem(BaseModel):
    """Compact summary metadata for the bundle selector dropdown."""

    bundle_id: str
    matter_id: Optional[str] = None
    title: str
    document_type: str
    total_claims: int
    verified_count: int
    extrapolation_count: int
    assumption_count: int
    tension_count: int
    pending_comments: int = 0


class CompilePipelineRequest(BaseModel):
    """Payload for compiling Tier 1 intermediate sections into a Tier 2 bundle."""

    bundle_id: str = "custom_compiled_bundle"
    title: str
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sections: List[SectionOutput] = Field(min_length=1)
    smoothed_text: Optional[str] = None
    tensions: List[TensionObject] = Field(default_factory=list)


class CreateMatterRequest(BaseModel):
    """Request body for creating a new project matter workspace."""

    matter_id: str = Field(min_length=1)


class AskMatterRequest(BaseModel):
    """Request body for executing the 4-stage pipeline on a matter question `(c)`."""

    question: str = Field(min_length=1)
    bundle_id: Optional[str] = None
    smooth_transitions: bool = True


class AddCommentRequest(BaseModel):
    """Request body for anchoring a human review comment onto a graph node."""

    node_id: str
    section_id: str
    comment_text: str = Field(min_length=1)
    suggested_status: Optional[AuditStatus] = None


class RegenerateRequest(BaseModel):
    """Request body for batched feedback regeneration."""

    comments: List[ReviewComment] = Field(default_factory=list)
    smooth_transitions: bool = True


class CanonicalIngestRequest(BaseModel):
    """Request body for rebuilding canonical `[AUTH:...]` artifacts and `INDEX.md`."""

    purge_encoded: bool = False


# =====================================================================
# Runtime Service Resolution Helpers
# =====================================================================

def _get_corpus_services(
    request: Request,
) -> Tuple[CanonicalRouter, MatterIngestor, CanonicalIngestor]:
    """Resolves `CanonicalRouter`, `MatterIngestor`, and `CanonicalIngestor` without an LLM client."""
    state = request.app.state
    canonical_router = getattr(state, "canonical_router", None) or CanonicalRouter(
        BASE_DIR / "canonical"
    )
    matter_ingestor = getattr(state, "matter_ingestor", None) or MatterIngestor(
        BASE_DIR / "matters"
    )
    canonical_ingestor = getattr(state, "canonical_ingestor", None) or CanonicalIngestor(
        canonical_router.canonical_dir
    )
    return canonical_router, matter_ingestor, canonical_ingestor


def _get_optional_llm_provider(request: Request) -> Optional[LLMProvider]:
    """Resolves an `LLMProvider` if configured or attached in `app.state`, else returns `None`."""
    state = request.app.state
    explicit = getattr(state, "llm_provider", None)
    if explicit is not None:
        return explicit
    cfg = getattr(state, "llm_config", {}) or {}
    try:
        return create_llm_provider(
            provider_name=cfg.get("provider", "gemini"),
            model=cfg.get("model"),
            api_key=cfg.get("api_key"),
        )
    except Exception:
        return None


def _get_services(
    request: Request,
) -> Tuple[CanonicalRouter, MatterIngestor, LLMProvider]:
    """Resolves active `CanonicalRouter`, `MatterIngestor`, and `LLMProvider`.

    Respects test overrides attached to `app.state`, falling back to workspace
    directories and CLI `--provider` / `--model` configuration.
    """
    canonical_router, matter_ingestor, _ = _get_corpus_services(request)
    state = request.app.state
    llm_provider = getattr(state, "llm_provider", None)
    if llm_provider is None:
        cfg = getattr(state, "llm_config", {}) or {}
        llm_provider = create_llm_provider(
            provider_name=cfg.get("provider", "gemini"),
            model=cfg.get("model"),
            api_key=cfg.get("api_key"),
        )
    return canonical_router, matter_ingestor, llm_provider


def _persist_bundle(bundle: CompiledBundle, matter_ingestor: MatterIngestor) -> None:
    """Persists bundle JSON to disk without requiring an active LLM provider."""
    if not bundle.matter_id or not bundle.bundle_id:
        return
    _, _, _, bundles_dir = matter_ingestor._matter_dirs(bundle.matter_id)
    bundles_dir.mkdir(parents=True, exist_ok=True)
    out_path = bundles_dir / f"{bundle.bundle_id}.json"
    out_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")


def _sanitize_slug(raw: str) -> str:
    """Converts a user-entered matter or bundle name into a safe filesystem slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip()).strip("_").lower()
    if not slug:
        raise HTTPException(status_code=422, detail="Invalid identifier slug.")
    return slug


# =====================================================================
# Canvas & Bundle Endpoints
# =====================================================================

@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Renders the main Bounded Spatial Canvas workspace interface."""
    logger.info("Rendering Bounded Spatial Canvas index view.")
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/api/bundles", response_model=List[BundleSummaryItem])
async def list_bundles() -> List[BundleSummaryItem]:
    """Lists all available audit bundles with summary verification metrics."""
    items: List[BundleSummaryItem] = []
    for b_id, bundle in BUNDLE_STORE.items():
        doc_type = str(
            bundle.artifact.metadata.get("document_type", "Audit-Grounded Artifact")
        )
        pending = sum(1 for c in bundle.comments if not c.resolved)
        items.append(
            BundleSummaryItem(
                bundle_id=b_id,
                matter_id=bundle.matter_id,
                title=bundle.artifact.title,
                document_type=doc_type,
                total_claims=bundle.audit_summary.total_claims,
                verified_count=bundle.audit_summary.verified_count,
                extrapolation_count=bundle.audit_summary.extrapolation_count,
                assumption_count=bundle.audit_summary.assumption_count,
                tension_count=len(bundle.audit_summary.cross_section_tensions),
                pending_comments=pending,
            )
        )
    return items


@router.get("/api/bundles/{bundle_id}", response_model=CompiledBundle)
async def get_bundle(bundle_id: str) -> CompiledBundle:
    """Retrieves a specific compiled audit bundle by its identifier."""
    if bundle_id not in BUNDLE_STORE:
        logger.warning("Requested unknown bundle_id=%s", bundle_id)
        raise HTTPException(
            status_code=404, detail=f"Bundle '{bundle_id}' was not found."
        )
    logger.info("Serving compiled bundle_id=%s", bundle_id)
    return BUNDLE_STORE[bundle_id]


@router.post("/api/bundles", response_model=CompiledBundle)
async def upload_compiled_bundle(payload: Dict[str, Any]) -> CompiledBundle:
    """Validates and registers a custom Tier 2 `CompiledBundle` JSON payload."""
    try:
        bundle = CompiledBundle.model_validate(payload)
    except ValidationError as exc:
        logger.error("Custom bundle schema validation failed: %s", exc)
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

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
    """Validates Tier 1 sections, checks stitch invariants, and compiles a DAG bundle."""
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
        has_namespaced_tags = bool(
            re.search(r"<ref\s+n=['\"][^:'\"]+:\d+['\"]>", req.smoothed_text)
        )
        pre_stitched = (
            StitchInvariantGate.prepare_for_stitch(req.sections)
            if has_namespaced_tags
            else "\n\n".join(s.text for s in req.sections)
        )
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


# =====================================================================
# Project Matters, Canonical Corpus, Ingestion & Agentic Q&A Endpoints
# =====================================================================

@router.get("/api/canonical")
async def get_canonical_corpus(request: Request) -> Dict[str, Any]:
    """Returns canonical `INDEX.md`, active `[AUTH:...]` blocks, and raw source inventory."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    return canonical_ingestor.get_corpus_status()


@router.post("/api/canonical/upload")
async def upload_canonical_file(
    request: Request,
    domain: str = Form("general"),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Uploads a raw canonical document into `canonical/raw/<domain>/` and encodes it."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    domain_dir = canonical_ingestor.create_domain(domain)

    safe_name = Path(file.filename or "canonical_source.md").name
    dest_path = domain_dir / safe_name
    content = await file.read()
    dest_path.write_bytes(content)

    optional_llm = _get_optional_llm_provider(request)
    summary = await asyncio.to_thread(canonical_ingestor.ingest_corpus, False, optional_llm)
    return {
        "domain": domain_dir.name,
        "uploaded_file": safe_name,
        "summary": summary,
        **canonical_ingestor.get_corpus_status(),
    }


@router.post("/api/canonical/ingest")
async def ingest_canonical_corpus(
    request: Request,
    req: Optional[CanonicalIngestRequest] = None,
) -> Dict[str, Any]:
    """Re-encodes raw canonical files into `[AUTH:...]` Markdown and rebuilds `INDEX.md`."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    purge = req.purge_encoded if req is not None else False
    optional_llm = _get_optional_llm_provider(request)
    summary = await asyncio.to_thread(canonical_ingestor.ingest_corpus, purge, optional_llm)
    return {"summary": summary, **canonical_ingestor.get_corpus_status()}


@router.get("/api/matters")
async def list_matters_and_corpus(request: Request) -> Dict[str, Any]:
    """Lists all project matters `(a)` and standing canonical authorities `(b)`."""
    canonical_router, matter_ingestor, _ = _get_corpus_services(request)
    authorities = [
        auth.model_dump() for auth in canonical_router.list_authorities().values()
    ]
    return {
        "matters": matter_ingestor.list_matters(),
        "canonical_authorities": authorities,
    }


@router.post("/api/matters")
async def create_matter(req: CreateMatterRequest, request: Request) -> Dict[str, Any]:
    """Creates a new isolated project matter workspace under `matters/<matter_id>`."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(req.matter_id)
    matter_dir = matter_ingestor.create_matter(slug)
    return {"matter_id": slug, "path": str(matter_dir)}


@router.post("/api/matters/{matter_id}/upload")
async def upload_matter_file(
    matter_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Uploads a raw project file (`.pdf`, `.xlsx`, `.csv`, `.md`, `.txt`) and ingests it."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    matter_ingestor.create_matter(slug)
    _, raw_dir, _, _ = matter_ingestor._matter_dirs(slug)

    safe_name = Path(file.filename or "uploaded_input.md").name
    dest_path = raw_dir / safe_name
    content = await file.read()
    dest_path.write_bytes(content)

    manifest = await asyncio.to_thread(matter_ingestor.ingest_matter, slug)
    return {"matter_id": slug, "uploaded_file": safe_name, "manifest": manifest}


@router.post("/api/matters/{matter_id}/ingest")
async def ingest_matter_inputs(matter_id: str, request: Request) -> Dict[str, Any]:
    """Runs deterministic coordinate extraction on `matters/<matter_id>/inputs/raw/`."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    manifest = await asyncio.to_thread(matter_ingestor.ingest_matter, slug)
    return manifest


@router.post("/api/matters/{matter_id}/ask", response_model=CompiledBundle)
async def ask_matter_question(
    matter_id: str,
    req: AskMatterRequest,
    request: Request,
) -> CompiledBundle:
    """Executes the 4-stage agentic pipeline for question `(c)` and registers the bundle."""
    canonical_router, matter_ingestor, llm_provider = _get_services(request)
    slug = _sanitize_slug(matter_id)
    runner = AuditPipelineRunner(llm_provider, canonical_router, matter_ingestor)

    bundle = await asyncio.to_thread(
        runner.run_full_pipeline,
        slug,
        req.question,
        req.bundle_id,
        req.smooth_transitions,
    )
    if bundle.bundle_id:
        BUNDLE_STORE[bundle.bundle_id] = bundle
    return bundle


@router.post("/api/matters/{matter_id}/ask/stream")
async def ask_matter_question_stream(
    matter_id: str,
    req: AskMatterRequest,
    request: Request,
) -> StreamingResponse:
    """Streams SSE stage progress while running the 4-stage pipeline, ending with the bundle."""
    canonical_router, matter_ingestor, llm_provider = _get_services(request)
    slug = _sanitize_slug(matter_id)
    runner = AuditPipelineRunner(llm_provider, canonical_router, matter_ingestor)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

    def on_progress(stage: str, message: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"event": "progress", "stage": stage, "message": message}
        )

    async def worker() -> None:
        try:
            bundle = await asyncio.to_thread(
                runner.run_full_pipeline,
                slug,
                req.question,
                req.bundle_id,
                req.smooth_transitions,
                on_progress,
            )
            if bundle.bundle_id:
                BUNDLE_STORE[bundle.bundle_id] = bundle
            await queue.put({"event": "bundle", "bundle": bundle.model_dump()})
        except Exception as exc:
            logger.exception("Streaming pipeline error for matter=%s", slug)
            await queue.put({"event": "error", "detail": str(exc)})
        finally:
            await queue.put(None)

    asyncio.create_task(worker())

    async def event_stream() -> AsyncGenerator[str, None]:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# =====================================================================
# Antigravity-Style Inline Review Comments & Batch Regeneration
# =====================================================================

@router.post("/api/bundles/{bundle_id}/comments", response_model=CompiledBundle)
async def add_review_comment(
    bundle_id: str,
    req: AddCommentRequest,
    request: Request,
) -> CompiledBundle:
    """Anchors a human review comment onto an `L0`, `L1`, or `L2+` node in a bundle."""
    if bundle_id not in BUNDLE_STORE:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")

    bundle = BUNDLE_STORE[bundle_id]
    if req.node_id not in bundle.nodes:
        raise HTTPException(
            status_code=422, detail=f"Target node '{req.node_id}' not found in bundle."
        )

    comment = ReviewComment(
        comment_id=f"cmt_{uuid.uuid4().hex[:8]}",
        node_id=req.node_id,
        section_id=req.section_id,
        comment_text=req.comment_text,
        suggested_status=req.suggested_status,
        resolved=False,
    )
    bundle.comments.append(comment)

    _, matter_ingestor, _ = _get_corpus_services(request)
    _persist_bundle(bundle, matter_ingestor)
    return bundle


@router.delete("/api/bundles/{bundle_id}/comments/{comment_id}", response_model=CompiledBundle)
async def delete_review_comment(
    bundle_id: str,
    comment_id: str,
    request: Request,
) -> CompiledBundle:
    """Deletes a queued review comment from the bundle before regeneration."""
    if bundle_id not in BUNDLE_STORE:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")

    bundle = BUNDLE_STORE[bundle_id]
    bundle.comments = [c for c in bundle.comments if c.comment_id != comment_id]

    _, matter_ingestor, _ = _get_corpus_services(request)
    _persist_bundle(bundle, matter_ingestor)
    return bundle


@router.post("/api/bundles/{bundle_id}/regenerate", response_model=CompiledBundle)
async def regenerate_from_feedback(
    bundle_id: str,
    req: RegenerateRequest,
    request: Request,
) -> CompiledBundle:
    """Applies all queued review comments using smart Stage-2 fallback regeneration."""
    if bundle_id not in BUNDLE_STORE:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")

    bundle = BUNDLE_STORE[bundle_id]
    canonical_router, matter_ingestor, llm_provider = _get_services(request)
    runner = AuditPipelineRunner(llm_provider, canonical_router, matter_ingestor)

    updated = await asyncio.to_thread(
        runner.apply_comments_and_recompile,
        bundle,
        req.comments,
        req.smooth_transitions,
    )
    BUNDLE_STORE[bundle_id] = updated
    return updated
