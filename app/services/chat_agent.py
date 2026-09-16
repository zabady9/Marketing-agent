from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ChatMessage, ChatSession, MemoryEntry, Project, StudyResult
from app.schemas.chart import ChartSeries, ChartSpec
from app.schemas.project import BusinessProfileUpdate
from app.services.chat import get_latest_study_id_for_session, maybe_set_title
from app.services.memory import add_memory_entry, list_memory_entries
from app.services.project import update_business_profile
from app.services.study import run_feasibility_study, run_single_phase_study
from app.services.tool_intent import detect_single_tool_intent
from app.sse import EventQueue, SSEEvent

logger = logging.getLogger(__name__)

# Hard cap on tool-call rounds within a single chat turn. One "round" = one
# model response containing tool calls, followed by executing them and
# feeding results back. Without this, a model that keeps calling tools
# back-to-back (e.g. stuck re-triggering the same tool) would loop forever.
MAX_TOOL_ROUNDS = 6

_FALLBACK_MESSAGE = (
    "I wasn't able to finish that in a reasonable number of steps. "
    "Try rephrasing your request or asking for one thing at a time."
)

# How often the streaming assistant row is flushed to the DB while tokens are
# still arriving — frequent enough that a refresh loses at most a fraction of
# a second of text, infrequent enough not to hammer the DB per-token.
_FLUSH_INTERVAL_SECONDS = 0.3


def _system_prompt(project: Project, memory_entries: list[MemoryEntry]) -> str:
    profile = project.business_profile
    memory_section = (
        "\n\nWhat you remember about this user across all projects:\n"
        + "\n".join(f"- {m.content}" for m in memory_entries)
        if memory_entries
        else ""
    )
    return (
        "You are a business analyst assistant helping the user develop a feasibility "
        f"study for their project, \"{project.name}\".\n\n"
        "Business profile on file:\n"
        f"- Description: {profile.business_description}\n"
        f"- Problem: {profile.problem_statement or 'unknown'}\n"
        f"- Unique value proposition: {profile.unique_value_proposition or 'unknown'}\n"
        f"- Target market: {profile.target_market_description or 'unknown'} "
        f"({profile.target_market_geography or 'geography unknown'})\n"
        f"- Business model: {profile.business_model_type or 'unknown'}\n"
        f"- Pricing: {profile.pricing_unit_price} {profile.pricing_currency} "
        f"({profile.pricing_model or 'model unspecified'})\n"
        f"- Competitors: {', '.join(c['name'] for c in profile.competitors) or 'none listed'}\n"
        f"- Study goal: {profile.study_goal or 'unknown'}\n\n"
        "The feasibility study is a collection of INDEPENDENT capabilities, each "
        "with its own dedicated tool — it is NOT one bulk operation you run by "
        "default. Map exactly what the user names to exactly one tool:\n"
        "  - market sizing / TAM / SAM / SOM / market opportunity -> run_market_sizing_tool\n"
        "  - competitors / competitive landscape / competitor analysis -> run_competitive_analysis_tool\n"
        "  - financials / costs / break-even / ROI / financial model -> run_financial_analysis_tool\n"
        "  - risks / risk profile / risk analysis -> run_risk_analysis_tool\n"
        "  - verdict / recommendation / executive summary -> run_synthesis_tool\n"
        "  - the WHOLE study/report as a single unit -> run_feasibility_study_tool\n"
        "DEFAULT RULE: if the user names ONE specific capability from the list "
        "above, call ONLY that capability's own tool — never "
        "run_feasibility_study_tool. Only call run_feasibility_study_tool when "
        "the user's phrasing clearly refers to the study/report AS A WHOLE (e.g. "
        "'run the full feasibility study', 'build the complete report', 'do the "
        "whole analysis') or explicitly lists multiple/all capabilities "
        "together. A message about one topic — 'run competitor analysis', "
        "'just check the market', 'what's the risk profile', 'analyze the "
        "competition only' — is ALWAYS a single-capability request: call that "
        "one tool and nothing else, even though that capability happens to "
        "also be part of the full pipeline. When genuinely unsure, prefer the "
        "single narrower tool over the full study — it is far cheaper to run "
        "one more tool afterward than to run everything when only one part was "
        "wanted. Note that run_risk_analysis_tool and run_synthesis_tool still "
        "compute their own prerequisite sections first (risk needs market "
        "sizing + competitive analysis + financial modeling; synthesis needs "
        "risk too) — mention that if relevant, but this does not change which "
        "single tool to call. If study data "
        "is already provided below, answer follow-up questions about it (e.g. "
        "about specific competitors, financial figures, or risks) directly from "
        "that data instead of calling a tool again — only call a tool when the "
        "user explicitly asks to run, build, refresh, or redo a capability (or "
        "the whole study), or when no study data is available yet. Use the "
        "update_business_profile tool when the user reveals new or corrected "
        "information about the business that should be saved. Use the "
        "remember_fact_tool when the user states a durable preference or fact "
        "about themselves or their business that would be useful in *future* "
        "conversations and other projects (not just this one) — e.g. their name, "
        "role, industry background, or a stated preference for how you should "
        "respond. Do not use it for facts that only matter to this project's "
        "business profile; use update_business_profile for those instead. "
        "Whenever your answer includes meaningful numerical or quantitative "
        "data suited to visual comparison — figures across categories or "
        "competitors, a trend over time, a proportional breakdown — call "
        "generate_chart_tool to render an actual chart, IN ADDITION TO your "
        "normal text reply, rather than only describing the numbers in "
        "prose. This applies whether the data came from a study section "
        "already generated or from your own analysis in this conversation. "
        "Skip it for a single standalone number with nothing to compare "
        "against. Keep "
        "replies concise and focused on helping the user reason about this "
        "business idea." + memory_section
    )


# Fields that matter for report generation / QC (source citations, financial
# calculation traces, per-claim sourcing classification, raw search queries)
# but are pure noise for the model answering a natural-language follow-up
# question — stripped out to keep the injected study digest compact.
_STUDY_CONTEXT_VERBOSE_KEYS = frozenset(
    {"citations", "calculation_trace", "claim_type", "claim_types", "search_queries_used", "methodology"}
)


def _trim_for_context(value: object) -> object:
    if isinstance(value, dict):
        return {k: _trim_for_context(v) for k, v in value.items() if k not in _STUDY_CONTEXT_VERBOSE_KEYS}
    if isinstance(value, list):
        return [_trim_for_context(v) for v in value]
    return value


def _study_context_block(study: StudyResult) -> str:
    """Compact digest of a completed study's section data, appended to the
    system prompt so the model can answer follow-up questions (e.g. "tell me
    about the competitors") directly from real data instead of its only
    option being to re-run the whole pipeline — see get_latest_study_id_for_session."""
    parts = []
    for section_name, envelope in (study.sections or {}).items():
        if section_name == "glossary":
            continue  # term definitions aren't useful as Q&A context
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not data:
            continue
        parts.append(f"### {section_name}\n{json.dumps(_trim_for_context(data), ensure_ascii=False)}")

    if not parts:
        return ""

    return (
        "\n\nData from the most recently completed feasibility study for this "
        f"project (verdict: {study.verdict}, confidence: {study.confidence_score}):\n\n"
        + "\n\n".join(parts)
    )


_PHASE_TO_SECTION = {
    "market_sizing": "market_overview",
    "competitive": "competitive_landscape",
    "financial": "financial_feasibility",
    "risk": "risk_assessment",
    "synthesis": "executive_summary",
}


def _build_tools(
    db: Session,
    project: Project,
    queue: EventQueue,
    session: ChatSession,
    assistant_message: ChatMessage,
    project_id: str,
) -> list:
    """Every tool below is self-contained: it catches its own exceptions,
    emits CHAT_TOOL_ERROR on failure, and persists its own ChatMessage(role=
    "tool") row via `_finish_tool_call` — rather than the caller (run_chat_turn
    / the tool-calling loop) doing this after the fact. This is deliberate: the
    legacy manual loop and the deep-agent code path have very different tool-
    execution telemetry (the deep agent's LangGraph ToolNode executes tools
    internally; reverse-engineering its "updates" stream to extract per-call
    results/errors would depend on unstable internals), but both paths call
    the exact same `tool.ainvoke(...)` — so putting the side effects inside the
    tool itself makes them path-independent for free."""

    async def _finish_tool_call(
        tool_name: str, content: str, study_id: str | None = None, chart_data: dict | None = None
    ) -> str:
        tool_message_row = ChatMessage(
            role="tool", content=content, tool_name=tool_name, status="complete",
            study_id=study_id, chart_data=chart_data,
        )
        session.messages.append(tool_message_row)
        # Heartbeat the assistant placeholder row too — a single tool call
        # (e.g. the full feasibility-study pipeline) can run far longer than
        # the streaming flush interval, and the stuck-generation sweep in
        # app.main relies on updated_at staying fresh.
        assistant_message.updated_at = datetime.utcnow()
        db.commit()
        if chart_data is not None:
            # Live push, mirroring SECTION_READY — a page reload instead
            # picks the chart back up from the persisted chart_data column.
            await queue.put(
                SSEEvent.CHAT_CHART_READY,
                {"message_id": tool_message_row.id, "tool_name": tool_name, "chart": chart_data},
            )
        return content

    async def _run_tool_safely(tool_name: str, body) -> str:
        try:
            content, study_id, chart_data = await body()
        except Exception as exc:
            # A DB write failing inside `body()` (e.g. a flush error) leaves
            # the session in a pending-rollback state — clear it before any
            # further ORM use (including the log line below, which doesn't
            # touch the session, but _finish_tool_call's commit right after
            # does) or that write would itself raise PendingRollbackError,
            # masking the real error entirely.
            db.rollback()
            logger.warning("Chat tool '%s' failed for project %s: %s", tool_name, project_id, exc)
            await queue.put(SSEEvent.CHAT_TOOL_ERROR, {"tool_name": tool_name, "error": str(exc)})
            content, study_id, chart_data = f"Error running {tool_name}: {exc}", None, None
        return await _finish_tool_call(tool_name, content, study_id, chart_data)

    @tool
    async def run_feasibility_study_tool() -> str:
        """Run the COMPLETE, FULL feasibility study pipeline — market sizing,
        competitive analysis, financial modeling, risk assessment, AND the
        executive-summary synthesis — for this project's business profile.

        ONLY use this when the user explicitly asks for the whole study/
        report as a single unit — e.g. "run the full feasibility study",
        "build the complete report", "give me the whole analysis". If the
        user names just ONE specific capability (market sizing, competitive/
        competitor analysis, financial analysis, risk analysis, or the
        verdict/executive summary alone), you MUST use that capability's own
        dedicated tool below instead — do NOT call this tool for a request
        about a single topic, even if that topic happens to be one of this
        pipeline's phases. When genuinely unsure whether the user wants one
        section or the whole thing, prefer the single narrower tool — it's
        far cheaper to run again for something extra than to run everything
        when only one part was wanted. Each run creates a new, independently
        viewable study — past runs are kept, not overwritten."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            result = await run_feasibility_study(db, project, queue)
            if result.status == "failed":
                return f"Study failed: {result.error}", result.id, None
            return (
                f"Study completed. Verdict: {result.verdict}. "
                f"Confidence score: {result.confidence_score}. "
                f"Sections generated: {', '.join(result.sections.keys())}."
            ), result.id, None

        return await _run_tool_safely("run_feasibility_study_tool", _inner)

    def _make_single_phase_tool_body(phase: str, label: str):
        async def _inner() -> tuple[str, str | None, dict | None]:
            result = await run_single_phase_study(db, project, phase, queue)
            if result.status == "failed":
                return f"{label} failed: {result.error}", result.id, None
            section = _PHASE_TO_SECTION[phase]
            if section not in (result.sections or {}):
                return (
                    f"{label} completed, but that section didn't come back — "
                    f"sections generated this run: {', '.join(result.sections.keys())}."
                ), result.id, None
            return (
                f"{label} completed. Sections generated this run: "
                f"{', '.join(result.sections.keys())}."
            ), result.id, None

        return _inner

    @tool
    async def run_market_sizing_tool() -> str:
        """Run ONLY market sizing (TAM/SAM/SOM estimation) for this project —
        nothing else in the pipeline. Use this whenever the user asks about
        market size, TAM/SAM/SOM, or market opportunity specifically, without
        asking for the full study. Does not run competitive analysis,
        financial modeling, risk assessment, or synthesis. Each run creates a
        new, independently viewable partial study."""
        return await _run_tool_safely(
            "run_market_sizing_tool", _make_single_phase_tool_body("market_sizing", "Market sizing")
        )

    @tool
    async def run_competitive_analysis_tool() -> str:
        """Run ONLY competitive/competitor analysis for this project — nothing
        else in the pipeline. Use this whenever the user asks about
        competitors, competitive landscape, or competitor analysis
        specifically (however phrased — "competition analysis", "who are my
        competitors", etc.), without asking for the full study. Does not run
        market sizing, financial modeling, risk assessment, or synthesis.
        Each run creates a new, independently viewable partial study."""
        return await _run_tool_safely(
            "run_competitive_analysis_tool",
            _make_single_phase_tool_body("competitive", "Competitive analysis"),
        )

    @tool
    async def run_financial_analysis_tool() -> str:
        """Run ONLY financial modeling (capex/opex, break-even, ROI, NPV,
        sensitivity, cash flow) for this project — nothing else in the
        pipeline. Use this whenever the user asks about financials, costs,
        break-even, ROI, or the financial model specifically, without asking
        for the full study. Does not run market sizing, competitive analysis,
        risk assessment, or synthesis. Each run creates a new, independently
        viewable partial study."""
        return await _run_tool_safely(
            "run_financial_analysis_tool", _make_single_phase_tool_body("financial", "Financial analysis")
        )

    @tool
    async def run_risk_analysis_tool() -> str:
        """Run ONLY risk assessment for this project — nothing else in the
        pipeline. Use this whenever the user asks about risks, risk profile,
        or risk analysis specifically, without asking for the full study.
        This still computes market sizing, competitive analysis, and
        financial modeling first as inputs risk assessment depends on —
        mention that if relevant — but does NOT run synthesis. Each run
        creates a new, independently viewable partial study."""
        return await _run_tool_safely(
            "run_risk_analysis_tool", _make_single_phase_tool_body("risk", "Risk analysis")
        )

    @tool
    async def run_synthesis_tool() -> str:
        """Run ONLY the executive-summary synthesis (verdict + confidence
        score) for this project. Use this when the user asks specifically for
        the verdict, recommendation, or executive summary, without asking for
        the full study. This still computes market sizing, competitive
        analysis, financial modeling, and risk assessment first as inputs
        synthesis depends on — mention that if relevant. Each run creates a
        new, independently viewable partial study."""
        return await _run_tool_safely(
            "run_synthesis_tool", _make_single_phase_tool_body("synthesis", "Synthesis")
        )

    @tool
    async def update_business_profile_tool(
        business_description: str | None = None,
        problem_statement: str | None = None,
        unique_value_proposition: str | None = None,
        target_market_description: str | None = None,
        target_market_geography: str | None = None,
        target_market_type: str | None = None,
        business_model_type: str | None = None,
        capex_amount: float | None = None,
        capex_currency: str | None = None,
        funding_source: str | None = None,
        opex_monthly_amount: float | None = None,
        opex_monthly_currency: str | None = None,
        pricing_unit_price: float | None = None,
        pricing_currency: str | None = None,
        pricing_model: str | None = None,
        expected_monthly_sales: float | None = None,
        founder_risks: str | None = None,
        team_size: int | None = None,
        key_roles_needed: list[str] | None = None,
        marketing_channels: list[str] | None = None,
        study_goal: str | None = None,
    ) -> str:
        """Update the project's business profile with new or corrected
        information the user reveals during the conversation. Only pass the
        fields that should change; omit everything else."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            # The tool call always binds every parameter (unprovided ones default
            # to None), so forwarding them all straight into BusinessProfileUpdate
            # would make Pydantic treat every field as explicitly "set to None" —
            # defeating update_business_profile's exclude_unset PATCH semantics
            # and overwriting NOT NULL columns with NULL. Filter to only the
            # fields actually provided.
            provided = {
                "business_description": business_description,
                "problem_statement": problem_statement,
                "unique_value_proposition": unique_value_proposition,
                "target_market_description": target_market_description,
                "target_market_geography": target_market_geography,
                "target_market_type": target_market_type,
                "business_model_type": business_model_type,
                "capex_amount": capex_amount,
                "capex_currency": capex_currency,
                "funding_source": funding_source,
                "opex_monthly_amount": opex_monthly_amount,
                "opex_monthly_currency": opex_monthly_currency,
                "pricing_unit_price": pricing_unit_price,
                "pricing_currency": pricing_currency,
                "pricing_model": pricing_model,
                "expected_monthly_sales": expected_monthly_sales,
                "founder_risks": founder_risks,
                "team_size": team_size,
                "key_roles_needed": key_roles_needed,
                "marketing_channels": marketing_channels,
                "study_goal": study_goal,
            }
            non_null = {k: v for k, v in provided.items() if v is not None}
            if not non_null:
                return "No fields provided — nothing updated.", None, None
            patch = BusinessProfileUpdate(**non_null)
            update_business_profile(db, project.business_profile, patch)
            return "Business profile updated.", None, None

        return await _run_tool_safely("update_business_profile_tool", _inner)

    @tool
    async def remember_fact_tool(content: str) -> str:
        """Persist a short, durable fact or preference about the user or their
        business that should be remembered in ALL future conversations across
        ALL projects (not just this one) — e.g. "prefers metric units", "is
        based in Cairo", "runs a family business with 2 co-founders". Do not
        call this for facts that only apply to the current project's business
        profile — use update_business_profile for those instead."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            add_memory_entry(db, content, source="agent_extracted")
            return "Noted — I'll remember that.", None, None

        return await _run_tool_safely("remember_fact_tool", _inner)

    @tool
    async def generate_chart_tool(
        chart_type: Literal["bar", "line", "pie"],
        title: str,
        categories: list[str],
        series: list[dict],
        x_label: str | None = None,
        y_label: str | None = None,
    ) -> str:
        """Generate an actual chart to visualize numerical/quantitative data
        instead of only describing it in text — call this whenever your
        reply includes data suited to visual comparison: values across
        categories or competitors, a trend over time, or a proportional
        breakdown. Use "bar" for comparing values across categories/items,
        "line" for a trend across an ordered sequence (e.g. months/years),
        "pie" for parts of a whole. `categories` are the x-axis labels (bar/
        line) or slice labels (pie). `series` is a list of
        {"name": str, "data": [numbers matching categories 1:1, same order,
        None for a missing value]} — usually just one series, more than one
        only when genuinely comparing multiple series side by side (e.g.
        this year vs last year). Prefer one focused chart over cramming
        unrelated data into one; call this again for a second chart if truly
        needed. Do not call this for a single number with nothing to
        compare it against — plain text is fine for that."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            try:
                spec = ChartSpec(
                    chart_type=chart_type,
                    title=title,
                    categories=categories,
                    series=[ChartSeries(**s) for s in series],
                    x_label=x_label,
                    y_label=y_label,
                )
            except ValidationError as exc:
                return f"Chart generation failed: invalid chart data ({exc}).", None, None
            return f"Chart generated: {title}.", None, spec.model_dump()

        return await _run_tool_safely("generate_chart_tool", _inner)

    return [
        run_feasibility_study_tool,
        run_market_sizing_tool,
        run_competitive_analysis_tool,
        run_financial_analysis_tool,
        run_risk_analysis_tool,
        run_synthesis_tool,
        update_business_profile_tool,
        remember_fact_tool,
        generate_chart_tool,
    ]


def _load_history_messages(session: ChatSession) -> list:
    """Replays prior turns for the LLM call. Persisted "tool" rows are skipped
    here — the assistant's natural-language reply that followed each tool call
    already narrates the outcome, and reconstructing a valid ToolMessage would
    need the original tool_call_id, which isn't persisted. Live tool calls made
    *within* the current turn still use real ToolMessage objects (see
    run_chat_turn) — only cross-request replay is folded down like this."""
    messages: list = []
    for m in session.messages:
        if m.deleted_at is not None:
            continue
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            messages.append(AIMessage(content=m.content))
    return messages


def _extract_text(content: object) -> str:
    """ChatGoogleGenerativeAI's AIMessage.content is sometimes a plain str and
    sometimes a list of content blocks (e.g. a text block plus a signature/
    thought block) — normalize to plain text for storage in ChatMessage.content
    (a Text column, which can't bind a list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return "" if content is None else str(content)


def _build_llm() -> ChatGoogleGenerativeAI:
    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.reasoning_model,
        google_api_key=settings.google_api_key,
        temperature=0,
    )


async def _run_legacy_tool_loop(
    tools: list,
    tool_by_name: dict,
    restricted: str | None,
    history: list,
    queue: EventQueue,
    assistant_message: ChatMessage,
    db: Session,
    project_id: str,
    session: ChatSession,
) -> str:
    """The original hand-rolled bounded tool-calling loop (MAX_TOOL_ROUNDS),
    used when settings.deepagents_enabled is False. Tool execution itself no
    longer persists a ChatMessage row here — every tool in _build_tools does
    that itself now — but a tool call that fails before even reaching its own
    body (e.g. bad args, unknown tool name) still needs a fallback here."""
    if restricted == "none":
        llm = _build_llm()
    elif restricted:
        llm = _build_llm().bind_tools([tool_by_name[restricted]])
    else:
        llm = _build_llm().bind_tools(tools)

    for round_num in range(MAX_TOOL_ROUNDS):
        response = None
        last_flush = time.monotonic()
        async for chunk in llm.astream(history):
            response = chunk if response is None else response + chunk
            delta_text = _extract_text(chunk.content)
            if delta_text:
                await queue.put(SSEEvent.CHAT_MESSAGE_DELTA, {"content": delta_text})
            now = time.monotonic()
            if now - last_flush >= _FLUSH_INTERVAL_SECONDS:
                assistant_message.content = _extract_text(response.content)
                assistant_message.status = "streaming"
                db.commit()
                last_flush = now

        # Flush whatever this round produced even if it never hit the
        # throttle interval above (e.g. a short reply, or the tail end
        # after the last throttled flush).
        assistant_message.content = _extract_text(response.content)
        assistant_message.status = "streaming"
        db.commit()

        if not response.tool_calls:
            return assistant_message.content

        history.append(response)
        for call in response.tool_calls:
            tool_fn = tool_by_name.get(call["name"])
            try:
                if tool_fn is None:
                    raise ValueError(f"Unknown tool: {call['name']}")
                tool_result = await tool_fn.ainvoke(call["args"])
            except Exception as exc:
                # The tool itself never got to run (bad args, unknown name) —
                # every other failure is already caught and persisted inside
                # the tool's own body (see _build_tools's _run_tool_safely).
                # Roll back first — a failed flush inside tool_fn.ainvoke
                # leaves the session in a pending-rollback state, and the
                # ChatMessage insert below would otherwise raise
                # PendingRollbackError instead of recording the real error.
                db.rollback()
                logger.warning(
                    "Chat tool '%s' failed for project %s: %s", call["name"], project_id, exc
                )
                await queue.put(SSEEvent.CHAT_TOOL_ERROR, {"tool_name": call["name"], "error": str(exc)})
                tool_result = f"Error running {call['name']}: {exc}"
                session.messages.append(
                    ChatMessage(role="tool", content=str(tool_result), tool_name=call["name"], status="complete")
                )
                db.commit()

            history.append(ToolMessage(content=str(tool_result), tool_call_id=call["id"]))

    logger.warning(
        "Chat tool loop hit the %s-round cap for project %s without a final reply",
        MAX_TOOL_ROUNDS,
        project_id,
    )
    return _FALLBACK_MESSAGE


async def _run_deep_agent_turn(
    tools: list,
    tool_by_name: dict,
    restricted: str | None,
    system_prompt: str,
    history: list,
    queue: EventQueue,
    assistant_message: ChatMessage,
    db: Session,
    project_id: str,
    settings,
) -> str:
    """Runs the chat turn on the Deep Agents runtime: create_deep_agent with
    no write_todos/virtual-FS (3-4 tools, mostly single-tool turns — the
    planning/filesystem overhead isn't earning its keep here), tool-intent
    restriction applied via middleware instead of pre-binding the model, and
    checkpointer=None PERMANENTLY — the app's resume-after-refresh mechanism
    is DB-row-based (a ChatMessage row polled by resume_chat_message_stream_
    endpoint), fully decoupled from any in-memory agent state, so LangGraph
    checkpointing must never be wired in here; the two would become
    divergent sources of truth for the same thing."""
    from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
    from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
    from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
    from langgraph.errors import GraphRecursionError

    from app.services.chat_middleware import ToolIntentRestrictionMiddleware
    from deepagents import create_deep_agent

    agent = create_deep_agent(
        model=_build_llm(),
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            ToolIntentRestrictionMiddleware(restricted, tool_by_name),
            ModelCallLimitMiddleware(run_limit=settings.chat_model_call_limit, exit_behavior="error"),
            ToolCallLimitMiddleware(run_limit=settings.chat_model_call_limit * 3, exit_behavior="error"),
        ],
        checkpointer=None,
    )

    response_msg = None
    last_flush = time.monotonic()
    try:
        async for mode, chunk in agent.astream({"messages": history}, stream_mode=["messages", "updates"]):
            if mode == "updates":
                if "tools" in chunk:
                    # A tool round just completed — the NEXT "model" chunks
                    # start a fresh reply; accumulating across this boundary
                    # would concatenate an earlier round's (often empty, or
                    # preamble) text with the final answer.
                    response_msg = None
                continue

            message_chunk, metadata = chunk
            if metadata.get("langgraph_node") != "model":
                continue

            response_msg = message_chunk if response_msg is None else response_msg + message_chunk
            delta_text = _extract_text(message_chunk.content)
            if delta_text:
                await queue.put(SSEEvent.CHAT_MESSAGE_DELTA, {"content": delta_text})
            now = time.monotonic()
            if now - last_flush >= _FLUSH_INTERVAL_SECONDS:
                assistant_message.content = _extract_text(response_msg.content)
                assistant_message.status = "streaming"
                db.commit()
                last_flush = now
    except (ModelCallLimitExceededError, ToolCallLimitExceededError, GraphRecursionError) as exc:
        logger.warning(
            "Chat deep agent hit its call-budget limit for project %s: %s", project_id, exc
        )
        return _FALLBACK_MESSAGE

    if response_msg is None:
        return ""
    return _extract_text(response_msg.content)


@traceable(name="Chat Turn", run_type="chain")
async def run_chat_turn(
    db: Session,
    project: Project,
    session: ChatSession,
    user_content: str,
    queue: EventQueue,
) -> ChatMessage:
    """Persists the user's message, runs the tool-calling turn (either the
    legacy bounded manual loop or the Deep Agents runtime, depending on
    settings.deepagents_enabled), persists every intermediate tool call and
    the final assistant reply, and emits CHAT_MESSAGE_COMPLETED when done.
    Tool errors are caught, reported via CHAT_TOOL_ERROR, and fed back to the
    model as a tool result rather than crashing the turn.

    The assistant's reply is persisted as a single ChatMessage row created
    up front (status="pending") and updated in place as text streams in
    (status="streaming") and finally completes (status="complete") or fails
    (status="error") — this is the row a client reconnecting after a page
    refresh finds and resumes via get_active_generation / the resume-stream
    endpoint, so no already-generated text is ever lost to a disconnect."""
    # Captured once, up front, and used for all logging from here on instead
    # of re-touching project.id later — after a failed flush/commit anywhere
    # below, the session enters a pending-rollback state, and accessing a
    # lazy ORM attribute like project.id in that state raises
    # PendingRollbackError itself, masking the original error entirely.
    project_id = project.id

    user_message = ChatMessage(role="user", content=user_content, status="complete")
    session.messages.append(user_message)
    maybe_set_title(session, user_content)
    db.commit()

    assistant_message = ChatMessage(role="assistant", content="", status="pending")
    session.messages.append(assistant_message)
    db.commit()

    settings = get_settings()
    tools = _build_tools(db, project, queue, session, assistant_message, project_id)
    tool_by_name = {t.name: t for t in tools}

    restricted = await detect_single_tool_intent(
        user_content,
        {name: t.description for name, t in tool_by_name.items()},
        google_api_key=settings.google_api_key,
        cheap_model=settings.cheap_model,
    )

    memory_entries = list_memory_entries(db)
    system_prompt = _system_prompt(project, memory_entries)
    latest_study_id = get_latest_study_id_for_session(db, session)
    if latest_study_id:
        latest_study = db.query(StudyResult).filter_by(id=latest_study_id).one_or_none()
        if latest_study is not None:
            system_prompt += _study_context_block(latest_study)

    history: list = [SystemMessage(content=system_prompt)]
    history.extend(_load_history_messages(session))

    try:
        if settings.deepagents_enabled:
            final_text = await _run_deep_agent_turn(
                tools, tool_by_name, restricted, system_prompt, history, queue,
                assistant_message, db, project_id, settings,
            )
        else:
            final_text = await _run_legacy_tool_loop(
                tools, tool_by_name, restricted, history, queue, assistant_message, db, project_id, session,
            )

        assistant_message.content = final_text
        assistant_message.status = "complete"
        db.commit()
        await queue.put(
            SSEEvent.CHAT_MESSAGE_COMPLETED,
            {
                "message_id": assistant_message.id,
                "role": "assistant",
                "content": assistant_message.content,
            },
        )
        return assistant_message
    except Exception as exc:
        # A mid-commit failure leaves the session in a pending-rollback state —
        # clear it before ANY further ORM use, including the log line below
        # (project_id is a plain string precisely so logging never needs a
        # session round-trip, but assistant_message.content does). Skipping
        # this, or rolling back only after logging, would raise
        # PendingRollbackError right here and mask the original error
        # entirely — which is exactly what happened before this was fixed.
        # This also reloads assistant_message.content back to its last
        # successfully committed (i.e. already-streamed) value, which is
        # deliberately preserved below rather than discarded.
        db.rollback()
        logger.exception("Chat turn failed for project %s", project_id)
        if assistant_message.content:
            assistant_message.content += f"\n\n[Something went wrong finishing this reply: {exc}]"
        else:
            assistant_message.content = f"Something went wrong handling that message: {exc}"
        assistant_message.status = "error"
        db.commit()
        await queue.put(SSEEvent.CHAT_TOOL_ERROR, {"tool_name": "chat_turn", "error": str(exc)})
        await queue.put(
            SSEEvent.CHAT_MESSAGE_COMPLETED,
            {
                "message_id": assistant_message.id,
                "role": "assistant",
                "content": assistant_message.content,
            },
        )
        return assistant_message
