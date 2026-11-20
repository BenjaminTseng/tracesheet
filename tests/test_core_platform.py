# Run: uv run pytest tests/test_core_platform.py -v
"""Unit tests for the domain-agnostic platform core (`app/core/`)."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import List

import pymupdf
import pytest
from pydantic import BaseModel, Field

from app.core.bundle import SourceLocator, TensionObject
from app.core.compiler import AppDescriptor, CompilerApp
from app.core.gate import GatePolicy, ReadinessGate, SignOffGate
from app.core.ingest import MatterIngestor
from app.core.pdf_forms import AcroFormEngine
from app.core.provenance import (
    CaseSummaryRow,
    EmergingQuestionItem,
    ProvenanceField,
    VerifiedLedgerSnapshot,
)
from app.core.tables import ReferenceTableRegistry
from app.core.verifier import IndexedMatterCorpus, ObservationVerifier
from app.core.workspace import MatterWorkspace


class SupportCaseModel(BaseModel):
    """Non-bankruptcy test model proving `ObservationVerifier.verify_model` generality."""

    case_id: str
    customer_tier: ProvenanceField[str]
    refund_amount: ProvenanceField[Decimal]
    last_event_summary: ProvenanceField[str]


def test_matter_workspace_ledgers_events_and_incremental_ingest(tmp_path: Path) -> None:
    """Tests MatterWorkspace ledger SHA-256 integrity, event append, and incremental ingest."""
    matters_root = tmp_path / "matters"
    ws = MatterWorkspace(matters_root, "support_101")
    ws.ensure_dirs()

    # 1. Raw markdown doc + raw JSON API payload + event stream
    (ws.raw_dir / "policy_notes.md").write_text(
        "Enterprise SLA guarantees 99.95% uptime and $250 service credit.", encoding="utf-8"
    )
    (ws.raw_dir / "stripe_charge.json").write_text(
        json.dumps({"charge": {"id": "ch_99", "amount_usd": "250.00", "tier": "enterprise"}}),
        encoding="utf-8",
    )
    ws.append_event("ticket_thread", {"actor": "customer", "note": "Outage lasted 4 hours"})

    # 2. Sibling ledger snapshot written by another compiler
    snap = VerifiedLedgerSnapshot(
        matter_id="support_101",
        app_id="billing",
        readiness_status="READY",
        facts={"eligible_credit_usd": "250.00", "sla_breach": True},
        line_items=[{"code": "SLA_4H", "amount": "250.00"}],
    )
    ledger_path = ws.write_ledger("billing", snap)
    assert ledger_path.exists()
    loaded = ws.read_ledger("billing", verify_hash=True)
    assert loaded is not None and loaded.sha256 == snap.compute_sha256()

    # Tampering fails hash verification
    tampered = json.loads(ledger_path.read_text(encoding="utf-8"))
    tampered["facts"]["eligible_credit_usd"] = "999.00"
    ledger_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="Ledger integrity mismatch"):
        ws.read_ledger("billing", verify_hash=True)
    # Restore valid snapshot before ingestion
    ws.write_ledger("billing", snap)

    # 3. Initial ingestion indexes raw files + ledgers
    ingestor = MatterIngestor(matters_root)
    manifest1 = ingestor.ingest_matter("support_101", incremental=False)
    assert manifest1["files_processed"] == 3
    assert len(manifest1["ledgers"]) == 1
    assert manifest1["ledgers"][0]["app_id"] == "billing"
    assert (ws.indexed_dir / "ledger__billing.indexed.md").exists()

    # 4. Append second event and run incremental=True ingest
    ws.append_event("ticket_thread", {"actor": "agent", "note": "Approved $250.00 SLA credit"})
    manifest2 = ingestor.ingest_matter("support_101", incremental=True)
    assert manifest2["files_processed"] == 3
    corpus = IndexedMatterCorpus.load_for_matter(ingestor, "support_101")
    assert any(loc.source_type == "calculation_ledger" for loc, _ in corpus.blocks_by_key.values())
    assert any(
        loc.source_type == "event_log" and "Approved $250.00 SLA credit" in txt
        for loc, txt in corpus.blocks_by_key.values()
    )

    # 5. Compiler state roundtrip
    ws.save_compiler_state("support", {"queue_status": "triaged"})
    assert ws.load_compiler_state("support") == {"queue_status": "triaged"}


def test_observation_verifier_json_path_and_non_bankruptcy_model(tmp_path: Path) -> None:
    """Verifies `ObservationVerifier.verify_model` and `json_path` checks on a generic model."""
    matters_root = tmp_path / "matters"
    ws = MatterWorkspace(matters_root, "case_json")
    ws.ensure_dirs()
    (ws.raw_dir / "crm.json").write_text(
        json.dumps({"account": {"tier": "Enterprise Plus", "credit_usd": 425.50}}),
        encoding="utf-8",
    )
    ws.append_event("stream", {"event_id": "evt_custom", "note": "Escalated outage ticket"})

    ingestor = MatterIngestor(matters_root)
    ingestor.ingest_matter("case_json")

    model = SupportCaseModel(
        case_id="case_json",
        customer_tier=ProvenanceField[str](
            value="Enterprise Plus",
            locators=[
                SourceLocator(
                    source_type="api",
                    file_name="crm.json",
                    json_path="$.account.tier",
                )
            ],
            verbatim_quotes=["Enterprise Plus"],
        ),
        refund_amount=ProvenanceField[Decimal](
            value=Decimal("425.50"),
            locators=[
                SourceLocator(
                    source_type="api",
                    file_name="crm.json",
                    json_path="account.credit_usd",
                )
            ],
            verbatim_quotes=["425.5"],
        ),
        last_event_summary=ProvenanceField[str](
            value="Wrong fabricated event",
            locators=[
                SourceLocator(
                    source_type="event_log",
                    file_name="stream.events.json",
                    json_path="events[0].note",
                )
            ],
            verbatim_quotes=["Wrong fabricated event"],
        ),
    )

    verified = ObservationVerifier().verify_model(model, "case_json", ingestor)
    assert verified.customer_tier.verification_status == "verified"
    assert verified.refund_amount.verification_status == "verified"
    assert verified.last_event_summary.verification_status == "unverified"


def test_readiness_gate_policies_and_signoff_gate(tmp_path: Path) -> None:
    """Tests strict_blocking vs advisory_coverage vs safety_blocking and HMAC SignOffGate."""
    q_crit = EmergingQuestionItem(
        question_id="q_1",
        rule_id="ALLERGY_CHECK",
        severity="critical",
        prompt="Missing patient allergy confirmation.",
    )
    t_block = TensionObject(
        tension_id="t_1",
        involved_claim_ids=["c_1"],
        severity="blocker",
        description="Dosage exceeds protocol.",
    )

    strict = ReadinessGate(GatePolicy.strict_blocking()).evaluate(
        unverified_fields=["dose (unverified)"],
        open_questions=[q_crit],
        tensions=[t_block],
        stale_warnings=["Table expired."],
    )
    assert strict.status == "BLOCKED"
    assert len(strict.blocking_reasons) == 4

    advisory = ReadinessGate(GatePolicy.advisory_coverage()).evaluate(
        unverified_fields=["dose (unverified)"],
        open_questions=[q_crit],
        tensions=[t_block],
        stale_warnings=["Table expired."],
    )
    assert advisory.status == "READY_WITH_ADVISORIES"
    assert advisory.blocking_reasons == []
    assert len(advisory.advisory_warnings) == 4

    safety = ReadinessGate(GatePolicy.safety_blocking()).evaluate(
        unverified_fields=["soft_note (unverified)"],
        open_questions=[],
        tensions=[],
    )
    assert safety.status == "READY_WITH_ADVISORIES"
    assert len(safety.advisory_warnings) == 1

    # SignOffGate test
    out_file = tmp_path / "brief.pdf"
    out_file.write_bytes(b"PDF-BYTES-1")
    signoff = SignOffGate(signing_secret="test-secret")
    with pytest.raises(PermissionError, match="attestation"):
        signoff.mint("m1", [out_file], "Dr. Patel", "clinician", "MD-4421", attested=False)

    token = signoff.mint("m1", [out_file], "Dr. Patel", "clinician", "MD-4421", attested=True)
    assert signoff.verify(token, "m1", [out_file]) is True
    out_file.write_bytes(b"TAMPERED")
    assert signoff.verify(token, "m1", [out_file]) is False


def test_reference_table_registry_custom_domain_and_protocols(tmp_path: Path) -> None:
    """Tests domain-agnostic ReferenceTableRegistry and CaseSummaryRow/AppDescriptor contracts."""
    tables_dir = tmp_path / "canonical" / "tables" / "support"
    tables_dir.mkdir(parents=True)
    (tables_dir / "sla_2026.json").write_text(
        json.dumps(
            {
                "table_id": "support_sla_2026",
                "stale_after": "2026-12-31",
                "effective_periods": [
                    {"effective_from": "2026-01-01", "response_hours": 4, "max_credit": 500}
                ],
            }
        ),
        encoding="utf-8",
    )

    reg = ReferenceTableRegistry(tables_dir)
    synced = reg.sync_tables(reference_date=datetime.date(2026, 6, 1))
    assert len(synced["tables_verified"]) == 1
    assert synced["stale_warnings"] == []
    period = reg.select_effective_period("sla_2026.json", datetime.date(2026, 6, 1))
    assert period["response_hours"] == 4
    assert reg.check_staleness(datetime.date(2027, 2, 1))

    desc = AppDescriptor(
        app_id="support",
        label="Support Triage",
        description="Customer SLA refund & policy compiler",
        ui_route="/support",
        api_prefix="/api/v1/support",
        gate_mode="safety_blocking",
    )
    row = CaseSummaryRow(
        matter_id="support_101",
        app_id="support",
        title="Outage Credit Request",
        status="READY",
        metrics={"credit": "$250.00"},
    )
    assert desc.app_id == row.app_id
    assert hasattr(CompilerApp, "build_router")


def test_acroform_engine_standalone_bake_overflow_and_lineage(tmp_path: Path) -> None:
    """Verifies `AcroFormEngine` handles generic non-bankruptcy templates, baking, overflow, and lineage."""
    templates_dir = tmp_path / "templates"
    output_dir = tmp_path / "out"
    engine = AcroFormEngine(templates_dir=templates_dir)

    pdfs, lineage_path, entries = engine.compile_packet(
        specs=[
            {
                "form_id": "PRIOR_AUTH_REQ",
                "output_filename": "Prior_Auth_Request.pdf",
                "fallback_title": "Medical Prior Authorization Request",
                "fallback_fields": ["Patient_Name", "Member_ID", "CPT_Code"],
                "bindings": {
                    "Patient_Name": ("Jane Doe", "direct_provenance", "$.patient.name", None, [], None),
                    "Member_ID": ("MEM-90125", "direct_provenance", "$.patient.member_id", None, [], None),
                    "CPT_Code": ("99214", "deterministic_calculation", "$.coding.primary_cpt", "=LOOKUP(CPT)", [], None),
                },
                "overflow_lines": [f"Supporting Lab Observation #{i}" for i in range(1, 5)],
            }
        ],
        output_dir=output_dir,
        watermark_draft=True,
    )

    assert len(pdfs) == 1
    assert pdfs[0].name == "Prior_Auth_Request.pdf"
    assert lineage_path.exists()
    assert len(entries) == 3

    with pymupdf.open(str(pdfs[0])) as doc:
        assert len(doc) == 2
        assert all(list(page.widgets() or []) == [] for page in doc)
        combined = "\n".join(page.get_text() for page in doc)
        assert "Jane Doe" in combined
        assert "99214" in combined
        assert "Supporting Lab Observation #4" in combined
        assert "DRAFT ONLY" in combined

