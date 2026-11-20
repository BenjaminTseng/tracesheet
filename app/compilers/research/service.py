"""Service and `CompilerApp` adapter for the Broadsheet Research 4-stage pipeline."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.compilers.research.blueprints import BlueprintStore
from app.compilers.research.pipeline import AuditPipelineRunner
from app.compilers.research.sample_data import get_sample_bundles
from app.core.bundle import (
    AuditStatus,
    BlueprintMode,
    CommentScope,
    CompiledBundle,
    OutlinePlan,
    ReviewComment,
    SectionOutput,
    SectionPlan,
    TensionObject,
)
from app.core.compiler import AppDescriptor, PlatformContext
from app.core.gate import GatePolicy, ReadinessGate
from app.core.ingest import CanonicalRouter, MatterIngestor
from app.core.llm import LLMProvider, MockLLMProvider, create_llm_provider
from app.core.provenance import CaseSummaryRow, ReadinessReport

logger = logging.getLogger("jd_screen.research")


class BundleSummaryItem(BaseModel):
    """Compact summary metadata for the research bundle selector dropdown."""

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


class ResearchCompilerService:
    """Manages compiled research bundles, blueprints, and 4-stage pipeline runs."""

    def __init__(
        self,
        base_dir: Path,
        ingestor: Optional[MatterIngestor] = None,
        canonical_router: Optional[CanonicalRouter] = None,
        llm_provider: Optional[LLMProvider] = None,
        seed_samples: bool = True,
    ) -> None:
        """Initializes research compiler state rooted at `base_dir`."""
        self.base_dir = base_dir
        self.matters_root = base_dir / "matters"
        self.canonical_dir = base_dir / "canonical"
        self.ingestor = ingestor or MatterIngestor(self.matters_root)
        self.canonical_router = canonical_router or CanonicalRouter(self.canonical_dir)
        self.llm_provider = llm_provider
        self.blueprints_root = base_dir / "blueprints"
        self.blueprint_store = BlueprintStore(self.blueprints_root)
        self.gate = ReadinessGate(GatePolicy.advisory_coverage())
        self.bundle_store: Dict[str, CompiledBundle] = self._load_initial_bundles(seed_samples)
        self.active_run_streams: Dict[str, Any] = {}

    def _load_initial_bundles(self, seed_samples: bool) -> Dict[str, CompiledBundle]:
        store: Dict[str, CompiledBundle] = get_sample_bundles() if seed_samples else {}
        if self.matters_root.exists():
            for bundle_path in sorted(self.matters_root.glob("*/bundles/*.json")):
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

    def persist_bundle(self, bundle: CompiledBundle) -> None:
        """Persists a compiled research bundle to `matters/<id>/bundles/<bundle_id>.json`."""
        if not bundle.matter_id or not bundle.bundle_id:
            return
        _, _, _, bundles_dir = self.ingestor._matter_dirs(bundle.matter_id)
        bundles_dir.mkdir(parents=True, exist_ok=True)
        (bundles_dir / f"{bundle.bundle_id}.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8"
        )

    def resolve_llm_provider(
        self, override: Optional[LLMProvider] = None, llm_config: Optional[Dict[str, Any]] = None
    ) -> LLMProvider:
        """Resolves an active `LLMProvider`, defaulting to Gemini or Mock fallback."""
        if override is not None:
            return override
        if self.llm_provider is not None:
            return self.llm_provider
        cfg = llm_config or {}
        return create_llm_provider(
            provider_name=cfg.get("provider", "gemini"),
            model=cfg.get("model"),
            api_key=cfg.get("api_key"),
        )

    def make_runner(
        self,
        llm_override: Optional[LLMProvider] = None,
        canonical_override: Optional[CanonicalRouter] = None,
        ingestor_override: Optional[MatterIngestor] = None,
        blueprints_root_override: Optional[Path] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        allow_mock_fallback: bool = False,
    ) -> AuditPipelineRunner:
        """Constructs an `AuditPipelineRunner` with platform defaults and test overrides."""
        router = canonical_override or self.canonical_router
        ingestor = ingestor_override or self.ingestor
        bp_root = blueprints_root_override or self.blueprints_root
        if allow_mock_fallback:
            try:
                llm = self.resolve_llm_provider(override=llm_override, llm_config=llm_config)
            except Exception:
                llm = MockLLMProvider()
        else:
            llm = self.resolve_llm_provider(override=llm_override, llm_config=llm_config)
        return AuditPipelineRunner(
            llm=llm,
            canonical_router=router,
            matter_ingestor=ingestor,
            blueprints_root=bp_root,
        )

    def evaluate_bundle_readiness(self, bundle: CompiledBundle) -> ReadinessReport:
        """Evaluates a research bundle under `advisory_coverage` policy."""
        return self.gate.evaluate(
            unverified_fields=[
                nid
                for nid, node in bundle.nodes.items()
                if node.type == "claim" and node.audit.status in ("unverified", "disputed")
            ],
            open_questions=[],
            tensions=list(bundle.audit_summary.cross_section_tensions),
        )

    def list_bundle_summaries(self) -> List[BundleSummaryItem]:
        """Returns compact bundle summaries for UI bundle/matter selection."""
        items: List[BundleSummaryItem] = []
        for b_id, bundle in self.bundle_store.items():
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


class ResearchCompilerApp:
    """`CompilerApp` adapter registering Broadsheet Research into `app.server`."""

    descriptor = AppDescriptor(
        app_id="research",
        label="Broadsheet Research",
        description="4-stage cited research, legal brief, and memo compiler with inline review regeneration.",
        ui_route="/research",
        api_prefix="/api/v1/research",
        gate_mode="advisory_coverage",
    )

    def __init__(self, service: ResearchCompilerService) -> None:
        self.service = service

    def list_cases(self) -> List[CaseSummaryRow]:
        """Returns standardized `CaseSummaryRow` items for compiled research bundles."""
        rows: List[CaseSummaryRow] = []
        for summary in self.service.list_bundle_summaries():
            bundle = self.service.bundle_store[summary.bundle_id]
            report = self.service.evaluate_bundle_readiness(bundle)
            rows.append(
                CaseSummaryRow(
                    matter_id=summary.matter_id or summary.bundle_id,
                    app_id="research",
                    title=summary.title,
                    status=report.status,
                    open_blockers=0,
                    open_advisories=summary.tension_count + summary.pending_comments,
                    metrics={
                        "bundle_id": summary.bundle_id,
                        "claims": f"{summary.verified_count}/{summary.total_claims}",
                        "tensions": str(summary.tension_count),
                    },
                    updated_at=bundle.artifact.created_at
                    or datetime.datetime.now(datetime.timezone.utc).isoformat(),
                )
            )
        return rows

    def build_router(self, ctx: PlatformContext) -> APIRouter:
        """Builds the `/api/v1/research` router mounted on the shared platform app."""
        from app.compilers.research.routes import build_research_router

        return build_research_router(self.service)
