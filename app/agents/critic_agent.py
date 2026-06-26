from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.agents.schemas import ContentOutput, CriticOutput

CRITIC_SYSTEM = (
    "You are a brand safety reviewer. Check the post for: "
    "tone alignment with the brand voice, spelling/grammar errors, "
    "and presence of any terms on the brand's avoid list. "
    "Return JSON: approved (bool), issues (list of strings), "
    "fixed_body (string or null — populate only when approved is false)."
)


class CriticAgent:
    """Critic agent — uses cheap model (gemini-2.5-flash)."""

    def __init__(self) -> None:
        self._chain = get_llm("cheap").with_structured_output(
            CriticOutput, method="json_schema"
        )

    async def review(self, post: ContentOutput, brand_profile: dict) -> CriticOutput:
        messages = [
            SystemMessage(content=CRITIC_SYSTEM),
            HumanMessage(
                content=f"Post: {post.model_dump()}\nBrand profile: {brand_profile}"
            ),
        ]
        return await self._chain.ainvoke(messages)
