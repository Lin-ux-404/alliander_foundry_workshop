# Day 2 — Observability, Evaluation, and Safety

These labs turn the internal-operations assistant into a system that can be
inspected, measured, regression-tested, and challenged before release.

The progression intentionally separates two concerns:

- **Foundry IQ / Azure AI Search** retrieve enterprise knowledge.
- **Foundry evaluation** measures the quality of retrieved context, generated
  answers, agent behavior, and tool use.

Evaluation does not create or replace a knowledge base.

## Learning path

| Lab | Status | Time | Outcome |
|---|---|---:|---|
| [1 — Telemetry and tracing](./1-telemetry.ipynb) | Required | 45 min | One correlated agent trace with privacy-safe custom attributes |
| [2 — Grounded-answer evaluation](./2-agent-evaluation.ipynb) | Required | 50 min | A small quality baseline covering retrieval, groundedness, and relevance |
| [3 — Agent evaluation with function tools](./3-agent-evaluation-with-function-tools.ipynb) | Required | 50 min | System- and process-level evaluation of an incident-assistance trajectory |
| [4 — Tool-call regression testing](./4-tool-call-accuracy-evaluation.ipynb) | Required challenge | 45 min | Deterministic checks plus Foundry Tool Call Accuracy evaluation |
| [5 — Red-team and security testing](./5-red-team-security-testing.ipynb) | Optional preview | 60–90 min | A reviewed risk policy and, where supported, a cloud red-team run |
| [6 — End-to-end Azure AI Search RAG evaluation](./6-end-to-end-search-rag-evaluation.ipynb) | Required production-minded extension | 45–60 min | Live Search retrieval, answer generation, groundedness and operational metrics |
| [7 — End-to-end Foundry IQ RAG evaluation](./7-end-to-end-foundry-iq-rag-evaluation.ipynb) | Optional production-minded extension | 45–60 min | Live multi-source IQ retrieval, answer synthesis and the same release contract |

Each required notebook contains a working baseline, a participant `TODO`, a
deterministic success check, and an optional extension.

## Expected artifacts

By the end of the required path, each team should have:

1. A trace ID and a screenshot or URL for a trace in Foundry/Application
   Insights.
2. A completed cloud evaluation with a small, version-controlled-style test
   set.
3. A comparison of response-quality metrics and agent/process metrics.
4. A tool-call regression gate with at least one negative test.
5. A short release recommendation: ship, mitigate, or collect more evidence.
6. A row-level live RAG report containing retrieval recall, citation coverage,
   citation validity, groundedness, latency and observable cost usage.

The optional lab adds a red-team risk register and Attack Success Rate review.

## Prerequisites

- Python 3.12 (the repository-supported workshop runtime).
- Repository dependencies installed in the active virtual environment.
- `azure-ai-projects==2.3.0` for the cloud-evaluation examples.
- Azure CLI authentication (`az login`) or another credential supported by
  `DefaultAzureCredential`.
- The **Foundry User** role on the project.
- **Monitoring Reader** on the connected Application Insights resource and
  **Log Analytics Reader** on its workspace.
- A deployed chat-capable model.

Client-side GenAI tracing is a preview capability. Cloud red teaming also has
regional and target restrictions; see [Preview fallbacks](#preview-fallbacks).

## Environment contract

The deployment-generated repository-root `.env` should provide:

```dotenv
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL=<chat-model-deployment>
WORKSHOP_RESOURCE_NAMESPACE=team-07
WORKSHOP_TEAM_ID=team-07
WORKSHOP_PARTICIPANT_ID=participant-23
AZURE_SEARCH_ENDPOINT=https://<search-service>.search.windows.net
AZURE_SEARCH_INDEX=<procedure-index>
FOUNDRY_IQ_KNOWLEDGE_BASE=<knowledge-base>
```

The notebooks also accept the current Microsoft Learn aliases
`AZURE_AI_PROJECT_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME`.

`WORKSHOP_RESOURCE_NAMESPACE` is the authoritative suffix for every agent,
evaluation, run, and taxonomy created by these labs. If it is absent, the
notebooks derive a fallback from `WORKSHOP_TEAM_ID` and then
`WORKSHOP_PARTICIPANT_ID`. Facilitators should assign the namespace explicitly
for concurrent delivery.

Cleanup is disabled by default. To allow a notebook to remove only resources
whose names match its own namespace:

```dotenv
WORKSHOP_ALLOW_CLEANUP=true
```

Never share a namespace between teams.

The end-to-end labs always record model tokens, agentic-retrieval tokens and
Search request counts. Exact USD rates depend on the Azure agreement and
billing plan, so they are never hard-coded. To enable an estimate, set the four
`RAG_*_USD_*` variables documented in `.env.example` from the applicable price
sheet.

## Before participants arrive

Run this preflight with a non-administrator participant identity:

```bash
az login
python -c "import azure.ai.projects, azure.monitor.opentelemetry, openai; print('SDK imports OK')"
```

Then verify:

- The Foundry project endpoint includes `/api/projects/<project-name>`.
- The model deployment is available and has evaluation capacity.
- Application Insights is connected to the project.
- The participant can view traces after the normal 2–5 minute ingestion delay.
- Team namespaces are unique.
- The project region supports any selected evaluation preview.

## Lab design

### 1. Telemetry and tracing

The first lab enables the Azure AI Projects OpenTelemetry instrumentation,
exports spans to Application Insights, creates a namespaced prompt agent, and
records a custom incident-assistance span.

Message-content recording remains **off by default**. Prompts, tool arguments,
and model output may contain sensitive operational data. A participant can
enable capture only in an approved development environment.

Success means:

- the response completed;
- a non-zero trace ID was recorded;
- the custom span contains a team namespace, synthetic incident ID, scenario,
  and outcome—but no secrets or personal data;
- the trace becomes visible in Foundry/Application Insights.

### 2. Grounded-answer evaluation

The second lab evaluates a tiny deterministic dataset of queries, retrieved
context, and pre-computed responses. It uses:

- **Retrieval** for context relevance;
- **Groundedness** for faithfulness to supplied context;
- **Relevance** for whether the answer addresses the question.

The intentionally weak row makes metric differences visible. Participants fix
that row, rerun the evaluation, and compare run reports.

Foundry IQ may have supplied the context in a real application, but this lab
starts after retrieval so the evaluation remains deterministic.

### 3. Agent evaluation with function tools

The third lab evaluates complete OpenAI-style message trajectories containing
system instructions, tool calls, tool results, and final answers. It separates:

- system outcome: task adherence/completion;
- process quality: tool selection/input/output utilization;
- deterministic policy rules that must always pass locally.

The tools are synthetic functions. No production operational system is called.

### 4. Tool-call regression testing

The fourth lab treats tool use as a release gate. It first runs exact local
assertions over expected tool names and arguments, then sends the same cases to
the Foundry Tool Call Accuracy evaluator for semantic review.

The deterministic suite includes a no-tool-expected case. The current cloud
tool evaluators require at least one tool call per row, so that invariant stays
in the local gate and only rows containing tool calls are submitted for
semantic scoring.

The lab uses function-tool traces because current Foundry agent evaluator
support is strongest for function tools, file search, MCP, and knowledge-based
MCP. Tool evaluators currently have limited support for trajectories that
contain Azure AI Search and several other built-in tools.

### 5. Red-team and security testing

The optional lab begins with a deterministic policy-abuse suite and risk
register. The cloud section is gated by `RUN_CLOUD_RED_TEAM=true`; it creates a
namespaced test agent and taxonomy in a non-production project.

Review the generated prohibited-actions taxonomy before using its results.
Automated Attack Success Rate is evidence, not a compliance decision.

### 6. End-to-end Azure AI Search RAG evaluation

The sixth lab runs the complete direct-Search RAG path against a versioned
benchmark:

1. semantic retrieval from the live procedure index;
2. answer generation through the project-scoped Responses API;
3. deterministic recall and citation checks;
4. cloud groundedness evaluation over the exact retrieved pages; and
5. stage latency, token usage, request counts and optional cost estimation.

Expected evidence is represented as groups of stable document identifiers. This
keeps recall deterministic while allowing a group to list equivalent valid
identifiers where necessary.

### 7. End-to-end Foundry IQ RAG evaluation

The seventh lab calls the live knowledge-base `retrieve` API in extractive
output mode. IQ performs query planning and Search retrieval; a separate
project-model call turns only the returned evidence into a strict structured
answer whose every factual claim lists one or more returned `ref_id` values.
This avoids using IQ answer synthesis as both the system under test and the
citation formatter.

Procedure, authorization and crew evidence remain separate recall groups. This
exposes cases where synthesis sounds complete even though one required source
was not retrieved.

The benchmark explicitly queries all three required sources, applies
case-specific exact-identifier filters, and uses source-specific reranker
thresholds. The per-source candidate cap follows the preview API's 50–200
contract; a separate top-level cap limits the final set to 12 documents. The
defaults are documented in `.env.example`.

Every case runs `RAG_EVAL_REPEATS` times (three by default). Release requires
full evidence-group recall, 100% claim citation coverage and validity, no
missing requested evidence, warning-free HTTP 200 retrieval, and Foundry
groundedness and response-completeness scores of at least 4/5 on every repeat.
The case summary reports worst-case quality and p95 end-to-end latency.

## Preview fallbacks

| Capability | Current maturity/constraint | Workshop fallback |
|---|---|---|
| Client-side GenAI tracing | Preview; span schema may change | Keep custom OpenTelemetry spans and console trace IDs; use server-side prompt-agent traces where available |
| Trace evaluation | Preview | Evaluate the deterministic inline dataset from Labs 2–4 |
| Agent evaluators such as task completion/adherence | Some evaluators are preview | Retain deterministic policy assertions and use groundedness/relevance for the final text |
| Cloud agentic red teaming | Region- and target-limited; non-deterministic | Complete the local policy-abuse suite and risk register; optionally use local red teaming outside the timed workshop |
| Prompt-agent or model capacity | Quota/throttling can delay jobs | Reuse the inline pre-computed responses; the facilitator provides a saved result walkthrough |
| Foundry IQ retrieve preview or incomplete multi-source result | API shape can evolve; HTTP 206 and source warnings are possible | Run Lab 6 against direct Search and retain IQ activity/reference evidence for diagnosis |
| Contract-specific billing rates unavailable | Public list prices might not match the subscription agreement | Report tokens and request counts; leave USD estimate unset |

Cloud red teaming currently supports Foundry prompt and container agents but
not workflow agents, non-Foundry agents, or function-tool calls. Run it only in
a non-production “purple” environment with synthetic data.

The region gate uses `WORKSHOP_FOUNDRY_REGION` when explicitly set and otherwise
uses the deployment-generated `AZURE_LOCATION`.

## Interpreting results

Do not reduce a release decision to a single score.

- **Groundedness** asks whether the answer is supported by context.
- **Relevance** asks whether it addresses the query.
- **Retrieval** asks whether the retrieved context is useful.
- **Task adherence/completion** asks whether the agent followed instructions
  and produced the required outcome.
- **Tool Call Accuracy** combines tool choice and parameter quality.
- **Attack Success Rate** reports the share of adversarial attempts that
  succeeded; review the underlying examples and possible false positives.

LLM-assisted evaluators can vary between runs. Use deterministic assertions for
hard invariants, evaluate representative datasets, compare runs, and review
failed examples.

## Troubleshooting

### Authentication errors

Run `az login`, confirm the project endpoint, and verify the participant has the
Foundry User role. `DefaultAzureCredential` can also use managed identity or
developer credentials where configured.

### Evaluation API or type errors

Check:

```bash
python -c "import importlib.metadata as m; print(m.version('azure-ai-projects'))"
```

These notebooks target the repository pin `azure-ai-projects==2.3.0`. Mapping field names are
case-sensitive. Agent-response evaluation accepts inline `file_content`, not a
`file_id`.

### Traces do not appear

- Confirm Application Insights is connected.
- Confirm the user can read Application Insights/Log Analytics data.
- Wait 2–5 minutes and refresh.
- Ensure `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` was set before
  instrumentation.
- Create the OpenAI client after instrumentation to preserve trace context.

### Evaluation remains queued

Model capacity can cause server-side retries. Cancel the run, reduce the test
set, or use another approved deployment with sufficient capacity.

## Current official sources

Verified against Microsoft documentation in July 2026:

- [Add client-side tracing to Foundry agents](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side)
- [Set up tracing in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup)
- [Tracing and data handling](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-data)
- [Run cloud evaluations with the Foundry SDK](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/cloud-evaluation)
- [Agent evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators)
- [RAG evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators)
- [Retrieve from a Foundry IQ knowledge base](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve)
- [Foundry IQ FAQ and billing boundaries](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/foundry-iq-faq)
- [Azure AI Search pricing](https://azure.microsoft.com/en-us/pricing/details/search/)
- [Risk and safety evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/risk-safety-evaluators)
- [AI Red Teaming Agent](https://learn.microsoft.com/en-us/azure/foundry/concepts/ai-red-teaming-agent)
- [Run AI Red Teaming Agent in the cloud](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/run-ai-red-teaming-cloud)
- [Prompt Shields quickstart](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/quickstart-jailbreak)
