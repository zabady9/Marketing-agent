from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable
from pydantic import BaseModel

from app.agents.deep_agent_factory import DeepAgentPhaseError, run_structured_deep_agent
from app.config import get_settings
from app.schemas.intake import FeasibilityInput
from app.schemas.report import (
    CalcTrace,
    CalculatedFigure,
    FinancialModelOutput,
    LocalizedText,
)
from app.sse import EventQueue, SSEEvent
from app.tools.financial_calc import (
    CALC_METHODOLOGY,
    BreakEvenInput,
    CashFlowInput,
    CostStructureInput,
    NPVInput,
    ROIInput,
    SensitivityInput,
    calculate_break_even,
    calculate_cost_structure,
    calculate_npv,
    calculate_roi,
    project_cash_flow,
    run_sensitivity_analysis,
)
from app.tools.language import ENGLISH_ONLY_TERMS_NOTE


class FinancialCalcError(Exception):
    """Raised when a required financial input is unavailable or a calc fails."""


def run_full_financial_model(
    *,
    capex: float,
    opex_monthly: float,
    unit_price: float,
    expected_monthly_sales: float,
    analysis_horizon_years: int,
) -> dict[str, dict[str, Any]]:
    """The same six-calculation sequence FinancialModelingAgent.run() uses,
    as one pure function with no SSE/CalcTrace/LLM involvement — shared by
    the real pipeline (below) and chat's what-if scenario tool (see
    chat_agent.run_scenario_simulation_tool) so the two can never silently
    drift apart. Raises FinancialCalcError on any calculator failure."""
    horizon_months = analysis_horizon_years * 12
    monthly_revenue = unit_price * expected_monthly_sales
    annual_net = (monthly_revenue - opex_monthly) * 12

    try:
        break_even = calculate_break_even(BreakEvenInput(
            fixed_costs=capex, unit_price=unit_price,
            variable_cost_per_unit=0.0, monthly_unit_sales=expected_monthly_sales,
        ))
    except Exception as exc:
        raise FinancialCalcError(f"calculate_break_even failed: {exc}") from exc

    try:
        roi_year_1 = calculate_roi(ROIInput(
            total_investment=capex, net_profit=annual_net - capex,
        ))
    except Exception as exc:
        raise FinancialCalcError(f"calculate_roi (year 1) failed: {exc}") from exc

    try:
        roi_year_n = calculate_roi(ROIInput(
            total_investment=capex,
            net_profit=annual_net * analysis_horizon_years - capex,
        ))
    except Exception as exc:
        raise FinancialCalcError(
            f"calculate_roi (year {analysis_horizon_years}) failed: {exc}"
        ) from exc

    try:
        npv = calculate_npv(NPVInput(
            initial_investment=capex,
            annual_cash_flows=[annual_net] * analysis_horizon_years,
            discount_rate=0.10,
        ))
    except Exception as exc:
        raise FinancialCalcError(f"calculate_npv failed: {exc}") from exc

    try:
        sensitivity = run_sensitivity_analysis(SensitivityInput(
            fixed_costs=capex, unit_price=unit_price, variable_cost_per_unit=0.0,
            monthly_unit_sales=expected_monthly_sales, revenue_multipliers=[0.7, 1.0, 1.3],
        ))
    except Exception as exc:
        raise FinancialCalcError(f"run_sensitivity_analysis failed: {exc}") from exc

    try:
        cash_flow = project_cash_flow(CashFlowInput(
            monthly_revenue=monthly_revenue, monthly_opex=opex_monthly,
            capex=capex, horizon_months=horizon_months,
        ))
    except Exception as exc:
        raise FinancialCalcError(f"project_cash_flow failed: {exc}") from exc

    try:
        cost_structure = calculate_cost_structure(CostStructureInput(
            capex=capex, opex_monthly=opex_monthly, horizon_months=horizon_months,
        ))
    except Exception as exc:
        raise FinancialCalcError(f"calculate_cost_structure failed: {exc}") from exc

    return {
        "break_even": break_even,
        "roi_year_1": roi_year_1,
        "roi_year_n": roi_year_n,
        "npv": npv,
        "sensitivity": sensitivity,
        "cash_flow": cash_flow,
        "cost_structure": cost_structure,
    }


def _confidence(fi: FeasibilityInput, *fields: str) -> Literal["high", "low"]:
    """Return 'low' if any of the named FeasibilityInput fields has low_confidence."""
    for name in fields:
        fws = getattr(fi, name, None)
        if fws is not None and getattr(fws, "low_confidence", False):
            return "low"
    return "high"


async def _emit_calc(
    queue: EventQueue,
    study_id: str,
    fn: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
    conf: Literal["high", "low"],
) -> CalcTrace:
    """Emit calc_started → calc_completed and return the CalcTrace."""
    await queue.put(SSEEvent.CALC_STARTED, {"study_id": study_id, "fn": fn, "inputs": inputs})
    trace = CalcTrace(
        fn=fn, inputs=inputs, output=output, input_confidence=conf,
        methodology=CALC_METHODOLOGY.get(fn, ""),
    )
    await queue.put(
        SSEEvent.CALC_COMPLETED,
        {"study_id": study_id, "fn": fn, "output": output, "input_confidence": conf},
    )
    return trace


class FinancialModelingAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.reasoning_model,
            google_api_key=s.google_api_key,
            temperature=0,
        )
        self._settings = s

    @traceable(name="Financial Modeling Agent", run_type="chain")
    async def run(
        self,
        fi: FeasibilityInput,
        queue: EventQueue,
    ) -> FinancialModelOutput:
        await queue.put(SSEEvent.AGENT_STARTED, {"agent": "financial", "study_id": fi.study_id})

        # ── 1. Validate inputs — fail hard if any required value is None ───────
        unit_price = fi.pricing_unit_price.value
        capex = fi.capex.value
        opex_monthly = fi.opex_monthly.value
        monthly_sales = fi.expected_monthly_sales.value

        missing = [
            name for name, val in [
                ("pricing_unit_price", unit_price),
                ("capex", capex),
                ("opex_monthly", opex_monthly),
                ("expected_monthly_sales", monthly_sales),
            ]
            if val is None
        ]
        if missing:
            raise FinancialCalcError(
                f"Cannot compute financial model — required inputs are None: {missing}. "
                "This indicates web-search estimation failed during intake."
            )

        horizon_months = fi.analysis_horizon_years * 12
        monthly_revenue = unit_price * monthly_sales
        annual_net = (monthly_revenue - opex_monthly) * 12

        # ── 2. Run all calculations via the shared formula path, emitting
        # SSE + building a CalcTrace for each (see run_full_financial_model's
        # docstring for why the calculations themselves live there, not here).
        results = run_full_financial_model(
            capex=capex,
            opex_monthly=opex_monthly,
            unit_price=unit_price,
            expected_monthly_sales=monthly_sales,
            analysis_horizon_years=fi.analysis_horizon_years,
        )

        be_output = results["break_even"]
        be_inputs = dict(
            fixed_costs=capex, unit_price=unit_price,
            variable_cost_per_unit=0.0, monthly_unit_sales=monthly_sales,
        )
        be_conf = _confidence(fi, "capex", "expected_monthly_sales")
        be_trace = await _emit_calc(queue, fi.study_id, "calculate_break_even",
                                    be_inputs, be_output, be_conf)

        roi1_output = results["roi_year_1"]
        roi1_inputs = dict(total_investment=capex, net_profit=annual_net - capex)
        roi1_conf = _confidence(fi, "capex", "opex_monthly", "expected_monthly_sales")
        roi1_trace = await _emit_calc(queue, fi.study_id, "calculate_roi",
                                      roi1_inputs, roi1_output, roi1_conf)

        roin_output = results["roi_year_n"]
        roin_inputs = dict(
            total_investment=capex,
            net_profit=annual_net * fi.analysis_horizon_years - capex,
        )
        roin_conf = roi1_conf
        roin_trace = await _emit_calc(queue, fi.study_id, "calculate_roi",
                                      roin_inputs, roin_output, roin_conf)

        npv_output = results["npv"]
        npv_inputs = dict(
            initial_investment=capex,
            annual_cash_flows=[annual_net] * fi.analysis_horizon_years,
            discount_rate=0.10,
        )
        npv_conf = _confidence(fi, "capex", "opex_monthly", "expected_monthly_sales")
        npv_trace = await _emit_calc(queue, fi.study_id, "calculate_npv",
                                     npv_inputs, npv_output, npv_conf)

        sens_output = results["sensitivity"]
        sens_inputs = dict(
            fixed_costs=capex, unit_price=unit_price, variable_cost_per_unit=0.0,
            monthly_unit_sales=monthly_sales, revenue_multipliers=[0.7, 1.0, 1.3],
        )
        sens_conf = _confidence(fi, "capex", "expected_monthly_sales")
        sens_trace = await _emit_calc(queue, fi.study_id, "run_sensitivity_analysis",
                                      sens_inputs, sens_output, sens_conf)

        cf_output = results["cash_flow"]
        cf_inputs = dict(
            monthly_revenue=monthly_revenue, monthly_opex=opex_monthly,
            capex=capex, horizon_months=horizon_months,
        )
        cf_conf = _confidence(fi, "capex", "opex_monthly", "expected_monthly_sales")
        cf_trace = await _emit_calc(queue, fi.study_id, "project_cash_flow",
                                    cf_inputs, cf_output, cf_conf)

        cs_output = results["cost_structure"]
        cs_inputs = dict(capex=capex, opex_monthly=opex_monthly, horizon_months=horizon_months)
        cs_conf = _confidence(fi, "capex", "opex_monthly")
        cs_trace = await _emit_calc(queue, fi.study_id, "calculate_cost_structure",
                                    cs_inputs, cs_output, cs_conf)

        # ── 3. LLM generates narrative only — no numbers ──────────────────────
        any_low = any(
            t.input_confidence == "low"
            for t in [be_trace, roi1_trace, roin_trace, npv_trace, sens_trace, cf_trace, cs_trace]
        )

        class _Narrative(BaseModel):
            summary: str
            key_insights: list[str]
            risks_from_numbers: list[str]

        system_prompt = (
            "You are a financial analyst writing a feasibility report section. "
            "You will be given pre-computed financial results. "
            "Your job is to write ONLY narrative interpretation — "
            "do NOT invent numbers; reference the computed values provided. "
            f"Write entirely in language code: {fi.output_language}. "
            f"{ENGLISH_ONLY_TERMS_NOTE}"
            + (
                "\n\nIMPORTANT: Some inputs (marked estimated) carry low "
                "confidence. Clearly note this uncertainty in your narrative."
                if any_low else ""
            )
            + (
                "\n\nYou may `read_file` any `/calc/*.json` to double-check a "
                "figure before writing about it; never state a number that "
                "isn't in one of these files or in the message below."
            )
        )
        human_message = (
            f"Business: {fi.business_description.value}\n"
            f"Unit price: {unit_price} {fi.pricing_currency}\n"
            f"Monthly sales (estimated={fi.expected_monthly_sales.low_confidence}): "
            f"{monthly_sales}\n"
            f"Capex (estimated={fi.capex.low_confidence}): {capex} {fi.capex_currency}\n"
            f"Monthly opex (estimated={fi.opex_monthly.low_confidence}): "
            f"{opex_monthly} {fi.opex_monthly_currency}\n\n"
            f"COMPUTED RESULTS:\n"
            f"Break-even: {be_output['break_even_units']} units / "
            f"{be_output['break_even_months']} months\n"
            f"ROI year 1: {roi1_output['roi_percent']}%\n"
            f"ROI year {fi.analysis_horizon_years}: {roin_output['roi_percent']}%\n"
            f"NPV: {npv_output['npv']} (positive={npv_output['is_positive']})\n"
            f"Payback month: {cf_output['payback_month']}\n"
            f"Sensitivity: {sens_output['scenarios']}\n"
        )

        # Narrative failure is a separate, independently-handled step from the
        # calculator block above: the numbers are already valid Python-computed
        # results by this point, so a narrative failure degrades this section
        # (fallback text/empty lists) rather than aborting the whole financial
        # phase. This is a deliberate behavior change from before, when a
        # narrative-call exception propagated uncaught and would have aborted
        # the phase like a calculator failure.
        try:
            if self._settings.deepagents_enabled:
                seed_files: dict[str, str] = {
                    "/calc/break_even.json": json.dumps(be_trace.model_dump()),
                    "/calc/roi_year_1.json": json.dumps(roi1_trace.model_dump()),
                    "/calc/roi_year_n.json": json.dumps(roin_trace.model_dump()),
                    "/calc/npv.json": json.dumps(npv_trace.model_dump()),
                    "/calc/sensitivity.json": json.dumps(sens_trace.model_dump()),
                    "/calc/cash_flow.json": json.dumps(cf_trace.model_dump()),
                    "/calc/cost_structure.json": json.dumps(cs_trace.model_dump()),
                }
                narrative_result: _Narrative = await run_structured_deep_agent(
                    model=self._llm,
                    tools=[],
                    seed_files=seed_files,
                    system_prompt=system_prompt,
                    human_message=human_message,
                    output_schema=_Narrative,
                    model_call_limit=self._settings.phase_model_call_limit,
                )
            else:
                structured_llm = self._llm.with_structured_output(_Narrative)
                narrative_result = await structured_llm.ainvoke(
                    [SystemMessage(content=system_prompt), HumanMessage(content=human_message)]
                )
        except DeepAgentPhaseError:
            narrative_result = _Narrative(
                summary="[Narrative unavailable]",
                key_insights=[],
                risks_from_numbers=[],
            )
        except Exception:
            narrative_result = _Narrative(
                summary="[Narrative unavailable]",
                key_insights=[],
                risks_from_numbers=[],
            )

        narrative = LocalizedText(
            text=narrative_result.summary,
            language=fi.output_language,
        )

        # ── 4. Assemble output ────────────────────────────────────────────────
        output = FinancialModelOutput(
            study_id=fi.study_id,
            output_language=fi.output_language,
            capex_value=capex,
            capex_currency=fi.capex_currency,
            capex_source=fi.capex.source,
            opex_monthly_value=opex_monthly,
            opex_monthly_currency=fi.opex_monthly_currency,
            opex_monthly_source=fi.opex_monthly.source,
            unit_price=unit_price,
            pricing_currency=fi.pricing_currency,
            expected_monthly_sales=monthly_sales,
            expected_monthly_sales_source=fi.expected_monthly_sales.source,
            analysis_horizon_years=fi.analysis_horizon_years,
            break_even=CalculatedFigure(
                value=be_output,
                calculation_trace=be_trace,
                input_confidence=be_conf,
            ),
            roi_year_1=CalculatedFigure(
                value=roi1_output,
                calculation_trace=roi1_trace,
                input_confidence=roi1_conf,
            ),
            roi_year_n=CalculatedFigure(
                value=roin_output,
                calculation_trace=roin_trace,
                input_confidence=roin_conf,
            ),
            npv=CalculatedFigure(
                value=npv_output,
                calculation_trace=npv_trace,
                input_confidence=npv_conf,
            ),
            sensitivity=CalculatedFigure(
                value=sens_output,
                calculation_trace=sens_trace,
                input_confidence=sens_conf,
            ),
            cash_flow=CalculatedFigure(
                value=cf_output,
                calculation_trace=cf_trace,
                input_confidence=cf_conf,
            ),
            cost_structure=CalculatedFigure(
                value=cs_output,
                calculation_trace=cs_trace,
                input_confidence=cs_conf,
            ),
            narrative=narrative,
            review_recommended=any_low,
        )

        await queue.put(SSEEvent.AGENT_COMPLETED, {"agent": "financial", "study_id": fi.study_id})
        return output
