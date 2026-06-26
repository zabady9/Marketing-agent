import anthropic

from app.config import settings


class StrategyAgent:
    """Strategy and content generation agent — uses claude-sonnet-4-6."""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.strategy_model
