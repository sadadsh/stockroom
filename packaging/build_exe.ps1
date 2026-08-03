# Compatibility wrapper for the former portable-executable command.
#
# The canonical path is Build-Windows-Package.ps1, which also proves the MSIX
# manifest and App Installer policy. This wrapper emits the same deterministic
# unsigned development executable at dist\Stockroom.exe for existing callers.
[CmdletBinding()]
param(
    [string]$Version = "0.1.0.0",
    [string]$ReleaseInputsRoot = "",
    [switch]$SkipReproducibilityProof
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$packageOutput = Join-Path $repositoryRoot "dist\Windows Package"
if ([string]::IsNullOrWhiteSpace($ReleaseInputsRoot)) {
    $ReleaseInputsRoot = Join-Path $repositoryRoot "work\Portable Release Inputs"
}
$ReleaseInputsRoot = [IO.Path]::GetFullPath($ReleaseInputsRoot)
if ($ReleaseInputsRoot -eq [IO.Path]::GetPathRoot($ReleaseInputsRoot)) {
    throw "ReleaseInputsRoot cannot be a drive root."
}
New-Item -ItemType Directory -Force -Path $ReleaseInputsRoot | Out-Null

function Receive-PinnedInput {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$ExpectedSha256,
        [Parameter(Mandatory)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        $temporary = "$Destination.partial"
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest -Uri $Uri -OutFile $temporary -MaximumRedirection 10
        Move-Item -LiteralPath $temporary -Destination $Destination
    }
    $actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
    if ($actual -cne $ExpectedSha256.ToUpperInvariant()) {
        throw "Pinned release input failed SHA-256 verification: $Destination"
    }
}

# Exact upstream release inputs for the owner-portable EXE. The hashes make a
# changed upstream download fail closed instead of silently changing what a
# fresh PC executes.
$minGitArchive = Join-Path $ReleaseInputsRoot "MinGit-2.55.0.3-64-bit.zip"
Receive-PinnedInput `
    -Uri "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/MinGit-2.55.0.3-64-bit.zip" `
    -ExpectedSha256 "f48e2d2dc74a24454adc6d8fd0ac25bf9c2386f19cfb06202b9465aaad4f9f05" `
    -Destination $minGitArchive

$minGitRoot = Join-Path $ReleaseInputsRoot "MinGit-2.55.0.3"
if (-not (Test-Path -LiteralPath (Join-Path $minGitRoot "cmd\git.exe") -PathType Leaf)) {
    if (Test-Path -LiteralPath $minGitRoot) {
        throw "The pinned MinGit extraction is incomplete: $minGitRoot"
    }
    Expand-Archive -LiteralPath $minGitArchive -DestinationPath $minGitRoot
}

$gitLfsArchive = Join-Path $ReleaseInputsRoot "git-lfs-windows-amd64-v3.7.1.zip"
Receive-PinnedInput `
    -Uri "https://github.com/git-lfs/git-lfs/releases/download/v3.7.1/git-lfs-windows-amd64-v3.7.1.zip" `
    -ExpectedSha256 "8683cdc3d6c029b49393dcebbaa6265bd6efd9abdcf837be855b4cd42e5e80b6" `
    -Destination $gitLfsArchive
$gitLfsRoot = Join-Path $ReleaseInputsRoot "Git LFS 3.7.1"
$gitLfsSource = Join-Path $gitLfsRoot "git-lfs-3.7.1\git-lfs.exe"
if (-not (Test-Path -LiteralPath $gitLfsSource -PathType Leaf)) {
    if (Test-Path -LiteralPath $gitLfsRoot) {
        throw "The pinned Git LFS extraction is incomplete: $gitLfsRoot"
    }
    Expand-Archive -LiteralPath $gitLfsArchive -DestinationPath $gitLfsRoot
}
$gitLfsDestination = Join-Path $minGitRoot "mingw64\bin\git-lfs.exe"
Copy-Item -LiteralPath $gitLfsSource -Destination $gitLfsDestination -Force
if ((Get-FileHash $gitLfsSource -Algorithm SHA256).Hash -cne
    (Get-FileHash $gitLfsDestination -Algorithm SHA256).Hash) {
    throw "The bundled Git LFS executable failed copy verification."
}

$nodeArchive = Join-Path $ReleaseInputsRoot "node-v24.19.0-win-x64.zip"
Receive-PinnedInput `
    -Uri "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip" `
    -ExpectedSha256 "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73" `
    -Destination $nodeArchive
$nodeRoot = Join-Path $ReleaseInputsRoot "node-v24.19.0-win-x64"
if (-not (Test-Path -LiteralPath (Join-Path $nodeRoot "node.exe") -PathType Leaf)) {
    if (Test-Path -LiteralPath $nodeRoot) {
        throw "The pinned Node extraction is incomplete: $nodeRoot"
    }
    Expand-Archive -LiteralPath $nodeArchive -DestinationPath $ReleaseInputsRoot
}
if (-not (Test-Path -LiteralPath (Join-Path $nodeRoot "npm.cmd") -PathType Leaf)) {
    throw "The pinned Node runtime does not contain npm.cmd."
}

$webView2Bootstrapper = Join-Path $ReleaseInputsRoot "MicrosoftEdgeWebView2Setup.exe"
Receive-PinnedInput `
    -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
    -ExpectedSha256 "e99838c51bb3379b244654aa77e33032d42fc2b5d224c5babce432d9fd3dcb28" `
    -Destination $webView2Bootstrapper
if ((Get-AuthenticodeSignature -LiteralPath $webView2Bootstrapper).Status.ToString() -cne "Valid") {
    throw "The pinned WebView2 bootstrapper does not have a valid Microsoft signature."
}

$buildArguments = @{
    Mode = "Fixture"
    Version = $Version
    MinGitRoot = $minGitRoot
    NodeRoot = $nodeRoot
    WebView2BootstrapperPath = $webView2Bootstrapper
    OutputRoot = $packageOutput
}
if ($SkipReproducibilityProof) {
    $buildArguments.SkipReproducibilityProof = $true
}
& (Join-Path $PSScriptRoot "Build-Windows-Package.ps1") @buildArguments
if ($LASTEXITCODE -ne 0) {
    throw "The canonical Windows package build failed."
}

$source = Join-Path $packageOutput "Artifacts\Stockroom.exe"
$destination = Join-Path $repositoryRoot "dist\Stockroom.exe"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Output "Compatibility output: $destination"
