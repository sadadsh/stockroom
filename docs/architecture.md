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
│   one library repo ── one independent git repo per component collection: one-JSON-per-part       │
│                      records + real KiCad/Altium assets and a derived SQLite index. Every write   │
│                   byte-preserving s-expression layer inside one atomic git transaction.          │
│                                                                                                   │
│   app/frontend  ── a React + TypeScript + Tailwind + TanStack Query SPA. Built to                 │
│      (built to app/frontend-dist/, which IS committed because the backend serves it)             │
│                                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The frontend never touches the filesystem or KiCad. It only speaks to `/api/*`. The backend owns
all state, all file I/O, and all KiCad knowledge. The application repository never contains a
user library: each library has its own root, Git history, optional remote, and collaborator ACL.
Changing libraries means changing repositories. The legacy one-profile folder inside a migrated
library is an internal disk-compatibility boundary, not a user-facing workspace concept.

## Windows process and delivery boundary

Windows launches only the signed WPF executable declared by the MSIX:
`WindowHost\Stockroom.WindowHost.exe`. The host owns single-instance activation,
the visible WebView2 window, rotating diagnostics, and one crash-contained worker
job. It resolves the package's TUF-bound built-in release, launches
`Backend\Stockroom Worker.exe --port <loopback-port>`, and waits for an
identity-aware health response before showing the window.

The worker is a PyInstaller onedir runtime. It serves the committed frontend and
owns backend/service coordination; it has no interactive entry point. Production
startup does not execute application Git source, `uv`, or a source Python. It also
does not install WebView2 or provider browsers. Windows/MSIX owns Start menu,
Installed Apps, update, and uninstall registration. The in-process updater accepts
only signed TUF release sets and keeps `repository_offline` as an honest degraded
state instead of falling back to mutable source.

A second native launch sends an activation request through a same-user secured
named pipe and exits after the existing window acknowledges focus. Native-host
logs live under `%LOCALAPPDATA%\Stockroom\Logs`; workers run in kill-on-close
Windows jobs. The host removes only old, Stockroom-marked legacy `_MEI*`
extractions.

Source development is a separate product boundary. `scripts/Start-Stockroom-Development.ps1`
starts the selected checkout directly through its existing `.venv`, an ephemeral loopback backend,
and Vite. Vite proxies `/api`; the source host injects a per-session credential only into its
same-origin app renderer, never a committed file or `VITE_*` build variable. Frontend edits use
HMR; backend Python edits terminate the complete
development child job and relaunch from fresh imports. This mode uses the title `Stockroom
Development`, AUMID `Stockroom.Development.Unpackaged`, authority scope
`DevelopmentApplicationService`, and state under `%LOCALAPPDATA%\Stockroom Development`. It
removes inherited `STOCKROOM_*` production inputs and disables application Git convergence, so it
can neither open production state nor pull over dirty source. Dependency setup and shortcut
installation are explicit commands. None of this code is a production startup fallback.

## Backend packages (`app/backend/stockroom/`)

Each package is a cohesive domain. Add code to the one whose job it already is; reach for a new
package only for a genuinely new domain.

| Package | Owns |
|---|---|
| `api/` | The FastAPI app (`app.py`), the request context (`context.py`), the single error→HTTP map (`errors.py`), the bearer-token guard (`security.py`), and one router per surface under `api/routers/`. |
| `model/` | The canonical records (`PartRecord`, `ProjectRecord`) and their JSON shape. The source of truth the index and the API DTOs mirror. |
| `store/` | Independent library-repository discovery/selection, the internal compatibility layout, derived SQLite indexes, and per-machine config. |
| `mutation/` | The atomic write engine: `Transaction` (one scoped git commit or full rollback), plus the library/project mutation ops. The ONLY committer. |
| `sexp/` | Layer 0: the byte-preserving s-expression editor. The ONLY thing that edits `.kicad_*` files (scoped span-splices, never a re-serialize). |
| `kicad/` | KiCad domain logic: symbols, footprints, boards, netlists, the CLI wrapper. |
| `ingest/` | Turning verified provider/download evidence into staged, complete-to-add candidates. |
| `enrich/` | Filling a part's data from distributor APIs + scraped pages (the pipeline, per-field sourcing, passives). |
| `templates/` | Versioned tool-neutral shared-template contracts and explicit per-EDA bindings. Template declarations never substitute for native verification. |
| `scrape/` | Fetching + extracting distributor/vendor pages (`extract/sites/` is one module per site). |
| `projects/` | Project-level analysis: BOM, fill, checks, buildability. |
| `altium/` | The Altium DbLib emitter + status. |
| `capture/` | The person-driven provider surface lease, the task-bound download broker, immutable provider evidence, and per-part requirements. It opens the page and stages what the person downloads; it never drives a provider control. |
| `host/` | The WebView2 app shell, lifecycle, rendered-DOM bridge, and diagnostics. The ONLY place `pywebview` may be imported. |
| `vcs/` | Git: the repo wrapper, library-only synchronization, and per-Windows-user GitHub auth through Git Credential Manager. Stockroom never stores an app-wide PAT. |
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
