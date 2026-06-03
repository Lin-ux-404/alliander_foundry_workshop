<#
.SYNOPSIS
    Deploys all Azure resources for the Alliander Workshop (labs + DRAAD app).

.DESCRIPTION
    Creates:
      1. Resource Group
      2. AI Foundry account (shared) with N projects
      3. Model deployments (gpt-5.4-mini, text-embedding-ada-002, gpt-4.1-mini)
      4. Azure AI Search (basic, system-assigned identity)
      5. Storage Account (Standard_LRS)
      6. Application Insights
      7. Foundry ↔ Search ↔ Storage RBAC bindings
      8. Per-project Foundry connections (Search, AppInsights)
      9. Per-project .env files

.PARAMETER Prefix
    Naming prefix for all resources (e.g. "alliander-workshop").

.PARAMETER Location
    Azure region. Default: swedencentral.

.PARAMETER ProjectCount
    Number of Foundry projects to create under the single account.
    Default: 1. With 1 project, name is "{Prefix}-project".
    With N>1, names are "{Prefix}-project-01" .. "{Prefix}-project-N".
    Each project gets its own connections and .env file.

.PARAMETER SubscriptionId
    Target subscription. Uses current default if omitted.

.EXAMPLE
    .\deploy.ps1 -Prefix "alliander-workshop"
    .\deploy.ps1 -Prefix "myteam-lab" -Location "westeurope" -ProjectCount 5
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Prefix,

    [string]$Location = "swedencentral",

    [ValidateRange(1, 100)]
    [int]$ProjectCount = 1,

    [string]$SubscriptionId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) { Write-Host "`n🔹 $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "   ✅ $msg" -ForegroundColor Green }
function Write-Skip([string]$msg) { Write-Host "   ⏭️  $msg" -ForegroundColor Yellow }

function Invoke-Az {
    [CmdletBinding()]
    param([Parameter(ValueFromRemainingArguments)] $Args_)
    # Localize to Continue: az frequently writes WARNINGs (and absent-resource
    # errors) to stderr. Under $ErrorActionPreference='Stop', Windows PowerShell
    # 5.1 turns ANY native stderr write into a terminating NativeCommandError —
    # so a harmless TLS-deprecation warning would crash an otherwise-successful
    # create. Decide success/failure from the real exit code only.
    $ErrorActionPreference = 'Continue'
    $result = az @Args_ 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "az command failed: $result"
    }
    return $result
}

# Probe helper for "does this resource already exist?" reads. Windows PowerShell
# 5.1 turns a non-zero native exit + stderr into a terminating NativeCommandError
# whenever $ErrorActionPreference is 'Stop' — even with `2>$null`. We deliberately
# drop the Stop preference in this function's local scope so a missing resource
# returns $null instead of crashing the script. (pwsh 7 doesn't have this quirk.)
function Get-AzOrNull {
    param([Parameter(ValueFromRemainingArguments)] $Args_)
    $ErrorActionPreference = 'SilentlyContinue'
    $out = az @Args_ 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out
}

# ── Derived names ────────────────────────────────────────────────────────────

$rgName          = "$Prefix-rg"
$foundryName     = "$Prefix-foundry"
$searchName      = "$Prefix-search"
$storageName     = ($Prefix -replace '[^a-z0-9]', '') + "blob"
$appInsightsName = ($Prefix -replace '[^a-z0-9]', '') + "insights"

# Build project name list
if ($ProjectCount -eq 1) {
    $projectNames = @("$Prefix-project")
} else {
    $projectNames = 1..$ProjectCount | ForEach-Object {
        "$Prefix-project-{0:D2}" -f $_
    }
}

# Truncate storage name to 24 chars (Azure limit)
if ($storageName.Length -gt 24) { $storageName = $storageName.Substring(0, 24) }

# ── Pre-flight ───────────────────────────────────────────────────────────────

Write-Step "Pre-flight checks"

if ($SubscriptionId) {
    Invoke-Az account set --subscription $SubscriptionId | Out-Null
}

$account = az account show --output json | ConvertFrom-Json
$subId = $account.id
$tenantId = $account.tenantId
Write-Ok "Subscription: $($account.name) ($subId)"

# Failure mode #1: workspace-based App Insights creation hangs without the
# AIWorkspacePreview feature flag, and the first `az monitor app-insights` call
# silently prompts to install its CLI extension (invisible inside the script).
# Register the flag + enable non-interactive extension install up front.
Write-Host "   ⚙️  Registering App Insights pre-reqs (feature flag + dynamic install)..." -ForegroundColor Yellow
az config set extension.use_dynamic_install=yes_without_prompt --only-show-errors 2>$null | Out-Null
az feature register --name AIWorkspacePreview --namespace microsoft.insights --only-show-errors 2>$null | Out-Null
az provider register --namespace microsoft.insights --only-show-errors 2>$null | Out-Null
Write-Ok "App Insights pre-reqs registered"

$callerUpn = $account.user.name
$callerId = $null

# Try Graph API first
$callerInfo = Get-AzOrNull ad signed-in-user show --output json
if ($LASTEXITCODE -eq 0 -and $callerInfo) {
    $callerParsed = $callerInfo | ConvertFrom-Json
    $callerId = $callerParsed.id
    $callerUpn = $callerParsed.userPrincipalName
}

# Fallback: resolve UPN to object ID
if (-not $callerId) {
    Write-Host "   ⚠️  Graph query failed, resolving user via 'az ad user show'..." -ForegroundColor Yellow
    $adUser = Get-AzOrNull ad user show --id $callerUpn --query "id" --output tsv
    if ($LASTEXITCODE -eq 0 -and $adUser) {
        $callerId = $adUser.Trim()
    }
}

# Last resort: extract object ID from the access token (no Graph permissions needed)
if (-not $callerId) {
    Write-Host "   ⚠️  Extracting object ID from access token..." -ForegroundColor Yellow
    $tokenJson = Get-AzOrNull account get-access-token --output json
    if ($LASTEXITCODE -eq 0 -and $tokenJson) {
        $token = ($tokenJson | ConvertFrom-Json).accessToken
        # JWT has 3 parts; decode the payload (part 2)
        $payload = $token.Split('.')[1]
        # Pad base64 to multiple of 4
        switch ($payload.Length % 4) {
            2 { $payload += '==' }
            3 { $payload += '=' }
        }
        $decoded = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($payload))
        $claims = $decoded | ConvertFrom-Json
        if ($claims.oid) {
            $callerId = $claims.oid
            if ($claims.upn) { $callerUpn = $claims.upn }
        }
    }
}

if (-not $callerId) {
    throw "Could not resolve object ID for '$callerUpn'. Ensure you have Graph read permissions or pass a service principal."
}
Write-Ok "Deploying as: $callerUpn ($callerId)"

# ── 1. Resource Group ────────────────────────────────────────────────────────

Write-Step "Resource Group: $rgName"
$rgExists = az group exists --name $rgName --output tsv
if ($rgExists -eq "true") {
    Write-Skip "Already exists"
} else {
    Invoke-Az group create --name $rgName --location $Location --output none
    Write-Ok "Created"
}

# ── 2. AI Foundry Account ───────────────────────────────────────────────────

Write-Step "AI Foundry account: $foundryName"
$foundryExists = Get-AzOrNull cognitiveservices account show --name $foundryName --resource-group $rgName --output json
if ($foundryExists) {
    Write-Skip "Already exists"
    # Ensure custom subdomain and identity are set (required for projects)
    $foundryParsed = $foundryExists | ConvertFrom-Json
    if (-not $foundryParsed.properties.customSubDomainName) {
        Write-Host "   ⚙️  Setting custom subdomain..." -ForegroundColor Yellow
        Invoke-Az cognitiveservices account update `
            --name $foundryName `
            --resource-group $rgName `
            --custom-domain $foundryName `
            --output none
        Write-Ok "Custom subdomain set"
    }
    if (-not $foundryParsed.identity.principalId) {
        Write-Host "   ⚙️  Enabling system identity..." -ForegroundColor Yellow
        Invoke-Az cognitiveservices account identity assign `
            --name $foundryName `
            --resource-group $rgName `
            --output none
        Write-Ok "Identity enabled"
    }
} else {
    # Azure AI Services accounts are SOFT-DELETED (not purged) when their RG is
    # deleted. Recreating with the same name fails with FlagMustBeSetForRestore
    # until the soft-deleted account is purged. Purge any matching ghost first.
    $deleted = Get-AzOrNull cognitiveservices account list-deleted --query "[?name=='$foundryName']" --output json | ConvertFrom-Json
    if ($deleted -and $deleted.Count -gt 0) {
        Write-Host "   ⚙️  Purging soft-deleted account of the same name..." -ForegroundColor Yellow
        Invoke-Az cognitiveservices account purge `
            --location $Location `
            --resource-group $rgName `
            --name $foundryName
        Write-Ok "Soft-deleted account purged"
    }
    Invoke-Az cognitiveservices account create `
        --name $foundryName `
        --resource-group $rgName `
        --location $Location `
        --kind AIServices `
        --sku S0 `
        --custom-domain $foundryName `
        --assign-identity `
        --yes `
        --output none
    Write-Ok "Created"
}

# Get Foundry managed identity
$foundryJson = az cognitiveservices account show --name $foundryName --resource-group $rgName --output json | ConvertFrom-Json
$foundryMI = $foundryJson.identity.principalId
$foundryResourceId = $foundryJson.id
Write-Ok "Foundry MI: $foundryMI"

# ── 3. Foundry Projects ─────────────────────────────────────────────────────

Write-Step "Foundry projects ($ProjectCount)"

$projectBody = @{
    location   = $Location
    properties = @{}
    identity   = @{ type = "SystemAssigned" }
} | ConvertTo-Json -Compress

$projectResourceIds = @{}

foreach ($projName in $projectNames) {
    $projResId = "$foundryResourceId/projects/$projName"
    $projectResourceIds[$projName] = $projResId
    $projExists = Get-AzOrNull resource show --ids $projResId --output json
    if ($projExists) {
        Write-Skip "$projName already exists"
    } else {
        $tmpFile = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $tmpFile -Value $projectBody -Encoding UTF8
        $projUrl = "https://management.azure.com$projResId`?api-version=2025-04-01-preview"
        Invoke-Az rest --method PUT --url $projUrl --body "@$tmpFile" --headers "Content-Type=application/json" --output none
        Remove-Item $tmpFile
        Write-Ok "$projName created"
    }
}

# ── 3b. Agents Capability Hosts ─────────────────────────────────────────────
# Failure mode #19: the Foundry Agent Service requires an "Agents" capability
# host on BOTH the account and each project. Without it, the agents data plane
# returns 404 "Project not found" for connections.get / agents.create_version,
# even though the project provisioningState is "Succeeded". A same-name
# redeploy can mask this if a capability host survived from a prior portal
# session, but a genuinely clean account has none — so create them explicitly.
# The account host must reach "Succeeded" before the project host is created.

Write-Step "Agents capability hosts"

function Ensure-CapabilityHost {
    param([string]$ScopeResourceId, [string]$Label)
    $hostUrlBase = "https://management.azure.com$ScopeResourceId/capabilityHosts/agentshost"
    $existing = Get-AzOrNull rest --method get --url "$hostUrlBase`?api-version=2025-04-01-preview" --query "properties.provisioningState" --output tsv
    if ($existing -eq "Succeeded") {
        Write-Skip "$Label capability host exists"
        return
    }
    if (-not $existing) {
        $body = '{"properties":{"capabilityHostKind":"Agents"}}'
        $f = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $f -Value $body -Encoding UTF8
        Invoke-Az rest --method put --url "$hostUrlBase`?api-version=2025-04-01-preview" `
            --body "@$f" --headers "Content-Type=application/json" --output none
        Remove-Item $f
    }
    # Poll until provisioning completes
    do {
        Start-Sleep -Seconds 10
        $state = Get-AzOrNull rest --method get --url "$hostUrlBase`?api-version=2025-04-01-preview" --query "properties.provisioningState" --output tsv
    } while ($state -eq "Creating")
    if ($state -eq "Succeeded") {
        Write-Ok "$Label capability host ready"
    } else {
        throw "$Label capability host provisioning failed: $state"
    }
}

Ensure-CapabilityHost $foundryResourceId "Account"
foreach ($projName in $projectNames) {
    Ensure-CapabilityHost $projectResourceIds[$projName] "Project ($projName)"
}

# ── 4. Model Deployments ────────────────────────────────────────────────────

Write-Step "Model deployments"

$models = @(
    @{ Name = "gpt-5.4-mini";             Model = "gpt-5.4-mini";             Version = "2026-03-17"; Sku = "GlobalStandard"; Capacity = 1000 }
    @{ Name = "text-embedding-ada-002";    Model = "text-embedding-ada-002";    Version = "2";          Sku = "GlobalStandard"; Capacity = 656  }
    @{ Name = "gpt-4.1-mini";             Model = "gpt-4.1-mini";             Version = "2025-04-14"; Sku = "GlobalStandard"; Capacity = 5000 }
)

foreach ($m in $models) {
    $existing = Get-AzOrNull cognitiveservices account deployment show `
        --name $foundryName --resource-group $rgName `
        --deployment-name $m.Name --output json
    if ($existing) {
        Write-Skip "$($m.Name) already deployed"
    } else {
        Invoke-Az cognitiveservices account deployment create `
            --name $foundryName `
            --resource-group $rgName `
            --deployment-name $m.Name `
            --model-name $m.Model `
            --model-version $m.Version `
            --model-format OpenAI `
            --sku-name $m.Sku `
            --sku-capacity $m.Capacity `
            --output none
        Write-Ok "$($m.Name) deployed"
    }
}

# ── 5. Azure AI Search ──────────────────────────────────────────────────────

Write-Step "AI Search: $searchName"
$searchExists = Get-AzOrNull search service show --name $searchName --resource-group $rgName --output json
if ($searchExists) {
    Write-Skip "Already exists"
} else {
    Invoke-Az search service create `
        --name $searchName `
        --resource-group $rgName `
        --location $Location `
        --sku basic `
        --replica-count 1 `
        --partition-count 1 `
        --identity-type SystemAssigned `
        --output none
    Write-Ok "Created"
}

$searchJson = az search service show --name $searchName --resource-group $rgName --output json | ConvertFrom-Json
$searchMI = $searchJson.identity.principalId
$searchResourceId = $searchJson.id
$searchEndpoint = "https://$searchName.search.windows.net"
Write-Ok "Search MI: $searchMI"

# Failure mode #5 (part 1): the AzureAISearchTool authenticates with an AAD
# token. A service in apiKeyOnly mode returns 403 regardless of RBAC. Force
# mixed auth (AAD + keys) so connection-based AAD auth works.
Write-Host "   ⚙️  Enabling AAD auth on Search (aadOrApiKey, http403)..." -ForegroundColor Yellow
Invoke-Az search service update --name $searchName --resource-group $rgName `
    --auth-options aadOrApiKey --aad-auth-failure-mode http403 --output none
Write-Ok "Search auth set to aadOrApiKey"

# Get search admin key (needed for .env / index scripts)
$searchKeys = az search admin-key show --service-name $searchName --resource-group $rgName --output json | ConvertFrom-Json
$searchAdminKey = $searchKeys.primaryKey

# ── 6. Storage Account ──────────────────────────────────────────────────────

Write-Step "Storage account: $storageName"
$storageExists = Get-AzOrNull storage account show --name $storageName --resource-group $rgName --output json
if ($storageExists) {
    Write-Skip "Already exists"
} else {
    Invoke-Az storage account create `
        --name $storageName `
        --resource-group $rgName `
        --location $Location `
        --sku Standard_LRS `
        --kind StorageV2 `
        --output none
    Write-Ok "Created"
}
$storageUrl = "https://$storageName.blob.core.windows.net/"

# ── 7. Application Insights ─────────────────────────────────────────────────

Write-Step "Application Insights: $appInsightsName"
$aiExists = Get-AzOrNull monitor app-insights component show --app $appInsightsName --resource-group $rgName --output json
if ($aiExists) {
    Write-Skip "Already exists"
} else {
    Invoke-Az monitor app-insights component create `
        --app $appInsightsName `
        --resource-group $rgName `
        --location $Location `
        --kind web `
        --application-type web `
        --output none
    Write-Ok "Created"
}
$aiJson = az monitor app-insights component show --app $appInsightsName --resource-group $rgName --output json | ConvertFrom-Json
$aiConnectionString = $aiJson.connectionString
$aiResourceId = $aiJson.id

# ── 8. RBAC Assignments ─────────────────────────────────────────────────────

Write-Step "RBAC role assignments"

function Ensure-RoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$Role,
        [string]$Scope,
        [string]$Label
    )
    $existing = Get-AzOrNull role assignment list --assignee $PrincipalId --role $Role --scope $Scope --output json | ConvertFrom-Json
    if ($existing -and $existing.Count -gt 0) {
        Write-Skip "$Label → $Role (exists)"
    } else {
        Invoke-Az role assignment create `
            --assignee-object-id $PrincipalId `
            --assignee-principal-type ServicePrincipal `
            --role $Role `
            --scope $Scope `
            --output none
        Write-Ok "$Label → $Role"
    }
}

function Ensure-UserRoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$Role,
        [string]$Scope,
        [string]$Label
    )
    $existing = Get-AzOrNull role assignment list --assignee $PrincipalId --role $Role --scope $Scope --output json | ConvertFrom-Json
    if ($existing -and $existing.Count -gt 0) {
        Write-Skip "$Label → $Role (exists)"
    } else {
        Invoke-Az role assignment create `
            --assignee-object-id $PrincipalId `
            --assignee-principal-type User `
            --role $Role `
            --scope $Scope `
            --output none
        Write-Ok "$Label → $Role"
    }
}

$storageResourceId = "/subscriptions/$subId/resourceGroups/$rgName/providers/Microsoft.Storage/storageAccounts/$storageName"

# Foundry MI → Search: read indexes + manage service
Ensure-RoleAssignment $foundryMI "Search Index Data Reader" $searchResourceId "Foundry MI"
Ensure-RoleAssignment $foundryMI "Search Service Contributor" $searchResourceId "Foundry MI"

# Failure mode #5 (parts 2+3): each Foundry PROJECT has its own system-assigned
# MI, distinct from the account MI above. The AzureAISearchTool authenticates as
# the PROJECT MI, so it (not the account MI) needs the Search roles.
foreach ($projName in $projectNames) {
    $projResId = $projectResourceIds[$projName]
    $projMi = Get-AzOrNull rest --method get `
        --url "https://management.azure.com$projResId`?api-version=2025-04-01-preview" `
        --query "identity.principalId" --output tsv
    if ($projMi) {
        $projMi = $projMi.Trim()
        Ensure-RoleAssignment $projMi "Search Index Data Reader" $searchResourceId "$projName MI"
        Ensure-RoleAssignment $projMi "Search Service Contributor" $searchResourceId "$projName MI"
    } else {
        Write-Host "   ⚠️  Could not resolve project MI for $projName (Search RBAC skipped)" -ForegroundColor Yellow
    }
}

# Search MI → Foundry: call OpenAI models
Ensure-RoleAssignment $searchMI "Cognitive Services OpenAI User" $foundryResourceId "Search MI"

# Current user → Foundry User (on the foundry resource)
Ensure-UserRoleAssignment $callerId "Cognitive Services User" $foundryResourceId "User ($callerUpn)"

# Current user → Search Index Data Reader
Ensure-UserRoleAssignment $callerId "Search Index Data Reader" $searchResourceId "User ($callerUpn)"

# Current user → Storage Blob Data Contributor
Ensure-UserRoleAssignment $callerId "Storage Blob Data Contributor" $storageResourceId "User ($callerUpn)"

# ── 9. Foundry Project Connections (per project) ────────────────────────────

Write-Step "Foundry project connections"

$apiVersion = "2025-04-01-preview"
$searchConnName = "search-connection"
$aiConnName     = "appinsights-connection"

$searchConnBody = @{
    properties = @{
        category = "CognitiveSearch"
        target   = $searchEndpoint
        authType = "AAD"
    }
} | ConvertTo-Json -Depth 5

# Failure mode #17: AppInsights connections reject authType="AAD" with HTTP
# 400 ("AuthType for AppInsights Connection can only be ApiKey"). They MUST
# use ApiKey auth with the App Insights connection string as the key. Unlike
# the Search connection (which works with AAD), this category has no AAD path.
$aiConnBody = @{
    properties = @{
        category    = "AppInsights"
        target      = $aiResourceId
        authType    = "ApiKey"
        credentials = @{ key = $aiConnectionString }
    }
} | ConvertTo-Json -Depth 5

$searchConnNames = @{}

foreach ($projName in $projectNames) {
    $projResId = $projectResourceIds[$projName]
    $projApiBase = "https://management.azure.com$projResId"

    # Search connection
    $existingConn = Get-AzOrNull rest --method get --url "$projApiBase/connections?api-version=$apiVersion" --query "value[?properties.category=='CognitiveSearch'].name" --output json | ConvertFrom-Json
    if ($existingConn -and $existingConn.Count -gt 0) {
        $actualSearchConn = $existingConn[0]
        Write-Skip "$projName → Search connection exists: $actualSearchConn"
    } else {
        $actualSearchConn = $searchConnName
        # Failure mode #2: this PUT MUST include Content-Type or ARM returns
        # HTTP 415. Pass the body via temp file + header (same pattern as the
        # project-create PUT in section 3). Use Invoke-Az so a 415 throws
        # instead of being swallowed by `2>$null --output none`.
        $searchConnFile = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $searchConnFile -Value $searchConnBody -Encoding UTF8
        Invoke-Az rest --method put `
            --url "$projApiBase/connections/$($searchConnName)?api-version=$apiVersion" `
            --body "@$searchConnFile" `
            --headers "Content-Type=application/json" `
            --output none
        Remove-Item $searchConnFile
        Write-Ok "$projName → Search connection: $searchConnName"
    }

    # AppInsights connection
    $existingAiConn = Get-AzOrNull rest --method get --url "$projApiBase/connections?api-version=$apiVersion" --query "value[?properties.category=='AppInsights'].name" --output json | ConvertFrom-Json
    if ($existingAiConn -and $existingAiConn.Count -gt 0) {
        Write-Skip "$projName → AppInsights connection exists: $($existingAiConn[0])"
    } else {
        # Failure mode #2: same Content-Type requirement as the Search connection.
        $aiConnFile = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $aiConnFile -Value $aiConnBody -Encoding UTF8
        Invoke-Az rest --method put `
            --url "$projApiBase/connections/$($aiConnName)?api-version=$apiVersion" `
            --body "@$aiConnFile" `
            --headers "Content-Type=application/json" `
            --output none
        Remove-Item $aiConnFile
        Write-Ok "$projName → AppInsights connection: $aiConnName"
    }

    # Store connection name for .env generation
    $searchConnNames[$projName] = if ($existingConn -and $existingConn.Count -gt 0) { $existingConn[0] } else { $searchConnName }
}

# ── 10. Generate .env file(s) ────────────────────────────────────────────────

Write-Step "Generating .env file(s)"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path

function Write-EnvFile {
    param(
        [string]$Path,
        [string]$ProjectName,
        [string]$SearchConnectionName
    )
    $endpoint = "https://$foundryName.services.ai.azure.com/api/projects/$ProjectName"
    $content = @"
# Azure AI Foundry
FOUNDRY_PROJECT_ENDPOINT=$endpoint
FOUNDRY_MODEL=gpt-5.4-mini

# Azure AI Search
AZURE_SEARCH_ENDPOINT=$searchEndpoint
AZURE_SEARCH_ADMIN_KEY=$searchAdminKey
AZURE_SEARCH_INDEX=idx_bls_corpus
AZURE_SEARCH_RO_INDEX=idx_raamopdrachten
AZURE_SEARCH_CREW_INDEX=idx_crew
AZURE_SEARCH_CONNECTION_NAME=$SearchConnectionName

# Azure Blob Storage (for crew data)
AZURE_STORAGE_ACCOUNT_URL=$storageUrl
AZURE_STORAGE_CREW_CONTAINER=crew-data
AZURE_STORAGE_CREW_BLOB=crew.json
AZURE_STORAGE_RO_BLOB=raamopdrachten.json

# Foundry Agent Names (set after running scripts/deploy_agents.py)
DRAAD_RETRIEVER_AGENT=draad-procedure-retriever
DRAAD_MATCHER_AGENT=draad-dispatch-matcher
DRAAD_REVIEWER_AGENT=draad-dispatch-reviewer
DRAAD_QA_AGENT=draad-qa-assistant

# FastAPI
ALLOWED_ORIGINS=http://localhost:3000

# Tuning
SEARCH_TOP_K=6
"@
    if (Test-Path $Path) {
        Copy-Item $Path "$Path.bak" -Force
    }
    Set-Content -Path $Path -Value $content -Encoding UTF8
    Write-Ok "Written to $Path"
}

if ($ProjectCount -eq 1) {
    # Single project → write .env at repo root
    $envPath = Join-Path $repoRoot ".env"
    $projName = $projectNames[0]
    Write-EnvFile -Path $envPath -ProjectName $projName -SearchConnectionName $searchConnNames[$projName]
} else {
    # Multiple projects → write .env.<project-name> per project + .env pointing to first
    foreach ($projName in $projectNames) {
        $envPath = Join-Path $repoRoot ".env.$projName"
        Write-EnvFile -Path $envPath -ProjectName $projName -SearchConnectionName $searchConnNames[$projName]
    }
    # Default .env → first project (can be switched by copying)
    $defaultEnv = Join-Path $repoRoot ".env"
    $firstProj = $projectNames[0]
    Write-EnvFile -Path $defaultEnv -ProjectName $firstProj -SearchConnectionName $searchConnNames[$firstProj]
    Write-Ok "Default .env points to $firstProj (switch by copying .env.<name> to .env)"
}

# Failure mode #3: uvicorn runs in app/backend/ and loads app/backend/.env, while
# the deploy/index scripts load the repo-root .env. Mirror the root .env into
# app/backend/ so both consumers see the same config after every deploy.
$backendEnv = Join-Path $repoRoot "app\backend\.env"
Copy-Item (Join-Path $repoRoot ".env") $backendEnv -Force
Write-Ok "Mirrored .env to app\backend\.env"

# ── Summary ──────────────────────────────────────────────────────────────────

Write-Host "`n" -NoNewline
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host " Deployment complete!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host " Resource Group:    $rgName"
Write-Host " Location:          $Location"
Write-Host " Foundry:           $foundryName"
Write-Host " Projects:          $($projectNames -join ', ')"
Write-Host " Search:            $searchName"
Write-Host " Storage:           $storageName"
Write-Host " App Insights:      $appInsightsName"
Write-Host ""
if ($ProjectCount -gt 1) {
    Write-Host " Project endpoints:" -ForegroundColor Yellow
    foreach ($p in $projectNames) {
        Write-Host "   • https://$foundryName.services.ai.azure.com/api/projects/$p"
    }
    Write-Host ""
    Write-Host " .env files:" -ForegroundColor Yellow
    Write-Host "   • .env           → $($projectNames[0]) (default)"
    foreach ($p in $projectNames) {
        Write-Host "   • .env.$p"
    }
    Write-Host "   To switch: copy .env.<project-name> to .env"
    Write-Host ""
}
Write-Host " Next steps:" -ForegroundColor Yellow
Write-Host "   1. Run index scripts:      python app/scripts/setup_search.py --all"
