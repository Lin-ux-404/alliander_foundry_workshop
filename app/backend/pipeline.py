"""
pipeline.py
Routes user messages to either Q&A or the 3-agent dispatch pipeline.
All LLM agents are Foundry-managed Prompt Agents (deployed via deploy_agents.py).
The rule_checker is deterministic (no LLM).

Q&A path:
  FoundryAgent(draad-qa-assistant) → {type: "qa", response, model, sources}

Incident path:
  1. procedure_retriever (FoundryAgent) → {vwi_candidates[], ro_candidates[]}
  2. dispatch_matcher    (FoundryAgent) → structured proposal
  3. rule_checker        (deterministic, local) → rule verdicts
  4. dispatch_reviewer   (FoundryAgent) → {review_status, findings[]}
     → if "revise": loop back to step 2 (max 2)

Accepts both free-text and structured JSON input (§5 format).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from agent_framework import AgentResponseUpdate, WorkflowBuilder

from config import (
    MAX_REVISIONS,
    MODEL,
    MATCHER_AGENT,
    QA_AGENT,
    RETRIEVER_AGENT,
    REVIEWER_AGENT,
    get_foundry_agent,
)
from rules.evaluate_rules import evaluate_rules

# ---- Intent detection ----

_INCIDENT_KEYWORDS = [
    "storing", "stroom", "spanningsloos", "uitval", "alarm",
    "brandlucht", "vonken", "rook", "schade", "kapot",
    "meldt", "melding", "klant meldt", "scada",
    "monteur", "dispatch", "dekkingsanalyse",
    "aansluitkast", "meterkast", "zekering",
]

_POSTCODE_RE = re.compile(r"\b\d{4}\s*[A-Z]{0,2}\b")
_MS_RE = re.compile(r"\bMS\b")
_HS_RE = re.compile(r"\bHS\b")
_CREW_RE = re.compile(r"crew-\d{3}-[A-Za-z-]+")


def _is_incident(text: str) -> bool:
    text_lower = text.lower()
    if any(kw in text_lower for kw in _INCIDENT_KEYWORDS):
        return True
    if _POSTCODE_RE.search(text):
        return True
    return False


# ---- Anchor extraction ----

def _extract_anchors_from_text(text: str) -> dict[str, Any]:
    postcode = None
    m = re.search(r"\b(\d{4})\s*[A-Z]{0,2}\b", text)
    if m:
        postcode = m.group(1)

    voltage_class = "LS"
    if _MS_RE.search(text):
        voltage_class = "MS"
    elif _HS_RE.search(text):
        voltage_class = "HS"

    asset_class = "unknown"
    for kw, cls in [
        ("aansluitkast", "aansluitkast"), ("meterkast", "meterkast"),
        ("schakelstation", "schakelstation"), ("kabelnet", "kabelnet"),
        ("transformator", "transformator"), ("mof", "kabelnet"),
        ("rek", "schakelstation"),
    ]:
        if kw in text.lower():
            asset_class = cls
            break

    crew = _CREW_RE.findall(text)

    return {
        "postcode": postcode,
        "voltage_class": voltage_class,
        "asset_class": asset_class,
        "timestamp": datetime.now().isoformat(),
        "available_crew": crew if crew else [],
    }


def _parse_structured_input(text: str):
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

    anchors = {
        "postcode": sa.get("postcode"),
        "voltage_class": sa.get("voltage_class", "LS"),
        "asset_class": sa.get("asset_class_hint", sa.get("asset_class", "unknown")),
        "timestamp": data.get("received_at", datetime.now().isoformat()),
        "available_crew": crew,
        "incident_id": data.get("incident_id"),
        "address": sa.get("address"),
    }
    return free_text, anchors, crew


# ---- Agent runner ----

async def _run_foundry_agent(agent_name: str, input_text: str) -> str:
    """Run a Foundry-managed Prompt Agent and return its full text output."""
    agent = get_foundry_agent(agent_name)
    text = ""
    workflow = WorkflowBuilder(start_executor=agent).build()
    async for event in workflow.run(input_text, stream=True):
        if event.type == "output" and isinstance(event.data, AgentResponseUpdate):
            text += event.data.text or ""
    return text


# ---- JSON parsing helpers ----

def _try_parse_json(text: str):
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


# ---- Main entry point ----

async def run_chat(user_message: str) -> dict[str, Any]:
    """Returns a dict with the full response."""

    # --- Try structured JSON input first ---
    structured = _parse_structured_input(user_message)

    if structured:
        free_text, anchors, crew = structured
        incident_id = (
            anchors.get("incident_id")
            or f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
    else:
        if not _is_incident(user_message):
            # Q&A path — use the Foundry QA agent
            text = await _run_foundry_agent(QA_AGENT, user_message)
            return {
                "type": "qa",
                "response": text.strip(),
                "model": MODEL,
                "sources": [],
            }

        free_text = user_message
        anchors = _extract_anchors_from_text(user_message)
        incident_id = f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    crew_label = (
        anchors["available_crew"]
        if anchors["available_crew"]
        else ["(all available crew)"]
    )

    # ---- Incident path ----

    # Step 1: procedure_retriever (Foundry agent)
    retriever_input = (
        f"=== INCIDENT PAYLOAD ===\n"
        f"Incident ID: {incident_id}\n"
        f"Free text: {free_text}\n"
        f"Postcode: {anchors.get('postcode') or 'unknown'}\n"
        f"Voltage class: {anchors.get('voltage_class', 'LS')}\n"
        f"Asset class: {anchors.get('asset_class', 'unknown')}\n"
        f"Timestamp: {anchors.get('timestamp')}\n"
        f"Available crew: {crew_label}\n"
        f"=== END INCIDENT PAYLOAD ==="
    )
    retriever_text = await _run_foundry_agent(RETRIEVER_AGENT, retriever_input)
    retriever_data = _try_parse_json(retriever_text)

    vwi_candidates = []
    if isinstance(retriever_data, dict):
        vwi_candidates = retriever_data.get("vwi_candidates", [])

    # Revise loop
    revision = 0
    reviewer_feedback = None
    matcher_proposal = None
    rule_findings = None
    reviewer_verdict = None

    while revision <= MAX_REVISIONS:
        # Step 2: dispatch_matcher (Foundry agent — has idx_raamopdrachten attached)
        matcher_input_parts = [
            "=== INCIDENT PAYLOAD ===",
            f"Incident ID: {incident_id}",
            f"Free text: {free_text}",
            f"Postcode: {anchors.get('postcode') or 'unknown'}",
            f"Voltage class: {anchors.get('voltage_class', 'LS')}",
            f"Asset class: {anchors.get('asset_class', 'unknown')}",
            f"Timestamp: {anchors.get('timestamp')}",
            f"Available crew: {crew_label}",
            "=== END INCIDENT PAYLOAD ===",
            "",
            "=== VWI CANDIDATES ===",
            json.dumps(vwi_candidates, ensure_ascii=False),
            "=== END VWI CANDIDATES ===",
        ]
        if reviewer_feedback:
            matcher_input_parts.extend([
                "",
                f"=== REVIEWER FEEDBACK (revision {revision}) ===",
                reviewer_feedback,
                "=== END REVIEWER FEEDBACK ===",
            ])

        matcher_text = await _run_foundry_agent(
            MATCHER_AGENT, "\n".join(matcher_input_parts)
        )
        matcher_proposal = _try_parse_json(matcher_text) or {"raw": matcher_text}

        # Step 3: rule_checker (DETERMINISTIC — no LLM, no Foundry)
        vwis_from_proposal = (
            matcher_proposal.get("vwis", [])
            if isinstance(matcher_proposal, dict) else []
        )
        vwi_ids = [v.get("vwi_id", "") for v in vwis_from_proposal]
        requires_live = any("onder-sp" in v for v in vwi_ids)

        rule_input = (
            dict(matcher_proposal)
            if isinstance(matcher_proposal, dict) else {}
        )
        rule_input["postcode"] = anchors.get("postcode", "")
        rule_input["incident_timestamp"] = anchors.get("timestamp", "")
        rule_input["requires_live_work"] = requires_live

        rule_findings = json.loads(evaluate_rules(rule_input))

        # Step 4: dispatch_reviewer (Foundry agent)
        reviewer_input = (
            "=== INCIDENT PAYLOAD (ORIGINAL) ===\n"
            f"Incident ID: {incident_id}\n"
            f"Free text: {free_text}\n"
            f"Postcode: {anchors.get('postcode') or 'unknown'}\n"
            f"Voltage class: {anchors.get('voltage_class', 'LS')}\n"
            f"Asset class: {anchors.get('asset_class', 'unknown')}\n"
            "=== END INCIDENT PAYLOAD ===\n\n"
            "=== MATCHER PROPOSAL ===\n"
            f"{json.dumps(matcher_proposal, ensure_ascii=False)}\n"
            "=== END MATCHER PROPOSAL ===\n\n"
            "=== RULE FINDINGS ===\n"
            f"{json.dumps(rule_findings, ensure_ascii=False)}\n"
            "=== END RULE FINDINGS ===\n\n"
            f"Revision iteration: {revision} of {MAX_REVISIONS} max."
        )
        reviewer_text = await _run_foundry_agent(REVIEWER_AGENT, reviewer_input)
        reviewer_verdict = _try_parse_json(reviewer_text) or {
            "review_status": "flagged_for_human_review",
            "findings": [],
            "feedback_for_matcher": None,
        }

        review_status = reviewer_verdict.get("review_status", "pass")

        if review_status == "revise" and revision < MAX_REVISIONS:
            revision += 1
            reviewer_feedback = reviewer_verdict.get(
                "feedback_for_matcher", ""
            )
            continue

        if review_status == "revise":
            reviewer_verdict["review_status"] = "flagged_for_human_review"
        break

    # Assemble final response
    final = (
        dict(matcher_proposal)
        if isinstance(matcher_proposal, dict) else {}
    )
    final["incident_id"] = incident_id
    final["review_status"] = (
        reviewer_verdict.get("review_status", "pass")
        if reviewer_verdict else "pass"
    )
    final["review_findings"] = (
        reviewer_verdict.get("findings", [])
        if reviewer_verdict else []
    )
    final["rule_verdicts"] = rule_findings or []
    final["revision_count"] = revision

    any_hard_fail = any(
        not r.get("pass", True) for r in (rule_findings or [])
    )
    if final["review_status"] == "flagged_for_human_review" or any_hard_fail:
        final["operational_action"] = "wv_escalation_needed"

    vwi_ids_out = [v.get("vwi_id", "") for v in final.get("vwis", [])]

    return {
        "type": "dispatch",
        "response": final,
        "model": MODEL,
        "sources": vwi_ids_out,
    }
