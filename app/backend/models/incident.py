"""Pydantic models for incident data and anchors."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Anchors(BaseModel):
    """Structured anchors extracted from incident text or JSON input."""

    postcode: str | None = None
    voltage_class: str = "LS"
    asset_class: str = "unknown"
    timestamp: str = ""
    available_crew: list[str] = Field(default_factory=list)
    incident_id: str | None = None
    address: str | None = None


class IncidentPayload(BaseModel):
    """Full incident payload for the dispatch pipeline."""

    free_text: str
    anchors: Anchors
    incident_id: str
