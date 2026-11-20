"""Domain-agnostic deterministic citation, JSON-path, and numeric anchor verifier.

Validates every `ProvenanceField` in any Pydantic model against cryptographic
SHA-256 hashes, coordinate-stamped Markdown blocks (`*.indexed.md`),
spreadsheet cells (`sheets_index.jsonl`), and raw/ledger JSON documents.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypeVar

from pydantic import BaseModel

from app.core.bundle import SourceLocator
from app.core.ingest import LOCATOR_COMMENT_RE, MatterIngestor, _sha256_short
from app.core.provenance import ProvenanceField


TModel = TypeVar("TModel", bound=BaseModel)


def _normalize_ws_lower(text: str) -> str:
    """Normalizes whitespace and case for deterministic substring checks."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _digits_and_decimal(value: Any) -> List[str]:
    """Builds canonical numeric string representations to verify literal presence in quotes."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (Decimal, int, float)):
        dec = Decimal(str(value))
        candidates = set()
        plain = format(dec, "f")
        candidates.add(plain)
        if "." in plain:
            whole, frac = plain.split(".", 1)
            sign = "-" if whole.startswith("-") else ""
            whole_abs = whole.lstrip("-")
            if whole_abs.isdigit():
                candidates.add(f"{sign}{int(whole_abs):,}.{frac}")
            if set(frac) == {"0"}:
                candidates.add(f"{sign}{whole_abs}")
                if whole_abs.isdigit():
                    candidates.add(f"{sign}{int(whole_abs):,}")
            else:
                candidates.add(plain.rstrip("0").rstrip("."))
        else:
            sign = "-" if plain.startswith("-") else ""
            whole_abs = plain.lstrip("-")
            if whole_abs.isdigit():
                candidates.add(f"{sign}{int(whole_abs):,}")
                candidates.add(f"{plain}.00")
                candidates.add(f"{sign}{int(whole_abs):,}.00")
        return sorted(candidates, key=len, reverse=True)
    return []


def resolve_json_path(doc: Any, json_path: str) -> Tuple[bool, Any]:
    """Resolves a dotted/bracketed path (e.g. `$.facts.cmi` or `events[0].amount`) in JSON."""
    cleaned = (json_path or "").strip()
    if cleaned.startswith("$."):
        cleaned = cleaned[2:]
    elif cleaned == "$":
        return True, doc
    elif cleaned.startswith("$["):
        cleaned = cleaned[1:]

    if not cleaned:
        return False, None

    tokens = re.findall(r"[^.\[\]]+|\[\d+\]", cleaned)
    if not tokens:
        return False, None

    cur = doc
    for tok in tokens:
        if tok.startswith("[") and tok.endswith("]"):
            idx = int(tok[1:-1])
            if isinstance(cur, list) and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return False, None
        else:
            if isinstance(cur, dict) and tok in cur:
                cur = cur[tok]
            else:
                return False, None
    return True, cur


class IndexedMatterCorpus:
    """In-memory lookup index of verified blocks, spreadsheet cells, and JSON documents."""

    def __init__(self) -> None:
        """Initializes empty block, cell, and JSON maps."""
        self.blocks_by_key: Dict[Tuple[str, str], Tuple[SourceLocator, str]] = {}
        self.cells_by_coord: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self.json_docs: Dict[str, Tuple[str, str, Any]] = {}

    @classmethod
    def load_for_matter(
        cls, ingestor: MatterIngestor, matter_id: str
    ) -> "IndexedMatterCorpus":
        """Loads indexed blocks, cells, raw JSON files, and sibling calculation ledgers."""
        corpus = cls()
        matter_dir, raw_dir, indexed_dir, _ = ingestor._matter_dirs(matter_id)
        if indexed_dir.exists():
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

        # Index raw *.json files and ledgers/*.json for direct `json_path` verification.
        def _register_json(key_names: List[str], path: Path) -> None:
            try:
                raw_bytes = path.read_bytes()
                parsed = json.loads(raw_bytes.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return
            short_h = _sha256_short(raw_bytes)
            full_h = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
            for kn in key_names:
                corpus.json_docs[kn] = (short_h, full_h, parsed)

        if raw_dir.exists():
            for jp in sorted(raw_dir.glob("*.json")):
                _register_json([jp.name], jp)

        ledgers_dir = matter_dir / "ledgers"
        if ledgers_dir.exists():
            for lp in sorted(ledgers_dir.glob("*.json")):
                _register_json([f"ledgers/{lp.name}", lp.name], lp)

        return corpus


class ObservationVerifier:
    """Deterministically validates extracted `ProvenanceField`s against indexed sources."""

    @staticmethod
    def _matches_hash(expected: Optional[str], short_h: str, full_h: str) -> bool:
        if not expected:
            return True
        return expected in (short_h, full_h)

    @staticmethod
    def _value_in_json_leaf(value: Any, leaf: Any) -> bool:
        """Checks whether a non-numeric extracted scalar value is present in a JSON leaf."""
        if isinstance(value, bool):
            return leaf is value or str(value).lower() in _normalize_ws_lower(json.dumps(leaf))
        if isinstance(value, datetime.date):
            iso = value.isoformat()
            return iso in _normalize_ws_lower(json.dumps(leaf, default=str))
        if isinstance(value, str):
            norm_v = _normalize_ws_lower(value)
            if not norm_v:
                return True
            hay = _normalize_ws_lower(
                leaf if isinstance(leaf, str) else json.dumps(leaf, default=str)
            )
            return norm_v in hay
        return True

    def verify_field(
        self, field: ProvenanceField[Any], corpus: IndexedMatterCorpus
    ) -> ProvenanceField[Any]:
        """Verifies a single `ProvenanceField` against `corpus`."""
        if field.verification_status == "human_overridden" and field.override is not None:
            return field

        if not field.locators or not field.verbatim_quotes:
            return field.model_copy(update={"verification_status": "unverified"})

        verified_locators: List[SourceLocator] = []
        matched_quote_texts: List[str] = []

        for idx, loc in enumerate(field.locators):
            quote = (
                field.verbatim_quotes[idx]
                if idx < len(field.verbatim_quotes)
                else field.verbatim_quotes[0]
            )
            norm_quote = _normalize_ws_lower(quote)
            if not norm_quote:
                return field.model_copy(update={"verification_status": "unverified"})

            # Case 1: Block locator inside *.indexed.md (PDF, DOCX, Markdown, Event/Ledger block).
            if loc.file_name and loc.locator_key:
                entry = corpus.blocks_by_key.get((loc.file_name, loc.locator_key))
                if entry is None:
                    return field.model_copy(update={"verification_status": "unverified"})
                stored_loc, stored_text = entry
                if loc.payload_hash and stored_loc.payload_hash != loc.payload_hash:
                    return field.model_copy(update={"verification_status": "unverified"})
                if norm_quote not in _normalize_ws_lower(stored_text):
                    return field.model_copy(update={"verification_status": "unverified"})
                if loc.json_path and loc.file_name in corpus.json_docs:
                    short_h, full_h, parsed_doc = corpus.json_docs[loc.file_name]
                    if not self._matches_hash(loc.payload_hash, short_h, full_h):
                        return field.model_copy(update={"verification_status": "unverified"})
                    found, _ = resolve_json_path(parsed_doc, loc.json_path)
                    if not found:
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
            # Case 3: Direct JSON key-path locator against raw JSON or sibling ledgers.
            elif loc.file_name and loc.json_path:
                doc_entry = corpus.json_docs.get(loc.file_name)
                if doc_entry is None:
                    return field.model_copy(update={"verification_status": "unverified"})
                short_h, full_h, parsed_doc = doc_entry
                if not self._matches_hash(loc.payload_hash, short_h, full_h):
                    return field.model_copy(update={"verification_status": "unverified"})
                found, leaf = resolve_json_path(parsed_doc, loc.json_path)
                if not found:
                    return field.model_copy(update={"verification_status": "unverified"})
                leaf_text = leaf if isinstance(leaf, str) else json.dumps(leaf, default=str)
                if norm_quote not in _normalize_ws_lower(leaf_text):
                    return field.model_copy(update={"verification_status": "unverified"})
                if not self._value_in_json_leaf(field.value, leaf):
                    return field.model_copy(update={"verification_status": "unverified"})
                verified_loc = loc.model_copy(
                    update={
                        "payload_hash": short_h,
                        "raw_value": leaf if not isinstance(leaf, (dict, list)) else leaf_text,
                    }
                )
                verified_locators.append(verified_loc)
                matched_quote_texts.append(quote)
            else:
                return field.model_copy(update={"verification_status": "unverified"})

        # Numeric literal anchor check: ensures extracted numbers appear verbatim
        # in the verified quote or raw primitive (blocks digit swaps).
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

    def verify_model(
        self, model: TModel, matter_id: str, ingestor: MatterIngestor
    ) -> TModel:
        """Recursively verifies every `ProvenanceField` on an arbitrary Pydantic model."""
        corpus = IndexedMatterCorpus.load_for_matter(ingestor, matter_id)

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

        return _walk(model)

    def verify_case_graph(self, graph: TModel, ingestor: MatterIngestor) -> TModel:
        """Verifies every `ProvenanceField` on a graph exposing `.matter_id`."""
        matter_id = getattr(graph, "matter_id")
        return self.verify_model(graph, matter_id, ingestor)
