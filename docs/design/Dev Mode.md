# Design Studio

Design Studio is Stockroom's in-app interface editor. Press `Ctrl+Shift+D` on Windows to open it.
The editor has two modes:

- **Preview** operates Stockroom normally.
- **Edit** selects and changes visible Stockroom UI without triggering the product action beneath it.

The fixed toolbar provides Exit, Preview/Edit, the current screen or state, theme, Undo/Redo, view
controls, draft status, and **Apply To This PC**. Screens and Layers are optional drawers. The View
menu owns viewport, zoom, the visible grid, 1-64 px grid and snap size, snapping, presentation mode,
and the separate developer tools.

## Draft, Apply, And Ship

Design work has three deliberately separate states:

1. **Draft** autosaves the personal design document. It is visible in Design Studio but does not
   change the normal app.
2. **Applied To This PC** changes only after **Apply To This PC** is pressed. The applied document
   lives outside release directories, survives updates, and can be reset from Settings.
3. **Shipped** is a developer release action through source control. Applying a personal design
   never commits, pushes, or changes another installation.

`Ctrl+Shift` during launch bypasses an applied design for recovery. A failed editor render recovers
the last renderable product preview instead of replacing Stockroom with a blank surface.

## Selection And Identity

In Edit, click the visible element you mean to change. Shift-click adds another target and Tab moves
through related parent and child targets. The selection outline provides one move grip, eight resize
handles, removal, and reset controls. Removed targets leave layout without deleting their saved
identity or edits, and remain available as restorable ghost rows in Layers and Undo.

Every Stockroom-owned JSX element receives a deterministic `data-design-id` during the production
build, so a developer does not need to add an ID merely to make new UI editable. Authored
`data-dev-id` values remain authoritative semantic identities when they exist; use one for a stable
product boundary that must retain meaning across refactors or scenario assertions. Imperative
Stockroom DOM uses the same identity contract. Provider-page internals and raw CAD geometry are not
Stockroom UI, but their Stockroom-owned containers and presentation controls remain editable.

The default Layers view shows useful product boundaries. **All Elements** reveals generated wrapper
and boundary targets without turning the normal view into implementation noise.

## Editing

The compact inspector groups controls under **Layout**, **Appearance**, **Content**, and
**Advanced**. Box, text, and icon domains are separate: changing visible text does not rename an
unrelated wrapper, and changing an icon does not recolor technical CAD geometry. Safe controls cover
layout, sizing, flow or detached placement, spacing, stacking, visibility, color, border, shadow,
typography, text content, icon asset and treatment, interaction states, and validated advanced CSS.
Direct text on an authored target is editable even when it has no separate copy wrapper.
Executable JavaScript and unsafe HTML are never accepted.

Move and resize gestures use the selected View preference:

- **Snap** rounds movement to the current 1-64 px grid.
- **Free** preserves exact pixel placement.
- **Flow** keeps the target in layout.
- **Detached** positions it freely inside its nearest stable container.

Arrow keys move the selection; Shift increases the step. Each gesture is one undo entry and Escape
cancels the active gesture. Arrange controls also expose rotation and forward/backward layer order.
Reset is available for one property, one target, the current screen, the active theme or variation,
and the full personal design.

Static interface wording should still use `<Text id="area.name">Default text</Text>` or `useText`
for attributes. That authored copy identity supplies a stable default and targeted content editing;
it is not the mechanism that exposes surrounding layout elements.

## Screens, States, And CAD Presentation

Screens contains every production Design Studio scenario and its meaningful data, loading, empty,
error, permission, modal, theme, and responsive states. Fixture Preview Data blocks API mutations,
native pickers, provider visibility, navigation, downloads, updater, EDA, filesystem, and source
actions. Real Data is the only route to real product operations.

CAD viewports expose presentation only. Symbol, footprint, and 3D controls can change visible
layers, colors, opacity, grid, axes, background, tint, and material treatment. They never move
engineering primitives or rewrite CAD source.

## Persistence Contract

Design Document schema v2 stores global target identities, Light and Dark theme patches,
variations, flow/detached geometry, CAD presentation, and unresolved post-update edits. Version 1
documents migrate automatically. Unresolved identities remain visible for remapping instead of
being discarded.

The local activation API is:

- `POST /api/design-studio/apply-local`
- `DELETE /api/design-studio/apply-local`

Personal Draft autosave uses the Design Studio personal-document API. Applying is intentionally
unavailable while Preview Data is active.

## Verification

`scripts/Verify-DesignStudio.ps1` is the deterministic acceptance entry point. Its browser case list
is generated from the production scenario registry during `npm run build` and written to
`app/frontend-dist/design-studio-scenarios.json`; the browser harness does not maintain a second
scenario list.

The browser matrix renders every projected scenario in both themes and supported viewports. It
checks visible targets, Preview/Edit, drawers, inspector domains, interaction isolation, draft
restart persistence, and console health. Component and provider cases use the production
**CAD Models > Manage Models** workspace while keeping the third-party provider document outside
the editable target tree.

Run the complete entry point from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\Verify-DesignStudio.ps1
```

`-BrowserOnly` runs the production projection and browser matrix. `-SkipBrowser` runs the frontend,
deterministic-build, and repository-gate portion. Browser proof does not replace native Windows,
provider-account, EDA, credential, or signed-release acceptance.
