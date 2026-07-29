"""Parsing utilities: anchor extraction, structured input, JSON recovery."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from models.incident import Anchors, IncidentPayload

MS_RE = re.compile(r"\bMS\b", re.IGNORECASE)
HS_RE = re.compile(r"\bHS\b", re.IGNORECASE)
CREW_RE = re.compile(r"crew-\d{3}-[A-Za-z-]+", re.IGNORECASE)
POSTCODE_RE = re.compile(r"\b(\d{4})\s*[A-Z]{0,2}\b", re.IGNORECASE)

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
    m = POSTCODE_RE.search(text)
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
        timestamp=datetime.now().astimezone().isoformat(),
        available_crew=crew if crew else [],
    )


class IncidentPayloadError(ValueError):
    """A JSON value looked like a structured incident but failed validation."""


def new_incident_id() -> str:
    """Return a collision-resistant, readable incident identifier."""
    return f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"


def _require_optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IncidentPayloadError(f"{field} must be a string")
    return value.strip() or None


def _validate_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now().astimezone().isoformat()
    if not isinstance(value, str) or not value.strip():
        raise IncidentPayloadError("received_at must be an ISO 8601 timestamp")
    candidate = value.strip()
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncidentPayloadError(
            "received_at must be an ISO 8601 timestamp"
        ) from exc
    return candidate


def parse_structured_input(text: str) -> IncidentPayload | None:
    """Try to parse text as a structured JSON incident.

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
    if not isinstance(free_text, str) or not free_text.strip():
        raise IncidentPayloadError("free_text_nl must be a non-empty string")
    free_text = free_text.strip()

    sa = data.get("structured_anchors", {})
    if not isinstance(sa, dict):
        raise IncidentPayloadError("structured_anchors must be an object")

    crew = data.get("available_crew", [])
    if not isinstance(crew, list) or any(
        not isinstance(item, str) or not item.strip() for item in crew
    ):
        raise IncidentPayloadError("available_crew must be an array of crew IDs")
    crew = [item.strip() for item in crew]

    postcode = _require_optional_string(sa.get("postcode"), "postcode")
    if postcode:
        match = POSTCODE_RE.search(postcode)
        if not match:
            raise IncidentPayloadError("postcode must contain a four-digit prefix")
        postcode = match.group(1)

    voltage_class = _require_optional_string(
        sa.get("voltage_class", "LS"), "voltage_class"
    ) or "LS"
    voltage_class = voltage_class.upper()
    if voltage_class not in {"LS", "MS", "HS"}:
        raise IncidentPayloadError("voltage_class must be LS, MS, or HS")

    anchors = Anchors(
        postcode=postcode,
        voltage_class=voltage_class,
        asset_class=(
            _require_optional_string(
                sa.get("asset_class_hint", sa.get("asset_class")),
                "asset_class",
            )
            or "unknown"
        ),
        timestamp=_validate_timestamp(data.get("received_at")),
        available_crew=crew,
        incident_id=_require_optional_string(data.get("incident_id"), "incident_id"),
        address=_require_optional_string(sa.get("address"), "address"),
    )

    incident_id = anchors.incident_id or new_incident_id()

    return IncidentPayload(
        free_text=free_text,
        anchors=anchors,
        incident_id=incident_id,
    )


def try_parse_json(text: str) -> dict | list | None:
    """Extract the first complete JSON object or array from model output.

    ``JSONDecoder.raw_decode`` correctly handles nested values and braces inside
    strings, unlike a greedy regular expression.
    """
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, (dict, list)) else None
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for position, character in enumerate(cleaned):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[position:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
    return None
