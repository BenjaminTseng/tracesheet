"""Shared core platform modules for audit-grounded compiler applications.

Modules:
- `bundle`: Tier-1/Tier-2 DAG contracts, `SourceLocator`, `CompiledBundle`, `TensionObject`.
- `provenance`: Domain-agnostic `ProvenanceField[T]`, `ReadinessReport`, `CaseSummaryRow`, `VerifiedLedgerSnapshot`.
- `workspace`: `MatterWorkspace` per-matter directory/ledger/event management.
- `gate`: Configurable `GatePolicy`, `ReadinessGate`, and `SignOffGate`.
- `verifier`: `IndexedMatterCorpus` and `ObservationVerifier` (with `json_path` support).
- `compiler`: `AppDescriptor`, `PlatformContext`, and `CompilerApp` protocol.
- `ingest`: `CanonicalRouter`, `CanonicalIngestor`, and `MatterIngestor`.
- `llm`: Provider-agnostic `LLMProvider` gateway (`GeminiInteractionsProvider`, `MockLLMProvider`, etc.).
- `pii`: Deterministic PII/PHI tokenization and restricted re-hydration vault.
- `ocr`: Pluggable OCR extraction interface.
- `tables`: Effective-dated `ReferenceTableRegistry` and `StatutoryTableRegistry`.
"""
