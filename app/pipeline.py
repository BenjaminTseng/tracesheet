"""Four-stage bottom-up agentic pipeline and smart feedback regenerator.

Orchestrates the end-to-end compilation of a user question `(c)` against
standing canonical authorities `(b)` and coordinate-indexed project inputs `(a)`:
1. Stage 1 (`run_stage1_outline`): Question decomposition & canonical `[AUTH:...]` mapping.
2. Stage 2 (`run_stage2_harvester`): Tool-assisted fact harvesting over indexed inputs `(a)`.
3. Stage 3 (`run_stage3_section_drafter`): Constrained Tier-1 `SectionOutput` drafting.
4. Stage 4 (`run_stage4_section_auditor`, cross-section tensions, editorial stitcher,
   and `CompiledGraphBuilder`): Verification, smoothing, and DAG compilation.

Also implements `apply_comments_and_recompile` for Antigravity-style batched inline
review comments with smart Stage-2 fallback triage.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.ingest import CanonicalRouter, MatterIngestor
from app.llm import LLMProvider
from app.models import (
    AuditStatus,
    CompiledBundle,
    CompiledGraphBuilder,
    ExtractedFactItem,
    NodeAudit,
    OutlinePlan,
    ReviewComment,
    SectionAuditResult,
    SectionOutput,
    SectionPlan,
    SectionValidator,
    SourceLocator,
    StitchInvariantGate,
    SubSupportItem,
    SupportGroup,
    SupportItem,
    TensionObject,
    VerifiedFactLedger,
)

logger = logging.getLogger("jd_screen.pipeline")


# =====================================================================
# Stage 4 & Feedback Triage Output Schemas
# =====================================================================

class CrossSectionAuditOutput(BaseModel):
    """Structured list of cross-section logical or numeric tensions."""

    tensions: List[TensionObject] = Field(default_factory=list)


class SmoothedSectionItem(BaseModel):
    """Polished prose for one section preserving `<ref n='sec_id:X'>` tags."""

    section_id: str
    smoothed_text: str


class StitchedDocumentOutput(BaseModel):
    """Per-section output of the Stage 4 Executive Managing Editor pass."""

    sections: List[SmoothedSectionItem] = Field(default_factory=list)


class FeedbackTriageDecision(BaseModel):
    """Classifies whether queued human comments require Stage 2 re-harvesting."""

    needs_stage2_reharvest: bool
    rationale: str
    additional_fact_queries: List[str] = Field(default_factory=list)


# =====================================================================
# Pipeline Runner
# =====================================================================

class AuditPipelineRunner:
    """Executes the 4-stage grounded authoring pipeline and incremental feedback loops."""

    def __init__(
        self,
        llm: LLMProvider,
        canonical_router: CanonicalRouter,
        matter_ingestor: MatterIngestor,
    ) -> None:
        """Initializes the pipeline runner.

        Args:
            llm: Configured `LLMProvider` (`GeminiInteractionsProvider`, etc.).
            canonical_router: Router providing `canonical/INDEX.md` and `[AUTH:...]` texts.
            matter_ingestor: Ingestor providing indexed inputs `(a)` and Stage 2 tools.
        """
        self.llm = llm
        self.canonical_router = canonical_router
        self.matter_ingestor = matter_ingestor

    def _emit_progress(
        self,
        callback: Optional[Callable[[str, str], None]],
        stage: str,
        message: str,
    ) -> None:
        """Logs progress and invokes an optional UI/CLI progress callback."""
        logger.info("[%s] %s", stage, message)
        if callback is not None:
            callback(stage, message)

    # ------------------------------------------------------------------
    # Stage 1: Question Decomposition & Canonical Rule Mapping
    # ------------------------------------------------------------------

    def run_stage1_outline(self, matter_id: str, question: str) -> OutlinePlan:
        """Decomposes user request `(c)` into sections routed over catalog `(b)`.

        Reads ONLY the compact Tier 1 `canonical/INDEX.md` catalog and gives Stage 1
        canonical browse/search/read tools so large corpora stay token-efficient.
        Hydrates exact `verbatim_quote` and `url` fields from `CanonicalRouter`.

        Args:
            matter_id: Target project/matter identifier.
            question: User analytical or legal question `(c)`.

        Returns:
            Validated `OutlinePlan` with hydrated canonical authorities.
        """
        index_md = self.canonical_router.get_index_markdown()
        stage1_tools = self.canonical_router.build_stage1_tools()
        matter_info = next(
            (m for m in self.matter_ingestor.list_matters() if m["matter_id"] == matter_id),
            {"matter_id": matter_id, "raw_files": []},
        )

        system_instruction = (
            "You are the Lead Analytical Architect. Decompose the user's question (c) into "
            "ordered, non-overlapping sections. Read the high-level Canonical Knowledge Catalog "
            "(INDEX.md) first. Whenever a document looks relevant, call `browse_canonical_toc`, "
            "`search_canonical_authorities`, and `read_canonical_authority` to identify exact "
            "[AUTH:...] rules to assign to that section's `governing_authorities`. If a section "
            "depends solely on project evidence (a) plus arithmetic or commonsense reasoning, "
            "leave `governing_authorities` empty (`[]`) rather than forcing irrelevant citations. "
            "For EVERY section, fill `routing_rationale` in plain English explaining why you chose "
            "those rules (or why pure evidence/commonsense suffices) and what facts Stage 2 must verify."
        )
        prompt = (
            f"### User Request (c)\n{question}\n\n"
            f"### Available Project Files (a) in matter '{matter_id}'\n"
            f"{json.dumps(matter_info.get('raw_files', []), indent=2)}\n\n"
            f"### Canonical Knowledge Catalog (b) — INDEX.md\n{index_md}\n\n"
            "Inspect relevant canonical TOCs/authorities with your tools if needed, then emit an OutlinePlan JSON."
        )
        plan = self.llm.run_tool_loop(
            prompt=prompt,
            system_instruction=system_instruction,
            tools=stage1_tools,
            response_model=OutlinePlan,
        )

        # Hydrate exact canonical quotes/URLs from disk to prevent paraphrase drift
        for sec in plan.sections:
            hydrated = []
            for ref in sec.governing_authorities:
                canonical_entry = self.canonical_router.get_authority(ref.auth_id)
                hydrated.append(canonical_entry if canonical_entry is not None else ref)
            sec.governing_authorities = hydrated

        return plan

    # ------------------------------------------------------------------
    # Stage 2: Agentic Evidence Harvesting
    # ------------------------------------------------------------------

    def run_stage2_harvester(
        self,
        matter_id: str,
        section_plan: SectionPlan,
        extra_queries: Optional[List[str]] = None,
    ) -> VerifiedFactLedger:
        """Runs a tool-assisted fact & authority verification loop over `(a)` and `(b)`.

        Combines project file search tools `(a)` with canonical discovery tools `(b)`,
        verifies and hydrates returned locators/values against disk via
        `MatterIngestor.verify_and_hydrate_ledger`, and merges any newly discovered
        canonical authorities into `section_plan.governing_authorities`.
        """
        # Ensure deterministic ingestion has run before harvesting
        _, _, indexed_dir, _ = self.matter_ingestor._matter_dirs(matter_id)
        if not (indexed_dir / "manifest.json").exists():
            self.matter_ingestor.ingest_matter(matter_id)

        tools = (
            self.matter_ingestor.build_stage2_tools(matter_id)
            + self.canonical_router.build_stage1_tools()
        )
        queries = list(section_plan.required_fact_queries)
        if extra_queries:
            queries.extend(q for q in extra_queries if q not in queries)

        system_instruction = (
            "You are a Forensic Fact Extractor. Use the project search and spreadsheet tools "
            "to gather exact evidence from the coordinate-indexed project inputs (a). You MUST "
            "copy the exact `locator` coordinates and verbatim `quote` (or `raw_value` and `formula`) "
            "returned by the tools—never invent page numbers, locator keys, or cell coordinates. "
            "MANDATORY LOCATOR COORDINATES: "
            "(1) For markdown/pdf sources, set `locator.source_type` to `'markdown'` or `'pdf'`, set "
            "`locator.file_name`, and ALWAYS populate `locator.locator_key` (preferring substantive body "
            "paragraph or table-row locators over bare `# Heading` locators). "
            "(2) For spreadsheet/CSV sources, set `locator.source_type` to `'spreadsheet'`, set "
            "`locator.file_name`, and ALWAYS populate BOTH `locator.sheet` (e.g. `'CSV'`) AND exact "
            "`locator.cell_range` (e.g. `'C2'`). "
            "If evidence reveals an unanticipated issue governed by a canonical rule not listed "
            "under Governing Authorities, use the canonical browse/search/read tools to fetch it "
            "and list it in `additional_authorities`. Record unanswerable queries in `unresolved_gaps`, "
            "and write a concise plain-English `harvest_summary` describing what you found or missed."
        )
        prompt = (
            f"Section ID: {section_plan.section_id}\n"
            f"Section Title: {section_plan.section_title}\n"
            f"Stated Intention: {section_plan.stated_intention}\n"
            f"Stage 1 Routing Rationale: {section_plan.routing_rationale or 'N/A'}\n\n"
            f"Governing Authorities (b):\n"
            f"{json.dumps([a.model_dump() for a in section_plan.governing_authorities], indent=2)}\n\n"
            f"Required Fact Queries:\n"
            + "\n".join(f"- {q}" for q in queries)
            + "\n\nSearch the indexed files now and emit a VerifiedFactLedger JSON."
        )

        ledger = self.llm.run_tool_loop(
            prompt=prompt,
            system_instruction=system_instruction,
            tools=tools,
            response_model=VerifiedFactLedger,
        )
        ledger.section_id = section_plan.section_id

        # Programmatic L1 locator + quote verification and disk hydration
        ledger, _ = self.matter_ingestor.verify_and_hydrate_ledger(matter_id, ledger)

        # Hydrate any newly discovered canonical authorities and merge into section_plan
        hydrated_extra = []
        existing_ids = {a.auth_id for a in section_plan.governing_authorities}
        for ref in ledger.additional_authorities:
            canonical_entry = self.canonical_router.get_authority(ref.auth_id)
            resolved = canonical_entry if canonical_entry is not None else ref
            hydrated_extra.append(resolved)
            if resolved.auth_id not in existing_ids:
                section_plan.governing_authorities.append(resolved)
                existing_ids.add(resolved.auth_id)
        ledger.additional_authorities = hydrated_extra

        return ledger

    # ------------------------------------------------------------------
    # Stage 3: Constrained Tier-1 Section Drafting (with validator retries)
    # ------------------------------------------------------------------

    @staticmethod
    def _hydrate_node_locator(
        node: Any,
        by_fact_id: Dict[str, Any],
        by_key: Dict[str, Any],
        by_cell: Dict[Tuple[Optional[str], Optional[str]], Any],
    ) -> None:
        """Hydrates full disk `SourceLocator` metadata onto a support or sub-support node."""
        matched_fact = by_fact_id.get(node.fact_id) if getattr(node, "fact_id", None) else None
        if matched_fact is not None:
            if node.locator is None:
                node.locator = matched_fact.locator.model_copy()
            else:
                merged = matched_fact.locator.model_dump()
                for k, v in node.locator.model_dump(exclude_none=True).items():
                    merged[k] = v
                node.locator = SourceLocator.model_validate(merged)
            if not node.quote and matched_fact.quote:
                node.quote = matched_fact.quote
            return

        if node.locator is not None:
            if node.locator.locator_key and node.locator.locator_key in by_key:
                disk_loc = by_key[node.locator.locator_key].locator.model_dump()
                for k, v in node.locator.model_dump(exclude_none=True).items():
                    disk_loc[k] = v
                node.locator = SourceLocator.model_validate(disk_loc)
            elif (
                node.locator.file_name
                and node.locator.cell_range
                and (node.locator.file_name, node.locator.cell_range) in by_cell
            ):
                disk_loc = by_cell[
                    (node.locator.file_name, node.locator.cell_range)
                ].locator.model_dump()
                for k, v in node.locator.model_dump(exclude_none=True).items():
                    disk_loc[k] = v
                node.locator = SourceLocator.model_validate(disk_loc)

    @classmethod
    def _hydrate_stage3_locators(
        cls, draft: SectionOutput, ledger: VerifiedFactLedger
    ) -> None:
        """Deterministically hydrates full `SourceLocator` metadata across items and sub-supports."""
        by_fact_id = {f.fact_id: f for f in ledger.verified_facts if f.fact_id}
        by_key = {
            f.locator.locator_key: f
            for f in ledger.verified_facts
            if f.locator.locator_key
        }
        by_cell: Dict[Tuple[Optional[str], Optional[str]], Any] = {
            (f.locator.file_name, f.locator.cell_range): f
            for f in ledger.verified_facts
            if f.locator.cell_range
        }

        for grp in draft.supports:
            for item in grp.items:
                cls._hydrate_node_locator(item, by_fact_id, by_key, by_cell)
                for sub in item.sub_supports:
                    cls._hydrate_node_locator(sub, by_fact_id, by_key, by_cell)

    def run_stage3_section_drafter(
        self,
        section_plan: SectionPlan,
        ledger: VerifiedFactLedger,
        prior_draft: Optional[SectionOutput] = None,
        review_comments: Optional[List[ReviewComment]] = None,
        audit_critique: Optional[str] = None,
        max_validation_retries: int = 2,
    ) -> SectionOutput:
        """Drafts a Tier-1 `SectionOutput` grounded strictly in `ledger` and `(b)`.

        Automatically retries if `SectionValidator.validate_section` or
        `MatterIngestor.verify_section_citations` detects structural tag parity errors,
        missing plain-English explanations on reasoning/calculation/assumption nodes,
        or unverified `L1`/`L2` citations.
        """
        system_instruction = (
            "You are an expert legal and analytical author. Follow the Closed-World Evidence "
            "Constraint strictly: cite ONLY verified facts, quotes, formulas, and `locator` objects from the "
            "VerifiedFactLedger (for L1 evidence/calculations) and Governing Canonical Authorities (for L2+ "
            "authorities). Wrap every substantive empirical, legal, or gap-disclosure claim in "
            "`<ref n='1'>clause text</ref>` using sequential integers 1, 2, 3... "
            "Every `<ref n='X'>` in `text` MUST have a matching SupportGroup `n=X` in `supports`. "
            "CRITICAL CITATION RULES: "
            "(1) EVERY SupportItem OR SubSupportItem with `type='evidence'` MUST cite a `VerifiedFact` from `VerifiedFactLedger`: "
            "set `fact_id` to that fact's `fact_id` (e.g., `\"FACT-1\"`), copy its `quote`, and optionally include "
            "its compact `locator` (`{\"source_type\": ..., \"file_name\": ..., \"locator_key\": ...}`). Never emit "
            "`type='evidence'` (at L1 or in `sub_supports`) without a valid `fact_id` or `locator`, and never mix one fact's locator with another fact's quote. "
            "(2) You MUST include a matching SupportGroup entry in `supports` for EVERY `<ref n='X'>` tag in `text` (never stop early). "
            "(2) NEVER invent facts, party attributions, or external legal authorities not in `(a)` or `(b)`. When noting "
            "missing records, absent party attribution, or unresolved gaps without a direct quote, set `type='assumption'` "
            "or `type='reasoning'` (NOT `type='evidence'`) with a clear plain-English `body`. "
            "(3) Any `<ref n='10X'>` inside a `body` MUST have a matching SubSupportItem `n=10X` in `sub_supports`. "
            "When citing a Governing Authority (`type='authority'`), include its `AUTH:...` ID in `title` and copy "
            "its `verbatim_quote`. When a claim relies on L1 evidence plus commonsense or arithmetic rather than a "
            "canonical rule, leave `sub_supports=[]` and explain the logic in `body`. "
            "(4) Every `reasoning`, `calculation`, or `assumption` SupportItem MUST have a non-empty plain-English `body`. "
            "Always populate `drafting_notes` explaining how you connected facts, authorities, gaps, or commonsense."
        )

        feedback_block = ""
        if prior_draft is not None and review_comments:
            formatted_comments = "\n".join(
                f"- [Scope: {c.scope.upper()} | Target: {c.target_label or c.node_id}"
                + (f" | Requested Status: {c.suggested_status}" if c.suggested_status else "")
                + f"]: {c.comment_text}"
                for c in review_comments
            )
            feedback_block = (
                f"\n\n### Prior Section Draft\n{prior_draft.model_dump_json(indent=2)}\n\n"
                f"### Human Reviewer Feedback (MUST ADDRESS)\n{formatted_comments}\n"
                "Revise the section text, support reasoning, logical connections, and audit flags to "
                "directly resolve all reviewer comments while keeping valid citations intact."
            )

        base_prompt = (
            f"Section ID: {section_plan.section_id}\n"
            f"Section Title: {section_plan.section_title}\n"
            f"Stated Intention: {section_plan.stated_intention}\n"
            f"Stage 1 Routing Rationale: {section_plan.routing_rationale or 'N/A'}\n"
            f"Stage 2 Harvest Summary: {ledger.harvest_summary or 'N/A'}\n\n"
            f"### Verified Fact Ledger (a)\n{ledger.model_dump_json(indent=2)}\n\n"
            f"### Governing Canonical Authorities (b)\n"
            f"{json.dumps([a.model_dump() for a in section_plan.governing_authorities], indent=2)}"
            f"{feedback_block}"
        )
        if audit_critique:
            base_prompt += f"\n\n### Auditor Critique to Fix\n{audit_critique}"

        prompt = base_prompt
        last_errors: List[str] = []
        draft: Optional[SectionOutput] = None

        for attempt in range(max_validation_retries + 1):
            draft = self.llm.generate_structured(
                prompt=prompt,
                system_instruction=system_instruction,
                response_model=SectionOutput,
            )
            draft.section_id = section_plan.section_id
            if not draft.section_title:
                draft.section_title = section_plan.section_title
            self._hydrate_stage3_locators(draft, ledger)

            is_valid, struct_errors = SectionValidator.validate_section(draft)
            cit_errors = self.matter_ingestor.verify_section_citations(
                draft, ledger, section_plan.governing_authorities
            )
            all_errors = struct_errors + cit_errors
            if is_valid and not all_errors:
                return draft

            last_errors = all_errors
            logger.warning(
                "Section '%s' failed Stage 3 validation/citation check (attempt %d): %s",
                section_plan.section_id,
                attempt + 1,
                all_errors,
            )
            prompt = (
                f"{base_prompt}\n\n"
                f"### Structural & Citation Verification Errors to Fix\n"
                + "\n".join(f"- {e}" for e in all_errors)
            )

        raise ValueError(
            f"Section '{section_plan.section_id}' failed SectionValidator/Citation check after "
            f"{max_validation_retries + 1} attempts: {last_errors}"
        )

    # ------------------------------------------------------------------
    # Stage 4: 3-Point Section Auditor, Tension Audit & Editorial Stitcher
    # ------------------------------------------------------------------

    def run_stage4_section_auditor(
        self,
        matter_id: str,
        section_plan: SectionPlan,
        draft: SectionOutput,
    ) -> SectionAuditResult:
        """Verifies relevance, surrounding-context congruence, and outline alignment."""
        locators: List[SourceLocator] = []
        for grp in draft.supports:
            for item in grp.items:
                if item.locator:
                    locators.append(item.locator)
                for sub in item.sub_supports:
                    if sub.locator:
                        locators.append(sub.locator)

        expanded_context = self.matter_ingestor.expand_locator_context(matter_id, locators)
        auth_context = json.dumps(
            [a.model_dump() for a in section_plan.governing_authorities], indent=2
        )

        system_instruction = (
            "You are an Independent Audit Gate. Verify three invariants: "
            "(a) check_a_relevance: every support item (including pure commonsense, gap-disclosure, or "
            "arithmetic reasoning) logically backs its `<ref n>` clause; "
            "(b) check_b_congruence: surrounding source context strictly entails each factual claim "
            "without cherry-picking, distorting numbers/entities, or dropping disqualifying exceptions; "
            "(c) check_c_intent: the section answers its stated_intention using the available closed-world inputs. "
            "CLOSED-WORLD HONESTY RULE: Under the Closed-World Evidence Constraint, the drafter CANNOT "
            "invent missing facts or unindexed legal authorities. If source records `(a)` or Canonical "
            "Authorities `(b)` omit required details (e.g., LLC member domiciles, missing party attribution, "
            "or unindexed rules), honestly stating those exact evidentiary gaps via `assumption`/`reasoning` "
            "nodes SATISFIES `check_c_intent` and should PASS (`passed=True`, tagging uncertain claims as "
            "`assumption` or `extrapolation` in `node_verdicts`). NEVER reject with `passed=False` merely to "
            "demand non-existent external records or outside case law. "
            "Return passed=False with `critique_for_retry` ONLY if the draft misstates/distorts the provided "
            "context, makes an unsupported attribution leap without disclosing it as an assumption/gap, drops "
            "a disqualifying exception present in context, or fails to use available facts relevant to stated_intention. "
            "Always populate `audit_rationale` and `node_verdicts` with clear `evaluator_note` explanations."
        )
        prompt = (
            f"Stated Intention: {section_plan.stated_intention}\n\n"
            f"Drafted SectionOutput:\n{draft.model_dump_json(indent=2)}\n\n"
            f"Expanded Source Context (a):\n{expanded_context or '(No external block context)'}\n\n"
            f"Canonical Authorities (b):\n{auth_context}"
        )

        questions: Dict[str, Dict[str, Any]] = {
            "check_a_relevance": {
                "type": "noul",
                "instructions": (
                    "Does every support item (including commonsense/arithmetic reasoning or explicit gap disclosures) "
                    "directly back its paired <ref n> claim without irrelevant padding?"
                ),
            },
            "check_b_congruence": {
                "type": "noul",
                "instructions": (
                    "Do the verbatim source quotes and expanded source context strictly entail "
                    "every factual claim, number, and entity attribution (or honestly flag unattributed/missing records "
                    "as assumptions/gaps without overclaiming)?"
                ),
            },
            "check_c_intent": {
                "type": "noul",
                "instructions": (
                    "Does the drafted section address its stated_intention using only the available closed-world "
                    "evidence and canonical authorities—either answering it directly OR honestly identifying exact "
                    "record/authority gaps when the provided inputs are incomplete?"
                ),
            },
        }
        for grp in draft.supports:
            questions[f"claim_{grp.n}_entailment"] = {
                "type": "noul",
                "instructions": (
                    f"Is claim n={grp.n} ('{grp.title or grp.n}') strictly supported by its attached evidence, "
                    "calculations, and canonical authority items—OR, if framed as an explicit assumption or gap "
                    "disclosure, does it accurately report what the closed-world context establishes vs. omits?"
                ),
            }
            questions[f"claim_{grp.n}_status"] = {
                "type": "choice",
                "instructions": f"Classify the epistemic audit status of claim n={grp.n}.",
                "criteria": {
                    "verified": "Directly entailed by source quote/formula or valid step-by-step arithmetic.",
                    "extrapolation": "Reasonable inference extending slightly beyond literal quote.",
                    "assumption": "Unverified premise or missing supporting link.",
                    "disputed": "Contradicted by surrounding source context or cited values.",
                },
            }

        decision_model = os.environ.get("JD_SCREEN_DECISION_MODEL", "models/gemini-decision-1")
        batch = self.llm.evaluate_decisions(
            input_text=prompt,
            questions=questions,
            decision_model=decision_model,
        )

        if batch.answers:
            ans = batch.answers
            probs: Dict[str, float] = {}
            for qid, item in ans.items():
                if item.question_type == "noul" and item.noul is not None:
                    probs[qid] = float(item.noul)
                else:
                    probs[qid] = float(item.confidence)

            check_a = (ans["check_a_relevance"].noul or 0.0) >= 0.80 if "check_a_relevance" in ans else True
            check_b = (ans["check_b_congruence"].noul or 0.0) >= 0.80 if "check_b_congruence" in ans else True
            check_c = (ans["check_c_intent"].noul or 0.0) >= 0.80 if "check_c_intent" in ans else True

            all_claims_entailed = True
            failing_reasons: List[str] = []
            if not check_a:
                failing_reasons.append(f"check_a_relevance={probs.get('check_a_relevance', 0.0):.2f} < 0.80")
            if not check_b:
                failing_reasons.append(f"check_b_congruence={probs.get('check_b_congruence', 0.0):.2f} < 0.80")
            if not check_c:
                failing_reasons.append(f"check_c_intent={probs.get('check_c_intent', 0.0):.2f} < 0.80")

            node_verdicts: Dict[int, NodeAudit] = {}
            for grp in draft.supports:
                ent_key = f"claim_{grp.n}_entailment"
                st_key = f"claim_{grp.n}_status"
                ent_prob = float(ans[ent_key].noul or 0.0) if ent_key in ans else 1.0
                if ent_key in ans and ent_prob < 0.75:
                    all_claims_entailed = False
                    failing_reasons.append(f"{ent_key}={ent_prob:.2f} < 0.75")
                if st_key in ans and ans[st_key].choice:
                    raw_choice = ans[st_key].choice
                    valid_statuses = ("verified", "extrapolation", "assumption", "disputed")
                    status_val = (
                        raw_choice
                        if raw_choice in valid_statuses
                        else ("verified" if ent_prob >= 0.75 else "extrapolation")
                    )
                    conf_val = float(ans[st_key].confidence)
                    node_verdicts[grp.n] = NodeAudit(
                        status=status_val,
                        score=round(conf_val, 3),
                        evaluator_type="llm_auditor",
                        evaluator_note=(
                            f"Decisions API ({raw_choice}): confidence={conf_val:.2f}, "
                            f"entailment={ent_prob:.2f}"
                        ),
                    )

            if check_a and check_b and check_c and all_claims_entailed:
                return SectionAuditResult(
                    section_id=draft.section_id,
                    check_a_relevance=True,
                    check_b_congruence=True,
                    check_c_intent=True,
                    passed=True,
                    audit_rationale=(
                        "All Stage 4 audit invariants (Checks A/B/C >= 0.80) and per-claim "
                        "entailment scores (>= 0.75) cleared via Gemini Decisions API."
                    ),
                    node_verdicts=node_verdicts,
                    decision_probabilities=probs,
                )

            rejection_prompt = (
                f"{prompt}\n\n"
                f"### Decisions API Rejection Flags\n"
                + "\n".join(f"- {r}" for r in failing_reasons)
                + "\nExplain the failure in `audit_rationale` and emit a concrete `critique_for_retry`."
            )
            result = self.llm.generate_structured(
                prompt=rejection_prompt,
                system_instruction=system_instruction,
                response_model=SectionAuditResult,
            )
            result.section_id = draft.section_id
            result.passed = False
            result.check_a_relevance = result.check_a_relevance and check_a
            result.check_b_congruence = result.check_b_congruence and check_b
            result.check_c_intent = result.check_c_intent and check_c
            result.decision_probabilities = probs
            if not result.node_verdicts and node_verdicts:
                result.node_verdicts = node_verdicts
            return result

        result = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
            response_model=SectionAuditResult,
        )
        result.section_id = draft.section_id
        return result

    def _draft_and_audit_section(
        self,
        matter_id: str,
        section_plan: SectionPlan,
        ledger: VerifiedFactLedger,
        prior_draft: Optional[SectionOutput] = None,
        review_comments: Optional[List[ReviewComment]] = None,
        max_audit_retries: int = 2,
    ) -> Tuple[SectionOutput, SectionAuditResult]:
        """Runs Stage 3 + Stage 4 Section Auditor with up to 2 congruence retries."""
        critique: Optional[str] = None
        draft: Optional[SectionOutput] = None
        audit_res: Optional[SectionAuditResult] = None

        for attempt in range(max_audit_retries + 1):
            draft = self.run_stage3_section_drafter(
                section_plan=section_plan,
                ledger=ledger,
                prior_draft=prior_draft,
                review_comments=review_comments,
                audit_critique=critique,
            )
            audit_res = self.run_stage4_section_auditor(matter_id, section_plan, draft)
            if audit_res.passed:
                # Apply per-claim audit verdicts emitted by the auditor
                for grp in draft.supports:
                    if grp.n in audit_res.node_verdicts:
                        grp.audit = audit_res.node_verdicts[grp.n]
                return draft, audit_res

            critique = audit_res.critique_for_retry or (
                f"Failed invariants: relevance={audit_res.check_a_relevance}, "
                f"congruence={audit_res.check_b_congruence}, intent={audit_res.check_c_intent}"
            )
            logger.warning(
                "Section '%s' failed Stage 4 audit (attempt %d): %s",
                section_plan.section_id,
                attempt + 1,
                critique,
            )

        assert draft is not None and audit_res is not None
        return draft, audit_res

    def run_stage4_cross_section_tensions(
        self, sections: List[SectionOutput]
    ) -> List[TensionObject]:
        """Detects logical or quantitative contradictions across compiled sections."""
        if len(sections) < 2:
            return []

        claim_summaries = []
        tag_re = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)
        for sec in sections:
            supports_by_n = {grp.n: grp for grp in sec.supports}
            for n_str, clause in tag_re.findall(sec.text):
                grp = supports_by_n.get(int(n_str))
                l1_supports = []
                if grp:
                    for item in grp.items:
                        l1_supports.append(
                            {
                                "type": item.type,
                                "title": item.title,
                                "quote": item.quote,
                                "formula": item.formula,
                                "body": item.body,
                            }
                        )
                claim_summaries.append(
                    {
                        "claim_id": f"claim_{sec.section_id}_{n_str}",
                        "section_id": sec.section_id,
                        "section_title": sec.section_title,
                        "full_section_text": sec.text,
                        "clause": clause.strip(),
                        "l1_supports": l1_supports,
                    }
                )

        system_instruction = (
            "You are a Cross-Section Consistency Auditor. Inspect all claims, full section context, "
            "and underlying L1 support values/formulas across sections. Flag only genuine numerical "
            "discrepancies, scope conflicts, or logical tensions. Use exact `claim_id` strings in "
            "`involved_claim_ids`."
        )
        prompt = f"Claims across sections:\n{json.dumps(claim_summaries, indent=2)}"
        res = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
            response_model=CrossSectionAuditOutput,
        )
        return res.tensions

    def run_stage4_stitcher(
        self, sections: List[SectionOutput]
    ) -> Optional[Dict[str, str]]:
        """Smooths rhetorical transitions across sections while enforcing `StitchInvariantGate`.

        Returns:
            Mapping `section_id -> smoothed_text` if `StitchInvariantGate` passes,
            or `None` to fall back cleanly to raw section text.
        """
        if not sections:
            return None

        namespaced_by_sec = {
            sec.section_id: StitchInvariantGate.prepare_section_for_stitch(sec)
            for sec in sections
        }
        pre_stitched = "\n\n".join(namespaced_by_sec.values())

        system_instruction = (
            "You are the Executive Managing Editor. Polish rhetorical transitions between "
            "sections without deleting, renaming, or emptying ANY `<ref n='...'>...</ref>` tag. "
            "Preserve the exact `sec_id:n` attribute values inside every `<ref>` tag and return "
            "one entry per section_id."
        )
        prompt = (
            "Polish transitions across these sections while strictly preserving every <ref> tag:\n\n"
            + json.dumps(
                [
                    {"section_id": sec_id, "text": txt}
                    for sec_id, txt in namespaced_by_sec.items()
                ],
                indent=2,
            )
        )
        stitched = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
            response_model=StitchedDocumentOutput,
        )

        smoothed_map = {item.section_id: item.smoothed_text for item in stitched.sections}
        if set(smoothed_map.keys()) != {s.section_id for s in sections}:
            logger.warning("Stitcher dropped or renamed section IDs; falling back to unsmoothed sections.")
            return None

        post_stitched = "\n\n".join(smoothed_map[s.section_id] for s in sections)
        passed, violations = StitchInvariantGate.verify_stitch(pre_stitched, post_stitched)
        if not passed:
            logger.warning("StitchInvariantGate rejected editorial pass: %s", violations)
            return None
        return smoothed_map

    # ------------------------------------------------------------------
    # Persistence & End-to-End Orchestration
    # ------------------------------------------------------------------

    def save_bundle(self, bundle: CompiledBundle) -> Optional[Path]:
        """Persists a `CompiledBundle` JSON under `matters/<matter_id>/bundles/`."""
        if not bundle.matter_id or not bundle.bundle_id:
            return None
        _, _, _, bundles_dir = self.matter_ingestor._matter_dirs(bundle.matter_id)
        bundles_dir.mkdir(parents=True, exist_ok=True)
        out_path = bundles_dir / f"{bundle.bundle_id}.json"
        out_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        return out_path

    def run_full_pipeline(
        self,
        matter_id: str,
        question: str,
        bundle_id: Optional[str] = None,
        smooth_transitions: bool = True,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CompiledBundle:
        """Executes Stages 1 -> 2 -> 3 -> 4 for a project matter and user question `(c)`.

        Args:
            matter_id: Project matter slug under `matters/`.
            question: User analytical or legal question `(c)`.
            bundle_id: Optional output bundle identifier (auto-generated if omitted).
            smooth_transitions: Whether to run the Stage 4 editorial stitcher pass.
            progress_callback: Optional `(stage, message)` callback for UI/CLI streaming.

        Returns:
            Compiled and persisted `CompiledBundle`.
        """
        self._emit_progress(progress_callback, "stage_1", "Decomposing question and mapping canonical authorities...")
        plan = self.run_stage1_outline(matter_id, question)

        ledgers: Dict[str, VerifiedFactLedger] = {}
        sections: List[SectionOutput] = []
        audits: Dict[str, SectionAuditResult] = {}

        for sec_plan in plan.sections:
            self._emit_progress(
                progress_callback,
                "stage_2",
                f"Harvesting coordinate-stamped facts for '{sec_plan.section_title}'...",
            )
            ledger = self.run_stage2_harvester(matter_id, sec_plan)
            ledgers[sec_plan.section_id] = ledger

            self._emit_progress(
                progress_callback,
                "stage_3_4",
                f"Drafting and auditing section '{sec_plan.section_title}'...",
            )
            section_out, audit_res = self._draft_and_audit_section(matter_id, sec_plan, ledger)
            sections.append(section_out)
            audits[sec_plan.section_id] = audit_res

        self._emit_progress(progress_callback, "stage_4_global", "Checking cross-section tensions and compiling DAG...")
        tensions = self.run_stage4_cross_section_tensions(sections)
        smoothed_map = self.run_stage4_stitcher(sections) if smooth_transitions else None

        builder = CompiledGraphBuilder(
            document_title=plan.document_title,
            summary=plan.executive_summary_intent,
            metadata={"document_type": "Audit-Grounded Agentic Brief", "matter_id": matter_id},
        )
        bundle = builder.compile_sections(
            sections=sections,
            smoothed_sections=smoothed_map,
            tensions=tensions,
        )
        slug = bundle_id or re.sub(r"[^a-z0-9]+", "_", f"{matter_id}_{plan.document_title[:24]}".lower()).strip("_")
        bundle.bundle_id = slug
        bundle.matter_id = matter_id
        bundle.question = question
        bundle.stage_artifacts = {
            "outline_plan": plan.model_dump(),
            "ledgers": {k: v.model_dump() for k, v in ledgers.items()},
            "sections": [s.model_dump() for s in sections],
            "audits": {k: v.model_dump() for k, v in audits.items()},
        }
        self.save_bundle(bundle)
        self._emit_progress(progress_callback, "completed", f"Compiled bundle '{slug}' with {bundle.audit_summary.total_claims} claims.")
        return bundle

    # ------------------------------------------------------------------
    # Antigravity-Style Batched Feedback & Smart Stage-2 Fallback
    # ------------------------------------------------------------------

    def _rehydrate_stage_artifacts(
        self, bundle: CompiledBundle
    ) -> Tuple[OutlinePlan, Dict[str, VerifiedFactLedger], Dict[str, SectionOutput]]:
        """Loads `stage_artifacts` or reconstructs fallback Tier-1 structures from a bundle."""
        artifacts = bundle.stage_artifacts or {}
        if "outline_plan" in artifacts and "ledgers" in artifacts and "sections" in artifacts:
            plan = OutlinePlan.model_validate(artifacts["outline_plan"])
            ledgers = {
                k: VerifiedFactLedger.model_validate(v)
                for k, v in artifacts["ledgers"].items()
            }
            sections = {
                s["section_id"]: SectionOutput.model_validate(s)
                for s in artifacts["sections"]
            }
            return plan, ledgers, sections

        # Fallback reconstruction for pre-loaded bundles without saved stage_artifacts
        ref_id_re = re.compile(r"<ref\s+id=['\"]([^'\"]+)['\"]>(.*?)</ref>", re.DOTALL)
        sec_plans: List[SectionPlan] = []
        ledgers = {}
        sections = {}

        for sec_obj in bundle.artifact.sections:
            local_idx = 0
            supports: List[SupportGroup] = []
            facts: List[ExtractedFactItem] = []

            def replace_claim(match: re.Match[str]) -> str:
                nonlocal local_idx
                node_id = match.group(1)
                clause = match.group(2)
                local_idx += 1
                claim_node = bundle.nodes.get(node_id)
                items: List[SupportItem] = []
                if claim_node:
                    for cid in claim_node.direct_child_ids:
                        cnode = bundle.nodes.get(cid)
                        if not cnode:
                            continue
                        if cnode.locator and cnode.quote:
                            facts.append(
                                ExtractedFactItem(
                                    fact_id=cid,
                                    query_addressed=cnode.title,
                                    title=cnode.title,
                                    quote=cnode.quote,
                                    formula=cnode.formula,
                                    locator=cnode.locator,
                                )
                            )
                        sub_items: List[SubSupportItem] = []
                        sub_body = cnode.body or ""
                        sub_counter = 100
                        for scid in cnode.direct_child_ids:
                            snode = bundle.nodes.get(scid)
                            if not snode:
                                continue
                            sub_counter += 1
                            sub_body = re.sub(
                                rf"<ref\s+id=['\"]{re.escape(scid)}['\"]>(.*?)</ref>",
                                lambda m, num=sub_counter: f"<ref n='{num}'>{m.group(1)}</ref>",
                                sub_body,
                                flags=re.DOTALL,
                            )
                            sub_items.append(
                                SubSupportItem(
                                    n=sub_counter,
                                    type=snode.type if snode.type != "claim" else "evidence",
                                    title=snode.title,
                                    quote=snode.quote,
                                    body=snode.body,
                                    formula=snode.formula,
                                    url=snode.url,
                                    locator=snode.locator,
                                    audit=snode.audit,
                                )
                            )
                        items.append(
                            SupportItem(
                                type=cnode.type if cnode.type != "claim" else "evidence",
                                title=cnode.title,
                                quote=cnode.quote,
                                body=sub_body or None,
                                formula=cnode.formula,
                                url=cnode.url,
                                locator=cnode.locator,
                                audit=cnode.audit,
                                sub_supports=sub_items,
                            )
                        )
                if not items:
                    items.append(
                        SupportItem(
                            type="assumption",
                            title=claim_node.title if claim_node else "Claim Support",
                            body=clause,
                        )
                    )
                supports.append(
                    SupportGroup(
                        n=local_idx,
                        title=claim_node.title if claim_node else None,
                        audit=claim_node.audit if claim_node else None,
                        items=items,
                    )
                )
                return f"<ref n='{local_idx}'>{clause}</ref>"

            rewritten_text = ref_id_re.sub(replace_claim, sec_obj.content)
            sec_plans.append(
                SectionPlan(
                    section_id=sec_obj.section_id,
                    section_title=sec_obj.section_title,
                    stated_intention=sec_obj.section_title,
                    governing_authorities=list(self.canonical_router.list_authorities().values()),
                    required_fact_queries=[],
                )
            )
            ledgers[sec_obj.section_id] = VerifiedFactLedger(
                section_id=sec_obj.section_id, verified_facts=facts, unresolved_gaps=[]
            )
            sections[sec_obj.section_id] = SectionOutput(
                section_id=sec_obj.section_id,
                section_title=sec_obj.section_title,
                text=rewritten_text,
                supports=supports,
            )

        plan = OutlinePlan(
            document_title=bundle.artifact.title,
            executive_summary_intent=bundle.artifact.summary or bundle.artifact.title,
            sections=sec_plans,
        )
        return plan, ledgers, sections

    def _triage_section_feedback(
        self,
        section_plan: SectionPlan,
        section_draft: SectionOutput,
        comments: List[ReviewComment],
    ) -> FeedbackTriageDecision:
        """Determines whether reviewer comments require re-searching `(a)` via Stage 2."""
        system_instruction = (
            "You triage human review feedback on an audit-grounded document section. "
            "Set needs_stage2_reharvest=True ONLY if the reviewer asks for new facts, asks "
            "a follow-up factual question, or challenges data requiring lookup in project files (a). "
            "Set needs_stage2_reharvest=False if the comments only ask to rephrase claims, adjust "
            "reasoning warrants, or change audit caveats (verified/extrapolation/assumption)."
        )
        formatted = "\n".join(
            f"- [{c.scope.upper()}] {c.target_label or c.node_id} "
            f"(suggested_status={c.suggested_status}): {c.comment_text}"
            for c in comments
        )
        prompt = (
            f"Section: {section_plan.section_title}\n"
            f"Current Draft:\n{section_draft.model_dump_json(indent=2)}\n\n"
            f"Reviewer Comments:\n{formatted}"
        )
        decision_model = os.environ.get("JD_SCREEN_DECISION_MODEL", "models/gemini-decision-1")
        batch = self.llm.evaluate_decisions(
            input_text=prompt,
            questions={
                "route": {
                    "type": "choice",
                    "instructions": (
                        "Does addressing these reviewer comments only require editing prose, "
                        "reasoning, or caveats from existing harvested facts (stage_3_redraft), "
                        "or does it require searching project files for new facts/numbers (stage_2_reharvest)?"
                    ),
                    "criteria": {
                        "stage_3_redraft": (
                            "Rephrase, formatting, date/title wording, logic adjustment, or audit "
                            "status change using already harvested facts."
                        ),
                        "stage_2_reharvest": (
                            "Requires looking up new facts, documents, spreadsheet cells, or "
                            "unharvested evidence."
                        ),
                    },
                }
            },
            decision_model=decision_model,
        )
        route_ans = batch.answers.get("route")
        if route_ans is not None and route_ans.choice == "stage_3_redraft":
            return FeedbackTriageDecision(
                needs_stage2_reharvest=False,
                rationale=(
                    f"Decisions API classified feedback as stage_3_redraft "
                    f"(confidence={route_ans.confidence:.2f})."
                ),
                additional_fact_queries=[],
            )

        decision = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
            response_model=FeedbackTriageDecision,
        )
        if route_ans is not None and route_ans.choice == "stage_2_reharvest":
            decision.needs_stage2_reharvest = True
        return decision

    def apply_comments_and_recompile(
        self,
        bundle: CompiledBundle,
        new_comments: Optional[List[ReviewComment]] = None,
        smooth_transitions: bool = True,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> CompiledBundle:
        """Applies queued inline review comments and surgically regenerates affected sections.

        Args:
            bundle: Existing `CompiledBundle` containing nodes and optional `stage_artifacts`.
            new_comments: Optional newly submitted `ReviewComment` objects to append before running.
            smooth_transitions: Whether to run the Stage 4 editorial stitcher pass.
            progress_callback: Optional `(stage, message)` progress callback.

        Returns:
            Updated `CompiledBundle` with affected sections regenerated and comments marked resolved.
        """
        all_comments = list(bundle.comments)
        existing_ids = {c.comment_id for c in all_comments}
        for c in new_comments or []:
            if c.comment_id not in existing_ids:
                all_comments.append(c)

        pending = [c for c in all_comments if not c.resolved]
        if not pending:
            return bundle

        plan, ledgers, sections_map = self._rehydrate_stage_artifacts(bundle)
        matter_id = bundle.matter_id or bundle.bundle_id or "default"

        doc_comments: List[ReviewComment] = []
        comments_by_section: Dict[str, List[ReviewComment]] = {}
        for c in pending:
            if c.scope == "document" or c.section_id == "__document__":
                doc_comments.append(c)
            else:
                comments_by_section.setdefault(c.section_id, []).append(c)

        if doc_comments:
            for sec_plan in plan.sections:
                comments_by_section.setdefault(sec_plan.section_id, []).extend(doc_comments)

        plan_by_sec = {s.section_id: s for s in plan.sections}
        audits_map: Dict[str, Dict[str, Any]] = dict(
            (bundle.stage_artifacts or {}).get("audits", {})
        )

        for sec_id, sec_comments in comments_by_section.items():
            sec_plan = plan_by_sec.get(sec_id)
            prior_sec = sections_map.get(sec_id)
            if sec_plan is None or prior_sec is None:
                logger.warning("Skipping comments for unknown section_id='%s'", sec_id)
                continue

            self._emit_progress(
                progress_callback,
                "triage",
                f"Triaging {len(sec_comments)} comment(s) on '{sec_plan.section_title}'...",
            )
            triage = self._triage_section_feedback(sec_plan, prior_sec, sec_comments)
            ledger = ledgers.get(
                sec_id, VerifiedFactLedger(section_id=sec_id, verified_facts=[], unresolved_gaps=[])
            )

            if triage.needs_stage2_reharvest:
                self._emit_progress(
                    progress_callback,
                    "stage_2",
                    f"Re-harvesting project inputs for '{sec_plan.section_title}'...",
                )
                extra_queries = triage.additional_fact_queries or [
                    c.comment_text for c in sec_comments
                ]
                new_ledger = self.run_stage2_harvester(
                    matter_id, sec_plan, extra_queries=extra_queries
                )
                existing_keys = {
                    (f.title, f.locator.locator_key, f.locator.cell_range)
                    for f in ledger.verified_facts
                }
                for fact in new_ledger.verified_facts:
                    key = (fact.title, fact.locator.locator_key, fact.locator.cell_range)
                    if key not in existing_keys:
                        ledger.verified_facts.append(fact)
                        existing_keys.add(key)
                ledger.unresolved_gaps.extend(new_ledger.unresolved_gaps)
                ledgers[sec_id] = ledger

            self._emit_progress(
                progress_callback,
                "stage_3_4",
                f"Regenerating and auditing '{sec_plan.section_title}'...",
            )
            updated_sec, audit_res = self._draft_and_audit_section(
                matter_id=matter_id,
                section_plan=sec_plan,
                ledger=ledger,
                prior_draft=prior_sec,
                review_comments=sec_comments,
            )
            audits_map[sec_id] = audit_res.model_dump()

            # Deterministically honor explicit human status overrides anchored to claims
            for c in sec_comments:
                if c.suggested_status:
                    m = re.match(rf"^claim_{re.escape(sec_id)}_(\d+)$", c.node_id)
                    if m:
                        target_n = int(m.group(1))
                        for grp in updated_sec.supports:
                            if grp.n == target_n:
                                grp.audit = NodeAudit(
                                    status=c.suggested_status,
                                    score=0.80 if c.suggested_status != "verified" else 1.0,
                                    evaluator_type="human",
                                    evaluator_note=f"Human reviewer feedback: {c.comment_text}",
                                )

            sections_map[sec_id] = updated_sec

        ordered_sections = [
            sections_map[s.section_id] for s in plan.sections if s.section_id in sections_map
        ]
        tensions = self.run_stage4_cross_section_tensions(ordered_sections)
        smoothed_map = (
            self.run_stage4_stitcher(ordered_sections) if smooth_transitions else None
        )

        builder = CompiledGraphBuilder(
            document_title=bundle.artifact.title,
            summary=bundle.artifact.summary,
            metadata=bundle.artifact.metadata,
        )
        recompiled = builder.compile_sections(
            sections=ordered_sections,
            smoothed_sections=smoothed_map,
            tensions=tensions,
        )

        # Mark addressed comments resolved and retain full review history
        addressed_sec_ids = set(comments_by_section.keys())
        for c in all_comments:
            if not c.resolved and (
                c.section_id in addressed_sec_ids
                or c.scope == "document"
                or c.section_id == "__document__"
            ):
                c.resolved = True

        recompiled.bundle_id = bundle.bundle_id
        recompiled.matter_id = bundle.matter_id
        recompiled.question = bundle.question
        recompiled.comments = all_comments
        recompiled.stage_artifacts = {
            "outline_plan": plan.model_dump(),
            "ledgers": {k: v.model_dump() for k, v in ledgers.items()},
            "sections": [s.model_dump() for s in ordered_sections],
            "audits": audits_map,
        }
        self.save_bundle(recompiled)
        self._emit_progress(progress_callback, "completed", "Batch feedback applied and DAG recompiled.")
        return recompiled
