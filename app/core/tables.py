"""Effective-dated JSON reference table registry with SHA-256 verification.

Provides the generic `ReferenceTableRegistry` (supporting arbitrary compiler
domains under `canonical/tables/<domain>/`) and `StatutoryTableRegistry` for
federal/state bankruptcy thresholds, means-test standards, exemptions, and rules.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class TableIntegrityError(RuntimeError):
    """Raised when a JSON reference table fails schema or checksum verification."""


class ReferenceTableRegistry:
    """Loads, verifies, and selects effective-dated reference JSON tables."""

    REQUIRED_TABLES: Tuple[str, ...] = ()

    def __init__(
        self,
        tables_dir: Path,
        required_tables: Optional[Tuple[str, ...]] = None,
    ) -> None:
        """Initializes a domain reference table registry.

        Args:
            tables_dir: Directory containing `*.json` reference tables.
            required_tables: Optional explicit tuple of required table filenames.
        """
        self.tables_dir = tables_dir
        self.required_tables: Tuple[str, ...] = (
            required_tables if required_tables is not None else self.REQUIRED_TABLES
        )
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._hashes: Dict[str, str] = {}

    @staticmethod
    def _sha256_bytes(raw: bytes) -> str:
        """Computes full SHA-256 hex digest with `sha256:` prefix."""
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"

    def load_table(self, filename: str, expected_sha256: Optional[str] = None) -> Dict[str, Any]:
        """Loads and caches a JSON reference table, verifying its SHA-256 if provided.

        Args:
            filename: Basename of the JSON file under `self.tables_dir`.
            expected_sha256: Optional expected `sha256:<hex>` checksum for tamper detection.

        Returns:
            Parsed JSON dictionary.

        Raises:
            FileNotFoundError: If the table file does not exist.
            TableIntegrityError: If checksum fails or JSON is malformed.
        """
        path = self.tables_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Statutory reference table not found: {path}")

        raw = path.read_bytes()
        digest = self._sha256_bytes(raw)
        if expected_sha256 and digest != expected_sha256:
            raise TableIntegrityError(
                f"Checksum mismatch for {filename}: expected {expected_sha256}, got {digest}"
            )

        if filename in self._cache and self._hashes.get(filename) == digest:
            return self._cache[filename]

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TableIntegrityError(f"Invalid JSON in {filename}: {exc}") from exc

        if not isinstance(parsed, dict):
            raise TableIntegrityError(f"Top-level object in {filename} must be a dict.")

        self._cache[filename] = parsed
        self._hashes[filename] = digest
        return parsed

    def get_checksum(self, filename: str) -> str:
        """Returns the computed SHA-256 checksum for a loaded table.

        Args:
            filename: Basename of the JSON table.

        Returns:
            `sha256:<hex>` digest string.
        """
        self.load_table(filename)
        return self._hashes[filename]

    def list_metadata(self) -> List[Dict[str, Any]]:
        """Returns metadata and SHA-256 checksums for all registered JSON tables.

        Returns:
            List of dictionaries describing each available table.
        """
        summaries: List[Dict[str, Any]] = []
        if not self.tables_dir.exists():
            return summaries
        for path in sorted(self.tables_dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            data = self.load_table(path.name)
            summaries.append(
                {
                    "filename": path.name,
                    "table_id": data.get("table_id", path.stem),
                    "description": data.get("description", ""),
                    "source_authority": data.get("source_authority", ""),
                    "sha256": self._hashes[path.name],
                    "effective_periods": [
                        p.get("effective_from")
                        for p in data.get("effective_periods", [])
                        if isinstance(p, dict)
                    ],
                }
            )
        return summaries

    @staticmethod
    def _parse_date(value: str) -> datetime.date:
        """Parses an ISO `YYYY-MM-DD` date string."""
        return datetime.date.fromisoformat(value)

    def select_effective_period(
        self,
        filename: str,
        filing_date: datetime.date,
        expected_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Selects the active effective-dated period dictionary for `filing_date`.

        Picks the period with the greatest `effective_from <= filing_date` (and
        optional `effective_to >= filing_date` if bounded).

        Args:
            filename: JSON table filename containing an `effective_periods` array.
            filing_date: Expected or actual petition filing date.
            expected_sha256: Optional SHA-256 pin for tamper-evident execution.

        Returns:
            Matching effective period dictionary augmented with `_table_sha256`.

        Raises:
            TableIntegrityError: If no effective period covers `filing_date`.
        """
        data = self.load_table(filename, expected_sha256=expected_sha256)
        periods = data.get("effective_periods", [])
        candidates: List[tuple[datetime.date, Dict[str, Any]]] = []
        for period in periods:
            eff_from = self._parse_date(period["effective_from"])
            eff_to_str = period.get("effective_to")
            if eff_from <= filing_date:
                if eff_to_str and self._parse_date(eff_to_str) < filing_date:
                    continue
                candidates.append((eff_from, period))

        if not candidates:
            raise TableIntegrityError(
                f"No effective period in {filename} covers filing_date={filing_date.isoformat()}."
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = dict(candidates[0][1])
        selected["_table_filename"] = filename
        selected["_table_sha256"] = self._hashes[filename]
        return selected

    def _target_filenames(self) -> List[str]:
        """Returns filenames to inspect for staleness and sync."""
        if not self.tables_dir.exists():
            return list(self.required_tables)
        discovered = [
            p.name
            for p in sorted(self.tables_dir.glob("*.json"))
            if not p.name.startswith(".")
        ]
        if self.required_tables:
            seen = set(self.required_tables)
            return list(self.required_tables) + [f for f in discovered if f not in seen]
        return discovered

    def check_staleness(self, filing_date: datetime.date) -> List[str]:
        """Checks whether any versioned table is stale relative to `filing_date`."""
        warnings: List[str] = []
        for fname in self._target_filenames():
            path = self.tables_dir / fname
            if not path.exists():
                continue
            data = self.load_table(fname)
            stale_str = data.get("stale_after")
            if stale_str:
                stale_date = self._parse_date(str(stale_str))
                if filing_date > stale_date:
                    tid = data.get("table_id", fname)
                    warnings.append(
                        f"Statutory table '{tid}' ({fname}) expired after {stale_date.isoformat()} "
                        f"for target filing date {filing_date.isoformat()}. Run statutory table sync."
                    )
        return warnings

    def sync_tables(
        self, reference_date: Optional[datetime.date] = None
    ) -> Dict[str, Any]:
        """Verifies SHA-256 checksums and staleness across tables in `self.tables_dir`."""
        self._cache.clear()
        self._hashes.clear()
        ref = reference_date or datetime.date.today()

        verified: List[Dict[str, str]] = []
        for fname in self._target_filenames():
            if not (self.tables_dir / fname).exists():
                continue
            data = self.load_table(fname)
            verified.append(
                {
                    "filename": fname,
                    "table_id": str(data.get("table_id", fname)),
                    "sha256": self._hashes[fname],
                    "stale_after": str(data.get("stale_after", "")),
                }
            )

        stale_warnings = self.check_staleness(ref)
        synced_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = {
            "synced_at": synced_at,
            "reference_date": ref.isoformat(),
            "tables_verified": verified,
            "stale_warnings": stale_warnings,
        }
        if self.tables_dir.exists():
            status_path = self.tables_dir / ".sync_status.json"
            status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


class StatutoryTableRegistry(ReferenceTableRegistry):
    """Bankruptcy-specific effective-dated statutory reference table registry."""

    REQUIRED_TABLES = (
        "federal_thresholds_2026.json",
        "ustp_ca_means_test_2026.json",
        "exemptions_2026.json",
        "dependency_rules.json",
    )

    def get_federal_thresholds(self, filing_date: datetime.date) -> Dict[str, Any]:
        """Returns active federal statutory thresholds (`109(e)`, `1182`, `522(p)`, `707(b)`)."""
        return self.select_effective_period("federal_thresholds_2026.json", filing_date)

    def get_ustp_ca_means_test(self, filing_date: datetime.date) -> Dict[str, Any]:
        """Returns active DOJ USTP California median income & IRS standards."""
        return self.select_effective_period("ustp_ca_means_test_2026.json", filing_date)

    def get_exemption_regimes(self, filing_date: datetime.date) -> Dict[str, Any]:
        """Returns active exemption regime specifications (`CA_CCP_704`, `CA_CCP_703_140`, `FEDERAL_522D`)."""
        return self.select_effective_period("exemptions_2026.json", filing_date)

    def get_dependency_rules(self) -> Dict[str, Any]:
        """Returns the declarative cross-schedule dependency specification."""
        return self.load_table("dependency_rules.json")

    def get_schedule_ab_taxonomy(self) -> Dict[str, Any]:
        """Returns Official Form 106A/B 53-line taxonomy mapped to Best Case aliases."""
        return self.load_table("schedule_ab_taxonomy.json")

    def sync_statutory_tables(
        self, reference_date: Optional[datetime.date] = None
    ) -> Dict[str, Any]:
        """Alias maintaining bankruptcy table sync semantics."""
        return self.sync_tables(reference_date=reference_date)


StatutoryTableLoader = StatutoryTableRegistry
