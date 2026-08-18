# Workshop infrastructure and access

The supported production topology is **one isolated environment per team**.
Each invocation creates a resource group containing a Foundry account and
project, Azure AI Search, Storage, and Application Insights. Use a unique prefix
for every team.

`SharedProjects` is available as an explicit cost-optimization mode. It creates
multiple Foundry projects on one Search and Storage service. Resources are
namespaced per project, but built-in Search and Storage data roles apply across
the service. Shared mode is therefore **logical isolation, not a security
boundary**.

## Prerequisites

Operators need:

- Azure CLI and an active `az login` session in the target tenant.
- `Owner`, `User Access Administrator`, or equivalent permission to create the
  required role assignments at the deployed resource scopes.
- Permission to create resources and model deployments in the target
  subscription.
- Confirmed model quota and feature availability in the selected region.
- Entra object IDs for team security groups or individual principals.

Participants need Python 3.12, Node.js 20 or newer, Azure CLI, and the
repository dependencies. Local code uses `DefaultAzureCredential` or
`AzureCliCredential`; both use the participant's Azure CLI session. Search API
keys are disabled.

```powershell
az login --tenant <tenant-id>
az account set --subscription <subscription-id>
```

## Recommended: isolated team deployment

Prepare an access manifest for the team. Copy
[`access-manifest.example.json`](access-manifest.example.json), replace the
placeholder object IDs, and keep `projectIndex` set to `1`.

```powershell
.\setup\deploy.ps1 `
  -Prefix "workshop-team01" `
  -Location "swedencentral" `
  -SubscriptionId "<subscription-id>" `
  -AccessManifestPath ".\setup\access-manifest.json"
```

Repeat with `workshop-team02`, `workshop-team03`, and so on. Each invocation is
idempotent for the same prefix.

## Optional: shared-project deployment

Use shared mode only when all teams are allowed to access the same Search and
Storage services.

```powershell
.\setup\deploy.ps1 `
  -Prefix "workshop-shared" `
  -Topology "SharedProjects" `
  -ProjectCount 10 `
  -SearchSku "standard2" `
  -Location "swedencentral" `
  -AccessManifestPath ".\setup\access-shared.json"
```

Map every manifest entry with either:

- `projectIndex`: one-based index in the generated project list; or
- `projectName`: exact generated project name.

For example, a facilitator who needs all ten projects appears ten times in the
manifest, once for each project. Use Entra security groups instead of individual
users when practical.

### Search sizing guardrail

The deployment reserves an estimate of seven indexes per project: application
indexes, a hands-on Search index, and three Foundry IQ indexes. It rejects
topologies that exceed the documented index limit of the selected SKU.

| Search SKU | Maximum indexes | Maximum projects using the seven-index estimate |
|---|---:|---:|
| `basic` | 15 | 2 |
| `standard` (S1) | 50 | 7 |
| `standard2` (S2) | 200 | 28 |

The estimate is a deployment guardrail, not a substitute for load testing.
Parallel participants also share replicas, partitions, model quota, and
agent-service limits.

## Access manifest

The manifest uses Microsoft Entra **object IDs**, not application/client IDs or
user principal names. This avoids a Microsoft Graph dependency during
deployment.

```json
{
  "assignments": [
    {
      "projectIndex": 1,
      "principalId": "00000000-0000-0000-0000-000000000001",
      "principalType": "Group",
      "displayName": "workshop-team-01"
    }
  ]
}
```

Supported `principalType` values are `Group`, `User`, `ServicePrincipal`, and
`ForeignGroup`.

Each entry receives:

| Role | Scope | Purpose |
|---|---|---|
| `Reader` | Foundry account | See the account that contains the assigned project |
| `Foundry User` | Assigned Foundry project | Build, run, and evaluate agents |
| `Search Service Contributor` | Search service | Create and manage index definitions and knowledge resources |
| `Search Index Data Contributor` | Search service | Load and query index content |
| `Search Index Data Reader` | Search service | Query index content |
| `Storage Blob Data Contributor` | Storage account | Read and write workshop blobs |
| `Monitoring Reader` | Application Insights | Inspect telemetry configuration and trace views |
| `Log Analytics Reader` | Connected workspace | Query ingested traces and logs |

In shared mode, the last four service data roles are not project-scoped. A team
can technically access another team's Search or Storage resources. Namespacing
prevents accidental collisions, not malicious or mistaken cross-team access.

## Resources

For prefix `workshop-team01`, the script creates:

| Resource | Name |
|---|---|
| Resource group | `workshop-team01-rg` |
| Foundry account | `workshop-team01-foundry` |
| Foundry project | `workshop-team01-project` |
| Azure AI Search | `workshop-team01-search` |
| Storage account | Alphanumeric prefix plus `blob`; long names retain a deterministic hash |
| Application Insights | Alphanumeric prefix plus `insights` |

The Foundry account and projects use system-assigned managed identities. Project
connections to Search use Microsoft Entra authentication. Search data-plane API
keys are disabled.

Model deployments are created only after the deployment verifies that the exact
model version and deployment type are currently available to the subscription
in the selected region. The script also verifies that the Cognitive Services
quota endpoint is available. Use `-SkipQuotaCheck` only after an operator has
manually verified quota.

## Collision-safe environment files

Single-project deployment writes `.env`. Shared deployment writes one
`.env.<project-name>` per project plus `.env` for the first project.

Every file contains a unique `WORKSHOP_RESOURCE_NAMESPACE`. The generated names
include:

- `AZURE_SEARCH_INDEX`
- `AZURE_SEARCH_RO_INDEX`
- `AZURE_SEARCH_CREW_INDEX`
- `LAB_SEARCH_INDEX`
- `FOUNDRY_IQ_KNOWLEDGE_BASE`
- `FOUNDRY_IQ_PROCEDURES_INDEX`
- `FOUNDRY_IQ_RAAMOPDRACHTEN_INDEX`
- `FOUNDRY_IQ_CREW_INDEX`
- three corresponding `FOUNDRY_IQ_*_SOURCE` names
- `FOUNDRY_IQ_MCP_CONNECTION_NAME`
- `AZURE_STORAGE_CREW_CONTAINER`

Participant code must use these values and must not create or delete fixed-name
Search indexes, knowledge sources, knowledge bases, or containers.

No Search admin key is written to an environment file.

## Validation gates

After deployment, run the read-only operator validation:

```powershell
.\setup\Test-WorkshopDeployment.ps1 `
  -Prefix "workshop-team01" `
  -Location "swedencentral" `
  -AccessManifestPath ".\setup\access-team01.json"
```

For shared mode, pass the same `Topology`, `ProjectCount`, and `SearchSku` values
used for deployment. Fresh role assignments can take several minutes to
propagate; rerun the validation before investigating an immediate RBAC failure.

Every participant should then run:

```powershell
.\setup\Test-WorkshopPrerequisites.ps1 -EnvironmentFile ".env"
```

The check automatically uses the repository `.venv` when present, even when
PowerShell itself was launched outside an activated environment. An explicit
Python 3.12 executable can be supplied with `-PythonPath`.

The participant check verifies:

- required non-secret environment settings;
- Azure CLI, Python, Python packages, Node.js, and npm;
- expected tenant and subscription;
- Entra token acquisition for ARM, Foundry, Search, and Storage;
- Foundry project visibility;
- effective Search and Blob Storage data-plane access.

Do not distribute an environment until both gates pass.

## Seed the environment

From the selected project environment:

```powershell
python app/scripts/setup_search.py --all
python app/scripts/deploy_agents.py
```

For the optional multi-source Foundry IQ lab, also run:

```powershell
python app/scripts/setup_search.py --foundry-iq
```

This command creates namespaced semantic indexes for the synthetic
raamopdrachten and crew tables, then idempotently creates three knowledge
sources, one knowledge base, and its project-managed-identity MCP connection.
The reference application continues to use the local structured tables for its
deterministic authorization gates.

After seeding, run the drift check. It uses GET requests only and does not
recreate or update Azure resources:

```powershell
python app/scripts/setup_foundry_iq.py --validate-only
```

For shared mode, copy the target `.env.<project-name>` to `.env` before seeding
that project. Validate the generated namespace before running cleanup.

## Authentication model

- Operators authenticate with Azure CLI and require control-plane plus
  role-assignment permissions.
- Participants authenticate locally with Azure CLI.
- Python applications use `DefaultAzureCredential`, whose local developer chain
  can use that CLI session.
- Agent-to-Search access uses the Foundry project's managed identity.
- Search-to-model access uses the Search service's managed identity.
- Blob access uses Entra identities and `Storage Blob Data Contributor`.
- Trace review uses `Monitoring Reader` plus `Log Analytics Reader`; the
  Application Insights connection string is not distributed in `.env`.
- Search API keys are disabled and never distributed.

This design keeps participant access revocable through Entra groups and ensures
the preflight exercises the same identity path used by the labs.
