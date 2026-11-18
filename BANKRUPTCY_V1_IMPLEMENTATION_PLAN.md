# Step 4: Implementation & Atomic-Commit Plan (`Bankruptcy v1`)

This plan breaks the implementation defined in [BANKRUPTCY_V1_ARCHITECTURE.md](file:///home/ben/restructure/jd_screen/BANKRUPTCY_V1_ARCHITECTURE.md) into **8 atomic commits**. Each commit is self-contained, keeps all existing `jd_screen` tests passing, and pairs its implementation with deep, adversarial unit and integration tests (never superficial happy-path-only checks).

---

## Atomic Commit Roadmap

1. **Commit 1: Shared Core Platform Extensions (`app/core/` & `canonical/tables/bankruptcy/`)**
   - `PIITokenizer` vault (`[PII:SSN_001]`, `[PII:ACCT_001_LAST4_4829]`), pluggable `OCRProvider` (`LocalOCRProvider` + `ModalOCRProvider` + `MockOCRProvider`), and `StatutoryTableRegistry` with effective-dated JSON tables (`federal_thresholds_2026.json`, `ustp_ca_means_test_2026.json`, `exemptions_2026.json`, `dependency_rules.json`).
   - Tests: `tests/test_pii_ocr_and_tables.py`
2. **Commit 2: Generalized Canonical Case Graph & Deterministic `ObservationVerifier`**
   - `ProvenanceField[T]`, `HumanOverrideRecord`, generalized `PartyEntity`, `AssetItem`, `ClaimItem` (Ch. 7/13/SubV ready), `CashFlowSeries`, `EmergingQuestionItem`, `CanonicalCaseGraph`, and `ObservationVerifier`.
   - Tests: `tests/test_bk_models_and_verifier.py`
3. **Commit 3: Pure-Python Deterministic Statutory Calculators (`app/bankruptcy/calculators/`)**
   - `EligibilityEngine` (H.R. 7730 `$2.75M` Ch. 13 & `$7.5M` SubV), `CMIAndMeansTestEngine` (`Form 122A/C`), Universal `ExemptionOptimizer` (`CA_CCP_704`, `CA_CCP_703_140`, `FEDERAL_522D`, `§ 522(p)`), and `Chapter13PlanCalculator`.
   - Tests: `tests/test_bk_calculators.py`
4. **Commit 4: Declarative Dependency Graph, Quantitative Forensics, Plausibility Auditor, & Strict Gate (`app/bankruptcy/audit.py`)**
   - `DeclarativeDependencyAuditor` (`dependency_rules.json` -> `EmergingQuestionItem`s), `QuantitativeForensicAuditor` (bank debt-service outflow matcher, inter-account transfer tracer, CMI/YTD/deposit triangulation), `PlausibilityAuditEngine`, and strict `FilingReadinessGate`.
   - Tests: `tests/test_bk_audit_and_gates.py`
5. **Commit 5: Uncategorized Document Harvester & `L0 → L1 → L2+` Bezier `CompiledBundle` Compiler**
   - `BankruptcyCaseExtractor` (many-to-many file-to-graph extraction) and `BankruptcyBundleCompiler` (compiles schedules, math, questions, and tensions into a normalized `CompiledBundle` DAG for the Bezier canvas).
   - Tests: `tests/test_bk_extractor_and_bundle.py`
6. **Commit 6: `FormPacketPlanner`, `PyMuPDF` AcroForm Baker, Continuation Sheets, District Adapters (`CACB` & `CAEB`), & Credential Vault**
   - `FormPacketPlanner`, `AcroFormFillerAndBaker` (`doc.bake(annots=True, widgets=True)` + overflow continuation sheets + `field_lineage.json`), `CACBDistrictAdapter`, `CAEBDistrictAdapter` (`<= 8 MB` splitter), and `CredentialAndTOTPVault` (`Rule9011SignOffGate`).
   - Tests: `tests/test_bk_pdf_districts_and_vault.py`
7. **Commit 7: Standalone Bankruptcy FastAPI Server (`bankruptcy_main.py`) & Realistic Client Case Fixtures**
   - `/api/v1/bankruptcy/*` routes, `bankruptcy_main.py` (port `8001`), and two realistic pre-seeded multi-PDF cases (`bk_ch7_cacb_martinez` and `bk_ch13_caeb_chen`).
   - Tests: `tests/test_bk_api.py`
8. **Commit 8: Standalone Bankruptcy Workbench Frontend (`templates/bankruptcy.html`, `static/bankruptcy.js`) & Full Suite Verification**
   - `L0 → L1 → L2+` SVG Cubic Bezier Traceability Canvas for schedules/worksheets, inline Emerging Question & Contradiction resolution, `SourceInspectorDrawer`, and `FilingPacketDrawer` with Rule 9011 submission.
   - Tests: `tests/test_bk_e2e_ui.py` + full `uv run pytest tests/ -v`.

---

## Phase 2: Official PDF Forms, Canonical Corpus & Design-Partner Upgrade (Completed)

1. **Canonical Corpus & Official PDF Template Ingestion (`f85b2d8`, `bc7a74f`, `5104d3d`):**
   - Downloaded 25 official U.S. Courts, CACB, and CAEB fillable PDF forms into gitignored `canonical/tables/bankruptcy/templates/`.
   - Ingested 14 official CACB/CAEB LBR, CM/ECF manual, U.S. Courts Instruction, and California/Title 11 canonical authority files under `canonical/bankruptcy/` with Tier-1 `canonical/INDEX.md` routing.
   - Added [form_field_maps.json](file:///home/ben/restructure/jd_screen/canonical/tables/bankruptcy/form_field_maps.json) and `form_line_ref` lineage tracking in [pdf_engine.py](file:///home/ben/restructure/jd_screen/app/bankruptcy/pdf_engine.py).
2. **UI Hardening & `NextBlockerStepper` (`391355f`):**
   - Refactored [static/bankruptcy.js](file:///home/ben/restructure/jd_screen/static/bankruptcy.js) and [static/styles.css](file:///home/ben/restructure/jd_screen/static/styles.css) to replace multi-card clutter with the single-focus `NextBlockerStepper`, align `L0` sections to `Form 101` / `Form 106Sum` / `Schedule A/B–J` line numbers, remove fake defaults, and pass `impeccable detect` (`[]`).
3. **6-Part Design-Partner Upgrade (`schedule_ab_taxonomy.json` -> `ch13_plan.py` -> `bankruptcy.js`):**
   - **53-Line Schedule A/B Taxonomy & Best Case 35-Item Aliases:** [schedule_ab_taxonomy.json](file:///home/ben/restructure/jd_screen/canonical/tables/bankruptcy/schedule_ab_taxonomy.json) + orthogonal `exemption_pool` + Two-Tier `MANDATORY_ASSET_AND_WINDFALL_SWEEP`.
   - **Unknown Valuations & *Schwab v. Reilly* `"100% of FMV"`:** `valuation_state="unknown"`, `check 2.1..2.3` (`fair#20market`) on `B106C.pdf`, `workers_comp`, `personal_injury`, `75%` `unpaid_wages`, `social_security_deposit`, `life_insurance_csv`, and regime tie-breaking.
   - **Cross-Document Forensics & Sync:** Trauma/medical PI detector, bidirectional `SOFA Line 9 ↔ A/B ↔ E/F`, `60-day` paystub continuity check, and `180-day` windfall checks.
   - **Married Filing Separately:** `Column B` Spouse CMI, Form `122A-2 Line 3` Marital Adjustment deduction, separate-and-apart exclusion, and `CCP § 703.140(a)(2)` spousal waiver gate.
   - **Federal Caps on State Exemptions:** Form 106C Line 3 `check 3` / `check 3-1`, `§ 522(p)(2)(B)` rollover, `§ 522(o)` reduction, `§ 522(n)` `$1,711,975` IRA cap, and `§ 541(b)(5)–(6)` 529 lookbacks.
   - **Chapter 13 Upgrade & Table Sync:** `910-day` vehicle cramdown, *Lam/Zimmer* junior lien strip, trustee/attorney fee math, `§ 1325(a)(6)` feasibility gate, `§ 1308` 4-year tax return check, `--sync-statutory-tables`, and `POST /api/v1/bankruptcy/tables/sync`.
   - Verified with `73 passed, 2 skipped` across `uv run pytest tests/ -v`.
