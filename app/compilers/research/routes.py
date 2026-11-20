"""FastAPI router for `/api/v1/research/*` endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.compilers.research.blueprints import BlueprintStore, sanitize_slug
from app.compilers.research.pipeline import AuditPipelineRunner
from app.compilers.research.service import (
    AddCommentRequest,
    AskMatterRequest,
    BundleSummaryItem,
    CompilePipelineRequest,
    CreateBlueprintRequest,
    RegenerateRequest,
    ResearchCompilerService,
    ResumeRunRequest,
)
from app.core.bundle import (
    CompiledBundle,
    CompiledGraphBuilder,
    DocumentBlueprint,
    PipelineRunRecord,
    ReviewComment,
    SectionValidator,
    StitchInvariantGate,
)

logger = logging.getLogger("jd_screen.research.routes")


@dataclass
class _ActiveRunStream:
    """Tracks live SSE subscribers for an actively executing `PipelineRunRecord`."""

    run_id: str
    subscribers: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue[Optional[Dict[str, Any]]]]] = (
        field(default_factory=list)
    )
    done: bool = False


def _broadcast_run_event(stream: _ActiveRunStream, payload: Optional[Dict[str, Any]]) -> None:
    """Delivers an event (or `None` sentinel) thread-safely to all subscribers on `stream`."""
    for loop, queue in list(stream.subscribers):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        except RuntimeError:
            pass


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


def build_research_router(service: ResearchCompilerService) -> APIRouter:
    """Builds the `/api/v1/research` FastAPI router bound to `service`."""
    router = APIRouter()

    def _get_blueprint_store(request: Request) -> BlueprintStore:
        explicit = getattr(request.app.state, "blueprint_store", None)
        if explicit is not None:
            return explicit
        bp_root = getattr(request.app.state, "blueprints_root", None)
        if bp_root is not None:
            return BlueprintStore(Path(bp_root))
        return service.blueprint_store

    def _state_overrides(request: Request) -> Dict[str, Any]:
        st = request.app.state
        bp_store = _get_blueprint_store(request)
        return {
            "llm_override": getattr(st, "llm_provider", None),
            "canonical_override": getattr(st, "canonical_router", None),
            "ingestor_override": getattr(st, "matter_ingestor", None),
            "blueprints_root_override": bp_store.blueprints_root,
            "llm_config": getattr(st, "llm_config", None),
        }

    def _build_runner(request: Request, allow_mock_fallback: bool = False) -> AuditPipelineRunner:
        return service.make_runner(
            **_state_overrides(request),
            allow_mock_fallback=allow_mock_fallback,
        )

    def _launch_run_background(
        runner: AuditPipelineRunner,
        run: PipelineRunRecord,
    ) -> Tuple[_ActiveRunStream, asyncio.Queue[Optional[Dict[str, Any]]]]:
        loop = asyncio.get_running_loop()
        initial_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
        stream = _ActiveRunStream(run_id=run.run_id, subscribers=[(loop, initial_queue)])
        service.active_run_streams[run.run_id] = stream

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
                        service.bundle_store[bundle.bundle_id] = bundle
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
                service.active_run_streams.pop(run.run_id, None)

        asyncio.create_task(worker())
        return stream, initial_queue

    @router.get("/api/v1/research/bundles", response_model=List[BundleSummaryItem])
    async def list_bundles() -> List[BundleSummaryItem]:
        """Lists all compiled research audit bundles with verification metrics."""
        return service.list_bundle_summaries()

    @router.get("/api/v1/research/bundles/{bundle_id}", response_model=CompiledBundle)
    async def get_bundle(bundle_id: str, request: Request) -> CompiledBundle:
        """Retrieves a specific compiled audit bundle by `bundle_id`."""
        if bundle_id not in service.bundle_store:
            raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' was not found.")
        bundle = service.bundle_store[bundle_id]
        if bundle.matter_id:
            ingestor = getattr(request.app.state, "matter_ingestor", None) or service.ingestor
            slug = sanitize_slug(bundle.matter_id)
            _, raw_dir, _, _ = ingestor._matter_dirs(slug)
            raw_files = (
                sorted(p.name for p in raw_dir.iterdir() if p.is_file() and not p.name.startswith("."))
                if raw_dir.exists()
                else []
            )
            bundle.artifact.metadata["available_raw_files"] = raw_files
        return bundle

    @router.post("/api/v1/research/bundles", response_model=CompiledBundle)
    async def upload_compiled_bundle(payload: Dict[str, Any]) -> CompiledBundle:
        """Validates and registers a custom Tier 2 `CompiledBundle` JSON payload."""
        try:
            bundle = CompiledBundle.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        missing_targets = [
            f"{node_id} -> {child_id}"
            for node_id, node in bundle.nodes.items()
            for child_id in node.direct_child_ids
            if child_id not in bundle.nodes
        ]
        if missing_targets:
            raise HTTPException(
                status_code=422,
                detail=f"Broken graph edges detected (missing target nodes): {missing_targets}",
            )

        bundle_id = bundle.bundle_id or f"custom_{len(service.bundle_store) + 1}"
        bundle.bundle_id = bundle_id
        service.bundle_store[bundle_id] = bundle
        return bundle

    @router.post("/api/v1/research/compile", response_model=CompiledBundle)
    async def compile_intermediate_sections(req: CompilePipelineRequest) -> CompiledBundle:
        """Validates Tier 1 sections, checks stitch invariants, and compiles a DAG bundle."""
        all_errors: List[str] = []
        for sec in req.sections:
            is_valid, sec_errors = SectionValidator.validate_section(sec)
            if not is_valid:
                for err in sec_errors:
                    all_errors.append(f"[{sec.section_id}] {err}")
        if all_errors:
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
                raise HTTPException(
                    status_code=422, detail={"stitch_violations": stitch_violations}
                )

        builder = CompiledGraphBuilder(
            document_title=req.title,
            summary=req.summary,
            metadata=req.metadata,
        )
        bundle = builder.compile_sections(
            sections=req.sections,
            final_smoothed_text=req.smoothed_text,
            tensions=req.tensions,
        )
        bundle.bundle_id = req.bundle_id
        service.bundle_store[req.bundle_id] = bundle
        return bundle

    @router.post(
        "/api/v1/research/matters/{matter_id}/ask",
        response_model=Union[CompiledBundle, PipelineRunRecord],
    )
    async def ask_matter_question(
        matter_id: str,
        req: AskMatterRequest,
        request: Request,
    ) -> Union[CompiledBundle, PipelineRunRecord]:
        """Executes the 4-stage research pipeline for `(c)`."""
        slug = sanitize_slug(matter_id)
        runner = _build_runner(request)
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
                service.bundle_store[bundle.bundle_id] = bundle
            return bundle
        return updated_run

    @router.post("/api/v1/research/matters/{matter_id}/ask/stream")
    async def ask_matter_question_stream(
        matter_id: str,
        req: AskMatterRequest,
        request: Request,
    ) -> StreamingResponse:
        """Streams granular SSE progress for a persisted 4-stage research pipeline run."""
        slug = sanitize_slug(matter_id)
        runner = _build_runner(request)
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
        stream, queue = _launch_run_background(runner, run)
        loop = asyncio.get_running_loop()

        def cleanup() -> None:
            try:
                stream.subscribers.remove((loop, queue))
            except ValueError:
                pass

        return _sse_queue_stream(queue, on_close=cleanup)

    @router.get("/api/v1/research/matters/{matter_id}/runs", response_model=List[PipelineRunRecord])
    async def list_matter_runs(matter_id: str, request: Request) -> List[PipelineRunRecord]:
        """Lists persisted pipeline runs and checkpoints for a matter."""
        runner = _build_runner(request, allow_mock_fallback=True)
        return runner.list_runs(sanitize_slug(matter_id))

    @router.get("/api/v1/research/runs/{run_id}", response_model=PipelineRunRecord)
    async def get_pipeline_run(run_id: str, request: Request) -> PipelineRunRecord:
        """Fetches a single persisted `PipelineRunRecord` by `run_id`."""
        runner = _build_runner(request, allow_mock_fallback=True)
        run = runner.find_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        return run

    @router.get("/api/v1/research/runs/{run_id}/stream")
    async def stream_pipeline_run(run_id: str, request: Request) -> StreamingResponse:
        """Replays recorded run events and subscribes to live progress if active."""
        runner = _build_runner(request, allow_mock_fallback=True)
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

        active = service.active_run_streams.get(run_id)
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

        if run.status == "completed" and run.result_bundle_id:
            bundle = service.bundle_store.get(run.result_bundle_id)
            if bundle is None:
                _, _, _, bundles_dir = runner.matter_ingestor._matter_dirs(run.matter_id)
                b_path = bundles_dir / f"{run.result_bundle_id}.json"
                if b_path.exists():
                    bundle = CompiledBundle.model_validate_json(b_path.read_text(encoding="utf-8"))
                    service.bundle_store[run.result_bundle_id] = bundle
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
        run: PipelineRunRecord, req: Optional[ResumeRunRequest]
    ) -> PipelineRunRecord:
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

    @router.post(
        "/api/v1/research/runs/{run_id}/resume",
        response_model=Union[CompiledBundle, PipelineRunRecord],
    )
    async def resume_pipeline_run(
        run_id: str,
        request: Request,
        req: Optional[ResumeRunRequest] = None,
    ) -> Union[CompiledBundle, PipelineRunRecord]:
        """Resumes a checkpointed or interrupted run synchronously."""
        runner = _build_runner(request)
        run = runner.find_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        run = _prepare_run_for_resume(run, req)
        updated_run, bundle = await asyncio.to_thread(runner.execute_run, run)
        if bundle is not None:
            if bundle.bundle_id:
                service.bundle_store[bundle.bundle_id] = bundle
            return bundle
        return updated_run

    @router.post("/api/v1/research/runs/{run_id}/resume/stream")
    async def resume_pipeline_run_stream(
        run_id: str,
        request: Request,
        req: Optional[ResumeRunRequest] = None,
    ) -> StreamingResponse:
        """Resumes a checkpointed or interrupted run with SSE progress."""
        runner = _build_runner(request)
        run = runner.find_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        run = _prepare_run_for_resume(run, req)
        stream, queue = _launch_run_background(runner, run)
        loop = asyncio.get_running_loop()

        def cleanup() -> None:
            try:
                stream.subscribers.remove((loop, queue))
            except ValueError:
                pass

        return _sse_queue_stream(queue, on_close=cleanup)

    @router.get("/api/v1/research/blueprints")
    async def list_blueprints(request: Request) -> List[Dict[str, Any]]:
        """Lists all persisted Document Blueprints `(d)`."""
        store = _get_blueprint_store(request)
        return [bp.model_dump() for bp in store.list_blueprints()]

    @router.post("/api/v1/research/blueprints")
    async def create_or_update_blueprint(
        req: CreateBlueprintRequest,
        request: Request,
    ) -> Dict[str, Any]:
        """Saves a reusable Document Blueprint `(d)` directly or from a run."""
        store = _get_blueprint_store(request)
        sections = list(req.sections)
        title_tmpl = req.document_title_template
        exec_intent = req.executive_summary_intent
        default_domains = list(req.default_domains)

        source_plan = req.outline_plan
        if source_plan is None and req.source_run_id:
            runner = _build_runner(request, allow_mock_fallback=True)
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

        slug = sanitize_slug(req.blueprint_id or req.title)
        bp = DocumentBlueprint(
            blueprint_id=slug,
            title=req.title.strip(),
            domain=req.domain.strip() or "general",
            description=(req.description or "").strip() or None,
            default_domains=default_domains,
            document_title_template=title_tmpl or f"{req.title.strip()} — {{matter_id}}",
            executive_summary_intent=exec_intent
            or f"Structured synthesis using blueprint '{req.title.strip()}'.",
            sections=sections,
        )
        saved = store.save_blueprint(bp)
        return saved.model_dump()

    @router.delete("/api/v1/research/blueprints/{blueprint_id}")
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

    @router.post("/api/v1/research/bundles/{bundle_id}/comments", response_model=CompiledBundle)
    async def add_review_comment(
        bundle_id: str,
        req: AddCommentRequest,
        request: Request,
    ) -> CompiledBundle:
        """Anchors an inline human review comment onto a bundle node, link, section, or document."""
        if bundle_id not in service.bundle_store:
            raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")
        bundle = service.bundle_store[bundle_id]
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
        ingestor = getattr(request.app.state, "matter_ingestor", None) or service.ingestor
        if bundle.matter_id and bundle.bundle_id:
            _, _, _, bundles_dir = ingestor._matter_dirs(bundle.matter_id)
            bundles_dir.mkdir(parents=True, exist_ok=True)
            (bundles_dir / f"{bundle.bundle_id}.json").write_text(
                bundle.model_dump_json(indent=2), encoding="utf-8"
            )
        return bundle

    @router.delete(
        "/api/v1/research/bundles/{bundle_id}/comments/{comment_id}",
        response_model=CompiledBundle,
    )
    async def delete_review_comment(
        bundle_id: str,
        comment_id: str,
        request: Request,
    ) -> CompiledBundle:
        """Deletes a queued review comment from the bundle before regeneration."""
        if bundle_id not in service.bundle_store:
            raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")
        bundle = service.bundle_store[bundle_id]
        bundle.comments = [c for c in bundle.comments if c.comment_id != comment_id]
        ingestor = getattr(request.app.state, "matter_ingestor", None) or service.ingestor
        if bundle.matter_id and bundle.bundle_id:
            _, _, _, bundles_dir = ingestor._matter_dirs(bundle.matter_id)
            bundles_dir.mkdir(parents=True, exist_ok=True)
            (bundles_dir / f"{bundle.bundle_id}.json").write_text(
                bundle.model_dump_json(indent=2), encoding="utf-8"
            )
        return bundle

    @router.post("/api/v1/research/bundles/{bundle_id}/regenerate", response_model=CompiledBundle)
    async def regenerate_from_feedback(
        bundle_id: str,
        req: RegenerateRequest,
        request: Request,
    ) -> CompiledBundle:
        """Applies queued review comments via smart Stage-2 fallback regeneration."""
        if bundle_id not in service.bundle_store:
            raise HTTPException(status_code=404, detail=f"Bundle '{bundle_id}' not found.")
        bundle = service.bundle_store[bundle_id]
        runner = _build_runner(request)
        updated = await asyncio.to_thread(
            runner.apply_comments_and_recompile,
            bundle,
            req.comments,
            req.smooth_transitions,
        )
        service.bundle_store[bundle_id] = updated
        return updated

    return router
