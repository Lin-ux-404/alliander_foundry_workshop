# Microsoft Foundry grid-operations workshop

A two-day, level 100–200 workshop for building and evaluating a grounded
internal-operations assistant with Microsoft Foundry, Microsoft Agent Framework,
Azure AI Search, Foundry IQ, OpenTelemetry and Foundry evaluation.

All scenarios and records are synthetic. Nothing in this repository authorizes
real electrical work or replaces an operational decision maker.

## Completion outcome

Every team demonstrates a vertical slice that:

1. answers a procedure question from grounded knowledge and returns sources;
2. calls a deterministic tool or workflow step;
3. produces an inspectable trace;
4. passes deterministic behavior checks; and
5. has an evaluation result the team can interpret.

Preview-dependent capabilities have explicit fallbacks and do not block the
core outcome.

## Start here

| Audience | Guide |
|---|---|
| Participant | [Workshop path and schedule](docs/WORKSHOP_GUIDE.md) |
| Cloud operator | [Infrastructure, access and deployment](setup/README.md) |
| Core-lab participant | [Agent and knowledge labs](labs/azure-ai-agents/README.md) |
| Day-2 participant | [Observability, evaluation and safety labs](labs/observability-and-evaluation/README.md) |
| Facilitator | [Facilitator runbook](docs/FACILITATOR_RUNBOOK.md) |
| Workshop owner | [Release decisions and recommendations](docs/OWNER_CHECKLIST.md) |
| Application builder | [DRAAD reference application](app/README.md) |
| Technical reviewer | [Research baseline](docs/RESEARCH_BASELINE.md) and [architecture decisions](docs/ARCHITECTURE_DECISIONS.md) |

## Learning path

### Core agents and knowledge

| Lab | Topic | Expected artifact |
|---|---|---|
| 1 | Agent with function tools | Tool-grounded incident response |
| 2 | Streaming | Streamed operations brief |
| 3 | Sequential workflow | Triage-to-planning workflow |
| 4 | Deterministic executor | Auditable safety gate |
| 5 | Azure AI Search | Grounded answer with citation inspection |
| 6 | Foundry IQ | Optional multi-source knowledge-base comparison |
| 7 | Reflection | Optional bounded revision loop |

### Observability, evaluation and safety

| Lab | Topic | Expected artifact |
|---|---|---|
| 1 | OpenTelemetry and Application Insights | Correlated trace |
| 2 | Grounded-answer evaluation | Retrieval, groundedness and relevance baseline |
| 3 | Agent evaluation with tools | System and process-quality comparison |
| 4 | Tool-call regression | Deterministic and semantic release gate |
| 5 | Red-team testing | Optional risk register and cloud assessment |
| 6 | End-to-end Search RAG evaluation | Live recall, citations, groundedness, latency and cost |
| 7 | End-to-end Foundry IQ RAG evaluation | Multi-source retrieval and synthesis release view |

## Supported environment

- Python 3.12
- Node.js 20 or later
- Azure CLI authenticated to the assigned tenant
- PowerShell 7 for deployment and preflight scripts
- Microsoft Entra ID access to the assigned Foundry project
- Pinned direct Python dependencies from `requirements.txt`

Every team receives a unique `WORKSHOP_RESOURCE_NAMESPACE`. The supported
default deployment creates an isolated Foundry/Search/Storage environment per
team. Shared-project mode is an explicit cost optimization and is not a security
boundary.

## Participant setup

The cloud operator provides a generated `.env` file. First create the validated
Python environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Then validate the environment, tooling, Azure identity, and data-plane access:

```powershell
.\setup\Test-WorkshopPrerequisites.ps1 -EnvironmentFile ".env"
```

The preflight automatically uses the repository `.venv` when present. Pass
`-PythonPath` only when using a different Python 3.12 environment.

Install the reference UI:

```bash
cd app/frontend
npm ci
```

For a manual local configuration, copy `.env.example` to `.env` and replace
every placeholder. Never reuse another team's namespace.

## Repository layout

```text
app/                                  DRAAD FastAPI + Next.js reference app
labs/azure-ai-agents/                 Agent, workflow, Search and Foundry IQ labs
labs/observability-and-evaluation/    Trace, evaluation and security labs
setup/                                Deployment, RBAC and preflight automation
docs/                                 Curriculum, architecture and facilitation
tests/                                Deterministic application tests
scripts/validate_workshop.py          Offline release gate
```

## Offline validation

```bash
python3.12 scripts/validate_workshop.py
python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q app tests scripts
cd app/frontend && npm run build
```

Offline validation cannot prove tenant RBAC propagation, regional feature
availability, model quota, Search/Foundry IQ behavior, trace ingestion or cloud
evaluation execution. The facilitator runbook makes those live checks release
gates.

## Safety

- Use only synthetic workshop data.
- Keep message-content tracing off unless explicitly approved.
- Never commit `.env`, keys, tokens or participant identity files.
- Delete only resources that contain the current team namespace.
- Treat model-based evaluators as evidence, not deterministic truth.
- Escalate any operationally consequential result to a qualified human.
