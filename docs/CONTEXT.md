# DRAAD reference application

## Purpose

DRAAD is a grid-operations teaching application. It accepts a free-text incident,
retrieves relevant low-voltage work instructions, builds a dispatch proposal,
applies deterministic rules and asks a reviewer agent to challenge the result.

All records are synthetic. The application must not be used to authorize real
electrical work or replace an operational decision maker.

## Runtime architecture

```text
Next.js UI
    |
    | HTTP + server-sent events
    v
FastAPI pipeline
    |
    +--> procedure retriever --> Azure AI Search / VWI PDFs
    |
    +--> matcher agent -------> VWI selection and rationale
    |
    +--> deterministic code --> RO/crew match, coverage and hard rules
    |
    +--> reviewer agent ------> pass, revise or human review
```

The backend streams stage, token and result events so learners can see the
pipeline rather than receive only a final answer.

## Responsibility split

| Component | Type | Responsibility |
|---|---|---|
| Intent router | Deterministic Python | Chooses procedure Q&A or incident dispatch |
| Procedure retriever | Foundry prompt agent with Search | Retrieves candidate VWI passages and source metadata |
| Dispatch matcher | Foundry prompt agent | Selects applicable VWIs and evidence-sensitive confidence |
| RO/crew matcher | Deterministic Python | Filters time/geography/availability and selects by VWI overlap |
| Rule checker | Deterministic Python | Evaluates the five auditable BEI-BLS rules |
| Dispatch reviewer | Foundry prompt agent | Challenges selection, dangerous-situation handling and confidence |
| Final gate | Deterministic Python | Emits `dispatch_ok` or `wv_escalation_needed` |
| Q&A assistant | Foundry prompt agent with Search | Answers procedure questions with sources |

## Dispatch state

The final response separates three concerns:

```json
{
  "coverage_status": "covered | partial | not_covered | unknown",
  "review_status": "pass | revise | flagged_for_human_review",
  "operational_action": "dispatch_ok | wv_escalation_needed"
}
```

`coverage_status` describes the structured VWI-to-RO relationship.
`review_status` describes workflow control. `operational_action` is the final
deterministic gate.

`dispatch_ok` requires:

- a matched raamopdracht;
- complete VWI coverage;
- no failed hard rule; and
- no human-review verdict.

## Deterministic rules

| Rule | Check |
|---|---|
| BLS-R01 | Every selected VWI exists in the indexed PDF catalogue |
| BLS-R02 | The selected VWI set is covered by the matched raamopdracht |
| BLS-R03 | The incident date is inside the raamopdracht validity window |
| BLS-R04 | The incident postcode prefix is inside the geographic scope |
| BLS-R05 | Live-work variants are explicitly permitted and covered |

Bare codes such as `E-22` can match an explicitly covered variant such as
`E-22-onder-sp`; the live-work rule still validates the selected variant.

## Data

| Source | Purpose | Runtime treatment |
|---|---|---|
| `app/docs/VWI/*.pdf` | Procedure knowledge | Indexed into Azure AI Search |
| `app/data/raamopdrachten.json` | Synthetic work scopes | Deterministic local lookup |
| `app/data/crew.json` | Synthetic crew assignments | Deterministic local lookup |
| `app/data/incidents.json` | Demonstration inputs | Loaded by the UI |

The Blob upload is an infrastructure/data-ingestion exercise. The reference
backend intentionally uses the versioned local JSON fixtures so demonstrations
remain reproducible.

## Isolation

Every team receives a unique `WORKSHOP_RESOURCE_NAMESPACE`. Unless explicit
resource names are supplied, the application appends this namespace to agent,
Search and Blob names.

The supported default is an isolated environment per team. Shared infrastructure
is an opt-in topology and requires namespaced resources plus participant-level
RBAC validation.

## Validation limits

Offline checks can prove:

- Python syntax and deterministic unit behavior;
- notebook structure and exercise markers;
- frontend compilation;
- resource-name derivation; and
- documentation consistency.

Only a live tenant test can prove identity propagation, model quota, regional
availability, Search/Foundry IQ behavior, trace export and evaluation execution.

Related documents:

- [Workshop guide](WORKSHOP_GUIDE.md)
- [Architecture decisions](ARCHITECTURE_DECISIONS.md)
- [Technical research baseline](RESEARCH_BASELINE.md)
- [Failure-mode catalog](FAILURE_MODES.md)
