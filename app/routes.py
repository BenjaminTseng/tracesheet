"""FastAPI routes for serving the bounded spatial canvas, ingestion, agentic Q&A, and review loops."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import LLMProvider, MockLLMProvider, create_llm_provider
from app.models import (
    AuditStatus,
    BlueprintMode,
    CommentScope,
    CompiledBundle,
    CompiledGraphBuilder,
    DocumentBlueprint,
    OutlinePlan,
    PipelineRunRecord,
    ReviewComment,
    SectionOutput,
    SectionPlan,
    SectionValidator,
    SourceReliabilityTier,
    StitchInvariantGate,
    TensionObject,
)
from app.pipeline import AuditPipelineRunner, BlueprintStore
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
    checkpoint_mode: bool = False
    run_id: Optional[str] = None
    canonical_domains: Optional[List[str]] = None
    blueprint_id: Optional[str] = None
    blueprint_mode: BlueprintMode = "none"


class UpdateMatterFileMetadataRequest(BaseModel):
    """Request body for updating origin & reliability tier metadata on a matter input `(a)`."""

    reliability_tier: SourceReliabilityTier = "primary_record"
    origin_description: Optional[str] = None


class CreateBlueprintRequest(BaseModel):
    """Request body for saving a reusable Document Blueprint `(d)`."""

    blueprint_id: Optional[str] = None
    title: str = Field(min_length=1)
    domain: str = "general"
    description: Optional[str] = None
    default_domains: List[str] = Field(default_factory=list)
    document_title_template: Optional[str] = None
    executive_summary_intent: Optional[str] = None
    sections: List[SectionPlan] = Field(default_factory=list)
    outline_plan: Optional[OutlinePlan] = None
    source_run_id: Optional[str] = None


class ResumeRunRequest(BaseModel):
    """Request body for resuming a persisted or checkpointed pipeline run."""

    outline_plan: Optional[OutlinePlan] = None
    reharvest_section_ids: Optional[List[str]] = None
    smooth_transitions: Optional[bool] = None
    checkpoint_mode: Optional[bool] = None


class AddCommentRequest(BaseModel):
    """Request body for anchoring feedback onto a node, logical link, section, or overall document."""

    scope: CommentScope = "node"
    node_id: Optional[str] = None
    section_id: Optional[str] = None
    target_label: Optional[str] = None
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


def _make_run_reader(request: Request) -> AuditPipelineRunner:
    """Builds a pipeline runner suitable for reading/listing persisted run JSON without an LLM call."""
    canonical_router, matter_ingestor, _ = _get_corpus_services(request)
    llm = _get_optional_llm_provider(request) or MockLLMProvider()
    blueprints_root = getattr(request.app.state, "blueprints_root", None)
    return AuditPipelineRunner(
        llm, canonical_router, matter_ingestor, blueprints_root=blueprints_root
    )


def _build_pipeline_runner(request: Request) -> AuditPipelineRunner:
    """Instantiates `AuditPipelineRunner` with resolved services and blueprint store."""
    canonical_router, matter_ingestor, llm_provider = _get_services(request)
    blueprints_root = _get_blueprint_store(request).blueprints_root
    return AuditPipelineRunner(
        llm_provider,
        canonical_router,
        matter_ingestor,
        blueprints_root=blueprints_root,
    )


def _get_blueprint_store(request: Request) -> BlueprintStore:
    """Resolves `BlueprintStore` respecting optional `app.state` test overrides."""
    explicit = getattr(request.app.state, "blueprint_store", None)
    if explicit is not None:
        return explicit
    _, matter_ingestor, _ = _get_corpus_services(request)
    blueprints_root = getattr(request.app.state, "blueprints_root", None)
    return BlueprintStore(blueprints_root or (matter_ingestor.matters_root.parent / "blueprints"))


def _stream_worker_sse(
    work_fn: Callable[[Callable[[str, str], None]], Dict[str, Any]],
) -> StreamingResponse:
    """Runs a blocking ingestion helper in a worker thread while streaming SSE progress events."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

    def on_progress(stage: str, message: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"event": "progress", "stage": stage, "message": message},
        )

    async def worker() -> None:
        try:
            payload = await asyncio.to_thread(work_fn, on_progress)
            await queue.put({"event": "complete", **payload})
        except Exception as exc:
            logger.exception("Streaming ingestion error")
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


@dataclass
class _ActiveRunStream:
    """Tracks live SSE subscribers for an actively executing `PipelineRunRecord`."""

    run_id: str
    subscribers: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue[Optional[Dict[str, Any]]]]] = (
        field(default_factory=list)
    )
    done: bool = False


def _get_run_streams(request: Request) -> Dict[str, _ActiveRunStream]:
    """Returns per-app active SSE run registry stored on `app.state`."""
    streams = getattr(request.app.state, "active_run_streams", None)
    if streams is None:
        streams = {}
        request.app.state.active_run_streams = streams
    return streams


def _broadcast_run_event(stream: _ActiveRunStream, payload: Optional[Dict[str, Any]]) -> None:
    """Delivers an event (or `None` sentinel) thread-safely to all subscribers on `stream`."""
    for loop, queue in list(stream.subscribers):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except RuntimeError:
            pass


def _launch_run_background(
    request: Request,
    runner: AuditPipelineRunner,
    run: PipelineRunRecord,
) -> Tuple[_ActiveRunStream, asyncio.Queue[Optional[Dict[str, Any]]]]:
    """Starts `runner.execute_run` in the background and returns `(stream, initial_queue)`."""
    streams = _get_run_streams(request)
    loop = asyncio.get_running_loop()
    initial_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
    stream = _ActiveRunStream(run_id=run.run_id, subscribers=[(loop, initial_queue)])
    streams[run.run_id] = stream

    runner.save_run(run)
    initial_queue.put_nowait({"event": "run_started", "run": run.model_dump()})

    def on_progress(stage: str, message: str) -> None:
        _broadcast_run_event(
            stream,
            {
                "event": "progress",
                "stage": stage,
                "message": message,
                "run_id": run.run_id,
                "seq": len(run.events),
            },
        )

    async def worker() -> None:
        try:
            updated_run, bundle = await asyncio.to_thread(
                runner.execute_run, run, on_progress
            )
            if bundle is not None:
                if bundle.bundle_id:
                    BUNDLE_STORE[bundle.bundle_id] = bundle
                _broadcast_run_event(
                    stream,
                    {
                        "event": "bundle",
                        "bundle": bundle.model_dump(),
                        "run": updated_run.model_dump(),
                    },
                )
            else:
                _broadcast_run_event(
                    stream,
                    {"event": "checkpoint", "run": updated_run.model_dump()},
                )
        except Exception as exc:
            logger.exception("Streaming pipeline error for run=%s", run.run_id)
            _broadcast_run_event(
                stream,
                {
                    "event": "error",
                    "detail": str(exc),
                    "run": run.model_dump(),
                },
            )
        finally:
            stream.done = True
            _broadcast_run_event(stream, None)
            streams.pop(run.run_id, None)

    asyncio.create_task(worker())
    return stream, initial_queue


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
    """Returns canonical `INDEX.md`, active `[AUTH:...]` blocks, domains, and raw source inventory."""
    canonical_router, _, canonical_ingestor = _get_corpus_services(request)
    status = canonical_ingestor.get_corpus_status()
    status["canonical_domains"] = canonical_router.list_domains()
    return status


@router.get("/api/canonical/documents/{doc_id:path}")
async def get_canonical_document_detail(doc_id: str, request: Request) -> Dict[str, Any]:
    """Returns Tier 2 TOC markdown and parsed `[AUTH:...]` rules for a single canonical document."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    try:
        detail = canonical_ingestor.get_document_detail(doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail["card"] is None and not detail["authorities"] and not detail["toc_markdown"]:
        raise HTTPException(status_code=404, detail=f"Canonical document '{doc_id}' not found.")
    return detail


@router.delete("/api/canonical/files/{domain}/{filename}")
async def delete_canonical_document(
    domain: str,
    filename: str,
    request: Request,
) -> Dict[str, Any]:
    """Deletes a canonical raw/encoded file and rebuilds `INDEX.md`."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    optional_llm = _get_optional_llm_provider(request)
    try:
        return await asyncio.to_thread(
            canonical_ingestor.delete_canonical_file,
            domain,
            filename,
            optional_llm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.post("/api/canonical/upload/stream")
async def upload_canonical_file_stream(
    request: Request,
    domain: str = Form("general"),
    file: UploadFile = File(...),
) -> StreamingResponse:
    """Uploads a canonical file and streams SSE progress events during encoding & index rebuild."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    domain_dir = canonical_ingestor.create_domain(domain)

    safe_name = Path(file.filename or "canonical_source.md").name
    dest_path = domain_dir / safe_name
    content = await file.read()
    dest_path.write_bytes(content)
    optional_llm = _get_optional_llm_provider(request)

    def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
        cb("upload", f"Saved {safe_name} into canonical/raw/{domain_dir.name}/")
        summary = canonical_ingestor.ingest_corpus(False, optional_llm, progress_callback=cb)
        return {
            "domain": domain_dir.name,
            "uploaded_file": safe_name,
            "summary": summary,
            **canonical_ingestor.get_corpus_status(),
        }

    return _stream_worker_sse(run_work)


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


@router.post("/api/canonical/ingest/stream")
async def ingest_canonical_corpus_stream(
    request: Request,
    req: Optional[CanonicalIngestRequest] = None,
) -> StreamingResponse:
    """Streams SSE progress events while re-encoding raw canonical files and rebuilding `INDEX.md`."""
    _, _, canonical_ingestor = _get_corpus_services(request)
    purge = req.purge_encoded if req is not None else False
    optional_llm = _get_optional_llm_provider(request)

    def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
        summary = canonical_ingestor.ingest_corpus(purge, optional_llm, progress_callback=cb)
        return {"summary": summary, **canonical_ingestor.get_corpus_status()}

    return _stream_worker_sse(run_work)


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


@router.get("/api/matters/{matter_id}/files")
async def list_matter_files(matter_id: str, request: Request) -> Dict[str, Any]:
    """Lists raw and indexed file metadata for a specific project matter."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    return matter_ingestor.list_matter_files(slug)


@router.delete("/api/matters/{matter_id}/files/{filename}")
async def delete_matter_file(
    matter_id: str,
    filename: str,
    request: Request,
) -> Dict[str, Any]:
    """Deletes a raw project file and refreshes the matter's coordinate index."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    try:
        return await asyncio.to_thread(matter_ingestor.delete_matter_file, slug, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/api/matters/{matter_id}/files/{filename}/metadata")
async def update_matter_file_metadata(
    matter_id: str,
    filename: str,
    req: UpdateMatterFileMetadataRequest,
    request: Request,
) -> Dict[str, Any]:
    """Updates the `reliability_tier` and `origin_description` metadata on an uploaded matter file `(a)`."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    _, raw_dir, _, _ = matter_ingestor._matter_dirs(slug)
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename or ".." in filename:
        raise HTTPException(status_code=422, detail=f"Invalid filename: {filename}")
    target = raw_dir / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=404, detail=f"Matter file '{safe_name}' not found in '{slug}'."
        )
    matter_ingestor.set_file_metadata(
        slug,
        safe_name,
        reliability_tier=req.reliability_tier,
        origin_description=req.origin_description,
    )
    return matter_ingestor.list_matter_files(slug)


@router.post("/api/matters/{matter_id}/upload")
async def upload_matter_file(
    matter_id: str,
    request: Request,
    file: UploadFile = File(...),
    reliability_tier: SourceReliabilityTier = Form("primary_record"),
    origin_description: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Uploads a raw project file (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.md`, `.txt`) and ingests it."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    matter_ingestor.create_matter(slug)
    _, raw_dir, _, _ = matter_ingestor._matter_dirs(slug)

    safe_name = Path(file.filename or "uploaded_input.md").name
    dest_path = raw_dir / safe_name
    content = await file.read()
    dest_path.write_bytes(content)
    matter_ingestor.set_file_metadata(
        slug,
        safe_name,
        reliability_tier=reliability_tier,
        origin_description=origin_description,
    )

    manifest = await asyncio.to_thread(matter_ingestor.ingest_matter, slug)
    return {
        "matter_id": slug,
        "uploaded_file": safe_name,
        "manifest": manifest,
        **matter_ingestor.list_matter_files(slug),
    }


@router.post("/api/matters/{matter_id}/upload/stream")
async def upload_matter_file_stream(
    matter_id: str,
    request: Request,
    file: UploadFile = File(...),
    reliability_tier: SourceReliabilityTier = Form("primary_record"),
    origin_description: Optional[str] = Form(None),
) -> StreamingResponse:
    """Uploads a raw project file and streams SSE progress events while indexing coordinates."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    matter_ingestor.create_matter(slug)
    _, raw_dir, _, _ = matter_ingestor._matter_dirs(slug)

    safe_name = Path(file.filename or "uploaded_input.md").name
    dest_path = raw_dir / safe_name
    content = await file.read()
    dest_path.write_bytes(content)
    matter_ingestor.set_file_metadata(
        slug,
        safe_name,
        reliability_tier=reliability_tier,
        origin_description=origin_description,
    )

    def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
        cb("upload", f"Saved {safe_name} into matters/{slug}/inputs/raw/ ({reliability_tier})")
        manifest = matter_ingestor.ingest_matter(slug, progress_callback=cb)
        return {
            "matter_id": slug,
            "uploaded_file": safe_name,
            "manifest": manifest,
            **matter_ingestor.list_matter_files(slug),
        }

    return _stream_worker_sse(run_work)


@router.post("/api/matters/{matter_id}/ingest")
async def ingest_matter_inputs(matter_id: str, request: Request) -> Dict[str, Any]:
    """Runs deterministic coordinate extraction on `matters/<matter_id>/inputs/raw/`."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)
    manifest = await asyncio.to_thread(matter_ingestor.ingest_matter, slug)
    return manifest


@router.post("/api/matters/{matter_id}/ingest/stream")
async def ingest_matter_inputs_stream(matter_id: str, request: Request) -> StreamingResponse:
    """Streams SSE progress events while indexing `matters/<matter_id>/inputs/raw/`."""
    _, matter_ingestor, _ = _get_corpus_services(request)
    slug = _sanitize_slug(matter_id)

    def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
        manifest = matter_ingestor.ingest_matter(slug, progress_callback=cb)
        return {"manifest": manifest, **matter_ingestor.list_matter_files(slug)}

    return _stream_worker_sse(run_work)


@router.post("/api/matters/{matter_id}/ask", response_model=Union[CompiledBundle, PipelineRunRecord])
async def ask_matter_question(
    matter_id: str,
    req: AskMatterRequest,
    request: Request,
) -> Union[CompiledBundle, PipelineRunRecord]:
    """Executes the 4-stage pipeline for `(c)`, returning the bundle or paused checkpoint run."""
    slug = _sanitize_slug(matter_id)
    runner = _build_pipeline_runner(request)

    run = PipelineRunRecord(
        run_id=req.run_id or f"run_{uuid.uuid4().hex[:10]}",
        matter_id=slug,
        question=req.question,
        bundle_id=req.bundle_id,
        checkpoint_mode=req.checkpoint_mode,
        smooth_transitions=req.smooth_transitions,
        canonical_domains=req.canonical_domains,
        blueprint_id=req.blueprint_id,
        blueprint_mode=req.blueprint_mode,
    )
    updated_run, bundle = await asyncio.to_thread(runner.execute_run, run)
    if bundle is not None:
        if bundle.bundle_id:
            BUNDLE_STORE[bundle.bundle_id] = bundle
        return bundle
    return updated_run


def _sse_queue_stream(
    queue: asyncio.Queue[Optional[Dict[str, Any]]],
    on_close: Optional[Callable[[], None]] = None,
) -> StreamingResponse:
    """Creates a `text/event-stream` response draining `queue` until `None`."""

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            if on_close is not None:
                on_close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/matters/{matter_id}/ask/stream")
async def ask_matter_question_stream(
    matter_id: str,
    req: AskMatterRequest,
    request: Request,
) -> StreamingResponse:
    """Streams granular SSE progress for a persisted 4-stage pipeline run."""
    slug = _sanitize_slug(matter_id)
    runner = _build_pipeline_runner(request)

    run = PipelineRunRecord(
        run_id=req.run_id or f"run_{uuid.uuid4().hex[:10]}",
        matter_id=slug,
        question=req.question,
        bundle_id=req.bundle_id,
        checkpoint_mode=req.checkpoint_mode,
        smooth_transitions=req.smooth_transitions,
        canonical_domains=req.canonical_domains,
        blueprint_id=req.blueprint_id,
        blueprint_mode=req.blueprint_mode,
    )
    stream, queue = _launch_run_background(request, runner, run)
    loop = asyncio.get_running_loop()

    def cleanup() -> None:
        try:
            stream.subscribers.remove((loop, queue))
        except ValueError:
            pass

    return _sse_queue_stream(queue, on_close=cleanup)


@router.get("/api/matters/{matter_id}/runs", response_model=List[PipelineRunRecord])
async def list_matter_runs(matter_id: str, request: Request) -> List[PipelineRunRecord]:
    """Lists all persisted pipeline runs and checkpoint records for a project matter."""
    runner = _make_run_reader(request)
    slug = _sanitize_slug(matter_id)
    return runner.list_runs(slug)


@router.get("/api/runs/{run_id}", response_model=PipelineRunRecord)
async def get_pipeline_run(run_id: str, request: Request) -> PipelineRunRecord:
    """Fetches a single persisted `PipelineRunRecord` by `run_id`."""
    runner = _make_run_reader(request)
    run = runner.find_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
    return run


@router.get("/api/runs/{run_id}/stream")
async def stream_pipeline_run(run_id: str, request: Request) -> StreamingResponse:
    """Replays recorded run events and subscribes to live progress if the run is active."""
    runner = _make_run_reader(request)
    run = runner.find_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")

    queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    queue.put_nowait({"event": "run_started", "run": run.model_dump()})
    replayed_count = len(run.events)
    for ev in run.events:
        queue.put_nowait(
            {
                "event": "progress",
                "stage": ev.stage,
                "message": ev.message,
                "run_id": run.run_id,
            }
        )

    streams = _get_run_streams(request)
    active = streams.get(run_id)
    if active is not None and not active.done:
        sub_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
        active.subscribers.append((loop, sub_queue))

        async def forward_stream() -> AsyncGenerator[str, None]:
            try:
                while not queue.empty():
                    item = queue.get_nowait()
                    if item is not None:
                        yield f"data: {json.dumps(item)}\n\n"
                while True:
                    item = await sub_queue.get()
                    if item is None:
                        break
                    seq = item.get("seq")
                    if seq is not None and seq <= replayed_count:
                        continue
                    yield f"data: {json.dumps(item)}\n\n"
            finally:
                try:
                    active.subscribers.remove((loop, sub_queue))
                except ValueError:
                    pass

        return StreamingResponse(forward_stream(), media_type="text/event-stream")

    # Terminal or paused run already on disk
    if run.status == "completed" and run.result_bundle_id:
        bundle = BUNDLE_STORE.get(run.result_bundle_id)
        if bundle is None:
            _, _, _, bundles_dir = runner.matter_ingestor._matter_dirs(run.matter_id)
            b_path = bundles_dir / f"{run.result_bundle_id}.json"
            if b_path.exists():
                bundle = CompiledBundle.model_validate_json(b_path.read_text(encoding="utf-8"))
                BUNDLE_STORE[run.result_bundle_id] = bundle
        if bundle is not None:
            queue.put_nowait(
                {"event": "bundle", "bundle": bundle.model_dump(), "run": run.model_dump()}
            )
    elif run.status in ("awaiting_stage1_approval", "awaiting_stage2_approval"):
        queue.put_nowait({"event": "checkpoint", "run": run.model_dump()})
    elif run.status == "failed":
        queue.put_nowait(
            {"event": "error", "detail": run.error or "Pipeline failed.", "run": run.model_dump()}
        )
    else:
        queue.put_nowait({"event": "run_state", "run": run.model_dump()})
    queue.put_nowait(None)
    return _sse_queue_stream(queue)


def _prepare_run_for_resume(
    run: PipelineRunRecord,
    req: Optional[ResumeRunRequest],
) -> PipelineRunRecord:
    """Applies user edits, section re-harvest flags, and toggles onto `run` prior to resuming."""
    if req is None:
        return run
    if req.outline_plan is not None:
        run.outline_plan = req.outline_plan
    if req.smooth_transitions is not None:
        run.smooth_transitions = req.smooth_transitions
    if req.checkpoint_mode is not None:
        run.checkpoint_mode = req.checkpoint_mode
    if req.reharvest_section_ids:
        target_ids = set(req.reharvest_section_ids)
        for sec_id in target_ids:
            run.ledgers.pop(sec_id, None)
            run.audits.pop(sec_id, None)
        run.sections = [s for s in run.sections if s.section_id not in target_ids]
    return run


@router.post("/api/runs/{run_id}/resume", response_model=Union[CompiledBundle, PipelineRunRecord])
async def resume_pipeline_run(
    run_id: str,
    request: Request,
    req: Optional[ResumeRunRequest] = None,
) -> Union[CompiledBundle, PipelineRunRecord]:
    """Resumes a checkpointed or interrupted run synchronously, returning the bundle or next checkpoint."""
    runner = _build_pipeline_runner(request)
    run = runner.find_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")

    run = _prepare_run_for_resume(run, req)
    updated_run, bundle = await asyncio.to_thread(runner.execute_run, run)
    if bundle is not None:
        if bundle.bundle_id:
            BUNDLE_STORE[bundle.bundle_id] = bundle
        return bundle
    return updated_run


@router.post("/api/runs/{run_id}/resume/stream")
async def resume_pipeline_run_stream(
    run_id: str,
    request: Request,
    req: Optional[ResumeRunRequest] = None,
) -> StreamingResponse:
    """Resumes a checkpointed or interrupted run and streams granular SSE progress."""
    runner = _build_pipeline_runner(request)
    run = runner.find_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")

    run = _prepare_run_for_resume(run, req)
    stream, queue = _launch_run_background(request, runner, run)
    loop = asyncio.get_running_loop()

    def cleanup() -> None:
        try:
            stream.subscribers.remove((loop, queue))
        except ValueError:
            pass

    return _sse_queue_stream(queue, on_close=cleanup)


# =====================================================================
# Reusable Document Blueprints (d)
# =====================================================================


@router.get("/api/blueprints")
async def list_blueprints(request: Request) -> List[Dict[str, Any]]:
    """Lists all persisted Document Blueprints `(d)` (auto-seeding starters on first access)."""
    store = _get_blueprint_store(request)
    return [bp.model_dump() for bp in store.list_blueprints()]


@router.post("/api/blueprints")
async def create_or_update_blueprint(
    req: CreateBlueprintRequest,
    request: Request,
) -> Dict[str, Any]:
    """Saves a reusable Document Blueprint `(d)` directly or derived from a Stage 1 outline/run."""
    store = _get_blueprint_store(request)
    sections = list(req.sections)
    title_tmpl = req.document_title_template
    exec_intent = req.executive_summary_intent
    default_domains = list(req.default_domains)

    source_plan = req.outline_plan
    if source_plan is None and req.source_run_id:
        runner = _make_run_reader(request)
        run = runner.find_run(req.source_run_id)
        if run is None:
            raise HTTPException(
                status_code=404, detail=f"Pipeline run '{req.source_run_id}' not found."
            )
        source_plan = run.outline_plan
        if not default_domains and run.selected_domains:
            default_domains = list(run.selected_domains)

    if source_plan is not None:
        if not sections:
            sections = [s.model_copy(deep=True) for s in source_plan.sections]
        title_tmpl = title_tmpl or source_plan.document_title
        exec_intent = exec_intent or source_plan.executive_summary_intent

    if not sections:
        raise HTTPException(
            status_code=422,
            detail="Document Blueprint must contain at least one section or reference an outline_plan.",
        )

    slug = _sanitize_slug(req.blueprint_id or req.title)
    bp = DocumentBlueprint(
        blueprint_id=slug,
        title=req.title.strip(),
        domain=req.domain.strip() or "general",
        description=(req.description or "").strip() or None,
        default_domains=default_domains,
        document_title_template=title_tmpl or f"{req.title.strip()} — {{matter_id}}",
        executive_summary_intent=exec_intent or f"Structured synthesis using blueprint '{req.title.strip()}'.",
        sections=sections,
    )
    saved = store.save_blueprint(bp)
    return saved.model_dump()


@router.delete("/api/blueprints/{blueprint_id}")
async def delete_blueprint(blueprint_id: str, request: Request) -> Dict[str, Any]:
    """Deletes a persisted Document Blueprint `(d)` by ID."""
    store = _get_blueprint_store(request)
    try:
        removed = store.delete_blueprint(blueprint_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Blueprint '{blueprint_id}' not found.")
    return {"deleted": blueprint_id}


# =====================================================================
# Antigravity-Style Inline Review Comments & Batch Regeneration
# =====================================================================

@router.post("/api/bundles/{bundle_id}/comments", response_model=CompiledBundle)
async def add_review_comment(
    bundle_id: str,
    req: AddCommentRequest,
    request: Request,
) -> CompiledBundle:
    """Anchors a human review comment onto a node, logical link, section, or overall document."""
    if bundle_id not in BUNDLE_STORE:
        raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")

    bundle = BUNDLE_STORE[bundle_id]
    if req.scope in ("node", "link"):
        if not req.node_id or req.node_id not in bundle.nodes:
            raise HTTPException(
                status_code=422, detail=f"Target node '{req.node_id}' not found in bundle."
            )
        target_node = bundle.nodes[req.node_id]
        resolved_node_id = req.node_id
        resolved_section_id = req.section_id or target_node.section_id
        resolved_label = req.target_label or target_node.title
    elif req.scope == "section":
        valid_sections = {s.section_id: s.section_title for s in bundle.artifact.sections}
        if not req.section_id or req.section_id not in valid_sections:
            raise HTTPException(
                status_code=422, detail=f"Target section '{req.section_id}' not found in bundle."
            )
        resolved_node_id = "__section__"
        resolved_section_id = req.section_id
        resolved_label = req.target_label or valid_sections[req.section_id]
    else:
        resolved_node_id = "__document__"
        resolved_section_id = "__document__"
        resolved_label = req.target_label or bundle.artifact.title

    comment = ReviewComment(
        comment_id=f"cmt_{uuid.uuid4().hex[:8]}",
        scope=req.scope,
        node_id=resolved_node_id,
        section_id=resolved_section_id,
        target_label=resolved_label,
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
    runner = _build_pipeline_runner(request)

    updated = await asyncio.to_thread(
        runner.apply_comments_and_recompile,
        bundle,
        req.comments,
        req.smooth_transitions,
    )
    BUNDLE_STORE[bundle_id] = updated
    return updated
