# Stockroom Windows Packaging

This directory contains Stockroom's production Windows package boundary:

- deterministic full-application PyInstaller payload creation;
- a pinned TUF root and complete immutable built-in release set;
- one executable that runs the stable broker/window host normally and an
  immutable candidate worker with `--port`;
- a generation-fenced workflow coordinator and live handoff runtime;
- an x64 full-trust MSIX manifest;
- a 2021-schema `.appinstaller` policy for silent launch checks and Windows'
  automatic background update task;
- Windows SDK semantic validation and package round-trip verification; and
- fail-closed production signing and trust inputs;
- a signed, consistent-snapshot TUF feed authored from the exact unpacked
  release; and
- an actual launch proof against the unpacked packaged executable.

`stockroom_launcher.py` never provisions or updates an application Git
checkout. Application releases are complete immutable sets verified by the
TUF-backed broker. MinGit remains bundled because a user's component library
is intentionally Git-backed; it is not an application-delivery mechanism.

## Reproducible unsigned fixture

Run from the repository root on Windows:

```powershell
.\packaging\Build-Windows-Package.ps1 `
  -Mode Fixture `
  -Version 0.1.0.0 `
  -OutputRoot "work\Windows Package Proof"
```

Fixture mode is deliberately non-installable:

- package identity: `Stockroom.Desktop.Development`;
- publisher: `CN=Stockroom Development`;
- update host: the reserved `.invalid` namespace;
- no certificate is created, installed, trusted, or used; and
- both the executable and MSIX remain unsigned.

Unless `-SkipReproducibilityProof` is supplied, the command builds the
PyInstaller executable twice in independent directories and requires identical
SHA-256 digests. For an unsigned fixture it also creates the MSIX twice and
requires identical package and App Installer bytes.

Outputs are written under `Artifacts`:

- `Stockroom.exe`
- `Stockroom.Development_<Version>_x64_unsigned.msix`
- `Stockroom.Development.appinstaller`
- `Package Contract\AppxManifest.xml`
- `Payload Manifest.json`
- `Stockroom_TUF_Feed_<Version>.zip`
- `Release Feed Evidence.json`
- `Build Evidence.json`
- `SHA256SUMS.txt`

`Build Evidence.json` records exact digests, SDK/PyInstaller versions,
reproducibility comparison, immutable-release round-trip, managed-host launch
receipt, service generation, coordinator state, frontend proof, policy values,
Git state, and the fixture's signing blocker. `Release Feed Evidence.json`
records every signed metadata and target digest plus an independent trusted
updater round trip.

## Production-input mode

Production mode enforces the real code-signing and offline TUF trust inputs.

```powershell
$env:STOCKROOM_SIGNING_CERT_PASSWORD = "<PFX password from the secret store>"

.\packaging\Build-Windows-Package.ps1 `
  -Mode Production `
  -Version 1.2.3.4 `
  -Publisher "CN=Exact certificate subject, O=Exact organization, C=US" `
  -FeedBaseUri "https://updates.stockroom.com/windows/x64" `
  -SigningCertificatePath "X:\secure\Stockroom-Code-Signing.pfx" `
  -MinGitRoot "X:\release-inputs\MinGit" `
  -WebView2BootstrapperPath "X:\release-inputs\MicrosoftEdgeWebview2Setup.exe" `
  -TufRootPath "X:\release-inputs\Root.json" `
  -TufMetadataVersion 42 `
  -TufTargetsKeyPaths "X:\ephemeral\Targets.pem" `
  -TufSnapshotKeyPaths "X:\ephemeral\Snapshot.pem" `
  -TufTimestampKeyPaths "X:\ephemeral\Timestamp.pem" `
  -RollbackReleaseId "release-1.2.3.3" `
  -CompatibleFromReleaseIds @("release-bootstrap", "release-1.2.3.3")
```

Production mode fails before building when:

- the Git worktree is dirty;
- the feed is not real HTTPS or uses a fixture/loopback host;
- the publisher looks like a development/test identity;
- the PFX or password is absent;
- the PFX lacks a private key or Code Signing EKU;
- the publisher differs byte-for-byte from the certificate subject; or
- pinned MinGit/WebView2 inputs are missing;
- the offline-authored TUF root is absent, malformed, or lacks a valid
  self-signature; or
- an online-role Ed25519 PKCS#8 PEM is absent, unauthorized by that root, or
  fails the configured role threshold;
- the metadata version is not a positive monotonic release sequence; or
- the full packaged managed-host launch proof fails.

The PFX is loaded with `EphemeralKeySet`; the script never installs or trusts
it. SignTool signs and timestamps the executable first, then the MSIX, and
verifies both signatures. Timestamped signatures are intentionally outside the
bit-reproducible unsigned-payload proof.

Windows requires the MSIX package to be signed by a certificate trusted on the
target device. The `.appinstaller` file itself is an HTTPS-hosted XML policy;
its `MainPackage` publisher/name/version must exactly match the signed package.
No self-signed certificate is generated here and an unsigned fixture must never
be described as installable production output.

## GitHub release contract

`.github/workflows/release.yml` has no unsigned publication path. A tag build
or manually dispatched build can only invoke `Build-Windows-Package.ps1` in
`Production` mode. The build job uses the dedicated `Windows Release` GitHub
Environment with read-only repository access; configure that environment's
deployment protection separately. A second job without signing secrets gets
release-write access only for version tags.

Configure these GitHub Environment or repository values before dispatch:

- secrets `WINDOWS_CERT_BASE64` and `WINDOWS_CERT_PASSWORD`;
- secrets `STOCKROOM_TUF_TARGETS_KEY_BASE64`,
  `STOCKROOM_TUF_SNAPSHOT_KEY_BASE64`, and
  `STOCKROOM_TUF_TIMESTAMP_KEY_BASE64`, each containing an unencrypted
  Ed25519 PKCS#8 PEM authorized by the corresponding pinned-root role;
- variables `STOCKROOM_WINDOWS_PUBLISHER` and
  `STOCKROOM_WINDOWS_FEED_BASE_URI`;
- variables `STOCKROOM_MINGIT_URL` and `STOCKROOM_MINGIT_SHA256`; and
- variables `STOCKROOM_WEBVIEW2_BOOTSTRAPPER_URL` and
  `STOCKROOM_WEBVIEW2_BOOTSTRAPPER_SHA256`; and
- public variable `STOCKROOM_TUF_ROOT_BASE64`, containing the offline-authored
  pinned root metadata.

The dependency URLs must be HTTPS URLs on their expected GitHub/Microsoft
upstreams and their configured SHA-256 digests must match. The certificate and
three online TUF keys are decoded only under the ephemeral runner directory.
The certificate is loaded with `EphemeralKeySet`; every secret file is
overwritten and removed in an `always()` step before any artifact upload.

The workflow stages and uploads exactly six files:

- the signed `Stockroom_<Version>_x64.msix`;
- `Stockroom.appinstaller`;
- `Stockroom_TUF_Feed_<Version>.zip`;
- `Release Feed Evidence.json`;
- `Build Evidence.json`; and
- `SHA256SUMS.txt`, covering the other five published files.

Manual runs produce the same verified GitHub Actions artifact without creating
a GitHub release. A version tag may populate a new or asset-empty prerelease,
but it can never replace published assets: TUF metadata bytes are immutable at
a given metadata version. An unexpected artifact, existing published asset,
invalid signature, incomplete managed-runtime evidence, dirty source revision,
invalid TUF root, or missing input stops publication.

## Update policy

`Stockroom.appinstaller.in` uses the 2021 schema and contains exactly:

```xml
<UpdateSettings>
  <OnLaunch
    HoursBetweenUpdateChecks="0"
    ShowPrompt="false"
    UpdateBlocksActivation="false" />
  <AutomaticBackgroundTask />
</UpdateSettings>
```

This gives Windows both a silent check on every launch and its independent
background update task. `ForceUpdateFromAnyVersion` is absent so the stable
host package cannot opt into downgrade through App Installer. Independently,
the in-process broker checks the signed TUF release feed and adopts a verified
candidate without replacing the stable window origin.

`release_feed.py` signs the exact immutable manifest and every declared member,
writes hash-prefixed targets required by the root's consistent-snapshot policy,
authors versioned targets/snapshot metadata plus timestamp metadata, verifies
all online-role thresholds, and stages the result through the real
`TrustedReleaseRepository`. The release workflow derives the next metadata
version from all prior canonical release tags and refuses a package version
older than an existing tag.

The ZIP is a deployment payload, not proof that the configured feed is live.
After publication, an operator or separate deployment system must publish its
`metadata/` and `targets/` trees as an atomic merge at the HTTPS origin
configured by `STOCKROOM_WINDOWS_FEED_BASE_URI`. Existing versioned root
metadata must be retained so clients can traverse every root rotation; files
at an existing metadata version must never be replaced with different bytes.
`Release Feed Evidence.json` and `Build Evidence.json` intentionally retain
`staged-not-deployed` as the production boundary until that external host is
wired.

## Validation and reproducibility

The build fixes:

- `PYTHONHASHSEED=1`;
- `SOURCE_DATE_EPOCH` (default `1704067200`);
- the PyInstaller version from `uv.lock`;
- explicit MinGit/WebView2 and TUF trust inputs; and
- every package staging timestamp.

The installed x64 Windows SDK `MakeAppx.exe` runs without `/nv`, so its normal
semantic validation remains enabled. The command then unpacks the produced
MSIX, requires the executable, manifest, and complete immutable update bundle
to be byte-identical to staging, and reruns the strict Stockroom contract
validator against the unpacked contents and App Installer file. It then starts
that exact unpacked executable in headless acceptance mode and requires a
receipt proving active generation authority, a running workflow coordinator,
the production update channel, and the packaged frontend.

MakeAppx writes its wall clock into ZIP local/central headers even when every
payload timestamp is fixed. After SDK creation, Stockroom normalizes only those
DOS header fields to `SOURCE_DATE_EPOCH`; it does not decompress, recompress,
reorder, or change any package member or block-map byte. The second SDK build
must then match bit-for-bit, and a final SDK unpack/CRC round-trip validates the
normalized container before it is accepted or signed.

Microsoft references:

- [Create packages with MakeAppx](https://learn.microsoft.com/windows/msix/package/create-app-package-with-makeappx-tool)
- [Create an App Installer file](https://learn.microsoft.com/windows/msix/app-installer/how-to-create-appinstaller-file)
- [Automatic update and repair](https://learn.microsoft.com/windows/msix/app-installer/auto-update-and-repair--overview)
- [Sign an MSIX package](https://learn.microsoft.com/windows/msix/package/signing-package-overview)

## Application identity

The EXE, native host window, installed-app entry, Start tile, and taskbar tile
all derive from the same tracked multi-resolution ICO. Its flat grayscale
pad-field mark is generated deterministically rather than edited by hand:

```powershell
uv run python packaging\brand_assets.py --write
uv run python packaging\brand_assets.py --check
```

Every package build runs the check before invoking PyInstaller or MakeAppx, so
stale brand bytes fail closed.

## Development gates

Run the focused contract checks from the repository root:

```powershell
uv run python packaging\brand_assets.py --check
uv run pytest tests\backend\packaging -q
uv run ruff check packaging\brand_assets.py packaging\package_contract.py packaging\release_bundle.py packaging\release_feed.py tests\backend\packaging
uv run ty check packaging\brand_assets.py packaging\package_contract.py packaging\release_bundle.py packaging\release_feed.py tests\backend\packaging

Import-Module PSScriptAnalyzer
Invoke-ScriptAnalyzer `
  -Path packaging\Build-Windows-Package.ps1 `
  -Severity Error,Warning
Invoke-ScriptAnalyzer `
  -Path packaging\build_exe.ps1 `
  -Severity Error,Warning

actionlint .github\workflows\release.yml
uvx --from zizmor zizmor `
  --strict-collection `
  --persona auditor `
  --min-severity informational `
  .github\workflows\release.yml
```
