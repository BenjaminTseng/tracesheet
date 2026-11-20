"""Domain-agnostic provenance, readiness, ledger, and case-summary contracts."""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.core.bundle import SourceLocator


T = TypeVar("T")

VerificationStatus = Literal["verified", "human_overridden", "unverified", "contradicted"]


class HumanOverrideRecord(BaseModel):
    """Audited human attestation or override attached to a `ProvenanceField`.

    Attributes:
        actor_name: Full name of the human operator approving or overriding a value.
        actor_role: Role performing the override (e.g., `"paralegal"`, `"attorney"`,
            `"clinician"`, `"recruiter"`, `"reviewer"`).
        rationale: Substantive explanation justifying the value or confirmation.
        supporting_locator: Optional client source coordinate backing the override.
        overridden_at: ISO-8601 UTC timestamp when recorded.
    """

    actor_name: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    rationale: str = Field(min_length=5)
    supporting_locator: Optional[SourceLocator] = None
    overridden_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class ProvenanceField(BaseModel, Generic[T]):
    """Wraps a typed domain value with mandatory coordinate and audit provenance.

    Attributes:
        value: Typed primitive value (`Decimal`, `str`, `int`, `datetime.date`, etc.).
        verification_status: Current deterministic verification state.
        locators: Non-empty coordinate references for AI-extracted observations.
        verbatim_quotes: Exact source text snippets grounding `value`.
        override: Mandatory audit record whenever `verification_status == "human_overridden"`.
    """

    value: T
    verification_status: VerificationStatus = "unverified"
    locators: List[SourceLocator] = Field(default_factory=list)
    verbatim_quotes: List[str] = Field(default_factory=list)
    override: Optional[HumanOverrideRecord] = None

    @model_validator(mode="after")
    def _enforce_override_invariant(self) -> "ProvenanceField[T]":
        """Ensures `"human_overridden"` fields carry a valid `HumanOverrideRecord`."""
        if self.verification_status == "human_overridden" and self.override is None:
            raise ValueError(
                "ProvenanceField with verification_status='human_overridden' requires a non-null override."
            )
        return self


class EmergingQuestionItem(BaseModel):
    """Relational or completeness gap surfaced by a declarative or semantic auditor.

    Attributes:
        question_id: Unique question ID inside the case.
        rule_id: Rule identifier from a canonical rule catalog.
        severity: `"critical"` (can block delivery) or `"warning"`.
        trigger_forms: Downstream forms, sections, or outputs impacted by this gap.
        prompt: Plain-English question explaining what is missing and why.
        entity_id: Related asset/claim/record identifier if applicable.
        resolution_options: Allowed UI action keys.
        status: `"open"` or `"answered"`.
        selected_option: Action chosen by the reviewer when answered.
        override: Audit trail attached when answered.
    """

    question_id: str
    rule_id: str
    severity: Literal["critical", "warning"] = "critical"
    trigger_forms: List[str] = Field(default_factory=list)
    prompt: str
    entity_id: Optional[str] = None
    resolution_options: List[str] = Field(default_factory=list)
    status: Literal["open", "answered"] = "open"
    selected_option: Optional[str] = None
    override: Optional[HumanOverrideRecord] = None


class FieldLineageEntry(BaseModel):
    """Cryptographic provenance record emitted for every rendered form/output field."""

    form_id: str
    pdf_field_name: str
    form_line_ref: Optional[str] = None
    rendered_value: str
    derivation_type: Literal[
        "direct_provenance",
        "deterministic_calculation",
        "human_override",
        "system_constant",
    ]
    case_graph_path: str
    formula: Optional[str] = None
    source_locators: List[SourceLocator] = Field(default_factory=list)
    human_override: Optional[HumanOverrideRecord] = None


class ReadinessReport(BaseModel):
    """Compiler gate verdict (`READY`, `READY_WITH_ADVISORIES`, or `BLOCKED`)."""

    status: Literal["READY", "READY_WITH_ADVISORIES", "BLOCKED"]
    unverified_field_paths: List[str] = Field(default_factory=list)
    unresolved_critical_questions: List[str] = Field(default_factory=list)
    unresolved_critical_tensions: List[str] = Field(default_factory=list)
    packet_validation_errors: List[str] = Field(default_factory=list)
    required_forms: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    advisory_warnings: List[str] = Field(default_factory=list)


FilingReadinessReport = ReadinessReport


class CaseSummaryRow(BaseModel):
    """Standardized platform case summary supporting selectors and triage queues."""

    matter_id: str
    app_id: str
    title: str
    status: str
    open_blockers: int = 0
    open_advisories: int = 0
    metrics: Dict[str, str] = Field(default_factory=dict)
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class VerifiedLedgerSnapshot(BaseModel):
    """Hashed deterministic calculation summary published for cross-compiler citation."""

    matter_id: str
    app_id: str
    schema_version: str = "1.0"
    generated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    readiness_status: str = "BLOCKED"
    facts: Dict[str, Any] = Field(default_factory=dict)
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    sha256: str = ""

    def compute_sha256(self) -> str:
        """Computes the canonical SHA-256 digest over `facts`, `line_items`, and identity."""
        canonical = json.dumps(
            {
                "matter_id": self.matter_id,
                "app_id": self.app_id,
                "schema_version": self.schema_version,
                "readiness_status": self.readiness_status,
                "facts": self.facts,
                "line_items": self.line_items,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    @model_validator(mode="after")
    def _ensure_digest(self) -> "VerifiedLedgerSnapshot":
        """Populates `sha256` automatically when omitted."""
        if not self.sha256:
            self.sha256 = self.compute_sha256()
        return self
