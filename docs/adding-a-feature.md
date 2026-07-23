# Adding a feature

Concrete recipes for the extension points you will actually reach for. Each one follows an existing
pattern, so a new feature is a small, predictable change instead of a new branch of logic. Read
[architecture.md](architecture.md) first for the map. Every recipe ends the same way: run the
[gates](../CONTRIBUTING.md#the-gates).

Pick the smallest recipe that fits — most features are one or two of these composed.

---

## Add a backend API endpoint

1. Add (or extend) a router under `app/backend/stockroom/api/routers/`. Follow the factory shape:

   ```python
   from fastapi import APIRouter, Depends, Request
   from stockroom.api.errors import ApiError

   def widget_router(require_token) -> APIRouter:
       r = APIRouter(prefix="/api/widget", dependencies=[Depends(require_token)])

       @r.get("")
       def get_widget(request: Request) -> dict:
           ctx = request.app.state.ctx          # the AppContext: config, profile, repo, ...
           if not ctx.something:
               raise ApiError(404, "no widget here")   # never invent a status inline
           return {"ok": True}

       return r
   ```

2. Register it in `api/app.py` (one `include_router` line).
3. Errors: `raise ApiError(status, detail)` — the single handler in `api/errors.py` maps every
   exception to an honest HTTP body. Do not build a status or error shape by hand.
4. Test it: `tests/backend/api/test_widget.py`, using the `client` fixture (it wires the app +
   bearer token). Build the seam TDD (red → green) before the frontend lands.

## Expose it to the frontend

1. Add the response shape to `app/frontend/src/api/types.ts` (mirror the backend DTO exactly).
2. Add a method to the `api` object in `api/client.ts`:

   ```ts
   getWidget(): Promise<Widget> {
     return apiGet<Widget>("/api/widget");        // or request("POST", path, { body })
   }
   ```

3. Add a TanStack hook in `api/queries.ts` (a `useQuery` for reads, a `useMutation` that
   invalidates the affected keys for writes). Components consume the hook, never `fetch`.

## Add a page / route

1. Add the route to `lib/router.tsx` and a nav entry to `lib/nav.ts`.
2. Add the page component under `pages/`, wired in `App.tsx`.
3. The nav rail (`components/Rail.tsx`) renders it automatically from `railNav()`.

## Add a component

- Compose it from `components/primitives.tsx` (`Panel`, `Field`, `Button`, `Badge`, `TabStrip`,
  `SegmentedControl`, ...). Do not re-derive a card/border/shadow string — that is what the
  primitives are for.
- Style with tokens only: `bg-raise` / `bg-surface`, `text-t1` / `text-t2` / `text-t3`,
  `border-line`, `rounded-card` / `rounded-control`. Never a raw hex, px radius, or font-size
  literal — route it through a token so it flips with the theme and stays consistent.
- Interactive labels are Title Case; body prose is sentence case; no em dashes (design contract).

## Add a design token

1. Add the variable to `styles/index.css` — a value on `:root` (dark) and on
   `:root[data-theme="light"]` (light); a theme-agnostic value (like a radius) only needs `:root`.
2. Map it in `tailwind.config.js` (e.g. `raise: "var(--c-raise)"`).
3. To make it live-nudgeable in dev mode, add one row to `lib/devTokens.ts` (its var, label, group,
   kind, whether it is theme-specific, and its default). That is the whole change.

## Make UI copy editable

- Wrap a static label in `<Text id="area.name">Default text</Text>` (`lib/copy.tsx`). It renders
  the default unless an override exists, and becomes click-to-edit in dev mode.
- For copy in an attribute (a `placeholder`, `aria-label`, `title`) use
  `const label = useText("area.name", "Default")` and pass `label`.
- Saved rewordings ship from `lib/copy.overrides.ts` for everyone. Use a stable, unique `id`.

## Add a parametric spec / attribute

No code change — these are registries:

- To group / label / unit a new spec key in the detail sheet and the parametric search, add one row
  to `SPEC_REGISTRY` in `lib/specSchema.ts`.
- To make a category headline nicely or surface a key attribute chip, add a row to `TITLE_REGISTRY`
  / `ATTRIBUTE_REGISTRY` in `lib/derive.ts`.
- An unregistered key still lands in a sane group and renders honestly, so this only refines.

## Add a distributor / vendor scraper

- Add a site module under `app/backend/stockroom/scrape/extract/sites/`, matched by host. The
  enrich pipeline (`enrich/pipeline.py`) picks it up; keep extraction pure (no network in the
  extractor — the fetch layer owns that).

---

## Before you call it done

- Backend: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend -q`
- Frontend: `cd app/frontend && npm run test:run && npm run typecheck && npm run build`
- Commit the regenerated `app/frontend-dist/` in the **same** commit as its source — that is what
  the backend serves.
- New behaviour gets a test. A UI change gets looked at in both themes.
