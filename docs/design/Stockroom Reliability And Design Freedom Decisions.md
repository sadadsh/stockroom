# Stockroom Reliability And Design Freedom Decisions

This concise log records the durable product and architecture decisions for the reliability and
complete-design-freedom work. Implementation evidence belongs in tests and Git, not here.

## Accepted Decisions

### Draft, Applied, And Shipped Are Separate

A Draft autosaves for recovery but changes only Design Studio preview. Apply To This PC creates a
local active snapshot. Publish Release remains an explicit developer action. Application updates
preserve both personal and applied design data.

### Global Means One Semantic Element Everywhere

The editor exposes no Instance, Role, or Screen scope choice. An authored or generated target key
addresses the same semantic source element across every route, state, and repeated render. Color
remains independently editable for Light and Dark; other properties are shared.

### Complete Exposure Uses Hybrid Identity

Authored `data-dev-id` values remain stable public identities. The build supplies deterministic
identities to all other Stockroom-owned JSX elements, and imperative DOM uses an explicit helper.
Coverage is derived from the rendered production tree rather than an opt-in marker.

### Editor Chrome Is The Recovery Boundary

Every application element, including the preview root, may be hidden or rearranged. Design Studio's
own chrome is not an editable target. Ctrl+Shift launch bypass and Reset Applied Design provide
recovery from an unusable applied design.

### Provider Browsing Is Modal And Native

The provider document uses a dedicated native WebView positioned inside a draggable, resizable
React modal. The primary Stockroom WebView remains on the app. Close hides the surface without
canceling the acquisition workflow.

### Provider Browsing Is Person Driven

Manage Models provides quick links to major providers plus an editable ordinary address. Stockroom
may construct the correct part-specific landing URL, then stops controlling the provider page. It
does not choose formats, operate provider controls, or automate account and download flows. Native
download interception begins only when a file lands and reports the exact detected, accepted,
rejected, and missing artifacts.

The acquisition starts with a registered EDA multiselect. KiCad and Altium are available first, at
least one remains selected, and the task requests only selected EDA symbol and footprint formats.
A shared 3D model is collected once when required. The selection is task-bound so changing a later
preference cannot reinterpret an already running or retained acquisition.

### Releases Stay Immutable

The frozen launcher activates verified immutable release generations. It never updates production
by mutating the active checkout. Trusted metadata recovery is anchored in the packaged root and
verified root history. Stockroom 1.0 establishes the `1.0.0` product line, and each successful main
release uses `1.0.0.<build number>`.

## Implementation Waves

### Provider Modal Boundary

Manage Models owns the provider list, capture status, downloads, and import recovery. Opening a
provider creates a React modal with a fixed Close control and a measured native content rectangle.
The managed WPF host keeps its provider WebView inside that rectangle. The source pywebview host
uses a second provider-only window over the same rectangle; it never navigates the Stockroom
window. Closing only hides the native surface, so an active download and its lease continue.

### Generated Global Identity Boundary

The JSX build transform will preserve authored `data-dev-id` values and add deterministic
`data-design-id` values to otherwise unidentified Stockroom-owned host elements. The key is derived
from the owning source component and host-element source location, so repeated renders share one
global target while unrelated elements cannot collide. Portals remain Stockroom-owned; provider
document internals and raw CAD geometry remain outside this boundary. Runtime-created Stockroom DOM
must use the same identity helper. Production coverage derives candidates from the rendered tree and
fails when any owned element lacks either identity.

Dynamic JSX tags, cloned elements, portals, and imperative DOM use a deterministic runtime fallback.
The coverage gate instruments only the bounded Stockroom product tree before proving that every
non-technical element is addressable; Design Studio chrome remains outside selection.

Design Document v2 removes legacy scope selection, stores global target overrides, and retains
unresolved identities as orphaned edits. Loading v1 is a migration, not a destructive rewrite:
legacy overrides are mapped where deterministic authority exists and otherwise remain visible for
manual remapping.

### Preview And Edit Mode Boundary

Design Studio has one operating boundary: Preview leaves Stockroom fully interactive, while Edit
enables both selection and direct layout manipulation. The former Browse, Inspect, and Arrange
states remain accepted only as persisted preference migration inputs; they are never shown as
separate modes. Design Studio chrome is marked as protected and excluded from generated target
selection, while authored and generated product identities use the same selection path.

### Manual Provider Acquisition Boundary

Manage Models now treats every provider row as a quick link rather than an automation recipe. The
user chooses KiCad, Altium, or both before opening a provider; that selection is frozen for the
capture task and controls the exact backend requirements and provider formats requested. The modal
address bar supports ordinary HTTPS navigation, while Back, Forward, Reload, and Close remain
Stockroom controls around the dedicated provider WebView.

Stockroom does not operate the provider page. It observes downloads after the browser receives
them, validates only the selected EDA deliverables, retains partial results, and reports remaining
requirements. A shared 3D model is requested once even when both EDA tools are selected. Design
Studio scenarios may open a deterministic provider modal to show each state, but entering Manage
Models in normal use never launches a provider automatically.

Closing the preview chrome is always a local UI operation. The modal is removed and focus restored
before Stockroom asks a native host to hide its provider WebView. A Design Studio fixture may refuse
that native effect, but the refusal can never trap the person inside the modal.

### Draft And Applied Design Boundary

The personal Design Document is an autosaved Draft and is resolved into the preview only while
Design Studio is open. Outside Design Studio, Stockroom resolves either the explicitly activated
machine-local document or the shipped design; autosave alone never changes the ordinary app.

Apply writes a complete validated Design Document atomically to
`design-studio-applied.json` under the machine configuration directory and records its content
revision. This file is outside immutable release generations and survives updates. Reset Applied
Design deletes only that activation, leaving the personal Draft untouched. Source promotion remains
a separate developer action and is not represented by the fixed Apply control.

The visible action uses Stockroom's established interface vocabulary: **Set** writes the Draft to
this PC, while the technical endpoint remains `/api/design-studio/apply-local`. This wording does
not collapse Draft, machine activation, and source promotion into one operation.

### Universal Direct Manipulation Boundary

Edit mode places one protected overlay over the exact clicked Stockroom element while every
occurrence with the same authored or generated identity receives the resulting global override.
The overlay owns one move grip, eight directional resize handles, visibility, flow or detached
placement, and reset. Pointer motion is previewed imperatively, then committed as one atomic draft
replacement on release so one gesture is one undo entry; Escape restores the pre-gesture styles.

Flow movement uses relative offsets and retains layout space. Detached movement uses absolute
placement inside the nearest identified Stockroom container, which becomes positioned only when
needed. Snap uses the current Studio grid and Free uses one-pixel increments; both compensate for
preview zoom. Hiding uses `visibility` so the target remains discoverable and reversible in Layers.

Layers starts with meaningful targets, offers All Elements for every generated wrapper, and retains
hidden targets as dashed ghost rows. Hide Screen Contents targets the product root, allowing a blank
application while the editor remains usable. Both Windows hosts capture Control+Shift during launch
as an ephemeral applied-design bypass; the bypass is never saved as a preference.

### Compact Inspector And CAD Presentation Boundary

The visible inspector has four stable sections only: Layout, Appearance, Content, and Advanced.
Existing safe box, typography, icon, behavior, state, and validated-property capabilities are grouped
inside those sections instead of exposed as seven competing modes. Selection context remains visible,
but internal implementation domains are no longer navigation concepts the person must understand.

CAD presentation is stored as typed Design Document data keyed to the Stockroom-owned Symbol,
Footprint, or 3D preview container. The presentation layer may hide or restyle rendered bodies, pins,
labels, footprint layers, models, boards, grids, and scene appearance; it never changes parsed CAD
geometry, source files, placements, nets, pad coordinates, or engineering primitives. Raw SVG/canvas
geometry remains protected while its Stockroom container and typed presentation controls are editable.
All color-bearing element, interaction-state, and CAD presentation values are written into the active
Light or Dark theme patch; geometry, visibility, content, and arrangement remain shared global edits.

### Trusted Update Recovery Boundary

The packaged `Root.json` remains the only trust bootstrap. Machine-local TUF metadata is a cache,
not an authority: a missing, empty, truncated, or invalid cached root is quarantined and restored
atomically from the packaged root or the newest locally retained root that chains back to it. A
valid cached root is never silently replaced, preserving TUF rollback protection and root rotation.

Release downloads stage into a new immutable generation and are health-checked before activation.
The running generation is not edited in place. Activation occurs on the next launch or an explicit
Restart Now, retains the previous accepted generation for rollback, and leaves the library, personal
Design Studio Draft, and Applied Design outside release directories. Update status reports Current,
Downloading, Ready, Offline, Blocked, Retry, or Rollback from durable host state rather than guessing
from a Git checkout.

### Repository Byte Fidelity On Windows

Every Git repository created or cloned by Stockroom sets repository-local `core.autocrlf=false`
and `core.longpaths=true`; clone checkout receives both settings before files are materialized. Generated CAD,
transaction snapshots, rollback files, and publish comparisons are byte contracts; they must not
change because a machine-wide Windows Git preference converts line endings, and provider library
paths must remain writable beyond the legacy 260-character boundary. These local settings do not
alter the person's global Git configuration or normalize unrelated repositories.

### Direct Editing Reliability Boundary

Direct selection accepts any Stockroom-owned target in the product tree or an authored Stockroom
portal, while continuing to reject Design Studio chrome and third-party page internals. Runtime
fallback identities include a deterministic structural sibling position so unrelated elements can
never share an accidental override that moves or hides an entire surface.

Rotation is a first-class direct gesture beside move and resize. Pointer rotation is measured around
the selected target center; keyboard rotation uses one degree in Free mode and fifteen degrees in
Snap mode. A complete gesture remains one undo entry and Reset restores the prior transform.

Grid visibility, snapping, and cell size are separate settings. Cell size is a persisted integer from
1 through 64 pixels, drives both direct manipulation systems, and scales its visible preview grid with
preview zoom. The complete bundled Font Awesome Free library opens directly in Content editing; the
small same-family icon row is only a convenience, never the apparent library boundary.

Content identity is exact even when appearance is shared. Editing text writes only the selected
`data-copy-id`, and replacing or relabelling an icon writes only the selected `data-icon-id`; shared
roles may still carry global layout and appearance styling. A role can never cause an MPN value edit
to rewrite Stockroom branding or another field.

### Provider Launch And Complete Intake Data Boundary

The React provider modal is the permanent owner of browser chrome and geometry; the native provider
WebView is only its clipped content surface. A viewport published before the native capture lease is
ready is retained and applied when that lease opens, so startup ordering can never leave the modal on
a placeholder. The primary Stockroom WebView is never navigated away from the application.

Adding a component exhausts every eligible data source for the exact manufacturer part number. An
early Mouser or DigiKey identity hit may lead the merge, but it cannot terminate the LCSC, datasheet,
or other configured distributor passes. Distributor stock numbers are resolved once to the canonical
manufacturer part number before another distributor is queried; one distributor's order number is
never sent to another distributor as if it were the MPN.

Remote PDF datasheets are fetched through Stockroom's authenticated document endpoint, validated as
public HTTPS PDF bytes, and cached outside the library record. The renderer never asks pdf.js to fetch
a distributor URL directly, avoiding browser CORS failures while preserving an explicit source-page
fallback and leaving canonical library data unchanged.

### Visual Property Editing Boundary

Common Design Studio settings are manipulated visually rather than entered as CSS text. Numeric
geometry, typography, opacity, stroke, viewport, grid, and CAD alpha use bounded sliders; colors use
native color controls; closed vocabularies use pickers or segmented choices. Every visual control
writes through the same validated Design Document grammar and remains undoable.

Text entry remains only where text is the actual content: labels, copy, search, accessibility text,
draft names, and the explicitly named Advanced validated-value escape hatch. Advanced preserves exact
CSS authoring without making ordinary property editing depend on memorizing CSS syntax.

### Exact Intake Recovery And Direct Gesture Safety

Distributor enrichment remains exact-identity only. When an entered manufacturer part number has no
exact match but an official distributor returns close candidates, Stockroom must not create or enrich
a near-match record automatically. It presents the candidate manufacturer part numbers as explicit
corrections; choosing one replaces the draft identity and starts a new exhaustive lookup against all
enabled sources. The source status must distinguish an API query that returned no exact match from a
source that was never queried.

Direct Edit selection begins on the capture-phase pointer press, not the later click. This makes the
element under the visible highlight the inspector authority before nested controls or copy handlers can
consume the click. A press on Move, Rotate, or Resize without actual pointer motion is selection-only
and creates no draft/history entry. Design Studio overlay chrome is permanently outside the target
grammar, and Escape cancellation restores the complete inline-style preview before leaving the gesture.

The provider placeholder is not success evidence. It remains visible only behind the dedicated native
provider WebView; browser readiness requires a current host runtime to accept and apply the measured
modal viewport after the capture lease exists. Source fixes are not represented as delivered until CI
passes and a usable Windows runtime containing them is published or installed.

### Quiet Hierarchy And Exact Visual Controls

Stockroom groups routine content with spacing and restrained surface shifts, not a box around every
row, action, and nested section. Borders remain for major application regions, active inputs,
selection, tables whose columns need tracking, and floating surfaces. Specifications stay compact,
but ordinary rows use a subtle horizontal rhythm rather than a full cell grid.

Each region exposes one visually primary action. Secondary actions are quiet controls, while rare or
administrative actions remain in the existing overflow or Manage menu. Simplification must never
remove data, provenance, conflicts, accessibility, or a unique workflow.

Settings uses one readable content column. Child sections may not retain container-query column spans
from an older multi-column parent because those spans create implicit tracks and collapse real content
to a few pixels. Every Settings scenario must preserve a useful content width at supported viewports.

A background onboarding refetch may report an error without erasing the last validated ready document.
When cached ready data exists, Stockroom keeps the application mounted and lets the owning Settings
section show its retryable local error. Only the absence of any validated onboarding document may
replace the application with the fatal setup error. A transient refetch must never gray or blank the app.

About shows update truth in every state. A current installation receives one compact Current status;
a stale installation keeps its warning and recovery action. Suppressing the current state until it is
visually identical to the generic About view is not an acceptable scenario or product representation.

Every Design Studio range uses one visible-value contract. Its current value and unit remain visible
during pointer and keyboard use, and exact entry is available where a precise number matters. Slider
position is never the only representation of the saved value.

### Quiet Preview And Structural Separation

Preview mode renders normal Stockroom without editor underlines, tab stops, tooltips, or pointer
interception. Edit mode alone exposes those authoring affordances. The target identities remain in the
Preview DOM so switching modes never changes what can be edited.

Separators use low-contrast structural tokens instead of outlining routine content. Dark and Light
themes keep stronger boundaries for the application frame, floating surfaces, active inputs, tables
that require column tracking, and the selected editing target; nested cards, rows, labels, and quiet
actions must not recreate a grid of boxes.

### Component Data Authority And Commit Boundary

An exact Add Part lookup asks Mouser first and DigiKey second. Manufacturer datasheets may verify or
fill facts those catalogue APIs do not provide. LCSC and browser-derived pages may still contribute a
purchase link, stock, or CAD discovery, but they do not decide specification values or the component
category. An absent fact is not materialized as a synthetic `Missing` specification row; Stockroom
shows only facts a permitted source supplied and never invents an engineering value.

Mouser is the fixed winner when Mouser and DigiKey disagree. Every competing answer remains visible
as evidence, but routine component editing does not offer a source-ranking control. A reviewed manual
value is still an explicit override rather than a new source priority.

The same authority owns the visible manufacturer, description, and datasheet identity. LCSC and page
scrapes may supply offers or discovery links, but they cannot make the component identity disagree with
the specification record. Sourcing automatically marks one strongest usable in-stock offer as Suggested;
there is no routine priority editor to learn or maintain.

Authority follows evidence, not merge order. Each Mouser and DigiKey binding participates even when its
value exactly agrees with an earlier discovery result and therefore created no conflict entry. Provider-
branded browser HTML remains browser evidence; only the official Mouser and DigiKey adapters enter the
fixed fact order. A downloaded PDF becomes manufacturer-datasheet authority only after its extracted text
contains the requested MPN. Until then, neither its identity fields nor its specifications may fill the
part. A pasted provider page may recover the MPN needed for that official lookup and may update its own
offer, but it cannot directly populate identity or engineering facts. When a discovered PDF does contain
the exact MPN, its URL is promoted as the verified manufacturer-datasheet link while the page that first
supplied the link remains visible in provenance.

Older records keep LCSC and parsed-page candidates in provenance and conflict views, but those candidates
cannot become the preferred specification, manufacturer, or description. Refiling an unclassified record
uses the same official-source filter. Schema expectations remain available as one concise expected and
recommended gap summary; they do not create rows or a routine Missing filter.

Offline re-derivation applies that filter directly to the source-tagged result rebuilt from immutable
Mouser and DigiKey payloads. It must not flatten those answers into a provenance-free record view before
classification. A legacy record may be refiled from a stored value only when its enrichment or alternate
evidence identifies a permitted authority; an unattributed value is retained but cannot classify the part.

`Suggested` means actionable as well as available. The first offer in the existing provider order must
have positive stock, a successful source state, an orderable SKU, a listing URL, and a positive unit or
price-break value. A stock number without a route to order it is evidence, not a recommendation.

The Add Part commit boundary must carry every selected specification, its source and confidence,
procurement fields that live as specifications, provider catalogue data, both distributor offers, and
all disagreements. A successful lookup is not complete evidence until the newly created component
dossier renders that same data after persistence.

### Exact Target Editing, Safe Additions, And Recovery

A generated text or icon identity is an independent target even when it lives inside an authored
container. Its own visible node participates in the Text or Icon domain; the inspector must never
replace it with the first text or icon found in an ancestor. Copy selection and element selection are
synchronized from the same pointer target so a label cannot display one identity while the inspector
edits another.

Adding an icon is a declarative Design Document edit. The document stores a sanitized SVG body, the
stable target it is attached to, and a closed before/after placement. The runtime may materialize that
SVG, but it accepts no HTML, script, event handler, or network URL. Removing or undoing the edit removes
the materialized node without changing the component's React source.

Bring Forward and Send Backward are target-local z-index edits in the same undo history as all other
visual changes. The app preview root cannot be moved, resized, or rotated through a casual direct
gesture; whole-screen hiding remains an explicit reversible command in Layers.

The product preview is protected by a Design Studio recovery boundary. A render exception leaves the
fixed editor chrome and an Undo recovery action visible instead of replacing Stockroom with an empty
canvas. Draft application remains atomic and the last accepted document remains recoverable.
# Canvas-First Design Studio Simplification

- Ordinary Design Studio now has one canvas, one contextual inspector, and closed-by-default Screens and Layers drawers.
- View settings are progressively disclosed; developer IDs, tokens, diagnostics, source saving, and publishing are isolated in Developer Tools.
- Each editing capability has one ordinary home. Legacy editors may remain available only behind Developer Tools while migrations complete.
- The icon picker is a large offline multi-library visual catalog rather than a narrow Font Awesome list.
- Automated tests prove contracts; representative user workflows and screenshots determine whether the result is simple and polished.

## Blind-Audit Repair Decisions

### Exact Occurrence Is Editing Authority

A semantic identity may intentionally recur, but a pointer selection always owns one exact rendered
occurrence until the user explicitly multi-selects. The selection contract therefore carries both the
stable semantic identity and a stable occurrence locator. Every inspector facet, direct gesture,
domain write, reset, state preview, and developer tool consumes that same authority; none may fall
back to the first matching DOM node or silently expand through a role.

Generated identities are fallbacks. A reusable primitive must preserve the identity supplied by its
caller, and runtime copy/icon/layout metadata must not overwrite a valid caller or authored identity.
If a remount cannot prove which occurrence replaced the selected node, Stockroom clears the selection
instead of guessing and editing a peer.

### Collision Means Recovery, Never Replacement

All add paths use the same canonical MPN identity as catalog lookup. An exact or normalized match is
classified as Existing before any filesystem, CAD, index, or Git mutation. The user receives Open
Component and Refresh Evidence actions; Stockroom never turns a repeated add into a destructive
replacement. Editing a visible primary purchase URL changes only that offer and preserves every other
offer and its price, stock, ordering-number, currency, and provenance evidence.

### Recovery Is Independent Of History

Undo is not a crash-reset mechanism. When a preview render fails, Design Studio restores the last
known renderable document or exits the failing fixture/state and remounts the product tree. This must
work when history is empty. The preview root is protected consistently across direct handles, the
compact inspector, Layers, advanced controls, and developer tools.

### Delivery Evidence Is Layered

A green source or fixture test does not prove the installed product. Stockroom reports source tests,
native-host fixture proof, signed-package installation, visible Windows acceptance, and update/rollback
adoption separately. Main pushes remain the release trigger, but publication waits for the canonical
quality workflow and legitimate trusted signing/feed configuration. Missing trust inputs are a blocker,
not permission to invent a self-signed production identity.

### Full-Surface Polish Uses Hierarchy Before Chrome

The final visual pass removes decoration only when structure and meaning survive. Routine specification
rows, evidence drawers, nested editors, sourcing groups, summary metrics, and task choices use spacing,
type hierarchy, and one neutral background step instead of stacked outlines. One hairline remains where
it marks a real application edge, section heading, or data-table tracking boundary. Active inputs,
selection, floating surfaces, and safety states keep the stronger boundaries they require.

The pass is judged from representative Light and Dark screenshots at supported window sizes. Automated
tests protect behavior and identity, but they cannot accept density, hierarchy, discoverability, or visual
calm. Every screenshot review records what still competes with the focal workflow and either corrects it
or leaves one explicit backlog item with its evidence boundary.

Missing CAD representations keep their named row and exact status, but they no longer receive an equal
share of the inspection stage. At rest, each absent Symbol, Footprint, or 3D Model uses one compact
40 px technical-sheet strip; attached previews alone divide the remaining height. Focusing a missing
row may expand it, and Manage CAD Assets remains the single acquisition route, so the quieter absence
state changes no data or workflow.

### Intake Never Promises Automatic CAD

Adding a component and collecting CAD are separate, person-controlled workflows. Intake records
`CAD Needed` and points to Manage Models, but it never describes an automatic provider ladder, opens a
provider, chooses an EDA, or starts a download. Manage Models may take the user to the correct provider
page and may process a file after the user downloads it; it does not drive the page for them.

Visual instructions follow the same rule: a real input keeps an input boundary, a dangerous state keeps
its warning treatment, and a dock or table may keep one structural edge. Read-only values, helper paths,
candidate summaries, completed setup states, and nested review sections use type, spacing, and neutral
surface steps instead of borders that imply additional controls.

### A Successful CAD Download Finishes The Part

Provider browsing remains person-driven, but Stockroom owns the download outcome. Navigation and download
progress must have bounded stall detection and an explicit recovery action; a spinner may never run forever.
When a landed archive validates and maps unambiguously to every asset required by the selected EDA set plus
the shared 3D model, Stockroom stages and attaches it to the exact part automatically and shows a durable
`CAD Ready` result. A second Apply click would add no useful decision in that happy path.

Ambiguous or partial archives keep the proposal and manual-mapping fallback. They state the exact roles still
needed and never mark the part complete. Other providers remain available later, but they are optional after
one complete validated package. Adding staged part assets to the machine's KiCad or Altium catalog remains a
separate, explicit Assets build so downloading a part never changes an EDA installation unexpectedly.

### One Inspector, Four Groups, And Explicit Apply

The ordinary selected-element inspector has exactly four progressive groups: Layout, Appearance,
Content, and Advanced. Visibility and geometry share Layout; interactive states share Appearance;
text, icons, and CAD presentation share Content; validated CSS and behavior remain Advanced. This
removes the former Quick, Arrangement, and States duplication without removing any capability.

Draft autosave and activation use different language. `Apply To This PC` is the only ordinary action
that makes a personal draft affect Stockroom outside Design Studio. Status uses Draft, Draft Changes,
Applying, Applied, and Apply Failed. Release publishing remains a separate developer-only workflow.

### The Toolbar Keeps Only Primary Actions

The fixed Design Studio toolbar contains Exit, Preview/Edit, the current screen or state, theme,
undo/redo, View, status, and Apply To This PC. Viewport, zoom, presentation, grid visibility, snap,
and the exact shared grid size live together in the View popover. Grid size remains an explicit
1–64 px slider with a visible numeric value; moving it out of the canvas bar reduces clutter without
hiding or weakening the setting.

Fit measures the actual canvas after every open drawer and inspector width is applied. The scaled
product is centered by a stage whose layout footprint equals its rendered width; transforming an
oversized child around its center is rejected because it shifts half the preview outside the clipped
canvas. Fit must leave the complete right edge visible and clickable at every supported viewport.

### Provider Windows Stay Inside Stockroom

The provider browser uses one movable modal with eight resize edges and corners. Drag and resize
measure the actual frame and preserve a 24 px application margin; they do not use viewport-half
guesses or a browser-specific bottom-corner resize affordance. Every accepted frame change republishes
the native provider viewport, while Close only hides the modal so an owned download can finish.

### One Icon Grammar Serves The Whole Product

Stockroom uses one coherent interface-icon family, optical grid, stroke weight, corner language, and
size scale across navigation, actions, status, CAD, and component-category imagery. An icon has one
stable semantic name and one registered asset; components may not substitute unrelated glyphs merely
because they are visually convenient. Filled treatment is reserved for selected navigation and strong
status, while ordinary actions use the shared outline treatment. Component-category marks follow the
same geometry and weight so the catalogue reads as one product rather than a mixture of icon sets.

The audit covers every registered icon, detects duplicate semantics and inconsistent view boxes or
stroke contracts, then reviews representative Light and Dark screenshots. Design Studio may replace a
selected icon from the installed catalogue, but shipped Stockroom defaults remain curated and coherent.

Implemented 2026-08-19: Tabler Outline 3.46.0 owns 97 shipped defaults on a 24 px optical grid with a
2 px round stroke. Six Stockroom IEC-style category marks fill the upstream library's semantic gaps on
that exact frame; the 19 component categories therefore stay both coherent and truthful. Stable
semantic IDs map to unique source marks and the neutral-theme adapter uses the same authority.
Stockroom technical CAD artwork and LinkedIn/GitHub brand marks are explicit exceptions. Filled
navigation or status is a caller-selected treatment, never an alternate shipped family. Served-bundle
1500 x 900 Light and Dark captures under `work/Icon Grammar Audit` verify representative navigation,
actions, statuses, and category marks. Source-to-bundle parity, native WebView2 rendering, Windows
DPI, and minimum-width behavior remain final acceptance boundaries until the synchronized build is
captured.

Correction decision, 2026-08-19: one visual grammar does not justify a false symbol. When Tabler has
no truthful electronics mark, Stockroom uses a small IEC-style category drawing on the same 24 px,
2 px, round-cap outline frame. Crystal, fuse, LED, op-amp, transformer, and transistor therefore use
literal circuit symbols rather than a gem, battery cell, desk lamp, generic triangle, workflow arrow,
or binary tree. Interface controls never use font characters as icons; zoom, disclosure, and sort all
resolve through the semantic registry. A single completion or selection uses one check, while the
double-check remains reserved for the theme slot that explicitly asks for it. The 3D viewer's board
visibility control uses a board mark, not electrical ground.

Whole-application icon audit repair, 2026-08-19: the renderer must preserve visible outline
geometry even when it loads a legacy persisted `solid` treatment, and the ordinary Design Studio
inspector no longer offers that misleading treatment for outline defaults. Component-category
resolution uses explicit normalized taxonomy and ordered token-safe aliases; unsupported categories
receive a dedicated neutral category mark instead of borrowing an IC symbol. Every remaining
Design Studio font glyph, project-document monogram, and loading spinner routes through the semantic
registry. Forward navigation, Projects, CAD Assets, embedded provider display, existing-file import,
and neutral information each have distinct truthful IDs. The uniformity gate audits individual SVG
nodes and approved technical or brand exceptions, rendered font glyphs, CSS pseudo-icons, imported
or constructed SVGs, dynamic IDs, semantic collisions, and visible geometry across default, Light,
Dark, disabled, selected, and legacy-solid states. The change is accepted only after focused failing
regressions turn green, all production icon IDs resolve, TypeScript passes, and the broad icon,
adoption, and UI-focused suites pass; generated `frontend-dist` is outside this repair slice.

Scoped re-review correction, 2026-08-19: legacy `solid` is also absent from the original Dev Panel
icon editor, and persisted values display as the safe line fallback. Automatic 3D placement,
distributor offers, generic success, generic error, and value-transition separators now have typed,
truthful semantic IDs with distinct outline assets; modal close and generic information reuse their
existing action and status semantics. The shared `.ico` rule consumes the Design Studio stroke token
with the shipped 2 px fallback. The source gate now counts every approved raw SVG node, recognizes
unlisted standalone Unicode icon marks while exempting prose and keyboard hints, and rejects SVG
assets hidden in CSS URLs or expression-backed image sources.

Visual sizing and rail-semantics correction, 2026-08-19: caller-supplied icon classes remain
authoritative, so every production icon call that supplies `className` must also declare a bounded
square size or explicit height and width. A source gate now audits direct icons, shared named
wrappers, and local pass-through wrappers; the STM Explorer search glyph explicitly uses its compact
box instead of inheriting an unbounded SVG viewport. Design Studio also owns the dedicated
`nav.design-studio` palette mark rather than reusing the Settings tool mark. Both defects require
component-level regressions in addition to representative Light and Dark visual capture.

The Design Studio drawer controls also name what they reveal: Screens uses a screen-layout mark and
Layers uses a layer-stack mark. They may not borrow the Components book or the search-filter funnel,
because those shapes already mean different product actions elsewhere.

Icon-library loading correction, 2026-08-19: the optional Design Studio catalogue may contain several
offline families, but opening the picker must not parse all of them. The picker starts with one family,
loads and caches only the family the person selects, and keeps every other library dormant until it is
requested. Search is scoped to the active family, with an explicit family selector for broader choice;
pagination alone is not accepted as a loading boundary. The normal Stockroom application continues to
load none of these optional catalogue chunks.

### Assets Opens On The Next Useful Work

The Assets page does not stop at a blank chooser. When components need CAD evidence it opens Needs
Assets; otherwise, when validated components await catalogue projection, it opens Build Now. The two
views remain directly switchable, but the page never spends the dominant workspace asking the person
to choose between two already-known next steps.

### Dense Tables Use Quiet Structure

High-density engineering tables use subtle row separation, row hover, and a clear horizontal-scroll
boundary instead of bright full-width rules. Headers that continue beyond the viewport must remain
reachable and the surface must visibly communicate horizontal movement; clipping a partial heading
without a cue is not accepted. Density may remain high, but the table cannot visually overpower the
data it exists to compare.

### Project Files Preserve Their Difference

Files with the same base name must remain distinguishable in the project list. The list shows the
base name and a truthful PCB, Schematic, or Project kind rather than truncating every entry to the
same prefix. The full file name remains available for precise identification.

### Manage Models Is A Dashboard, Not An Empty Browser Frame

Before a provider is chosen, Manage Models shows the selected EDA requirements, providers, current
downloads, staged files, and the manual-import fallback in a compact workspace. It does not reserve
the rest of the application for an empty historical browser pane or say a page opens “here.” Clicking
a provider opens the dedicated movable and resizable modal; closing that modal returns to the same
dashboard without canceling an owned download.

When no download has started, the remaining workspace presents one quiet next-step message that
points to the provider links and the manual-import fallback. Provider links read as deliberate quick
actions, not undifferentiated navigation text, while the empty state avoids another bordered panel.

### Release Evidence Describes The Product That Actually Ships

The 1.0 package must not claim more evidence than it carries. Its SPDX document inventories every
packaged worker, native-host, CAD-converter, and tool file; computes the SPDX package verification
code from that declared file set; and records the locked Python and production frontend dependency
graphs. Third-party notices name the actual pinned icon sources, including Tabler Outline 3.46.0 and
the offline Design Studio catalogues. Generated evidence remains deterministic and is tested from
the same lockfiles used to build the product.

The SPDX file is the sole circular verification-code exclusion. Every other release-manifest
member, including notices and exact license texts, is an analyzed SPDX file and contributes to the
package verification code; the gate compares that inventory against the produced release manifest.

Stockroom's own licensing remains the existing all-rights-reserved default unless the owner chooses
an open-source license separately. The repository states that default explicitly for 1.0 rather than
silently implying an open-source grant. Native version metadata names the packaged worker as the
worker, never as the visible bootstrap or `Stockroom.exe`.

### Layers Show Product Meaning Before Implementation Detail

The default Layers view contains authored product boundaries plus generated targets that are
independently useful to edit. A generated wrapper is not meaningful merely because it contains
text, hosts an icon, or implements a control that already has a richer copy, icon, layout, or
authored identity. Those internal generated identities remain available under All Elements so no
editing freedom is removed. Hidden edited targets remain visible as ghost rows regardless of the
filter.

### Main Owns The Stable 1.0 Release Line

A successful push to `main` is the only automatic publication trigger. It produces the immutable
four-part Windows version `1.0.0.<GitHub run number>` and a normal GitHub Release, not a prerelease.
Manual workflow dispatch remains a bounded package-verification route and does not publish. Version
tags do not create a second competing release line; this avoids a later three-part `v1.0.0` being
older than an already published automatic build and keeps the updater aligned with the owner's
push-based delivery model.

### The Committed Web Bundle Uses A Content Identity

`app/frontend-dist` cannot embed the checkout commit as its reproducibility identity: committing the
bundle creates a new commit, so the next clean CI build would necessarily change the bundle again.
The frontend build therefore derives one stable hexadecimal identity from its complete declared
source/configuration input set and pinned lockfile. Identical inputs reproduce identical bytes before
and after commit; any relevant input change requires a rebuilt distribution. The signed release
manifest continues to carry the exact Git revision separately, so content identity never substitutes
for release provenance.

Production builds ignore local `.env` files and reject inherited development or `VITE_*` inputs.
Development API base and bearer fallbacks are compiled only into the browser development path, so
machine-local configuration cannot alter or leak into committed release bytes.

### Release Review Safety Boundaries

A downloaded CAD package may attach automatically only when its parsed identity is bound to the
exact target part MPN. A merely unique or complete package with absent or different identity remains
staged for explicit review; convenience never outranks attaching files to the correct component.

An accepted Design Studio edit remains pending until the personal-design service acknowledges the
exact revision. Conflict, transport failure, navigation, or close cannot silently discard the sole
pending or in-flight document. Close either completes the flush or remains visibly blocked with a
recoverable draft.

Official provenance is granted only from server-held raw evidence for the exact punctuation-
preserving part identity and selected result. Client-submitted values may choose among proven
bindings but cannot manufacture an official source relationship.

Manual provider sessions and staged files have explicit ownership and bounded lifetime. Apply,
discard, expiry, and host shutdown release their leases and temporary evidence.

The packaged worker startup channel never releases an unauthenticated loopback port for another
process to win. Readiness must be tied to the exact spawned worker through an inherited listener or
an authenticated challenge before the native host sends its bearer token.

Duplicate editable occurrences need stable, deterministic locators that survive a restart. Layers
may group their semantic identity for readability, but must expose each concrete occurrence when
selection, hiding, or a saved override differs.

### Release Health Keeps Current Contracts And Exact Notices

Design Studio documentation describes the shipped Preview/Edit workflow, personal Drafts,
explicit Apply To This PC activation, and automatic design identities. Authored semantic IDs remain
authoritative when present, but they are not a prerequisite for editing Stockroom-owned UI. Shipping
a design through source control remains a separate developer release action.

Every bundled font carries its exact upstream license in the release package and a matching entry in
Third Party Notices. Repository-local task evidence stays ignored and cannot become product
authority. Binary font formats are marked as binary so Git never rewrites release assets.

### Repository Tooling Stays Product-Owned

The release repository carries product source, product tests, and deterministic project tooling.
Generated editor tooling, private instruction references, and tool-specific configuration are local
development artifacts rather than product authority. They are
removed from version control and ignored at their generated locations. Frontend acceptance remains
owned by the repository's type, test, accessibility, build, browser, and native gates.

The repository publishes product source, product documentation, deterministic build inputs, and
required third-party notices only. Personal development instructions and tool-specific working files
remain local so the public tree presents Stockroom itself without unrelated development metadata.

### Wall-Clock Performance Runs On Controlled Hardware

The 1,000-identity workflow simulation keeps its 35-second acceptance budget on the supported
Stockroom workstation through `scripts/Gates.ps1`. A shared GitHub-hosted runner is not a comparable
performance instrument: the exact accepted source completed the measured call in 23.27 seconds on
the supported PC but required 375.27 seconds on the hosted runner's virtual SQLite storage. GitHub
CI therefore runs the smaller exact-once scale case and all ordinary backend behavior, while the
controlled workstation gate alone enforces the absolute wall-clock budget. This separates functional
regression detection from variable host performance without weakening the product budget.

### Cross-Machine UI Gates Separate Structure From Local Presentation

Stockroom displays exact timestamps in the person's local time. DOM-structure snapshots preserve
the count and position of those tooltips but normalize only their clock text, which is independently
covered by the timestamp formatter tests. This keeps UTC CI and the local Windows app comparable
without forcing production timestamps into the wrong timezone. A deliberately broad Design Studio
inspector integration may use an explicit per-test timeout when it exercises lazy icon-catalog loading;
the timeout belongs to the test boundary and does not weaken any product response-time contract.

### The Provider Browser Frame Owns The Modal Body

The provider browser is a native surface placed inside Stockroom's React modal. Its React frame must
fill the modal body before publishing native viewport geometry; a content-sized frame can collapse to
toolbar height and cause the host to reject the route as too small, leaving a misleading blank or
perpetually opening browser. The frame therefore owns the full available body height, and focused tests
cover that sizing contract.

Close is always a recoverable Stockroom action. It dismisses the React modal immediately, including
while the native route is still preparing or when a stale identity-bound native close command is
refused. The exact task remains active in the background, and Show Provider restores the same page
without restarting the download workflow.
