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

app = FastAPI(title="DRAAD API", version="0.1.0")

_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    return await run_chat(request.message)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    async def event_generator():
        try:
            async for event in run_chat_stream(request.message):
                data = event.model_dump()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error_event = {"type": "error", "agent": "", "summary": str(exc), "data": None}
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
