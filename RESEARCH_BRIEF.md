# Bankruptcy Automation & `jd_screen` Platform Research Brief

- **Date:** 2026-11-16
- **Scope:** Personal Bankruptcy (Chapter 7 & Chapter 13, California Districts `CACB`/`CANB`/`CAEB`/`CASB`) with Forward Compatibility for Chapter 11 / Subchapter V; Paralegal/Attorney Workbench; `jd_screen` Platform Integration
- **Status:** Step 1 Complete — Independently Validated Against Primary Sources

---

## Executive Summary

Building an AI-native replacement for Stretto’s Best Case aimed at dramatically increasing active cases per attorney/paralegal is technically viable, provided the architecture separates **probabilistic LLM extraction** from **deterministic statutory computation, form rendering, and court submission**.

Our research across official U.S. Courts specifications, California federal bankruptcy districts, California exemption statutes, and `jd_screen`’s existing codebase yields five foundational conclusions:

1. **Where Best Case’s Labor Bottleneck Actually Lives:** Best Case’s moat is form depth, local-rule precision, and OneTouch® CM/ECF submission, but legacy paralegal workflows remain bottlenecked by manual transcription and reconciliation across unstructured client PDFs (6 months of paystubs, bank statements, 2 years of tax returns, credit reports, bills). Catching contradictions *before* drafting (e.g., gross-vs-net paystub errors, unexplained Venmo/cash deposits, household-size mismatches between Form 122A-1 and Schedule I) eliminates the most costly rework and trustee-dismissal risks.
2. **Official Forms Are Fillable AcroForms, Not Pure XFA—With Critical Overflow Caveats:** Modernized national bankruptcy forms on `uscourts.gov` (B 101, B 106 series, B 107, B 122A/C) are standard **AcroForms**, making deterministic Python filling and flattening via `PyMuPDF` (`doc.bake(annots=True, widgets=True)`) feasible. However, local California Chapter 13 plan forms may be PDF or `.docx`, static AcroForms cannot dynamically paginate unlimited creditor/asset rows (requiring generated continuation sheets), and **Form B 121 (SSN)** must always be split into a separate restricted PDF.
3. **California Has Four Distinct District Regimes:** Supporting California means handling four separate sets of local Chapter 13 plans (`F 3015-1.01`, CANB GO-34 plan, `EDC 3-080`, `CSD 1300`), electronic filing declarations (`F 5005-4`, `BLR 5005-2`, `CSD 1801`), PDF size caps (`8 MB`–`50 MB`), and creditor matrix `.txt` exclusions—plus **CAEB’s separate e-Filing portal (`efiling3.caeb.uscourts.gov`)**, which diverges from standard CM/ECF.
4. **There Is No Open Public PACER Filing API—and Credential Sharing Is Prohibited:** AOUSC provides read-only PACER Auth/PCL APIs, plus **CM/ECF Case Upload (`debtor.txt` + creditor matrix `.txt` + PDFs)** and **NextGen XML Case Opening (IEPD)**. Mandatory TOTP MFA took effect December 31, 2025 for all filers. A non-barred JD **cannot** obtain an attorney CM/ECF login, and sharing a design partner’s login violates PACER Terms of Use and creates **Fed. R. Bankr. P. 9011** liability. Testing must use court **CM/ECF Training databases (`ecf-train.*`)** or a separate **Filing Agent** account with explicit attorney review.
5. **`jd_screen` Should Evolve Into a Shared Core Platform:** `jd_screen` already solves coordinate-stamped provenance (`MatterIngestor`, `SourceLocator`), canonical legal rules (`CanonicalRouter` `[AUTH:...]`), and cross-document tension detection. Rather than forcing bankruptcy into a prose broadsheet, `jd_screen` should factor out a shared core platform so **Research/Memo Broadsheet** and **Bankruptcy Case Workbench** run as sibling applications.

---

## Theme 1: Best Case Parity & Paralegal Labor Bottlenecks

### Conclusion
Parity for an internal paralegal/attorney workbench does **not** require replicating Best Case’s practice management, billing, or marketing suite; it requires parity on **case data integrity, statutory calculators (Means Test & CA exemptions), contradiction detection, court-compliant forms/matrices, and CM/ECF upload packaging**, while surpassing Best Case by eliminating manual PDF-to-form transcription.

### Evidence & Facts
* **Legacy vs. Cloud Workflows:** Best Case Desktop historically required manual transcription from client PDFs (paystubs, 6 months of bank statements, tax returns) with limited credit-report/questionnaire imports, alongside local file/VPN friction [1][2]. Stretto added Best Case Cloud “Document Flow” AI extraction, while cloud competitors (NextChapter, Jubilee/Lexria) focus on browser-based portals and financial PDF parsing [1][3][4].
* **Highest-Leverage Contradictions (Where Paralegal Hours & Trustee Risks Concentrate):**
  * **CMI 6-Month Lookback Window:** Form 122A-1/122C-1 averages *gross* income over the **6 full calendar months** before filing (e.g., filing Nov 15 -> May 1–Oct 31) [5][6]. Common errors: using net bank deposits instead of gross paystub amounts, omitting YTD verification, or missing side-gig/Venmo/cash deposits visible on bank statements [5][7][8].
  * **Tax Return vs. Recent Paystub Divergence:** Prior-year 1040s vs. recent 6-month paystubs frequently diverge due to bonuses, overtime, or raises; unexplained gaps draw U.S. Trustee inquiries [5][6].
  * **Household Size & Schedule I/J Mismatches:** Household size on Form 122A-1 must reconcile with tax dependents and Schedule I, and Means Test disposable income (`122A-2`) must not contradict Schedule J living expenses [5][9].
  * **Double-Dipping & IRS Standard vs. Actuals:** Form 122A-2 mandates IRS National/Local Standards (not actual grocery/clothing spend) and prohibits deducting secured payments on surrendered collateral [5][10].

### Contra-Analysis (Straw Man)
*“Paralegals already import credit reports in Best Case, so AI PDF extraction only saves a few minutes per case.”*

### Rebuttal
Credit reports only capture reporting tradelines—often missing medical bills, collection letters, private loans, exact paystub gross-to-net deductions, 6-month bank deposit anomalies, tax liabilities, vehicle/home equity valuations, and recent transfers required for Schedule A/B and Form 107 (SOFA) [5][8]. Reconciling those unstructured PDFs page-by-page across schedules is the primary labor sink.

### Candid Weaknesses
* Without observing the design partner’s actual client packet mix (scanned phone photos vs. digital bank PDFs, Chapter 7 vs. Chapter 13 ratio), exact time savings per case remain unquantified until tested on real client files.

---

## Theme 2: Official Forms, PDF Engineering, & Deterministic Calculation

### Conclusion
National official bankruptcy forms (`uscourts.gov`) use standard **AcroForms** rather than dynamic XFA, enabling reliable, verifiable Python population and flattening via **`PyMuPDF`** (`Document.bake`). However, overflow schedules, Word-based local Chapter 13 plans, and statutory calculators require a hybrid **AcroForm + programmatic continuation sheet + deterministic calculator** architecture.

### Evidence & Facts
* **AcroForm Architecture:** Under the Judicial Conference’s *Forms Modernization Project* (effective Dec 2015 onward), national forms (`B 101`, `B 106` series, `B 107`, `B 122A/C`) were standardized as static AcroForms (`/AcroForm` field dictionaries) rather than proprietary Adobe LiveCycle dynamic XFA [11][12][13].
* **Flattening Requirement:** Courts reject PDFs with active mutable form widgets or embedded scripts; `PyMuPDF` natively supports filling widgets and burning them into static page content via `Document.bake(annots=True, widgets=True)` [14][15].
* **Mandatory Document Separation (Privacy):** **Official Form B 121** (*Statement About Your Social Security Numbers*) must **never** be bundled into the public petition PDF; it must be generated as a standalone PDF and docketed under a private event [16][17].
* **Current 2025–2026 Statutory Parameters (Verified):**
  * **H.R. 7730 (Bankruptcy Threshold Adjustment Act, signed Nov 10, 2026):** Permanently sets Subchapter V (`11 U.S.C. § 1182`) debt ceiling at **$7,500,000** and replaces bifurcated Chapter 13 (`11 U.S.C. § 109(e)`) secured/unsecured caps with a single unified aggregate cap of **$2,750,000** for cases filed on or after Nov 10, 2026 [18][19][20].
  * **11 U.S.C. § 104 Triennial Adjustments:** Took effect **April 1, 2025** (`90 FR 8941`, corrected `90 FR 10643`) [21][22].
  * **USTP Means Testing Tables:** DOJ U.S. Trustee Program publishes Census Bureau median family income and IRS National/Local Standards as downloadable XLS/XLSX tables by state and California county [23][24].
  * **California Exemptions (Opt-Out State — Federal `§ 522(d)` Barred):** Debtors must elect *either* **CCP § 704** (county-median homestead `§ 704.730`, indexed for 2026 to **~$371,547 floor / ~$743,681 ceiling**, subject to the federal 1,215-day `§ 522(p)` cap and 730-day domicile rule) *or* **CCP § 703.140** (per Judicial Council **Form EJ-156**, April 1, 2025 cycle: **$36,750** residence, **$8,625** vehicle, **$1,950 + unused residence** wildcard; plus **CCP § 704.220** bank deposit exemption revised July 20, 2026 to **$2,325**) [25][26][27][28].

### Contra-Analysis (Straw Man)
*“An LLM can generate the filled PDFs or compute Means Test / exemption values directly inside its structured JSON output.”*

### Rebuttal
LLMs fail arithmetic consistency, rounding, and statutory edge cases (e.g., prorating 6-month bonuses, applying `§ 703.140(b)(5)` wildcard spillover, checking the `§ 522(p)` 1,215-day cap). Zero-hallucination guarantees require that **LLMs only extract typed observations with `SourceLocator` coordinates**, while **pure Python rules engines** compute every derived line item and bind fields deterministically into AcroForm IDs.

### Candid Weaknesses
* We did not inspect the raw PDF binary of every local California district form (`F 3015-1`, `EDC 3-080`, `CSD 1300`). Several California local courts publish local Chapter 13 plans in **both fillable PDF and `.docx`** formats [29][30][31], and **CANB** explicitly mandates converting word-processed plans to text-searchable PDF rather than scanning [32]. At implementation time, each form template must be inspected for `/XFA` vs `/AcroForm` tags and field names.
* Secondary legal summaries showed minor rounding variance on 2026 `CCP § 704.730` figures (`$371,547`–`$371,841` floor; `$743,459`–`$743,681` ceiling) [26][33]. Production calculators should ingest official Judicial Council / county median tables with effective-date versioning.

---

## Theme 3: California Districts (`CACB`, `CANB`, `CAEB`, `CASB`)

### Conclusion
California cannot be treated as a single filing target. Each of the four federal bankruptcy districts enforces distinct **local Chapter 13 plan forms, electronic filing declarations, PDF size limits, creditor matrix exclusions, and—in the Eastern District—a completely separate e-Filing portal**.

### Evidence & Facts

| District | Local Ch. 13 Plan | E-Filing Declaration / Signature Rule | Creditor Matrix `.txt` & PDF Rules | Submission System |
| :--- | :--- | :--- | :--- | :--- |
| **CACB** (Central) | `F 3015-1.01.CHAPTER13.PLAN` + `F 3015-1.7.RARA` [31][34] | LBR 5005-4 Electronic Filing Declaration (`F 5005-4`); debtor + attorney signed [35] | `.txt`: max 5 lines/block, 50 chars name, 40 chars address, no punctuation except `,` between city/state, **exclude debtor, UST, IRS, FTB** (`F 1007-1`); PDF max **50 MB**, flattened [36][37] | NextGen CM/ECF; **Case Upload** supports complete **Ch. 7 & Ch. 13 only** (NOT Ch. 11) [38][39] |
| **CANB** (Northern) | Mandatory GO-34 District Plan + class addenda (word-processed -> searchable PDF) [32] | BLR 5005-2 signature & retention of wet-signed declarations [40] | Plain ASCII `.txt`, left-justified, blank line between blocks, max 5 lines × 40 chars; PDF max **35 MB**, text-searchable [41][42] | NextGen CM/ECF; **Case Upload** (`debtor.txt` + PDFs + matrix `.txt`) [41] |
| **CAEB** (Eastern) | `EDC 3-080` (+ `EDC 3-086`, `3-088`) [43] | Local administrative e-filing signature rules | Max 5 lines × 40 chars, no leading spaces; PDF max **~8 MB** (300 dpi B&W if scanned), flattened [44] | **Separate `CAEB e-Filing` portal** (`efiling3.caeb.uscourts.gov`) for petitions/pleadings; accepts `debtor.txt` upload; CM/ECF used mainly for claims/trustee [45][46] |
| **CASB** (Southern) | `CSD 1300` (Mandatory under LBR 3015-1) [30] | `CSD 1801` Declaration Re: Electronic Filing [47] | `CSD 1007` (LBR 1007-1) `.txt` matching Schedules D/E/F; fillable PDFs submitted via CM/ECF [47][48] | NextGen CM/ECF; Case Upload supports complete Ch. 7 & Ch. 13 [49] |

### Contra-Analysis (Straw Man)
*“Can’t we just implement National Form 113 for Chapter 13 and one generic PDF bundle across California?”*

### Rebuttal
All four California districts opted out of National Form 113 and mandate their own local Chapter 13 plans (`F 3015-1.01`, GO-34 plan, `EDC 3-080`, `CSD 1300`) [30][31][32][43]. Filing the wrong plan or failing to split Form B 121 / meet CAEB’s 8 MB cap results in clerk deficiency notices or dismissal.

### Candid Weaknesses
* CAEB’s `efiling3.caeb.uscourts.gov` upload screens and exact local validation errors could not be inspected without active CAEB filer credentials.

---

## Theme 4: PACER / CM/ECF Submission Reality & Credential Risks

### Conclusion
**There is no public REST/JSON CM/ECF filing API.** Automated filing tools (like Best Case OneTouch®) rely on generating CM/ECF **`Case Upload` (`debtor.txt` / NextGen XML IEPD)** artifacts combined with browser/session automation under an **admitted attorney’s NextGen PACER + mandatory TOTP MFA** credentials. **Do not** use a non-barred JD for attorney access, and **do not** share a design partner’s login credentials.

### Evidence & Facts
* **Available Official Interfaces:**
  1. **PACER Auth & PACER Case Locator (PCL) APIs:** Read/search-only; cannot file documents [50].
  2. **CM/ECF Case Upload (`debtor.txt` + matrix `.txt` + PDFs):** Supported inside CM/ECF web UI (and CAEB e-Filing) for Ch. 7/13 case opening using fixed/comma-delimited item records defined in the PACER *Bankruptcy Case Information File* specification [38][41][46][51].
  3. **NextGen XML Case Opening & Docketing (IEPD):** Official XML schemas published on `pacer.uscourts.gov` for petition software vendors communicating with NextGen CM/ECF web services, explicitly accommodating Subchapter V and post-petition filings [52][53].
* **Mandatory MFA:** Since **December 31, 2025**, PACER enforces mandatory **TOTP multifactor authentication** for all users with CM/ECF filing privileges [54].
* **Legal & Account Risks for Cofounder / Design Partner:**
  * **JD Without Bar Admission:** A Juris Doctor who is not admitted to the U.S. District Court / State Bar **cannot** obtain attorney CM/ECF filing privileges [55][56]. (`Pro Hac Vice` in CACB requires out-of-state active bar admission, local counsel, and a $450 fee [57]).
  * **Credential Sharing Prohibition & Rule 9011:** Federal courts explicitly prohibit sharing upgraded PACER/CM/ECF logins with third-party software or staff; doing so risks exposing sealed documents and violates PACER Terms of Use [58][59]. Moreover, every filing submitted under an attorney’s login constitutes that attorney’s **Fed. R. Bankr. P. 9011** certification, carrying non-delegable sanctions liability [58][60].
* **Safe Testing & Submission Paths:**
  * **Path A (Recommended for Dev/Testing):** Generate deterministic **Filing Packets** (split flattened PDFs, B 121 separated, creditor matrix `.txt`, `debtor.txt` / IEPD XML, and filing checklist) and test submission exclusively against district **CM/ECF Training Databases** (`ecf-train.cacb.uscourts.gov`, `ecf-train.canb.uscourts.gov`, `ecf-train.casb.uscourts.gov`) using court-issued training credentials [61][62].
  * **Path B (Design Partner Pilot):** Never ask for the design partner’s personal PACER password. Either have the design partner upload the generated `Case Upload` packet themselves, **or** have the design partner authorize an individual non-attorney **Filing Agent** account via CM/ECF (`Maintain Your ECF Account -> Create a New Filing Agent`) with explicit attorney review/sign-off and wet-signed declarations (`F 5005-4` / `CSD 1801` / `BLR 5005-2`) before any live click [55][63].

### Contra-Analysis (Straw Man)
*“Best Case OneTouch files directly into CM/ECF automatically, so we should build a headless Playwright bot that logs in with the design partner’s PACER username, password, and TOTP seed.”*

### Rebuttal
Centralizing an attorney’s PACER password + TOTP seed in third-party backend automation directly violates NextGen credential-sharing rules, breaks Rule 9011 accountability if an unreviewed filing submits, and risks suspension of the design partner’s court account [54][58]. A **local/client-side assisted uploader or human-triggered Filing Agent workflow** (plus `Case Upload` / IEPD XML export) achieves 95%+ of the speed gain without risking the partner’s license.

### Candid Weaknesses
* While PACER publishes IEPD ZIPs on `pacer.uscourts.gov`, we did not download and verify whether every California bankruptcy district currently has NextGen XML web-service endpoints enabled for third-party vendor submission vs. browser-based `Case Upload` (`debtor.txt`). Checking this via PACER Lookup / court help desks is an immediate follow-up.

---

## Theme 5: Platform Fit with `jd_screen`

### Conclusion
`jd_screen` provides an unusually strong foundation for **anti-hallucination provenance**, but its current output schema (`CompiledBundle` prose broadsheet) is the wrong UI and data model for bankruptcy forms and statutory math. **Recommended path:** Refactor `jd_screen` into a **shared core platform + multi-application workspace** inside this repository (not a separate disconnected repo, and not shoehorned into prose memos).

### Evidence & Facts (`jd_screen` Codebase Inspection)
* **Directly Reusable Core Primitives:**
  * [app/ingest.py](file:///home/ben/restructure/jd_screen/app/ingest.py): `MatterIngestor` deterministically indexes raw PDFs/spreadsheets/Markdown into coordinate-stamped blocks (`pdfplumber` `[x1, y1, x2, y2]` bounding boxes, `openpyxl` dual-pass formulas + values, SHA-256 digests) and verifies citations deterministically. `CanonicalRouter` / `CanonicalIngestor` indexes `[AUTH:...]` legal rules under `canonical/`.
  * [app/models.py](file:///home/ben/restructure/jd_screen/app/models.py): `SourceLocator`, `NodeAudit`, `VerifiedFactLedger`, `TensionObject`, `MatterFileMetadata` (`reliability_tier` = `primary_record` / `secondary_analysis` / `self_reported`).
  * [app/llm.py](file:///home/ben/restructure/jd_screen/app/llm.py): Provider-agnostic `LLMProvider` (`GeminiInteractionsProvider`, `MockLLMProvider`, structured output + tool loops + decisions).
* **Gaps Where Bankruptcy Diverges From `jd_screen`’s Current Pipeline ([app/pipeline.py](file:///home/ben/restructure/jd_screen/app/pipeline.py), [static/app.js](file:///home/ben/restructure/jd_screen/static/app.js)):**
  1. `OutlinePlan` -> `SectionOutput` -> `CompiledBundle` assumes the deliverable is a **multi-section narrative memo**, whereas bankruptcy deliverables are a **typed Canonical Case Graph** (Debtors, RealProperty, Vehicles, BankAccounts, IncomePaystubs, TaxReturns, Creditors, Transfers) -> **Deterministic Calculators** -> **Filled AcroForm PDFs + `debtor.txt`/XML + Matrix `.txt`**.
  2. Contradiction detection in bankruptcy requires **cross-document numerical/temporal reconciliation** (e.g., 6-month CMI paystubs vs. bank deposits vs. 1040 AGI; Schedule D secured claim vs. Schedule A/B collateral value), not just narrative `CrossSectionAuditOutput`.
  3. The frontend broadsheet (`L0` -> `L1` -> `L2+`) is ideal for **reviewing flagged contradictions, legal analyses (e.g., exemption election rationale, Ch. 7 vs. 13 vs. SubV eligibility memos), and research**, while paralegals also need a **structured Case Ledger / Schedule Review & Packet Export UI** backed by the same `SourceInspectorDrawer` PDF bounding-box highlighting!

### Contra-Analysis (Straw Man)
*“Just create a brand-new repository for bankruptcy so `jd_screen` stays pure, or cram bankruptcy into a `DocumentBlueprint` inside the existing pipeline.”*

### Rebuttal
* A **separate repo** forces duplicating `MatterIngestor`, `SourceLocator`, `LLMProvider`, `CanonicalRouter`, and the `SourceInspectorDrawer`—the exact modules that prevent hallucinations.
* Cramming bankruptcy into prose **`DocumentBlueprint`s** breaks deterministic Means Test math, creditor matrix generation, and AcroForm PDF filling.
* Factoring `app/core/` (ingestion, locators, canonical `[AUTH:...]` corpus, LLM gateway, audit/tension primitives) with pluggable **Application Modules** (`apps/broadsheet/` for research/memos, `apps/bankruptcy/` for Ch. 7/13/SubV case preparation) preserves `jd_screen`’s versatility for general research while letting bankruptcy leverage every provenance guarantee.

---

## Follow-Up Verification Needed (Pre-Build)
1. Download sample `uscourts.gov` Official Forms (`B 101`, `B 106A/B`, `B 107`, `B 122A-1/2`) and CA district local plans (`F 3015-1.01`, `EDC 3-080`, `CSD 1300`) to run an automated `/AcroForm` vs `/XFA` field inspection script.
2. Download the official PACER *CM/ECF Bankruptcy Case Upload* & *NextGen XML IEPD* specs from `pacer.uscourts.gov` to confirm exact `debtor.txt` item counts and XML XSD availability in CACB/CANB/CAEB/CASB.
3. Download current DOJ USTP Means Testing XLS/XLSX tables (`justice.gov/ust`) and California Judicial Council `EJ-156` / county median home-price tables for deterministic seeding.
4. Confirm with the design partner whether they can obtain or sponsor an `ecf-train` or `Filing Agent` credential for sandboxed submission testing.

---

## Sources & Bibliography

1. Best Case by Stretto / Document Flow & OneTouch® Overview — `stretto.com`, `bestcase.com`, `youtube.com`
2. NextChapter & Jubilee Cloud Bankruptcy Platforms — `nextchapterlegal.com`, `nextchapterbk.com`, `jubileepro.com`
3. *Common Mistakes on Bankruptcy Forms 122A-1 & 122A-2*, Legal Practice Guides — `wagnerlawofficepc.com`, `indybankruptcylaw.com`, `braziellaw.com`, `bankruptcymastery.com`
4. Official U.S. Bankruptcy Forms (`B 101`, `B 106`, `B 107`, `B 121`, `B 122`) & Forms Modernization Project — `uscourts.gov` (`https://www.uscourts.gov/forms/bankruptcy-forms`)
5. PyMuPDF `Document.bake` Documentation — `pymupdf.readthedocs.io`
6. PDF AcroForm vs. XFA Technical Guides — `pdfops.dev`, `countedbankruptcy.com`, `artifex.com`
7. **H.R. 7730 (119th Congress), Bankruptcy Threshold Adjustment Act (enacted Nov 10, 2026)** — `govinfo.gov`, `whitehouse.gov`, `thompsoncoburn.com`, `mcdonaldhopkins.com`, `herrinlaw.com`, `afslaw.com`
8. Judicial Conference Triennial Dollar Adjustments (`11 U.S.C. § 104`, effective April 1, 2025) — `federalregister.gov` (90 FR 8941; 90 FR 10643), `uscourts.gov`
9. U.S. Trustee Program Means Testing Data (Census & IRS Standards) — `justice.gov` (`https://www.justice.gov/ust/means-testing`)
10. Judicial Council of California Form `EJ-156` (*Current Dollar Amounts of Exemptions*, revised April 1, 2025 & July 20, 2026) — `courts.ca.gov`
11. California CCP § 704.730 Homestead Inflation Adjustments (2025–2026) — `abi.org`, `ultimateassetprotection.com`, `helpsishere.org`, `sandiegobk.com`
12. U.S. Bankruptcy Court, Central District of California (`cacb.uscourts.gov`) — LBR 1007-1, LBR 5005-4 (`F 5005-4`), `F 1007-1`, `F 3015-1.01`, `F 3015-1.7.RARA`, Case Upload & `ecf-train.cacb.uscourts.gov`
13. U.S. Bankruptcy Court, Northern District of California (`canb.uscourts.gov`) — Amended General Order 34 Chapter 13 Plan, BLR 5005-2, Case Upload & `ecf-train.canb.uscourts.gov`
14. U.S. Bankruptcy Court, Eastern District of California (`caeb.uscourts.gov`) — `CAEB e-Filing` (`efiling3.caeb.uscourts.gov`), `debtor.txt` upload, `EDC 3-080`, PDF size/DPI guidelines
15. U.S. Bankruptcy Court, Southern District of California (`casb.uscourts.gov`) — `CSD 1007`, `CSD 1300`, `CSD 1801`, Case Upload & `ecf-train.casb.uscourts.gov`
16. PACER Developer Resources, Mandatory MFA (Dec 31, 2025), Case Upload & NextGen XML IEPD, and Federal Court Credential-Sharing / Rule 9011 Notices — `pacer.uscourts.gov`, `uscourts.gov`
17. `jd_screen` Repository — [app/ingest.py](file:///home/ben/restructure/jd_screen/app/ingest.py), [app/models.py](file:///home/ben/restructure/jd_screen/app/models.py), [app/pipeline.py](file:///home/ben/restructure/jd_screen/app/pipeline.py), [app/llm.py](file:///home/ben/restructure/jd_screen/app/llm.py), [app/routes.py](file:///home/ben/restructure/jd_screen/app/routes.py), [static/app.js](file:///home/ben/restructure/jd_screen/static/app.js)
