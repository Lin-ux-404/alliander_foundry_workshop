"""
Dispatch workflow: 3-agent + rules + revision loop for incident processing.

Pipeline:
  1. procedure_retriever → VWI candidates
  2. dispatch_matcher    → structured proposal  (revision loop)
  3. rule_checker        → deterministic verdicts
  4. dispatch_reviewer   → pass / revise / flagged_for_human_review
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from agents.matcher import MATCHER_NAME
from agents.retriever import RETRIEVER_NAME
from agents.reviewer import REVIEWER_NAME
from config import MAX_REVISIONS, MODEL
from models.incident import IncidentPayload
from models.responses import ChatResponse, StepEvent
from rules.evaluate_rules import evaluate_rules
from utils.agent_runner import stream_foundry_agent
from utils.parsing import try_parse_json


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
    reviewer_feedback: str | None,
    revision: int,
) -> str:
    a = payload.anchors
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
        "=== VWI CANDIDATES ===",
        json.dumps(vwi_candidates, ensure_ascii=False),
        "=== END VWI CANDIDATES ===",
    ]
    if reviewer_feedback:
        parts.extend([
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
            payload, crew_label, vwi_candidates,
            reviewer_feedback, revision,
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

        matched_ro = matcher_proposal.get("matched_raamopdracht_id", "none")
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
    if final["review_status"] == "flagged_for_human_review" or any_hard_fail:
        final["operational_action"] = "wv_escalation_needed"

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
