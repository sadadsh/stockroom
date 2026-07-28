# Settings Readiness Workspace

## Outcome

Settings is a machine-readiness console, not a catalog of collapsed forms. It
answers two questions before exposing controls:

1. Is this installation current and how does it update?
2. What, if anything, does this machine still need?

The page itself does not scroll. The active category owns the bounded internal
scroll region.

## Information architecture

| Category | Owns | Does not own |
| --- | --- | --- |
| General | Appearance and application delivery | Library sharing |
| Library | Active component profile, collaborator sync, GitHub access | App updates |
| EDA Tools | KiCad and Altium machine integration | CAD capture providers |
| Data Sources | Distributor keys, provider sign-ins, procurement refresh | Library repair |
| Maintenance | Completion, derivation, health, binary storage, destructive recovery | Daily setup |

Categories are the only disclosure layer. Every capability in the selected
category is a permanent card with scope, consequence, live status, and its
controls visible. This prevents a theme choice, a credential, a health scan, and
a destructive reset from masquerading as the same generic row.

## Control language

Interactive labels state the result:

- `Switch To This Profile`
- `Pull And Push Library`
- `Recheck And Wire KiCad`
- `Save Paths And Rewire`
- `Save Mouser Key` / `Remove Mouser Key`
- `Save GitHub Access` / `Remove GitHub Access`
- `Fill Supported CAD Gaps`
- `Apply Safe Library Repairs`
- `Install And Restart`

Machine Readiness renders achieved capabilities as quiet state. Only unmet
requirements are buttons, and each button jumps directly to the owning category.

## Backend contract

- Credential updates persist through the machine credential/config layer and
  invalidate the Settings query.
- KiCad path updates rebuild the live CLI/config engines and rewire the active
  library without waiting for restart.
- Profile activation invalidates profile, system, part, facet, and Altium status
  state.
- Library sync refreshes its status and, after a pull, invalidates library and
  Altium projections.
- Update checks fetch before comparing revisions, report offline and unmanaged
  states honestly, and return installed revision, branch, launch policy, and
  check interval.
- Update apply handles fast-forward, safely rebases disjoint local library
  commits, runs the frozen dependency sync, and requests a graceful restart.

## Current delivery truth

The GitHub release executable is a frozen-once portable launcher. It bundles
portable Git, uv, and the WebView2 bootstrapper. The launcher creates a managed
checkout on first run and reconciles it on later launches; active sessions check
every two minutes. This is usable automatic convergence for the current product,
but it is not the signed coherent release-set design accepted for vNext. The
portable launcher itself does not yet self-replace.

## Verification log

- Permanent-card/category behavior: `SettingsPage.test.tsx`, 43 passing cases.
- The full frontend suite passes 1,142 cases across 104 files, including the
  Settings/dev-ID contract.
- Updater Git and route behavior: 9 passing backend cases covering current,
  update-ready, offline, unmanaged, fast-forward, disjoint rebase, restart, and
  refusal paths.
- Settings/profile/sync/system backends: 55 passing backend cases.
- Completion, derivation, CAD reset, repair, and procurement jobs: 35 passing
  backend cases.
- Library mutation/LFS and Altium integration routes: 45 passing backend cases.
- Final dark/light captures of General, Library, and Data Sources at
  1,384 × 861 all measured `settings.root` client/scroll height as 837/837 with
  zero document overflow.
- Windows UI control was intentionally not used during this work. Visual review
  uses the headless Playwright capture harness in both themes.
