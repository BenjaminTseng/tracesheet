"""Standalone entrypoint for the Bankruptcy Case Workbench Webapp (`bankruptcy_main.py`).

Runs completely independently of the Broadsheet Research Webapp (`main.py`) on
port `8001` by default, sharing `app/core/` verification primitives while serving
`templates/bankruptcy.html` and `/api/v1/bankruptcy/*`.

Usage:
    uv run python bankruptcy_main.py --host 127.0.0.1 --port 8001 --name bk_workbench
"""

from __future__ import annotations

import argparse
import datetime
import logging
from pathlib import Path
from typing import List, Optional

import uvicorn
from dotenv import load_dotenv

from app.compilers.bankruptcy.routes import create_bankruptcy_app
from app.core.llm import create_llm_provider


def configure_logging(log_prefix: str = "bk_workbench") -> Path:
    """Initializes standard logging writing to `logs/<prefix>-YYYYMMDDHHmm.log`."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
    log_path = log_dir / f"{log_prefix}-{stamp}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    return log_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses CLI flags for configuring the standalone bankruptcy workbench server."""
    parser = argparse.ArgumentParser(
        description="Standalone Bankruptcy Case Workbench Webapp (Ch. 7 & 13, CACB/CAEB)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host address")
    parser.add_argument("--port", type=int, default=8001, help="Bind port (default 8001)")
    parser.add_argument("--name", default="bk_workbench", help="Log file prefix")
    parser.add_argument(
        "--provider",
        default="mock",
        choices=["mock", "gemini", "anthropic", "openai"],
        help="Optional LLM provider for unstructured extraction & rubric evaluation",
    )
    parser.add_argument("--api-key", default=None, help="Optional API key override")
    parser.add_argument("--model", default=None, help="Optional LLM model override")
    parser.add_argument(
        "--sync-statutory-tables",
        action="store_true",
        help="Verify SHA-256 integrity and effective-date staleness across statutory tables, print JSON summary, and exit",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """Launches the standalone Bankruptcy Case Workbench Uvicorn server or runs table sync."""
    load_dotenv(Path(__file__).resolve().parent / ".env")
    args = parse_args(argv)
    if args.sync_statutory_tables:
        import json
        from app.core.tables import StatutoryTableRegistry

        reg = StatutoryTableRegistry(Path(__file__).resolve().parent / "canonical" / "tables" / "bankruptcy")
        print(json.dumps(reg.sync_statutory_tables(), indent=2))
        return

    configure_logging(args.name)
    llm_provider = create_llm_provider(
        provider_name=args.provider,
        api_key=args.api_key,
        model=args.model,
    )
    app = create_bankruptcy_app(
        base_dir=Path(__file__).resolve().parent,
        llm_provider=llm_provider,
        seed_samples=True,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
