from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ChatMessage, ChatSession, MemoryEntry, Project, StudyResult
from app.schemas.project import BusinessProfileUpdate
from app.services.chat import get_latest_study_id_for_session, maybe_set_title
from app.services.memory import add_memory_entry, list_memory_entries
from app.services.project import update_business_profile
from app.services.study import run_feasibility_study
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
        "Use the run_feasibility_study tool when the user asks you to build, run, "
        "generate, or refresh the feasibility study (market sizing, competitive "
        "analysis, financial modeling, risk assessment, synthesis). If study data "
        "is already provided below, answer follow-up questions about it (e.g. "
        "about specific competitors, financial figures, or risks) directly from "
        "that data instead of calling the tool again — only call it when the "
        "user explicitly asks to run, build, refresh, or redo the study, or when "
        "no study data is available yet. Use the "
        "update_business_profile tool when the user reveals new or corrected "
        "information about the business that should be saved. Use the "
        "remember_fact_tool when the user states a durable preference or fact "
        "about themselves or their business that would be useful in *future* "
        "conversations and other projects (not just this one) — e.g. their name, "
        "role, industry background, or a stated preference for how you should "
        "respond. Do not use it for facts that only matter to this project's "
        "business profile; use update_business_profile for those instead. Keep "
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


def _build_tools(db: Session, project: Project, queue: EventQueue, last_study: dict) -> list:
    @tool
    async def run_feasibility_study_tool() -> str:
        """Run the full feasibility study pipeline (market sizing, competitive
        analysis, financial modeling, risk assessment, and synthesis) for this
        project's business profile, and return a summary of the result. Each
        run creates a new, independently viewable study — past runs are kept,
        not overwritten."""
        result = await run_feasibility_study(db, project, queue)
        if result.status == "failed":
            return f"Study failed: {result.error}"
        last_study["id"] = result.id
        return (
            f"Study completed. Verdict: {result.verdict}. "
            f"Confidence score: {result.confidence_score}. "
            f"Sections generated: {', '.join(result.sections.keys())}."
        )

    @tool
    def update_business_profile_tool(
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
        # The tool call always binds every parameter (unprovided ones default to
        # None), so forwarding them all straight into BusinessProfileUpdate would
        # make Pydantic treat every field as explicitly "set to None" — defeating
        # update_business_profile's exclude_unset PATCH semantics and overwriting
        # NOT NULL columns with NULL. Filter to only the fields actually provided.
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
            return "No fields provided — nothing updated."
        patch = BusinessProfileUpdate(**non_null)
        update_business_profile(db, project.business_profile, patch)
        return "Business profile updated."

    @tool
    def remember_fact_tool(content: str) -> str:
        """Persist a short, durable fact or preference about the user or their
        business that should be remembered in ALL future conversations across
        ALL projects (not just this one) — e.g. "prefers metric units", "is
        based in Cairo", "runs a family business with 2 co-founders". Do not
        call this for facts that only apply to the current project's business
        profile — use update_business_profile for those instead."""
        add_memory_entry(db, content, source="agent_extracted")
        return "Noted — I'll remember that."

    return [run_feasibility_study_tool, update_business_profile_tool, remember_fact_tool]


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


async def run_chat_turn(
    db: Session,
    project: Project,
    session: ChatSession,
    user_content: str,
    queue: EventQueue,
) -> ChatMessage:
    """Persists the user's message, runs the tool-calling loop (capped at
    MAX_TOOL_ROUNDS), persists every intermediate tool call and the final
    assistant reply, and emits CHAT_MESSAGE_COMPLETED when done. Tool errors
    are caught, reported via CHAT_TOOL_ERROR, and fed back to the model as a
    tool result rather than crashing the turn.

    The assistant's reply is persisted as a single ChatMessage row created
    up front (status="pending") and updated in place as text streams in
    (status="streaming") and finally completes (status="complete") or fails
    (status="error") — this is the row a client reconnecting after a page
    refresh finds and resumes via get_active_generation / the resume-stream
    endpoint, so no already-generated text is ever lost to a disconnect."""
    user_message = ChatMessage(role="user", content=user_content, status="complete")
    session.messages.append(user_message)
    maybe_set_title(session, user_content)
    db.commit()

    last_study: dict = {}
    tools = _build_tools(db, project, queue, last_study)
    tool_by_name = {t.name: t for t in tools}

    settings = get_settings()
    restricted = await detect_single_tool_intent(
        user_content,
        {name: t.description for name, t in tool_by_name.items()},
        google_api_key=settings.google_api_key,
        cheap_model=settings.cheap_model,
    )
    if restricted == "none":
        llm = _build_llm()
    elif restricted:
        llm = _build_llm().bind_tools([tool_by_name[restricted]])
    else:
        llm = _build_llm().bind_tools(tools)

    memory_entries = list_memory_entries(db)
    system_prompt = _system_prompt(project, memory_entries)
    latest_study_id = get_latest_study_id_for_session(db, session)
    if latest_study_id:
        latest_study = db.query(StudyResult).filter_by(id=latest_study_id).one_or_none()
        if latest_study is not None:
            system_prompt += _study_context_block(latest_study)

    history: list = [SystemMessage(content=system_prompt)]
    history.extend(_load_history_messages(session))

    assistant_message = ChatMessage(role="assistant", content="", status="pending")
    session.messages.append(assistant_message)
    db.commit()

    try:
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

            history.append(response)
            for call in response.tool_calls:
                tool_fn = tool_by_name.get(call["name"])
                try:
                    if tool_fn is None:
                        raise ValueError(f"Unknown tool: {call['name']}")
                    tool_result = await tool_fn.ainvoke(call["args"])
                except Exception as exc:
                    logger.warning(
                        "Chat tool '%s' failed for project %s: %s", call["name"], project.id, exc
                    )
                    await queue.put(
                        SSEEvent.CHAT_TOOL_ERROR,
                        {"tool_name": call["name"], "error": str(exc)},
                    )
                    tool_result = f"Error running {call['name']}: {exc}"

                tool_message_row = ChatMessage(
                    role="tool",
                    content=str(tool_result),
                    tool_name=call["name"],
                    status="complete",
                    study_id=last_study.pop("id", None)
                    if call["name"] == "run_feasibility_study_tool"
                    else None,
                )
                session.messages.append(tool_message_row)
                # Heartbeat the assistant placeholder row too — a single tool
                # call (e.g. the full feasibility-study pipeline) can run far
                # longer than the streaming flush interval above, and the
                # stuck-generation sweep in app.main relies on updated_at
                # staying fresh to avoid mistaking a legitimately long-running
                # tool call for an orphaned/crashed generation.
                assistant_message.updated_at = datetime.utcnow()
                db.commit()

                history.append(ToolMessage(content=str(tool_result), tool_call_id=call["id"]))

        logger.warning(
            "Chat tool loop hit the %s-round cap for project %s without a final reply",
            MAX_TOOL_ROUNDS,
            project.id,
        )
        assistant_message.content = _FALLBACK_MESSAGE
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
        logger.exception("Chat turn failed for project %s", project.id)
        # A mid-commit failure leaves the session in a pending-rollback state —
        # clear it before writing the error, or that write would itself raise
        # PendingRollbackError. This also reloads assistant_message.content
        # back to its last successfully committed (i.e. already-streamed)
        # value, which is deliberately preserved below rather than discarded.
        db.rollback()
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
