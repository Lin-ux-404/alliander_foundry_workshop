<#
.SYNOPSIS
    Runs read-only participant checks for a deployed workshop environment.

.DESCRIPTION
    Validates local tooling, the active Azure CLI tenant/subscription, token
    acquisition, Foundry project visibility, Azure AI Search data-plane access,
    and Blob Storage data-plane access. Safe to run repeatedly.

.EXAMPLE
    .\setup\Test-WorkshopPrerequisites.ps1 -EnvironmentFile .env
#>

[CmdletBinding()]
param(
    [string]$EnvironmentFile = (Join-Path $PSScriptRoot "..\.env"),
    [string]$PythonPath = "",
    [switch]$SkipDataPlane
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$script:Failures = 0
$script:Warnings = 0

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

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#' -or [string]::IsNullOrWhiteSpace($line)) { continue }
        $separator = $line.IndexOf('=')
        if ($separator -lt 1) { continue }
        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        $values[$key] = $value
    }
    return $values
}

function Require-Setting {
    param(
        [hashtable]$Values,
        [string]$Name
    )

    if (-not $Values.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Values[$Name])) {
        Write-Fail "Environment setting '$Name' is missing."
        return $null
    }
    return $Values[$Name]
}

Write-Host "`nWorkshop participant preflight" -ForegroundColor Cyan
Write-Host "Environment: $EnvironmentFile`n"

if (-not (Test-Path $EnvironmentFile)) {
    Write-Fail "Environment file not found: $EnvironmentFile"
    exit 1
}
$settings = Read-DotEnv (Resolve-Path $EnvironmentFile).Path

$requiredNames = @(
    "TENANT_ID",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "FOUNDRY_PROJECT_RESOURCE_ID",
    "FOUNDRY_PROJECT_ENDPOINT",
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_STORAGE_ACCOUNT_NAME"
)
$required = @{}
foreach ($name in $requiredNames) {
    $required[$name] = Require-Setting $settings $name
}
if ($script:Failures -gt 0) { exit 1 }
Write-Pass "Environment file contains the required non-secret settings."

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Fail "Azure CLI is not installed or isn't on PATH."
} else {
    $azVersion = az version --query '"azure-cli"' --output tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and $azVersion) {
        Write-Pass "Azure CLI $azVersion is available."
    } else {
        Write-Fail "Azure CLI couldn't return its version."
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoVenvPython = if ($IsWindows) {
    Join-Path $repoRoot ".venv\Scripts\python.exe"
} else {
    Join-Path $repoRoot ".venv/bin/python"
}

$pythonExecutable = $null
if ($PythonPath) {
    if (Test-Path $PythonPath) {
        $pythonExecutable = (Resolve-Path $PythonPath).Path
    } else {
        Write-Fail "Requested Python executable wasn't found: $PythonPath"
    }
} elseif (Test-Path $repoVenvPython) {
    $pythonExecutable = (Resolve-Path $repoVenvPython).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($pythonCommand) {
        $pythonExecutable = $pythonCommand.Source
    }
}

if (-not $pythonExecutable) {
    Write-Fail "Python isn't installed or isn't on PATH."
} else {
    $pythonVersionText = & $pythonExecutable --version 2>&1
    $pythonMatch = [regex]::Match("$pythonVersionText", '(\d+)\.(\d+)\.(\d+)')
    if (-not $pythonMatch.Success) {
        Write-Fail "Couldn't determine the Python version."
    } else {
        $pythonVersion = [version]$pythonMatch.Value
        if ($pythonVersion.Major -ne 3 -or $pythonVersion.Minor -ne 12) {
            Write-Fail "Python $pythonVersion at '$pythonExecutable' isn't the validated runtime; Python 3.12 is required."
        } else {
            Write-Pass "Python $pythonVersion is available at '$pythonExecutable'."
        }

        & $pythonExecutable -c "import azure.identity, azure.ai.projects" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Pass "Required Azure Python packages can be imported."
        } else {
            Write-Fail "Required Python packages aren't installed in '$pythonExecutable'. Run: python -m pip install -r requirements.txt"
        }
    }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue) -or
    -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Fail "Node.js and npm are required for the workshop application."
} else {
    $nodeVersionText = (node --version 2>$null).TrimStart('v')
    if ([version]$nodeVersionText -lt [version]"20.0.0") {
        Write-Fail "Node.js $nodeVersionText is too old; Node.js 20 or newer is required."
    } else {
        Write-Pass "Node.js $nodeVersionText and npm are available."
    }
}

if (Get-Command az -ErrorAction SilentlyContinue) {
    $accountRaw = az account show --output json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $accountRaw) {
        Write-Fail "No active Azure CLI session. Run: az login --tenant $($required['TENANT_ID'])"
    } else {
        $account = $accountRaw | ConvertFrom-Json
        if ($account.tenantId -ne $required["TENANT_ID"]) {
            Write-Fail "Azure CLI is using tenant '$($account.tenantId)'; expected '$($required['TENANT_ID'])'."
        } else {
            Write-Pass "Azure CLI is signed in to the expected tenant."
        }
        if ($account.id -ne $required["AZURE_SUBSCRIPTION_ID"]) {
            Write-Fail "Azure CLI is using subscription '$($account.id)'; run: az account set --subscription $($required['AZURE_SUBSCRIPTION_ID'])"
        } else {
            Write-Pass "Azure CLI is using the expected subscription."
        }

        foreach ($scope in @(
            "https://management.azure.com/.default",
            "https://ai.azure.com/.default",
            "https://search.azure.com/.default",
            "https://storage.azure.com/.default"
        )) {
            $token = az account get-access-token --scope $scope --query accessToken --output tsv 2>$null
            if ($LASTEXITCODE -eq 0 -and $token) {
                Write-Pass "Microsoft Entra token acquired for $scope"
            } else {
                Write-Fail "Couldn't acquire a Microsoft Entra token for $scope"
            }
        }

        $projectUrl = "https://management.azure.com$($required['FOUNDRY_PROJECT_RESOURCE_ID'])?api-version=2025-06-01"
        az rest --method get --url $projectUrl --output none 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Pass "Foundry project is visible through Azure Resource Manager."
        } else {
            Write-Fail "Foundry project isn't visible. Verify Reader on the Foundry account and Foundry User on the project."
        }

        if (-not $SkipDataPlane) {
            try {
                $searchToken = az account get-access-token --scope "https://search.azure.com/.default" --query accessToken --output tsv 2>$null
                $searchHeaders = @{ Authorization = "Bearer $searchToken" }
                $searchUri = "$($required['AZURE_SEARCH_ENDPOINT'].TrimEnd('/'))/indexes?api-version=2025-09-01"
                Invoke-RestMethod -Method Get -Uri $searchUri -Headers $searchHeaders | Out-Null
                Write-Pass "Azure AI Search accepts the participant's Entra identity."
            } catch {
                Write-Fail "Azure AI Search data-plane access failed. Required roles are Search Service Contributor, Search Index Data Contributor, and Search Index Data Reader."
            }

            az storage container list `
                --account-name $required["AZURE_STORAGE_ACCOUNT_NAME"] `
                --auth-mode login `
                --output none `
                --only-show-errors 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Pass "Blob Storage accepts the participant's Entra identity."
            } else {
                Write-Fail "Blob Storage data-plane access failed. Verify Storage Blob Data Contributor."
            }
        } else {
            Write-Warn "Search and Storage data-plane checks were skipped."
        }
    }
}

Write-Host ""
if ($script:Failures -gt 0) {
    Write-Host "Preflight failed: $($script:Failures) failure(s), $($script:Warnings) warning(s)." -ForegroundColor Red
    exit 1
}

Write-Host "Preflight passed with $($script:Warnings) warning(s)." -ForegroundColor Green
exit 0
