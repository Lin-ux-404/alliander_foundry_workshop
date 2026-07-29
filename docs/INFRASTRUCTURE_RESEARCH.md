# Infrastructure and access research

Research checked on **2026-07-29** against current Microsoft documentation.
This note records the implementation decisions behind `setup/`.

## Decisions

### Isolation topology

The default supported topology is one isolated Azure environment per team:
resource group, Foundry account/project, Search, Storage, and Application
Insights. A Foundry project is an individual development container, but it
doesn't turn a shared Search or Storage service into a project-level security
boundary.

`SharedProjects` is an explicit cost-optimized alternative. Every project gets a
unique namespace, but Search and Storage built-in data roles still apply across
their service scopes. Search index data roles can be narrowed to an existing
index, but participants who create Search objects and Foundry IQ knowledge
resources need service-level object-management permission. Isolated services are
therefore the reliable boundary for an open hands-on environment.

### Foundry RBAC

Microsoft recommends Microsoft Entra authentication and the least-privilege
Foundry roles. The current developer role is `Foundry User`, stable role ID
`53ca6127-db72-4b80-b1b0-d745d6d5456d`. It was previously displayed as
`Azure AI User`; the ID and permissions did not change.

Participants receive `Reader` on the Foundry account and `Foundry User` on their
assigned project. Each project managed identity also receives `Foundry User` on
the Foundry account, matching Microsoft's minimum-assignment guidance.

The deployment accepts Entra object IDs for groups, users, service principals,
and foreign groups. Object IDs plus `--assignee-principal-type` avoid a Graph
lookup and reduce role-assignment failures during principal propagation.

### Search and Foundry IQ permissions

Microsoft's Foundry agent/Search guidance requires the project managed identity
to have:

- `Search Service Contributor` for index and knowledge-resource definitions.
- `Search Index Data Contributor` for index content and queries.

Hands-on users also receive `Search Index Data Reader` so the three documented
Search development roles are explicit. Search API keys are disabled; all data
access uses Entra tokens.

Foundry IQ is backed by Azure AI Search. Its availability follows Search,
Foundry/model, and agentic-retrieval regional availability. Search and Foundry
must be checked in the same intended physical region for integrated scenarios.

### Collision prevention

Azure AI Search resource types have different naming rules. The deployment uses
lowercase letters, numbers, and dashes, a conservative subset valid for Search
indexes and related knowledge resources. Names are derived from the Foundry
project name, normalized, and limited to 40 characters before a resource suffix
is added.

The generated environment defines unique names for application indexes, lab
indexes, Foundry IQ indexes and knowledge bases, and Blob containers. Fixed
resource names and unconditional cleanup are unsupported in shared mode.

### Authentication

Local participants explicitly use `az login` in the correct tenant and
subscription. `AzureCliCredential` uses that session directly;
`DefaultAzureCredential` can use it in the local developer credential chain.
Applications and scripts do not receive a Search admin key.

Effective access is checked at the data plane because role-list inspection alone
doesn't prove access inherited through Entra group membership.

Application Insights is workspace-based. Participants receive `Monitoring
Reader` on the component and `Log Analytics Reader` on the connected workspace
so they can inspect traces without receiving the component connection string.

### Deployment APIs, region, and quota

Project, connection, and capability-host operations use the stable
`Microsoft.CognitiveServices` API version `2025-06-01` instead of the earlier
preview API.

Foundry feature, Agent Service tool, model, Search, and Foundry IQ availability
can differ by region and subscription. The deployment:

1. Queries the Cognitive Services regional quota endpoint.
2. Lists the exact model versions and deployment types available to the newly
   created Foundry account before deploying them.
3. Rejects a model or SKU that isn't currently available.
4. Provides a separate read-only operator validator.

Quota is regional, per subscription, and per model/deployment type. A successful
resource deployment doesn't prove sufficient throughput for simultaneous
participants, so a representative concurrency test remains mandatory.

Azure AI Search has hard index limits by tier. The shared topology reserves an
estimate of seven indexes per project and rejects a project count that exceeds
the selected SKU's documented index limit.

## Official sources

- [Role-based access control for Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/concepts/rbac-foundry)
- [Authentication and authorization in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/concepts/authentication-authorization-foundry)
- [Elevated-role tasks in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/concepts/administrator-guide)
- [Create a Foundry project](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-projects)
- [Azure built-in roles for AI and machine learning](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/ai-machine-learning)
- [Assign Azure roles using Azure CLI](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-cli)
- [Foundry projects REST API, version 2025-06-01](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/projects/create?view=rest-microsoftfoundry-accountmanagement-2025-06-01)
- [Foundry project capability hosts REST API, version 2025-06-01](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/project-capability-hosts/create-or-update?view=rest-microsoftfoundry-accountmanagement-2025-06-01)
- [Foundry account connections REST API, version 2025-06-01](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/account-connections/create?view=rest-microsoftfoundry-accountmanagement-2025-06-01)
- [Enable role-based access control for Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-security-enable-roles)
- [Azure AI Search role permissions](https://learn.microsoft.com/en-us/azure/search/search-security-rbac)
- [Connect Azure AI Search to Foundry agents](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/ai-search)
- [Connect Foundry agents to a Foundry IQ knowledge base](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect)
- [Foundry IQ FAQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/foundry-iq-faq)
- [Azure AI Search naming rules](https://learn.microsoft.com/en-us/rest/api/searchservice/naming-rules)
- [Azure AI Search service limits](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)
- [Azure AI Search regional availability](https://learn.microsoft.com/en-us/azure/search/search-region-support)
- [Microsoft Foundry regional feature availability](https://learn.microsoft.com/en-us/azure/foundry/reference/region-support)
- [Foundry Agent Service quotas and regional support](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions)
- [Manage Azure OpenAI quota in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota)
- [Automate model deployments using quota information](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/automate-quota-deployments)
