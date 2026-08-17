"""Multi-agent Meeting Room orchestrator.

Turn-taking model: relevance-based self-selection (bidding).

Flow per user message
─────────────────────
1. Seed transcript with user message.
2. Loop until stop condition:
   a. Emit bidding_start.
   b. Parallel bid — every agent except the last speaker.
   c. Apply recency decay, select winner.
   d. If max_score < SILENCE_THRESHOLD for 2 consecutive rounds → stop (consensus).
   e. If total_turns >= MEETING_HARD_CAP → stop (cap_reached).
   f. Emit agent_turn_start → stream tokens → emit agent_turn_end.
   g. Persist turn to DB, append to in-memory transcript.
3. Emit meeting_concluded.
4. Synthesis pass (Chief of Staff, uses tools, streams).
5. Emit synthesis_end → done.
"""
import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from sqlalchemy import update as sa_update

from app.agents.chat_tools import make_chat_tools
from app.agents.llm import get_llm
from app.agents.meeting_roster import CHIEF_OF_STAFF, ROSTER, ROSTER_MAP, AgentPersona
from app.database import AsyncSessionLocal
from app.models.chat import MessageRole
from app.models.consulting_analysis import ConsultingAnalysis
from app.services import event_bus
from app.services.chat import attach_visuals_to_message, save_message
from app.services.response_validator import validate_and_repair
from app.services.visual_generator import generate_visuals, run_report_visualization_pass

logger = logging.getLogger(__name__)

# ── tunables ──────────────────────────────────────────────────────────────────
MEETING_HARD_CAP = 10        # total agent turns before forced stop
SILENCE_THRESHOLD = 4        # max_bid < this for N consecutive rounds → consensus
CONSECUTIVE_SILENCE_LIMIT = 2
RECENCY_PENALTY = 2          # score deducted per appearance in the last-2-speakers window
RECENCY_WINDOW = 2           # how many recent speakers to penalise
BID_CONTEXT_WINDOW = 12      # how many transcript entries to show bidding agents
MAX_TOOL_ROUNDS = 5          # per individual agent turn (same as single-agent chat)


# ── bid schema ────────────────────────────────────────────────────────────────
class BidResult(BaseModel):
    score: int = Field(ge=0, le=10, description="Confidence 0-10 that I have something new to add")
    reason: str = Field(description="One-line reason (shown to user as bid signal)")


# ── helpers ───────────────────────────────────────────────────────────────────
def _format_transcript(transcript: list[dict], window: int | None = None) -> str:
    entries = transcript[-window:] if window else transcript
    lines = []
    for t in entries:
        if t["role"] == "user":
            lines.append(f"[User]: {t['content']}")
        else:
            label = f"{t.get('agent_name', 'Assistant')} ({t.get('agent_id', 'assistant')})"
            lines.append(f"[{label}]: {t['content']}")
    return "\n\n".join(lines)


async def _safe_bid(
    persona: AgentPersona,
    transcript: list[dict],
    recent_speakers: list[str],
    brand_profile: dict,
) -> BidResult:
    """Run one agent's bid call. Returns score=0 on any failure."""
    try:
        transcript_text = _format_transcript(transcript, window=BID_CONTEXT_WINDOW)

        system = f"""\
You are {persona.name}, a specialist analyst.

## Subject Profile
{json.dumps(brand_profile, indent=2)}

## Your role
{persona.system_prompt}

## Bidding instructions
Decide whether you have something GENUINELY NEW to add to this discussion.

Bid HIGH (7-10) only if you have a SPECIFIC, SUBSTANTIVE contribution:
- A clear disagreement with something already said
- An unanswered question you are best positioned to answer
- A critical missing perspective (e.g. an SEO angle nobody mentioned, a brand risk)
- A concrete next step you can execute right now

Bid LOW (0-3) if:
- The conversation already covers your perspective well
- You would just be repeating or agreeing with what was said
- You have nothing meaningfully new to add

Example of a correct low-score non-bid:
{{"score": 1, "reason": "The Insights Director already covered the strategic angle I had in mind."}}

Respond ONLY with JSON matching the schema: {{"score": 0-10, "reason": "<one line>"}}
"""
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=f"Meeting transcript so far:\n\n{transcript_text}\n\n"
                        "Do you have something new to contribute?"
            ),
        ]

        llm = get_llm("cheap").with_structured_output(BidResult)
        result: BidResult = await llm.ainvoke(messages)

        # Recency decay — penalise agents who spoke recently
        penalty = recent_speakers.count(persona.id) * RECENCY_PENALTY
        result.score = max(0, result.score - penalty)
        return result

    except Exception as exc:
        logger.warning("Bid failed for agent %s: %s", persona.id, exc)
        return BidResult(score=0, reason=f"bid error: {exc}")


async def _run_agent_turn(
    session_id: str,
    persona: AgentPersona,
    user_message: str,
    transcript: list[dict],
    brand_profile: dict,
    retrieved_context: str,
    all_tools: list,
    tool_map: dict[str, Any],
) -> str:
    """Run one agent's turn, streaming tokens via event_bus. Returns full_content."""
    # Filter to this persona's allowed tools
    agent_tools = [t for t in all_tools if t.name in persona.tools]
    agent_tool_map = {k: v for k, v in tool_map.items() if k in persona.tools}
    llm_with_tools = get_llm("cheap").bind_tools(agent_tools)

    system = f"""\
You are {persona.name}, a specialist analyst participating in a team discussion.

## Subject Profile
{json.dumps(brand_profile, indent=2)}

## Relevant Subject Knowledge
{retrieved_context or "No knowledge documents indexed yet."}

## Your role in this discussion
{persona.system_prompt}

## Guidelines
- Be concise and direct — this is a fast-paced team discussion, not a monologue.
- Build on or challenge what others said; don't repeat what's already been covered.
- Use your tools when they would genuinely add value (research, data retrieval, knowledge search).

## Language (CRITICAL)
Detect the language of the user's message and respond ONLY in that language.
- User writes in Arabic → respond entirely in Arabic.
- User writes in English → respond entirely in English.
Never switch languages regardless of the language used in the subject profile or these instructions.
"""

    transcript_text = _format_transcript(transcript)

    messages = [
        SystemMessage(content=system),
        HumanMessage(
            content=f"Original user request: {user_message}\n\n"
                    f"Meeting transcript so far:\n\n{transcript_text}\n\n"
                    f"It's your turn, {persona.name}. What's your specific contribution?"
        ),
    ]

    full_content = ""
    tool_rounds = 0

    while tool_rounds <= MAX_TOOL_ROUNDS:
        response = None

        async for ev in llm_with_tools.astream_events(messages, version="v2"):
            etype = ev["event"]
            if etype == "on_chat_model_stream":
                chunk = ev["data"]["chunk"]
                raw = chunk.content
                if isinstance(raw, list):
                    text = "".join(
                        p.get("text", "") for p in raw
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                else:
                    text = raw or ""
                if text:
                    await event_bus.emit(session_id, {"type": "token", "content": text})
                    full_content += text
            elif etype == "on_chat_model_end":
                response = ev["data"]["output"]

        if not response or not getattr(response, "tool_calls", None):
            break

        tool_rounds += 1
        if tool_rounds > MAX_TOOL_ROUNDS:
            fallback = "\n\n[Reached tool-call depth limit. Answering from available context.]"
            full_content += fallback
            await event_bus.emit(session_id, {"type": "token", "content": fallback})
            break

        messages.append(response)
        for tc in response.tool_calls:
            await event_bus.emit(
                session_id,
                {"type": "tool_start", "tool": tc["name"], "agent": persona.id},
            )
            tool_fn = agent_tool_map.get(tc["name"])
            if tool_fn is None:
                result = f"Unknown tool: {tc['name']}"
            else:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as exc:
                    logger.warning("Tool %s failed for %s: %s", tc["name"], persona.id, exc)
                    result = f"Error: {exc}"
            await event_bus.emit(
                session_id,
                {"type": "tool_end", "tool": tc["name"], "agent": persona.id},
            )
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return full_content


async def _run_synthesis(
    session_id: str,
    user_message: str,
    transcript: list[dict],
    brand_profile: dict,
    retrieved_context: str,
    all_tools: list,
    tool_map: dict[str, Any],
) -> str:
    """Chief of Staff synthesis pass — streams tokens, may call tools."""
    persona = CHIEF_OF_STAFF
    agent_tools = [t for t in all_tools if t.name in persona.tools]
    agent_tool_map = {k: v for k, v in tool_map.items() if k in persona.tools}
    llm_with_tools = get_llm("cheap").bind_tools(agent_tools)

    system = f"""\
You are {persona.name}, the Lead Analyst.

## Subject Profile
{json.dumps(brand_profile, indent=2)}

## Relevant Subject Knowledge
{retrieved_context or "No knowledge documents indexed yet."}

## Your task
{persona.system_prompt}

## Language (CRITICAL)
Detect the language of the user's message and respond ONLY in that language.
- User writes in Arabic → respond entirely in Arabic.
- User writes in English → respond entirely in English.
Never switch languages regardless of the language used in the subject profile or these instructions.
"""
    transcript_text = _format_transcript(transcript)

    messages = [
        SystemMessage(content=system),
        HumanMessage(
            content=f"Original user request: {user_message}\n\n"
                    f"Full meeting transcript:\n\n{transcript_text}\n\n"
                    "Now synthesize the discussion and deliver a concrete outcome."
        ),
    ]

    full_content = ""
    tool_rounds = 0

    while tool_rounds <= MAX_TOOL_ROUNDS:
        response = None
        async for ev in llm_with_tools.astream_events(messages, version="v2"):
            etype = ev["event"]
            if etype == "on_chat_model_stream":
                chunk = ev["data"]["chunk"]
                raw = chunk.content
                if isinstance(raw, list):
                    text = "".join(
                        p.get("text", "") for p in raw
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                else:
                    text = raw or ""
                if text:
                    await event_bus.emit(session_id, {"type": "token", "content": text})
                    full_content += text
            elif etype == "on_chat_model_end":
                response = ev["data"]["output"]

        if not response or not getattr(response, "tool_calls", None):
            break

        tool_rounds += 1
        if tool_rounds > MAX_TOOL_ROUNDS:
            break

        messages.append(response)
        for tc in response.tool_calls:
            await event_bus.emit(
                session_id,
                {"type": "tool_start", "tool": tc["name"], "agent": persona.id},
            )
            tool_fn = agent_tool_map.get(tc["name"])
            if tool_fn is None:
                result = f"Unknown tool: {tc['name']}"
            else:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as exc:
                    logger.warning("Synthesis tool %s failed: %s", tc["name"], exc)
                    result = f"Error: {exc}"
            await event_bus.emit(
                session_id,
                {"type": "tool_end", "tool": tc["name"], "agent": persona.id},
            )
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return full_content


# ── bypass / focused helpers ──────────────────────────────────────────────────

_BYPASS_SYSTEM_INSTRUCTIONS: dict[str, str] = {
    "casual": (
        "The user sent a casual greeting or small talk. "
        "Respond warmly and naturally in 1-2 short sentences. "
        "No analysis, no tools, no lengthy explanations. Just be friendly and welcoming."
    ),
    "system_question": (
        "The user wants to know what this analyst team can help with. "
        "Give a brief, clear overview: the team specialises in market intelligence and strategic analysis — "
        "market research, competitive analysis, SWOT and PESTEL reports, feasibility studies, "
        "quantitative benchmarking, gap identification, and strategic recommendations. "
        "Be concise, friendly, and helpful."
    ),
    "followup_clarification": (
        "The user is asking for clarification or expansion on the previous response. "
        "Use the conversation context to give a focused, helpful clarification. "
        "Be direct and concise — no need to repeat background that was already covered."
    ),
    "out_of_scope": (
        "The user's request is outside the scope of this analyst team's expertise. "
        "Politely decline in 1-2 sentences and briefly note what the team CAN help with: "
        "market research, competitive analysis, SWOT/PESTEL reports, feasibility studies, "
        "quantitative benchmarking, gap analysis, and strategic recommendations."
    ),
}


async def _run_casey_bypass(
    session_id: str,
    meeting_id: str,
    workspace_id: str,
    user_message: str,
    intent: str,
    brand_profile: dict,
    retrieved_context: str,
    session_factory: async_sessionmaker,
) -> None:
    """Lead Analyst responds directly without bidding or tools.

    Used for casual, system_question, followup_clarification, out_of_scope, setup_subject,
    and report_retrieval intents.
    Emits stream_complete in its own finally but does NOT close the event bus
    — the outer run_meeting_agent finally block handles that.
    """
    system_instruction = _BYPASS_SYSTEM_INSTRUCTIONS.get(intent, _BYPASS_SYSTEM_INSTRUCTIONS["casual"])

    system = f"""\
You are {CHIEF_OF_STAFF.name}, the Lead Analyst.

## Subject Profile
{json.dumps(brand_profile, indent=2)}

## Task
{system_instruction}

## Language (CRITICAL)
Detect the language of the user's message and respond ONLY in that language.
- User writes in Arabic → respond entirely in Arabic.
- User writes in English → respond entirely in English.
Never switch languages regardless of the language used in the subject profile or these instructions.
"""

    llm = get_llm("cheap")  # no bind_tools — intentionally no tools in bypass path
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_message),
    ]

    full_content = ""
    try:
        async for ev in llm.astream_events(messages, version="v2"):
            if ev["event"] == "on_chat_model_stream":
                chunk = ev["data"]["chunk"]
                raw = chunk.content
                if isinstance(raw, list):
                    text = "".join(
                        p.get("text", "") for p in raw
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                else:
                    text = raw or ""
                if text:
                    await event_bus.emit(session_id, {"type": "token", "content": text})
                    full_content += text

        bypass_msg_id: str | None = None
        async with session_factory() as db:
            bypass_msg = await save_message(
                db,
                session_id=session_id,
                workspace_id=workspace_id,
                role=MessageRole.assistant,
                content=full_content,
                agent_id=CHIEF_OF_STAFF.id,
                meeting_id=meeting_id,
                turn_index=0,
                metadata={"intent": intent, "bypass": True},
            )
            bypass_msg_id = bypass_msg.id
            await db.commit()

        await event_bus.emit(session_id, {"type": "done"})

        # Auto-visualize follow-up intents when the session has prior data-rich analysis.
        # The visual generator returns [] for non-data follow-ups ("وضح أكثر"), so this
        # only produces output when the previous response actually contained numbers/stats.
        if intent == "followup_clarification":
            from app.services.chat import get_messages as _get_bypass_msgs
            try:
                async with session_factory() as db:
                    _prior = await _get_bypass_msgs(db, session_id)
                _analysis_msgs = [
                    m for m in _prior
                    if m.role == MessageRole.assistant.value and len(m.content) > 300
                ]
                if _analysis_msgs:
                    _prev_content = _analysis_msgs[-1].content
                    await event_bus.emit(session_id, {"type": "visuals_generating"})
                    _visual_resp = await asyncio.wait_for(
                        generate_visuals(user_message, _prev_content, [], brand_profile),
                        timeout=30.0,
                    )
                    if _visual_resp.visuals:
                        _visuals_data = [v.model_dump() for v in _visual_resp.visuals]
                        _sources_data = [s.model_dump() for s in _visual_resp.sources]
                        await event_bus.emit(session_id, {
                            "type": "visuals",
                            "visuals": _visuals_data,
                            "sources": _sources_data,
                        })
                        if bypass_msg_id:
                            async with session_factory() as db:
                                await attach_visuals_to_message(db, bypass_msg_id, _visuals_data, _sources_data)
                                await db.commit()
            except Exception as exc:
                logger.warning(
                    "Auto-visual in bypass failed for session %s: %s", session_id, exc
                )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Casey bypass failed for session %s (intent=%s)", session_id, intent)
        await event_bus.emit(session_id, {"type": "error", "message": str(exc)})
    finally:
        await event_bus.emit(session_id, {"type": "stream_complete"})


async def _run_focused_agent(
    session_id: str,
    meeting_id: str,
    workspace_id: str,
    user_message: str,
    intent: str,
    persona: AgentPersona,
    allowed_tool_names: list[str],
    brand_profile: dict,
    retrieved_context: str,
    all_tools: list,
    tool_map: dict[str, Any],
    session_factory: async_sessionmaker,
    created_analysis_ids: list[str],
    source_registry: Any | None = None,
) -> None:
    """One designated agent responds with a subset of tools. No bidding, no synthesis.

    Used for trend_lookup, data_insights, and plan_generation intents.
    Emits stream_complete in its own finally but does NOT close the event bus
    — the outer run_meeting_agent finally block handles that.
    """
    try:
        await event_bus.emit(
            session_id,
            {
                "type": "agent_turn_start",
                "agent": persona.id,
                "name": persona.name,
                "bid_reason": f"Designated specialist for {intent.replace('_', ' ')}",
            },
        )

        focused_tools = [t for t in all_tools if t.name in allowed_tool_names]
        focused_tool_map = {k: v for k, v in tool_map.items() if k in allowed_tool_names}
        llm_with_tools = get_llm("cheap").bind_tools(focused_tools) if focused_tools else get_llm("cheap")

        system = f"""\
You are {persona.name}, a specialist analyst responding directly to the user's request.

## Subject Profile
{json.dumps(brand_profile, indent=2)}

## Relevant Subject Knowledge
{retrieved_context or "No knowledge documents indexed yet."}

## Your role
{persona.system_prompt}

## Language (CRITICAL)
Detect the language of the user's message and respond ONLY in that language.
- User writes in Arabic → respond entirely in Arabic.
- User writes in English → respond entirely in English.
Never switch languages regardless of the language used in the subject profile or these instructions.
"""

        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user_message),
        ]

        full_content = ""
        tool_rounds = 0

        while tool_rounds <= MAX_TOOL_ROUNDS:
            response = None

            async for ev in llm_with_tools.astream_events(messages, version="v2"):
                etype = ev["event"]
                if etype == "on_chat_model_stream":
                    chunk = ev["data"]["chunk"]
                    raw = chunk.content
                    if isinstance(raw, list):
                        text = "".join(
                            p.get("text", "") for p in raw
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    else:
                        text = raw or ""
                    if text:
                        await event_bus.emit(session_id, {"type": "token", "content": text})
                        full_content += text
                elif etype == "on_chat_model_end":
                    response = ev["data"]["output"]

            if not response or not getattr(response, "tool_calls", None):
                break

            tool_rounds += 1
            if tool_rounds > MAX_TOOL_ROUNDS:
                break

            messages.append(response)
            for tc in response.tool_calls:
                await event_bus.emit(
                    session_id,
                    {"type": "tool_start", "tool": tc["name"], "agent": persona.id},
                )
                tool_fn = focused_tool_map.get(tc["name"])
                if tool_fn is None:
                    result = f"Unknown tool: {tc['name']}"
                else:
                    try:
                        result = await tool_fn.ainvoke(tc["args"])
                    except Exception as exc:
                        logger.warning(
                            "Tool %s failed for focused agent %s: %s", tc["name"], persona.id, exc
                        )
                        result = f"Error: {exc}"
                await event_bus.emit(
                    session_id,
                    {"type": "tool_end", "tool": tc["name"], "agent": persona.id},
                )
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

        await event_bus.emit(session_id, {"type": "agent_turn_end", "agent": persona.id})

        focused_msg_id: str | None = None
        async with session_factory() as db:
            focused_msg = await save_message(
                db,
                session_id=session_id,
                workspace_id=workspace_id,
                role=MessageRole.assistant,
                content=full_content,
                agent_id=persona.id,
                meeting_id=meeting_id,
                turn_index=0,
                metadata={"intent": intent, "focused": True},
            )
            focused_msg_id = focused_msg.id
            await db.commit()
            if created_analysis_ids and focused_msg_id:
                await db.execute(
                    sa_update(ConsultingAnalysis)
                    .where(ConsultingAnalysis.id.in_(list(created_analysis_ids)))
                    .values(chat_message_id=focused_msg_id)
                )
                await db.commit()
                created_analysis_ids.clear()

        await event_bus.emit(session_id, {"type": "done"})

        if intent in _VISUAL_INTENTS:
            try:
                await event_bus.emit(session_id, {"type": "visuals_generating"})
                # Prefer the source_registry bibliography over the old tool-message extraction
                tool_sources = (
                    [s.model_dump() for s in source_registry.to_list()]
                    if source_registry and not source_registry.is_empty()
                    else _extract_tool_sources(messages)
                )
                visual_response = await asyncio.wait_for(
                    generate_visuals(user_message, full_content, tool_sources, brand_profile),
                    timeout=30.0,
                )
                if visual_response.visuals:
                    visuals_data = [v.model_dump() for v in visual_response.visuals]
                    sources_data = [s.model_dump() for s in visual_response.sources]
                    await event_bus.emit(session_id, {
                        "type": "visuals",
                        "visuals": visuals_data,
                        "sources": sources_data,
                    })
                    if focused_msg_id:
                        async with session_factory() as db:
                            await attach_visuals_to_message(db, focused_msg_id, visuals_data, sources_data)
                            await db.commit()
            except Exception as exc:
                logger.warning(
                    "Visual generation failed for focused session %s (intent=%s): %s",
                    session_id, intent, exc,
                )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(
            "Focused agent failed for session %s (persona=%s, intent=%s)",
            session_id, persona.id, intent,
        )
        await event_bus.emit(session_id, {"type": "error", "message": str(exc)})
    finally:
        await event_bus.emit(session_id, {"type": "stream_complete"})


# ── visual generation helpers ─────────────────────────────────────────────────

_VISUAL_INTENTS = frozenset({
    "market_research", "competitive_analysis", "gap_analysis",
    "strategic_recommendation", "subject_analysis",
    "data_insights", "quantitative_analysis", "trend_lookup",
    "swot", "pestel", "feasibility",
})


def _extract_tool_sources(messages: list) -> list[dict]:
    """Parse ToolMessage results and extract source references from get_market_data calls."""
    sources = []
    for msg in messages:
        if hasattr(msg, "content") and isinstance(msg.content, str):
            try:
                data = json.loads(msg.content)
                if isinstance(data, dict) and data.get("source_url"):
                    sources.append({
                        "title": data.get("source_title", "Market data"),
                        "url": data["source_url"],
                        "fetched_at": data.get("fetched_at", ""),
                    })
            except (json.JSONDecodeError, TypeError):
                pass
    return sources


# ── routing constants ─────────────────────────────────────────────────────────

_AUTO_SEARCH_INTENTS = frozenset({
    "market_research", "competitive_analysis", "gap_analysis",
    "strategic_recommendation", "subject_analysis", "general_analysis",
    "trend_lookup", "data_insights", "quantitative_analysis",
})


async def _auto_preflight_search(
    user_message: str,
    brand_profile: dict,
    tool_map: dict[str, Any],
    intent: str,
) -> str:
    """Search subject knowledge (always) and the web (for analysis intents) before
    any agent speaks, making data retrieval the default rather than optional.

    For broad analytical intents, uses query_decomposer to generate 3-5 targeted
    sub-queries instead of a single combined query, surfacing more evidence angles.
    """
    from app.agents.query_decomposer import decompose_query

    parts = []

    sk_fn = tool_map.get("search_subject_knowledge")
    if sk_fn:
        try:
            result = await sk_fn.ainvoke({"query": user_message})
            if result and "No relevant" not in result:
                parts.append(f"## Subject Knowledge\n{result}")
        except Exception as exc:
            logger.warning("Pre-flight subject knowledge search failed: %s", exc)

    if intent in _AUTO_SEARCH_INTENTS:
        ws_fn = tool_map.get("web_search")
        if ws_fn:
            # Decompose broad queries into targeted sub-queries; fall back to single query
            sub_queries = await decompose_query(user_message, intent, brand_profile)

            if not sub_queries:
                subject = (
                    brand_profile.get("subject_name")
                    or brand_profile.get("legal_name")
                    or ""
                )
                industry = brand_profile.get("industry") or ""
                sub_queries = [f"{subject} {industry} {user_message}"[:200]]

            web_results: list[str] = []
            for query in sub_queries:
                try:
                    result = await ws_fn.ainvoke({"query": query})
                    if result and "unavailable" not in result.lower():
                        web_results.append(result)
                except Exception as exc:
                    logger.warning("Pre-flight web search failed for %r: %s", query, exc)

            if web_results:
                parts.append("## Web Search Results\n" + "\n\n---\n\n".join(web_results))

    return "\n\n".join(parts)


_BYPASS_INTENTS = frozenset({
    "casual", "system_question", "followup_clarification", "out_of_scope",
})

# Maps intent → (persona_id, allowed_tool_names)
_FOCUSED_ROUTING: dict[str, tuple[str, list[str]]] = {
    "trend_lookup":          ("data_scout",    ["web_search"]),
    "data_insights":         ("data_scout",    ["get_market_data", "web_search"]),
    "quantitative_analysis": ("quant_analyst", ["search_subject_knowledge"]),
    "setup_subject":         ("lead_analyst",  []),
    "report_retrieval":      ("lead_analyst",  []),
    "swot":                  ("lead_analyst",  ["run_formal_analysis", "web_search"]),
    "pestel":                ("lead_analyst",  ["run_formal_analysis", "web_search"]),
    "feasibility":           ("lead_analyst",  ["run_formal_analysis", "web_search"]),
    "general_analysis":      ("lead_analyst",  ["run_formal_analysis", "web_search"]),
}

# Full lookup including CHIEF_OF_STAFF for focused routing to lead_analyst
_ALL_PERSONA_MAP: dict[str, "AgentPersona"] = {**ROSTER_MAP, CHIEF_OF_STAFF.id: CHIEF_OF_STAFF}


# ── main orchestrator ─────────────────────────────────────────────────────────
async def run_meeting_agent(
    session_id: str,
    meeting_id: str,
    workspace_id: str,
    user_message: str,
    brand_profile: dict,
    retrieved_context: str,
    session_factory: async_sessionmaker = AsyncSessionLocal,
) -> None:
    """Background task. Orchestrates the full multi-agent meeting room."""
    try:
        # ── Step 0: enrich retrieved_context with prior conversation turns ────
        from app.services.context_retriever import retrieve_context as _retrieve_context
        try:
            async with session_factory() as _ctx_db:
                prior_context = await _retrieve_context(session_id=session_id, db=_ctx_db, k=5)
            if prior_context:
                retrieved_context = (
                    f"{prior_context}\n\n{retrieved_context}".strip()
                    if retrieved_context
                    else prior_context
                )
        except Exception as exc:
            logger.warning("Context retrieval failed (non-fatal): %s", exc)

        # ── Step 1: classify intent and route ────────────────────────────────
        from app.agents.intent_agent import classify_analyst_intent

        try:
            intent_result = await classify_analyst_intent(user_message, brand_profile)
            intent = intent_result.intent
            logger.debug("Chat intent for session %s: %s (reason: %s)", session_id, intent, intent_result.reasoning)
        except Exception as exc:
            logger.warning("Intent classification failed, defaulting to market_research: %s", exc)
            intent = "market_research"

        if intent in _BYPASS_INTENTS:
            await _run_casey_bypass(
                session_id=session_id,
                meeting_id=meeting_id,
                workspace_id=workspace_id,
                user_message=user_message,
                intent=intent,
                brand_profile=brand_profile,
                retrieved_context=retrieved_context,
                session_factory=session_factory,
            )
            return

        # Tools are needed for focused and full-meeting paths
        all_tools, tool_map, created_analysis_ids, source_registry = make_chat_tools(workspace_id, brand_profile, session_factory)

        # ── Pre-flight: search for relevant data before any agent speaks ─────
        preflight = await _auto_preflight_search(user_message, brand_profile, tool_map, intent)
        if preflight:
            retrieved_context = (
                f"{retrieved_context}\n\n{preflight}".strip()
                if retrieved_context
                else preflight
            )

        if intent in _FOCUSED_ROUTING:
            persona_id, allowed_tool_names = _FOCUSED_ROUTING[intent]
            persona = _ALL_PERSONA_MAP[persona_id]
            await _run_focused_agent(
                session_id=session_id,
                meeting_id=meeting_id,
                workspace_id=workspace_id,
                user_message=user_message,
                intent=intent,
                persona=persona,
                allowed_tool_names=allowed_tool_names,
                brand_profile=brand_profile,
                retrieved_context=retrieved_context,
                all_tools=all_tools,
                tool_map=tool_map,
                session_factory=session_factory,
                created_analysis_ids=created_analysis_ids,
                source_registry=source_registry,
            )
            return

        # ── Step 2: Full meeting flow (analysis intents) ─────────────────────

        # Transcript: list of {role, content, agent_id?, agent_name?}
        transcript: list[dict] = [{"role": "user", "content": user_message}]
        # Tracks last RECENCY_WINDOW speakers for recency decay
        recent_speakers: list[str] = []
        consecutive_silence = 0
        total_turns = 0
        conclusion_reason = "cap_reached"

        while total_turns < MEETING_HARD_CAP:
            # ── bidding phase ────────────────────────────────────────────────
            await event_bus.emit(session_id, {"type": "bidding_start"})

            last_speaker = recent_speakers[-1] if recent_speakers else None
            eligible = [p for p in ROSTER if p.id != last_speaker]

            raw_bids: list[BidResult] = await asyncio.gather(
                *[_safe_bid(p, transcript, recent_speakers, brand_profile) for p in eligible]
            )

            max_score = max((b.score for b in raw_bids), default=0)

            if max_score < SILENCE_THRESHOLD:
                consecutive_silence += 1
                if consecutive_silence >= CONSECUTIVE_SILENCE_LIMIT:
                    conclusion_reason = "consensus"
                    break
            else:
                consecutive_silence = 0

            # Select winner: highest score; tie-break by least-recent speaker
            # Build a last-spoke-at map (higher index = more recent = penalised in tie)
            last_spoke: dict[str, int] = {}
            for i, entry in enumerate(transcript):
                if entry["role"] == "assistant" and entry.get("agent_id"):
                    last_spoke[entry["agent_id"]] = i

            def _rank(idx: int) -> tuple[int, int]:
                score = raw_bids[idx].score
                spoke_at = last_spoke.get(eligible[idx].id, -1)
                return (score, -spoke_at)  # higher score first, less-recent first on tie

            winner_idx = max(range(len(eligible)), key=_rank)
            winner = eligible[winner_idx]
            winner_bid = raw_bids[winner_idx]

            # Collect all bids for debuggability — stored in message metadata
            all_bids_debug = [
                {"agent": eligible[i].id, "score": raw_bids[i].score, "reason": raw_bids[i].reason}
                for i in range(len(eligible))
            ]

            # ── agent speaks ─────────────────────────────────────────────────
            await event_bus.emit(
                session_id,
                {
                    "type": "agent_turn_start",
                    "agent": winner.id,
                    "name": winner.name,
                    "bid_reason": winner_bid.reason,
                },
            )

            agent_content = await _run_agent_turn(
                session_id=session_id,
                persona=winner,
                user_message=user_message,
                transcript=transcript,
                brand_profile=brand_profile,
                retrieved_context=retrieved_context,
                all_tools=all_tools,
                tool_map=tool_map,
            )

            async with session_factory() as db:
                await save_message(
                    db,
                    session_id=session_id,
                    workspace_id=workspace_id,
                    role=MessageRole.assistant,
                    content=agent_content,
                    agent_id=winner.id,
                    meeting_id=meeting_id,
                    turn_index=total_turns,
                    metadata={
                        "bid_score": winner_bid.score,
                        "bid_reason": winner_bid.reason,
                        "all_bids": all_bids_debug,
                    },
                )
                await db.commit()

            await event_bus.emit(
                session_id, {"type": "agent_turn_end", "agent": winner.id}
            )

            # Update in-memory transcript + recency tracker
            transcript.append(
                {
                    "role": "assistant",
                    "agent_id": winner.id,
                    "agent_name": winner.name,
                    "content": agent_content,
                }
            )
            recent_speakers.append(winner.id)
            if len(recent_speakers) > RECENCY_WINDOW:
                recent_speakers.pop(0)

            total_turns += 1

        # ── meeting ended ─────────────────────────────────────────────────────
        await event_bus.emit(
            session_id, {"type": "meeting_concluded", "reason": conclusion_reason}
        )

        # ── synthesis pass ────────────────────────────────────────────────────
        await event_bus.emit(session_id, {"type": "synthesis_start"})

        synthesis_content = await _run_synthesis(
            session_id=session_id,
            user_message=user_message,
            transcript=transcript,
            brand_profile=brand_profile,
            retrieved_context=retrieved_context,
            all_tools=all_tools,
            tool_map=tool_map,
        )

        synthesis_msg_id: str | None = None
        async with session_factory() as db:
            synthesis_msg = await save_message(
                db,
                session_id=session_id,
                workspace_id=workspace_id,
                role=MessageRole.assistant,
                content=synthesis_content,
                agent_id=CHIEF_OF_STAFF.id,
                meeting_id=meeting_id,
                turn_index=total_turns,
                metadata={"synthesis": True},
            )
            synthesis_msg_id = synthesis_msg.id
            await db.commit()
            if created_analysis_ids and synthesis_msg_id:
                await db.execute(
                    sa_update(ConsultingAnalysis)
                    .where(ConsultingAnalysis.id.in_(list(created_analysis_ids)))
                    .values(chat_message_id=synthesis_msg_id)
                )
                await db.commit()
                created_analysis_ids.clear()

        await event_bus.emit(session_id, {"type": "synthesis_end"})

        # ── Post-generation quality gate ──────────────────────────────────────
        validated_synthesis, validation_warnings = await validate_and_repair(
            synthesis=synthesis_content,
            intent=intent,
        )
        if validated_synthesis != synthesis_content:
            synthesis_content = validated_synthesis
            # Update the persisted message if repair added content
            if synthesis_msg_id:
                async with session_factory() as db:
                    from sqlalchemy import update as _upd
                    from app.models.chat import ChatMessage
                    await db.execute(
                        _upd(ChatMessage)
                        .where(ChatMessage.id == synthesis_msg_id)
                        .values(content=synthesis_content)
                    )
                    await db.commit()
        if validation_warnings:
            logger.info("Validator warnings for session %s: %s", session_id, validation_warnings)

        await event_bus.emit(session_id, {"type": "done"})

        if intent in _VISUAL_INTENTS:
            try:
                await event_bus.emit(session_id, {"type": "visuals_generating"})
                # Pass the full source registry accumulated across all agent turns
                synthesis_sources = (
                    [s.model_dump() for s in source_registry.to_list()]
                    if source_registry and not source_registry.is_empty()
                    else []
                )
                # Report-mode intents use the full dedup+placement pipeline
                _REPORT_MODE_INTENTS = frozenset({
                    "swot", "pestel", "feasibility", "general_analysis", "market_research",
                })
                if intent in _REPORT_MODE_INTENTS:
                    visual_response = await asyncio.wait_for(
                        run_report_visualization_pass(
                            user_message, synthesis_content, synthesis_sources,
                            brand_profile, intent,
                        ),
                        timeout=45.0,
                    )
                else:
                    visual_response = await asyncio.wait_for(
                        generate_visuals(user_message, synthesis_content, synthesis_sources, brand_profile),
                        timeout=30.0,
                    )
                if visual_response.visuals:
                    visuals_data = [v.model_dump() for v in visual_response.visuals]
                    # Prefer the source_registry bibliography over LLM-generated sources
                    if source_registry and not source_registry.is_empty():
                        sources_data = [s.model_dump() for s in source_registry.to_list()]
                    else:
                        sources_data = [s.model_dump() for s in visual_response.sources]
                    await event_bus.emit(session_id, {
                        "type": "visuals",
                        "visuals": visuals_data,
                        "sources": sources_data,
                    })
                    if synthesis_msg_id:
                        async with session_factory() as db:
                            await attach_visuals_to_message(db, synthesis_msg_id, visuals_data, sources_data)
                            await db.commit()
            except Exception as exc:
                logger.warning(
                    "Visual generation failed for meeting %s (intent=%s): %s",
                    meeting_id, intent, exc,
                )

    except asyncio.CancelledError:
        logger.debug("Meeting agent cancelled (client disconnected) for session %s", session_id)
        raise
    except Exception as exc:
        logger.exception("Meeting agent failed for session %s", session_id)
        await event_bus.emit(session_id, {"type": "error", "message": str(exc)})
    finally:
        await event_bus.emit(session_id, {"type": "stream_complete"})
        event_bus.close(session_id)
