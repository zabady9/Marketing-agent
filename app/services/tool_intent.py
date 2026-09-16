from __future__ import annotations

import asyncio
import logging
from typing import Mapping

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Bounds worst-case added latency from this classification call — unlike
# app.tools.language.detect_language (which runs once at study-start), this
# runs on every chat turn before the main reply starts streaming, so a slow/
# hanging call must not stall the turn indefinitely.
_CLASSIFY_TIMEOUT_SECONDS = 6.0


class _ToolIntentResult(BaseModel):
    restrict_to_tool_name: str | None = Field(
        default=None,
        description=(
            "Exact name of the single tool the user explicitly asked to use "
            "exclusively this turn (and no other tool), or null if the message "
            "isn't an explicit single-tool request."
        ),
    )
    restrict_to_no_tools: bool = Field(
        default=False,
        description="True only if the user explicitly asked that no tools be used at all this turn.",
    )


async def detect_single_tool_intent(
    user_content: str,
    tool_descriptions: Mapping[str, str],
    *,
    google_api_key: str,
    cheap_model: str,
) -> str | None:
    """Detects whether the user explicitly asked for exactly one specific tool
    (or explicitly asked for no tools at all) to be used this turn, in any
    language or phrasing — classified by a fast LLM call (cheap_model) rather
    than a hardcoded keyword list, mirroring
    app.tools.language.detect_language's try/fallback-safe structure.

    Returns:
      - a tool name  -> the caller should bind ONLY that tool this turn.
      - "none"       -> the caller should bind ZERO tools this turn.
      - None         -> no restriction; unrestricted tool-calling (today's
                        behavior) — the common case, and the safe fallback on
                        any classification failure, timeout, or hallucinated
                        tool name not present in tool_descriptions.
    """
    try:
        restrict_to_tool_name, restrict_to_no_tools = await asyncio.wait_for(
            _gemini_classify(user_content, tool_descriptions, google_api_key, cheap_model),
            timeout=_CLASSIFY_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Tool-intent classification failed; falling back to unrestricted", exc_info=True)
        return None

    if restrict_to_no_tools:
        return "none"
    if restrict_to_tool_name and restrict_to_tool_name in tool_descriptions:
        return restrict_to_tool_name
    return None


async def _gemini_classify(
    user_content: str,
    tool_descriptions: Mapping[str, str],
    google_api_key: str,
    cheap_model: str,
) -> tuple[str | None, bool]:
    tool_list = "\n".join(f"- {name}: {description}" for name, description in tool_descriptions.items())
    llm = ChatGoogleGenerativeAI(model=cheap_model, google_api_key=google_api_key, temperature=0)
    structured = llm.with_structured_output(_ToolIntentResult)

    result: _ToolIntentResult = await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "You are classifying a chat message to detect an explicit request to "
                    "restrict which tools may be used to handle it this turn. Most messages "
                    "are ordinary requests where the assistant should stay free to use zero, "
                    "one, or several of the tools below as needed — in that common case, "
                    "leave both fields at their default (null / false).\n\n"
                    "Only set restrict_to_tool_name when the user's phrasing clearly means "
                    "'use ONLY this one tool and nothing else' (in any language or phrasing), "
                    "e.g. 'only remember this fact, don't do anything else'. This also applies "
                    "when the user names ONE specific capability out of several similar ones "
                    "available below (e.g. asking for competitor analysis when both a single-"
                    "capability tool and a broader all-in-one tool exist) — that is exactly a "
                    "'use only this one' request even without the word 'only', since naming one "
                    "specific capability implicitly excludes the broader one. Only set "
                    "restrict_to_no_tools when the user clearly asked that no tool be used at "
                    "all. If the request is unsure, ambiguous, or could plausibly need more "
                    "than one tool, leave both fields at their default.\n\n"
                    "Available tools this turn:\n" + tool_list
                )
            ),
            HumanMessage(content=user_content),
        ]
    )
    return result.restrict_to_tool_name, result.restrict_to_no_tools
