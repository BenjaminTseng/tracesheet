"""Unified single-server FastAPI factory composing shared platform core and pluggable compilers."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.compilers.bankruptcy.sample_cases import seed_bankruptcy_sample_cases
from app.compilers.bankruptcy.service import BankruptcyCaseService, BankruptcyCompilerApp
from app.compilers.research.service import ResearchCompilerApp, ResearchCompilerService
from app.core.bundle import SourceReliabilityTier
from app.core.compiler import CompilerApp, PlatformContext
from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.core.llm import LLMProvider, create_llm_provider
from app.core.ocr import LocalOCRProvider
from app.core.pii import PIITokenizer
from app.core.tables import ReferenceTableRegistry, StatutoryTableRegistry
from app.core.workspace import MatterWorkspace

logger = logging.getLogger("jd_screen.server")

COMPILER_REGISTRY: Tuple[str, ...] = ("bankruptcy", "research")


class CreateMatterRequest(BaseModel):
    """Request body for creating a new isolated project matter workspace."""

    matter_id: str = Field(min_length=1)


class UpdateMatterFileMetadataRequest(BaseModel):
    """Request body for updating origin & reliability tier metadata on a matter input `(a)`."""

    reliability_tier: SourceReliabilityTier = "primary_record"
    origin_description: Optional[str] = None


class CanonicalIngestRequest(BaseModel):
    """Request body for rebuilding canonical `[AUTH:...]` artifacts and `INDEX.md`."""

    purge_encoded: bool = False


def parse_enabled_apps(raw: Optional[Any]) -> List[str]:
    """Parses CLI/env app selection (`all`, `bankruptcy`, `research`, or comma-separated list)."""
    if raw is None:
        return list(COMPILER_REGISTRY)
    if isinstance(raw, str):
        tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    else:
        tokens = [str(t).strip().lower() for t in raw if str(t).strip()]
    if not tokens or "all" in tokens:
        return list(COMPILER_REGISTRY)
    ordered: List[str] = []
    for tok in tokens:
        if tok not in COMPILER_REGISTRY:
            raise ValueError(
                f"Unknown compiler app '{tok}'. Supported apps: {', '.join(COMPILER_REGISTRY)}."
            )
        if tok not in ordered:
            ordered.append(tok)
    return ordered


def _sanitize_slug(raw: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip()).strip("_").lower()
    if not slug:
        raise HTTPException(status_code=422, detail="Invalid identifier slug.")
    return slug


def _infer_inline_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".md", ".txt"}:
        return "text/plain; charset=utf-8"
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".xlsm":
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _stream_worker_sse(
    work_fn: Callable[[Callable[[str, str], None]], Dict[str, Any]],
) -> StreamingResponse:
    """Runs a blocking helper in a worker thread while streaming SSE progress events."""
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


def create_platform_app(
    base_dir: Optional[Path] = None,
    enabled_apps: Optional[Any] = None,
    default_app: str = "bankruptcy",
    llm_provider: Optional[LLMProvider] = None,
    llm_config: Optional[Dict[str, Any]] = None,
    seed_samples: bool = True,
) -> FastAPI:
    """Creates the unified FastAPI platform mounting shared `/api/v1/` services and enabled compilers.

    Args:
        base_dir: Root workspace directory containing `templates/`, `static/`, `matters/`, `canonical/`.
        enabled_apps: List or comma-separated string of compilers to mount (`bankruptcy`, `research`, or `all`).
        default_app: Compiler route redirected to by `GET /` (defaults to `"bankruptcy"`).
        llm_provider: Optional pre-configured `LLMProvider` instance.
        llm_config: Optional `{provider, model, api_key}` runtime configuration dict.
        seed_samples: Whether to pre-seed sample data for enabled compilers.

    Returns:
        Configured `FastAPI` instance ready for Uvicorn or `TestClient`.
    """
    root_dir = base_dir or Path(__file__).resolve().parent.parent
    enabled = parse_enabled_apps(enabled_apps)
    resolved_default = default_app if default_app in enabled else enabled[0]

    matters_root = root_dir / "matters"
    canonical_dir = root_dir / "canonical"
    tables_root = canonical_dir / "tables"

    tokenizer = PIITokenizer(matters_root)
    ocr_provider = LocalOCRProvider()
    ingestor = MatterIngestor(
        matters_root=matters_root,
        ocr_provider=ocr_provider,
        pii_tokenizer=tokenizer,
    )
    canonical_router = CanonicalRouter(canonical_dir)
    canonical_ingestor = CanonicalIngestor(canonical_dir)
    templates = Jinja2Templates(directory=str(root_dir / "templates"))

    api = FastAPI(
        title="Audit-Grounded Verification Platform",
        version="2.0.0",
        description="Unified audit-grounded compilation platform with pluggable vertical compilers.",
    )

    api.state.base_dir = root_dir
    api.state.enabled_apps = enabled
    api.state.default_app = resolved_default
    api.state.llm_provider = llm_provider
    api.state.llm_config = llm_config or {"provider": "gemini", "model": None, "api_key": None}
    api.state.canonical_router = canonical_router
    api.state.canonical_ingestor = canonical_ingestor
    api.state.matter_ingestor = ingestor

    static_dir = root_dir / "static"
    if static_dir.exists():
        api.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Instantiate enabled compilers against PlatformContext.
    effective_llm: Any = llm_provider
    ctx = PlatformContext(
        base_dir=root_dir,
        matters_root=matters_root,
        canonical_dir=canonical_dir,
        tables_root=tables_root,
        ingestor=ingestor,
        canonical_router=canonical_router,
        llm_provider=effective_llm,
    )
    api.state.platform_ctx = ctx

    mounted_apps: List[CompilerApp] = []
    if "bankruptcy" in enabled:
        bk_service = BankruptcyCaseService(
            base_dir=root_dir,
            ocr_provider=ocr_provider,
            llm_provider=llm_provider,
        )
        if seed_samples:
            seed_bankruptcy_sample_cases(bk_service)
        bk_app = BankruptcyCompilerApp(bk_service)
        mounted_apps.append(bk_app)
        api.state.bankruptcy_service = bk_service
        api.state.bankruptcy_app = bk_app
        api.include_router(bk_app.build_router(ctx))

    if "research" in enabled:
        rs_service = ResearchCompilerService(
            base_dir=root_dir,
            ingestor=ingestor,
            canonical_router=canonical_router,
            llm_provider=llm_provider,
            seed_samples=seed_samples,
        )
        rs_app = ResearchCompilerApp(rs_service)
        mounted_apps.append(rs_app)
        api.state.research_service = rs_service
        api.state.research_app = rs_app
        api.include_router(rs_app.build_router(ctx))

    api.state.mounted_apps = mounted_apps

    def _get_corpus(request: Request) -> Tuple[CanonicalRouter, MatterIngestor, CanonicalIngestor]:
        st = request.app.state
        c_router = getattr(st, "canonical_router", None) or canonical_router
        m_ing = getattr(st, "matter_ingestor", None) or ingestor
        c_ing = getattr(st, "canonical_ingestor", None) or CanonicalIngestor(c_router.canonical_dir)
        return c_router, m_ing, c_ing

    def _get_optional_llm(request: Request) -> Optional[LLMProvider]:
        st = request.app.state
        explicit = getattr(st, "llm_provider", None)
        if explicit is not None:
            return explicit
        cfg = getattr(st, "llm_config", {}) or {}
        try:
            return create_llm_provider(
                provider_name=cfg.get("provider", "gemini"),
                model=cfg.get("model"),
                api_key=cfg.get("api_key"),
            )
        except Exception:
            return None

    platform_router = APIRouter()

    @platform_router.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        """Redirects root `/` to the configured default compiler UI (`/{resolved_default}`)."""
        return RedirectResponse(url=f"/{resolved_default}", status_code=307)

    if "bankruptcy" in enabled:

        @platform_router.get("/bankruptcy", response_class=HTMLResponse)
        async def serve_bankruptcy_ui(request: Request) -> HTMLResponse:
            """Serves the Bankruptcy Case Workbench workspace."""
            return templates.TemplateResponse(request, "bankruptcy.html", {})

    if "research" in enabled:

        @platform_router.get("/research", response_class=HTMLResponse)
        async def serve_research_ui(request: Request) -> HTMLResponse:
            """Serves the Broadsheet Research Canvas workspace."""
            template_name = (
                "research.html"
                if (root_dir / "templates" / "research.html").exists()
                else "index.html"
            )
            return templates.TemplateResponse(request, template_name, {})

    @platform_router.get("/api/v1/apps")
    async def list_mounted_apps() -> Dict[str, Any]:
        """Returns the mounted compiler metadata driving the UI app switcher dropdown."""
        return {
            "default_app": resolved_default,
            "apps": [app_item.descriptor.model_dump() for app_item in mounted_apps],
        }

    @platform_router.get("/api/v1/apps/cases")
    async def list_all_compiler_cases(app_id: Optional[str] = None) -> Dict[str, Any]:
        """Aggregates standardized `CaseSummaryRow` records across enabled compilers."""
        rows = []
        for comp in mounted_apps:
            if app_id and comp.descriptor.app_id != app_id:
                continue
            rows.extend(row.model_dump() for row in comp.list_cases())
        return {"cases": rows}

    # ------------------------------------------------------------------
    # Shared Reference Tables Endpoints
    # ------------------------------------------------------------------

    @platform_router.get("/api/v1/tables/{domain}")
    async def list_domain_tables(domain: str) -> Dict[str, Any]:
        """Lists effective-dated JSON reference tables for a compiler domain."""
        safe_domain = _sanitize_slug(domain)
        tdir = tables_root / safe_domain
        if not tdir.exists():
            raise HTTPException(status_code=404, detail=f"No table registry for domain '{safe_domain}'.")
        reg = (
            StatutoryTableRegistry(tdir)
            if safe_domain == "bankruptcy"
            else ReferenceTableRegistry(tdir)
        )
        return {"domain": safe_domain, "tables": reg.list_metadata()}

    @platform_router.post("/api/v1/tables/{domain}/sync")
    async def sync_domain_tables(domain: str) -> Dict[str, Any]:
        """SHA-256 verifies and checks staleness across tables in `canonical/tables/<domain>/`."""
        safe_domain = _sanitize_slug(domain)
        tdir = tables_root / safe_domain
        if not tdir.exists():
            raise HTTPException(status_code=404, detail=f"No table registry for domain '{safe_domain}'.")
        reg = (
            StatutoryTableRegistry(tdir)
            if safe_domain == "bankruptcy"
            else ReferenceTableRegistry(tdir)
        )
        return {"domain": safe_domain, **reg.sync_tables()}

    # ------------------------------------------------------------------
    # Shared Canonical Corpus `(b)` Endpoints
    # ------------------------------------------------------------------

    @platform_router.get("/api/v1/canonical")
    async def get_canonical_corpus(request: Request) -> Dict[str, Any]:
        c_router, _, c_ing = _get_corpus(request)
        status = c_ing.get_corpus_status()
        status["canonical_domains"] = c_router.list_domains()
        return status

    @platform_router.get("/api/v1/canonical/documents/{doc_id:path}")
    async def get_canonical_document_detail(doc_id: str, request: Request) -> Dict[str, Any]:
        _, _, c_ing = _get_corpus(request)
        try:
            detail = c_ing.get_document_detail(doc_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if detail["card"] is None and not detail["authorities"] and not detail["toc_markdown"]:
            raise HTTPException(status_code=404, detail=f"Canonical document '{doc_id}' not found.")
        return detail

    @platform_router.get("/api/v1/canonical/files/{domain}/{filename}/raw")
    async def get_canonical_raw_file(domain: str, filename: str, request: Request) -> FileResponse:
        _, _, c_ing = _get_corpus(request)
        safe_domain = _sanitize_slug(domain)
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename or ".." in filename:
            raise HTTPException(status_code=422, detail=f"Invalid filename: {filename}")
        canonical_root = c_ing.canonical_dir.resolve()
        candidates = [
            (c_ing.raw_dir / safe_domain / safe_name).resolve(),
            (c_ing.canonical_dir / safe_domain / safe_name).resolve(),
        ]
        stem = Path(safe_name).stem
        if not stem.endswith("_source"):
            candidates.append((c_ing.raw_dir / safe_domain / f"{stem}_source.md").resolve())
        for candidate in candidates:
            if canonical_root in candidate.parents and candidate.exists() and candidate.is_file():
                return FileResponse(
                    path=candidate,
                    media_type=_infer_inline_media_type(candidate.name),
                    filename=candidate.name,
                    content_disposition_type="inline",
                )
        raise HTTPException(
            status_code=404,
            detail=f"Canonical file '{safe_name}' not found in domain '{safe_domain}'.",
        )

    @platform_router.delete("/api/v1/canonical/files/{domain}/{filename}")
    async def delete_canonical_document(
        domain: str, filename: str, request: Request
    ) -> Dict[str, Any]:
        _, _, c_ing = _get_corpus(request)
        optional_llm = _get_optional_llm(request)
        try:
            return await asyncio.to_thread(c_ing.delete_canonical_file, domain, filename, optional_llm)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @platform_router.post("/api/v1/canonical/upload")
    async def upload_canonical_file(
        request: Request,
        domain: str = Form("general"),
        file: UploadFile = File(...),
    ) -> Dict[str, Any]:
        _, _, c_ing = _get_corpus(request)
        domain_dir = c_ing.create_domain(domain)
        safe_name = Path(file.filename or "canonical_source.md").name
        (domain_dir / safe_name).write_bytes(await file.read())
        optional_llm = _get_optional_llm(request)
        summary = await asyncio.to_thread(c_ing.ingest_corpus, False, optional_llm)
        return {
            "domain": domain_dir.name,
            "uploaded_file": safe_name,
            "summary": summary,
            **c_ing.get_corpus_status(),
        }

    @platform_router.post("/api/v1/canonical/upload/stream")
    async def upload_canonical_file_stream(
        request: Request,
        domain: str = Form("general"),
        file: UploadFile = File(...),
    ) -> StreamingResponse:
        _, _, c_ing = _get_corpus(request)
        domain_dir = c_ing.create_domain(domain)
        safe_name = Path(file.filename or "canonical_source.md").name
        (domain_dir / safe_name).write_bytes(await file.read())
        optional_llm = _get_optional_llm(request)

        def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
            cb("upload", f"Saved {safe_name} into canonical/raw/{domain_dir.name}/")
            summary = c_ing.ingest_corpus(False, optional_llm, progress_callback=cb)
            return {
                "domain": domain_dir.name,
                "uploaded_file": safe_name,
                "summary": summary,
                **c_ing.get_corpus_status(),
            }

        return _stream_worker_sse(run_work)

    @platform_router.post("/api/v1/canonical/ingest")
    async def ingest_canonical_corpus(
        request: Request, req: Optional[CanonicalIngestRequest] = None
    ) -> Dict[str, Any]:
        _, _, c_ing = _get_corpus(request)
        purge = req.purge_encoded if req is not None else False
        optional_llm = _get_optional_llm(request)
        summary = await asyncio.to_thread(c_ing.ingest_corpus, purge, optional_llm)
        return {"summary": summary, **c_ing.get_corpus_status()}

    @platform_router.post("/api/v1/canonical/ingest/stream")
    async def ingest_canonical_corpus_stream(
        request: Request, req: Optional[CanonicalIngestRequest] = None
    ) -> StreamingResponse:
        _, _, c_ing = _get_corpus(request)
        purge = req.purge_encoded if req is not None else False
        optional_llm = _get_optional_llm(request)

        def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
            summary = c_ing.ingest_corpus(purge, optional_llm, progress_callback=cb)
            return {"summary": summary, **c_ing.get_corpus_status()}

        return _stream_worker_sse(run_work)

    # ------------------------------------------------------------------
    # Shared Matter Inputs `(a)` & Cross-Compiler Ledgers Endpoints
    # ------------------------------------------------------------------

    @platform_router.get("/api/v1/matters")
    async def list_matters_and_corpus(request: Request) -> Dict[str, Any]:
        c_router, m_ing, _ = _get_corpus(request)
        authorities = [auth.model_dump() for auth in c_router.list_authorities().values()]
        return {"matters": m_ing.list_matters(), "canonical_authorities": authorities}

    @platform_router.post("/api/v1/matters")
    async def create_matter(req: CreateMatterRequest, request: Request) -> Dict[str, Any]:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(req.matter_id)
        matter_dir = m_ing.create_matter(slug)
        return {"matter_id": slug, "path": str(matter_dir)}

    @platform_router.get("/api/v1/matters/{matter_id}/files")
    async def list_matter_files(matter_id: str, request: Request) -> Dict[str, Any]:
        _, m_ing, _ = _get_corpus(request)
        return m_ing.list_matter_files(_sanitize_slug(matter_id))

    @platform_router.get("/api/v1/matters/{matter_id}/files/{filename}/raw")
    async def get_matter_raw_file(
        matter_id: str, filename: str, request: Request
    ) -> FileResponse:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename or ".." in filename:
            raise HTTPException(status_code=422, detail=f"Invalid filename: {filename}")
        _, raw_dir, _, _ = m_ing._matter_dirs(slug)
        raw_root = raw_dir.resolve()
        target = (raw_dir / safe_name).resolve()
        if raw_root not in target.parents or not target.exists() or not target.is_file():
            raise HTTPException(
                status_code=404, detail=f"Matter file '{safe_name}' not found in '{slug}'."
            )
        return FileResponse(
            path=target,
            media_type=_infer_inline_media_type(safe_name),
            filename=safe_name,
            content_disposition_type="inline",
        )

    @platform_router.delete("/api/v1/matters/{matter_id}/files/{filename}")
    async def delete_matter_file(
        matter_id: str, filename: str, request: Request
    ) -> Dict[str, Any]:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        try:
            return await asyncio.to_thread(m_ing.delete_matter_file, slug, filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @platform_router.patch("/api/v1/matters/{matter_id}/files/{filename}/metadata")
    async def update_matter_file_metadata(
        matter_id: str,
        filename: str,
        req: UpdateMatterFileMetadataRequest,
        request: Request,
    ) -> Dict[str, Any]:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        _, raw_dir, _, _ = m_ing._matter_dirs(slug)
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename or ".." in filename:
            raise HTTPException(status_code=422, detail=f"Invalid filename: {filename}")
        target = raw_dir / safe_name
        if not target.exists() or not target.is_file():
            raise HTTPException(
                status_code=404, detail=f"Matter file '{safe_name}' not found in '{slug}'."
            )
        m_ing.set_file_metadata(
            slug,
            safe_name,
            reliability_tier=req.reliability_tier,
            origin_description=req.origin_description,
        )
        return m_ing.list_matter_files(slug)

    @platform_router.post("/api/v1/matters/{matter_id}/upload")
    async def upload_matter_file(
        matter_id: str,
        request: Request,
        file: UploadFile = File(...),
        reliability_tier: SourceReliabilityTier = Form("primary_record"),
        origin_description: Optional[str] = Form(None),
    ) -> Dict[str, Any]:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        m_ing.create_matter(slug)
        _, raw_dir, _, _ = m_ing._matter_dirs(slug)
        safe_name = Path(file.filename or "uploaded_input.md").name
        (raw_dir / safe_name).write_bytes(await file.read())
        m_ing.set_file_metadata(
            slug, safe_name, reliability_tier=reliability_tier, origin_description=origin_description
        )
        manifest = await asyncio.to_thread(m_ing.ingest_matter, slug)
        return {
            "matter_id": slug,
            "uploaded_file": safe_name,
            "manifest": manifest,
            **m_ing.list_matter_files(slug),
        }

    @platform_router.post("/api/v1/matters/{matter_id}/upload/stream")
    async def upload_matter_file_stream(
        matter_id: str,
        request: Request,
        file: UploadFile = File(...),
        reliability_tier: SourceReliabilityTier = Form("primary_record"),
        origin_description: Optional[str] = Form(None),
    ) -> StreamingResponse:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        m_ing.create_matter(slug)
        _, raw_dir, _, _ = m_ing._matter_dirs(slug)
        safe_name = Path(file.filename or "uploaded_input.md").name
        (raw_dir / safe_name).write_bytes(await file.read())
        m_ing.set_file_metadata(
            slug, safe_name, reliability_tier=reliability_tier, origin_description=origin_description
        )

        def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
            cb("upload", f"Saved {safe_name} into matters/{slug}/inputs/raw/ ({reliability_tier})")
            manifest = m_ing.ingest_matter(slug, progress_callback=cb)
            return {
                "matter_id": slug,
                "uploaded_file": safe_name,
                "manifest": manifest,
                **m_ing.list_matter_files(slug),
            }

        return _stream_worker_sse(run_work)

    @platform_router.post("/api/v1/matters/{matter_id}/ingest")
    async def ingest_matter_inputs(
        matter_id: str, request: Request, incremental: bool = False
    ) -> Dict[str, Any]:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        return await asyncio.to_thread(m_ing.ingest_matter, slug, None, incremental)

    @platform_router.post("/api/v1/matters/{matter_id}/ingest/stream")
    async def ingest_matter_inputs_stream(
        matter_id: str, request: Request, incremental: bool = False
    ) -> StreamingResponse:
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)

        def run_work(cb: Callable[[str, str], None]) -> Dict[str, Any]:
            manifest = m_ing.ingest_matter(slug, progress_callback=cb, incremental=incremental)
            return {"manifest": manifest, **m_ing.list_matter_files(slug)}

        return _stream_worker_sse(run_work)

    @platform_router.get("/api/v1/matters/{matter_id}/ledgers")
    async def list_matter_ledgers(matter_id: str, request: Request) -> Dict[str, Any]:
        """Lists verified calculation ledgers published for `matter_id`."""
        _, m_ing, _ = _get_corpus(request)
        slug = _sanitize_slug(matter_id)
        ws = MatterWorkspace(m_ing.matters_root, slug)
        ledgers = [snap.model_dump(mode="json") for snap in ws.list_ledgers(verify_hash=False)]
        return {"matter_id": slug, "ledgers": ledgers}

    api.include_router(platform_router)
    return api
