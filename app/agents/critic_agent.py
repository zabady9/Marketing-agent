from app.agents.llm import get_llm


class CriticAgent:
    """Critic and analytics agent — uses cheap model (gemini-2.5-flash)."""

    def __init__(self) -> None:
        self._llm = get_llm("cheap")
