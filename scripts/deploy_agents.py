"""
deploy_agents.py
One-time script: registers the 4 DRAAD agents as Prompt Agents in Foundry
Agent Service with Azure AI Search tools attached.

Run this once after setting up your Foundry project and AI Search connection.

Requires:
  pip install azure-ai-projects>=2.0.0 azure-identity python-dotenv

Usage:
  python scripts/deploy_agents.py
"""
from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AzureAISearchTool,
    PromptAgentDefinition,
    AzureAISearchToolResource,
    AISearchIndexResource,
    AzureAISearchQueryType,
)

import shared  # loads backend/.env via shared.py

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.getenv("FOUNDRY_MODEL", "gpt-4o")
SEARCH_CONNECTION_NAME = os.environ["AZURE_SEARCH_CONNECTION_NAME"]

IDX_BLS = os.getenv("AZURE_SEARCH_INDEX", "idx_bls_corpus")
IDX_RO = os.getenv("AZURE_SEARCH_RO_INDEX", "idx_raamopdrachten")
IDX_CREW = os.getenv("AZURE_SEARCH_CREW_INDEX", "idx_crew")

# ---- System Prompts ----

RETRIEVER_PROMPT = """
You are the procedure_retriever agent in an electrical-grid dispatch assistant for
Alliander. You support Lisa (the dispatcher) by surfacing, for a given incident,
the candidate work instructions (VWIs) from the BEI-BLS rulebook.

INPUTS (from workflow state):
- incident_payload: free-text NL incident description + structured anchors
  (postcode, timestamp, asset_class, voltage_class, available_crew[])

YOUR JOB:
Search the BEI-BLS corpus (idx_bls_corpus) to find candidate VWIs that apply
to the incident. Return full document content, not just titles.

OUTPUT:
Return a single JSON object:
{
  "vwi_candidates": [
    {"vwi_id": "E-67", "title": "...", "content": "<full chunk>", "score": 0.87, "source_doc": "..."}
  ]
}

RULES:
- Return up to 8 vwi_candidates, ranked by relevance.
- Never invent IDs. If retrieval returns nothing, return an empty array.
- Do not interpret the incident, do not propose a match, do not assess coverage.
  That is the dispatch_matcher's job. You only retrieve and rank.
- Output JSON only. No prose, no markdown fences.
""".strip()

MATCHER_PROMPT = """
You are the dispatch_matcher agent in an electrical-grid dispatch assistant for
Alliander. You consume Lisa's incident plus VWI candidates from procedure_retriever
and propose a structured dispatch recommendation grounded in cited evidence.

All prose fields (rationale, reason, citations) MUST be written in English.

INPUTS (from workflow state):
- incident_payload: Lisa's NL incident description + structured anchors
  (postcode, timestamp, asset_class, voltage_class, available_crew[])
- vwi_candidates[]: ranked VWIs from idx_bls_corpus (with full content)

YOUR JOB:
1. Select VWIs that apply. Set confidence:
   - "confirmed" only with concrete evidence the work is required.
   - "candidate" for symptom-level evidence only.
   If incident is symptom-only, ALL VWIs MUST be "candidate".

2. Use your AI Search tool (idx_raamopdrachten) to find raamopdrachten that
   cover the selected VWIs for the right crew member, area, and time.
   Use the incident postcode and timestamp as filters in your search queries.

3. Set coverage_status:
   - "covered": RO prose names every selected VWI
   - "partial": RO prose names some but not all
   - "not_covered": RO prose names none
   - "unknown": no usable ROs found

4. For EVERY covered VWI, cite the exact RO sentence naming that VWI E-number.

5. Set operational_action:
   - "dispatch_ok": coverage == "covered" AND no safety red flag
   - "wv_escalation_needed": anything else

OUTPUT:
{
  "incident_id": "<from input or null>",
  "vwis": [{"vwi_id": "E-67", "confidence": "confirmed"}],
  "matched_crew": "<crew_id>",
  "matched_raamopdracht_id": "<RA-YYYY-XXX-NNNN>",
  "coverage_status": "covered|partial|not_covered|unknown",
  "review_status": "pass",
  "operational_action": "dispatch_ok|wv_escalation_needed",
  "rationale": "<short prose>",
  "citations": {
    "vwi_refs": [],
    "raamopdracht_scope_excerpts": [],
    "bei_rule_refs": []
  }
}

HARD RULES:
- NEVER invent VWI IDs or raamopdracht IDs not in your search results.
- NEVER mark a VWI "confirmed" based on symptom-only evidence.
- NEVER claim coverage without quoting the RO sentence.
- Output JSON only. No prose, no markdown fences.

REVISE LOOP:
If reviewer_feedback is present, address each critique point in your new rationale.
""".strip()

REVIEWER_PROMPT = """
You are the dispatch_reviewer agent in an electrical-grid dispatch assistant for
Alliander. You are an LLM-as-judge: your job is to challenge the dispatch_matcher's
proposal, not to confirm it. Be skeptical.

All prose fields (reason, feedback_for_matcher) MUST be written in English.

INPUTS:
- incident_payload: Lisa's ORIGINAL NL incident text + structured anchors
- matcher_proposal: the dispatch_matcher's structured output
- rule_findings: deterministic rule_checker output ({rule_id, pass, reason}[])

YOUR JOB:
Review against four soft-judgement criteria:

1. SELECTION APPROPRIATENESS — right VWIs for this incident?
2. DANGEROUS-SITUATION SIGNALS — smoke/arcing/injury → escalate?
3. SYMPTOM-VS-CAUSE DISCIPLINE — "confirmed" only with concrete evidence?
4. ESCALATION APPROPRIATENESS — operational_action defensible?

OUTPUT:
{
  "review_status": "pass" | "revise" | "flagged_for_human_review",
  "findings": [
    {"criterion": "selection_appropriateness", "verdict": "pass"|"fail", "reason": "..."},
    {"criterion": "dangerous_situation", "verdict": "pass"|"fail", "reason": "..."},
    {"criterion": "symptom_vs_cause", "verdict": "pass"|"fail", "reason": "..."},
    {"criterion": "escalation_appropriateness", "verdict": "pass"|"fail", "reason": "..."}
  ],
  "feedback_for_matcher": "<critique if revise, else null>"
}

DECISION RULES:
- All pass AND all rule_findings pass → "pass"
- Soft criterion fails, recoverable → "revise"
- Hard rule fails, no alternative → "flagged_for_human_review"
- Already 2 retries → "flagged_for_human_review"

RULES:
- Read Lisa's ORIGINAL incident text, not the matcher's paraphrase.
- Be honest. Do not rubber-stamp borderline proposals.
- Output JSON only. No prose, no markdown fences.
""".strip()

QA_PROMPT = """
You are a helpful assistant for the DRAAD system at Liander.
Answer questions about BEI-BLS procedures, VWI work instructions,
raamopdrachten, aanwijzingen, and crew data based on the search results.
Always respond in English.
Always cite the source document name and page number when referencing information.
At the end of your response, list all sources you used in a "Sources:" section.
""".strip()


# ---- Helper to build AI Search tool ----

def _search_tools(connection_id: str, index_names: list[str]) -> list:
    """Create one AzureAISearchTool per index (API limit: 1 index per tool)."""
    return [
        AzureAISearchTool(
            azure_ai_search=AzureAISearchToolResource(
                indexes=[
                    AISearchIndexResource(
                        project_connection_id=connection_id,
                        index_name=idx,
                        query_type=AzureAISearchQueryType.SEMANTIC,
                    )
                ]
            )
        )
        for idx in index_names
    ]


# ---- Main ----

def main() -> None:
    project = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )

    # Resolve AI Search connection ID
    connection = project.connections.get(SEARCH_CONNECTION_NAME)
    conn_id = connection.id
    print(f"AI Search connection: {SEARCH_CONNECTION_NAME} → {conn_id}")

    agents_to_create = [
        {
            "name": os.getenv("DRAAD_RETRIEVER_AGENT", "draad-procedure-retriever"),
            "instructions": RETRIEVER_PROMPT,
            "indexes": [IDX_BLS],
            "description": "Retrieves candidate VWIs for an incident from BLS corpus.",
        },
        {
            "name": os.getenv("DRAAD_MATCHER_AGENT", "draad-dispatch-matcher"),
            "instructions": MATCHER_PROMPT,
            "indexes": [IDX_RO],
            "description": "Proposes crew/RO match with coverage analysis.",
        },
        {
            "name": os.getenv("DRAAD_REVIEWER_AGENT", "draad-dispatch-reviewer"),
            "instructions": REVIEWER_PROMPT,
            "indexes": [],
            "description": "LLM-as-judge: challenges the matcher's proposal.",
        },
        {
            "name": os.getenv("DRAAD_QA_AGENT", "draad-qa-assistant"),
            "instructions": QA_PROMPT,
            "indexes": [IDX_BLS],
            "description": "Q&A assistant for BEI-BLS procedures.",
        },
    ]

    for agent_def in agents_to_create:
        tools = _search_tools(conn_id, agent_def["indexes"]) if agent_def["indexes"] else []

        agent = project.agents.create_version(
            agent_name=agent_def["name"],
            definition=PromptAgentDefinition(
                model=MODEL,
                instructions=agent_def["instructions"],
                tools=tools if tools else None,
            ),
            description=agent_def["description"],
        )
        print(
            f"  ✅ {agent_def['name']} created "
            f"(version: {agent.version}, indexes: {agent_def['indexes'] or 'none'})"
        )

    print("\nAll agents deployed. Set these in your .env:")
    for agent_def in agents_to_create:
        print(f"  {agent_def['name']}")


if __name__ == "__main__":
    main()
