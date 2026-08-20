# Stockroom Full Blind Audit

## Scope And Baseline

This audit independently inspected Stockroom `development` at
`077c0502a7f849124a8607826b534a0e6509d1b8`. It covered the Add Parts data path,
component dossier, documents, CAD acquisition, Design Studio, native Windows host,
update/release system, CI, dependency security, repository health, and the current
machine's installed/runtime state.

The audit used task-owned temporary configuration for runtime checks. It did not mutate
the real component library, production signing state, trusted roots, or supplier
credentials. Findings are separated from external acceptance boundaries.

## Premise Results

### Added parts are missing DigiKey and specifications

**Observed report: supported on the photographed laptop build. Proposed current-source
cause: disproved.** A live exact-MPN run for `ADG714BRUZ-REEL` against current source on
this PC queried both configured Mouser and DigiKey APIs. It returned 40 sourced
specifications: 19 Mouser, 20 DigiKey, and one browser-derived field. It also returned
both distributor URLs, ordering numbers, prices, stock, and catalogue identities.

The current specifications/category authority is Mouser first, DigiKey second, then the
manufacturer datasheet. LCSC is excluded from that fact boundary. This localizes the
photographed behavior to stale installed code, credentials/configuration, or cached
state on the laptop rather than a current-source early-return after Mouser. Delivery
repair is therefore required in addition to source tests.

### Datasheet reports “failed to fetch”

**Observed report: supported on the photographed build. Current-source fetch path:
supported.** Current source fetched the exact Mouser PDF referenced by the photographed
part as 367,501 valid PDF bytes. Stockroom's authenticated document proxy is able to
serve it without asking pdf.js to cross distributor CORS boundaries. Installed-build
and native document-opening acceptance remains required.

### Clicking one target edits another

**Supported and localized.** The overlay retained the exact clicked DOM node, but the
Inspector and developer controls retained only its stable ID and re-resolved the first
matching occurrence. The automatic identity transform also appended fallback identities
after prop spreads, allowing reusable primitive internals to overwrite distinct caller
identities. Role metadata silently broadened some edits. These combined mechanisms
explain a clicked MPN target editing Stockroom branding or unrelated copies.

### Move/undo can blank Design Studio

**Supported and localized.** Root-destructive controls remained reachable outside the
direct overlay, and recovery only called Undo. With empty history or a deterministic
render fault, clearing the boundary merely rendered the same crash again. Transform
replacement, stale occurrence rebinding, and uncoalesced histories increased the risk.

### Provider browser does not open

**Delivery failure supported; current source requires native acceptance.** The current
source has a dedicated provider WebView surface rather than navigating the primary app,
but the machine does not have the intended installed MSIX product. Its visible shortcut
launches the Python-owned Development host. Scenario fixtures can also contradict real
browser visibility, and command dispatch previously acknowledged bridge presence rather
than host acceptance. The real URL/modal/download path must be proven through the native
host after repair.

### The app is not a true installed Windows product

**Supported.** This PC has no matching Stockroom Appx/MSIX or Installed Apps registration.
The current shortcut launches Development. The intended WPF host, immutable worker,
MSIX/App Installer, and signed TUF feed exist in source and fixture tests, but production
publication is blocked by absent trusted publisher, certificate/password, and feed
configuration. Creating a self-signed production identity without owner authorization
would weaken the trust model and is not an acceptable fix.

## Critical Findings

1. Exact MPN re-add could overwrite an existing record. Separator/case-normalized
   variants could bypass the add guard even though catalogue lookup treated them as the
   same identity.
2. Editing the visible primary purchase URL could replace the full supplier-offer array,
   discarding secondary offers and metadata.
3. Duplicate badges were not invalidated after staged or passive add.
4. Design Studio's clicked occurrence was not the shared editing authority across all
   inspector surfaces.
5. Product-root hiding/geometry and empty-history crash recovery were not consistently
   guarded.
6. Second-launch acknowledgement could precede or indefinitely wait for foreground
   focus, and post-ready worker death could leave a dead visible host or lose final logs.
7. Release publication did not depend on the documented complete CI contract.

## Important Findings

- Add Parts ended after one component instead of retaining a durable session tray.
- Initial Add did not retain the same raw official evidence/source index as Refresh.
- A temporary failure in one optional official source could block a usable exact result
  from the other source.
- Altium-only local requirements omitted the shared 3D model.
- Manual CAD import could attach files directly instead of showing a mapping proposal
  and requiring Apply.
- Provider scenarios could force a browser visible in returned/canceled/completed states.
- Rotate could replace existing authored transforms; z-order could be visually inert;
  slider and pointer histories were not one gesture per undo.
- Runtime identity assignment could overwrite valid caller-generated identities.
- Design Studio exposed overlapping geometry systems, global Tab interception, small hit
  targets, incomplete overlay focus ownership, misleading custom-value controls, and a
  silently truncated icon search.
- Assets identified itself as Settings, and Build Now was only a filter rather than a
  build workflow.
- README/install guidance mixed legacy portable Python and intended installed WPF paths.
- Production dependency audit found fixed-version vulnerabilities in `aiohttp 3.14.1`,
  `cryptography 49.0.0`, and `pypdf 6.14.2`.

## Repository And Verification Health

- Current GitHub CI for the baseline commit was green, but its workflow was narrower than
  the documented Windows gate and omitted frontend/dist/package coverage.
- The fresh local canonical gate passed KiCad/workflow/Ruff/backend typing, 6,066 parallel
  backend tests, 59 serialized backend tests, 2,856 frontend tests, TypeScript, native
  host tests, and the frontend production build. It failed the final dist synchronization
  check because committed `app/frontend-dist` was stale.
- NPM production audit found no known vulnerability. After lock upgrades, the Python
  environment audit also finds no known vulnerability.
- Full-history secret scanning produced historical generic-key matches in captured vendor
  JSON/test data, but no finding was introduced at the baseline head. Current tracked
  matches are obvious test fixtures; no production credential was found in tracked source.
- Large ignored evidence/scratch directories exist. They are not product source, but they
  must be removed only after replacement evidence is retained and exact ownership is
  proven.

## Repair Order

1. Data-safe add and exact recovery.
2. Exact occurrence selection, root safety, transform/history semantics, and crash reset.
3. Durable Add Session and initial evidence completeness.
4. Provider modal/manual-import confirmation and real native browser outcomes.
5. Native activation/liveness, complete CI, dependencies, and truthful install/update docs.
6. UI simplification, Assets completion, and representative Light/Dark native screenshots.
7. Stable-source full gates, deterministic dist/package builds, repository cleanup, final
   review, commit, and non-force push.

## Evidence Boundary

Source and fixture evidence do not prove a signed installed product. Completion requires a
stable integrated tree, current-source native screenshots, real provider/modal behavior,
deterministic package evidence, and a legitimate signed release. If trusted signing/feed
inputs remain absent, the source repair can be merged while signed install/update
acceptance remains explicitly blocked.
