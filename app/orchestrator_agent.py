"""Deep Agent supervisor for the feasibility pipeline.

The planner's tools are the 6 phase agents (Market Sizing, Competitive
Analysis, Financial Modeling, Risk Assessment, Synthesis, Citation QC), each
wrapped as a near-argument-free tool that reads/writes a plain-Python
`PipelineRunState` dataclass closed over by every wrapper — NOT the deep
agent's own virtual filesystem or message history. The filesystem is still
seeded with a compact JSON summary per phase purely so the planner LLM can
read it if useful for its own reasoning; no downstream phase's correctness
ever depends on the LLM correctly referencing a file path.

Two invariants the user requires to be enforced deterministically, not by
system-prompt instruction, live here:

- Financial-abort: the financial tool wrapper itself catches
  `FinancialCalcError`, sets `state.aborted`, and returns a plain string
  (never lets the exception reach LangGraph's tool-execution node, which by
  default catches tool exceptions into an error ToolMessage and lets the
  model keep going). Every OTHER phase tool checks `state.aborted` first and
  refuses to run if set — deterministic even if a confused planner tries
  another tool next.
- Citation-QC-always-last: `state.qc_called` is set inside the QC tool
  wrapper's closure the instant it actually runs. After the deep agent's
  graph invocation completes, `run_feasibility_pipeline_deep_agent` force-
  invokes QC in application code if the planner never called it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from app.agents.citation_qc import CitationValidationAgent
from app.agents.competitive import CompetitiveAnalysisAgent
from app.agents.financial import FinancialCalcError, FinancialModelingAgent
from app.agents.market_sizing import MarketSizingAgent
from app.agents.risk import RiskAssessmentAgent
from app.agents.synthesis import FeasibilitySynthesisAgent
from app.config import get_settings
from app.orchestrator_legacy import PipelineResult
from app.schemas.intake import FeasibilityInput
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.qc import CitationQCOutput
from app.schemas.report import FinancialModelOutput
from app.schemas.risk import RiskAssessmentOutput
from app.schemas.synthesis import FeasibilitySynthesisOutput
from app.sse import EventQueue, SSEEvent
from deepagents import create_deep_agent

logger = logging.getLogger(__name__)

# Keyword scan for branch (b): "extra risk pass for regulated industries" —
# deterministic detection, planner discretion only over whether to act on it.
_REGULATED_INDUSTRY_KEYWORDS = (
    "health", "medical", "clinic", "pharma", "bank", "lending", "loan",
    "insurance", "securities", "investment advis", "broker", "legal",
    "law firm", "cannabis", "alcohol", "tobacco", "firearm", "gun",
    "childcare", "daycare", "food safety", "restaurant", "aviation",
    "airline", "energy utility", "utility provider", "crypto", "gambling",
    "casino",
)

_PIPELINE_TIMEOUT_SECONDS = 900


@dataclass
class PipelineRunState:
    market_output: MarketSizingOutput | None = None
    competitive_output: CompetitiveAnalysisOutput | None = None
    competitive_skipped_reason: str | None = None
    financial_output: FinancialModelOutput | None = None
    risk_output: RiskAssessmentOutput | None = None
    synthesis_output: FeasibilitySynthesisOutput | None = None
    qc_output: CitationQCOutput | None = None
    aborted: bool = False
    financial_error: str | None = None
    qc_called: bool = False
    market_retried: bool = False
    financial_rerun_done: bool = False
    fatal_agent_failures: list[str] = field(default_factory=list)


def _detect_regulated_industry(fi: FeasibilityInput) -> str | None:
    haystack = " ".join(
        (fi.business_description.value or "", fi.business_model_type.value or "",
         fi.target_market_description.value or "")
    ).lower()
    for keyword in _REGULATED_INDUSTRY_KEYWORDS:
        if keyword in haystack:
            return keyword
    return None


def _broadened_geography_input(fi: FeasibilityInput) -> FeasibilityInput:
    revised = fi.model_copy(deep=True)
    revised.target_market_geography = revised.target_market_geography.model_copy(
        update={"value": "global", "low_confidence": True}
    )
    return revised


def build_pipeline_tools(fi: FeasibilityInput, queue: EventQueue, state: PipelineRunState) -> list:
    regulated_keyword = _detect_regulated_industry(fi)

    @tool
    async def run_market_and_competitive_tool(
        skip_competitive: bool = False, skip_reason: str | None = None
    ) -> str:
        """Run market sizing, and competitive analysis unless
        skip_competitive=True. Only set skip_competitive=True if the business
        is a genuinely novel category with no meaningful comparables to
        analyze — give a short skip_reason explaining why. Call this first."""
        if state.aborted:
            return "FATAL: pipeline already aborted. Do not call any more tools."

        if skip_competitive:
            state.competitive_skipped_reason = skip_reason or "novel category, no comparables"
            market_result = await MarketSizingAgent().run(fi, queue)
            competitive_result = None
        else:
            market_result, competitive_result = await asyncio.gather(
                MarketSizingAgent().run(fi, queue),
                CompetitiveAnalysisAgent().run(fi, queue),
                return_exceptions=True,
            )

        summary_parts = []
        if isinstance(market_result, Exception):
            summary_parts.append(f"Market sizing failed (non-fatal): {market_result}")
        else:
            market_result = MarketSizingOutput.model_validate(market_result.model_dump())
            # Branch (d): deterministic retry with broadened geography if
            # TAM/SAM/SOM all came back null — a pure Python check on an
            # already-typed output, not planner discretion.
            all_null = (
                market_result.tam.value is None
                and market_result.sam.value is None
                and market_result.som.value is None
            )
            if all_null and not state.market_retried:
                state.market_retried = True
                broadened_fi = _broadened_geography_input(fi)
                retry_result = await MarketSizingAgent().run(broadened_fi, queue)
                if retry_result.tam.value is not None or retry_result.sam.value is not None or retry_result.som.value is not None:
                    market_result = MarketSizingOutput.model_validate(retry_result.model_dump())
            state.market_output = market_result
            summary_parts.append(
                f"Market sizing complete. TAM={market_result.tam.value}, "
                f"SAM={market_result.sam.value}, SOM={market_result.som.value}."
            )

        if skip_competitive:
            summary_parts.append(f"Competitive analysis skipped: {state.competitive_skipped_reason}")
        elif isinstance(competitive_result, Exception):
            summary_parts.append(f"Competitive analysis failed (non-fatal): {competitive_result}")
        else:
            state.competitive_output = CompetitiveAnalysisOutput.model_validate(
                competitive_result.model_dump()
            )
            summary_parts.append(
                f"Competitive analysis complete. {len(state.competitive_output.competitors)} competitors found."
            )

        summary_parts.append("Call financial modeling next.")
        return " ".join(summary_parts)

    @tool
    async def run_financial_modeling_tool() -> str:
        """Run financial modeling (capex/opex, break-even, ROI, NPV,
        sensitivity, cash flow). Call this after market sizing/competitive
        analysis, before risk assessment or synthesis. If the result starts
        with 'FATAL', the study is over — do not call any other tool
        afterward, just produce a short final message."""
        if state.aborted:
            return "FATAL: pipeline already aborted. Do not call any more tools."
        try:
            output = await FinancialModelingAgent().run(fi, queue)
        except FinancialCalcError as exc:
            state.aborted = True
            state.financial_error = str(exc)
            state.fatal_agent_failures.append("financial")
            return (
                f"FATAL: financial modeling failed irrecoverably ({exc}). "
                "The study has been aborted. Do not call any other tool."
            )
        state.financial_output = FinancialModelOutput.model_validate(output.model_dump())
        return (
            f"Financial modeling complete. capex={state.financial_output.capex_value} "
            f"{state.financial_output.capex_currency}. Call risk assessment next."
        )

    @tool
    async def run_risk_assessment_tool(regulatory_focus: bool = False) -> str:
        """Run risk assessment. Requires financial modeling to have completed
        first. Set regulatory_focus=True to run a second, regulation-focused
        pass IN ADDITION to a normal pass — only do this once, and only when
        there are real regulatory/compliance signals for this business."""
        if state.aborted:
            return "FATAL: pipeline already aborted. Do not call any more tools."
        if state.financial_output is None:
            return "Cannot run risk assessment before financial modeling has completed."

        base_fi = fi
        if regulatory_focus:
            extra_focus = (
                (fi.founder_risks.value or "")
                + " Additionally give particular attention to regulatory and "
                "compliance risk given signals in this business description."
            )
            base_fi = fi.model_copy(deep=True)
            base_fi.founder_risks = base_fi.founder_risks.model_copy(update={"value": extra_focus})

        output = await RiskAssessmentAgent().run(
            base_fi, queue,
            market_output=state.market_output,
            competitive_output=state.competitive_output,
            financial_output=state.financial_output,
        )
        output = RiskAssessmentOutput.model_validate(output.model_dump())
        if state.risk_output is None:
            state.risk_output = output
        else:
            state.risk_output = _merge_risk_outputs(state.risk_output, output)
        return f"Risk assessment complete. {len(state.risk_output.risks)} risks identified so far."

    @tool
    async def run_synthesis_tool() -> str:
        """Run the executive-summary synthesis. Requires financial modeling
        (and ideally risk assessment) to have completed first."""
        if state.aborted:
            return "FATAL: pipeline already aborted. Do not call any more tools."
        if state.financial_output is None:
            return "Cannot synthesize before financial modeling has completed."

        output = await FeasibilitySynthesisAgent().run(
            fi, queue,
            market_output=state.market_output,
            competitive_output=state.competitive_output,
            financial_output=state.financial_output,
            risk_output=state.risk_output,
            fatal_agent_failures=state.fatal_agent_failures,
        )
        output = FeasibilitySynthesisOutput.model_validate(output.model_dump())

        # Branch (c): deterministic one-time financial re-run if synthesis
        # flags a demand/market contradiction against an ESTIMATED (not
        # user-asserted) sales assumption — not planner discretion, since the
        # trigger is a typed boolean, not free text requiring judgment.
        if (
            getattr(output, "demand_assumption_flagged", False)
            and fi.expected_monthly_sales.low_confidence
            and not state.financial_rerun_done
        ):
            state.financial_rerun_done = True
            revised_fi = fi.model_copy(deep=True)
            current = revised_fi.expected_monthly_sales.value or 0
            revised_fi.expected_monthly_sales = revised_fi.expected_monthly_sales.model_copy(
                update={"value": current * 0.6, "low_confidence": True}
            )
            try:
                refreshed_financial = await FinancialModelingAgent().run(revised_fi, queue)
            except FinancialCalcError as exc:
                state.aborted = True
                state.financial_error = str(exc)
                state.fatal_agent_failures.append("financial")
                return f"FATAL: financial re-run failed irrecoverably ({exc})."
            state.financial_output = FinancialModelOutput.model_validate(refreshed_financial.model_dump())
            output = await FeasibilitySynthesisAgent().run(
                fi, queue,
                market_output=state.market_output,
                competitive_output=state.competitive_output,
                financial_output=state.financial_output,
                risk_output=state.risk_output,
                fatal_agent_failures=state.fatal_agent_failures,
            )
            output = FeasibilitySynthesisOutput.model_validate(output.model_dump())

        state.synthesis_output = output
        return f"Synthesis complete. Verdict: {output.verdict}. Call citation QC last."

    @tool
    async def run_citation_qc_tool() -> str:
        """Run the citation QC gate over whatever sections have completed so
        far. This MUST be the last tool called before finishing — always
        call it once everything else is done, even if some sections failed
        or were skipped."""
        if state.aborted:
            return "FATAL: pipeline already aborted. Do not call any more tools."
        output = await CitationValidationAgent().run(
            fi, queue,
            market_output=state.market_output,
            competitive_output=state.competitive_output,
            financial_output=state.financial_output,
            risk_output=state.risk_output,
            synthesis_output=state.synthesis_output,
        )
        state.qc_output = CitationQCOutput.model_validate(output.model_dump())
        state.qc_called = True
        return "Citation QC complete. The study is now finished — write your final summary message."

    tools = [
        run_market_and_competitive_tool,
        run_financial_modeling_tool,
        run_risk_assessment_tool,
        run_synthesis_tool,
        run_citation_qc_tool,
    ]
    # Regulated-industry detection is injected as a fact for the planner to
    # act on at its discretion (branch b) — not itself a tool call.
    if regulated_keyword is not None:
        logger.info("Detected regulated-industry signal (%r) for study %s", regulated_keyword, fi.study_id)
    return tools, regulated_keyword


def _merge_risk_outputs(base: RiskAssessmentOutput, supplemental: RiskAssessmentOutput) -> RiskAssessmentOutput:
    merged = base.model_copy(deep=True)
    seen_descriptions = {r.risk_description for r in merged.risks}
    for r in supplemental.risks:
        if r.risk_description not in seen_descriptions:
            merged.risks.append(r)
            seen_descriptions.add(r.risk_description)
    merged.high_critical_count = sum(
        1 for r in merged.risks if r.probability == "high" and r.impact == "high"
    )
    seen_urls = {c.url for c in merged.citations}
    for c in supplemental.citations:
        if c.url not in seen_urls:
            merged.citations.append(c)
            seen_urls.add(c.url)
    if supplemental.narrative.text and supplemental.narrative.text not in merged.narrative.text:
        merged.narrative = merged.narrative.model_copy(
            update={"text": merged.narrative.text + "\n\n" + supplemental.narrative.text}
        )
    return merged


def _orchestrator_system_prompt(regulated_keyword: str | None) -> str:
    base = (
        "You are coordinating a feasibility-study pipeline by calling the "
        "tools available to you, in order: (1) run_market_and_competitive_tool, "
        "(2) run_financial_modeling_tool, (3) run_risk_assessment_tool, "
        "(4) run_synthesis_tool, (5) run_citation_qc_tool. Call each tool "
        "exactly once, in this order, unless a tool's own result tells you "
        "otherwise. If any tool's result starts with 'FATAL', stop calling "
        "tools immediately and just write a short final message noting the "
        "failure — do not call any further tools. citation QC must always be "
        "the last tool you call, no matter what happened in earlier steps."
    )
    if regulated_keyword is not None:
        base += (
            f"\n\nNote: this business description contains a signal ({regulated_keyword!r}) "
            "suggesting it may operate in a regulated industry. Consider calling "
            "run_risk_assessment_tool a second time with regulatory_focus=True, "
            "in addition to your normal risk assessment call, if you judge the "
            "regulatory/compliance risk here is material."
        )
    return base


async def run_feasibility_pipeline_deep_agent(
    study_id: str,
    feasibility_input: FeasibilityInput,
    queue: EventQueue,
    glossary: dict[str, str] | None = None,
) -> PipelineResult:
    """Deep Agent supervisor entry point — same signature and PipelineResult
    shape as orchestrator_legacy.run_feasibility_pipeline_fixed_order, so
    app/orchestrator.py can dispatch between the two transparently."""
    settings = get_settings()
    state = PipelineRunState()

    if glossary is not None:
        await queue.put(
            SSEEvent.SECTION_READY,
            {"section": "glossary", "language": feasibility_input.output_language, "data": {"terms": glossary}},
        )

    tools, regulated_keyword = build_pipeline_tools(feasibility_input, queue, state)
    model = ChatGoogleGenerativeAI(
        model=settings.reasoning_model, google_api_key=settings.google_api_key, temperature=0,
    )
    system_prompt = _orchestrator_system_prompt(regulated_keyword)
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            ModelCallLimitMiddleware(run_limit=settings.orchestrator_model_call_limit, exit_behavior="error"),
            ToolCallLimitMiddleware(run_limit=settings.orchestrator_model_call_limit * 2, exit_behavior="error"),
        ],
        checkpointer=None,
    )

    orchestrator_error: str | None = None
    try:
        await asyncio.wait_for(
            agent.ainvoke(
                {
                    "messages": [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content="Run the full feasibility study pipeline for this business."),
                    ]
                }
            ),
            timeout=_PIPELINE_TIMEOUT_SECONDS,
        )
    except (ModelCallLimitExceededError, ToolCallLimitExceededError) as exc:
        logger.warning("Pipeline planner exceeded its call budget for study %s: %s", study_id, exc)
        orchestrator_error = f"Planner exceeded its call budget: {exc}"
    except asyncio.TimeoutError:
        logger.warning("Pipeline planner timed out for study %s", study_id)
        orchestrator_error = "Planner timed out."
    except Exception as exc:  # noqa: BLE001 — a planner meltdown must never propagate raw
        logger.exception("Pipeline planner failed unexpectedly for study %s", study_id)
        orchestrator_error = f"Planner failed unexpectedly: {exc}"

    # Citation-QC-always-last, enforced in application code — force-invoke
    # if the planner never called it (and the pipeline wasn't aborted).
    if not state.aborted and not state.qc_called:
        try:
            output = await CitationValidationAgent().run(
                feasibility_input, queue,
                market_output=state.market_output,
                competitive_output=state.competitive_output,
                financial_output=state.financial_output,
                risk_output=state.risk_output,
                synthesis_output=state.synthesis_output,
            )
            state.qc_output = CitationQCOutput.model_validate(output.model_dump())
            state.qc_called = True
        except Exception as exc:
            logger.warning("Forced citation QC failed (non-fatal) for study %s: %s", study_id, exc)

    return PipelineResult(
        market_output=state.market_output,
        competitive_output=state.competitive_output,
        competitive_skipped_reason=state.competitive_skipped_reason,
        financial_output=state.financial_output,
        financial_error=state.financial_error,
        risk_output=state.risk_output,
        synthesis_output=state.synthesis_output,
        qc_output=state.qc_output,
        fatal_agent_failures=state.fatal_agent_failures,
        orchestrator_error=orchestrator_error,
        glossary=glossary,
        glossary_language=feasibility_input.output_language,
    )
