"""Abstract `DistrictAdapter` and registry for California federal bankruptcy courts."""

from __future__ import annotations

import datetime
import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Tuple

import pymupdf

from app.compilers.bankruptcy.schema import (
    BankruptcyCaseState,
    CanonicalCaseGraph,
    ChapterType,
    CourtFilingReceipt,
    DistrictCode,
)
from app.core.pii import PIITokenizer


class DistrictAdapter(ABC):
    """Abstract interface encapsulating local court matrix, PDF, and submission rules."""

    district_code: DistrictCode
    portal_url: str
    train_url: str
    max_pdf_bytes: int

    @abstractmethod
    def format_creditor_matrix(self, graph: CanonicalCaseGraph) -> Tuple[str, List[str]]:
        """Generates a district-compliant ASCII `creditor_matrix.txt` and validation warnings."""

    @abstractmethod
    def format_debtor_txt(self, graph: CanonicalCaseGraph, tokenizer: PIITokenizer) -> str:
        """Generates a district CM/ECF Case Upload `debtor.txt` (unmasking SSN via vault)."""

    @abstractmethod
    def package_pdfs(
        self, packet_dir: Path, pdf_paths: List[Path], chapter: ChapterType
    ) -> Tuple[List[Path], List[str]]:
        """Validates isolation of Form B 121, zero remaining widgets, and enforces PDF size limits."""

    @abstractmethod
    def submit_packet(
        self,
        state: BankruptcyCaseState,
        packet_files: List[Path],
        submission_mode: str,
        attorney_name: str,
        attorney_bar_number: str,
        totp_code: str,
    ) -> CourtFilingReceipt:
        """Executes district-specific filing driver and returns an official `CourtFilingReceipt`."""

    @staticmethod
    def verify_baked_and_b121_isolated(pdf_paths: List[Path]) -> List[str]:
        """Checks every PDF has zero unbaked `/Widget` annotations and Form B 121 is standalone."""
        errors: List[str] = []
        b121_files = [p for p in pdf_paths if p.name.startswith("Form_B121_RESTRICTED")]
        if not b121_files:
            errors.append("Missing standalone Form_B121_RESTRICTED.pdf.")

        for p in pdf_paths:
            with pymupdf.open(str(p)) as doc:
                for page_idx, page in enumerate(doc, start=1):
                    widgets = list(page.widgets() or [])
                    if widgets:
                        errors.append(
                            f"{p.name} page {page_idx} contains {len(widgets)} unbaked interactive widget(s)."
                        )
                    if not p.name.startswith("Form_B121_RESTRICTED"):
                        text = page.get_text("text")
                        if "Statement About Your Social Security Numbers" in text:
                            errors.append(
                                f"Privacy violation: Form B 121 content detected inside public PDF {p.name}."
                            )
        return errors

    @staticmethod
    def _wrap_block_lines(
        name: str, address_lines: List[str], city: str, state: str, zip_code: str,
        max_name_chars: int = 50, max_addr_chars: int = 40, allow_leading_spaces: bool = False
    ) -> List[str]:
        """Formats a single creditor address block to strict 5-line / 40-char ASCII court rules."""
        def _clean_ascii(s: str) -> str:
            ascii_only = s.encode("ascii", errors="ignore").decode("ascii")
            ascii_only = re.sub(r"[~^`<>|]", "", ascii_only)
            return ascii_only.strip()

        clean_name = _clean_ascii(name)[:max_name_chars]
        body_lines = [_clean_ascii(ln)[:max_addr_chars] for ln in address_lines if _clean_ascii(ln)]
        csz = _clean_ascii(f"{city}, {state.upper()} {zip_code}".strip(", "))[:max_addr_chars]
        # Keep max 3 address body lines so total block <= 5 lines (name + <=3 body + csz).
        lines = [clean_name] + body_lines[:3] + [csz]
        if not allow_leading_spaces:
            lines = [ln.lstrip() for ln in lines]
        return [ln for ln in lines if ln][:5]

    @staticmethod
    def _receipt_hash(matter_id: str, district: str, files: List[Path]) -> str:
        h = hashlib.sha256()
        h.update(f"{matter_id}:{district}:{datetime.datetime.now(datetime.timezone.utc).isoformat()}".encode())
        for p in sorted(files):
            h.update(p.name.encode())
        return f"sha256:{h.hexdigest()[:24]}"


def get_district_adapter(
    district: DistrictCode, max_pdf_bytes: Optional[int] = None
) -> DistrictAdapter:
    """Factory returning the concrete `DistrictAdapter` for `CACB` or `CAEB`."""
    from app.compilers.bankruptcy.districts.cacb import CACBDistrictAdapter
    from app.compilers.bankruptcy.districts.caeb import CAEBDistrictAdapter

    if district == "CACB":
        return CACBDistrictAdapter(max_pdf_bytes=max_pdf_bytes)
    if district == "CAEB":
        return CAEBDistrictAdapter(max_pdf_bytes=max_pdf_bytes)
    raise ValueError(f"Unsupported California district: {district}")
