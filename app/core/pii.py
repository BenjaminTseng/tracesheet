"""Deterministic PII tokenization and local re-hydration vault.

Ensures raw Social Security Numbers / ITINs and full financial account numbers
are stripped and replaced with stable tokens (`[PII:SSN_001]`,
`[PII:ACCT_001_LAST4_4829]`) prior to external LLM ingestion, while preserving
the last 4 digits required by Fed. R. Bankr. P. 9037 and allowing local
Python re-hydration exclusively for restricted court artifacts (`B121`, `debtor.txt`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


ALLOWED_UNMASK_FORMS: Set[str] = {"B121", "debtor.txt"}

# Matches standard formatted SSNs/ITINs (e.g., 123-45-6789 or 912 34 5678).
SSN_PATTERN = re.compile(r"\b(\d{3})[-\s](\d{2})[-\s](\d{4})\b")

# Matches account/card/loan labels followed by an 8 to 17 digit account string
# (allowing optional internal hyphens/spaces, avoiding phone numbers or dates).
ACCOUNT_CONTEXT_PATTERN = re.compile(
    r"(?i)(\b(?:acct|account|loan|card|routing|policy)\s*(?:no\.?|number|#|:)?\s*[:#-]?\s*)"
    r"([0-9][0-9\-\s]{6,18}[0-9])"
)

TOKEN_PATTERN = re.compile(r"\[PII:(?:SSN_\d+|ACCT_\d+_LAST4_\d{4})\]")


class PIITokenizer:
    """Manages per-matter deterministic PII masking and restricted unmasking.

    Attributes:
        matters_root: Root directory containing per-matter folders (`matters/<id>`).
    """

    def __init__(self, matters_root: Path) -> None:
        """Initializes the PII tokenizer.

        Args:
            matters_root: Root directory containing per-matter folders.
        """
        self.matters_root = matters_root

    def _vault_path(self, matter_id: str) -> Path:
        """Returns the path to the local PII vault JSON for a matter.

        Args:
            matter_id: Matter identifier slug.

        Returns:
            Path to `matters/<matter_id>/pii_vault.json`.
        """
        return self.matters_root / matter_id / "pii_vault.json"

    def _load_vault(self, matter_id: str) -> Dict[str, Dict[str, str]]:
        """Loads or initializes the vault dictionary for a matter.

        Args:
            matter_id: Matter identifier slug.

        Returns:
            Dictionary with `"tokens"` (token -> raw value) and `"reverse"`
            (raw normalized value -> token).
        """
        path = self._vault_path(matter_id)
        if not path.exists():
            return {"tokens": {}, "reverse": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"tokens": {}, "reverse": {}}
        if not isinstance(data, dict):
            return {"tokens": {}, "reverse": {}}
        tokens = data.get("tokens")
        reverse = data.get("reverse")
        return {
            "tokens": dict(tokens) if isinstance(tokens, dict) else {},
            "reverse": dict(reverse) if isinstance(reverse, dict) else {},
        }

    def _save_vault(self, matter_id: str, vault: Dict[str, Dict[str, str]]) -> None:
        """Persists the PII vault dictionary locally on disk.

        Args:
            matter_id: Matter identifier slug.
            vault: Vault dictionary containing `tokens` and `reverse` mappings.
        """
        path = self._vault_path(matter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(vault, indent=2, sort_keys=True), encoding="utf-8")

    def _get_or_create_ssn_token(
        self, vault: Dict[str, Dict[str, str]], raw_ssn: str
    ) -> str:
        """Returns an existing or newly minted `[PII:SSN_XXX]` token.

        Args:
            vault: Mutable vault dictionary for the active matter.
            raw_ssn: Matched raw SSN/ITIN string.

        Returns:
            Deterministic SSN token string.
        """
        digits = re.sub(r"\D", "", raw_ssn)
        canonical_key = f"SSN:{digits}"
        if canonical_key in vault["reverse"]:
            return vault["reverse"][canonical_key]

        existing_ssn_count = sum(
            1 for k in vault["tokens"] if k.startswith("[PII:SSN_")
        )
        token = f"[PII:SSN_{existing_ssn_count + 1:03d}]"
        formatted_raw = f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
        vault["tokens"][token] = formatted_raw
        vault["reverse"][canonical_key] = token
        return token

    def _get_or_create_acct_token(
        self, vault: Dict[str, Dict[str, str]], raw_acct: str
    ) -> str:
        """Returns an existing or newly minted `[PII:ACCT_XXX_LAST4_YYYY]` token.

        Args:
            vault: Mutable vault dictionary for the active matter.
            raw_acct: Matched raw account number string.

        Returns:
            Deterministic account token preserving the last 4 digits.
        """
        digits = re.sub(r"\D", "", raw_acct)
        canonical_key = f"ACCT:{digits}"
        if canonical_key in vault["reverse"]:
            return vault["reverse"][canonical_key]

        existing_acct_count = sum(
            1 for k in vault["tokens"] if k.startswith("[PII:ACCT_")
        )
        last4 = digits[-4:]
        token = f"[PII:ACCT_{existing_acct_count + 1:03d}_LAST4_{last4}]"
        vault["tokens"][token] = digits
        vault["reverse"][canonical_key] = token
        return token

    def mask_text(self, matter_id: str, text: str) -> str:
        """Deterministically masks SSNs and full account numbers in `text`.

        Preserves existing tokens and ensures repeated occurrences of the same
        raw SSN or account number across documents map to the exact same token.

        Args:
            matter_id: Matter identifier slug.
            text: Raw extracted text that may contain sensitive PII.

        Returns:
            Masked text safe for external LLM ingestion.
        """
        if not text:
            return text

        vault = self._load_vault(matter_id)
        changed = False

        # First replace full SSN/ITIN occurrences (XXX-XX-XXXX).
        def _replace_ssn(match: re.Match[str]) -> str:
            nonlocal changed
            token = self._get_or_create_ssn_token(vault, match.group(0))
            changed = True
            return token

        masked = SSN_PATTERN.sub(_replace_ssn, text)

        # Next replace context-anchored account numbers of 8-17 digits while
        # preserving the label prefix and the trailing 4 digits in the token.
        def _replace_acct(match: re.Match[str]) -> str:
            nonlocal changed
            prefix = match.group(1)
            candidate = match.group(2)
            digits = re.sub(r"\D", "", candidate)
            if len(digits) < 8 or len(digits) > 17:
                return match.group(0)
            token = self._get_or_create_acct_token(vault, candidate)
            changed = True
            return f"{prefix}{token}"

        masked = ACCOUNT_CONTEXT_PATTERN.sub(_replace_acct, masked)

        if changed or not self._vault_path(matter_id).exists():
            self._save_vault(matter_id, vault)
        return masked

    def register_raw_value(
        self, matter_id: str, kind: str, raw_value: str
    ) -> str:
        """Explicitly registers an SSN or account number into the local PII vault.

        Args:
            matter_id: Matter identifier slug.
            kind: Either `"ssn"` or `"account"`.
            raw_value: Raw SSN or full account number string.

        Returns:
            Deterministic token referencing `raw_value`.

        Raises:
            ValueError: If `kind` is invalid or digit length is out of range.
        """
        vault = self._load_vault(matter_id)
        digits = re.sub(r"\D", "", raw_value)
        if kind == "ssn":
            if len(digits) != 9:
                raise ValueError("SSN must contain exactly 9 digits.")
            token = self._get_or_create_ssn_token(vault, digits)
        elif kind == "account":
            if not (4 <= len(digits) <= 17):
                raise ValueError("Account number must contain 4 to 17 digits.")
            token = self._get_or_create_acct_token(vault, digits)
        else:
            raise ValueError(f"Unsupported PII kind: {kind}")
        self._save_vault(matter_id, vault)
        return token

    def resolve_token(
        self, matter_id: str, token_or_text: str, form_id: str
    ) -> Optional[str]:
        """Looks up a single raw value for a restricted court filing artifact.

        Args:
            matter_id: Matter identifier slug.
            token_or_text: Token string such as `[PII:SSN_001]`.
            form_id: Target artifact identifier; must be in `ALLOWED_UNMASK_FORMS`.

        Returns:
            Raw value if found, else `None`.

        Raises:
            PermissionError: If `form_id` is not an authorized restricted artifact.
        """
        if form_id not in ALLOWED_UNMASK_FORMS:
            raise PermissionError(
                f"PII unmasking denied for public artifact '{form_id}'. "
                f"Only {sorted(ALLOWED_UNMASK_FORMS)} may unmask raw identifiers."
            )
        vault = self._load_vault(matter_id)
        return vault["tokens"].get(token_or_text)

    def unmask_for_restricted_form(
        self, matter_id: str, text: str, form_id: str
    ) -> str:
        """Re-hydrates PII tokens inside `text` exclusively for restricted court outputs.

        Args:
            matter_id: Matter identifier slug.
            text: Text containing `[PII:...]` tokens.
            form_id: Target form/artifact ID; restricted to `B121` and `debtor.txt`.

        Returns:
            Text with vaulted PII values restored.

        Raises:
            PermissionError: If `form_id` is not in `ALLOWED_UNMASK_FORMS`.
        """
        if form_id not in ALLOWED_UNMASK_FORMS:
            raise PermissionError(
                f"PII unmasking denied for public artifact '{form_id}'. "
                f"Only {sorted(ALLOWED_UNMASK_FORMS)} may unmask raw identifiers."
            )
        vault = self._load_vault(matter_id)
        tokens = vault["tokens"]

        def _restore(match: re.Match[str]) -> str:
            tok = match.group(0)
            return tokens.get(tok, tok)

        return TOKEN_PATTERN.sub(_restore, text)

    def redact_for_public_form(self, token_or_text: str) -> str:
        """Converts tokens or raw 9-digit SSNs into FRBP 9037 last-4 redacted strings.

        Args:
            token_or_text: Input text possibly containing tokens or raw SSNs.

        Returns:
            String with full numbers replaced by `XXX-XX-XXXX` or `...LAST4`.
        """
        out = SSN_PATTERN.sub("XXX-XX-XXXX", token_or_text)

        def _mask_token(match: re.Match[str]) -> str:
            tok = match.group(0)
            if tok.startswith("[PII:SSN_"):
                return "XXX-XX-XXXX"
            if "_LAST4_" in tok:
                last4 = tok.split("_LAST4_")[-1].rstrip("]")
                return f"****{last4}"
            return "REDACTED"

        return TOKEN_PATTERN.sub(_mask_token, out)

    def list_tokens(self, matter_id: str) -> List[Tuple[str, str]]:
        """Lists registered tokens and redacted previews without exposing raw SSNs.

        Args:
            matter_id: Matter identifier slug.

        Returns:
            List of `(token, redacted_preview)` pairs.
        """
        vault = self._load_vault(matter_id)
        return [
            (tok, self.redact_for_public_form(tok))
            for tok in sorted(vault["tokens"].keys())
        ]
