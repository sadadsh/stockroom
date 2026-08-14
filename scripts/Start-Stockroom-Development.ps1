param(
    [string]$RepositoryRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $RepositoryRoot) {
    $RepositoryRoot = Join-Path $PSScriptRoot '..'
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$vite = Join-Path $root 'app\frontend\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    throw 'Development dependencies are missing. Run scripts\Setup-Stockroom-Development.ps1 first.'
}
if (-not $env:LOCALAPPDATA) {
    throw 'LOCALAPPDATA is unavailable.'
}
$stateRoot = Join-Path $env:LOCALAPPDATA 'Stockroom Development'
$env:PYTHONPATH = "$(Join-Path $root 'app\backend');$root"
Write-Host "Stockroom Development: $root"
Write-Host "Logs: $stateRoot\Logs"
& $python -m stockroom.host.development `
    --repository-root $root `
    --state-root $stateRoot
exit $LASTEXITCODE
