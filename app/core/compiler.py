"""Pluggable compiler protocol and shared platform runtime context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol, runtime_checkable

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.ingest import CanonicalRouter, MatterIngestor
from app.core.llm import LLMProvider
from app.core.provenance import CaseSummaryRow


class AppDescriptor(BaseModel):
    """Metadata describing one mounted compiler vertical exposed to `/api/v1/apps`."""

    app_id: str
    label: str
    description: str
    ui_route: str
    api_prefix: str
    gate_mode: str = "strict_blocking"


@dataclass
class PlatformContext:
    """Shared infrastructure injected into every compiler application."""

    base_dir: Path
    matters_root: Path
    canonical_dir: Path
    tables_root: Path
    ingestor: MatterIngestor
    canonical_router: CanonicalRouter
    llm_provider: LLMProvider


@runtime_checkable
class CompilerApp(Protocol):
    """Contract implemented by every vertical compiler mounted on the platform server."""

    descriptor: AppDescriptor

    def list_cases(self) -> List[CaseSummaryRow]:
        """Returns standardized `CaseSummaryRow` entries owned by this compiler."""
        ...

    def build_router(self, ctx: PlatformContext) -> APIRouter:
        """Builds the FastAPI router mounted at `descriptor.api_prefix`."""
        ...
