# Audit-Grounded Platform & Pluggable Domain Compilers (`jd_screen`)

A unified verification platform that compiles client documents `(a)`, controlling rules/tables `(b)`, and structured output schemas `(c)` into `L0 → L1 → L2+` traceability graphs (`CompiledBundle`), coordinate-verified calculations, and court-ready packets across pluggable domain compilers.

## Architecture Overview

1. **Core Platform Spine (`app/core/`):**
   - **LLM Gateway (`app/core/llm.py`):** Provider-agnostic `LLMProvider` (`GeminiInteractionsProvider` via `google-genai` Interactions + Decisions API, `AnthropicProvider`, `OpenAIProvider`, and `MockLLMProvider`).
   - **Ingestion & PII/OCR (`app/core/ingest.py`, `app/core/pii.py`, `app/core/ocr.py`):** `CanonicalIngestor`/`CanonicalRouter` (`canonical/raw/<domain>/` → Tier 1/2/3 `[AUTH:...]` Markdown + `INDEX.md` + `catalog.json`), `MatterIngestor` (coordinate-stamped `*.indexed.md`, `sheets_index.jsonl`, `event_log`, and `calculation_ledger` snapshots in `ledgers/*.json`), `PIITokenizer` local vault masking (`[PII:SSN_001]`), and pluggable `OCRProvider` (`modal`, `local`, `mock`).
   - **Provenance, Gates & Compiler Contracts (`app/core/{bundle,provenance,workspace,gate,compiler,verifier,tables,pdf_forms}.py`):** Normalized `CompiledBundle`, generic `ProvenanceField[T]` & `EmergingQuestionItem`, `MatterWorkspace` with atomic SHA-256 `VerifiedLedgerSnapshot` cross-compiler publishing (`ledgers/<app>.json`), `ObservationVerifier`, `ReadinessGate` & `SignOffGate`, `ReferenceTableRegistry` (and `StatutoryTableRegistry` staleness/sync), and generic `AcroFormEngine` (`.bake(annots=True, widgets=True)`, overflow sheets, `field_lineage.json`).

2. **Pluggable Domain Compilers (`app/compilers/`):**
   - **Bankruptcy Compiler (`app/compilers/bankruptcy/`, default UI at `/bankruptcy`):**
     - **Schema, Extractor & Dispatch (`schema.py`, `extractor.py`, `calculators/registry.py`):** 53-line Form 106A/B taxonomy ([schedule_ab_taxonomy.json](file:///home/ben/restructure/jd_screen/canonical/tables/bankruptcy/schedule_ab_taxonomy.json)), entity-first multi-form extractor with deterministic fallback, and pluggable `ChapterCalculatorDispatch` (`"7"`, `"13"`, `"11_subv"`).
     - **Deterministic Calculators (`calculators/`):** `exemptions.py` (`CA_CCP_704`, `CA_CCP_703_140`, `FEDERAL_522D`, *Schwab v. Reilly* `"100% of FMV"`, `§§ 522(p)/(n)/(o)`, `§ 541(b)(5)–(6)`), `means_test.py` (6-month CMI, Married Filing Separately Column B & Line 3 Marital Adjustment), `eligibility.py` (`$2.75M` Ch. 13, `$7.5M` SubV), and `ch13_plan.py` (910-day cramdown, *Lam/Zimmer* lien strip, trustee/RARA fees, `§ 1325(a)(6)` feasibility).
     - **Auditors, Binder, Districts & Vault (`rules_auditor.py`, `bundle_adapter.py`, `form_binder.py`, `districts/`, `vault.py`, `service.py`):** Trauma PI detector, bidirectional `SOFA Line 9 ↔ A/B ↔ E/F`, 60-day paystub gap check, Tier-2 asset/180-day windfall sweep, `CACB`/`CAEB` adapters (`8 MB` splitter), Rule 9011 TOTP vault, and automatic `ledgers/bankruptcy.json` publishing.
   - **Research Broadsheet Compiler (`app/compilers/research/`, UI at `/research`):**
     - **4-Stage Agentic Pipeline (`pipeline.py`, `service.py`, `routes.py`):** Outline & `[AUTH:...]` routing → Tool-loop harvesting (including sibling compiler `calculation_ledger` files) → `SectionValidator` drafting → Decisions API auditing, `StitchInvariantGate` smoothing, DAG compilation, and smart batch feedback regeneration (`apply_comments_and_recompile`).

3. **Unified Host & Clean `/api/v1/` Surface (`app/server.py`, `main.py`, `bankruptcy_main.py`):**
   - `main.py` (default port `8000`) mounts `--apps` (default `bankruptcy,research`, `--default-app bankruptcy` so `GET / → 307 /bankruptcy`).
   - Shared platform routes: `/api/v1/apps`, `/api/v1/apps/cases`, `/api/v1/tables/*`, `/api/v1/canonical/*`, `/api/v1/matters/*` (including `/api/v1/matters/{id}/ledgers`).
   - Compiler routes: `/api/v1/bankruptcy/*` and `/api/v1/research/*`.

4. **Three-Tier Slot-Based Frontend (`static/core/` + `static/apps/` — Preact + HTM, zero build step):**
   - `static/core/shell.js`: `PlatformShell` top-bar chrome with App Switcher dropdown from `GET /api/v1/apps` (auto-hiding when only one app is mounted), SVG icon primitives, formatters, and `/api/v1/` source resolution.
   - `static/core/canvas.js`, `inspector.js`, `stepper.js`: Shared `TraceabilityCanvas` (`L0 → L1 → L2+`), `BezierConnectorLayer`, polymorphic `SourceInspectorDrawer` (including `calculation_ledger` & `event_log`), and `TriageStepperFrame`.
   - `static/apps/bankruptcy/app.js` (`templates/bankruptcy.html`) & `static/apps/research/app.js` (`templates/research.html`): Domain-tailored views composing shared core slots.

## Adding a New Domain Compiler (4-Step Guide)

1. **Create Compiler Package (`app/compilers/<app_id>/`):** Implement schema/calculators/auditors implementing `BaseCompiler` and register any effective-dated tables with `ReferenceTableRegistry` (optionally emit `VerifiedLedgerSnapshot` via `MatterWorkspace.publish_ledger_snapshot` or bind fillable PDFs via `AcroFormEngine`).
2. **Expose FastAPI Router (`app/compilers/<app_id>/routes.py`):** Mount app-specific endpoints under `/api/v1/<app_id>/*`.
3. **Register in `COMPILER_REGISTRY` (`app/server.py`):** Add the compiler descriptor (`app_id`, `label`, `ui_route`, `api_prefix`, router factory) so `GET /api/v1/apps` and `--apps` discover it automatically.
4. **Add Thin Slot UI (`templates/<app_id>.html` + `static/apps/<app_id>/app.js`):** Compose `PlatformShell`, `TraceabilityCanvas`, `SourceInspectorDrawer`, and `TriageStepperFrame` from `static/core/*.js`.

## WSL2 Execution & Testing Commands

### 0. Configure `.env` (Optional, for Live Gemini Calls)
```bash
cd ~/restructure/jd_screen
cp .env.example .env
# Set GEMINI_API_KEY and optional JD_SCREEN_MODEL
```

### 1. Run Offline Unit, Integration & UI Craft Verification
```bash
cd ~/restructure/jd_screen
uv run pytest tests/ -v
uv run python main.py --sync-tables bankruptcy
node --check static/core/*.js static/apps/*/*.js
```

### 2. Run Opt-In, Token-Disciplined Live Gemini Evaluation (`tests/test_live_eval.py`)
Live tests reuse pre-encoded `canonical/` and cache Stage 1–4 output in `.pytest_cache/live_eval_bundle_1332.json` to avoid wasted tokens, and can be run selectively:
```bash
cd ~/restructure/jd_screen
# Run all 5 granular live tests:
RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -v -s

# Run a single live sub-test (e.g., bankruptcy PII masking + extractor, or hybrid ledger bridge):
RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -k test_live_02 -v -s
RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -k test_live_05 -v -s

# Re-run only failed live tests:
RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py --lf -v -s
```

### 3. Ingest Canonical Corpus & Start Servers
```bash
cd ~/restructure/jd_screen
uv run python main.py --ingest-canonical --purge-canonical
uv run python main.py --ingest-matter legal_motion_1332

# Start unified server co-mounting /bankruptcy (default) and /research on port 8000:
uv run python main.py --host 127.0.0.1 --port 8000 --apps bankruptcy,research --default-app bankruptcy

# Or start single-app Bankruptcy Workbench on port 8001 (auto-hides App Switcher):
uv run python bankruptcy_main.py --host 127.0.0.1 --port 8001
```
