# Component Inspection Workspace

## Purpose

Stockroom's Components surface should answer one product question:

> Is this component record complete, correct, traceable, and safe to use in KiCad
> and Altium?

The existing four-pane composition is worth keeping. Its information architecture
and actions are not. Symbol, footprint, 3D model, specifications, sourcing,
readiness, provenance, and history currently behave like separate widgets. The new
workspace treats them as different projections and evidence for one selected
component.

KiCad is an important adapter, not Stockroom's ontology. The same workspace must
represent Altium containers, neutral mechanical files, native glTF, vendor
archives, and future EDA formats without disguising them as KiCad assets.

This is the canonical design direction for that workspace. It is not an
implementation log or permission for a big-bang rewrite.

## Product Principles

1. **Inspect before decorating.** A viewer exists to prove correctness, not merely
   to display an attractive asset.
2. **One component, three projections.** Symbol, footprint, and 3D share selection,
   checks, provenance, comparison, and actions.
3. **Actions follow their object.** Component-wide actions live in the component
   header, projection actions live in the viewer toolbar, and field actions live on
   the field.
4. **Truth is visible.** Readiness names KiCad and Altium separately and cites the
   evidence behind every pass, warning, or failure.
5. **Empty space is conditional.** No permanent column is reserved for missing
   sourcing data or a closed inspector.
6. **Automation reports; it does not become navigation.** Enrichment, refreshing,
   conversion, and capture are observable jobs rather than top-level manual chores.
7. **A mode changes the question, not just the color.** Material, Technical, and
   X-Ray have distinct inspection purposes.
8. **The app is a fixed workstation.** The page never scrolls. A bounded Library,
   viewer, facts card, inspector, or activity card owns any overflow it creates.

## Evidence and Diagnosis

Reviewed evidence:

- `components-dark-1600w.png` and `components-light-1600w.png`
- `2026-07-28 Rail Fix/components-dark-1384w.png`
- `2026-07-28 Rail Fix/components-light-1384w.png`
- The real WebView2 host at 1,384 × 861 in both themes
- `ComponentsPage.tsx`, `DetailPanel.tsx`, `PreviewModal.tsx`,
  `PreviewImage.tsx`, `SvgViewport.tsx`, `Glb3DView.tsx`, and
  `threeScene.ts`

Observed problems:

- The selected part is identified three different ways in the list, page title,
  and detail lede.
- The 3D model is a large card while Symbol and Footprint are small unrelated
  cards; the UI does not teach that the three must agree.
- The eye icon is the only thumbnail action and does not say whether it means
  inspect, preview, compare, or edit.
- Component-wide navigation (`Details`, `Handoff`, `Enrich`, `Timeline`) is mixed
  with domain content (`Sourcing`) and manual implementation stages.
- Actions are scattered: Add Parts, Refresh, row stars, asset eyes, CAD Complete,
  pane chevrons, and a lone delete icon each use a different placement rule.
- `CAD Complete` can contradict missing-data warnings and does not distinguish
  KiCad from Altium.
- Top Specifications duplicates rows immediately below it without explaining the
  difference between promoted facts and the canonical specification table.
- Empty Sourcing permanently consumes a major column.
- The screen has a strong grid but weak focus: it allocates more width to absent
  data than to inspection and next decisions.

## Preserved Four-Pane Layout

The shell remains four-pane, but each pane receives one stable responsibility:

| Pane | Responsibility | Contents |
| --- | --- | --- |
| Navigation rail | App destination | Components, STM Viewer, Settings, utilities |
| Library | Find and select | Search, saved filters, categories, component rows, intake |
| Inspection | Verify physical/logical assets | Unified Symbol / Footprint / 3D stage and toolbar |
| Facts | Understand the record | Overview, Specifications, Sourcing, compatibility |
| Context inspector | Resolve the current question | Checks, properties, provenance, comparison, activity |

The context inspector is collapsible and disappears when it has nothing useful to
say. On narrower windows it becomes a right sheet rather than forcing the
Inspection and Facts panes below their usable widths.

## Library Surface Information Architecture

The previous plan mixed destinations, maintenance modes, and pipeline verbs:
`Parts`, `Sourcing Health`, `Maintenance`, `Handoff`, and `Enrich`. Those are real
capabilities, but they are not stable objects in a person's mental model.

The product shell becomes:

| Destination | Job |
| --- | --- |
| Library | Find, inspect, and select accepted components |
| Intake | Submit one part, pasted rows, CSV/XLSX, copied BOM rows, or dropped files |
| Runs | Observe durable acquisition, normalization, and publish work |
| Review | Resolve exceptions and conflicts only |
| Settings | Configure providers, credentials, EDA capabilities, updates, and support |

Projects remains absent from vNext. Sourcing Health becomes a saved Library view
and a Review queue, not a separate workstation. Maintenance becomes background
health plus safe actions such as deduplicate, trash/restore, repair paths, and
re-derive; it does not compete with daily component work for top-level navigation.

### Library pane

The left pane keeps the layout the owner likes and changes its function:

- instantaneous virtualized search and facets;
- saved views: `All`, `Needs Decision`, `Missing Representation`,
  `Unattributed`, `Unchecked`, and `Changed`;
- a single row state: `Ready`, `Working`, `Needs Decision`,
  `Blocked by Setup`, or `Failed`;
- identity, package, and one concise reason/next action per row;
- KiCad and Altium detail on demand rather than two contradictory status badges;
- intake at the object boundary, not a modal reached from an unrelated toolbar.

The single state is a roll-up, not a loss of information. Opening the row exposes
per-tool, per-representation presence, verification, provenance, and the exact
reason behind the roll-up.

### Open component routes

The current open-part page starts moving toward five stable routes:

| Route | Contains |
| --- | --- |
| Overview | Accepted identity, key facts, readiness summary, current next action |
| Representations | Symbol, Footprint, 3D/Mechanical by EDA tool; accepted refs, provenance, checks |
| Pinout | Logical-to-physical mapping and pin evidence when applicable |
| Sources | Immutable pulls, alternates/conflicts, refresh/acquire actions |
| Activity | Jobs, edits, commits, failures, retry/recovery |

`Enrich` is a pipeline verb, not a destination. `Handoff` is an outcome composed
from representations plus fields, not a container for both. `Timeline` becomes
Activity because it contains active and failed work as well as historical events.

The first implemented slice is the compact Representation summary in the existing
Handoff panel. Each registered EDA tool is one bounded row with Symbol, Footprint,
and 3D state chips plus source/check summaries; exact artifact and embedding detail
stay available on the chip instead of expanding every cell. The existing
placement-field handoff remains beneath it until the controlled decomposition
reaches that panel.

### Component Header

One full-width header above Inspection, Facts, and Context contains:

- canonical display name;
- manufacturer and exact MPN;
- class and package;
- concise KiCad and Altium readiness;
- unresolved issue count;
- one state-derived primary action;
- an overflow menu for uncommon and destructive actions.

The primary action is never a fixed button. Examples:

- `Resolve 3 Issues`
- `Review Replacement`
- `Complete Component`
- `Ready`

Delete, raw-file operations, and administrative actions live in the overflow menu,
not as an isolated red icon at the bottom of the window.

## Unified Inspection Stage

Symbol, Footprint, and 3D are tabs in one stage:

```text
┌ Symbol  Footprint  3D ───────────── Compare  Fit  More ┐
│                                                        │
│                  active projection                     │
│                                                        │
├ projection controls ───────────────────────────────────┤
│ PASS 8   WARN 1   FAIL 0       source / revision / hash│
└────────────────────────────────────────────────────────┘
```

Switching projection preserves the selected pin/pad, comparison target, issue
filter, and component context. Expanding the stage preserves its camera/view state
and must not create a second renderer.

The inline stage exposes the same capabilities as the expanded workspace through
progressive disclosure, not by squeezing every control into one icon row.

## Symbol Inspector

### Core controls

- Fit, zoom, pan, reset, and actual-size view
- Show/hide pin names, pin numbers, fields, anchors, and grid
- Select a unit for multi-unit symbols
- Select normal or De Morgan representation when present
- Search and focus a pin by name or number
- Neutral, electrical-type, and comparison display modes

### Inspection behavior

Clicking a pin selects the same logical pin everywhere:

- Symbol highlights its pin.
- Footprint highlights its mapped pad.
- 3D highlights the corresponding lead when a mapping is available.
- Context shows number, name, electrical type, unit, alternates, and evidence.

### Automatic checks

- Duplicate or missing pin numbers
- Duplicate names where not explicitly allowed
- Missing power pins or unexpected hidden pins
- Pin electrical type inconsistent with known function
- Symbol pins not mapped to footprint pads
- Pinout disagreements between record, symbol, and datasheet
- Off-grid pins, malformed anchors, and implausible bounds
- Multi-unit pin collisions or omissions

### Useful actions

- Compare with source, candidate, previous revision, or datasheet pinout
- Accept or reject a candidate with a reason
- Open in KiCad
- Replace symbol
- Copy/export the inspection image with component and revision metadata

## Footprint Inspector

### Core controls

- Top and Bottom view
- Rotate in 90° steps and free pan/zoom
- Fit, actual size, grid, ruler, and measurement
- Layer visibility and isolate/solo
- Pad number/name visibility
- Origin, centroid, anchor, and Pin 1 markers

### Layer model

- Copper pads
- Mask
- Paste
- Silkscreen
- Fabrication
- Courtyard
- Drills and routed slots
- 3D body silhouette
- Datasheet land-pattern overlay

Physical layers use source-authentic color only in Material mode. Technical mode
uses restrained semantic contrast and a visible legend.

### Automatic checks

- Symbol pin ↔ footprint pad mapping
- Duplicate, missing, or non-numeric pad identities
- Pad pitch and body dimensions against datasheet facts
- Courtyard containment
- Mask and paste plausibility
- Drill, annular-ring, and slot plausibility
- Pin 1 agreement across symbol, footprint, model, and datasheet
- Footprint origin and model origin disagreement
- 3D body/leads against pads
- Model or pads below/intersecting the PCB

### Useful actions

- Measure between any two snapped features
- Compare current/source/candidate/revision/datasheet
- Overlay 3D body bounds without leaving 2D
- Open in KiCad
- Replace footprint
- Edit and save placement through a reviewed diff

## 3D Inspector

### View and camera

- Static three-quarter view by default; Spin is opt-in
- Top, Bottom, Front, Back, Left, and Right canonical views
- Orthographic projection for technical face views
- Perspective/Orthographic toggle for free orbit
- Fit, reset, frame selection, pan, orbit, and zoom
- Double-click to frame the selected object
- Keyboard shortcuts and a discoverable help overlay

### View cube

Use a real clickable view cube in the upper-right of the stage:

- labeled faces, edges, and corners;
- click a face for canonical orthographic view;
- click an edge/corner for an isometric view;
- drag the cube to orbit;
- animate under the motion budget and snap under reduced motion;
- show axis labels and current projection;
- remain usable with keyboard and screen reader controls outside the canvas.

Stockroom adopts `three-viewport-gizmo` directly against the existing Three.js
renderer and OrbitControls. The cube is rebuilt when projection cameras change,
shares the active orbit target, honors reduced motion, and does not require React
Three Fiber or a second rendering framework.

### Display modes

| Mode | Question answered | Rendering contract |
| --- | --- | --- |
| Material | What did the source model say this object looks like? | Vendor colors, conservative material inference, neutral studio lighting |
| Technical | Can I read its form and alignment unambiguously? | Neutral clay surface, restrained edge/depth cues, semantic overlays |
| X-Ray | What is hidden and how do body, leads, pads, and board overlap? | Stable transparency, ghosted occluders, visible selected geometry |

Optional tools are Wireframe, Edges, Section Plane, Exploded Stack, Measure, and
Isolate Selection. Raw lighting, shader, roughness, and GTAO controls remain
developer-only.

### Automatic checks

- Plausible scale and dimensions
- Inspectable KiCad translation, rotation, and scale
- STEP Z-up to glTF Y-up basis correctness
- Body and leads above the PCB
- Leads aligned to expected pads
- Body contained by courtyard
- Pin 1 agreement
- Suspicious 90°/270° rotation
- Implausible origin or offset
- Datasheet dimension mismatch
- Back-side placement correctness

Selecting a warning focuses the relevant geometry and enables only the overlays
needed to understand it.

## Renderer Quality Contract

### Shared color and lighting

- Explicit sRGB output and one documented color-management path
- Neutral HDR studio environment
- ACES filmic tone mapping with bounded per-mode exposure
- Theme-derived field/background, never a hard-coded dark canvas in light mode
- Lighting scaled from model bounds so packages from 0402 to connectors remain
  legible
- A contact cue that grounds the part without creating a fake second surface

### Material mode

- Preserve source colors.
- Treat STEP color as color, not proof of physical material.
- Apply conservative, evidence-backed finish inference to known lead finishes and
  moulded bodies.
- Expose `Source` versus `Enhanced` material interpretation in provenance, not as
  a hidden mutation.
- Keep black bodies readable with rim separation and controlled specular response,
  rather than repainting them gray.

### Technical mode

- Use a stable neutral material.
- Prefer screen-space normal/depth edges over per-mesh `EdgesGeometry` when the
  latter produces assembly seams and tessellation noise.
- Use ambient/contact occlusion only to clarify convergence.
- Keep overlays crisp and independent from the model's material.

### X-Ray mode

- Avoid ordinary transparent-mesh sorting artifacts through a tested dual-pass or
  order-independent strategy.
- Selected geometry remains opaque enough to locate.
- Pads, board, origin, and section plane keep a stable visual hierarchy.

### Quality and performance

- Render on demand; run animation frames only during input, tween, or explicit
  spin.
- Pause when hidden, occluded, or off-screen.
- Dispose every pass, render target, material, geometry, control, helper, and
  context exactly once.
- Cancel or ignore late loader callbacks after disposal.
- Adapt pixel ratio and antialiasing to WebView2 performance.
- Recover honestly from WebGL context loss.
- Maintain one renderer for inline/expanded presentation.

### Visual regression corpus

The renderer is accepted against representative fixtures, not one attractive
capacitor:

- tiny passive;
- dark epoxy IC with metallic leads;
- connector with several materials;
- through-hole part;
- mechanical part;
- model with non-zero offset;
- models rotated 90°, 180°, and 270°;
- back-side footprint;
- large asymmetric assembly;
- missing normals and malformed-model failure cases.

Each fixture is captured in both themes, all three modes, and canonical views in
the real WebView2 host. Checks include framing, silhouette, theme contrast,
orientation, placement, and bounded luminance—not only snapshot existence.

## Non-KiCad Representation and Frame Contract

Stockroom stores four different truths separately:

1. **Raw source artifact** — immutable bytes plus vendor, URL, capture time, hash,
   native container/entry, and source-declared metadata.
2. **Canonical inspection representation** — a disposable rendering projection
   in Stockroom's Y-up, millimetre scene. It never replaces the raw artifact.
3. **EDA binding and placement** — KiCad model transform, Altium embedded 3D Body,
   or a future tool adapter's native contract.
4. **Board validation** — measured agreement among pads, body, leads, origin,
   courtyard, and board surface.

These frames must not be collapsed into one `rotation` field. A source may be
perfectly valid while its EDA placement is wrong, or an EDA placement may be
correct while an OBJ's unit is unknowable.

### Format behavior

| Source family | Contract |
| --- | --- |
| KiCad `.kicad_sym` / `.kicad_mod` | Parsed by the KiCad adapter; native bytes remain evidence |
| Altium `.SchLib` / `.PcbLib` | Parsed/exported by the Altium adapter; binary container remains evidence |
| STEP/STP | Source-declared units, Z-up to canonical Y-up conversion, deterministic basis metadata |
| glTF/GLB | Standard Y-up and metres; identity basis unless an adapter states otherwise |
| OBJ/STL/PLY and other meshes | Up axis and units are `unknown` unless a manifest or adapter supplies them |
| Vendor ZIP/archive | Immutable evidence and candidate extraction boundary, never an accepted representation itself |

Every converted GLB carries a `stockroom` frame descriptor in `asset.extras`:
source format, source/render up axes, source/render units, basis transform, and
confidence. STEP is `declared`; native glTF is `standard`; a unitless mesh is
`unresolved`. Conversion cache `c6` prevents older GLBs without this contract from
masquerading as current output.

### Calibration

When metadata is absent or KiCad/Altium placement fails plausibility checks, the
inspector exposes three explicit comparisons:

- `Raw` — as authored;
- `Canonical` — normalized inspection frame;
- `EDA` — tool placement against the footprint/board.

Auto can choose a safe preview but cannot silently accept its guess. A saved
calibration is a reviewed, derived transform with author, reason, before/after
measurements, and source hash. It never rewrites vendor bytes and invalidates
automatically if those bytes change.

This is also how placement-data defects are handled: KiCad and Altium placements
are evidence candidates, not unquestioned truth. Board-level validation is the
acceptance authority.

## Facts and Data Information Architecture

### Overview

Overview contains only the fastest decision facts:

- canonical identity;
- concise description;
- class/package;
- promoted key specifications;
- lifecycle and availability summary;
- KiCad and Altium readiness;
- unresolved decisions.

Promoted facts are references to canonical specification rows, not duplicated
copies. Editing either surface edits one field.

### Specifications

- Searchable, grouped canonical rows
- Source, confidence, alternates, and last-verified time
- Pin-to-Key-Spec remains possible, but the star is named and explained
- Conflicts and missing facts are visible filters
- Datasheet comparison and source selection happen in Context

### Sourcing

Sourcing appears only when it has information or active work. It includes:

- vendor ladder and availability;
- price breaks and selected quantity;
- lifecycle and compliance;
- source URLs and timestamps;
- automatic refresh/acquisition state;
- fallback or blocked decision.

`Refresh` sits beside the last-verified status inside Sourcing. Empty sourcing
collapses into an actionable `Acquiring sourcing data…`, `Needs credentials`, or
`No source found` state; it never reserves an empty full-height column.

### Evidence and Activity

Handoff, Enrich, and Timeline become:

- **Evidence:** sources, hashes, checks, alternatives, and trust
- **Activity:** automatic jobs, edits, commits, failures, and recovery

Internal pipeline stages remain observable here without becoming primary
navigation or a series of manual buttons.

## Action Placement Rules

| Action scope | Placement |
| --- | --- |
| Component-wide primary next step | Component header |
| Component-wide uncommon/destructive | Header overflow |
| Projection/view control | Inspection toolbar |
| Selected pin/pad/mesh | Context inspector |
| Field edit/source choice | Field row and Context |
| Background job status/retry | The domain panel that owns the job |
| Compare/accept/reject candidate | Context inspector |
| Global intake | Library pane |

No unlabeled eye, warning, star, chevron, or refresh icon is allowed to be the
only explanation of a consequential action.

## Delivery Strategy

This is a controlled replacement behind existing boundaries:

1. Characterize the current component record, API, and renderer fixtures.
2. Repair the model/footprint transform graph and scene lifecycle.
3. Create the unified Inspection stage while retaining the existing data APIs.
4. Add Symbol and Footprint selection/overlay primitives.
5. Add shared checks and Context inspector.
6. Re-home actions and replace false completion language.
7. Reorganize Facts, Sourcing, Evidence, and Activity.
8. Add placement editing and candidate comparison.
9. Verify both themes, supported widths/DPI, keyboard use, and real WebView2.

`DetailPanel.tsx` should be decomposed by these responsibilities. It should not
be rewritten in one branch.

## Acceptance Evidence

- A person can identify the selected component and its one next action in under
  five seconds.
- Symbol pin, footprint pad, and 3D lead selection stay linked.
- Every failed check names evidence and focuses the relevant geometry.
- KiCad and Altium readiness cannot contradict asset warnings.
- Empty sourcing consumes no permanent column.
- All projection controls have visible hierarchy, accessible names, and keyboard
  paths.
- The view cube changes camera views and accurately reflects the active camera.
- STEP source axes are normalized deterministically before rendering; source
  geometry, materials, normals, and authored node transforms remain intact.
- KiCad placement remains selectable evidence rather than an unquestioned truth.
  Auto flags gross scale, offset, below-board, and vertical anomalies; Source and
  Model frames remain explicitly inspectable, and any saved calibration goes
  through a reviewed diff.
- The placement corpus covers non-zero transforms, 90°/180°/270° rotations,
  incorrect source placements, and correctly authored placements without
  “repairing” the latter.
- Renderer resources remain bounded after repeatedly switching 100 components and
  opening/closing the expanded stage.
- Both themes pass the real-host visual corpus without hard-coded canvas color,
  clipped controls, or illegible materials.

## Work Log

### 2026-07-28 — implemented and verified

- Replaced pointer-sensitive `focus-within` rail expansion with
  `:has(:focus-visible)` so auto mode closes after pointer navigation and remains
  keyboard accessible.
- Rebuilt every pinned/collapsed rail row on one 35 px glyph track and one label
  track. Real WebView2 centers are 25.5 px for Components, STM Viewer, Settings,
  About, Update, and Theme in both states.
- Kept the Stockroom wordmark present as the collapsed peek label.
- Reduced and unified the typography token scale; the body now inherits the base
  token and literal 9/10 px outliers were replaced by semantic tokens.
- Rebuilt `app/frontend-dist`.
- Reviewed dark/light Components and Settings captures and recorded their hashes
  in `Visual Audit Backlog.md`.
- Verified collapsed pointer navigation at 52 px, pinned width at 190 px, keyboard
  focus reveal, typography parity, and both themes in the real WebView2 host.
- Added rail regressions; all 1,108 frontend tests pass.
- Typecheck and production build pass.

### 2026-07-28 — inspection foundation implemented and verified

- Traced Components from `ComponentsPage` through `DetailPanel`, preview queries,
  `Glb3DView`, `threeScene`, the GLB conversion route, and footprint placement.
- Rebuilt model placement around the loader-authored transform. Source placement,
  model-frame inspection, and conservative Auto assessment are now separate,
  explicit states; a bad source can no longer silently become “truth.”
- Corrected the user-visible orientation defect at the conversion boundary:
  OpenCASCADE emitted STEP-native Z-up positions into glTF’s Y-up coordinate
  system, standing the 0603 on its side. Every STEP scene now receives one
  JSON-only `rotateX(-90deg)` parent node and basis metadata. Mesh buffers,
  materials, normals, and authored nodes are untouched, and cache version `c5`
  prevents stale conversions from hiding the fix.
- Matched non-zero placement to KiCad’s own OpenGL/ray-tracing matrix contract:
  `T · Rz(-z) · Ry(-y) · Rx(-x) · S`. Stockroom conjugates that complete matrix
  through the STEP→glTF basis, preserving multi-axis rotation order and swapping
  anisotropic scale axes correctly; focused tests cover identity, translation,
  scale, and combined XYZ rotation.
- Removed world-center/local-position subtraction that destroyed footprint
  semantics. Camera, board, pads, contact surface, and placement assessment now
  derive from the selected world-space frame without secretly recentering it.
- Fixed the asynchronous land-pattern race and replayed current React state after
  lazy renderer mount, including layers, render mode, spin, view, and placement.
- Bound render errors to the GLB bytes that caused them so changing parts can
  recover; ignored and disposed late loader callbacks after unmount.
- Made disposal idempotent and covered the scene, materials, textures, edge
  geometry, post-processing passes, environment targets, controls, gizmo,
  renderer, and WebGL context.
- Replaced the inert axes helper with a 92 px clickable/drag-capable view cube
  from `three-viewport-gizmo`. It follows camera swaps and orbit targets, exposes
  an accessible DOM affordance, clears misleading preset state for free cube
  views, and honors reduced motion.
- Reorganized the compact 3D toolbar into persistent Layers, Spin, and Settings.
  View, Shading, and Placement live in one compact popover; the expanded viewer
  keeps the full labeled control bar without wrapping.
- Added explicit `−`, zoom percentage, `+`, Fit, and SVG export controls to Symbol
  and Footprint, plus keyboard `+`, `−`, `0`, and `F`, double-click Fit, and a
  visible focus path. Reordered inspection tabs to Symbol, Footprint, 3D.
- Replaced the screenshot seed’s parser-only blank CAD fixtures with the installed
  production `Device:R`, `R_0603_1608Metric` footprint, and STEP model. Acceptance
  now exercises meaningful Symbol, Footprint, land-pattern, placement, and 3D
  content instead of a technically valid blank stage.
- Installed `three-viewport-gizmo` 2.2.0 (MIT); its Three.js peer range includes
  the project’s 0.169 release. Production dependency audit reports zero
  vulnerabilities.
- Verified in the real WebView2 host at 1,384 × 861 in both themes: flat/correct
  model basis, pad alignment, non-wrapping compact controls, view-cube face click,
  material rendering, Symbol/Footprint fit controls, and SVG export affordance.

### 2026-07-28 — representation-first Library slice implemented

- Reconciled the current project state and vNext architecture with the older
  Library north-star and rebuild backlog. Preserved the four-pane layout while
  replacing implementation-stage navigation with Library, Intake, Runs, Review,
  and Settings responsibilities.
- Defined non-KiCad assets as peer representations with their own adapter,
  provenance, checks, coordinate/unit contract, and EDA binding. Native Altium
  containers and unitless meshes no longer inherit KiCad semantics by implication.
- Added a compact cross-EDA Representation summary to the current open-part page.
  Its equal four-column grid reports Design Tool, Symbol, Footprint, and 3D Model
  for every registered tool. Exact asset reference, provenance, check count, and
  missing/default/embedded behavior stay inside the asset cell they describe.
- Renamed the current workbench tabs to `Overview`, `Representations`, `Sources`,
  and `Activity`. Stable internal IDs remain unchanged while the panel
  decomposition proceeds.
- Fixed a real-host route isolation defect: Tailwind display utilities overrode
  the browser's `[hidden]` rule, so the Overview grid remained above whichever tab
  was selected. Inactive panels now have an explicit layout boundary and a
  route-switch regression test.
- Rejected the first table layout after real-host review because it consumed too
  much vertical space, then rejected a loose chip layout because its detached
  evidence and irregular widths made comparison uneven. The replacement is two
  compact tool rows in an equal four-column grid; the route is `overflow-hidden`,
  and only its bounded Representation and EDA Handoff cards can scroll. The
  tool-only Handoff qualifier is also separated from Category. At 1,384 × 861,
  viewport, document, body, panel client height, and panel scroll height measure
  861, 861, 861, 717, and 717 px in both themes.
- Added explicit GLB frame metadata for STEP, native glTF/GLB, and unitless mesh
  conversions. Unknown source axes/units remain `unresolved` instead of being
  promoted to a guessed fact; conversion cache moved to `c6`.
- Verification: all 1,121 frontend tests, frontend typecheck and production
  build, six converter tests with five environment skips, and Ruff all pass.

### 2026-07-28 — specification identity and pinned-spec schema rebuilt

- Separated the distributor's raw evidence key from the presentation identity.
  Every resolved specification now carries a canonical semantic ID while the raw
  key remains available for provenance, editing, and disagreement review.
- Rebuilt pinned preferences around canonical category and specification IDs.
  Existing label-keyed preferences migrate on read, category spelling variants
  collapse to one bucket, semantic duplicates are removed, and a pin remains
  removable when another part or distributor uses different wording.
- Replaced broad substring rules with category-scoped semantic selectors and
  explicit aliases. Expanded the category profiles with the actual vocabulary
  used by diodes, transistors, ICs, switches, and electromechanical parts.
- Enforced one visible home for a physical fact: recommended and user-pinned rows
  appear in `Key Specifications`; the full list contains the remaining depth
  instead of repeating the same rows immediately below.
- Reclassified lifecycle, lead time, tariff families, pack quantity, and unit
  weight as sourcing/trade facts. They remain visible beside vendors but cannot
  leak into or be pinned as electrical/physical parameters.
- Checked the registry against the repository's historical 158-part corpus, not
  only synthetic fixtures. Added coverage for such observed keys as
  `Standard Pack Qty`, `Unit Weight (kg)`, `BRHTS`, `KRHTS`,
  `Power (Watts)`, `Composition`, `Rds On`, and `Vgs(th)`.
- Updated the headless vendor-data driver to open Trade before its nested HTS
  family, matching the new information architecture. At 1,384 × 861 in both
  themes, the Key Specifications block measures 314 × 117 px, the residual list
  314 × 88 px, neither has dead space or overflow, and the document width equals
  the viewport.
- Verification: all 1,133 frontend tests, frontend typecheck, production build,
  and the dark/light `components` and `part-vendor-data` headless surfaces pass.

### 2026-07-28 — overview balance, pinout placement, and preview space

- Removed Pinout from the top-level workflow tabs. Datasheet pin assignment is
  part identity, so it now sits directly below the CAD readiness row in the
  specimen column instead of requiring a route change and leaving that column
  empty.
- Replaced the tall single-column pinout table with a 184 px two-column card.
  It keeps pin number, signal, datasheet provenance, confidence, and filtering
  visible; large packages scroll only inside the bounded row region.
- Rebalanced the open Overview workspace to three equal content tracks and gave
  the specimen, specification, and sourcing cells the same horizontal inset and
  section rhythm. At 1,384 × 861 the measured content widths are 281, 280, and
  280 px.
- Made specification rows container-aware. Their compact/labelled transition now
  follows the width of the card that owns them rather than the full detail
  workspace, preventing short sourcing values such as lifecycle and country from
  wrapping vertically in a narrow pane.
- Expanded the shared Symbol, Footprint, and 3D preview shell from an 860 × 680 px
  cap to the available window with a 1,600 × 1,100 px safety cap. At the test
  viewport the modal measures 1,360 × 837 px and its inspection stage
  1,358 × 797 px.
- Fixed the headless capture driver so a requested modal is reopened after each
  theme switch. The final dark/light captures therefore verify the modal itself,
  not the page behind it.
- Verification: all 1,135 frontend tests, frontend typecheck, production build,
  four headless-driver tests, and final dark/light Overview and expanded-3D
  captures pass. The document and viewport widths both measure 1,384 px and the
  Overview root has no page-level scroll tail.

### 2026-07-28 — 3D orientation cube and control dock rebuilt

- Replaced the red/green/blue orientation cube with a 104 px monochrome CAD
  instrument. Its six faces use luminance rather than hue, say `TOP`, `FRONT`,
  `RIGHT`, and their opposites, and render at 256 px texture resolution. Crisp
  grayscale corner/edge joints preserve face, edge, corner, and drag hit regions
  without the previous coloured bulb treatment.
- Rejected a first full-width segmented toolbar after visual review: larger text
  made it usable but it still read as a status strip assembled from unrelated
  chips. The replacement is one centered bottom control dock with a raised modal
  surface and five explicit groups: Layers, Appearance, Placement, Motion, and
  View.
- Every expanded-view action now combines a purpose-drawn icon with its name in a
  32 px target. Selected state is raised, inactive state remains visibly
  clickable, placement result is styled as status instead of as another button,
  and the viewport reserves 82 px so the dock never covers the component.
- The owner rejected the compact settings revision after seeing it in context:
  even correctly sized controls turned the specimen card into a cramped miniature
  workstation. Compact 3D is now presentation-only and auto-rotates (except when
  the operating system requests reduced motion); all inspection settings remain
  in the expanded stage.
- Moved expansion out of the detached footer eye and into the representation
  itself. Hovering any present 3D, Symbol, or Footprint stage reveals one centred
  eye-and-`Expand` action; keyboard focus reveals the same action. The stage
  scrim uses the theme canvas colour—darkening the model in dark mode and
  lightening it in light mode—while the small action surface stays opaque. The footer
  now carries only representation identity and link status.
- Added a pure cube-style contract and regression tests that reject any
  non-grayscale surface/hover colour and require camera-destination face names.
- Headless dark/light expanded captures measure the cube at 104 × 104 px and the
  dock's main group region at 789 × 55 px. The corrected compact captures show
  no embedded control bar or settings surface; the 3D card remains 281 × 340 px,
  its sibling cards remain 136 × 142 px, and each has a 1 px layout tail.
- Verification: all 1,137 frontend tests, frontend typecheck, production build,
  and the final expanded/compact headless captures pass. No visible Windows UI
  control was used.

### 2026-07-28 — remaining product work

- Symbol and Footprint now have credible navigation/export controls and share
  the compact stage-centred Expand contract, but remain
  rasterized projections; pin/pad selection, shared logical selection, layer
  control, measurement, mapping, comparison, checks, and provenance are not yet
  implemented.
- The view cube and placement checks are real, but compact and expanded 3D still
  mount separate scenes instead of transferring one renderer/state.
- The renderer still runs a continuous animation loop when idle. On-demand
  invalidation, hidden/off-screen pausing, context-loss recovery, adaptive pixel
  ratio, and the full representative regression corpus remain.
- Facts, empty Sourcing, readiness truth, action placement, and the Context
  inspector still require the controlled IA replacement described above. The
  representation matrix is the first slice, not the finished unified stage.
- Altium native Symbol/Footprint rendering, 3D Body extraction from `.PcbLib`,
  unit/axis calibration UI, accepted-candidate switching, and cross-projection
  selection are not implemented yet.
- Reviewed current and updated Components screenshots at 1,384 and 1,600 widths.
- Inspected the real Windows host after the rail changes.
- Checked current Three.js `ViewHelper` interaction requirements before adopting
  the narrower view-cube dependency.

### Verification caveats

- The specification-schema full gate completed with Ruff green, all 1,133
  frontend tests green, and 4,034 backend passes with 25 skips. Four unrelated
  backend failures remain in the dirty worktree: two capture-attachment
  assertions, the unregistered `altium_native_authoring_proof.py` script, and a
  parenthesized-plural message in `capture/runner.py`.
- The required full gate ran. It reported 3,917 backend passes, 25 skips, and one
  historical harness failure under the 12-worker run caused by an intermittent
  circular-import process exit; that exact boundary test passed in isolation.
- The first full frontend run exposed the removed collapsed wordmark; it was fixed,
  and the complete frontend suite then passed 1,108/1,108.
- The background Windows PowerShell gate process later failed to resolve
  `Get-FileHash` while snapshotting `frontend-dist`; direct PowerShell sessions do
  resolve that command. This is a gate-environment issue, not a claimed green full
  gate.
- The canonical working tree and rebuilt test host contain the UI changes. The
  separate installed `Downloads\Stockroom.exe` checkout remains unchanged until
  the work is committed and deployed.

## References

- Three.js `ViewHelper`: https://threejs.org/docs/pages/ViewHelper.html
- Three Viewport Gizmo: https://fennec-hub.github.io/three-viewport-gizmo/
- KiCad `FP_3DMODEL`: https://docs.kicad.org/doxygen/classFP__3DMODEL.html
- KiCad 3D renderer source: https://gitlab.com/kicad/code/kicad/-/tree/master/3d-viewer
