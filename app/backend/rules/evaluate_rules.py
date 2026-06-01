"""
Tool: evaluate_rules
Deterministic BEI-BLS rule gate. Validates a matcher proposal against the
five hard rules from the briefing §6.3.

No LLM call — pure Python logic so the verdict is auditable and reproducible.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

# Curated VWI catalogue — the set of VWI IDs that exist in idx_bls_corpus.
# Any VWI referenced by the matcher must be in this set.
CURATED_VWI_IDS = {
    "E-04", "E-11", "E-22", "E-22-onder-sp", "E-22-sp-loos",
    "E-40", "E-40-onder-sp", "E-40-sp-loos",
    "E-48", "E-60", "E-66", "E-67", "E-85",
}

# Live-work VWI variants
LIVE_WORK_VARIANTS = {"E-22-onder-sp", "E-40-onder-sp", "E-66"}

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


@lru_cache(maxsize=1)
def _load_raamopdrachten() -> tuple:
    """Load raamopdrachten from local data (cached after first call).
    Returns a tuple (immutable) so lru_cache can store it."""
    ro_path = _DATA_DIR / "raamopdrachten.json"
    if ro_path.exists():
        data = json.loads(ro_path.read_text(encoding="utf-8"))
        # Support both {"raamopdrachten": [...]} and bare [...]
        if isinstance(data, dict):
            data = data.get("raamopdrachten", list(data.values())[0])
        return tuple(data)
    return ()


def _find_ro(ro_id: str, ro_db: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ro in ro_db:
        if ro.get("raamopdracht_id") == ro_id:
            return ro
    return None


def evaluate_rules(proposal: dict[str, Any]) -> str:
    """Evaluate a matcher proposal against BEI-BLS hard rules.

    Args:
        proposal: The matcher's JSON proposal containing:
            - vwis: [{vwi_id, confidence}]
            - matched_raamopdracht_id: str
            - postcode: str (from incident anchors)
            - incident_timestamp: str (ISO datetime, optional)
            - requires_live_work: bool (optional)

    Returns:
        JSON string: [{rule_id, pass (bool), reason (str)}]
    """
    verdicts: list[dict[str, Any]] = []
    ro_db = list(_load_raamopdrachten())

    vwis = proposal.get("vwis", [])
    vwi_ids = [v.get("vwi_id", "") for v in vwis]
    confirmed_vwi_ids = [v.get("vwi_id", "") for v in vwis if v.get("confidence") == "confirmed"]
    ro_id = proposal.get("matched_raamopdracht_id", "")
    postcode = proposal.get("postcode", "")
    incident_ts = proposal.get("incident_timestamp", "")
    requires_live_work = proposal.get("requires_live_work", False)

    matched_ro = _find_ro(ro_id, ro_db) if ro_id else None

    # ---- BLS-R01: VWI existence ----
    # Every vwi_id must exist in the curated catalogue.
    unknown_vwis = [v for v in vwi_ids if v and v not in CURATED_VWI_IDS]
    verdicts.append({
        "rule_id": "BLS-R01",
        "pass": len(unknown_vwis) == 0,
        "reason": (
            f"Unknown VWI IDs not in catalogue: {unknown_vwis}"
            if unknown_vwis
            else "All VWI IDs exist in the curated catalogue."
        ),
    })

    # ---- BLS-R02: Coverage map ----
    # Every selected VWI (confirmed AND candidate) must appear in the matched RO's covered_vwi_ids[].
    # This determines coverage_status (covered/partial/not_covered).
    if matched_ro:
        ro_covered = set(matched_ro.get("covered_vwi_ids", []))
        uncovered = [v for v in vwi_ids if v and v not in ro_covered]
        verdicts.append({
            "rule_id": "BLS-R02",
            "pass": len(uncovered) == 0,
            "reason": (
                f"Confirmed VWIs not in RO {ro_id} coverage: {uncovered}. "
                f"RO covers: {sorted(ro_covered)}"
                if uncovered
                else f"All confirmed VWIs covered by RO {ro_id}."
            ),
        })
    else:
        verdicts.append({
            "rule_id": "BLS-R02",
            "pass": False,
            "reason": f"No matching raamopdracht found (ID: '{ro_id}').",
        })

    # ---- BLS-R03: Temporal validity ----
    # Incident timestamp must fall within RO geldigheidsduur_start..end.
    today = date.today()
    incident_date = _parse_date(incident_ts) or today
    if matched_ro:
        ro_start = _parse_date(matched_ro.get("geldigheidsduur_start"))
        ro_end = _parse_date(matched_ro.get("geldigheidsduur_end"))
        if ro_start and ro_end:
            in_range = ro_start <= incident_date <= ro_end
            verdicts.append({
                "rule_id": "BLS-R03",
                "pass": in_range,
                "reason": (
                    f"RO {ro_id} valid {ro_start} to {ro_end}, incident date {incident_date}."
                    if in_range
                    else f"RO {ro_id} expired or not yet valid: {ro_start} to {ro_end}, "
                         f"incident date {incident_date}."
                ),
            })
        else:
            verdicts.append({
                "rule_id": "BLS-R03",
                "pass": False,
                "reason": f"RO {ro_id} missing validity dates.",
            })
    else:
        verdicts.append({
            "rule_id": "BLS-R03",
            "pass": False,
            "reason": "No matched RO — cannot check temporal validity.",
        })

    # ---- BLS-R04: Geographic validity ----
    # Incident postcode must be in RO geldigheidsgebied_postcodes[].
    if matched_ro and postcode:
        ro_postcodes = set(matched_ro.get("geldigheidsgebied_postcodes", []))
        # Match on 4-digit prefix
        postcode_4 = postcode.strip()[:4]
        in_region = postcode_4 in ro_postcodes
        verdicts.append({
            "rule_id": "BLS-R04",
            "pass": in_region,
            "reason": (
                f"Postcode {postcode_4} is in RO {ro_id} region."
                if in_region
                else f"Postcode {postcode_4} NOT in RO {ro_id} region "
                     f"(valid: {sorted(ro_postcodes)})."
            ),
        })
    elif not postcode:
        verdicts.append({
            "rule_id": "BLS-R04",
            "pass": False,
            "reason": "No incident postcode provided — cannot verify geographic validity.",
        })
    else:
        verdicts.append({
            "rule_id": "BLS-R04",
            "pass": False,
            "reason": "No matched RO — cannot check geographic validity.",
        })

    # ---- BLS-R05: Variant compatibility ----
    # If a live-work (onder-sp) VWI is selected, the matched RO must permit it.
    live_vwis_selected = [v for v in vwi_ids if v in LIVE_WORK_VARIANTS]
    if live_vwis_selected or requires_live_work:
        if matched_ro:
            ro_permits = matched_ro.get("permits_live_work", False)
            ro_covered = set(matched_ro.get("covered_vwi_ids", []))
            uncovered_live = [v for v in live_vwis_selected if v not in ro_covered]
            ok = ro_permits and len(uncovered_live) == 0
            verdicts.append({
                "rule_id": "BLS-R05",
                "pass": ok,
                "reason": (
                    f"RO {ro_id} permits live work and covers {live_vwis_selected}."
                    if ok
                    else f"Live work required but RO {ro_id} "
                         f"{'does not permit live work' if not ro_permits else f'does not cover {uncovered_live}'}."
                ),
            })
        else:
            verdicts.append({
                "rule_id": "BLS-R05",
                "pass": False,
                "reason": "Live work required but no matched RO to verify.",
            })
    else:
        verdicts.append({
            "rule_id": "BLS-R05",
            "pass": True,
            "reason": "No live-work VWIs selected; variant check not applicable.",
        })

    return json.dumps(verdicts, ensure_ascii=False)
