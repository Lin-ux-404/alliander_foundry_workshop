# Grid Operations Agent Learning Path

This directory contains a coherent, level 100–200 learning path for building a
grounded internal operations assistant for electricity-grid teams. The scenario
is synthetic and advisory: none of the labs operate equipment, dispatch a real
crew, or write to a production operational system.

## Learning path

| Lab | Path | Time | Participant artifact |
|---|---|---:|---|
| 1. Grid Operations Agent with Function Tools | Required | 45 min | Tool-grounded incident response and tool-call check |
| 2. Stream a Field-Operations Brief | Required | 30 min | Streamed shift-handover brief |
| 3. Sequential Incident Triage and Crew Planning | Required | 45 min | Fact-first triage followed by an approval-aware plan |
| 4. Deterministic Grid-Safety Executor | Required | 45 min | Advisory plan with an auditable safety-gate result |
| 5. Grounding with Azure AI Search | Required | 45 min | Search-grounded answer and citation inspection |
| 6. Multi-Source Retrieval with Foundry IQ | Optional; preview-dependent | 60 min | Cited multi-source answer and safe agent cleanup |
| 7. Bounded Reflection | Optional | 60 min | Quality-reviewed brief with bounded retries |

Labs 1–5 form the minimum path. Labs 6–7 are extensions for environments and
groups that are ready for preview retrieval capabilities and cyclic workflows.

## Prerequisites

Use Python 3.12 and install the repository `requirements.txt`. Authenticate to
the intended tenant before opening the notebooks:

```bash
az login
az account show
```

The workshop environment supplies a root `.env` file. At minimum it must define:

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL=<deployed-model-name>
WORKSHOP_RESOURCE_NAMESPACE=<unique-team-or-participant-slug>
```

Search labs additionally use:

```dotenv
AZURE_SEARCH_ENDPOINT=https://<service>.search.windows.net
AZURE_SEARCH_CONNECTION_NAME=<foundry-project-search-connection>
LAB_SEARCH_INDEX=<prepared-procedure-index>
```

The Foundry IQ extension uses:

```dotenv
FOUNDRY_IQ_KNOWLEDGE_BASE=<prepared-knowledge-base>
FOUNDRY_IQ_MCP_CONNECTION_NAME=<project-managed-identity-remote-tool-connection>
FOUNDRY_IQ_API_VERSION=2026-05-01-preview
```

The operator prepares the namespaced three-source knowledge base with:

```bash
python app/scripts/setup_search.py --foundry-iq
```

`WORKSHOP_RESOURCE_NAMESPACE` is preferred. For compatibility, the notebooks
fall back to `WORKSHOP_TEAM_ID` and then `WORKSHOP_PARTICIPANT_ID`. A namespace
is mandatory: it isolates agent and executor names and prevents accidental
cross-team cleanup.

## Resource and cleanup policy

- Labs 1–5 create only in-process agents and read prepared resources.
- Lab 5 never creates or deletes a Search index.
- Lab 6 creates a namespaced prompt-agent version. Its cleanup cell refuses to
  delete an agent that does not carry the current namespace.
- Lab 6 never deletes the shared MCP connection, knowledge base, knowledge
  sources, or indexes.
- Do not put real incident data, personal data, credentials, or production
  switching instructions into these notebooks.

## Definition of done

A team completes the required path when it can demonstrate:

1. an incident question resolved through deterministic function tools;
2. a streamed operator-facing response;
3. an explicit triage-to-planning workflow;
4. a deterministic safety check; and
5. a Search-grounded answer with inspectable citations or a documented citation
   field/configuration issue.

Each notebook ends with a deterministic check. Model wording remains
nondeterministic; checks therefore validate tool calls, workflow artifacts,
namespacing, outputs, and cleanup ownership rather than exact prose.

## Current Microsoft references

The labs follow the current official API and design guidance:

- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Function tools](https://learn.microsoft.com/en-us/agent-framework/agents/tools/function-tools)
- [Agent streaming API](https://learn.microsoft.com/en-us/python/api/agent-framework-core/agent_framework.agentprotocol)
- [Agent Framework workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/)
- [Workflow orchestrations](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/)
- [Workflow builder and execution](https://learn.microsoft.com/en-us/agent-framework/workflows/workflows)
- [Connect Azure AI Search to Foundry agents](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search)
- [What is Foundry IQ?](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq)
- [Connect agents to Foundry IQ knowledge bases](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect)
- [Foundry IQ FAQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/foundry-iq-faq)

The repository uses the consolidated import namespaces
`agent_framework.foundry` and `agent_framework.orchestrations`. Foundry IQ code
uses `azure-ai-projects` 2.x and the current prompt-agent version API.

## Preview and service fallbacks

Some Foundry IQ capabilities are generally available through the
`2026-04-01` Search REST API, while the full connection example used in Lab 6
requires `2026-05-01-preview`. Preview functionality has no production SLA and
can differ by region.

If Lab 6 is unavailable:

1. finish Lab 5 using the direct Azure AI Search tool;
2. compare single-index retrieval with a facilitator-provided multi-source
   response; and
3. discuss where query decomposition, source selection, citations, permissions,
   latency, and cost would be owned.

Do not represent the fallback as Foundry IQ. It is a direct Search baseline.

For transient model quota or throttling failures, retry only after the
facilitator confirms capacity. For `401`/`403`, verify tenant selection, Foundry
roles, the project managed identity, and Search data-plane roles. For an empty
or uncited answer, verify the index contains retrievable content, title, and
source URL fields and that the Foundry project connection targets the correct
Search service.
