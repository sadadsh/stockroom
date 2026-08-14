[CmdletBinding()]
param(
    [ValidateSet("Fixture", "Production")]
    [string]$Mode = "Fixture",

    [string]$Version = "0.7.0.0",
    [string]$MinimumHostVersion = "0.7.0.0",
    [int]$ProtocolVersion = 1,
    [string]$Publisher = "",
    [string]$FeedBaseUri = "",
    [string]$SigningCertificatePath = "",
    [string]$SigningEnvironmentVariableName = "STOCKROOM_SIGNING_CERT_PASSWORD",
    [string]$TufRootPath = "",
    [int]$TufMetadataVersion = 1,
    [string[]]$TufTargetsKeyPaths = @(),
    [string[]]$TufSnapshotKeyPaths = @(),
    [string[]]$TufTimestampKeyPaths = @(),
    [string]$RollbackReleaseId = "release-bootstrap",
    [string[]]$CompatibleFromReleaseIds = @("release-bootstrap"),
    [string]$TimestampUri = "https://timestamp.digicert.com",
    [long]$SourceDateEpoch = 1704067200,
    [string]$OutputRoot = "",
    [switch]$SkipReproducibilityProof
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PackagingRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$BrandAssetsTool = Join-Path $PackagingRoot "brand_assets.py"
$ContractModule = "packaging.package_contract"
$ReleaseBundleTool = Join-Path $PackagingRoot "release_bundle.py"
$ReleaseFeedModule = "packaging.release_feed"
$WorkerProbeTool = Join-Path $PackagingRoot "package_worker_probe.py"
$SpecPath = Join-Path $PackagingRoot "stockroom.spec"
$SourceIcon = Join-Path $RepositoryRoot "app\backend\stockroom\host\assets\stockroom.ico"
$WindowHostProject = Join-Path $RepositoryRoot "app\desktop\Stockroom.WindowHost\Stockroom.WindowHost.csproj"
$CadConverterProject = Join-Path $RepositoryRoot "app\desktop\Stockroom.CadConverter\Stockroom.CadConverter.csproj"
$WorkspaceDotNetPath = [IO.Path]::GetFullPath(
    (Join-Path $RepositoryRoot "..\..\System\Capabilities\Bin\dotnet-sdk.cmd")
)
$DotNetPath = if (Test-Path -LiteralPath $WorkspaceDotNetPath -PathType Leaf) {
    $WorkspaceDotNetPath
}
else {
    (Get-Command dotnet -CommandType Application -ErrorAction Stop).Source
}
Push-Location $RepositoryRoot
try {
    $DotNetSdkVersion = (& $DotNetPath --version).Trim()
}
finally {
    Pop-Location
}
$PinnedDotNetSdkVersion = (
    Get-Content -Raw -LiteralPath (Join-Path $RepositoryRoot "global.json") |
        ConvertFrom-Json
).sdk.version
if (
    $LASTEXITCODE -ne 0 -or
    $DotNetSdkVersion -cne $PinnedDotNetSdkVersion
) {
    throw "The native window host build requires pinned .NET SDK $PinnedDotNetSdkVersion."
}

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $RepositoryRoot "work\Windows Package Proof"
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if ($OutputRoot -eq [IO.Path]::GetPathRoot($OutputRoot)) {
    throw "OutputRoot cannot be a drive root."
}

if ($Mode -eq "Fixture") {
    if (
        -not [string]::IsNullOrWhiteSpace($TufRootPath) -or
        $TufTargetsKeyPaths.Count -gt 0 -or
        $TufSnapshotKeyPaths.Count -gt 0 -or
        $TufTimestampKeyPaths.Count -gt 0
    ) {
        throw "Fixture mode refuses production TUF root and signing-key inputs."
    }
    if ([string]::IsNullOrWhiteSpace($Publisher)) {
        $Publisher = "CN=Stockroom Development"
    }
    if ([string]::IsNullOrWhiteSpace($FeedBaseUri)) {
        $FeedBaseUri = "https://updates.example.invalid/stockroom/development/x64"
    }
}
else {
    if ([string]::IsNullOrWhiteSpace($Publisher)) {
        throw "Production mode requires -Publisher matching the real signing certificate subject."
    }
    if ([string]::IsNullOrWhiteSpace($FeedBaseUri)) {
        throw "Production mode requires the real HTTPS -FeedBaseUri."
    }
    if ([string]::IsNullOrWhiteSpace($SigningCertificatePath)) {
        throw "Production mode requires -SigningCertificatePath to the real code-signing PFX."
    }
    if ([string]::IsNullOrWhiteSpace($TufRootPath)) {
        throw "Production mode requires -TufRootPath to the offline-authored trust root."
    }
    foreach ($entry in ([ordered]@{
        TufTargetsKeyPaths = $TufTargetsKeyPaths
        TufSnapshotKeyPaths = $TufSnapshotKeyPaths
        TufTimestampKeyPaths = $TufTimestampKeyPaths
    }).GetEnumerator()) {
        if ($entry.Value.Count -eq 0) {
            throw "Production mode requires at least one -$($entry.Key) value."
        }
    }
    if ([string]::IsNullOrWhiteSpace($RollbackReleaseId)) {
        throw "Production mode requires -RollbackReleaseId."
    }
    if ($CompatibleFromReleaseIds.Count -eq 0) {
        throw "Production mode requires at least one -CompatibleFromReleaseIds value."
    }
    $dirty = & git -C $RepositoryRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect Git state."
    }
    if ($dirty) {
        throw "Production packaging refuses a dirty Git working tree."
    }
}

if ($SourceDateEpoch -lt 315532800 -or $SourceDateEpoch -gt 2147483647) {
    throw "SourceDateEpoch must be a valid reproducible PE timestamp between 1980 and 2038."
}
if ($ProtocolVersion -le 0) {
    throw "ProtocolVersion must be a positive integer."
}
if ($Version -notmatch '^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$') {
    throw "Version must be a canonical four-part numeric version."
}
if ($MinimumHostVersion -notmatch '^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$') {
    throw "MinimumHostVersion must be a canonical four-part numeric version."
}
$VersionParts = @($Version.Split(".") | ForEach-Object { [uint64]$_ })
$MinimumHostVersionParts = @($MinimumHostVersion.Split(".") | ForEach-Object { [uint64]$_ })
for ($VersionPartIndex = 0; $VersionPartIndex -lt 4; $VersionPartIndex++) {
    if ($MinimumHostVersionParts[$VersionPartIndex] -gt $VersionParts[$VersionPartIndex]) {
        throw "MinimumHostVersion cannot exceed Version."
    }
    if ($MinimumHostVersionParts[$VersionPartIndex] -lt $VersionParts[$VersionPartIndex]) {
        break
    }
}
if ($TufMetadataVersion -le 0) {
    throw "TufMetadataVersion must be a positive integer."
}

function Get-DescendantPath {
    param(
        [Parameter(Mandatory)]
        [string]$Parent,
        [Parameter(Mandatory)]
        [string]$Child
    )

    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $childFull = [IO.Path]::GetFullPath($Child)
    $prefix = $parentFull + [IO.Path]::DirectorySeparatorChar
    if (-not $childFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside OutputRoot: $childFull"
    }
    return $childFull
}

function Initialize-OutputDirectory {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = "Low")]
    param([Parameter(Mandatory)][string]$Path)

    $resolved = Get-DescendantPath -Parent $OutputRoot -Child $Path
    if ($PSCmdlet.ShouldProcess($resolved, "reset the scoped packaging output directory")) {
        if (Test-Path -LiteralPath $resolved) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
        New-Item -ItemType Directory -Path $resolved | Out-Null
    }
    return $resolved
}

function Find-WindowsSdkTool {
    param([Parameter(Mandatory)][string]$Name)

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $versioned = Get-ChildItem -LiteralPath $kitsRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Name } -Descending
    foreach ($directory in $versioned) {
        $candidate = Join-Path $directory.FullName "x64\$Name"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    $fallback = Join-Path $kitsRoot "x64\$Name"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) {
        return [IO.Path]::GetFullPath($fallback)
    }
    throw "$Name was not found in the installed Windows SDK."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$([IO.Path]::GetFileName($FilePath)) failed with exit code $LASTEXITCODE."
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory)][string]$Path)

    $resolved = [IO.Path]::GetFullPath($Path)
    $stream = [IO.File]::OpenRead($resolved)
    try {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = $hasher.ComputeHash($stream)
        }
        finally {
            $hasher.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
    return ([BitConverter]::ToString($digest) -replace "-", "").ToLowerInvariant()
}

function Get-DirectoryFingerprint {
    param([Parameter(Mandatory)][string]$Root)

    $resolved = [IO.Path]::GetFullPath($Root).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    $rows = @(
        Get-ChildItem -LiteralPath $resolved -Recurse -File |
            Sort-Object FullName |
            ForEach-Object {
                $relative = $_.FullName.Substring($resolved.Length + 1).Replace("\", "/")
                "$relative`0$($_.Length)`0$(Get-Sha256 -Path $_.FullName)"
            }
    )
    return [string]::Join("`n", $rows)
}

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Text)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $hasher = [Security.Cryptography.SHA256]::Create()
    $digest = $null
    try {
        $digest = $hasher.ComputeHash($bytes)
        return -join @($digest | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        if ($null -ne $digest) {
            [Array]::Clear($digest, 0, $digest.Length)
        }
        [Array]::Clear($bytes, 0, $bytes.Length)
        $hasher.Dispose()
    }
}

function Set-ReproducibleTimestamp {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = "Low")]
    param([Parameter(Mandatory)][string]$Root)

    if ($PSCmdlet.ShouldProcess($Root, "normalize all payload timestamps")) {
        $fixed = [DateTimeOffset]::FromUnixTimeSeconds($SourceDateEpoch).UtcDateTime
        Get-ChildItem -LiteralPath $Root -Force -Recurse |
            ForEach-Object { $_.LastWriteTimeUtc = $fixed }
        (Get-Item -LiteralPath $Root).LastWriteTimeUtc = $fixed
    }
}

$UvPath = (Get-Command uv -ErrorAction Stop).Source
$MakeAppx = Find-WindowsSdkTool -Name "makeappx.exe"
$SignTool = Find-WindowsSdkTool -Name "signtool.exe"
$SigningCertificateProvided = $Mode -eq "Production"
$Certificate = $null
$CertificatePassword = ""

if ($Mode -eq "Fixture" -and -not [string]::IsNullOrWhiteSpace($SigningCertificatePath)) {
    throw "Fixture mode refuses a signing certificate."
}

if ($Mode -eq "Production") {
    $SigningCertificatePath = [IO.Path]::GetFullPath($SigningCertificatePath)
    if (-not (Test-Path -LiteralPath $SigningCertificatePath -PathType Leaf)) {
        throw "Signing certificate does not exist: $SigningCertificatePath"
    }
    $CertificatePassword = [Environment]::GetEnvironmentVariable(
        $SigningEnvironmentVariableName,
        [EnvironmentVariableTarget]::Process
    )
    if ([string]::IsNullOrEmpty($CertificatePassword)) {
        throw "Production signing password environment variable is missing."
    }
    $flags = [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
    $Certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $SigningCertificatePath,
        $CertificatePassword,
        $flags
    )
    if (-not $Certificate.HasPrivateKey) {
        throw "The signing PFX has no private key."
    }
    if ($Certificate.Subject -cne $Publisher) {
        throw "Publisher must exactly equal the signing certificate subject."
    }
    $codeSigningOid = "1.3.6.1.5.5.7.3.3"
    $hasCodeSigningEku = $false
    foreach ($extension in $Certificate.Extensions) {
        if ($extension -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            foreach ($usage in $extension.EnhancedKeyUsages) {
                if ($usage.Value -eq $codeSigningOid) {
                    $hasCodeSigningEku = $true
                }
            }
        }
    }
    if (-not $hasCodeSigningEku) {
        throw "The signing PFX does not contain the Code Signing EKU."
    }

    $TufRootPath = [IO.Path]::GetFullPath($TufRootPath)
    if (-not (Test-Path -LiteralPath $TufRootPath -PathType Leaf)) {
        throw "Pinned TUF root does not exist."
    }
    foreach ($variableName in @(
        "TufTargetsKeyPaths",
        "TufSnapshotKeyPaths",
        "TufTimestampKeyPaths"
    )) {
        $keyPaths = @((Get-Variable -Name $variableName -ValueOnly))
        for ($index = 0; $index -lt $keyPaths.Count; $index++) {
            $keyPaths[$index] = [IO.Path]::GetFullPath($keyPaths[$index])
            if (-not (Test-Path -LiteralPath $keyPaths[$index] -PathType Leaf)) {
                throw "A required TUF online-role signing key does not exist."
            }
        }
        Set-Variable -Name $variableName -Value $keyPaths
    }
}

# The committed ICO is generated from a small, deterministic grayscale mark.
# Refuse stale or hand-edited identity bytes before PyInstaller or MSIX can
# silently embed a different icon.
Invoke-Checked -FilePath $UvPath -Arguments @(
    "run", "--frozen", "python", $BrandAssetsTool, "--check"
)

$WorkRoot = Initialize-OutputDirectory -Path (Join-Path $OutputRoot "Work")
$ArtifactsRoot = Initialize-OutputDirectory -Path (Join-Path $OutputRoot "Artifacts")
$ContractRoot = Initialize-OutputDirectory -Path (Join-Path $ArtifactsRoot "Package Contract")
$SeedRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot "Contract Seed")
$SeedPackage = Join-Path $SeedRoot "Package"
$SeedAppInstaller = Join-Path $SeedRoot "Stockroom.appinstaller"
$VersionInfoPath = Join-Path $SeedRoot "StockroomVersionInfo.txt"
$BuildIdentityPath = Join-Path $SeedRoot "stockroom-build-identity.json"
$GitRevision = (& git -C $RepositoryRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $GitRevision -notmatch "^[0-9a-f]{40}$") {
    throw "Could not resolve the exact Git revision."
}
$BuildIdentity = [ordered]@{
    schema = "stockroom-build-identity/1"
    package_version = $Version
    release_id = "release-$Version"
    protocol_version = $ProtocolVersion
    source_revision = $GitRevision
}
[IO.File]::WriteAllText(
    $BuildIdentityPath,
    (($BuildIdentity | ConvertTo-Json -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
)

$contractArguments = @(
    "run", "--frozen", "python", "-m", $ContractModule, "render",
    "--mode", $Mode,
    "--publisher", $Publisher,
    "--version", $Version,
    "--feed-base-uri", $FeedBaseUri,
    "--package-root", $SeedPackage,
    "--appinstaller-path", $SeedAppInstaller,
    "--template-directory", $PackagingRoot,
    "--version-info-path", $VersionInfoPath,
    "--source-icon", $SourceIcon
)
if ($SigningCertificateProvided) {
    $contractArguments += "--signing-certificate-provided"
}
Invoke-Checked -FilePath $UvPath -Arguments $contractArguments

function Build-Executable {
    param([Parameter(Mandatory)][string]$Name)

    $buildRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot $Name)
    $distRoot = Join-Path $buildRoot "Dist"
    $pyinstallerRoot = Join-Path $buildRoot "PyInstaller"
    New-Item -ItemType Directory -Path $distRoot, $pyinstallerRoot | Out-Null

    $previous = @{
        PYTHONHASHSEED = $env:PYTHONHASHSEED
        SOURCE_DATE_EPOCH = $env:SOURCE_DATE_EPOCH
        STOCKROOM_VERSION_FILE = $env:STOCKROOM_VERSION_FILE
        STOCKROOM_BUILD_IDENTITY = $env:STOCKROOM_BUILD_IDENTITY
    }
    try {
        $env:PYTHONHASHSEED = "1"
        $env:SOURCE_DATE_EPOCH = [string]$SourceDateEpoch
        $env:STOCKROOM_VERSION_FILE = $VersionInfoPath
        $env:STOCKROOM_BUILD_IDENTITY = $BuildIdentityPath

        Invoke-Checked -FilePath $UvPath -Arguments @(
            "run",
            "--project", $RepositoryRoot,
            "--directory", $buildRoot,
            "--frozen",
            "pyinstaller",
            $SpecPath,
            "--noconfirm",
            "--clean",
            "--log-level", "WARN",
            "--distpath", $distRoot,
            "--workpath", $pyinstallerRoot
        )
    }
    finally {
        foreach ($name in $previous.Keys) {
            $value = $previous[$name]
            if ($null -eq $value) {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:$name" $value
            }
        }
    }

    $workerRoot = Join-Path $distRoot "Stockroom Worker"
    $executable = Join-Path $workerRoot "Stockroom Worker.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "PyInstaller did not produce the packaged Stockroom worker."
    }
    return $workerRoot
}

function Build-WindowHost {
    param([Parameter(Mandatory)][string]$Name)

    $buildRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot $Name)
    # Roslyn source-generator identities include generated source paths. Build
    # both independent publish trees through the same freshly cleared compile
    # root so path-derived names do not differ merely because the proof labels
    # are "Build 1" and "Build 2".
    $compileRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot "Window Host Compilation")
    $publishRoot = Join-Path $buildRoot "Publish"
    Push-Location $RepositoryRoot
    try {
        $null = Invoke-Checked -FilePath $DotNetPath -Arguments @(
            "publish", $WindowHostProject,
            "--configuration", "Release",
            "--runtime", "win-x64",
            "--self-contained", "true",
            "--output", $publishRoot,
            "--disable-build-servers",
            "-p:RestoreLockedMode=true",
            "-p:ContinuousIntegrationBuild=true",
            "-p:Deterministic=true",
            "-p:Version=$Version",
            "-p:AssemblyVersion=$Version",
            "-p:FileVersion=$Version",
            "-p:InformationalVersion=$Version+$GitRevision",
            "-p:UseArtifactsOutput=true",
            "-p:ArtifactsPath=$compileRoot"
        )
    }
    finally {
        Pop-Location
    }
    $hostExecutable = Join-Path $publishRoot "Stockroom.WindowHost.exe"
    if (-not (Test-Path -LiteralPath $hostExecutable -PathType Leaf)) {
        throw "dotnet publish did not produce Stockroom.WindowHost.exe."
    }
    return $publishRoot
}

function Build-CadConverter {
    param([Parameter(Mandatory)][string]$Name)

    $buildRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot $Name)
    $compileRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot "CAD Converter Compilation")
    $publishRoot = Join-Path $buildRoot "Publish"
    Push-Location $RepositoryRoot
    try {
        $null = Invoke-Checked -FilePath $DotNetPath -Arguments @(
            "publish", $CadConverterProject,
            "--configuration", "Release",
            "--runtime", "win-x64",
            "--self-contained", "true",
            "--output", $publishRoot,
            "--disable-build-servers",
            "-p:RestoreLockedMode=true",
            "-p:ContinuousIntegrationBuild=true",
            "-p:Deterministic=true",
            "-p:DebugType=None",
            "-p:UseArtifactsOutput=true",
            "-p:ArtifactsPath=$compileRoot"
        )
    }
    finally {
        Pop-Location
    }
    $converterExecutable = Join-Path $publishRoot "Stockroom.CadConverter.exe"
    if (-not (Test-Path -LiteralPath $converterExecutable -PathType Leaf)) {
        throw "dotnet publish did not produce Stockroom.CadConverter.exe."
    }
    return $publishRoot
}

$FirstWindowHost = Build-WindowHost -Name "Window Host Build 1"
$FirstCadConverter = Build-CadConverter -Name "CAD Converter Build 1"
$FirstExecutable = Build-Executable -Name "Build 1"
$FirstExecutableHash = Get-TextSha256 -Text (
    Get-DirectoryFingerprint -Root $FirstExecutable
)
$SecondExecutable = $null
$SecondExecutableHash = $null

if (-not $SkipReproducibilityProof) {
    $SecondWindowHost = Build-WindowHost -Name "Window Host Build 2"
    $SecondCadConverter = Build-CadConverter -Name "CAD Converter Build 2"
    $SecondExecutable = Build-Executable -Name "Build 2"
    $SecondExecutableHash = Get-TextSha256 -Text (
        Get-DirectoryFingerprint -Root $SecondExecutable
    )
    if ($FirstExecutableHash -cne $SecondExecutableHash) {
        throw "Packaged worker reproducibility failed: the two runtime trees differ."
    }
    if ((Get-DirectoryFingerprint -Root $FirstWindowHost) -cne
        (Get-DirectoryFingerprint -Root $SecondWindowHost)) {
        throw "Native window host reproducibility failed: publish trees differ."
    }
    if ((Get-DirectoryFingerprint -Root $FirstCadConverter) -cne
        (Get-DirectoryFingerprint -Root $SecondCadConverter)) {
        throw "Native CAD converter reproducibility failed: publish trees differ."
    }
}

if ($Mode -eq "Production") {
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "sign",
        "/fd", "SHA256",
        "/f", $SigningCertificatePath,
        "/p", $CertificatePassword,
        "/tr", $TimestampUri,
        "/td", "SHA256",
        (Join-Path $FirstExecutable "Stockroom Worker.exe")
    )
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "verify", "/pa", "/all", (Join-Path $FirstExecutable "Stockroom Worker.exe")
    )
    $WindowHostExecutable = Join-Path $FirstWindowHost "Stockroom.WindowHost.exe"
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "sign",
        "/fd", "SHA256",
        "/f", $SigningCertificatePath,
        "/p", $CertificatePassword,
        "/tr", $TimestampUri,
        "/td", "SHA256",
        $WindowHostExecutable
    )
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "verify", "/pa", "/all", $WindowHostExecutable
    )
    $CadConverterExecutable = Join-Path $FirstCadConverter "Stockroom.CadConverter.exe"
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "sign",
        "/fd", "SHA256",
        "/f", $SigningCertificatePath,
        "/p", $CertificatePassword,
        "/tr", $TimestampUri,
        "/td", "SHA256",
        $CadConverterExecutable
    )
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "verify", "/pa", "/all", $CadConverterExecutable
    )
}

if ($Mode -eq "Fixture") {
    $PackageFileName = "Stockroom.Development_${Version}_x64_unsigned.msix"
    $AppInstallerFileName = "Stockroom.Development.appinstaller"
}
else {
    $PackageFileName = "Stockroom_${Version}_x64.msix"
    $AppInstallerFileName = "Stockroom.appinstaller"
}

function Initialize-PackageStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WorkerRoot,
        [Parameter(Mandatory)][string]$WindowHostRoot,
        [Parameter(Mandatory)][string]$CadConverterRoot,
        [Parameter(Mandatory)][string]$AppInstallerPath
    )

    $stage = Initialize-OutputDirectory -Path (Join-Path $WorkRoot $Name)
    Copy-Item -LiteralPath $WindowHostRoot -Destination (Join-Path $stage "WindowHost") -Recurse
    $renderArguments = @(
        "run", "--frozen", "python", "-m", $ContractModule, "render",
        "--mode", $Mode,
        "--publisher", $Publisher,
        "--version", $Version,
        "--feed-base-uri", $FeedBaseUri,
        "--package-root", $stage,
        "--appinstaller-path", $AppInstallerPath,
        "--template-directory", $PackagingRoot,
        "--version-info-path", $VersionInfoPath,
        "--source-icon", $SourceIcon
    )
    if ($SigningCertificateProvided) {
        $renderArguments += "--signing-certificate-provided"
    }
    Invoke-Checked -FilePath $UvPath -Arguments $renderArguments
    $bundleEvidence = Join-Path $WorkRoot "$Name Release Bundle.json"
    $bundleArguments = @(
        "run", "--frozen", "python", $ReleaseBundleTool,
        "--mode", $Mode,
        "--executable", $WorkerRoot,
        "--window-host-root", (Join-Path $stage "WindowHost"),
        "--cad-converter-root", $CadConverterRoot,
        "--bundle-root", (Join-Path $stage "Update"),
        "--version", $Version,
        "--minimum-host-version", $MinimumHostVersion,
        "--protocol-version", [string]$ProtocolVersion,
        "--feed-base-uri", $FeedBaseUri,
        "--source-revision", $GitRevision,
        "--source-date-epoch", [string]$SourceDateEpoch,
        "--rollback-release-id", $RollbackReleaseId,
        "--output", $bundleEvidence
    )
    foreach ($predecessor in $CompatibleFromReleaseIds) {
        if ([string]::IsNullOrWhiteSpace($predecessor)) {
            throw "Compatible predecessor release IDs cannot be blank."
        }
        $bundleArguments += @("--compatible-from-release-id", $predecessor)
    }
    if ($Mode -eq "Production") {
        $bundleArguments += @("--tuf-root-path", $TufRootPath)
    }
    Invoke-Checked -FilePath $UvPath -Arguments $bundleArguments
    Set-ReproducibleTimestamp -Root $stage
    return $stage
}

$FinalAppInstaller = Join-Path $ArtifactsRoot $AppInstallerFileName
$FirstStage = Initialize-PackageStage `
    -Name "Package 1" `
    -WorkerRoot $FirstExecutable `
    -WindowHostRoot $FirstWindowHost `
    -CadConverterRoot $FirstCadConverter `
    -AppInstallerPath $FinalAppInstaller

$PayloadInventory = Join-Path $ArtifactsRoot "Payload Manifest.json"
Invoke-Checked -FilePath $UvPath -Arguments @(
    "run", "--frozen", "python", "-m", $ContractModule, "inventory",
    "--root", $FirstStage,
    "--output", $PayloadInventory
)

$FinalPackage = Join-Path $ArtifactsRoot $PackageFileName
Invoke-Checked -FilePath $MakeAppx -Arguments @(
    "pack",
    "/v",
    "/h", "SHA256",
    "/d", $FirstStage,
    "/p", $FinalPackage,
    "/o"
)
Invoke-Checked -FilePath $UvPath -Arguments @(
    "run", "--frozen", "python", "-m", $ContractModule, "normalize-msix",
    "--path", $FinalPackage,
    "--source-date-epoch", [string]$SourceDateEpoch
)

if ($Mode -eq "Production") {
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "sign",
        "/fd", "SHA256",
        "/f", $SigningCertificatePath,
        "/p", $CertificatePassword,
        "/tr", $TimestampUri,
        "/td", "SHA256",
        $FinalPackage
    )
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "verify", "/pa", "/all", (Join-Path $FirstStage "WindowHost\Stockroom.WindowHost.exe")
    )
    Invoke-Checked -FilePath $SignTool -Arguments @(
        "verify", "/pa", "/all", $FinalPackage
    )
    $ExecutableSignatureStatus = "Valid"
    $PackageSignatureStatus = "Valid"
}
else {
    $priorPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $SignTool verify /pa /all (Join-Path $FirstStage "WindowHost\Stockroom.WindowHost.exe") *> $null
        $executableVerifyExitCode = $LASTEXITCODE
        & $SignTool verify /pa /all $FinalPackage *> $null
        $packageVerifyExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $priorPreference
    }
    if ($executableVerifyExitCode -eq 0) {
        throw "Fixture executable unexpectedly has an Authenticode signature."
    }
    if ($packageVerifyExitCode -eq 0) {
        throw "Fixture MSIX unexpectedly has an Authenticode signature."
    }
    $ExecutableSignatureStatus = "NotSigned"
    $PackageSignatureStatus = "NotSigned"
}

$ReproduciblePackageHash = $null
if (-not $SkipReproducibilityProof -and $Mode -eq "Fixture") {
    $SecondAppInstaller = Join-Path $WorkRoot "Stockroom.Development.Second.appinstaller"
    $SecondStage = Initialize-PackageStage `
        -Name "Package 2" `
        -WorkerRoot $SecondExecutable `
        -WindowHostRoot $SecondWindowHost `
        -CadConverterRoot $SecondCadConverter `
        -AppInstallerPath $SecondAppInstaller
    $secondPackage = Join-Path $WorkRoot $PackageFileName
    Invoke-Checked -FilePath $MakeAppx -Arguments @(
        "pack",
        "/v",
        "/h", "SHA256",
        "/d", $SecondStage,
        "/p", $secondPackage,
        "/o"
    )
    Invoke-Checked -FilePath $UvPath -Arguments @(
        "run", "--frozen", "python", "-m", $ContractModule, "normalize-msix",
        "--path", $secondPackage,
        "--source-date-epoch", [string]$SourceDateEpoch
    )
    $ReproduciblePackageHash = Get-Sha256 -Path $secondPackage
    if ((Get-Sha256 -Path $FinalPackage) -cne $ReproduciblePackageHash) {
        throw "MSIX reproducibility failed: the two unsigned package digests differ."
    }
    if ((Get-Sha256 -Path $FinalAppInstaller) -cne (Get-Sha256 -Path $SecondAppInstaller)) {
        throw "App Installer reproducibility failed."
    }
}

$UnpackedRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot "SDK Unpacked")
Invoke-Checked -FilePath $MakeAppx -Arguments @(
    "unpack",
    "/v",
    "/p", $FinalPackage,
    "/d", $UnpackedRoot,
    "/o"
)

if ((Get-Sha256 -Path (Join-Path $FirstStage "AppxManifest.xml")) -cne
    (Get-Sha256 -Path (Join-Path $UnpackedRoot "AppxManifest.xml"))) {
    throw "MakeAppx round-trip changed AppxManifest.xml."
}
if ((Get-DirectoryFingerprint -Root (Join-Path $FirstStage "Update")) -cne
    (Get-DirectoryFingerprint -Root (Join-Path $UnpackedRoot "Update"))) {
    throw "MakeAppx round-trip changed the immutable update bundle."
}
if ((Get-DirectoryFingerprint -Root (Join-Path $FirstStage "WindowHost")) -cne
    (Get-DirectoryFingerprint -Root (Join-Path $UnpackedRoot "WindowHost"))) {
    throw "MakeAppx round-trip changed the native window host payload."
}

$validateArguments = @(
    "run", "--frozen", "python", "-m", $ContractModule, "validate",
    "--mode", $Mode,
    "--publisher", $Publisher,
    "--version", $Version,
    "--feed-base-uri", $FeedBaseUri,
    "--package-root", $UnpackedRoot,
    "--appinstaller-path", $FinalAppInstaller
)
if ($SigningCertificateProvided) {
    $validateArguments += "--signing-certificate-provided"
}
Invoke-Checked -FilePath $UvPath -Arguments $validateArguments

$ProbeRoot = Initialize-OutputDirectory -Path (Join-Path $WorkRoot "Managed Host Launch")
$ProbeReceiptPath = Join-Path $ProbeRoot "Managed Host Receipt.json"
$ProbeConfigRoot = Join-Path $ProbeRoot "Config"
$ProbeLocalAppData = Join-Path $ProbeRoot "Local App Data"
$ProbeRoamingAppData = Join-Path $ProbeRoot "Roaming App Data"
New-Item -ItemType Directory -Path $ProbeConfigRoot, $ProbeLocalAppData, $ProbeRoamingAppData |
    Out-Null
$probeStart = [Diagnostics.ProcessStartInfo]::new()
$probeStart.FileName = Join-Path $UnpackedRoot "WindowHost\Stockroom.WindowHost.exe"
$probeStart.UseShellExecute = $false
$probeStart.CreateNoWindow = $true
$probeStart.RedirectStandardError = $true
$probeStart.RedirectStandardOutput = $true
# Windows PowerShell 5.1 runs on .NET Framework, whose ProcessStartInfo has
# Arguments but not ArgumentList. The generated receipt path cannot contain a
# quote on Windows and is a file path (so it cannot end in a directory
# separator), making one quoted argument lossless even when OutputRoot has
# spaces. Keep this build gate runnable on the Windows host we actually ship
# from instead of accidentally requiring PowerShell 7.
$probeStart.Arguments = '--native-host-probe "' + $ProbeReceiptPath + '"'
$probeStart.EnvironmentVariables["STOCKROOM_CONFIG_DIR"] = $ProbeConfigRoot
$probeStart.EnvironmentVariables["LOCALAPPDATA"] = $ProbeLocalAppData
$probeStart.EnvironmentVariables["APPDATA"] = $ProbeRoamingAppData
$probeStart.EnvironmentVariables["GIT_TERMINAL_PROMPT"] = "0"
$probeProcess = [Diagnostics.Process]::Start($probeStart)
if ($null -eq $probeProcess) {
    throw "The packaged managed host process could not be started."
}
if (-not $probeProcess.WaitForExit(180000)) {
    $probeProcess.Kill()
    $probeProcess.WaitForExit()
    throw "The packaged managed host launch proof exceeded 180 seconds."
}
$probeStandardOutput = $probeProcess.StandardOutput.ReadToEnd()
$probeStandardError = $probeProcess.StandardError.ReadToEnd()
if ($probeProcess.ExitCode -ne 0) {
    throw "The packaged managed host launch proof failed: $probeStandardError$probeStandardOutput"
}
if (-not (Test-Path -LiteralPath $ProbeReceiptPath -PathType Leaf)) {
    throw "The packaged managed host did not write its launch receipt."
}
$ProbeReceipt = Get-Content -Raw -LiteralPath $ProbeReceiptPath | ConvertFrom-Json
if (
    $ProbeReceipt.schema -cne "stockroom-native-host-launch/1" -or
    $ProbeReceipt.release_id -cne "release-$Version" -or
    $ProbeReceipt.host_package_version -cne $Version -or
    -not $ProbeReceipt.native_host -or
    -not $ProbeReceipt.packaged_worker
) {
    throw "The packaged native host launch receipt is incomplete or invalid."
}

$BundleEvidence = Get-Content -Raw -LiteralPath (
    Join-Path $WorkRoot "Package 1 Release Bundle.json"
) | ConvertFrom-Json
$PackagedReleaseDirectory = Join-Path (
    Join-Path $UnpackedRoot "Update\Initial Release"
) $BundleEvidence.release_id
$PackagedWorker = Join-Path $PackagedReleaseDirectory "Backend\Stockroom Worker.exe"
$WorkerProbeReceiptPath = Join-Path $ProbeRoot "Packaged Worker Handoff Receipt.json"
$WorkerProbeConfigRoot = Join-Path $ProbeRoot "Worker Config"
$WorkerProbeLocalAppData = Join-Path $ProbeRoot "Worker Local App Data"
$WorkerProbeRoamingAppData = Join-Path $ProbeRoot "Worker Roaming App Data"
New-Item -ItemType Directory -Path $WorkerProbeConfigRoot, $WorkerProbeLocalAppData, $WorkerProbeRoamingAppData |
    Out-Null
Invoke-Checked -FilePath $UvPath -Arguments @(
    "run", "--frozen", "python", $WorkerProbeTool,
    "--worker-executable", $PackagedWorker,
    "--release-directory", $PackagedReleaseDirectory,
    "--release-id", $BundleEvidence.release_id,
    "--manifest-sha256", $BundleEvidence.manifest_sha256,
    "--receipt", $WorkerProbeReceiptPath,
    "--config-root", $WorkerProbeConfigRoot,
    "--local-app-data", $WorkerProbeLocalAppData,
    "--roaming-app-data", $WorkerProbeRoamingAppData
)
$WorkerProbeReceipt = Get-Content -Raw -LiteralPath $WorkerProbeReceiptPath |
    ConvertFrom-Json
if (
    $WorkerProbeReceipt.schema -cne "stockroom-packaged-worker-handoff/1" -or
    $WorkerProbeReceipt.candidate_release_id -cne $BundleEvidence.release_id -or
    -not $WorkerProbeReceipt.adopted -or
    -not $WorkerProbeReceipt.rolled_back -or
    $WorkerProbeReceipt.exact_worker_sha256 -cne (Get-Sha256 -Path $PackagedWorker) -or
    -not $WorkerProbeReceipt.frontend_served -or
    $WorkerProbeReceipt.exact_cad_converter_sha256 -cne $BundleEvidence.cad_converter_sha256 -or
    [int]$WorkerProbeReceipt.candidate_generation -ne
        ([int]$WorkerProbeReceipt.initial_generation + 1) -or
    [int]$WorkerProbeReceipt.restored_generation -ne
        ([int]$WorkerProbeReceipt.initial_generation + 2)
) {
    throw "The exact packaged --port worker failed its managed handoff proof."
}

$ReleaseFeedRoot = Initialize-OutputDirectory -Path (
    Join-Path $WorkRoot "Release Feed Repository"
)
$ReleaseFeedArchiveName = "Stockroom_TUF_Feed_${Version}.zip"
$ReleaseFeedArchivePath = Join-Path $ArtifactsRoot $ReleaseFeedArchiveName
$ReleaseFeedEvidencePath = Join-Path $ArtifactsRoot "Release Feed Evidence.json"
$releaseFeedArguments = @(
    "run", "--frozen", "python", "-m", $ReleaseFeedModule,
    "--mode", $Mode,
    "--feed-base-uri", $FeedBaseUri,
    "--root", (Join-Path $UnpackedRoot "Update\Root.json"),
    "--release-directory", $PackagedReleaseDirectory,
    "--release-id", $BundleEvidence.release_id,
    "--manifest-sha256", $BundleEvidence.manifest_sha256,
    "--metadata-version", [string]$TufMetadataVersion,
    "--repository-root", $ReleaseFeedRoot,
    "--archive", $ReleaseFeedArchivePath,
    "--evidence", $ReleaseFeedEvidencePath
)
if ($Mode -eq "Production") {
    foreach ($keyPath in $TufTargetsKeyPaths) {
        $releaseFeedArguments += @("--targets-key", $keyPath)
    }
    foreach ($keyPath in $TufSnapshotKeyPaths) {
        $releaseFeedArguments += @("--snapshot-key", $keyPath)
    }
    foreach ($keyPath in $TufTimestampKeyPaths) {
        $releaseFeedArguments += @("--timestamp-key", $keyPath)
    }
}
Invoke-Checked -FilePath $UvPath -Arguments $releaseFeedArguments
$ReleaseFeedEvidence = Get-Content -Raw -LiteralPath $ReleaseFeedEvidencePath |
    ConvertFrom-Json
if (
    $ReleaseFeedEvidence.schema -cne "stockroom-release-feed/1" -or
    $ReleaseFeedEvidence.mode -cne $Mode.ToLowerInvariant() -or
    $ReleaseFeedEvidence.release_id -cne $BundleEvidence.release_id -or
    $ReleaseFeedEvidence.manifest_sha256 -cne $BundleEvidence.manifest_sha256 -or
    [int]$ReleaseFeedEvidence.metadata_version -ne $TufMetadataVersion -or
    $ReleaseFeedEvidence.root.sha256 -cne $BundleEvidence.root_sha256 -or
    $ReleaseFeedEvidence.archive.path -cne $ReleaseFeedArchiveName -or
    $ReleaseFeedEvidence.deployment.feed_base_uri -cne $FeedBaseUri.TrimEnd("/") -or
    $ReleaseFeedEvidence.archive.sha256 -cne (
        Get-Sha256 -Path $ReleaseFeedArchivePath
    ) -or
    -not $ReleaseFeedEvidence.validation.consistent_snapshot_layout -or
    -not $ReleaseFeedEvidence.validation.online_role_thresholds -or
    -not $ReleaseFeedEvidence.validation.trusted_updater_round_trip
) {
    throw "The exact packaged release did not produce a valid signed TUF feed."
}
if (
    $Mode -eq "Production" -and (
        $ReleaseFeedEvidence.deployment.state -cne "staged-not-deployed" -or
        -not $ReleaseFeedEvidence.deployment.external_action_required
    )
) {
    throw "Production TUF feed evidence omitted its external deployment boundary."
}

Copy-Item -LiteralPath (Join-Path $FirstStage "AppxManifest.xml") `
    -Destination (Join-Path $ContractRoot "AppxManifest.xml")
Copy-Item -LiteralPath $FinalAppInstaller `
    -Destination (Join-Path $ContractRoot $AppInstallerFileName)
Copy-Item -LiteralPath (Join-Path $FirstStage "WindowHost\Stockroom.WindowHost.exe") `
    -Destination (Join-Path $ArtifactsRoot "Stockroom.WindowHost.exe")

$GitDirty = [bool](& git -C $RepositoryRoot status --porcelain)
$PackageHash = Get-Sha256 -Path $FinalPackage
$AppInstallerHash = Get-Sha256 -Path $FinalAppInstaller
$FinalExecutableHash = Get-Sha256 -Path (Join-Path $ArtifactsRoot "Stockroom.WindowHost.exe")
$ManifestHash = Get-Sha256 -Path (Join-Path $ContractRoot "AppxManifest.xml")

$SigningState = if ($Mode -eq "Production") {
    "authenticode-signed"
}
else {
    "unsigned-development-fixture"
}
$SigningBlocker = if ($Mode -eq "Production") {
    $null
}
else {
    "Installation and production distribution are blocked until the owner supplies a real trusted code-signing PFX whose subject becomes the package Publisher."
}
$CertificateThumbprint = if ($null -eq $Certificate) { $null } else { $Certificate.Thumbprint }
$FinalWorkerHash = Get-Sha256 -Path $PackagedWorker
if ($BundleEvidence.backend_sha256 -cne $FinalWorkerHash) {
    throw "The immutable backend is not the exact packaged worker executable."
}
$ExpectedCompatibleReleases = $CompatibleFromReleaseIds -join ","
if (
    $BundleEvidence.rollback_release_id -cne $RollbackReleaseId -or
    $BundleEvidence.compatible_from_release_ids -cne $ExpectedCompatibleReleases -or
    $BundleEvidence.minimum_host_version -cne $MinimumHostVersion
) {
    throw "The immutable release compatibility contract differs from the requested host floor or predecessors."
}

$Evidence = [ordered]@{
    schema = "stockroom-windows-package-build/3"
    mode = $Mode.ToLowerInvariant()
    runtime_status = if ($Mode -eq "Fixture") {
        "verified-offline-fixture"
    }
    else {
        "stable-managed-release-runtime"
    }
    source = [ordered]@{
        git_revision = $GitRevision
        git_dirty = $GitDirty
        source_date_epoch = $SourceDateEpoch
        python_hash_seed = 1
    }
    contract = [ordered]@{
        package_name = if ($Mode -eq "Fixture") { "Stockroom.Desktop.Development" } else { "Stockroom.Desktop" }
        publisher = $Publisher
        version = $Version
        minimum_host_version = $MinimumHostVersion
        protocol_version = $ProtocolVersion
        tuf_metadata_version = $TufMetadataVersion
        architecture = "x64"
        feed_base_uri = $FeedBaseUri.TrimEnd("/")
        rollback_release_id = $RollbackReleaseId
        compatible_from_release_ids = @($CompatibleFromReleaseIds)
        appinstaller_schema = "http://schemas.microsoft.com/appx/appinstaller/2021"
        on_launch_hours_between_checks = 0
        show_prompt = $false
        update_blocks_activation = $false
        automatic_background_task = $true
        force_update_from_any_version = $false
    }
    tools = [ordered]@{
        uv = [ordered]@{
            path = $UvPath
            sha256 = Get-Sha256 -Path $UvPath
        }
        pyinstaller = (& $UvPath run --frozen pyinstaller --version).Trim()
        makeappx = [ordered]@{
            path = $MakeAppx
            file_version = (Get-Item -LiteralPath $MakeAppx).VersionInfo.FileVersion
        }
        signtool = [ordered]@{
            path = $SignTool
            file_version = (Get-Item -LiteralPath $SignTool).VersionInfo.FileVersion
        }
        cad_converter = [ordered]@{
            tree_sha256 = Get-TextSha256 -Text (
                Get-DirectoryFingerprint -Root $FirstCadConverter
            )
            executable_sha256 = Get-Sha256 -Path (
                Join-Path $FirstCadConverter "Stockroom.CadConverter.exe"
            )
        }
    }
    signing = [ordered]@{
        state = $SigningState
        executable_signature_status = $ExecutableSignatureStatus
        msix_signature_status = $PackageSignatureStatus
        certificate_thumbprint = $CertificateThumbprint
        production_blocker = $SigningBlocker
        certificate_was_installed_or_trusted = $false
    }
    validation = [ordered]@{
        python_contract_validator = $true
        makeappx_semantic_validation = $true
        deterministic_zip_timestamp_normalization = $true
        makeappx_round_trip = $true
        unpacked_manifest_matches = $true
        unpacked_executable_matches = $true
        immutable_release_bundle_round_trip = $true
        managed_host_launch = $true
        managed_service_authority = $true
        workflow_coordinator_running = $true
        packaged_frontend_served = [bool]$WorkerProbeReceipt.frontend_served
        packaged_worker_handoff = $true
        signed_tuf_release_feed = $true
    }
    managed_runtime = [ordered]@{
        release_id = $BundleEvidence.release_id
        host_package_version = $ProbeReceipt.host_package_version
        minimum_host_version = $BundleEvidence.minimum_host_version
        host_protocol_version = $ProtocolVersion
        release_manifest_sha256 = $BundleEvidence.manifest_sha256
        pinned_tuf_root_sha256 = $BundleEvidence.root_sha256
        immutable_backend_sha256 = $FinalWorkerHash
        immutable_cad_converter_sha256 = $BundleEvidence.cad_converter_sha256
        rollback_release_id = $BundleEvidence.rollback_release_id
        compatible_from_release_ids = @($CompatibleFromReleaseIds)
        launch_receipt_schema = $ProbeReceipt.schema
        native_host = [bool]$ProbeReceipt.native_host
        packaged_worker = [bool]$ProbeReceipt.packaged_worker
        update_channel = "production"
        update_check_interval_seconds = 60.0
        worker_handoff_receipt_schema = $WorkerProbeReceipt.schema
        worker_candidate_generation = [int]$WorkerProbeReceipt.candidate_generation
        worker_restored_generation = [int]$WorkerProbeReceipt.restored_generation
        worker_exact_executable_sha256 = $WorkerProbeReceipt.exact_worker_sha256
        worker_exact_cad_converter_sha256 = $WorkerProbeReceipt.exact_cad_converter_sha256
    }
    release_feed = [ordered]@{
        schema = $ReleaseFeedEvidence.schema
        metadata_version = [int]$ReleaseFeedEvidence.metadata_version
        release_id = $ReleaseFeedEvidence.release_id
        manifest_sha256 = $ReleaseFeedEvidence.manifest_sha256
        root_sha256 = $ReleaseFeedEvidence.root.sha256
        archive_sha256 = $ReleaseFeedEvidence.archive.sha256
        feed_base_uri = $ReleaseFeedEvidence.deployment.feed_base_uri
        trusted_updater_round_trip = [bool](
            $ReleaseFeedEvidence.validation.trusted_updater_round_trip
        )
        deployment_state = $ReleaseFeedEvidence.deployment.state
        external_action_required = [bool](
            $ReleaseFeedEvidence.deployment.external_action_required
        )
        production_deployment_blocker = if ($Mode -eq "Production") {
            "Deploy the signed archive's metadata/ and targets/ trees to the configured HTTPS feed origin; package CI deliberately cannot attest that external hosting step."
        } else { $null }
    }
    reproducibility = [ordered]@{
        checked = -not $SkipReproducibilityProof
        pyinstaller_payloads_match = if ($SkipReproducibilityProof) { $null } else { $true }
        first_unsigned_executable_sha256 = $FirstExecutableHash
        second_unsigned_executable_sha256 = $SecondExecutableHash
        unsigned_fixture_packages_match = if ($Mode -eq "Fixture" -and -not $SkipReproducibilityProof) { $true } else { $null }
        second_unsigned_fixture_package_sha256 = $ReproduciblePackageHash
    }
    outputs = [ordered]@{
        executable = [ordered]@{
            path = "Stockroom.WindowHost.exe"
            size = (Get-Item -LiteralPath (Join-Path $ArtifactsRoot "Stockroom.WindowHost.exe")).Length
            sha256 = $FinalExecutableHash
        }
        msix = [ordered]@{
            path = $PackageFileName
            size = (Get-Item -LiteralPath $FinalPackage).Length
            sha256 = $PackageHash
        }
        appinstaller = [ordered]@{
            path = $AppInstallerFileName
            size = (Get-Item -LiteralPath $FinalAppInstaller).Length
            sha256 = $AppInstallerHash
        }
        appx_manifest = [ordered]@{
            path = "Package Contract/AppxManifest.xml"
            sha256 = $ManifestHash
        }
        payload_manifest = [ordered]@{
            path = "Payload Manifest.json"
            sha256 = Get-Sha256 -Path $PayloadInventory
        }
        release_feed = [ordered]@{
            path = $ReleaseFeedArchiveName
            size = (Get-Item -LiteralPath $ReleaseFeedArchivePath).Length
            sha256 = Get-Sha256 -Path $ReleaseFeedArchivePath
        }
        release_feed_evidence = [ordered]@{
            path = "Release Feed Evidence.json"
            size = (Get-Item -LiteralPath $ReleaseFeedEvidencePath).Length
            sha256 = Get-Sha256 -Path $ReleaseFeedEvidencePath
        }
    }
}

$EvidencePath = Join-Path $ArtifactsRoot "Build Evidence.json"
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText(
    $EvidencePath,
    ($Evidence | ConvertTo-Json -Depth 12) + "`n",
    $utf8
)

$Sums = @(
    "$FinalExecutableHash  Stockroom.WindowHost.exe"
    "$PackageHash  $PackageFileName"
    "$AppInstallerHash  $AppInstallerFileName"
    "$ManifestHash  Package Contract/AppxManifest.xml"
    "$(Get-Sha256 -Path $PayloadInventory)  Payload Manifest.json"
    "$(Get-Sha256 -Path $ReleaseFeedArchivePath)  $ReleaseFeedArchiveName"
    "$(Get-Sha256 -Path $ReleaseFeedEvidencePath)  Release Feed Evidence.json"
) -join "`n"
[IO.File]::WriteAllText(
    (Join-Path $ArtifactsRoot "SHA256SUMS.txt"),
    $Sums + "`n",
    [Text.Encoding]::ASCII
)

Write-Output ""
Write-Output "Windows package proof complete."
Write-Output "Mode: $Mode"
Write-Output "Executable SHA-256: $FinalExecutableHash"
Write-Output "MSIX SHA-256:       $PackageHash"
Write-Output "AppInstaller SHA-256: $AppInstallerHash"
Write-Output "Evidence: $EvidencePath"
