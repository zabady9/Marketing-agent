import json
from enum import StrEnum
from typing import Any, AsyncGenerator

from sse_starlette.sse import ServerSentEvent


class SSEEvent(StrEnum):
    # Intake
    LANGUAGE_DETECTED = "language_detected"
    INTAKE_WARNING = "intake_warning"

    # Per-agent
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_WARNING = "agent_warning"

    # Web search
    SEARCH_QUERY_SENT = "search_query_sent"
    SEARCH_RESULTS_RECEIVED = "search_results_received"

    # Financial calculation
    CALC_STARTED = "calc_started"
    CALC_COMPLETED = "calc_completed"
    CALC_FAILED = "calc_failed"

    # Report sections (streamed incrementally)
    SECTION_READY = "section_ready"

    # QC gate
    QC_STARTED = "qc_started"
    QC_FLAG_RAISED = "qc_flag_raised"
    QC_COMPLETED = "qc_completed"

    # Chat
    CHAT_TOOL_ERROR = "chat_tool_error"
    CHAT_MESSAGE_COMPLETED = "chat_message_completed"


def make_event(event: SSEEvent, data: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(
        event=event,
        data=json.dumps(data, ensure_ascii=False),
    )


class EventQueue:
    """
    Async generator queue used by the orchestrator to push SSE events
    and by the router to stream them to the client.
    """

    def __init__(self) -> None:
        import asyncio
        self._queue: asyncio.Queue[ServerSentEvent | None] = asyncio.Queue()

    async def put(self, event: SSEEvent, data: dict[str, Any]) -> None:
        await self._queue.put(make_event(event, data))

    async def close(self) -> None:
        await self._queue.put(None)  # sentinel

    async def __aiter__(self) -> AsyncGenerator[ServerSentEvent, None]:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item
