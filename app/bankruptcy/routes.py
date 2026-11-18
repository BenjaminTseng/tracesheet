"""Standalone FastAPI routes and application factory for the Bankruptcy Case Workbench."""

from __future__ import annotations

import datetime
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.bankruptcy.models import (
    BankruptcyCaseState,
    ChapterType,
    CourtFilingReceipt,
    DistrictCode,
)
from app.bankruptcy.sample_cases import seed_bankruptcy_sample_cases
from app.bankruptcy.service import BankruptcyCaseService
from app.bankruptcy.vault import SubmissionMode
from app.llm import LLMProvider


class InitBankruptcyCaseRequest(BaseModel):
    """Payload to initialize a new bankruptcy case workspace."""

    matter_id: str = Field(min_length=1)
    chapter: ChapterType = "7"
    district: DistrictCode = "CACB"
    expected_filing_date: Optional[datetime.date] = None


class ExtractBankruptcyCaseRequest(BaseModel):
    """Payload to run ingestion + extraction + audit compilation on a matter."""

    chapter: Optional[ChapterType] = None
    district: Optional[DistrictCode] = None
    expected_filing_date: Optional[datetime.date] = None


class OverrideFieldRequest(BaseModel):
    """Payload to override a `ProvenanceField` with an audited `HumanOverrideRecord`."""

    field_path: str = Field(min_length=1)
    new_value: Any
    actor_name: str = Field(min_length=1)
    actor_role: str = "paralegal"
    rationale: str = Field(min_length=5)


class AnswerQuestionRequest(BaseModel):
    """Payload to answer an `EmergingQuestionItem`."""

    selected_option: str = Field(min_length=1)
    actor_name: str = Field(min_length=1)
    actor_role: str = "paralegal"
    rationale: str = Field(min_length=5)
    payload: Dict[str, Any] = Field(default_factory=dict)


class ResolveTensionRequest(BaseModel):
    """Payload to resolve a critical contradiction `TensionObject`."""

    actor_name: str = Field(min_length=1)
    actor_role: str = "paralegal"
    rationale: str = Field(min_length=5)


class CompilePacketRequest(BaseModel):
    """Payload to compile court-ready baked PDFs, matrices, and `field_lineage.json`."""

    allow_draft: bool = False


class SaveCredentialRequest(BaseModel):
    """Payload to store a PACER/CM/ECF credential profile + TOTP seed in the local vault."""

    mode: SubmissionMode
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    totp_secret: str = Field(min_length=8)
    sponsoring_bar_number: Optional[str] = None


class SubmitCourtRequest(BaseModel):
    """Payload for attorney Rule 9011 attestation and district court submission."""

    submission_mode: SubmissionMode = "ecf_train"
    attorney_name: str = Field(min_length=1)
    attorney_bar_number: str = Field(min_length=1)
    attested: bool = True


def create_bankruptcy_app(
    base_dir: Optional[Path] = None,
    llm_provider: Optional[LLMProvider] = None,
    seed_samples: bool = True,
) -> FastAPI:
    """Creates and configures the standalone Bankruptcy Case Workbench FastAPI application.

    Args:
        base_dir: Workspace root containing `templates/`, `static/`, `matters/`, `canonical/`.
        llm_provider: Optional `LLMProvider` instance for live LLM extraction/decisions.
        seed_samples: Whether to pre-seed sample CA bankruptcy cases when missing.

    Returns:
        Configured `FastAPI` instance ready to run via Uvicorn or `TestClient`.
    """
    root_dir = base_dir or Path(__file__).resolve().parent.parent.parent
    templates = Jinja2Templates(directory=str(root_dir / "templates"))
    service = BankruptcyCaseService(base_dir=root_dir, llm_provider=llm_provider)

    if seed_samples:
        seed_bankruptcy_sample_cases(service)

    api = FastAPI(
        title="Bankruptcy Case Workbench (v1)",
        description="Standalone audit-grounded personal & small-business bankruptcy filing workbench.",
        version="1.0.0",
    )
    api.state.bankruptcy_service = service

    static_dir = root_dir / "static"
    if static_dir.exists():
        api.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def bankruptcy_index(request: Request) -> HTMLResponse:
        """Serves the standalone Bankruptcy Case Workbench shell."""
        return templates.TemplateResponse(request, "bankruptcy.html")

    @router.get("/api/v1/bankruptcy/tables")
    async def list_statutory_tables() -> Dict[str, Any]:
        """Lists loaded effective-dated statutory reference tables and SHA-256 checksums."""
        return {"tables": service.registry.list_metadata()}

    @router.post("/api/v1/bankruptcy/tables/sync")
    async def sync_statutory_tables() -> Dict[str, Any]:
        """Refreshes, SHA-256 verifies, and checks staleness across statutory reference tables."""
        return service.registry.sync_statutory_tables()

    @router.get("/api/v1/bankruptcy/tables/taxonomy")
    async def get_schedule_ab_taxonomy() -> Dict[str, Any]:
        """Returns Official Form 106A/B 53-line taxonomy mapped to Best Case 35 categories."""
        return service.registry.get_schedule_ab_taxonomy()

    @router.get("/api/v1/bankruptcy/matters")
    async def list_bankruptcy_matters() -> Dict[str, Any]:
        """Lists all initialized bankruptcy matters."""
        return {"matters": service.list_cases()}

    @router.post("/api/v1/bankruptcy/matters", response_model=BankruptcyCaseState)
    async def init_bankruptcy_matter(req: InitBankruptcyCaseRequest) -> BankruptcyCaseState:
        """Initializes a new bankruptcy case workspace."""
        return service.init_case(
            matter_id=req.matter_id,
            chapter=req.chapter,
            district=req.district,
            expected_filing_date=req.expected_filing_date,
        )

    @router.get("/api/v1/bankruptcy/matters/{matter_id}/case", response_model=BankruptcyCaseState)
    async def get_bankruptcy_case(matter_id: str) -> BankruptcyCaseState:
        """Returns complete `BankruptcyCaseState` including Bezier `CompiledBundle`."""
        return service.load_case(matter_id)

    @router.get("/api/v1/bankruptcy/matters/{matter_id}/files")
    async def list_case_files(matter_id: str) -> Dict[str, Any]:
        """Lists raw uploaded files for a bankruptcy matter."""
        _, raw_dir, _, _ = service.ingestor._matter_dirs(matter_id)
        files = sorted(p.name for p in raw_dir.iterdir() if p.is_file()) if raw_dir.exists() else []
        return {"matter_id": matter_id, "files": files}

    @router.get("/api/v1/bankruptcy/matters/{matter_id}/files/{filename}/raw")
    async def get_raw_case_file(matter_id: str, filename: str) -> FileResponse:
        """Serves a raw uploaded client PDF/spreadsheet for the `SourceInspectorDrawer`."""
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename or ".." in filename:
            raise HTTPException(status_code=400, detail="Invalid filename.")
        _, raw_dir, _, _ = service.ingestor._matter_dirs(matter_id)
        fpath = raw_dir / safe_name
        if not fpath.exists():
            raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found.")
        media_type, _ = mimetypes.guess_type(str(fpath))
        return FileResponse(path=fpath, media_type=media_type or "application/octet-stream", filename=safe_name)

    @router.post("/api/v1/bankruptcy/matters/{matter_id}/upload")
    async def upload_case_files(
        matter_id: str, files: List[UploadFile] = File(...)
    ) -> Dict[str, Any]:
        """Uploads uncategorized raw client PDFs/CSVs into `matters/<id>/inputs/raw/`."""
        matter_dir = service.ingestor.create_matter(matter_id)
        raw_dir = matter_dir / "inputs" / "raw"
        saved: List[str] = []
        for up in files:
            safe_name = Path(up.filename or "").name
            if not safe_name:
                continue
            data = await up.read()
            (raw_dir / safe_name).write_bytes(data)
            saved.append(safe_name)
        manifest = service.ingestor.ingest_matter(matter_id)
        return {"matter_id": matter_id, "uploaded": saved, "manifest": manifest}

    @router.post("/api/v1/bankruptcy/matters/{matter_id}/extract", response_model=BankruptcyCaseState)
    async def extract_case(
        matter_id: str, req: Optional[ExtractBankruptcyCaseRequest] = None
    ) -> BankruptcyCaseState:
        """Runs entity-first extraction, citation verification, calculators, and audit compilation."""
        body = req or ExtractBankruptcyCaseRequest()
        return service.extract_matter(
            matter_id=matter_id,
            chapter=body.chapter,
            district=body.district,
            expected_filing_date=body.expected_filing_date,
        )

    @router.post("/api/v1/bankruptcy/matters/{matter_id}/recalculate", response_model=BankruptcyCaseState)
    async def recalculate_case(matter_id: str) -> BankruptcyCaseState:
        """Deterministically recomputes calculators, audits, and readiness gate (<100ms)."""
        return service.recompute_state(service.load_case(matter_id))

    @router.patch("/api/v1/bankruptcy/matters/{matter_id}/fields", response_model=BankruptcyCaseState)
    async def override_case_field(
        matter_id: str, req: OverrideFieldRequest
    ) -> BankruptcyCaseState:
        """Overrides a `ProvenanceField` with an audited `HumanOverrideRecord`."""
        return service.override_field(
            matter_id=matter_id,
            field_path=req.field_path,
            new_value=req.new_value,
            actor_name=req.actor_name,
            actor_role=req.actor_role,
            rationale=req.rationale,
        )

    @router.post(
        "/api/v1/bankruptcy/matters/{matter_id}/questions/{question_id}/answer",
        response_model=BankruptcyCaseState,
    )
    async def answer_emerging_question(
        matter_id: str, question_id: str, req: AnswerQuestionRequest
    ) -> BankruptcyCaseState:
        """Answers a relational/forensic `EmergingQuestionItem` and recompiles."""
        return service.answer_question(
            matter_id=matter_id,
            question_id=question_id,
            selected_option=req.selected_option,
            actor_name=req.actor_name,
            actor_role=req.actor_role,
            rationale=req.rationale,
            payload=req.payload,
        )

    @router.post(
        "/api/v1/bankruptcy/matters/{matter_id}/tensions/{tension_id}/resolve",
        response_model=BankruptcyCaseState,
    )
    async def resolve_contradiction(
        matter_id: str, tension_id: str, req: ResolveTensionRequest
    ) -> BankruptcyCaseState:
        """Resolves a flagged `TensionObject` with rationale and updates readiness."""
        return service.resolve_tension(
            matter_id=matter_id,
            tension_id=tension_id,
            actor_name=req.actor_name,
            actor_role=req.actor_role,
            rationale=req.rationale,
        )

    @router.post("/api/v1/bankruptcy/matters/{matter_id}/declaration", response_model=BankruptcyCaseState)
    async def upload_signed_declaration(
        matter_id: str, file: UploadFile = File(...)
    ) -> BankruptcyCaseState:
        """Uploads the wet-signed Electronic Filing Declaration required for Rule 9011 submission."""
        raw_bytes = await file.read()
        return service.record_signed_declaration(matter_id, raw_bytes)

    @router.post("/api/v1/bankruptcy/matters/{matter_id}/compile-packet")
    async def compile_filing_packet(
        matter_id: str, req: Optional[CompilePacketRequest] = None
    ) -> Dict[str, Any]:
        """Enforces strict `FilingReadinessGate` and compiles baked PDFs, matrices, and lineage."""
        body = req or CompilePacketRequest()
        return service.compile_packet(matter_id, allow_draft=body.allow_draft)

    @router.get("/api/v1/bankruptcy/matters/{matter_id}/packet/files/{filename}")
    async def download_packet_file(matter_id: str, filename: str) -> FileResponse:
        """Serves a compiled PDF, `creditor_matrix.txt`, `debtor.txt`, or `field_lineage.json`."""
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename or ".." in filename:
            raise HTTPException(status_code=400, detail="Invalid packet filename.")
        fpath = service.matters_root / matter_id / "packet" / safe_name
        if not fpath.exists():
            raise HTTPException(status_code=404, detail=f"Packet file '{safe_name}' not found.")
        media_type, _ = mimetypes.guess_type(str(fpath))
        return FileResponse(path=fpath, media_type=media_type or "application/octet-stream", filename=safe_name)

    @router.get("/api/v1/bankruptcy/credentials")
    async def list_credentials() -> Dict[str, Any]:
        """Lists redacted PACER/CM/ECF credential profiles in the internal vault."""
        return {"profiles": service.vault.list_profiles_redacted()}

    @router.post("/api/v1/bankruptcy/credentials")
    async def save_credential(req: SaveCredentialRequest) -> Dict[str, Any]:
        """Saves an encrypted PACER/CM/ECF credential profile + TOTP secret."""
        entry = service.vault.save_credential(
            mode=req.mode,
            username=req.username,
            password=req.password,
            totp_secret=req.totp_secret,
            sponsoring_bar_number=req.sponsoring_bar_number,
        )
        return {"mode": entry.mode, "username": entry.username, "status": "saved"}

    @router.post("/api/v1/bankruptcy/matters/{matter_id}/submit", response_model=CourtFilingReceipt)
    async def submit_filing_packet(
        matter_id: str, req: SubmitCourtRequest
    ) -> CourtFilingReceipt:
        """Validates Rule 9011 sign-off and executes CACB or CAEB filing submission."""
        return service.submit_to_court(
            matter_id=matter_id,
            submission_mode=req.submission_mode,
            attorney_name=req.attorney_name,
            attorney_bar_number=req.attorney_bar_number,
            attested=req.attested,
        )

    api.include_router(router)
    return api
