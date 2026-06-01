"""Parsing utilities: anchor extraction, structured input, JSON recovery."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from models.incident import Anchors, IncidentPayload

MS_RE = re.compile(r"\bMS\b")
HS_RE = re.compile(r"\bHS\b")
CREW_RE = re.compile(r"crew-\d{3}-[A-Za-z-]+")

_ASSET_KEYWORDS = [
    ("aansluitkast", "aansluitkast"),
    ("meterkast", "meterkast"),
    ("schakelstation", "schakelstation"),
    ("kabelnet", "kabelnet"),
    ("transformator", "transformator"),
    ("mof", "kabelnet"),
    ("rek", "schakelstation"),
]


def extract_anchors(text: str) -> Anchors:
    """Extract structured anchors from free-text incident description."""
    postcode = None
    m = re.search(r"\b(\d{4})\s*[A-Z]{0,2}\b", text)
    if m:
        postcode = m.group(1)

    voltage_class = "LS"
    if MS_RE.search(text):
        voltage_class = "MS"
    elif HS_RE.search(text):
        voltage_class = "HS"

    asset_class = "unknown"
    text_lower = text.lower()
    for kw, cls in _ASSET_KEYWORDS:
        if kw in text_lower:
            asset_class = cls
            break

    crew = CREW_RE.findall(text)

    return Anchors(
        postcode=postcode,
        voltage_class=voltage_class,
        asset_class=asset_class,
        timestamp=datetime.now().isoformat(),
        available_crew=crew if crew else [],
    )


def parse_structured_input(text: str) -> IncidentPayload | None:
    """Try to parse text as structured JSON incident input (§5 format).

    Returns an IncidentPayload if valid, None otherwise.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if "free_text_nl" not in data and "structured_anchors" not in data:
        return None

    free_text = data.get("free_text_nl", "")
    sa = data.get("structured_anchors", {})
    crew = data.get("available_crew", [])

    anchors = Anchors(
        postcode=sa.get("postcode"),
        voltage_class=sa.get("voltage_class", "LS"),
        asset_class=sa.get("asset_class_hint", sa.get("asset_class", "unknown")),
        timestamp=data.get("received_at", datetime.now().isoformat()),
        available_crew=crew,
        incident_id=data.get("incident_id"),
        address=sa.get("address"),
    )

    incident_id = (
        anchors.incident_id
        or f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )

    return IncidentPayload(
        free_text=free_text,
        anchors=anchors,
        incident_id=incident_id,
    )


def try_parse_json(text: str) -> dict | list | None:
    """Best-effort JSON extraction: strips markdown fences, searches for objects/arrays."""
    cleaned = re.sub(r"```json?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue
    return None
