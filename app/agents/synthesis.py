from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.agents.base import AgentName, AgentSoftError
from app.config import get_settings
from app.schemas.intake import FeasibilityInput
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.report import FinancialModelOutput, LocalizedText
from app.schemas.risk import RiskAssessmentOutput
from app.schemas.synthesis import FeasibilitySynthesisOutput, Verdict
from app.sse import EventQueue, SSEEvent
from app.tools.confidence import ConfidenceInput, build_confidence_input, compute_confidence_score
from app.tools.language import ENGLISH_ONLY_TERMS_NOTE

logger = logging.getLogger(__name__)

_AGENT = AgentName.SYNTHESIS


# ── Internal LLM schema ────────────────────────────────────────────────────────

class _SynthesisLLMOutput(BaseModel):
    verdict: Literal["proceed", "proceed_with_caution", "do_not_proceed"]
    executive_summary: str      # full narrative in output_language
    key_opportunities: list[str]  # 3–5 items in output_language
    key_risks: list[str]          # 3–5 items in output_language
    data_gaps: list[str]          # null/missing fields explicitly listed
    contradictions: list[str]     # cross-section contradictions, or []
    rationale: str                # why this verdict, in output_language


# ── Context formatters ─────────────────────────────────────────────────────────

def _fmt_market_null(m: MarketSizingOutput | None) -> tuple[str, str, str]:
    """Returns (sam_str, som_str, market_block) for use in the synthesis prompt."""
    if m is None:
        return "[AGENT FAILED]", "[AGENT FAILED]", "Market Sizing: [AGENT FAILED — section unavailable]"
    sam = f"{m.sam.value} {m.sam.unit} [{m.sam.confidence}]" if m.sam.value is not None else "[DATA UNAVAILABLE]"
    som = f"{m.som.value} {m.som.unit} [{m.som.confidence}]" if m.som.value is not None else "[DATA UNAVAILABLE]"
    tam = f"{m.tam.value} {m.tam.unit} [{m.tam.confidence}]" if m.tam.value is not None else "[DATA UNAVAILABLE]"
    cagr = f"{m.growth_rate_cagr}%" if m.growth_rate_cagr is not None else "[DATA UNAVAILABLE]"
    block = (
        f"Market Sizing:\n"
        f"  TAM: {tam}\n"
        f"  SAM: {sam}\n"
        f"  SOM: {som}\n"
        f"  CAGR: {cagr}\n"
        f"  review_recommended: {m.review_recommended}"
    )
    return sam, som, block


def _fmt_competitive(c: CompetitiveAnalysisOutput | None) -> str:
    if c is None:
        return "Competitive Landscape: [AGENT FAILED — section unavailable]"
    comps = "; ".join(
        f"{x.name} [{x.source}, {x.market_position}]" for x in c.competitors
    )
    diffs = " / ".join(c.key_differentiators[:3])
    gaps = " / ".join(c.market_gaps[:3])
    return (
        f"Competitive Landscape:\n"
        f"  Competitors: {comps}\n"
        f"  Key differentiators vs. competitors: {diffs}\n"
        f"  Market gaps identified: {gaps}"
    )


def _fmt_financial(f: FinancialModelOutput | None) -> str:
    if f is None:
        return "Financial Modeling: [AGENT FAILED — section unavailable]"
    be = f.break_even.value
    roi1 = f.roi_year_1.value
    roin = f.roi_year_n.value
    npv = f.npv.value
    cf = f.cash_flow.value
    return (
        f"Financial Modeling:\n"
        f"  Unit price: {f.unit_price} {f.pricing_currency}\n"
        f"  Monthly sales: {f.expected_monthly_sales} (source: {f.expected_monthly_sales_source})\n"
        f"  Capex: {f.capex_value} {f.capex_currency} (source: {f.capex_source})\n"
        f"  Monthly opex: {f.opex_monthly_value} {f.opex_monthly_currency} (source: {f.opex_monthly_source})\n"
        f"  Break-even: {be.get('break_even_months')} months / {be.get('break_even_units')} units\n"
        f"  ROI year 1: {roi1.get('roi_percent')}%\n"
        f"  ROI year {f.analysis_horizon_years}: {roin.get('roi_percent')}%\n"
        f"  NPV: {npv.get('npv')} (positive={npv.get('is_positive')})\n"
        f"  Payback month: {cf.get('payback_month')}\n"
        f"  All figures have low input_confidence (estimated inputs used): {f.review_recommended}"
    )


def _fmt_risk(r: RiskAssessmentOutput | None) -> str:
    if r is None:
        return "Risk Assessment: [AGENT FAILED — section unavailable]"
    risk_lines = "\n  ".join(
        f"[{e.probability.upper()} prob × {e.impact.upper()} impact | {e.category}] {e.risk_description}"
        for e in r.risks
    )
    return (
        f"Risk Assessment ({len(r.risks)} risks, {r.high_critical_count} high×high):\n"
        f"  {risk_lines}"
    )


def _build_confidence_input(
    fi: FeasibilityInput,
    market: MarketSizingOutput | None,
    competitive: CompetitiveAnalysisOutput | None,
    financial: FinancialModelOutput | None,
    risk: RiskAssessmentOutput | None,
    fatal_failures: list[str],
) -> ConfidenceInput:
    """Convert live pipeline outputs into the ConfidenceInput struct."""
    # Market: 4 citeable slots (TAM, SAM, SOM, CAGR)
    if market is not None:
        market_tam_cited = len(market.tam.citations) > 0
        market_sam_null = market.sam.value is None
        market_som_null = market.som.value is None
        market_cagr_cited = len(market.growth_rate_citations) > 0
    else:
        market_tam_cited = False
        market_sam_null = True
        market_som_null = True
        market_cagr_cited = False

    # Competitive: 1 slot per competitor
    if competitive is not None:
        comp_total = len(competitive.competitors)
        comp_cited = sum(1 for c in competitive.competitors if len(c.citations) > 0)
    else:
        comp_total = 0
        comp_cited = 0

    # Financial: always 6 calc_traced figures → always cited
    financial_count = 6 if financial is not None else 0

    # Risk: 1 slot per risk entry, cited if any citation exists
    if risk is not None:
        risk_total = len(risk.risks)
        risk_cited = min(risk_total, len(risk.citations))
    else:
        risk_total = 0
        risk_cited = 0

    # Intake completeness: count FieldWithSource fields
    intake_fields = [
        fi.business_description,
        fi.target_market_description,
        fi.target_market_geography,
        fi.business_model_type,
        fi.capex,
        fi.opex_monthly,
        fi.pricing_unit_price,
        fi.expected_monthly_sales,
    ]
    total_intake = len(intake_fields)
    user_provided = sum(1 for f in intake_fields if not f.low_confidence)

    return build_confidence_input(
        market_tam_cited=market_tam_cited,
        market_sam_null=market_sam_null,
        market_som_null=market_som_null,
        market_cagr_cited=market_cagr_cited,
        competitive_cited_count=comp_cited,
        competitive_total_count=comp_total,
        financial_figure_count=financial_count,
        risk_cited_count=risk_cited,
        risk_total_count=risk_total,
        high_critical_risks=risk.high_critical_count if risk else 0,
        user_provided_intake_fields=user_provided,
        total_intake_fields=total_intake,
        fatal_agent_failures=fatal_failures,
    )


class FeasibilitySynthesisAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.reasoning_model,
            google_api_key=s.google_api_key,
            temperature=0,
        )

    async def run(
        self,
        fi: FeasibilityInput,
        queue: EventQueue,
        *,
        market_output: MarketSizingOutput | None,
        competitive_output: CompetitiveAnalysisOutput | None,
        financial_output: FinancialModelOutput | None,
        risk_output: RiskAssessmentOutput | None,
        fatal_agent_failures: list[str],
    ) -> FeasibilitySynthesisOutput:
        await queue.put(SSEEvent.AGENT_STARTED, {"agent": _AGENT, "study_id": fi.study_id})

        # ── 1. Deterministic confidence score (Python only, no LLM) ────────────
        conf_input = _build_confidence_input(
            fi, market_output, competitive_output, financial_output,
            risk_output, fatal_agent_failures,
        )
        conf_bd = compute_confidence_score(conf_input)

        # ── 2. Format null-aware context ───────────────────────────────────────
        sam_str, som_str, market_block = _fmt_market_null(market_output)
        competitive_block = _fmt_competitive(competitive_output)
        financial_block = _fmt_financial(financial_output)
        risk_block = _fmt_risk(risk_output)

        null_guard = (
            "=== CRITICAL DATA HANDLING RULES ===\n"
            "\n"
            f"1. NULL MARKET FIGURES — SAM = {sam_str}  /  SOM = {som_str}\n"
            "   — If either value above is \"[DATA UNAVAILABLE]\", write that exact string\n"
            "     in your executive_summary where you discuss serviceable market size.\n"
            "   — NEVER substitute a number. NEVER treat null as zero.\n"
            "   — Add \"SAM unavailable\" and/or \"SOM unavailable\" to data_gaps.\n"
            "   — A null SAM or SOM is a data gap, not a zero market. It means web research\n"
            "     could not produce a grounded estimate. Factor this into your verdict:\n"
            "     lean toward \"proceed_with_caution\" unless the financial model is\n"
            "     independently compelling without needing market size validation.\n"
            "\n"
            "2. CONTRADICTION CHECK\n"
            "   Inspect whether the financial model's demand assumption "
            f"({fi.expected_monthly_sales.value} units/month) is consistent with the\n"
            "   available market data. If SAM is unavailable, note that the demand assumption\n"
            "   cannot be validated — add a contradiction entry.\n"
            "   Also check: if competitive analysis shows high saturation but market shows\n"
            "   high growth, or if financial assumptions contradict market data — flag each.\n"
            "   Empty list is fine if no genuine contradiction found.\n"
            "\n"
            f"3. PRE-COMPUTED CONFIDENCE SCORE = {conf_bd.final_score:.2f}\n"
            "   This number is deterministic and already correct (computed from citation\n"
            "   quality, risk severity, data completeness, and pipeline success rate).\n"
            "   Reference it in your executive_summary. NEVER modify or override it."
        )

        full_context = "\n\n".join([
            market_block,
            competitive_block,
            financial_block,
            risk_block,
        ])

        # ── 3. LLM synthesis call ──────────────────────────────────────────────
        structured_llm = self._llm.with_structured_output(_SynthesisLLMOutput)
        try:
            llm_out: _SynthesisLLMOutput = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a senior business analyst writing the executive summary "
                            "and final recommendation for a feasibility study.\n"
                            "You will receive all prior analysis sections and a pre-computed "
                            "confidence score. Your job is to synthesize the findings, identify "
                            "contradictions between sections, and produce an actionable verdict.\n"
                            f"Write ALL text fields in language: {fi.output_language}.\n"
                            f"{ENGLISH_ONLY_TERMS_NOTE}\n\n"
                            f"{null_guard}"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Business: {fi.business_description.value}\n"
                            f"Geography: {fi.target_market_geography.value or 'global'}\n"
                            f"Model: {fi.business_model_type.value or 'unspecified'}\n"
                            f"Analysis horizon: {fi.analysis_horizon_years} years\n"
                            f"Confidence score (pre-computed): {conf_bd.final_score:.2f}\n\n"
                            f"=== All Analysis Sections ===\n\n{full_context}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            raise AgentSoftError(f"Synthesis LLM call failed: {exc}") from exc

        output = FeasibilitySynthesisOutput(
            study_id=fi.study_id,
            output_language=fi.output_language,
            verdict=Verdict(llm_out.verdict),
            confidence_score=conf_bd.final_score,
            confidence_breakdown=conf_bd.breakdown_dict(),
            executive_summary=LocalizedText(
                text=llm_out.executive_summary, language=fi.output_language
            ),
            key_opportunities=llm_out.key_opportunities,
            key_risks=llm_out.key_risks,
            data_gaps=llm_out.data_gaps,
            contradictions=llm_out.contradictions,
            rationale=LocalizedText(text=llm_out.rationale, language=fi.output_language),
        )

        await queue.put(SSEEvent.AGENT_COMPLETED, {"agent": _AGENT, "study_id": fi.study_id})
        return output
