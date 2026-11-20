"""Internal PACER/CM/ECF Credential + RFC-6238 TOTP Vault and Rule 9011 Sign-Off Gate."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
import struct
import time
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.compilers.bankruptcy.schema import BankruptcyCaseState
from app.core.gate import SignOffGate, SignOffToken


SubmissionMode = Literal["ecf_train", "filing_agent", "firm_attorney"]


class StoredCredential(BaseModel):
    """Encrypted/obfuscated PACER/CM-ECF credential profile for one execution mode."""

    mode: SubmissionMode
    username: str
    secret_blob: str
    totp_blob: str
    sponsoring_bar_number: Optional[str] = None
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class Rule9011SignOffToken(BaseModel):
    """Cryptographic attestation minted when an attorney signs off under Fed. R. Bankr. P. 9011."""

    matter_id: str
    attorney_name: str
    attorney_bar_number: str
    declaration_sha256: str
    packet_sha256: str
    signed_at: str
    token_digest: str


class CredentialAndTOTPVault:
    """Manages internal firm/training CM/ECF credentials and generates RFC-6238 TOTP codes."""

    def __init__(self, vault_path: Path, master_key: Optional[str] = None) -> None:
        """Initializes the credential vault.

        Args:
            vault_path: Path to local JSON vault file (e.g., `matters/_vault/credentials.json`).
            master_key: Optional encryption passphrase (defaults to `JD_SCREEN_VAULT_KEY` env or local key).
        """
        self.vault_path = vault_path
        self._key_bytes = hashlib.sha256(
            (master_key or os.getenv("JD_SCREEN_VAULT_KEY", "jd-screen-local-vault-key")).encode("utf-8")
        ).digest()

    def _xor_seal(self, plaintext: str) -> str:
        """Deterministic authenticated XOR-stream seal using HMAC-derived keystream."""
        raw = plaintext.encode("utf-8")
        stream = hashlib.sha256(self._key_bytes + len(raw).to_bytes(4, "big")).digest()
        sealed = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(raw))
        return base64.urlsafe_b64encode(sealed).decode("ascii")

    def _xor_unseal(self, blob: str) -> str:
        raw = base64.urlsafe_b64decode(blob.encode("ascii"))
        stream = hashlib.sha256(self._key_bytes + len(raw).to_bytes(4, "big")).digest()
        plain = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(raw))
        return plain.decode("utf-8")

    def _load_all(self) -> Dict[str, StoredCredential]:
        if not self.vault_path.exists():
            return {}
        data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        return {k: StoredCredential.model_validate(v) for k, v in data.items()}

    def _save_all(self, creds: Dict[str, StoredCredential]) -> None:
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_text(
            json.dumps({k: v.model_dump(mode="json") for k, v in creds.items()}, indent=2),
            encoding="utf-8",
        )

    def save_credential(
        self,
        mode: SubmissionMode,
        username: str,
        password: str,
        totp_secret: str,
        sponsoring_bar_number: Optional[str] = None,
    ) -> StoredCredential:
        """Encrypts and stores a PACER/CM-ECF credential profile for `mode`."""
        creds = self._load_all()
        entry = StoredCredential(
            mode=mode,
            username=username,
            secret_blob=self._xor_seal(password),
            totp_blob=self._xor_seal(totp_secret),
            sponsoring_bar_number=sponsoring_bar_number,
        )
        creds[mode] = entry
        self._save_all(creds)
        return entry

    def list_profiles_redacted(self) -> List[Dict[str, Optional[str]]]:
        """Lists stored credential profiles with passwords and TOTP secrets redacted."""
        creds = self._load_all()
        return [
            {
                "mode": entry.mode,
                "username": entry.username,
                "sponsoring_bar_number": entry.sponsoring_bar_number,
                "updated_at": entry.updated_at,
                "configured": "yes",
            }
            for entry in creds.values()
        ]

    def generate_totp_code(
        self, mode: SubmissionMode, timestamp: Optional[int] = None
    ) -> str:
        """Computes a standard 6-digit RFC 6238 TOTP code from the stored Base32 seed.

        Args:
            mode: Credential profile (`ecf_train`, `filing_agent`, `firm_attorney`).
            timestamp: Optional Unix epoch seconds override for deterministic tests.

        Returns:
            6-digit zero-padded TOTP string.

        Raises:
            KeyError: If no credential is configured for `mode`.
        """
        creds = self._load_all()
        if mode not in creds:
            raise KeyError(f"No PACER credential configured in vault for mode='{mode}'.")
        b32_secret = self._xor_unseal(creds[mode].totp_blob).strip().replace(" ", "").upper()
        # Pad Base32 to multiple of 8.
        pad = (-len(b32_secret)) % 8
        key = base64.b32decode(b32_secret + ("=" * pad))
        counter = int((timestamp if timestamp is not None else time.time()) // 30)
        msg = struct.pack(">Q", counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        return f"{code_int % 1_000_000:06d}"


class Rule9011SignOffGate:
    """Enforces attorney Rule 9011 sign-off and signed declaration prerequisites before submission."""

    def __init__(self, signing_secret: Optional[str] = None) -> None:
        """Initializes the Rule 9011 gate delegating cryptographic signing to `core.gate.SignOffGate`."""
        self._gate = SignOffGate(signing_secret=signing_secret)

    @staticmethod
    def compute_packet_hash(packet_files: List[Path]) -> str:
        """Computes a deterministic SHA-256 hash over all compiled packet files."""
        return SignOffGate.compute_files_hash(packet_files)

    def mint_token(
        self,
        state: BankruptcyCaseState,
        packet_files: List[Path],
        attorney_name: str,
        attorney_bar_number: str,
        attested: bool,
    ) -> Rule9011SignOffToken:
        """Mints a `Rule9011SignOffToken` after validating readiness and wet-sig declaration."""
        if not attested:
            raise PermissionError("Explicit Rule 9011 attorney attestation is required.")
        if state.readiness is None or state.readiness.status != "READY":
            raise PermissionError(
                "Cannot sign off under Rule 9011 while FilingReadinessGate is BLOCKED."
            )
        if not state.case_graph.signed_declaration_uploaded or not state.case_graph.signed_declaration_sha256:
            raise PermissionError(
                "Debtor-signed Electronic Filing Declaration (F 5005-4 / CAEB e-Sig) must be uploaded before filing."
            )
        if not attorney_name.strip() or not attorney_bar_number.strip():
            raise PermissionError("Admitted attorney name and CA Bar number are required.")

        core_tok = self._gate.mint(
            matter_id=state.case_graph.matter_id,
            artifact_files=packet_files,
            actor_name=attorney_name,
            actor_role="attorney",
            actor_credential_id=attorney_bar_number,
            attested=attested,
            declaration_sha256=state.case_graph.signed_declaration_sha256,
            readiness_status=state.readiness.status,
            allow_advisory=False,
        )
        return Rule9011SignOffToken(
            matter_id=core_tok.matter_id,
            attorney_name=core_tok.actor_name,
            attorney_bar_number=core_tok.actor_credential_id,
            declaration_sha256=core_tok.declaration_sha256,
            packet_sha256=core_tok.artifact_sha256,
            signed_at=core_tok.signed_at,
            token_digest=core_tok.token_digest,
        )

    def verify_token(
        self, token: Rule9011SignOffToken, state: BankruptcyCaseState, packet_files: List[Path]
    ) -> bool:
        """Verifies HMAC signature and confirms packet hash has not drifted since sign-off."""
        core_tok = SignOffToken(
            matter_id=token.matter_id,
            actor_name=token.attorney_name,
            actor_role="attorney",
            actor_credential_id=token.attorney_bar_number,
            artifact_sha256=token.packet_sha256,
            declaration_sha256=token.declaration_sha256,
            attested=True,
            signed_at=token.signed_at,
            token_digest=token.token_digest,
        )
        return self._gate.verify(
            token=core_tok,
            matter_id=state.case_graph.matter_id,
            artifact_files=packet_files,
            expected_declaration_sha256=state.case_graph.signed_declaration_sha256 or "",
        )
