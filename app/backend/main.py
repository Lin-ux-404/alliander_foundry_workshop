"""
main.py — FastAPI application for DRAAD.

Endpoints:
  POST /api/chat        — JSON response; accepts {message: str}
  POST /api/chat/stream — SSE stream with agent step events
  GET  /api/health      — health check

CORS is configured for localhost:3000 (Next.js dev server).
Set ALLOWED_ORIGINS env var to override in production.
"""
from __future__ import annotations

import json
import os
import logging
import warnings
from uuid import uuid4

# Suppress noisy Azure SDK failsafe deserialization tracebacks.
# The SDK prints these via the logger with exc_info=True at DEBUG level.
logging.getLogger("azure").setLevel(logging.ERROR)

# Suppress experimental warnings from agent-framework-foundry SDK.
warnings.filterwarnings("ignore", category=UserWarning, message=".*ExperimentalWarning.*")
warnings.filterwarnings("ignore", message=".*MemoryStore is experimental.*")
warnings.filterwarnings("ignore", message=".*SkillResource is experimental.*")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from models.responses import ChatRequest
from pipeline import run_chat, run_chat_stream
from utils.parsing import IncidentPayloadError

app = FastAPI(title="DRAAD API", version="0.1.0")

_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
_allow_credentials = "*" not in _origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    try:
        return await run_chat(request.message)
    except IncidentPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    async def event_generator():
        try:
            async for event in run_chat_stream(request.message):
                data = event.model_dump()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except IncidentPayloadError as exc:
            error_event = {
                "type": "error",
                "agent": "",
                "summary": str(exc),
                "data": None,
            }
            yield f"data: {json.dumps(error_event)}\n\n"
        except Exception:
            reference = uuid4().hex[:12]
            logging.getLogger(__name__).exception(
                "Unhandled chat stream failure (reference=%s)", reference
            )
            error_event = {
                "type": "error",
                "agent": "",
                "summary": f"Pipeline failed. Reference: {reference}",
                "data": None,
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
