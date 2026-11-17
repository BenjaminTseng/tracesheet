"""Shared core platform extensions for audit-grounded applications.

Provides reusable infrastructure across applications built on `jd_screen`:
- `pii`: Deterministic text PII tokenization and restricted re-hydration vault.
- `ocr`: Pluggable OCR extraction interface (Local CPU, Modal GPU, Mock).
- `tables`: Effective-dated JSON statutory reference table registry with SHA-256 verification.
"""
