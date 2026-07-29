"""
pipeline.py — Thin router: classifies user input and delegates to the
appropriate workflow (Q&A or dispatch).

Q&A path:    workflows.qa.run_qa()
Dispatch:    workflows.dispatch.run_dispatch_stream()
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from models.incident import IncidentPayload
from models.responses import StepEvent
from utils.intent import is_incident
from utils.parsing import extract_anchors, new_incident_id, parse_structured_input
from workflows.dispatch import run_dispatch_stream
from workflows.qa import run_qa


async def run_chat(user_message: str) -> dict:
    """Non-streaming entry point — collects the stream and returns the final result dict."""
    last_data: dict = {}
    async for event in run_chat_stream(user_message):
        if event.type == "result" and event.data:
            last_data = event.data
    return last_data


async def run_chat_stream(user_message: str) -> AsyncGenerator[StepEvent, None]:
    """Streaming entry point — yields StepEvents for SSE."""

    payload = parse_structured_input(user_message)

    if payload:
        async for event in run_dispatch_stream(payload):
            yield event
        return

    if not is_incident(user_message):
        response = await run_qa(user_message)
        yield StepEvent(
            type="result",
            agent="qa_assistant",
            summary="Q&A response",
            data=response.model_dump(),
        )
        return

    anchors = extract_anchors(user_message)
    incident_id = new_incident_id()
    payload = IncidentPayload(
        free_text=user_message,
        anchors=anchors,
        incident_id=incident_id,
    )
    async for event in run_dispatch_stream(payload):
        yield event
