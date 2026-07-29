<#
.SYNOPSIS
    Deploys all Azure resources for the Alliander Workshop (labs + DRAAD app).

.DESCRIPTION
    Creates:
      1. Resource Group
      2. Microsoft Foundry account with one or more projects
      3. Model deployments (gpt-5.4-mini, text-embedding-ada-002, gpt-4.1-mini)
      4. Azure AI Search (basic, system-assigned identity)
      5. Storage Account (Standard_LRS)
      6. Application Insights
      7. Foundry ↔ Search ↔ Storage RBAC bindings
      8. Per-project Foundry connections (Search, AppInsights)
      9. Entra principal access from an optional access manifest
     10. Per-project, collision-safe .env files

.PARAMETER Prefix
    Naming prefix for all resources (e.g. "alliander-workshop").

.PARAMETER Location
    Azure region. Default: swedencentral.

.PARAMETER ProjectCount
    Number of Foundry projects. TeamIsolated requires 1. SharedProjects requires
    at least 2. Each project gets a unique resource namespace and .env file.

.PARAMETER Topology
    TeamIsolated (default) deploys one resource group, Foundry account/project,
    Search service, Storage account, and Application Insights instance for one
    team. Run the script once per team with a unique Prefix.

    SharedProjects deploys multiple projects on shared services. It provides
    logical naming isolation only; Search and Storage RBAC remain service-wide.

.PARAMETER SearchSku
    Azure AI Search SKU. SharedProjects capacity is checked against an estimate
    of seven workshop indexes per project.

.PARAMETER AccessManifestPath
    Optional JSON manifest that maps Entra object IDs (groups, users, service
    principals, or foreign groups) to Foundry projects. See
    setup/access-manifest.example.json.

.PARAMETER SubscriptionId
    Target subscription. Uses current default if omitted.

.EXAMPLE
    .\deploy.ps1 -Prefix "workshop-team01" -AccessManifestPath .\setup\access-manifest.example.json
    .\deploy.ps1 -Prefix "workshop-shared" -Topology SharedProjects -ProjectCount 2 -SearchSku basic
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Prefix,

    [string]$Location = "swedencentral",

    [ValidateRange(1, 40)]
    [int]$ProjectCount = 1,

    [ValidateSet("TeamIsolated", "SharedProjects")]
    [string]$Topology = "TeamIsolated",

    [ValidateSet("basic", "standard", "standard2")]
    [string]$SearchSku = "basic",

    [string]$AccessManifestPath,

    [string]$SubscriptionId,

    [switch]$SkipQuotaCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FoundryArmApiVersion = "2025-06-01"
$FoundryUserRoleId = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
$ReaderRoleId = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
$SearchServiceContributorRoleId = "7ca78c08-252a-4471-8644-bb5ff32d4ba0"
$SearchIndexDataContributorRoleId = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
$SearchIndexDataReaderRoleId = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
$StorageBlobDataContributorRoleId = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
$CognitiveServicesOpenAIUserRoleId = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
$MonitoringReaderRoleId = "43d0d8ad-25c7-4714-9337-8ba259a9fe05"
$LogAnalyticsReaderRoleId = "73c42c96-874c-492b-b04d-ab87d138a893"

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
    #
    # Retry logic: Windows ephemeral port exhaustion (WinError 10048) is common
    # when scripts make many rapid az CLI calls. Each call opens a new HTTPS
    # connection; closed sockets sit in TIME_WAIT for ~2 min, eventually
    # exhausting the pool. Retry with backoff on connection errors.
    $maxAttempts = 3
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $ErrorActionPreference = 'Continue'
        $result = az @Args_ 2>&1
        if ($LASTEXITCODE -eq 0) {
            return $result
        }
        $msg = "$result"
        if ($msg -match 'WinError 10048|ephemeral|NewConnectionError|Max retries exceeded' -and $attempt -lt $maxAttempts) {
            Write-Host "   ⚠️  Connection error (attempt $attempt/$maxAttempts), waiting 30s for ports to free..." -ForegroundColor Yellow
            Start-Sleep -Seconds 30
            continue
        }
        throw "az command failed: $result"
    }
}

# Probe helper for "does this resource already exist?" reads. Windows PowerShell
# 5.1 turns a non-zero native exit + stderr into a terminating NativeCommandError
# whenever $ErrorActionPreference is 'Stop' — even with `2>$null`. We deliberately
# drop the Stop preference in this function's local scope so a missing resource
# returns $null instead of crashing the script. (pwsh 7 doesn't have this quirk.)
#
# Same retry logic as Invoke-Az for transient connection errors.
function Get-AzOrNull {
    param([Parameter(ValueFromRemainingArguments)] $Args_)
    $maxAttempts = 3
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $ErrorActionPreference = 'SilentlyContinue'
        $out = az @Args_ 2>$null
        if ($LASTEXITCODE -eq 0) { return $out }
        $msg = "$out"
        if ($msg -match 'WinError 10048|ephemeral|NewConnectionError|Max retries exceeded' -and $attempt -lt $maxAttempts) {
            Write-Host "   ⚠️  Connection error (attempt $attempt/$maxAttempts), waiting 30s for ports to free..." -ForegroundColor Yellow
            Start-Sleep -Seconds 30
            continue
        }
        return $null
    }
    return $null
}

function ConvertTo-ResourceNamespace {
    param([Parameter(Mandatory = $true)][string]$Value)

    $name = $Value.ToLowerInvariant() -replace '[^a-z0-9-]', '-'
    $name = $name -replace '-+', '-'
    $name = $name.Trim('-')
    if ($name.Length -gt 40) { $name = $name.Substring(0, 40).TrimEnd('-') }
    if ($name.Length -lt 2) {
        throw "Cannot derive a valid resource namespace from '$Value'."
    }
    return $name
}

function Get-ShortHash {
    param([Parameter(Mandatory = $true)][string]$Value)

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hashBytes = $sha256.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hashBytes) -replace '-', '').Substring(0, 6).ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

# ── Derived names ────────────────────────────────────────────────────────────

$Prefix = $Prefix.ToLowerInvariant()
$Location = $Location.ToLowerInvariant()
if ($Prefix.Length -lt 3 -or $Prefix.Length -gt 40 -or
    $Prefix -notmatch '^[a-z0-9][a-z0-9-]*[a-z0-9]$' -or
    $Prefix -match '--') {
    throw "Prefix must be 3-40 lowercase letters, numbers, or single dashes; it must start and end with a letter or number."
}
if ($Topology -eq "TeamIsolated" -and $ProjectCount -ne 1) {
    throw "TeamIsolated supports exactly one project. Run deploy.ps1 once per team with a unique Prefix, or explicitly choose -Topology SharedProjects."
}
if ($Topology -eq "SharedProjects" -and $ProjectCount -lt 2) {
    throw "SharedProjects requires ProjectCount 2 or greater."
}

$estimatedIndexesPerProject = 7
$searchIndexLimits = @{
    basic     = 15
    standard  = 50
    standard2 = 200
}
$estimatedIndexCount = $ProjectCount * $estimatedIndexesPerProject
if ($estimatedIndexCount -gt $searchIndexLimits[$SearchSku]) {
    throw "$SearchSku supports at most $($searchIndexLimits[$SearchSku]) indexes, while this workshop topology reserves approximately $estimatedIndexCount ($estimatedIndexesPerProject per project). Select a larger SearchSku or fewer projects."
}

$rgName          = "$Prefix-rg"
$foundryName     = "$Prefix-foundry"
$searchName      = "$Prefix-search"
$storageBase     = ($Prefix -replace '[^a-z0-9]', '') + "blob"
$storageName     = $storageBase
$appInsightsName = ($Prefix -replace '[^a-z0-9]', '') + "insights"

# Build project name list
if ($ProjectCount -eq 1) {
    $projectNames = @("$Prefix-project")
} else {
    $projectNames = 1..$ProjectCount | ForEach-Object {
        "$Prefix-project-{0:D2}" -f $_
    }
}

# Storage names are global. Preserve a deterministic hash when truncating so
# long team prefixes don't collapse to the same first 24 characters.
if ($storageName.Length -gt 24) {
    $storageName = $storageBase.Substring(0, 18) + (Get-ShortHash $Prefix)
}

$projectNamespaces = @{}
foreach ($projName in $projectNames) {
    $projectNamespaces[$projName] = ConvertTo-ResourceNamespace $projName
}
if (@($projectNamespaces.Values | Select-Object -Unique).Count -ne $projectNames.Count) {
    throw "Project names produced duplicate resource namespaces. Choose a different Prefix."
}

# Resolve access-manifest entries before any Azure mutation. Entries use Entra
# object IDs directly, so deployment doesn't require Microsoft Graph read access.
$accessAssignments = @()
if ($AccessManifestPath) {
    $resolvedManifestPath = (Resolve-Path $AccessManifestPath).Path
    $accessManifest = Get-Content -Raw $resolvedManifestPath | ConvertFrom-Json
    if (-not $accessManifest.assignments) {
        throw "Access manifest '$resolvedManifestPath' must contain a non-empty 'assignments' array."
    }

    foreach ($entry in @($accessManifest.assignments)) {
        $entryProperties = @($entry.PSObject.Properties.Name)
        if ("principalId" -notin $entryProperties -or
            -not $entry.principalId -or
            $entry.principalId -notmatch '^[0-9a-fA-F-]{36}$') {
            throw "Every access assignment requires a principalId containing an Entra object ID."
        }
        if ("principalType" -notin $entryProperties -or
            $entry.principalType -notin @("Group", "User", "ServicePrincipal", "ForeignGroup")) {
            throw "principalType for '$($entry.principalId)' must be Group, User, ServicePrincipal, or ForeignGroup."
        }

        $targetProject = $null
        if ("projectName" -in $entryProperties -and $entry.projectName) {
            $targetProject = [string]$entry.projectName
            if ($targetProject -notin $projectNames) {
                throw "Access assignment projectName '$targetProject' is not one of: $($projectNames -join ', ')."
            }
        } elseif ("projectIndex" -in $entryProperties -and $null -ne $entry.projectIndex) {
            $projectIndex = [int]$entry.projectIndex
            if ($projectIndex -lt 1 -or $projectIndex -gt $ProjectCount) {
                throw "Access assignment projectIndex '$projectIndex' must be between 1 and $ProjectCount."
            }
            $targetProject = $projectNames[$projectIndex - 1]
        } elseif ($ProjectCount -eq 1) {
            $targetProject = $projectNames[0]
        } else {
            throw "Each SharedProjects access assignment requires projectIndex or projectName."
        }

        $displayName = if ("displayName" -in $entryProperties -and $entry.displayName) {
            [string]$entry.displayName
        } else {
            [string]$entry.principalId
        }
        $accessAssignments += [pscustomobject]@{
            PrincipalId   = ([string]$entry.principalId).ToLowerInvariant()
            PrincipalType = [string]$entry.principalType
            DisplayName   = $displayName
            ProjectName   = $targetProject
        }
    }
}

# ── Pre-flight ───────────────────────────────────────────────────────────────

Write-Step "Pre-flight checks"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required. Install it, then run 'az login --tenant <tenant-id>'."
}
$azVersionText = az version --query '"azure-cli"' --output tsv 2>$null
if (-not $azVersionText) {
    throw "Azure CLI is installed but could not run. Verify the installation and try again."
}
Write-Ok "Azure CLI: $azVersionText"

if ($SubscriptionId) {
    Invoke-Az account set --subscription $SubscriptionId | Out-Null
}

$accountRaw = Get-AzOrNull account show --output json
if (-not $accountRaw) {
    throw "No active Azure CLI session. Run 'az login --tenant <tenant-id>' and select the target subscription."
}
$account = $accountRaw | ConvertFrom-Json
$subId = $account.id
$tenantId = $account.tenantId
Write-Ok "Subscription: $($account.name) ($subId)"
Write-Ok "Tenant: $tenantId"
Write-Ok "Topology: $Topology ($ProjectCount project(s), Search SKU $SearchSku)"

if (-not $SkipQuotaCheck) {
    $usageRaw = Get-AzOrNull cognitiveservices usage list --location $Location --output json
    if ($usageRaw) {
        $usage = @($usageRaw | ConvertFrom-Json)
        $limited = @($usage | Where-Object { $_.limit -gt 0 })
        Write-Ok "Cognitive Services quota endpoint is available in $Location ($($limited.Count) quota line(s))"
    } else {
        throw "Could not query Cognitive Services quota in '$Location'. Verify the region, provider registration, and caller permissions, or rerun with -SkipQuotaCheck after manual validation."
    }
} else {
    Write-Skip "Quota API check skipped; model/region capacity must be validated manually before delivery"
}

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
$callerPrincipalType = if ($account.user.type -eq "user") { "User" } else { "ServicePrincipal" }

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
    $deletedRaw = Get-AzOrNull cognitiveservices account list-deleted --query "[?name=='$foundryName']" --output json
    $deleted = if ($deletedRaw) { $deletedRaw | ConvertFrom-Json } else { @() }
    if (@($deleted).Count -gt 0) {
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

    # Wait for the account to fully provision before creating child resources.
    # Without this, project creation fails with "Parent account does not provision correctly".
    Write-Host "   ⏳ Waiting for Foundry account provisioning..." -ForegroundColor Yellow
    do {
        Start-Sleep -Seconds 10
        $provState = az cognitiveservices account show --name $foundryName --resource-group $rgName --query "properties.provisioningState" --output tsv 2>$null
    } while ($provState -ne "Succeeded")
    Write-Ok "Foundry account provisioning complete"
}

# Always verify the account is fully provisioned before proceeding.
# Even a pre-existing account can be stuck in a non-Succeeded state
# (e.g. after a partial deploy), causing project creation to fail with
# "Parent account does not provision correctly".
$provState = az cognitiveservices account show --name $foundryName --resource-group $rgName --query "properties.provisioningState" --output tsv 2>$null
if ($provState -ne "Succeeded") {
    Write-Host "   ⏳ Account provisioning state: $provState — waiting..." -ForegroundColor Yellow
    $maxRetries = 30   # 30 × 10s = 5 min max wait
    $retries = 0
    do {
        Start-Sleep -Seconds 10
        $retries++
        $provState = az cognitiveservices account show --name $foundryName --resource-group $rgName --query "properties.provisioningState" --output tsv 2>$null
        if ($provState) { $provState = $provState.Trim() }
        if (-not $provState) {
            Write-Host "   ⚠️  Empty response from az (retry $retries/$maxRetries)..." -ForegroundColor Yellow
        } else {
            Write-Host "   ⏳ Provisioning state: $provState (attempt $retries/$maxRetries)" -ForegroundColor Yellow
        }
    } while ($provState -ne "Succeeded" -and $retries -lt $maxRetries)
    if ($provState -ne "Succeeded") {
        throw "Foundry account provisioning failed after $maxRetries attempts. Last state: '$provState'"
    }
    Write-Ok "Foundry account provisioning complete"
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
        $projUrl = "https://management.azure.com$projResId`?api-version=$FoundryArmApiVersion"
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
    $existing = Get-AzOrNull rest --method get --url "$hostUrlBase`?api-version=$FoundryArmApiVersion" --query "properties.provisioningState" --output tsv
    if ($existing) { $existing = $existing.Trim() }
    if ($existing -eq "Succeeded") {
        Write-Skip "$Label capability host exists"
        return
    }
    if (-not $existing -or $existing -eq "NotFound") {
        $body = '{"properties":{"capabilityHostKind":"Agents"}}'
        $f = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $f -Value $body -Encoding UTF8
        Invoke-Az rest --method put --url "$hostUrlBase`?api-version=$FoundryArmApiVersion" `
            --body "@$f" --headers "Content-Type=application/json" --output none
        Remove-Item $f
    }
    # Poll until provisioning completes (tolerate empty responses from port exhaustion)
    $maxRetries = 30
    $retries = 0
    do {
        Start-Sleep -Seconds 10
        $retries++
        $state = Get-AzOrNull rest --method get --url "$hostUrlBase`?api-version=$FoundryArmApiVersion" --query "properties.provisioningState" --output tsv
        if ($state) { $state = $state.Trim() }
        if (-not $state) {
            Write-Host "   ⚠️  Empty response polling $Label capability host (retry $retries/$maxRetries)..." -ForegroundColor Yellow
        }
    } while ($state -ne "Succeeded" -and $state -ne "Failed" -and $retries -lt $maxRetries)
    if ($state -eq "Succeeded") {
        Write-Ok "$Label capability host ready"
    } else {
        throw "$Label capability host provisioning failed after $retries attempts. Last state: '$state'"
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

$modelCatalogRaw = Get-AzOrNull cognitiveservices account list-models `
    --name $foundryName --resource-group $rgName --output json
if (-not $modelCatalogRaw) {
    throw "Could not list models available to '$foundryName' in '$Location'. Region and subscription availability must be known before deployment."
}
$modelCatalog = @($modelCatalogRaw | ConvertFrom-Json)

foreach ($m in $models) {
    $availableModel = @($modelCatalog | Where-Object {
        $_.name -eq $m.Model -and $_.version -eq $m.Version -and $_.format -eq "OpenAI"
    })
    if ($availableModel.Count -eq 0) {
        throw "Model '$($m.Model)' version '$($m.Version)' isn't currently available for this subscription in '$Location'. Select a supported region/version after checking the Foundry model catalog and quota."
    }
    $availableSku = @($availableModel[0].skus | Where-Object { $_.name -eq $m.Sku })
    if ($availableSku.Count -eq 0) {
        throw "Deployment type '$($m.Sku)' isn't available for '$($m.Model)' version '$($m.Version)' in '$Location'."
    }
    if ($availableSku[0].capacity.maximum -and $m.Capacity -gt $availableSku[0].capacity.maximum) {
        throw "Requested capacity $($m.Capacity) for '$($m.Name)' exceeds the current model maximum $($availableSku[0].capacity.maximum) in '$Location'."
    }

    $existing = Get-AzOrNull cognitiveservices account deployment show `
        --name $foundryName --resource-group $rgName `
        --deployment-name $m.Name --output json
    if ($existing) {
        Write-Skip "$($m.Name) already deployed"
        continue
    }

    if (-not $SkipQuotaCheck) {
        $usageName = $availableSku[0].usageName
        $quotaLine = @($usage | Where-Object { $_.name.value -eq $usageName })
        if (-not $usageName -or $quotaLine.Count -eq 0) {
            throw "No quota line was found for '$($m.Model)' / '$($m.Sku)' in '$Location'. Request quota or select another supported region."
        }
        $remainingCapacity = [int]$quotaLine[0].limit - [int]$quotaLine[0].currentValue
        if ($remainingCapacity -lt $m.Capacity) {
            throw "Insufficient quota for '$($m.Name)' in '$Location': requested $($m.Capacity), remaining $remainingCapacity ($usageName)."
        }
    }

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

# ── 5. Azure AI Search ──────────────────────────────────────────────────────

Write-Step "AI Search: $searchName"
$searchExists = Get-AzOrNull search service show --name $searchName --resource-group $rgName --output json
if ($searchExists) {
    $existingSearch = $searchExists | ConvertFrom-Json
    if ($existingSearch.sku.name -ne $SearchSku) {
        throw "Existing Search service '$searchName' uses SKU '$($existingSearch.sku.name)', but '$SearchSku' was requested. Use the original value or a new Prefix."
    }
    Write-Skip "Already exists"
} else {
    Invoke-Az search service create `
        --name $searchName `
        --resource-group $rgName `
        --location $Location `
        --sku $SearchSku `
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

# Agents, local scripts, and participants all use Microsoft Entra credentials.
# Roles-only removes the shared admin-key bypass and makes RBAC authoritative.
# New Search services are created with authOptions.apiKeyOnly. Azure rejects a
# disableLocalAuth update while that property is present, so remove authOptions
# and enable roles-only authentication atomically through ARM.
Write-Host "   ⚙️  Enabling Microsoft Entra-only data-plane authentication..." -ForegroundColor Yellow
Invoke-Az resource update `
    --ids $searchResourceId `
    --api-version "2025-05-01" `
    --set properties.disableLocalAuth=true `
    --remove properties.authOptions `
    --output none
Write-Ok "Search authentication set to roles only"

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
        --min-tls-version TLS1_2 `
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
$aiWorkspaceResourceId = $aiJson.workspaceResourceId
if (-not $aiWorkspaceResourceId) {
    throw "Application Insights '$appInsightsName' has no Log Analytics workspace. Workspace-based Application Insights is required for trace review."
}

# ── 8. RBAC Assignments ─────────────────────────────────────────────────────

Write-Step "RBAC role assignments"

function Ensure-PrincipalRoleAssignment {
    param(
        [string]$PrincipalId,
        [ValidateSet("Group", "User", "ServicePrincipal", "ForeignGroup")]
        [string]$PrincipalType,
        [string]$RoleDefinitionId,
        [string]$RoleLabel,
        [string]$Scope,
        [string]$Label
    )
    $raw = Get-AzOrNull role assignment list --scope $Scope --output json
    $existing = if ($raw) { $raw | ConvertFrom-Json } else { @() }
    $exact = @($existing | Where-Object {
        $_.principalId -eq $PrincipalId -and
        $_.scope -eq $Scope -and
        $_.roleDefinitionId -match "/$RoleDefinitionId$"
    })
    if ($exact.Count -gt 0) {
        Write-Skip "$Label → $RoleLabel (exists)"
    } else {
        try {
            Invoke-Az role assignment create `
                --assignee-object-id $PrincipalId `
                --assignee-principal-type $PrincipalType `
                --role $RoleDefinitionId `
                --scope $Scope `
                --output none
            Write-Ok "$Label → $RoleLabel"
        } catch {
            if ($_.Exception.Message -match 'RoleAssignmentExists') {
                Write-Skip "$Label → $RoleLabel (exists)"
            } else {
                throw
            }
        }
    }
}

$storageResourceId = "/subscriptions/$subId/resourceGroups/$rgName/providers/Microsoft.Storage/storageAccounts/$storageName"

# Foundry account MI can manage index definitions and content for account-level
# connections and vectorization workflows.
Ensure-PrincipalRoleAssignment $foundryMI "ServicePrincipal" $SearchServiceContributorRoleId "Search Service Contributor" $searchResourceId "Foundry MI"
Ensure-PrincipalRoleAssignment $foundryMI "ServicePrincipal" $SearchIndexDataContributorRoleId "Search Index Data Contributor" $searchResourceId "Foundry MI"

$projectManagedIdentities = @{}
foreach ($projName in $projectNames) {
    $projResId = $projectResourceIds[$projName]
    $projMi = Get-AzOrNull rest --method get `
        --url "https://management.azure.com$projResId`?api-version=$FoundryArmApiVersion" `
        --query "identity.principalId" --output tsv
    if ($projMi) {
        $projMi = $projMi.Trim()
        $projectManagedIdentities[$projName] = $projMi
        Ensure-PrincipalRoleAssignment $projMi "ServicePrincipal" $FoundryUserRoleId "Foundry User" $foundryResourceId "$projName MI"
        Ensure-PrincipalRoleAssignment $projMi "ServicePrincipal" $SearchServiceContributorRoleId "Search Service Contributor" $searchResourceId "$projName MI"
        Ensure-PrincipalRoleAssignment $projMi "ServicePrincipal" $SearchIndexDataContributorRoleId "Search Index Data Contributor" $searchResourceId "$projName MI"
    } else {
        throw "Could not resolve the managed identity for project '$projName'."
    }
}

# Search MI → Foundry: call OpenAI models
Ensure-PrincipalRoleAssignment $searchMI "ServicePrincipal" $CognitiveServicesOpenAIUserRoleId "Cognitive Services OpenAI User" $foundryResourceId "Search MI"

# Deployer gets the same keyless data-plane permissions required to seed and
# verify the workshop. Foundry User is referenced by stable role ID because the
# role was recently renamed from Azure AI User.
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $FoundryUserRoleId "Foundry User" $foundryResourceId "Deployer ($callerUpn)"
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $SearchServiceContributorRoleId "Search Service Contributor" $searchResourceId "Deployer ($callerUpn)"
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $SearchIndexDataContributorRoleId "Search Index Data Contributor" $searchResourceId "Deployer ($callerUpn)"
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $SearchIndexDataReaderRoleId "Search Index Data Reader" $searchResourceId "Deployer ($callerUpn)"
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $StorageBlobDataContributorRoleId "Storage Blob Data Contributor" $storageResourceId "Deployer ($callerUpn)"
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $MonitoringReaderRoleId "Monitoring Reader" $aiResourceId "Deployer ($callerUpn)"
Ensure-PrincipalRoleAssignment $callerId $callerPrincipalType $LogAnalyticsReaderRoleId "Log Analytics Reader" $aiWorkspaceResourceId "Deployer ($callerUpn)"

# Team/user assignments are deliberately scoped to one Foundry project. Search
# and Storage built-in data roles remain service-wide; only TeamIsolated is a
# security boundary. SharedProjects relies on collision-safe namespaces.
foreach ($assignment in $accessAssignments) {
    $principalLabel = "$($assignment.DisplayName) [$($assignment.PrincipalType)]"
    $projectScope = $projectResourceIds[$assignment.ProjectName]
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $ReaderRoleId "Reader" $foundryResourceId $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $FoundryUserRoleId "Foundry User" $projectScope $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $SearchServiceContributorRoleId "Search Service Contributor" $searchResourceId $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $SearchIndexDataContributorRoleId "Search Index Data Contributor" $searchResourceId $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $SearchIndexDataReaderRoleId "Search Index Data Reader" $searchResourceId $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $StorageBlobDataContributorRoleId "Storage Blob Data Contributor" $storageResourceId $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $MonitoringReaderRoleId "Monitoring Reader" $aiResourceId $principalLabel
    Ensure-PrincipalRoleAssignment $assignment.PrincipalId $assignment.PrincipalType $LogAnalyticsReaderRoleId "Log Analytics Reader" $aiWorkspaceResourceId $principalLabel
}

# ── 9. Foundry Project Connections (per project) ────────────────────────────

Write-Step "Foundry project connections"

$apiVersion = $FoundryArmApiVersion
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
    $connRaw = Get-AzOrNull rest --method get --url "$projApiBase/connections?api-version=$apiVersion" --query "value[?properties.category=='CognitiveSearch'].name" --output json
    $existingConn = if ($connRaw) { $connRaw | ConvertFrom-Json } else { @() }
    if (@($existingConn).Count -gt 0) {
        $actualSearchConn = @($existingConn)[0]
        Write-Skip "$projName → Search connection exists: $actualSearchConn"
    } else {
        $actualSearchConn = $searchConnName
        $searchConnFile = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $searchConnFile -Value $searchConnBody -Encoding UTF8
        try {
            Invoke-Az rest --method put `
                --url "$projApiBase/connections/$($searchConnName)?api-version=$apiVersion" `
                --body "@$searchConnFile" `
                --headers "Content-Type=application/json" `
                --output none
            Write-Ok "$projName → Search connection: $searchConnName"
        } catch {
            if ($_.Exception.Message -match 'already exist') {
                Write-Skip "$projName → Search connection already exists (created externally)"
            } else { throw }
        } finally { Remove-Item $searchConnFile -ErrorAction SilentlyContinue }
    }

    # AppInsights connection
    $aiConnRaw = Get-AzOrNull rest --method get --url "$projApiBase/connections?api-version=$apiVersion" --query "value[?properties.category=='AppInsights'].name" --output json
    $existingAiConn = if ($aiConnRaw) { $aiConnRaw | ConvertFrom-Json } else { @() }
    if (@($existingAiConn).Count -gt 0) {
        Write-Skip "$projName → AppInsights connection exists: $(@($existingAiConn)[0])"
    } else {
        $aiConnFile = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $aiConnFile -Value $aiConnBody -Encoding UTF8
        try {
            Invoke-Az rest --method put `
                --url "$projApiBase/connections/$($aiConnName)?api-version=$apiVersion" `
                --body "@$aiConnFile" `
                --headers "Content-Type=application/json" `
                --output none
            Write-Ok "$projName → AppInsights connection: $aiConnName"
        } catch {
            if ($_.Exception.Message -match 'already exist') {
                Write-Skip "$projName → AppInsights connection already exists (created externally)"
            } else { throw }
        } finally { Remove-Item $aiConnFile -ErrorAction SilentlyContinue }
    }

    # Store connection name for .env generation
    $searchConnNames[$projName] = if (@($existingConn).Count -gt 0) { @($existingConn)[0] } else { $searchConnName }
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
    $resourceNamespace = $projectNamespaces[$ProjectName]
    $projectResourceId = $projectResourceIds[$ProjectName]
    $content = @"
# Workshop identity and Azure resource scope
WORKSHOP_TOPOLOGY=$Topology
WORKSHOP_RESOURCE_NAMESPACE=$resourceNamespace
AZURE_SUBSCRIPTION_ID=$subId
AZURE_RESOURCE_GROUP=$rgName
AZURE_LOCATION=$Location

# Microsoft Foundry
FOUNDRY_ACCOUNT_NAME=$foundryName
FOUNDRY_PROJECT_NAME=$ProjectName
FOUNDRY_PROJECT_RESOURCE_ID=$projectResourceId
FOUNDRY_PROJECT_ENDPOINT=$endpoint
FOUNDRY_MODEL=gpt-5.4-mini

# Observability & Evaluation labs
TENANT_ID=$tenantId
WORKSHOP_ALLOW_CLEANUP=false

# Azure AI Search
AZURE_SEARCH_SERVICE_NAME=$searchName
AZURE_SEARCH_RESOURCE_ID=$searchResourceId
AZURE_SEARCH_ENDPOINT=$searchEndpoint
AZURE_SEARCH_INDEX=$resourceNamespace-bls-corpus
AZURE_SEARCH_RO_INDEX=$resourceNamespace-raamopdrachten
AZURE_SEARCH_CREW_INDEX=$resourceNamespace-crew
AZURE_SEARCH_CONNECTION_NAME=$SearchConnectionName
LAB_SEARCH_INDEX=$resourceNamespace-bls-corpus
FOUNDRY_IQ_KNOWLEDGE_BASE=$resourceNamespace-grid-operations-kb
FOUNDRY_IQ_PROCEDURES_INDEX=$resourceNamespace-bls-corpus
FOUNDRY_IQ_RAAMOPDRACHTEN_INDEX=$resourceNamespace-raamopdrachten
FOUNDRY_IQ_CREW_INDEX=$resourceNamespace-crew
FOUNDRY_IQ_PROCEDURES_SOURCE=$resourceNamespace-bls-knowledge-source
FOUNDRY_IQ_RAAMOPDRACHTEN_SOURCE=$resourceNamespace-raamopdrachten-knowledge-source
FOUNDRY_IQ_CREW_SOURCE=$resourceNamespace-crew-knowledge-source
FOUNDRY_IQ_MCP_CONNECTION_NAME=$resourceNamespace-grid-operations-kb-connection
FOUNDRY_IQ_API_VERSION=2026-05-01-preview
FOUNDRY_IQ_MODEL=gpt-4.1-mini

# Azure Blob Storage
AZURE_STORAGE_ACCOUNT_NAME=$storageName
AZURE_STORAGE_RESOURCE_ID=$storageResourceId
AZURE_STORAGE_ACCOUNT_URL=$storageUrl
AZURE_STORAGE_CREW_CONTAINER=$resourceNamespace-crew-data
AZURE_STORAGE_CREW_BLOB=crew.json
AZURE_STORAGE_RO_BLOB=raamopdrachten.json

# Foundry Agent Names (set after running scripts/deploy_agents.py)
DRAAD_RETRIEVER_AGENT=draad-procedure-retriever-$resourceNamespace
DRAAD_MATCHER_AGENT=draad-dispatch-matcher-$resourceNamespace
DRAAD_REVIEWER_AGENT=draad-dispatch-reviewer-$resourceNamespace
DRAAD_QA_AGENT=draad-qa-assistant-$resourceNamespace

# FastAPI
ALLOWED_ORIGINS=http://localhost:3000

# Tuning
SEARCH_TOP_K=6
MAX_REVISIONS=2
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
Write-Host " Topology:          $Topology"
Write-Host " Foundry:           $foundryName"
Write-Host " Projects:          $($projectNames -join ', ')"
Write-Host " Search:            $searchName ($SearchSku, roles only)"
Write-Host " Storage:           $storageName"
Write-Host " App Insights:      $appInsightsName"
Write-Host " Access entries:    $($accessAssignments.Count)"
Write-Host ""
if ($ProjectCount -gt 1) {
    Write-Host " Project endpoints:" -ForegroundColor Yellow
    foreach ($p in $projectNames) {
        Write-Host "   • $p [$($projectNamespaces[$p])]"
        Write-Host "     https://$foundryName.services.ai.azure.com/api/projects/$p"
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
Write-Host "   1. Validate deployment: .\setup\Test-WorkshopDeployment.ps1 -Prefix `"$Prefix`" -Topology $Topology -ProjectCount $ProjectCount -SearchSku $SearchSku"
Write-Host "   2. Participant preflight: .\setup\Test-WorkshopPrerequisites.ps1 -EnvironmentFile .env"
Write-Host "   3. Seed Search/Storage: python app/scripts/setup_search.py --all"
