# Stockroom Instructions

Read `docs\architecture.md`, `docs\adding-a-feature.md`, and the workspace
registry-linked canonical Stockroom `Current State.md` before changing
behavior. `CONTRIBUTING.md` defines the product gates.

## Environment

- Native Windows is authoritative. Use Python 3.12 through `uv`; do not use
  bare `py -3`.
- Install locked dependencies with `uv sync --frozen` and
  `npm.cmd --prefix app\frontend ci`.
- `scripts\Gates.ps1` is the Windows aggregate gate. The Bash and WSL bridge
  scripts are not Windows entry points.
- The Windows gate exposes an installed KiCad 10 CLI from Program Files when
  it is not already on `PATH`, then reports the verified CLI version.

## Product Invariants

- The frontend talks only to `/api/*`; it never owns filesystem or KiCad logic.
- The backend imports no Qt. Only `stockroom.host` may import `pywebview`.
- Every KiCad write uses the byte-preserving `sexp` layer inside one
  `mutation.Transaction`; never reserialize or write a KiCad file directly.
- Extend existing registries and factories before adding parallel code paths.
- UI uses design tokens and primitives. Interactive labels are Title Case,
  prose is sentence case, and new behavior gets a test.
- `app\frontend-dist` is committed and must be rebuilt with frontend source.

## Completion

- Run `powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1`.
- The gate snapshots the current working `app\frontend-dist` before its build
  and requires the build to leave every path and byte unchanged. Existing
  generated changes are valid input; synchronization is not inferred from
  comparison with `HEAD`.
- Do not call skipped credential-, browser-, or machine-dependent checks
  passing evidence. State exactly what ran and what remains.
- UI or host changes require real Windows/WebView2 inspection in both themes,
  in addition to automated gates.
- Test, demo, and screenshot fixtures must set `STOCKROOM_CONFIG_DIR` to a
  task-owned temporary directory. Never repoint the live machine config at a
  fixture or `work\` library; after native acceptance, verify the live config
  still names the canonical library root and profile. Passing a directly
  constructed `MachineConfig` into `build_context` is not isolation: any later
  Settings or library mutation can still resolve `save()` to the live default
  path unless `STOCKROOM_CONFIG_DIR` was set before app import.
- Every screenshot is also a visual audit. Deduplicate observations into
  `docs\design\Visual Audit Backlog.md` with the exact evidence capture; only a
  finding that invalidates current acceptance evidence interrupts the active slice.
- Live enrichment and vendor access are opt-in. Never expose or commit machine
  configuration, supplier credentials, passwords, or GitHub tokens.
- Preserve unrelated changes and stage scoped paths, never `git add -A`.
