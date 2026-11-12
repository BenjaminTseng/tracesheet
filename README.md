# Audit-Grounded Spatial Document Canvas (`jd_screen`)

A bounded spatial canvas and verification engine for introspecting AI-generated documents alongside their multi-level reasoning, evidence, authority, calculation, and assumption Directed Acyclic Graph (DAG).

## Architecture Overview

1. **Backend (`FastAPI` + `Pydantic` + `Jinja2`):**
   - `app/models.py`: Implements both Tier 1 (`SectionOutput`) and Tier 2 (`CompiledBundle`) schemas, plus the deterministic verification and compilation pipeline (`SectionValidator`, `StitchInvariantGate`, and `CompiledGraphBuilder`).
   - `app/sample_data.py`: Ships with multi-level sample bundles (`legal_motion_1332` and `candidate_exec_screen`) showcasing all 6 node types (`claim`, `evidence`, `reasoning`, `authority`, `calculation`, `assumption`), all 5 polymorphic source locators (`pdf`, `spreadsheet`, `web`, `api`, `internal_db`), 3-level sub-citation chains, and cross-section tension alerts.
   - `app/routes.py`: Serves the spatial UI shell and REST endpoints (`GET /api/bundles`, `GET /api/bundles/{id}`, `POST /api/bundles`, `POST /api/compile`).

2. **Frontend (`Preact` + `HTM` via ESM, zero build step):**
   - `static/styles.css`: Implements the pure light-mode design system (`#FFFFFF` base, `#F8FAFC` subtle slate cards, `1px solid #E2E8F0` crisp borders, `#1E3A8A` classic deep navy accents, `Newsreader` editorial serif headings paired with `Inter` UI copy and `JetBrains Mono` telemetry).
   - `static/app.js`: Renders the 3-column bounded spatial canvas (`L0 Synthesized Artifact` → `L1 Primary Reasoning & Evidence` → `L2+ Backing Authorities & Sub-Citations`) with dynamic SVG cubic Bezier connector vectors, hover preview tooltips, click-to-pin branch isolation, and a slide-over **Source Inspector Drawer** (rendering simulated PDF bounding boxes, Excel spreadsheet cell tables, API JSON payloads, read-only SQL queries, and web snapshots).

## WSL2 Execution & Testing Commands

### 1. Run Unit & API Test Suite
```bash
cd ~/restructure/jd_screen
uv run pytest tests/ -v
```

### 2. Start the Development Server
```bash
cd ~/restructure/jd_screen
uv run python main.py --host 127.0.0.1 --port 8000 --name jd_screen
```

Then open `http://127.0.0.1:8000` in your browser.
