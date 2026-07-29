# DRAAD — failure modes, fixes, and architecture
*Alliander dispatcher-assistant demo. Built on Azure AI Foundry Agent Service +*
*Azure AI Search + FastAPI/SSE + Next.js. Use case: Lisa (KCC dispatcher) gets a*
*free-text incident, system proposes RO+crew+coverage with rule + judge gates.*

> **Historical engineering log.** It explains previously observed defects, but
> embedded SDK versions, role names, agent versions and preview API commands are
> not the current setup contract. Use `setup/README.md`,
> `docs/RESEARCH_BASELINE.md` and `requirements.txt` for current instructions.
> Reproduce a symptom before applying an older workaround.

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

### #13 — `deploy.ps1` saved as UTF-8 **without BOM** → parse error under Windows PowerShell 5.1
**Where:** `setup/deploy.ps1` line 55 (`Write-Step` helper, which contains a
`🔹` emoji), but it breaks the *whole file* at parse time.

**Symptom:**
```
function Write-Step([string]$msg) { Write-Host "`nðŸ”¹ $msg" ...
Missing closing '}' in statement block or type definition.
```
The script never runs a single line. Note the mangled emoji `ðŸ”¹` — that's the
tell.

**Root cause:** The file contains multi-byte UTF-8 (emoji in the `Write-*`
helpers and the `─` box-drawing section headers). Windows PowerShell 5.1
(`powershell.exe`, the default shell on a fresh Windows box) assumes the
**system ANSI codepage (Windows-1252)** for files with no BOM. It decodes the
emoji bytes as several Latin-1 chars, one of which collides with quoting and
the parser loses brace tracking. It only ever "worked" before because it was
run under **PowerShell 7** (`pwsh`), which defaults to UTF-8.

**Fix:** Save `deploy.ps1` as **UTF-8 with BOM** (`EF BB BF`). 5.1 then detects
UTF-8 correctly and 7 still reads it fine.
```powershell
$p = (Resolve-Path 'setup/deploy.ps1').Path
$t = [System.IO.File]::ReadAllText($p)
[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding $true))
```

**Trap:** Most editors and several edit tools re-save without a BOM. After any
programmatic edit, re-stamp the BOM before running under 5.1. (Alternatively,
strip all non-ASCII from the script — but the BOM is less invasive.)

**Verification:** first 3 bytes must be `EF BB BF`.

---

### #14 — Existence probes crash under `$ErrorActionPreference = "Stop"` in PS 5.1
**Where:** every "does this resource already exist?" check —
`az ... show ... 2>$null`, `az ... list ... 2>$null` (Foundry, project,
deployments, search, storage, app-insights, role assignments, connections).

**Symptom (first hit, fresh RG):**
```
🔹 AI Foundry account: alliander-draad-foundry
az : ERROR: (ResourceNotFound) The Resource '...alliander-draad-foundry' ... was not found.
... NativeCommandError
EXIT=1
```
The script dies on the *existence check itself* — before it can act on "not
found = create it".

**Root cause:** When a resource is absent, `az ... show` exits non-zero **and**
writes to stderr. In Windows PowerShell 5.1, a native command that writes to
stderr while `$ErrorActionPreference = "Stop"` is in effect raises a
**terminating `NativeCommandError`** — and the `2>$null` redirect does not
reliably suppress it. (PowerShell 7 does not do this, which is why it worked
before.) On a *fresh* deploy every existence check returns "not found", so the
script can't get past the first probe.

**Fix:** Route all existence/probe reads through a helper that drops the Stop
preference in its local scope and returns `$null` on non-zero exit:
```powershell
function Get-AzOrNull {
    param([Parameter(ValueFromRemainingArguments)] $Args_)
    $ErrorActionPreference = 'SilentlyContinue'
    $out = az @Args_ 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out
}
```
Then `$x = Get-AzOrNull <service> show ...` instead of `az <service> show ... 2>$null`.
`Invoke-Az` (which *should* throw on failure for create/update calls) is left
as-is.

**Lesson:** "Probe" reads and "must-succeed" calls need different error
semantics. Don't run idempotency checks under a blanket `Stop` in 5.1.

---

### #15 — Cognitive Services account is **soft-deleted**, blocks same-name redeploy
**Where:** `setup/deploy.ps1` section 2, after deleting the RG and re-running.

**Symptom:**
```
🔹 AI Foundry account: alliander-draad-foundry
az : ERROR: (FlagMustBeSetForRestore) An existing resource ... has been
soft-deleted. To restore ... specify 'restore' to be 'true' ... If you don't
want to restore ... please purge it first.
EXIT=1
```

**Root cause:** Deleting the resource group does **not** hard-delete an Azure
AI Services (`Microsoft.CognitiveServices`) account — it goes to a 48-hour
**soft-delete** state. The name stays reserved, so `account create` with the
same name fails until the ghost is purged (or restored).

**Fix (added to the script, runs in the `else` branch before create):**
```powershell
$deleted = Get-AzOrNull cognitiveservices account list-deleted `
    --query "[?name=='$foundryName']" --output json | ConvertFrom-Json
if ($deleted -and $deleted.Count -gt 0) {
    Invoke-Az cognitiveservices account purge `
        --location $Location --resource-group $rgName --name $foundryName
}
```
Manual one-off:
```powershell
az cognitiveservices account purge --location swedencentral `
    --resource-group alliander-draad-rg --name alliander-draad-foundry
```

**Lesson:** Any teardown/redeploy cycle that reuses names must account for
soft-delete (Cognitive Services, Key Vault, API Management, etc.). "Delete the
RG and redeploy" is *not* a clean slate for these resource types.

---

### #16 — `Invoke-Az` crashes on a harmless `az` **WARNING** under PS 5.1
**Where:** `setup/deploy.ps1`, the `Invoke-Az` helper (`$result = az @Args_ 2>&1`),
first triggered by Storage account creation.

**Symptom:**
```
🔹 Storage account: allianderdraadblob
az : WARNING: The --min-tls-version argument values TLS1_0 and TLS1_1
have been retired ...
+     $result = az @Args_ 2>&1
    ... NativeCommandError
EXIT=1
```
The storage account *was* actually created — the script died on a **warning**,
not an error.

**Root cause:** Same Windows PowerShell 5.1 quirk as #14, but in the
*must-succeed* path. `Invoke-Az` merges stderr into the pipeline with `2>&1`
while the script-level `$ErrorActionPreference = "Stop"` is in effect. In 5.1,
**any** native command that writes to stderr under `Stop` raises a terminating
`NativeCommandError` — and `az` writes WARNINGs (deprecation notices, preview
flags, etc.) to stderr all the time. So a successful command with a warning
banner crashes the script.

**Fix:** Localize the error preference to `Continue` inside `Invoke-Az` and
decide success/failure purely from `$LASTEXITCODE`:
```powershell
function Invoke-Az {
    param([Parameter(ValueFromRemainingArguments)] $Args_)
    $ErrorActionPreference = 'Continue'   # don't let stderr warnings throw
    $result = az @Args_ 2>&1
    if ($LASTEXITCODE -ne 0) { throw "az command failed: $result" }
    return $result
}
```

**Lesson:** stderr ≠ failure for `az`. Gate on the exit code, never on the
presence of stderr output. (#14 = same root cause on the probe path; #16 =
the create/update path. Both stem from `Stop` + native stderr in PS 5.1.)

---

### #17 — AppInsights Foundry connection rejects `authType = "AAD"`
**Where:** `setup/deploy.ps1`, section 9 (Foundry project connections), the
`$aiConnBody` PUT for the `appinsights-connection`.

**Symptom:**
```
ERROR: AuthType for AppInsights Connection can only be ApiKey
... "code":"ValidationError" ... "statusCode":400
```
The Search connection (category `CognitiveSearch`) creates fine with
`authType = "AAD"`, so the same shape was used for AppInsights — but the
AppInsights category has **no AAD code path** and returns HTTP 400.

**Root cause:** Foundry connection categories don't share auth capabilities.
`CognitiveSearch` supports managed-identity (AAD) auth; `AppInsights` only
supports `ApiKey`, where the "key" is the App Insights **connection string**.

**Fix:** Build the AppInsights connection body with ApiKey auth, the resource
ID as `target`, and the connection string as the credential key:
```powershell
$aiResourceId = $aiJson.id   # captured right after the component show
...
$aiConnBody = @{
    properties = @{
        category    = "AppInsights"
        target      = $aiResourceId
        authType    = "ApiKey"
        credentials = @{ key = $aiConnectionString }
    }
} | ConvertTo-Json -Depth 5
```

**Lesson:** Connection `authType` is per-category, not global. Check each
category's supported auth modes; don't assume AAD works everywhere just
because it worked for Search.

---

### #18 — Agent `create_version` returns "Project not found" after same-name recreate
**Where:** `app/scripts/deploy_agents.py`, `project.agents.create_version(...)`,
run against a project that was just deleted and recreated with the **same name**.

**Symptom:**
```
azure.core.exceptions.ResourceNotFoundError: (NotFound) Project not found
Code: NotFound
Message: Project not found
```
…even though:
- the control-plane project shows `provisioningState = "Succeeded"`,
- `project.connections.get(...)` succeeds, and
- `project.agents.list()` / `project.agents.get(name)` return the agents with
  their full latest definitions.

**Root cause:** The Foundry **Agent service** keys agents by the stable account
host + project *name*. After an RG delete + same-name recreate, the agent
service's **read** path still serves the previously registered agents (cache /
retained registration), but its **write** path (`create_version`) rejects new
versions until the recreated project resource is re-registered with the agent
backend. Control-plane "Succeeded" and the data-plane connections route both
register faster than the agent write path, so there's a window where reads work
but writes 404 with "Project not found".

**Impact / handling:**
- This is an Azure-side eventual-consistency lag, **not** a bug in
  `deploy_agents.py`. The script is correct.
- Because the agent service retained the prior registrations, the agents remain
  present at their correct versions (matcher v8, retriever v3, reviewer v3,
  qa v1) pointing to the same-named indexes (`idx_bls_corpus`), so the demo is
  fully functional even while `create_version` is temporarily blocked.
- Re-running `deploy_agents.py` succeeds once the agent write path catches up
  (typically within ~15–30 min of the recreate). No code change required.

**Lesson:** For soft-delete resource types, "reads work" does not imply "writes
work" immediately after a same-name recreate. Treat agent (re)deployment as
eventually-consistent; verify end state with `agents.list()` / `agents.get()`
rather than assuming a failed `create_version` means nothing was deployed.

> **Correction (see #19):** On a *genuinely clean* account (RG deleted **and**
> the soft-deleted Foundry account purged), the "Project not found" error is
> **not** eventual-consistency lag — it is a hard, permanent failure caused by
> the missing **Agents capability host**. The same-name redeploys that
> "recovered on their own" did so because a capability host survived from a
> prior portal session. A from-scratch deploy never gets one unless it is
> created explicitly. #19 is the real root cause and fix.

---

### #19 — "Project not found" on a clean deploy: missing capability host + SDK `connections.get` 404
**Where:** `app/scripts/deploy_agents.py` (`project.connections.get(...)` and
`project.agents.create_version(...)`) and `setup/deploy.ps1` (no capability
host was ever created).

**Symptom:** After a fully clean redeploy (RG deleted, soft-deleted Foundry
account **purged**, fresh infra with brand-new managed identities), agent
deployment fails permanently:
```
azure.core.exceptions.ResourceNotFoundError: (NotFound) Project not found
```
Unlike #18, this never self-heals — retried 10+ times over a long window with
no change.

**Diagnosis (two distinct problems):**

1. **Missing Agents capability host (the real root cause).** The Foundry Agent
   Service requires an `Agents`-kind **capability host** on *both* the account
   and the project. On a clean account both were absent:
   ```
   az rest GET .../capabilityHosts?api-version=2025-04-01-preview  →  {"value": []}
   ```
   `setup/deploy.ps1` never created them (`grep capabilityHost` → no matches).
   Same-name redeploys appeared to "recover" only because a capability host
   left over from an earlier portal session was still attached to the surviving
   (soft-deleted-then-restored) account. A purged account has none.

2. **SDK `connections.get(name)` 404s under api-version `v1` (masking bug).**
   `azure-ai-projects` 2.1.0 defaults to `api_version="v1"`. Even after the
   capability hosts existed and the data plane was reachable
   (`GET .../assistants?api-version=v1` → empty list, OK), the **singular**
   connection fetch failed while the **list** succeeded:
   - `GET .../connections/search-connection?api-version=v1` → **404**
   - `GET .../connections?api-version=v1` (list) → **OK, 2 connections**

   The SDK surfaces that 404 as the same misleading `"Project not found"`,
   making it look like problem #1 was still unresolved.

**Fix (both parts):**

- **`setup/deploy.ps1` — create capability hosts (new section 3b).** After the
  projects are created and before agent deployment, PUT an `Agents` capability
  host on the account, poll to `Succeeded`, then do the same for each project:
  ```powershell
  $body = '{"properties":{"capabilityHostKind":"Agents"}}'
  az rest --method put `
    --url ".../capabilityHosts/agentshost?api-version=2025-04-01-preview" `
    --body "@$f" --headers "Content-Type=application/json"
  # poll properties.provisioningState until "Succeeded" (account first, then project)
  ```
  Made idempotent via a `Get-AzOrNull` probe that skips when the host already
  reports `Succeeded`.

- **`app/scripts/deploy_agents.py` — resolve the connection via `list()`.**
  Replace the broken singular `get` with a list-and-match:
  ```python
  conn_id = None
  for c in project.connections.list():
      if c.name == SEARCH_CONNECTION_NAME:
          conn_id = c.id
          break
  ```

**Result:** With the capability hosts present and the connection resolved via
`list()`, all four agents deploy cleanly (`EXIT=0`): retriever v3, matcher v8,
reviewer v3, qa v1.

**Lesson:**
- The Foundry Agent Service is **not** automatically usable just because the
  project provisioning state is `Succeeded`; it needs explicit account- and
  project-level `Agents` capability hosts that an RG delete destroys. Bake this
  into the IaC, don't rely on portal side-effects.
- A misleading SDK error (`"Project not found"`) can hide a much narrower cause.
  Probe the raw data plane (assistants/connections list endpoints) to localise
  the failure before assuming the project itself is missing — here the project
  was always reachable; only the singular `connections.get` route was broken.
- Always validate reproducibility from a **purged** account, not just an RG
  delete; soft-delete + restore can mask missing prerequisites.

---

### #20 — `create_version` 404s transiently on a freshly provisioned project (eventual-consistency write lag)
**Where:** `app/scripts/deploy_agents.py`,
`project.agents.create_version(...)` (and, less often, the
`project.connections.list()` resolver), run shortly after a clean deploy where
the capability hosts (#19) already exist and report `Succeeded`.

**Symptom:** The first data-plane write fails:
```
azure.core.exceptions.ResourceNotFoundError: (NotFound) Project not found
Code: NotFound
Message: Project not found
```
…even though, at the same moment:
- both capability hosts report `provisioningState = "Succeeded"`,
- the raw data plane is reachable
  (`GET .../agents?api-version=v1` already lists the agents), and
- `project.connections.list()` returns the connections (HTTP 200, verified via
  `logging_enable=True`).

Re-inspecting after the throw shows the write **did** land server-side: all four
agents exist at their expected versions. The matcher had accumulated 8 versions
precisely because each failed-looking retry actually created a new version.

**Root cause:** This is the **write-path** tail of the same eventual-consistency
window described in #18/#19, isolated to the agent service. After a fresh
(re)provision, the *read* routes (`connections.list`, `agents.list`) catch up
first; the `create_version` *write* route briefly still resolves the project on a
replica that 404s with `"Project not found"`. The write often commits anyway, so
the SDK exception is misleading. Unlike #19 (a permanent, missing-capability-host
failure), this self-heals within seconds.

**Fix (official Azure transient-fault guidance):** wrap the eventually-consistent
data-plane calls in **retry with exponential backoff** — the documented pattern
in [Recommendations for handling transient faults](https://learn.microsoft.com/azure/well-architected/reliability/handle-transient-faults)
and the Azure AI Search reliability guidance ("use a retry strategy with
exponential backoffs for both read and write operations"). Added a `_with_retry`
helper in `deploy_agents.py` that retries **only** on a 404 whose message
contains `"project not found"`, backing off `5 → 10 → 20 → 40 → 80s` (max 6
attempts), and applied it to both the connection resolver and each
`create_version` call:
```python
def _with_retry(label, fn):
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except HttpResponseError as e:
            transient = e.status_code == 404 and "project not found" in str(e).lower()
            if not transient or attempt == _MAX_RETRIES:
                raise
            time.sleep(_BASE_DELAY_SEC * (2 ** (attempt - 1)))
```

**Result:** Deploy now self-recovers — one transient 404 on the first agent, then
`EXIT=0`: retriever v3 (`idx_bls_corpus`), matcher v8 (no index), reviewer v3,
qa v1 (`idx_bls_corpus`).

**Lesson:**
- On a freshly provisioned Foundry project, treat the **first write** as
  eventually consistent even when reads already succeed and the capability hosts
  are `Succeeded`. Don't assume a 404 means the write failed — verify with
  `agents.list()`.
- Scope the retry tightly (only 404 + `"project not found"`) so genuine
  not-found / auth / schema errors still fail fast instead of looping.

---

### #21 — `The property 'Count' cannot be found on this object` under StrictMode (PS 5.1)
**Where:** `setup/deploy.ps1`, every `if ($x -and $x.Count -gt 0)` guard over
`az ... --output json | ConvertFrom-Json` output — section 9 (Foundry project
connections, the `CognitiveSearch` / `AppInsights` checks) hit it first, plus
the soft-delete purge check and the two `Ensure-*RoleAssignment` helpers.

**Symptom (client-reported, never reproduced on our box):**
```
🔹 Foundry project connections
deploy.ps1: The property 'Count' cannot be found on this object. Verify that the property exists.
```
The script aborts (`$ErrorActionPreference = "Stop"`) at the very first
connection check, before any project connection is created.

**Root cause:** The script runs under `Set-StrictMode -Version Latest`. In
**Windows PowerShell 5.1**, `.Count` is a synthetic member that only exists on
collections and `$null` — **not** on a *scalar* `[string]` or a *single*
`[pscustomobject]`. Under StrictMode, accessing `.Count` on such a scalar
throws "The property 'Count' cannot be found on this object" (without StrictMode
it would silently return `$null`).

The scalar appears because of a **build-dependent quirk of `ConvertFrom-Json`
in PS 5.1**: on *older* 5.1 builds a single-element JSON array
(`["search-connection"]`) is *unwrapped* into a bare scalar string, so
`$existingConn.Count` throws. This is also exactly **why it never reproduced on
our box** — our newer 5.1 build (5.1.26100+) keeps the one-element result as an
`Object[]` (Count = 1, fine), so the same line ran clean for us regardless of
how many connections existed. The crash only surfaces where the *client's*
older 5.1 build does the unwrap **and** a category has exactly one connection.
Verified by simulating the unwrapped scalar: the OLD guard
`if ($existing -and $existing.Count -gt 0)` throws the exact client error, while
the fixed `if (@($existing).Count -gt 0)` returns `1`.

Proof (PS 5.1, `Set-StrictMode -Version Latest`):
```powershell
('search-connection').Count          # ERR: property 'Count' cannot be found
([pscustomobject]@{name='x'}).Count  # ERR: property 'Count' cannot be found
('[]' | ConvertFrom-Json).Count      # 0   (ok)
@('search-connection').Count         # 1   (ok)
```

**Fix:** Force array context with the array-subexpression operator `@(...)`
before reading `.Count` (and before indexing `[0]`). `@($null).Count` is `0`
and `@($scalar).Count` is `1`, so the `-and $x` null-guard is no longer needed:
```powershell
# before (fragile)
if ($existingConn -and $existingConn.Count -gt 0) { $existingConn[0] }
# after (array-safe)
if (@($existingConn).Count -gt 0) { @($existingConn)[0] }
```
Applied to all six call sites (soft-delete purge, both role-assignment helpers,
the two per-project connection checks, and the `.env` connection-name lookup).

**Lesson:** Under StrictMode in PS 5.1, never call `.Count`/`.Length` directly
on a value that *might* be a scalar — `ConvertFrom-Json` may unwrap a
single-element result into a scalar on some PS 5.1 builds (and keep it as an
array on others). Always wrap in `@(...)` to normalise to an array first.
"Works on my machine" here was **not** data luck — it was a *PowerShell build*
difference: our 5.1 build never unwraps single results, so no count of
connections could trigger it locally. Test idempotent guards against the 0-, 1-,
and N-result cases **and** assume `ConvertFrom-Json` may hand you a scalar.

---

## Part 2 — Code changes summary

### `setup/deploy.ps1`
- (Not yet patched; documented as #2/#5 above — user is running fixes manually
  after each deploy. Sustainable fix = add Content-Type to both `az rest`
  PUTs, drop `--output none 2>$null`, and add the project-MI + RBAC + AAD
  block.)
- Fix for **#21**: all six `.Count` guards over `ConvertFrom-Json` output now
  use array-safe `@($x).Count` (and `@($x)[0]`) so single-result scalars don't
  throw under `Set-StrictMode` in PS 5.1.

### `app/scripts/deploy_agents.py`
- Fix for **#4**: import path / sys.path layout.
- Fix for **#7**: `_search_tools` collapses to one tool / one index per agent;
  returns `[]` when an agent has no indexes (matcher post-refactor).
- Fix for **#20**: `_with_retry` exponential-backoff wrapper around the
  eventually-consistent `connections.list()` resolver and each
  `create_version` call; retries only on a 404 + `"project not found"`.

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
