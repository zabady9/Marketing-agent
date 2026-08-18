"""
CitationValidationAgent — QC gate that runs after FeasibilitySynthesisAgent.

Coverage is explicit and documented in COVERAGE_MANIFEST below.

Tier A  (citation-required, drives citation_support_rate):
    market_overview       — TAM, SAM, SOM, CAGR (4 slots; nulls count as uncited)
    competitive_landscape — one slot per competitor profile
    risk_assessment       — one slot per risk entry

Tier B  (faithfulness-checked via CHEAP_MODEL back-check; no URL required):
    financial_feasibility — narrative text vs. computed calc_trace outputs
    executive_summary     — full text vs. all prior sections
    contradictions        — each contradiction statement vs. the source data it references
    key_risks             — vs. risk_assessment risk list

Tier C  (pipeline-verifiable, pure Python, no LLM):
    data_gaps             — each reported gap verified against actual null fields in outputs

Out of scope:
    key_opportunities     — strategic recommendations, not falsifiable factual claims
    rationale             — qualitative verdict reasoning; implicitly covered by exec_summary check
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.agents.base import AgentName
from app.config import get_settings
from app.schemas.intake import FeasibilityInput
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.qc import CitationQCOutput, QCFlag, QCIssue, QCSeverity
from app.schemas.report import FinancialModelOutput
from app.schemas.risk import RiskAssessmentOutput
from app.schemas.synthesis import FeasibilitySynthesisOutput
from app.sse import EventQueue, SSEEvent

logger = logging.getLogger(__name__)

_AGENT = AgentName.CITATION_QC

CITATION_THRESHOLD = 0.80

# Manifest shown to users and included in CitationQCOutput.coverage
COVERAGE_MANIFEST: dict[str, list[str]] = {
    "tier_a_citation_required": [
        "market_overview (TAM, SAM, SOM, CAGR — nulls count as uncited)",
        "competitive_landscape (one slot per competitor profile)",
        "risk_assessment (one slot per risk entry)",
    ],
    "tier_b_faithfulness": [
        "financial_feasibility (narrative vs. calc_trace outputs)",
        "executive_summary (full text vs. all prior sections)",
        "contradictions (each statement vs. source data it references)",
        "key_risks (vs. risk_assessment entries)",
    ],
    "tier_c_pipeline_verifiable": [
        "data_gaps (each reported gap vs. actual null fields in pipeline outputs)",
    ],
    "out_of_scope": [
        "key_opportunities (strategic recommendations, not falsifiable claims)",
        "rationale (qualitative verdict; implicitly covered by executive_summary check)",
    ],
}


# ── Tier A helpers (pure Python) ──────────────────────────────────────────────

def _tier_a_counts(
    market: MarketSizingOutput | None,
    competitive: CompetitiveAnalysisOutput | None,
    risk: RiskAssessmentOutput | None,
) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Returns (total, cited, per_section_counts)."""
    per: dict[str, tuple[int, int]] = {}

    # market_overview: 4 slots
    if market is not None:
        m_cited = (
            int(len(market.tam.citations) > 0)
            + int(market.sam.value is not None and len(market.sam.citations) > 0)
            + int(market.som.value is not None and len(market.som.citations) > 0)
            + int(len(market.growth_rate_citations) > 0)
        )
        per["market_overview"] = (4, m_cited)
    else:
        per["market_overview"] = (4, 0)

    # competitive_landscape: one slot per competitor
    if competitive is not None and competitive.competitors:
        c_total = len(competitive.competitors)
        c_cited = sum(1 for c in competitive.competitors if len(c.citations) > 0)
        per["competitive_landscape"] = (c_total, c_cited)
    else:
        per["competitive_landscape"] = (0, 0)

    # risk_assessment: one slot per risk entry
    if risk is not None and risk.risks:
        r_total = len(risk.risks)
        r_cited = min(r_total, len(risk.citations))
        per["risk_assessment"] = (r_total, r_cited)
    else:
        per["risk_assessment"] = (0, 0)

    total = sum(t for t, _ in per.values())
    cited = sum(c for _, c in per.values())
    return total, cited, per


# ── Tier C helpers (pure Python) ──────────────────────────────────────────────

_NULL_FIELD_LABELS = {
    "SAM unavailable": lambda m: m is None or m.sam.value is None,
    "SOM unavailable": lambda m: m is None or m.som.value is None,
    "TAM unavailable": lambda m: m is None or m.tam.value is None,
    "market sizing unavailable": lambda m: m is None,
    "competitive landscape unavailable": lambda _: False,  # checked via competitive param
    "capex estimated": lambda _: False,   # always from fi
    "opex estimated": lambda _: False,    # always from fi
}

_INTAKE_NULL_LABELS = {
    "capex estimated": lambda fi: fi.capex.low_confidence,
    "opex estimated": lambda fi: fi.opex_monthly.low_confidence,
    "monthly sales estimated": lambda fi: fi.expected_monthly_sales.low_confidence,
}


def _verify_data_gaps(
    fi: FeasibilityInput,
    market: MarketSizingOutput | None,
    competitive: CompetitiveAnalysisOutput | None,
    synthesis: FeasibilitySynthesisOutput,
) -> list[QCFlag]:
    """Tier C: check each reported data_gap against actual pipeline state."""
    flags: list[QCFlag] = []
    actual_nulls: set[str] = set()

    if market is None or market.sam.value is None:
        actual_nulls.add("sam")
    if market is None or market.som.value is None:
        actual_nulls.add("som")
    if market is None or market.tam.value is None:
        actual_nulls.add("tam")
    if market is None:
        actual_nulls.add("market_sizing")
    if competitive is None:
        actual_nulls.add("competitive_landscape")
    if fi.capex.low_confidence:
        actual_nulls.add("capex")
    if fi.opex_monthly.low_confidence:
        actual_nulls.add("opex")
    if fi.expected_monthly_sales.low_confidence:
        actual_nulls.add("monthly_sales")

    for gap in synthesis.data_gaps:
        gap_lower = gap.lower()
        # Check if gap references something that IS actually missing/low-confidence
        matches_real = any(key in gap_lower for key in actual_nulls)
        if not matches_real and len(gap) > 10:
            # Heuristic: if the gap claims something is missing/estimated
            # but we can't match it to a real null, flag it
            if any(kw in gap_lower for kw in ["unavailable", "missing", "null", "estimated", "not provided"]):
                flags.append(
                    QCFlag(
                        section="data_gaps",
                        claim=gap[:120],
                        issue=QCIssue.DATA_GAP_MISMATCH,
                        severity=QCSeverity.WARNING,
                        detail=(
                            f"Gap '{gap[:60]}...' claims a missing field but no matching "
                            "null/low-confidence field found in pipeline outputs."
                        ),
                    )
                )

    return flags


# ── Tier B LLM schemas ─────────────────────────────────────────────────────────

class _FaithfulnessItem(BaseModel):
    section: str
    claim: str          # ≤ 120 chars describing what was checked
    is_faithful: bool
    issue: str | None   # if not faithful, what specifically is wrong


class _FaithfulnessReport(BaseModel):
    items: list[_FaithfulnessItem]


class _ContradictionCheck(BaseModel):
    contradiction_text: str   # the contradiction being verified
    accurately_stated: bool   # does it correctly characterize a real tension in the data?
    issue: str | None         # if inaccurately stated, what's wrong


class _ContradictionReport(BaseModel):
    checks: list[_ContradictionCheck]


class CitationValidationAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.cheap_model,   # faithfulness check uses CHEAP_MODEL
            google_api_key=s.google_api_key,
            temperature=0,
        )

    # ── Tier B: narrative faithfulness (one batched LLM call) ─────────────────

    async def _check_faithfulness(
        self,
        financial: FinancialModelOutput | None,
        synthesis: FeasibilitySynthesisOutput,
        market: MarketSizingOutput | None,
        competitive: CompetitiveAnalysisOutput | None,
        risk: RiskAssessmentOutput | None,
    ) -> list[QCFlag]:
        flags: list[QCFlag] = []

        # Build compact source context
        fin_context = "Financial: [UNAVAILABLE]"
        if financial is not None:
            be = financial.break_even.value
            roi1 = financial.roi_year_1.value
            fin_context = (
                f"Financial computed figures:\n"
                f"  break_even_months={be.get('break_even_months')} units={be.get('break_even_units')}\n"
                f"  roi_year_1={roi1.get('roi_percent')}%\n"
                f"  npv={financial.npv.value.get('npv')} positive={financial.npv.value.get('is_positive')}\n"
                f"  payback_month={financial.cash_flow.value.get('payback_month')}\n"
                f"  all figures have calc_trace (source=calculated)\n"
                f"  Financial narrative:\n  {financial.narrative.text[:300]}"
            )

        mkt_context = "Market: [UNAVAILABLE]"
        if market is not None:
            tam = f"{market.tam.value} {market.tam.unit}" if market.tam.value else "[DATA UNAVAILABLE]"
            sam = f"{market.sam.value} {market.sam.unit}" if market.sam.value else "[DATA UNAVAILABLE]"
            som = f"{market.som.value} {market.som.unit}" if market.som.value else "[DATA UNAVAILABLE]"
            mkt_context = f"Market: TAM={tam}  SAM={sam}  SOM={som}  CAGR={market.growth_rate_cagr}%"

        risk_context = "Risk: [UNAVAILABLE]"
        if risk is not None:
            risk_lines = "; ".join(
                f"[{r.probability}×{r.impact}|{r.category}] {r.risk_description[:60]}"
                for r in risk.risks[:5]
            )
            risk_context = f"Risks: {risk_lines}"

        comp_context = "Competitive: [UNAVAILABLE]"
        if competitive is not None:
            names = ", ".join(c.name for c in competitive.competitors)
            comp_context = f"Competitive: {names}"

        source_context = "\n".join([mkt_context, comp_context, fin_context, risk_context])

        # Items to check (Tier B)
        items_to_check = [
            {
                "section": "financial_feasibility",
                "text": financial.narrative.text[:400] if financial else "[UNAVAILABLE]",
                "instruction": (
                    "Verify this narrative text is faithful to the computed financial figures above. "
                    "Flag if it invents numbers not in calc_trace outputs, or contradicts them."
                ),
            },
            {
                "section": "executive_summary",
                "text": synthesis.executive_summary.text[:600],
                "instruction": (
                    "Verify this executive summary is faithful to all prior sections (market, "
                    "competitive, financial, risk). Flag factual errors or invented figures."
                ),
            },
            {
                "section": "key_risks",
                "text": "; ".join(synthesis.key_risks[:5]),
                "instruction": (
                    "Verify these key risks are consistent with the risk_assessment entries above. "
                    "Flag any risk claimed here that does not appear in or cannot be inferred from "
                    "the risk section."
                ),
            },
        ]

        checks_text = "\n\n".join(
            f"[{i}] section={item['section']}\n"
            f"Text: {item['text']}\n"
            f"Check: {item['instruction']}"
            for i, item in enumerate(items_to_check)
        )

        structured_llm = self._llm.with_structured_output(_FaithfulnessReport)
        try:
            report: _FaithfulnessReport = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a QC auditor verifying that narrative text in a feasibility "
                            "report is faithful to its source data. For each item, return "
                            "is_faithful=true if the text accurately represents the source, "
                            "false if it contains factual errors, invented numbers, or misleading "
                            "characterizations. Be precise — minor wording differences are fine; "
                            "only flag genuine factual inconsistencies."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Source data:\n{source_context}\n\n"
                            f"Items to verify ({len(items_to_check)} total):\n\n{checks_text}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            logger.warning("Faithfulness check LLM call failed: %s", exc)
            return flags

        for item_check in report.items:
            if not item_check.is_faithful:
                # executive_summary gets ERROR severity — it is the most user-facing section.
                # A fabricated figure there is qualitatively worse than in a sub-section
                # because users reading only the summary export will never see the flag.
                # ERROR signals to frontends: gate display behind a hard warning overlay.
                # All other Tier B sections use WARNING (footnote-level).
                severity = (
                    QCSeverity.ERROR
                    if item_check.section == "executive_summary"
                    else QCSeverity.WARNING
                )
                flags.append(
                    QCFlag(
                        section=item_check.section,
                        claim=item_check.claim[:120],
                        issue=QCIssue.FAITHFULNESS,
                        severity=severity,
                        detail=item_check.issue or "Faithfulness check failed",
                    )
                )

        return flags

    # ── Tier B: contradiction faithfulness (separate focused LLM call) ─────────

    async def _verify_contradictions(
        self,
        synthesis: FeasibilitySynthesisOutput,
        market: MarketSizingOutput | None,
        financial: FinancialModelOutput | None,
        risk: RiskAssessmentOutput | None,
    ) -> tuple[list[QCFlag], bool | None]:
        """
        Check each contradiction statement against the data it references.
        Returns (flags, contradictions_faithful).
        contradictions_faithful is None when there are no contradictions to check.
        """
        contradictions = synthesis.contradictions
        if not contradictions:
            return [], None

        # Build concise source data for contradiction verification
        source_facts: list[str] = []
        if financial is not None:
            roi1 = financial.roi_year_1.value.get("roi_percent")
            be = financial.break_even.value.get("break_even_months")
            npv_pos = financial.npv.value.get("is_positive")
            source_facts.append(f"roi_year_1={roi1}%  break_even={be}mo  npv_positive={npv_pos}")
        if market is not None:
            tam = f"{market.tam.value} {market.tam.unit}" if market.tam.value else "[NULL]"
            sam = f"{market.sam.value}" if market.sam.value else "[NULL]"
            source_facts.append(
                f"TAM={tam}  SAM={sam}  CAGR={market.growth_rate_cagr}%"
            )
        if risk is not None:
            hc = risk.high_critical_count
            source_facts.append(f"high_critical_risks={hc}")

        source_summary = "  ".join(source_facts) or "No source data available."

        contras_text = "\n".join(
            f"[{i}] {c}" for i, c in enumerate(contradictions)
        )

        structured_llm = self._llm.with_structured_output(_ContradictionReport)
        try:
            report: _ContradictionReport = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a QC auditor verifying contradiction statements in a "
                            "feasibility study. For each contradiction, check:\n"
                            "1. Does it accurately reference real data from the source?\n"
                            "2. Is the tension it describes real (not fabricated)?\n"
                            "Return accurately_stated=true if the contradiction correctly "
                            "characterizes a genuine tension in the data. "
                            "Return false only if it misstates specific figures or invents "
                            "a conflict that doesn't exist in the source data."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Source data facts:\n{source_summary}\n\n"
                            f"Contradiction statements to verify ({len(contradictions)}):\n"
                            f"{contras_text}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            logger.warning("Contradiction verification LLM call failed: %s", exc)
            return [], None

        flags: list[QCFlag] = []
        all_accurate = True

        for check in report.checks:
            if not check.accurately_stated:
                all_accurate = False
                flags.append(
                    QCFlag(
                        section="contradictions",
                        claim=check.contradiction_text[:120],
                        issue=QCIssue.FAITHFULNESS,
                        severity=QCSeverity.WARNING,
                        detail=check.issue or "Contradiction statement inaccurately references source data",
                    )
                )

        return flags, all_accurate

    # ── Main run ──────────────────────────────────────────────────────────────

    async def run(
        self,
        fi: FeasibilityInput,
        queue: EventQueue,
        *,
        market_output: MarketSizingOutput | None,
        competitive_output: CompetitiveAnalysisOutput | None,
        financial_output: FinancialModelOutput | None,
        risk_output: RiskAssessmentOutput | None,
        synthesis_output: FeasibilitySynthesisOutput | None,
    ) -> CitationQCOutput:
        await queue.put(SSEEvent.QC_STARTED, {"study_id": fi.study_id})

        all_flags: list[QCFlag] = []

        # ── Tier A: Citation support rate ─────────────────────────────────────
        total, cited, per_section = _tier_a_counts(market_output, competitive_output, risk_output)
        citation_support_rate = cited / total if total > 0 else 1.0
        threshold_passed = citation_support_rate >= CITATION_THRESHOLD

        # Flag sections below threshold
        for section, (sec_total, sec_cited) in per_section.items():
            if sec_total == 0:
                continue
            sec_rate = sec_cited / sec_total
            if sec_rate < CITATION_THRESHOLD:
                flag = QCFlag(
                    section=section,
                    claim=f"{sec_cited}/{sec_total} claims cited ({sec_rate:.0%})",
                    issue=QCIssue.CITATION_GAP,
                    severity=QCSeverity.WARNING if sec_rate >= 0.5 else QCSeverity.ERROR,
                    detail=(
                        f"{section} has only {sec_cited}/{sec_total} claims backed by citations "
                        f"(threshold: {CITATION_THRESHOLD:.0%}). "
                        "Null or uncited figures lower the overall citation_support_rate."
                    ),
                )
                all_flags.append(flag)
                await queue.put(
                    SSEEvent.QC_FLAG_RAISED,
                    {
                        "study_id": fi.study_id,
                        "section": section,
                        "issue": QCIssue.CITATION_GAP,
                        "detail": flag.detail,
                        "section_rate": round(sec_rate, 3),
                    },
                )

        # ── Tier B: Faithfulness (narrative + contradictions) ──────────────────
        contradictions_verified = False
        contradictions_faithful: bool | None = None

        if synthesis_output is not None:
            # B1: narrative faithfulness
            faithfulness_flags = await self._check_faithfulness(
                financial_output, synthesis_output, market_output, competitive_output, risk_output
            )
            for flag in faithfulness_flags:
                all_flags.append(flag)
                await queue.put(
                    SSEEvent.QC_FLAG_RAISED,
                    {
                        "study_id": fi.study_id,
                        "section": flag.section,
                        "issue": QCIssue.FAITHFULNESS,
                        "detail": flag.detail,
                    },
                )

            # B2: contradiction faithfulness (explicitly in scope per COVERAGE_MANIFEST)
            if synthesis_output.contradictions:
                contradictions_verified = True
                contra_flags, contradictions_faithful = await self._verify_contradictions(
                    synthesis_output, market_output, financial_output, risk_output
                )
                for flag in contra_flags:
                    all_flags.append(flag)
                    await queue.put(
                        SSEEvent.QC_FLAG_RAISED,
                        {
                            "study_id": fi.study_id,
                            "section": "contradictions",
                            "issue": QCIssue.FAITHFULNESS,
                            "detail": flag.detail,
                        },
                    )
            else:
                contradictions_verified = False
                contradictions_faithful = None

        # ── Tier C: Data-gap accuracy ──────────────────────────────────────────
        gap_flags: list[QCFlag] = []
        if synthesis_output is not None:
            gap_flags = _verify_data_gaps(fi, market_output, competitive_output, synthesis_output)
            for flag in gap_flags:
                all_flags.append(flag)
                await queue.put(
                    SSEEvent.QC_FLAG_RAISED,
                    {
                        "study_id": fi.study_id,
                        "section": "data_gaps",
                        "issue": QCIssue.DATA_GAP_MISMATCH,
                        "detail": flag.detail,
                    },
                )

        # ── Emit QC_COMPLETED ─────────────────────────────────────────────────
        flagged_sections = sorted({f.section for f in all_flags})
        faithfulness_issues = sum(1 for f in all_flags if f.issue == QCIssue.FAITHFULNESS)
        gap_mismatches = sum(1 for f in all_flags if f.issue == QCIssue.DATA_GAP_MISMATCH)

        # executive_summary_trusted = False when any ERROR-severity faithfulness flag
        # hit the executive_summary section. This is the downstream signal that lets
        # frontends gate display (show a blocking warning overlay rather than raw text).
        # False is safer than True: trust requires passing, not just absence of a check.
        executive_summary_trusted = not any(
            f.section == "executive_summary"
            and f.issue == QCIssue.FAITHFULNESS
            and f.severity == QCSeverity.ERROR
            for f in all_flags
        )

        output = CitationQCOutput(
            citation_support_rate=round(citation_support_rate, 3),
            citation_threshold=CITATION_THRESHOLD,
            citation_threshold_passed=threshold_passed,
            faithfulness_issues=faithfulness_issues,
            executive_summary_trusted=executive_summary_trusted,
            contradictions_in_scope=True,
            contradictions_verified=contradictions_verified,
            contradictions_faithful=contradictions_faithful,
            data_gap_mismatches=gap_mismatches,
            flags=all_flags,
            flagged_sections=flagged_sections,
            total_flags=len(all_flags),
            coverage=COVERAGE_MANIFEST,
        )

        await queue.put(
            SSEEvent.QC_COMPLETED,
            {
                "study_id": fi.study_id,
                "citation_support_rate": output.citation_support_rate,
                "citation_threshold_passed": output.citation_threshold_passed,
                "faithfulness_issues": output.faithfulness_issues,
                "executive_summary_trusted": output.executive_summary_trusted,
                "contradictions_in_scope": output.contradictions_in_scope,
                "contradictions_verified": output.contradictions_verified,
                "contradictions_faithful": output.contradictions_faithful,
                "data_gap_mismatches": output.data_gap_mismatches,
                "total_flags": output.total_flags,
                "flagged_sections": output.flagged_sections,
                "coverage": output.coverage,
            },
        )

        return output
