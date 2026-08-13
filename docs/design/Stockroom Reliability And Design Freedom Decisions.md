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
