"""Application entry point and CLI runner for the Audit-Grounded Document Viewer.

Follows the configuration and logging protocol:
`uv run python main.py --host 127.0.0.1 --port 8000 --name jd_screen`
"""

from __future__ import annotations

import argparse
import datetime
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

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


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance.

    Returns:
        Configured `FastAPI` application with mounted static assets and routes.
    """
    application = FastAPI(
        title="Audit-Grounded Spatial Document Canvas",
        version="0.1.0",
        description="Bounded spatial canvas for introspecting AI-generated artifacts and their provenance DAG.",
    )
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    application.include_router(router)
    return application


app = create_app()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments for server configuration and logging.

    Args:
        argv: Optional list of CLI argument strings.

    Returns:
        Parsed `argparse.Namespace` object.
    """
    parser = argparse.ArgumentParser(
        description="Run the Audit-Grounded Spatial Document Canvas server."
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
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    log_path = configure_logging(prefix=args.name)
    logging.getLogger("jd_screen").info(
        "Starting server on %s:%d (log=%s)", args.host, args.port, log_path
    )
    uvicorn.run("main:app", host=args.host, port=args.port, reload=False)
