# Design Mode and Performance Plan — v2, the full builder

Owner-approved direction, 2026-08-06, revised the same day after a decision session.
This document is the implementation brief for a follow-up build. Nothing in it is
implemented; every claim about current behaviour names the module that holds it so the
implementer verifies rather than trusts.

## The owner's decisions (settled — do not re-litigate)

Taken by explicit choice, question by question:

1. **Ceiling: full builder.** Restyle everything, rearrange everything, compose new
   screens from existing pieces, AND create new elements — wired only to real data and
   real actions.
2. **Structural freedoms: the workspace grid itself and the application shell.** Not
   just moving sections between three fixed columns — the column count and arrangement
   are editable, and the rail, picker, status bar and identity header are editable
   regions like everything else.
   Deliberately NOT chosen (do not build): per-category layouts, named view presets.
3. **Guardrails: warn, never block.** The editor performs any edit and keeps a live
   issues list ("Delete Component is now unreachable", "this pairing fails contrast").
   The owner decides. Nothing refuses.
4. **Persistence: a committed redesign becomes the app.** One-click commit writes the
   layout to source; it ships through main like any change and lands on the owner's
   laptop. Named local drafts exist while experimenting.
5. **Editing surface: directly on the live app.** Edit mode makes the real application
   the canvas — real parts, real data, drag the actual sections. No separate design
   canvas. What the owner sees while editing is literally what ships.
6. **New shipped pieces auto-place by rules.** When later work ships a new section or
   action into a redesigned layout, the system places it from the piece's own manifest
   hints. No blocking tray, no paused updates. Mitigation (required): every auto-place
   is recorded in the issues list as an informational entry ("Alternate Parts was
   auto-placed at the bottom of Sourcing"), so it is discoverable without being a gate.
7. **New elements are made of real data and real actions only.** A field picker over
   everything the backend serves; an action picker over everything the app can do. No
   free text authoring, no computed expressions. A button always does something real; a
   value is always the truth. (This also means the builder can never author a string,
   so the interface letter rule is structurally unviolable from inside it.)

**The standing motivation:** the owner dislikes the shipped look, and prose-driven
visual iteration failed to converge. The builder exists so the owner never has to
describe a design in words again. Editing-surface work therefore precedes performance
work in every sequencing decision.

## What exists today (verified foundations)

- **Semantic roles.** Sixteen typography roles in `components/typography.ts`;
  `TYPOGRAPHY_SCALE` is machine-readable and its test reads the shipped stylesheet.
- **Tokens with parity gates.** `styles/index.css` (both themes) ↔ `tailwind.config.js`
  ↔ `lib/devTokens.ts`, pinned by `devTokens.parity.test.ts`;
  `visualLanguage.test.ts` enforces the neutral bounds (no blue; no amber in chrome;
  `--c-layer-copper` is data and exempt).
- **Dev Mode** (`Ctrl+Shift+D`): Inspect, Show IDs, live token and copy editing,
  undo/redo, source-backed overrides. State machinery already split into five hook
  modules plus a reducer — the intended growth point.
- **Instance vs class:** `data-dev-id` (instance) vs `data-dev-role` (shared class),
  with count and exact-partition parity tests in `devIds.ts`.
- **Copy layer:** effectively all interface prose routes through `<Text>` / `useText` /
  `useCopyFormatter`; `copy.coverage.test.ts` binds five shapes with no carve-outs.
- **Dossier writes** return the full recomputed document; the client replaces
  wholesale (`api/queries.ts`).
- **Layout constants already pure:** `lib/workspaceColumns.ts` computes column geometry
  from data; splitters persist fractions to localStorage.
- **Known costs:** ~1.7 MB bundle with pdf.js eager; three.js loads with the
  workspace; picker and specification lists unvirtualised.

---

# Part 1 — The architecture: layout as data

Everything the owner chose follows from one enabling change: **the arrangement of the
interface must become a data structure the app renders, instead of JSX the app is.**
Today the three columns, their sections, the header and the shell are hardcoded
composition. A builder cannot edit code; it can edit a document.

## 1.1 The layout document

A versioned, serialisable tree:

- **Region** — a container with a layout mode (row / column / stack), size constraints,
  and splitter behaviour. Regions nest. The workspace, each column, the shell rail, the
  picker, the status bar and the identity header are all regions.
- **Slot** — an ordered position inside a region.
- **Piece** — a reference to a registered component plus its per-placement settings
  (collapsed, hidden, size overrides, style-role overrides).

The shipped default layout is itself a layout document committed to source — the
current design, transcribed. Custom layouts are edits of that document, not forks of
code.

## 1.2 The piece registry

Every placeable unit registers a manifest: stable id, display name, the data it needs
(dossier paths / query keys), the actions it exposes, minimum and preferred size,
scroll ownership, and **home hints** (default region + sibling group) used by
auto-placement. The registry is gated like `devIds`: a coverage test walks the
workspace and shell and fails if any rendered section is not a registered piece —
a new feature cannot ship unplaceable.

## 1.3 The action and field registries (the builder's vocabulary)

- **Action registry:** every command the app can perform (open datasheet, refresh
  offers, reveal files, delete component…) with id, label id, required context
  (component / global), and destructiveness. The Manage menu, header actions and
  section toolbars become consumers of this registry — which is what makes "new button
  wired to a real action" possible and dead buttons impossible.
- **Field registry:** derived from the dossier's own machine-readable shape (the
  backend already serves `specificationGroups`, `supplySummary`, `qualitySummary`,
  documents, offers — all typed). The field picker presents every servable value with
  its real formatting roles. No field can be invented; no value can be guessed.

## 1.4 The validator (warn, never block)

A pure function over (layout document, registries) producing the issues list:

- **Reachability:** every registered action reachable from at least one placed piece;
  a destructive action's confirmation intact. "Delete Component is unreachable" is the
  canonical warning.
- **Visibility:** contrast of every text role against the surface it now sits on
  (reuse the measured-contrast machinery from `visualLanguage.test.ts`).
- **Structure:** overlapping pieces, pieces below their minimum size, scroll-owner
  conflicts (two scrolling pieces sharing an axis in one region), keyboard/focus-order
  coherence.
- **Provenance:** informational entries — auto-placements since the layout was last
  edited, style-role exceptions scoped to single instances.

The issues list renders live in edit mode, stays inspectable outside it, and ships
with the committed layout (a committed layout's known issues are part of the commit,
visible in Dev Mode — honesty travels with the design).

## 1.5 Edit mode (directly on the live app)

Toggle from Dev Mode. The running app gains handles: drag pieces between slots, drag
region boundaries (splitters generalise), collapse/hide, right-click for piece
settings. The style property panel from the v1 plan attaches here — clicking a piece
edits its roles and tokens visually (sliders, swatches bound to tokens, legal ranges),
with "everywhere (class)" as the default scope and "only here" recorded as a tracked
exception. Undo/redo spans structure and style as one history.

**New element composer:** a palette entry "New element" opens a compositor: pick
fields, pick actions, arrange them in a small row/stack — producing a piece whose
manifest is its bindings. It is a *composition*, not code: deleting it orphans
nothing.

## 1.6 Commit pipeline

Draft (localStorage, named) → **Commit**: serialise the layout document to its source
module, regenerate whatever registries it touches, run the gates. The gates evolve:
tests that today pin the *arrangement* (three columns, section order, three scroll
owners) become tests of the **default layout document**, while a new suite tests the
**engine invariants that hold for any layout**: no page scroll, every region owns at
most one scroll axis, focus order follows visual order, every action reachable or
warned, every piece registered. That reframing is part of this work, not optional —
otherwise the first committed redesign breaks hundreds of arrangement tests and the
implementer "fixes" them by weakening.

## 1.7 Explicit boundaries

- The native window chrome (the WPF tab strip, `WindowTabStrip.cs`) is not React and
  is not editable by this system. The React shell inside the window is.
- Closed vocabularies stay closed: CAD states, quality states, provider names. The
  builder places and styles them; it cannot rename them (it has no text authoring).
- The backend remains the single authority on data semantics. The builder binds to
  what is served; it never derives.

---

# Part 2 — Performance and feel (after the builder)

Unchanged from v1 in content, demoted in order by the owner's priority.

- **Optimistic writes** for the four mutation families with the pending-not-predicted
  rule: show the person's own input immediately with a pending marker; never predict
  derived fields (verification state, conflicts, completeness); reconcile with the
  authoritative full document; roll back with the row-says-so pattern on failure.
- **Reads:** `keepPreviousData` on component switch; prefetch dossier + symbol SVG on
  picker hover/keyboard intent.
- **Bundle:** lazy pdf.js (keep the worker-in-same-module rule inside the chunk), lazy
  three.js, route-splits for STM viewer and projects. `LazyMotion` stays `domMax`
  (toast uses `layout`).
- **Render:** measure with react-scan (URL mode only — never inject into
  `index.html`/`frontend-dist`) before virtualising anything; candidates are the
  picker, the spec column, search results.
- **Budgets asserted:** open-from-cache < 100 ms to header paint; edit echo < 16 ms;
  hover-to-prefetch < 150 ms.

---

# Sequencing

Phase 0 — **Baseline.** Full uishot capture of every surface, both themes (the visual
baseline the owner edits away from); bundle and interaction measurements.

Phase 1 — **Layout as data, pixel-identical.** Transcribe the current UI into the
layout document + piece registry and render from it. Gate: uishot diffs against Phase
0 show no visual change. This is the riskiest engineering step and ships alone.

Phase 2 — **Test reframing.** Arrangement tests → default-document tests; engine
invariants get their own suite. Ships with Phase 1's parity intact.

Phase 3 — **Edit mode: arrange + style.** Handles, drag, region editing, the style
panel, undo/redo, drafts. Validator v1 (reachability, contrast, structure) live in
the panel.

Phase 4 — **Commit pipeline.** Source serialisation, gate integration, deviation
list. From here the owner's redesigns ship.

Phase 5 — **The composer.** Action + field registries surfaced as pickers; new
elements; auto-place rules with issues-list provenance.

Phase 6 — **Shell regions.** Rail, picker, status bar, header join the editable tree.

Phases 7–8 — **Feel:** cheap wins (lazy chunks, prefetch, keepPreviousData), then
optimistic writes.

## Standing constraints binding every phase

Copy layer and letter rule as enforced (allowlist capped at 4; part data untouched);
token and devIds parity; no blue, no amber, copper stays; states never colour-alone;
accessible names complete; every behavioural fix ships with a test proven non-vacuous
(revert it, watch it fail — two known vacuous-test shapes are documented in the files
that fixed them); frontend check stays 100 and `doctor.config.jsonc` gains no entry
without a written mechanism.
