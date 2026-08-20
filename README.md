# Stockroom

Stockroom is a Windows desktop app for managing a shared KiCad V10 and Altium
component library and the PCB projects that use it. Open a component and choose
**CAD Models > Manage Models** to see every known provider, with complete Symbol +
Footprint + 3D Model sets first. Choose KiCad, Altium, or both, then open any
provider in Stockroom's movable mini browser. Stockroom never drives the provider
page; it validates and attaches only files that arrive for the selected EDAs.
**Choose Downloaded Files** is the manual recovery path. It also audits existing PCB projects, adding
the parts it does not recognize and relinking the ones it does.

The installed app is a native WPF shell with WebView2. It supervises an immutable,
windowless Python worker (FastAPI) that serves the React single-page app; provider pages use a
separate native WebView2 surface inside Stockroom's modal. The library itself is a git repository of one JSON file per part,
with a SQLite index that is derived and never committed. Every write to a
`.kicad_*` file goes through a byte-preserving s-expression layer inside a single
git-backed transaction, so an edit either lands as one clean commit or leaves no
trace.

> New here? [`CONTRIBUTING.md`](CONTRIBUTING.md) is the short path to a clean change.
> [`docs/architecture.md`](docs/architecture.md) is the full module map and the patterns that keep
> the codebase modular; [`docs/adding-a-feature.md`](docs/adding-a-feature.md) is step-by-step
> recipes per extension point.

## Repository layout

    app/backend/stockroom/   Backend package (see "Backend layers" below)
    app/frontend/            React + TypeScript + Tailwind SPA (source)
    app/frontend-dist/       The built SPA the backend serves (committed)
    tests/backend/           Backend test suite, mirroring the package tree
    packaging/               Windows MSIX/App Installer build and release tooling
    docs/                    Architecture, the add-a-feature guide, and the design contract
    scripts/                 Local dev and benchmarking harnesses

### Backend layers

The backend is a stack, low level to high:

- `sexp/` is the byte-preserving s-expression editor. It is the only thing that
  edits `.kicad_*` files, splicing scoped spans and passing everything it doesn't
  model through untouched.
- `model/` holds plain dataclasses for a part, a project, a category.
- `mutation/` is the `Transaction` (the atomic git committer) plus the library and
  project operations built on it.
- `kicad/` reads and writes KiCad files: symbols, footprints, schematics, boards,
  the library tables, and the kicad-cli wrapper.
- `ingest/` takes provider downloads apart: fingerprinting, staging, and preparing
  verified KiCad, Altium, and shared 3D assets.
- `enrich/` and `scrape/` turn a manufacturer part number into specs, datasheets,
  and assets. `scrape/` is the portable headless-browser engine; `enrich/`
  orchestrates it.
- `api/` is the FastAPI app and its routers, plus the per-launch bearer token and
  the job and SSE plumbing.
- `host/` owns the source-development WebView bridge and worker lifecycle helpers;
  `launcher/` is the frozen worker entry point. The visible installed shell lives in
  `app/desktop/Stockroom.WindowHost/`.

### Frontend

`app/frontend/src` holds the SPA. `pages/` has the top-level screens, `components/`
the shared UI (the primitive import surface is `components/primitives.ts`), `api/` the
typed client and the TanStack Query hooks, and `lib/` the router, theme, and
view-model helpers. Design tokens (color, spacing, type, radius) live in
`styles/index.css` and `tailwind.config.js`.

## Developing

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node 20+. KiCad 10 is
optional; the features that use it (ERC, DRC, previews) degrade honestly when it is
missing rather than crashing.

Set up both halves:

    uv sync
    cd app/frontend && npm ci

For the isolated source-development loop, use
`scripts\Start-Stockroom-Development.ps1`; its optional Start menu shortcut is
named **Stockroom Development** and targets one exact checkout. The installed
product is designed as a separate signed WPF/MSIX application. Building and
shipping it is covered in `packaging/README.md`.

## Installing and updating

The supported public Windows route is the
[Microsoft Store](https://apps.microsoft.com/detail/9NQ6HP17PH4H). Microsoft signs
the submitted MSIX after certification and owns installation and updates. Windows
owns the Start menu entry, Installed Apps registration, repair, and uninstall.
Normal startup launches `Stockroom.WindowHost.exe`, which supervises the immutable
packaged backend without invoking a checkout, `uv`, or a system Python environment.

`.github/workflows/store.yml` builds a private unsigned Store candidate only after
canonical CI passes. GitHub continues to host source, release notes, SBOMs,
checksums, and evidence; it does not publish the unsigned Store MSIX as a normal
download. See `packaging/README.md` for the exact package and trust boundaries.

## Verifying a change

The completion authority is the Windows aggregate gate:

    powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1

Its individual layers can be run while developing:

Backend:

    uv run pytest tests/backend

Tests that need the `kicad-cli` binary skip themselves when it is absent, so the
suite is green on a machine without KiCad installed. The write-verification gate is
described in `docs/backend-testing.md`.

Frontend:

    cd app/frontend
    npm run test:run
    npm run typecheck
    npm run build

`npm run build` regenerates `app/frontend-dist/`, which the backend serves. Commit
that rebuilt output in the same commit as the source change that produced it.

Windows CI runs the aggregate gate's backend, native,
frontend, type, production-build, and committed-distribution checks, then builds
the documented unsigned package fixture. The release workflow calls that same CI
workflow before any signed package can publish.

## Adding a feature

The grain of the codebase runs backend to frontend:

1. Build the backend seam first, with a test. Start at the layer that owns the
   change (a model field, a mutation, an enrich step) and write the `pytest`
   before the code.
2. Expose it through an `api/` router.
3. Add the typed call to `api/client.ts` and a TanStack hook in `api/queries.ts`.
4. Build the UI from the shared primitives, following the design contract.
5. Run both verify gates and commit the rebuilt `frontend-dist/` alongside the
   source.

That order keeps the seams testable and the layers honest.
[`docs/adding-a-feature.md`](docs/adding-a-feature.md) turns each of those steps into a concrete
recipe (a new endpoint, an API type, a page, a design token, editable copy, a spec rule).

## Conventions

- The UI follows `docs/design/design-rules.md`: named tokens over scattered
  literals, one small set of radii, Title Case on interactive labels, no em
  dashes. `docs/design/Stockroom Reliability And Design Freedom Decisions.md` is
  the current design authority; `docs/design/north-star-ui.md` is historical context.
- Commits are scoped (`git add <path>`, never `-A`) with a plain one-line message.
- Nothing that touches a `.kicad_*` file bypasses the s-expression layer, and no
  mutation escapes a `Transaction`.
