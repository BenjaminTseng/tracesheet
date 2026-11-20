"""Unified application entrypoint & CLI runner for the Audit-Grounded Verification Platform.

Examples:
- Web UI Server (Bankruptcy default + Research co-mounted):
    uv run python main.py --host 127.0.0.1 --port 8000 --apps all --default-app bankruptcy
- Bankruptcy-only partner launch:
    uv run python main.py --host 127.0.0.1 --port 8000 --apps bankruptcy
- Verify reference tables:
    uv run python main.py --sync-tables bankruptcy
- CLI Ingestion / Research Q&A:
    uv run python main.py --ingest-matter legal_motion_1332
    uv run python main.py --matter legal_motion_1332 --ask "Evaluate diversity"
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI
import uvicorn

from app.compilers.research.pipeline import AuditPipelineRunner
from app.core.ingest import CanonicalIngestor, CanonicalRouter, MatterIngestor
from app.core.llm import create_llm_provider
from app.core.tables import ReferenceTableRegistry, StatutoryTableRegistry
from app.server import create_platform_app, parse_enabled_apps

load_dotenv(dotenv_path=find_dotenv(usecwd=True), override=False)

BASE_DIR = Path(__file__).resolve().parent


def configure_logging(prefix: str = "log") -> Path:
    """Configures file and console logging following `[prefix-]YYYYMMDDHHmm.log`."""
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
    apps: Optional[str] = None,
    default_app: Optional[str] = None,
    seed_samples: bool = True,
) -> FastAPI:
    """Creates the unified FastAPI platform application."""
    raw_apps = apps if apps is not None else os.getenv("JD_SCREEN_APPS", "all")
    resolved_default = default_app or os.getenv("JD_SCREEN_DEFAULT_APP", "bankruptcy")
    return create_platform_app(
        base_dir=BASE_DIR,
        enabled_apps=parse_enabled_apps(raw_apps),
        default_app=resolved_default,
        llm_config={"provider": provider, "model": model, "api_key": api_key},
        seed_samples=seed_samples,
    )


app = create_app()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI flags for unified server, app selection, table sync, ingest, and Q&A."""
    parser = argparse.ArgumentParser(
        description="Run the unified Audit-Grounded Verification Platform server or CLI tools."
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8000, help="TCP port to bind (default: 8000).")
    parser.add_argument("--name", type=str, default="jd_screen", help="Log filename prefix.")
    parser.add_argument(
        "--apps",
        type=str,
        default="all",
        help="Enabled compiler apps (`all`, `bankruptcy`, `research`, or comma-separated list).",
    )
    parser.add_argument(
        "--default-app",
        type=str,
        default="bankruptcy",
        help="Default UI compiler route redirected from `/` (default: bankruptcy).",
    )
    parser.add_argument(
        "--sync-tables",
        type=str,
        default=None,
        help="Verify SHA-256 checksums and staleness for `canonical/tables/<domain>/`, print JSON, and exit.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="gemini",
        choices=["gemini", "anthropic", "openai", "mock"],
        help="LLM backend provider for agentic stages (default: gemini).",
    )
    parser.add_argument("--model", type=str, default=None, help="Model identifier override.")
    parser.add_argument("--api-key", type=str, default=None, help="Optional API key override.")
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
        help="Combined with --ingest-canonical, purge old encoded canonical artifacts before rebuilding.",
    )
    parser.add_argument("--matter", type=str, default=None, help="Matter ID for `--ask`.")
    parser.add_argument("--ask", type=str, default=None, help="Run the 4-stage research pipeline from CLI.")
    parser.add_argument("--output-bundle", type=str, default=None, help="Optional bundle slug for `--ask`.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    log_path = configure_logging(prefix=args.name)
    logger = logging.getLogger("jd_screen")

    ingestor = MatterIngestor(BASE_DIR / "matters")
    canonical_router = CanonicalRouter(BASE_DIR / "canonical")
    canonical_ingestor = CanonicalIngestor(BASE_DIR / "canonical")

    if args.sync_tables:
        domain = args.sync_tables.strip().lower()
        tdir = BASE_DIR / "canonical" / "tables" / domain
        reg = (
            StatutoryTableRegistry(tdir)
            if domain == "bankruptcy"
            else ReferenceTableRegistry(tdir)
        )
        print(json.dumps(reg.sync_tables(), indent=2))
    elif args.ingest_canonical:
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
        os.environ["JD_SCREEN_APPS"] = args.apps
        os.environ["JD_SCREEN_DEFAULT_APP"] = args.default_app
        app = create_app(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            apps=args.apps,
            default_app=args.default_app,
        )
        logger.info(
            "Starting unified server on %s:%d apps=%s default=%s provider=%s model=%s (log=%s)",
            args.host,
            args.port,
            args.apps,
            args.default_app,
            args.provider,
            args.model or "default",
            log_path,
        )
        uvicorn.run(app, host=args.host, port=args.port, reload=False)
