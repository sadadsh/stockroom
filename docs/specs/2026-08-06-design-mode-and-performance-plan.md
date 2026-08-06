# Design Mode and Performance Plan

Owner-approved direction, 2026-08-06. This document is the implementation brief for a
follow-up build. It plans three initiatives: a visual Design Mode built on the existing
Dev Mode, a specimen-driven "base UI" editing model, and an optimistic-rendering and
performance pass. Nothing in this document is implemented; every claim about current
behaviour names the module that holds it so the implementer can verify rather than trust.

## The owner's asks, verbatim in spirit

1. "Build the UI with dev mode — change literally everything if I wanted, super
   intuitive, nothing that requires me to write anything, just visually make changes."
2. "Dev mode shows a base UI — something that you edit that all the components follow
   the format of."
3. "Make the app feel better — incorporate optimistic rendering and other optimizations."

## What exists today (verified foundations)

- **Semantic roles, not ad-hoc styles.** Typography is sixteen roles in
  `app/frontend/src/components/typography.ts` (`TYPOGRAPHY_SCALE` is machine-readable;
  its test reads the shipped stylesheet). Feature components are forbidden from inventing
  hierarchy with ad-hoc utilities.
- **Tokens with a parity gate.** Colours, radii and surfaces are CSS variables declared
  in `styles/index.css` for both themes, mapped in `tailwind.config.js`, and registered in
  `lib/devTokens.ts`. `devTokens.parity.test.ts` pins registry to stylesheet, so Reset is
  trustworthy. `visualLanguage.test.ts` enforces the neutral policy (saturation and cast
  bounds; no blue; no amber in chrome; `--c-layer-copper` is data and exempt).
- **Dev Mode.** `Ctrl+Shift+D`. Inspect (hover → id), Show IDs (badge every
  `data-dev-id`), live token editing with undo/redo, live copy editing. Overrides are
  source-backed: they write to override modules, not a scratch layer. State machinery was
  recently split into five hook modules plus a reducer (`lib/devModeDraft/History/Save/
  Selection/Toggle.ts`), which is the intended foundation for growth.
- **Instance vs class.** `data-dev-id` names one instance; `data-dev-role` names the
  shared class. `devIds.ts` carries a count assertion and an exact-partition parity test.
- **Copy layer.** Effectively all interface text routes through `<Text id>` / `useText` /
  `useCopyFormatter`; `copy.coverage.test.ts` enforces five shapes (JSX text runs, runs
  after an expression, `toast(...)` arguments, conditional JSX children,
  `title`/`aria-label`/`placeholder`). This is what makes app-wide copy editing possible.
- **Wholesale-replace writes.** Every mutating dossier endpoint returns the full
  recomputed `ComponentDossier` and the client replaces its cache (`api/queries.ts`).
  Consistency is excellent; perceived latency is the round trip.
- **Known costs.** The bundle is ~1.7 MB with pdf.js eager; three.js loads with the
  workspace; the picker and specification lists are unvirtualised.

---

# Initiative 1 — Design Mode: the specimen board ("base UI")

The owner's second message is the architecture: do not build a free-form page builder.
Build a **specimen board** — one exemplar of every visual primitive the application is
made of — and make editing the exemplar edit the class everywhere. The codebase is
already organised this way; the board is a viewport onto it.

## 1.1 The board

A new Dev Mode surface (route or full-screen overlay) rendering, from the REAL
components with representative fake data, one specimen of each:

- every typography role in `TYPOGRAPHY_SCALE`, labelled, in both tiers of surface
- every control class: command button, toolbar icon button, split button, select,
  input (inset), checkbox row, menu + items + separator, tab, status text (every tone),
  badge, disclosure chevron, splitter handle
- every surface: app shell band, panel, raised section, inset field, table (header,
  alternating rows, numeric column), property row (label + value), section header rule,
  dialog frame, toast, empty state
- the composite exemplars: one picker row, one specification row (each of the six
  states), one offer row, one document row, one CAD module header

**Coverage is gated, not aspirational**: a test walks `TYPOGRAPHY_SCALE`, the control
class registry and the token registry and fails if the board is missing a specimen. A
new role cannot ship without becoming editable.

## 1.2 Editing model

Click any specimen (or any element in the live app via Inspect) → a floating property
panel opens for its **role**, not the instance. Controls are visual only:

- steppers/sliders for size, spacing, height, radius — bounded to the design system's
  legal ranges (type steps the scale already defines; radius 0–2; nothing below 10px)
- swatches bound to tokens for colour — never a free hex field in the default view
- weight and tier pickers limited to the roles' legal values
- toggles for optional parts (meta counts, icons)

Every change previews live app-wide (CSS variables make this nearly free) and lands in
the existing undo/redo history.

A visible scope switch on the panel: **"Everywhere (class)"** — the default — vs
**"Only here (this instance)"**, which writes a dev-id-scoped override and is visually
marked as an exception wherever it applies. Exceptions are listed in the diff panel so
they cannot accumulate silently.

## 1.3 Guardrails inside the editor (not after it)

- A live contrast meter on every colour pairing the panel touches, using the same
  measurement the tests use; below-AA shows in the panel at edit time.
- Policy checks surfaced inline: the no-blue and no-amber bounds, the saturation/cast
  limits, the type floor. The panel refuses out-of-policy values with the reason, the
  same way the backend refuses an unofferable CAD source.
- A "deviation list": every difference from the shipped baseline as a human-readable
  row ("Property label 10px → 11px"), individually revertable. Reset-all remains.

## 1.4 Persistence pipeline

Three layers, all already present in embryo:

1. **Live preview** — CSS variable writes, instant, session-only.
2. **Draft profile** — localStorage, survives restart, named ("trying dense rows").
3. **Commit** — the existing source-backed override writer, extended so committing a
   look also updates the token/typography registries it changes, keeping
   `devTokens.parity.test.ts` and the stylesheet-reading typography test green by
   construction. Commit is explicit and shows the deviation list as its confirmation.

## 1.5 What Design Mode deliberately does NOT do

State this in the UI's own help text. It does not create components, move regions
between columns, or restructure information architecture. The three-column workspace,
section order, and closed vocabularies (CAD states, quality states) remain code-owned.
Design Mode owns every visual property of the pieces; the arrangement of the pieces is
a code change. This is the line between "a person who writes nothing can restyle
everything" and a page builder that lets one drag destroy the product's logic.

## 1.6 New editable surface required (work item)

Some control metrics are Tailwind literals today, not tokens (control heights, some
paddings, icon sizes). Promote these to tokens (`--m-control-h`, `--m-row-h`,
`--m-icon`, spacing steps) with both-theme declarations, Tailwind mappings and registry
rows, so the panel can edit them. This is the largest single work item in the
initiative; without it "change literally everything" is false for density.

---

# Initiative 2 — Optimistic rendering and perceived performance

Principle carried over from the dossier work: **the frontend never guesses semantics.**
Optimism shows the person's own input as pending; it never predicts the projection.

## 2.1 Optimistic writes (dossier mutations)

For the four write families (spec override set/clear, preferred-source pin set/clear,
CAD preference, pinout/identity edits):

- On mutate: snapshot the cached dossier, apply a **minimal local patch** that shows
  exactly what the person typed or chose, mark the row `data-pending="true"` (subtle
  visual: the value dims or carries a small in-flight glyph; the row must not jump).
- Derived fields — `verificationState`, `conflictState`, completeness counts, quality
  summary — are NOT predicted. They show a pending placeholder until the authoritative
  document arrives, because the backend owns those meanings.
- On success: replace wholesale with the server's full dossier exactly as today.
- On error: restore the snapshot and surface the failure beside the editor (the
  row-reverts-and-says-so pattern already implemented; keep it).
- Concurrency: writes are already serialised per column (`busy` gate). Keep that; an
  optimistic layer on parallel writes to one document invites reconciliation bugs.

## 2.2 Perceived latency on reads

- `placeholderData: keepPreviousData` for the dossier query on component switch: show
  the previous component's frame being replaced by cached data instantly rather than a
  loading state; a thin refresh indicator on the status bar while revalidating.
- Prefetch on intent: hovering or arrow-keying onto a picker row prefetches that
  part's dossier (and its symbol SVG) with a small debounce. The API is local, so this
  converts most opens into cache hits.
- Keep skeletons only for the genuinely-first load.

## 2.3 Bundle and code-splitting (measured wins first)

1. **pdf.js lazy** — dynamic-import the DatasheetViewer module on first open; it is the
   single largest dependency and is unused until a datasheet is viewed. Preserve the
   worker-src-in-same-module rule inside the lazy chunk.
2. **three.js lazy** — load the 3D scene module when a component with a model first
   renders, with the canvas area holding a static placeholder until then.
3. Route-level splits for the STM viewer and projects workbenches.
4. `LazyMotion` is already in place; keep `domMax` (toast uses `layout`).

## 2.4 Render performance — measure, then fix

The react-doctor performance families taught the standard: syntax is not slowness.
Before virtualising anything, measure with react-scan (URL mode against the running
app; do NOT inject it into index.html — it must never ship in `frontend-dist`) and
Performance marks. Candidates, in expected order of payoff: picker list at large
library sizes, specification column on parts with hundreds of rows, search overlay
results. Virtualise only what measurement convicts, and keep scroll position, focus
order, keyboard navigation and the three-scroll-owners invariant intact.

## 2.5 Budgets, asserted

Add an interaction-budget test harness (Playwright against the real app, the uishot
boot path): open-component from cache < 100 ms to first paint of the header; spec edit
keystroke-to-echo < 16 ms; picker hover-to-prefetch-issued < 150 ms. Budgets are
asserted with headroom on CI-class hardware and documented as budgets, not races.

---

# Sequencing for the implementing model

**Priority, stated by the owner after the plan was first written: the owner dislikes
how the shipped interface looks.** Repeated rounds of describing changes in words and
reviewing screenshots converged slowly and did not land on a look the owner likes.
Design Mode exists so the owner can set the look directly, without describing it to
anyone. Therefore the editing surface comes FIRST and the performance work follows it —
the reverse of this plan's original order. Do not reorder back for engineering
convenience.

Phase 0 — **Baseline.** Bundle analysis, react-scan pass, interaction timings on a
seeded large library, and a full uishot capture of every surface in both themes as the
visual baseline the owner will edit away from. Numbers and shots recorded; every later
phase cites them.

Phase 1 — **Specimen board, read-only** (was phase 3). The board, the coverage gate,
Inspect landing on a specimen from a live element.

Phase 2 — **Role editing + metric tokenisation** (was phase 4). The property panel,
inline guardrails, draft profiles. This is the phase that lets the owner change the
look themselves; everything before it exists to make it safe.

Phase 3 — **Commit pipeline** (was phase 5). Source-backed commit, deviation list,
instance-exception accounting. From here the owner's edits become shipped defaults.

Phase 4 — **Cheap feel wins** (was phase 1). keepPreviousData, picker-intent prefetch,
pdf.js + three.js lazy chunks.

Phase 5 — **Optimistic writes** (was phase 2). The four families, pending-not-predicted,
revert tests per family.

Phase 1 — **Cheap feel wins.** keepPreviousData on dossier, picker-intent prefetch,
pdf.js + three.js lazy chunks. (Small diffs, immediately perceptible.)

Phase 2 — **Optimistic writes.** The four families, with the pending-not-predicted rule
and revert tests per family (including a forced-failure test proving the snapshot
restore, proven non-vacuous by breaking the restore).

Phase 3 — **Specimen board, read-only.** The board, the coverage gate, Inspect landing
on the board's specimen from a live element. No editing yet — this phase is pure
inventory and is independently shippable.

Phase 4 — **Role editing + metric tokenisation.** The property panel bound to tokens,
typography roles and the newly tokenised metrics; guardrails inline; draft profiles.

Phase 5 — **Commit pipeline.** Source-backed commit extended to registries; deviation
list; instance-exception accounting.

## Standing constraints that bind all phases

- Copy layer and letter rule as enforced by `copy.coverage.test.ts` and
  `copy.letterRule.test.ts` (allowlist is DigiKey + Courtyard/Layer/Symbol/
  Compatibility, capped at 4; part data exempt and never altered).
- Token parity, `visualLanguage` bounds (no blue; no amber; copper stays), `devIds`
  count + partition, the three-scroll-owners rule, no dead click paths, states never
  colour-alone, accessible names complete.
- Every behavioural fix ships with a test proven non-vacuous (revert the fix, watch it
  fail). Two vacuous-test shapes already caught in this repo are documented in the test
  files that fixed them: an effect settling before the assertion reads, and a source
  gate matching its own explanatory comment.
- react-doctor stays at 100: `npm run doctor` is part of the gate, and
  `doctor.config.jsonc` may not gain entries without a written mechanism as its reason.
