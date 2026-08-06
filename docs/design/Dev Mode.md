# Dev Mode

Dev Mode is Stockroom's source-backed interface editor. Press `Ctrl+Shift+D` on Windows to open
the Design panel. Changes preview immediately in the running app; **Save To Source** writes the
validated override modules, and **Publish To Main** verifies, builds, commits, and pushes only the
Dev Mode-owned files.

It is intentionally not a second settings system. Saved changes become normal application source
and therefore ship to every checkout and installation through the existing `main` update channel.

## Editing Model

Use **Inspect** and select an element in the app, or search the catalogue of registered Dev IDs.
The panel exposes five facets:

- **Tokens** changes shared color, typography, radius, shadow, and spacing primitives.
- **Copy** changes registered interface wording.
- **Icon** replaces a registered icon with sanitized SVG geometry or another registered icon.
- **Box** edits the selected element's dimensions, spacing, layout, appearance, typography, and
  flex alignment. Fill Width, Row, Stack, Wrap, and Hide are repeatable presets.
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

Publishing is available only from the managed Stockroom source checkout on `main`, after the
working design is saved. A clean checkout does not offer an empty publish, and foreign dirty files
show a blocker instead of failing late. Stockroom then:

1. refuses unrelated dirty files;
2. fetches GitHub and requires local `HEAD` to equal `origin/main`;
3. runs TypeScript validation and the production frontend build without opening command windows;
4. rechecks the dirty-file boundary;
5. commits only the six override modules and `app/frontend-dist`; and
6. pushes `main`, reporting a push failure rather than claiming success.

The confirmation step accepts a one-line commit message. It does not force-push or merge divergent
history.

## Extending Coverage

Every registered `data-dev-id` can use the Box editor. A control needs the semantic
`AdaptiveChoice` primitive before the Behavior editor can safely change its presentation. This
boundary is deliberate: Dev Mode can reshape the interface extensively, but it does not rewrite
arbitrary JSX or silently change application meaning.
