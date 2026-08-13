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
