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
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.ingest import CanonicalRouter, MatterIngestor
from app.llm import LLMProvider
from app.models import (
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
        """Decomposes user request `(c)` into sections mapped to canonical rules `(b)`.

        Hydrates exact `verbatim_quote` and `url` fields from `CanonicalRouter` so
        downstream drafting always receives unmodified canonical authority text.

        Args:
            matter_id: Target project/matter identifier.
            question: User analytical or legal question `(c)`.

        Returns:
            Validated `OutlinePlan` with hydrated canonical authorities.
        """
        index_md = self.canonical_router.get_index_markdown()
        auth_context = self.canonical_router.get_authorities_context()
        matter_info = next(
            (m for m in self.matter_ingestor.list_matters() if m["matter_id"] == matter_id),
            {"matter_id": matter_id, "raw_files": []},
        )

        system_instruction = (
            "You are the Lead Analytical Architect. Decompose the user's question into "
            "ordered, non-overlapping sections. Map each section to relevant [AUTH:...] "
            "authorities from the Canonical Knowledge Corpus (b) and specify concrete "
            "factual queries that must be verified against the project files (a)."
        )
        prompt = (
            f"### User Request (c)\n{question}\n\n"
            f"### Available Project Files (a) in matter '{matter_id}'\n"
            f"{json.dumps(matter_info.get('raw_files', []), indent=2)}\n\n"
            f"### Canonical Knowledge Index (b)\n{index_md}\n\n"
            f"### Canonical Authority Entries\n{auth_context}\n\n"
            "Emit an OutlinePlan JSON covering every part of the user's question."
        )
        plan = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
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
        """Runs a tool-assisted fact extraction loop over indexed project inputs `(a)`.

        Args:
            matter_id: Project identifier whose `inputs/indexed/` should be searched.
            section_plan: Stage 1 plan defining `stated_intention` and `required_fact_queries`.
            extra_queries: Optional additional queries generated from human review feedback.

        Returns:
            `VerifiedFactLedger` containing coordinate-stamped facts and unresolved gaps.
        """
        # Ensure deterministic ingestion has run before harvesting
        _, _, indexed_dir, _ = self.matter_ingestor._matter_dirs(matter_id)
        if not (indexed_dir / "manifest.json").exists():
            self.matter_ingestor.ingest_matter(matter_id)

        tools = self.matter_ingestor.build_stage2_tools(matter_id)
        queries = list(section_plan.required_fact_queries)
        if extra_queries:
            queries.extend(q for q in extra_queries if q not in queries)

        system_instruction = (
            "You are a Forensic Fact Extractor. Use the provided search and spreadsheet "
            "tools to gather exact evidence from the coordinate-indexed project inputs (a). "
            "You MUST copy the exact `locator` dictionary and verbatim `quote` (or `raw_value` "
            "and `formula`) returned by the tools. Never invent page numbers, bounding boxes, "
            "or cell coordinates. Record any unanswerable queries in `unresolved_gaps`."
        )
        prompt = (
            f"Section ID: {section_plan.section_id}\n"
            f"Section Title: {section_plan.section_title}\n"
            f"Stated Intention: {section_plan.stated_intention}\n\n"
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
        return ledger

    # ------------------------------------------------------------------
    # Stage 3: Constrained Tier-1 Section Drafting (with validator retries)
    # ------------------------------------------------------------------

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

        Automatically retries if `SectionValidator.validate_section` detects
        orphaned `<ref n="...">` tags, unused supports, or broken `<ref n="10X">`
        sub-references.

        Args:
            section_plan: Stage 1 plan for this section.
            ledger: Harvested coordinate-stamped facts and gaps from `(a)`.
            prior_draft: Optional previous draft when regenerating from feedback.
            review_comments: Optional human review comments targeting this section.
            audit_critique: Optional critique from Stage 4's 3-Point Auditor.
            max_validation_retries: Maximum retries for structural tag parity errors.

        Returns:
            Validated Tier-1 `SectionOutput`.
        """
        system_instruction = (
            "You are an expert legal and analytical author. Follow the Closed-World Evidence "
            "Constraint: cite ONLY facts, quotes, formulas, and `locator` objects from the "
            "VerifiedFactLedger (for L1 evidence/calculations) and Governing Authorities (for L2+ "
            "authorities inside reasoning `sub_supports`). Wrap every substantive empirical or "
            "legal claim in `<ref n='1'>clause text</ref>` using sequential integers 1, 2, 3... "
            "Every `<ref n='X'>` in `text` MUST have a matching SupportGroup `n=X` in `supports`. "
            "Any `<ref n='10X'>` inside a reasoning/calculation `body` MUST have a matching "
            "SubSupportItem `n=10X` in `sub_supports`."
        )

        feedback_block = ""
        if prior_draft is not None and review_comments:
            formatted_comments = "\n".join(
                f"- [Target Node: {c.node_id}"
                + (f" | Requested Status: {c.suggested_status}" if c.suggested_status else "")
                + f"]: {c.comment_text}"
                for c in review_comments
            )
            feedback_block = (
                f"\n\n### Prior Section Draft\n{prior_draft.model_dump_json(indent=2)}\n\n"
                f"### Human Reviewer Feedback (MUST ADDRESS)\n{formatted_comments}\n"
                "Revise the section text, support reasoning, and audit flags to directly resolve "
                "all reviewer comments while keeping valid citations intact."
            )

        base_prompt = (
            f"Section ID: {section_plan.section_id}\n"
            f"Section Title: {section_plan.section_title}\n"
            f"Stated Intention: {section_plan.stated_intention}\n\n"
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

            is_valid, errors = SectionValidator.validate_section(draft)
            if is_valid:
                return draft

            last_errors = errors
            logger.warning(
                "Section '%s' failed SectionValidator (attempt %d): %s",
                section_plan.section_id,
                attempt + 1,
                errors,
            )
            prompt = (
                f"{base_prompt}\n\n"
                f"### Structural Validation Errors to Fix\n"
                + "\n".join(f"- {e}" for e in errors)
            )

        raise ValueError(
            f"Section '{section_plan.section_id}' failed SectionValidator after "
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
            "(a) check_a_relevance: every support item directly backs its `<ref n>` clause; "
            "(b) check_b_congruence: surrounding source context strictly entails each claim "
            "without cherry-picking or dropping disqualifying exceptions; "
            "(c) check_c_intent: the section answers its stated_intention. "
            "Return passed=False with `critique_for_retry` if any factual distortion exists."
        )
        prompt = (
            f"Stated Intention: {section_plan.stated_intention}\n\n"
            f"Drafted SectionOutput:\n{draft.model_dump_json(indent=2)}\n\n"
            f"Expanded Source Context (a):\n{expanded_context or '(No external block context)'}\n\n"
            f"Canonical Authorities (b):\n{auth_context}"
        )
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
    ) -> SectionOutput:
        """Runs Stage 3 + Stage 4 Section Auditor with up to 2 congruence retries."""
        critique: Optional[str] = None
        draft: Optional[SectionOutput] = None

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
                return draft

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

        assert draft is not None
        return draft

    def run_stage4_cross_section_tensions(
        self, sections: List[SectionOutput]
    ) -> List[TensionObject]:
        """Detects logical or quantitative contradictions across compiled sections."""
        if len(sections) < 2:
            return []

        claim_summaries = []
        tag_re = re.compile(r"<ref\s+n=['\"](\d+)['\"]>(.*?)</ref>", re.DOTALL)
        for sec in sections:
            for n_str, clause in tag_re.findall(sec.text):
                claim_summaries.append(
                    {
                        "claim_id": f"claim_{sec.section_id}_{n_str}",
                        "section_id": sec.section_id,
                        "clause": clause.strip(),
                    }
                )

        system_instruction = (
            "You are a Cross-Section Consistency Auditor. Inspect all claims across sections "
            "and flag only genuine numerical discrepancies, scope conflicts, or logical tensions. "
            "Use exact `claim_id` strings in `involved_claim_ids`."
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
            section_out = self._draft_and_audit_section(matter_id, sec_plan, ledger)
            sections.append(section_out)

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
            f"- Node {c.node_id} (suggested_status={c.suggested_status}): {c.comment_text}"
            for c in comments
        )
        prompt = (
            f"Section: {section_plan.section_title}\n"
            f"Current Draft:\n{section_draft.model_dump_json(indent=2)}\n\n"
            f"Reviewer Comments:\n{formatted}"
        )
        return self.llm.generate_structured(
            prompt=prompt,
            system_instruction=system_instruction,
            response_model=FeedbackTriageDecision,
        )

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

        comments_by_section: Dict[str, List[ReviewComment]] = {}
        for c in pending:
            comments_by_section.setdefault(c.section_id, []).append(c)

        plan_by_sec = {s.section_id: s for s in plan.sections}

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
            updated_sec = self._draft_and_audit_section(
                matter_id=matter_id,
                section_plan=sec_plan,
                ledger=ledger,
                prior_draft=prior_sec,
                review_comments=sec_comments,
            )

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
            if not c.resolved and c.section_id in addressed_sec_ids:
                c.resolved = True

        recompiled.bundle_id = bundle.bundle_id
        recompiled.matter_id = bundle.matter_id
        recompiled.question = bundle.question
        recompiled.comments = all_comments
        recompiled.stage_artifacts = {
            "outline_plan": plan.model_dump(),
            "ledgers": {k: v.model_dump() for k, v in ledgers.items()},
            "sections": [s.model_dump() for s in ordered_sections],
        }
        self.save_bundle(recompiled)
        self._emit_progress(progress_callback, "completed", "Batch feedback applied and DAG recompiled.")
        return recompiled
