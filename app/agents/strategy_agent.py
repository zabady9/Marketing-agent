from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.llm import get_llm
from app.agents.schemas import StrategyOutput

STRATEGY_SYSTEM = (
    "You are a social media strategist. Given a brand profile and an optional goal, "
    "produce exactly 7 content ideas for a one-week posting plan. "
    "Return a structured JSON object with an 'ideas' array of exactly 7 items. "
    "Each idea must have: day (integer 1-7), theme (string), format (string), angle (string)."
)


class StrategyAgent:
    """Strategy agent — uses reasoning model (gemini-2.5-pro)."""

    def __init__(self) -> None:
        self._chain = get_llm("reasoning").with_structured_output(
            StrategyOutput, method="json_schema"
        )

    async def generate(
        self, brand_profile: dict, goal: str | None = None
    ) -> StrategyOutput:
        messages = [
            SystemMessage(content=STRATEGY_SYSTEM),
            HumanMessage(
                content=(
                    f"Brand profile: {brand_profile}\n"
                    f"Goal: {goal or 'general brand awareness'}"
                )
            ),
        ]
        return await self._invoke_with_retry(messages)

    async def _invoke_with_retry(self, messages: list) -> StrategyOutput:
        try:
            result = await self._chain.ainvoke(messages)
            if not isinstance(result, StrategyOutput) or len(result.ideas) != 7:
                raise ValueError(f"Expected 7 ideas, got {len(result.ideas) if isinstance(result, StrategyOutput) else 'non-StrategyOutput'}")
            return result
        except (ValidationError, ValueError):
            # Retry once with reinforcing instruction
            retry_messages = messages + [
                HumanMessage(
                    content="You must return exactly 7 ideas in the 'ideas' array — no more, no less."
                )
            ]
            try:
                result = await self._chain.ainvoke(retry_messages)
                if not isinstance(result, StrategyOutput):
                    raise ValueError("Retry did not return StrategyOutput")
                if len(result.ideas) > 7:
                    result = StrategyOutput(ideas=result.ideas[:7])
                elif len(result.ideas) < 7:
                    raise ValueError(
                        f"Strategy returned {len(result.ideas)} ideas after retry, expected 7"
                    )
                return result
            except ValidationError as exc:
                raise ValueError(f"Strategy failed after retry: {exc}") from exc
