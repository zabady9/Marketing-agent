from typing import Literal

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def get_llm(tier: Literal["reasoning", "cheap"]) -> ChatGoogleGenerativeAI:
    model = settings.reasoning_model if tier == "reasoning" else settings.cheap_model
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key.get_secret_value(),
        max_tokens=settings.max_tokens,
        max_retries=3,
        request_timeout=120,
    )
