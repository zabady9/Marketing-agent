"""The engine's only door to Gemini — a tiny client the tests replace with a fake."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

# Waits before each retry of a transient Gemini error (overload / rate limit).
_RETRY_DELAYS = (3.0, 8.0, 20.0)
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "DEADLINE", "timed out")


def is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return any(m in text for m in _TRANSIENT_MARKERS)


class AnalysisLLM:
    def __init__(self) -> None:
        s = get_settings()
        self._key = s.google_api_key
        self._reasoning = s.reasoning_model
        self._cheap = s.cheap_model
        self.calls = 0

    async def _call(self, cheap: bool, make: Callable[[bool], Awaitable[R]]) -> R:
        """Run one model call with retries on transient errors. If the
        reasoning model is still overloaded after the retries, fall back to
        the cheap model once rather than losing the step."""
        self.calls += 1
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
            try:
                return await make(cheap)
            except Exception as exc:
                if not is_transient(exc):
                    raise
                if delay is None:
                    if cheap:
                        raise
                    logger.warning("Reasoning model still unavailable (%s); falling back to the cheap model", exc)
                    self.calls += 1
                    return await make(True)
                logger.info("Transient model error (attempt %d): %s; retrying in %.0fs", attempt + 1, exc, delay)
                await asyncio.sleep(delay + random.uniform(0, 1.5))
        raise AssertionError("unreachable")

    def _model(self, cheap: bool, **kwargs: Any) -> ChatGoogleGenerativeAI:
        return ChatGoogleGenerativeAI(
            model=self._cheap if cheap else self._reasoning,
            google_api_key=self._key,
            temperature=0.2,
            **kwargs,
        )

    async def structured(self, schema: type[T], system: str, human: str, *, cheap: bool = False) -> T:
        async def make(use_cheap: bool) -> T:
            result = await self._model(use_cheap).with_structured_output(schema).ainvoke(
                [SystemMessage(content=system), HumanMessage(content=human)]
            )
            if result is None:
                raise ValueError(f"model returned no {schema.__name__}")
            return result

        return await self._call(cheap, make)

    async def json(self, system: str, human: str, *, cheap: bool = False) -> dict:
        """Free-form JSON (used for step blocks, whose union is too open for
        Gemini's structured output). Parsed leniently."""

        async def make(use_cheap: bool) -> dict:
            msg = await self._model(use_cheap, response_mime_type="application/json").ainvoke(
                [SystemMessage(content=system), HumanMessage(content=human)]
            )
            return parse_json_object(_text(msg.content))

        return await self._call(cheap, make)

    async def tool_round(self, messages: list[BaseMessage], tools: list) -> AIMessage:
        async def make(use_cheap: bool) -> AIMessage:
            return await self._model(use_cheap).bind_tools(tools).ainvoke(messages)

        return await self._call(False, make)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def parse_json_object(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if isinstance(value, list):
        return {"blocks": value}
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
