"""Effective-dated JSON statutory reference table registry with SHA-256 verification.

Loads versioned federal bankruptcy thresholds, DOJ U.S. Trustee Means Testing
standards, multi-jurisdiction exemption regimes, and declarative cross-schedule
dependency rules from `canonical/tables/bankruptcy/`.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class TableIntegrityError(RuntimeError):
    """Raised when a statutory JSON reference table fails schema or checksum verification."""


class StatutoryTableRegistry:
    """Loads, verifies, and selects effective-dated statutory reference JSON tables.

    Attributes:
        tables_dir: Directory containing `*.json` statutory reference files.
    """

    REQUIRED_TABLES = (
        "federal_thresholds_2026.json",
        "ustp_ca_means_test_2026.json",
        "exemptions_2026.json",
        "dependency_rules.json",
    )

    def __init__(self, tables_dir: Path) -> None:
        """Initializes the statutory table registry.

        Args:
            tables_dir: Path to `canonical/tables/bankruptcy/`.
        """
        self.tables_dir = tables_dir
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

    def get_federal_thresholds(self, filing_date: datetime.date) -> Dict[str, Any]:
        """Returns active federal statutory thresholds (`109(e)`, `1182`, `522(p)`, `707(b)`).

        Args:
            filing_date: Petition filing date.

        Returns:
            Effective period payload from `federal_thresholds_2026.json`.
        """
        return self.select_effective_period("federal_thresholds_2026.json", filing_date)

    def get_ustp_ca_means_test(self, filing_date: datetime.date) -> Dict[str, Any]:
        """Returns active DOJ USTP California median income & IRS standards.

        Args:
            filing_date: Petition filing date.

        Returns:
            Effective period payload from `ustp_ca_means_test_2026.json`.
        """
        return self.select_effective_period("ustp_ca_means_test_2026.json", filing_date)

    def get_exemption_regimes(self, filing_date: datetime.date) -> Dict[str, Any]:
        """Returns active exemption regime specifications (`CA_CCP_704`, `CA_CCP_703_140`, `FEDERAL_522D`).

        Args:
            filing_date: Petition filing date.

        Returns:
            Effective period payload from `exemptions_2026.json`.
        """
        return self.select_effective_period("exemptions_2026.json", filing_date)

    def get_dependency_rules(self) -> Dict[str, Any]:
        """Returns the declarative cross-schedule dependency specification.

        Returns:
            Parsed dictionary from `dependency_rules.json`.
        """
        return self.load_table("dependency_rules.json")

    def get_schedule_ab_taxonomy(self) -> Dict[str, Any]:
        """Returns Official Form 106A/B 53-line taxonomy mapped to Best Case aliases.

        Returns:
            Parsed dictionary from `schedule_ab_taxonomy.json`.
        """
        return self.load_table("schedule_ab_taxonomy.json")

    def check_staleness(self, filing_date: datetime.date) -> List[str]:
        """Checks whether any versioned statutory table is stale relative to `filing_date`.

        Args:
            filing_date: Expected or actual petition filing date.

        Returns:
            List of descriptive staleness warning/blocker messages.
        """
        warnings: List[str] = []
        for fname in (
            "ustp_ca_means_test_2026.json",
            "exemptions_2026.json",
            "federal_thresholds_2026.json",
            "schedule_ab_taxonomy.json",
        ):
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

    def sync_statutory_tables(
        self, reference_date: Optional[datetime.date] = None
    ) -> Dict[str, Any]:
        """Verifies SHA-256 checksums and staleness across canonical bankruptcy tables.

        Clears in-memory caches, recomputes SHA-256 digests for all registered JSON
        tables under `self.tables_dir`, writes `.sync_status.json`, and returns a
        structured audit summary.

        Args:
            reference_date: Optional filing date for staleness evaluation (defaults to today).

        Returns:
            Summary dict containing `synced_at`, `tables_verified`, and `stale_warnings`.
        """
        self._cache.clear()
        self._hashes.clear()
        ref = reference_date or datetime.date.today()

        verified: List[Dict[str, str]] = []
        target_files = (
            "federal_thresholds_2026.json",
            "ustp_ca_means_test_2026.json",
            "exemptions_2026.json",
            "dependency_rules.json",
            "schedule_ab_taxonomy.json",
            "form_field_maps.json",
        )
        for fname in target_files:
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
        status_path = self.tables_dir / ".sync_status.json"
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


StatutoryTableLoader = StatutoryTableRegistry
