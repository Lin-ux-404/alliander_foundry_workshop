"""Intent detection: classify user message as incident vs Q&A."""
from __future__ import annotations

import re

INCIDENT_KEYWORDS = [
    "storing", "stroom", "spanningsloos", "uitval", "alarm",
    "brandlucht", "vonken", "rook", "schade", "kapot",
    "meldt", "melding", "klant meldt", "scada",
    "monteur", "dispatch", "dekkingsanalyse",
    "aansluitkast", "meterkast", "zekering",
]

POSTCODE_RE = re.compile(r"\b\d{4}\s*[A-Z]{0,2}\b")


def is_incident(text: str) -> bool:
    """Return True if text looks like an incident report."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in INCIDENT_KEYWORDS):
        return True
    if POSTCODE_RE.search(text):
        return True
    return False
