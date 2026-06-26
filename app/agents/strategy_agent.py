from app.agents.llm import get_llm


class StrategyAgent:
    """Strategy and content generation agent — uses reasoning model (gemini-2.5-pro)."""

    def __init__(self) -> None:
        self._llm = get_llm("reasoning")
