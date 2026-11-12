# Audit-Grounded Spatial Document Canvas & Agentic Q&A Platform (`jd_screen`)

An agentic question-answering and verification workspace that synthesizes grounded documents from a standing canonical corpus `(b)` and project-specific task inputs `(a)` with full Toulmin-graph traceability (`L0` → `L1` → `L2+`), deterministic coordinate verification, and an Antigravity-style inline review queue for batched regeneration.

## Architecture Overview

1. **Provider-Agnostic LLM Gateway (`app/llm.py`):**
   - Defines `LLMProvider` (`generate_structured`, `generate_text`, `run_tool_loop`).
   - Primary implementation: `GeminiInteractionsProvider` built on the Google Gemini Interactions API (`client.interactions.create` via `google-genai`), with `response_format` JSON Schema constrained decoding and stateful `previous_interaction_id` tool-calling turns.
   - Includes drop-in adapters for `AnthropicProvider` and `OpenAIProvider`, plus `MockLLMProvider` for offline tests.

2. **Deterministic Ingestion & Coordinate Stamping (`app/ingest.py`):**
   - `CanonicalRouter`: Reads `canonical/INDEX.md` and parses `[AUTH:...]` anchored canonical Markdown files `(b)`.
   - `MatterIngestor`: Indexes `matters/<matter_id>/inputs/raw/` into coordinate-stamped `*.indexed.md` blocks (`pdfplumber` `[x1, y1, x2, y2]` bounding boxes, Markdown block locators, SHA-256 digests) and `sheets_index.jsonl` (dual-pass `openpyxl` formulas + evaluated primitives, plus CSV), exposing deterministic Stage 2 search tools.

3. **Four-Stage Agentic Pipeline & Smart Feedback Regenerator (`app/pipeline.py`):**
   - **Stage 1:** Question decomposition & canonical `[AUTH:...]` hydration (`OutlinePlan`).
   - **Stage 2:** Tool-loop fact harvesting over indexed inputs (`VerifiedFactLedger`).
   - **Stage 3:** Constrained Tier-1 `SectionOutput` drafting with `SectionValidator` auto-retries.
   - **Stage 4:** Surrounding-context congruence auditing, cross-section tension detection, `StitchInvariantGate`-protected editorial smoothing, and `CompiledGraphBuilder` DAG compilation.
   - **Smart Batch Feedback (`apply_comments_and_recompile`):** Triages queued human comments per section to either re-run Stage 3→4 (prose/reasoning/caveat edits) or Stage 2→3→4 (new/different factual queries), preserving unaffected sections verbatim.

4. **Frontend (`static/app.js`, `static/styles.css` — Preact + HTM, zero build step):**
   - Implements the **Swiss Quantitative Broadsheet + Archival Press** aesthetic (`L0` → `L1` → `L2+`), dynamic SVG cubic Bezier connectors, slide-over **Source Inspector Drawer**, **Ask Question** pipeline modal, and **Inline Commenting + Sticky Batch Review Queue** across `L0` claims and `L1`/`L2+` plates.

## WSL2 Execution & Testing Commands

### 1. Run Unit & API Integration Test Suite
```bash
cd ~/restructure/jd_screen
uv run pytest tests/ -v
```

### 2. Ingest a Project Matter via CLI
```bash
cd ~/restructure/jd_screen
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

### 4. Start the Web UI Server
```bash
cd ~/restructure/jd_screen
GEMINI_API_KEY="your-key" uv run python main.py \
  --host 127.0.0.1 --port 8000 --name jd_screen \
  --provider gemini --model gemini-4-argon
```

Then open `http://127.0.0.1:8000` in your browser.
