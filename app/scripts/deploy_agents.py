"""
deploy_agents.py
Registers the DRAAD agents as Prompt Agents in Foundry Agent Service
with Azure AI Search tools attached.

Agent definitions (prompts, names, indexes) are imported from
backend/agents/ — single source of truth for both deployment and runtime.

Requires:
  pip install azure-ai-projects>=2.0.0 azure-identity python-dotenv

Usage:
  python scripts/deploy_agents.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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

# Add backend to sys.path so we can import agent definitions
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from backend.agents import get_all_agent_configs

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL = os.getenv("FOUNDRY_MODEL", "gpt-4o")
SEARCH_CONNECTION_NAME = os.environ["AZURE_SEARCH_CONNECTION_NAME"]


def _search_tools(connection_id: str, index_names: list[str]) -> list:
    """Create one AzureAISearchTool per index.

    Foundry constraints: each agent can have only ONE AzureAISearchTool, and
    that tool can hold at most ONE index. So an agent gets at most 1 index.
    If callers pass multiple indexes, only the first is used.
    """
    if not index_names:
        return []
    return [
        AzureAISearchTool(
            azure_ai_search=AzureAISearchToolResource(
                indexes=[
                    AISearchIndexResource(
                        project_connection_id=connection_id,
                        index_name=index_names[0],
                        query_type=AzureAISearchQueryType.SEMANTIC,
                    )
                ]
            )
        )
    ]


def main() -> None:
    project = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )

    # Resolve AI Search connection ID.
    # Failure mode #19: under azure-ai-projects 2.x (api-version "v1"), the
    # singular connections.get(name) returns 404 ("Project not found") on a
    # freshly created project even though the connection exists — but
    # connections.list() works. So resolve the connection by listing and
    # matching on name instead of calling get().
    conn_id = None
    for c in project.connections.list():
        if c.name == SEARCH_CONNECTION_NAME:
            conn_id = c.id
            break
    if conn_id is None:
        raise RuntimeError(
            f"AI Search connection '{SEARCH_CONNECTION_NAME}' not found in project"
        )
    print(f"AI Search connection: {SEARCH_CONNECTION_NAME} → {conn_id}")

    for agent_def in get_all_agent_configs():
        tools = (
            _search_tools(conn_id, agent_def["indexes"])
            if agent_def["indexes"]
            else []
        )

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

    print("\nAll agents deployed.")


if __name__ == "__main__":
    main()
