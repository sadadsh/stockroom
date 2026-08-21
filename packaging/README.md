# Stockroom Windows Packaging

Stockroom's rapid Windows delivery is a signed x64 MSIX from
`https://sadadsh.github.io/stockroom/`. The person trusts the pinned public
certificate once and opens `Stockroom.appinstaller`; later successful `main`
pushes update through the verified feed without another download. Windows launches
`WindowHost\Stockroom.WindowHost.exe`, the self-contained .NET 10 WPF host. The
host starts one immutable PyInstaller onedir backend from the package's verified
release set. Microsoft Store remains an optional, separately signed channel.

Normal startup does not clone application source, run `uv`, execute a source
Python environment, install WebView2, or provision provider browsers. The Python
worker has no interactive entry point. `packaging\build_exe.ps1` fails closed
because the former standalone bootstrap is no longer a supported product.

The Store package contains:

- the native WPF window host;
- an immutable onedir backend worker and committed frontend;
- the source-pinned native CAD converter;
- a built-in immutable release;
- an exact Microsoft Store distribution marker; and
- MSIX assets and registration metadata.

MSIX installation owns the Start menu entry, Installed Apps registration, update
policy, and uninstall operation. The Store submission is intentionally unsigned;
Microsoft signs it after certification. The build never creates or trusts a
self-signed certificate.

## Microsoft Store build

Build the unsigned upload candidate from the repository root on Windows:

```powershell
.\packaging\Build-Windows-Package.ps1 `
  -Mode Store `
  -Version 1.0.1.0 `
  -OutputRoot "work\Microsoft Store Candidate"
```

Store versions use `1.0.<build>.0`. The command builds twice by default and
requires identical worker, host, converter, unpacked package, and MSIX outputs.
The artifact directory contains only the MSIX, build evidence, and checksums. It
contains no App Installer file, TUF feed, private key, certificate, or password.
The Microsoft Store is the package's only update authority.

Before packing either reproducibility stage, the build scans every staged PE
file's Authenticode certificate table. The build fails if any table is truncated,
misaligned, or structurally invalid because Microsoft cannot re-sign an MSIX that
contains such a binary. Unused Tk/Tcl GUI modules are excluded from the worker;
Stockroom's supported desktop UI is the native WPF/WebView2 host.

## Unsigned fixture

Run the fixture from the repository root on Windows:

```powershell
.\packaging\Build-Windows-Package.ps1 `
  -Mode Fixture `
  -Version 1.0.0.0 `
  -MinimumHostVersion 1.0.0.0 `
  -OutputRoot "work\Windows Package Proof"
```

Fixture mode uses `Stockroom.Desktop.Development`, `CN=Stockroom Development`,
and a reserved `.invalid` update origin. Its executable and MSIX remain unsigned,
so the fixture is evidence rather than an installable production release.

Unless you pass `-SkipReproducibilityProof`, the command builds the native host,
backend runtime, CAD converter, MSIX, and App Installer twice and requires
identical unsigned outputs.

The `Artifacts` directory contains:

- `Stockroom.WindowHost.exe`;
- `Stockroom.Development_<Version>_x64_unsigned.msix`;
- `Stockroom.Development.appinstaller`;
- `Stockroom_TUF_Feed_<Version>.zip`;
- `Release Feed Evidence.json`;
- `Build Evidence.json`;
- `Payload Manifest.json`;
- `Package Contract\AppxManifest.xml`; and
- `SHA256SUMS.txt`.

The fixture launches the exact unpacked native host in headless probe mode. That
host starts the exact manifest-bound worker. A second probe transfers coordinator
authority to the worker, checks health and the committed frontend, then rolls back
to the prior generation. The build also runs MakeAppx validation, package
round-trip checks, a native CAD conversion canary, and a trusted TUF updater
round trip.

## Production build

Production mode requires the code-signing PFX, its password, the exact publisher,
the HTTPS feed origin, the offline-authored TUF root, and online-role TUF keys.

```powershell
$env:STOCKROOM_SIGNING_CERT_PASSWORD = "<PFX password>"

.\packaging\Build-Windows-Package.ps1 `
  -Mode Production `
  -Version 1.2.3.4 `
  -MinimumHostVersion 1.2.3.4 `
  -Publisher "CN=Exact certificate subject, O=Exact organization, C=US" `
  -FeedBaseUri "https://updates.stockroom.com/windows/x64" `
  -SigningCertificatePath "X:\secure\Stockroom-Code-Signing.pfx" `
  -TufRootPath "X:\release-inputs\Root.json" `
  -TufMetadataVersion 42 `
  -TufTargetsKeyPaths "X:\ephemeral\Targets.pem" `
  -TufSnapshotKeyPaths "X:\ephemeral\Snapshot.pem" `
  -TufTimestampKeyPaths "X:\ephemeral\Timestamp.pem" `
  -RollbackReleaseId "release-1.2.3.3" `
  -CompatibleFromReleaseIds @("release-bootstrap", "release-1.2.3.3")
```

Production mode stops before publication when:

- the Git worktree is dirty;
- package or minimum-host versions are invalid;
- the feed URI is not a real HTTPS origin;
- the PFX, password, private key, or Code Signing EKU is missing;
- the publisher differs from the certificate subject;
- the TUF root or an authorized online-role key is invalid;
- native-host, worker, frontend, authority-handoff, CAD, or updater probes fail;
- reproducibility fails; or
- SignTool cannot verify the native host and MSIX.

The script loads the PFX with `EphemeralKeySet`. It signs and timestamps the
backend worker, native host, CAD converter, and MSIX, then verifies each required
signature boundary. Signing occurs after the unsigned reproducibility proof.

## Release workflow

`.github\workflows\release.yml` first calls the canonical Windows CI workflow;
only after that gate passes does it invoke the production packager. A successful
push to `main` publishes one normal immutable GitHub Release as
`1.0.0.<GitHub run number>`, merges the verified TUF history, and atomically
deploys the public install site plus `windows/x64` update feed to GitHub Pages. Manual
dispatch builds and verifies the Actions artifact without publishing; version
tags do not trigger this workflow. Configure:

- secrets `WINDOWS_CERT_BASE64` and `WINDOWS_CERT_PASSWORD`;
- secrets `STOCKROOM_TUF_TARGETS_KEY_BASE64`,
  `STOCKROOM_TUF_SNAPSHOT_KEY_BASE64`, and
  `STOCKROOM_TUF_TIMESTAMP_KEY_BASE64`;
- variables `STOCKROOM_WINDOWS_PUBLISHER` and
  `STOCKROOM_WINDOWS_FEED_BASE_URI`; and
- variable `STOCKROOM_TUF_ROOT_BASE64`.

The repository pins the public half of the GitHub-channel signing identity at
`packaging\Stockroom GitHub Signing.cer`. The workflow verifies its subject,
fingerprint, validity, and Code Signing EKU, temporarily trusts it on the isolated
runner, and requires the secret PFX to match it. The Pages site publishes that
public certificate at `downloads/Stockroom-GitHub-Signing.cer` for the one-time
installation trust step; the private key exists only as an environment secret.

The runner decodes signing material under its temporary directory, overwrites and
removes each secret file before upload, and publishes only:

- the signed MSIX;
- `Stockroom.appinstaller`;
- the TUF feed archive;
- release-feed evidence;
- build evidence; and
- checksums.

An automatic main-push release cannot replace an existing published asset.

## Update ownership

`Stockroom.appinstaller.in` asks Windows to check silently on every launch and in
its background task:

```xml
<UpdateSettings>
  <OnLaunch
    HoursBetweenUpdateChecks="0"
    ShowPrompt="false"
    UpdateBlocksActivation="false" />
  <AutomaticBackgroundTask />
</UpdateSettings>
```

The backend also checks the signed TUF feed every 60 seconds while Stockroom is
open. It stages only verified release sets and uses generation-fenced authority
handoff for adoption and rollback. A network outage reports `repository_offline`;
it does not fall back to Git or mutable source.

The TUF ZIP is a deployment payload. Production evidence records it as
`staged-not-deployed` until the release job publishes the immutable GitHub Release.
The following Pages job merges prior feed archives, refuses any immutable-path
conflict, and atomically deploys the complete public site and `windows/x64` feed.
Installed GitHub-channel builds check on launch and in the background; no manual
redownload is required after a successful `main` release.

## Diagnostics and legacy cleanup

The native host writes rotating JSONL diagnostics to:

```text
%LOCALAPPDATA%\Stockroom\Logs\Native Host.jsonl
```

Rolling workers write per-release logs under:

```text
%LOCALAPPDATA%\Stockroom\Logs\Release Workers\
```

The host owns the worker process tree through a kill-on-close Windows job. On
startup it removes only `_MEI*` directories older than one hour that contain
Stockroom's `stockroom-build-identity.json` marker. The onedir worker does not
create new `_MEI` extraction trees.

## Package identity and registration

`AppxManifest.xml.in` declares one full-trust desktop application:

```text
WindowHost\Stockroom.WindowHost.exe
```

The package identity, native executable, release manifest, and evidence use the
same four-part version. Brand assets come from the committed Stockroom icon:

```powershell
uv run python packaging\brand_assets.py --check
```

Every package build checks those bytes before PyInstaller or MakeAppx runs.

## Focused validation

```powershell
uv run pytest tests\backend\packaging -q
uv run ruff check packaging tests\backend\packaging
uv run ty check packaging tests\backend\packaging --python-platform win32

dotnet test `
  tests\native\Stockroom.WindowHost.Tests\Stockroom.WindowHost.Tests.csproj `
  --configuration Release
```

The repository completion authority remains:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1
```

Microsoft references:

- [Create packages with MakeAppx](https://learn.microsoft.com/windows/msix/package/create-app-package-with-makeappx-tool)
- [Create an App Installer file](https://learn.microsoft.com/windows/msix/app-installer/how-to-create-appinstaller-file)
- [Automatic update and repair](https://learn.microsoft.com/windows/msix/app-installer/auto-update-and-repair--overview)
- [Sign an MSIX package](https://learn.microsoft.com/windows/msix/package/signing-package-overview)
