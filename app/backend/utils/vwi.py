"""Canonical VWI identifiers and coverage matching.

VWI work-mode suffixes are safety-significant. A bare base code may only expand
to a suffixed code when the indexed corpus contains exactly one variant for that
base. Bases such as E-22 and E-40 have both energized and de-energized variants,
so they must never be treated as interchangeable.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_VWI_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "VWI"
_VWI_CODE_RE = re.compile(
    r"\bE[-_]\d{2}(?:[-_](?:onder[-_]sp|sp[-_]loos))?\b",
    re.IGNORECASE,
)


def normalize_vwi_code(raw: str) -> str:
    """Return the canonical spelling for a syntactically valid VWI code."""
    match = _VWI_CODE_RE.fullmatch(raw.strip())
    if not match:
        return ""
    parts = match.group(0).upper().replace("_", "-").split("-")
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"
    return f"{parts[0]}-{parts[1]}-{'-'.join(p.lower() for p in parts[2:])}"


@lru_cache(maxsize=1)
def load_indexed_vwi_ids() -> frozenset[str]:
    """Build the VWI catalogue from the PDF filenames used by the indexer."""
    ids: set[str] = set()
    for path in _VWI_DOCS_DIR.glob("*.pdf"):
        match = _VWI_CODE_RE.search(path.name)
        if match:
            ids.add(normalize_vwi_code(match.group(0)))
    ids.discard("")
    if not ids:
        raise RuntimeError(f"No VWI documents found under {_VWI_DOCS_DIR}")
    return frozenset(ids)


def vwi_matches(
    selected: str,
    covered: str,
    *,
    catalogue: frozenset[str] | None = None,
) -> bool:
    """Return whether a selected VWI is covered without crossing work modes.

    Exact identifiers always match. A bare selected base can match a suffixed
    covered identifier only if the catalogue contains exactly one variant for
    that base. This permits defensive recovery from a dropped suffix only when
    doing so is unambiguous.
    """
    selected_code = normalize_vwi_code(selected)
    covered_code = normalize_vwi_code(covered)
    if not selected_code or not covered_code:
        return False
    if selected_code == covered_code:
        return True
    if selected_code.count("-") != 1:
        return False

    prefix = selected_code + "-"
    variants = {
        code
        for code in (catalogue or load_indexed_vwi_ids())
        if code.startswith(prefix)
    }
    return len(variants) == 1 and covered_code in variants


def is_live_work_vwi(vwi_id: str) -> bool:
    """Return whether a VWI explicitly represents energized work."""
    code = normalize_vwi_code(vwi_id)
    return code.endswith("-onder-sp") or code in {"E-45", "E-66"}
