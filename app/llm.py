"""Temporary compatibility shim delegating to `app.core.llm` (removed in Commit 3)."""

from app.core.llm import *  # noqa: F401, F403
