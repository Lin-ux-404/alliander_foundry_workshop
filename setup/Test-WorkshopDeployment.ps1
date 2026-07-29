<#
.SYNOPSIS
    Performs read-only operator validation of a workshop deployment.

.DESCRIPTION
    Checks resource provisioning, supported topology, roles-only Search
    authentication, Foundry projects and capability hosts, managed-identity
    RBAC, project connections, model deployments, quota visibility, and access
    manifest role assignments. Safe to run repeatedly.

.EXAMPLE
    .\setup\Test-WorkshopDeployment.ps1 -Prefix workshop-team01 -AccessManifestPath .\setup\access-manifest.example.json
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
    [string]$SubscriptionId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$script:Failures = 0
$script:Warnings = 0
$apiVersion = "2025-06-01"

$roles = @{
    FoundryUser                 = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
    Reader                      = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
    SearchServiceContributor    = "7ca78c08-252a-4471-8644-bb5ff32d4ba0"
    SearchIndexDataContributor  = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
    SearchIndexDataReader       = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
    StorageBlobDataContributor  = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
    CognitiveServicesOpenAIUser = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
    MonitoringReader            = "43d0d8ad-25c7-4714-9337-8ba259a9fe05"
    LogAnalyticsReader          = "73c42c96-874c-492b-b04d-ab87d138a893"
}

function Write-Pass([string]$Message) {
    Write-Host "PASS  $Message" -ForegroundColor Green
}

function Write-Fail([string]$Message) {
    $script:Failures++
    Write-Host "FAIL  $Message" -ForegroundColor Red
}

function Write-Warn([string]$Message) {
    $script:Warnings++
    Write-Host "WARN  $Message" -ForegroundColor Yellow
}

function Get-AzJson {
    param([Parameter(ValueFromRemainingArguments)]$Arguments)

    $ErrorActionPreference = "SilentlyContinue"
    $output = az @Arguments 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    return ($output | ConvertFrom-Json)
}

function Test-Role {
    param(
        [string]$PrincipalId,
        [string]$RoleDefinitionId,
        [string]$RoleLabel,
        [string]$Scope,
        [string]$PrincipalLabel
    )

    $assignments = Get-AzJson role assignment list --scope $Scope --output json
    $exact = @($assignments | Where-Object {
        $_.principalId -eq $PrincipalId -and
        $_.scope -eq $Scope -and
        $_.roleDefinitionId -match "/$RoleDefinitionId$"
    })
    if ($exact.Count -gt 0) {
        Write-Pass "$PrincipalLabel has $RoleLabel at the expected scope."
    } else {
        Write-Fail "$PrincipalLabel is missing $RoleLabel at '$Scope'."
    }
}

function ConvertTo-ResourceNamespace {
    param([string]$Value)
    $name = $Value.ToLowerInvariant() -replace '[^a-z0-9-]', '-'
    $name = ($name -replace '-+', '-').Trim('-')
    if ($name.Length -gt 40) { $name = $name.Substring(0, 40).TrimEnd('-') }
    return $name
}

function Get-ShortHash {
    param([string]$Value)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hashBytes = $sha256.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hashBytes) -replace '-', '').Substring(0, 6).ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Fail "Azure CLI is required."
    exit 1
}

$Prefix = $Prefix.ToLowerInvariant()
$Location = $Location.ToLowerInvariant()
if ($Prefix.Length -lt 3 -or $Prefix.Length -gt 40 -or
    $Prefix -notmatch '^[a-z0-9][a-z0-9-]*[a-z0-9]$' -or
    $Prefix -match '--') {
    Write-Fail "Prefix isn't valid."
    exit 1
}
if ($Topology -eq "TeamIsolated" -and $ProjectCount -ne 1) {
    Write-Fail "TeamIsolated requires ProjectCount 1."
}
if ($Topology -eq "SharedProjects" -and $ProjectCount -lt 2) {
    Write-Fail "SharedProjects requires ProjectCount 2 or greater."
}

$account = Get-AzJson account show --output json
if (-not $account) {
    Write-Fail "No active Azure CLI session."
    exit 1
}
if ($SubscriptionId -and $account.id -ne $SubscriptionId) {
    Write-Fail "Active subscription '$($account.id)' doesn't match requested '$SubscriptionId'."
    exit 1
}
$subId = $account.id

$rgName = "$Prefix-rg"
$foundryName = "$Prefix-foundry"
$searchName = "$Prefix-search"
$storageBase = ($Prefix -replace '[^a-z0-9]', '') + "blob"
$storageName = $storageBase
$appInsightsName = ($Prefix -replace '[^a-z0-9]', '') + "insights"
if ($storageName.Length -gt 24) {
    $storageName = $storageBase.Substring(0, 18) + (Get-ShortHash $Prefix)
}

if ($ProjectCount -eq 1) {
    $projectNames = @("$Prefix-project")
} else {
    $projectNames = @(1..$ProjectCount | ForEach-Object { "$Prefix-project-{0:D2}" -f $_ })
}

$foundryResourceId = "/subscriptions/$subId/resourceGroups/$rgName/providers/Microsoft.CognitiveServices/accounts/$foundryName"
$searchResourceId = "/subscriptions/$subId/resourceGroups/$rgName/providers/Microsoft.Search/searchServices/$searchName"
$storageResourceId = "/subscriptions/$subId/resourceGroups/$rgName/providers/Microsoft.Storage/storageAccounts/$storageName"

Write-Host "`nWorkshop deployment validation" -ForegroundColor Cyan
Write-Host "Subscription: $($account.name) ($subId)"
Write-Host "Topology: $Topology; projects: $ProjectCount; location: $Location`n"

$resourceGroup = Get-AzJson group show --name $rgName --output json
if ($resourceGroup) {
    Write-Pass "Resource group '$rgName' exists."
} else {
    Write-Fail "Resource group '$rgName' doesn't exist."
}

$foundry = Get-AzJson cognitiveservices account show --name $foundryName --resource-group $rgName --output json
if (-not $foundry) {
    Write-Fail "Foundry account '$foundryName' doesn't exist."
} else {
    if ($foundry.properties.provisioningState -eq "Succeeded") {
        Write-Pass "Foundry account provisioning succeeded."
    } else {
        Write-Fail "Foundry account state is '$($foundry.properties.provisioningState)'."
    }
    if ($foundry.location -eq $Location) {
        Write-Pass "Foundry account is in '$Location'."
    } else {
        Write-Fail "Foundry account is in '$($foundry.location)', expected '$Location'."
    }
}

$search = Get-AzJson search service show --name $searchName --resource-group $rgName --output json
if (-not $search) {
    Write-Fail "Search service '$searchName' doesn't exist."
} else {
    if ($search.status -eq "running") {
        Write-Pass "Search service is running."
    } else {
        Write-Fail "Search service status is '$($search.status)'."
    }
    if ($search.sku.name -eq $SearchSku) {
        Write-Pass "Search SKU is '$SearchSku'."
    } else {
        Write-Fail "Search SKU is '$($search.sku.name)', expected '$SearchSku'."
    }
    if ($search.disableLocalAuth -eq $true) {
        Write-Pass "Search API keys are disabled; Microsoft Entra RBAC is authoritative."
    } else {
        Write-Fail "Search API keys are enabled. Redeploy to enforce roles-only authentication."
    }
}

$storage = Get-AzJson storage account show --name $storageName --resource-group $rgName --output json
if ($storage) {
    Write-Pass "Storage account '$storageName' exists."
} else {
    Write-Fail "Storage account '$storageName' doesn't exist."
}

$appInsights = Get-AzJson monitor app-insights component show --app $appInsightsName --resource-group $rgName --output json
if ($appInsights) {
    Write-Pass "Application Insights '$appInsightsName' exists."
    if ($appInsights.workspaceResourceId) {
        Write-Pass "Application Insights uses a Log Analytics workspace."
    } else {
        Write-Fail "Application Insights isn't connected to a Log Analytics workspace."
    }
} else {
    Write-Fail "Application Insights '$appInsightsName' doesn't exist."
}

$projectsUrl = "https://management.azure.com$foundryResourceId/projects?api-version=$apiVersion"
$projects = Get-AzJson rest --method get --url $projectsUrl --query value --output json
if (@($projects).Count -ne $ProjectCount) {
    Write-Fail "Foundry account contains $(@($projects).Count) project(s); expected exactly $ProjectCount."
} else {
    Write-Pass "Foundry account contains exactly $ProjectCount project(s)."
}

$projectResourceIds = @{}
$projectManagedIdentities = @{}
foreach ($projectName in $projectNames) {
    $projectResourceId = "$foundryResourceId/projects/$projectName"
    $projectResourceIds[$projectName] = $projectResourceId
    $projectUrl = "https://management.azure.com$projectResourceId`?api-version=$apiVersion"
    $project = Get-AzJson rest --method get --url $projectUrl --output json
    if (-not $project) {
        Write-Fail "Project '$projectName' doesn't exist."
        continue
    }
    if ($project.properties.provisioningState -eq "Succeeded") {
        Write-Pass "Project '$projectName' provisioning succeeded."
    } else {
        Write-Fail "Project '$projectName' state is '$($project.properties.provisioningState)'."
    }
    if ($project.identity.principalId) {
        $projectManagedIdentities[$projectName] = $project.identity.principalId
        Write-Pass "Project '$projectName' has a system-assigned managed identity."
    } else {
        Write-Fail "Project '$projectName' has no system-assigned managed identity."
    }

    $hostUrl = "https://management.azure.com$projectResourceId/capabilityHosts/agentshost?api-version=$apiVersion"
    $capabilityHost = Get-AzJson rest --method get --url $hostUrl --output json
    if ($capabilityHost -and $capabilityHost.properties.provisioningState -eq "Succeeded") {
        Write-Pass "Project '$projectName' Agents capability host is ready."
    } else {
        Write-Fail "Project '$projectName' Agents capability host isn't ready."
    }

    $connectionUrl = "https://management.azure.com$projectResourceId/connections?api-version=$apiVersion"
    $connections = Get-AzJson rest --method get --url $connectionUrl --query value --output json
    $categories = @($connections | ForEach-Object { $_.properties.category })
    if ("CognitiveSearch" -in $categories -and "AppInsights" -in $categories) {
        Write-Pass "Project '$projectName' has Search and Application Insights connections."
    } else {
        Write-Fail "Project '$projectName' is missing a Search or Application Insights connection."
    }
}

$accountHostUrl = "https://management.azure.com$foundryResourceId/capabilityHosts/agentshost?api-version=$apiVersion"
$accountHost = Get-AzJson rest --method get --url $accountHostUrl --output json
if ($accountHost -and $accountHost.properties.provisioningState -eq "Succeeded") {
    Write-Pass "Account Agents capability host is ready."
} else {
    Write-Fail "Account Agents capability host isn't ready."
}

if ($foundry -and $foundry.identity.principalId -and $search) {
    Test-Role $foundry.identity.principalId $roles.SearchServiceContributor "Search Service Contributor" $searchResourceId "Foundry account MI"
    Test-Role $foundry.identity.principalId $roles.SearchIndexDataContributor "Search Index Data Contributor" $searchResourceId "Foundry account MI"
}
foreach ($projectName in $projectManagedIdentities.Keys) {
    $projectMi = $projectManagedIdentities[$projectName]
    Test-Role $projectMi $roles.FoundryUser "Foundry User" $foundryResourceId "$projectName MI"
    Test-Role $projectMi $roles.SearchServiceContributor "Search Service Contributor" $searchResourceId "$projectName MI"
    Test-Role $projectMi $roles.SearchIndexDataContributor "Search Index Data Contributor" $searchResourceId "$projectName MI"
}
if ($search -and $search.identity.principalId) {
    Test-Role $search.identity.principalId $roles.CognitiveServicesOpenAIUser "Cognitive Services OpenAI User" $foundryResourceId "Search MI"
}

$deployments = Get-AzJson cognitiveservices account deployment list --name $foundryName --resource-group $rgName --output json
$expectedDeployments = @("gpt-5.4-mini", "text-embedding-ada-002", "gpt-4.1-mini")
foreach ($deploymentName in $expectedDeployments) {
    $deployment = @($deployments | Where-Object { $_.name -eq $deploymentName })
    if ($deployment.Count -gt 0 -and $deployment[0].properties.provisioningState -eq "Succeeded") {
        Write-Pass "Model deployment '$deploymentName' is ready."
    } else {
        Write-Fail "Model deployment '$deploymentName' is missing or not ready."
    }
}

$usage = Get-AzJson cognitiveservices usage list --location $Location --output json
if ($usage) {
    Write-Pass "Quota usage is visible in '$Location' ($(@($usage).Count) line(s))."
} else {
    Write-Fail "Quota usage couldn't be queried in '$Location'."
}

$namespaces = @($projectNames | ForEach-Object { ConvertTo-ResourceNamespace $_ })
if (@($namespaces | Select-Object -Unique).Count -eq $ProjectCount) {
    Write-Pass "Every project has a unique resource namespace: $($namespaces -join ', ')."
} else {
    Write-Fail "Project namespaces collide."
}

if ($Topology -eq "SharedProjects") {
    Write-Warn "SharedProjects provides naming isolation only. Search and Storage data-plane roles are service-wide."
    $indexLimits = @{ basic = 15; standard = 50; standard2 = 200 }
    $estimatedIndexes = 7 * $ProjectCount
    if ($estimatedIndexes -le $indexLimits[$SearchSku]) {
        Write-Pass "Estimated index demand ($estimatedIndexes) fits the $SearchSku limit ($($indexLimits[$SearchSku]))."
    } else {
        Write-Fail "Estimated index demand ($estimatedIndexes) exceeds the $SearchSku limit ($($indexLimits[$SearchSku]))."
    }
}

if ($AccessManifestPath) {
    $manifest = Get-Content -Raw (Resolve-Path $AccessManifestPath).Path | ConvertFrom-Json
    foreach ($entry in @($manifest.assignments)) {
        $entryProperties = @($entry.PSObject.Properties.Name)
        if ("principalId" -notin $entryProperties -or -not $entry.principalId) {
            Write-Fail "Access manifest entry is missing principalId."
            continue
        }
        if ("projectName" -in $entryProperties -and $entry.projectName) {
            $projectName = [string]$entry.projectName
        } elseif ("projectIndex" -in $entryProperties -and $null -ne $entry.projectIndex) {
            $manifestProjectIndex = [int]$entry.projectIndex
            if ($manifestProjectIndex -lt 1 -or $manifestProjectIndex -gt $ProjectCount) {
                Write-Fail "Access entry '$($entry.principalId)' has invalid projectIndex '$manifestProjectIndex'."
                continue
            }
            $projectName = $projectNames[$manifestProjectIndex - 1]
        } elseif ($ProjectCount -eq 1) {
            $projectName = $projectNames[0]
        } else {
            Write-Fail "Access entry '$($entry.principalId)' has no project mapping."
            continue
        }
        if ($projectName -notin $projectNames) {
            Write-Fail "Access entry '$($entry.principalId)' maps to unknown project '$projectName'."
            continue
        }
        $label = if ("displayName" -in $entryProperties -and $entry.displayName) {
            $entry.displayName
        } else {
            $entry.principalId
        }
        Test-Role $entry.principalId $roles.Reader "Reader" $foundryResourceId $label
        Test-Role $entry.principalId $roles.FoundryUser "Foundry User" $projectResourceIds[$projectName] $label
        Test-Role $entry.principalId $roles.SearchServiceContributor "Search Service Contributor" $searchResourceId $label
        Test-Role $entry.principalId $roles.SearchIndexDataContributor "Search Index Data Contributor" $searchResourceId $label
        Test-Role $entry.principalId $roles.SearchIndexDataReader "Search Index Data Reader" $searchResourceId $label
        Test-Role $entry.principalId $roles.StorageBlobDataContributor "Storage Blob Data Contributor" $storageResourceId $label
        Test-Role $entry.principalId $roles.MonitoringReader "Monitoring Reader" $appInsights.id $label
        Test-Role $entry.principalId $roles.LogAnalyticsReader "Log Analytics Reader" $appInsights.workspaceResourceId $label
    }
} else {
    Write-Warn "No access manifest was supplied; participant/team assignments weren't validated."
}

Write-Host ""
if ($script:Failures -gt 0) {
    Write-Host "Deployment validation failed: $($script:Failures) failure(s), $($script:Warnings) warning(s)." -ForegroundColor Red
    Write-Host "Role assignments can take several minutes to propagate; rerun this check before investigating a fresh assignment."
    exit 1
}

Write-Host "Deployment validation passed with $($script:Warnings) warning(s)." -ForegroundColor Green
exit 0
