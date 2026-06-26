import anthropic

from app.config import settings


class CriticAgent:
    """Critic and analytics agent — uses claude-haiku-4-5-20251001."""

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._model = settings.critic_model
