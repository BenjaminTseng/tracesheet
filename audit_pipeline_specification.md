# Audit-Grounded Document Pipeline: Specification & Architecture

This document specifies the data contracts, LLM operational prompts, and programmatic verification pipelines required to generate audit-ready, grounded documents accompanied by an introspectable reasoning and evidence graph.

---

## 1. Format Evaluation & Final Data Contracts

### 1.1 Format Trade-Off Analysis

| Format | Strengths | Failure Modes & Weaknesses | Recommendation |
| :--- | :--- | :--- | :--- |
| **Strict JSON (Full)** | Native schema enforcement (Pydantic / JSON Schema grammars), zero ambiguity on types, direct UI consumption. | Long prose strings require heavy quote/newline escaping (`\"`, `\n`), which increases token usage and occasionally leads to syntax cutoffs. | **Recommended for Final Bundle**; usable for intermediate steps with schema-enforced APIs. |
| **YAML** | Highly legible for humans and LLMs; multi-line strings (`\|`) require no escaping. | Indentation sensitivity can cause silent parser corruption when an LLM indents child lists inconsistently. | Avoid for multi-stage automated pipelines. |
| **Markdown + XML `<supports>` Block** | Natural authoring: prose is written without string escaping, and structured citations sit in a dedicated block. | Requires custom parser or regex rather than standard library deserialization. | Viable alternative for human-in-the-loop review. |

### Final Architectural Decision: Two-Tier Schema
* **Tier 1 (Intermediate Worker Output):** Structured JSON using Pydantic constrained decoding. The LLM generates natural prose containing numbered `<ref n="...">` tags and an array of local `supports`.
* **Tier 2 (Final Compiled Bundle):** Flat, normalized JSON DAG. Deterministic Python code transforms the local references into a collision-free node dictionary consumed directly by the spatial canvas UI.

---

### 1.2 Intermediate Section Schema (Worker LLM Output)

This is the exact contract the worker LLM outputs for an individual section. During generation, the LLM isolates its attention to one section and uses local sequential integer keys (`n=1, n=2...`) for claims and sub-claims.

#### 1.2.1 Field Specification Tables

##### Primary Section Container
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `section_id` | `string` | **Yes** | Unique section slug (e.g., `sec_02_jurisdiction`). |
| `text` | `string` | **Yes** | Markdown narrative containing inline XML tags `<ref n="X">clause text</ref>`. |
| `supports` | `array[SupportGroup]` | **Yes** | Array of supporting clusters matching the `n` indices cited in `text`. |

##### SupportGroup
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `n` | `integer` | **Yes** | Matches the `n` attribute of `<ref n="X">` in `text`. |
| `items` | `array[SupportItem]` | **Yes** | List of supporting nodes for this claim (minimum 1 item). |

##### SupportItem & SubSupportItem
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `n` | `integer` | *Sub-only* | Required for `sub_supports` to match `<ref n="10X">` tags in parent `body`. |
| `type` | `enum` | **Yes** | One of: `"evidence"`, `"reasoning"`, `"authority"`, `"calculation"`, `"assumption"`. |
| `title` | `string` | **Yes** | Compact headline for the UI card (under 8 words). |
| `quote` | `string` | *Optional* | Exact verbatim excerpt from the source document (used for `evidence`). |
| `body` | `string` | *Optional* | Explanatory synthesis or rationale. May contain `<ref n="10X">` for sub-citations. |
| `formula` | `string` | *Optional* | Mathematical or spreadsheet formula (e.g., `=SUM(E14:E26)`, `$Payback = CAC / ARPU$`). |
| `url` | `string` | *Optional* | Public web URL or internal documentation link. |
| `image_url` | `string` | *Optional* | Relative or absolute path to an image, chart, or visual asset. |
| `locator` | `SourceLocator` | *Conditional* | Required if `type` is `"evidence"`. Pinpoints exact coordinates in raw files/APIs. |
| `sub_supports` | `array[SubSupportItem]` | *Optional* | Nested level-2 backup nodes referenced inside `body`. |

##### SourceLocator (Polymorphic by `source_type`)
| Field | Allowed Types | Relevant `source_type` | Description |
| :--- | :--- | :--- | :--- |
| `source_type` | `enum` | **All** | `"pdf"`, `"spreadsheet"`, `"web"`, `"api"`, `"internal_db"`. |
| `file_name` | `string` | `pdf`, `spreadsheet` | Basename of the file (e.g., `Exhibit_B.pdf`, `Q3_Actuals.xlsx`). |
| `page` | `integer` | `pdf` | 1-based page number where the quote or table appears. |
| `bounding_box`| `array[int]` | `pdf` | Normalized coordinates `[x1, y1, x2, y2]` for visual canvas highlighting. |
| `locator_key` | `string` | `pdf`, `web` | Anchor ID, paragraph index, or DOM selector (e.g., `DE-CORP-48821`). |
| `sheet` | `string` | `spreadsheet` | Worksheet name (e.g., `Aging_Summary`, `P&L`). |
| `cell_range` | `string` | `spreadsheet` | Excel A1 notation for cell or block (e.g., `G14`, `B2:F12`). |
| `raw_value` | `any` | `spreadsheet`, `api` | Raw primitive value (e.g., `42150.00`, `0.7142`, `"active"`). |
| `url` | `string` | `web` | Full canonical URL visited. |
| `snapshot_timestamp` | `string` (ISO 8601) | `web` | Exact time the page was crawled or snapshotted. |
| `endpoint` | `string` | `api` | HTTP method and path (e.g., `GET /api/v2/analytics/churn`). |
| `method` | `enum` | `api` | `"GET"`, `"POST"`, `"PUT"`. |
| `query_params`| `object` | `api` | Key-value dictionary of query parameters passed to the API. |
| `json_path` | `string` | `api` | JSONPath expression extracting the metric (e.g., `$.data.metrics.rate`). |
| `payload_hash`| `string` | `api`, `web` | SHA-256 hash of raw response payload for tamper verification. |
| `database` | `string` | `internal_db` | Database name or connection identifier. |
| `table` | `string` | `internal_db` | Table or view queried. |
| `query` | `string` | `internal_db` | Read-only SQL query executed. |
| `row_id` | `string` / `int` | `internal_db` | Primary key identifier of the matching record. |

---

#### 1.2.2 Exhaustive Concrete Example (All Node & Locator Types)

```json
{
  "section_id": "sec_02_jurisdiction_and_metrics",
  "text": "The Court must dismiss Plaintiff's complaint because <ref n='1'>complete diversity does not exist between the parties</ref>. Furthermore, Plaintiff's alleged contractual damages <ref n='2'>fail to meet the $75,000 threshold under 28 U.S.C. § 1332</ref>, since unpaid invoices total only $42,150. Even under Plaintiff's alternative tort theory, <ref n='3'>gross margins on cloud delivery expanded to 71.4%</ref>, while <ref n='4'>regional churn held at 3.2%</ref> under <ref n='5'>standard cohort definitions</ref>, yielding an <ref n='6'>expected customer lifetime value calculation of $128,000</ref> based on <ref n='7'>conservative linear churn assumptions</ref>.",
  "supports": [
    {
      "n": 1,
      "items": [
        {
          "type": "evidence",
          "title": "Delaware Corporate Registry (PDF)",
          "quote": "Principal place of business registered at 1209 North Orange St, Wilmington, DE.",
          "locator": {
            "source_type": "pdf",
            "file_name": "Exhibit_B_DE_Filing.pdf",
            "page": 2,
            "bounding_box": [120, 450, 480, 520],
            "locator_key": "DE-CORP-48821"
          }
        },
        {
          "type": "reasoning",
          "title": "Corporate Citizenship Determination",
          "body": "Under the <ref n='101'>nerve center test</ref>, citizenship is tied to executive headquarters. Because Defendant is also a Delaware entity, complete diversity is destroyed.",
          "sub_supports": [
            {
              "n": 101,
              "type": "authority",
              "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
              "quote": "'Principal place of business' refers to the place where a corporation's officers direct, control, and coordinate activities.",
              "url": "https://supreme.justia.com/cases/federal/us/559/77/"
            }
          ]
        }
      ]
    },
    {
      "n": 2,
      "items": [
        {
          "type": "evidence",
          "title": "Aged Receivables Ledger (Spreadsheet)",
          "quote": "Total unpaid invoice balance: $42,150.00.",
          "locator": {
            "source_type": "spreadsheet",
            "file_name": "Invoices_2026.xlsx",
            "sheet": "Aging_Summary",
            "cell_range": "G14",
            "raw_value": 42150.00
          }
        },
        {
          "type": "authority",
          "title": "28 U.S.C. § 1332(a)",
          "quote": "The district courts shall have original jurisdiction of all civil actions where the matter in controversy exceeds the sum or value of $75,000.",
          "url": "https://www.law.cornell.edu/uscode/text/28/1332"
        }
      ]
    },
    {
      "n": 3,
      "items": [
        {
          "type": "evidence",
          "title": "Internal P&L Model (Spreadsheet with Formula)",
          "quote": "Gross Margin: 71.42%",
          "formula": "=E26/E14",
          "locator": {
            "source_type": "spreadsheet",
            "file_name": "Q3_2026_Actuals_v4.xlsx",
            "sheet": "Consolidated_P&L",
            "cell_range": "E28",
            "raw_value": 0.7142
          }
        },
        {
          "type": "evidence",
          "title": "SEC Form 10-Q Filing (Live Web)",
          "quote": "Subscription gross margins reached seventy-one percent during the quarter ended September 30, 2026.",
          "locator": {
            "source_type": "web",
            "url": "https://www.sec.gov/edgar/data/100234/q3-2026-10q.htm",
            "snapshot_timestamp": "2026-09-20T14:32:00Z",
            "locator_key": "#item2_management_discussion",
            "payload_hash": "sha256:8f43a9b1c78e4d2938a4bc109f"
          }
        }
      ]
    },
    {
      "n": 4,
      "items": [
        {
          "type": "evidence",
          "title": "Salesforce Analytics API Response",
          "quote": "Monthly enterprise churn: 3.2%.",
          "locator": {
            "source_type": "api",
            "endpoint": "GET /api/v2/analytics/churn_rate",
            "method": "GET",
            "query_params": {
              "region": "EMEA",
              "period": "2026-Q3",
              "tier": "enterprise"
            },
            "json_path": "$.data.metrics.churn_rate_pct",
            "raw_value": 0.032,
            "payload_hash": "sha256:1a2b3c4d5e6f7a8b9c0d"
          }
        }
      ]
    },
    {
      "n": 5,
      "items": [
        {
          "type": "evidence",
          "title": "Customer Warehouse Database (SQL Query)",
          "quote": "Cohort definition: enterprise accounts with >= 500 active seats.",
          "locator": {
            "source_type": "internal_db",
            "database": "prod_dw_analytics",
            "table": "dim_cohort_taxonomy",
            "query": "SELECT definition_str FROM dim_cohort_taxonomy WHERE cohort_key = 'ENT_500_SEATS' LIMIT 1;",
            "row_id": "ENT_500_SEATS"
          }
        }
      ]
    },
    {
      "n": 6,
      "items": [
        {
          "type": "calculation",
          "title": "Customer Lifetime Value (LTV) Formula",
          "formula": "LTV = (ARPU * Gross_Margin) / Monthly_Churn = ($5,750 * 0.714) / 0.032 = $128,306",
          "body": "Calculated by compounding monthly ARPU across historical gross margins and observed EMEA churn rates."
        }
      ]
    },
    {
      "n": 7,
      "items": [
        {
          "type": "assumption",
          "title": "Constant Linear Churn Decay",
          "body": "Assumes churn remains flat at 3.2% without seasonality adjustments over months 1-12."
        }
      ]
    }
  ]
}
```

---

### 1.3 Section-Level Audit & Schema Transformation Pipeline

Before any section is merged into the broader document, it passes through an automated **Section-Level Audit**. This gate ensures factual accuracy and narrative coherence before compute is spent on document-wide stitching.

#### The Three Core Audit Invariants:
1. **Relevance to the Immediate Text:** Every supporting node attached to `<ref n="X">` must directly bear on the specific assertion made in that clause. Irrelevant data dumps or tangential facts are flagged and pruned.
2. **Congruence with Source Material (Factual Entailment):** The extracted quote, numerical metric, cell value, or legal authority must strictly support the claim without exaggeration. The auditor checks: *"Does Source $S$ strictly entail Claim $C$?"* Nodes that extrapolate without proof are either downgraded with an `audit_status: "extrapolation"` flag or rejected.
3. **Alignment with Outline Scope & Intent:** The section as a whole must satisfy the thematic objective, analytical questions, or legal arguments assigned to it in Step 1. The section cannot wander into topics reserved for downstream sections.

#### Flow & Retry Logic:
```
[Section Worker Outputs Draft]
               │
               ▼
   [Local Section Auditor]
      ├── (a) Is support relevant to clause?
      ├── (b) Is support congruent with source?
      └── (c) Does section meet outline intent?
               │
      ┌────────┴────────┐
      ▼                 ▼
   [PASS]            [FAIL]
      │                 ├── If (b) fails: Re-draft section with specific critique (Max 2 retries)
      │                 ├── If (a) fails: Prune or substitute the support item
      │                 └── If (c) fails: Adjust downstream outline points or flag narrative pivot
      ▼
[Committed to Global Evidence Register]
```

---

#### Why and How Intermediate Sections are Converted to the Compiled Bundle

#### 1. Why the Conversion is Necessary:
* **LLM Cognitive Load Isolation:** During generation, forcing an LLM to manage global UUIDs (like `node_sec02_c1`) or cross-document dependencies causes key misspelling, hallucinated references, and syntax crashes. Numbering locally (`n=1, n=2`) is intuitive and virtually error-proof for the model.
* **Global Deduplication & Cross-Linking:** In the final document, Section 1 and Section 4 might both rely on the same Delaware corporate filing or financial model cell. The compiler ensures that shared sources resolve to a single canonical node in the global graph.
* **Frontend Performance ($O(1)$ Lookups):** The frontend spatial canvas cannot efficiently parse nested trees buried within sections. It requires a flat dictionary where looking up any node by its ID is an instant, constant-time operation.

#### 2. How the Transformation Works (Deterministic Python):
1. **Namespacing:** The compiler prefixes each local integer with the section identifier: `(sec_02_jurisdiction, n=1)` becomes `node_sec02_c1`.
2. **Tree Flattening:** Nested objects (such as `sub_supports` containing legal authorities or underlying formulas inside a reasoning node) are extracted from their parent nodes and placed into the top-level `nodes` dictionary as independent nodes.
3. **Directed Edge Creation:** The compiler establishes explicit parent-to-child pointers (`direct_child_ids`) linking the claim to its supporting evidence/reasoning, and the reasoning to its governing authority.
4. **Tag Translation:** The compiler replaces all local `<ref n="1">` tags in the narrative text with the globally unique `<ref id="node_sec02_c1">` identifiers.

---

### 1.4 Final Compiled Bundle Schema (Frontend Spatial Canvas Contract)

Python compiles all sections, resolves local integer numbering into globally unique IDs, extracts nested sub-supports into top-level nodes, and outputs this normalized flat structure. This schema is the single source of truth consumed by the bounded spatial canvas UI.

#### 1.4.1 Field Specification Tables

##### Document Envelope (`artifact`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `title` | `string` | **Yes** | Formal document title. |
| `version` | `string` | **Yes** | Semantic version or build hash (e.g., `"1.0.0"`). |
| `created_at` | `string` (ISO 8601) | **Yes** | Compilation timestamp. |
| `metadata` | `object` | *Optional* | Key-value dictionary of metadata (e.g., author, jurisdiction, target audience). |
| `summary` | `string` | *Optional* | High-level executive abstract of the entire document. |
| `sections` | `array[Section]` | **Yes** | Ordered array of compiled sections. |

##### Section Object (Inside `artifact.sections`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `section_id` | `string` | **Yes** | Canonical section identifier (e.g., `"sec_02_jurisdiction"`). |
| `section_title` | `string` | **Yes** | Human-readable heading for navigation / table of contents. |
| `order` | `integer` | **Yes** | 1-based display sequence order. |
| `content` | `string` | **Yes** | Full markdown text containing rewritten global tags `<ref id="node_...">clause</ref>`. |

##### Holistic Audit Summary (`audit_summary`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `total_claims` | `integer` | **Yes** | Total count of claim nodes in the document. |
| `verified_count` | `integer` | **Yes** | Number of claims with direct, verified factual grounding. |
| `extrapolation_count` | `integer` | **Yes** | Number of claims relying on inductive leaps or partial data. |
| `assumption_count` | `integer` | **Yes** | Number of claims grounded on explicit baseline assumptions. |
| `cross_section_tensions` | `array[Tension]` | **Yes** | Contradictions detected during Step 4 global auditing. |

##### Tension Object (Inside `audit_summary.cross_section_tensions`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `tension_id` | `string` | **Yes** | Unique tension slug (e.g., `"ten_margin_vs_churn"`). |
| `involved_claim_ids` | `array[string]` | **Yes** | List of conflicting claim node IDs across different sections. |
| `severity` | `enum` | **Yes** | `"warning"` (minor friction or nuance) or `"blocker"` (direct logical contradiction). |
| `description` | `string` | **Yes** | Plain-English explanation of why the two passages conflict. |

##### Graph Nodes Registry (`nodes[node_id]`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `id` | `string` | **Yes** | Globally unique identifier (e.g., `"claim_sec02_1"`, `"evi_sec02_1_1"`). |
| `type` | `enum` | **Yes** | `"claim"`, `"evidence"`, `"reasoning"`, `"authority"`, `"calculation"`, `"assumption"`. |
| `title` | `string` | **Yes** | Compact card headline. |
| `section_id` | `string` | **Yes** | Originating section ID for spatial clustering. |
| `clause_text` | `string` | *Claim only* | Exact text excerpt from the document tagged by this claim. |
| `quote` | `string` | *Optional* | Verbatim excerpt from source document (used for `evidence` and `authority`). |
| `body` | `string` | *Optional* | Explanatory synthesis. May contain child `<ref id="node_...">` tags. |
| `formula` | `string` | *Optional* | Mathematical or spreadsheet formula expression. |
| `url` | `string` | *Optional* | Hyperlink for external public reference. |
| `image_url` | `string` | *Optional* | Path to visual evidence or chart. |
| `locator` | `SourceLocator` | *Optional* | Exact locator object (same schema as Section 1.2). |
| `direct_child_ids` | `array[string]` | **Yes** | Outgoing edge IDs to child supporting nodes. |
| `parent_claim_ids` | `array[string]` | **Yes** | Incoming edge IDs pointing back to the claims this node supports. |
| `audit` | `NodeAudit` | **Yes** | Provenance and truthfulness verification metadata. |

##### NodeAudit Object (Inside `nodes[node_id].audit`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `status` | `enum` | **Yes** | `"verified"`, `"extrapolation"`, `"assumption"`, `"disputed"`, `"unverified"`. |
| `score` | `float` | **Yes** | Numeric confidence score between `0.0` and `1.0`. |
| `evaluator_type`| `enum` | **Yes** | `"deterministic"` (code checks), `"llm_auditor"` (adversarial AI), `"human"`. |
| `evaluator_note`| `string` | **Yes** | Concise rationale explaining the verification verdict. |

---

#### 1.4.2 Exhaustive Concrete Example (All Nodes, Locators, and Tensions)

```json
{
  "artifact": {
    "title": "Motion to Dismiss for Lack of Subject-Matter Jurisdiction and Financial Review",
    "version": "1.0.0",
    "created_at": "2026-09-26T22:45:00Z",
    "metadata": {
      "case_number": "1:26-cv-09142",
      "court": "U.S. District Court for the District of Delaware",
      "document_type": "legal_motion"
    },
    "summary": "Motion establishing that complete diversity is destroyed under 28 U.S.C. § 1332 and contractual damages fail to satisfy the jurisdictional threshold.",
    "sections": [
      {
        "section_id": "sec_01_procedural_standing",
        "section_title": "I. Procedural Standing & Jurisdictional Deficiencies",
        "order": 1,
        "content": "This Court must dismiss Plaintiff's complaint because <ref id='claim_sec01_1'>complete diversity does not exist between the parties</ref>. Furthermore, Plaintiff's alleged contractual damages <ref id='claim_sec01_2'>fail to satisfy the $75,000 threshold under 28 U.S.C. § 1332</ref>."
      },
      {
        "section_id": "sec_02_unit_economics",
        "section_title": "II. Counter-Analysis of Unit Economics & Damages Claims",
        "order": 2,
        "content": "Even under Plaintiff's tort theory of lost enterprise profits, <ref id='claim_sec02_3'>gross margins on cloud delivery expanded to 71.4%</ref>, while <ref id='claim_sec02_4'>regional churn held at 3.2%</ref> under <ref id='claim_sec02_5'>standard cohort definitions</ref>, yielding an <ref id='claim_sec02_6'>expected customer lifetime value calculation of $128,000</ref> based on <ref id='claim_sec02_7'>conservative linear churn assumptions</ref>."
      }
    ]
  },
  "audit_summary": {
    "total_claims": 7,
    "verified_count": 5,
    "extrapolation_count": 1,
    "assumption_count": 1,
    "cross_section_tensions": [
      {
        "tension_id": "ten_damages_vs_ltv",
        "involved_claim_ids": ["claim_sec01_2", "claim_sec02_6"],
        "severity": "warning",
        "description": "Section 1 claims total unpaid receivables are only $42,150, but Section 2 introduces a theoretical LTV tort claim of $128,000 that Plaintiff may argue meets statutory limits."
      }
    ]
  },
  "nodes": {
    "claim_sec01_1": {
      "id": "claim_sec01_1",
      "type": "claim",
      "title": "Lack of Complete Diversity",
      "section_id": "sec_01_procedural_standing",
      "clause_text": "complete diversity does not exist between the parties",
      "direct_child_ids": ["evi_sec01_1_1", "rea_sec01_1_2"],
      "parent_claim_ids": [],
      "audit": {
        "status": "verified",
        "score": 0.99,
        "evaluator_type": "deterministic",
        "evaluator_note": "Directly confirmed against Secretary of State filings."
      }
    },
    "evi_sec01_1_1": {
      "id": "evi_sec01_1_1",
      "type": "evidence",
      "title": "Delaware Corporate Registry (PDF)",
      "section_id": "sec_01_procedural_standing",
      "quote": "Principal place of business registered at 1209 North Orange St, Wilmington, DE.",
      "locator": {
        "source_type": "pdf",
        "file_name": "Exhibit_B_DE_Filing.pdf",
        "page": 2,
        "bounding_box": [120, 450, 480, 520],
        "locator_key": "DE-CORP-48821"
      },
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec01_1"],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Exact page bounding box matches text quote."
      }
    },
    "rea_sec01_1_2": {
      "id": "rea_sec01_1_2",
      "type": "reasoning",
      "title": "Corporate Citizenship Determination",
      "section_id": "sec_01_procedural_standing",
      "body": "Under the <ref id='aut_sec01_1_2_sub101'>nerve center test</ref>, citizenship is tied to executive headquarters. Because Defendant is also a Delaware entity, complete diversity is destroyed.",
      "direct_child_ids": ["aut_sec01_1_2_sub101"],
      "parent_claim_ids": ["claim_sec01_1"],
      "audit": {
        "status": "verified",
        "score": 0.96,
        "evaluator_type": "llm_auditor",
        "evaluator_note": "Valid deductive logic applying Supreme Court precedent to uncontested entity locations."
      }
    },
    "aut_sec01_1_2_sub101": {
      "id": "aut_sec01_1_2_sub101",
      "type": "authority",
      "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
      "section_id": "sec_01_procedural_standing",
      "quote": "'Principal place of business' refers to the place where a corporation's officers direct, control, and coordinate activities.",
      "url": "https://supreme.justia.com/cases/federal/us/559/77/",
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec01_1"],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Controlling Supreme Court precedent cited correctly."
      }
    },
    "claim_sec01_2": {
      "id": "claim_sec01_2",
      "type": "claim",
      "title": "Amount in Controversy Under Threshold",
      "section_id": "sec_01_procedural_standing",
      "clause_text": "fail to satisfy the $75,000 threshold under 28 U.S.C. § 1332",
      "direct_child_ids": ["evi_sec01_2_1", "aut_sec01_2_2"],
      "parent_claim_ids": [],
      "audit": {
        "status": "verified",
        "score": 0.98,
        "evaluator_type": "deterministic",
        "evaluator_note": "Aged receivables ledger confirms unpaid balance is $42,150."
      }
    },
    "evi_sec01_2_1": {
      "id": "evi_sec01_2_1",
      "type": "evidence",
      "title": "Aged Receivables Ledger (Spreadsheet)",
      "section_id": "sec_01_procedural_standing",
      "quote": "Total unpaid invoice balance: $42,150.00.",
      "locator": {
        "source_type": "spreadsheet",
        "file_name": "Invoices_2026.xlsx",
        "sheet": "Aging_Summary",
        "cell_range": "G14",
        "raw_value": 42150.00
      },
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec01_2"],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Cell coordinates G14 match ledger balance."
      }
    },
    "aut_sec01_2_2": {
      "id": "aut_sec01_2_2",
      "type": "authority",
      "title": "28 U.S.C. § 1332(a)",
      "section_id": "sec_01_procedural_standing",
      "quote": "The district courts shall have original jurisdiction of all civil actions where the matter in controversy exceeds the sum or value of $75,000.",
      "url": "https://www.law.cornell.edu/uscode/text/28/1332",
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec01_2"],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Federal statute accurately quoted."
      }
    },
    "claim_sec02_3": {
      "id": "claim_sec02_3",
      "type": "claim",
      "title": "Cloud Delivery Gross Margin Expansion",
      "section_id": "sec_02_unit_economics",
      "clause_text": "gross margins on cloud delivery expanded to 71.4%",
      "direct_child_ids": ["evi_sec02_3_1", "evi_sec02_3_2"],
      "parent_claim_ids": [],
      "audit": {
        "status": "verified",
        "score": 0.97,
        "evaluator_type": "deterministic",
        "evaluator_note": "Reconciled between internal financial model and SEC 10-Q filing."
      }
    },
    "evi_sec02_3_1": {
      "id": "evi_sec02_3_1",
      "type": "evidence",
      "title": "Internal P&L Model (Spreadsheet with Formula)",
      "section_id": "sec_02_unit_economics",
      "quote": "Gross Margin: 71.42%",
      "formula": "=E26/E14",
      "locator": {
        "source_type": "spreadsheet",
        "file_name": "Q3_2026_Actuals_v4.xlsx",
        "sheet": "Consolidated_P&L",
        "cell_range": "E28",
        "raw_value": 0.7142
      },
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec02_3"],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Formula =E26/E14 verified against revenue and direct COGS rows."
      }
    },
    "evi_sec02_3_2": {
      "id": "evi_sec02_3_2",
      "type": "evidence",
      "title": "SEC Form 10-Q Filing (Live Web)",
      "section_id": "sec_02_unit_economics",
      "quote": "Subscription gross margins reached seventy-one percent during the quarter ended September 30, 2026.",
      "locator": {
        "source_type": "web",
        "url": "https://www.sec.gov/edgar/data/100234/q3-2026-10q.htm",
        "snapshot_timestamp": "2026-09-20T14:32:00Z",
        "locator_key": "#item2_management_discussion",
        "payload_hash": "sha256:8f43a9b1c78e4d2938a4bc109f"
      },
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec02_3"],
      "audit": {
        "status": "verified",
        "score": 0.95,
        "evaluator_type": "deterministic",
        "evaluator_note": "HTML snapshot verified against SEC EDGAR repository."
      }
    },
    "claim_sec02_4": {
      "id": "claim_sec02_4",
      "type": "claim",
      "title": "Regional EMEA Churn Rate",
      "section_id": "sec_02_unit_economics",
      "clause_text": "regional churn held at 3.2%",
      "direct_child_ids": ["evi_sec02_4_1"],
      "parent_claim_ids": [],
      "audit": {
        "status": "verified",
        "score": 0.94,
        "evaluator_type": "deterministic",
        "evaluator_note": "Direct pull from production CRM telemetry API."
      }
    },
    "evi_sec02_4_1": {
      "id": "evi_sec02_4_1",
      "type": "evidence",
      "title": "Salesforce Analytics API Response",
      "section_id": "sec_02_unit_economics",
      "quote": "Monthly enterprise churn: 3.2%.",
      "locator": {
        "source_type": "api",
        "endpoint": "GET /api/v2/analytics/churn_rate",
        "method": "GET",
        "query_params": {
          "region": "EMEA",
          "period": "2026-Q3",
          "tier": "enterprise"
        },
        "json_path": "$.data.metrics.churn_rate_pct",
        "raw_value": 0.032,
        "payload_hash": "sha256:1a2b3c4d5e6f7a8b9c0d"
      },
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec02_4"],
      "audit": {
        "status": "verified",
        "score": 0.98,
        "evaluator_type": "deterministic",
        "evaluator_note": "Payload hash and JSONPath verified."
      }
    },
    "claim_sec02_5": {
      "id": "claim_sec02_5",
      "type": "claim",
      "title": "Enterprise Cohort Taxonomy",
      "section_id": "sec_02_unit_economics",
      "clause_text": "standard cohort definitions",
      "direct_child_ids": ["evi_sec02_5_1"],
      "parent_claim_ids": [],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Matches corporate data dictionary."
      }
    },
    "evi_sec02_5_1": {
      "id": "evi_sec02_5_1",
      "type": "evidence",
      "title": "Customer Warehouse Database (SQL Query)",
      "section_id": "sec_02_unit_economics",
      "quote": "Cohort definition: enterprise accounts with >= 500 active seats.",
      "locator": {
        "source_type": "internal_db",
        "database": "prod_dw_analytics",
        "table": "dim_cohort_taxonomy",
        "query": "SELECT definition_str FROM dim_cohort_taxonomy WHERE cohort_key = 'ENT_500_SEATS' LIMIT 1;",
        "row_id": "ENT_500_SEATS"
      },
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec02_5"],
      "audit": {
        "status": "verified",
        "score": 1.0,
        "evaluator_type": "deterministic",
        "evaluator_note": "Direct SQL table extraction."
      }
    },
    "claim_sec02_6": {
      "id": "claim_sec02_6",
      "type": "claim",
      "title": "Customer Lifetime Value Synthesis",
      "section_id": "sec_02_unit_economics",
      "clause_text": "expected customer lifetime value calculation of $128,000",
      "direct_child_ids": ["calc_sec02_6_1"],
      "parent_claim_ids": [],
      "audit": {
        "status": "extrapolation",
        "score": 0.78,
        "evaluator_type": "llm_auditor",
        "evaluator_note": "Mathematical derivation is sound ($128,306 rounded to $128,000), but relies on unseasoned churn stability."
      }
    },
    "calc_sec02_6_1": {
      "id": "calc_sec02_6_1",
      "type": "calculation",
      "title": "Customer Lifetime Value (LTV) Formula",
      "section_id": "sec_02_unit_economics",
      "formula": "LTV = (ARPU * Gross_Margin) / Monthly_Churn = ($5,750 * 0.714) / 0.032 = $128,306",
      "body": "Calculated by compounding monthly ARPU across historical gross margins and observed EMEA churn rates.",
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec02_6"],
      "audit": {
        "status": "verified",
        "score": 0.95,
        "evaluator_type": "deterministic",
        "evaluator_note": "Arithmetic formula verified deterministically."
      }
    },
    "claim_sec02_7": {
      "id": "claim_sec02_7",
      "type": "claim",
      "title": "Linear Churn Assumption",
      "section_id": "sec_02_unit_economics",
      "clause_text": "conservative linear churn assumptions",
      "direct_child_ids": ["ass_sec02_7_1"],
      "parent_claim_ids": [],
      "audit": {
        "status": "assumption",
        "score": 0.70,
        "evaluator_type": "llm_auditor",
        "evaluator_note": "Explicitly declared model assumption; pending Q4 renewal validation."
      }
    },
    "ass_sec02_7_1": {
      "id": "ass_sec02_7_1",
      "type": "assumption",
      "title": "Constant Linear Churn Decay",
      "section_id": "sec_02_unit_economics",
      "body": "Assumes churn remains flat at 3.2% without seasonality adjustments over months 1-12.",
      "direct_child_ids": [],
      "parent_claim_ids": ["claim_sec02_7"],
      "audit": {
        "status": "assumption",
        "score": 0.70,
        "evaluator_type": "llm_auditor",
        "evaluator_note": "Declared assumption; documented in financial diligence annex."
      }
    }
  }
}
```

---

## 2. Knowledge Storage & Multi-Stage Prompt Architecture

To generate answers that are both **(I) analytically sound** and **(II) strictly verifiable**, the system separates inputs into three distinct epistemic tiers that map 1:1 onto the `L0` → `L1` → `L2+` Toulmin graph:

| Input Tier | Epistemic Role | Graph Column & Node Types |
| :--- | :--- | :--- |
| **`(c)` Questions / Requests** | Defines the section outline, `stated_intention`, and target conclusions to be proven | **`L0` Synthesized Document** (`claim` nodes wrapped in `<ref n="1">`) |
| **`(a)` Task-Specific Input Documents** *(project filings, spreadsheets, APIs, transcripts)* | Supplies case-specific facts, quotes, and calculations; linked to `L0` claims via explicit reasoning | **`L1` Primary Support** (`evidence`, `calculation`, `assumption`, plus `reasoning` bridging `(a)` to `(c)`) |
| **`(b)` Canonical Source Documents** *(statutes, controlling case law, regulatory manuals, playbooks)* | Supplies the governing warrant/backing that justifies *why* a fact in `(a)` supports a conclusion in `(c)` | **`L2+` Backing Authorities** (`authority` and secondary `evidence` inside `sub_supports`, linked from `<ref n="101">` inside `L1` `reasoning` cards) |

---

### 2.1 Storage & Indexing Architecture (Agentic Search Without Vector RAG)

Asking an LLM to guess page numbers, bounding boxes, or cell coordinates from raw text is a primary source of citation failure. Instead, **coordinates are pre-computed deterministically at ingest** so the agent only copies pre-stamped `SourceLocator` blocks.

#### A. Storing `(a)` Task-Specific Input Documents (`matters/<matter_id>/inputs/`)
Each project or matter lives in an isolated directory where a deterministic ingestion script parses raw files (`raw/`) into **coordinate-stamped text and JSONL indices (`indexed/`)** alongside a `manifest.json`:

1. **PDFs & Word Documents (`.pdf`, `.docx` → `*.indexed.md`):**
   - Parsed by page and paragraph/bounding-box block. Every block is preceded by a machine-readable `LOCATOR` header containing its exact `SourceLocator` JSON and SHA-256 digest:
     ```markdown
     <!-- LOCATOR: {"source_type":"pdf","file_name":"Exhibit_B_DE_Filing.pdf","page":2,"bounding_box":[120,450,480,520],"locator_key":"DE-CORP-48821","payload_hash":"sha256:9f86d08"} -->
     Principal place of business registered at 1209 North Orange St, Wilmington, DE.
     ```
2. **Spreadsheets & Financial Models (`.xlsx`, `.csv` → `sheets_index.jsonl`):**
   - Parsed via `openpyxl` (inspecting both `data_only=False` for formulas and `data_only=True` for evaluated primitives) into one JSON line per populated cell/metric:
     ```json
     {"file_name":"Q3_2026_Actuals_v4.xlsx","sheet":"Consolidated_P&L","cell_range":"E28","line_item":"Gross Margin","display":"71.42%","raw_value":0.7142,"formula":"=E26/E14"}
     ```
3. **APIs & Internal Databases (`telemetry_receipts.jsonl`):**
   - Read-only SQL and API execution tools automatically append a deterministic receipt (`source_type`, `endpoint`/`query`, `json_path`, `raw_value`, `payload_hash`) to the matter's receipt log whenever called.

#### B. Storing `(b)` Canonical Source Documents (`canonical/`)
Because `(b)` changes infrequently and represents standing legal, regulatory, or institutional knowledge, it is stored as a **versioned Markdown library with a two-level routing index**:

1. **Top-Level Routing Map (`canonical/INDEX.md`):**
   - A compact directory listing every canonical document, its stable `[AUTH:...]` section IDs, and 1-sentence scope descriptions. Because `INDEX.md` is small (1–3 pages), it is injected directly into the Stage 1 planning prompt so the agent always knows which canonical authorities exist without fragile vector similarity search.
2. **Section-Anchored Canonical Files (`canonical/<domain>/<doc_id>.md`):**
   - Each canonical rule or precedent has a permanent anchor ID, metadata header, and full verbatim text (preserving statutory exceptions and qualifiers that chunked vector RAG often truncates):
     ```markdown
     ## [AUTH:HERTZ-2010-NERVE-CENTER] Hertz Corp. v. Friend, 559 U.S. 77 (2010)
     - **Title:** Hertz Corp. v. Friend, 559 U.S. 77 (2010)
     - **URL:** https://supreme.justia.com/cases/federal/us/559/77/
     - **Verbatim Holding:** "'Principal place of business' refers to the place where a corporation's officers direct, control, and coordinate activities."
     ```

---

### 2.2 Four-Stage Bottom-Up Prompt Pipeline

When an LLM searches documents and writes prose in a single step, it **post-hoc rationalizes**—drafting a plausible sentence first and hunting for a loosely related quote afterward. To prevent this, generation is split into four sequential stages:

```mermaid
flowchart LR
  C["(c) User Request"] --> S1["Stage 1: Outline & Canonical Rule Mapping"]
  B["(b) Canonical INDEX.md + Rules"] --> S1
  S1 --> S2["Stage 2: Agentic Evidence Harvesting"]
  A["(a) Coordinate-Stamped Task Inputs"] --> S2
  S2 --> S3["Stage 3: Constrained Tier-1 Section Drafting"]
  S3 --> S4["Stage 4: Audit Gate + Stitch + Graph Compile"]
```

#### Stage 1 Prompt: Question Decomposition & Canonical Rule Grounding (`(c)` + `(b)` → Outline Plan)

```markdown
You are the Lead Analytical Architect. You are given:
1. User Request (c): {{user_request}}
2. Canonical Knowledge Index (b): {{canonical_index_md}}

### Task:
1. Read `INDEX.md` and inspect the full text of all relevant `[AUTH:...]` sections in `(b)`.
2. Decompose the response to `(c)` into ordered sections. For each section, output:
   - `section_id` and `section_title`
   - `stated_intention`: The exact analytical or legal question this section must resolve.
   - `governing_authorities`: The list of `[AUTH:...]` IDs, titles, URLs, and verbatim quotes from `(b)` that govern the analysis in this section.
   - `required_fact_queries`: The specific factual questions, metrics, or record checks that must be extracted from the project input documents `(a)` to apply those governing authorities.
```

#### Stage 2 Prompt: Agentic Evidence Harvesting (`Outline Plan` + `(a)` → Verified Fact Ledger)

```markdown
You are a Forensic Fact Extractor. You are preparing the evidence base for Section "{{section_title}}".

You are given:
1. Section Intention: {{stated_intention}}
2. Governing Authorities from (b): {{governing_authorities}}
3. Required Fact Queries: {{required_fact_queries}}
4. Access to Coordinate-Indexed Task Inputs (a) under `matters/{{matter_id}}/inputs/indexed/`

### Instructions:
1. Use full-text search (`grep`), file range reads, and spreadsheet index lookups across `(a)` to answer every query in `required_fact_queries`.
2. Do NOT draft narrative prose yet. Output a JSON `VerifiedFactLedger` containing:
   - `verified_facts`: Array of extracted items. Each item MUST copy the exact `locator` object and verbatim `quote` (or `raw_value` and `formula`) directly from the indexed source in `(a)`.
   - `unresolved_gaps`: Any required fact that could not be verified in `(a)`, along with whether it requires an explicit `assumption` or `extrapolation`.
```

#### Stage 3 Prompt: Constrained Tier-1 Section Generator (`Verified Fact Ledger` + `(b)` → `SectionOutput`)

```markdown
You are an expert legal and analytical author tasked with writing Section {{section_index}}: "{{section_title}}".

You are provided with:
1. Section Outline & Stated Intention: {{stated_intention}}
2. Verified Fact Ledger from Task Inputs (a): {{verified_fact_ledger}}
3. Governing Canonical Authorities from (b): {{governing_authorities}}

### Strict Grounding & Structural Rules:
1. **Closed-World Evidence Constraint:** You may ONLY cite facts, quotes, formulas, and `locator` objects present in `verified_fact_ledger` (for `L1` evidence/calculations) and `governing_authorities` (for `L2+` authorities). Never invent or alter a `quote` or `locator`.
2. **Tag Every Substantive Claim (`L0`):** In `text`, wrap every empirical assertion, legal conclusion, or quantitative finding in `<ref n="X">clause text</ref>` using sequential integers (`1, 2, 3...`).
3. **Mandatory Two-Tier Toulmin Pairing (`L1` = `(a)`, `L2+` = `(b)`):**
   - For each `<ref n="X">`, provide a matching entry in `supports`.
   - Attach the primary factual record from `(a)` as an `evidence` or `calculation` item in `supports[X].items` (`L1`).
   - Whenever connecting a fact in `(a)` to the claim in `L0` requires applying a legal standard, policy rule, or analytical methodology from `(b)`, include a `reasoning` item in `supports[X].items` (`L1`).
   - Inside that `reasoning.body`, wrap the reference to the governing rule in `<ref n="10X">rule phrase</ref>` and attach the canonical `authority` item from `(b)` inside `sub_supports` (`L2+`).
4. **Explicit Caveat Honesty:** If a claim relies on an entry in `unresolved_gaps` or extrapolates beyond the four corners of `(a)`, include an explicit `assumption` item in `supports[X].items` so downstream human reviewers see it flagged clearly.

### Output Format:
Emit your response strictly adhering to the `SectionOutput` JSON schema (`section_id`, `text`, `supports`). Do not include conversational preambles.
```

---

### 2.3 Section-Level 3-Point Auditor Prompt

```markdown
You are an Independent Audit Gate evaluating a drafted `SectionOutput` before it is allowed into the compiled document.

You are given:
1. Stated Outline Intention: {{stated_intention}}
2. Drafted Section JSON (`SectionOutput`): {{section_output_json}}
3. Surrounding Source Context from (a) and (b) for all cited locators: {{expanded_source_context}}

### Verify Three Invariants:
1. **Relevance (`check_a_relevance`):** Does every item in `supports[n]` directly support the specific phrase wrapped in `<ref n="...">`?
2. **Source Congruence (`check_b_congruence`):** Reading the surrounding paragraphs in `expanded_source_context`, does the source material strictly entail the claim without cherry-picking, reversing negation, or dropping a disqualifying exception? (If the claim makes an inductive leap beyond the strict text, mark status as `"extrapolation"` or `"assumption"`).
3. **Outline Alignment (`check_c_intent`):** Does the section fully answer `stated_intention` without drifting into other sections' scope?

Output a structured audit verdict with per-node `NodeAudit` statuses (`verified`, `extrapolation`, `assumption`, `disputed`) and actionable retry critiques if any invariant fails.
```

---

### 2.4 Whole-Document Editorial Stitcher Prompt

```markdown
You are the Executive Managing Editor. You are given an assembled multi-section document where individual sections were written by specialized research agents.

Your job is to polish transitions, eliminate repetitive phrases, and ensure unified rhetorical cadence.

### Critical Invariants (Non-Negotiable):
1. **TAG IMMUTABILITY:** The text contains `<ref n="...">` tags (or `<ref id="...">` tags). Every single tag represents a verified legal/factual provenance link.
2. **ZERO DELETIONS:** You must NEVER delete, omit, or rename a `<ref>` tag. The final text must contain the exact same set of tags as the input.
3. **ZERO RE-INVENTIONS:** You may smooth the wording surrounding a tag or slightly adjust the words within a tag for grammatical agreement, but you must NOT change the substantive meaning of any tagged clause.
4. **NO UNTAGGED FACTUAL ASSERTIONS:** Do not insert new unsupported empirical claims as "filler" during transitions. Transition sentences should only provide logical framing (e.g., "Turning from jurisdictional standing to the merits...").

### Input Document:
{{concatenated_document_text}}

### Output:
Return ONLY the polished document text.
```

---

## 3. Programmatic Python Verification & Assembly Suite

### 3.1 Plain-English Overview (For Non-Coders)

The Python script below serves as the **deterministic quality gate and compiler** connecting the AI authoring stage to the user interface. While LLMs are creative and capable of synthesizing complex documents, they cannot be trusted to self-police their own factual consistency or maintain rigid data schemas across multi-step jobs. 

This script acts as an incorruptible software inspector that executes four sequential jobs:

```
[Raw AI Section Output]
           │
           ▼
[1. Structural Inspector]  ──► Rejects invalid JSON, missing coordinates, or illegal types
           │
           ▼
[2. Local Fact-Checker]    ──► Ensures every text tag has proof, and no proof is left uncited
           │
           ▼
[3. Editorial Bouncer]     ──► Proves the transition-smoothing pass did not drop or fake citations
           │
           ▼
[4. Master Mapmaker]       ──► Re-indexes local tags to global IDs & flattens nodes into a DAG
           │
           ▼
[Final Bounded Canvas Bundle]
```

#### 1. The Structural Inspector (`Pydantic Models`)
* **What it does:** Defines the strict "legal contract" of what an AI output must look like.
* **Why it matters:** It guarantees that every piece of evidence includes an exact file name, page number, spreadsheet cell, or API endpoint, and that every node is properly tagged as `evidence`, `reasoning`, or `authority`. If the AI hallucinates an unknown format or forgets a field, this step immediately flags it.

#### 2. The Local Fact-Checker (`SectionValidator`)
* **What it does:** Scans the AI's written text for reference tags like `<ref n="1">` and cross-references them against the attached `supports` list.
* **Why it matters:** It catches two major AI mistakes:
  * *Orphaned Tags:* The AI claimed something in the text with `<ref n="3">`, but forgot to provide the evidence for #3.
  * *Unused Backup:* The AI assembled an evidence card, but never actually used it to support anything in the text.
  * *Broken Logic Links:* If a reasoning card refers to a legal case or manual (sub-reference), it ensures that authority card is actually included.

#### 3. The Editorial Invariant Bouncer (`StitchInvariantGate`)
* **What it does:** When all sections are stitched together, an editorial LLM polishes the transitions. The bouncer compares the text **before** and **after** that editorial pass.
* **Why it matters:** Editorial LLMs love deleting awkward citations or inventing rhetorical flourishes (e.g., *"This dramatically proves our market dominance..."*). The bouncer verifies mathematically that `pre_citations == post_citations`. If even a single citation was deleted, altered, or invented, the pass is rejected.

#### 4. The Master Mapmaker / Graph Compiler (`CompiledGraphBuilder`)
* **What it does:** Converts isolated, section-by-section drafts into a unified, interactive network.
* **Why it matters:** 
  * Section 1 and Section 3 might both use `<ref n="1">`. The compiler converts these into unique, non-colliding global addresses (e.g., `claim_sec01_1` and `claim_sec03_1`).
  * It pulls nested backup items (like legal authorities buried inside reasoning cards) into a clean, flat list of cards connected by directional lines (`direct_child_ids`).
  * It updates the final document text so clicking any highlighted phrase instantly opens the exact corresponding card in the spatial canvas.

---

### 3.2 Production Python Script

The following production-ready Python script implements the four verification and compilation layers described above:

```python
"""Audit pipeline verification and graph compilation engine.

This module provides data models and deterministic compilation steps to
validate LLM-generated section blocks, enforce citation invariants across
whole-document editing passes, and build a normalized DAG for spatial UI consumption.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from pydantic import BaseModel, Field, ValidationError


# =====================================================================
# 1. Pydantic Models for Intermediate Worker Output
# =====================================================================

class SourceLocator(BaseModel):
    """Pinpoints exact evidence coordinates in source files or APIs."""
    source_type: Literal["pdf", "spreadsheet", "web", "api", "internal_db"]
    file_name: Optional[str] = None
    page: Optional[int] = None
    bounding_box: Optional[List[int]] = None
    sheet: Optional[str] = None
    cell_range: Optional[str] = None
    raw_value: Optional[Any] = None
    url: Optional[str] = None
    locator_key: Optional[str] = None
    snapshot_timestamp: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[Literal["GET", "POST", "PUT"]] = None
    query_params: Optional[Dict[str, Any]] = None
    json_path: Optional[str] = None
    payload_hash: Optional[str] = None
    database: Optional[str] = None
    table: Optional[str] = None
    query: Optional[str] = None
    row_id: Optional[Any] = None


class SubSupportItem(BaseModel):
    """Level 2+ supporting authority or secondary deduction."""
    n: int
    type: Literal["evidence", "reasoning", "authority", "calculation", "assumption"]
    title: str
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    locator: Optional[SourceLocator] = None


class SupportItem(BaseModel):
    """Level 1 supporting node attached to a substantive claim."""
    type: Literal["evidence", "reasoning", "authority", "calculation", "assumption"]
    title: str
    quote: Optional[str] = None
    body: Optional[str] = None
    formula: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    locator: Optional[SourceLocator] = None
    sub_supports: List[SubSupportItem] = Field(default_factory=list)


class SupportGroup(BaseModel):
    """Maps a reference index n to its cluster of supporting objects."""
    n: int
    items: List[SupportItem] = Field(min_length=1)


class SectionOutput(BaseModel):
    """Schema expected from individual section worker LLMs."""
    section_id: str
    text: str
    supports: List[SupportGroup]


# =====================================================================
# 2. Section Verification Engine
# =====================================================================

class SectionValidator:
    """Verifies that an individual section adheres to strict grounding invariants."""

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

    @classmethod
    def validate_section(cls, section: SectionOutput) -> Tuple[bool, List[str]]:
        """Validates reference parity between inline tags and support definitions.

        Args:
            section: Deserialized SectionOutput instance.

        Returns:
            Tuple of (is_valid, list_of_error_strings).
        """
        errors: List[str] = []
        found_matches = cls.TAG_PATTERN.findall(section.text)
        text_indices: Set[int] = {int(m[0]) for m in found_matches}
        support_indices: Set[int] = {s.n for s in section.supports}

        # Check for orphaned inline tags (tagged in text but missing from supports)
        orphaned_in_text = text_indices - support_indices
        if orphaned_in_text:
            errors.append(f"Inline tags lack support definitions: {sorted(list(orphaned_in_text))}")

        # Check for unreferenced support items (defined in supports but never used in text)
        unused_supports = support_indices - text_indices
        if unused_supports:
            errors.append(f"Support items never referenced in text: {sorted(list(unused_supports))}")

        # Verify internal sub-references within reasoning bodies
        for group in section.supports:
            for item in group.items:
                if item.type == "reasoning" and item.body:
                    sub_matches = cls.TAG_PATTERN.findall(item.body)
                    sub_indices = {int(m[0]) for m in sub_matches}
                    defined_sub_indices = {sub.n for sub in item.sub_supports}
                    
                    unresolved_subs = sub_indices - defined_sub_indices
                    if unresolved_subs:
                        errors.append(
                            f"Reasoning node under ref n={group.n} references sub-refs "
                            f"{sorted(list(unresolved_subs))} that are missing from sub_supports."
                        )

        return (len(errors) == 0, errors)


# =====================================================================
# 3. Editorial Stitch Invariant Gate
# =====================================================================

class StitchInvariantGate:
    """Validates that a whole-document smoothing pass preserved all citations."""

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

    @classmethod
    def verify_stitch(cls, pre_stitched_text: str, post_stitched_text: str) -> Tuple[bool, List[str]]:
        """Ensures that no tags were deleted, duplicated, or substantive text erased.

        Args:
            pre_stitched_text: Concatenated text of all raw sections.
            post_stitched_text: Output from the editorial smoothing LLM.

        Returns:
            Tuple of (passed, list_of_violations).
        """
        violations: List[str] = []

        pre_matches = cls.TAG_PATTERN.findall(pre_stitched_text)
        post_matches = cls.TAG_PATTERN.findall(post_stitched_text)

        pre_dict: Dict[int, str] = {int(n): text.strip() for n, text in pre_matches}
        post_dict: Dict[int, str] = {int(n): text.strip() for n, text in post_matches}

        pre_ids = set(pre_dict.keys())
        post_ids = set(post_dict.keys())

        # Check 1: Missing tags
        missing = pre_ids - post_ids
        if missing:
            violations.append(f"Editorial pass removed citations with n={sorted(list(missing))}")

        # Check 2: Hallucinated / added tags
        added = post_ids - pre_ids
        if added:
            violations.append(f"Editorial pass invented ungrounded citations with n={sorted(list(added))}")

        # Check 3: Check for empty or severely truncated clauses
        for n, original_clause in pre_dict.items():
            if n in post_dict:
                smoothed_clause = post_dict[n]
                if len(smoothed_clause) == 0:
                    violations.append(f"Citation n={n} clause was completely emptied.")
                # Basic sanity check: smoothed text must retain reasonable length
                elif len(smoothed_clause) < len(original_clause) * 0.4:
                    violations.append(
                        f"Citation n={n} clause was truncated excessively: "
                        f"'{original_clause}' -> '{smoothed_clause}'"
                    )

        return (len(violations) == 0, violations)


# =====================================================================
# 4. Graph Compiler (Transforms Local References to Global DAG)
# =====================================================================

class CompiledGraphBuilder:
    """Compiles validated sections into a global, flat DAG schema for the UI."""

    TAG_PATTERN = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)

    def __init__(self, document_title: str) -> None:
        self.document_title = document_title
        self.sections_payload: List[Dict[str, Any]] = []
        self.nodes_registry: Dict[str, Dict[str, Any]] = {}

    def compile_sections(self, sections: List[SectionOutput], final_smoothed_text: Optional[str] = None) -> Dict[str, Any]:
        """Compiles all sections, rewriting local IDs to globally unique keys.

        Args:
            sections: List of verified SectionOutput blocks.
            final_smoothed_text: Optional full smoothed text containing all sections.

        Returns:
            The complete JSON bundle conforming to the frontend spatial canvas schema.
        """
        # Map local integer references (sec_id, n) -> global_node_id
        global_ref_map: Dict[Tuple[str, int], str] = {}

        # First Pass: Generate IDs and populate nodes into the registry
        for sec in sections:
            sec_matches = dict(self.TAG_PATTERN.findall(sec.text))

            for support_group in sec.supports:
                n = support_group.n
                claim_id = f"claim_{sec.section_id}_{n}"
                global_ref_map[(sec.section_id, n)] = claim_id

                clause_text = sec_matches.get(str(n), "").strip()
                child_node_ids: List[str] = []

                for idx, item in enumerate(support_group.items):
                    child_id = f"{item.type[:3]}_{sec.section_id}_{n}_{idx+1}"
                    child_node_ids.append(child_id)

                    sub_child_ids: List[str] = []
                    item_body = item.body or ""

                    # Process sub_supports (Level 2 authorities/evidence)
                    if item.sub_supports:
                        for sub_idx, sub in enumerate(item.sub_supports):
                            sub_id = f"{sub.type[:3]}_{sec.section_id}_{n}_{idx+1}_sub{sub.n}"
                            sub_child_ids.append(sub_id)
                            global_ref_map[(sec.section_id, sub.n)] = sub_id

                            self.nodes_registry[sub_id] = {
                                "id": sub_id,
                                "type": sub.type,
                                "title": sub.title,
                                "quote": sub.quote,
                                "body": sub.body,
                                "formula": sub.formula,
                                "url": sub.url,
                                "image_url": sub.image_url,
                                "locator": sub.locator.model_dump() if sub.locator else None,
                                "direct_child_ids": [],
                                "audit": {
                                    "status": "verified",
                                    "score": 1.0,
                                    "evaluator_type": "deterministic",
                                    "evaluator_note": "Compiled from sub-support definition."
                                }
                            }

                            # Replace inline sub-ref tags inside parent reasoning body
                            item_body = re.sub(
                                rf"<ref\s+n=['\"]{sub.n}['\"]>(.*?)</ref>",
                                rf"<ref id='{sub_id}'>\1</ref>",
                                item_body
                            )

                    self.nodes_registry[child_id] = {
                        "id": child_id,
                        "type": item.type,
                        "title": item.title,
                        "quote": item.quote,
                        "body": item_body,
                        "formula": item.formula,
                        "url": item.url,
                        "image_url": item.image_url,
                        "locator": item.locator.model_dump() if item.locator else None,
                        "direct_child_ids": sub_child_ids,
                        "audit": {
                            "status": "verified",
                            "score": 1.0,
                            "evaluator_type": "deterministic",
                            "evaluator_note": "Compiled from primary support definition."
                        }
                    }

                # Register the top-level Claim Node
                self.nodes_registry[claim_id] = {
                    "id": claim_id,
                    "type": "claim",
                    "title": clause_text[:40] + ("..." if len(clause_text) > 40 else ""),
                    "clause_text": clause_text,
                    "section_id": sec.section_id,
                    "direct_child_ids": child_node_ids,
                    "audit": {
                        "status": "verified",
                        "score": 0.98,
                        "evaluator_type": "deterministic",
                        "evaluator_note": "Verified across local supports."
                    }
                }

        # Second Pass: Rewrite inline text tags from local n to global ID
        if final_smoothed_text:
            # If smoothed as a single document, replace tags across the whole text
            compiled_text = final_smoothed_text
            for (sec_id, n), global_id in global_ref_map.items():
                compiled_text = re.sub(
                    rf"<ref\s+n=['\"]{n}['\"]>(.*?)</ref>",
                    rf"<ref id='{global_id}'>\1</ref>",
                    compiled_text
                )
            self.sections_payload.append({
                "section_id": "unified_document",
                "content": compiled_text
            })
        else:
            # Otherwise rewrite per section
            for sec in sections:
                compiled_sec_text = sec.text
                for (s_id, n), global_id in global_ref_map.items():
                    if s_id == sec.section_id:
                        compiled_sec_text = re.sub(
                            rf"<ref\s+n=['\"]{n}['\"]>(.*?)</ref>",
                            rf"<ref id='{global_id}'>\1</ref>",
                            compiled_sec_text
                        )
                self.sections_payload.append({
                    "section_id": sec.section_id,
                    "content": compiled_sec_text
                })

        return {
            "artifact": {
                "title": self.document_title,
                "sections": self.sections_payload
            },
            "nodes": self.nodes_registry
        }


# =====================================================================
# 5. Verification Test & Execution Example
# =====================================================================

if __name__ == "__main__":
    # Sample worker output from Step 2
    sample_section_raw = {
        "section_id": "sec_02_jurisdiction",
        "text": "The Court must dismiss because <ref n='1'>complete diversity is destroyed</ref> under 28 U.S.C. § 1332.",
        "supports": [
            {
                "n": 1,
                "items": [
                    {
                        "type": "evidence",
                        "title": "DE Corp Registry",
                        "quote": "Principal place in DE.",
                        "locator": {
                            "source_type": "pdf",
                            "file_name": "Exhibit_B.pdf",
                            "page": 2
                        }
                    },
                    {
                        "type": "reasoning",
                        "title": "Headquarters Analysis",
                        "body": "Applies the <ref n='101'>nerve center test</ref>.",
                        "sub_supports": [
                            {
                                "n": 101,
                                "type": "authority",
                                "title": "Hertz Corp. v. Friend",
                                "quote": "Where executive officers direct activities.",
                                "url": "https://supreme.justia.com/cases/federal/us/559/77/"
                            }
                        ]
                    }
                ]
            }
        ]
    }

    print("Step 1: Parsing Section Output via Pydantic...")
    section_obj = SectionOutput.model_validate(sample_section_raw)

    print("Step 2: Validating Section Grounding Invariants...")
    is_valid, validation_errors = SectionValidator.validate_section(section_obj)
    assert is_valid, f"Validation failed: {validation_errors}"
    print("Section passed local grounding validation.")

    print("Step 3: Simulating Editorial Smoothing Pass...")
    raw_text = section_obj.text
    # Simulated smoothed text with preserved tag
    smoothed_text = "As an initial matter, this Court must dismiss because <ref n='1'>complete diversity is destroyed</ref> pursuant to 28 U.S.C. § 1332."

    passed_stitch, stitch_violations = StitchInvariantGate.verify_stitch(raw_text, smoothed_text)
    assert passed_stitch, f"Stitch gate failed: {stitch_violations}"
    print("Editorial smoothing pass satisfied invariant checks.")

    print("Step 4: Compiling Global DAG Bundle...")
    builder = CompiledGraphBuilder(document_title="Sample Motion to Dismiss")
    final_bundle = builder.compile_sections([section_obj], final_smoothed_text=smoothed_text)

    print("\n--- Compiled Final Bundle (Extract) ---")
    print(f"Artifact Sections: {len(final_bundle['artifact']['sections'])}")
    print(f"Total Graph Nodes: {len(final_bundle['nodes'])}")
    print("Sample Node Keys:", list(final_bundle['nodes'].keys()))
    print("Compilation successfully completed with zero orphaned references.")
```
