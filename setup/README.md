# Workshop Deployment

## Quick Start

```powershell
.\setup\deploy.ps1 -Prefix "myteam-lab" -Location "westeurope" -ProjectCount 3
```

| Parameter      | Description                                              | Default          |
|----------------|----------------------------------------------------------|------------------|
| `-Prefix`      | Naming prefix for all resources (required)               | —                |
| `-Location`    | Azure region                                             | `swedencentral`  |
| `-ProjectCount`| Number of Foundry projects under a single Foundry account| `1`              |
| `-SubscriptionId`| Target subscription (uses current default if omitted)  | —                |

## What Gets Deployed

### 1. Resource Group

`{Prefix}-rg` — container for all resources below.

### 2. Azure AI Foundry Account

| Property      | Value                                                    |
|---------------|----------------------------------------------------------|
| Name          | `{Prefix}-foundry`                                       |
| Kind          | `AIServices`                                             |
| SKU           | **S0**                                                   |
| Identity      | System-assigned managed identity (enabled)               |
| Custom domain | `{Prefix}-foundry` (required for project creation)       |

### 3. Foundry Projects

One shared Foundry account with **N** projects underneath:

- `ProjectCount = 1` → `{Prefix}-project`
- `ProjectCount = N` → `{Prefix}-project-01` … `{Prefix}-project-{N}`

Each project gets its own system-assigned managed identity, connections, and `.env` file.

### 4. Model Deployments (on the Foundry account)

| Deployment Name            | Model                     | Version      | SKU              | Capacity (TPM) |
|----------------------------|---------------------------|--------------|------------------|----------------|
| `gpt-5.4-mini`            | gpt-5.4-mini              | 2026-03-17   | GlobalStandard   | 1 000          |
| `text-embedding-ada-002`  | text-embedding-ada-002    | 2             | GlobalStandard   | 656            |
| `gpt-4.1-mini`            | gpt-4.1-mini              | 2025-04-14   | GlobalStandard   | 8 000          |

All models are shared across projects (deployed at the account level).

### 5. Azure AI Search

| Property       | Value                                     |
|----------------|-------------------------------------------|
| Name           | `{Prefix}-search`                         |
| SKU            | **Basic**                                 |
| Replicas       | 1                                         |
| Partitions     | 1                                         |
| Identity       | System-assigned managed identity          |

### 6. Storage Account

| Property | Value                                            |
|----------|--------------------------------------------------|
| Name     | `{Prefix (alphanumeric only)}blob` (max 24 chars)|
| SKU      | **Standard_LRS**                                 |
| Kind     | StorageV2                                        |

### 7. Application Insights

| Property | Value                                             |
|----------|---------------------------------------------------|
| Name     | `{Prefix (alphanumeric only)}insights`            |
| Kind     | web                                               |

## RBAC Role Assignments

### Service-to-Service (managed identities)

| Principal          | Role                            | Scope       | Why                                                        |
|--------------------|---------------------------------|-------------|------------------------------------------------------------|
| Foundry MI         | Search Index Data Reader        | AI Search   | Agents can query search indexes                            |
| Foundry MI         | Search Service Contributor      | AI Search   | Agents can manage indexes (create, update)                 |
| Search MI          | Cognitive Services OpenAI User  | Foundry     | Search can call Foundry models for vectorization           |

### Deploying User

| Principal          | Role                            | Scope       | Why                                                        |
|--------------------|---------------------------------|-------------|------------------------------------------------------------|
| Signed-in user     | Cognitive Services User         | Foundry     | Can call Foundry APIs (agents, models, connections)        |
| Signed-in user     | Search Index Data Reader        | AI Search   | Can query search indexes from local scripts                |
| Signed-in user     | Storage Blob Data Contributor   | Storage     | Can upload/download blobs (crew data, documents)           |

## Per-Project Connections

Each Foundry project gets two connections created via the Management API:

| Connection          | Category          | Auth  | Purpose                                     |
|---------------------|-------------------|-------|---------------------------------------------|
| `search-connection` | CognitiveSearch   | AAD   | Agents can access AI Search indexes          |
| `appinsights-connection` | AppInsights  | AAD   | Tracing and telemetry from agent runs        |

## Generated `.env` Files

| Scenario           | Files                                                                 |
|--------------------|-----------------------------------------------------------------------|
| `ProjectCount = 1` | `.env` at repo root                                                   |
| `ProjectCount = N` | `.env.{project-name}` per project + `.env` defaulting to first project|

To switch the active project (multi-project): copy `.env.{project-name}` to `.env`.

## Next Steps After Deployment

```bash
# 1. Index data into AI Search
python app/scripts/setup_search.py --all

# 2. Deploy Foundry agents
python app/scripts/deploy_agents.py

# 3. Start the backend
cd app/backend && uvicorn main:app --reload

# 4. Start the frontend
cd app/frontend && npm run dev
```