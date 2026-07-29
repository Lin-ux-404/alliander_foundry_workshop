# Workshop owner release checklist

The repository now has safe defaults, but these delivery decisions require an
accountable owner. Record the answers before the environment freeze.

## Questions that must be answered

| Decision | Question for the owner | Recommended default | Release evidence |
|---|---|---|---|
| Outcome | Is the required outcome the five-part vertical slice in the workshop guide, and who can accept it? | One named content owner signs off against the evidence checklist. | Signed dry-run checklist |
| Audience | How many learners, teams, locations and managed-device profiles are expected? | Teams of three to five; one active facilitator per ten learners. | Roster and staffing plan |
| Schedule | What are the confirmed delivery dates, time zone, room/remote format and hard breaks? | Freeze the two-day schedule seven days before delivery. | Calendar and published agenda |
| Tenant | Which tenant and subscription are approved, and who owns emergency access? | A dedicated workshop subscription with a named cloud operator. | Tenant/subscription IDs and escalation owner |
| Isolation | Can each team receive its own resource group and services? | Use `TeamIsolated`; approve `SharedProjects` only as a documented cost tradeoff. | Topology decision |
| Identity | Which Entra groups map to each team, and may guest identities be used? | Pre-created groups; validate with ordinary learner accounts. | Completed access manifest and preflight |
| Region | Which Azure region is approved by policy and supports the exact models and features? | Select only after the operator checks current Foundry, Search and quota availability. | Deployment validator output |
| Capacity | What concurrency and latency are acceptable, and who can request quota? | Load-test the real team count; keep optional preview work outside the critical path. | Load-test result and quota owner |
| Data | Is synthetic data mandatory, and are trace content capture and retention approved? | Synthetic data only; message-content tracing off by default. | Data-handling decision |
| Network | Do managed devices use proxies, TLS inspection or package-source restrictions? | Test a representative managed device at least four days ahead. | Device preflight output |
| Features | Is Foundry IQ available and approved in the target environment? | Direct Search is required; Foundry IQ remains an optional comparison. | Feature check or fallback declaration |
| Support | Who owns content, identity, infrastructure and device escalations during each block? | Name distinct owners; the presenter is not counted as floor support. | Support rota |
| Lifecycle | When are model deployments and team resources removed, and what evidence is retained? | Namespace-scoped cleanup after sanitized results are exported. | Cleanup owner and deadline |

## Recommendations to adopt

1. Create a release tag and stop feature changes one day before delivery.
2. Run every required notebook from a clean Python 3.12 environment using the
   pinned dependencies.
3. Validate deployment and participant access with non-administrator accounts.
4. Test at least two teams concurrently to expose quota and naming collisions.
5. Keep known-good notebook outputs and deterministic fallbacks available to
   facilitators without distributing solution material in advance.
6. Treat Foundry IQ, hosted agents, Toolboxes and cloud red teaming as optional
   unless their regional availability and permissions are proven in the target
   tenant.
7. Capture only sanitized evidence: resource namespace, trace/correlation ID,
   evaluation summary and recovery notes—never credentials or personal data.
8. Assign one person to enforce timeboxes and route blocked learners to the
   access clinic.

## Final go/no-go

The owner should declare **go** only when every release gate in
[FACILITATOR_RUNBOOK.md](FACILITATOR_RUNBOOK.md) is green and no required path
depends on a preview feature. Any exception must name an owner, fallback and
deadline.
