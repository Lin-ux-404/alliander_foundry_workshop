# Technical research baseline

**Verified:** 29 July 2026
**Policy:** recheck every link, region, model deployment, quota, package version,
and preview flag during the final environment validation.

This file records the product boundaries used by the workshop. It is deliberately
short: the linked Microsoft documentation remains the source of truth.

## Platform choices

| Area | Workshop choice | Product boundary |
|---|---|---|
| Agent development | Microsoft Agent Framework with a Foundry project | Agent Framework separates individual agents from graph-based workflows. Use an agent for model reasoning and tool selection; use a workflow for explicit routing, state and deterministic gates. |
| Knowledge | Direct Azure AI Search first, Foundry IQ second | Foundry IQ is the knowledge/retrieval layer. It is not an evaluation or prompt-comparison feature. |
| Evaluation | Foundry evaluation with a small versioned dataset | Compare aggregate and row-level results across runs. Keep deterministic task/tool assertions beside model-based quality evaluators. |
| Observability | OpenTelemetry traces exported to Application Insights | Traces can contain customer data. Use synthetic workshop data, avoid secrets and apply the documented retention/access controls. |
| Identity | Microsoft Entra ID and Foundry-specific RBAC | Developers receive **Foundry User** at project scope and Reader at the parent resource where required. Do not use Cognitive Services roles for Foundry projects. |
| Isolation | One isolated environment per team by default | Shared Search is allowed only when every mutable resource is namespaced and cleanup is constrained to that namespace. |
| Hosted agents and Toolboxes | Stretch material only | Both surfaces can depend on preview capabilities and additional `azd`/hosting prerequisites. They are not required for the core completion outcome. |

## Foundry IQ boundaries

- A knowledge base groups one or more knowledge sources and uses Azure AI Search
  agentic retrieval.
- Retrieval reasoning effort controls query planning depth, latency and cost.
- Indexed sources can automate chunking, vectorization and metadata extraction.
- Permission enforcement is not automatic for every source. It depends on the
  source supporting ACL synchronization and on correct configuration.
- Microsoft documents a mix of generally available and preview surfaces. Portal
  behavior can still rely on preview APIs.
- The stable fallback in this repository is the direct Azure AI Search lab.

## Evaluation boundaries

The required evaluation path uses:

1. Deterministic output-schema and tool-call assertions.
2. Evidence-group recall over actual Search or Foundry IQ references when
   ground-truth document relevance is available.
3. Claim-level citation coverage and reference validity.
4. Groundedness and relevance for generated answers using the exact retrieved
   context.
5. Trace or API activity inspection for latency, errors and tool behavior.
6. Observable token and request counts, with cost estimates only when the
   applicable subscription rates are explicitly configured.

Groundedness measures whether the response stays within its context; response
completeness measures whether expected information was omitted. They are not
interchangeable. Preview-only evaluators are optional and must have a fallback.

For multi-source agentic retrieval, record source-specific query activity,
reranker warnings and returned references beside aggregate recall. A global
document cap and one shared reranker threshold can hide a required small-table
result behind many long-document chunks. Repeat representative cases before
setting a release threshold.

## Version policy

`requirements.txt` pins the directly used Python packages to the versions
validated for this repository. Upgrade them only in a dedicated change that:

1. recreates a clean Python 3.12 environment;
2. validates all notebook imports;
3. compiles the application;
4. exercises one live agent, Search, Foundry IQ, trace and evaluation path; and
5. updates this baseline.

Python 3.12 is the reference runtime. The application may work on newer versions,
but those versions are outside the workshop validation target.

## Official sources

- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Agent Framework workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/workflows)
- [Agent Framework orchestration patterns](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/)
- [Foundry IQ overview](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/what-is-foundry-iq?preserve-view=true&view=foundry)
- [Foundry IQ FAQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/foundry-iq-faq)
- [Azure AI Search agentic retrieval](https://learn.microsoft.com/en-us/azure/search/search-agentic-retrieval-concept)
- [Foundry RBAC](https://learn.microsoft.com/en-us/azure/foundry/concepts/rbac-foundry)
- [Foundry region and feature availability](https://learn.microsoft.com/en-us/azure/foundry/reference/region-support)
- [Foundry trace data handling](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-data)
- [View and compare evaluation results](https://learn.microsoft.com/en-us/azure/foundry/how-to/evaluate-results)
- [RAG evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators)
- [Retrieve from a knowledge base](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve)
- [Foundry IQ FAQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/foundry-iq-faq)
- [Azure AI Search pricing](https://azure.microsoft.com/en-us/pricing/details/search/)
- [Prompt Optimizer](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/prompt-optimizer)
- [Prompt Shields](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/quickstart-jailbreak)
- [Foundry hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Foundry Toolboxes](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox)
