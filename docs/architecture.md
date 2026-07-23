# Architecture

Stockroom is a KiCad component-library and PCB-project manager for the desktop. This map is the
"where does anything live and why" reference; the step-by-step recipes for extending it are in
[adding-a-feature.md](adding-a-feature.md), and the day-to-day rules are in
[../CONTRIBUTING.md](../CONTRIBUTING.md).

## The shape at a glance

```
┌─────────────────────────────────────────── one desktop process ───────────────────────────────┐
│                                                                                                 │
│   host/  ── a WebView2 window that boots the backend, mints a per-launch token, and points      │
│             the webview at http://127.0.0.1:<port>                                              │
│              │                                                                                   │
│              ▼                                                                                   │
│   app/backend/stockroom  ── a FastAPI app. /api/* is the whole surface; everything below /api   │
│      (Python, no Qt)        is the built SPA served as static files (api routes always win).     │
│              │  reads/writes                                                                      │
│              ▼                                                                                    │
│   the library  ── a git repo of one-JSON-per-part records + the real KiCad files, with a         │
│                   derived, never-committed SQLite index. Every KiCad write goes through a         │
│                   byte-preserving s-expression layer inside one atomic git transaction.          │
│                                                                                                   │
│   app/frontend  ── a React + TypeScript + Tailwind + TanStack Query SPA. Built to                 │
│      (built to app/frontend-dist/, which IS committed because the backend serves it)             │
│                                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The frontend never touches the filesystem or KiCad. It only speaks to `/api/*`. The backend owns
all state, all file I/O, and all KiCad knowledge.

## Backend packages (`app/backend/stockroom/`)

Each package is a cohesive domain. Add code to the one whose job it already is; reach for a new
package only for a genuinely new domain.

| Package | Owns |
|---|---|
| `api/` | The FastAPI app (`app.py`), the request context (`context.py`), the single error→HTTP map (`errors.py`), the bearer-token guard (`security.py`), and one router per surface under `api/routers/`. |
| `model/` | The canonical records (`PartRecord`, `ProjectRecord`) and their JSON shape. The source of truth the index and the API DTOs mirror. |
| `store/` | The library on disk: profiles, the derived SQLite index, per-machine config. |
| `mutation/` | The atomic write engine: `Transaction` (one scoped git commit or full rollback), plus the library/project mutation ops. The ONLY committer. |
| `sexp/` | Layer 0: the byte-preserving s-expression editor. The ONLY thing that edits `.kicad_*` files (scoped span-splices, never a re-serialize). |
| `kicad/` | KiCad domain logic: symbols, footprints, boards, netlists, the CLI wrapper. |
| `ingest/` | Turning a dropped ZIP / vendor bundle into a staged, complete-to-add candidate. |
| `enrich/` | Filling a part's data from distributor APIs + scraped pages (the pipeline, per-field sourcing, passives). |
| `scrape/` | Fetching + extracting distributor/vendor pages (`extract/sites/` is one module per site). |
| `projects/` | Project-level analysis: BOM, fill, checks, buildability. |
| `altium/` | The Altium DbLib emitter + status. |
| `capture/` | The guided cross-EDA asset-capture flow (requirements + session). |
| `host/` | The WebView2 window + launcher + the Windows capture driver. The ONLY place `pywebview` may be imported. |
| `vcs/` | Git: the repo wrapper, GitHub auth. |
| `verify/` | Self-check / doctor helpers. |

**Two invariants that shape everything here:** the backend imports zero Qt (CI greps and fails on
a hit), and every KiCad/`.kicad_pro` edit goes through `sexp/` + `mutation/Transaction` — never a
re-serialize, never a bare file write. See the gitignored agent contract for the full list.

## Frontend structure (`app/frontend/src/`)

| Dir | Owns |
|---|---|
| `api/` | `types.ts` (the response shapes, mirrored from the backend DTOs), `client.ts` (the typed fetch client), `queries.ts` (TanStack Query hooks). This is the whole backend seam. |
| `pages/` | One component per route (Components, Projects, Settings, ...). Wired by `lib/router.tsx` + `lib/nav.ts`. |
| `components/` | Reusable UI. `primitives.tsx` is the kit (Panel, Field, Button, Badge, TabStrip, ...) everything composes from. |
| `lib/` | Non-UI logic + cross-cutting providers: the router, theme, toasts, the spec/attribute registries (`specSchema.ts`, `derive.ts`), the design-token registry + copy layer + dev mode (`devTokens.ts`, `copy.tsx`, `devMode.tsx`), inline-edit, SSE, etc. |
| `styles/` | `index.css` holds the design tokens as CSS variables (dark on `:root`, light on `:root[data-theme=light]`). `tailwind.config.js` maps them to utility classes. |
| `test/` | Test setup. |

## The patterns that keep it modular

New work should extend a **registry or a factory**, not fork a code path. The repo already leans
on these, and following them is what keeps a feature a one-line-here change instead of a new branch
of logic:

- **Router factory** — every API surface is `foo_router(require_token) -> APIRouter`, registered in
  `api/app.py`. Errors are `raise ApiError(status, detail)`; the one handler maps them to HTTP.
- **Spec / attribute registries** — a new parametric spec groups, labels, and units sanely by
  adding one row to `SPEC_REGISTRY` (`lib/specSchema.ts`); a new headline/chip rule is one row in
  `TITLE_REGISTRY` / `ATTRIBUTE_REGISTRY` (`lib/derive.ts`). An unknown key still degrades sanely.
- **Design tokens** — colours/radii are CSS variables; a component uses `bg-raise` / `text-t1` /
  `rounded-card`, never a literal. A token becomes live-editable by adding one row to
  `lib/devTokens.ts`.
- **Copy layer** — a UI label wrapped in `<Text id="...">` (or `useText` for an attribute) is
  reworded through dev mode and ships from `lib/copy.overrides.ts`.
- **Primitives** — build UI by composing `components/primitives.tsx`, so depth, radius, and rhythm
  stay consistent by construction.

## Keeping it healthy

- **The quality gates are the contract** (see [../CONTRIBUTING.md](../CONTRIBUTING.md)): backend
  `pytest`, frontend `test:run` + `typecheck` + `build`, and the committed `frontend-dist/`. A
  change is not done until they pass. Windows CI (`.github/workflows/ci.yml`) is the release gate.
- **`.editorconfig`** pins indentation + line endings so files do not drift across editors.
- **`.pre-commit-config.yaml`** (opt in with `pre-commit install`) formats and lightly lints the
  files you touch, so new code stays clean without a big-bang reformat.

## Known refactors (deferred, tracked)

Honest debt, left for a deliberate pass rather than hidden. These are large files that have grown
past one responsibility; splitting them is safe only when no other branch is mid-flight in them:

- `mutation/project_ops.py` (~1.3k lines) — a god-module; split by concern (bom / checks / fill).
- `projects/bom.py` + `projects/bom_export.py` — overlapping BOM build/format logic to reconcile.
- `enrich/pipeline.py` — the enrichment orchestration is dense; extract per-stage steps.

When you pick one up, do it as its own scoped change with the gates green before and after, and
update this list.
