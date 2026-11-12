"""Pre-loaded sample audit bundles demonstrating multi-level DAG introspection.

Each bundle conforms strictly to the Tier 2 `CompiledBundle` specification and
showcases multi-level drill-downs (Document Clause -> Level 1 Reasoning/Evidence
-> Level 2 Authority/Calculation -> Level 3 Primary Source), all five source
locator types (`pdf`, `spreadsheet`, `web`, `api`, `internal_db`), and
cross-section tension warnings.
"""

from __future__ import annotations

from typing import Dict
from app.models import CompiledBundle


RAW_BUNDLES: Dict[str, dict] = {
    "legal_motion_1332": {
        "bundle_id": "legal_motion_1332",
        "artifact": {
            "title": "Motion to Dismiss for Lack of Subject-Matter Jurisdiction & Financial Review",
            "version": "1.2.0",
            "created_at": "2026-10-24T08:30:00Z",
            "metadata": {
                "case_number": "1:26-cv-09142-LPS",
                "court": "U.S. District Court for the District of Delaware",
                "document_type": "Legal Motion & Forensic Accounting Annex",
                "author": "Litigation & Forensic Diligence Pipeline v2.4"
            },
            "summary": "Rule 12(b)(1) motion establishing that complete diversity is destroyed under 28 U.S.C. § 1332 because both parties maintain principal executive operations in Delaware, and demonstrating that contractual unpaid balances ($42,150) fall below the $75,000 statutory threshold.",
            "sections": [
                {
                    "section_id": "sec_01_procedural_standing",
                    "section_title": "I. Procedural Standing & Jurisdictional Deficiencies",
                    "order": 1,
                    "content": (
                        "This Court must dismiss Plaintiff's complaint under Rule 12(b)(1) because "
                        "<ref id='claim_sec01_1'>complete diversity does not exist between the parties</ref> "
                        "at the time of filing. Furthermore, Plaintiff's alleged contractual damages "
                        "<ref id='claim_sec01_2'>fail to satisfy the $75,000 threshold under 28 U.S.C. § 1332</ref>, "
                        "as undisputed billing records establish a net balance of $42,150.00."
                    )
                },
                {
                    "section_id": "sec_02_unit_economics",
                    "section_title": "II. Counter-Analysis of Unit Economics & Tort Valuation",
                    "order": 2,
                    "content": (
                        "Even under Plaintiff's alternative tort theory of lost enterprise platform value, "
                        "<ref id='claim_sec02_3'>gross margins on cloud delivery expanded to 71.4%</ref> during Q3, "
                        "demonstrating no operational impairment. While <ref id='claim_sec02_4'>regional EMEA churn held at 3.2%</ref> "
                        "under <ref id='claim_sec02_5'>standard cohort definitions</ref>, Plaintiff's "
                        "<ref id='claim_sec02_6'>expected customer lifetime value calculation of $128,000</ref> "
                        "relies entirely on <ref id='claim_sec02_7'>unseasoned linear churn assumptions</ref> "
                        "that cannot be included in statutory controversy calculations."
                    )
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
                    "description": "Section I asserts that the amount in controversy is capped at $42,150 in unpaid invoices, whereas Section II models a $128,000 theoretical LTV figure that Plaintiff's counsel could cite as consequential tort damages unless explicitly excluded under contractual limitation-of-liability clauses."
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
                    "evaluator_note": "Directly confirmed against Delaware Division of Corporations filings and board minutes."
                }
            },
            "evi_sec01_1_1": {
                "id": "evi_sec01_1_1",
                "type": "evidence",
                "title": "Delaware Corporate Registry Filing",
                "section_id": "sec_01_procedural_standing",
                "quote": "Principal place of business and executive headquarters registered at 1209 North Orange St, Suite 400, Wilmington, DE 19801.",
                "locator": {
                    "source_type": "pdf",
                    "file_name": "Exhibit_B_DE_Filing.pdf",
                    "page": 2,
                    "bounding_box": [118, 442, 488, 526],
                    "locator_key": "DE-CORP-48821",
                    "payload_hash": "sha256:94c8e2a10f8b41c77d"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec01_1"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Exact page 2 bounding box matches certified franchise tax report."
                }
            },
            "rea_sec01_1_2": {
                "id": "rea_sec01_1_2",
                "type": "reasoning",
                "title": "Corporate Citizenship Determination",
                "section_id": "sec_01_procedural_standing",
                "body": (
                    "Under the <ref id='aut_sec01_1_2_sub101'>nerve center test</ref>, a corporation's principal "
                    "place of business is the single location where officers direct and coordinate corporate activities. "
                    "Because <ref id='evi_sec01_1_2_sub102'>executive board resolutions were executed in Wilmington</ref> "
                    "and Defendant is a Delaware LLC, <ref id='aut_sec01_1_2_sub103'>complete diversity is destroyed</ref>."
                ),
                "direct_child_ids": [
                    "aut_sec01_1_2_sub101",
                    "evi_sec01_1_2_sub102",
                    "aut_sec01_1_2_sub103"
                ],
                "parent_claim_ids": ["claim_sec01_1"],
                "audit": {
                    "status": "verified",
                    "score": 0.97,
                    "evaluator_type": "llm_auditor",
                    "evaluator_note": "Deductive chain properly links corporate headquarters evidence to controlling Supreme Court precedent."
                }
            },
            "aut_sec01_1_2_sub101": {
                "id": "aut_sec01_1_2_sub101",
                "type": "authority",
                "title": "Hertz Corp. v. Friend, 559 U.S. 77 (2010)",
                "section_id": "sec_01_procedural_standing",
                "quote": "'Principal place of business' is best read as referring to the place where a corporation's officers direct, control, and coordinate the corporation's activities — the 'nerve center.'",
                "body": "Establishes that administrative headquarters govern over regional sales offices; see <ref id='evi_sec01_1_2_sub1001'>Third Circuit appellate application</ref>.",
                "url": "https://supreme.justia.com/cases/federal/us/559/77/",
                "direct_child_ids": ["evi_sec01_1_2_sub1001"],
                "parent_claim_ids": ["claim_sec01_1"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Controlling U.S. Supreme Court authority verified."
                }
            },
            "evi_sec01_1_2_sub1001": {
                "id": "evi_sec01_1_2_sub1001",
                "type": "authority",
                "title": "Johnson v. SmithKline Beecham Corp., 724 F.3d 337 (3d Cir. 2013)",
                "section_id": "sec_01_procedural_standing",
                "quote": "When a holding or operating entity conducts its board governance and treasury approvals in Wilmington, Delaware is its nerve center regardless of remote engineering headcount.",
                "url": "https://case-law.vlex.com/vid/johnson-v-smithkline-beecham-88921402",
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec01_1"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Binding Third Circuit precedent directly on point for District of Delaware."
                }
            },
            "evi_sec01_1_2_sub102": {
                "id": "evi_sec01_1_2_sub102",
                "type": "evidence",
                "title": "Q1–Q3 Board Governance Minutes",
                "section_id": "sec_01_procedural_standing",
                "quote": "All seven quarterly budget approvals, officer appointments, and credit facility covenants were executed at the Wilmington headquarters.",
                "locator": {
                    "source_type": "pdf",
                    "file_name": "Exhibit_D_Board_Minutes_2026.pdf",
                    "page": 14,
                    "bounding_box": [92, 210, 512, 340],
                    "locator_key": "MINUTES-2026-Q3-SEC4"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec01_1"],
                "audit": {
                    "status": "verified",
                    "score": 0.98,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Corroborates nerve-center activity in Wilmington."
                }
            },
            "aut_sec01_1_2_sub103": {
                "id": "aut_sec01_1_2_sub103",
                "type": "authority",
                "title": "Strawbridge v. Curtiss, 7 U.S. (3 Cranch) 267 (1806)",
                "section_id": "sec_01_procedural_standing",
                "quote": "Complete diversity requires that no plaintiff be a citizen of the same state as any defendant.",
                "url": "https://supreme.justia.com/cases/federal/us/7/267/",
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec01_1"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Foundational complete diversity rule."
                }
            },
            "claim_sec01_2": {
                "id": "claim_sec01_2",
                "type": "claim",
                "title": "Amount in Controversy Below $75,000",
                "section_id": "sec_01_procedural_standing",
                "clause_text": "fail to satisfy the $75,000 threshold under 28 U.S.C. § 1332",
                "direct_child_ids": ["evi_sec01_2_1", "aut_sec01_2_2", "rea_sec01_2_3"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "verified",
                    "score": 0.98,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Aged receivables ledger confirms net unpaid balance is $42,150.00."
                }
            },
            "evi_sec01_2_1": {
                "id": "evi_sec01_2_1",
                "type": "evidence",
                "title": "Aged Receivables Ledger (Spreadsheet)",
                "section_id": "sec_01_procedural_standing",
                "quote": "Total unpaid invoice balance across Invoices #INV-882 through #INV-889: $42,150.00.",
                "formula": "=SUM(G6:G13)-H14",
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
                    "evaluator_note": "Cell G14 formula and raw float value verified."
                }
            },
            "aut_sec01_2_2": {
                "id": "aut_sec01_2_2",
                "type": "authority",
                "title": "28 U.S.C. § 1332(a) — Jurisdictional Amount",
                "section_id": "sec_01_procedural_standing",
                "quote": "The district courts shall have original jurisdiction of all civil actions where the matter in controversy exceeds the sum or value of $75,000, exclusive of interest and costs.",
                "url": "https://www.law.cornell.edu/uscode/text/28/1332",
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec01_2"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Statutory text verified."
                }
            },
            "rea_sec01_2_3": {
                "id": "rea_sec01_2_3",
                "type": "reasoning",
                "title": "Exclusion of Speculative Consequential Damages",
                "section_id": "sec_01_procedural_standing",
                "body": "Under Section 11.4 of the <ref id='evi_sec01_2_3_sub201'>Master Services Agreement</ref>, consequential and lost-profit damages are expressly waived, capping legal recovery at unpaid direct fees ($42,150).",
                "direct_child_ids": ["evi_sec01_2_3_sub201"],
                "parent_claim_ids": ["claim_sec01_2"],
                "audit": {
                    "status": "verified",
                    "score": 0.95,
                    "evaluator_type": "llm_auditor",
                    "evaluator_note": "Contractual limitation clause legally forecloses consequential damages above invoice balance."
                }
            },
            "evi_sec01_2_3_sub201": {
                "id": "evi_sec01_2_3_sub201",
                "type": "evidence",
                "title": "Master Services Agreement § 11.4 (Limitation of Liability)",
                "section_id": "sec_01_procedural_standing",
                "quote": "NEITHER PARTY SHALL BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES, OR DAMAGES FOR LOST PROFITS OR REVENUE.",
                "locator": {
                    "source_type": "pdf",
                    "file_name": "Exhibit_A_MSA_2025.pdf",
                    "page": 9,
                    "bounding_box": [88, 510, 520, 595],
                    "locator_key": "MSA-SEC-11-4"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec01_2"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Verbatim limitation clause verified on page 9 of Exhibit A."
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
                    "evaluator_note": "Cross-reconciled between audited P&L workbook and public SEC 10-Q filing."
                }
            },
            "evi_sec02_3_1": {
                "id": "evi_sec02_3_1",
                "type": "evidence",
                "title": "Internal P&L Model (Consolidated_P&L!E28)",
                "section_id": "sec_02_unit_economics",
                "quote": "Q3 Cloud Subscription Gross Margin: 71.42% (up 240 bps YoY).",
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
                    "evaluator_note": "Formula =E26/E14 verified against Gross Profit ($10.14M) / Revenue ($14.20M)."
                }
            },
            "evi_sec02_3_2": {
                "id": "evi_sec02_3_2",
                "type": "evidence",
                "title": "SEC Form 10-Q Filing (EDGAR Web Snapshot)",
                "section_id": "sec_02_unit_economics",
                "quote": "Subscription gross margins reached seventy-one percent during the third fiscal quarter ended September 30, 2026.",
                "url": "https://www.sec.gov/edgar/searchedgar/companysearch",
                "locator": {
                    "source_type": "web",
                    "url": "https://www.sec.gov/edgar/data/100234/q3-2026-10q.htm",
                    "snapshot_timestamp": "2026-10-02T14:32:00Z",
                    "locator_key": "#item2_management_discussion",
                    "payload_hash": "sha256:8f43a9b1c78e4d2938a4bc109f"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec02_3"],
                "audit": {
                    "status": "verified",
                    "score": 0.96,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Archived DOM selector #item2_management_discussion matches quote."
                }
            },
            "claim_sec02_4": {
                "id": "claim_sec02_4",
                "type": "claim",
                "title": "Regional EMEA Churn Rate",
                "section_id": "sec_02_unit_economics",
                "clause_text": "regional EMEA churn held at 3.2%",
                "direct_child_ids": ["evi_sec02_4_1"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "verified",
                    "score": 0.94,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Direct telemetry pull from production CRM analytics endpoint."
                }
            },
            "evi_sec02_4_1": {
                "id": "evi_sec02_4_1",
                "type": "evidence",
                "title": "Salesforce Analytics API Telemetry",
                "section_id": "sec_02_unit_economics",
                "quote": "EMEA Enterprise Monthly Churn Rate: 3.20% (n=142 active enterprise accounts).",
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
                    "evaluator_note": "API response digest and JSONPath value verified."
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
                    "evaluator_note": "Matches governed enterprise data warehouse taxonomy."
                }
            },
            "evi_sec02_5_1": {
                "id": "evi_sec02_5_1",
                "type": "evidence",
                "title": "Customer Data Warehouse (SQL Taxonomy Query)",
                "section_id": "sec_02_unit_economics",
                "quote": "Cohort ENT_500_SEATS: Organizations with >= 500 provisioned seats or >= $50,000 ARR.",
                "locator": {
                    "source_type": "internal_db",
                    "database": "prod_dw_analytics",
                    "table": "dim_cohort_taxonomy",
                    "query": "SELECT cohort_key, definition_str, min_arr_usd FROM dim_cohort_taxonomy WHERE cohort_key = 'ENT_500_SEATS' LIMIT 1;",
                    "row_id": "ENT_500_SEATS"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec02_5"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Read-only SQL query verified against production schema."
                }
            },
            "claim_sec02_6": {
                "id": "claim_sec02_6",
                "type": "claim",
                "title": "Customer Lifetime Value Synthesis ($128,000)",
                "section_id": "sec_02_unit_economics",
                "clause_text": "expected customer lifetime value calculation of $128,000",
                "direct_child_ids": ["calc_sec02_6_1"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "extrapolation",
                    "score": 0.78,
                    "evaluator_type": "llm_auditor",
                    "evaluator_note": "Arithmetic formula is accurate ($128,306), but extrapolates steady-state LTV from a single quarter of EMEA churn."
                }
            },
            "calc_sec02_6_1": {
                "id": "calc_sec02_6_1",
                "type": "calculation",
                "title": "Customer Lifetime Value (LTV) Derivation",
                "section_id": "sec_02_unit_economics",
                "formula": "LTV = (ARPU * Gross_Margin) / Monthly_Churn = ($5,750 * 0.714) / 0.032 = $128,306",
                "body": "Derived by dividing monthly gross margin contribution by the <ref id='evi_sec02_4_1'>observed 3.2% EMEA churn rate</ref> and assuming <ref id='ass_sec02_7_1'>zero seasonal decay</ref>.",
                "direct_child_ids": ["evi_sec02_4_1", "ass_sec02_7_1"],
                "parent_claim_ids": ["claim_sec02_6"],
                "audit": {
                    "status": "verified",
                    "score": 0.95,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Formula arithmetic verified deterministically."
                }
            },
            "claim_sec02_7": {
                "id": "claim_sec02_7",
                "type": "claim",
                "title": "Unseasoned Linear Churn Assumption",
                "section_id": "sec_02_unit_economics",
                "clause_text": "unseasoned linear churn assumptions",
                "direct_child_ids": ["ass_sec02_7_1"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "assumption",
                    "score": 0.70,
                    "evaluator_type": "llm_auditor",
                    "evaluator_note": "Explicitly flagged model assumption; historical Q4 renewal cliffs typically elevate churn by 90-140 bps."
                }
            },
            "ass_sec02_7_1": {
                "id": "ass_sec02_7_1",
                "type": "assumption",
                "title": "Constant Linear Churn Decay",
                "section_id": "sec_02_unit_economics",
                "body": "Assumes monthly logo churn remains invariant at 3.2% across 36 months without accounting for annual contract renewal cliffs.",
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_sec02_7", "claim_sec02_6"],
                "audit": {
                    "status": "assumption",
                    "score": 0.70,
                    "evaluator_type": "llm_auditor",
                    "evaluator_note": "Unverified multi-year baseline assumption."
                }
            }
        }
    },
    "candidate_exec_screen": {
        "bundle_id": "candidate_exec_screen",
        "artifact": {
            "title": "VP of Infrastructure Engineering — Candidate Technical & Reference Audit",
            "version": "1.0.0",
            "created_at": "2026-10-24T09:15:00Z",
            "metadata": {
                "candidate_id": "CAND-2026-089",
                "role": "VP of Infrastructure & Distributed Systems",
                "requisition": "REQ-ENG-402",
                "document_type": "Executive Screening & Reference Verification Memo"
            },
            "summary": "Structured evaluation of Candidate CAND-2026-089 against the VP of Infrastructure JD rubric. Verifies multi-region Kubernetes migration scale and cloud unit-cost reductions while flagging a tension between self-reported team headcount and verified org chart records.",
            "sections": [
                {
                    "section_id": "sec_01_scale_verification",
                    "section_title": "I. Infrastructure Scale & Cost Optimization Track Record",
                    "order": 1,
                    "content": (
                        "Candidate meets the principal technical bar of the JD, having "
                        "<ref id='claim_jd_1'>reduced compute unit costs by 34% across a $28M AWS footprint</ref> "
                        "while maintaining <ref id='claim_jd_2'>99.994% multi-region availability during peak traffic</ref>."
                    )
                },
                {
                    "section_id": "sec_02_org_leadership",
                    "section_title": "II. Organizational Scope & Executive Reference Audit",
                    "order": 2,
                    "content": (
                        "On organizational scope, the candidate's resume states they "
                        "<ref id='claim_jd_3'>directed a 95-person global platform organization</ref>, "
                        "whereas backchannel verification indicates <ref id='claim_jd_4'>direct management of 38 FTEs with 57 dotted-line contractors</ref>."
                    )
                }
            ]
        },
        "audit_summary": {
            "total_claims": 4,
            "verified_count": 3,
            "extrapolation_count": 1,
            "assumption_count": 0,
            "cross_section_tensions": [
                {
                    "tension_id": "ten_org_headcount",
                    "involved_claim_ids": ["claim_jd_3", "claim_jd_4"],
                    "severity": "blocker",
                    "description": "Candidate's resume claims a 95-engineer org size (Section II, Claim 3), but verified HRIS/reference records show 38 direct FTEs and 57 offshore migration contractors (Claim 4). Requires calibration against JD requirement of 60+ direct FTE leadership."
                }
            ]
        },
        "nodes": {
            "claim_jd_1": {
                "id": "claim_jd_1",
                "type": "claim",
                "title": "34% Compute Unit Cost Reduction",
                "section_id": "sec_01_scale_verification",
                "clause_text": "reduced compute unit costs by 34% across a $28M AWS footprint",
                "direct_child_ids": ["evi_jd_1_1", "calc_jd_1_2"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "verified",
                    "score": 0.96,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Corroborated by CTO reference transcript and FinOps architecture case study."
                }
            },
            "evi_jd_1_1": {
                "id": "evi_jd_1_1",
                "type": "evidence",
                "title": "Former CTO Reference Transcript",
                "section_id": "sec_01_scale_verification",
                "quote": "They led our Graviton4 and Karpenter bin-packing migration in 2025, taking annual EC2/EKS spend from $28.4M down to $18.7M at flat request volume.",
                "locator": {
                    "source_type": "pdf",
                    "file_name": "Ref_Transcript_CTO_2026_10.pdf",
                    "page": 3,
                    "bounding_box": [105, 310, 495, 415],
                    "locator_key": "REF-CTO-Q4"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_jd_1"],
                "audit": {
                    "status": "verified",
                    "score": 0.98,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Verbatim quote from structured 45-minute executive reference call."
                }
            },
            "calc_jd_1_2": {
                "id": "calc_jd_1_2",
                "type": "calculation",
                "title": "Annualized AWS Savings Calculation",
                "section_id": "sec_01_scale_verification",
                "formula": "Reduction = ($28.4M - $18.7M) / $28.4M = 34.15%",
                "body": "Matches the <ref id='aut_jd_1_2_sub101'>JD Level-6 Rubric Threshold</ref> requiring >= 25% verified unit-cost optimization at >$20M annual cloud spend.",
                "direct_child_ids": ["aut_jd_1_2_sub101"],
                "parent_claim_ids": ["claim_jd_1"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Exact arithmetic match."
                }
            },
            "aut_jd_1_2_sub101": {
                "id": "aut_jd_1_2_sub101",
                "type": "authority",
                "title": "JD Competency Rubric — Cloud Economics (REQ-ENG-402)",
                "section_id": "sec_01_scale_verification",
                "quote": "Score 5/5 (Distinguished): Demonstrated ownership of >$20M cloud budget with >=25% unit-economic efficiency improvement without SLA degradation.",
                "locator": {
                    "source_type": "internal_db",
                    "database": "talent_rubric_db",
                    "table": "jd_competency_matrix",
                    "query": "SELECT competency_name, level_5_criteria FROM jd_competency_matrix WHERE req_id = 'REQ-ENG-402' AND competency_id = 'CLOUD_FINOPS';",
                    "row_id": "CLOUD_FINOPS"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_jd_1"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Canonical hiring rubric requirement."
                }
            },
            "claim_jd_2": {
                "id": "claim_jd_2",
                "type": "claim",
                "title": "99.994% Multi-Region Uptime SLA",
                "section_id": "sec_01_scale_verification",
                "clause_text": "99.994% multi-region availability during peak traffic",
                "direct_child_ids": ["evi_jd_2_1"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "verified",
                    "score": 0.95,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Confirmed via public status history archive and engineering post-mortem review."
                }
            },
            "evi_jd_2_1": {
                "id": "evi_jd_2_1",
                "type": "evidence",
                "title": "Public StatusPage Historical Telemetry",
                "section_id": "sec_01_scale_verification",
                "quote": "FY2025 Core API Gateway Uptime: 99.994% (26.2 minutes total unscheduled degradation across 365 days).",
                "locator": {
                    "source_type": "web",
                    "url": "https://status.acme-cloud-example.io/history/2025-annual",
                    "snapshot_timestamp": "2026-10-18T11:20:00Z",
                    "locator_key": "#uptime-summary-2025",
                    "payload_hash": "sha256:44e812b90c33a"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_jd_2"],
                "audit": {
                    "status": "verified",
                    "score": 0.95,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Verified against external status archive."
                }
            },
            "claim_jd_3": {
                "id": "claim_jd_3",
                "type": "claim",
                "title": "Self-Reported 95-Person Org Scope",
                "section_id": "sec_02_org_leadership",
                "clause_text": "directed a 95-person global platform organization",
                "direct_child_ids": ["evi_jd_3_1"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "extrapolation",
                    "score": 0.62,
                    "evaluator_type": "llm_auditor",
                    "evaluator_note": "Candidate conflates temporary vendor migration contractors with permanent direct FTE engineering reports."
                }
            },
            "evi_jd_3_1": {
                "id": "evi_jd_3_1",
                "type": "evidence",
                "title": "Candidate Curriculum Vitae (Page 1)",
                "section_id": "sec_02_org_leadership",
                "quote": "VP of Infrastructure (2023–2026): Led a global organization of 95 SREs, platform engineers, and database reliability specialists.",
                "locator": {
                    "source_type": "pdf",
                    "file_name": "Candidate_089_CV.pdf",
                    "page": 1,
                    "bounding_box": [75, 220, 540, 290],
                    "locator_key": "CV-EXP-1"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_jd_3"],
                "audit": {
                    "status": "verified",
                    "score": 1.0,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Accurately quotes candidate CV, though underlying reality is qualified by Claim 4."
                }
            },
            "claim_jd_4": {
                "id": "claim_jd_4",
                "type": "claim",
                "title": "Verified Headcount Split (38 FTEs / 57 Contractors)",
                "section_id": "sec_02_org_leadership",
                "clause_text": "direct management of 38 FTEs with 57 dotted-line contractors",
                "direct_child_ids": ["evi_jd_4_1"],
                "parent_claim_ids": [],
                "audit": {
                    "status": "verified",
                    "score": 0.97,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Confirmed by VP of People reference and Greenhouse scorecard notes."
                }
            },
            "evi_jd_4_1": {
                "id": "evi_jd_4_1",
                "type": "evidence",
                "title": "Executive Recruiter Scorecard & Reference Matrix",
                "section_id": "sec_02_org_leadership",
                "quote": "Core FTE headcount was 38 across 4 Engineering Managers; 57 systems integrator contractors rolled up for a 9-month datacenter exit.",
                "locator": {
                    "source_type": "spreadsheet",
                    "file_name": "REQ_402_Candidate_Calibration.xlsx",
                    "sheet": "Org_Verification",
                    "cell_range": "D11",
                    "raw_value": "38 FTE / 57 SI Contractors"
                },
                "direct_child_ids": [],
                "parent_claim_ids": ["claim_jd_4"],
                "audit": {
                    "status": "verified",
                    "score": 0.97,
                    "evaluator_type": "deterministic",
                    "evaluator_note": "Directly verified in calibration workbook cell D11."
                }
            }
        }
    }
}


def get_sample_bundles() -> Dict[str, CompiledBundle]:
    """Deserializes and returns all built-in sample `CompiledBundle` datasets.

    Returns:
        Dictionary mapping `bundle_id` strings to validated `CompiledBundle` objects.
    """
    return {
        bundle_id: CompiledBundle.model_validate(payload)
        for bundle_id, payload in RAW_BUNDLES.items()
    }
