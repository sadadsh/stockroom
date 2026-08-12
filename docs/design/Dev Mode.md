# Dev Mode

Dev Mode is Stockroom's source-backed interface editor. Press `Ctrl+Shift+D` on Windows to open
the Design panel. Changes preview immediately in the running app; **Save To Source** writes the
validated override modules, and **Publish To Main** verifies, builds, commits, and pushes only the
Dev Mode-owned files.

It is intentionally not a second settings system. Saved changes become normal application source
and therefore ship to every checkout and installation through the existing `main` update channel.

## Editing Model

Use **Inspect** and select an element in the app, or search the catalogue of registered Dev IDs.
The panel exposes six facets:

- **Tokens** changes shared color, typography, radius, shadow, and spacing primitives.
- **Copy** changes registered interface wording.
- **Icon** replaces a registered icon with sanitized SVG geometry or another registered icon, and
  controls its stroke width, treatment, accessible label, and inline alignment.
- **Box** edits the selected element's dimensions, spacing, position and inset, overflow, gradient,
  border, shadow, grid, and flex alignment. Fill Width, Row, Stack, Wrap, and Hide are repeatable
  presets.
- **Text** edits a closed set of font families, transforms, wrapping, and truncation rules.
- **Behavior** changes a compatible single-choice control between Dropdown, Segmented Control,
  Radio Group, and Searchable Picker, or disables it. The value, options, validation, and change
  callback do not change with the presentation.

Undo and Redo keep the latest 50 working snapshots in the current session. `Ctrl+Z` and
`Ctrl+Shift+Z` work while focus is outside a text editor. **Reset All** returns the working design to
the committed baseline.

## Source Contract

Saving regenerates exactly these files:

- `app/frontend/src/lib/token.overrides.ts`
- `app/frontend/src/lib/copy.overrides.ts`
- `app/frontend/src/lib/icon.overrides.ts`
- `app/frontend/src/lib/element.overrides.ts`
- `app/frontend/src/lib/behavior.overrides.ts`
- `app/frontend/src/lib/layout.overrides.ts`

Promoting a complete personal document also records its named variations in
`app/frontend/src/lib/design.variations.ts`. Six built-in starting points are always available:
Full Data, Compact, Purchasing, CAD Review, Minimal, and Custom. Personal variations can be
created, deleted, or assigned a non-cyclic parent; inherited patches remain sparse instead of
flattening into the currently selected appearance.

`layout.overrides.ts` carries the committed arrangement (Design Mode Phase 4) and, beside it,
`LAYOUT_COMMITTED_ISSUES` - the validator's reading of that arrangement at the moment it was
committed. That list is a record rather than a cache: live validation may differ as data, tokens and
the piece registry move, and both readings are worth having. `copy.overrides.ts` carries a second
export too, `OWNER_AUTHORED_COPY_IDS`, marking the rewordings the owner typed themselves so the
interface-letter gate exempts them while still binding everything the application authors.

The backend validates every payload before writing any file. CSS is restricted to the editor's
property/value grammar, SVG is parsed and rebuilt from a safe element and attribute allowlist, and
behavior presets are closed enums. A packaged app without its source checkout refuses to pretend it
saved.

## Publishing Contract

Publishing is available only from the managed Stockroom source checkout on `main`. **Make App
Default** is one backend transaction: it validates the personal document and both theme/variation
translations before changing source, snapshots every owned source and distribution path, writes the
validated modules, builds, and then commits and pushes. A clean checkout does not offer an empty
publish, and foreign dirty files show a blocker instead of failing late. Stockroom then:

1. refuses unrelated dirty files;
2. fetches GitHub and requires local `HEAD` to equal `origin/main`;
3. translates the base plus every supported named variation in both themes without flattening the
   active selection;
4. runs TypeScript validation and the production frontend build without opening command windows;
5. rechecks the dirty-file boundary;
6. commits only the owned override/variation modules and `app/frontend-dist`; and
7. pushes `main`, reporting a push failure rather than claiming success.

Any save/build/commit/push failure restores the pre-transaction source and distribution snapshot;
push failure also reverts the local promotion commit. The personal document remains intact for
recovery and retry.

The confirmation step accepts a one-line commit message. It does not force-push or merge divergent
history.

## Extending Coverage

Every registered `data-dev-id` can use the Box editor. A control needs the semantic
`AdaptiveChoice` primitive before the Behavior editor can safely change its presentation. This
boundary is deliberate: Dev Mode can reshape the interface extensively, but it does not rewrite
arbitrary JSX or silently change application meaning.

## Acceptance And Preview Isolation

`scripts/Verify-DesignStudio.ps1` is the deterministic Design Studio acceptance entry point. Its
browser case list is generated from the production scenario registry during `npm run build` and
written to `app/frontend-dist/design-studio-scenarios.json`; the browser harness does not maintain
a second scenario list. The current projection contains 190 scenarios.

Cases whose ordinary product markup would otherwise look identical carry a visible Preview State
notice inside the fixture product. It names the exact condition and its meaning. Both the jsdom
floor and the Chromium matrix compare rendered product DOM and reject duplicate cases; a renamed
default render is not accepted as another state.

The browser matrix opens every projected scenario in dark and light themes at 1,366 x 872,
1,600 x 1,000, and 1,920 x 1,200. It verifies the registered visible targets, Browse/Inspect/Arrange
click-through, editor-panel collapse and expansion, all inspector domains, and browser console
health. Every scenario carries an authority-derived interactive/layout/text/icon boundary and a
domain-owned state contract; acceptance asserts its expected targets and distinguishing rendered
DOM. It rejects every external/native/product effect while a fixture is active,
including API mutations, host file and folder pickers, provider visibility, navigation, downloads,
updater, EDA, and source actions. A blocked action explains itself in the visible Studio toast.
The one exception is the local `/api/design-studio/personal` autosave: acceptance makes a real
token edit, stops the service, restarts it with the same task-owned configuration, and requires the
exact value to return.

Run the complete entry point from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\Verify-DesignStudio.ps1
```

`-BrowserOnly` runs the production projection and browser matrix; `-SkipBrowser` runs the full
frontend, deterministic-build, and repository-gate portion. The wrapper writes only to its
task-owned evidence and configuration directories. Fixture previews never call component,
project, provider, credential, updater, EDA, filesystem, or source-promotion mutations. Real Data
mode remains the only route to real product operations, and packaged builds must refuse source
promotion when a writable managed source checkout is unavailable.

The automated matrix is browser-rendered product proof, not native-host, provider-account, EDA,
credential, or signed-release proof. Those layers remain separately recorded whenever the real
Windows owner state prevents an isolated current-source run.

Component and provider cases use the production **CAD Models > Manage Models** workspace. They
cover complete, partial, unavailable, active, validation, attached, invalid-file, and recovery
states while keeping the provider document itself outside the editable target tree. The provider
list, browser chrome, status, and recovery controls remain inspectable; fixture activation cannot
open the native provider WebView or file picker.

The Studio remembers the last scenario/case, viewport and custom width, data mode, zoom, grid,
snap, and presentation preference in the existing machine-preferences record. Fixture restore is
fail-closed and retries if persisted state is temporarily unavailable. The canvas offers a visible
Fit control and pan cue; keyboard arrow and pointer-drag panning keep the 1,920 px viewport usable
without concealing the editor rails.

Fixture preview blocks product effects before dispatch. This includes API operations, native file
and folder pickers, same-tab and new-window external links, auxiliary-click navigation, downloads,
provider visibility, updater actions, EDA launches, and source promotion. Personal design GET/PUT
and the dedicated closing-window keepalive handoff are the only live service requests allowed.
