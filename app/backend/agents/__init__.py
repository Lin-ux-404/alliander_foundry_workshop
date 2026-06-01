"""Agent definitions: names, prompts, and tool configs for all DRAAD agents."""
from __future__ import annotations

from agents.retriever import RETRIEVER_NAME, RETRIEVER_PROMPT, RETRIEVER_INDEXES
from agents.matcher import MATCHER_NAME, MATCHER_PROMPT, MATCHER_INDEXES
from agents.reviewer import REVIEWER_NAME, REVIEWER_PROMPT
from agents.qa import QA_NAME, QA_PROMPT, QA_INDEXES


def get_all_agent_configs() -> list[dict]:
    """Return deployment configs for all DRAAD agents.

    Each dict has: name, instructions, indexes, description.
    Used by deploy_agents.py to register agents in Foundry.
    """
    return [
        {
            "name": RETRIEVER_NAME,
            "instructions": RETRIEVER_PROMPT,
            "indexes": RETRIEVER_INDEXES,
            "description": "Retrieves candidate VWIs for an incident from BLS corpus.",
        },
        {
            "name": MATCHER_NAME,
            "instructions": MATCHER_PROMPT,
            "indexes": MATCHER_INDEXES,
            "description": "Proposes crew/RO match with coverage analysis.",
        },
        {
            "name": REVIEWER_NAME,
            "instructions": REVIEWER_PROMPT,
            "indexes": [],
            "description": "LLM-as-judge: challenges the matcher's proposal.",
        },
        {
            "name": QA_NAME,
            "instructions": QA_PROMPT,
            "indexes": QA_INDEXES,
            "description": "Q&A assistant for BEI-BLS procedures.",
        },
    ]
