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
   value is always the truth. (For NEW elements the builder can never author a string.
   Existing interface text became editable by the owner's same-day amendment below —
   see 1.5 for how the letter rule survives that.)

**Owner amendment (2026-08-06, later the same day): "by every surface I mean
everything, text too."** Two clarifications with plan-wide force:

- **Editable scope is the whole application.** Every route — the components
  workspace, the shell, projects, the STM viewer, ingest, settings, the search
  overlay, dialogs — eventually becomes regions and pieces. Sequencing is unchanged
  (workspace first, shell in its own phase); the remaining routes join the layout
  system in a phase of their own after the shell, one route at a time, each with its
  own pixel-parity transcription gate. The performance phases renumber after it.
- **Text is editable in place.** Decision 7 stands for new elements — the composer
  still cannot author a new standalone string — but existing interface text can be
  reworded where it is, backed by the copy layer. See 1.5.

**Owner amendment #2 (2026-08-06): "literally everything on the front end is
editable."** The owner's words: not a single thing the user sees should be unable to
be edited — every UI feature of every element, text, lines, the 3D viewer's colours,
everything — and the editor must not block the thing being edited. Five consequences
with plan-wide force:

1. **The editability universe is every computed visual property of every rendered
   element.** Click an element, resolve it instance-vs-class exactly as today, and
   every visual property it renders is editable. Tokens and typography roles remain
   the PREFERRED binding — they cascade and stay consistent — but a per-role and
   per-instance property override exists for whatever is not tokenized (spacing,
   borders, shadows, line widths, icon sizes, radii). Tokens where they exist,
   tracked overrides where they do not; tracked instance exceptions sit in the
   deviation list as before. The acceptance bar: the editor never answers a click
   with "not editable".
2. **Drawn graphics are in scope**: the symbol and land-pattern previews' linework,
   stroke widths, fills, the sheet, pin-number text, splitters, scrollbars, focus
   rings, selection markers. The SVG previews render from the layer tokens
   already, so much of this is registry extension.
3. **The 3D scene is in scope**: materials, background, lighting tone, outline
   colours in threeScene.ts, behind a scene-property registry parallel to the token
   registry.
4. **Policy guards become owner-overridable warnings**, exactly as the letter rule
   resolved: the visual-language bounds (no blue, no amber, saturation and cast
   caps) and the colour-is-data doctrine become DEFAULTS. An owner edit that
   crosses a bound warns live in the issues list; at commit, owner-authored
   provenance exempts the owner's committed values from the CI gates, and the
   gates keep binding everything agents author.
5. **The editor chrome detaches from the surface being edited**: a separate editor
   window carrying the panels, message-bridged to the app, selection in the app
   and editing in the window — and it must work in the pywebview source host the
   owner actually runs, not only the frozen WPF host. If a real second window
   cannot be carried cleanly there, the fallback is an edge-docked drawer that
   never overlaps the selected element; the real window is attempted first.

Sequencing: points 1-2 belong to the style slice (it must not ship as a roles-only
panel); the 3D scene and the detached window are slices of their own inside the
edit-mode phase. The commit pipeline landed before this amendment carrying six
override slices through one generic payload mechanism; the property, graphics and
scene slices extend that payload the same way the layout slice did — one recorded
extension, not a redesign.

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

**Text edits in place (owner amendment):** clicking any text in edit mode edits it
directly, backed by the copy layer — every interface string already routes through
`<Text>` / `useText` / `useCopyFormatter` with a stable copy id, which is exactly why
the copy-routing work was done. A reworded string is a copy override keyed on that
id, carried with the layout draft and committed through the same pipeline. The
composer still cannot author NEW standalone strings (decision 7 stands: new elements
are real data and real actions only); this is rewording what exists.

**The letter rule under owner-typed text, resolved:** the letter rule and the term
map are the owner's own rules, enforced by `copy.letterRule.test.ts` against
app-authored source. When the OWNER types text through Design Mode, the editor
validates live and shows violations in the issues list (warn, never block, per
decision 3). At commit, an owner-authored override carries provenance marking it
owner-authored, and the lint exempts owner-authored overrides while still binding
everything agents author. The lint's purpose is to catch authored-for-the-owner
violations, not to overrule the owner in their own product. None of this is built
before the edit-mode phase; it is recorded here so the implementing agent does not
invent something worse.

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
  builder places and styles them; it cannot rename them — their strings sit outside
  in-place text editing, and the vocabulary tests keep binding them.
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

Phase 7 — **The remaining routes.** Projects, the STM viewer, ingest, settings, the
search overlay and the dialogs join the layout system one route at a time, each
transcribed with its own pixel-parity gate exactly as Phase 1 did the workspace.

Phases 8–9 — **Feel:** cheap wins (lazy chunks, prefetch, keepPreviousData), then
optimistic writes.

## Follow-ups recorded, not scheduled

- **No-reload tab switching in the source-run provider browser.** The source host's
  chrome (host/window_chrome.py, 2026-08-06) runs a single WebView, so switching tabs
  reloads the page; login survives through the persistent profile. The fix is a
  two-WebView design in the source host. Recorded here so it is chosen deliberately,
  not rediscovered.

## Standing constraints binding every phase

Copy layer and letter rule as enforced (allowlist capped at 4; part data untouched);
token and devIds parity; no blue, no amber, copper stays; states never colour-alone;
accessible names complete; every behavioural fix ships with a test proven non-vacuous
(revert it, watch it fail — two known vacuous-test shapes are documented in the files
that fixed them); frontend check stays 100 and `doctor.config.jsonc` gains no entry
without a written mechanism.
