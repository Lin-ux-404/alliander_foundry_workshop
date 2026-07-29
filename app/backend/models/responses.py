"""Pydantic models for API request/response."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(max_length=16_000)


class ChatResponse(BaseModel):
    type: str
    response: Any
    model: str
    sources: list[str] = Field(default_factory=list)


class StepEvent(BaseModel):
    """Server-Sent Event payload for pipeline progress."""

    type: str  # step_start, step_complete, incident_detected, result, error
    agent: str = ""
    summary: str = ""
    data: Any = None
