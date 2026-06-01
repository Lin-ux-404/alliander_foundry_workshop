<#
.SYNOPSIS
    Deploys all Azure resources for the Alliander Workshop (labs + DRAAD app).

.DESCRIPTION
    Creates:
      1. Resource Group
      2. AI Foundry account + project (with system-assigned identity)
      3. Model deployments (gpt-5.4-mini, text-embedding-ada-002, gpt-4.1-mini)
      4. Azure AI Search (basic, system-assigned identity)
      5. Storage Account (Standard_LRS)
      6. Application Insights
      7. Foundry ↔ Search ↔ Storage RBAC bindings
      8. Foundry project connections (Search, AppInsights)
      9. .env file

.PARAMETER Prefix
    Naming prefix for all resources (e.g. "alliander-workshop").

.PARAMETER Location
    Azure region. Default: swedencentral.

.PARAMETER SubscriptionId
    Target subscription. Uses current default if omitted.

.EXAMPLE
    .\deploy.ps1 -Prefix "alliander-workshop"
    .\deploy.ps1 -Prefix "myteam-lab" -Location "westeurope"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Prefix,

    [string]$Location = "swedencentral",

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
    $result = az @Args_ 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "az command failed: $result"
    }
    return $result
}

# ── Derived names ────────────────────────────────────────────────────────────

$rgName          = "$Prefix-rg"
$foundryName     = "$Prefix-foundry"
$projectName     = "$Prefix-project"
$searchName      = "$Prefix-search"
$storageName     = ($Prefix -replace '[^a-z0-9]', '') + "blob"
$appInsightsName = ($Prefix -replace '[^a-z0-9]', '') + "insights"

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

$callerInfo = az ad signed-in-user show --output json 2>$null | ConvertFrom-Json
$callerId = $callerInfo.id
$callerUpn = $callerInfo.userPrincipalName
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
$foundryExists = az cognitiveservices account show --name $foundryName --resource-group $rgName --output json 2>$null
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

# ── 3. Foundry Project ──────────────────────────────────────────────────────

Write-Step "Foundry project: $projectName"
$projectResourceId = "$foundryResourceId/projects/$projectName"
$projectExists = az resource show --ids $projectResourceId --output json 2>$null
if ($projectExists) {
    Write-Skip "Already exists"
} else {
    # Use REST API — project needs identity in the body
    $projectBody = @{
        location   = $Location
        properties = @{}
        identity   = @{ type = "SystemAssigned" }
    } | ConvertTo-Json -Compress
    $tmpFile = [System.IO.Path]::GetTempFileName()
    Set-Content -Path $tmpFile -Value $projectBody -Encoding UTF8
    $projectUrl = "https://management.azure.com$projectResourceId`?api-version=2025-04-01-preview"
    Invoke-Az rest --method PUT --url $projectUrl --body "@$tmpFile" --headers "Content-Type=application/json" --output none
    Remove-Item $tmpFile
    Write-Ok "Created"
}

$foundryEndpoint = "https://$foundryName.services.ai.azure.com/api/projects/$projectName"

# ── 4. Model Deployments ────────────────────────────────────────────────────

Write-Step "Model deployments"

$models = @(
    @{ Name = "gpt-5.4-mini";             Model = "gpt-5.4-mini";             Version = "2026-03-17"; Sku = "GlobalStandard"; Capacity = 1000 }
    @{ Name = "text-embedding-ada-002";    Model = "text-embedding-ada-002";    Version = "2";          Sku = "GlobalStandard"; Capacity = 656  }
    @{ Name = "gpt-4.1-mini";             Model = "gpt-4.1-mini";             Version = "2025-04-14"; Sku = "GlobalStandard"; Capacity = 8000 }
)

foreach ($m in $models) {
    $existing = az cognitiveservices account deployment show `
        --name $foundryName --resource-group $rgName `
        --deployment-name $m.Name --output json 2>$null
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
$searchExists = az search service show --name $searchName --resource-group $rgName --output json 2>$null
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

# Get search admin key (needed for .env / index scripts)
$searchKeys = az search admin-key show --service-name $searchName --resource-group $rgName --output json | ConvertFrom-Json
$searchAdminKey = $searchKeys.primaryKey

# ── 6. Storage Account ──────────────────────────────────────────────────────

Write-Step "Storage account: $storageName"
$storageExists = az storage account show --name $storageName --resource-group $rgName --output json 2>$null
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
$aiExists = az monitor app-insights component show --app $appInsightsName --resource-group $rgName --output json 2>$null
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

# ── 8. RBAC Assignments ─────────────────────────────────────────────────────

Write-Step "RBAC role assignments"

function Ensure-RoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$Role,
        [string]$Scope,
        [string]$Label
    )
    $existing = az role assignment list --assignee $PrincipalId --role $Role --scope $Scope --output json 2>$null | ConvertFrom-Json
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
    $existing = az role assignment list --assignee $PrincipalId --role $Role --scope $Scope --output json 2>$null | ConvertFrom-Json
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

# Search MI → Foundry: call OpenAI models
Ensure-RoleAssignment $searchMI "Cognitive Services OpenAI User" $foundryResourceId "Search MI"

# Current user → Foundry User (on the foundry resource)
Ensure-UserRoleAssignment $callerId "Cognitive Services User" $foundryResourceId "User ($callerUpn)"

# Current user → Search Index Data Reader
Ensure-UserRoleAssignment $callerId "Search Index Data Reader" $searchResourceId "User ($callerUpn)"

# Current user → Storage Blob Data Contributor
Ensure-UserRoleAssignment $callerId "Storage Blob Data Contributor" $storageResourceId "User ($callerUpn)"

# ── 9. Foundry Project Connections ───────────────────────────────────────────

Write-Step "Foundry project connections"

$projectApiBase = "https://management.azure.com$projectResourceId"
$apiVersion = "2025-04-01-preview"

# Search connection
$searchConnName = ($storageName -replace 'blob$', 'search') + "conn"
# Use a deterministic short name
$searchConnName = "search-connection"

$searchConnBody = @{
    properties = @{
        category = "CognitiveSearch"
        target   = $searchEndpoint
        authType = "AAD"
    }
} | ConvertTo-Json -Depth 5

$existingConn = az rest --method get --url "$projectApiBase/connections?api-version=$apiVersion" --query "value[?properties.category=='CognitiveSearch'].name" --output json 2>$null | ConvertFrom-Json
if ($existingConn -and $existingConn.Count -gt 0) {
    $searchConnName = $existingConn[0]
    Write-Skip "Search connection exists: $searchConnName"
} else {
    az rest --method put `
        --url "$projectApiBase/connections/$($searchConnName)?api-version=$apiVersion" `
        --body $searchConnBody `
        --output none 2>$null
    Write-Ok "Search connection: $searchConnName"
}

# AppInsights connection
$aiConnName = "appinsights-connection"
$aiConnBody = @{
    properties = @{
        category = "AppInsights"
        target   = $aiConnectionString
        authType = "AAD"
    }
} | ConvertTo-Json -Depth 5

$existingAiConn = az rest --method get --url "$projectApiBase/connections?api-version=$apiVersion" --query "value[?properties.category=='AppInsights'].name" --output json 2>$null | ConvertFrom-Json
if ($existingAiConn -and $existingAiConn.Count -gt 0) {
    Write-Skip "AppInsights connection exists: $($existingAiConn[0])"
} else {
    az rest --method put `
        --url "$projectApiBase/connections/$($aiConnName)?api-version=$apiVersion" `
        --body $aiConnBody `
        --output none 2>$null
    Write-Ok "AppInsights connection: $aiConnName"
}

# ── 10. Generate .env ────────────────────────────────────────────────────────

Write-Step "Generating .env file"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$envPath = Join-Path $repoRoot ".env"

$envContent = @"
# Azure AI Foundry
FOUNDRY_PROJECT_ENDPOINT=$foundryEndpoint
FOUNDRY_MODEL=gpt-5.4-mini

# Azure AI Search
AZURE_SEARCH_ENDPOINT=$searchEndpoint
AZURE_SEARCH_ADMIN_KEY=$searchAdminKey
AZURE_SEARCH_INDEX=idx_bls_corpus
AZURE_SEARCH_RO_INDEX=idx_raamopdrachten
AZURE_SEARCH_CREW_INDEX=idx_crew
AZURE_SEARCH_CONNECTION_NAME=$searchConnName

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

if (Test-Path $envPath) {
    $backup = "$envPath.bak"
    Copy-Item $envPath $backup -Force
    Write-Ok "Backed up existing .env → .env.bak"
}

Set-Content -Path $envPath -Value $envContent -Encoding UTF8
Write-Ok "Written to $envPath"

# ── Summary ──────────────────────────────────────────────────────────────────

Write-Host "`n" -NoNewline
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host " Deployment complete!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host " Resource Group:    $rgName"
Write-Host " Location:          $Location"
Write-Host " Foundry:           $foundryName"
Write-Host " Project:           $projectName"
Write-Host " Endpoint:          $foundryEndpoint"
Write-Host " Search:            $searchName"
Write-Host " Storage:           $storageName"
Write-Host " App Insights:      $appInsightsName"
Write-Host ""
Write-Host " Next steps:" -ForegroundColor Yellow
Write-Host "   1. Run index scripts:      python app/scripts/setup_search.py --all"
Write-Host "   2. Deploy agents:          python app/scripts/deploy_agents.py"
Write-Host "   3. Start backend:          cd app/backend && uvicorn main:app --reload"
Write-Host "   4. Start frontend:         cd app/frontend && npm run dev"
Write-Host ""
