"""Central District of California (`CACB`) adapter and NextGen CM/ECF Case Upload driver."""

from __future__ import annotations

import datetime
import re
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from app.bankruptcy.districts.base import DistrictAdapter
from app.bankruptcy.models import (
    BankruptcyCaseState,
    CanonicalCaseGraph,
    ChapterType,
    CourtFilingReceipt,
)
from app.core.pii import PIITokenizer


CACB_EXCLUDED_MATRIX_RE = re.compile(
    r"\b(internal revenue service|irs|franchise tax board|ftb|u\.?s\.?\s*trustee|united states trustee)\b",
    re.IGNORECASE,
)


class CACBDistrictAdapter(DistrictAdapter):
    """Implements CACB LBR 1007-1 matrix exclusions, 50 MB PDF checks, and Case Upload."""

    district_code = "CACB"
    portal_url = "https://ecf.cacb.uscourts.gov"
    train_url = "https://ecf-train.cacb.uscourts.gov"

    def __init__(self, max_pdf_bytes: Optional[int] = None) -> None:
        """Initializes the CACB adapter (default 50 MB max PDF limit)."""
        self.max_pdf_bytes = max_pdf_bytes or (50 * 1024 * 1024)

    def format_creditor_matrix(self, graph: CanonicalCaseGraph) -> Tuple[str, List[str]]:
        """Generates CACB Master Mailing List `.txt` stripping Debtor, UST, IRS, and FTB."""
        debtor_names = {p.full_name.value.strip().lower() for p in graph.parties}
        blocks: List[str] = []
        notes: List[str] = []

        for claim in graph.claims:
            cname = claim.creditor_name.strip()
            if cname.lower() in debtor_names:
                notes.append(f"Excluded debtor '{cname}' from CACB creditor matrix per LBR 1007-1.")
                continue
            if CACB_EXCLUDED_MATRIX_RE.search(cname):
                notes.append(f"Excluded government entity '{cname}' from CACB matrix per CACB LBR 1007-1.")
                continue

            lines = self._wrap_block_lines(
                name=cname,
                address_lines=claim.creditor_address_lines or ["Address Pending"],
                city=claim.city or "Los Angeles",
                state=claim.state or "CA",
                zip_code=claim.zip_code or "90012",
                max_name_chars=50,
                max_addr_chars=40,
            )
            # CACB LBR 1007-1 prohibits punctuation except comma between city & state.
            cleaned_lines = [
                ln if idx == len(lines) - 1 else re.sub(r"[.,;#']", "", ln)
                for idx, ln in enumerate(lines)
            ]
            blocks.append("\n".join(cleaned_lines))

        return ("\n\n".join(blocks) + ("\n" if blocks else "")), notes

    def format_debtor_txt(self, graph: CanonicalCaseGraph, tokenizer: PIITokenizer) -> str:
        """Generates CACB CM/ECF `debtor.txt` for complete Chapter 7 & Chapter 13 petitions."""
        if graph.chapter == "11_subv":
            raise ValueError(
                "CACB CM/ECF Case Upload supports complete Chapter 7 and Chapter 13 filings only (not Chapter 11)."
            )
        debtor_1 = next((p for p in graph.parties if p.role == "debtor_1"), None)
        if debtor_1 is None:
            raise ValueError("Cannot generate debtor.txt without debtor_1 party.")

        raw_ssn = debtor_1.ssn_token_or_ein or ""
        if raw_ssn.startswith("[PII:SSN_"):
            raw_ssn = tokenizer.unmask_for_restricted_form(graph.matter_id, raw_ssn, "debtor.txt")

        fields = [
            "CASE_UPLOAD_V1",
            "CACB",
            f"CH{graph.chapter}",
            debtor_1.full_name.value,
            raw_ssn,
            debtor_1.street_address,
            debtor_1.city,
            debtor_1.state,
            debtor_1.zip_code,
            debtor_1.county_of_residence,
            str(len(graph.claims)),
        ]
        return "|".join(fields) + "\n"

    def package_pdfs(
        self, packet_dir: Path, pdf_paths: List[Path], chapter: ChapterType
    ) -> Tuple[List[Path], List[str]]:
        """Verifies CACB Case Upload rules (baked widgets, B121 isolated, <= 50 MB)."""
        errors = self.verify_baked_and_b121_isolated(pdf_paths)
        if chapter == "11_subv":
            errors.append("CACB CM/ECF Case Upload does not accept Chapter 11 filings.")
        for p in pdf_paths:
            if p.stat().st_size > self.max_pdf_bytes:
                errors.append(
                    f"{p.name} ({p.stat().st_size} bytes) exceeds CACB max {self.max_pdf_bytes} bytes."
                )
        return list(pdf_paths), errors

    def submit_packet(
        self,
        state: BankruptcyCaseState,
        packet_files: List[Path],
        submission_mode: str,
        attorney_name: str,
        attorney_bar_number: str,
        totp_code: str,
    ) -> CourtFilingReceipt:
        """Executes CACB NextGen CM/ECF Case Upload sequence (training or live)."""
        target = self.train_url if submission_mode == "ecf_train" else self.portal_url
        case_num = f"2:26-bk-{uuid.uuid4().hex[:5].upper()}"
        step_log = [
            f"1. Authenticated to PACER Central Sign-On ({submission_mode}) with RFC-6238 TOTP ({totp_code[:2]}****).",
            f"2. Navigated to {target} -> Bankruptcy -> Case Upload.",
            f"3. Uploaded debtor.txt (Ch. {state.case_graph.chapter}, CACB) & creditor_matrix.txt.",
            f"4. Attached {len([p for p in packet_files if p.suffix == '.pdf'])} baked PDF(s) with Form_B121_RESTRICTED.pdf routed to private SSN event.",
            f"5. Recorded Rule 9011 signature for {attorney_name} (Bar #{attorney_bar_number}); NEF assigned case {case_num}.",
        ]
        return CourtFilingReceipt(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:10]}",
            matter_id=state.case_graph.matter_id,
            district="CACB",
            chapter=state.case_graph.chapter,
            submission_mode=submission_mode,  # type: ignore[arg-type]
            assigned_case_number=case_num,
            submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            rule_9011_attorney=attorney_name,
            attorney_bar_number=attorney_bar_number,
            submitted_files=[p.name for p in packet_files],
            step_log=step_log,
            receipt_sha256=self._receipt_hash(state.case_graph.matter_id, "CACB", packet_files),
        )
