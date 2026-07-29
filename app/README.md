# DRAAD reference application

DRAAD is a synthetic grid-operations assistant built with Microsoft Foundry,
Agent Framework, Azure AI Search, FastAPI and Next.js.

It demonstrates a grounded agent pipeline with deterministic safety gates. It is
training software, not an operational dispatch or electrical-work authorization
system.

## Architecture

```text
frontend/  Next.js interface and pipeline visualization
backend/   FastAPI, agents, deterministic rules and streaming orchestration
scripts/   Search indexing, Blob upload and prompt-agent deployment
data/      Synthetic incident, crew and raamopdracht fixtures
docs/      Synthetic workshop copies of procedure PDFs
```

Pipeline:

1. `procedure_retriever` searches the VWI corpus.
2. `dispatch_matcher` selects applicable VWIs and confidence.
3. Python selects the matching raamopdracht and crew.
4. `rule_checker` applies five deterministic checks.
5. `dispatch_reviewer` challenges the structured proposal.
6. Python computes the final operational action.

See [the architecture context](../docs/CONTEXT.md) for the responsibility split.

## Prerequisites

- Python 3.12
- Node.js 20 or later
- Azure CLI authenticated to the assigned tenant
- A Microsoft Foundry project with the required model deployment
- Azure AI Search connected to the project
- `Foundry User` on the assigned project
- Search data-plane roles required by the selected setup path

Run the repository participant preflight before starting.

## Configure

From the repository root:

```bash
cp .env.example .env
```

Set the project, Search and storage endpoints. Use the namespace assigned to your
team:

```dotenv
WORKSHOP_RESOURCE_NAMESPACE=team-01
```

Explicit resource-name variables override derived names. Never reuse another
team's namespace.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd app/frontend
npm ci
cd ../..
```

## Prepare Search and agents

The infrastructure deployment normally generates the environment file and
connections. From the repository root:

```bash
python app/scripts/setup_search.py --documents
python app/scripts/deploy_agents.py
```

To copy the synthetic lookup fixtures to Blob Storage as an ingestion exercise:

```bash
python app/scripts/setup_search.py --blob
```

The backend intentionally reads the versioned local JSON fixtures for
deterministic demonstrations.

## Run

Backend:

```bash
cd app/backend
python -m uvicorn main:app --reload --port 8000
```

Frontend, in a second terminal:

```bash
cd app/frontend
npm run dev
```

Open `http://localhost:3000`.

## Validate

From the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q app
cd app/frontend && npm run build
```

Cloud-dependent validation must still exercise one Search query, one deployed
agent and one complete dispatch in the assigned tenant.

## Safety and cleanup

- Use only the synthetic data included in the repository.
- Do not place credentials, access tokens or personal data in prompts or traces.
- Preserve exact VWI work-mode suffixes; ambiguous base codes fail closed.
- Delete only resources that contain your `WORKSHOP_RESOURCE_NAMESPACE`.
- Treat every dispatch result as a teaching artifact requiring human review.
