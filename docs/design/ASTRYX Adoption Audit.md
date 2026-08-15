# ASTRYX Adoption Audit

## Purpose

Stockroom should feel like one dense Windows engineering tool. ASTRYX can supply polished controls,
status surfaces, and accessibility behavior, but it cannot repair a weak composition by itself. Each
migration must improve alignment, density, hierarchy, and interaction without changing product
ownership or hiding evidence.

## Premise Check

The owner's observation is **Supported**. The first ASTRYX screenshots still mixed several visual
systems:

- Settings combined bordered status pills, distant label/value pairs, variable control heights,
  custom cards, ASTRYX links, and isolated ASTRYX inputs.
- Search placed its result count above the filter rail while Sort controlled the results pane.
- About placed brand icons, external-link marks, version text, and a wide status note on unrelated
  alignments.
- A global ASTRYX Button replacement added an empty `role="status"` live region to every idle button.
  This created false status landmarks in provider workflows and changed stable workspace DOM.

The global Button swap is rejected. Tests remain unchanged because they exposed a product-semantic
regression, not snapshot noise.

## Audited Captures

### Settings Cards, Dark And Light

Evidence:

- `work/ASTRYX Settings Composition Dark.png`, SHA-256 `99833729a24f`
- `work/ASTRYX Settings Composition Light.png`, SHA-256 `90acad8e2ac9`

Initial findings:

- The two machine-summary cards used different left margins and density.
- Header summaries looked like unrelated mini-buttons.
- Full-width status values sat at the far right edge, more than 1,000 pixels from their labels.
- Card borders, body rules, and inset controls competed at the same strength.
- Appearance and About repeated their summary inside the body.

Applied composition:

- Every capability uses the same ASTRYX Card surface with 2px geometry and low elevation.
- The machine summary is one joined surface with a shared center divider.
- Header summaries are unboxed text.
- Status rows use one bounded property grid with a 9–13rem label column and left-aligned values.
- The property grid uses spacing rather than bright full-width rules.
- About uses a three-column grid for identity, details, and project links.

Remaining constraints:

- Capability summaries remain because every mounted Settings card must state its current condition.
- Application Updates appears in the machine summary and in its full control card. The summary
  answers readiness; the card owns update controls and evidence.
- Legacy actions remain until ASTRYX Button stops emitting idle live regions or Stockroom swizzles a
  corrected implementation.

### Catalog Inputs, Dark And Light

Evidence:

- `work/ASTRYX Catalog Inputs Dark.png`, SHA-256 `0dd35d3b36c4`
- `work/ASTRYX Catalog Inputs Light.png`, SHA-256 `d1345b533ab3`

Applied composition:

- Clone URL and catalog folder use compact ASTRYX TextInput controls.
- Both controls measure 28px high, use 2px corners, and use Segoe UI Variable.
- Labels remain accessible and machine paths remain ordinary values.

Do not migrate credential fields yet. ASTRYX TextInput 0.4.1 does not expose the required
`autocomplete` contract, and Stockroom must preserve explicit credential handling.

### About Version Disagreement

Evidence:

- `work/ASTRYX Version Disagreement Dark.png`, SHA-256 `4575d20b2090`

Applied composition:

- ASTRYX Banner appears only for an actual frontend/backend version disagreement.
- Current-version notes do not create a redundant green banner.
- The stale Design Studio scenario now carries coherent, valid differing revisions and a restart
  instruction.
- LinkedIn and GitHub rely on the ASTRYX external-link indicator; duplicate brand glyphs were
  removed.

### Parametric Search, Dark And Light

Evidence:

- `work/ASTRYX Search Composition Dark.png`, SHA-256 `4ca3a3e05c36`
- `work/ASTRYX Search Composition Light.png`, SHA-256 `d9bfb473e356`

Initial findings:

- The result count began above Filters while Sort belonged to Results.
- A blank toolbar band split the query field from both pane headers.
- The full-screen search is a parametric browser with facets, a virtualized evidence table, durable
  selection, and exact keyboard behavior. ASTRYX CommandPalette cannot replace it.

Applied composition:

- Filters and Results now own equal 34px pane headers.
- Results, count, active chips, and Sort share one results toolbar.
- The filter rail no longer has an unrelated result count above it.
- ASTRYX Kbd continues to own all visible keyboard hints.

Future candidates:

- Evaluate ASTRYX Selector for Sort after verifying disabled-option explanations and keyboard
  behavior.
- Evaluate CheckboxInput for simple filters only if the full row remains one valid activation
  target. Do not nest a checkbox inside a button.
- Keep the virtualized result table and facet projection custom.

### Component Workspace And CAD

Evidence reviewed:

- `output/playwright/components-light.png`
- `output/playwright/components-light-compact.png`
- `output/playwright/components-dark-compact.png`
- `work/CAD Fixture Corrected Light.png`
- `work/CAD Fixture Corrected Dark Compact.png`

Findings:

- The master/detail frame, fixed rail geometry, three CAD modules, specification projection, and
  sourcing pane form one application-specific tool layout. ASTRYX AppShell, SideNav, and generic
  Layout must not replace it.
- The full-size workspace is structurally coherent. Compact Design Studio captures scale the whole
  preview and are useful for fit checks, not typography acceptance.
- Preferred Source, specification filters, and compact toolbar actions remain candidate controls.
  Their adapters must preserve disabled reasons, Design Studio copy targets, and 22–26px desktop
  geometry.
- CAD canvases, electrical geometry, native provider content, and exhaustive official evidence have
  no ASTRYX substitute.

### Sourcing

Older `work/Sourcing IA *` captures predate the accepted line-free, price-pill, and fitted-CAD pass.
They are rejected as current visual evidence. Current Sourcing keeps its price-first information
architecture, all retained offers and price breaks, and its no-structural-rule contract. ASTRYX may
supply disclosure or status controls later, but it cannot own offer normalization, evidence
retention, or sorting.

## Replacement Map

### Adopt Now

- Card for standalone Settings widgets and capability surfaces.
- Banner for persistent, evidence-backed warnings or failures.
- TextInput for non-sensitive bounded text fields.
- Link for external project destinations.
- Kbd for keyboard hints.

### Adopt After A Focused Adapter

- Selector for bounded source, sort, and mode choices.
- Switch and CheckboxInput for true boolean settings.
- Token for removable filter chips after preserving Stockroom's exact accessible removal names.
- StatusDot for exceptional states after reducing repeated healthy badges.
- Table for small static tables only.
- Dialog and AlertDialog after preserving Stockroom's modal stack, viewport sizes, nested flows, and
  Design Studio targets.
- Tooltip for icon-only actions where native `title` does not provide enough guidance.

### Hold Or Reject

- Button and IconButton globally: rejected because 0.4.1 emits idle live-region statuses and its
  default press scaling conflicts with the owner-authored native interaction contract.
- Spinner globally: hold because the canvas implementation needs a test adapter and slows rather
  than stops under reduced motion.
- AppShell, SideNav, TopNav, and Layout for the production frame.
- CommandPalette for Parametric Search.
- Table for virtualized search, sourcing, official evidence, or CAD data.
- Card around dense rows, offers, parts, or evidence records.

## Acceptance For Each Later Slice

1. Capture dark and light at 1,400 × 900 and the supported minimum viewport.
2. Audit alignment, heights, gutters, repeated emphasis, empty space, copy, and status truth.
3. Verify keyboard use, focus return, reduced motion, and screen-reader landmarks.
4. Compare payload before and after.
5. Run focused tests, all frontend tests, TypeScript, production build, dist synchronization, and the
   full Windows gate before publication.
