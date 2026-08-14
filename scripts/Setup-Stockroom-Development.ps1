param(
    [string]$RepositoryRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $RepositoryRoot) {
    $RepositoryRoot = Join-Path $PSScriptRoot '..'
}
$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
$uv = if ($null -ne $uvCommand) {
    $uvCommand.Source
} else {
    Join-Path $HOME '.local\bin\uv.exe'
}
if (-not (Test-Path -LiteralPath $uv -PathType Leaf)) {
    throw 'uv.exe is unavailable. Install the pinned Python environment tool first.'
}
if ($null -eq (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm.cmd is unavailable. Install the repository-supported Node.js runtime first.'
}

Push-Location $root
try {
    & $uv sync --frozen
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & npm.cmd --prefix app\frontend ci
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
Write-Host 'Stockroom Development dependencies are ready.'
