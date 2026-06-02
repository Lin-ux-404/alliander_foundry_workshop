"""
Dispatch workflow: 3-agent + rules + revision loop for incident processing.

Pipeline:
  1. procedure_retriever → VWI candidates (LLM: semantic relevance over 193-chunk
     BLS rulebook)
  2. PYTHON: filter raamopdrachten by postcode + date window
  3. dispatch_matcher    → selects VWIs + writes rationale/citations only.
     RO selection, crew assignment, coverage_status are computed deterministically
     in Python from the matcher's VWI selection — the LLM never picks the RO.
  4. PYTHON: pick best RO by VWI overlap, lookup crew, compute coverage_status
  5. rule_checker        → deterministic verdicts
  6. dispatch_reviewer   → pass / revise / flagged_for_human_review (revisions
     only affect VWI selection; structured fields are always re-derived)
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from functools import lru_cache
from pathlib import Path
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

from agents.matcher import MATCHER_NAME
from agents.retriever import RETRIEVER_NAME
from agents.reviewer import REVIEWER_NAME
from config import MAX_REVISIONS, MODEL
from models.incident import IncidentPayload
from models.responses import ChatResponse, StepEvent
from rules.evaluate_rules import evaluate_rules
from utils.agent_runner import stream_foundry_agent
from utils.parsing import try_parse_json


@lru_cache(maxsize=1)
def _bls_search_client() -> SearchClient:
    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    key = os.getenv("AZURE_SEARCH_ADMIN_KEY")
    cred = AzureKeyCredential(key) if key else DefaultAzureCredential()
    return SearchClient(
        endpoint=endpoint,
        index_name=os.getenv("AZURE_SEARCH_INDEX", "idx_bls_corpus"),
        credential=cred,
    )


def _fallback_retrieve_vwis(query: str, top: int = 8) -> list[dict]:
    """Direct Azure Search fallback when the retriever LLM returns an empty array.

    Returns the same shape the LLM was supposed to produce, deduped by vwi_code.
    """
    try:
        hits = _bls_search_client().search(
            search_text=query or "*",
            top=top * 3,
            select=["vwi_code", "title", "content", "source_file"],
        )
    except Exception:
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for h in hits:
        code = h.get("vwi_code")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({
            "vwi_id": code,
            "title": h.get("title") or code,
            "content": h.get("content") or "",
            "score": h.get("@search.score"),
            "source_doc": h.get("source_file"),
        })
        if len(out) >= top:
            break
    return out


# ---- Deterministic data lookups (synthetic data, small & local) ----

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@lru_cache(maxsize=1)
def _load_raamopdrachten() -> list[dict]:
    data = json.loads((_DATA_DIR / "raamopdrachten.json").read_text(encoding="utf-8"))
    return data.get("raamopdrachten", []) if isinstance(data, dict) else data


@lru_cache(maxsize=1)
def _load_crew() -> list[dict]:
    data = json.loads((_DATA_DIR / "crew.json").read_text(encoding="utf-8"))
    return data.get("crew", []) if isinstance(data, dict) else data


def _filter_raamopdrachten(
    postcode: str | None,
    timestamp: str | None,
    available_crew: list[str] | None,
) -> list[dict]:
    """Deterministic filter: postcode prefix in scope AND date in validity window.

    Returns the surviving ROs untouched. RO selection from this filtered set is
    done after the matcher picks VWIs (by max VWI overlap).
    """
    ros = _load_raamopdrachten()
    day = (timestamp or "")[:10]
    prefix = (postcode or "")[:4]
    crew_filter: set[str] | None = None
    if available_crew:
        crew_to_ro: dict[str, list[str]] = {
            c["crew_id"]: c.get("raamopdracht_ids", []) for c in _load_crew()
        }
        crew_filter = set()
        for cid in available_crew:
            crew_filter.update(crew_to_ro.get(cid, []))

    out: list[dict] = []
    for ro in ros:
        if day:
            start = ro.get("geldigheidsduur_start", "0000-00-00")
            end = ro.get("geldigheidsduur_end", "9999-12-31")
            if not (start <= day <= end):
                continue
        if prefix:
            if prefix not in ro.get("geldigheidsgebied_postcodes", []):
                continue
        if crew_filter is not None and ro.get("raamopdracht_id") not in crew_filter:
            continue
        out.append(ro)
    return out


def _vwi_matches(selected: str, covered: str) -> bool:
    """Exact match, or selected is a bare base code (E-22) that prefix-matches
    a fully-qualified covered code (E-22-onder-sp, E-22-sp-loos).
    Defensive: covers cases where the indexer or matcher dropped the suffix.
    """
    if selected == covered:
        return True
    # Bare base like "E-22" matches "E-22-*"
    if "-" in selected and selected.count("-") == 1 and covered.startswith(selected + "-"):
        return True
    return False


def _overlap_vwi_set(selected_ids: list[str], covered_ids: list[str]) -> set[str]:
    """Return the set of *selected* IDs that have a matching covered ID (using
    exact or base-code prefix match). Returns selected-IDs so coverage math
    against the selection is consistent.
    """
    out: set[str] = set()
    for s in selected_ids:
        for c in covered_ids:
            if _vwi_matches(s, c):
                out.add(s)
                break
    return out


def _pick_best_ro(
    filtered_ros: list[dict],
    selected_vwi_ids: list[str],
) -> tuple[dict | None, set[str]]:
    """Pick the RO with maximum VWI overlap; tie-break by smaller scope (more specific)."""
    if not filtered_ros or not selected_vwi_ids:
        return None, set()
    best: dict | None = None
    best_overlap: set[str] = set()
    for ro in filtered_ros:
        overlap = _overlap_vwi_set(selected_vwi_ids, ro.get("covered_vwi_ids", []))
        if len(overlap) > len(best_overlap):
            best, best_overlap = ro, overlap
        elif (
            len(overlap) == len(best_overlap)
            and best is not None
            and len(ro.get("covered_vwi_ids", [])) < len(best.get("covered_vwi_ids", []))
        ):
            best, best_overlap = ro, overlap
    return best, best_overlap


def _coverage_status(selected_vwi_ids: list[str], covered_overlap: set[str]) -> str:
    if not selected_vwi_ids:
        return "unknown"
    sel = set(selected_vwi_ids)
    if not covered_overlap:
        return "not_covered"
    if covered_overlap >= sel:
        return "covered"
    return "partial"


def _crew_for_ro(ra_id: str | None) -> str | None:
    if not ra_id:
        return None
    for c in _load_crew():
        if ra_id in c.get("raamopdracht_ids", []):
            return c.get("crew_id")
    return None


def _apply_deterministic_match(
    matcher_proposal: dict,
    filtered_ros: list[dict],
) -> dict:
    """Overwrite RO/crew/coverage with Python-derived values; keep VWIs + rationale."""
    vwis = matcher_proposal.get("vwis", []) if isinstance(matcher_proposal, dict) else []
    vwi_ids = [v.get("vwi_id", "") for v in vwis if v.get("vwi_id")]
    best_ro, overlap = _pick_best_ro(filtered_ros, vwi_ids)

    if best_ro is None:
        matcher_proposal["matched_raamopdracht_id"] = None
        matcher_proposal["matched_crew"] = None
        matcher_proposal["coverage_status"] = "unknown" if not vwi_ids else "not_covered"
    else:
        ra_id = best_ro.get("raamopdracht_id")
        matcher_proposal["matched_raamopdracht_id"] = ra_id
        matcher_proposal["matched_crew"] = _crew_for_ro(ra_id)
        matcher_proposal["coverage_status"] = _coverage_status(vwi_ids, overlap)
    return matcher_proposal


# ---- Input formatters ----

def _format_retriever_input(payload: IncidentPayload, crew_label: list[str]) -> str:
    a = payload.anchors
    return (
        f"=== INCIDENT PAYLOAD ===\n"
        f"Incident ID: {payload.incident_id}\n"
        f"Free text: {payload.free_text}\n"
        f"Postcode: {a.postcode or 'unknown'}\n"
        f"Voltage class: {a.voltage_class}\n"
        f"Asset class: {a.asset_class}\n"
        f"Timestamp: {a.timestamp}\n"
        f"Available crew: {crew_label}\n"
        f"=== END INCIDENT PAYLOAD ==="
    )


def _format_matcher_input(
    payload: IncidentPayload,
    crew_label: list[str],
    vwi_candidates: list,
    filtered_ros: list[dict],
    reviewer_feedback: str | None,
    revision: int,
    previous_proposal: dict | None = None,
) -> str:
    a = payload.anchors
    # Compact RO summaries for the matcher (no need to send the full doc, just
    # what's required to write citations and pick a sane VWI list).
    ro_summary = [
        {
            "raamopdracht_id": r.get("raamopdracht_id"),
            "bestemd_voor": r.get("bestemd_voor"),
            "covered_vwi_ids": r.get("covered_vwi_ids", []),
            "permits_live_work": r.get("permits_live_work"),
            "omschrijving_werkzaamheden": r.get("omschrijving_werkzaamheden"),
            "omschrijving_bedieningshandelingen": r.get(
                "omschrijving_bedieningshandelingen"
            ),
        }
        for r in filtered_ros
    ]
    parts = [
        "=== INCIDENT PAYLOAD ===",
        f"Incident ID: {payload.incident_id}",
        f"Free text: {payload.free_text}",
        f"Postcode: {a.postcode or 'unknown'}",
        f"Voltage class: {a.voltage_class}",
        f"Asset class: {a.asset_class}",
        f"Timestamp: {a.timestamp}",
        f"Available crew: {crew_label}",
        "=== END INCIDENT PAYLOAD ===",
        "",
        "=== VWI CANDIDATES (from rulebook retrieval) ===",
        json.dumps(vwi_candidates, ensure_ascii=False),
        "=== END VWI CANDIDATES ===",
        "",
        "=== FILTERED RAAMOPDRACHTEN (already filtered by postcode + date) ===",
        json.dumps(ro_summary, ensure_ascii=False),
        "=== END FILTERED RAAMOPDRACHTEN ===",
    ]
    if reviewer_feedback:
        parts.extend([
            "",
            f"=== PREVIOUS PROPOSAL (revision {revision}) ===",
            json.dumps(previous_proposal or {}, ensure_ascii=False),
            "=== END PREVIOUS PROPOSAL ===",
            "",
            f"=== REVIEWER FEEDBACK (revision {revision}) ===",
            reviewer_feedback,
            "=== END REVIEWER FEEDBACK ===",
        ])
    return "\n".join(parts)


def _format_reviewer_input(
    payload: IncidentPayload,
    matcher_proposal: dict,
    rule_findings: list,
    revision: int,
) -> str:
    a = payload.anchors
    return (
        "=== INCIDENT PAYLOAD (ORIGINAL) ===\n"
        f"Incident ID: {payload.incident_id}\n"
        f"Free text: {payload.free_text}\n"
        f"Postcode: {a.postcode or 'unknown'}\n"
        f"Voltage class: {a.voltage_class}\n"
        f"Asset class: {a.asset_class}\n"
        "=== END INCIDENT PAYLOAD ===\n\n"
        "=== MATCHER PROPOSAL ===\n"
        f"{json.dumps(matcher_proposal, ensure_ascii=False)}\n"
        "=== END MATCHER PROPOSAL ===\n\n"
        "=== RULE FINDINGS ===\n"
        f"{json.dumps(rule_findings, ensure_ascii=False)}\n"
        "=== END RULE FINDINGS ===\n\n"
        f"Revision iteration: {revision} of {MAX_REVISIONS} max."
    )


# ---- Streaming dispatch pipeline ----

async def run_dispatch_stream(
    payload: IncidentPayload,
) -> AsyncGenerator[StepEvent, None]:
    """Execute the dispatch pipeline, yielding StepEvent for each stage."""
    crew_label = (
        payload.anchors.available_crew
        if payload.anchors.available_crew
        else ["(all available crew)"]
    )

    yield StepEvent(
        type="incident_detected",
        agent="intent_classifier",
        summary=f"Incident {payload.incident_id} detected",
        data={
            "incident_id": payload.incident_id,
            "postcode": payload.anchors.postcode,
            "voltage_class": payload.anchors.voltage_class,
            "asset_class": payload.anchors.asset_class,
        },
    )

    # Step 1: procedure_retriever
    yield StepEvent(
        type="step_start", agent="procedure_retriever",
        summary="Searching BLS corpus for VWI candidates...",
    )
    retriever_input = _format_retriever_input(payload, crew_label)
    retriever_text = ""
    async for tok in stream_foundry_agent(RETRIEVER_NAME, retriever_input):
        retriever_text += tok
        yield StepEvent(
            type="token", agent="procedure_retriever",
            summary=tok,
        )
    retriever_data = try_parse_json(retriever_text)

    vwi_candidates: list = []
    if isinstance(retriever_data, dict):
        vwi_candidates = retriever_data.get("vwi_candidates", [])

    # Fallback: gpt-5.4-mini sometimes returns an empty array even when search
    # has hits. Do a direct Azure Search call so the matcher always has VWIs.
    if not vwi_candidates:
        vwi_candidates = _fallback_retrieve_vwis(payload.free_text)
        if vwi_candidates:
            yield StepEvent(
                type="step_complete",
                agent="procedure_retriever",
                summary=(
                    f"LLM returned empty; deterministic fallback found "
                    f"{len(vwi_candidates)} VWI(s)"
                ),
            )

    vwi_ids_found = [
        v.get("vwi_id", "?") for v in vwi_candidates
    ]
    yield StepEvent(
        type="step_complete",
        agent="procedure_retriever",
        summary=(
            f"Found {len(vwi_candidates)} VWI candidate(s): "
            f"{', '.join(vwi_ids_found) or 'none'}"
        ),
    )

    # Deterministic pre-filter: which raamopdrachten could possibly apply?
    filtered_ros = _filter_raamopdrachten(
        payload.anchors.postcode,
        payload.anchors.timestamp,
        payload.anchors.available_crew,
    )
    ro_ids_filtered = [r.get("raamopdracht_id") for r in filtered_ros]
    yield StepEvent(
        type="step_complete",
        agent="procedure_retriever",
        summary=(
            f"Filtered {len(filtered_ros)} raamopdracht(en) by postcode+date: "
            f"{', '.join(ro_ids_filtered) or 'none'}"
        ),
    )

    # Revision loop
    revision = 0
    reviewer_feedback: str | None = None
    matcher_proposal: dict[str, Any] = {}
    rule_findings: list = []
    reviewer_verdict: dict[str, Any] = {}

    while revision <= MAX_REVISIONS:
        # Step 2: dispatch_matcher
        suffix = f" (revision {revision})" if revision > 0 else ""
        yield StepEvent(
            type="step_start", agent="dispatch_matcher",
            summary=f"Building dispatch proposal{suffix}...",
        )
        matcher_input = _format_matcher_input(
            payload, crew_label, vwi_candidates, filtered_ros,
            reviewer_feedback, revision,
            previous_proposal=matcher_proposal if revision > 0 else None,
        )
        matcher_text = ""
        async for tok in stream_foundry_agent(
            MATCHER_NAME, matcher_input,
        ):
            matcher_text += tok
            yield StepEvent(
                type="token", agent="dispatch_matcher",
                summary=tok,
            )
        matcher_proposal = (
            try_parse_json(matcher_text) or {"raw": matcher_text}
        )

        # Deterministic post-step: overwrite matched_raamopdracht_id, matched_crew,
        # coverage_status with values derived from VWI overlap. The LLM never picks
        # the RO, so revisions cannot regress these structured fields.
        if isinstance(matcher_proposal, dict):
            matcher_proposal = _apply_deterministic_match(matcher_proposal, filtered_ros)

        matched_ro = matcher_proposal.get("matched_raamopdracht_id") or "none"
        coverage = matcher_proposal.get("coverage_status", "unknown")
        yield StepEvent(
            type="step_complete",
            agent="dispatch_matcher",
            summary=f"Proposed RO: {matched_ro}, coverage: {coverage}",
        )

        # Step 3: rule_checker (deterministic)
        yield StepEvent(type="step_start", agent="rule_checker", summary="Evaluating BEI-BLS hard rules...")
        vwis_from_proposal = (
            matcher_proposal.get("vwis", [])
            if isinstance(matcher_proposal, dict) else []
        )
        vwi_ids = [v.get("vwi_id", "") for v in vwis_from_proposal]
        requires_live = any("onder-sp" in v for v in vwi_ids)

        rule_input = (
            dict(matcher_proposal) if isinstance(matcher_proposal, dict) else {}
        )
        rule_input["postcode"] = payload.anchors.postcode or ""
        rule_input["incident_timestamp"] = payload.anchors.timestamp
        rule_input["requires_live_work"] = requires_live

        rule_findings = json.loads(evaluate_rules(rule_input))

        passed = sum(1 for r in rule_findings if r.get("pass", False))
        total = len(rule_findings)
        yield StepEvent(
            type="step_complete",
            agent="rule_checker",
            summary=f"{passed}/{total} rules passed",
        )

        # Step 4: dispatch_reviewer
        yield StepEvent(
            type="step_start", agent="dispatch_reviewer",
            summary="Reviewing proposal (LLM-as-judge)...",
        )
        reviewer_input = _format_reviewer_input(
            payload, matcher_proposal, rule_findings, revision,
        )
        reviewer_text = ""
        async for tok in stream_foundry_agent(
            REVIEWER_NAME, reviewer_input,
        ):
            reviewer_text += tok
            yield StepEvent(
                type="token", agent="dispatch_reviewer",
                summary=tok,
            )
        reviewer_verdict = try_parse_json(reviewer_text) or {
            "review_status": "flagged_for_human_review",
            "findings": [],
            "feedback_for_matcher": None,
        }

        review_status = reviewer_verdict.get("review_status", "pass")
        yield StepEvent(
            type="step_complete",
            agent="dispatch_reviewer",
            summary=f"Verdict: {review_status}",
        )

        if review_status == "revise" and revision < MAX_REVISIONS:
            revision += 1
            reviewer_feedback = reviewer_verdict.get("feedback_for_matcher", "")
            yield StepEvent(
                type="step_start",
                agent="dispatch_reviewer",
                summary=f"Requesting revision {revision}: {reviewer_feedback[:120]}...",
            )
            continue

        if review_status == "revise":
            reviewer_verdict["review_status"] = "flagged_for_human_review"
        break

    # Assemble final response
    final: dict[str, Any] = (
        dict(matcher_proposal) if isinstance(matcher_proposal, dict) else {}
    )
    final["incident_id"] = payload.incident_id
    final["review_status"] = reviewer_verdict.get("review_status", "pass")
    final["review_findings"] = reviewer_verdict.get("findings", [])
    final["rule_verdicts"] = rule_findings
    final["revision_count"] = revision

    any_hard_fail = any(not r.get("pass", True) for r in rule_findings)
    coverage_final = final.get("coverage_status")
    if (
        final["review_status"] == "flagged_for_human_review"
        or any_hard_fail
        or coverage_final != "covered"
        or not final.get("matched_raamopdracht_id")
    ):
        final["operational_action"] = "wv_escalation_needed"
    else:
        final["operational_action"] = "dispatch_ok"

    vwi_ids_out = [v.get("vwi_id", "") for v in final.get("vwis", [])]

    yield StepEvent(
        type="result",
        agent="pipeline",
        summary="Dispatch complete",
        data=ChatResponse(
            type="dispatch",
            response=final,
            model=MODEL,
            sources=vwi_ids_out,
        ).model_dump(),
    )
