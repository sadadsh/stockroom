# Stockroom M6 — Frontend (the whole in-window app)

Status: **Active.** Milestone M5 (API + WebView2 host + launcher) is complete and
Windows-verified (ledger gen [14], HEAD `5bf792d`). M6 turns the thin one-page
Components slice into the full in-window app the design spec §7 describes: Library,
Ingest, Duplicates, Doctor, Settings, the Ctrl+K palette, the symbol/footprint/3D
viewers, the pinout viewer, and per-part git history. Full Projects stays M7.

This is a **full-stack** milestone. Most pages consume M5 endpoints that already exist,
but four features need a new backend seam first (duplicates listing, 3D GLB conversion,
per-part git history/diff, and the doctor auto-repair *apply* path). Each new seam is
built TDD with `pytest` before its frontend lands.

## Ground truth (mapped 2026-07-13)

Two Explore passes established the exact state; the load-bearing facts:

**Backend (M5, all tested, `pytest` 380/4 on Linux, 379/4 on Windows):**
- Library: `GET /api/library/parts` (q, category, complete_only), `/facets`,
  `/parts/{id}` (full `PartRecord.to_dict()`), `PATCH /parts/{id}` (`{field,value}`),
  `POST /parts/{id}/move` (`{category}`), `DELETE /parts/{id}`. Mutations rebuild the index.
- Ingest: `POST /api/ingest/inspect` (`{paths,lcsc_ids}` → `{job_id}`), `POST /api/ingest/commit`
  (a staging-candidate DTO → new `PartRecord`, or **`IncompleteError` 422 with `missing[]`** —
  the complete-to-add gate). Jobs stream at `GET /api/jobs/{job_id}/events` (SSE:
  `progress`/`result`/`error`/`done`).
- Enrich: `POST /api/enrich/part` (`{mpn,category?,want?}` → `EnrichmentResult` with
  `Sourced` fields + `price_breaks` + `specs` incl. `specs.pinout`), `POST /api/enrich/bulk`
  (job → `BulkReport`), `POST /api/enrich/datasheet` (`{url,candidate}` → `{stored}`).
- Previews: `GET /api/previews/symbol/{id}.svg`, `/footprint/{id}.svg` (kicad-cli SVG text,
  transparent bg, content-hash cached). **No 3D/GLB endpoint yet.**
- Doctor: `GET /api/doctor/drift` (`DriftReport`), `POST /api/doctor/wire-kicad` (job →
  `WiringReport`). **No auto-repair `apply` endpoint yet.**
- Profiles: `GET /api/profiles` (`{profiles,active}`), `POST /api/profiles` (`{name,archive?}`),
  `POST /api/profiles/{name}/activate` (`{active,part_count}`), `DELETE /api/profiles/{name}`.
- Sync: `POST /api/sync` (`SyncResult`), `GET /api/sync/status` (`{has_remote,current_branch,ahead,behind}`).
- Update: `GET /api/update/check`, `POST /api/update/apply`.
- System: `GET /api/health` (unauthed), `GET /api/system/info`.
- Auth: every non-health route wants `Authorization: Bearer <token>` (or `X-Stockroom-Token`).
- The index already computes `duplicates_by_mpn()` / `duplicates_by_footprint()` — **no router
  exposes them yet.**

**Frontend (`app/frontend/`, Vite + React 18 + TS strict + Tailwind + TanStack Query):**
- Committed dist at `app/frontend-dist/` (3 files, hashed) — **every change rebuilds + commits dist.**
- `App.tsx` renders a single `<ComponentsPage/>`; there is **no router**. `Rail.tsx` shows
  Components/Projects + Activity/Theme/Settings but only Components is wired (the rest are inert labels).
- The api layer wires only the three read endpoints (`listParts`, `facets`, `partDetail`). All
  mutations, previews, ingest, enrich, doctor, profiles, sync, update are **unwired**.
- The Components page (list + search + facets + read-only detail + files/sourcing cards) is
  fully built and renders live data. `DetailPanel` is read-only.
- **There is no test runner and zero frontend tests** — the first thing M6 lands.
- Design tokens live in `tailwind.config.js` (canvas #0b0b0b, layered translucent surfaces,
  t1/t2/t3 text, ok/warn/err, `card` 8px / `control` 6px radii, DM Sans). Mockups in
  `docs/mockups/` (`library-v2.html` is the Components source; `projects.html` is M7).

## Architecture decisions (locked)

1. **State-based routing, not react-router.** A single WebView2 window with `base: ./` has no
   URL semantics to honor; a small `route` store (a React context + `useSyncExternalStore` or a
   tiny zustand-free reducer) is simpler, fully testable, and avoids a dependency and hash-router
   quirks. Routes: `components | ingest | duplicates | doctor | settings | projects`.
2. **A command registry is the seam that unifies the rail and Ctrl+K.** Every navigation and
   every app action ("switch profile", "run audit", "add from link", "wire KiCad") registers as a
   command with an id, title, group, and `run()`. The Rail dispatches nav commands; the Ctrl+K
   palette fuzzy-searches commands **and** parts. Built in M6a (registry + nav commands), consumed
   in full by M6h (palette).
3. **Test substrate = vitest + @testing-library/react + jsdom.** Component tests mock the `api`
   module (not global fetch) so they assert behavior against a typed seam. This is the TDD floor;
   it lands in M6a-1 before any new feature.
4. **Theme = a real toggle backed by a `data-theme`/class on the root + a token set.** The Theme
   rail item and the design spec's light theme become real in M6a; the SVG previews re-tint to the
   active theme client-side (spec §8).
5. **Every mutation routes through TanStack Query mutations with optimistic-safe invalidation** of
   the parts list, facets, and the affected detail — never a manual refetch race.
6. **Honest degradation, mirrored from the backend.** 422 `IncompleteError` surfaces the `missing[]`
   list verbatim; a job's `error` SSE event surfaces its `detail`; sync/update states render their
   exact backend state string. No fake success anywhere.

## Verify loop (per slice)

- `npm run test:run` — vitest (behavior; the TDD substrate).
- `npm run typecheck` — `tsc -b --noEmit` (strict; must stay green).
- `npm run build` — `tsc -b && vite build` (bundle green; regenerates `app/frontend-dist/`).
- `pytest` for any new/changed backend endpoint (the strong loop; run offscreen).
- Commit the regenerated `frontend-dist/` alongside the source in the same scoped commit.
- **Visual/design gate (batched, Windows-interop):** build the SPA, serve it against a seeded
  library, screenshot via msedge headless on the Windows box, **Read the PNG** against
  `docs/design/contract.md` + the mockups. Anything not yet pixel-verified is stated as such
  (No-fault gate #3: say exactly what was exercised and where).
- Each sub-milestone ends with an **adversarial-review Workflow** on its committed diff before it is
  called done.

## Sub-milestone roadmap

| Sub | Scope | Backend work | Verify |
|-----|-------|--------------|--------|
| **M6a** | Foundation: test substrate, state router + command registry, rail wiring, page shells, theme toggle, toast system, global drop-target scaffold | none | vitest/tsc/build |
| **M6b** | Core mutations: editable `DetailPanel` (PATCH), category move, delete (in-window confirm), enrich-to-fill (`/enrich/part` → apply), complete-to-add gate surfacing | none | vitest + pytest contract confirm |
| **M6c** | Ingest: global drag/drop → `/ingest/inspect` (job+SSE) → staging editor → `/ingest/commit` (gate); LCSC-id add; datasheet fetch during staging | none | vitest + SSE mock + pytest |
| **M6d** | Viewers: symbol/footprint SVG (pan/zoom + theme re-tint) wired to `/previews/*`; **+ new `GET /api/previews/model/{id}.glb`** (cascadio STEP→GLB) + three.js 3D viewer | GLB endpoint (TDD) | vitest + pytest |
| **M6e** | Duplicates surface: **new `GET /api/duplicates`** over the index's `duplicates_by_*`; side-by-side compare + keep/delete via the mutation engine | duplicates endpoint (TDD) | vitest + pytest |
| **M6f** | Doctor page: drift + wire-kicad (existing) **+ new `POST /api/doctor/repair`** (absolute→`${SR_LIB}` paths, dangling refs, uncommitted assets, one-click) | repair endpoint (TDD) | vitest + pytest |
| **M6g** | Settings: profiles (list/create/activate/delete/archive), sync (status/sync), update (check/apply), KiCad wiring status, Mouser key, theme | none | vitest + pytest confirm |
| **M6h** | Ctrl+K command palette: fuzzy over every part field + every registered command | none | vitest |
| **M6i** | Pinout viewer: **persist enrich `specs.pinout` into the record** (gate-resolving decision, see below) + interactive pin table/diagram | persist pinout (TDD) | vitest + pytest |
| **M6k** | Per-part git timeline + visual diff: **new `GET /api/library/parts/{id}/history` + `/diff`** (read git blobs, no checkout) + timeline UI + JSON field-diff + old/new SVG overlay | history/diff endpoints (TDD) | vitest + pytest |

Each sub-milestone produces working, testable software and is adversarially reviewed before the next.

## M6a — Foundation (detailed)

**M6a-1 — Test substrate.** Add dev deps `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom`. Add `vitest.config.ts`
(jsdom env, setup file importing `@testing-library/jest-dom`, globals on). Scripts: `test`
(watch) and `test:run` (CI). Write characterization tests that lock today's behavior so the
refactors in M6a-2 can't regress it silently:
- `api/client.test.ts`: `apiGet` sets the bearer header, serializes params, throws `ApiError`
  with the backend `error`/`detail` message on non-ok, and status 0 on network failure.
- `pages/ComponentsPage.test.tsx`: renders the list from a mocked `api`, selects the first part,
  shows the detail, filters by search, and shows the empty/error states.
- RED first (a trivially failing assertion) to prove the runner runs, then GREEN.

**M6a-2 — Route store + command registry + rail wiring + page shells.**
- `lib/router.tsx`: a `Route` union, a `RouterProvider` holding `{route, navigate}` over
  `useSyncExternalStore` (external store so commands outside React can navigate), `useRoute()`.
- `lib/commands.ts`: a `Command {id, title, group, keywords?, run(ctx)}` registry with
  `registerCommand`, `allCommands()`, and the nav commands (`nav.components`, `nav.ingest`, …).
- `App.tsx`: switch on `route` → the six page components. `Rail.tsx`: items become buttons that
  `navigate()`, `selected` derives from the active route; the inert-label comment goes away.
- Page shells `pages/{Ingest,Duplicates,Doctor,Settings,Projects}Page.tsx`: real routed pages
  with the page chrome (header + eyebrow), each rendering its own honest "not built yet in this
  slice" body **only where true** — but M6a lands them as reachable shells, and each subsequent
  sub-milestone fills its page. Projects shows a "Projects lands in M7" honest placeholder.
- Tests: rail click switches route; each route renders its page; nav command `run()` navigates.

**M6a-3 — Theme toggle + toast system + global drop target.**
- `lib/theme.tsx`: `ThemeProvider` toggling `light`/`dark` on the root (class or `data-theme`),
  persisted to `localStorage`; the Theme rail item toggles it. Add the light-theme token set to
  `tailwind.config.js` / CSS vars so both themes are real (spec §7 Feel).
- `components/Toasts.tsx`: a `useToast()` hook + a bottom-corner stack; background jobs and
  mutation errors report here (quiet, 150ms, auto-dismiss). Tests: a toast appears and dismisses.
- `lib/dropTarget.tsx`: a window-wide drag overlay (the whole window becomes the drop target per
  spec §7 Feel) that, on drop, reads `pywebviewFullPath` when present (native paths) or the
  browser `File` list, and dispatches to a handler the Ingest slice (M6c) registers. In M6a it
  lands as the scaffold + the "drop to ingest" overlay visual + a no-op handler with a test that
  the overlay shows on dragenter and hides on dragleave/drop.

## M6b — Core mutations (detailed)

- `api/client.ts`: add `editField(id, field, value)` (PATCH), `moveCategory(id, category)` (POST),
  `deletePart(id)` (DELETE), `enrichPart(mpn, category?, want?)` (POST). `api/queries.ts`: add the
  matching `useMutation`s with invalidation of `parts`, `facets`, and the `partDetail(id)` key.
- `DetailPanel`: each identity field (display_name, mpn, manufacturer, category, description, tags)
  becomes inline-editable (click → input → save on blur/Enter, Esc cancels) calling `editField`;
  category uses a select of known categories → `moveCategory`; a kebab/delete action calls
  `deletePart` behind an **in-window confirm** (no OS dialog). Optimistic where safe; on the 422
  gate, the returned `missing[]` renders as the exact still-needed list.
- Enrich-to-fill: an "Enrich" action on a part with an MPN calls `enrichPart`, shows the sourced
  candidate values inline (value + source + confidence), and lets the user apply each into the
  record via `editField` (respecting the gate). Honest when a field can't be sourced.
- Tests: edit round-trips through a mocked `api`; delete confirms then removes + reselects; enrich
  renders sourced fields and applies one; the 422 path renders `missing[]`.
- Backend: no change — confirm the exact PATCH/move/delete/enrich contracts with a focused `pytest`
  run against the existing router tests, and add a frontend-contract test only if a shape is unclear.

## Backend seams M6 adds (each TDD with pytest, byte-layer + gate discipline intact)

- **`GET /api/duplicates`** (M6e): returns `{by_mpn: {key:[id,…]}, by_footprint: {key:[id,…]}}`
  straight from `index.duplicates_by_mpn()/by_footprint()`; the surface reuses the existing
  `DELETE /parts/{id}` for the keep/delete flow (no new mutation primitive).
- **`GET /api/previews/model/{id}.glb`** (M6d): cascadio/trimesh STEP→GLB, content-hash cached
  beside the SVG previews; honest 404 when no model, 502 when conversion tooling is absent.
- **`POST /api/doctor/repair`** (M6f): the auto-repair pass (absolute→`${SR_LIB}` asset paths,
  dangling symbol/footprint refs, uncommitted assets), atomic + reported per fix; dry-run first.
- **Persist `specs.pinout`** into the `PartRecord` (M6i): decide whether enrichment writes the
  pinout (and other high-confidence specs) into the record at ingest/enrich time. Leaning **yes,
  under a `specs` block on the record** so the pinout viewer reads the source of truth, not a
  transient enrich call. Resolve with the owner if it widens the complete-to-add gate.
- **`GET /api/library/parts/{id}/history` + `/diff`** (M6k): read the part's git blobs via the
  existing git layer (no working-tree checkout), scoped to the part subtree; `/diff` returns the
  structured JSON field-diff between two revs; the SVG overlay is client-side.

## Open decisions (flag to owner when reached)

- **Pinout persistence widening the gate (M6i).** If pinout becomes a record field, is it
  *required* for "complete"? Default: **no** — pinout is an optional spec, not a gate field, so a
  passive part without a pinout stays complete. Confirm.
- **Duplicates auto-merge vs. manual keep/delete (M6e).** Default: manual keep/delete through the
  existing atomic delete; no automatic content merge in v1.
- **Light theme as default vs. dark (M6a).** Default: dark (the mockups are dark); the toggle is
  real and persisted.
- **3D viewer library (M6d).** three.js directly vs. `<model-viewer>`. Default: three.js (spec §8
  names it) with a GLTFLoader; revisit if bundle size argues for the web component.

## Non-negotiables carried from the spec + repo rules

- Zero Qt/pywebview in `stockroom.api` (CI-gated) — M6 is frontend + headless-API seams only.
- Byte-preserving KiCad writes + the canonical-diff/`kicad-cli` gate on every write path (M6d/f/i/k
  touch no write path except through the existing atomic engine).
- No em dashes anywhere; Title Case for interactive labels; 8/6 radii; the design tokens are the
  only source of color/spacing.
- Honest completion: Linux green (vitest/tsc/build/pytest) is necessary, not sufficient; the pixel
  gate is the Windows screenshot loop, stated explicitly per slice.
