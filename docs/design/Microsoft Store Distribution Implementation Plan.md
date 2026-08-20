# Microsoft Store Distribution Implementation Plan

> **For automated workers:** REQUIRED SUB-SKILL: Use work plans:worker-driven-development (recommended) or work plans:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce Stockroom's zero-cost Microsoft Store MSIX, make the Store the package's only update authority, and prepare a truthful first submission without publishing an unsigned public installer.

**Architecture:** Extend the existing Windows package contract with a third, fail-closed `Store` mode rather than creating a second packager. A checked-in Store identity document drives the manifest, package evidence, native worker environment, backend update status, frontend copy, CI artifact, privacy site, and listing source. Store packages retain the immutable built-in release and managed service authority, but they construct no TUF repository, poll no direct feed, and expose only the Microsoft Store product page.

**Tech Stack:** Python 3.12, PowerShell 7, MSIX/MakeAppx, .NET 10 WPF/WebView2, FastAPI, React 19/TypeScript/Vite, Vitest, pytest, GitHub Actions, GitHub Pages.

**Spec:** `docs/design/Microsoft Store Distribution.md`

## Global Constraints

- Microsoft Store is the only public Windows install and update authority.
- Store identity is exactly `Sadad.Stockroom`, publisher `CN=6586C41B-410B-4C94-8631-F025DB362E47`, Store ID `9NQ6HP17PH4H`, and package family `Sadad.Stockroom_p16bsq5x1dh0a`.
- Store package versions are `1.0.<build>.0`; the fourth component is always zero and every component is at most `65535`.
- Store MSIX output is unsigned before upload; Microsoft signs it after certification.
- Store packages contain no active App Installer or TUF feed contract and never poll or activate the reserved GitHub Pages feed.
- Development and direct-production package modes remain behaviorally unchanged.
- GitHub hosts source, release notes, SBOM, checksums, and evidence; it does not present the unsigned Store MSIX as a normal public download.
- No certificate, password, TUF online key, Partner Center credential, or user library enters the Store artifact.
- Frontend source changes require a deterministic committed `app/frontend-dist` rebuild.
- Package upload and final certification submission each require fresh user confirmation immediately before the external action.

---

## File Structure

- `packaging/StoreIdentity.json`: one immutable machine-readable Partner Center identity.
- `packaging/store_distribution.py`: parse and validate Store identity, Store package versions, and the shipped `Distribution.json` marker.
- `packaging/package_contract.py`: add the `Store` package mode and make App Installer rendering conditional.
- `packaging/Build-Windows-Package.ps1`: build one deterministic unsigned Store MSIX without signing or TUF publication inputs.
- `app/desktop/Stockroom.WindowHost/PackagedWorkerRuntime.cs`: read the validated distribution marker and pass the exact update mode to the worker.
- `app/backend/stockroom/host/release_runtime.py`: add the managed Store runtime that retains service authority without direct update convergence.
- `app/backend/stockroom/api/routers/update.py`: expose a truthful `microsoft-store` authority and reject direct apply.
- `app/frontend/src/pages/SettingsPage.tsx`: render Store-specific update copy and open the Store page through the guarded navigation helper.
- `.github/workflows/store.yml`: run canonical CI and build the unsigned Store candidate as a private workflow artifact.
- `store-site/`: public privacy page and minimal Store landing page deployed by GitHub Pages.
- `packaging/StoreListing.json`: reviewed listing copy, support/privacy URLs, and submission instructions.

---

### Task 1: Lock Store Identity And Package Contract

**Files:**
- Create: `packaging/StoreIdentity.json`
- Create: `packaging/store_distribution.py`
- Modify: `packaging/package_contract.py:55-220`
- Modify: `packaging/package_contract.py:426-585`
- Test: `tests/backend/packaging/test_store_distribution.py`
- Test: `tests/backend/packaging/test_windows_package_contract.py`

**Interfaces:**
- Consumes: Partner Center identity recorded in the approved spec.
- Produces: `StoreIdentity.load(path)`, `StoreDistributionMarker`, `PackageConfiguration.for_mode(mode="Store", ...)`, `configuration.update_channel`, and `configuration.requires_appinstaller`.

- [ ] **Step 1: Write failing identity and mixed-authority tests**

```python
def test_store_identity_matches_partner_center() -> None:
    identity = StoreIdentity.load(REPOSITORY_ROOT / "packaging/StoreIdentity.json")
    assert identity.package_name == "Sadad.Stockroom"
    assert identity.publisher == "CN=6586C41B-410B-4C94-8631-F025DB362E47"
    assert identity.store_id == "9NQ6HP17PH4H"
    assert identity.package_family_name == "Sadad.Stockroom_p16bsq5x1dh0a"
    assert identity.store_uri == "https://apps.microsoft.com/detail/9NQ6HP17PH4H"


def test_store_package_refuses_direct_feed_or_nonzero_revision() -> None:
    with pytest.raises(PackageContractError, match="Store package cannot use a direct feed"):
        PackageConfiguration.for_mode(
            mode="Store",
            publisher=STORE_PUBLISHER,
            version="1.0.42.0",
            feed_base_uri="https://sadadsh.github.io/stockroom/windows/x64",
            signing_certificate_provided=False,
        )
    with pytest.raises(PackageContractError, match="fourth component must be zero"):
        PackageConfiguration.for_mode(
            mode="Store",
            publisher=STORE_PUBLISHER,
            version="1.0.42.1",
            feed_base_uri="",
            signing_certificate_provided=False,
        )
```

- [ ] **Step 2: Run the focused RED tests**

Run: `uv run pytest tests/backend/packaging/test_store_distribution.py tests/backend/packaging/test_windows_package_contract.py -q`

Expected: FAIL because Store identity types and `Store` mode do not exist.

- [ ] **Step 3: Add the immutable identity document and strict parser**

```json
{
  "schema": "stockroom-microsoft-store-identity/1",
  "product_name": "Stockroom",
  "store_id": "9NQ6HP17PH4H",
  "package_name": "Sadad.Stockroom",
  "publisher": "CN=6586C41B-410B-4C94-8631-F025DB362E47",
  "publisher_display_name": "Sadad",
  "package_family_name": "Sadad.Stockroom_p16bsq5x1dh0a",
  "store_uri": "https://apps.microsoft.com/detail/9NQ6HP17PH4H"
}
```

Implement `StoreIdentity.load()` with duplicate-key rejection, exact key-set validation, absolute HTTPS Store URI validation, and exact derived package-family validation. Implement `StoreDistributionMarker` with schema `stockroom-distribution/1`, channel `microsoft-store`, Store ID, package name, publisher, Store URI, and version.

- [ ] **Step 4: Extend `PackageConfiguration` without weakening existing modes**

```python
@property
def update_channel(self) -> str:
    return "microsoft-store" if self.mode == "store" else self.mode

@property
def requires_appinstaller(self) -> bool:
    return self.mode != "store"
```

For Store mode, load the checked-in identity, require exact publisher, require an empty feed URI, require `signing_certificate_provided is False`, require a nonzero major version and zero fourth component, use package name `Sadad.Stockroom`, application ID `Stockroom`, display name `Stockroom`, and publisher display name `Sadad`. Render `AppxManifest.xml`, assets, version info, and `Support/Distribution.json`; do not render or validate an App Installer file.

- [ ] **Step 5: Run GREEN tests and existing package regressions**

Run: `uv run pytest tests/backend/packaging/test_store_distribution.py tests/backend/packaging/test_windows_package_contract.py tests/backend/packaging/test_release_evidence.py -q`

Expected: PASS; Fixture and Production expectations remain unchanged.

- [ ] **Step 6: Commit the package contract**

```powershell
git add packaging/StoreIdentity.json packaging/store_distribution.py packaging/package_contract.py tests/backend/packaging/test_store_distribution.py tests/backend/packaging/test_windows_package_contract.py
git commit -m "feat: add Microsoft Store package identity"
```

---

### Task 2: Build A Deterministic Unsigned Store MSIX

**Files:**
- Modify: `packaging/Build-Windows-Package.ps1:1-1250`
- Modify: `packaging/release_bundle.py`
- Modify: `packaging/package_probe.py`
- Test: `tests/backend/packaging/test_managed_runtime_package.py`
- Test: `tests/backend/packaging/test_release_evidence.py`
- Test: `tests/backend/packaging/test_store_package_script.py`

**Interfaces:**
- Consumes: Store `PackageConfiguration` and `StoreDistributionMarker` from Task 1.
- Produces: `Build-Windows-Package.ps1 -Mode Store -Version 1.0.<build>.0 -OutputRoot <path>` and exactly one upload artifact `Stockroom_<version>_x64_store.msix` plus local build evidence.

- [ ] **Step 1: Write failing Store build-script contract tests**

```python
def test_store_build_needs_no_signing_or_tuf_material() -> None:
    script = PACKAGE_SCRIPT.read_text(encoding="utf-8")
    assert '[ValidateSet("Fixture", "Production", "Store")]' in script
    assert '$Mode -eq "Store"' in script
    assert 'update_channel = "microsoft-store"' in script
    assert 'store-unsigned' in script


def test_store_output_excludes_direct_update_artifacts(store_build: Path) -> None:
    names = {path.name for path in store_build.iterdir() if path.is_file()}
    assert names == {
        "Stockroom_1.0.42.0_x64_store.msix",
        "Build Evidence.json",
        "Checksums.sha256",
    }
```

- [ ] **Step 2: Run the Store packaging RED tests**

Run: `uv run pytest tests/backend/packaging/test_store_package_script.py tests/backend/packaging/test_release_evidence.py -q`

Expected: FAIL because `Store` is not an accepted PowerShell mode and evidence is production-only.

- [ ] **Step 3: Add Store mode to the existing build pipeline**

Implement these exact branches:

```powershell
$IsFixture = $Mode -ceq "Fixture"
$IsDirectProduction = $Mode -ceq "Production"
$IsStore = $Mode -ceq "Store"
$SigningCertificateProvided = $IsDirectProduction
$UpdateChannel = if ($IsStore) { "microsoft-store" } elseif ($IsDirectProduction) { "production" } else { "fixture" }
```

Store mode loads `packaging/StoreIdentity.json`, refuses `-SigningCertificatePath`, `-FeedBaseUri`, TUF key paths, rollback IDs, and compatible-release overrides, and still builds the same frontend, PyInstaller worker, native host, CAD converter, SBOM, notices, immutable initial release, semantic MSIX validation, unpack/repack check, managed host probe, and package probe. It skips App Installer generation, release-feed generation, Authenticode verification, and TUF round-trip verification. Evidence records `mode: store`, `update_channel: microsoft-store`, `signing.state: store-unsigned`, exact Store identity, Git revision, frontend content revision, and package SHA-256.

- [ ] **Step 4: Add deterministic Store package proof**

Build Store mode twice into separate temporary roots, normalize MSIX ZIP timestamps through the existing `normalize-msix` command, and compare package SHA-256 plus unpacked directory fingerprints. Never weaken Production signing checks to make Store pass.

- [ ] **Step 5: Run the focused package suite**

Run: `uv run pytest tests/backend/packaging/test_store_package_script.py tests/backend/packaging/test_managed_runtime_package.py tests/backend/packaging/test_release_evidence.py -q`

Expected: PASS with direct-production signing/TUF tests still green.

- [ ] **Step 6: Build the first local candidate twice**

```powershell
$a = Join-Path $env:TEMP 'Stockroom Store A'
$b = Join-Path $env:TEMP 'Stockroom Store B'
& .\packaging\Build-Windows-Package.ps1 -Mode Store -Version 1.0.1.0 -OutputRoot $a
& .\packaging\Build-Windows-Package.ps1 -Mode Store -Version 1.0.1.0 -OutputRoot $b
Get-FileHash "$a\Artifacts\Stockroom_1.0.1.0_x64_store.msix" -Algorithm SHA256
Get-FileHash "$b\Artifacts\Stockroom_1.0.1.0_x64_store.msix" -Algorithm SHA256
```

Expected: identical SHA-256 values and zero App Installer/TUF feed files.

- [ ] **Step 7: Commit the Store packager**

```powershell
git add packaging/Build-Windows-Package.ps1 packaging/release_bundle.py packaging/package_probe.py tests/backend/packaging/test_store_package_script.py tests/backend/packaging/test_managed_runtime_package.py tests/backend/packaging/test_release_evidence.py
git commit -m "feat: build unsigned Microsoft Store packages"
```

---

### Task 3: Make Microsoft Store The Only Runtime Update Authority

**Files:**
- Modify: `app/desktop/Stockroom.WindowHost/PackagedWorkerRuntime.cs:54-103`
- Modify: `app/desktop/Stockroom.WindowHost/PackagedWorkerRuntime.cs:517-550`
- Modify: `app/backend/stockroom/host/release_runtime.py:101-109`
- Modify: `app/backend/stockroom/host/release_runtime.py:1342-1769`
- Modify: `app/backend/stockroom/host/release_runtime.py:1934-2166`
- Modify: `app/backend/stockroom/host/run.py:510-705`
- Modify: `app/backend/stockroom/api/routers/update.py:35-108`
- Test: `tests/native/Stockroom.WindowHost.Tests/PackagedWorkerRuntimeTests.cs`
- Test: `tests/backend/host/test_release_runtime.py`
- Test: `tests/backend/api/test_host_run.py`
- Test: `tests/backend/api/test_update_api.py`

**Interfaces:**
- Consumes: shipped `Support/Distribution.json` from Tasks 1-2.
- Produces: `HostUpdateMode.MICROSOFT_STORE`, `StoreUpdateRuntime.status()`, and API `channel: "microsoft-store"` with `store_uri`.

- [ ] **Step 1: Write native and backend RED tests**

```csharp
[Fact]
public void StoreDistributionPassesOnlyMicrosoftStoreUpdateMode()
{
    var release = PackagedRelease.Resolve(storePackageRoot);
    Assert.Equal("microsoft_store", release.UpdateMode);
    Assert.Equal("https://apps.microsoft.com/detail/9NQ6HP17PH4H", release.StoreUri);
    var start = PackagedWorkerRuntime.CreateStartInfoForTest(release, 42119, "token", "proof");
    Assert.Equal("microsoft_store", start.Environment["STOCKROOM_UPDATE_MODE"]);
    Assert.False(start.Environment.ContainsKey("STOCKROOM_UPDATE_BUNDLE_ROOT"));
}
```

```python
def test_store_runtime_never_constructs_a_direct_repository(monkeypatch, app_ctx) -> None:
    monkeypatch.setenv("STOCKROOM_UPDATE_MODE", "microsoft_store")
    monkeypatch.setattr(release_runtime, "TrustedReleaseRepository", Mock(side_effect=AssertionError))
    runtime = create_store_update_runtime(context=app_ctx, release_id="release-store")
    assert runtime.status()["channel"] == "microsoft-store"
    assert runtime.status()["store_uri"] == STORE_URI
    assert runtime.activate_ready() is False
```

- [ ] **Step 2: Run focused RED tests**

Run: `dotnet test tests/native/Stockroom.WindowHost.Tests/Stockroom.WindowHost.Tests.csproj --filter PackagedWorkerRuntimeTests`

Run: `uv run pytest tests/backend/host/test_release_runtime.py tests/backend/api/test_host_run.py tests/backend/api/test_update_api.py -q`

Expected: FAIL because the host always exports `production` and no Store runtime exists.

- [ ] **Step 3: Validate the marker in the native host before spawning**

Extend `PackagedRelease` with `UpdateMode` and `StoreUri`. Exact Store identity yields `microsoft_store`; missing marker preserves `production` for the existing direct package. Reject malformed JSON, unknown channels, Store identity with a production channel, and a Store marker paired with `Update/Update Feed.json`. Export `STOCKROOM_UPDATE_BUNDLE_ROOT` only for direct production.

- [ ] **Step 4: Extract common managed-release service ownership**

Refactor the production runtime composition so both direct and Store modes seed/verify the immutable packaged release, acquire the service authority, preserve the prior generation for rollback, expose native shell/provider surfaces, and retain personal data. Only direct production constructs `TrustedReleaseRepository`, `ProductionUpdateRuntime`, and its convergence thread. Store mode returns a small `StoreUpdateRuntime` whose status is:

```python
{
    "update_available": False,
    "state": "store_managed",
    "detail": "Microsoft Store manages installation and updates.",
    "current_release_id": release_id,
    "target_release_id": "",
    "current_revision": release_id,
    "target_revision": "",
    "channel": "microsoft-store",
    "store_uri": "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
    "automatic_on_launch": True,
    "automatic_apply": True,
    "check_interval_seconds": 0,
}
```

- [ ] **Step 5: Make `/api/update/apply` fail closed for Store packages**

Return HTTP `409` with state `store_managed`, `updated: false`, and detail `Microsoft Store owns Stockroom updates.`. The GET route returns the Store status and frontend revision; it never invokes `AppUpdater` or a TUF broker.

- [ ] **Step 6: Run the native/backend GREEN suites**

Run: `dotnet test tests/native/Stockroom.WindowHost.Tests/Stockroom.WindowHost.Tests.csproj`

Run: `uv run pytest tests/backend/host/test_release_runtime.py tests/backend/api/test_host_run.py tests/backend/api/test_update_api.py -q`

Expected: PASS; direct production convergence tests remain unchanged.

- [ ] **Step 7: Commit runtime authority**

```powershell
git add app/desktop/Stockroom.WindowHost/PackagedWorkerRuntime.cs app/backend/stockroom/host/release_runtime.py app/backend/stockroom/host/run.py app/backend/stockroom/api/routers/update.py tests/native/Stockroom.WindowHost.Tests/PackagedWorkerRuntimeTests.cs tests/backend/host/test_release_runtime.py tests/backend/api/test_host_run.py tests/backend/api/test_update_api.py
git commit -m "feat: delegate Store updates to Microsoft"
```

---

### Task 4: Render Truthful Store Update UI

**Files:**
- Modify: `app/frontend/src/api/types.ts:1527-1549`
- Modify: `app/frontend/src/pages/SettingsPage.tsx:300-350`
- Modify: `app/frontend/src/pages/SettingsPage.tsx:1539-1728`
- Modify: `app/frontend/src/pages/SettingsPage.test.tsx`
- Modify: `app/frontend/src/design-studio/scenarios/settings.ts`
- Modify: `app/frontend/src/design-studio/scenarios/settings.test.tsx`
- Modify: `app/frontend/src/lib/devIds.ts`
- Test: `app/frontend/src/lib/copy.coverage.test.ts`

**Interfaces:**
- Consumes: API `channel` and `store_uri` from Task 3.
- Produces: Store-specific Settings card with one guarded `Open Microsoft Store` action and no direct-updater controls.

- [ ] **Step 1: Write failing Store UI tests**

```tsx
it("shows Microsoft Store as the only update authority", async () => {
  mockApi.checkUpdate.mockResolvedValue({
    update_available: false,
    state: "store_managed",
    channel: "microsoft-store",
    store_uri: "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
    automatic_on_launch: true,
    automatic_apply: true,
  });
  await openSettings("settings.update");
  expect(screen.getAllByText("Updates From Microsoft Store").length).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole("button", { name: "Open Microsoft Store" }));
  expect(window.open).toHaveBeenCalledWith(
    "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
    "_blank",
    "noreferrer",
  );
  expect(screen.queryByRole("button", { name: "Restart Now" })).not.toBeInTheDocument();
  expect(screen.queryByText("View Releases")).not.toBeInTheDocument();
  expect(mockApi.applyUpdate).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the focused frontend RED tests**

Run: `npm.cmd --prefix app/frontend run test:run -- src/pages/SettingsPage.test.tsx src/design-studio/scenarios/settings.test.tsx`

Expected: FAIL because the type and Store branch do not exist.

- [ ] **Step 3: Add the Store API type and a dedicated rendering branch**

Add `store_uri?: string` to `UpdateCheck`. When `channel === "microsoft-store"`, machine summary copy is `Updates From Microsoft Store`; `UpdateSection` renders authority, installed version, status `Managed By Microsoft Store`, the short explanation `Microsoft Store installs trusted Stockroom updates automatically.`, and one button. The button calls `openExternalUrl(check.data.store_uri)` so Design Studio preview effects remain fail-closed. Do not render remote revision, retry, rollback, restart, direct release, or App Installer language.

- [ ] **Step 4: Add one exact Store scenario**

Add `settings.update-store` to the explicit Settings state contract with fixture status `microsoft-store` and expected targets `settings.root`, `settings.update`, and the Store action ID. Keep total scenario parity exact by replacing the obsolete direct-release-only alias rather than adding an indistinguishable state.

- [ ] **Step 5: Run UI, copy, identity, and type gates**

Run: `npm.cmd --prefix app/frontend run test:run -- src/pages/SettingsPage.test.tsx src/design-studio/scenarios/settings.test.tsx src/lib/copy.coverage.test.ts src/lib/devIds.parity.test.ts`

Run: `npm.cmd --prefix app/frontend run typecheck`

Expected: PASS.

- [ ] **Step 6: Commit the Store UI**

```powershell
git add app/frontend/src/api/types.ts app/frontend/src/pages/SettingsPage.tsx app/frontend/src/pages/SettingsPage.test.tsx app/frontend/src/design-studio/scenarios/settings.ts app/frontend/src/design-studio/scenarios/settings.test.tsx app/frontend/src/lib/devIds.ts app/frontend/src/lib/copy.coverage.test.ts
git commit -m "feat: show Microsoft Store update authority"
```

---

### Task 5: Add Private Store Build Workflow And Public Policy Site

**Files:**
- Create: `.github/workflows/store.yml`
- Create: `.github/workflows/pages.yml`
- Create: `tests/backend/packaging/test_store_workflow.py`
- Create: `store-site/index.html`
- Create: `store-site/privacy/index.html`
- Create: `packaging/StoreListing.json`
- Create: `tests/backend/packaging/test_store_listing.py`
- Modify: `README.md:83-105`
- Modify: `packaging/README.md`

**Interfaces:**
- Consumes: Store packager from Task 2 and Store URI/identity from Task 1.
- Produces: private workflow artifact `Stockroom-Microsoft-Store-<version>`, public privacy URL `https://sadadsh.github.io/stockroom/privacy/`, and versioned listing source.

- [ ] **Step 1: Write failing workflow/listing tests**

```python
def test_store_workflow_has_no_signing_or_public_release_permissions() -> None:
    workflow = load_workflow(".github/workflows/store.yml")
    assert workflow["permissions"] == {}
    build = workflow["jobs"]["build-store-package"]
    assert build["needs"] == "quality-gate"
    assert build["permissions"] == {"contents": "read"}
    assert "WINDOWS_CERT" not in STORE_WORKFLOW_TEXT
    assert "STOCKROOM_TUF" not in STORE_WORKFLOW_TEXT
    assert "gh release" not in STORE_WORKFLOW_TEXT
    assert "-Mode Store" in STORE_WORKFLOW_TEXT


def test_listing_uses_public_policy_and_exact_store_identity() -> None:
    listing = json.loads(STORE_LISTING.read_text(encoding="utf-8"))
    assert listing["store_id"] == "9NQ6HP17PH4H"
    assert listing["privacy_policy"] == "https://sadadsh.github.io/stockroom/privacy/"
    assert listing["price"] == "free"
    assert "automatic provider download" not in listing["description"].casefold()
```

- [ ] **Step 2: Run RED tests**

Run: `uv run pytest tests/backend/packaging/test_store_workflow.py tests/backend/packaging/test_store_listing.py -q`

Expected: FAIL because workflow, site, and listing do not exist.

- [ ] **Step 3: Create the private Store artifact workflow**

The workflow is `workflow_dispatch` only for the first submission. It calls reusable canonical `ci.yml`, checks out the exact revision with credentials disabled, installs pinned uv/.NET/Node routes already used by `release.yml`, computes `1.0.<github.run_number>.0` with a hard `1..65535` build limit, runs Store mode, validates the exact three-file output allowlist, and uploads it through pinned `actions/upload-artifact` with `retention-days: 14`. It has no `contents: write`, Pages, OIDC, environment, signing secret, TUF secret, Partner Center credential, or GitHub Release step.

- [ ] **Step 4: Create the privacy and Store landing pages**

The privacy policy states: Stockroom stores libraries, drafts, applied designs, settings, and provider download staging on the user's PC; sends part identifiers to configured Mouser/DigiKey APIs and pages the user explicitly opens; may open third-party provider pages whose own policies apply; stores API secrets in Windows Credential Manager when supported; has no Stockroom-operated advertising, analytics, or telemetry service; and provides deletion through library removal/uninstall plus linked support. The landing page links the Store product, GitHub source, issues, release notes, and privacy page.

The Pages workflow deploys only `store-site/`, uses pinned official Pages actions, and has `pages: write` plus `id-token: write` only in its deployment job.

- [ ] **Step 5: Create reviewed listing source**

`StoreListing.json` includes title `Stockroom`, short description, full description, feature bullets, search terms, free price, Windows desktop/x64 device family, support URL, privacy URL, release notes, and testing instructions: create or select a library, add a component by exact MPN, open CAD Models > Manage Models, and use provider pages manually when required. It must not claim universal CAD availability, automatic sign-in, CAPTCHA bypass, or unattended provider automation.

- [ ] **Step 6: Run workflow, policy, link, and actionlint checks**

Run: `uv run pytest tests/backend/packaging/test_store_workflow.py tests/backend/packaging/test_store_listing.py -q`

Run: `actionlint .github/workflows/store.yml .github/workflows/pages.yml`

Run: `uv run python scripts/check_markdown_links.py README.md docs packaging`

Expected: PASS.

- [ ] **Step 7: Commit workflow and public policy**

```powershell
git add .github/workflows/store.yml .github/workflows/pages.yml tests/backend/packaging/test_store_workflow.py tests/backend/packaging/test_store_listing.py store-site packaging/StoreListing.json README.md packaging/README.md
git commit -m "feat: prepare Microsoft Store submission"
```

---

### Task 6: Verify The Complete Store Candidate

**Files:**
- Modify: `app/frontend-dist/**`
- Modify: `docs/design/Visual Audit Backlog.md`
- Modify: `docs/design/Stockroom Reliability And Design Freedom Decisions.md`
- Modify: canonical Stockroom `Current State.md` resolved through the project registry.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: settled source, synchronized frontend distribution, deterministic Store MSIX, visual evidence, canonical gate evidence, and a reviewed upload candidate.

- [ ] **Step 1: Run focused Store gates**

```powershell
uv run pytest tests/backend/packaging/test_store_distribution.py tests/backend/packaging/test_windows_package_contract.py tests/backend/packaging/test_store_package_script.py tests/backend/packaging/test_store_workflow.py tests/backend/packaging/test_store_listing.py tests/backend/host/test_release_runtime.py tests/backend/api/test_update_api.py -q
dotnet test tests/native/Stockroom.WindowHost.Tests/Stockroom.WindowHost.Tests.csproj
npm.cmd --prefix app/frontend run test:run -- src/pages/SettingsPage.test.tsx src/design-studio/scenarios/settings.test.tsx
npm.cmd --prefix app/frontend run typecheck
```

Expected: every command exits zero.

- [ ] **Step 2: Rebuild and prove deterministic frontend distribution**

Run: `npm.cmd --prefix app/frontend run build`

Record all `app/frontend-dist` SHA-256 values, run the build again, and require the same path set and byte hashes. Stage the synchronized distribution only after both builds match.

- [ ] **Step 3: Run the canonical Windows gate**

Run: `powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1`

Expected: actionlint, Ruff, backend typecheck/tests, native host, CAD converter, frontend tests/typecheck/build, and frontend-dist synchronization all pass on one settled tree.

- [ ] **Step 4: Build and compare two Store packages**

Build `1.0.<build>.0` twice from the exact candidate commit. Require identical MSIX SHA-256, identical unpacked fingerprints, the exact Partner Center identity, `microsoft-store` evidence, no App Installer, no `Update Feed.json`, no TUF metadata, no signature/private key, and no unexpected file.

- [ ] **Step 5: Inspect the current-source packaged layout**

Launch the unpacked Store package's native host/worker through the existing package probe with isolated `LOCALAPPDATA`, `APPDATA`, and Stockroom config roots. Inspect Settings in light and dark at 1366x872 and 1600x1000. Verify `Updates From Microsoft Store`, the Store action, no direct updater controls, managed provider modal operation, library persistence, Design Studio entry, no gray screen, no clipped content, and no console/network error. Record screenshots and findings in `docs/design/Visual Audit Backlog.md`.

- [ ] **Step 6: Update durable decisions and current state**

Record the Store identity, fourth-component version rule, one-update-authority rule, exact test/build hashes, privacy URL, Store URL, and remaining Partner Center submission boundary. Refresh the canonical QMD collection and verify one Stockroom Current State alias retrieval.

- [ ] **Step 7: Commit settled evidence and generated output**

```powershell
git add app/frontend-dist docs/design/Visual\ Audit\ Backlog.md docs/design/Stockroom\ Reliability\ And\ Design\ Freedom\ Decisions.md docs/design/Microsoft\ Store\ Distribution.md docs/design/Microsoft\ Store\ Distribution\ Implementation\ Plan.md
git commit -m "chore: verify Microsoft Store candidate"
```

---

### Task 7: Upload And Submit With Two Explicit Human Gates

**Files:**
- No repository mutation after the verified candidate commit except a factual Current State update if Partner Center reports a validation result.

**Interfaces:**
- Consumes: exact candidate MSIX, package SHA-256, `StoreListing.json`, privacy URL, screenshots, and test instructions.
- Produces: Partner Center validation result and, only after separate approval, a certification submission.

- [ ] **Step 1: Review the complete submission locally**

Present the exact MSIX path/hash/version, listing copy, privacy URL, screenshots, supported devices, free price, age-rating answers, testing instructions, and canonical gate result together. Confirm that GitHub exposes no unsigned normal installer.

- [ ] **Step 2: Stop for upload confirmation**

Ask: `Upload Stockroom_<version>_x64_store.msix to Partner Center now?` Do not browse to the file picker or transfer the file before the user confirms this exact action.

- [ ] **Step 3: Upload and record Partner Center validation**

After confirmation, upload only the verified MSIX. Record Partner Center's package identity, version, architecture, device-family ranking, warnings, and errors. If validation fails, remove the rejected package, fix source locally through a new RED/GREEN cycle, rebuild, and return to Step 1.

- [ ] **Step 4: Complete listing sections without certification**

Enter the reviewed free pricing, properties, age rating, listing copy, privacy/support URLs, screenshots, release notes, and testing instructions. Save the draft but do not click the final certification action.

- [ ] **Step 5: Stop for final certification confirmation**

Show the completed submission summary and ask: `Submit Stockroom 1.0 to Microsoft certification now?` Do not click the final action until the user confirms.

- [ ] **Step 6: Submit and monitor**

After confirmation, submit once. Record submission ID, time, and current status. A rejection remains a Store-owned draft correction; it must not enable the direct updater or publish the unsigned MSIX on GitHub.

- [ ] **Step 7: Close the release only after Store proof**

After certification, install Stockroom from its public Store page on this PC, launch it, verify running package identity `Sadad.Stockroom`, confirm Microsoft Store update authority in Settings, verify a persisted library and Design Studio draft, and update Current State/QMD with the public Store result.

