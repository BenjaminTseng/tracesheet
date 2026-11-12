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
from pydantic import BaseModel, Field


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
        text: Markdown narrative containing `<ref n="X">clause</ref>` tags.
        supports: List of support clusters corresponding to each inline `<ref>`.
    """

    section_id: str
    section_title: Optional[str] = None
    text: str
    supports: List[SupportGroup]


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
    """Represents a cross-section contradiction or tension flagged by the global audit.

    Attributes:
        tension_id: Unique identifier for the tension warning.
        involved_claim_ids: Claim node IDs whose assertions are in tension.
        severity: Either `warning` (nuance/scope friction) or `blocker` (contradiction).
        description: Plain-English explanation of the discrepancy.
    """

    tension_id: str
    involved_claim_ids: List[str]
    severity: Literal["warning", "blocker"] = "warning"
    description: str


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


class CompiledBundle(BaseModel):
    """Complete compiled payload consumed by the bounded spatial canvas UI.

    Attributes:
        bundle_id: Optional slug identifying the bundle in the viewer library.
        artifact: Document envelope containing metadata and ordered sections.
        audit_summary: Document-wide audit counts and tension alerts.
        nodes: Flat lookup dictionary mapping `node_id` to `GraphNode`.
    """

    bundle_id: Optional[str] = None
    artifact: ArtifactEnvelope
    audit_summary: AuditSummary
    nodes: Dict[str, GraphNode]


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

        # Recursively check nested sub-references inside reasoning/calculation bodies
        for group in section.supports:
            for item in group.items:
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

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

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

        pre_dict: Dict[int, str] = {int(n): text.strip() for n, text in pre_matches}
        post_dict: Dict[int, str] = {int(n): text.strip() for n, text in post_matches}

        pre_ids = set(pre_dict.keys())
        post_ids = set(post_dict.keys())

        missing = pre_ids - post_ids
        if missing:
            violations.append(
                f"Editorial pass removed citations with n={sorted(list(missing))}"
            )

        added = post_ids - pre_ids
        if added:
            violations.append(
                f"Editorial pass invented ungrounded citations with n={sorted(list(added))}"
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
                rf"<ref id='{sub_id}'>\1</ref>",
                updated_body,
            )

        return updated_body, sub_child_ids

    def compile_sections(
        self,
        sections: List[SectionOutput],
        final_smoothed_text: Optional[str] = None,
        tensions: Optional[List[TensionObject]] = None,
    ) -> CompiledBundle:
        """Compiles validated sections into a `CompiledBundle` instance.

        Args:
            sections: Ordered list of `SectionOutput` objects from section workers.
            final_smoothed_text: Optional unified document text if smoothed globally.
            tensions: Optional list of cross-section tension warnings from Step 4.

        Returns:
            Validated `CompiledBundle` ready for frontend rendering.
        """
        global_ref_map: Dict[Tuple[str, int], str] = {}

        for sec in sections:
            sec_matches = {
                int(n_str): clause.strip()
                for n_str, clause in self.TAG_PATTERN.findall(sec.text)
            }

            for support_group in sec.supports:
                n = support_group.n
                claim_id = f"claim_{sec.section_id}_{n}"
                global_ref_map[(sec.section_id, n)] = claim_id

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
                claim_audit = support_group.audit or NodeAudit(
                    status="assumption" if has_assumption else "verified",
                    score=0.75 if has_assumption else 0.98,
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

        # Rewrite inline text tags from `<ref n="X">` to `<ref id="global_id">`
        if final_smoothed_text:
            compiled_text = final_smoothed_text
            for (_sec_id, n), global_id in global_ref_map.items():
                compiled_text = re.sub(
                    rf"<ref\s+n=['\"]{n}['\"]>(.*?)</ref>",
                    rf"<ref id='{global_id}'>\1</ref>",
                    compiled_text,
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
                compiled_sec_text = sec.text
                for (s_id, n), global_id in global_ref_map.items():
                    if s_id == sec.section_id:
                        compiled_sec_text = re.sub(
                            rf"<ref\s+n=['\"]{n}['\"]>(.*?)</ref>",
                            rf"<ref id='{global_id}'>\1</ref>",
                            compiled_sec_text,
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
