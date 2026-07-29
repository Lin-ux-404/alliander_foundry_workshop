# Facilitator runbook

## Release gates

Do not start the workshop until every required gate is green.

| Gate | Pass condition | Owner |
|---|---|---|
| Curriculum | Required/optional path and expected artifacts are frozen | Content lead |
| Repository | Release tag created; clean-clone validation passes | Repository owner |
| Identity | Test learners can enter only their assigned projects | Cloud operator |
| Isolation | Two teams can run Search and Foundry IQ concurrently without name collisions | Cloud operator |
| Capacity | Model/Search load test completes without sustained throttling | Cloud operator |
| Devices | Preflight passes on a managed learner device | Learner support |
| Support | Presenter, floor support and infrastructure escalation shifts assigned | Facilitation lead |
| Recovery | Known-good checkpoints and fallback outputs are available | Lab owners |

## Recommended staffing

For 50 learners, plan at least five active technical facilitators plus one
infrastructure escalation owner. A person presenting cannot simultaneously be
counted as floor support.

Assign these roles for every block:

- lead instructor;
- two or more floor facilitators;
- remote/chat facilitator where applicable;
- cloud and identity operator;
- timekeeper/evidence coordinator.

## Seven-day readiness sequence

### Seven to five days before

- Freeze package versions, lab content and infrastructure topology.
- Deploy all team environments in the target tenant and region.
- Import participant or team Entra groups.
- Confirm quota for the model, Search tier and Foundry IQ dependencies.
- Run the participant preflight with non-administrator identities.

### Four to two days before

- Run every required lab from a clean clone.
- Run a parallel Search/Foundry IQ collision test.
- Measure realistic latency and adjust timings.
- Prepare known-good notebook checkpoints and static fallback outputs.
- Publish the support matrix and escalation contacts.

### One day before

- Stop making feature changes.
- Revalidate access and quota.
- Confirm room power, Wi-Fi, proxy behavior and display setup.
- Verify the release tag and checksum.
- Send only the participant path; keep solutions/recovery notes restricted.

## Opening access clinic

Learners must demonstrate all of the following before joining a lab:

1. open the assigned Foundry project;
2. authenticate with Azure CLI using the correct tenant;
3. create the Python 3.12 environment and import the pinned packages;
4. run the participant preflight;
5. read the shared Search endpoint with their assigned identity;
6. display a non-empty `WORKSHOP_RESOURCE_NAMESPACE`.

Move blocked learners to an access clinic instead of debugging identity problems
inside the main instruction flow.

## Live support protocol

Classify issues before changing code:

| Category | First check | Escalation |
|---|---|---|
| Identity/RBAC | Tenant, signed-in account, role scope, token refresh | Cloud operator |
| Quota/throttling | HTTP status, Retry-After, model deployment and regional quota | Cloud operator |
| Resource collision | Namespace and target Search/KB/agent names | Lab owner |
| SDK/API | Pinned environment, notebook kernel, release tag | Repository owner |
| Content/output | Input data, trace, retrieved context, deterministic checks | Content facilitator |
| Device/network | Proxy, TLS inspection, ports and package source | Learner support |

Capture the command, status code, correlation ID and sanitized error before
escalating. Never paste tokens or connection secrets into shared chat.

## Completion review

A team passes when it can explain:

- where nondeterministic reasoning is used;
- where deterministic validation is used;
- how the answer is grounded;
- what the trace shows;
- what the evaluation measures; and
- when the system must escalate to a human.

The number of notebooks executed is not a success metric.

## Cleanup

- Delete only resources carrying the team's namespace.
- Preserve evaluation summaries and sanitized evidence.
- Revoke temporary group assignments.
- Remove temporary keys or rotate them if any were issued.
- Confirm cost-bearing resources and model deployments have the intended
  post-workshop lifecycle.
