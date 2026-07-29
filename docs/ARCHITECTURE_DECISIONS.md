# DRAAD architecture decisions

## Status

The reference application is an educational vertical slice. It demonstrates a
grounded agent, deterministic operational rules, an LLM reviewer and an
inspectable streaming pipeline. It is not a production dispatch system.

## Decision 1: semantic documents use Search

VWI procedure PDFs contain unstructured prose and belong in Azure AI Search.
The retriever searches `AZURE_SEARCH_INDEX` and returns candidate VWI codes,
content and sources.

Small structured tables such as crew and raamopdrachten are loaded
deterministically. Selecting a record from six rows is a set/filtering problem,
not a semantic-retrieval problem.

Consequences:

- semantic retrieval is limited to content for which it adds value;
- record identifiers are never invented by a model;
- coverage and authorization-like checks remain reproducible; and
- the Foundry IQ lab uses separate semantic copies of the synthetic structured
  tables to demonstrate multi-source retrieval without moving the reference
  application's authorization gates into a model.

## Decision 2: deterministic gates remain code

The application uses Python for:

- postcode and temporal filtering;
- VWI-to-raamopdracht overlap;
- crew lookup;
- coverage status;
- BEI rule verdicts; and
- final operational action.

Models are used for:

- semantic VWI retrieval;
- incident-to-procedure judgement;
- evidence-sensitive confidence classification; and
- soft review of a structured proposal.

This separation keeps safety-relevant gates auditable while still showing the
value and limitations of agent reasoning.

## Decision 3: orchestration has stable and stretch paths

The FastAPI application is the stable executable path. It exposes every stage as
a server-sent event and works even when a hosted workflow surface is unavailable.

The Agent Framework workflow labs are the learning path for explicit routing,
custom executors and reflection loops. Hosted agents and Toolboxes are stretch
material because their prerequisites and availability can change.

## Decision 4: Foundry IQ is knowledge, evaluation is quality

Foundry IQ supplies agentic retrieval over knowledge sources. It is compared
against the direct Search baseline in the knowledge labs.

Evaluation and observability are separate:

- traces explain what happened;
- deterministic assertions check schemas and tool behavior;
- retrieval evaluators assess the retrieved context;
- groundedness/relevance assess the generated answer; and
- red-team exercises probe adversarial behavior.

## Decision 5: every mutable name is scoped

`WORKSHOP_RESOURCE_NAMESPACE` scopes indexes, knowledge bases, agents, evaluation
runs and Blob containers. Explicit environment variables can override the
derived names.

Cleanup logic must delete only names carrying the current namespace. The default
deployment remains one isolated environment per team.

## Known product boundaries

- Feature, model and tool availability varies by region and subscription.
- Foundry IQ combines generally available and preview surfaces.
- Hosted agents and Toolboxes are not required for workshop completion.
- Traces can contain input, output and tool data; only synthetic data is used.
- Search/agent/evaluation cloud execution requires a live tenant and cannot be
  proven by offline repository validation alone.

See [RESEARCH_BASELINE.md](RESEARCH_BASELINE.md) for the current official sources
and [FAILURE_MODES.md](FAILURE_MODES.md) for the operational troubleshooting
catalog.
