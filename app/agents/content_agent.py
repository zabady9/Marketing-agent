from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.agents.schemas import ContentIdea, ContentOutput

CONTENT_SYSTEM = (
    "You are a social media copywriter. Given a content idea and a brand profile, "
    "write a complete social media post. "
    "Return JSON with: content (post body string), hashtags (list of strings), "
    "suggested_time (HH:MM string for the best posting time)."
)


class ContentAgent:
    """Content writing agent — uses reasoning model (gemini-2.5-pro)."""

    def __init__(self) -> None:
        self._chain = get_llm("reasoning").with_structured_output(
            ContentOutput, method="json_schema"
        )

    async def write(
        self,
        idea: ContentIdea,
        brand_profile: dict,
        revision_hint: str | None = None,
    ) -> ContentOutput:
        hint = f"\nRevision hint: {revision_hint}" if revision_hint else ""
        messages = [
            SystemMessage(content=CONTENT_SYSTEM),
            HumanMessage(
                content=(
                    f"Idea: {idea.model_dump()}\n"
                    f"Brand profile: {brand_profile}"
                    f"{hint}"
                )
            ),
        ]
        return await self._chain.ainvoke(messages)
