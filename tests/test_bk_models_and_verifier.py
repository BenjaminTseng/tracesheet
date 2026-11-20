# Run: uv run pytest tests/test_bk_models_and_verifier.py -v
"""Adversarial tests for ProvenanceField invariants and ObservationVerifier."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError

from app.compilers.bankruptcy.schema import (
    AssetItem,
    CanonicalCaseGraph,
    HumanOverrideRecord,
    PartyEntity,
    PaystubRecord,
    ProvenanceField,
)
from app.core.bundle import SourceLocator
from app.core.ingest import MatterIngestor
from app.core.verifier import IndexedMatterCorpus, ObservationVerifier


def _write_paystub_pdf(path: Path, text: str) -> None:
    """Creates a clean PDF with selectable text at fixed coordinates."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 120), text, fontsize=11)
    doc.save(str(path))
    doc.close()


def test_provenance_field_requires_override_record_for_human_overridden() -> None:
    """Rejects `human_overridden` without an explicit `HumanOverrideRecord`."""
    with pytest.raises(ValidationError):
        ProvenanceField[Decimal](
            value=Decimal("1500.00"),
            verification_status="human_overridden",
            override=None,
        )

    valid = ProvenanceField[Decimal](
        value=Decimal("1500.00"),
        verification_status="human_overridden",
        override=HumanOverrideRecord(
            actor_name="Jane Paralegal",
            actor_role="paralegal",
            rationale="Confirmed balance from client phone log.",
        ),
    )
    assert valid.verification_status == "human_overridden"


def test_observation_verifier_catches_digit_swap_and_hash_tamper(tmp_path: Path) -> None:
    """Verifies ObservationVerifier rejects swapped digits, bad locators, and stale file hashes."""
    ingestor = MatterIngestor(tmp_path / "matters")
    matter_dir = ingestor.create_matter("bk_verify")
    pdf_path = matter_dir / "inputs" / "raw" / "adp_may_2026.pdf"
    _write_paystub_pdf(
        pdf_path,
        "ADP Earnings Statement\nGross Pay: $4,850.00 Net Pay: $3,610.00\nFederal Tax: $720.00",
    )
    ingestor.ingest_matter("bk_verify")

    corpus = IndexedMatterCorpus.load_for_matter(ingestor, "bk_verify")
    assert len(corpus.blocks_by_key) >= 1
    (fname, lkey), (stored_loc, stored_text) = next(iter(corpus.blocks_by_key.items()))

    verifier = ObservationVerifier()

    # 1. Exact valid extraction passes deterministically.
    good_field = ProvenanceField[Decimal](
        value=Decimal("4850.00"),
        locators=[stored_loc],
        verbatim_quotes=["Gross Pay: $4,850.00 Net Pay: $3,610.00"],
    )
    assert verifier.verify_field(good_field, corpus).verification_status == "verified"

    # 2. Digit swap hallucination ($4,850.00 -> $4,580.00) while citing valid locator MUST fail.
    swapped_field = ProvenanceField[Decimal](
        value=Decimal("4580.00"),
        locators=[stored_loc],
        verbatim_quotes=["Gross Pay: $4,850.00 Net Pay: $3,610.00"],
    )
    assert verifier.verify_field(swapped_field, corpus).verification_status == "unverified"

    # 3. Fabricated locator_key MUST fail.
    bad_key_loc = stored_loc.model_copy(update={"locator_key": "ADP_MAY_2026-P99-B9"})
    bad_loc_field = ProvenanceField[Decimal](
        value=Decimal("4850.00"),
        locators=[bad_key_loc],
        verbatim_quotes=["Gross Pay: $4,850.00"],
    )
    assert verifier.verify_field(bad_loc_field, corpus).verification_status == "unverified"

    # 4. Quote not present inside the indexed block MUST fail.
    bad_quote_field = ProvenanceField[Decimal](
        value=Decimal("4850.00"),
        locators=[stored_loc],
        verbatim_quotes=["Bonus Pay: $4,850.00"],
    )
    assert verifier.verify_field(bad_quote_field, corpus).verification_status == "unverified"

    # 5. Tampered payload_hash MUST fail.
    stale_loc = stored_loc.model_copy(update={"payload_hash": "sha256:stale0000000000"})
    stale_field = ProvenanceField[Decimal](
        value=Decimal("4850.00"),
        locators=[stale_loc],
        verbatim_quotes=["Gross Pay: $4,850.00"],
    )
    assert verifier.verify_field(stale_field, corpus).verification_status == "unverified"

    # 6. Full CaseGraph walk verifies valid fields and leaves human_overridden intact.
    graph = CanonicalCaseGraph(
        matter_id="bk_verify",
        parties=[
            PartyEntity(
                party_id="debtor_1",
                role="debtor_1",
                full_name=ProvenanceField[str](
                    value="Elena Martinez",
                    verification_status="human_overridden",
                    override=HumanOverrideRecord(
                        actor_name="Ben Paralegal",
                        actor_role="paralegal",
                        rationale="Verified against driver license.",
                    ),
                ),
                ca_domicile_days_continuous=ProvenanceField[int](
                    value=1200,
                    verification_status="human_overridden",
                    override=HumanOverrideRecord(
                        actor_name="Ben Paralegal",
                        actor_role="paralegal",
                        rationale="Lived in LA since 2020.",
                    ),
                ),
                household_size=ProvenanceField[int](
                    value=1,
                    verification_status="human_overridden",
                    override=HumanOverrideRecord(
                        actor_name="Ben Paralegal",
                        actor_role="paralegal",
                        rationale="Single filer.",
                    ),
                ),
            )
        ],
        assets=[
            AssetItem(
                asset_id="asset_1",
                category="bank_account",
                description="Checking",
                current_value=swapped_field,
            )
        ],
        paystubs=[
            PaystubRecord(
                paystub_id="ps_1",
                employer="Acme",
                pay_period_start=datetime.date(2026, 5, 1),
                pay_period_end=datetime.date(2026, 5, 15),
                pay_date=datetime.date(2026, 5, 15),
                gross_pay=good_field,
                net_pay=ProvenanceField[Decimal](
                    value=Decimal("3610.00"),
                    locators=[stored_loc],
                    verbatim_quotes=["Net Pay: $3,610.00"],
                ),
                tax_withheld=ProvenanceField[Decimal](
                    value=Decimal("720.00"),
                    locators=[stored_loc],
                    verbatim_quotes=["Federal Tax: $720.00"],
                ),
            )
        ],
    )
    verified_graph = verifier.verify_case_graph(graph, ingestor)
    assert verified_graph.parties[0].full_name.verification_status == "human_overridden"
    assert verified_graph.assets[0].current_value.verification_status == "unverified"
    assert verified_graph.paystubs[0].gross_pay.verification_status == "verified"
    assert verified_graph.paystubs[0].net_pay.verification_status == "verified"
    assert verified_graph.paystubs[0].tax_withheld.verification_status == "verified"
