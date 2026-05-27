# DRAAD – Dispatch & Routing AI Assistant for Alliander

Multi-agent dispatch assistant for Alliander's electrical grid, built on Azure AI Foundry.

## Architecture

```
frontend/  → Next.js UI (chat interface)
backend/   → FastAPI server (pipeline orchestration + rule engine)
scripts/   → One-time setup scripts (indexing, agent deployment)
data/      → Synthetic crew & raamopdrachten JSON
docs/      → BEI-BLS procedure PDFs (VWI work instructions)
```

**Agent pipeline** (see `backend/pipeline.py`):

1. `procedure_retriever` – searches VWI corpus for candidate work instructions
2. `dispatch_matcher` – proposes crew/RO match with coverage analysis
3. `rule_checker` – deterministic BEI-BLS rule validation (no LLM)
4. `dispatch_reviewer` – LLM-as-judge that challenges the proposal

## Prerequisites

- Python 3.11+
- Node.js 18+
- An Azure AI Foundry project with a deployed model (e.g. `gpt-4o`)
- An Azure AI Search resource connected to the Foundry project

## Setup

### 1. Configure environment

```bash
cp backend/.env.example backend/.env
# Fill in FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL,
# AZURE_SEARCH_ENDPOINT, and AZURE_SEARCH_CONNECTION_NAME
```

### 2. Install dependencies

```bash
# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### 3. Index all data into AI Search

```bash
python scripts/index_documents.py      # idx_bls_corpus
python scripts/index_raamopdrachten.py  # idx_raamopdrachten
python scripts/index_crew.py            # idx_crew
```

### 4. Set `AZURE_SEARCH_CONNECTION_NAME` in `backend/.env`

Create the AI Search connection in the Foundry portal first, then set the
connection name in your `.env`.

### 5. Deploy agents to Foundry

```bash
python scripts/deploy_agents.py
```

### 6. Run the app

```bash
# Terminal 1 – backend
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2 – frontend
cd frontend && npm run dev
```

Open http://localhost:3000 to use the app.
