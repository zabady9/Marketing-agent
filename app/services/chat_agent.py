from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ChatMessage, ChatSession, Project
from app.schemas.project import BusinessProfileUpdate
from app.services.project import update_business_profile
from app.services.study import run_feasibility_study
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


def _system_prompt(project: Project) -> str:
    profile = project.business_profile
    return (
        "You are a business analyst assistant helping the user develop a feasibility "
        f"study for their project, \"{project.name}\".\n\n"
        "Business profile on file:\n"
        f"- Description: {profile.business_description}\n"
        f"- Target market: {profile.target_market_description or 'unknown'} "
        f"({profile.target_market_geography or 'geography unknown'})\n"
        f"- Business model: {profile.business_model_type or 'unknown'}\n"
        f"- Pricing: {profile.pricing_unit_price} {profile.pricing_currency} "
        f"({profile.pricing_model or 'model unspecified'})\n"
        f"- Competitors: {', '.join(c['name'] for c in profile.competitors) or 'none listed'}\n\n"
        "Use the run_feasibility_study tool when the user asks you to build, run, "
        "generate, or refresh the feasibility study (market sizing, competitive "
        "analysis, financial modeling, risk assessment, synthesis). Use the "
        "update_business_profile tool when the user reveals new or corrected "
        "information about the business that should be saved. Keep replies "
        "concise and focused on helping the user reason about this business idea."
    )


def _build_tools(db: Session, project: Project, queue: EventQueue) -> list:
    @tool
    async def run_feasibility_study_tool() -> str:
        """Run the full feasibility study pipeline (market sizing, competitive
        analysis, financial modeling, risk assessment, and synthesis) for this
        project's business profile, and return a summary of the result. This
        overwrites any previous study result for the project."""
        result = await run_feasibility_study(db, project, queue)
        if result.status == "failed":
            return f"Study failed: {result.error}"
        return (
            f"Study completed. Verdict: {result.verdict}. "
            f"Confidence score: {result.confidence_score}. "
            f"Sections generated: {', '.join(result.sections.keys())}."
        )

    @tool
    def update_business_profile_tool(
        business_description: str | None = None,
        target_market_description: str | None = None,
        target_market_geography: str | None = None,
        business_model_type: str | None = None,
        capex_amount: float | None = None,
        capex_currency: str | None = None,
        opex_monthly_amount: float | None = None,
        opex_monthly_currency: str | None = None,
        pricing_unit_price: float | None = None,
        pricing_currency: str | None = None,
        pricing_model: str | None = None,
        expected_monthly_sales: float | None = None,
        team_size: int | None = None,
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
            "target_market_description": target_market_description,
            "target_market_geography": target_market_geography,
            "business_model_type": business_model_type,
            "capex_amount": capex_amount,
            "capex_currency": capex_currency,
            "opex_monthly_amount": opex_monthly_amount,
            "opex_monthly_currency": opex_monthly_currency,
            "pricing_unit_price": pricing_unit_price,
            "pricing_currency": pricing_currency,
            "pricing_model": pricing_model,
            "expected_monthly_sales": expected_monthly_sales,
            "team_size": team_size,
        }
        non_null = {k: v for k, v in provided.items() if v is not None}
        if not non_null:
            return "No fields provided — nothing updated."
        patch = BusinessProfileUpdate(**non_null)
        update_business_profile(db, project.business_profile, patch)
        return "Business profile updated."

    return [run_feasibility_study_tool, update_business_profile_tool]


def _load_history_messages(session: ChatSession) -> list:
    """Replays prior turns for the LLM call. Persisted "tool" rows are skipped
    here — the assistant's natural-language reply that followed each tool call
    already narrates the outcome, and reconstructing a valid ToolMessage would
    need the original tool_call_id, which isn't persisted. Live tool calls made
    *within* the current turn still use real ToolMessage objects (see
    run_chat_turn) — only cross-request replay is folded down like this."""
    messages: list = []
    for m in session.messages:
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
    tool result rather than crashing the turn."""
    user_message = ChatMessage(role="user", content=user_content)
    session.messages.append(user_message)
    db.commit()

    tools = _build_tools(db, project, queue)
    tool_by_name = {t.name: t for t in tools}
    llm = _build_llm().bind_tools(tools)

    history: list = [SystemMessage(content=_system_prompt(project))]
    history.extend(_load_history_messages(session))

    for round_num in range(MAX_TOOL_ROUNDS):
        response = await llm.ainvoke(history)

        if not response.tool_calls:
            assistant_message = ChatMessage(role="assistant", content=_extract_text(response.content))
            session.messages.append(assistant_message)
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
                role="tool", content=str(tool_result), tool_name=call["name"]
            )
            session.messages.append(tool_message_row)
            db.commit()

            history.append(ToolMessage(content=str(tool_result), tool_call_id=call["id"]))

    logger.warning(
        "Chat tool loop hit the %s-round cap for project %s without a final reply",
        MAX_TOOL_ROUNDS,
        project.id,
    )
    fallback_message = ChatMessage(role="assistant", content=_FALLBACK_MESSAGE)
    session.messages.append(fallback_message)
    db.commit()
    await queue.put(
        SSEEvent.CHAT_MESSAGE_COMPLETED,
        {
            "message_id": fallback_message.id,
            "role": "assistant",
            "content": fallback_message.content,
        },
    )
    return fallback_message
