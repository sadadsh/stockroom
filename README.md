# Stockroom

Stockroom is a Windows desktop app for managing a KiCad V10 component library and
the PCB projects that use it. You drag in the vendor zips for a part (symbol,
footprint, 3D model), paste the product link, and it converts, names, categorizes,
fills the fields, stores the datasheet and purchase link, and registers everything
with KiCad so the part is usable right away. It also audits an existing KiCad
project: adding the parts it doesn't recognize, relinking the ones it does.

The app is a Python backend (FastAPI) that serves a React single-page app inside a
WebView2 window. The library itself is a git repository of one JSON file per part,
with a SQLite index that is derived and never committed. Every write to a
`.kicad_*` file goes through a byte-preserving s-expression layer inside a single
git-backed transaction, so an edit either lands as one clean commit or leaves no
trace.

## Repository layout

    app/backend/stockroom/   Backend package (see "Backend layers" below)
    app/frontend/            React + TypeScript + Tailwind SPA (source)
    app/frontend-dist/       The built SPA the backend serves (committed)
    tests/backend/           Backend test suite, mirroring the package tree
    packaging/               Windows launcher build (PyInstaller)
    docs/design/             UI design contract and north-star spec
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
- `ingest/` takes vendor zips apart: fingerprinting, staging, and converting to
  KiCad.
- `enrich/` and `scrape/` turn a manufacturer part number into specs, datasheets,
  and assets. `scrape/` is the portable headless-browser engine; `enrich/`
  orchestrates it.
- `api/` is the FastAPI app and its routers, plus the per-launch bearer token and
  the job and SSE plumbing.
- `host/` and `launcher/` are the WebView2 window and the frozen launcher that
  provisions and runs it on Windows.

### Frontend

`app/frontend/src` holds the SPA. `pages/` has the top-level screens, `components/`
the shared UI (styled primitives live in `components/primitives.tsx`), `api/` the
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

The packaged app runs the WebView2 host (`stockroom.host.run`), which starts the
backend (`stockroom.api.serve`) on a loopback port and loads the built SPA in a
native window. Building and shipping the Windows exe is covered in
`packaging/README.md`. For fast UI work, `npm run dev` serves the SPA with hot
reload.

## Verifying a change

Two gates, both green before anything ships.

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

Linux-green is necessary, not sufficient. The release gate is Windows, on the real
library; CI runs the backend suite on both ubuntu-latest and windows-latest
(`.github/workflows/ci.yml`).

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

## Conventions

- The UI follows `docs/design/design-rules.md`: named tokens over scattered
  literals, one small set of radii, Title Case on interactive labels, no em
  dashes. `docs/design/north-star-ui.md` is the end state each screen aims at.
- Commits are scoped (`git add <path>`, never `-A`) with a plain one-line message.
- Nothing that touches a `.kicad_*` file bypasses the s-expression layer, and no
  mutation escapes a `Transaction`.
