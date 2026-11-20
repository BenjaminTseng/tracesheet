"""Blueprint store helpers for the Broadsheet Research compiler."""

from __future__ import annotations

import re
from fastapi import HTTPException

from app.compilers.research.pipeline import BlueprintStore


def sanitize_slug(raw: str) -> str:
    """Converts a user-entered matter, bundle, or blueprint name into a safe filesystem slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip()).strip("_").lower()
    if not slug:
        raise HTTPException(status_code=422, detail="Invalid identifier slug.")
    return slug


__all__ = ["BlueprintStore", "sanitize_slug"]
