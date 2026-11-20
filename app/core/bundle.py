"""Data models, invariant validators, and DAG compiler for audit-grounded documents.

This module implements the two-tier data contract defined in the Audit-Grounded
Document Pipeline Specification:
1. Tier 1 (Intermediate Section Schema): Validated worker LLM output with local
   numbered `<ref n="X">` tags and nested `supports` / `sub_supports`.
2. Tier 2 (Final Compiled Bundle Schema): Normalized flat Directed Acyclic Graph (DAG)
   with globally unique node IDs, bidirectional edges, audit metadata, and
   cross-section tension flags consumed by the bounded spatial canvas frontend.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from pydantic import BaseModel, Field, field_validator


# =====================================================================
# Shared & Polymorphic Models
# =====================================================================

NodeType = Literal[
    "claim",
    "evidence",
    "reasoning",
    "authority",
    "calculation",
    "assumption",
]

SupportNodeType = Literal[
    "evidence",
    "reasoning",
    "authority",
    "calculation",
    "assumption",
]

SourceType = Literal[
    "pdf",
    "spreadsheet",
    "web",
    "api",
    "internal_db",
    "markdown",
    "docx",
    "calculation_ledger",
    "event_log",
]

SourceReliabilityTier = Literal[
    "primary_record",
    "secondary_analysis",
    "self_reported",
]

AuditStatus = Literal[
    "verified",
    "extrapolation",
    "assumption",
    "disputed",
    "unverified",
]

EvaluatorType = Literal[
    "deterministic",
    "llm_auditor",
    "human",
]


class SourceLocator(BaseModel):
    """Pinpoints exact evidence coordinates in source files, web snapshots, or APIs.

    Attributes:
        source_type: Polymorphic discriminator indicating the backing medium.
        file_name: Basename of the PDF or spreadsheet file.
        page: 1-based page number for PDF sources.
        bounding_box: Normalized `[x1, y1, x2, y2]` coordinates on a PDF page.
        locator_key: Anchor ID, record number, or CSS/DOM selector.
        sheet: Worksheet name for spreadsheet sources.
        cell_range: A1-style cell coordinate or range (e.g., `G14`, `B4:F12`).
        raw_value: Unformatted primitive value from a cell or API payload.
        url: Full canonical URL for web sources.
        snapshot_timestamp: ISO-8601 timestamp when the web resource was captured.
        endpoint: HTTP method and path for API telemetry sources.
        method: HTTP verb (`GET`, `POST`, `PUT`).
        query_params: Dictionary of request parameters sent to the API.
        json_path: JSONPath expression extracting the cited value.
        payload_hash: SHA-256 digest of the raw response or document for verification.
        database: Database connection or catalog name for SQL sources.
        table: Table or view name queried.
        query: Read-only SQL query executed to retrieve the record.
        row_id: Primary key of the matched database record.
        event_id: Event identifier for streaming/case-management event logs.
        reliability_tier: Epistemic reliability classification of the backing file `(a)`.
        origin_description: User-supplied description of file origin/context.
    """

    source_type: SourceType
    file_name: Optional[str] = None
    page: Optional[int] = None
    bounding_box: Optional[List[int]] = None
    locator_key: Optional[str] = None
    sheet: Optional[str] = None
    cell_range: Optional[str] = None
    raw_value: Optional[Any] = None
    url: Optional[str] = None
    snapshot_timestamp: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[Literal["GET", "POST", "PUT"]] = None
    query_params: Optional[Dict[str, Any]] = None
    json_path: Optional[str] = None
    payload_hash: Optional[str] = None
    database: Optional[str] = None
    table: Optional[str] = None
    query: Optional[str] = None
    row_id: Optional[Any] = None
    event_id: Optional[str] = None
    reliability_tier: Optional[SourceReliabilityTier] = None
    origin_description: Optional[str] = None


class MatterFileMetadata(BaseModel):
    """Origin description and reliability classification attached to a matter input file `(a)`."""

    filename: str
    reliability_tier: SourceReliabilityTier = "primary_record"
    origin_description: Optional[str] = None
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class NodeAudit(BaseModel):
    """Provenance and truthfulness verification verdict attached to a graph node.

    Attributes:
        status: Epistemic status classification of the node.
        score: Numeric confidence score between 0.0 and 1.0.
        evaluator_type: Whether verified by deterministic code, LLM auditor, or human.
        evaluator_note: Concise explanation justifying the verification verdict.
    """

    status: AuditStatus = "verified"
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    evaluator_type: EvaluatorType = "deterministic"
    evaluator_note: str = "Verified against source definitions."


# =====================================================================
# Tier 1: Intermediate Section Schema (Worker LLM Output)
# =====================================================================

class SubSupportItem(BaseModel):
    """Level 2+ supporting authority, calculation, or secondary deduction.

    Attributes:
        n: Local integer reference matching `<ref n="10X">` inside the parent `body`.
        type: Classification of the supporting item.
        title: Concise card headline.
        quote: Verbatim excerpt from the governing source or authority.
        body: Explanatory synthesis (may itself contain deeper `<ref n="100X">` tags).
        formula: Mathematical or spreadsheet expression.
        url: External reference URL.
        image_url: Path to visual diagram or chart asset.
        locator: Optional source coordinates if backed by a raw file/API.
        audit: Optional audit verdict from the local section auditor.
        sub_supports: Optional Level 3 nested support items.
    """

    n: int
    type: SupportNodeType
    title: str
    fact_id: Optional[str] = None
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    locator: Optional[SourceLocator] = None
    audit: Optional[NodeAudit] = None
    sub_supports: List[SubSupportItem] = Field(default_factory=list)


class SupportItem(BaseModel):
    """Level 1 supporting node attached directly to a tagged document clause.

    Attributes:
        type: Classification (`evidence`, `reasoning`, `authority`, `calculation`, `assumption`).
        title: Compact card headline (under 8 words recommended).
        quote: Verbatim excerpt from the raw source.
        body: Explanatory synthesis; may contain `<ref n="10X">` sub-citations.
        formula: Mathematical or spreadsheet formula string.
        url: Public or internal reference hyperlink.
        image_url: Optional visual chart or figure URL.
        locator: Exact coordinates in the backing file, database, or API.
        audit: Optional local audit metadata.
        sub_supports: Nested Level 2+ items referenced inside `body`.
    """

    type: SupportNodeType
    title: str
    fact_id: Optional[str] = None
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    locator: Optional[SourceLocator] = None
    audit: Optional[NodeAudit] = None
    sub_supports: List[SubSupportItem] = Field(default_factory=list)


class SupportGroup(BaseModel):
    """Maps a local reference integer `n` to its cluster of supporting objects.

    Attributes:
        n: Sequential reference integer matching `<ref n="X">` in the section text.
        title: Optional short title for the claim itself.
        audit: Optional audit metadata for the claim node.
        items: Non-empty list of supporting nodes attached to this clause.
    """

    n: int
    title: Optional[str] = None
    audit: Optional[NodeAudit] = None
    items: List[SupportItem] = Field(min_length=1)


class SectionOutput(BaseModel):
    """Contract expected from an individual section worker LLM.

    Attributes:
        section_id: Unique section slug (e.g., `sec_02_jurisdiction`).
        section_title: Optional human-readable heading for the section.
        drafting_notes: Plain-English explanation of how this section synthesized facts,
            calculations, and commonsense/canonical warrants.
        text: Markdown narrative containing `<ref n="X">clause</ref>` tags.
        supports: List of support clusters corresponding to each inline `<ref>`.
    """

    section_id: str
    section_title: Optional[str] = None
    drafting_notes: Optional[str] = None
    text: str
    supports: List[SupportGroup]


class Stage3CompactLocator(BaseModel):
    """Lightweight file/cell locator emitted by Stage 2 and Stage 3 before disk hydration."""

    source_type: Literal[
        "markdown",
        "pdf",
        "spreadsheet",
        "calculation_ledger",
        "event_log",
        "api",
    ]
    file_name: str
    locator_key: Optional[str] = None
    sheet: Optional[str] = None
    cell_range: Optional[str] = None
    json_path: Optional[str] = None
    event_id: Optional[str] = None


class Stage2CanonicalRefDraft(BaseModel):
    """Lightweight canonical authority citation emitted by Stage 2 before disk hydration."""

    auth_id: str
    title: str
    verbatim_quote: str
    source_file: str


class Stage2ExtractedFactDraft(BaseModel):
    """Lightweight Stage 2 fact entry paired with `Stage3CompactLocator`."""

    fact_id: str
    query_addressed: str
    title: str
    quote: str
    formula: Optional[str] = None
    locator: Stage3CompactLocator


class Stage2VerifiedFactLedgerDraft(BaseModel):
    """Compact wire schema for Stage 2 decoding into `VerifiedFactLedger`."""

    section_id: str
    harvest_summary: str
    verified_facts: List[Stage2ExtractedFactDraft]
    unresolved_gaps: List[UnresolvedGapItem]
    additional_authorities: List[Stage2CanonicalRefDraft]


class Stage3SubSupportItem(BaseModel):
    """Non-recursive Level-2 support item for lightweight Stage 3 JSON decoding."""

    n: int
    type: SupportNodeType
    title: str
    fact_id: Optional[str] = None
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    url: Optional[str] = None
    locator: Optional[Stage3CompactLocator] = None


class Stage3SupportItem(BaseModel):
    """Lightweight Stage 3 support node without Stage-4 audit fields or 22-field locators."""

    type: SupportNodeType
    title: str
    fact_id: Optional[str] = None
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    locator: Optional[Stage3CompactLocator] = None
    sub_supports: List[Stage3SubSupportItem] = Field(default_factory=list)


class Stage3SupportGroup(BaseModel):
    """Lightweight Stage 3 support cluster matching `<ref n='X'>`."""

    n: int
    title: Optional[str] = None
    items: List[Stage3SupportItem] = Field(min_length=1)


class Stage3SectionDraft(BaseModel):
    """Compact non-recursive wire schema for Stage 3 decoding into `SectionOutput`."""

    section_id: str
    section_title: str
    drafting_notes: str
    text: str
    supports: List[Stage3SupportGroup]


def compact_json_schema(model_cls: type[BaseModel]) -> Dict[str, Any]:
    """Returns a Pydantic JSON schema stripped of verbose string docstring descriptions."""

    def _strip(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _strip(v)
                for k, v in obj.items()
                if not (k == "description" and isinstance(v, str))
            }
        if isinstance(obj, list):
            return [_strip(item) for item in obj]
        return obj

    return _strip(model_cls.model_json_schema())


# =====================================================================
# Tier 2: Final Compiled Bundle Schema (Frontend Canvas Contract)
# =====================================================================

class SectionObject(BaseModel):
    """Compiled section inside the final artifact envelope.

    Attributes:
        section_id: Canonical section identifier.
        section_title: Human-readable heading for navigation.
        order: 1-based sequence order.
        content: Markdown prose with global `<ref id="node_id">clause</ref>` tags.
    """

    section_id: str
    section_title: str
    order: int
    content: str


class ArtifactEnvelope(BaseModel):
    """Top-level document container metadata and ordered sections.

    Attributes:
        title: Formal document title.
        version: Semantic version string.
        created_at: ISO-8601 compilation timestamp.
        metadata: Arbitrary key-value document attributes (domain, case_number, author).
        summary: Executive abstract of the document.
        sections: Ordered list of compiled section blocks.
    """

    title: str
    version: str = "1.0.0"
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None
    sections: List[SectionObject]


class TensionObject(BaseModel):
    """Represents a cross-section or cross-bundle contradiction flagged by auditing.

    Attributes:
        tension_id: Unique identifier for the tension warning.
        involved_claim_ids: Claim node IDs whose assertions are in tension.
        severity: Either `warning` (nuance/scope friction) or `blocker` (contradiction).
        description: Plain-English explanation of the discrepancy.
        tension_scope: Whether tension is within the active document or against a prior bundle.
        conflicting_bundle_id: Identifier of the prior bundle in conflict (for `cross_bundle`).
        conflicting_bundle_title: Title of the prior bundle in conflict (for `cross_bundle`).
    """

    tension_id: str
    involved_claim_ids: List[str]
    severity: Literal["warning", "blocker"] = "warning"
    description: str
    tension_scope: Literal["intra_document", "cross_bundle"] = "intra_document"
    conflicting_bundle_id: Optional[str] = None
    conflicting_bundle_title: Optional[str] = None


class AuditSummary(BaseModel):
    """Holistic audit telemetry across the compiled document.

    Attributes:
        total_claims: Total number of substantive claim nodes in the document.
        verified_count: Count of claims with verified status.
        extrapolation_count: Count of claims flagged as extrapolations.
        assumption_count: Count of claims relying on baseline assumptions.
        cross_section_tensions: List of cross-section tension warnings.
    """

    total_claims: int
    verified_count: int
    extrapolation_count: int
    assumption_count: int
    cross_section_tensions: List[TensionObject] = Field(default_factory=list)


class GraphNode(BaseModel):
    """Single node in the normalized Directed Acyclic Graph (DAG).

    Attributes:
        id: Globally unique node key (e.g., `claim_sec01_1`, `evi_sec01_1_1`).
        type: Node classification (`claim`, `evidence`, `reasoning`, `authority`,
            `calculation`, `assumption`).
        title: Compact headline displayed at the top of the spatial card.
        section_id: Originating section identifier for visual grouping.
        clause_text: Exact tagged text from the document (populated for `claim` nodes).
        quote: Verbatim source quote (populated for `evidence` and `authority` nodes).
        body: Explanatory narrative; may contain `<ref id="child_node_id">` tags.
        formula: Mathematical or spreadsheet formula string.
        url: External hyperlink.
        image_url: Optional diagram or chart image path.
        locator: Polymorphic source coordinates for raw file/API/DB inspection.
        direct_child_ids: Outgoing edge IDs to supporting child nodes.
        parent_claim_ids: Incoming root claim IDs that this node ultimately supports.
        audit: Truthfulness and provenance audit metadata.
    """

    id: str
    type: NodeType
    title: str
    section_id: str
    clause_text: Optional[str] = None
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    locator: Optional[SourceLocator] = None
    direct_child_ids: List[str] = Field(default_factory=list)
    parent_claim_ids: List[str] = Field(default_factory=list)
    audit: NodeAudit = Field(default_factory=NodeAudit)


CommentScope = Literal["node", "link", "section", "document"]


class ReviewComment(BaseModel):
    """Human inline comment anchored to a graph node, logical link, section, or overall document.

    Attributes:
        comment_id: Unique identifier for the review comment.
        scope: Feedback target granularity (`node`, `link`, `section`, or `document`).
        node_id: Target node ID in `CompiledBundle.nodes` (or `__section__`/`__document__`).
        section_id: Section ID that owns the target (or `__document__` for document-wide notes).
        target_label: Human-readable label of what was commented on (e.g. link edge or section).
        comment_text: Reviewer's feedback, critique, or instruction for regeneration.
        suggested_status: Optional human audit status override.
        created_at: ISO-8601 timestamp when the comment was created.
        resolved: Whether a regeneration pass has addressed this comment.
    """

    comment_id: str
    scope: CommentScope = "node"
    node_id: str = "__document__"
    section_id: str = "__document__"
    target_label: Optional[str] = None
    comment_text: str
    suggested_status: Optional[AuditStatus] = None
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    resolved: bool = False


class CompiledBundle(BaseModel):
    """Complete compiled payload consumed by the bounded spatial canvas UI.

    Attributes:
        bundle_id: Optional slug identifying the bundle in the viewer library.
        matter_id: Optional project/matter directory identifier owning this bundle.
        question: Optional user prompt `(c)` that generated this artifact.
        artifact: Document envelope containing metadata and ordered sections.
        audit_summary: Document-wide audit counts and tension alerts.
        nodes: Flat lookup dictionary mapping `node_id` to `GraphNode`.
        comments: Queued and resolved human review comments anchored to nodes.
        stage_artifacts: Intermediate pipeline state (`outline_plan`, `ledgers`,
            `sections`) preserved for surgical feedback regeneration.
    """

    bundle_id: Optional[str] = None
    matter_id: Optional[str] = None
    question: Optional[str] = None
    artifact: ArtifactEnvelope
    audit_summary: AuditSummary
    nodes: Dict[str, GraphNode]
    comments: List[ReviewComment] = Field(default_factory=list)
    stage_artifacts: Dict[str, Any] = Field(default_factory=dict)


# =====================================================================
# Pipeline Stage Contracts
# =====================================================================


class CanonicalAuthorityRef(BaseModel):
    """Canonical authority entry mapped during Stage 1 from `canonical/`.

    Attributes:
        auth_id: Stable `[AUTH:...]` identifier from the canonical library.
        title: Display title of the statute, rule, or precedent.
        url: Optional external or canonical reference URL.
        verbatim_quote: Exact authoritative holding or policy excerpt.
        source_file: Relative path to the canonical Markdown file.
    """

    auth_id: str
    title: str
    url: Optional[str] = None
    verbatim_quote: str
    source_file: Optional[str] = None


class CanonicalDocumentSynopsisDraft(BaseModel):
    """LLM-synthesized routing metadata generated at ingest time for a canonical document."""

    title: str
    authority_tier: Literal[
        "statute_regulation",
        "case_law_precedent",
        "treatise_commentary",
        "local_rule_guidance",
        "internal_rubric_policy",
    ] = "statute_regulation"
    jurisdiction_scope: str = "General / Federal"
    scope_synopsis: str


class CanonicalDocumentCard(BaseModel):
    """Tier-1 card catalog entry representing one canonical document in `canonical/INDEX.md`."""

    doc_id: str
    domain: str
    title: str
    authority_tier: str = "statute_regulation"
    jurisdiction_scope: str = "General / Federal"
    scope_synopsis: str
    authority_file: str
    toc_file: str
    authority_count: int
    content_hash: Optional[str] = None


class SectionPlan(BaseModel):
    """Stage 1 outline plan for an individual section of the response.

    Attributes:
        section_id: Unique section slug.
        section_title: Human-readable section heading.
        stated_intention: Exact analytical or legal question the section must resolve.
        routing_rationale: Explanation of why the selected canonical `[AUTH:...]` rules
            govern this section, or why it relies on direct evidence/commonsense logic.
        governing_authorities: Canonical `[AUTH:...]` entries governing this section.
        required_fact_queries: Specific factual questions to answer from inputs `(a)`.
    """

    section_id: str
    section_title: str
    stated_intention: str
    routing_rationale: Optional[str] = None
    governing_authorities: List[CanonicalAuthorityRef] = Field(default_factory=list)
    required_fact_queries: List[str] = Field(default_factory=list)


class OutlinePlan(BaseModel):
    """Complete Stage 1 plan decomposing user request `(c)` against corpus `(b)`.

    Attributes:
        document_title: Proposed title for the synthesized broadsheet artifact.
        executive_summary_intent: Core thesis or synthesis objective.
        sections: Ordered list of planned document sections.
    """

    document_title: str
    executive_summary_intent: str
    sections: List[SectionPlan] = Field(min_length=1)


class ExtractedFactItem(BaseModel):
    """Single coordinate-stamped fact extracted from project inputs `(a)`.

    Attributes:
        fact_id: Local identifier within the section's fact ledger.
        query_addressed: Which Stage 1 fact query this item answers.
        title: Concise descriptive title for the extracted fact.
        quote: Verbatim quote or formatted value copied from the indexed source.
        formula: Optional spreadsheet or mathematical formula string.
        locator: Exact pre-computed `SourceLocator` copied from the indexed source.
    """

    fact_id: str
    query_addressed: str
    title: str
    quote: str
    formula: Optional[str] = None
    locator: SourceLocator


class UnresolvedGapItem(BaseModel):
    """Records a required fact query that could not be confirmed in inputs `(a)`.

    Attributes:
        query: The factual question that lacked direct verification.
        recommended_handling: Whether downstream drafting should flag as `assumption`
            or `extrapolation`.
        rationale: Explanation of what was searched and why it remains unresolved.
    """

    query: str
    recommended_handling: Literal["assumption", "extrapolation"]
    rationale: str


class VerifiedFactLedger(BaseModel):
    """Stage 2 output ledger containing harvested facts, gaps, and discovered rules.

    Attributes:
        section_id: Identifier of the section this ledger supports.
        harvest_summary: Plain-English explanation of what sources were searched and found.
        verified_facts: Coordinate-stamped facts harvested from `(a)`.
        unresolved_gaps: Queries that could not be directly verified in `(a)`.
        additional_authorities: Canonical rules discovered while investigating `(a)`.
    """

    section_id: str
    harvest_summary: Optional[str] = None
    verified_facts: List[ExtractedFactItem] = Field(default_factory=list)
    unresolved_gaps: List[UnresolvedGapItem] = Field(default_factory=list)
    additional_authorities: List[CanonicalAuthorityRef] = Field(default_factory=list)


class DecisionAnswerItem(BaseModel):
    """Normalized answer for a single question from the Gemini Decisions API."""

    question_id: str
    question_type: Literal["noul", "choice", "score"]
    noul: Optional[float] = None
    choice: Optional[str] = None
    probabilities: Dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0


class DecisionBatchResult(BaseModel):
    """Normalized batch response from `LLMProvider.evaluate_decisions`."""

    answers: Dict[str, DecisionAnswerItem] = Field(default_factory=dict)


class SectionAuditResult(BaseModel):
    """Stage 4 section-level 3-point audit verdict.

    Attributes:
        section_id: Audited section identifier.
        check_a_relevance: Whether every support node directly bears on its clause.
        check_b_congruence: Whether source quotes strictly entail the drafted claims.
        check_c_intent: Whether the section satisfies its Stage 1 `stated_intention`.
        passed: Overall pass/fail gate decision.
        audit_rationale: Plain-English explanation of why the section passed or failed audit.
        critique_for_retry: Specific actionable critique if `passed` is False.
        node_verdicts: Per-claim (`n`) `NodeAudit` overrides produced by the auditor.
        decision_probabilities: Optional Decisions API calibrated scores keyed by question ID.
    """

    section_id: str
    check_a_relevance: bool
    check_b_congruence: bool
    check_c_intent: bool
    passed: bool
    audit_rationale: Optional[str] = None
    critique_for_retry: Optional[str] = None
    node_verdicts: Dict[int, NodeAudit] = Field(default_factory=dict)
    decision_probabilities: Dict[str, float] = Field(default_factory=dict)

    @field_validator("node_verdicts", mode="before")
    @classmethod
    def _coerce_node_verdict_keys(cls, v: Any) -> Any:
        """Accepts `'ref-1'`, `'n=1'`, or `'1'` keys from structured LLM outputs."""
        if not isinstance(v, dict):
            return v
        coerced: Dict[int, Any] = {}
        for k, val in v.items():
            if isinstance(k, int):
                coerced[k] = val
            else:
                match = re.search(r"(\d+)", str(k))
                if match:
                    coerced[int(match.group(1))] = val
        return coerced


PipelineRunStatus = Literal[
    "running",
    "awaiting_stage1_approval",
    "awaiting_stage2_approval",
    "completed",
    "failed",
]


class PipelineProgressEvent(BaseModel):
    """Granular progress event recorded on a persisted pipeline run."""

    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    stage: str
    substage: Optional[str] = None
    message: str


BlueprintMode = Literal["guided", "strict", "none"]


class DocumentBlueprint(BaseModel):
    """Reusable document outline template `(d)` for recurring filings or reports."""

    blueprint_id: str
    title: str
    domain: str = "general"
    description: Optional[str] = None
    default_domains: List[str] = Field(default_factory=list)
    document_title_template: str
    executive_summary_intent: str
    sections: List[SectionPlan] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class PipelineRunRecord(BaseModel):
    """Disk-persisted state of a 4-stage pipeline execution (`matters/<id>/runs/<run_id>.json`)."""

    run_id: str
    matter_id: str
    question: str
    bundle_id: Optional[str] = None
    checkpoint_mode: bool = False
    smooth_transitions: bool = True
    canonical_domains: Optional[List[str]] = None
    selected_domains: List[str] = Field(default_factory=list)
    blueprint_id: Optional[str] = None
    blueprint_mode: BlueprintMode = "none"
    status: PipelineRunStatus = "running"
    current_stage: str = "init"
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    error: Optional[str] = None
    events: List[PipelineProgressEvent] = Field(default_factory=list)
    outline_plan: Optional[OutlinePlan] = None
    ledgers: Dict[str, VerifiedFactLedger] = Field(default_factory=dict)
    sections: List[SectionOutput] = Field(default_factory=list)
    audits: Dict[str, SectionAuditResult] = Field(default_factory=dict)
    result_bundle_id: Optional[str] = None


# =====================================================================
# Deterministic Verification & Graph Compilation Suite
# =====================================================================

class SectionValidator:
    """Verifies that an individual section adheres to strict grounding invariants."""

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

    @classmethod
    def validate_section(cls, section: SectionOutput) -> Tuple[bool, List[str]]:
        """Validates reference parity between inline tags and support definitions.

        Checks that every `<ref n="X">` tag in `section.text` resolves to a
        `SupportGroup` in `section.supports`, that no `SupportGroup` is left
        uncited, and that nested sub-references inside `body` text resolve to
        `sub_supports`.

        Args:
            section: Deserialized `SectionOutput` instance to inspect.

        Returns:
            Tuple of `(is_valid, list_of_error_strings)`.
        """
        errors: List[str] = []
        found_matches = cls.TAG_PATTERN.findall(section.text)
        text_indices: Set[int] = {int(m[0]) for m in found_matches}
        support_indices: Set[int] = {s.n for s in section.supports}

        orphaned_in_text = text_indices - support_indices
        if orphaned_in_text:
            errors.append(
                f"Inline tags lack support definitions: {sorted(list(orphaned_in_text))}"
            )

        unused_supports = support_indices - text_indices
        if unused_supports:
            errors.append(
                f"Support items never referenced in text: {sorted(list(unused_supports))}"
            )

        # Recursively check nested sub-references and mandatory plain-English
        # explanations on reasoning/calculation/assumption cards.
        for group in section.supports:
            for item in group.items:
                if item.type in ("reasoning", "calculation", "assumption") and not (
                    item.body and item.body.strip()
                ):
                    errors.append(
                        f"Node '{item.title}' (type={item.type}) under ref n={group.n} "
                        "must include a non-empty plain-English `body` explanation."
                    )
                cls._validate_nested_body(group.n, item.body, item.sub_supports, errors)

        return (len(errors) == 0, errors)

    @classmethod
    def _validate_nested_body(
        cls,
        parent_n: int,
        body: Optional[str],
        sub_supports: List[SubSupportItem],
        errors: List[str],
    ) -> None:
        """Recursively validates `<ref n='...'>` tags inside support node bodies.

        Args:
            parent_n: Reference integer of the parent node for clear error messages.
            body: Optional markdown narrative on the support item.
            sub_supports: Attached child `SubSupportItem` list.
            errors: Mutable list accumulating validation error descriptions.
        """
        if not body:
            return
        sub_matches = cls.TAG_PATTERN.findall(body)
        sub_indices = {int(m[0]) for m in sub_matches}
        defined_sub_indices = {sub.n for sub in sub_supports}

        unresolved_subs = sub_indices - defined_sub_indices
        if unresolved_subs:
            errors.append(
                f"Node under ref n={parent_n} references sub-refs "
                f"{sorted(list(unresolved_subs))} that are missing from sub_supports."
            )

        for sub in sub_supports:
            cls._validate_nested_body(sub.n, sub.body, sub.sub_supports, errors)


class StitchInvariantGate:
    """Validates that a whole-document smoothing pass preserved all citations."""

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"]([\w:.-]+)['\"]>(.*?)</ref>", re.DOTALL)
    LOCAL_TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

    @classmethod
    def prepare_section_for_stitch(cls, section: SectionOutput) -> str:
        """Namespaces local `<ref n='X'>` tags in a section to `<ref n='sec_id:X'>`.

        Args:
            section: Validated `SectionOutput` whose local indices should be isolated.

        Returns:
            Section text with section-namespaced reference keys preventing cross-section
            collisions during whole-document smoothing.
        """
        return cls.LOCAL_TAG_PATTERN.sub(
            lambda m: f"<ref n='{section.section_id}:{m.group(1)}'>{m.group(2)}</ref>",
            section.text,
        )

    @classmethod
    def prepare_for_stitch(cls, sections: List[SectionOutput]) -> str:
        """Concatenates all sections with section-namespaced `<ref n='sec_id:X'>` tags.

        Args:
            sections: Ordered list of validated `SectionOutput` objects.

        Returns:
            Combined pre-stitched text safe for multi-section editorial smoothing.
        """
        return "\n\n".join(cls.prepare_section_for_stitch(sec) for sec in sections)

    @staticmethod
    def _format_ref_keys(keys: Set[str]) -> List[Any]:
        """Formats reference keys as integers when purely numeric for readable error output."""
        formatted: List[Any] = [int(k) if k.isdigit() else k for k in keys]
        return sorted(formatted, key=lambda x: (isinstance(x, str), str(x)))

    @classmethod
    def verify_stitch(
        cls, pre_stitched_text: str, post_stitched_text: str
    ) -> Tuple[bool, List[str]]:
        """Ensures that no tags were deleted, invented, or substantively gutted.

        Args:
            pre_stitched_text: Concatenated text of all raw sections prior to smoothing.
            post_stitched_text: Output returned by the editorial smoothing LLM.

        Returns:
            Tuple of `(passed, list_of_violations)`.
        """
        violations: List[str] = []

        pre_matches = cls.TAG_PATTERN.findall(pre_stitched_text)
        post_matches = cls.TAG_PATTERN.findall(post_stitched_text)

        pre_dict: Dict[str, str] = {n.strip(): text.strip() for n, text in pre_matches}
        post_dict: Dict[str, str] = {n.strip(): text.strip() for n, text in post_matches}

        pre_ids = set(pre_dict.keys())
        post_ids = set(post_dict.keys())

        missing = pre_ids - post_ids
        if missing:
            violations.append(
                f"Editorial pass removed citations with n={cls._format_ref_keys(missing)}"
            )

        added = post_ids - pre_ids
        if added:
            violations.append(
                f"Editorial pass invented ungrounded citations with n={cls._format_ref_keys(added)}"
            )

        for n, original_clause in pre_dict.items():
            if n in post_dict:
                smoothed_clause = post_dict[n]
                if len(smoothed_clause) == 0:
                    violations.append(f"Citation n={n} clause was completely emptied.")
                elif len(smoothed_clause) < len(original_clause) * 0.4:
                    violations.append(
                        f"Citation n={n} clause was truncated excessively: "
                        f"'{original_clause}' -> '{smoothed_clause}'"
                    )

        return (len(violations) == 0, violations)


class CompiledGraphBuilder:
    """Compiles validated `SectionOutput` objects into a global `CompiledBundle` DAG."""

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

    def __init__(
        self,
        document_title: str,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initializes the graph compiler.

        Args:
            document_title: Formal title of the compiled artifact.
            summary: Optional executive abstract.
            metadata: Optional dictionary of document metadata.
        """
        self.document_title = document_title
        self.summary = summary
        self.metadata = metadata or {}
        self.sections_payload: List[SectionObject] = []
        self.nodes_registry: Dict[str, GraphNode] = {}

    @staticmethod
    def _rewrite_section_tags(
        text: str,
        section_id: str,
        global_ref_map: Dict[Tuple[str, int], str],
    ) -> str:
        """Rewrites both namespaced (`sec_id:n`) and local (`n`) ref tags for one section."""
        updated = text
        for (s_id, n), global_id in global_ref_map.items():
            if s_id != section_id:
                continue
            updated = re.sub(
                rf"<ref\s+n=['\"]{re.escape(s_id)}:{n}['\"]>(.*?)</ref>",
                lambda m, gid=global_id: f"<ref id='{gid}'>{m.group(1)}</ref>",
                updated,
                flags=re.DOTALL,
            )
            updated = re.sub(
                rf"<ref\s+n=['\"]{n}['\"]>(.*?)</ref>",
                lambda m, gid=global_id: f"<ref id='{gid}'>{m.group(1)}</ref>",
                updated,
                flags=re.DOTALL,
            )
        return updated

    def _compile_sub_supports(
        self,
        sec_id: str,
        root_claim_id: str,
        parent_prefix: str,
        parent_body: str,
        sub_supports: List[SubSupportItem],
        global_ref_map: Dict[Tuple[str, int], str],
    ) -> Tuple[str, List[str]]:
        """Recursively flattens nested `sub_supports` into the global node registry.

        Args:
            sec_id: Originating section identifier.
            root_claim_id: Top-level claim ID for `parent_claim_ids` tracking.
            parent_prefix: String prefix used to construct deterministic child IDs.
            parent_body: Narrative body containing `<ref n="10X">` tags to rewrite.
            sub_supports: List of nested `SubSupportItem` nodes.
            global_ref_map: Lookup mapping `(section_id, local_n)` to `global_node_id`.

        Returns:
            Tuple of `(rewritten_parent_body, list_of_direct_child_ids)`.
        """
        sub_child_ids: List[str] = []
        updated_body = parent_body or ""

        for sub in sub_supports:
            sub_id = f"{sub.type[:3]}_{parent_prefix}_sub{sub.n}"
            sub_child_ids.append(sub_id)
            global_ref_map[(sec_id, sub.n)] = sub_id

            nested_body, deeper_child_ids = self._compile_sub_supports(
                sec_id=sec_id,
                root_claim_id=root_claim_id,
                parent_prefix=sub_id,
                parent_body=sub.body or "",
                sub_supports=sub.sub_supports,
                global_ref_map=global_ref_map,
            )

            default_status: AuditStatus = (
                "assumption" if sub.type == "assumption" else "verified"
            )
            node_audit = sub.audit or NodeAudit(
                status=default_status,
                score=0.75 if default_status == "assumption" else 1.0,
                evaluator_type="deterministic",
                evaluator_note="Compiled from nested sub-support definition.",
            )

            self.nodes_registry[sub_id] = GraphNode(
                id=sub_id,
                type=sub.type,
                title=sub.title,
                section_id=sec_id,
                quote=sub.quote,
                body=nested_body if nested_body else None,
                formula=sub.formula,
                url=sub.url,
                image_url=sub.image_url,
                locator=sub.locator,
                direct_child_ids=deeper_child_ids,
                parent_claim_ids=[root_claim_id],
                audit=node_audit,
            )

            updated_body = re.sub(
                rf"<ref\s+n=['\"]{sub.n}['\"]>(.*?)</ref>",
                lambda m, sid=sub_id: f"<ref id='{sid}'>{m.group(1)}</ref>",
                updated_body,
                flags=re.DOTALL,
            )

        return updated_body, sub_child_ids

    def compile_sections(
        self,
        sections: List[SectionOutput],
        final_smoothed_text: Optional[str] = None,
        tensions: Optional[List[TensionObject]] = None,
        smoothed_sections: Optional[Dict[str, str]] = None,
    ) -> CompiledBundle:
        """Compiles validated sections into a `CompiledBundle` instance.

        Args:
            sections: Ordered list of `SectionOutput` objects from section workers.
            final_smoothed_text: Optional unified document text if smoothed globally.
            tensions: Optional list of cross-section tension warnings from Step 4.
            smoothed_sections: Optional mapping of `section_id -> smoothed_text`
                preserving individual section boundaries.

        Returns:
            Validated `CompiledBundle` ready for frontend rendering.
        """
        global_ref_map: Dict[Tuple[str, int], str] = {}
        claim_ref_map: Dict[Tuple[str, int], str] = {}

        for sec in sections:
            sec_matches = {
                int(n_str): clause.strip()
                for n_str, clause in self.TAG_PATTERN.findall(sec.text)
            }

            for support_group in sec.supports:
                n = support_group.n
                claim_id = f"claim_{sec.section_id}_{n}"
                global_ref_map[(sec.section_id, n)] = claim_id
                claim_ref_map[(sec.section_id, n)] = claim_id

                clause_text = sec_matches.get(n, "")
                child_node_ids: List[str] = []

                for idx, item in enumerate(support_group.items):
                    child_id = f"{item.type[:3]}_{sec.section_id}_{n}_{idx + 1}"
                    child_node_ids.append(child_id)

                    rewritten_body, sub_child_ids = self._compile_sub_supports(
                        sec_id=sec.section_id,
                        root_claim_id=claim_id,
                        parent_prefix=f"{sec.section_id}_{n}_{idx + 1}",
                        parent_body=item.body or "",
                        sub_supports=item.sub_supports,
                        global_ref_map=global_ref_map,
                    )

                    default_status: AuditStatus = (
                        "assumption" if item.type == "assumption" else "verified"
                    )
                    item_audit = item.audit or NodeAudit(
                        status=default_status,
                        score=0.75 if default_status == "assumption" else 1.0,
                        evaluator_type="deterministic",
                        evaluator_note="Compiled from primary support definition.",
                    )

                    self.nodes_registry[child_id] = GraphNode(
                        id=child_id,
                        type=item.type,
                        title=item.title,
                        section_id=sec.section_id,
                        quote=item.quote,
                        body=rewritten_body if rewritten_body else None,
                        formula=item.formula,
                        url=item.url,
                        image_url=item.image_url,
                        locator=item.locator,
                        direct_child_ids=sub_child_ids,
                        parent_claim_ids=[claim_id],
                        audit=item_audit,
                    )

                # Determine claim audit status based on explicit group audit or child types
                has_assumption = any(i.type == "assumption" for i in support_group.items)
                has_extrapolation = any(
                    i.audit is not None and i.audit.status == "extrapolation"
                    for i in support_group.items
                )
                default_claim_status: AuditStatus = (
                    "assumption"
                    if has_assumption
                    else "extrapolation"
                    if has_extrapolation
                    else "verified"
                )
                claim_audit = support_group.audit or NodeAudit(
                    status=default_claim_status,
                    score=(
                        0.75
                        if default_claim_status == "assumption"
                        else 0.80
                        if default_claim_status == "extrapolation"
                        else 0.98
                    ),
                    evaluator_type="deterministic",
                    evaluator_note="Verified across attached local support nodes.",
                )

                claim_title = support_group.title or (
                    clause_text[:48] + ("..." if len(clause_text) > 48 else "")
                )

                self.nodes_registry[claim_id] = GraphNode(
                    id=claim_id,
                    type="claim",
                    title=claim_title,
                    section_id=sec.section_id,
                    clause_text=clause_text,
                    direct_child_ids=child_node_ids,
                    parent_claim_ids=[],
                    audit=claim_audit,
                )

        # Rewrite inline text tags from `<ref n="...">` to `<ref id="global_id">`
        if final_smoothed_text and not smoothed_sections:
            compiled_text = final_smoothed_text
            # First pass: replace section-namespaced tags `<ref n='sec_id:n'>`
            for (s_id, n), global_id in claim_ref_map.items():
                compiled_text = re.sub(
                    rf"<ref\s+n=['\"]{re.escape(s_id)}:{n}['\"]>(.*?)</ref>",
                    lambda m, gid=global_id: f"<ref id='{gid}'>{m.group(1)}</ref>",
                    compiled_text,
                    flags=re.DOTALL,
                )
            # Second pass: fallback for legacy un-namespaced `<ref n='n'>`
            for (_s_id, n), global_id in claim_ref_map.items():
                compiled_text = re.sub(
                    rf"<ref\s+n=['\"]{n}['\"]>(.*?)</ref>",
                    lambda m, gid=global_id: f"<ref id='{gid}'>{m.group(1)}</ref>",
                    compiled_text,
                    flags=re.DOTALL,
                )
            self.sections_payload.append(
                SectionObject(
                    section_id="unified_document",
                    section_title="Unified Document",
                    order=1,
                    content=compiled_text,
                )
            )
        else:
            for order_idx, sec in enumerate(sections, start=1):
                raw_sec_text = (
                    smoothed_sections.get(sec.section_id, sec.text)
                    if smoothed_sections
                    else sec.text
                )
                compiled_sec_text = self._rewrite_section_tags(
                    raw_sec_text, sec.section_id, claim_ref_map
                )
                self.sections_payload.append(
                    SectionObject(
                        section_id=sec.section_id,
                        section_title=sec.section_title
                        or sec.section_id.replace("_", " ").title(),
                        order=order_idx,
                        content=compiled_sec_text,
                    )
                )

        # Compute holistic audit summary counts across all claim nodes
        claim_nodes = [
            node for node in self.nodes_registry.values() if node.type == "claim"
        ]
        verified_count = sum(
            1 for c in claim_nodes if c.audit.status == "verified"
        )
        extrapolation_count = sum(
            1 for c in claim_nodes if c.audit.status == "extrapolation"
        )
        assumption_count = sum(
            1 for c in claim_nodes if c.audit.status == "assumption"
        )

        return CompiledBundle(
            artifact=ArtifactEnvelope(
                title=self.document_title,
                summary=self.summary,
                metadata=self.metadata,
                sections=self.sections_payload,
            ),
            audit_summary=AuditSummary(
                total_claims=len(claim_nodes),
                verified_count=verified_count,
                extrapolation_count=extrapolation_count,
                assumption_count=assumption_count,
                cross_section_tensions=tensions or [],
            ),
            nodes=self.nodes_registry,
        )
