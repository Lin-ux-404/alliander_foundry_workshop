# DRAAD — context

> Single-page orientation for anyone picking up this repo: **what** we are
> building, **why** the architecture looks the way it does, **how** it is
> deployed for the hackathon, and the **10 demo cases** that drive evaluation.
>
> Source briefings (Memory repo): `briefing-shenglin-evi-2026-05-20.md`,
> `use-case-explained.md`, `demo-scenarios.md`, `README.md`. This document is
> the working-repo distillation of those four.

**DRAAD** = **D**ispatcher-**R**eviewer **A**gent **A**rchitecture for **D**SOs.
(Dutch for "wire / thread.") A two-day hackathon (8–9 June 2026, 26 Alliander
participants) to upskill Alliander engineers in **Azure AI Foundry**.

---

## 1. Use case

A **BEI-LS dispatch coverage assistant** for a Liander dispatcher in the 24/7
low-voltage grid control room (bedrijfsvoeringscentrum).

**The system does not authorise work.** Dutch electrical-safety regulation (BEI)
distributes that authority across aanwijzingen, raamopdrachten, VWIs, the WV, and
the meldpunt. The assistant's job is narrower and BEI-faithful:

1. Identify the candidate VWIs (safety work instructions) likely required to
   resolve a storing (grid fault).
2. Check whether an available crew member's standing **aanwijzingen +
   raamopdrachten** appear to cover that work.
3. Flag cases needing **WV escalation** before dispatch.

**Persona — Lisa**, dispatcher in Duiven. A storing arrives via SCADA alarm, KCC
(customer-service) call, or field-crew radio. Lisa has a pool of available crew,
each holding standing raamopdrachten issued ahead of time by a WV. She decides
*who* to send, not *what* to do — and never replaces the crew's on-site LMRA
(last-minute risk analysis).

**Scope:** BLS (low voltage, ≤ 1000 V) only. BHS (medium/high voltage) is out.

### Domain vocabulary (the 7 terms you actually need)

| Term | Meaning |
|---|---|
| **BEI** | Dutch grid safety regulation. **BEI-BLS** = low voltage (our scope); BEI-BHS = MS/HS (out). PDFs at beiviag.nl, annual 15-April release; we use 2026-04-15. |
| **VWI** | VeiligheidsWerkInstructie — a numbered safety work instruction (E-04, E-22, E-67, …). The unit of work. LS catalogue = 40; we index 10. |
| **Aanwijzing** | Personal authorisation certifying *capability* (WV > OIV > IV > AVP > VP > VOP). WV = Werkverantwoordelijke, the work supervisor who can authorise. |
| **Raamopdracht (RO)** | A standing work order issued by a WV ahead of time: "you, holding this aanwijzing, may perform these VWIs in this region during this validity period." Format fixed by BEI-BLS bijlage 06. Answers *permitted right now, here?* |
| **Storing** | A grid fault/outage. Arrives via SCADA alarm, KCC call, or field-crew radio. |
| **Dispatcher / bedrijfsvoeringscentrum** | The control-room operator (Lisa) who assigns storingen to crews. |
| **LMRA** | Laatste Minuut Risico Analyse — the crew's own on-site safety check. DRAAD never replaces it. |

### Worked example (the lead case)

Input — Lisa logs a hybrid incident (free-text NL + structured anchors):

> "Klant aan de Hoofdstraat 12, 1701 AB Heerhugowaard meldt brandlucht uit de
> meterkast. Geen rookontwikkeling. Klant heeft hoofdschakelaar uitgezet."
> anchors: postcode 1701, asset `aansluitkast`, voltage LS, crew shortlist.

Output — a structured coverage + escalation recommendation:

- VWIs: `E-67` (candidate), `E-60` (candidate) — both *candidate* because the
  incident is symptom-only (a burning smell is not a confirmed cause).
- Matched crew K. de Vries / RA-NHN-0101. RO covers E-67 but **not** E-60.
- `coverage_status = partial`, `operational_action = wv_escalation_needed`.

Lisa reads it, sanity-checks, calls the WV, dispatches with authorisation.

---

## 2. Architecture (as built in this branch)

> This is the **single source of truth** for the implementation we are shipping
> on this branch. It deliberately diverges from the original briefing in three
> load-bearing ways — driven by real Foundry limits and quality bugs, not
> convenience. The full rationale is in [FAILURE_MODES.md](FAILURE_MODES.md)
> (esp. #6 invented RO IDs, #7 one-index-per-tool) and
> [CAPABILITY_GAP.md](CAPABILITY_GAP.md). The three divergences:
>
> 1. **The matcher only selects VWIs + writes prose.** It does **not** pick the
>    RO, crew, or coverage — those are computed deterministically in Python.
> 2. **Only the BLS rulebook is indexed.** Crew + raamopdrachten are **not** in
>    AI Search; they are JSON read by Python (→ Blob, see §5).
> 3. **Orchestration is FastAPI + `dispatch.py`**, not a Foundry Workflow YAML.
>    `rule_checker` is a Python module, not a Workflow node.

**Four prompt agents + a deterministic Python core.** The LLM does only the
LLM-appropriate work (semantic VWI retrieval, VWI judgement, review); every
structured/auditable decision (RO selection, crew assignment, coverage, rules,
final operational action) is plain Python.

| Component | Type | Role (as built) |
|---|---|---|
| **`procedure_retriever`** (`draad-procedure-retriever`) | Prompt agent, AI Search tool on `idx_bls_corpus` | Returns ranked VWI candidates with full content. **Only the rulebook** — no RO index. Has a **deterministic fallback**: if the LLM returns an empty array, `dispatch.py` calls Azure Search directly so the matcher always has VWIs. |
| **`dispatch_matcher`** (`draad-dispatch-matcher`) | Prompt agent, **no index** | Reads incident + VWI candidates + the **Python-prefiltered** ROs (passed inline in the prompt). Outputs **only** `vwis[]` (with `confidence`), `rationale`, and `citations`. **Does not pick RO/crew/coverage.** Never invents VWI/RO IDs. |
| **`rule_checker`** | Deterministic Python (`rules/evaluate_rules.py`) | Validates the proposal against hard BEI rules. Returns `[{check_id, pass, reason}]`. No LLM, no Workflow node. |
| **`dispatch_reviewer`** (`draad-dispatch-reviewer`) | Prompt agent (LLM-as-judge), no index | Reads original incident + matcher proposal + rule findings → `review_status ∈ {pass, revise, flagged_for_human_review}` + `feedback_for_matcher`. Revisions affect **only VWI selection**; structured fields are always re-derived. |
| **`qa_assistant`** (`draad-qa-assistant`) | Prompt agent, AI Search tool on `idx_bls_corpus` | Separate single-agent path for non-incident questions about the BLS rulebook. Routed to by `pipeline.py` when the input isn't an incident. |

### Pipeline (`dispatch.py`, streamed as SSE)

```text
[Lisa: NL incident text + structured anchors + crew pool]
        │
        ▼  pipeline.py classifies: incident? → dispatch.  else → qa_assistant.
        │
  1. procedure_retriever ──▶ VWI candidates  (LLM; deterministic Azure-Search fallback if empty)
        │
  2. PYTHON: _filter_raamopdrachten(postcode-prefix ∧ date-window ∧ available-crew)
        │
  3. dispatch_matcher ──▶ vwis[] + confidence + rationale + citations  (LLM ONLY picks VWIs)
        │
  4. PYTHON: _apply_deterministic_match()
        │      _pick_best_ro (max VWI overlap, tie-break smaller scope)
        │      _crew_for_ro, _coverage_status  → overwrite matched_ro / matched_crew / coverage
        │
  5. rule_checker ──▶ deterministic verdicts (evaluate_rules.py)
        │
  6. dispatch_reviewer ──▶ pass / revise / flagged_for_human_review
        │            ▲                         │
        │            └──── revise (max N=2) ───┘   (re-runs matcher; steps 4-5 re-derived)
        │
  7. PYTHON: compute operational_action, assemble final response
```

Because RO/crew/coverage are re-derived in Python on every iteration, a revision
can never regress the structured fields — it can only change the VWI set.

### Output schema

```json
{
  "incident_id": "INC-2026-05-20-0007",
  "vwis": [{"vwi_id": "E-67", "confidence": "confirmed"}],
  "matched_crew": "crew-001-K-de-Vries",
  "matched_raamopdracht_id": "RA-NHN-0101",
  "coverage_status": "covered | partial | not_covered | unknown",
  "review_status": "pass | revise | flagged_for_human_review",
  "operational_action": "dispatch_ok | wv_escalation_needed",
  "rationale": "<short prose>",
  "citations": { "vwi_refs": [], "raamopdracht_scope_excerpts": [], "bei_rule_refs": [] },
  "rule_verdicts": [], "review_findings": [], "revision_count": 0
}
```

`matched_crew`, `matched_raamopdracht_id`, `coverage_status` are **Python-derived**
(overwritten after the matcher). The matcher contributes `vwis`, `rationale`,
`citations`. The three status fields stay deliberately separate: `coverage_status`
(domain outcome, from VWI-overlap), `review_status` (workflow control, from
reviewer), `operational_action` (what Lisa does next, computed in Python).
`confidence` is a **2-value enum** (`confirmed` | `candidate`), not a float —
gives the Lab 5 evaluators a clean exact-match target. Required prerequisites →
`confirmed`; merely *possible* prerequisites stay in rationale prose, never in
`vwis[]`.

### `operational_action` is computed in Python (not the LLM)

After the loop, `dispatch.py` sets `wv_escalation_needed` if **any** of: a hard
rule failed, `review_status == flagged_for_human_review`, `coverage_status !=
covered`, or no RO matched. Otherwise `dispatch_ok`. This keeps the escalation
decision deterministic and auditable.

### Deterministic rules (`rules/evaluate_rules.py`)

1. **VWI existence** — every `vwi_id` exists in the catalogue.
2. **Coverage map** — every `confirmed` VWI appears in the matched RO's `covered_vwi_ids[]`.
3. **Temporal validity** — incident timestamp within RO `geldigheidsduur_start..end`.
4. **Geographic validity** — incident postcode in RO `geldigheidsgebied_postcodes[]`.
5. **Live-work permission** — any inherently live VWI (variant `-onder-sp` *or* a standalone live VWI like E-66) requires `permits_live_work: true`.
6. **Aanwijzing sufficiency** — wired in but trivially passes: all synth crew hold `WV-BLS` (hackathon simplification; per-VWI map is post-hackathon work).

### LLM judgement (`dispatch_reviewer`)

- **VWI selection appropriateness** — symptom vs cause.
- **Dangerous-situation handling** — smoke/smell/arcing → escalation unless explicitly covered.
- **Symptom vs cause discipline** — symptom-only → `candidate`; not itself an escalation trigger.
- **Escalation appropriateness** — when a hard rule failed.

### Indexes / storage

- **`idx_bls_corpus`** — the **only** AI Search index. Chunked BEI-BLS main +
  bijlage 06 + 10 curated VWI PDFs *with full content* (~193 chunks). Genuinely
  semantic prose. AI Search Basic tier (min for managed identity). Used by
  `procedure_retriever` and `qa_assistant`.
- **`crew.json` + `raamopdrachten.json`** — small structured tables (6 rows
  each). **Not indexed.** SQL-WHERE / set-overlap problems handled by Python in
  `dispatch.py` / `evaluate_rules.py`. **Source of record is Blob Storage**
  (container `crew-data`), loaded once per process via `BlobServiceClient` +
  `DefaultAzureCredential` (see §5). The local `data/` dir remains only as an
  offline fallback when the storage env vars are unset. `incidents.json` is the
  demo input set. *(Loader wiring lands in a follow-up change; the deterministic
  logic over the loaded JSON is unchanged.)*

> **Why no RO index?** Indexing the ROs is what made the matcher invent RO IDs
> (#6), and Foundry's one-index-per-tool limit (#7) blocks the briefing's
> "one agent, two indexes" design anyway. Python over 6 rows is simpler, exact,
> and free.

### Indexed VWI catalogue (10 entries)

E-04, E-11, E-22-onder-sp, E-22-sp-loos, E-40-sp-loos, E-48, E-60, E-66, E-67,
E-85. Every entry is exercised by ≥1 demo case (§4). All test data references
only these — anything else makes retrieval hallucinate or miss.

---

## 3. Deployment & participant model

This is how the workshop is actually run, and it shapes who runs which scripts
with which identity.

### Roles

| Step | Who | Tooling | What they do |
|---|---|---|---|
| **Infra deploy** | Client **infra team** (one operator) | **Azure CLI** (`setup/deploy.ps1`) | Provisions a single RG under the client's *engineering subscription*: **one Foundry account** with the shared infra (AI Search, Storage, App Insights, models, capability hosts), and **one Foundry project per participant**. |
| **Per-project setup** | Each **participant** | Setup scripts (`app/scripts/*`) run against **their own** Foundry project | Deploy agents, build indexes, upload data into the project they were assigned. |
| **Build the labs** | Each participant | Foundry portal + repo | Author the agents/workflow through Labs 1–5. |

### Key consequences (points 2–4)

- **One RG, one Foundry account, N projects.** The `-Prefix` / `ProjectCount`
  parameters in `deploy.ps1` exist precisely for this: the infra team creates one
  project per participant under the shared account. The **project prefix is the
  per-participant scoping mechanism.**
- **Capability hosts are provisioned by the infra team**, on the account and on
  every project (Agents kind). This is mandatory — without it the Agent Service
  returns the misleading "Project not found" (see
  [FAILURE_MODES.md](FAILURE_MODES.md) #19). It is **not** something participants
  do.
- **Only the infra team uses Azure CLI.** That is fine and by design — the CLI is
  only needed for the control-plane deploy. Participants do **not** need Azure
  CLI installed.
- **Participants authenticate via browser sign-on.** The setup scripts and the
  backend use `DefaultAzureCredential`, whose chain includes interactive /
  browser-based and VS Code / `az login` credentials. So a participant who has
  signed in through the browser (or the Foundry portal session) is picked up by
  `DefaultAzureCredential` without any CLI step. The RBAC the infra team grants on
  each project + the shared Search/Storage is what makes those tokens work.

### What the infra deploy provisions (per `deploy.ps1`)

Resource group → Foundry account (AIServices S0) → N projects → **Agents
capability hosts (account + each project)** → model deployments → AI Search
(Basic) → Storage (StorageV2) → App Insights → RBAC bindings (Foundry MI ↔
Search ↔ Storage) → Foundry connections (Search, App Insights) → `.env` mirrored
to `app/backend/.env`.

---

## 4. Demo scenarios (10 cases)

Synthetic pools: `crew.json` (6 crew, all `WV-BLS`), `raamopdrachten.json` (6
ROs), `incidents.json` (10 incidents, each with the full 6-crew shortlist).
**E-60 is deliberately in no RO's coverage** — it drives the partial-coverage
path in Case 1.

| # | Case | Expected VWIs | coverage | action | Tests |
|---|---|---|---|---|---|
| 1 | Aansluitkast brandlucht (lead) | E-67 cand, E-60 cand | partial | wv_escalation_needed | Danger soft-rule; symptom-vs-cause; partial coverage |
| 2 | Klant zonder stroom, zekering | E-85 confirmed | covered | dispatch_ok | Clean happy-path control |
| 3 | LS-groep onder spanning | E-22-onder-sp confirmed | covered | dispatch_ok | Live-work permission; matcher picks live variant; revise on rule 5 |
| 4 | Verbindingsmof, oorzaak onduidelijk | E-40-sp-loos candidate | covered | dispatch_ok | Variant uncertainty ≠ escalation; speculative prereqs stay in prose |
| 5 | Onder-spanning zekeringhouder | E-66 confirmed | covered | dispatch_ok | Live-work rule must be **VWI-agnostic** (E-66 ≠ suffix) |
| 6 | LS-netdeel uit bedrijf, RO verlopen | E-04 confirmed | covered (after revise) | dispatch_ok | **Revise loop** — temporal fail → re-pick crew |
| 7 | Postcode buiten gebied (Den Helder) | E-67 confirmed | not_covered | wv_escalation_needed | Geographic fail, no recovery → flagged_for_human_review |
| 8 | Kabelfout LS-groep, kabel onbekend | E-11 confirmed, E-22-sp-loos candidate | covered | dispatch_ok | Multi-VWI **mixed confidence** in one array |
| 9 | Toezicht bij graafwerk derden | E-48 confirmed | covered | dispatch_ok | Supervisory VWI — pick supervisor, not monteur |
| 10 | MS-asset op LS-storingslijn | `[]` (empty) | unknown | wv_escalation_needed | **No-fit refusal** — matcher must not invent; reviewer escalates → flagged_for_human_review |

**Lab 5 exact-match targets** per case: the set of `confirmed` VWIs +
`coverage_status` + `operational_action` (+ `review_status` where flagged).
Planted failure modes: partial coverage (1), temporal→revise-recovers (6),
geographic→exhaust→escalate (7), no-fit refusal (10).

---

## 5. Data strategy — Blob vs Index (answer to the open question)

**Decision (with Shenglin):** the JSON pools (`crew.json`, `raamopdrachten.json`,
`incidents.json`) do **not** need to be indexed. Upload them to Blob Storage,
expose them to `dispatch.py`, and keep the deterministic checking there.

**Is the deterministic check possible?** Yes — it already works exactly this way.
`dispatch.py` and `rules/evaluate_rules.py` already do postcode-prefix, validity-
window, coverage-map, and variant checks in-process over the loaded JSON. The
logic does not change at all; only the *source of the bytes* changes.

**Decided data source: Blob.** Crew + raamopdrachten live in Blob Storage
(container `crew-data`) and are loaded into the backend at runtime; the local
`data/` JSON stays only as an offline fallback. Most of the plumbing already
exists:

- `deploy.ps1` already creates the Storage account (`<prefix>blob`, StorageV2).
- `app/scripts/upload_crew_data.py` already uploads the three JSONs to a
  `crew-data` container using `BlobServiceClient` + `DefaultAzureCredential`.
- `app/backend/.env` already carries `AZURE_STORAGE_ACCOUNT_URL`,
  `AZURE_STORAGE_CREW_BLOB`, `AZURE_STORAGE_RO_BLOB`.

**Implementation checklist (follow-up change, not yet wired):**

1. **Switch the two loaders to Blob.** In `dispatch.py`, change `_load_crew()` /
   `_load_raamopdrachten()` (and the RO loader in `evaluate_rules.py`) to pull the
   blob via `BlobServiceClient(account_url=AZURE_STORAGE_ACCOUNT_URL,
   credential=DefaultAzureCredential())` → `download_blob().readall()` →
   `json.loads(...)`. Keep the existing `@lru_cache(maxsize=1)` so each blob is
   fetched once per process. Fall back to the local file when the env var is unset.
2. **Grant the backend identity `Storage Blob Data Reader`** on the storage
   account (the upload identity needs `…Data Contributor`). `deploy.ps1` already
   does Foundry↔Storage RBAC; extend it to grant the participant/app identity
   read on the container.

Until step 1 lands, the backend still reads the local `data/` dir — behaviour is
identical because the deterministic logic operates on the loaded JSON regardless
of source.

**Why this is the right call.** Crew and ROs are small structured tables —
SQL-WHERE / set-overlap problems, not semantic-relevance problems. Forcing an LLM
to "search" them is what caused the matcher to invent RO IDs
([FAILURE_MODES.md](FAILURE_MODES.md) #6) and ran into Foundry's one-index-per-tool
limit (#7). Blob + deterministic Python is both simpler and more correct: no index
schema, no agentic-retrieval cost, exact answers. Only the genuinely semantic BLS
prose (`idx_bls_corpus`) stays in AI Search.

**Trade-off to note for the demo narrative:** moving ROs out of search removes the
"multi-index agentic retrieval" showcase the briefing's Lab 1 was selling. That
tension and the options to recover it (connected agents for RO matching, or a
Workflow-YAML orchestration lab) are tracked in
[CAPABILITY_GAP.md](CAPABILITY_GAP.md).

---

## Cross-references

- [FAILURE_MODES.md](FAILURE_MODES.md) — deploy + agent failure catalog (#1–#19).
- [CAPABILITY_GAP.md](CAPABILITY_GAP.md) — working demo vs briefing-intent gap.
- Memory repo: `briefing-shenglin-evi-2026-05-20.md`, `use-case-explained.md`,
  `demo-scenarios.md`, `README.md`.
