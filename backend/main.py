"""
main.py — FastAPI application for DRAAD.

Endpoints:
  POST /api/chat   — JSON response; accepts {message: str}
  GET  /api/health — health check

CORS is configured for localhost:3000 (Next.js dev server).
Set ALLOWED_ORIGINS env var to override in production.
"""
from __future__ import annotations

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
from pydantic import BaseModel

from pipeline import run_chat

app = FastAPI(title="DRAAD API", version="0.1.0")

_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    return await run_chat(request.message)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
