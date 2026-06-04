# DRAAD — capability gap: working demo vs briefing intent

**Date:** 2026-06-02
**Status:** demo functionally correct; Foundry feature showcase incomplete.
**Audience:** June 1/prep-call discussion + hackathon design owners (Shireen, Shenglin, Evi).

---

## TL;DR

The refactor made the demo **produce correct answers** end-to-end. But in doing so
it moved the implementation *away* from the two Foundry features the labs were
built to teach: **multi-index agentic retrieval** and **Workflow-agent
orchestration**. The app currently demonstrates *good agent engineering* but
sidesteps the headline Foundry capabilities. This is a teaching-artifact gap,
not a correctness bug.

---

## What the briefing wanted to showcase

From `briefing-shenglin-evi-2026-05-20.md` §5 (lab table) and §3 (agents):

1. **Lab 1 — multi-index agentic retrieval (headline #1).**
   One `procedure_retriever` agent making **two parallel retrieval calls across
   two indexes** (`idx_bls_corpus` + `idx_raamopdrachten`).
   Quote: *"AI Search agentic retrieval (decomposition + parallel sub-queries +
   rerank) across two indexes."*

2. **Lab 4 — Workflow orchestration (headline #2, "the wow lab").**
   A **Foundry Workflow YAML** graph wiring
   `procedure_retriever → dispatch_matcher → rule_checker → dispatch_reviewer`
   with a conditional revise loop.
   Quote: *"Workflow agents + agentic loops + deterministic gating in one graph.
   Cleanest Foundry-over-Bedrock moment available."*

3. **Lab 3 — `rule_checker` as a deterministic Foundry Workflow node** (not an
   LLM, not plain Python in the app), to show Workflow agents support non-LLM
   nodes.

4. **3 agents + 1 deterministic Workflow node**, with the orchestrator holding
   shared state and each node declaring what it reads.

---

## What the build actually does today

| Briefing intent | Current build | Status |
|---|---|---|
| `procedure_retriever` does **2 retrievals over 2 indexes** | 1 retrieval over `idx_bls_corpus` only; `idx_raamopdrachten` orphaned | ❌ Diverged (Lab 1 headline) |
| `dispatch_matcher` proposes crew + RO + coverage | Matcher only picks VWIs; Python does crew/RO/coverage | ⚠️ Diverged (Lab 2 content) |
| `rule_checker` = **deterministic Foundry Workflow node** | Python `rules/evaluate_rules.py` inside FastAPI | ⚠️ Deterministic ✓, not a Workflow node |
| `dispatch_reviewer` LLM-as-judge | Present, working | ✅ Met |
| Revise loop, max N=2 | Present | ✅ Met |
| **Orchestration = Foundry Workflow YAML** | FastAPI / `dispatch.py` hand-orchestration | ❌ Diverged (Lab 4 headline) |
| 3 agents + 1 deterministic node | 4 agents (retriever, matcher, reviewer, qa) + Python rules | ⚠️ Shape changed |
| Output schema (coverage / review / operational_action) | Matches exactly | ✅ Met |
| Symptom-vs-cause discipline, confidence enum | Matches | ✅ Met |
| 10 demo cases pass | Case 1 retesting; 2–10 pending | 🔄 Partial |

---

## Why it diverged (and why some of it was unavoidable)

The divergence was driven by real Foundry limits and quality bugs, not laziness.
See `docs/FAILURE_MODES.md` for the full catalog. The load-bearing ones:

- **#7 — Foundry one-index-per-tool limit.** The briefing's Lab 1 design ("one
  agent, two indexes, two parallel calls") is **not actually possible** as
  written: an `AzureAISearchTool` targets exactly one index, and you cannot
  attach two of them to one agent. MS Learn's prescribed answer is **connected
  agents** — one agent per index. So Lab 1's premise needs correction
  regardless of our refactor.

- **#6 — Matcher invented RO IDs** when asked to do RO selection via search.
  Pushed RO/crew/coverage into deterministic Python, which is *correct
  engineering* but removed the multi-source-citation moment Lab 2 was selling.

- **The orchestrator** was built as FastAPI + `dispatch.py` for iteration speed,
  not as a Foundry Workflow YAML. Functionally equivalent; demonstrates none of
  the Workflow-agent surface the labs are named after.

**Net:** we optimized for "the demo gives the right answer," which is not the
same goal as "the reference app demonstrates the Foundry features 26
participants came to learn."

---

## What still genuinely needs an index vs what doesn't

- **Genuinely semantic → belongs in AI Search:** `idx_bls_corpus` (193 chunks of
  free-text BLS VWI procedure PDFs). Semantic relevance over prose. Used by
  retriever + qa. ✅ Correct.
- **Small structured tables → Python lookups, not search:** `raamopdrachten.json`
  (6 rows) and `crew.json` (6 rows). These are SQL-WHERE / set-overlap problems.
  Making the LLM "search" them caused #6 and #7. Python is the right call **for
  correctness** — but it's why the multi-index demo disappeared.

The tension: the *correct* data-engineering answer (Python for small tables)
directly removes the *teaching* artifact (multi-index retrieval). Resolving this
means choosing the **connected-agents** pattern, which is both Foundry-correct
*and* restores the showcase.

---

## Options to close the gap

### Option A — Connected agents for RO matching (recommended)
Re-introduce a `dispatch_ro_matcher` **connected agent** bound to
`idx_raamopdrachten`, called by the matcher. Keep crew lookup in Python (a
genuine dict lookup, defensible "right tool" beat).
- ✅ Restores multi-index — the way Foundry actually recommends (#7).
- ✅ Stronger than "one agent, two indexes": shows agent-to-agent composition.
- ✅ Dovetails with the failure-mode story (#7 is *why* you went connected-agents).
- ⚠️ Re-introduces some RO-selection nondeterminism; mitigate by keeping the
  Python `_pick_best_ro` as a deterministic post-check / tie-breaker.

### Option B — Reframe the narrative, keep current architecture
Teach "naive multi-index (and why it broke: #6/#7) → corrected architecture."
The failure-mode catalog *becomes* the lab.
- ✅ Strongest engineering story; zero rebuild.
- ❌ Does not deliver a working multi-index or Workflow demo — contradicts the
  lab titles.

### Option C — Foundry Workflow YAML for orchestration (addresses Lab 4)
Port `dispatch.py` orchestration into a Foundry Workflow YAML graph with the
revise loop and a deterministic rule node.
- ✅ Restores the Lab 4 / Lab 3 headlines.
- ⚠️ Larger lift; preview-feature stability risk (Workflow agents are preview).
- Note: Connected Agents (classic) is deprecated 31 Mar 2027 — if we go this
  route, prefer Workflow agents over classic connected agents.

**Recommended path:** A now (cheap, restores multi-index correctly), then C as
the stretch/"wow" lab if Workflow-agent preview proves stable on the prep-call
dry run. B's narrative is worth keeping *on top of* A — the failure modes are a
genuine asset for the workshop regardless.

---

## Decisions needed (prep call)

1. Is **multi-index retrieval** a required showcase? → if yes, Option A.
2. Is **Foundry Workflow YAML orchestration** required, or is FastAPI acceptable
   for the reference app? → drives Option C scope.
3. Does Lab 1's briefing text get **corrected** for the one-index-per-tool limit
   regardless? (It is factually wrong as written.)
4. Lab 3: does `rule_checker` need to be a real Workflow node, or is Python
   `evaluate_rules.py` an acceptable stand-in for teaching?

---

## What's solid and should not be touched

- Output schema + three-status separation (coverage / review / operational_action).
- Symptom-vs-cause discipline + 2-value confidence enum.
- Deterministic BEI hard-rules (BLS-R01..R05).
- Reviewer LLM-as-judge + revise loop.
- The refactor's core insight (small structured tables → Python). Keep it; just
  re-expose the RO match as a connected agent for the demo surface.

---

## Cross-references
- `docs/FAILURE_MODES.md` — full 12-mode catalog + LLM-vs-Python split.
- `briefing-shenglin-evi-2026-05-20.md` §3, §5 — agent specs + lab table.
- `demo-scenarios.md` — 10 demo cases + synthetic data.
- `use-case-explained.md` — domain background + worked example.
