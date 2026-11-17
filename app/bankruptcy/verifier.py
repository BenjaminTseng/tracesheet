"""Deterministic citation and numeric anchor verifier for bankruptcy observations.

Validates every `ProvenanceField` in a `CanonicalCaseGraph` against the
cryptographic SHA-256 hashes and coordinate-stamped blocks written by
`MatterIngestor` (`*.indexed.md` and `sheets_index.jsonl`), guaranteeing that
hallucinated locators, altered quotes, or misread numbers never enter schedules
as verified facts.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.bankruptcy.models import CanonicalCaseGraph, ProvenanceField
from app.ingest import LOCATOR_COMMENT_RE, MatterIngestor
from app.models import SourceLocator


def _normalize_ws_lower(text: str) -> str:
    """Normalizes whitespace and case for deterministic substring checks."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _digits_and_decimal(value: Any) -> List[str]:
    """Builds canonical numeric string representations to verify literal presence in quotes.

    Args:
        value: Numeric primitive (`Decimal`, `int`, `float`).

    Returns:
        Candidate numeric token strings (with and without commas/trailing zeros).
    """
    if isinstance(value, bool):
        return []
    if isinstance(value, (Decimal, int, float)):
        dec = Decimal(str(value))
        candidates = set()
        plain = format(dec, "f")
        candidates.add(plain)
        # Include formatted with thousands separator (e.g., 4,850.00).
        if "." in plain:
            whole, frac = plain.split(".", 1)
            sign = "-" if whole.startswith("-") else ""
            whole_abs = whole.lstrip("-")
            if whole_abs.isdigit():
                grouped = f"{sign}{int(whole_abs):,}.{frac}"
                candidates.add(grouped)
            if set(frac) == {"0"}:
                candidates.add(f"{sign}{whole_abs}")
                if whole_abs.isdigit():
                    candidates.add(f"{sign}{int(whole_abs):,}")
            else:
                trimmed = plain.rstrip("0").rstrip(".")
                candidates.add(trimmed)
        else:
            sign = "-" if plain.startswith("-") else ""
            whole_abs = plain.lstrip("-")
            if whole_abs.isdigit():
                candidates.add(f"{sign}{int(whole_abs):,}")
                candidates.add(f"{plain}.00")
                candidates.add(f"{sign}{int(whole_abs):,}.00")
        return sorted(candidates, key=len, reverse=True)
    return []


class IndexedMatterCorpus:
    """In-memory lookup index of verified blocks and spreadsheet cells for a matter."""

    def __init__(self) -> None:
        """Initializes empty block and cell maps."""
        self.blocks_by_key: Dict[Tuple[str, str], Tuple[SourceLocator, str]] = {}
        self.cells_by_coord: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    @classmethod
    def load_for_matter(
        cls, ingestor: MatterIngestor, matter_id: str
    ) -> "IndexedMatterCorpus":
        """Loads all `*.indexed.md` blocks and `sheets_index.jsonl` entries for `matter_id`.

        Args:
            ingestor: Active `MatterIngestor` instance.
            matter_id: Matter directory slug.

        Returns:
            Populated `IndexedMatterCorpus`.
        """
        corpus = cls()
        _, _, indexed_dir, _ = ingestor._matter_dirs(matter_id)
        if not indexed_dir.exists():
            return corpus

        for md_path in sorted(indexed_dir.glob("*.indexed.md")):
            current_loc: Optional[SourceLocator] = None
            buf: List[str] = []

            def _flush() -> None:
                if current_loc is not None and current_loc.file_name and current_loc.locator_key:
                    corpus.blocks_by_key[
                        (current_loc.file_name, current_loc.locator_key)
                    ] = (current_loc, "\n".join(buf).strip())

            for line in md_path.read_text(encoding="utf-8").splitlines():
                match = LOCATOR_COMMENT_RE.match(line.strip())
                if match:
                    _flush()
                    current_loc = SourceLocator.model_validate_json(match.group(1))
                    buf = []
                elif current_loc is not None:
                    buf.append(line)
            _flush()

        sheets_path = indexed_dir / "sheets_index.jsonl"
        if sheets_path.exists():
            for raw_line in sheets_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                row = json.loads(raw_line)
                key = (
                    str(row.get("file_name", "")),
                    str(row.get("sheet", "")),
                    str(row.get("cell_range", "")),
                )
                corpus.cells_by_coord[key] = row

        return corpus


class ObservationVerifier:
    """Deterministically validates extracted `ProvenanceField`s against indexed sources."""

    def verify_field(
        self, field: ProvenanceField[Any], corpus: IndexedMatterCorpus
    ) -> ProvenanceField[Any]:
        """Verifies a single `ProvenanceField` against `corpus`.

        Args:
            field: Field containing `value`, `locators`, `verbatim_quotes`, and optional `override`.
            corpus: Loaded `IndexedMatterCorpus` for the matter.

        Returns:
            Updated copy of `field` with deterministic `verification_status`.
        """
        if field.verification_status == "human_overridden" and field.override is not None:
            return field

        if not field.locators or not field.verbatim_quotes:
            return field.model_copy(update={"verification_status": "unverified"})

        verified_locators: List[SourceLocator] = []
        matched_quote_texts: List[str] = []

        for idx, loc in enumerate(field.locators):
            quote = field.verbatim_quotes[idx] if idx < len(field.verbatim_quotes) else field.verbatim_quotes[0]
            norm_quote = _normalize_ws_lower(quote)
            if not norm_quote:
                return field.model_copy(update={"verification_status": "unverified"})

            # Case 1: Block locator inside *.indexed.md (PDF, DOCX, Markdown).
            if loc.file_name and loc.locator_key:
                entry = corpus.blocks_by_key.get((loc.file_name, loc.locator_key))
                if entry is None:
                    return field.model_copy(update={"verification_status": "unverified"})
                stored_loc, stored_text = entry
                if loc.payload_hash and stored_loc.payload_hash != loc.payload_hash:
                    return field.model_copy(update={"verification_status": "unverified"})
                if norm_quote not in _normalize_ws_lower(stored_text):
                    return field.model_copy(update={"verification_status": "unverified"})
                verified_locators.append(stored_loc)
                matched_quote_texts.append(quote)
            # Case 2: Spreadsheet / PDF-table cell locator inside sheets_index.jsonl.
            elif loc.file_name and loc.sheet and loc.cell_range:
                row = corpus.cells_by_coord.get((loc.file_name, loc.sheet, loc.cell_range))
                if row is None:
                    return field.model_copy(update={"verification_status": "unverified"})
                stored_loc = SourceLocator.model_validate(row["locator"])
                if loc.payload_hash and stored_loc.payload_hash != loc.payload_hash:
                    return field.model_copy(update={"verification_status": "unverified"})
                cell_haystack = _normalize_ws_lower(
                    f"{row.get('line_item', '')} {row.get('display', '')} {row.get('raw_value', '')}"
                )
                if norm_quote not in cell_haystack:
                    return field.model_copy(update={"verification_status": "unverified"})
                verified_locators.append(stored_loc)
                matched_quote_texts.append(quote)
            else:
                return field.model_copy(update={"verification_status": "unverified"})

        # Numeric literal anchor check: ensures extracted numbers appear verbatim
        # in the verified quote or raw spreadsheet primitive (blocks digit swaps).
        numeric_candidates = _digits_and_decimal(field.value)
        if numeric_candidates:
            combined_quotes = _normalize_ws_lower(" ".join(matched_quote_texts))
            raw_vals = " ".join(
                str(loc.raw_value) for loc in verified_locators if loc.raw_value is not None
            ).lower()
            haystack = f"{combined_quotes} {raw_vals}"
            if not any(cand.lower() in haystack for cand in numeric_candidates):
                return field.model_copy(update={"verification_status": "unverified"})

        return field.model_copy(
            update={
                "verification_status": "verified",
                "locators": verified_locators,
            }
        )

    def verify_case_graph(
        self, graph: CanonicalCaseGraph, ingestor: MatterIngestor
    ) -> CanonicalCaseGraph:
        """Recursively verifies every `ProvenanceField` on a `CanonicalCaseGraph`.

        Args:
            graph: Case graph populated by extraction or user edits.
            ingestor: Active `MatterIngestor` holding indexed matter files.

        Returns:
            New `CanonicalCaseGraph` with deterministic verification statuses applied.
        """
        corpus = IndexedMatterCorpus.load_for_matter(ingestor, graph.matter_id)

        def _walk(obj: Any) -> Any:
            if isinstance(obj, ProvenanceField):
                return self.verify_field(obj, corpus)
            if isinstance(obj, list):
                return [_walk(item) for item in obj]
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, BaseModel):
                updates: Dict[str, Any] = {}
                for fname in type(obj).model_fields:
                    updates[fname] = _walk(getattr(obj, fname))
                return obj.model_copy(update=updates)
            return obj

        return _walk(graph)
