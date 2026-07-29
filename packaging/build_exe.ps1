# Compatibility wrapper for the former portable-executable command.
#
# The canonical path is Build-Windows-Package.ps1, which also proves the MSIX
# manifest and App Installer policy. This wrapper emits the same deterministic
# unsigned development executable at dist\Stockroom.exe for existing callers.
[CmdletBinding()]
param(
    [string]$Version = "0.1.0.0"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$packageOutput = Join-Path $repositoryRoot "dist\Windows Package"

& (Join-Path $PSScriptRoot "Build-Windows-Package.ps1") `
    -Mode Fixture `
    -Version $Version `
    -OutputRoot $packageOutput
if ($LASTEXITCODE -ne 0) {
    throw "The canonical Windows package build failed."
}

$source = Join-Path $packageOutput "Artifacts\Stockroom.exe"
$destination = Join-Path $repositoryRoot "dist\Stockroom.exe"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Output "Compatibility output: $destination"
