"""Configurable readiness gates and generic human sign-off attestation."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import os
from pathlib import Path
from typing import Any, List, Literal, Optional, Set

from pydantic import BaseModel, Field

from app.core.bundle import TensionObject
from app.core.provenance import EmergingQuestionItem, ProvenanceField, ReadinessReport


class GatePolicy(BaseModel):
    """Policy controlling which provenance gaps block vs. warn at readiness evaluation."""

    mode: Literal["strict_blocking", "advisory_coverage", "safety_blocking"] = "strict_blocking"
    block_on_unverified: bool = True
    block_on_critical_questions: bool = True
    block_on_blocker_tensions: bool = True
    enforce_table_staleness: bool = True

    @classmethod
    def strict_blocking(cls) -> "GatePolicy":
        """Zero-doubt policy used by statutory filings such as bankruptcy petitions."""
        return cls(
            mode="strict_blocking",
            block_on_unverified=True,
            block_on_critical_questions=True,
            block_on_blocker_tensions=True,
            enforce_table_staleness=True,
        )

    @classmethod
    def advisory_coverage(cls) -> "GatePolicy":
        """Research/brief policy that surfaces contradictions and gaps without blocking output."""
        return cls(
            mode="advisory_coverage",
            block_on_unverified=False,
            block_on_critical_questions=False,
            block_on_blocker_tensions=False,
            enforce_table_staleness=False,
        )

    @classmethod
    def safety_blocking(cls) -> "GatePolicy":
        """Hybrid policy blocking critical safety questions/contradictions while advising on soft fields."""
        return cls(
            mode="safety_blocking",
            block_on_unverified=False,
            block_on_critical_questions=True,
            block_on_blocker_tensions=True,
            enforce_table_staleness=True,
        )


class ReadinessGate:
    """Evaluates provenance completeness, open questions, and tensions against a `GatePolicy`."""

    def __init__(self, policy: Optional[GatePolicy] = None) -> None:
        """Initializes the readiness gate with a configurable `GatePolicy`."""
        self.policy = policy or GatePolicy.strict_blocking()

    @staticmethod
    def find_unverified_field_paths(obj: BaseModel) -> List[str]:
        """Recursively locates all `ProvenanceField` paths lacking verified or overridden status."""
        unverified: List[str] = []

        def _walk(item: Any, prefix: str) -> None:
            if isinstance(item, ProvenanceField):
                if item.verification_status not in ("verified", "human_overridden"):
                    unverified.append(f"{prefix} ({item.verification_status})")
                return
            if isinstance(item, list):
                for idx, elem in enumerate(item):
                    _walk(elem, f"{prefix}[{idx}]")
                return
            if isinstance(item, dict):
                for k, v in item.items():
                    _walk(v, f"{prefix}.{k}" if prefix else str(k))
                return
            if isinstance(item, BaseModel):
                for fname in type(item).model_fields:
                    val = getattr(item, fname)
                    if val is not None:
                        next_prefix = f"{prefix}.{fname}" if prefix else fname
                        _walk(val, next_prefix)

        _walk(obj, "")
        return sorted(unverified)

    def evaluate(
        self,
        unverified_fields: List[str],
        open_questions: List[EmergingQuestionItem],
        tensions: List[TensionObject],
        resolved_tension_ids: Optional[Set[str]] = None,
        stale_warnings: Optional[List[str]] = None,
        extra_errors: Optional[List[str]] = None,
        required_artifacts: Optional[List[str]] = None,
    ) -> ReadinessReport:
        """Evaluates blocking and advisory conditions under `self.policy`."""
        resolved_ids = resolved_tension_ids or set()
        open_critical_qs = [
            f"{q.question_id}: {q.prompt}"
            for q in open_questions
            if q.severity == "critical" and q.status != "answered"
        ]
        unresolved_blockers = [
            f"{t.tension_id}: {t.description}"
            for t in tensions
            if t.severity == "blocker" and t.tension_id not in resolved_ids
        ]
        pkt_errors = list(extra_errors or [])
        stale_list = list(stale_warnings or [])

        blocking_reasons: List[str] = []
        advisory_warnings: List[str] = []

        def _record(msg: str, is_blocking: bool) -> None:
            if is_blocking:
                blocking_reasons.append(msg)
            else:
                advisory_warnings.append(msg)

        if unverified_fields:
            _record(
                f"{len(unverified_fields)} unverified/contradicted field(s) lack provenance or human override.",
                self.policy.block_on_unverified,
            )
        if open_critical_qs:
            _record(
                f"{len(open_critical_qs)} critical emerging/completeness question(s) remain open.",
                self.policy.block_on_critical_questions,
            )
        if unresolved_blockers:
            _record(
                f"{len(unresolved_blockers)} critical contradiction(s) remain unresolved.",
                self.policy.block_on_blocker_tensions,
            )
        if pkt_errors:
            _record(
                f"{len(pkt_errors)} output/packet validation error(s) detected.",
                self.policy.mode != "advisory_coverage",
            )
        for sw in stale_list:
            _record(sw, self.policy.enforce_table_staleness)

        if blocking_reasons:
            status: Literal["READY", "READY_WITH_ADVISORIES", "BLOCKED"] = "BLOCKED"
        elif advisory_warnings:
            status = "READY_WITH_ADVISORIES"
        else:
            status = "READY"

        return ReadinessReport(
            status=status,
            unverified_field_paths=list(unverified_fields),
            unresolved_critical_questions=open_critical_qs,
            unresolved_critical_tensions=unresolved_blockers,
            packet_validation_errors=pkt_errors,
            required_forms=list(required_artifacts or []),
            blocking_reasons=blocking_reasons,
            advisory_warnings=advisory_warnings,
        )


class SignOffToken(BaseModel):
    """Generic cryptographic attestation minted when an authorized reviewer signs off."""

    matter_id: str
    actor_name: str
    actor_role: str
    actor_credential_id: str
    artifact_sha256: str
    declaration_sha256: str = ""
    attested: bool = True
    signed_at: str
    token_digest: str


class SignOffGate:
    """Mints and verifies HMAC-SHA256 human sign-off tokens over artifact hashes."""

    def __init__(self, signing_secret: Optional[str] = None) -> None:
        """Initializes the sign-off gate with an HMAC secret."""
        self._secret = (
            signing_secret or os.getenv("JD_SCREEN_RULE9011_SECRET", "jd-screen-rule9011-secret")
        ).encode("utf-8")

    @staticmethod
    def compute_files_hash(files: List[Path]) -> str:
        """Computes a deterministic SHA-256 digest across sorted artifact files."""
        h = hashlib.sha256()
        for p in sorted(files, key=lambda item: item.name):
            h.update(p.name.encode("utf-8"))
            h.update(p.read_bytes())
        return f"sha256:{h.hexdigest()}"

    def mint(
        self,
        matter_id: str,
        artifact_files: List[Path],
        actor_name: str,
        actor_role: str,
        actor_credential_id: str,
        attested: bool,
        declaration_sha256: str = "",
        readiness_status: str = "READY",
        allow_advisory: bool = False,
    ) -> SignOffToken:
        """Mints a signed attestation token after verifying readiness and credentials."""
        if not attested:
            raise PermissionError("Explicit human attestation is required before sign-off.")
        allowed = {"READY", "READY_WITH_ADVISORIES"} if allow_advisory else {"READY"}
        if readiness_status not in allowed:
            raise PermissionError(
                f"Cannot mint sign-off token while ReadinessGate status is {readiness_status}."
            )
        if not actor_name.strip() or not actor_credential_id.strip():
            raise PermissionError("Reviewer name and credential/bar identifier are required.")

        artifact_sha256 = self.compute_files_hash(artifact_files)
        signed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = (
            f"{matter_id}|{actor_name.strip()}|{actor_role.strip()}|{actor_credential_id.strip()}|"
            f"{declaration_sha256}|{artifact_sha256}|{signed_at}"
        )
        sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return SignOffToken(
            matter_id=matter_id,
            actor_name=actor_name.strip(),
            actor_role=actor_role.strip(),
            actor_credential_id=actor_credential_id.strip(),
            artifact_sha256=artifact_sha256,
            declaration_sha256=declaration_sha256,
            attested=True,
            signed_at=signed_at,
            token_digest=sig,
        )

    def verify(
        self,
        token: SignOffToken,
        matter_id: str,
        artifact_files: List[Path],
        expected_declaration_sha256: str = "",
    ) -> bool:
        """Verifies HMAC signature and confirms artifact bytes have not drifted."""
        if token.matter_id != matter_id:
            return False
        if expected_declaration_sha256 and token.declaration_sha256 != expected_declaration_sha256:
            return False
        if token.artifact_sha256 != self.compute_files_hash(artifact_files):
            return False
        payload = (
            f"{token.matter_id}|{token.actor_name}|{token.actor_role}|{token.actor_credential_id}|"
            f"{token.declaration_sha256}|{token.artifact_sha256}|{token.signed_at}"
        )
        expected = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, token.token_digest)
