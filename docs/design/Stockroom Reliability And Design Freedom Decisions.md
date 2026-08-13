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
verified root history. Each successful main release uses `0.7.0.<build number>`.

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
