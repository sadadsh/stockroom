[CmdletBinding()]
param(
    [switch]$BrowserOnly,
    [switch]$SkipBrowser,
    [string]$EvidenceRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $repositoryRoot "..\.."))
$capabilityBin = Join-Path $workspaceRoot "System\Capabilities\Bin"
if (Test-Path -LiteralPath $capabilityBin -PathType Container) {
    $env:Path = "$capabilityBin;$env:Path"
}
if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $EvidenceRoot = Join-Path $repositoryRoot ".work plans\sdd\2026-08-11-in-app-design-studio\task-15-evidence"
}
$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
if ($EvidenceRoot -eq [IO.Path]::GetPathRoot($EvidenceRoot)) {
    throw "EvidenceRoot cannot be a drive root."
}

$configRoot = Join-Path $EvidenceRoot "config"
$appDataRoot = Join-Path $EvidenceRoot "appdata"
$xdgRoot = Join-Path $EvidenceRoot "xdg"
New-Item -ItemType Directory -Force -Path $configRoot, $appDataRoot, $xdgRoot | Out-Null
$env:STOCKROOM_CONFIG_DIR = $configRoot
$env:APPDATA = $appDataRoot
$env:XDG_CONFIG_HOME = $xdgRoot
$env:STOCKROOM_REPOSITORY_ROOT = $repositoryRoot
$env:STOCKROOM_DESIGN_STUDIO_EVIDENCE = Join-Path $EvidenceRoot "browser"

$playwrightCore = Join-Path $repositoryRoot ".venv\Lib\site-packages\playwright\driver\package\index.mjs"
if (-not (Test-Path -LiteralPath $playwrightCore -PathType Leaf)) {
    throw "The locked Playwright core is missing. Run uv sync --frozen."
}
$env:STOCKROOM_PLAYWRIGHT_CORE = $playwrightCore

function Invoke-Checked {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Command)
    Write-Host ""
    Write-Host "== $Name =="
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

function Get-DistributionManifest {
    $distributionRoot = Join-Path $repositoryRoot "app\frontend-dist"
    return @(
        Get-ChildItem -LiteralPath $distributionRoot -Recurse -File |
            Sort-Object FullName |
            ForEach-Object {
                [ordered]@{
                    path = [IO.Path]::GetRelativePath($distributionRoot, $_.FullName).Replace("\", "/")
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                }
            }
    )
}

Push-Location $repositoryRoot
try {
    if (-not $SkipBrowser) {
        Invoke-Checked "All Scenario DOM Floor" {
            & npm.cmd --prefix app\frontend run test:run -- src/design-studio/allScenarios.browser.test.tsx --maxWorkers=1
        }
        Invoke-Checked "Production Frontend And Scenario Projection" {
            & npm.cmd --prefix app\frontend run build
        }
        Invoke-Checked "Playwright Browser Matrix" {
            & node tests\browser\design-studio.spec.mjs
        }
    }

    if (-not $BrowserOnly) {
        Invoke-Checked "Full Frontend Tests" {
            & npm.cmd --prefix app\frontend run test:run -- --maxWorkers=1
        }
        Invoke-Checked "Frontend Type Check" {
            & npm.cmd --prefix app\frontend run typecheck
        }
        Invoke-Checked "Deterministic Frontend Distribution" {
            & npm.cmd --prefix app\frontend run build
            if ($LASTEXITCODE -ne 0) { throw "First frontend build failed with exit code $LASTEXITCODE." }
            $first = Get-DistributionManifest
            & npm.cmd --prefix app\frontend run build
            if ($LASTEXITCODE -ne 0) { throw "Second frontend build failed with exit code $LASTEXITCODE." }
            $second = Get-DistributionManifest
            $firstJson = $first | ConvertTo-Json -Depth 4
            $secondJson = $second | ConvertTo-Json -Depth 4
            if ($firstJson -cne $secondJson) {
                throw "app/frontend-dist changed between identical production builds."
            }
            $manifestPath = Join-Path $EvidenceRoot "frontend-dist-sha256.json"
            $secondJson | Set-Content -LiteralPath $manifestPath -Encoding utf8
            Write-Host "Frontend distribution is byte-identical across two builds ($($second.Count) paths)."
        }
        Invoke-Checked "Repository Gates" {
            & powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1
        }
    }
} finally {
    Pop-Location
}

Write-Host "Design Studio verification passed. Evidence: $EvidenceRoot"
