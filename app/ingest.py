"""Temporary compatibility shim delegating to `app.core.ingest` (removed in Commit 3)."""

from app.core.ingest import *  # noqa: F401, F403
from app.core.ingest import LOCATOR_COMMENT_RE, _normalize_for_match, _sha256_short  # noqa: F401
