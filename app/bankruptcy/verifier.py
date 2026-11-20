"""Compatibility re-export of `app.core.verifier` (migrated to `app.core.verifier` in Commit 1)."""

from app.core.verifier import (  # noqa: F401
    IndexedMatterCorpus,
    ObservationVerifier,
    _digits_and_decimal,
    _normalize_ws_lower,
)
