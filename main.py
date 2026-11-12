"""Application entry point and CLI runner for the Audit-Grounded Document Platform.

Follows the configuration and logging protocol:
- Web UI Server: `uv run python main.py --host 127.0.0.1 --port 8000 --name jd_screen`
- CLI Ingestion: `uv run python main.py --ingest-matter legal_motion_1332`
- CLI Agentic Q&A: `uv run python main.py --matter legal_motion_1332 --ask "Evaluate diversity"`
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.llm import create_llm_provider
from app.pipeline import AuditPipelineRunner
from app.routes import router

BASE_DIR = Path(__file__).resolve().parent


def configure_logging(prefix: str = "log") -> Path:
    """Configures file and console logging following `[prefix-]YYYYMMDDHHmm.log`.

    Args:
        prefix: Filename prefix specified via CLI `--name` argument.

    Returns:
        Path to the created log file.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{prefix}-{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return log_file


def create_app(
    provider: str = "gemini",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> FastAPI:
    """Creates and configures the FastAPI application instance.

    Args:
        provider: Default LLM backend name (`gemini`, `anthropic`, `openai`, `mock`).
        model: Optional model identifier override.
        api_key: Optional API key override.

    Returns:
        Configured `FastAPI` application with mounted static assets and routes.
    """
    application = FastAPI(
        title="Audit-Grounded Spatial Document Canvas",
        version="0.2.0",
        description="Bounded spatial canvas and agentic Q&A pipeline with full citation traceability.",
    )
    application.state.llm_config = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
    }
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    application.include_router(router)
    return application


app = create_app()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments for server, provider, ingestion, and CLI Q&A.

    Args:
        argv: Optional list of CLI argument strings.

    Returns:
        Parsed `argparse.Namespace` object.
    """
    parser = argparse.ArgumentParser(
        description="Run the Audit-Grounded Spatial Document Canvas server or CLI pipeline."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="TCP port to bind (default: 8000).",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="jd_screen",
        help="Prefix for generated log files (default: jd_screen).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="gemini",
        choices=["gemini", "anthropic", "openai", "mock"],
        help="LLM backend provider for agentic stages (default: gemini).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model identifier override (e.g., gemini-4-argon, gemini-4-carbon, gemini-3.8-flash).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Optional API key override (defaults to GEMINI_API_KEY / provider env var).",
    )
    parser.add_argument(
        "--ingest-matter",
        type=str,
        default=None,
        help="Run deterministic coordinate ingestion on the specified matter ID and exit.",
    )
    parser.add_argument(
        "--ingest-canonical",
        action="store_true",
        help="Encode raw files in canonical/raw/ into [AUTH:...] Markdown and rebuild canonical/INDEX.md, then exit.",
    )
    parser.add_argument(
        "--purge-canonical",
        action="store_true",
        help="Combined with --ingest-canonical, remove old encoded canonical .md files and INDEX.md before rebuilding.",
    )
    parser.add_argument(
        "--matter",
        type=str,
        default=None,
        help="Project matter ID to query when running `--ask`.",
    )
    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Run the 4-stage agentic pipeline for a question `(c)` from CLI and exit.",
    )
    parser.add_argument(
        "--output-bundle",
        type=str,
        default=None,
        help="Optional bundle slug when saving `--ask` output.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    log_path = configure_logging(prefix=args.name)
    logger = logging.getLogger("jd_screen")

    ingestor = MatterIngestor(BASE_DIR / "matters")
    canonical_router = CanonicalRouter(BASE_DIR / "canonical")
    canonical_ingestor = CanonicalIngestor(BASE_DIR / "canonical")

    if args.ingest_canonical:
        optional_llm = None
        if args.provider != "mock" and (
            args.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        ):
            try:
                optional_llm = create_llm_provider(
                    provider_name=args.provider,
                    model=args.model,
                    api_key=args.api_key,
                )
            except Exception as exc:
                logger.warning("Proceeding with deterministic canonical ingestion (%s)", exc)
        summary = canonical_ingestor.ingest_corpus(
            purge_encoded=args.purge_canonical, llm=optional_llm
        )
        print(json.dumps(summary, indent=2))
    elif args.ingest_matter:
        manifest = ingestor.ingest_matter(args.ingest_matter)
        print(json.dumps(manifest, indent=2))
    elif args.ask:
        if not args.matter:
            raise SystemExit("Error: --matter <matter_id> is required when using --ask.")
        llm = create_llm_provider(
            provider_name=args.provider,
            model=args.model,
            api_key=args.api_key,
        )
        runner = AuditPipelineRunner(llm, canonical_router, ingestor)
        bundle = runner.run_full_pipeline(
            matter_id=args.matter,
            question=args.ask,
            bundle_id=args.output_bundle,
            progress_callback=lambda stage, msg: print(f"[{stage}] {msg}"),
        )
        saved = BASE_DIR / "matters" / args.matter / "bundles" / f"{bundle.bundle_id}.json"
        print(
            json.dumps(
                {
                    "bundle_id": bundle.bundle_id,
                    "title": bundle.artifact.title,
                    "total_claims": bundle.audit_summary.total_claims,
                    "verified_count": bundle.audit_summary.verified_count,
                    "saved_path": str(saved),
                },
                indent=2,
            )
        )
    else:
        app.state.llm_config = {
            "provider": args.provider,
            "model": args.model,
            "api_key": args.api_key,
        }
        logger.info(
            "Starting server on %s:%d provider=%s model=%s (log=%s)",
            args.host,
            args.port,
            args.provider,
            args.model or "default",
            log_path,
        )
        uvicorn.run("main:app", host=args.host, port=args.port, reload=False)
