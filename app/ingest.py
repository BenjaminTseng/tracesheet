"""Deterministic ingestion and coordinate-stamping engine for `(a)` and `(b)`.

This module implements:
1. `CanonicalRouter`: Loads the standing canonical corpus (`canonical/INDEX.md` and
   `[AUTH:...]` anchored Markdown files) representing epistemic tier `(b)`.
2. `MatterIngestor`: Deterministically converts raw project files under
   `matters/<matter_id>/inputs/raw/` (`.pdf`, `.xlsx`, `.csv`, `.md`, `.txt`) into
   coordinate-stamped Markdown (`*.indexed.md`) and spreadsheet indices
   (`sheets_index.jsonl`), and exposes deterministic read-only search tools so
   Stage 2 LLM agents copy pre-computed `SourceLocator` objects instead of guessing
   page numbers, bounding boxes, or cell coordinates.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import pdfplumber

from app.llm import ToolDefinition
from app.models import CanonicalAuthorityRef, SourceLocator

logger = logging.getLogger("jd_screen.ingest")

LOCATOR_COMMENT_RE = re.compile(r"^<!--\s*LOCATOR:\s*(\{.*?\})\s*-->$")
AUTH_HEADING_RE = re.compile(r"^##\s+\[(AUTH:[^\]]+)\]\s+(.+)$")


def _sha256_short(data: bytes) -> str:
    """Returns a short prefixed SHA-256 digest for tamper-evident locator stamping."""
    return f"sha256:{hashlib.sha256(data).hexdigest()[:18]}"


class CanonicalRouter:
    """Two-level router for standing canonical authorities `(b)` under `canonical/`."""

    def __init__(self, canonical_dir: Path) -> None:
        """Initializes the canonical router.

        Args:
            canonical_dir: Path to the directory containing `INDEX.md` and domain
                subdirectories with `[AUTH:...]` anchored Markdown files.
        """
        self.canonical_dir = canonical_dir

    def get_index_markdown(self) -> str:
        """Reads `canonical/INDEX.md` for direct injection into Stage 1 planning.

        Returns:
            Full contents of `INDEX.md`, or a fallback note if none exists yet.
        """
        index_path = self.canonical_dir / "INDEX.md"
        if not index_path.exists():
            return "# Canonical Index\nNo canonical INDEX.md found."
        return index_path.read_text(encoding="utf-8")

    def list_authorities(self) -> Dict[str, CanonicalAuthorityRef]:
        """Scans all Markdown files under `canonical/` for `[AUTH:...]` blocks.

        Returns:
            Dictionary mapping `auth_id` (e.g., `'AUTH:HERTZ-2010-NERVE-CENTER'`)
            to `CanonicalAuthorityRef`.
        """
        authorities: Dict[str, CanonicalAuthorityRef] = {}
        if not self.canonical_dir.exists():
            return authorities

        for md_path in sorted(self.canonical_dir.rglob("*.md")):
            if md_path.name == "INDEX.md":
                continue
            rel_path = str(md_path.relative_to(self.canonical_dir))
            lines = md_path.read_text(encoding="utf-8").splitlines()
            current_id: Optional[str] = None
            current_title: str = ""
            current_url: Optional[str] = None
            quote_lines: List[str] = []

            def flush_current() -> None:
                if current_id is not None:
                    verbatim = "\n".join(quote_lines).strip()
                    authorities[current_id] = CanonicalAuthorityRef(
                        auth_id=current_id,
                        title=current_title.strip(),
                        url=current_url,
                        verbatim_quote=verbatim or current_title.strip(),
                        source_file=rel_path,
                    )

            for raw_line in lines:
                heading_match = AUTH_HEADING_RE.match(raw_line.strip())
                if heading_match:
                    flush_current()
                    current_id = heading_match.group(1).strip()
                    current_title = heading_match.group(2).strip()
                    current_url = None
                    quote_lines = []
                    continue

                if current_id is None:
                    continue

                stripped = raw_line.strip()
                if stripped.startswith("- **Title:**"):
                    current_title = stripped.split("**Title:**", 1)[1].strip()
                elif stripped.startswith("- **URL:**"):
                    url_val = stripped.split("**URL:**", 1)[1].strip()
                    current_url = None if url_val.lower() in ("none", "n/a", "") else url_val
                elif stripped.startswith("- **Verbatim Holding:**"):
                    quote_lines.append(stripped.split("**Verbatim Holding:**", 1)[1].strip())
                elif stripped.startswith("- **Verbatim Rule:**"):
                    quote_lines.append(stripped.split("**Verbatim Rule:**", 1)[1].strip())
                elif stripped.startswith("- **Verbatim Text:**"):
                    quote_lines.append(stripped.split("**Verbatim Text:**", 1)[1].strip())
                elif stripped and not stripped.startswith("---"):
                    quote_lines.append(stripped)

            flush_current()

        return authorities

    def get_authority(self, auth_id: str) -> Optional[CanonicalAuthorityRef]:
        """Retrieves a single canonical authority by its `[AUTH:...]` identifier.

        Args:
            auth_id: Authority ID with or without surrounding brackets.

        Returns:
            Matching `CanonicalAuthorityRef` or `None`.
        """
        normalized = auth_id.strip().strip("[]")
        authorities = self.list_authorities()
        if normalized in authorities:
            return authorities[normalized]
        if not normalized.startswith("AUTH:") and f"AUTH:{normalized}" in authorities:
            return authorities[f"AUTH:{normalized}"]
        return None

    def get_authorities_context(self, auth_ids: Optional[List[str]] = None) -> str:
        """Formats selected (or all) canonical authorities into a prompt-ready block."""
        authorities = self.list_authorities()
        selected = (
            [authorities[aid] for aid in auth_ids if aid in authorities]
            if auth_ids
            else list(authorities.values())
        )
        chunks = []
        for auth in selected:
            chunks.append(
                f"### [{auth.auth_id}] {auth.title}\n"
                f"- Source: {auth.source_file or 'canonical'}\n"
                f"- URL: {auth.url or 'N/A'}\n"
                f"- Verbatim Text: {auth.verbatim_quote}\n"
            )
        return "\n".join(chunks)


class MatterIngestor:
    """Deterministic file parser and search tool builder for project inputs `(a)`."""

    def __init__(self, matters_root: Path) -> None:
        """Initializes the matter ingestor.

        Args:
            matters_root: Root directory containing per-matter folders (`matters/<id>`).
        """
        self.matters_root = matters_root

    def _matter_dirs(self, matter_id: str) -> Tuple[Path, Path, Path, Path]:
        """Returns `(matter_dir, raw_dir, indexed_dir, bundles_dir)` for a matter."""
        matter_dir = self.matters_root / matter_id
        raw_dir = matter_dir / "inputs" / "raw"
        indexed_dir = matter_dir / "inputs" / "indexed"
        bundles_dir = matter_dir / "bundles"
        return matter_dir, raw_dir, indexed_dir, bundles_dir

    def create_matter(self, matter_id: str) -> Path:
        """Creates the standard `inputs/raw`, `inputs/indexed`, and `bundles` directories."""
        matter_dir, raw_dir, indexed_dir, bundles_dir = self._matter_dirs(matter_id)
        raw_dir.mkdir(parents=True, exist_ok=True)
        indexed_dir.mkdir(parents=True, exist_ok=True)
        bundles_dir.mkdir(parents=True, exist_ok=True)
        return matter_dir

    def list_matters(self) -> List[Dict[str, Any]]:
        """Lists all project matters on disk along with their raw and indexed file counts."""
        if not self.matters_root.exists():
            return []
        results: List[Dict[str, Any]] = []
        for entry in sorted(self.matters_root.iterdir()):
            if not entry.is_dir():
                continue
            matter_id = entry.name
            _, raw_dir, indexed_dir, bundles_dir = self._matter_dirs(matter_id)
            raw_files = (
                sorted(p.name for p in raw_dir.iterdir() if p.is_file())
                if raw_dir.exists()
                else []
            )
            manifest_path = indexed_dir / "manifest.json"
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists()
                else None
            )
            bundle_files = (
                sorted(p.stem for p in bundles_dir.glob("*.json"))
                if bundles_dir.exists()
                else []
            )
            results.append(
                {
                    "matter_id": matter_id,
                    "raw_files": raw_files,
                    "indexed": manifest is not None,
                    "manifest": manifest,
                    "saved_bundles": bundle_files,
                }
            )
        return results

    def ingest_pdf(self, raw_path: Path, indexed_dir: Path) -> Tuple[Path, int]:
        """Extracts coordinate-stamped paragraph blocks from a PDF using `pdfplumber`.

        Groups extracted words into line-level blocks separated by vertical gaps,
        computing integer `[x1, y1, x2, y2]` bounding boxes and embedding a
        `<!-- LOCATOR: {...} -->` header above each block.

        Args:
            raw_path: Path to the source `.pdf` file.
            indexed_dir: Target directory for `<filename>.indexed.md`.

        Returns:
            Tuple of `(output_markdown_path, block_count)`.
        """
        file_hash = _sha256_short(raw_path.read_bytes())
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_path.stem).upper()
        md_blocks: List[str] = [f"# Indexed Document: {raw_path.name}\n"]
        block_count = 0

        with pdfplumber.open(raw_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                words = page.extract_words() or []
                if not words:
                    plain_text = (page.extract_text() or "").strip()
                    if plain_text:
                        block_count += 1
                        loc = SourceLocator(
                            source_type="pdf",
                            file_name=raw_path.name,
                            page=page_idx,
                            bounding_box=[0, 0, int(page.width), int(page.height)],
                            locator_key=f"{stem}-P{page_idx}-B1",
                            payload_hash=file_hash,
                        )
                        md_blocks.append(
                            f"<!-- LOCATOR: {loc.model_dump_json(exclude_none=True)} -->\n"
                            f"{plain_text}\n"
                        )
                    continue

                # Group words into visual lines (tolerance 4pt) and then paragraphs
                # separated by larger vertical gaps (> 18pt) so bounding boxes
                # tightly enclose coherent evidentiary passages.
                sorted_words = sorted(words, key=lambda w: (round(float(w["top"]), 1), float(w["x0"])))
                lines: List[List[Dict[str, Any]]] = []
                for word in sorted_words:
                    if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 4.0:
                        lines.append([word])
                    else:
                        lines[-1].append(word)

                paragraphs: List[List[List[Dict[str, Any]]]] = []
                for line in lines:
                    line.sort(key=lambda w: float(w["x0"]))
                    if not paragraphs:
                        paragraphs.append([line])
                    else:
                        prev_bottom = max(float(w["bottom"]) for w in paragraphs[-1][-1])
                        curr_top = min(float(w["top"]) for w in line)
                        if (curr_top - prev_bottom) > 18.0:
                            paragraphs.append([line])
                        else:
                            paragraphs[-1].append(line)

                for b_idx, para in enumerate(paragraphs, start=1):
                    flat_words = [w for ln in para for w in ln]
                    text = " ".join(" ".join(w["text"] for w in ln) for ln in para).strip()
                    if not text:
                        continue
                    x1 = int(min(float(w["x0"]) for w in flat_words))
                    y1 = int(min(float(w["top"]) for w in flat_words))
                    x2 = int(max(float(w["x1"]) for w in flat_words))
                    y2 = int(max(float(w["bottom"]) for w in flat_words))
                    block_count += 1
                    loc = SourceLocator(
                        source_type="pdf",
                        file_name=raw_path.name,
                        page=page_idx,
                        bounding_box=[x1, y1, x2, y2],
                        locator_key=f"{stem}-P{page_idx}-B{b_idx}",
                        payload_hash=file_hash,
                    )
                    md_blocks.append(
                        f"<!-- LOCATOR: {loc.model_dump_json(exclude_none=True)} -->\n{text}\n"
                    )

        out_path = indexed_dir / f"{raw_path.name}.indexed.md"
        out_path.write_text("\n".join(md_blocks), encoding="utf-8")
        return out_path, block_count

    def ingest_markdown(self, raw_path: Path, indexed_dir: Path) -> Tuple[Path, int]:
        """Splits a Markdown/text file into paragraph blocks stamped with locators."""
        content = raw_path.read_text(encoding="utf-8")
        file_hash = _sha256_short(content.encode("utf-8"))
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_path.stem).upper()
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        md_blocks: List[str] = [f"# Indexed Document: {raw_path.name}\n"]

        for idx, para in enumerate(paragraphs, start=1):
            loc = SourceLocator(
                source_type="markdown",
                file_name=raw_path.name,
                locator_key=f"{stem}-SEC-{idx}",
                payload_hash=file_hash,
            )
            md_blocks.append(
                f"<!-- LOCATOR: {loc.model_dump_json(exclude_none=True)} -->\n{para}\n"
            )

        out_path = indexed_dir / f"{raw_path.name}.indexed.md"
        out_path.write_text("\n".join(md_blocks), encoding="utf-8")
        return out_path, len(paragraphs)

    def ingest_spreadsheet(self, raw_path: Path) -> List[Dict[str, Any]]:
        """Extracts cell coordinates, row line-item labels, formulas, and evaluated values.

        Performs a dual pass on `.xlsx` workbooks (`data_only=False` for formula strings
        and `data_only=True` for evaluated cached values) and also supports `.csv`.

        Args:
            raw_path: Path to `.xlsx`, `.xlsm`, or `.csv` file.

        Returns:
            List of cell index records ready for `sheets_index.jsonl`.
        """
        file_hash = _sha256_short(raw_path.read_bytes())
        entries: List[Dict[str, Any]] = []

        if raw_path.suffix.lower() == ".csv":
            with raw_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                for r_idx, row in enumerate(reader, start=1):
                    row_label = row[0].strip() if row else ""
                    for c_idx, val in enumerate(row, start=1):
                        cleaned = val.strip()
                        if not cleaned:
                            continue
                        col_letter = openpyxl.utils.get_column_letter(c_idx)
                        coord = f"{col_letter}{r_idx}"
                        parsed_val: Any = cleaned
                        try:
                            parsed_val = float(cleaned) if "." in cleaned else int(cleaned)
                        except ValueError:
                            pass
                        loc = SourceLocator(
                            source_type="spreadsheet",
                            file_name=raw_path.name,
                            sheet="CSV",
                            cell_range=coord,
                            raw_value=parsed_val,
                            payload_hash=file_hash,
                        )
                        entries.append(
                            {
                                "file_name": raw_path.name,
                                "sheet": "CSV",
                                "cell_range": coord,
                                "line_item": row_label or coord,
                                "display": cleaned,
                                "raw_value": parsed_val,
                                "formula": None,
                                "locator": loc.model_dump(exclude_none=True),
                            }
                        )
            return entries

        wb_formulas = openpyxl.load_workbook(raw_path, data_only=False)
        wb_values = openpyxl.load_workbook(raw_path, data_only=True)

        for sheet_name in wb_formulas.sheetnames:
            ws_f = wb_formulas[sheet_name]
            ws_v = wb_values[sheet_name]
            for row_idx in range(1, ws_f.max_row + 1):
                first_cell_val = ws_v.cell(row=row_idx, column=1).value
                if first_cell_val is None:
                    first_cell_val = ws_f.cell(row=row_idx, column=1).value
                row_label = str(first_cell_val).strip() if first_cell_val is not None else ""

                for col_idx in range(1, ws_f.max_column + 1):
                    cell_f = ws_f.cell(row=row_idx, column=col_idx)
                    cell_v = ws_v.cell(row=row_idx, column=col_idx)
                    raw_expr = cell_f.value
                    eval_val = cell_v.value
                    if raw_expr is None and eval_val is None:
                        continue

                    formula_str = (
                        str(raw_expr)
                        if isinstance(raw_expr, str) and raw_expr.startswith("=")
                        else None
                    )
                    primitive = eval_val if eval_val is not None else raw_expr
                    coord = cell_f.coordinate
                    loc = SourceLocator(
                        source_type="spreadsheet",
                        file_name=raw_path.name,
                        sheet=sheet_name,
                        cell_range=coord,
                        raw_value=primitive,
                        payload_hash=file_hash,
                    )
                    entries.append(
                        {
                            "file_name": raw_path.name,
                            "sheet": sheet_name,
                            "cell_range": coord,
                            "line_item": row_label or coord,
                            "display": str(primitive),
                            "raw_value": primitive,
                            "formula": formula_str,
                            "locator": loc.model_dump(exclude_none=True),
                        }
                    )

        return entries

    def ingest_matter(self, matter_id: str) -> Dict[str, Any]:
        """Deterministically ingests all raw files for a matter into `inputs/indexed/`.

        Args:
            matter_id: Project/matter slug under `matters/`.

        Returns:
            Summary manifest dictionary written to `inputs/indexed/manifest.json`.
        """
        _, raw_dir, indexed_dir, _ = self._matter_dirs(matter_id)
        indexed_dir.mkdir(parents=True, exist_ok=True)
        if not raw_dir.exists():
            raw_dir.mkdir(parents=True, exist_ok=True)

        # Clean stale indexed markdown/jsonl artifacts before regenerating
        for old_file in indexed_dir.glob("*.indexed.md"):
            old_file.unlink()

        sheet_entries: List[Dict[str, Any]] = []
        indexed_files: List[Dict[str, Any]] = []

        for raw_path in sorted(raw_dir.iterdir()):
            if not raw_path.is_file():
                continue
            suffix = raw_path.suffix.lower()
            if suffix == ".pdf":
                out_path, count = self.ingest_pdf(raw_path, indexed_dir)
                indexed_files.append(
                    {"raw": raw_path.name, "indexed": out_path.name, "blocks": count}
                )
            elif suffix in (".xlsx", ".xlsm", ".csv"):
                rows = self.ingest_spreadsheet(raw_path)
                sheet_entries.extend(rows)
                indexed_files.append(
                    {"raw": raw_path.name, "indexed": "sheets_index.jsonl", "cells": len(rows)}
                )
            elif suffix in (".md", ".txt"):
                out_path, count = self.ingest_markdown(raw_path, indexed_dir)
                indexed_files.append(
                    {"raw": raw_path.name, "indexed": out_path.name, "blocks": count}
                )
            else:
                logger.info("Skipping unsupported file type during ingest: %s", raw_path.name)

        sheets_path = indexed_dir / "sheets_index.jsonl"
        sheets_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in sheet_entries)
            + ("\n" if sheet_entries else ""),
            encoding="utf-8",
        )

        manifest = {
            "matter_id": matter_id,
            "ingested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "files_processed": len(indexed_files),
            "spreadsheet_cells_indexed": len(sheet_entries),
            "files": indexed_files,
        }
        (indexed_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        logger.info(
            "Ingested matter=%s files=%d sheet_cells=%d",
            matter_id,
            len(indexed_files),
            len(sheet_entries),
        )
        return manifest

    def _load_indexed_blocks(self, matter_id: str) -> List[Dict[str, Any]]:
        """Parses all `*.indexed.md` files for a matter into structured block dictionaries."""
        _, _, indexed_dir, _ = self._matter_dirs(matter_id)
        blocks: List[Dict[str, Any]] = []
        if not indexed_dir.exists():
            return blocks

        for md_path in sorted(indexed_dir.glob("*.indexed.md")):
            lines = md_path.read_text(encoding="utf-8").splitlines()
            curr_locator: Optional[Dict[str, Any]] = None
            curr_lines: List[str] = []

            def flush_block() -> None:
                if curr_locator is not None:
                    blocks.append(
                        {
                            "indexed_file": md_path.name,
                            "locator": curr_locator,
                            "text": "\n".join(curr_lines).strip(),
                        }
                    )

            for line in lines:
                m = LOCATOR_COMMENT_RE.match(line.strip())
                if m:
                    flush_block()
                    curr_locator = json.loads(m.group(1))
                    curr_lines = []
                elif curr_locator is not None:
                    curr_lines.append(line)
            flush_block()

        return blocks

    def expand_locator_context(
        self, matter_id: str, locators: List[SourceLocator], window: int = 1
    ) -> str:
        """Collects surrounding document blocks/rows for Stage 4 congruence auditing."""
        blocks = self._load_indexed_blocks(matter_id)
        _, _, indexed_dir, _ = self._matter_dirs(matter_id)
        sheets_path = indexed_dir / "sheets_index.jsonl"
        sheet_rows = (
            [json.loads(line) for line in sheets_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if sheets_path.exists()
            else []
        )

        snippets: List[str] = []
        seen_keys: set[str] = set()

        for loc in locators:
            if loc.locator_key:
                for idx, blk in enumerate(blocks):
                    if blk["locator"].get("locator_key") == loc.locator_key:
                        start = max(0, idx - window)
                        end = min(len(blocks), idx + window + 1)
                        for neighbor in blocks[start:end]:
                            n_key = str(neighbor["locator"].get("locator_key"))
                            if n_key not in seen_keys:
                                seen_keys.add(n_key)
                                snippets.append(
                                    f"[{n_key} | {neighbor['locator'].get('file_name')} p.{neighbor['locator'].get('page', '-')}]\n"
                                    f"{neighbor['text']}"
                                )
            elif loc.source_type == "spreadsheet" and loc.file_name:
                matching = [
                    r
                    for r in sheet_rows
                    if r["file_name"] == loc.file_name and (not loc.sheet or r["sheet"] == loc.sheet)
                ]
                if matching:
                    snippets.append(
                        f"[Spreadsheet {loc.file_name} ! {loc.sheet}]\n"
                        + "\n".join(
                            f"  {r['cell_range']}: {r['line_item']} = {r['display']} (fx: {r['formula']})"
                            for r in matching[:25]
                        )
                    )

        return "\n\n".join(snippets)

    def build_stage2_tools(self, matter_id: str) -> List[ToolDefinition]:
        """Constructs deterministic search & read tools for the Stage 2 Fact Harvester.

        Args:
            matter_id: Target matter directory identifier.

        Returns:
            List of `ToolDefinition` instances safe to expose to an LLM agent.
        """
        _, raw_dir, indexed_dir, _ = self._matter_dirs(matter_id)

        def list_matter_files() -> Dict[str, Any]:
            manifest_path = indexed_dir / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                return {
                    "matter_id": matter_id,
                    "files": [
                        {"raw_file": f["raw"], **f} for f in manifest.get("files", [])
                    ],
                }
            raw_files = (
                [{"raw_file": p.name} for p in sorted(raw_dir.iterdir()) if p.is_file()]
                if raw_dir.exists()
                else []
            )
            return {"matter_id": matter_id, "files": raw_files}

        def grep_indexed_inputs(pattern: str, max_results: int = 10) -> Dict[str, Any]:
            blocks = self._load_indexed_blocks(matter_id)
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
            matches: List[Dict[str, Any]] = []
            for blk in blocks:
                if regex.search(blk["text"]):
                    matches.append(
                        {
                            "locator": blk["locator"],
                            "excerpt": blk["text"],
                        }
                    )
                    if len(matches) >= max_results:
                        break
            return {"pattern": pattern, "match_count": len(matches), "matches": matches}

        def read_locator_context(locator_key: str, window_blocks: int = 1) -> Dict[str, Any]:
            blocks = self._load_indexed_blocks(matter_id)
            for idx, blk in enumerate(blocks):
                if blk["locator"].get("locator_key") == locator_key:
                    start = max(0, idx - window_blocks)
                    end = min(len(blocks), idx + window_blocks + 1)
                    return {
                        "locator": blk["locator"],
                        "block_text": blk["text"],
                        "surrounding_blocks": [
                            {"locator": b["locator"], "text": b["text"]}
                            for b in blocks[start:end]
                        ],
                    }
            return {"error": f"No indexed block found with locator_key='{locator_key}'."}

        def search_spreadsheet_cells(query: str, max_results: int = 20) -> Dict[str, Any]:
            sheets_path = indexed_dir / "sheets_index.jsonl"
            if not sheets_path.exists():
                return {"query": query, "cells": []}
            q_lower = query.lower()
            matched: List[Dict[str, Any]] = []
            for line in sheets_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                haystack = " ".join(
                    str(row.get(k, ""))
                    for k in ("file_name", "sheet", "cell_range", "line_item", "display", "formula")
                ).lower()
                if q_lower in haystack or q_lower == "*":
                    matched.append(row)
                    if len(matched) >= max_results:
                        break
            return {"query": query, "cells": matched}

        return [
            ToolDefinition(
                name="list_matter_files",
                description="List all raw and coordinate-indexed files available in this project matter.",
                parameters_schema={"type": "object", "properties": {}},
                handler=list_matter_files,
            ),
            ToolDefinition(
                name="grep_indexed_inputs",
                description=(
                    "Case-insensitive search across all coordinate-stamped PDF and Markdown blocks "
                    "for this matter. Returns exact pre-computed `locator` objects and block text."
                ),
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Keyword or phrase to search for.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum blocks to return (default 10).",
                        },
                    },
                    "required": ["pattern"],
                },
                handler=grep_indexed_inputs,
            ),
            ToolDefinition(
                name="read_locator_context",
                description=(
                    "Reads the full text and surrounding blocks for a specific `locator_key` "
                    "to check for exceptions, qualifiers, or footnotes."
                ),
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "locator_key": {
                            "type": "string",
                            "description": "Exact `locator_key` returned by grep_indexed_inputs.",
                        },
                        "window_blocks": {
                            "type": "integer",
                            "description": "Number of adjacent blocks before/after to include.",
                        },
                    },
                    "required": ["locator_key"],
                },
                handler=read_locator_context,
            ),
            ToolDefinition(
                name="search_spreadsheet_cells",
                description=(
                    "Searches indexed Excel/CSV cells by line item, sheet name, cell coordinate, "
                    "or formula. Returns exact `sheet`, `cell_range`, `formula`, `raw_value`, and `locator`."
                ),
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword or metric name (e.g., 'Gross Margin', 'Total', or '*' for sample rows).",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum cells to return (default 20).",
                        },
                    },
                    "required": ["query"],
                },
                handler=search_spreadsheet_cells,
            ),
        ]
