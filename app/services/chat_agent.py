from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.financial import FinancialCalcError, run_full_financial_model
from app.agents.intake import IntakeHardBlockError
from app.config import get_settings
from app.models import Artifact, ChatMessage, ChatSession, MemoryEntry, Project, StudyResult
from app.schemas.artifact import (
    ArtifactSummary,
    DocumentOutline,
    DocumentSection,
    PresentationOutline,
    SlideContent,
)
from app.schemas.chart import ChartSeries, ChartSpec
from app.schemas.intake import FeasibilityStartRequest, Source
from app.schemas.project import BusinessProfileUpdate
from app.services.artifact_generation import (
    ArtifactGenerationError,
    generate_docx,
    generate_pdf,
    generate_pptx,
)
from app.services.artifact_generation import revise_artifact as run_artifact_revision
from app.services.chat import get_latest_study_id_for_session, maybe_set_title
from app.services.export import build_study_markdown, synthesize_chat_export
from app.services.memory import add_memory_entry, list_memory_entries
from app.services.project import populate_business_profile, update_business_profile
from app.services.study import run_feasibility_study, run_single_phase_study
from app.services.tool_intent import detect_single_tool_intent
from app.sse import EventQueue, SSEEvent
from app.tools import web_search

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


def _bootstrap_system_prompt(memory_entries: list[MemoryEntry]) -> str:
    """Used while project.business_profile is still None — chat's job right
    now is to have a natural conversation and build the profile for the
    first time via bootstrap_profile_tool, not to answer questions about
    data that doesn't exist yet (see _build_tools's profile-existence
    branch, which only offers bootstrap_profile_tool and web_research_tool
    until this succeeds)."""
    memory_section = (
        "\n\nWhat you remember about this user across all projects:\n"
        + "\n".join(f"- {m.content}" for m in memory_entries)
        if memory_entries
        else ""
    )
    return (
        "You are a business analyst assistant. This is a brand new project "
        "with no business profile yet — your job right now is to have a "
        "natural conversation to learn about the user's business idea, not "
        "to fill out a form. If they haven't described their business yet, "
        "ask them to in their own words. As they talk, use web_research_tool "
        "to look things up that help you ask better questions (e.g. typical "
        "pricing or costs for this kind of business) instead of asking cold. "
        "Once you have at least a clear description of the business AND a "
        "price per unit/subscription/transaction, call bootstrap_profile_tool "
        "with everything you've learned so far — pass every field you "
        "already know, not just those two. If bootstrap_profile_tool tells "
        "you it still needs the price, ask the user for it and call the tool "
        "again once you have it. Keep the conversation natural — a couple of "
        "questions at a time, not an interrogation." + memory_section
    )


# Fields with an objective, look-up-able answer — chat may research these
# itself (via web_research_tool) if the user doesn't know. capex/opex/
# expected_monthly_sales are reconsidered when flagged low_confidence (an
# earlier rough estimate); competitors when the list is still empty.
_RESEARCHABLE_GAP_LABELS: dict[str, str] = {
    "competitors": "competitors",
    "capex_low_confidence": "capex (currently just a rough estimate)",
    "opex_monthly_low_confidence": "monthly opex (currently just a rough estimate)",
    "expected_monthly_sales_low_confidence": "expected monthly sales (currently just a rough estimate)",
}

# Everything else patchable is a decision only the founder can make — chat
# must ask, never silently fabricate an answer for these.
_DECISION_GAP_FIELDS: list[tuple[str, str]] = [
    ("problem_statement", "the problem this business solves"),
    ("unique_value_proposition", "what makes this business different from alternatives"),
    ("target_market_description", "who the target customer is"),
    ("target_market_geography", "the target geography"),
    ("target_market_type", "B2C or B2B"),
    ("business_model_type", "the business model (SaaS, marketplace, etc.)"),
    ("funding_source", "how the business is funded"),
    ("founder_risks", "risks or concerns the founder has"),
    ("team_size", "current or planned team size"),
    ("key_roles_needed", "key roles/hires needed"),
    ("marketing_channels", "sales/marketing channels"),
    ("study_goal", "the purpose of this study"),
    ("pricing_model", "the pricing model (subscription, one-time, etc.)"),
]


def _profile_gaps(profile) -> tuple[list[str], list[str]]:
    """Returns (researchable, decision) — human-readable descriptions of
    still-missing or low-confidence fields, for _system_prompt's gap
    section. Recomputed fresh from the DB (not conversation memory) every
    turn, so an already-answered field is never re-listed, in this session
    or any future one."""
    researchable = []
    if not profile.competitors:
        researchable.append(_RESEARCHABLE_GAP_LABELS["competitors"])
    for flag_field, label in _RESEARCHABLE_GAP_LABELS.items():
        if flag_field != "competitors" and getattr(profile, flag_field):
            researchable.append(label)

    decision = [
        description
        for field, description in _DECISION_GAP_FIELDS
        if getattr(profile, field) in (None, "", [])
    ]
    return researchable, decision


_ARTIFACT_CAPABILITY_SECTION = (
    "Use generate_presentation_tool when the user asks for a presentation, "
    "slide deck, or slides on a topic (e.g. \"make a 10-slide deck about "
    "X\"). Use generate_word_document_tool when they ask to create/write a "
    "Word document or report. Use generate_pdf_report_tool when they ask "
    "for a PDF specifically. Use revise_artifact_tool when they ask to "
    "change, shorten, expand, or otherwise edit a document/deck you already "
    "generated — never regenerate one of the tools above from scratch for "
    "an edit request. "
)


def _system_prompt(project: Project, memory_entries: list[MemoryEntry]) -> str:
    profile = project.business_profile
    researchable_gaps, decision_gaps = _profile_gaps(profile)
    artifact_section = _ARTIFACT_CAPABILITY_SECTION if get_settings().mcp_artifacts_enabled else ""
    gap_section = ""
    if researchable_gaps or decision_gaps:
        gap_section = "\n\nStill missing from this profile:\n"
        if decision_gaps:
            gap_section += (
                "- Ask the user about (only the founder can answer these): "
                + "; ".join(decision_gaps) + "\n"
            )
        if researchable_gaps:
            gap_section += (
                "- You may research these yourself if the user doesn't know: "
                + "; ".join(researchable_gaps) + "\n"
            )
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
        f"- Study goal: {profile.study_goal or 'unknown'}\n"
        + gap_section + "\n"
        "This business profile persists across every chat session for this "
        "project — anything already filled in above is already known; never "
        "ask about it again in this or any future session. When it's "
        "natural in the conversation, weave in at most one or two questions "
        "at a time about the 'still missing' items above — not an "
        "interrogation. If the user says they don't know something listed "
        "under 'you may research', use web_research_tool then call "
        "update_business_profile with source=\"estimated\" to save what you "
        "find — don't leave it blank. If they don't know something you must "
        "ask them, offer a clarifying question or suggestion instead of "
        "researching it yourself, and move on rather than blocking the "
        "conversation if it stays unknown.\n\n"
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
        "Use web_research_tool for an open-ended market/industry question "
        "that isn't already answered by the data above — cite the source "
        "URL for every claim you build from it. Use explain_figure_tool "
        "when the user asks how a specific number/figure was derived or "
        "why it is what it is (e.g. 'why is break-even at month 8') — never "
        "re-derive it yourself. Use run_scenario_simulation_tool for a "
        "'what if' question about a financial input (price, capex, opex, "
        "expected sales) — it never runs a new study or changes saved data, "
        "it only shows a hypothetical comparison; follow it with "
        "generate_chart_tool to visualize baseline vs. scenario. "
        "Whenever your answer includes meaningful numerical or quantitative "
        "data suited to visual comparison — figures across categories or "
        "competitors, a trend over time, a proportional breakdown — call "
        "generate_chart_tool to render an actual chart, IN ADDITION TO your "
        "normal text reply, rather than only describing the numbers in "
        "prose. This applies whether the data came from a study section "
        "already generated or from your own analysis in this conversation. "
        "Skip it for a single standalone number with nothing to compare "
        "against. " + artifact_section + "Keep "
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


def _find_figure_data(data: object, needle: str) -> object | None:
    """Walks a section's raw (untrimmed) data looking for a figure matching
    needle — a dict key that contains it, or a list item whose name/
    category/title-like field matches — used by explain_figure_tool, which
    (unlike the system-prompt digest) needs the untrimmed calculation_trace/
    citations/methodology this deliberately doesn't strip."""
    if isinstance(data, dict):
        for key, value in data.items():
            if needle in key.lower().replace("_", " "):
                return {key: value}
        for label_key in ("name", "category", "title", "risk_description"):
            label = data.get(label_key)
            if isinstance(label, str) and needle in label.lower():
                return data
        for value in data.values():
            found = _find_figure_data(value, needle)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_figure_data(item, needle)
            if found is not None:
                return found
    return None


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
        tool_name: str,
        content: str,
        study_id: str | None = None,
        chart_data: dict | None = None,
        artifact: dict | None = None,
    ) -> str:
        tool_message_row = ChatMessage(
            role="tool", content=content, tool_name=tool_name, status="complete",
            study_id=study_id, chart_data=chart_data,
            artifact_id=artifact["id"] if artifact else None,
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
        if artifact is not None:
            # Live push, mirroring the chart branch above — a page reload
            # instead picks the artifact card back up via ChatMessage.artifact_id.
            await queue.put(
                SSEEvent.CHAT_ARTIFACT_READY,
                {"message_id": tool_message_row.id, "tool_name": tool_name, "artifact": artifact},
            )
        return content

    async def _run_tool_safely(tool_name: str, body) -> str:
        try:
            result = await body()
        except Exception as exc:
            # A DB write failing inside `body()` (e.g. a flush error) leaves
            # the session in a pending-rollback state — clear it before any
            # further ORM use (including the log line below, which doesn't
            # touch the session, but _finish_tool_call's commit right after
            # does) or that write would itself raise PendingRollbackError,
            # masking the real error entirely.
            db.rollback()
            # exc_info=True (not just str(exc)) matters here: an anyio
            # TaskGroup/ExceptionGroup's str() collapses to a useless
            # "unhandled errors in a TaskGroup (N sub-exception(s))" —
            # exc_info is what actually surfaces the wrapped cause(s) in the
            # logs.
            logger.warning(
                "Chat tool '%s' failed for project %s: %s", tool_name, project_id, exc, exc_info=True
            )
            await queue.put(SSEEvent.CHAT_TOOL_ERROR, {"tool_name": tool_name, "error": str(exc)})
            result = (f"Error running {tool_name}: {exc}", None, None, None)
        # Every tool's _inner() returns (content, study_id, chart_data) or,
        # for the artifact-generation tools, (content, study_id, chart_data,
        # artifact) — padding to length 4 lets both shapes flow through the
        # same call without touching every existing tool's return sites.
        content, study_id, chart_data, artifact = (tuple(result) + (None, None, None, None))[:4]
        return await _finish_tool_call(tool_name, content, study_id, chart_data, artifact)

    @tool
    async def web_research_tool(query: str) -> str:
        """Search the web for a specific, current market/industry
        fact-finding question that isn't already answered by the business
        profile or study data already provided above (e.g. "current pricing
        trends in <industry>", "typical customer acquisition cost for
        <business type>", "recent regulatory changes affecting <market>").
        Also useful before bootstrap_profile_tool, to look up typical
        pricing/costs for this kind of business instead of asking the user
        cold. Do NOT use this to explain a number that already appears in
        the data above — answer that directly instead. You MUST cite the
        source URL for every factual claim you build from these results."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            results = await web_search.search(
                query, get_settings().tavily_api_key, max_results=6
            )
            if not results:
                return f"No web results found for: {query}", None, None
            formatted = "\n\n".join(
                f"[{i}] {r.title}\n{r.url}\n{r.snippet}" for i, r in enumerate(results, start=1)
            )
            return formatted, None, None

        return await _run_tool_safely("web_research_tool", _inner)

    @tool
    async def bootstrap_profile_tool(
        business_description: str,
        raw_user_input: str | None = None,
        problem_statement: str | None = None,
        unique_value_proposition: str | None = None,
        target_market_description: str | None = None,
        target_market_geography: str | None = None,
        target_market_type: str | None = None,
        business_model_type: str | None = None,
        pricing_unit_price: float | None = None,
        pricing_currency: str = "USD",
        pricing_model: str | None = None,
        expected_monthly_sales: float | None = None,
        capex_amount: float | None = None,
        opex_monthly_amount: float | None = None,
        funding_source: str | None = None,
        team_size: int | None = None,
        key_roles_needed: list[str] | None = None,
        marketing_channels: list[str] | None = None,
        competitors: list[str] | None = None,
        founder_risks: str | None = None,
        study_goal: str | None = None,
        analysis_horizon_years: int = 3,
    ) -> str:
        """Build this project's business profile for the FIRST time, from
        everything the user has told you so far. Call this once you have at
        least a clear business_description — pass every other field you've
        already learned too, not just that one; anything omitted is
        extracted from business_description/raw_user_input automatically or
        estimated via research where possible. REQUIRES a
        pricing_unit_price (price per unit/subscription/transaction) — if
        you don't have one yet, ask the user for it before calling this.
        Calling this again later (e.g. once you've learned the price, or
        anything else new) re-runs extraction with everything you now
        know."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            try:
                request = FeasibilityStartRequest(
                    business_description=business_description,
                    raw_user_input=raw_user_input,
                    analysis_horizon_years=analysis_horizon_years,
                    problem_statement=problem_statement,
                    unique_value_proposition=unique_value_proposition,
                    target_market_description=target_market_description,
                    target_market_geography=target_market_geography,
                    target_market_type=target_market_type,
                    business_model_type=business_model_type,
                    pricing_unit_price=pricing_unit_price,
                    pricing_currency=pricing_currency,
                    pricing_model=pricing_model,
                    expected_monthly_sales=expected_monthly_sales,
                    capex_amount=capex_amount,
                    opex_monthly_amount=opex_monthly_amount,
                    funding_source=funding_source,
                    team_size=team_size,
                    key_roles_needed=key_roles_needed,
                    marketing_channels=marketing_channels,
                    competitors=competitors,
                    founder_risks=founder_risks,
                    study_goal=study_goal,
                )
            except ValidationError as exc:
                return f"Couldn't build the profile yet: {exc}", None, None

            try:
                await populate_business_profile(db, project, request)
            except IntakeHardBlockError:
                return (
                    "I still need to know the planned price per unit, "
                    "subscription fee, or transaction value before I can "
                    "build the profile — ask the user for it, then call "
                    "this tool again."
                ), None, None
            return (
                f'Business profile created for "{project.name}". The full '
                "toolset (running studies, updating the profile, etc.) is "
                "now available."
            ), None, None

        return await _run_tool_safely("bootstrap_profile_tool", _inner)

    if project.business_profile is None:
        # Nothing else is safe to expose yet: every other tool below reads
        # project.business_profile directly (via _system_prompt, or via
        # study.feasibility_input_from_business_profile) and would crash on
        # None — rather than scattering null-checks through all of them,
        # the profile's existence gates the whole tool list instead.
        return [bootstrap_profile_tool, web_research_tool]

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
        additional_context: str | None = None,
        source: Literal["user_provided", "estimated"] = "user_provided",
    ) -> str:
        """Update the project's business profile with new or corrected
        information. Only pass the fields that should change; omit
        everything else. Use additional_context for a useful fact that
        doesn't fit any other field — it's appended to previous notes, never
        overwritten. Set source="estimated" when YOU looked up or inferred a
        value yourself (e.g. via web_research_tool) rather than the user
        stating it directly — leave it as the default "user_provided" for
        anything the user told you themselves."""

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
                "additional_context": additional_context,
            }
            non_null = {k: v for k, v in provided.items() if v is not None}
            if not non_null:
                return "No fields provided — nothing updated.", None, None
            patch = BusinessProfileUpdate(**non_null)
            update_business_profile(db, project.business_profile, patch, source=Source(source))
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

    @tool
    async def generate_presentation_tool(title: str, slides: list[dict]) -> str:
        """Generate an actual PowerPoint presentation (.pptx) the user can
        download — call this when the user explicitly asks for a
        presentation, slide deck, or slides on a topic (e.g. "make a
        10-slide deck about X", "create a presentation about our market
        opportunity"). `slides` is a list of {"heading": str, "bullets":
        list[str] (1-8 short bullet points), "notes": str (optional speaker
        notes)} — one entry per slide, in order (max 30 slides). Write the
        slide content yourself from the conversation and the business
        profile/study data already available above — do not ask the user
        to supply the outline themselves unless they want to. Do NOT use
        this for a written report or document — use
        generate_word_document_tool or generate_pdf_report_tool instead."""

        async def _inner() -> tuple[str, str | None, dict | None, dict | None]:
            try:
                outline = PresentationOutline(
                    title=title, slides=[SlideContent(**s) for s in slides]
                )
            except ValidationError as exc:
                return f"Presentation generation failed: invalid slide data ({exc}).", None, None, None

            settings = get_settings()
            artifact_id = str(uuid.uuid4())
            try:
                file = await generate_pptx(
                    outline,
                    storage_dir=settings.artifact_storage_dir,
                    shared_output_dir=settings.mcp_shared_output_dir,
                    project_id=project_id,
                    artifact_id=artifact_id,
                    presenton_api_key=settings.presenton_api_key,
                )
            except ArtifactGenerationError as exc:
                return f"Presentation generation failed: {exc}", None, None, None

            artifact_row = Artifact(
                id=artifact_id, project_id=project_id, format="pptx", title=outline.title,
                filename=file.filename, storage_path=file.path, size_bytes=file.size_bytes,
                spec_json=outline.model_dump(),
            )
            db.add(artifact_row)
            db.flush()
            summary = ArtifactSummary(
                id=artifact_row.id, format="pptx", title=outline.title,
                filename=file.filename, size_bytes=file.size_bytes,
            )
            return (
                f'Presentation "{outline.title}" generated ({len(outline.slides)} slides).',
                None, None, summary.model_dump(),
            )

        return await _run_tool_safely("generate_presentation_tool", _inner)

    @tool
    async def generate_word_document_tool(title: str, sections: list[dict]) -> str:
        """Generate an actual Word document (.docx) the user can download —
        call this when the user explicitly asks to create/write a Word
        document or report (e.g. "create a Word doc about X", "write up a
        report on our findings"). `sections` is a list of {"heading": str,
        "body": str (one or more paragraphs)} — one entry per section, in
        order (max 50 sections). Write the content yourself from the
        conversation and the business profile/study data already available
        above. Do NOT use this for a PDF or a slide deck — use
        generate_pdf_report_tool or generate_presentation_tool instead."""

        async def _inner() -> tuple[str, str | None, dict | None, dict | None]:
            try:
                outline = DocumentOutline(
                    title=title, sections=[DocumentSection(**s) for s in sections]
                )
            except ValidationError as exc:
                return f"Document generation failed: invalid section data ({exc}).", None, None, None

            settings = get_settings()
            artifact_id = str(uuid.uuid4())
            try:
                file = await generate_docx(
                    outline,
                    storage_dir=settings.artifact_storage_dir,
                    shared_output_dir=settings.mcp_shared_output_dir,
                    project_id=project_id,
                    artifact_id=artifact_id,
                )
            except ArtifactGenerationError as exc:
                return f"Document generation failed: {exc}", None, None, None

            artifact_row = Artifact(
                id=artifact_id, project_id=project_id, format="docx", title=outline.title,
                filename=file.filename, storage_path=file.path, size_bytes=file.size_bytes,
                spec_json=outline.model_dump(),
            )
            db.add(artifact_row)
            db.flush()
            summary = ArtifactSummary(
                id=artifact_row.id, format="docx", title=outline.title,
                filename=file.filename, size_bytes=file.size_bytes,
            )
            return f'Word document "{outline.title}" generated.', None, None, summary.model_dump()

        return await _run_tool_safely("generate_word_document_tool", _inner)

    @tool
    async def generate_pdf_report_tool(title: str) -> str:
        """Generate an actual PDF report — a flowing, paginated text
        document, NOT a slide deck — the user can download. Call this when
        the user explicitly asks for a PDF or "a PDF report" specifically.
        Builds the report from the most recently completed feasibility
        study if one exists, otherwise synthesizes one from this
        conversation. `title` is the report's title (e.g. the business name
        or study topic). Do NOT use this for a PowerPoint/slide deck — use
        generate_presentation_tool for that."""

        async def _inner() -> tuple[str, str | None, dict | None, dict | None]:
            settings = get_settings()
            study = next(
                (s for s in project.study_results if s.status == "completed"), None
            )
            if study is not None:
                markdown = build_study_markdown([study])
            else:
                markdown = await synthesize_chat_export(
                    session, None,
                    google_api_key=settings.google_api_key,
                    reasoning_model=settings.reasoning_model,
                )

            artifact_id = str(uuid.uuid4())
            try:
                file = await generate_pdf(
                    markdown, title,
                    storage_dir=settings.artifact_storage_dir,
                    shared_output_dir=settings.mcp_shared_output_dir,
                    project_id=project_id,
                    artifact_id=artifact_id,
                )
            except ArtifactGenerationError as exc:
                return f"PDF generation failed: {exc}", None, None, None

            # Stored as a DocumentOutline (one section wrapping the whole
            # rendered markdown) rather than raw markdown, so
            # revise_artifact_tool can apply the same generic outline-edit
            # path it uses for Word documents — see app.services.artifact_generation.revise_artifact.
            spec = DocumentOutline(
                title=title, sections=[DocumentSection(heading="Report", body=markdown)]
            )
            artifact_row = Artifact(
                id=artifact_id, project_id=project_id, format="pdf", title=title,
                filename=file.filename, storage_path=file.path, size_bytes=file.size_bytes,
                spec_json=spec.model_dump(),
            )
            db.add(artifact_row)
            db.flush()
            summary = ArtifactSummary(
                id=artifact_row.id, format="pdf", title=title,
                filename=file.filename, size_bytes=file.size_bytes,
            )
            return f'PDF report "{title}" generated.', None, None, summary.model_dump()

        return await _run_tool_safely("generate_pdf_report_tool", _inner)

    @tool
    async def revise_artifact_tool(instructions: str, artifact_id: str | None = None) -> str:
        """Regenerate a previously generated document/presentation with
        changes, based on natural-language instructions — call this when
        the user asks to change, shorten, expand, or otherwise edit a
        document/deck you already generated (e.g. "make slide 3 shorter",
        "add a slide about risks", "expand the financial section"). Omit
        `artifact_id` to revise the most recently generated artifact in
        this project; pass it only if the user is clearly referring to an
        earlier one. This creates a NEW file — the previous version stays
        downloadable."""

        async def _inner() -> tuple[str, str | None, dict | None, dict | None]:
            target_id = artifact_id
            if target_id is None:
                latest = (
                    db.query(Artifact)
                    .filter(Artifact.project_id == project_id, Artifact.deleted_at.is_(None))
                    .order_by(Artifact.created_at.desc())
                    .first()
                )
                if latest is None:
                    return "No previously generated document/presentation to revise.", None, None, None
                target_id = latest.id

            original = (
                db.query(Artifact)
                .filter_by(id=target_id, project_id=project_id, deleted_at=None)
                .one_or_none()
            )
            if original is None:
                return f"Couldn't find a generated artifact with id {target_id}.", None, None, None

            settings = get_settings()
            new_artifact_id = str(uuid.uuid4())
            try:
                file, revised_spec = await run_artifact_revision(
                    original, instructions,
                    google_api_key=settings.google_api_key,
                    reasoning_model=settings.reasoning_model,
                    storage_dir=settings.artifact_storage_dir,
                    shared_output_dir=settings.mcp_shared_output_dir,
                    new_artifact_id=new_artifact_id,
                    presenton_api_key=settings.presenton_api_key,
                )
            except ArtifactGenerationError as exc:
                return f"Revision failed: {exc}", None, None, None

            new_title = revised_spec.get("title", original.title)
            artifact_row = Artifact(
                id=new_artifact_id, project_id=project_id, format=original.format,
                title=new_title, filename=file.filename, storage_path=file.path,
                size_bytes=file.size_bytes, spec_json=revised_spec,
                parent_artifact_id=original.id,
            )
            db.add(artifact_row)
            db.flush()
            summary = ArtifactSummary(
                id=artifact_row.id, format=original.format, title=new_title,
                filename=file.filename, size_bytes=file.size_bytes,
            )
            return f'"{new_title}" revised.', None, None, summary.model_dump()

        return await _run_tool_safely("revise_artifact_tool", _inner)

    @tool
    async def explain_figure_tool(
        figure_description: str,
        section_hint: Literal[
            "market_overview", "competitive_landscape",
            "financial_feasibility", "risk_assessment", "executive_summary",
        ] | None = None,
    ) -> str:
        """Explain the derivation, assumptions, methodology, and sources of
        ONE specific number/entity already computed in this project's most
        recent completed study (e.g. "TAM", "break-even months", "NPV", "the
        regulatory risk"). Use this INSTEAD OF web_research_tool or
        re-running any phase — never recompute or re-derive anything
        yourself. `figure_description` is your best-effort name for the
        figure as it appeared in the data already provided above.
        `section_hint` narrows the search if you know which section it's
        in."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            study = next(
                (s for s in project.study_results if s.status == "completed"), None
            )
            if study is None:
                return "No completed study exists yet for this project.", None, None

            sections = study.sections or {}
            section_names = [section_hint] if section_hint else [
                n for n in sections if n != "glossary"
            ]
            needle = figure_description.strip().lower()

            for name in section_names:
                envelope = sections.get(name)
                data = envelope.get("data") if isinstance(envelope, dict) else None
                if not data:
                    continue
                match = _find_figure_data(data, needle)
                if match is not None:
                    return (
                        f'From the "{name}" section of "{study.title or study.id}" '
                        f"(completed {study.completed_at}):\n"
                        f"{json.dumps(match, ensure_ascii=False, default=str)}"
                    ), None, None

            available = sorted(
                {
                    key
                    for name in section_names
                    for key in ((sections.get(name) or {}).get("data") or {}).keys()
                }
            )
            return (
                f'Couldn\'t find "{figure_description}" in the study data. '
                f"Available figures: {', '.join(available) or 'none'}."
            ), None, None

        return await _run_tool_safely("explain_figure_tool", _inner)

    @tool
    async def run_scenario_simulation_tool(
        unit_price: float | None = None,
        capex: float | None = None,
        opex_monthly: float | None = None,
        expected_monthly_sales: float | None = None,
        analysis_horizon_years: int | None = None,
    ) -> str:
        """Recompute break-even/ROI/NPV/sensitivity/cash-flow for a
        hypothetical change to one or more financial inputs, compared
        against the current business profile's baseline — WITHOUT running a
        new study or persisting anything. Pass ONLY the input(s) that
        change, as their new ABSOLUTE value (compute it yourself from the
        baseline shown above, e.g. baseline price × 1.2 for "raise price
        20%"); every omitted input is held at the profile's current value.
        Follow this up with generate_chart_tool (a "Baseline" vs "Scenario"
        series) to visualize the comparison."""

        async def _inner() -> tuple[str, str | None, dict | None]:
            profile = project.business_profile
            if profile.expected_monthly_sales is None:
                return (
                    "Missing expected monthly sales in the business profile — "
                    "ask the user for it, or run financial analysis first, "
                    "before simulating a scenario."
                ), None, None

            base_kwargs = dict(
                capex=profile.capex_amount,
                opex_monthly=profile.opex_monthly_amount,
                unit_price=profile.pricing_unit_price,
                expected_monthly_sales=profile.expected_monthly_sales,
                analysis_horizon_years=profile.analysis_horizon_years,
            )
            scenario_kwargs = {
                **base_kwargs,
                **{
                    k: v
                    for k, v in dict(
                        capex=capex,
                        opex_monthly=opex_monthly,
                        unit_price=unit_price,
                        expected_monthly_sales=expected_monthly_sales,
                        analysis_horizon_years=analysis_horizon_years,
                    ).items()
                    if v is not None
                },
            }

            try:
                baseline = run_full_financial_model(**base_kwargs)
                scenario = run_full_financial_model(**scenario_kwargs)
            except FinancialCalcError as exc:
                return f"Couldn't simulate that scenario: {exc}", None, None

            def _summarize(result: dict) -> dict:
                return {
                    "break_even_months": result["break_even"]["break_even_months"],
                    "roi_year_1_percent": result["roi_year_1"]["roi_percent"],
                    "npv": result["npv"]["npv"],
                    "payback_month": result["cash_flow"]["payback_month"],
                }

            summary = {
                "baseline_inputs": base_kwargs,
                "scenario_inputs": scenario_kwargs,
                "baseline": _summarize(baseline),
                "scenario": _summarize(scenario),
            }
            return json.dumps(summary, ensure_ascii=False), None, None

        return await _run_tool_safely("run_scenario_simulation_tool", _inner)

    tools = [
        run_feasibility_study_tool,
        run_market_sizing_tool,
        run_competitive_analysis_tool,
        run_financial_analysis_tool,
        run_risk_analysis_tool,
        run_synthesis_tool,
        update_business_profile_tool,
        remember_fact_tool,
        generate_chart_tool,
        web_research_tool,
        explain_figure_tool,
        run_scenario_simulation_tool,
    ]
    if get_settings().mcp_artifacts_enabled:
        # Gated separately from the rest — these depend on the three
        # sibling MCP Docker services (docker-compose.yml) being up, unlike
        # every other tool above which only needs this process.
        tools += [
            generate_presentation_tool,
            generate_word_document_tool,
            generate_pdf_report_tool,
            revise_artifact_tool,
        ]
    return tools


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
    if project.business_profile is None:
        system_prompt = _bootstrap_system_prompt(memory_entries)
    else:
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
