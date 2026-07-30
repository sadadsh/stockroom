[CmdletBinding()]
param(
    [ValidateRange(1, 64)]
    # Windows Git fixture setup launches several subprocesses per test. Twelve pytest workers
    # repeatedly exhausted the host process/pipe capacity and turned unrelated repo.init calls
    # into empty-stderr failures. Four keeps useful parallelism without invalidating the gate.
    [int]$Workers = 4
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Resolve-DotNetSdk {
    $requiredVersion = (
        Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'global.json') |
            ConvertFrom-Json
    ).sdk.version
    $candidates = [System.Collections.Generic.List[string]]::new()
    $command = Get-Command dotnet -CommandType Application -ErrorAction SilentlyContinue
    if ($command) {
        $candidates.Add($command.Source)
    }
    if (-not [string]::IsNullOrWhiteSpace($env:DOTNET_ROOT)) {
        $rootExecutable = Join-Path $env:DOTNET_ROOT 'dotnet.exe'
        if (Test-Path -LiteralPath $rootExecutable -PathType Leaf) {
            $candidates.Add($rootExecutable)
        }
    }
    $workspaceLauncher = 'D:\Workspace\System\Capabilities\Bin\dotnet-sdk.cmd'
    if (Test-Path -LiteralPath $workspaceLauncher -PathType Leaf) {
        $candidates.Add($workspaceLauncher)
    }

    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        $version = & $candidate --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -ceq $requiredVersion) {
            Write-Host ".NET SDK: $version ($candidate)"
            return $candidate
        }
    }
    throw ".NET SDK $requiredVersion is required by global.json"
}

function Enable-KiCadCli {
    $command = Get-Command kicad-cli -CommandType Application -ErrorAction SilentlyContinue
    if (-not $command) {
        $kiCadBin = Join-Path $env:ProgramFiles 'KiCad\10.0\bin'
        $installedCli = Join-Path $kiCadBin 'kicad-cli.exe'
        if (Test-Path -LiteralPath $installedCli -PathType Leaf) {
            $env:PATH = "$kiCadBin;$env:PATH"
            $command = Get-Command kicad-cli -CommandType Application -ErrorAction SilentlyContinue
        }
    }

    if (-not $command) {
        Write-Warning 'KiCad 10 CLI was not found; tests that require it will report skips.'
        return
    }

    $version = & $command.Source version
    if ($LASTEXITCODE -ne 0) {
        throw "kicad-cli version failed with exit code $LASTEXITCODE"
    }
    Write-Host "KiCad CLI: $version ($($command.Source))"
}

function Get-DirectorySnapshot {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $snapshot = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $snapshot
    }

    $root = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    $root = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar)
    $rootPrefix = "$root$([System.IO.Path]::DirectorySeparatorChar)"
    Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
        $fullPath = [System.IO.Path]::GetFullPath($_.FullName)
        if (-not $fullPath.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "snapshot path escaped its root: $fullPath"
        }
        $relative = $fullPath.Substring($rootPrefix.Length).Replace('\', '/')
        $snapshot[$relative] = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
    }
    return $snapshot
}

function Assert-DirectorySnapshotUnchanged {
    param(
        [Parameter(Mandatory)]
        [hashtable]$Before,
        [Parameter(Mandatory)]
        [hashtable]$After
    )

    $changes = [System.Collections.Generic.List[string]]::new()
    foreach ($path in @($Before.Keys | Sort-Object)) {
        if (-not $After.ContainsKey($path)) {
            $changes.Add("removed: $path")
        } elseif ($Before[$path] -ne $After[$path]) {
            $changes.Add("changed: $path")
        }
    }
    foreach ($path in @($After.Keys | Sort-Object)) {
        if (-not $Before.ContainsKey($path)) {
            $changes.Add("added: $path")
        }
    }

    if ($changes.Count) {
        $changes | ForEach-Object { Write-Warning "frontend-dist $_" }
        throw 'the frontend build changed app\frontend-dist; rebuild it before running the gate'
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Write-Host
    Write-Host "== $Name =="
    try {
        & $Command
        $exitCode = $LASTEXITCODE
    } catch {
        $failures.Add("$Name failed: $($_.Exception.Message)")
        Write-Warning $failures[-1]
        return
    }
    if ($exitCode -ne 0) {
        $failures.Add("$Name failed with exit code $exitCode")
        Write-Warning $failures[-1]
    }
}

Push-Location $projectRoot
try {
    $env:QT_QPA_PLATFORM = 'offscreen'

    Write-Host
    Write-Host '== KiCad CLI =='
    try {
        Enable-KiCadCli
    } catch {
        $failures.Add("KiCad CLI failed: $($_.Exception.Message)")
        Write-Warning $failures[-1]
    }

    Invoke-Checked 'GitHub Actions Workflows' {
        $actionlint = @(
            Get-Command actionlint -CommandType Application -ErrorAction SilentlyContinue
        )[0]
        if (-not $actionlint) {
            throw 'actionlint is required; install rhysd.actionlint with winget'
        }
        & $actionlint.Source .github\workflows\ci.yml .github\workflows\release.yml
    }
    Invoke-Checked 'Ruff' {
        & uv run ruff check app\backend scripts tests
    }
    Invoke-Checked 'Backend Type Check' {
        & uv run ty check app\backend\stockroom
    }
    Invoke-Checked 'Native Window Host Tests' {
        $dotnetSdk = Resolve-DotNetSdk
        & $dotnetSdk restore `
            tests\native\Stockroom.WindowHost.Tests\Stockroom.WindowHost.Tests.csproj `
            --locked-mode `
            --nologo
        if ($LASTEXITCODE -ne 0) {
            return
        }
        & $dotnetSdk test `
            tests\native\Stockroom.WindowHost.Tests\Stockroom.WindowHost.Tests.csproj `
            --configuration Release `
            --no-restore `
            --nologo
    }
    Invoke-Checked 'Backend Tests - Parallel Safe' {
        & uv run pytest tests\backend -q -p no:randomly `
            -m 'not live_enrich and not global_windows_mutex and not performance_budget' `
            --dist loadgroup -n $Workers
    }
    Invoke-Checked 'Backend Tests - Serialized Windows And Budgets' {
        & uv run pytest tests\backend -q -p no:randomly `
            -m 'not live_enrich and (global_windows_mutex or performance_budget)' `
            -n 0
    }
    Invoke-Checked 'Frontend Tests' {
        & npm.cmd --prefix app\frontend run test:run
    }
    Invoke-Checked 'Frontend Type Check' {
        & npm.cmd --prefix app\frontend run typecheck
    }
    $distPath = Join-Path $projectRoot 'app\frontend-dist'
    $distBefore = Get-DirectorySnapshot -Path $distPath
    Invoke-Checked 'Frontend Build' {
        & npm.cmd --prefix app\frontend run build
    }
    $distAfter = Get-DirectorySnapshot -Path $distPath

    Write-Host
    Write-Host '== Frontend Dist Synchronization =='
    try {
        Assert-DirectorySnapshotUnchanged -Before $distBefore -After $distAfter
        Write-Host 'app\frontend-dist is synchronized with the current frontend source.'
    } catch {
        $failures.Add("Frontend Dist Synchronization failed: $($_.Exception.Message)")
        Write-Warning $failures[-1]
    }

} finally {
    Pop-Location
}

Write-Host
& git -C $projectRoot status --short
if ($failures.Count) {
    Write-Host
    Write-Host 'Stockroom Windows gate failures:'
    $failures | ForEach-Object { Write-Host "- $_" }
    exit 1
}

Write-Host
Write-Host 'All Stockroom Windows gates passed.'
