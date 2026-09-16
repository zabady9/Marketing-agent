"""Shared entry point for every Deep-Agent-backed LLM call in the pipeline.

This is the ONLY place `create_deep_agent(...)` should be called from for a
phase that needs a validated Pydantic object back — every phase agent must
go through `run_structured_deep_agent()` rather than hand-rolling its own
`create_deep_agent(...)` + result-unpacking, because the single most
dangerous failure mode here is easy to miss and easy to reintroduce ad hoc:
LangChain's `create_agent` does NOT treat "the model finished its turn
without ever calling the structured-output tool" as an error — it just
leaves `structured_response` as `None` and the graph completes normally.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agents.base import AgentSoftError
from deepagents import create_deep_agent

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

DEFAULT_MODEL_CALL_LIMIT = 12
DEFAULT_TOOL_CALL_LIMIT = 30


class DeepAgentPhaseError(AgentSoftError):
    """Deep-agent-specific non-fatal failure: exhausted call budget, or the
    agent finished without ever producing a validated structured response.
    Subclasses AgentSoftError so existing orchestrator/pipeline exception
    handling (which already catches AgentSoftError as "flag and continue")
    needs no changes to also catch this."""


async def run_structured_deep_agent(
    *,
    model: BaseChatModel,
    tools: list,
    system_prompt: str,
    human_message: str,
    output_schema: type[SchemaT],
    middleware: list | None = None,
    seed_files: dict[str, str] | None = None,
    model_call_limit: int = DEFAULT_MODEL_CALL_LIMIT,
    tool_call_limit: int = DEFAULT_TOOL_CALL_LIMIT,
) -> SchemaT:
    """Run one bounded deep-agent turn and return a validated `output_schema`
    instance, or raise `DeepAgentPhaseError`.

    Bounded by `ModelCallLimitMiddleware`/`ToolCallLimitMiddleware` with
    `exit_behavior="error"` — NOT by deepagents' own internal
    `recursion_limit=9999`, which is far too high to be a useful safety net
    for a live, SSE-streamed request.
    """
    limit_middleware = [
        ModelCallLimitMiddleware(run_limit=model_call_limit, exit_behavior="error"),
        ToolCallLimitMiddleware(run_limit=tool_call_limit, exit_behavior="error"),
    ]
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[*limit_middleware, *(middleware or [])],
        response_format=ToolStrategy(output_schema, handle_errors=True),
        checkpointer=None,
    )

    invoke_input: dict = {
        "messages": [SystemMessage(content=system_prompt), HumanMessage(content=human_message)]
    }
    if seed_files:
        invoke_input["files"] = seed_files

    try:
        result = await agent.ainvoke(invoke_input)
    except (ModelCallLimitExceededError, ToolCallLimitExceededError) as exc:
        raise DeepAgentPhaseError(f"Deep agent exceeded its call budget: {exc}") from exc
    except Exception as exc:
        raise DeepAgentPhaseError(f"Deep agent run failed: {exc}") from exc

    structured_response = result.get("structured_response")
    if structured_response is None:
        # The agent finished its turn without ever calling the structured-
        # output tool. LangChain treats this as a *successful* graph
        # completion, not an error — so this check is not optional.
        raise DeepAgentPhaseError(
            "Deep agent finished without producing a structured response "
            f"(expected {output_schema.__name__})."
        )
    if not isinstance(structured_response, output_schema):
        # Defensive: re-validate rather than trust the graph's own typing.
        structured_response = output_schema.model_validate(
            structured_response
            if isinstance(structured_response, dict)
            else structured_response.model_dump()
        )
    return structured_response
