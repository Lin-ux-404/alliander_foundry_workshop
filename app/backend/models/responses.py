"""Pydantic models for API request/response."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    type: str
    response: Any
    model: str
    sources: list[str] = []


class StepEvent(BaseModel):
    """Server-Sent Event payload for pipeline progress."""

    type: str  # step_start, step_complete, incident_detected, result, error
    agent: str = ""
    summary: str = ""
    data: Any = None
