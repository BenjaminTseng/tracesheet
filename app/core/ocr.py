"""Pluggable OCR extraction interface for scanned PDFs and page images.

Supports deterministic `[x1, y1, x2, y2]` bounding-box extraction so scanned
client uploads (paystubs, tax returns, bank statements) integrate into the exact
same `SourceLocator` provenance and `SourceInspectorDrawer` pipeline as native
digital PDFs, while keeping raw images out of external text LLM calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

import pymupdf
from pydantic import BaseModel, Field


class OCRBlock(BaseModel):
    """Single OCR-extracted text passage with normalized page bounding box.

    Attributes:
        text: Extracted UTF-8 text content of the region.
        page: 1-based page number inside the source PDF.
        bounding_box: Page coordinates `[x1, y1, x2, y2]` in PDF point space.
        confidence: Recognition confidence score between `0.0` and `1.0`.
    """

    text: str
    page: int
    bounding_box: List[int] = Field(min_length=4, max_length=4)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OCRProvider(ABC):
    """Abstract interface for page-level OCR extraction returning coordinates."""

    @abstractmethod
    def extract_page_blocks(self, pdf_path: Path, page_number: int) -> List[OCRBlock]:
        """Extracts coordinate-stamped text blocks from one PDF page.

        Args:
            pdf_path: Absolute or workspace-relative path to the source PDF.
            page_number: 1-based page number to inspect.

        Returns:
            Ordered list of `OCRBlock` records with `[x1, y1, x2, y2]` coordinates.
        """


class LocalOCRProvider(OCRProvider):
    """Local PyMuPDF/CPU fallback OCR provider.

    Extracts native text blocks if present and attempts PyMuPDF built-in OCR
    when Tesseract/OCR language data is available on the host; degrades cleanly
    to an empty list on purely raster pages when no OCR binary is installed.
    """

    def __init__(self, dpi: int = 200, language: str = "eng") -> None:
        """Initializes the local OCR provider.

        Args:
            dpi: Rasterization DPI when running Tesseract OCR on image pages.
            language: Tesseract language pack identifier (default `"eng"`).
        """
        self.dpi = dpi
        self.language = language

    def extract_page_blocks(self, pdf_path: Path, page_number: int) -> List[OCRBlock]:
        """Extracts text blocks from `page_number` using PyMuPDF or local Tesseract.

        Args:
            pdf_path: Path to the source PDF file.
            page_number: 1-based page number to inspect.

        Returns:
            List of `OCRBlock` records with integer PDF-point bounding boxes.
        """
        blocks: List[OCRBlock] = []
        with pymupdf.open(str(pdf_path)) as doc:
            if page_number < 1 or page_number > len(doc):
                return []
            page = doc[page_number - 1]

            # First check standard PyMuPDF text blocks (handles PDFs where
            # pdfplumber misses custom font encodings or XObjects).
            for raw_blk in page.get_text("blocks"):
                x0, y0, x1, y1, text, _, block_type = raw_blk[:7]
                cleaned = (text or "").strip()
                if block_type == 0 and cleaned:
                    blocks.append(
                        OCRBlock(
                            text=cleaned,
                            page=page_number,
                            bounding_box=[int(x0), int(y0), int(x1), int(y1)],
                            confidence=1.0,
                        )
                    )
            if blocks:
                return blocks

            # Next attempt PyMuPDF's Tesseract TextPage OCR if installed on host.
            try:
                tp = page.get_textpage_ocr(
                    flags=0, language=self.language, dpi=self.dpi, full=True
                )
                for raw_blk in page.get_text("blocks", textpage=tp):
                    x0, y0, x1, y1, text, _, block_type = raw_blk[:7]
                    cleaned = (text or "").strip()
                    if block_type == 0 and cleaned:
                        blocks.append(
                            OCRBlock(
                                text=cleaned,
                                page=page_number,
                                bounding_box=[int(x0), int(y0), int(x1), int(y1)],
                                confidence=0.9,
                            )
                        )
            except Exception:
                # Host lacks Tesseract tessdata; return empty list cleanly so callers
                # can route to ModalOCRProvider or flag the raster PDF cleanly.
                return []
        return blocks


class ModalOCRProvider(OCRProvider):
    """Client adapter for self-hosted GPU OCR running on Modal (`uv run modal deploy`).

    Renders raster pages locally and dispatches compressed PNG bytes to a
    deployed Modal inference function (`jd-screen-ocr` / `extract_page_ocr`),
    ensuring sensitive client documents stay inside the firm's Modal tenant.
    """

    def __init__(
        self,
        app_name: str = "jd-screen-ocr",
        function_name: str = "extract_page_ocr",
        dpi: int = 200,
    ) -> None:
        """Initializes the Modal GPU OCR provider reference.

        Args:
            app_name: Deployed Modal app name.
            function_name: Remote Modal function name returning OCR blocks.
            dpi: Rendering resolution sent to the remote GPU worker.
        """
        self.app_name = app_name
        self.function_name = function_name
        self.dpi = dpi

    def extract_page_blocks(self, pdf_path: Path, page_number: int) -> List[OCRBlock]:
        """Renders `page_number` to PNG and invokes the deployed Modal OCR function.

        Args:
            pdf_path: Path to the source PDF file.
            page_number: 1-based page number to inspect.

        Returns:
            List of `OCRBlock` records returned by the Modal worker.

        Raises:
            RuntimeError: If `modal` is not installed or the remote app is unreachable.
        """
        try:
            import modal  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Modal SDK is required for ModalOCRProvider (`uv add modal`)."
            ) from exc

        with pymupdf.open(str(pdf_path)) as doc:
            if page_number < 1 or page_number > len(doc):
                return []
            page = doc[page_number - 1]
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            pix = page.get_pixmap(dpi=self.dpi)
            png_bytes = pix.tobytes("png")

        fn = modal.Function.from_name(self.app_name, self.function_name)
        raw_results = fn.remote(
            png_bytes=png_bytes,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
        )
        return [OCRBlock.model_validate(item) for item in raw_results]


class MockOCRProvider(OCRProvider):
    """Deterministic in-memory OCR provider for offline tests of scanned PDFs."""

    def __init__(self, page_map: Optional[Dict[TupleKey, List[OCRBlock]]] = None) -> None:
        """Initializes the mock OCR provider with scripted page responses.

        Args:
            page_map: Mapping of `(pdf_basename, page_number)` to `OCRBlock` lists.
        """
        self.page_map: Dict[tuple[str, int], List[OCRBlock]] = page_map or {}

    def extract_page_blocks(self, pdf_path: Path, page_number: int) -> List[OCRBlock]:
        """Returns scripted `OCRBlock` items for `(pdf_path.name, page_number)`.

        Args:
            pdf_path: Path to the PDF file being indexed.
            page_number: 1-based page number.

        Returns:
            Matching scripted `OCRBlock` list, or empty list if none registered.
        """
        return list(self.page_map.get((pdf_path.name, page_number), []))


TupleKey = tuple[str, int]
