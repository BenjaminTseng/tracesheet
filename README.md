# Audit-Grounded Spatial Document Canvas & Agentic Q&A Platform (`jd_screen`)

An agentic question-answering and verification workspace that synthesizes grounded documents from a standing canonical corpus `(b)` and project-specific task inputs `(a)` with full Toulmin-graph traceability (`L0` → `L1` → `L2+`), deterministic coordinate verification, and an Antigravity-style inline review queue for batched regeneration.

## Architecture Overview

1. **Provider-Agnostic LLM Gateway (`app/llm.py`):**
   - Defines `LLMProvider` (`generate_structured`, `generate_text`, `run_tool_loop`, `evaluate_decisions`).
   - Primary implementation: `GeminiInteractionsProvider` built on the Google Gemini Interactions API (`client.interactions.create`) + Gemini Decisions API (`client.decisions.create`), with automatic `.env` loading via `python-dotenv`.
   - Includes drop-in adapters for `AnthropicProvider` and `OpenAIProvider`, plus `MockLLMProvider` for offline tests.

2. **Deterministic Ingestion & 3-Tier Canonical Indexing (`app/ingest.py`):**
   - `CanonicalIngestor` & `CanonicalRouter`: Converts raw documents under `canonical/raw/<domain>/` (`.md`, `.txt`, `.pdf`, `.docx`, `.xlsx`, `.xlsm`, `.csv`) into Tier 3 `[AUTH:...]` Markdown blocks, Tier 2 per-document `.toc.md` tables, and Tier 1 `canonical/INDEX.md` + `canonical/catalog.json` cards.
   - `MatterIngestor`: Indexes `matters/<matter_id>/inputs/raw/` into coordinate-stamped `*.indexed.md` blocks (`pdfplumber` `[x1, y1, x2, y2]` bounding boxes, Markdown block locators, SHA-256 digests) and `sheets_index.jsonl` (dual-pass `openpyxl` formulas + evaluated primitives, plus CSV), and verifies L1/L2 citations deterministically.

3. **Four-Stage Agentic Pipeline & Smart Feedback Regenerator (`app/pipeline.py`):**
   - **Stage 1:** Question decomposition & canonical `[AUTH:...]` hydration (`OutlinePlan`).
   - **Stage 2:** Tool-loop fact harvesting over indexed inputs (`VerifiedFactLedger`).
   - **Stage 3:** Constrained Tier-1 `SectionOutput` drafting with `SectionValidator` auto-retries.
   - **Stage 4:** Surrounding-context congruence auditing, cross-section tension detection, `StitchInvariantGate`-protected editorial smoothing, and `CompiledGraphBuilder` DAG compilation.
   - **Smart Batch Feedback (`apply_comments_and_recompile`):** Triages queued human comments per section to either re-run Stage 3→4 (prose/reasoning/caveat edits) or Stage 2→3→4 (new/different factual queries), preserving unaffected sections verbatim.

4. **Frontend (`static/app.js`, `static/styles.css` — Preact + HTM, zero build step):**
   - Implements the **Swiss Quantitative Broadsheet + Archival Press** aesthetic (`L0` → `L1` → `L2+`), dynamic SVG cubic Bezier connectors, slide-over **Source Inspector Drawer**, **Ask Question** pipeline modal, and **Inline Commenting + Sticky Batch Review Queue** across `L0` claims and `L1`/`L2+` plates.

5. **Standalone Bankruptcy Case Workbench (`bankruptcy_main.py`, Port 8001 — `app/bankruptcy/`):**
   - **Entity-First Multi-Form Routing & 53-Line Taxonomy:** Maps uncategorized PDFs onto `CanonicalCaseGraph` with [schedule_ab_taxonomy.json](file:///home/ben/restructure/jd_screen/canonical/tables/bankruptcy/schedule_ab_taxonomy.json) (all 53 Official Form 106A/B lines paired with Best Case 35-item aliases and orthogonal `exemption_pool`s).
   - **Deterministic Calculators (`app/bankruptcy/calculators/`):**
     - **Exemptions (`exemptions.py`):** Evaluates `CA_CCP_704`, `CA_CCP_703_140`, and `FEDERAL_522D`, including `"Unknown"` valuations & *Schwab v. Reilly* (`560 U.S. 770`) `"100% of FMV"` Schedule C elections (`workers_comp`, `personal_injury`, `75%` `unpaid_wages`), `11 U.S.C. § 522(p)` `$214,000` / `1,215-day` homestead cap with `§ 522(p)(2)(B)` same-state rollover and `§ 522(o)` reduction, `§ 522(n)` `$1,711,975` non-rollover IRA cap, and `§ 541(b)(5)–(6)` 529 education lookbacks (`0%` within 365 days; `$7,575` cap for 365–720 days).
     - **Means Test (`means_test.py`):** Strict 6-calendar-month CMI lookback with **Married Filing Separately** `Column B` non-filing spouse CMI, `marital_adjustment_deduction` (`Form 122A-2 Line 3`), and separate-and-apart exclusion.
     - **Chapter 13 Plan (`ch13_plan.py`):** `910-day` PMSI vehicle cramdown (`11 U.S.C. § 1325(a)`), *Lam/Zimmer* wholly-unsecured junior mortgage lien strip, trustee percentage fee & RARA attorney fee plan math, and `11 U.S.C. § 1325(a)(6)` `Schedule I - J` feasibility gating.
   - **Cross-Schedule Auditors & Statutory Sync (`app/bankruptcy/audit.py`, `app/core/tables.py`):** Includes trauma/medical personal injury & workers' comp claim detection, bidirectional `SOFA Line 9 ↔ Schedule A/B ↔ Schedule E/F` lawsuit sync, 60-day paystub continuity checking, `CCP § 703.140(a)(2)` spousal waiver gate, `11 U.S.C. § 1308` 4-year tax return compliance, Tier-2 negative confirmation (`MANDATORY_ASSET_AND_WINDFALL_SWEEP` covering `11 U.S.C. § 541(a)(5)`), and effective-dated table staleness & SHA-256 sync (`--sync-statutory-tables`).
   - **Official PDF Filling & Baking (`app/bankruptcy/pdf_engine.py`, `form_field_maps.json`):** Maps values and checkboxes directly onto 25 official U.S. Courts, CACB, and CAEB fillable PDFs under `canonical/tables/bankruptcy/templates/`, flattens with `pymupdf.Document.bake(annots=True, widgets=True)`, isolates full SSNs in `Form_B121_RESTRICTED.pdf`, and emits `field_lineage.json`.
   - **Workbench UI (`templates/bankruptcy.html`, `static/bankruptcy.js`):** Official-form-aligned `L0` broadsheet tables, right-hand `NextBlockerStepper` resolution queue, `SourceInspectorDrawer`, `FilingPacketDrawer`, and header statutory table sync.

## WSL2 Execution & Testing Commands

### 0. Configure `.env` (Optional, for Live Gemini Calls)
```bash
cd ~/restructure/jd_screen
cp .env.example .env
# Edit .env with GEMINI_API_KEY and optional JD_SCREEN_MODEL (e.g., gemini-4-argon or gemini-4-hydrogen)
```

### 1. Run Offline Unit, Retry & API Integration Tests (and Opt-In Live Eval)
```bash
cd ~/restructure/jd_screen
uv run pytest tests/ -v

# Opt-in live Gemini evaluation suite (requires GEMINI_API_KEY in .env or environment):
RUN_LIVE_API_TESTS=1 uv run pytest tests/test_live_eval.py -v -s
```

### 2. Ingest Canonical Corpus & Project Matter via CLI
```bash
cd ~/restructure/jd_screen
uv run python main.py --ingest-canonical --purge-canonical
uv run python main.py --ingest-matter legal_motion_1332
```

### 3. Run the 4-Stage Agentic Pipeline via CLI
```bash
cd ~/restructure/jd_screen
GEMINI_API_KEY="your-key" uv run python main.py \
  --provider gemini --model gemini-4-argon \
  --matter legal_motion_1332 \
  --ask "Evaluate whether complete diversity and the $75,000 threshold are met."
```

### 4. Start the Web UI Server (Broadsheet Research App — Port 8000)
```bash
cd ~/restructure/jd_screen
GEMINI_API_KEY="your-key" uv run python main.py \
  --host 127.0.0.1 --port 8000 --name jd_screen \
  --provider gemini --model gemini-4-argon
```

Then open `http://127.0.0.1:8000` in your browser.

### 5. Start the Standalone Bankruptcy Case Workbench Webapp (Port 8001)
```bash
cd ~/restructure/jd_screen

# Verify SHA-256 integrity and effective-date freshness of canonical statutory tables:
uv run python bankruptcy_main.py --sync-statutory-tables

# Start the standalone Bankruptcy Case Workbench server:
uv run python bankruptcy_main.py --host 127.0.0.1 --port 8001 --name bk_workbench
```

Then open `http://127.0.0.1:8001` in your browser to test pre-seeded cases (`bk_ch7_cacb_martinez`, `bk_ch13_caeb_chen`) or upload client PDFs.
