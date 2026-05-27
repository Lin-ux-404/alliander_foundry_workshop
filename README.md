# Azure AI Foundry Workshop

> **This repository is for training purposes only.** It is not intended for production use.

## Contents

### Labs

Hands-on Jupyter notebooks covering Azure AI Agents and observability:

| # | Notebook | Topic |
|---|----------|-------|
| 1 | Azure AI Basics | Getting started with Azure AI Agents |
| 2 | Streaming | Streaming agent responses |
| 3 | Sequential Agents | Multi-agent loan application workflow |
| 4 | Custom Executors | Compliance workflow with custom executors |
| 5 | AI Search | Agents with Azure AI Search |
| 6 | Foundry IQ | Agentic retrieval with Knowledge Bases |
| 7 | Reflection Pattern | Workflow-as-agent with quality review loop |

### Demo App

A full-stack demo application (`app/`) with a Python backend and Next.js frontend, used to illustrate an end-to-end AI agent solution.

## Setup

1. Copy `.env.example` to `.env` and fill in your Azure resource details
2. Create a Python virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
3. Open the notebooks in VS Code and run them in order