"""Carrying out one planned step: research -> (calculations) -> blocks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from app.analysis import prompts
from app.analysis.llm import AnalysisLLM
from app.analysis.research import Research
from app.schemas.blocks import Citation, parse_blocks
from app.tools.financial_calc import get_financial_tools

logger = logging.getLogger(__name__)


@dataclass
class StepOutcome:
    summary: str
    blocks: list[dict]
    calculations: list[dict] = field(default_factory=list)


def _calc_tools() -> dict[str, StructuredTool]:
    return {t.name: t for t in get_financial_tools()}


async def _run_calculations(
    llm: AnalysisLLM,
    research: Research,
    language: str,
    context: str,
    max_rounds: int,
) -> list[dict]:
    """Bounded tool loop: the model calls the deterministic calculator (and,
    rarely, web_search for a missing input). Returns every calculation made."""
    calc_tools = _calc_tools()

    async def web_search(query: str) -> str:
        """Search the web for one missing input (a price, cost or market figure)."""
        return research.format(await research.search([query]))

    search_tool = StructuredTool.from_function(coroutine=web_search, name="web_search")
    tools = list(calc_tools.values()) + [search_tool]

    messages = [
        SystemMessage(content=prompts.step_tools_system(language)),
        HumanMessage(content=context),
    ]
    calculations: list[dict] = []
    for _ in range(max_rounds):
        reply = await llm.tool_round(messages, tools)
        messages.append(reply)
        if not reply.tool_calls:
            break
        for call in reply.tool_calls:
            name, args = call["name"], call.get("args", {})
            try:
                if name == "web_search":
                    result: object = await search_tool.ainvoke(args)
                elif name in calc_tools:
                    result = calc_tools[name].invoke(args)
                    calculations.append({"tool": name, "inputs": args, "output": result})
                else:
                    raise ValueError(f"unknown tool {name}")
            except Exception as exc:  # bad inputs: tell the model, let it retry
                result = f"Error: {exc}"
            messages.append(
                ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call["id"])
            )
    return calculations


def _apply_quality_checks(blocks: list[dict], has_calculations: bool) -> None:
    """A figure only keeps the basis it can prove: 'sourced' needs a citation on
    its block, 'calculated' needs a calculator run in this step."""
    for b in blocks:
        cited = bool(b.get("citations"))
        items = b.get("items") if b.get("type") == "stats" else [b] if b.get("type") == "chart" else []
        for item in items or []:
            basis = item.get("basis")
            if basis == "sourced" and not cited:
                item["basis"] = "estimate"
            elif basis == "calculated" and not has_calculations:
                item["basis"] = "estimate"


def _resolve_citations(blocks: list[dict], research: Research) -> None:
    for b in blocks:
        seen = {c["url"] for c in b.get("citations", [])}
        for i in b.pop("citation_indices", []) or []:
            r = research.result(i)
            if r is not None and r.url not in seen:
                b.setdefault("citations", []).append(
                    Citation(url=r.url, title=r.title, snippet=r.snippet[:300]).model_dump()
                )
                seen.add(r.url)


async def execute_step(
    llm: AnalysisLLM,
    research: Research,
    *,
    step: dict,
    plan_overview: str,
    goal: str,
    business: str,
    dependency_summaries: str,
    language: str,
    tool_rounds: int,
    inherited_sources: list[dict] | None = None,
) -> StepOutcome:
    inherited = research.seed(inherited_sources or [])
    results = await research.search(step.get("research_queries") or [])
    research_text = research.format(results, with_raw=True)
    if inherited:
        research_text = (
            "Sources behind the earlier steps' figures (cite these when you use those figures):\n"
            + research.format(inherited)
            + ("\n\nNew research for this step:\n" + research_text if research_text else "")
        )

    context = (
        f"User goal: {goal}\n\nAnalysis plan:\n{plan_overview}\n\n"
        f"THIS STEP: {step['title']}\nObjective: {step.get('objective', '')}\n"
        f"Suggested blocks: {', '.join(step.get('suggested_blocks') or []) or 'your choice'}\n\n"
        f"Business profile:\n{business}\n\n"
        + (f"Results of earlier steps this step builds on:\n{dependency_summaries}\n\n" if dependency_summaries else "")
        + f"Research results (cite by number):\n{research_text or '(no results found)'}"
    )

    calculations: list[dict] = []
    if step.get("needs_calculation"):
        calculations = await _run_calculations(llm, research, language, context, tool_rounds)

    calc_text = (
        "\n\nCalculator results (mark these figures basis=calculated):\n"
        + "\n".join(json.dumps(c, ensure_ascii=False, default=str) for c in calculations)
        if calculations
        else ""
    )
    # Citation numbers may now include searches made during the calculation loop.
    if calculations:
        context += "\n\nAll research results (final numbering):\n" + research.format(research.all(), with_raw=False)

    raw = await llm.json(prompts.step_output_system(language), context + calc_text)
    blocks = [b.model_dump() for b in parse_blocks(raw.get("blocks") or [])]
    _resolve_citations(blocks, research)
    _apply_quality_checks(blocks, bool(calculations))
    summary = str(raw.get("summary") or "").strip()
    return StepOutcome(summary=summary, blocks=blocks, calculations=calculations)
