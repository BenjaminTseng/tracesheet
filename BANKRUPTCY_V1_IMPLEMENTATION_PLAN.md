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
