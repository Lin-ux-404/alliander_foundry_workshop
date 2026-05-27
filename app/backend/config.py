"""
Singleton clients and environment configuration for DRAAD.
"""
import os
from functools import lru_cache

from agent_framework.foundry import FoundryAgent, FoundryChatClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()


@lru_cache(maxsize=1)
def get_foundry_client() -> FoundryChatClient:
    return FoundryChatClient(
        project_endpoint=_require("FOUNDRY_PROJECT_ENDPOINT"),
        model=_require("FOUNDRY_MODEL"),
        credential=get_credential(),
    )


def get_foundry_agent(agent_name: str) -> FoundryAgent:
    """Create a FoundryAgent that connects to a Prompt Agent in Foundry."""
    return FoundryAgent(
        project_endpoint=_require("FOUNDRY_PROJECT_ENDPOINT"),
        agent_name=agent_name,
        credential=get_credential(),
    )


# Agent names (from .env or defaults)
RETRIEVER_AGENT = os.getenv("DRAAD_RETRIEVER_AGENT", "draad-procedure-retriever")
MATCHER_AGENT = os.getenv("DRAAD_MATCHER_AGENT", "draad-dispatch-matcher")
REVIEWER_AGENT = os.getenv("DRAAD_REVIEWER_AGENT", "draad-dispatch-reviewer")
QA_AGENT = os.getenv("DRAAD_QA_AGENT", "draad-qa-assistant")

MODEL = os.getenv("FOUNDRY_MODEL", "gpt-4o")
SEARCH_TOP_K: int = int(os.getenv("SEARCH_TOP_K", "6"))
MAX_REVISIONS: int = int(os.getenv("MAX_REVISIONS", "2"))
