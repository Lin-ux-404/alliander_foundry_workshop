# DRAAD — failure modes, fixes, and architecture
*Alliander dispatcher-assistant demo. Built on Azure AI Foundry Agent Service +*
*Azure AI Search + FastAPI/SSE + Next.js. Use case: Lisa (KCC dispatcher) gets a*
*free-text incident, system proposes RO+crew+coverage with rule + judge gates.*

---

## Part 1 — Failure modes (in deploy order)

Numbering follows discovery order. All twelve were hit during the workshop
build. Modes 1–8 are infrastructure / protocol bugs; 9–12 are *quality* bugs
exposed once the protocol bugs were gone.

### #1 — App Insights step hangs forever
**Where:** `setup/deploy.ps1`, step that runs `az monitor app-insights component create`.

**Symptom:** Terminal sits silent. No error, no prompt, no progress.

**Root cause (two stacked):**
1. Workspace-based App Insights requires the `AIWorkspacePreview` feature flag
   on the `microsoft.insights` provider. Without it, the ARM call hangs instead
   of failing.
2. First invocation of `az monitor app-insights` silently prompts to install the
   `application-insights` az CLI extension. The prompt is invisible inside the
   deploy script and looks identical to the hang.

**Fix (pre-flight before `deploy.ps1`):**
```powershell
az feature register --name AIWorkspacePreview --namespace microsoft.insights
az provider register --namespace microsoft.insights
az config set extension.use_dynamic_install=yes_without_prompt
```

**MS Learn verification:** Workspace-based App Insights migration docs confirm
the `AIWorkspacePreview` feature flag requirement for new component creation
in subscriptions that haven't opted in.

---

### #2 — Foundry connections silently fail with HTTP 415 (CRITICAL)
**Where:** `setup/deploy.ps1` section 9, the two `az rest --method put` calls
for `connections/search-connection` and `connections/appinsights-connection`.

**Symptom:** Script exits green. Resources exist. `.env` is correct. But
`deploy_agents.py` then crashes with
`Connection search-connection can't be found in this workspace.`

**Root cause (two stacked):**
1. Both PUTs are missing the `--headers "Content-Type=application/json"` flag.
   ARM rejects with **HTTP 415 Unsupported Media Type**. The script's other
   PUTs (project create, section 3) *do* include the header — proves it's a
   localised bug, not the ARM API.
2. Both calls end with `2>$null --output none`, swallowing the 415. The next
   line prints `✅ Search connection: search-connection` unconditionally.

**Manual unblock:**
```powershell
$body = @{ properties = @{ category = "CognitiveSearch"; target = "https://<search>.search.windows.net"; authType = "AAD" } } | ConvertTo-Json -Depth 5
$body | Out-File -Encoding utf8 conn.json
az rest --method put `
    --url "https://management.azure.com$projResId/connections/search-connection?api-version=2025-04-01-preview" `
    --headers "Content-Type=application/json" `
    --body "@conn.json"
```

**Lesson:** Never combine `--output none` with `2>$null` in a deploy script —
you become blind to ARM rejections.

---

### #3 — `.env` override gotcha (two `.env` files)
**Symptom:** Script-side tools (`scripts/*.py`) see the right model, but
`uvicorn` running in `app/backend/` sees a stale model — or vice versa.

**Root cause:** Two consumers, two `.env` locations.
- Repo root `.env` → loaded by `app/scripts/shared.py` for deploy/index scripts.
- `app/backend/.env` → loaded by FastAPI when uvicorn starts in `app/backend/`.

`deploy.ps1` only writes the root one.

**Fix:**
```powershell
Copy-Item .\.env .\app\backend\.env -Force
```
After every `deploy.ps1` re-run.

---

### #4 — `scripts/deploy_agents.py` import bug
**Symptom:** `ModuleNotFoundError: No module named 'backend'`.

**Root cause:** The script does `from backend.agents import ...` but only puts
`app/backend/` on `sys.path` — so `backend` is not a discoverable top-level
package.

**Fix (run from `app/` instead of `app/backend/`):**
```powershell
cd app
$env:PYTHONPATH = "."
python scripts\deploy_agents.py
```

---

### #5 — Foundry project MI has no RBAC on Search (CRITICAL, 3-part)
**Symptom (frontend):**
```
Fout: <FoundryAgentChatClient> service failed to complete the prompt:
Access denied. Check your permissions or managed identity access to the search service.
```
Every pipeline step that uses `AzureAISearchTool` fails. Pipeline keeps
running because tool errors don't crash the agent — they return as content.

**Root cause (THREE stacked):**
1. **Search service is created with `apiKeyOnly` auth mode.** It will reject
   AAD tokens outright with 403, regardless of RBAC.
2. **The Foundry project has its own system-assigned MI** — distinct from the
   Foundry account MI. The two have different `principalId`s. The Azure AI
   Search tool authenticates as the **project** MI.
3. Neither MI has any role assignment on the Search service.

**Fix (all three required):**
```powershell
# 1. Allow AAD on the search service (keep keys too, in mixed mode)
az search service update --name alliander-draad-search -g alliander-draad-rg `
    --auth-options aadOrApiKey --aad-auth-failure-mode http403

# 2. Get the PROJECT MI (NOT the account MI)
$projMi = az rest --method get `
    --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/alliander-draad-rg/providers/Microsoft.CognitiveServices/accounts/alliander-draad-foundry/projects/alliander-draad-project?api-version=2025-04-01-preview" `
    --query "identity.principalId" -o tsv

# 3. Grant project MI roles on Search
$searchId = az search service show --name alliander-draad-search -g alliander-draad-rg --query id -o tsv
az role assignment create --assignee-object-id $projMi --assignee-principal-type ServicePrincipal `
    --role "Search Index Data Reader" --scope $searchId
az role assignment create --assignee-object-id $projMi --assignee-principal-type ServicePrincipal `
    --role "Search Service Contributor" --scope $searchId
```

**Trap:** I first granted roles to the *account* MI
(`az cognitiveservices account show ... identity.principalId`) — wrong
identity. Connection-based AAD auth uses the project MI.

**Diagnosis hint:**
`az search service show ... --query authOptions` — if it shows `apiKeyOnly`,
AAD won't work no matter what RBAC says.

**RBAC propagation:** 2–10 min. If still 403 after both fixes,
also redeploy agents (`python scripts/deploy_agents.py`).

**MS Learn verification:** Foundry "Connect an Azure AI Search index to
Foundry agents" docs explicitly say *"Assign the Search Index Data Contributor
role to the managed identity of your project."* Docs recommend `Contributor`;
`Reader` works for query-only.

---

### #6 — Matcher invents `RA-unknown` (CRITICAL prompt bug)
**Symptom:** Pipeline runs end-to-end. Retriever finds VWIs. Matcher's
AzureAISearchTool returns RO hits (matcher even cites the RO prose). But
`matched_raamopdracht_id` comes back as `"RA-unknown"` or `null`, so BLS-R02 /
R03 / R04 all fail and reviewer flags every case for human review — even the
happy path.

**Root cause:** `idx_raamopdrachten`'s semantic configuration prioritised
`bestemd_voor` (title) and the `omschrijving_*` fields (content). The
structured `raamopdracht_id` field (e.g. `"RA-NHN-0101"`) wasn't in the
semantic prioritization, so the LLM tool surfaced prose but didn't surface
the ID. The model invented `"RA-unknown"` rather than admit it didn't see one.

**Fix (prompt-side, since reindex would have been more invasive):**
Add to matcher prompt:
```
Each search hit document has a "raamopdracht_id" field with a value like
"RA-NHN-0101". You MUST copy this exact value verbatim into matched_raamopdracht_id.
NEVER use placeholders like "RA-unknown" — if the field is missing, set null.
```
Then redeploy → new agent version.

**Why this isn't the right long-term fix:** This was eventually superseded by
the architectural refactor (Part 3 below) which moves RO selection out of the
LLM entirely. But it bought us a working demo run.

---

### #7 — Matcher can't see `idx_crew` (Foundry hard limit)
**Symptom:** Even on happy-path runs, `matched_crew` is null or "all available
crew" rather than a real `crew_id`.

**Root cause:** Matcher only had `idx_raamopdrachten` as a tool index.
Naive fix is to add `idx_crew`. But:
- Two `AzureAISearchTool`s on the same agent → `400 Duplicate tool argument name: 'azure_ai_search'`.
- One tool with two indexes → `400 maxItems: Value should have at most 1 items`.

**MS Learn verification (`learn.microsoft.com/azure/foundry/agents/how-to/tools/ai-search#limitations`):**
> "The Azure AI Search tool can only target one index. To use multiple indexes,
> consider using **connected agents**, each with a configured index."

**Fix:** Don't use a second search tool. Do crew lookup deterministically in
Python (`workflows/dispatch.py` → `_crew_for_ro`). The `crew.json` doc has
`raamopdracht_ids: [...]` — a `for c in crew: ra_id in c["raamopdracht_ids"]`
is one line and 100% deterministic.

---

### #8 — Retriever prompt field names don't match index schema
**Symptom:** `Found 0 VWI candidate(s)` even though `idx_bls_corpus` is
populated and returns hits when queried directly via the Search SDK.

**Root cause:** Retriever prompt told the LLM the index fields were `vwi_id`
and `source_doc`. Real fields are `vwi_code` and `source_file`. The LLM
searched, didn't find a `vwi_id` field on the hits, and returned an empty
`vwi_candidates: []`.

**Fix:** In retriever prompt, document the actual schema explicitly and
instruct the LLM to copy `vwi_code → vwi_id`, `source_file → source_doc`.

**General rule:** Always verify prompt-side field references against
`SearchIndexClient.get_index(name).fields` before deploying any retrieval
agent. Same risk for any tool-using agent.

---

### #9 — Reviewer demands revise on happy-path AND matcher drops fields on revise
**Symptom:** All 5 hard rules pass. Matcher proposes RA-NHN-0101 with
`E-67/E-85/E-60`. Reviewer fires `revise` over a soft scope concern (E-60 is
arguably over-eager). On revision, matcher loses the RO match — drops to
`RA-unknown` — coverage drops, ends `flagged_for_human_review`. **Catastrophic
regression on the happy path.**

**Root cause (two coupled LLM-judgement bugs):**
1. Reviewer decision rules were "all pass → pass, soft fail → revise" — too
   aggressive. A soft scope concern shouldn't override a 5/5 hard-rule pass.
2. Matcher revise loop just said "address each critique" — LLM reran search,
   didn't reuse `matched_raamopdracht_id`, and when search result order
   shifted between calls the model couldn't reidentify the prior RO.

**Fix (both deployed):**
- `agents/reviewer.py` DECISION RULES: explicit priority order. Soft scope
  concerns alone with all hard rules passing → `pass` (concern recorded in
  findings). Only `revise` for confirmed-vs-candidate confidence misfit or
  dangerous-signal mismatch.
- `agents/matcher.py` REVISE LOOP: explicit "preserve previous proposal
  fields unless feedback says otherwise".
- `workflows/dispatch.py::_format_matcher_input`: passes the previous
  proposal JSON back to the matcher on revision so the LLM has a fixed point
  to anchor on, not just free-form critique.

**Lesson:** LLM-as-judge with vague "be skeptical" + free-form revise feedback
loops back into the actor → infinite-regression of small judgement drifts.
Pin the judge's decision tree with strict ordering, and feed the prior
structured proposal back on revision.

---

### #10 — Matcher selects only an "escalation" VWI without the work-execution VWI
**Symptom:** Case 1 (brandlucht meterkast) retest — retriever returns 5
candidates (E-67, E-85, E-60, E-04, E-66) but matcher picks ONLY `E-60`
("opheffen gevaarlijke situatie"). E-60 isn't in any RO's `covered_vwi_ids`
by design (escalation-only). Result: no RO matches → `not_covered` →
`flagged_for_human_review`. False negative on happy-ish path.

**Root cause:** Matcher prompt was overcorrected toward conservatism. The
LLM read "only confirmed evidence" too strictly and dropped the
work-execution VWIs that would actually have produced a coverable match.

**Fix:** Matcher prompt now has explicit inclusivity rule + worked examples:
> "Typical incidents need 2-4 VWIs, not 1. Burning smell at meterkast →
> E-67 (service cabinet fault) + E-60 (dangerous situation). Suspected
> blown fuse → E-67 + E-85. Group out / groep uit onder spanning →
> E-22-onder-sp."

Plus reviewer was told `operational_action` and `coverage_status` will be
null in its input (Python computes them downstream), so don't fail the
`escalation_appropriateness` criterion just because those fields are null.

---

### #11 — VWI ID schema mismatch: corpus uses bare codes, RO catalog uses variants
**Symptom:** Case 3 (`LS-groep onder spanning` in Alkmaar) — pipeline gets
to matcher cleanly, matcher emits `vwis: [E-22, E-22]`, Python set-overlap
with RO `covered_vwi_ids: [E-22-onder-sp, E-66, E-67, E-85]` is empty →
`matched_raamopdracht_id: null` → 3/5 rules fail → escalate.

**Root cause:** `app/scripts/index_documents.py` regex was `\bE-\d{2}\b`,
which only captures the base code and strips the `-onder-sp` / `-sp-loos`
variant suffix from the PDF filename. The corpus is **literally unable** to
distinguish `E-22-onder-sp` (live work) from `E-22-sp-loos` (de-energised),
even though they're separate VWIs with different live-work rules
(BLS-R05 hinges on this distinction). The RO catalog uses the full IDs.
Same trap exists for E-23, E-40, E-41, E-42.

**Fix (two-part):**
1. Indexer regex → `E[-_]\d{2}(?:[-_](?:onder[-_]sp|sp[-_]loos))?` with a
   `_normalize_vwi_code` helper that produces canonical `E-NN-suffix`.
   **Requires reindex** (`python app/scripts/index_documents.py`).
2. Defensive `_vwi_matches` in `dispatch.py`: bare base (`E-22`) prefix-matches
   any qualified covered ID (`E-22-onder-sp`). Safety net only — it cannot
   distinguish live vs de-energised, so BLS-R05 may misfire. Reindex is the
   real fix.

---

### #12 — Matcher overconfident on out-of-scope incidents (no-fit refusal)
**Symptom:** Case 10 (MS-ringstoring misrouted to LS-storingslijn, postcode
1701 is caller's not fault's) — matcher picks `E-67 + E-85` (LS aansluitkast
VWIs), Python finds RA-NHN-0101 in postcode 1701, coverage = covered,
reviewer rubber-stamps it, **Dispatch OK on an MS incident the system has no
business handling.** Expected: `vwis=[]`, `wv_escalation_needed`,
`flagged_for_human_review`.

**Root cause:** Matcher prompt's inclusivity push (fix #10) had no upper
bound. When retriever returned LS candidates (it always will — corpus is
LS-only), the matcher dutifully picked the most plausible-looking pair
without checking whether the incident actually belonged in the LS corpus.
Pipeline is deterministic enough that once matcher commits to LS VWIs,
the downstream is all green. Also: caller-postcode-as-evidence trap — the
text literally said "postcode 1701 is van de beller, niet van de storing",
which the matcher ignored.

**Fix:** Add explicit REFUSE TO FIT rules to matcher prompt:
- Voltage class mismatch (MS / middenspanning / 10 kV / ringstoring / RMU /
  trafohuis / verdeelstation) → return `vwis: []`.
- Asset class mismatch (gas / water / telecom / MS-asset) → return `[]`.
- Misrouting acknowledged in text → return `[]` even if LS keyword present.
- Caller postcode flagged as not the fault location → refuse, don't anchor
  on the geographic hit.

Rationale must name the refusal trigger; citations stay empty.

Deterministic side already handles `vwis=[]`: `_pick_best_ro` returns
`None, set()`, `_coverage_status` returns `unknown`, final assembly drops
to `wv_escalation_needed` + `flagged_for_human_review`.

**Lesson:** Inclusivity guidance for an LLM needs a paired exclusivity rule,
or the model will treat "be inclusive" as "always commit". A "refuse" path
with concrete triggers is required whenever the retriever can't say
"none of the above" itself (it can't — it's a search-tool agent and search
always returns top-k).

---

## Part 2 — Code changes summary

### `setup/deploy.ps1`
- (Not yet patched; documented as #2/#5 above — user is running fixes manually
  after each deploy. Sustainable fix = add Content-Type to both `az rest`
  PUTs, drop `--output none 2>$null`, and add the project-MI + RBAC + AAD
  block.)

### `app/scripts/deploy_agents.py`
- Fix for **#4**: import path / sys.path layout.
- Fix for **#7**: `_search_tools` collapses to one tool / one index per agent;
  returns `[]` when an agent has no indexes (matcher post-refactor).

### `app/scripts/index_documents.py`
- Fix for **#11**: regex captures variant suffix; `_normalize_vwi_code`
  produces canonical IDs. **Reindex required.**

### `app/backend/agents/retriever.py` (v3)
- Fix for **#8**: documents real index schema; maps `vwi_code → vwi_id`,
  `source_file → source_doc`. Strengthened "cast a WIDE net" guidance.

### `app/backend/agents/matcher.py` (v8)
- Fix for **#6**: "you do NOT pick RO/crew/coverage; leave them null. Python
  computes them. You only pick VWIs + confidence + rationale + citations."
- `MATCHER_INDEXES = []` — no search tool at all (consequence of refactor).
- Fix for **#9**: revise loop preserves previous proposal fields.
- Fix for **#10**: explicit inclusivity rule + worked examples for typical
  VWI combinations.
- Fix for **#12**: REFUSE TO FIT rules — voltage/asset-class mismatch,
  misrouting acknowledged, caller-postcode-not-fault-postcode → `vwis: []`.

### `app/backend/agents/reviewer.py` (v3)
- Fix for **#9**: strict decision-rule priority; soft scope concerns alone
  with all rules passing → pass.
- Fix for **#10**: explicit "operational_action and coverage_status may be
  null in your input — that's by design, Python sets them downstream."

### `app/backend/workflows/dispatch.py` (the architectural refactor)
- New: `_load_raamopdrachten`, `_load_crew` (lru_cache).
- New: `_filter_raamopdrachten(postcode, timestamp, available_crew)` — pure
  Python filter by postcode prefix + date window, optionally further by
  crew → RO array. Replaces the failed attempt to make an LLM do this.
- New: `_pick_best_ro(filtered_ros, selected_vwi_ids)` — max VWI overlap;
  tie-break by smaller `covered_vwi_ids` (more specific RO wins). Fix for #11
  uses `_vwi_matches` so a bare base code still prefix-matches.
- New: `_coverage_status` — pure set math: `covered | partial | not_covered | unknown`.
- New: `_crew_for_ro` — one-liner lookup by RA-id in `crew.json`'s
  `raamopdracht_ids` array. Replaces the impossible #7 setup.
- New: `_apply_deterministic_match` — overwrites RO/crew/coverage on matcher
  output, called after every matcher invocation (including revisions) so
  revisions cannot regress.
- New: `_fallback_retrieve_vwis(query, top=8)` — direct Azure Search SDK call
  against `idx_bls_corpus` when the LLM retriever returns empty (gpt-5.4-mini
  is flaky and sometimes returns `[]` despite hits existing). Same output
  shape as the LLM retriever.
- New: `_format_matcher_input` passes filtered ROs + previous_proposal (on
  revision) as structured input.
- New: final assembly derives `operational_action` from
  `coverage == "covered" AND no hard-rule failure AND review_status != flagged AND RO matched`.

---

## Part 3 — What's LLM vs what's deterministic Python

| Step | Owner | Why |
|---|---|---|
| Incident → VWI candidates | LLM (`procedure_retriever`) + idx_bls_corpus | Genuine semantic relevance across 193 BLS chunks. |
| Empty-retriever fallback | Python (`_fallback_retrieve_vwis`) | gpt-5.4-mini returns `[]` ~10% of the time despite hits — bypass the LLM. |
| **Filter ROs by postcode + date** | **Python (`_filter_raamopdrachten`)** | Pure set filter over 6 rows. The spec literally says "filter to postcode 1701" — that's a `WHERE`, not a semantic search. |
| VWI selection from candidates | LLM (`dispatch_matcher`) | Symptom-vs-cause judgement, work-type pairing (E-67+E-60 etc). |
| Confidence per VWI (confirmed / candidate) | LLM (`dispatch_matcher`) | Same — text interpretation. |
| Rationale + verbatim citations | LLM (`dispatch_matcher`) | NL prose generation, quote selection. |
| **Pick winning RO** | **Python (`_pick_best_ro`)** | Set overlap with tie-break by scope size. Deterministic; LLM was inventing IDs (#6). |
| **Crew assignment** | **Python (`_crew_for_ro`)** | One-line lookup. LLM couldn't even see `idx_crew` (#7). |
| **`coverage_status`** | **Python (`_coverage_status`)** | Pure subset math. |
| BEI-BLS hard-rule check (BLS-R01..R05) | Python (`rules/evaluate_rules.py`) | Always was deterministic. |
| Reviewer judgement (danger signals, escalation appropriateness, etc.) | LLM (`dispatch_reviewer`) | Soft judgement — but operates over the deterministic structured fields. |
| **`operational_action` enum** | **Python (final assembly)** | Boolean logic over four signals. |

**Rule of thumb established:** *if you can write it as a SQL WHERE or a set
operation over <100 rows, do it in Python; the LLM will eventually break it.*
The LLM keeps the work that genuinely requires reading and judgement:
matching free-text NL incidents to VWI candidates, picking subsets with
confidence, prose rationale, and reviewer judgement over structured fields.

---

## Resource naming (sub MCAPS-Hybrid-REQ-142317-2026-t-shireendan)
- RG: `alliander-draad-rg` (swedencentral)
- Foundry account: `alliander-draad-foundry`
- Foundry project: `alliander-draad-project`
- Project MI principalId: `cb2d59af-9ff1-4cde-9a16-ec2982587b41`
- Search: `alliander-draad-search` (auth: `aadOrApiKey`, mode `http403`)
- Storage: `allianderdraadblob`
- App Insights: `allianderdraadinsights`
- Foundry connections: `search-connection`, `appinsights-connection`
- Indexes: `idx_bls_corpus` (193 chunks; used by retriever + qa),
  `idx_raamopdrachten` (6 docs, **no longer used by agents post-refactor**),
  `idx_crew` (6 docs, **no longer used by agents post-refactor**).
- Deployed models: `gpt-5.4-mini`, `text-embedding-ada-002`, `gpt-4.1-mini`
  (NOT `gpt-4.1`).
- Agent versions after all fixes:
  - `draad-procedure-retriever` v3 (idx_bls_corpus)
  - `draad-dispatch-matcher` v8 (no indexes)
  - `draad-dispatch-reviewer` v3 (no indexes)
  - `draad-qa-assistant` v1 (idx_bls_corpus)
