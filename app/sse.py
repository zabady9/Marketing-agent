import json
from enum import StrEnum
from typing import Any, AsyncGenerator

from sse_starlette.sse import ServerSentEvent


class SSEEvent(StrEnum):
    # Intake
    LANGUAGE_DETECTED = "language_detected"
    INTAKE_WARNING = "intake_warning"

    # Analysis runs (app.analysis.engine) — every payload carries study_id,
    # so the chat UI can attribute each event to the right run even when
    # several run in parallel in one turn.
    STUDY_STARTED = "study_started"
    ANALYSIS_PLAN_READY = "analysis_plan_ready"
    ANALYSIS_STEP_STARTED = "analysis_step_started"
    ANALYSIS_STEP_COMPLETED = "analysis_step_completed"
    STUDY_COMPLETED = "study_completed"

    # Chat
    CHAT_TOOL_ERROR = "chat_tool_error"
    CHAT_MESSAGE_DELTA = "chat_message_delta"
    CHAT_MESSAGE_COMPLETED = "chat_message_completed"
    # Fired the moment generate_chart_tool produces a validated ChartSpec —
    # lets the frontend render the chart live, mid-turn.
    CHAT_CHART_READY = "chat_chart_ready"
    # Fired the moment a generate_presentation_tool/generate_word_document_tool/
    # generate_pdf_report_tool/revise_artifact_tool call produces a file —
    # lets the frontend render a downloadable artifact card live, mirroring
    # CHAT_CHART_READY.
    CHAT_ARTIFACT_READY = "chat_artifact_ready"


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

