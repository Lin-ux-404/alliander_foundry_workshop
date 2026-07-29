"""
Singleton clients and environment configuration for DRAAD.
"""
import os
from functools import lru_cache

from agent_framework.foundry import FoundryAgent, FoundryChatClient
from agent_framework.observability import enable_instrumentation
from azure.identity import DefaultAzureCredential

from utils.environment import load_workshop_environment

load_workshop_environment()

# Agent Framework emits metadata-only traces by default. Force prompt, response,
# and tool payload capture off even if a developer has ENABLE_SENSITIVE_DATA set
# in their shell.
enable_instrumentation(enable_sensitive_data=False)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
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


MODEL = os.getenv("FOUNDRY_MODEL", "gpt-4o")
SEARCH_TOP_K = _env_int("SEARCH_TOP_K", 6, minimum=1, maximum=50)
MAX_REVISIONS = _env_int("MAX_REVISIONS", 2, minimum=0, maximum=5)
