# Stockroom 0.7.0

Stockroom 0.7.0 makes the standalone Windows release usable on a fresh online
computer and adds the source-backed owner Dev Mode.

## Fresh Windows Setup

- The portable EXE carries pinned MinGit and Git LFS, Node/npm, a Microsoft-signed
  WebView2 bootstrapper, `uv`, and the complete self-contained native CAD converter.
- The launcher installs the converter atomically under LocalAppData and exposes
  it to the continuously updated source host before any CAD workflow starts.
- Python is pinned to 3.12.13 and first-run sync installs production dependencies,
  not the development test toolchain.
- Setup work executes once. A worker or host startup failure reaches the visible
  Windows error boundary instead of silently retrying or disappearing.
- This is a no-manual-prerequisite online bootstrap. It does not claim offline
  first launch because the public app checkout, Python packages, and provider
  browser builds are downloaded during initial setup.

## Get Files Reliability

- A provider stage recovered after an expired worker lease now safely replans
  from exact identity and retained evidence. It is no longer misclassified as a
  malformed provider retry and failed immediately.
- Failed workflows report the exact stage with actionable retry guidance instead
  of replacing every cause with a generic publication sentence.
- Native P-CAD `.lia` conversion is available from the standalone EXE, without
  Altium and without a separately installed converter.

## Owner Dev Mode

- Registered UI boundaries can be selected visually or from the catalogue and
  adjusted through Tokens, Copy, Icon, Box, and Behavior editors.
- Single-choice controls can switch among Dropdown, Segmented Control, Radio
  Group, and Searchable Picker while retaining their data and semantics.
- Undo and Redo cover all editor domains. Save writes reviewable generated source;
  Publish To Main is gated to a clean, current `main` checkout and owned paths.
- Publish installs the exact locked frontend dependency set before type checking and
  building, so a machine-wide Node or npm installation is not required.

## User-Owned Boundaries

- The portable EXE is currently unsigned, so Windows may show a SmartScreen warning until
  the owner supplies a trusted code-signing certificate.
- Stockroom never embeds a GitHub credential, distributor account, or API secret. Dev Mode
  publishing and authenticated provider access use credentials configured by that Windows user.
- KiCad and Altium remain separate EDA applications; Stockroom bundles its native CAD
  converter, not either editor or Altium license.

## Acceptance

- Full frontend: 1,404 tests across 130 files.
- Launcher, packaging, provider workflow, and workflow store: 177 focused tests;
  the final production-dependency package contract adds 29 passing checks.
- TypeScript, Ruff, Windows-targeted Python type checking, actionlint, production
  frontend build/token parity, PowerShell parsing, and Git diff checks pass.
- A clean-revision reproducible package build completed the managed-host and native
  converter probes and recorded exact digests for MinGit, Git LFS, Node/npm,
  WebView2, and the converter.
- A prerequisite-scrubbed clean Windows profile cloned the live public source with
  bundled Git/Git LFS, provisioned exact Python 3.12.13 and the provider browser
  runtime, installed the bundled converter, materialized real LFS payloads, and
  reached the visible Components workspace in both themes. The native converter
  then produced and strictly read back nonempty `.SchLib` and `.PcbLib` files.
- The GitHub asset is accepted only after the final rebuilt bytes repeat that
  no-argument clean-profile launch and the downloaded asset matches the accepted
  SHA-256 digest.
