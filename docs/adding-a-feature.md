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

- Compose it from `components/primitives.ts` (`Panel`, `Field`, `Button`, `Badge`, `TabStrip`,
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
3. To make it live-nudgeable in Design Studio, add one row to `lib/devTokens.ts` (its var, label, group,
   kind, whether it is theme-specific, and its default). That is the whole change.

## Make UI copy editable

- Wrap a static label in `<Text id="area.name">Default text</Text>` (`lib/copy.tsx`). It renders
  the default unless an override exists and gives Design Studio a stable, targeted copy identity.
- For copy in an attribute (a `placeholder`, `aria-label`, `title`) use
  `const label = useText("area.name", "Default")` and pass `label`.
- Personal rewordings stay in Draft until **Apply To This PC** activates them on that machine.
  Shipping copy for everyone remains a separate developer release action. Use a stable, unique `id`.

## Make an element editable in Design Studio

- Stockroom-owned JSX receives a deterministic `data-design-id` during the production build, so a
  new element is editable without manual registration.
- Give a meaningful layout or control boundary a stable `data-dev-id` and register the same ID in
  `lib/devIds.ts` when it needs an authoritative semantic identity across refactors or scenario
  assertions. Authored IDs take precedence over generated identities.
- For a single-choice control whose presentation may change, use `AdaptiveChoice` instead of a raw
  `<select>`. Pass the existing value, options, disabled state, and change handler unchanged. Dev
  Design Studio can then switch it among Dropdown, Segmented Control, Radio Group, and Searchable Picker
  without changing its semantics.
- If you authored an ID, add it to the parity tests. Confirm selection and the live edit in the real
  Windows host, in both themes, and exercise Undo/Redo before applying.
- The full identity, Draft, Apply To This PC, and release contract is in
  [Design Studio](design/Dev%20Mode.md).

## Add a parametric spec / attribute

No code change — these are **backend** registries. The dossier decides grouping, key
specifications, units, constraints and completeness once, per category, and serves the answer;
the frontend renders what it is given and owns none of this.

- To name a canonical field (its label, group, value type, unit, filter/sort/compare behaviour,
  and the distributor spellings that resolve to it), add one row to `FIELDS` in
  `app/backend/stockroom/dossier/fields.py`.
- To describe a **kind** of component — its key specifications, its group order, what it expects
  and recommends, what does not apply to it, its units, its validation constraints, its search
  facets, its comparison fields and its CAD validation relationships — add one `CategorySchema`
  row to `CATEGORY_SCHEMAS` in `dossier/categories.py`. A schema is resolved from the part's own
  words inside its filed category, so a new kind needs its `signals` and nothing else.
- An unregistered key still lands in a sane group under the source's own wording and is reported
  as an unmapped source field, so this only ever refines.

## Add a distributor / vendor scraper

- Add a site module under `app/backend/stockroom/scrape/extract/sites/`, matched by host. The
  enrich pipeline (`enrich/pipeline.py`) picks it up; keep extraction pure (no network in the
  extractor — the fetch layer owns that).

---

## Before you call it done

- Canonical Windows gate: `powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1`
- Backend focus: `uv run pytest tests/backend -q`
- Frontend focus: from `app/frontend`, run `npm run test:run`, `npm run typecheck`, and
  `npm run build`.
- Commit the regenerated `app/frontend-dist/` in the **same** commit as its source — that is what
  the backend serves.
- New behaviour gets a test. A UI change gets looked at in both themes.
