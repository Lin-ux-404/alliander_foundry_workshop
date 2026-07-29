# Workshop guide

## Completion outcome

Every team finishes with a grid-operations assistant that:

1. answers a procedure question from grounded knowledge and returns sources;
2. calls at least one deterministic tool or workflow step;
3. records an inspectable trace;
4. passes the repository's deterministic checks; and
5. has one Foundry evaluation run that the team can explain.

The goal is a reliable vertical slice. Hosted deployment, Toolboxes, custom
ingestion and advanced multi-agent patterns are stretch work.

## Audience and team model

- Level: Foundry 100–200.
- Assumed skills: Python fundamentals, JSON, basic command-line use and general
  cloud concepts.
- Recommended team size: three to five.
- Recommended support ratio: one active technical facilitator per ten learners.
- Every team receives a unique `WORKSHOP_RESOURCE_NAMESPACE`.

Suggested team roles:

- **Driver:** shares the screen and runs the current step.
- **Navigator:** reads instructions and checks success criteria.
- **Operator:** watches identity, quota and portal state.
- **Evaluator:** maintains the test cases and records results.

Rotate the driver after each required lab.

## Required and optional path

| Sequence | Material | Outcome | Track |
|---|---|---|---|
| 0 | Participant preflight | Identity, tools, namespace and project access validated | Required |
| 1 | Core lab 1 | Prompt agent with a deterministic function tool | Required |
| 2 | Core lab 2 | Streaming UX and observable progress | Required |
| 3 | Core lab 3 | Explicit multi-step workflow | Required |
| 4 | Core lab 4 | Custom deterministic safety executor | Required |
| 5 | Core lab 5 | Direct Azure AI Search grounding baseline | Required |
| 6 | Evaluation lab 1 | Trace exported and inspected | Required |
| 7 | Evaluation labs 2–4 | Response, trajectory and tool-call release gates | Required |
| 8 | Reference application | End-to-end dispatch demonstration | Required team demonstration |
| A | Core lab 6 | Foundry IQ knowledge-base comparison | Optional; use when the preview path is available |
| B | Core lab 7 | Reflection/revision loop | Optional |
| C | Evaluation lab 5 | Red-team and prompt-attack assessment | Optional |

## Two-day schedule

### Day 1 — foundations and grounded assistant

| Time | Activity |
|---|---|
| 09:00–09:30 | Access clinic and environment health check |
| 09:30–10:00 | Foundry, Agent Framework and the reference architecture |
| 10:00–10:45 | Core lab 1: agent and deterministic tool |
| 10:45–11:00 | Break |
| 11:00–11:30 | Core lab 2: streaming |
| 11:30–12:15 | Core lab 3: sequential workflow |
| 12:15–13:00 | Lunch |
| 13:00–13:45 | Core lab 4: deterministic safety executor |
| 13:45–14:30 | Core lab 5: direct Search baseline |
| 14:30–14:45 | Break |
| 14:45–15:20 | Team integration challenge |
| 15:20–15:30 | Checkpoint and evidence capture |

### Day 2 — workflows, quality and operational readiness

| Time | Activity |
|---|---|
| 09:00–09:20 | Recovery clinic and recap |
| 09:20–10:20 | Optional Foundry IQ comparison or direct-Search fallback analysis |
| 10:20–10:35 | Break |
| 10:35–11:20 | Evaluation lab 1: tracing |
| 11:20–12:10 | Evaluation lab 2: grounded-answer quality |
| 12:10–13:00 | Lunch |
| 13:00–13:50 | Evaluation lab 3: agent trajectories |
| 13:50–14:35 | Evaluation lab 4: tool-call regression |
| 14:35–14:50 | Break |
| 14:50–15:15 | End-to-end RAG release view or selected stretch lab |
| 15:15–15:30 | Evaluation comparison, takeaways and cleanup |

## Evidence checklist

Each team places the following in its handoff notes:

- team namespace and Foundry project;
- agent name and model deployment;
- one grounded question, response and source;
- one tool input/output pair;
- trace or correlation identifier;
- evaluation run name and metric summary;
- live RAG row with retrieval recall, citation coverage, groundedness, latency
  and token/request usage;
- one failure encountered and the recovery used;
- optional extension completed.

No secrets, keys, access tokens or personal data belong in the handoff.

## Preview fallback rules

- If Foundry IQ is unavailable, complete the direct Search lab and compare the
  architecture conceptually using the provided sample retrieval output.
- If a model-based evaluator is unavailable, run deterministic schema/tool tests
  and record the unavailable evaluator as skipped.
- If tracing export is delayed, inspect the local OpenTelemetry spans and retain
  the correlation identifier.
- Hosted agents, Toolboxes, Prompt Optimizer and preview evaluators never block
  the required completion outcome.
