"""Shared per-matter workspace managing raw inputs, incremental events, ledgers, and compiler state."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.provenance import VerifiedLedgerSnapshot


class MatterWorkspace:
    """Manages directory structure, ledgers, and event streams for one `matter_id`.

    Layout under `matters/<matter_id>/`:
    - `inputs/raw/`: immutable raw uploads and `*.events.json` event streams
    - `inputs/indexed/`: coordinate-stamped `*.indexed.md` and `sheets_index.jsonl`
    - `pii_vault.json`: isolated PII/PHI token vault
    - `ledgers/<app_id>.json`: verified calculation snapshots readable by sibling apps
    - `compilers/<app_id>/state.json`: app-owned persisted compiler state
    - `bundles/`: compiled `CompiledBundle` JSON artifacts
    """

    def __init__(self, matters_root: Path, matter_id: str) -> None:
        """Initializes workspace handles for `matter_id`."""
        self.matters_root = matters_root
        self.matter_id = matter_id

    @property
    def matter_dir(self) -> Path:
        """Root directory for this matter."""
        return self.matters_root / self.matter_id

    @property
    def raw_dir(self) -> Path:
        """Directory holding raw uploaded documents and event streams."""
        return self.matter_dir / "inputs" / "raw"

    @property
    def indexed_dir(self) -> Path:
        """Directory holding coordinate-stamped indexed artifacts."""
        return self.matter_dir / "inputs" / "indexed"

    @property
    def bundles_dir(self) -> Path:
        """Directory holding compiled bundles."""
        return self.matter_dir / "bundles"

    @property
    def ledgers_dir(self) -> Path:
        """Directory holding published `VerifiedLedgerSnapshot` JSON files."""
        return self.matter_dir / "ledgers"

    @property
    def pii_vault_path(self) -> Path:
        """Path to the isolated PII/PHI token mapping vault."""
        return self.matter_dir / "pii_vault.json"

    def compiler_dir(self, app_id: str) -> Path:
        """Directory scoped to a single compiler application."""
        return self.matter_dir / "compilers" / app_id

    def ensure_dirs(self) -> Path:
        """Creates standard subdirectories for a matter and returns `matter_dir`."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.indexed_dir.mkdir(parents=True, exist_ok=True)
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        self.ledgers_dir.mkdir(parents=True, exist_ok=True)
        return self.matter_dir

    def ledger_path(self, app_id: str) -> Path:
        """Returns path to `ledgers/<app_id>.json`."""
        return self.ledgers_dir / f"{app_id}.json"

    def write_ledger(self, app_id: str, snapshot: VerifiedLedgerSnapshot) -> Path:
        """Hashes and persists a verified calculation ledger snapshot for sibling compilers."""
        self.ensure_dirs()
        stamped = snapshot.model_copy(
            update={
                "matter_id": self.matter_id,
                "app_id": app_id,
                "sha256": "",
            }
        )
        stamped = stamped.model_copy(update={"sha256": stamped.compute_sha256()})
        target = self.ledger_path(app_id)
        target.write_text(stamped.model_dump_json(indent=2), encoding="utf-8")
        return target

    def read_ledger(
        self, app_id: str, verify_hash: bool = True
    ) -> Optional[VerifiedLedgerSnapshot]:
        """Reads and optionally verifies SHA-256 integrity of a stored ledger snapshot."""
        path = self.ledger_path(app_id)
        if not path.exists():
            return None
        snapshot = VerifiedLedgerSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        if verify_hash and snapshot.sha256 != snapshot.compute_sha256():
            raise ValueError(
                f"Ledger integrity mismatch for {self.matter_id}/{app_id}: "
                f"stored {snapshot.sha256} != computed {snapshot.compute_sha256()}"
            )
        return snapshot

    def list_ledgers(self, verify_hash: bool = False) -> List[VerifiedLedgerSnapshot]:
        """Lists all persisted calculation ledgers for this matter."""
        if not self.ledgers_dir.exists():
            return []
        out: List[VerifiedLedgerSnapshot] = []
        for path in sorted(self.ledgers_dir.glob("*.json")):
            snap = VerifiedLedgerSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            if verify_hash and snap.sha256 != snap.compute_sha256():
                raise ValueError(f"Ledger integrity mismatch in {path.name}.")
            out.append(snap)
        return out

    def append_event(self, stream_name: str, event: Dict[str, Any]) -> Path:
        """Appends a timestamped event record into `inputs/raw/<stream_name>.events.json`."""
        self.ensure_dirs()
        safe_stream = Path(stream_name).name
        target = self.raw_dir / f"{safe_stream}.events.json"
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                payload = {"stream": safe_stream, "events": []}
        else:
            payload = {"stream": safe_stream, "events": []}

        seq = len(payload["events"]) + 1
        entry = {
            "event_id": str(event.get("event_id") or f"evt_{seq:04d}"),
            "recorded_at": str(
                event.get("recorded_at")
                or datetime.datetime.now(datetime.timezone.utc).isoformat()
            ),
            **{k: v for k, v in event.items() if k not in ("event_id", "recorded_at")},
        }
        payload["events"].append(entry)
        target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return target

    def save_compiler_state(self, app_id: str, data: Dict[str, Any]) -> Path:
        """Saves arbitrary JSON compiler state under `compilers/<app_id>/state.json`."""
        c_dir = self.compiler_dir(app_id)
        c_dir.mkdir(parents=True, exist_ok=True)
        path = c_dir / "state.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    def load_compiler_state(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Loads JSON compiler state from `compilers/<app_id>/state.json`, if present."""
        path = self.compiler_dir(app_id) / "state.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
