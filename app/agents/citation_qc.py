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

Tier D  (structural consistency, pure Python, no LLM):
    claim_type tags on TAM/SAM/SOM/CAGR, competitor profiles, and risk entries —
    verified_fact must carry a resolved citation; unavailable must carry no value.
    Catches internal inconsistency, not "is this the *right* category" — that
    remains a human-review question the per-claim methodology text supports.

Tier E  (citation relevance, CHEAP_MODEL back-check):
    Every verified_fact claim (TAM/SAM/SOM/CAGR, competitor profiles, risk
    entries) — does its resolved citation actually support THIS specific
    claim, not just resolve to *a* search result? A citation about a
    same-named but different company, or an off-topic result, fails this
    check. Failing items are downgraded in place: market figures ->
    value=null/unavailable (per the "no ungrounded number" HARD RULE already
    applied elsewhere in market_overview); competitors/risks -> opinion with
    citations cleared. The methodology field is overwritten to explain why.

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
from app.schemas.common import Citation, ClaimType
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
    "tier_d_classification_consistency": [
        "market_overview (TAM, SAM, SOM, CAGR claim_type vs. value/citations)",
        "competitive_landscape (each competitor's claim_type vs. citations)",
        "risk_assessment (each risk's claim_type vs. citations)",
    ],
    "tier_e_citation_relevance": [
        "market_overview (TAM, SAM, SOM, CAGR — citation vs. this specific figure)",
        "competitive_landscape (each verified_fact competitor — citation(s) vs. this specific profile)",
        "risk_assessment (each verified_fact risk — citation vs. this specific risk)",
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


# ── Tier D helpers (pure Python) ──────────────────────────────────────────────

def _check_claim_type(
    section: str, label: str, claim_type, has_value: bool, has_citation: bool,
) -> QCFlag | None:
    if claim_type == ClaimType.VERIFIED_FACT and not has_citation:
        return QCFlag(
            section=section,
            claim=label[:120],
            issue=QCIssue.CLASSIFICATION_MISMATCH,
            severity=QCSeverity.WARNING,
            detail=f"{label} is tagged verified_fact but carries no resolved citation.",
        )
    if claim_type == ClaimType.UNAVAILABLE and has_value:
        return QCFlag(
            section=section,
            claim=label[:120],
            issue=QCIssue.CLASSIFICATION_MISMATCH,
            severity=QCSeverity.WARNING,
            detail=f"{label} is tagged unavailable but a value is present.",
        )
    return None


def _verify_claim_types(
    market: MarketSizingOutput | None,
    competitive: CompetitiveAnalysisOutput | None,
    risk: RiskAssessmentOutput | None,
) -> list[QCFlag]:
    """Tier D: verify claim_type tags are internally consistent with the
    citations/value they describe. Does NOT verify the LLM chose the *right*
    category — only that verified_fact/unavailable aren't self-contradictory."""
    flags: list[QCFlag] = []

    if market is not None:
        checks = [
            ("TAM", market.tam.claim_type, market.tam.value is not None, bool(market.tam.citations)),
            ("SAM", market.sam.claim_type, market.sam.value is not None, bool(market.sam.citations)),
            ("SOM", market.som.claim_type, market.som.value is not None, bool(market.som.citations)),
            (
                "CAGR", market.growth_rate_claim_type,
                market.growth_rate_cagr is not None, bool(market.growth_rate_citations),
            ),
        ]
        for label, claim_type, has_value, has_citation in checks:
            flag = _check_claim_type("market_overview", label, claim_type, has_value, has_citation)
            if flag:
                flags.append(flag)

    if competitive is not None:
        for c in competitive.competitors:
            flag = _check_claim_type(
                "competitive_landscape", f"competitor:{c.name}", c.claim_type, True, bool(c.citations),
            )
            if flag:
                flags.append(flag)

    if risk is not None:
        for r in risk.risks:
            flag = _check_claim_type(
                "risk_assessment", f"risk:{r.risk_description[:40]}", r.claim_type, True, bool(r.citations),
            )
            if flag:
                flags.append(flag)

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


class _RelevanceItem(BaseModel):
    item_id: str          # matches the id the check was submitted under
    is_relevant: bool      # does the citation genuinely support THIS claim?
    issue: str | None      # if not relevant, one sentence on the mismatch


class _RelevanceReport(BaseModel):
    items: list[_RelevanceItem]


_UNGROUNDED_MARKET_METHODOLOGY = (
    "Value withdrawn — a citation-relevance check found the cited source does "
    "not actually support this figure."
)
_UNGROUNDED_ENTITY_METHODOLOGY = (
    "Downgraded to opinion — a citation-relevance check found the cited "
    "source does not actually describe this entry."
)


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

    # ── Tier E: citation relevance (batched cheap-model back-check) ────────────

    @staticmethod
    def _cite_text(citations: list[Citation]) -> str:
        return " | ".join(f"{c.title}: {c.snippet}" for c in citations) or "[no citation text]"

    async def _check_citation_relevance(
        self,
        market: MarketSizingOutput | None,
        competitive: CompetitiveAnalysisOutput | None,
        risk: RiskAssessmentOutput | None,
    ) -> list[QCFlag]:
        """For every verified_fact claim, ask whether its resolved citation(s)
        actually support THIS specific claim — not just resolve topically.
        Failing items are downgraded IN PLACE (mutates the output objects
        passed in) before to_sections_payload() is built downstream. The live
        SECTION_READY SSE event for that section already fired earlier in the
        pipeline and can't be retracted — same documented limitation as
        executive_summary_trusted below."""
        flags: list[QCFlag] = []
        items: list[dict] = []

        if market is not None:
            for key, label in [("tam", "TAM"), ("sam", "SAM"), ("som", "SOM")]:
                figure = getattr(market, key)
                if figure.claim_type == ClaimType.VERIFIED_FACT:
                    items.append({
                        "item_id": f"market:{key}",
                        "claim_text": f"{label} = {figure.value} {figure.unit}. Methodology: {figure.methodology}",
                        "citation_text": self._cite_text(figure.citations),
                    })
            if market.growth_rate_claim_type == ClaimType.VERIFIED_FACT:
                items.append({
                    "item_id": "market:cagr",
                    "claim_text": f"CAGR = {market.growth_rate_cagr}%. Methodology: {market.growth_rate_methodology}",
                    "citation_text": self._cite_text(market.growth_rate_citations),
                })

        if competitive is not None:
            for i, c in enumerate(competitive.competitors):
                if c.claim_type == ClaimType.VERIFIED_FACT:
                    items.append({
                        "item_id": f"competitor:{i}",
                        "claim_text": (
                            f"Competitor profile for '{c.name}': strengths={c.strengths}, "
                            f"weaknesses={c.weaknesses}. Methodology: {c.methodology}"
                        ),
                        "citation_text": self._cite_text(c.citations),
                    })

        if risk is not None:
            for i, r in enumerate(risk.risks):
                if r.claim_type == ClaimType.VERIFIED_FACT:
                    items.append({
                        "item_id": f"risk:{i}",
                        "claim_text": f"Risk: {r.risk_description}. Methodology: {r.methodology}",
                        "citation_text": self._cite_text(r.citations),
                    })

        if not items:
            return flags

        items_text = "\n\n".join(
            f"[{it['item_id']}]\nClaim: {it['claim_text']}\nCitation content: {it['citation_text']}"
            for it in items
        )

        structured_llm = self._llm.with_structured_output(_RelevanceReport)
        try:
            report: _RelevanceReport = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a skeptical QC auditor checking whether a citation "
                            "genuinely supports a specific claim in a feasibility report — "
                            "not just whether it's topically related to the same industry. "
                            "Default to is_relevant=false unless the citation content "
                            "clearly and specifically supports THIS claim about THIS named "
                            "entity.\n"
                            "The 'Methodology' text inside each claim was written by the "
                            "same model that selected the citation — if it admits a "
                            "mismatch (different company, different city/country, "
                            "different industry, hedges with words like 'not', 'while', "
                            "'however', 'despite', or otherwise concedes the citation is "
                            "about something else), you MUST return is_relevant=false and "
                            "quote the admission back in `issue`. Do not give the benefit "
                            "of the doubt merely because the citation is in the same "
                            "general industry — e.g. a citation about a same-named company "
                            "in a different country, or an unrelated company entirely, is "
                            "NOT relevant even if both are 'coffee' or 'tech' businesses.\n"
                            "Example — irrelevant: claim is about competitor 'Toucano' in "
                            "Cairo; methodology says 'result [4] places Tucano Coffee in "
                            "Turkey' -> is_relevant=false, issue='Cited source describes a "
                            "Turkey-based business, not the named Cairo competitor.'\n"
                            "Return exactly one item per item_id given."
                        )
                    ),
                    HumanMessage(content=f"Items to verify ({len(items)} total):\n\n{items_text}"),
                ]
            )
        except Exception as exc:
            logger.warning("Citation relevance check LLM call failed: %s", exc)
            return flags

        verdicts = {item.item_id: item for item in report.items}

        for it in items:
            verdict = verdicts.get(it["item_id"])
            if verdict is None or verdict.is_relevant:
                continue

            item_id = it["item_id"]
            detail = verdict.issue or "Citation does not support this specific claim."

            if item_id.startswith("market:"):
                key = item_id.split(":", 1)[1]
                if key == "cagr":
                    market.growth_rate_cagr = None
                    market.growth_rate_citations = []
                    market.growth_rate_claim_type = ClaimType.UNAVAILABLE
                    market.growth_rate_methodology = _UNGROUNDED_MARKET_METHODOLOGY
                else:
                    figure = getattr(market, key)
                    figure.value = None
                    figure.citations = []
                    figure.claim_type = ClaimType.UNAVAILABLE
                    figure.methodology = _UNGROUNDED_MARKET_METHODOLOGY
                section = "market_overview"
            elif item_id.startswith("competitor:"):
                c = competitive.competitors[int(item_id.split(":", 1)[1])]
                c.claim_type = ClaimType.OPINION
                c.citations = []
                c.methodology = _UNGROUNDED_ENTITY_METHODOLOGY
                section = "competitive_landscape"
            else:  # "risk:"
                r = risk.risks[int(item_id.split(":", 1)[1])]
                r.claim_type = ClaimType.OPINION
                r.citations = []
                r.methodology = _UNGROUNDED_ENTITY_METHODOLOGY
                section = "risk_assessment"

            flags.append(QCFlag(
                section=section,
                claim=it["claim_text"][:120],
                issue=QCIssue.CITATION_RELEVANCE,
                severity=QCSeverity.WARNING,
                detail=detail,
            ))

        return flags

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

        # ── Tier D: Claim-type structural consistency ──────────────────────────
        classification_flags = _verify_claim_types(market_output, competitive_output, risk_output)
        for flag in classification_flags:
            all_flags.append(flag)
            await queue.put(
                SSEEvent.QC_FLAG_RAISED,
                {
                    "study_id": fi.study_id,
                    "section": flag.section,
                    "issue": QCIssue.CLASSIFICATION_MISMATCH,
                    "detail": flag.detail,
                },
            )

        # ── Tier E: Citation relevance (mutates outputs in place on failure) ───
        relevance_flags = await self._check_citation_relevance(
            market_output, competitive_output, risk_output
        )
        for flag in relevance_flags:
            all_flags.append(flag)
            await queue.put(
                SSEEvent.QC_FLAG_RAISED,
                {
                    "study_id": fi.study_id,
                    "section": flag.section,
                    "issue": QCIssue.CITATION_RELEVANCE,
                    "detail": flag.detail,
                },
            )

        # ── Emit QC_COMPLETED ─────────────────────────────────────────────────
        flagged_sections = sorted({f.section for f in all_flags})
        faithfulness_issues = sum(1 for f in all_flags if f.issue == QCIssue.FAITHFULNESS)
        gap_mismatches = sum(1 for f in all_flags if f.issue == QCIssue.DATA_GAP_MISMATCH)
        classification_mismatches = sum(
            1 for f in all_flags if f.issue == QCIssue.CLASSIFICATION_MISMATCH
        )
        citation_relevance_issues = sum(
            1 for f in all_flags if f.issue == QCIssue.CITATION_RELEVANCE
        )

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
            classification_mismatches=classification_mismatches,
            citation_relevance_issues=citation_relevance_issues,
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
                "classification_mismatches": output.classification_mismatches,
                "citation_relevance_issues": output.citation_relevance_issues,
                "total_flags": output.total_flags,
                "flagged_sections": output.flagged_sections,
                "coverage": output.coverage,
            },
        )

        return output
