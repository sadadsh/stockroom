# Stockroom Visual Audit Backlog

This is the canonical, deduplicated visual and UX debt list. It is not a session
log. Every screenshot must be checked for its intended acceptance claim and then
critically reviewed for anything else visible. A new observation updates an
existing finding when possible instead of creating another near-duplicate.

## Review Contract

1. Record the exact capture layer, surface, theme, dimensions, and short SHA-256.
2. Separate a verification failure from a later design improvement.
3. Interrupt the active slice only when a finding makes its acceptance evidence
   false, hides data loss, blocks the primary task, or creates a safety risk.
4. Otherwise keep moving and route the observation here with a testable
   acceptance condition.
5. Close a visual finding only with before/after evidence in both themes and in
   the real Windows host when the host can affect the result.

Priorities are `P0` false or unsafe product truth, `P1` primary-workflow harm,
and `P2` meaningful fit, finish, or clarity debt.

## Acceptance Captures

### 2026-08-14 — Restrained ASTRYX Neutral Foundation

- Capture layer: current Vite source in headless installed Microsoft Edge using the shipped Design
  Studio `About Open` and `Search Initial` scenarios at 1,400 × 900. Native WebView2 remains a
  separate host-level acceptance boundary.
- Evidence: `work/Astryx Neutral About Dark.png`, SHA-256 `1e9bca56f76f`;
  `work/Astryx Neutral About Light.png`, SHA-256 `971a0cd6842e`;
  `work/Astryx Neutral Search Dark.png`, SHA-256 `bd2e24d7b004`;
  `work/Astryx Neutral Search Light.png`, SHA-256 `4bab39a975d1`; and
  `work/Astryx Neutral Measurements.json`, SHA-256 `e75d83432620`.
- Intended claim: ASTRYX is an incremental foundation, not a replacement shell. Its editable
  Neutral theme follows Stockroom's existing machine-owned dark/light preference, Segoe UI
  Variable typography, 2px engineering-tool geometry, authored grayscale surfaces, shadows, and
  status colors. About uses semantic external links with explicit new-tab announcements; Search
  uses platform-aware ASTRYX key hints. Existing navigation, layout, data rows, modals, and product
  primitives retain ownership.
- Acceptance result: browser pass in both themes. The document and rendered subtree identify the
  active `neutral` theme; all five captured key hints retain 4px inline padding, 2px corners, and
  the platform font, while both About links resolve to the correct theme text color and platform
  font. React 19 exposed and repaired one real batching dependency in `useJob`: terminal job state
  is now computed synchronously from the stream rather than as a side effect of a deferred React
  state updater. The complete Windows gate passed 239 WindowHost tests, 5 converter tests, 5,980
  parallel backend tests with 20 skipped, 51 serialized tests, 2,823 frontend tests, TypeScript,
  production build, and deterministic distribution synchronization. ASTRYX raises the current
  critical CSS from 77.28/15.64 kB raw/gzip to 230.75/42.29 kB and the main JavaScript plus split
  JSX runtime from 2,402.21/625.13 kB to 2,593.32/680.73 kB; this accepted foundation cost is
  recorded rather than hidden, and further component adoption must earn its payload and UX cost.

### 2026-08-14 — Graphite Palette, Line-Free Sourcing, Fitted CAD, And Settings About

- Capture layer: current Vite source in headless installed Microsoft Edge using the shipped Design
  Studio `About Open` and `Full Data` scenarios. This exercises the real production components and
  CSS at 1,400 × 900 and 1,100 × 650 without taking foreground focus; native WebView2 remains a
  separate host-level acceptance boundary.
- Evidence: `work/Graphite Settings Dark.png`, SHA-256 `9f09839d166b`;
  `work/Graphite Settings Light.png`, SHA-256 `601d183bad04`;
  `work/CAD Fixture Corrected Light.png`, SHA-256 `ee616e88afef`;
  `work/CAD Fixture Corrected Dark Compact.png`, SHA-256 `3ad4ad83a1b0`; and
  `work/Graphite UI Audit Measurements.json`, SHA-256 `a5ca176c0731`.
  The former `work/Line Free Sourcing Light.png`, `work/Fitted CAD Light Compact.png`, and
  `work/Fitted CAD Dark Compact.png` are rejected for CAD-fidelity review: their visual scenario
  contradicted its own LM358DR identity with a two-pin rectangular symbol and a two-pad pseudo-
  footprint.
- Intended claim: the app uses a deeper graphite dark ladder and a soft near-white neutral light
  ladder; Sourcing contains no structural rules and presents every visible price tier as a pill;
  the CAD Assets body never scrolls and instead divides available height across all three previews;
  and About is a permanent Settings card rather than a rail modal.
- Acceptance result: browser pass in both themes and both measured heights. The populated sourcing
  scenario exposed four price-break pills and zero ruled descendants. At 1,400 × 900 the CAD body
  measured `697/697` client/scroll height with three 227/227/226 px modules; at 1,100 × 650 it
  measured `447/447` with 113/113/112 px modules. Computed CAD overflow remained `hidden` in both.
  About retained the authoritative version, stale-build note path, author, LinkedIn, and GitHub.
  The former `rail.about` Design Studio target remains as a compatibility wrapper inside the moved
  Settings content, so personal design documents do not become invalid. Owner review correctly
  rejected the original CAD drawing evidence even though its layout measurements passed. The
  repaired scenario now carries all eight LM358 terminals, two recognizable amplifier units, and
  an eight-pad SOIC land pattern with silkscreen, fabrication, courtyard, and pin-one geometry; a
  regression requires the scenario's identity, symbol, and footprint terminal counts to agree.

### 2026-08-14 — Full UI Scheme Structural Audit And Flat Settings

- Audit layer: complete frontend source review across tokens, primitives, route shells, settings,
  modals, state surfaces, component workspaces, STM, focus, and Design Studio scenario contracts.
  This is structural and automated evidence; native dark/light captures remain required.
- Repaired scheme drift: one `--c-scrim` owns every modal backdrop; `--c-focus` owns real and
  simulated keyboard focus; destructive button labels use a theme-specific contrast token; warning
  marks use a triangle rather than an indistinguishable neutral dot; stale `panel`, `positive`,
  `accent`, and `err-soft` utilities are removed; provider, warning, and query states use shared
  primitives; Add Part, Altium, confirmation, and Bench dialogs converge on the shared modal header,
  focus trap, stacking, and recovery contracts; and STM uses the docked route header.
- Settings result: pass at the structural layer. Category navigation and conditional group mounting
  are removed. Machine Readiness and every capability card share one page-owned vertical scroller;
  all 15 cards remain mounted in reading order, with two columns only when the container has room.
  Readiness and update shortcuts scroll to and focus the exact owning card. Design Studio scenarios
  scroll to their target card without hiding the others, and pinned modal scenarios can be closed.
- Regression evidence: the complete frontend passes 2,824 tests; TypeScript passes. New source
  guards reject selection-accent focus, retired semantic utilities, per-modal black opacities, and
  sub-10 px interface text. Contrast tests hold destructive labels at 4.5:1 in both themes, and the
  contextual token inspector resolves variants and opacity modifiers for every editable color.
- Remaining acceptance: inspect the flat page and modal family in real Windows/WebView2 at 960 × 640
  and 1,400 × 900, dark and light, using keyboard-only traversal and high-DPI scaling. Measure first
  Settings paint on a large catalog before deciding whether below-fold bodies need viewport deferral.

### 2026-08-14 — Compact CAD Preview Cleanup

- Capture layer: current source in the real Windows pywebview/WebView2 Development host, captured
  with background `PrintWindow` so verification did not take foreground focus.
- Evidence: `work/Model Preview Cleanup Dark.png`, 1,400 × 900, SHA-256 `5b68e394582f`.
  The intermediate light capture `81e6f76876e9` was rejected because the model used a distinct
  background rather than the product's shared technical sheet.
- Intended claim: the mini 3D preview begins with the component alone rather than a PCB slab; the
  footprint does not add a decorative pad-one ring over source geometry; and Model, Footprint, and
  Schematic use the same theme-aware technical-sheet background.
- Acceptance result: dark native pass and light structural pass. The mini preview's PCB control
  remains available but begins off, while the full inspector retains board context. A regression
  mounts all three live preview implementations and requires `bg-technical` on every canvas; token
  parity proves that shared surface flips with the theme. A replacement native light capture remains
  deferred while the owner uses the foreground desktop, because verification must not interrupt it.

### 2026-08-14 — Price-First Sourcing Information Architecture

- Capture layer: current source in the real Windows pywebview/WebView2 Development host with the
  live `ADG714BRUZ-REEL` dossier and all 19 retained price breaks.
- Evidence: `work/Sourcing IA Dark Final.png`, 1,400 × 900, SHA-256 `cce8bf23001f`;
  `work/Sourcing IA Light Final.png`, 1,400 × 900, SHA-256 `c723da7185d3`;
  `work/Sourcing IA Disclosures Dark Final.png`, 1,400 × 900, SHA-256 `053e11920fd0`; and
  `work/Sourcing IA Disclosures Light Final.png`, 1,400 × 900, SHA-256 `51ef95582a5b`.
- Intended claim: provider and offer identity plus every price tier are the only sourcing facts open
  by default. Stock, lifecycle, offer metadata, official payloads, documents, alternatives, and
  provenance remain complete but begin behind concise category disclosures. Blank-section recovery
  appears only in Design Studio.
- Acceptance result: pass. Mouser and three distinct DigiKey package offers retain all 19 tiers in
  normalized provider order. Each offer has one quiet **Details** disclosure; Stock and Status,
  Official Data, Documents, Alternatives when present, and Sources and Timeline each occupy one
  closed row. The repeated per-document `Document Details` rows and per-alternative equivalence
  warnings are gone; document metadata is flat inside the one Documents disclosure and the
  alternatives warning is stated once for the group. Both themes preserve the same density,
  alignment, scroll ownership, and exhaustive Full Sourcing Record path.

### 2026-08-14 — Navigation Rail State And Alignment

- Capture layer: current source in the real Windows pywebview/WebView2 Development host with the
  owner's applied Design Studio document still setting `rail.root` to a narrow inline width.
- Evidence: `work/Nav Rail Expanded Aligned.png`, 1,400 × 900, SHA-256 `b7b929df74b7`;
  `work/Nav Rail Collapsed Aligned.png`, 1,400 × 900, SHA-256 `49a3a4bc9019`;
  `work/Nav Rail Expanded Aligned Light.png`, 1,400 × 900, SHA-256 `90daecdc5689`; and
  `work/Nav Rail Collapsed Aligned Light.png`, 1,400 × 900, SHA-256 `1ff220556c7f`.
- Intended claim: the explicit toggle owns the rail's 190 px open and 52 px closed geometry even
  when personal styling supplies an inline width; expanded labels remain single-line; compact icons,
  utilities, and the expand control share one centerline; and workspace content reflows without an
  overlay in both themes.
- Acceptance result: pass. The saved 56 px width had previously exposed expanded labels inside the
  compact strip. Structural important widths now outrank that styling. Removing the compact band's
  hidden brand from flex flow and making the 35 px glyph wrapper non-shrinking moved the expand
  control from x=28 to the common x=33 centerline measured for the destination and utility controls.

### 2026-08-14 — True In-Workspace Provider Browser

- Capture layer: current source in the real Windows pywebview/WebView2 Development host, using the
  isolated Development configuration and the `ADG714BRUZ-REEL` component.
- Evidence: `work/True Embedded Provider Maximized.png`, 1,936 × 1,048, SHA-256
  `6f54f6c2232f`; `work/True Embedded Provider Second Provider.png`, 1,936 × 1,048, SHA-256
  `3eb18c1ebe1e`; and `work/True Embedded Provider Light Theme.png`, 1,936 × 1,048, SHA-256
  `e19e81d64eda`.
- Intended claim: selecting a provider remains inert; **Open Provider** creates the provider route;
  DigiKey and Ultra Librarian render inside the large Manage Models pane rather than in a floating
  window; the embedded WebView follows maximization; and Stockroom chrome remains usable in both
  themes.
- Acceptance result: pass after replacing the owned top-level overlay with a true child HWND. The
  failed overlay exposed only a white form because its WebView2 compositor was not in Stockroom's
  client tree. The corrected captures show real provider documents, exact component identity,
  Stockroom-owned Back/Forward/Reload/address/close controls, and provider-native scrolling. Ultra
  Librarian's advertising and horizontal overflow remain provider-owned presentation covered by
  VA-045; neither obscures Stockroom's provider controls.

### 2026-08-12 — Manage Models Browser Workspace

- Capture layer: current production frontend plus the real local Stockroom service through locked
  Chromium and a task-owned configuration. The final all-scenario run passed 190 scenarios in dark
  and light at 1,366 x 872, 1,600 x 1,000, and 1,920 x 1,200, including restart persistence and
  zero fixture product effects. A focused follow-up retained the five-provider Manage Models frame
  at `.work plans/sdd/2026-08-12-manage-models-focused/browser/`.
- Intended claim: **CAD Models > Manage Models** stays inside the open component, shows all five
  representative providers with complete sets first, leaves partial and unavailable rows honest,
  and keeps one component-bound browser viewport without any global provider tab.
- Visual result: dark `8d55030b3476` and light `1617ed1947ac` at 1,366 x 872 show two complete,
  two partial, and one unavailable provider simultaneously. The provider list remains readable,
  browser chrome stays inside the component, and identity/status survive the workspace change.
  The sparse first capture exposed an underrepresentative one-provider fixture; the fixture was
  expanded before these accepted frames.
- Windows boundary: native host unit coverage passes, but this task's isolated Computer Use run was
  interrupted before interaction. Exact current-source WebView2 overlay alignment, provider-account
  gates, and live automatic/manual downloads remain native/provider acceptance, not browser proof.

### 2026-08-11 — Exhaustive Design Studio Browser Matrix

- Capture layer: the production frontend and real local Stockroom service through locked Chromium,
  using a task-owned configuration. The production registry emitted 190 cases; each case was
  captured in dark and light themes at 1,366 x 872, 1,600 x 1,000, and 1,920 x 1,200, for 1,140
  scenario frames. Representative click-through and autosave-after-restart frames are retained
  beside the matrix under
  `.work plans/sdd/2026-08-11-in-app-design-studio/task-15-evidence/browser-source-final/browser/`.
- Intended claim: every production scenario exposes its case identity and registered target;
  preview fixtures produce no external request or product mutation; Browse, Inspect, Arrange,
  inspector domains, collapsed rails, dark/light contrast, and restart persistence remain usable
  throughout the supported desktop sizes.
- Acceptance result: functional pass at the browser-rendered product layer. The audit applied the
  existing Stockroom hierarchy and density contract while checking typography hierarchy, spacing
  and alignment, control-state affordances, loading/empty/error states, contrast, and icon
  consistency. Sequential scenario testing exposed and corrected stale capture, component-filter,
  workspace-selection, and STM-tab state. Existing dense-settings and muted-helper-text findings
  continue to own their established scopes; VA-052 records one new Studio-specific framing issue.
- Windows boundary: a Computer Use inspection found one real Stockroom WebView2 window, but its
  process belonged to the separate `Catalog Workspace Convergence` worktree and exposed no Design
  Studio entry. The task did not close, modify, or relabel that owner-controlled instance. A package
  build for this worktree refused safely because that instance owned coordinator authority, so
  current-source packaged entry/exit, editor modes, persistence, refusal, and promotion states are
  still required before calling the native layer accepted.

### 2026-08-03 — Source-Backed Dev Mode

- Capture layer: Computer Use against the current source in the real Windows pywebview/WebView2
  host, with a disposable configuration and a Git clone of the real seven-component Stockroom
  library. The original library was not mutated. Captures were inspected live at 1,386 × 900 and
  were not retained as standalone image files.
- Surfaces: Components, MAX17608ATC+ Readiness, the Design panel, the complete 283-item catalogue,
  and the Category control in dark and light themes.
- Intended claim: every registered element remains selectable; all five editing facets and the
  source/publish footer remain reachable; a real Category dropdown changes to Segmented Control
  without leaving Stockroom or changing its selected value.
- Acceptance result: pass after correction. The first audit found a P1 flex-layout defect: an
  expanded catalogue could consume the panel height and hide the source/publish footer. The panel
  header, toolbar, and footer are now non-shrinking, the catalogue scrolls independently, and the
  bounded confirmation rail can scroll. Retest kept the footer visible, selected
  `detail.category-control` from the filtered catalogue, and exposed the working Behavior presets.
  A second audit found that ref-backed history changed but the memoized context did not refresh,
  leaving Undo disabled after a live edit; the history revision is now part of the context contract
  and has a direct behavior-edit Undo/Redo regression test.

### 2026-08-03 — Exact GitHub 0.6.0 First Launch

- Capture layer: Computer Use against the exact 141,237,598-byte `v0.6.0` GitHub EXE with
  SHA-256 `55bc6179dec5`, downloaded again through GitHub and run with an empty disposable config.
- Intended claim: the published executable reaches visible first-run onboarding on Windows without
  relying on the developer source checkout.
- Acceptance result: functional pass with a P1 startup-experience failure. The exact asset did
  eventually reach the centered `Set Up Your Components` onboarding screen and its local default
  repository path, but it showed no visible window while the outer executable unpacked and started
  the continuous Python runtime. Multiple nested Stockroom/uv/Python processes existed before any
  feedback. On a fresh laptop this looks identical to a failed launch and encourages duplicate
  starts; VA-051 tracks the required early splash/progress and explicit runtime failure surface.

### 2026-08-01 — Current Capture Reliability Source Host

- Capture layer: Computer Use against the exact current source in the real
  pywebview/WebView2 host, using task-owned configuration and fixture library.
- Surfaces: empty Components and Add Parts in dark and light themes. Every
  point-in-time Windows capture was 1,386 × 872; Computer Use did not retain
  standalone image files or stable image digests.
- Intended claim: the current frontend distribution boots in a native WebView2
  window, Add Parts opens and closes through accessible controls, the saved
  intake draft survives the modal lifecycle, and both themes retain their
  intended hierarchy without overflow or compositor artifacts.
- Acceptance result: pass. The source host, loopback backend, and WebView2
  renderer were healthy; the detached audit launch initially left Stockroom
  behind the foreground apps, and activating its existing taskbar window
  surfaced it without a relaunch. A first-frame capture appeared to show page
  content through the bulk-import textarea, but a settled follow-up proved this
  was only the modal's intentional opacity transition; the opaque popover and
  field rendered correctly in both themes. No new product finding was opened.

### 2026-08-01 — Embedded Provider Surface

- Capture layer: Computer Use against the isolated self-contained native
  `Stockroom.WindowHost.exe`, with the production WPF/WebView2 provider surface
  and a task-owned diagnostic endpoint.
- Evidence:
  `work/Embedded Provider Visual Audit/Embedded Ultra Librarian Provider.jpg`,
  1,266 × 833, SHA-256 `18289af5c958`;
  `work/Embedded Provider Visual Audit/Returned To Stockroom.jpg`,
  1,266 × 833, SHA-256 `0a74146204c8`; and
  `work/Native Window Host/Embedded Provider Smoke 20260801-174945/Smoke Evidence.json`.
- Intended claim: an exact provider page opens inside the Stockroom window and
  `Return To Stockroom` restores the main app without opening a separate browser.
  The provider WebView was reachable over a private CDP endpoint when this audit
  ran; that endpoint has since been removed and no build opens one.
- Acceptance result: pass. The first live capture exposed an HWND airspace
  defect that painted the main WebView above the provider WebView; the native
  host now collapses the inactive WebView, and the corrected capture visibly
  contains Ultra Librarian plus Stockroom-owned chrome. The return control was
  activated through the native accessibility tree and restored Components.
  `diagnostic endpoint absent` in the returned frame is expected from this
  deliberately isolated smoke service, not a packaged-app result. Super-critical
  critique: Ultra Librarian's hero copy clips at the left edge at this viewport;
  VA-045 tracks provider-responsive mitigation without invalidating the visible
  login, navigation, search, or Stockroom return controls.

### 2026-08-01 — Independent Library Repository Settings

- Capture layer: development tool in-app browser against the isolated FastAPI service and
  current production frontend bundle.
- Evidence:
  `work/Library Repository Audit/Library Repositories Dark 1280x720.png`,
  1,280 × 720, SHA-256 `f7adcab94750`; and
  `work/Library Repository Audit/Library Repositories Light 1280x720.png`,
  1,280 × 720, SHA-256 `96356f955273`.
- Intended claim: library choice is repository choice; the active and available
  repositories, separate working-copy state, library-only synchronization,
  per-user Git Credential Manager identity, and no-PAT boundary are visible in
  both themes without horizontal overflow.
- Acceptance result: pass at the browser-rendered product layer. Document width
  remained exactly 1,280/1,280 px in light theme. The first dark capture exposed
  the retired `Profile: Stockroom` footer control; the source and tests were
  corrected to the non-interactive `Library: Stockroom Library` repository fact
  before these authority captures. Super-critical critique: at 720 px tall the
  GitHub Access panel begins below the bounded settings viewport, so users must
  scroll to inspect account details; muted helper text and the dense two-column
  Settings hierarchy remain covered by VA-014 and VA-027 rather than opening a
  duplicate finding. Real packaged WebView2/DPI proof remains outstanding.

### 2026-07-29 — Windows App Identity Asset Audit

- Capture layer: deterministic canonical asset contact sheet.
- Evidence:
  `work/Windows App Identity Audit/Canonical Icon Sizes And Shell Variants.png`,
  1,400 × 1,050, SHA-256 `e643e9f00973`.
- Surfaces: tiled Stockroom mark at 512, 256, 128, 96, 80, 72, 64, 60,
  48, 40, 36, 32, 30, 24, 20, and 16 px; transparent dark-surface and
  light-surface unplated shell variants at 96, 64, 48, 32, 24, and 16 px.
- Intended claim: the approved mirrored `S` is the box's exact top-panel joint,
  all cube edges and junctions connect at every generated Windows size, the
  mark remains grayscale, and shell variants preserve contrast without a
  platform-added plate.
- Acceptance result: pass at the asset layer. The box silhouette remains clear
  at 16 px; the `S` becomes secondary detail at that size instead of breaking
  the outline. Real EXE/titlebar/taskbar/Start/Apps inspection remains required
  after package construction.

### 2026-07-29 — Served Progress HTML Audit

- Capture layer: development tool in-app browser through the private Tailscale HTTPS route.
- Evidence: `work/Progress HTML Visual Audit/Desktop Current State.png`,
  1,265 × 712, SHA-256 `b0d78022cbb5`.
- Intended claim: the generated punch-list page is reachable, identifies
  product scope and current work before historical counters, and exposes
  evidence and blockers without relying on an aggregate readiness percentage.
- Acceptance result: functional pass. The follow-up DOM verification reports
  `document.characterSet = UTF-8`, no mojibake, and correctly marks Windows
  Package And Release Lifecycle as Active after its internal hot-adoption gap
  was found. VA-044 records the non-blocking scanability debt visible in the
  capture.

### 2026-07-30 — Served Progress HTML Scanability Follow-Up

- Capture layer: Chrome Browser through the private Tailscale HTTPS route, with
  deterministic responsive and preferred-colour-scheme overrides.
- Before evidence:
  `work/Progress HTML Visual Audit/Desktop Current State.png`, 1,265 × 712,
  SHA-256 `b0d78022cbb5`.
- After evidence:
  `work/Progress HTML Visual Audit/Desktop Dark Scanability After.png`,
  1,250 × 704, SHA-256 `91ded8f10580`;
  `Desktop Light Scanability After.png`, 1,250 × 704, SHA-256
  `91b71996b0ec`; `Phone Dark Scanability After.png`, 375 × 812, SHA-256
  `3d4f5650125e`; and `Phone Light Scanability After.png`, 375 × 812,
  SHA-256 `55f3705f5a4f`.
- Intended claim: each current-work card leads with one bounded state sentence,
  while its exact evidence, blocker, and next action remain in one explicit
  native disclosure. Long status prose uses a readable one-column measure at
  desktop and phone widths.
- Acceptance result: pass in both themes. The desktop page reports one 814 px
  workstream column; the phone page reports one 325 px column. All six state
  sentences, six disclosures, 11 owner-outcome gates, and 20 engineering items
  remain in the DOM. The first disclosure opened with Enter, closed with Space,
  retained focus on `SUMMARY`, and exposed the complete evidence string. With
  that long SHA-bearing evidence expanded, phone document/client width remained
  375/375 px; desktop document/client width remained 1,250/1,250 px.
  `document.characterSet` remains `UTF-8`. No content was removed and no new
  visual finding was opened.

### 2026-07-29 — Exact-Current Native Library UX Audit

- Capture layer: current source revision in the real pywebview/WebView2 host,
  with task-owned configuration, service state, and library copies. Durable
  frames are WebView2 CDP captures; the native titlebar and approved box mark
  were also observed through Computer Use.
- Evidence:
  `work/Native Current Acceptance/Screenshots/Empty Library Dark.png`
  (`d95161202089`), `Empty Library Light.png` (`8c6de370703f`),
  `Add Part Dark.png` (`68a9368a0e1a`), `Add Part Light.png`
  (`27b0b17c4f58`), `Dual EDA Readiness Dark.png` (`69e5844ff78e`),
  `Dual EDA Readiness Light.png` (`f09f10cbf417`),
  `Single Value Facet Dark.png` (`b3b3f66b5ad0`), and
  `Single Value Facet Light.png` (`62a32dbd9549`). Every frame is
  1,384 × 861.
- Intended claims: an empty library has one working intake state; Add Parts
  describes one shared KiCad + Altium + STEP package; local files cannot imply
  verified CAD readiness; and a degenerate numeric facet is one static value,
  not a fake range.
- Acceptance result: pass in both themes. Empty Components has one
  `No Components Yet` state, one working `Add Parts` action, and no impossible
  selection instruction. The populated canary visibly reports
  `KiCad Unverified · Altium Unverified` despite linked Symbol, Footprint, and
  3D files. The one-value `channels` fixture renders `Only value 6`, exposes no
  range control, and keeps the value in the result column. Root width/height
  equals client width/height at 1,384 × 861 and the WebView console is empty.
- Audit: the first native boot found and corrected a real syntax regression in
  the shared passive-template path. The network audit then found an implicit
  `/favicon.ico` 404; the deterministic approved icon is now generated into
  the frontend public assets as well as the host, and a fresh WebView reports
  no response with status 400 or higher. Existing VA-002, VA-004, and VA-014
  still describe the visible automation, whitespace, and low-emphasis-text
  debt; no duplicate finding was opened.

### 2026-07-29 — Altium Fresh-Session Placement Proof

- Capture layer: Computer Use point-in-time Windows capture.
- Surfaces: `Home Page`, `Sheet1.SchDoc`, and
  `S1M-Placed-Through-Native-UI.SchDoc` in Altium Designer Professional
  26.8.1, returned window id `75956996`.
- Theme and dimensions: Altium dark theme. Every main-window capture is
  1,176 × 747. Material owned-window captures are: initial Messages
  814 × 443, SCH List 450 × 366, Save As 946 × 533, and missing-path warning
  558 × 158. Computer Use supplies opaque, point-in-time capture ids rather
  than stable image bytes, so these captures have no file digest.
- Capture sequence: initial Home with Messages; Components opened on the
  built-in library; file-library selector open; exact isolated
  `Stockroom.DbLib - Parts` selected with its one `S1M` row; File and New
  menus; blank schematic with SCH List; blank schematic with the Components
  panel; active S1M placement; unrelated PowerToys error overlay; placed S1M
  selected with native Properties; Save As; entered proof path; missing-path
  warning; and the final saved native schematic. Repeated observations after
  a state-changing action were each audited even when they confirmed the same
  finding.
- Intended claim: Stockroom installed the isolated DbLib without manual Altium
  setup, the fresh native Components panel listed exact `S1M`, native
  placement produced a component carrying `Design Item ID = S1M` and
  `Footprint = DIOM5227X270N`, and native save/readback preserved it.
- Acceptance result: pass. Independent binary readback of the saved
  17,920-byte SchDoc (SHA-256 `3f383d1f5e02`) found two identical placements;
  both carry MPN `S1M`, Stockroom ID `webview-embed-s1m`, and footprint
  `DIOM5227X270N`. The two instances are a proof-driving artifact: the row was
  double-clicked and the active placement was clicked once. Cardinality was
  not inferred as a product behavior.
- Audit: the empty Messages and SCH List panels consumed large portions of the
  canvas, but both are Altium-owned chrome. The PowerToys error was an
  unrelated desktop-composition failure and was dismissed without changing
  Altium or Stockroom. The first Save As attempt correctly failed because the
  isolated evidence directory did not yet exist; the directory was created
  and native save then completed. The material Stockroom finding is the
  selector's two indistinguishable `Stockroom.DbLib - Parts` rows, tracked as
  VA-033.

## Open Findings

| ID | Priority | Surfaces | Finding | Acceptance condition |
| --- | --- | --- | --- | --- |
| VA-001 | P0 | Components | Source correction and exact-current native verification have landed: the compact state names KiCad and Altium separately and fails closed to `Unverified`; a canary with linked Symbol, Footprint, and 3D files remains `KiCad Unverified · Altium Unverified` in real WebView2 in both themes. The remaining proof is the positive completed state against immutable dual-EDA inspection evidence. | Completion is impossible until immutable artifacts and both KiCad and Altium bindings pass digest-bound inspection; the UI names both results and the blocking evidence. |
| VA-002 | P1 | Components, empty state | The primary path is still manual `Add Parts`; there is no visible durable intake, batch progress, fallback, recovery, or compact decision path. | One control accepts 1–1,000 identities, persists immediately, and shows incremental stage, retry/fallback, resume, and only genuinely blocked decisions without asking for field entry. |
| VA-004 | P1 | Components, Search | Fixed panes and very wide bands leave most of the window empty while useful content is compressed into the left/top. Search query occupies less than half its bar and Components reserves a full empty Sourcing column. Settings was removed from this finding by VA-027. | Layout reallocates space according to content and window width, keeps the focal workflow dominant, and has explicit useful empty states at 1,024, 1,384, and 1,600 CSS pixels. |
| VA-006 | P2 | Components, Search, Settings | The system audit removed undefined semantic utilities, unified scrims, focus, warning marks, destructive contrast, route headers, and the main modal/state primitives. Remaining drift is narrower: several older modal bodies and repeatable query states still hand-build spacing or prose, while nested bordered cards, boxed values, and repeated uppercase micro-labels remain on dense legacy surfaces. | Every modal and repeatable query state composes the shared frame/state vocabulary; each region has one elevation level; non-informative borders/boxes are removed; labels use the approved quiet hierarchy and casing. |
| VA-007 | P2 | Components | One selected entry is named three different ways: `100nF 0402`, `100 nF Capacitor`, and `100 nF 16V X7R 0402`. | Canonical display name and supporting description have defined roles and remain consistent across list, header, search, and EDA projections. |
| VA-008 | P2 | Components | Warning triangles sit at the far edge of rows without an adjacent reason, severity, or next system action. | Every warning exposes a concise reason and what Stockroom is doing next; keyboard and pointer users can reach the same explanation. |
| VA-010 | P2 | Search | The results table spends large horizontal spans on missing values and repeats result counts while the high-value identity/evidence fields are weak. | Columns prioritize exact manufacturer/MPN, match confidence/evidence, lifecycle, package, and dual-EDA readiness; empty columns collapse or move behind details. |
| VA-012 | P2 | Components | The open-part tabs now read `Overview`, `Representations`, `Sources`, and `Activity`, and a cross-EDA asset matrix replaces Handoff as the route's lead. Remaining Library/Add/health navigation still exposes legacy/manual implementation boundaries. | Navigation is organized around entry truth, evidence, dual-EDA readiness, and activity/decisions; internal stages remain observable without becoming manual chores. |
| VA-013 | P2 | Components | An empty Sourcing pane permanently consumes a major column and offers only a remote `Refresh` action. | Empty sourcing collapses into evidence/activity or shows active automatic acquisition and fallback; it does not reserve a full pane for no data. |
| VA-014 | P2 | Native Components, Native Settings | The structural audit removed the remaining literal 9 px interface label and added a source guard against sub-10 px text; the compact semantic scale now owns source typography. Native captures still show faint helper tiers, so supported Windows scale-factor and real-host contrast confidence remains open rather than solved by making text larger. | One compact semantic token scale owns all interface text with no one-off pixel sizes; the hierarchy remains legible at supported Windows scale factors and passes contrast checks in both themes. |
| VA-017 | P1 | Components, Symbol and Footprint previews | Owner correction supersedes the one-stage experiment: source again shows the interactive 3D hero plus separate, simultaneous Symbol and Footprint viewers. Each opens deep inspection directly on its own representation. Native dark/light and narrow-width visual proof remains pending. | Symbol, Footprint, and 3D remain simultaneously visible as separate representations; each exposes appropriate overlays, checks, comparison, and contextual actions with keyboard parity. |
| VA-018 | P1 | Components | Consequential actions follow no stable placement rule: Add Parts, Refresh, row stars, asset eyes, CAD Complete, pane chevrons, top workflow tabs, and the lone bottom delete icon are distributed by implementation location rather than action scope. | Component-wide, projection, field, background-job, candidate, and destructive actions each follow the placement rules in `Component Inspection Workspace.md`; no unlabeled icon is the sole explanation of a consequential action. |
| VA-019 | P1 | Components, 3D preview | Source restoration returns inline orbit/zoom, Model/Pads/PCB, Auto Rotate, and a settings popover for Isometric/Top/Front, Fit, Source Color/Studio/X-Ray, and Auto/Source/Model placement while retaining current renderer safety and keyboard Fit. Native interaction proof remains pending; issues still do not focus their relevant geometry. | Every shipped inspection control is reachable in the inline 3D hero and expanded inspector; issues focus relevant geometry and renderer state remains truthful across component changes. |
| VA-032 | P1 | Native acquisition, all surfaces | A managed `chrome-headless-shell.exe` launch raised a Windows Firewall public/private-network prompt over Stockroom even though acquisition needs outbound HTTPS and local process transport, not inbound LAN access. The security dialog obscured and disabled the primary app until dismissed. | Acquisition does not request inbound public/private firewall access. Any unavoidable browser/runtime setup happens only after an explicit acquisition action, explains why, and never presents a raw publisher-unknown system prompt as part of normal app startup. |
| VA-033 | P1 | Altium Components, profile switching | Two Stockroom-managed DbLib paths appear as identical `Stockroom.DbLib - Parts` choices, so the active profile cannot be identified from Altium's selector and a profile switch can leave a stale library selectable. | Automatic convergence keeps exactly one Stockroom-receipted DbLib installed. It installs and verifies the new active target before removing only obsolete receipt-owned targets, never touches arbitrary user libraries, and fails closed without abandoning the last working target. The isolated native embed acceptance run then removed the exact receipted proof DbLib and the exact prior UL-canary DbLib; Altium's measured final list contains only its built-in Simulation Generic Components library and zero Stockroom test registrations. |
| VA-043 | P1 | Live DigiKey assisted capture and security handoff | The redesigned closed-shadow HUD is verified in isolated Chromium at desktop and 320 × 600 bounds, but the new compact route, Session Memory, sticky outcomes, and paused-gate presentation have not yet been re-captured on DigiKey's live model, cookie, consent, sign-in, and guest-limit surfaces. | A visible managed DigiKey run captures assisted and paused states in light and dark at supported Windows scale factors. Exact provider/author/MPN, required formats, receipt count, Session Memory, Resume/Use Another/Close, collapse/move/focus, and the one human gate remain readable without obscuring the active provider control. Session Memory appears only with DigiKey's isolated persistent profile. |
| VA-045 | P2 | Embedded provider surface | Ultra Librarian's desktop hero content begins outside the left edge at a 1,266 × 833 native window even though its navigation, login, search, and Stockroom return controls remain reachable. This is provider-owned responsive behavior exposed by the new embedded viewport. | Provider-specific presentation mitigation is measured rather than guessed: supported provider pages retain their actionable controls and exact component identity at 1,024, 1,266, and 1,384 px Windows widths without Stockroom applying a global zoom that breaks another provider. |
| VA-046 | P0 | Projects, Altium project selection | Selecting the saved `WiFi_miniPCIe` project launched `X2.EXE` immediately through a generated `StockroomBoardScenes` script even though the user did not choose Render PCB or Open In Altium Designer. The UI simultaneously claimed native previews were paused. | Loading or selecting an Altium project is read-only and never launches Altium. Only an explicit Render/Open action may acquire the native-editor seat; the UI names that consequence before invocation and a regression proves selection alone creates no `X2.EXE` or helper command. |
| VA-047 | P1 | Projects, Activity | A missing remote ref replaced the complete Activity workbench with the raw backend string `remote ref is unavailable: refs/remotes/origin/branch/projects-library-grammar`. There was no local-work context, recovery action, or usable review/session surface. | Missing or stale remotes degrade to the normal Local Only/Connect Remote state; Activity remains usable for local work and provides one scoped recovery action without exposing raw ref plumbing as the whole page. |
| VA-048 | P1 | STM Viewer first run | Building the STM index without a configured CubeMX source ends with an implementation-facing instruction to set `stm_cubemx_source` via `PATCH /api/settings` or `STM32_CUBEMX`. The user cannot perform that recovery anywhere in the visible app. | The empty state discovers a safe local CubeMX source or opens one native folder picker, saves the choice in Settings, retries in place, and keeps API/environment details behind diagnostics. |
| VA-050 | P1 | Components, Complete Part | The visible 1,386 × 893 dark WebView2 Proof 7 frame exposed internal requirement keys verbatim in the lead state: `required projected references are absent: kicad_symbol, kicad_footprint, kicad_model, altium_symbol, altium_footprint`. This competes with the otherwise plain-language KiCad/Shared/Altium checklist and makes a normal missing-files state read like a backend exception. | The lead state says which user-facing files are needed without schema keys; exact requirement keys remain available only in diagnostics/evidence. |
| VA-051 | P1 | Windows first launch | The browser-downloaded 0.6.0 EXE can remain completely invisible while it unpacks and starts the continuous runtime. A fresh-machine acquisition or runtime failure has no user-facing error, and duplicate launches are easy. | Show a branded window or splash within two seconds, report each bounded bootstrap phase, make one launch authoritative, and surface an actionable failure instead of remaining invisible. Verify from a browser-downloaded asset on a clean Windows machine. |
| VA-051 | P1 | Components, Representations, CAD Variants | The real TPS62130RGTR source-host readback shows `33 Retained`, including 17 KiCad and 16 Altium Ultra Librarian variants, so repeated acquisition turns the primary inspection surface into a long wall of visually identical `Preferred` cards. The active all-five-role pair is correct, but history overwhelms comparison and makes a successful one-click workflow look unfinished. | Identical source-receipt evidence reuses one retained same-download pair regardless of nondeterministic generated timestamps. Existing duplicates are grouped or collapsed without deleting immutable originals; the active pair and genuinely different provider/geometry variants remain immediately comparable at 1,024 and 1,384 px widths. |
## Resolved Findings

| ID | Priority | Surfaces | Finding | Resolution evidence |
| --- | --- | --- | --- | --- |
| VA-049 | P2 | Settings category navigation | Category navigation and its inherited-scroll failure no longer exist. Settings is one continuous page with one scroll owner; all capability cards stay mounted, and readiness shortcuts move to the exact card without replacing the page DOM. Focus/scroll and all-card regressions pass; real-host dark/light acceptance remains recorded above. |
| VA-052 | P2 | Design Studio preview canvas | At the 1,920 px preset and 100% zoom, the virtual product viewport was wider than the remaining canvas after the scenario rail and inspector, with no persistent framing cue. | Added Fit, a visible pan cue, and bounded keyboard-arrow and pointer-drag panning. The production browser matrix proves the exact wide-canvas state and both input paths while all 190 scenarios pass at 1,366, 1,600, and 1,920 px in both themes. This is browser-rendered proof; native packaged-host acceptance remains a separate boundary. |
| VA-003 | P1 | Search | An equal minimum/maximum rendered a slider with duplicate endpoints and implied a selectable range that did not exist. | Equal bounds now render one static `Only value` fact and no range input; invalid bounds disappear. Exact-current WebView2 frames in both themes show `channels · Only value · 6`, one result value, zero slider/tick controls, no overflow, and an empty console. |
| VA-005 | P1 | Components empty state | An empty library rendered competing `No Components Yet` and `Select a part` instructions across separate panes, even though no selection was possible. | The current source host replaces both panes with one centered intake state and one working `Add Parts` action. Exact-current WebView2 frames in both themes contain no selection instruction; activating Add Parts opens the shared network intake modal. |
| VA-015 | P1 | Native navigation rail, all destinations | In auto-collapsed mode, `focus-within` treated a pointer click as keyboard intent and held the 190 px peek open over a 52 px layout slot. It covered the first 138 px of Components, STM Viewer, and Settings until another click moved focus. | Replaced the width and label reveal with `:has(:focus-visible)`. Real WebView2 pointer navigation leaves the rail at 52 px and the destination at x=52; keyboard focus still reveals it and leaving the rail closes it. Verified in both themes on 2026-07-28. |
| VA-016 | P2 | Native navigation rail, pinned and collapsed | The rail used separate flex/padding arrangements: collapsed centers were nav/about 25.5 px, Update 16 px, Theme 20.5 px; pinned centers were nav/about 30.5 px and Update 31 px. A later personal Design Studio width overrode both state widths, wrapping open labels inside 56 px, while the compact band's hidden brand sibling shrank the expand glyph five pixels left of the shared column. | Rebuilt every destination and utility as the same `35px minmax(0,1fr)` row grid with the same 8 px panel inset. The open/closed control now owns structural 190/52 px widths over personal styling; the title glyph wrapper cannot shrink and its hidden brand no longer participates in flex gaps. Real WebView2 dark/light captures at 1,400 × 900 show single-line expanded labels and x=33 compact centers for Expand, Projects, STM Viewer, Settings, and utilities. |
| VA-011 | P2 | Components | The 3D preview used decorative copper/gold color while the approved visual language requires neutral previews unless color carries data. | Studio is now the neutral default and `Source Color` is an explicit authored-material mode. Source/Vite browser captures at 1384×861 in both themes show the neutral whole-object frame and truthful `Visible model · Whole object framed` state. |
| VA-020 | P0 | Components, 3D preview | STEP-native Z-up positions were passed to a glTF/Three Y-up viewer without basis normalization, standing board-mounted parts on their side. Placement controls could not repair a coordinate system that was already wrong. | Added one non-destructive −90° X parent to each converted STEP scene, recorded basis metadata, and bumped the GLB cache to `c5`. The real WebView2 0603 now lies flat and aligns with its production footprint pads in both themes; converter structure is regression-tested. |
| VA-021 | P0 | Components, workbench tabs | Selecting a non-Overview tab left the entire Overview grid visible above the selected panel. Tailwind `grid` overrode the browser's `[hidden]` display rule, so two mutually exclusive routes occupied the screen at once. | Inactive workbench panels now receive an authoritative inline `display:none` while retaining `hidden` for accessibility. A regression test switches routes and asserts both layout states; real WebView2 dark/light Representations captures contain only the selected route. |
| VA-022 | P1 | Components, Representations | The first cross-EDA matrix expanded every representation into a full table row and made the selected route substantially taller than the former Handoff card, violating the fixed-workstation intent. | Replaced it with two compact EDA rows in an equal Design Tool / Symbol / Footprint / 3D Model grid. The route itself is non-scrolling; only its cards own overflow. Real WebView2 reports viewport/document/body = 861/861/861 px and panel client/scroll = 717/717 px in both themes. |
| VA-023 | P1 | Components, Representations and EDA Handoff | The compact chip revision still distributed information unevenly: asset evidence was detached from the asset, columns did not align across tools, and the tool-only qualifier visually collided with Category as `CATEGORY ALTIUM DESIGNER`. | Every asset cell now owns its exact reference, source, and check count in a shared four-column grid. The Handoff qualifier is independently aligned at the far edge and reads `Altium Designer only`. Verified in real WebView2 in both themes. |
| VA-024 | P0 | Components, Key Specifications | Pins were stored by raw display labels and category spelling, so vendor wording changes created duplicates and could make a pin appear curated and therefore impossible to remove. Trade/logistics facts could also leak into the physical summary, and promoted rows were repeated in the full list. | Added canonical category/specification IDs with read-time legacy migration and semantic deduplication; category-scoped selectors replace broad substring rules. Promoted physical facts now have one home, while lifecycle, lead time, tariffs, pack quantity, and unit weight stay with sourcing. Verified against the historical 158-part corpus, 1,133 frontend tests, and headless dark/light captures at 1,384 × 861. |
| VA-025 | P1 | Components Overview and expanded previews | The Overview used unequal pane tracks and inconsistent insets; spec rows reacted to the full-page width and wrapped narrow sourcing values; Pinout occupied a separate workflow tab while dead space remained below CAD readiness; Symbol, Footprint, and 3D modals were capped at 860 × 680 px. | The three open content panes now measure 281/280/280 px with matching insets. Spec rows use their own container width. Datasheet Pinout is a bounded 184 px, two-column, internally scrolling card directly below CAD readiness. The shared preview modal measures 1,360 × 837 px with a 1,358 × 797 px stage. Dark/light headless captures show no page overflow, and all 1,135 frontend tests pass. |
| VA-026 | P1 | Components, compact and expanded 3D controls | The orientation cube used saturated red/green/blue faces and rounded coloured nodes, while expanded controls were tiny text-only chips in a full-width status strip. A first compact correction still crowded the specimen with a toolbar and settings popover. | The cube is a 104 px, 256-resolution grayscale CAD control with named faces and crisp joints. Expanded controls form one centered bottom modal dock with icon-and-name actions grouped as Layers, Appearance, Placement, Motion, and View; targets are at least 32 px and the stage reserves the dock footprint. Compact is now auto-spin only, with no embedded controls; a shared eye-and-Expand overlay on the 3D, Symbol, and Footprint stages replaces detached footer eyes. Its canvas-colour scrim darkens in dark mode and lightens in light mode. Verified headlessly in both themes and with 1,137 passing frontend tests. |
| VA-009 | P2 | Settings | Machine setup was dominated by manual buttons and duplicated appearance state, with almost no health, recovery, credential-storage, or updater explanation. | Rebuilt Settings as an Application Delivery plus Machine Readiness console. Achieved capabilities are quiet state; only unmet requirements are controls. Credential storage and capability consequences are explicit, every category exposes permanent usable cards, and all visible actions were traced through focused backend API tests. |
| VA-027 | P1 | Settings | The old disclosure list occupied a small island, hid controls behind navigation layers, mixed application update with catalog sharing, and produced empty half-rows and stretched cards. | The final structure removes category tabs entirely. Machine Readiness, application, catalog, EDA, source, and maintenance capabilities stay on one continuous responsive sheet with one page scroller; full-width and paired cards preserve their scope without hiding DOM. Structural tests cover all 15 cards, direct focus jumps, summaries, scenarios, and modal lifecycle. Native dark/light recapture remains pending. |
| VA-028 | P0 | Native STM Viewer, Bench | Selecting a real STM32F/LQFP64 scope initially crashed after compilation because the API response model silently discarded the compiler's access-service and functional-foundation layers. Unit component tests had bypassed that serialization seam. | The API DTO now preserves both layers, the router regression asserts them, and the real WebView2 host renders the 53-target result, all service groups, and every functional-foundation obligation in both themes with no console errors. |
| VA-029 | P0 | Components, Add a Part | An exact `S1M` lookup surfaced `R+O / US1M` as ready to add. | The backend rejects and replaces foreign cached identities, and the frontend independently refuses near, substituted, and identity-free results. The deployed installed app was exercised through native WebView2 in dark and light themes on 2026-07-28: it named requested `S1M`, explained the exact-match rejection, contained no `US1M`, and exposed neither Review nor Add. |
| VA-030 | P0 | Native STM Viewer, Bench | The first target-definition UI displaced the package pinout with a vertically stacked audit report. Repeated cards, metrics, chips, ledgers, and per-target rows made the compiler output visible but made physical pin reasoning harder than the original viewer. | Rebuilt the Bench as a fixed pinout workstation: scope remains in the left rail, the physical perimeter/BGA map is the focal point, and a selected-position inspector owns grouped target identity, functional foundation, debug/recovery/extraction, and safety routing. Foundation, Access, and Board Plan are in-place map lenses; target-set, policy, raw similarity, and provenance remain available behind two quiet disclosures. Real WebView2 inspection covered LQFP144 dark and WLCSP81 light at 1,384 × 861; the full 1,143-test frontend suite, typecheck, token parity, and production build pass. |
| VA-031 | P0 | Native application launch | A development shortcut could launch the dirty canonical checkout beside the installed app. The source launcher also discarded its file-lock handle immediately, so its documented single-instance protection ended before supervision began. Two live windows showed different routes and code roots under the same `Stockroom` title. | The desktop launcher now targets the managed installed supervisor, the supervisor retains its OS lock for its complete lifetime, a regression proves a contender cannot acquire it during supervision, and the stray canonical host was stopped without touching the installed host. Installed revision `3a296a1e` was then launched twice through the desktop entry point and remained one window backed by one supervisor/host chain. |
| VA-040 | P0 | Native STM Viewer, Bench exports | A single undifferentiated export action could not explain which artifact a hardware implementation needed, and a large menu risked obscuring the restored pinout workstation. | The native source host now presents four compact, task-named exports with one-line intent: rebuild request, authoritative target definition, physical pin plan, and access route plan. The popover remains inside the 1,386 × 893 WebView2 viewport in light and dark themes without covering the package focal point. A live STM32F4/LQFP144 pin-plan download produced 144 ordered physical rows, compiler revision 5 provenance, digest `31b466517234…`, and blank consumer-owned implementation fields. |
| VA-034 | P0 | Native STM Viewer, universal support Bench | Compatibility, electrical, service, and board data were compressed into static strips or audit-heavy blocks. Counts lacked clear denominators, overlap was ambiguous, important STM roles were aggregated, conflicts read as dead ends, and the legend could not explain absent categories or how a consuming design could make a position universal without prescribing a component. | Rebuilt the presentation around five registry-driven lenses and one smart legend. Compatibility and Board Action are explicit 100% distributions; Run Critical, Electrical Role, and Service Access are explicit overlapping coverage views. Present categories are readable filter cards, while a complete grouped guide retains every supported zero-count category, definition, measurement basis, and filter action. Compiler revision 6 emits generic per-position universalization strategies, suggested or evidenced target-specific branches, one-of selection rules, safe-open defaults, path counts, and downstream validation constraints without naming implementation technology. A real source-host WebView2 pass exercised STM32F4/LQFP144 in dark and light: 55 conflicts became 55 configurable-selection positions and 110 implementation-neutral routing paths; run-critical coverage exposed 12 of 13 categories, electrical coverage 12 of 14, and service/extraction coverage 17 of 18. |
| VA-035 | P0 | Native STM Viewer, universal routing plan | Treating every GPIO-versus-critical-role collision as two switched identity branches doubled routing cost and hid useful passive/direct compaction. A GPIO/power position, for example, can often keep a current-limited common signal path while selecting only the power role, subject to proof. | Compiler revision 7 groups all GPIO identities at a physical position into one common signal path and prefers a passive-conditioned signal plus selected critical-role branches. The position inspector shows active path cost, passive path cost, connection mode, constraints, and a fully exclusive fallback. Stockroom specifies no component. For the real 16-device STM32F4/LQFP144 scope, 55 adaptation positions now compile to 47 compact hybrids, 8 fully exclusive positions, 63 active routing paths, and 47 passive-conditioned paths instead of 110 active paths. |
| VA-036 | P0 | STM Viewer, compiled family Bench | The compiled-family state gave a 1,063 × 143 px legend priority over the package, reduced the physical map to 711 × 365 px, and rendered the selected-position inspector as a 1,225 px report. Package selection also sat below the long family list, so the screen did not follow the decision sequence. | Rebuilt the compiled state as three bounded work zones. Package selection moves above the internally scrolling family list after scope selection; a compact 79 px lens/legend strip replaces the legend wall; the package map now measures 743 × 448 px; and the 343 × 589 px inspector switches between Decision, MCUs, and Evidence without growing the page. Reset, selection context, pan/zoom help, counts, filters, and the complete zero-category guide remain available. Headless dark/light captures at 1,384 × 861 report document/root/Bench height parity and zero page overflow. |
| VA-037 | P0 | Projects, Changes | The former KiCad-settings Projects surface was removed and provided no exact cross-EDA review or safe claim lifecycle. | The rebuilt Changes workstation now discovers pushed `work/*` branches for either EDA, keeps stale-base branches visible with an exact blocker, and binds selection to Base → Review → Main commit identities. Change requests remain immutable Git metadata. Review evidence is rebuilt independently from the exact commit for both EDAs: registered native files are hashed, committed schematic facts produce one normalized BOM/digest, and the shared semantic audit reports exact blockers. Native validation is now the same approval gate for both tools: KiCad runs ERC/DRC; Altium runs project validation and a parseable DRC OutJob in a disposable exact-source copy. Protected work can also be recovered after process restart: Stockroom verifies a clean checkout, reacquires only absent claims, rolls partial recovery back, and never force-unlocks another user. The drawer names pending branch and claim state instead of presenting false green completion. Retained source-host pywebview/WebView2 passes at 1,384 × 861 verify recovery in dark/light plus native passed dark/light and failed dark states with no page overflow or console errors. Remaining: exact-commit visual schematic/PCB comparison; KiCad native SVG is qualified, while Altium production rendering remains honestly blocked because the measured AD26 PDF publish command did not produce a repeatable artifact. |
| VA-038 | P0 | Projects, BOM | The rebuilt shell still showed BOM as a promise instead of a working tool, even though the backend already normalized KiCad and Altium placements. Basic passives could also be counted as identity-ready while receiving missing-identity instructions. | The BOM tab now opens directly onto one format-neutral native snapshot: grouped lines, build quantity, reference/MPN/value search, identity and library coverage, selected-line inspection, native source commit/documents, and a stable BOM digest. Basic parts are explicitly value-qualified; genuinely missing identity remains amber. Unlinked identical placements now produce one decision-first resolver for both EDAs. Safe value/footprint candidates can link the entire group; generic Altium symbol names are never treated as identity. KiCad persists native fields in the project Git history, while Altium persists stable component bindings in Stockroom project data and leaves the binary `.SchDoc` byte-identical. The displayed live snapshot now downloads as CSV in one click for either EDA at the selected board quantity, with no hidden priced-build prerequisite. A real Altium-backed WebView2 pass linked R1 and R2 in one click, refreshed to `Every placement linked`, exposed the exact MPN, and preserved SHA-256 `537cca3d…942ec` before and after. Retained resolver/export captures at 1,384 × 861 have no page overflow or console errors. Remaining: variants, pricing, and measured promotion of native Altium field mutation. |
| VA-039 | P0 | Projects, Assemble | The first guided bench persisted events, but it bypassed Stockroom's durable Altium bindings, counted only `Done` toward progress even though skipped/reworked placements can close a run, left the operator on the completed row, and used a dark-only translucent work card. | The bench now consumes the same linked library identity for KiCad and Altium, measures resolved work as Done + Skipped + Reworked, requires a matching reel scan when an MPN exists, saves on Enter, advances to the next pending placement, and keeps the verified reel loaded when the next reference uses the same MPN. Token-based surfaces render correctly in both themes. A real Altium-backed WebView2 run saved R1, advanced to R2, retained the verified reel, updated to `1/3 resolved · 33.3%`, and emitted no console errors or page overflow. Paired placement normalization now has one exact reference/board/X/Y/rotation/side/footprint shape and KiCad's native exporter is qualified. Highlighting remains hidden because both the AD26 PCB-object API and Pick and Place OutJob paths raised a native dialog on a real installed example while preserving source bytes. Remaining: qualify Altium native geometry, then add paired coordinate/polarity highlighting, inventory reservation/reversal, and repository publication of the sealed receipt. |
| VA-041 | P1 | Native provider capture HUD | The production provider HUD forced a dark palette, so its nominal light and dark real-page captures were byte-for-byte identical. It also used an em dash in instructional copy despite the product voice contract. | The closed-shadow HUD now uses one light-first variable palette with a complete `prefers-color-scheme: dark` override, retains forced-colors and reduced-motion behavior, and uses plain two-sentence sign-in guidance. Real CloakBrowser Chromium captures on the live DigiKey TPD6E05U06RVZR model page differ by theme while preserving the same 360 × 532 px bounds, exact identity, five required-file labels, live count, and three explicit outcomes. The panel remains movable and collapsible by pointer or keyboard; DigiKey's cookie banner and guest-limit notice are provider-owned state, not Stockroom chrome. |
| VA-042 | P1 | Projects, all tools | The rebuilt cross-EDA functionality initially retained its own dashboard/table composition instead of the Components/Library selection and inspection philosophy, so project choice and BOM work felt like a separate product. | Projects now uses the same 320 px searchable picker, compact selected-item title strip, shared tabs, bounded workbench, selectable list rows, and contextual inspector grammar as Components. BOM resolution moved beside the selected line; Design, Assemble, Changes, and Releases share the same hierarchy. A source contract forbids EDA-specific workbench branches, and KiCad/Altium fixtures prove the same five-tool shell. Real WebView2 captures at 1,384 × 861 in both themes have no page overflow or console errors. |
| VA-044 | P2 | Served progress HTML, development tool Active Work | Long evidence and blocker prose was forced into two dense columns at a 1,265 px viewport, producing a small, report-like text wall before the owner outcome gates. | Six workstream cards now lead with one bounded state sentence in a single readable column. Exact evidence, blocker, and next action remain inside a native disclosure with visible keyboard focus; Enter and Space both toggle it. Dark/light desktop and phone captures preserve every card and outcome, UTF-8, and zero horizontal overflow even when long SHA-bearing evidence is expanded. |

## Evidence Reviewed

Capture root:
`D:\Workspace\System\Runtime\Stockroom UI Review`

Projects task-owned capture root:
`D:\Workspace\Worktrees\Stockroom-Projects-Library-Grammar\work\projects-repository-audit`

| Evidence | Layer | Surface / theme | Pixels | SHA-256 prefix | Findings |
| --- | --- | --- | --- | --- | --- |
| `components-dark-1600w.png` | Playwright Chromium | Components / dark | 3200×2000 at DPR 2 | `2c51a8cd71b7` | VA-001, 002, 004, 006–008, 011–013 |
| `components-light-1600w.png` | Playwright Chromium | Components / light | 3200×2000 at DPR 2 | `7eec55344d59` | VA-001, 002, 004, 006–008, 011–013 |
| `search-dark-1600w.png` | Playwright Chromium | Search / dark | 3200×2000 at DPR 2 | `e6ee7bbb5edc` | VA-003, 004, 006, 010 |
| `search-light-1600w.png` | Playwright Chromium | Search / light | 3200×2000 at DPR 2 | `cdcb237870f6` | VA-003, 004, 006, 010 |
| `settings-dark-1600w.png` | Playwright Chromium | Settings / dark | 3200×2000 at DPR 2 | `2d03ac2e92f7` | VA-004, 006, 009 |
| `settings-light-1600w.png` | Playwright Chromium | Settings / light | 3200×2000 at DPR 2 | `4c9a9694f969` | VA-004, 006, 009 |
| `real-webview2-components-dark.png` | pywebview / WebView2 | Components empty / dark | 1384×861 | `fdf4d8706547` | VA-002, 004, 005, 014 |
| `real-webview2-components.png` | pywebview / WebView2 | Components empty / light | 1384×861 | `a2f69504390b` | VA-002, 004, 005, 014 |
| `real-webview2-settings-dark.png` | pywebview / WebView2 | Settings / dark | 1384×861 | `9e3f74482fa1` | VA-004, 009, 014 |
| `real-webview2-settings-light.png` | pywebview / WebView2 | Settings / light | 1384×861 | `ab8ae5799b4f` | VA-004, 009, 014 |
| `2026-07-28 Rail Fix/components-dark-1384w.png` | Playwright Chromium | Components / dark | 1384×861 | `565a5bb9c697` | VA-014, 015, 016 verification |
| `2026-07-28 Rail Fix/components-light-1384w.png` | Playwright Chromium | Components / light | 1384×861 | `ac1e835a4fcd` | VA-014, 015, 016 verification |
| `2026-07-28 Rail Fix/real-webview2-settings-dark-after.png` | pywebview / WebView2 | Settings collapsed / dark | 1384×861 | `df3bbe7d5a73` | VA-015, 016 resolved |
| `2026-07-28 Rail Fix/real-webview2-settings-dark-pinned-after.png` | pywebview / WebView2 | Settings pinned / dark | 1384×861 | `9c627b7f7d17` | VA-016 resolved |
| `2026-07-28 Rail Fix/real-webview2-settings-light-after.png` | pywebview / WebView2 | Settings collapsed / light | 1384×861 | `48d5743720b4` | VA-015, 016 resolved |
| `2026-07-28 Inspection Rebuild/renderprobe-inline-production-dark.png` | pywebview / WebView2 | Components inspection / dark | 1384×861 | `97b63ac2e14f` | VA-017, 019 partial; VA-020 resolved |
| `2026-07-28 Inspection Rebuild/renderprobe-inline-production-light.png` | pywebview / WebView2 | Components inspection / light | 1384×861 | `b2301cb462e0` | VA-017, 019 partial; VA-020 resolved |
| `2026-07-28 Inspection Rebuild/renderprobe-settings-dark.png` | pywebview / WebView2 | Compact 3D settings / dark | 1384×861 | `74c92d783183` | VA-019 partial |
| `2026-07-28 Inspection Rebuild/renderprobe-settings-light.png` | pywebview / WebView2 | Compact 3D settings / light | 1384×861 | `4b8297d5fbae` | VA-019 partial |
| `2026-07-28 Inspection Rebuild/renderprobe-3d-expanded-dark-basis-fixed.png` | pywebview / WebView2 | Expanded 3D / dark | 1384×861 | `7a5d0387d1ae` | VA-019 partial; VA-020 resolved |
| `2026-07-28 Inspection Rebuild/renderprobe-3d-expanded-light.png` | pywebview / WebView2 | Expanded 3D / light | 1384×861 | `15c030cd0bd8` | VA-019 partial; VA-020 resolved |
| `2026-07-28 Inspection Rebuild/renderprobe-gizmo-click-dark.png` | pywebview / WebView2 | View-cube front-face result / dark | 1384×861 | `5fe16ccc4521` | VA-019 view-cube interaction verified |
| `2026-07-28 Inspection Rebuild/renderprobe-symbol-production-dark.png` | pywebview / WebView2 | Symbol inspection / dark | 1384×861 | `9c12cd3d1b2c` | VA-017 partial |
| `2026-07-28 Inspection Rebuild/renderprobe-symbol-production-light.png` | pywebview / WebView2 | Symbol inspection / light | 1384×861 | `ece0f6cb94e4` | VA-017 partial |
| `2026-07-28 Inspection Rebuild/renderprobe-footprint-production-dark.png` | pywebview / WebView2 | Footprint inspection / dark | 1384×861 | `3af5865faff0` | VA-017 partial |
| `2026-07-28 Inspection Rebuild/renderprobe-footprint-production-light.png` | pywebview / WebView2 | Footprint inspection / light | 1384×861 | `43cf94f79ba0` | VA-017 partial |
| `2026-07-28 Inspection Rebuild/representations-dark-final.png` | pywebview / WebView2 | Cross-EDA representations / dark | 1384×861 | `a6f49a8208d1` | VA-001, 012 partial; VA-021 resolved |
| `2026-07-28 Inspection Rebuild/representations-light-final.png` | pywebview / WebView2 | Cross-EDA representations / light | 1384×861 | `afe49ad8c23f` | VA-001, 012 partial; VA-021 resolved |
| `2026-07-28 Inspection Rebuild/representations-compact-final-dark.png` | pywebview / WebView2 | Compact representations / dark | 1384×861 | `6736df094c83` | VA-001, 012 partial; VA-021, 022 resolved |
| `2026-07-28 Inspection Rebuild/representations-compact-final-light.png` | pywebview / WebView2 | Compact representations / light | 1384×861 | `064443c883cc` | VA-001, 012 partial; VA-021, 022 resolved |
| `2026-07-28 Inspection Rebuild/representations-even-dark.png` | pywebview / WebView2 | Even representations / dark | 1384×861 | `c8609ffc37bc` | VA-001, 012 partial; VA-021–023 resolved |
| `2026-07-28 Inspection Rebuild/representations-even-light.png` | pywebview / WebView2 | Even representations / light | 1384×861 | `4637ddfaba6d` | VA-001, 012 partial; VA-021–023 resolved |
| `2026-07-28 Specification Schema/components-dark-1384w.png` | Playwright Chromium | Components specification IA / dark | 1384×861 | `3735f739e768` | VA-024 resolved; compact block/list balance and no horizontal overflow |
| `2026-07-28 Specification Schema/components-light-1384w.png` | Playwright Chromium | Components specification IA / light | 1384×861 | `c213025fcb23` | VA-024 resolved; compact block/list balance and no horizontal overflow |
| `2026-07-28 Specification Schema/vendor-data/part-vendor-data-dark-1384w.png` | Playwright Chromium | Vendor data disclosures / dark | 1384×861 | `e9770a38895b` | VA-024 resolved; promoted-once, residual spec, and sourcing-only trade data |
| `2026-07-28 Specification Schema/vendor-data/part-vendor-data-light-1384w.png` | Playwright Chromium | Vendor data disclosures / light | 1384×861 | `17b671db26f4` | VA-024 resolved; promoted-once, residual spec, and sourcing-only trade data |
| `2026-07-28 Datasheet Pinout/final/part-vendor-data-dark-1384w.png` | Playwright Chromium | Balanced Overview and pinout / dark | 1384×861 | `1ad53942a16b` | VA-025 resolved; 281/280/280 px panes, bounded pinout, no page overflow |
| `2026-07-28 Datasheet Pinout/final/part-vendor-data-light-1384w.png` | Playwright Chromium | Balanced Overview and pinout / light | 1384×861 | `a6985f165120` | VA-025 resolved; equal rhythm and container-correct sourcing rows |
| `2026-07-28 Datasheet Pinout/expanded-modal-final/components-dark-1384w.png` | Playwright Chromium | Expanded 3D preview / dark | 1384×861 | `8e15b837c6b9` | VA-025 resolved; 1360×837 modal and 1358×797 stage |
| `2026-07-28 Datasheet Pinout/expanded-modal-final/components-light-1384w.png` | Playwright Chromium | Expanded 3D preview / light | 1384×861 | `3e3e55ff25d6` | VA-025 resolved; controls and view cube fit without clipping |
| `2026-07-28 3D Controls/bottom-dock/components-dark-1384w.png` | Playwright Chromium | Expanded 3D control dock / dark | 1384×861 | `858979dbc5cc` | VA-026 resolved; grayscale cube and grouped icon/name dock |
| `2026-07-28 3D Controls/bottom-dock/components-light-1384w.png` | Playwright Chromium | Expanded 3D control dock / light | 1384×861 | `4f7a39dbb42d` | VA-026 resolved; modal surface, reserved footprint, no clipping |
| `2026-07-28 3D Controls/compact-settings-final/components-dark-1384w.png` | Playwright Chromium | Compact 3D settings / dark | 1384×861 | `b8a083c23c26` | VA-026 resolved; 274×278 modal and no horizontal overflow |
| `2026-07-28 3D Controls/compact-settings-final/components-light-1384w.png` | Playwright Chromium | Compact 3D settings / light | 1384×861 | `a6e04354fe36` | VA-026 resolved; icon/name choices and separate placement status |
| `2026-07-28 3D Controls/compact-expand/components-dark-1384w.png` | Playwright Chromium | Compact representation Expand / dark | 1384×861 | `92eb820a4817` | VA-017 partial; VA-026 final correction—auto-spin specimen, dark canvas scrim, eye-and-Expand action |
| `2026-07-28 3D Controls/compact-expand/components-light-1384w.png` | Playwright Chromium | Compact representation Expand / light | 1384×861 | `2dd9a5f601de` | VA-017 partial; VA-026 final correction—light canvas scrim, keyboard/pointer-equivalent overlay, quiet footer |
| `2026-07-28 Settings Rebuild/final/general/settings-dark-1384w.png` | Playwright Chromium | Settings General / dark | 1384×861 | `e90cb11c3e1e` | VA-009, VA-027 resolved; automatic delivery and machine readiness |
| `2026-07-28 Settings Rebuild/final/general/settings-light-1384w.png` | Playwright Chromium | Settings General / light | 1384×861 | `6aad9c0b6833` | VA-009, VA-027 resolved; fixed page, category-owned scroll |
| `2026-07-28 Settings Rebuild/final/library/settings-dark-1384w.png` | Playwright Chromium | Settings Library / dark | 1384×861 | `e0ed6f79b420` | VA-027 resolved; balanced profile/sync pair and full-width access |
| `2026-07-28 Settings Rebuild/final/library/settings-light-1384w.png` | Playwright Chromium | Settings Library / light | 1384×861 | `72dcc4683209` | VA-027 resolved; no empty half-row |
| `2026-07-28 Settings Rebuild/final/sources/settings-dark-1384w.png` | Playwright Chromium | Settings Data Sources / dark | 1384×861 | `3b4412673e90` | VA-009, VA-027 resolved; provider data and actions grouped by scope |
| `2026-07-28 Settings Rebuild/final/sources/settings-light-1384w.png` | Playwright Chromium | Settings Data Sources / light | 1384×861 | `ae04bcead4e8` | VA-009, VA-027 resolved; balanced first row and internal scroll |
| `2026-07-28 STM Target Definition/stm-target-dark.png` | pywebview / WebView2 | STM target definition and access services / dark | 1384×861 | `1c013bf9f5bf` | VA-028 resolved; blocked evidence and service coverage readable |
| `2026-07-28 STM Target Definition/stm-target-light.png` | pywebview / WebView2 | STM target definition and access services / light | 1384×861 | `68c87e1e820e` | VA-028 resolved; blocked evidence and service coverage readable |
| `2026-07-28 STM Target Definition/stm-foundation-dark.png` | pywebview / WebView2 | STM functional foundation / dark | 1384×861 | `2baed3514844` | VA-028 resolved; all run-critical obligation groups fit and remain legible |
| `2026-07-28 STM Target Definition/stm-foundation-light.png` | pywebview / WebView2 | STM functional foundation / light | 1384×861 | `c021e18b2f13` | VA-028 resolved; all run-critical obligation groups fit and remain legible |
| `2026-07-28 STM Target Definition/stm-position-dark-final.png` | pywebview / WebView2 | STM critical-position inspector / dark | 1384×861 | `6944c7069c8e` | VA-028 resolved; power/VBAT identities truthfully read `functional foundation` |
| `2026-07-28 STM Target Definition/stm-position-light-final.png` | pywebview / WebView2 | STM critical-position inspector / light | 1384×861 | `829216c21fc8` | VA-028 resolved; power/VBAT identities truthfully read `functional foundation` |
| `2026-07-28 Acquisition/components-empty-dark-1024x720.png` | In-app Browser / Chromium | Components empty / dark | 1024×720 | `76d79312bfa8` | VA-002, 004, 005, 014 reconfirmed |
| `2026-07-28 Acquisition/lookup-near-match-dark-1024x720.png` | In-app Browser / Chromium | Add a Part lookup / dark | 1024×720 | `7051665a1223` | VA-014 reconfirmed; VA-029 opened |
| `2026-07-28 Acquisition/lookup-exact-rejection-light-1024x720.png` | In-app Browser / Chromium | Add a Part lookup / light | 1024×720 | `dc8739acb811` | VA-029 functional verification; VA-014 contrast reconfirmed |
| `2026-07-28 Acquisition/installed-exact-rejection-dark-1384x861.png` | pywebview / WebView2 | Installed Add a Part exact rejection / dark | 1384×861 | `3400f77633f5` | VA-029 resolved; VA-014 contrast reconfirmed |
| `2026-07-28 Acquisition/installed-exact-rejection-light-1384x861.png` | pywebview / WebView2 | Installed Add a Part exact rejection / light | 1384×861 | `e9815f662c65` | VA-029 resolved; VA-014 contrast reconfirmed |
| `2026-07-28 Acquisition/installed-launch-firewall-duplicate-components-1386x893.png` | pywebview / WebView2 + Windows Security | Installed Components with competing host and firewall prompt / dark | 1386×893 | `06299bbe23e5` | VA-031 opened and resolved in source; VA-032 opened |
| `2026-07-28 Acquisition/installed-launch-firewall-duplicate-stm-1386x893.png` | pywebview / WebView2 + Windows Security | Competing canonical STM window and firewall prompt / dark | 1386×893 | `be5b0a72e91c` | VA-031 route/root divergence evidence; VA-032 opened |
| `2026-07-28 Acquisition/deployed-provider-build-firewall-single-instance-1386x893.png` | pywebview / WebView2 + Windows Security | Deployed provider-feedback build after the second-launch test / dark | 1386×893 | `f3d2537307df` | VA-031 installed verification: one Stockroom window; VA-032 reconfirmed because the raw firewall dialog still blocks the app |
| `2026-07-28 Acquisition/deployed-provider-build-firewall-refocused-1386x893.png` | pywebview / WebView2 + Windows Security | Refocused installed Components after attempted safe dismissal / dark | 1386×893 | `dac1133489fa` | VA-032 reconfirmed: the publisher-unknown prompt retained modality and obscured the primary workflow until its Cancel action was invoked |
| `work/stm-ui-audit/after-target/components-dark-1384w.png` | Playwright Chromium | Compiled STM family Decision / dark | 1384×861 | `251486b17c89` | VA-036 resolved; 743 × 448 px map, bounded inspector, compact package-first hierarchy, zero page overflow |
| `work/stm-ui-audit/after-target/components-light-1384w.png` | Playwright Chromium | Compiled STM family Decision / light | 1384×861 | `4d8ffbb1fcef` | VA-036 resolved; theme parity and fixed workstation bounds |
| `work/stm-ui-audit/after-target-mcus/components-dark-1384w.png` | Playwright Chromium | Selected-position MCU comparison / dark | 1384×861 | `b93cb3493318` | VA-036 resolved; grouped identities and exact target denominators stay inside the inspector |
| `work/stm-ui-audit/after-target-evidence/components-light-1384w.png` | Playwright Chromium | Selected-position evidence / light | 1384×861 | `0c8f27e104ae` | VA-036 resolved; run-critical, route, board, fallback, and constraint evidence scroll inside the inspector |
| Live `Stockroom Projects QA` source-host capture | pywebview / WebView2 | Projects exact commit sign-off / dark | 1384×861 | not retained | VA-037 partial; Base → Review → Main chain, two-document ledger, repository state, and approval action fit without clipping |
| Live `Stockroom Projects QA` source-host capture | pywebview / WebView2 | Projects exact commit sign-off / light | 1384×861 | not retained | VA-037 partial; theme contrast, commit identities, changed documents, and approval action remain legible |
| Live `Stockroom Projects Review QA` source-host capture | pywebview / WebView2 | Projects reviewer change-request form / dark | 1384×861 | not retained | VA-037 partial; exact commit chain, two-document ledger, named reason fields, Request Changes, and Approve & Integrate fit without clipping |
| Live `Stockroom Projects Review QA` source-host capture | pywebview / WebView2 | Projects author request-received state / light | 1384×861 | not retained | VA-037 partial; requested reason, held document claims, Check Review, repository state, and suppressed Finish action remain legible |
| Live `Stockroom BOM QA` source-host capture | pywebview / WebView2 | Projects live BOM / dark | 1384×861 | not retained | VA-038 partial; five grouped lines, identity/library coverage, warnings, source commit, snapshot digest, and inspector fit without clipping |
| Live `Stockroom BOM QA` source-host capture | pywebview / WebView2 | Projects live BOM / light | 1384×861 | not retained | VA-038 partial; light tokens preserve table hierarchy, amber missing identity, green library state, and inspector readability without clipping |
| Live `Stockroom Review Evidence QA` source-host capture | pywebview / WebView2 | Projects exact review evidence / dark | 1384×861 | not retained | VA-037 partial; four hashed native files, 18/18 BOM identity coverage, semantic warning, two changed documents, and both reviewer decisions fit without clipping or page overflow |
| Live `Stockroom Review Evidence QA` source-host capture | pywebview / WebView2 | Projects exact review evidence / light | 1384×861 | not retained | VA-037 partial; evidence hierarchy, exact digests, pending native/visual states, and action contrast remain legible without clipping or page overflow |
| `work/projects-native-ui-audit/native-passed-dark-anchored.png` | pywebview / WebView2 | Projects native validation passed / dark | 1384×861 | `78a07a4e570c` | VA-037 partial; 2/2 approval gates, editor/runtime evidence, anchored decision controls, no page overflow |
| `work/projects-native-ui-audit/native-passed-light-anchored.png` | pywebview / WebView2 | Projects native validation passed / light | 1384×861 | `7c3857636bfb` | VA-037 partial; theme parity, exact commit chain, passed per-document checks, anchored approval |
| `work/projects-native-ui-audit/native-failed-dark.png` | pywebview / WebView2 | Projects native validation failed / dark | 1384×861 | `350e71b2f792` | VA-037 partial; 1/2 approval gates, failed DRC, Run Again, and disabled integration remain simultaneously visible |
| `work/projects-recovery-ui-audit/recovery-dark-final.png` | pywebview / WebView2 | Projects protected-work recovery / dark | 1384×861 | `3f16c74a7a8e` | VA-037 partial; pending claim/branch states are explicit and Resume Protected Work remains anchored |
| `work/projects-recovery-ui-audit/recovery-light-final.png` | pywebview / WebView2 | Projects protected-work recovery / light | 1384×861 | `5b1a5cdf7df8` | VA-037 partial; recovery hierarchy and disabled sharing remain legible without page overflow |
| `work/projects-bom-ui-audit/bom-resolver-dark-final.png` | pywebview / WebView2 | Projects Altium BOM resolver / dark | 1384×861 | `d4a24bade2a2` | VA-038 partial; one grouped R1/R2 decision is visible at the top of the inspector without scrolling |
| `work/projects-bom-ui-audit/bom-resolver-light-final.png` | pywebview / WebView2 | Projects Altium BOM resolver / light | 1384×861 | `1c5eaf080481` | VA-038 partial; shared resolver, match evidence, and native-binary promise remain clear in light theme |
| `work/projects-bom-ui-audit/bom-resolved-light-final.png` | pywebview / WebView2 | Projects resolved Altium BOM / light | 1384×861 | `925130d5ef7c` | VA-038 partial; one action links both placements, refreshes MPN/library state, and preserves the native `.SchDoc` digest |
| `work/projects-bom-ui-audit/bom-export-dark-final.png` | pywebview / WebView2 | Projects Altium live BOM export / dark | 1384×861 | `252973fdc299` | VA-038 partial; one-click CSV is primary, quantity/filter/refresh remain aligned, and the 13-line inspector workstation has no page overflow |
| `work/projects-bom-ui-audit/bom-export-light-final.png` | pywebview / WebView2 | Projects Altium live BOM export / light | 1384×861 | `72ae88f69eb8` | VA-038 partial; export contrast and full table/inspector hierarchy remain legible with body/root client and scroll bounds equal |
| `work/projects-assembly-ui-audit/assembly-dark-final.png` | pywebview / WebView2 | Projects guided assembly / dark | 1384×861 | `49f07865b4b7` | VA-039 partial; placement queue, work target, reel verification, and actions fit without page overflow |
| `work/projects-assembly-ui-audit/assembly-light-final.png` | pywebview / WebView2 | Projects guided assembly / light | 1384×861 | `ff576038da9f` | VA-039 partial; token-based stage/card contrast replaces the dark-only translucent surface |
| `work/projects-assembly-ui-audit/assembly-after-r1-dark-final.png` | pywebview / WebView2 | Projects live placement advance / dark | 1384×861 | `60c4fbb1ed61` | VA-039 partial; R1 event persisted, progress became 1/3, R2 became current, and the verified same-MPN reel stayed loaded |
| `work/Library Punch Completion/Provider HUD Audit/DigiKey Provider HUD Dark 1384x861.png` | CloakBrowser Chromium | Live DigiKey provider capture HUD / dark | 1384×861 | `f1d7cf86a801` | VA-041 resolved; exact manufacturer/MPN, five required formats, 2-file live receipt count, and Finish/Try Another Provider/Cancel remain visible without reading provider-controlled identity |
| `work/Library Punch Completion/Provider HUD Audit/DigiKey Provider HUD Light 1384x861.png` | CloakBrowser Chromium | Live DigiKey provider capture HUD / light | 1384×861 | `35e3f572dd2b` | VA-041 resolved; light variables replace the prior forced-dark panel while bounds and interaction hierarchy remain stable |
| `work/Provider HUD Audit/Assisted Capture Dark.png` | Stockroom managed Playwright Chromium | Redesigned assisted capture / dark | 368×514 | `7f0a5fdd004d` | VA-043 opened; compact workstation grammar, exact author route, DigiKey-only Session Memory, one Human Action, required formats, sticky outcomes, and dark token parity verified in isolation |
| `work/Provider HUD Audit/Assisted Capture Light.png` | Stockroom managed Playwright Chromium | Redesigned assisted capture / light | 368×514 | `e545c50b8f30` | VA-043 theme-parity evidence; light semantic tokens, compact radii, focus-ready controls, and truthful zero-file Resume gate remain legible |
| `work/Provider HUD Audit/Security Handoff Dark.png` | Stockroom managed Playwright Chromium | Redesigned provider security handoff / dark | 368×429 | `69b6b6c57eec` | VA-043 paused-state evidence; exact route, one provider-owned gate, no credential/CAPTCHA automation claim, and automatic-resume status are simultaneously visible |
| `work/Provider HUD Audit/Security Handoff Light.png` | Stockroom managed Playwright Chromium | Redesigned provider security handoff / light | 368×429 | `911dc2f8b3c9` | VA-043 theme-parity evidence; an earlier serif inheritance defect from inline `all: initial` was found during screenshot critique and corrected before this authority |
| `work/Library Punch Completion/Final Headless Audit/components-dark-1384w.png` | Playwright Chromium | Final Components inspection / dark | 1384×861 | `92706e157e89` | Final regression pass after the production workflow import-cycle correction: no Projects surface, exact selected-part identity, linked Symbol/Footprint/3D evidence, complete CAD state, aligned Overview panes, and zero measured content-tail overflow |
| `work/Library Punch Completion/Final Headless Audit/components-light-1384w.png` | Playwright Chromium | Final Components inspection / light | 1384×861 | `2ef5696d1980` | Theme-parity regression pass; the neutral 3D stage preserves white-part silhouette contrast, all asset/specification/sourcing boundaries remain legible, and the same three measured regions retain identical geometry |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Overview Dark 1384x861.png` | pywebview / WebView2 | Isolated native embed fixture before action / dark | 1384×861 | `90bcd158ba9c` | Real source host shows the exact S1M fixture, linked STEP, CAD readiness, and running revision before native mutation. The blank Symbol and one-solid-pad Footprint previews truthfully reflect this deliberately minimal functional fixture, not a representative production component. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Representations Dark 1384x861.png` | pywebview / WebView2 | Cross-EDA state before embed / dark | 1384×861 | `cda0dcfba00a` | Both tool rows expose exact symbol/footprint identities and source/evidence state; Altium alone reports `Needs Embed`, while no Projects navigation is present. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Action Dark 1384x861.png` | pywebview / WebView2 | Native Altium embed action / dark | 1384×861 | `3885dea0efbc` | The missing embedded model is repairable at the point of readiness with one explicit `Embed 3D Model` action; the action remains distinct from Complete Part and destructive asset-removal controls. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Running Dark 1384x861.png` | pywebview / WebView2 | Native Altium embed running / dark | 1384×861 | `46847033e0f9` | The action becomes disabled progress state and explains that Altium is writing the body, so the several-second native handoff does not look frozen or invite a duplicate run. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Complete Dark 1384x861.png` | pywebview / WebView2 | Native Altium embed complete / dark | 1384×861 | `a89110627203` | Completion replaces the action with an independently checkable `3D Model embedded in the footprint` state while both EDA rows remain ready. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Complete Light 1384x861.png` | pywebview / WebView2 | Native Altium embed complete / light | 1384×861 | `debf6555dba7` | The same completed readiness hierarchy remains legible in light theme; the action is absent and the success statement is not conveyed by colour alone. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Overview Complete Light 1384x861.png` | pywebview / WebView2 | Completed fixture overview after theme switch / light | 1384×861 | `c46d4b0c2b44` | Immediate post-switch capture confirms WebView2 theme convergence and retained 3D rendering. The cursor obscures part of the intentionally empty symbol fixture, so the clean follow-up below is the visual authority. |
| `work/Library Punch Completion/Native Embed Audit/Stockroom Embed Proof Overview Complete Light Clean 1384x861.png` | pywebview / WebView2 | Completed fixture overview / light | 1384×861 | `a8134e5791a5` | Clean theme-parity evidence after native mutation: 3D remains rendered, readiness remains complete, update standing converges to Current, and the sparse symbol/single-pad visuals exactly match the isolated fixture source. |
| `work/Library Punch Completion/Final UI Audit/Components Model Proof/components-dark-1384w.png` | Playwright Chromium | Model-bearing Components Overview / dark | 1384×861 | `a95bbcbbd39b` | VA-025/VA-026 regression: the real KiCad 0603 symbol, footprint, and STEP projection remain legible; the 290 × 310 px 3D stage and both information panes report no clipping or measured content-tail overflow. The sparse fixture's intentionally short specification and sourcing content is not treated as a layout defect. |
| `work/Library Punch Completion/Final UI Audit/Components Model Proof/components-light-1384w.png` | Playwright Chromium | Model-bearing Components Overview / light | 1384×861 | `830bb65dbe39` | VA-025/VA-026 regression: the transparent WebGL canvas exposes the light `bg-stage` token instead of retaining a dark renderer backdrop; geometry is identical to dark mode and the white package retains visible silhouette contrast. |
| `work/Library Punch Completion/Final UI Audit/Components Full Data Proof/part-vendor-data-dark-1384w.png` | Playwright Chromium | Full vendor-data Components Overview / dark | 1384×861 | `324a3b6feeac` | VA-025 regression: two vendor ladders, expanded alternate evidence, six-region compliance data, photo, CAD state, and eight-pin card remain simultaneously inspectable. Asset/specification/sourcing measurements are 290 × 112, 291 × 90, and 291 × 324 px with no clipping or content-tail overflow; the missing CAD art is fixture truth. |
| `work/Library Punch Completion/Final UI Audit/Components Full Data Proof/part-vendor-data-light-1384w.png` | Playwright Chromium | Full vendor-data Components Overview / light | 1384×861 | `9c984a3f998f` | VA-025 theme-parity regression: the same full-data hierarchy and independent pane boundaries remain readable with identical geometry and no document overflow. |
| `work/Library Punch Completion/Final UI Audit/Settings Proof/settings-dark-1384w.png` | Playwright Chromium | Settings General / dark | 1384×861 | `fa020b100769` | VA-009/VA-027 regression: Application Delivery and Machine Readiness provide distinct first-glance outcomes above task-scoped navigation, while the active General workspace uses the remaining viewport. Root client/scroll height is 837/837 px and the 1,292 × 41 px section navigator has no clipping. |
| `work/Library Punch Completion/Final UI Audit/Settings Proof/settings-light-1384w.png` | Playwright Chromium | Settings General / light | 1384×861 | `d510d503c073` | VA-009/VA-027 theme-parity regression: status, setup actions, navigation, appearance, and update evidence retain the same bounded layout and hierarchy without the former disclosure wall or wasted island. |
| `work/Library Punch Completion/Unrelated MPN Canary/Ultra Librarian Headed Security State.png` | Stockroom managed Playwright Chromium | Live Ultra Librarian exact-MPN search handoff | 1296×854 | `f8585f5377b1` | The persistent headed session avoids the provider's headless-browser rejection, preserves exact Texas Instruments / TPS62130RGTR context, and exposes an anchored handoff HUD. Critique: the HUD says to complete a visible sign-in while the search result is still the only actionable route; Stockroom should navigate to the login surface before asking the person to act. |
| `work/Library Punch Completion/Unrelated MPN Canary/Ultra Librarian Headed Product State.png` | Stockroom managed Playwright Chromium | Live Ultra Librarian remembered-login handoff | 1296×854 | `e88aaeeeccf4` | The exact product route reaches the real SSO form and the HUD correctly refuses to operate credentials, CAPTCHA, 2FA, or other security controls. The form/HUD pairing makes the single external action discoverable, but the panel obscures part of the form and should offer a compact/collapsed state for narrow windows. |
| `work/projects-library-grammar-audit/design-dark-1384x861.png` | pywebview / WebView2 | Projects Design / dark | 1384×861 | `f77779236b19` | VA-042 resolved; Components-style picker/title/workbench grammar, bounded native document stage, and collaboration/runtime inspector. |
| `work/projects-library-grammar-audit/bom-dark-1384x861.png` | pywebview / WebView2 | Projects BOM / dark | 1384×861 | `d5eb86ec989f` | VA-038, VA-042 regression; selected BOM line, filters, primary export, and contextual resolver fit without page overflow. |
| `work/projects-library-grammar-audit/bom-light-1384x861.png` | pywebview / WebView2 | Projects BOM / light | 1384×861 | `f8332fa9810b` | VA-038, VA-042 theme parity; identical geometry and legible list/inspector hierarchy. |
| `work/projects-library-grammar-audit/assembly-light-1384x861.png` | pywebview / WebView2 | Projects Assembly start / light | 1384×861 | `cc8cdcf55330` | VA-039, VA-042 regression; one calm shared start surface names the identical KiCad/Altium scan, verify, place, and recovery workflow. |
| `work/projects-library-grammar-audit/changes-light-1384x861.png` | pywebview / WebView2 | Projects Changes without Git / light | 1384×861 | `8c0196916a51` | VA-037, VA-042 regression; immediate repository requirement, bounded branch list/inspector, no false loading state or page overflow. |
| `work/Final Library Visual Audit/01 Empty Components Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Isolated empty Components / dark | 1384×861 | `f2687c3dcab0` | Super-critical final audit: zero console/network failures, zero document overflow, 52 px compact rail, and no Projects route. VA-005 is materially reconfirmed: `No Components Yet` and the impossible `Select a part` instruction compete across a mostly empty detail pane; VA-002/VA-004 remain visible in the manual Add Parts path and unused workspace. This is layout/theme evidence, not WebView2 host/DPI evidence. |
| `work/Final Library Visual Audit/02 Empty Components Light.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Isolated empty Components / light | 1384×861 | `77f1a0fce4fb` | Theme-parity capture is technically clean and geometrically identical, with Projects absent. It reconfirms VA-005 and makes VA-014 more acute: both competing instructions use faint low-emphasis text over an almost entirely empty white detail pane, so the only available next step is visually detached from the state explaining it. |
| `work/Final Library Visual Audit/03 Network Add Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Network-only Add a Part with exact MPN focus / dark | 1384×861 | `8226180ce905` | Clean functional frame: the real input owns `:focus-visible`, there are zero file inputs or Local Upload controls, exact identity precedes one KiCad + Altium + STEP set, and single/batch intake share one modal without page overflow. Super-critical critique: VA-002 remains because the screen does not expose durable batch progress, retries/fallbacks, resume, or the 1–1,000 operating envelope; `Preview Without Writing` is implementation language, and placeholder/stage microcopy is faint. |
| `work/Final Library Visual Audit/04 Network Add Light.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Network-only Add a Part with exact MPN focus / light | 1384×861 | `649033f04efe` | Theme-parity and keyboard-focus pass with identical 720 × 432 dialog geometry, no overflow, no file picker, no errors, and Projects absent. The primary lookup is unmistakable, but VA-002/VA-014 remain: durable automation/recovery is not stated and the helper, stage, example, and disabled-action text form an overly faint secondary tier. |
| `work/Final Library Visual Audit/05 Collect All Ledger Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | CAD-complete component after terminal Collect All / dark | 1384×861 | `70ffce68bc3c` | High-risk workflow pass: `Files Complete` remains distinct from exhaustive `Partial`; all seven terminal routes render independently as Activated, Retained, Unavailable, Needs Your Input, Blocked, Failed, and Not Attempted, each with a textual reason and a retryable Collect All action. The 560 × 716 dialog, anchored Done action, document, and body have no overflow or transport/console error. Super-critical critique: dense 2xs reason text and colour-heavy status accents keep VA-014 relevant, but no outcome relies on colour alone. |
| `work/Final Library Visual Audit/06 Collect All Ledger Light.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | CAD-complete component after terminal Collect All / light | 1384×861 | `b84aca202b47` | Functional and geometric theme-parity pass: all seven route labels/statuses/reasons remain present, Files Complete and Collection Partial remain simultaneous and non-contradictory, the retry and Done actions stay anchored, and the host/frontend layer reports no error or overflow. VA-014 remains open because amber summary/status text and the grey reason tier are faint at this scale, especially against the white card. |
| `work/Final Library Visual Audit/07 Shared CAD Pair Selector Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Exact shared KiCad+Altium pair selector / dark | 1384×861 | `76649312a2bc` | Atomic-selection pass: two same-download pairs, two KiCad variants, two Altium variants, and one supplementary manifest are retained; the active Ultra Librarian pair is marked in both tools; exactly one `Use SnapMagic for KiCad and Altium` action exists and each tool region has zero independent activation buttons. Real Tab navigation reaches that action and its `:focus-visible` outline is present. No error, page overflow, or Projects route. Critique: the evidence-dense 2xs hierarchy and clipped lower supplementary detail keep VA-014/VA-018 relevant, though all four activatable variants and the atomic rule are visible without scrolling. |
| `work/Final Library Visual Audit/08 Shared CAD Pair Selector Light.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Exact shared KiCad+Altium pair selector / light | 1384×861 | `623c3ddf6fc9` | Theme-parity atomic-selection pass with the same 2+2 retained variants, one whole-pair fallback action, zero per-tool actions, explicit active-in-both state, and keyboard-visible focus. Card/grid boundaries, green states, amber Altium embed gap, and exact references remain distinguishable with no error or document overflow. VA-014 persists in low-emphasis evidence/helper text; the active semantic structure itself is not colour-only. |
| `work/Final Library Visual Audit/09 Settings Version Update Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Settings General, version and automatic update / dark | 1384×861 | `edadac4d5d3b` | Delivery/version pass: Automatic Convergence, 3 Commits Ready, installed `92444712abcd`, remote `a41b52cc88ef`, automatic-while-open behavior, rollback explanation, and the compact rail's `r9244471 → a41b52c Update Available` all agree. Machine-readiness counts/actions and category scope remain bounded; root, Settings, and document client/scroll dimensions match with no console/network error or Projects route. Critique: helper/row-label contrast remains in VA-014, and update identity is intentionally repeated as summary plus detail rather than contradictory state. |
| `work/Final Library Visual Audit/10 Settings Version Update Light.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Settings General, version and automatic update / light | 1384×861 | `193ddb3404d4` | Theme-parity delivery/version pass: Automatic Convergence, 3 Commits Ready, installed `92444712abcd`, target `a41b52cc88ef`, automatic-while-open behavior, rollback text, and the rail update standing retain the dark frame's geometry and meaning. Settings is 1,332 × 837 px inside equal 1,384 × 861 document/root bounds, with no console/network error, overflow, or Projects route. Super-critical critique: helper and readiness-row labels remain faint and the amber update tier is low-contrast in light mode, so VA-014 remains open despite the otherwise clear hierarchy. |
| `work/Final Library Visual Audit/11 Shared CAD Pair Selector Narrow Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Shared KiCad+Altium pair selector, narrow workstation / dark | 1024×720 | `fda3196072f4` | Narrow-width functional pass: the 52 px rail, 341 px library pane, and 611 px representation workbench remain bounded with no document or region overflow; Projects is absent; both pairs and both tool columns remain simultaneously visible; the single atomic fallback action retains a real keyboard focus ring; zero per-tool activation actions exist. Super-critical critique: the fixed five-column readiness summary visibly truncates its rightmost 3D evidence at this width, retained-variant cards lose most evidence detail to ellipses, and the lower pair content requires inner scrolling. The workflow remains operable, but VA-018 remains relevant because evidence legibility degrades well before structural overflow is reported. |
| `work/Final Library Visual Audit/12 Components Loading Light.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Components initial network loading / light | 1384×861 | `c2b357e09fe9` | The isolated unresolved list request produces a stable, error-free loading frame with no overflow or Projects route; both picker and detail regions communicate that data is pending. Super-critical critique: `Loading parts...` and `Loading components...` duplicate one state across a nearly blank 1,332 × 837 workbench, neither gives progress or elapsed/recovery context, Add Parts and Search Parts appear actionable before the library resolves, and the footer prematurely asserts `0 Components`. This extends VA-005 from empty-state duplication into loading-state ambiguity and keeps VA-002/VA-014 relevant. |
| `work/Final Library Visual Audit/13 Components Error Dark.png` | `run_windowed` FastAPI + built SPA / Playwright Chromium window substitute | Components recoverable list-service error / dark | 1384×861 | `5ae9d7ed9e6f` | A deliberate 503 produces an honest inline reason plus Try Again, after the query layer's three bounded attempts; all three 503 responses and matching browser resource messages are explicitly classified as expected fixture evidence, while unrelated console/network failures remain zero. There is no overflow or Projects route. Super-critical critique: the detail pane simultaneously instructs `Select a part` when no list exists, Add Parts/Search Parts remain visually enabled, the footer again asserts `0 Components`, and the small low-contrast retry button is detached from most of the empty canvas. Error recovery exists, but VA-005/VA-014 remain and the screen does not explain whether adding can safely proceed during the outage. |
| `work/Final Library Visual Audit/14 Definitive Collect All Ledger Dark.png` | `run_windowed` FastAPI + current built SPA / Playwright Chromium window substitute | Definitive nine-route Collect All ledger / dark | 1384×861 | `14f736b82159` | Post-accessibility frozen-route authority: all nine terminal rows fit simultaneously, including all five declared DigiKey authors with exact labels—DigiKey CAD Models, SnapMagic, TraceParts, Manufacturer Provided, and CADENAS—plus three direct-provider routes and Texas Instruments Direct. The summary truthfully reports 5 of 9 settled; Manufacturer Provided is retained supplementary evidence, CADENAS is explicitly unavailable because no positive live download contract was measured, neither is activatable, and all seven status classes remain text-labelled. Essential heading, reason, neutral Unavailable, and semantic-status text now use tokens deterministically verified at 4.5:1 or better against the actual popover and both modal tint surfaces; the visual hierarchy is materially clearer without geometry change. There are zero unrelated console/network failures, overflow, or Projects routes. Super-critical critique: fitting nine reasoned outcomes still consumes nearly the entire 560 × 716 dialog with little vertical breathing room, this scrolled ledger authority hides the Files Complete heading and retry action above, and the top tab/step affordance remains visually quieter than route-status content. A separate top-state frame is still required to prove Files Complete versus collection Partial. This is not WebView2 host/DPI evidence. |
| `work/Final Library Visual Audit/15 Definitive Collect All Summary Dark.png` | `run_windowed` FastAPI + current built SPA / Playwright Chromium window substitute | Files Complete versus exhaustive collection Partial / dark | 1384×861 | `396060134dd4` | The post-accessibility scroll-top authority makes the non-contradiction explicit: the active KiCad+Altium files are complete while exhaustive collection is Partial, 5 of 9 routes are settled, and all five declared DigiKey authors remain simultaneously visible with exact labels and non-activatable supplementary semantics. The Files Complete explanation, Source Results heading, partial explanation, statuses, and route reasons are visibly stronger and covered by the 4.5:1 token contract; geometry is unchanged. The measured inner viewport is 603 of 979 px at scrollTop 0; dialog, body, and document remain bounded with zero unrelated errors or Projects route. Super-critical critique: `Files Complete` versus `Collection Partial` still requires reading two deliberately different scopes; the final direct-provider rows and Collect All retry action necessarily fall below this frame; the preferred-source helper text, tabs, and 3/4 step affordance remain much quieter than the result ledger. Read this frame with the full-ledger and bottom-action frames rather than alone. |
| `work/Final Library Visual Audit/16 Definitive Collect All Retry Dark.png` | `run_windowed` FastAPI + current built SPA / Playwright Chromium window substitute | Terminal route tail and retry / dark | 1384×861 | `e5b7f5582eae` | Post-accessibility scroll-bottom authority proves the terminal tail is not a dead end: TraceParts, Manufacturer Provided, CADENAS, Ultra Librarian Direct, SnapMagic Direct, SamacSys Direct, and Texas Instruments Direct retain their exact outcomes and clearer reasons; Collect All Sources is available again; Details and the anchored Done action remain reachable. The inner viewport is at its exact 376 px maximum scroll, with no document/dialog overflow, unrelated error, or Projects route. Super-critical critique: the route summary and first two successful DigiKey rows are necessarily outside this viewport, supplementary/non-activatable semantics still live in reason copy rather than a persistent structural badge, and the retry is visually modest for the primary recovery action; use this only with the summary/full-ledger frames. |
| `work/Final Library Visual Audit/17 Definitive Collect All Ledger Light.png` | `run_windowed` FastAPI + current built SPA / Playwright Chromium window substitute | Definitive nine-route Collect All ledger / light | 1384×861 | `93c5238fd7ba` | Post-accessibility theme-parity authority: all nine terminal rows, all five exact DigiKey labels, the 5-of-9 settled summary, Partial state, non-activatable retained Manufacturer Provided evidence, explicit unresolved CADENAS route, and all seven textual status classes remain simultaneously visible. The previous measurable light-theme failure is resolved: reason text and Source Results use the 6.1:1 neutral tier, Unavailable is no longer a borderline-subtle `text-t3` status, and green/amber/red route labels use semantic text tokens that clear 4.5:1 against the white popover and both tinted modal surfaces. The inner viewport is 603 of 979 px at scrollTop 124; geometry is unchanged and diagnostics contain no unrelated errors or Projects route. Super-critical critique: nine rows still leave almost no vertical rhythm and the preferred-source helper/progress affordances above the ledger remain markedly quieter; those are hierarchy/density observations, not a remaining contrast failure in the essential route ledger. |
| `work/Final Library Visual Audit/Empty Components Dark.png` | Playwright Chromium / isolated FastAPI fixture | Final empty Components / dark | 1384×861 | `2071c8b11f87` | Current-build regression: Projects is absent, Add Parts is the strongest available action, the rail and picker remain bounded, and there is no document overflow. Super-critical critique: `No Components Yet` still competes with the impossible `Select a part` instruction across a mostly empty detail pane; VA-005 remains open even though the source action itself is discoverable. |
| `work/Final Library Visual Audit/Empty Components Light.png` | Playwright Chromium / isolated FastAPI fixture | Final empty Components / light | 1384×861 | `f83f5d28a51b` | Geometry and action priority match dark mode and Projects remains absent. Super-critical critique: the white detail canvas amplifies the disconnected duplicate instruction, while the low-emphasis empty-state hint remains visually remote from Add Parts; VA-005/VA-014 remain visible. |
| `work/Final Library Visual Audit/Network Add Flow Dark.png` | Playwright Chromium / isolated FastAPI fixture | Final network-only Add a Part / dark | 1384×861 | `7f5749e47a2a` | Capability-language pass: exact identity and source evidence precede one shared KiCad + Altium + STEP package; available metadata, datasheet, provenance, source disagreements, and qualified-passive behavior are stated without a local-upload escape hatch. The modal is settled and unclipped. Critique: the numbered path and batch helper use a very quiet microtext tier, and `Preview Without Writing` remains implementation-oriented language. |
| `work/Final Library Visual Audit/Network Add Flow Light.png` | Playwright Chromium / isolated FastAPI fixture | Final network-only Add a Part / light | 1384×861 | `528fed0f877e` | Theme-parity capability pass with the same exact-MPN focus, retained-evidence promise, shared-package path, and bounded 720 × 432 dialog. The primary lookup remains unmistakable; the quiet helper/stage tier and disabled preview label remain the main visual-language weaknesses. |
| `work/Final Library Visual Audit/Settings Version And Update Dark.png` | Playwright Chromium / isolated FastAPI fixture | Final Settings version and automatic update / dark | 1384×861 | `8479a9865561` | Application Delivery, branch, installed revision, remote release, Current standing, automatic adoption while open, health check, and rollback semantics agree. No Projects navigation or overflow is present. Critique: readiness-row and explanatory helper contrast remains subdued, while revision identity is intentionally repeated between summary and detail. |
| `work/Final Library Visual Audit/Settings Version And Update Light.png` | Playwright Chromium / isolated FastAPI fixture | Final Settings version and automatic update / light | 1384×861 | `470dc9423ad4` | Theme-parity delivery pass with identical layout and update meaning; the user can tell this install is current and will converge without closing the app. Critique: pale helper text and readiness labels remain the weakest contrast tier, but no state depends on color alone. |
| `work/Final Library Visual Audit/Automatic Altium Setup Dark.png` | Playwright Chromium / isolated FastAPI fixture | Automatic Altium setup guide / dark | 1384×861 | `caf98438f791` | The guide now truthfully limits normal human setup to the SQLite ODBC prerequisite, then states automatic DbLib construction, installation, clean-close handling, fresh-session verification, profile-switch re-verification, and the shared STEP link/embed contract. Stale manual install and right-click-refresh instructions are gone. Critique: the diagnostic path is necessarily truncated and `0 of 0 parts` is technically correct but less natural than an explicit empty-profile message. |
| `work/Final Library Visual Audit/Automatic Altium Setup Light.png` | Playwright Chromium / isolated FastAPI fixture | Automatic Altium setup guide / light | 1384×861 | `929546893dd7` | Light-mode parity preserves the four-step automatic integration story, installed-driver proof, recovery-only Rebuild DbLib wording, and bounded modal geometry. The diagnostic path and dense explanatory tier are the only notable scanability costs; no manual-refresh contradiction remains. |
| `work/Final Library Visual Audit/Provider Sessions And Optional Sign-Ins Dark.png` | Playwright Chromium / isolated FastAPI fixture | Provider sessions and optional sign-ins / dark | 1384×861 | `f682ec8a6609` | The section now puts persistent provider sessions first, makes saved sign-ins optional for expired login walls, names Windows Credential Manager as the secret boundary, and explicitly leaves CAPTCHA/MFA to the person. DigiKey API and account credentials remain distinct. Critique: the repeated credential rows are inherently dense and require vertical scrolling, but their grouping and saved-state labels remain readable. |
| `work/Final Library Visual Audit/Provider Sessions And Optional Sign-Ins Light.png` | Playwright Chromium / isolated FastAPI fixture | Provider sessions and optional sign-ins / light | 1384×861 | `5a5942d5a646` | Theme-parity security pass: session reuse, optional saved sign-ins, Credential Manager storage, and CAPTCHA/MFA pauses remain unambiguous. Critique: disabled Save actions and placeholder text are intentionally pale and the lower provider rows fall below the viewport, but no control is clipped horizontally. |
| `work/Final Library Visual Audit/Shared Pair Selector Dark.png` | Playwright Chromium / isolated FastAPI fixture | Shared KiCad + Altium pair selector / dark | 1384×861 | `6672eae22be0` | Atomic-pair pass: Ultra Librarian is active in both tools, SnapMagic is a retained same-download fallback, both tool inventories expose the same provider choices, and the identical STEP filename is linked in KiCad and embedded in Altium. One whole-pair action replaces any divergent per-tool selection. Critique: evidence text is dense and the lower EDA handoff continues below the workbench viewport; `Altium Designer Only` applies to the Category handoff field, not the CAD-source set. |
| `work/Final Library Visual Audit/Shared Pair Selector Light.png` | Playwright Chromium / isolated FastAPI fixture | Shared KiCad + Altium pair selector / light | 1384×861 | `5165c6dda828` | Theme-parity atomic-selection pass with four retained variants, one active whole pair, one whole-pair fallback action, and the same STEP association in both EDA rows. Critique: compact evidence and lower handoff detail still demand deliberate reading, but provider/source divergence is not possible from this surface. |
| `work/Final Library Visual Audit/Complete Part Source Ledger Dark.png` | Playwright Chromium / isolated FastAPI fixture | Complete Part terminal provider ledger / dark | 1384×861 | `bd033ac0e6c1` | Terminal-ledger pass: cache, Ultra Librarian, SnapMagic, TraceParts, manufacturer, and SamacSys routes are all visible and settled as Activated, Retained, or Unavailable with explicit reasons; unavailable is correctly defined as checked with no exact deliverable. The detail checklist and anchored Done action remain visible. Critique: the audit intentionally scrolls past the beginning of the success paragraph to fit the complete ledger, and the reason tier is visually quiet. |
| `work/Final Library Visual Audit/Complete Part Source Ledger Light.png` | Playwright Chromium / isolated FastAPI fixture | Complete Part terminal provider ledger / light | 1384×861 | `1540fd8628af` | Theme-parity terminal pass: all six routes, their reasons, the complete state, four completed data fields, retryable Collect All Sources action, and Done control remain simultaneously inspectable. Critique: the scrolled success paragraph is partially hidden and secondary reasons are faint, but no route or outcome is hidden or color-only. |
| `work/Native Current Acceptance/Screenshots/Empty Library Dark.png` | pywebview / WebView2, current source | Empty Components / dark | 1384×861 | `d95161202089` | VA-005 resolution authority: one centered `No Components Yet` state, one Add Parts action, and no impossible selection prompt. VA-002/VA-004/VA-014 remain visible in the manual intake, unused canvas, and quiet helper tier. |
| `work/Native Current Acceptance/Screenshots/Empty Library Light.png` | pywebview / WebView2, current source | Empty Components / light | 1384×861 | `8c6de370703f` | Theme-parity VA-005 authority with identical geometry and action priority. The hint remains faint, so VA-014 is unchanged. |
| `work/Native Current Acceptance/Screenshots/Add Part Dark.png` | pywebview / WebView2, current source | Shared network intake / dark | 1384×861 | `68a9368a0e1a` | The working empty-state action opens one network intake that resolves identity and evidence before one KiCad + Altium + STEP package. The modal is bounded; the quiet workflow/helper tier keeps VA-002/VA-014 open. |
| `work/Native Current Acceptance/Screenshots/Add Part Light.png` | pywebview / WebView2, current source | Shared network intake / light | 1384×861 | `27b0b17c4f58` | Theme-parity intake authority. Exact capability text remains readable and the modal geometry is unchanged; muted secondary copy remains tracked by VA-014. |
| `work/Native Current Acceptance/Screenshots/Dual EDA Readiness Dark.png` | pywebview / WebView2, current source | Linked but unverified canary / dark | 1384×861 | `69e5844ff78e` | VA-001 negative-path authority: linked 3D, Symbol, and Footprint previews cannot grant completion; the compact state separately names KiCad Unverified and Altium Unverified. Large unused workbench space reconfirms VA-004/VA-013. |
| `work/Native Current Acceptance/Screenshots/Dual EDA Readiness Light.png` | pywebview / WebView2, current source | Linked but unverified canary / light | 1384×861 | `f09f10cbf417` | Theme-parity negative-path authority with identical readiness truth and projection geometry. Low-emphasis evidence remains under VA-014. |
| `work/Native Current Acceptance/Screenshots/Single Value Facet Dark.png` | pywebview / WebView2, current source | One-value parametric facet / dark | 1384×861 | `b3b3f66b5ad0` | VA-003 resolution authority: `channels` renders `Only value 6`, the result table carries one value, and no range slider, endpoints, or ticks exist. No document overflow or console error. |
| `work/Native Current Acceptance/Screenshots/Single Value Facet Light.png` | pywebview / WebView2, current source | One-value parametric facet / light | 1384×861 | `62a32dbd9549` | Theme-parity VA-003 authority with the same static fact and result semantics. The broad empty result canvas and faint generated-filter helper remain covered by VA-004/VA-014. |
| `work/VA Inspection Smoke/Inspection Dark 1384.png` | Chrome / source Vite + isolated API | Unified component inspection / dark | 1384×861 | `62e2c9c7f332` | VA-011 resolved; VA-017/VA-019 partial. One full-height neutral 3D stage, whole-object frame, truthful painted-geometry status, and no document overflow. |
| `work/VA Inspection Smoke/Inspection Light 1384.png` | Chrome / source Vite + isolated API | Unified component inspection / light | 1384×861 | `7f7b7eb14a6c` | Theme-parity source proof with identical 292×465 inspector geometry, 290×425 stage, selected 3D projection, whole-object frame, and no document overflow. |
| `local-only-dark-1024x720.png` | In-app Browser / Chromium | Projects repository setup / dark | 1024×720 | `b9d7ab35f60d` | Local and remote repository columns share one full-height workbench divider; no new finding |
| `local-only-light-1024x720.png` | In-app Browser / Chromium | Projects repository setup / light | 1024×720 | `15981201f091` | Split repository setup remains legible and has no document or sheet overflow; no new finding |
| `local-only-light-900x720.png` | In-app Browser / Chromium | Projects repository setup / light | 900×720 | `2992cf58913c` | The 621 px workbench stacks local facts above the remote action without horizontal overflow; no new finding |
| `local-only-light-1384x900.png` | In-app Browser / Chromium | Projects repository setup / light | 1384×900 | `27494a050763` | Wide repository setup uses a measured 394/616 px split and keeps one action hierarchy; no new finding |
| `no-git-dark-1024x720.png` | In-app Browser / Chromium | Projects missing-Git state / dark | 1024×720 | `252bc98fbae6` | Blocked state stays top-aligned, names the exact next action, and does not fabricate an unavailable control; no new finding |

## 2026-08-01 User-Facing Windows Acceptance Captures

All captures below came from a disposable library/config and the current source host unless the row names the self-contained WPF host. No real library content was mutated. Every visible state was reached through the Windows UI.

| Capture | Host / surface | Dimensions | SHA-256 | Visual audit |
| --- | --- | --- | --- | --- |
| `work/User Facing Acceptance 20260801/Screenshots/01 Empty Components Dark.jpg` | pywebview / Components | 1386×893 | `100718b1fba1` | One centered empty state and one Add Parts action pass VA-005. The very broad unused canvas and subdued helper tier keep VA-004/VA-014 open; the red fixture-only Update Blocked item incorrectly dominates this isolated frame. |
| `work/User Facing Acceptance 20260801/Screenshots/02 Empty Components Light.jpg` | pywebview / Components | 1386×893 | `3040b8b58652` | Light-theme parity preserves the single action and bounded rail. The faint helper copy and decorative pointer glow are more conspicuous on white, while the fixture-only blocked footer remains visually louder than the empty-state guidance. |
| `work/User Facing Acceptance 20260801/Screenshots/03 Add Parts Dialog Light.jpg` | pywebview / Add Parts transition | 1386×893 | `2f367d2f61e9` | The first observation caught the dimming/content state before the dialog painted; the underlying empty action stayed visible and no broken geometry appeared. The settled authority is the next frame. |
| `work/User Facing Acceptance 20260801/Screenshots/04 Add Parts Scrolled.jpg` | pywebview / Add Parts | 1386×893 | `14cccf71b181` | The intake settles into a bounded, centered dialog with exact lookup, one shared KiCad + Altium + STEP path, and a distinct list workflow. Disabled actions are truthful; the numbered microcopy remains quieter than the main task. |
| `work/User Facing Acceptance 20260801/Screenshots/05 Add Parts Filled.jpg` | pywebview / exact lookup | 1386×893 | `253c402b9f9f` | Entering an identity enables only Look Up and leaves list actions disabled. Focus and current value are clear, though the primary button sits far from the start of the long text field at this width. |
| `work/User Facing Acceptance 20260801/Screenshots/06 Add Parts Lookup Result.jpg` | pywebview / lookup progress | 1386×893 | `b62f98c07ef6` | The request locks duplicate submission and exposes an in-place stage. Provider implementation detail (`querying LCSC`) is useful diagnostics but competes with the user outcome and does not show elapsed or cancellation. |
| `work/User Facing Acceptance 20260801/Screenshots/07 Add Parts Lookup Final.jpg` | pywebview / exact-match rejection | 1386×893 | `e6b259cc0eb6` | The invalid identity receives a precise, non-destructive rejection and never exposes Add. Amber copy is readable but low-emphasis in light mode; the text correctly explains that near matches and blank replacements are refused. |
| `work/User Facing Acceptance 20260801/Screenshots/08 Batch Preview Result.jpg` | pywebview / non-writing preview | 1386×893 | `c715d0a40a31` | The preview completes with `1 Would Add` and explicitly reports that nothing needs attention. The result is honest and compact; `Preview Without Writing` remains implementation-oriented wording tracked by VA-002. |
| `work/User Facing Acceptance 20260801/Screenshots/09 Batch Preview Details.jpg` | pywebview / preview ledger | 1386×893 | `536154fac0db` | The expanded row preserves pasted identity, resolved identity, outcome, and CAD consequence in one line. `Needs Capture` is clear, but the detail lacks provider/evidence identity that would explain why the part is safe to add. |
| `work/User Facing Acceptance 20260801/Screenshots/10 Projects Workspace Light.jpg` | pywebview / Projects loading | 1386×893 | `30e259425ab3` | The two-project picker is immediately usable while the selected workbench loads. The centered loading text has no elapsed/retry context and leaves most of the screen blank, but the destination and selection are stable. |
| `work/User Facing Acceptance 20260801/Screenshots/11 Project Overview Light.jpg` | pywebview / Projects Overview | 1386×893 | `90ec7625d486` | The board-first three-pane structure, EDA/readiness label, document selector, and explicit Render/Open actions are legible. An empty scene still consumes the focal canvas and the generated fixture path/branch occupy more attention than useful design evidence. |
| `work/User Facing Acceptance 20260801/Screenshots/12 Project BOM Light.jpg` | pywebview / Projects BOM loading | 1386×893 | `ca66ac67a87a` | Tab selection is immediate and honest, but the full workbench collapses to a single loading label instead of retaining its stable skeleton or local controls. |
| `work/User Facing Acceptance 20260801/Screenshots/13 Project BOM Loaded Light.jpg` | pywebview / Projects BOM | 1386×893 | `0fb96f9f5f01` | BOM quantity, refresh/export, filters, selected line, link status, footprint, and board stage form a coherent workstation. The 0603 footprint wraps awkwardly in the narrow inspector and the empty scene still dominates. |
| `work/User Facing Acceptance 20260801/Screenshots/14 Project Build Light.jpg` | pywebview / Projects Build | 1386×893 | `e486ca0ec58c` | The blocked build state correctly explains that a clean snapshot is required and offers no unsafe start action. The left block is clear, though almost all remaining space becomes non-actionable empty board canvas. |
| `work/User Facing Acceptance 20260801/Screenshots/15 Project Activity Light.jpg` | pywebview / Projects Activity loading | 1386×893 | `d0cfc33f38fa` | Activity selection is visible and loading is bounded, but there is no retained work-session skeleton or recovery context while remote state resolves. |
| `work/User Facing Acceptance 20260801/Screenshots/16 Project Activity Loaded Light.jpg` | pywebview / Projects Activity failure | 1386×893 | `56ad8cf38ed8` | P1 VA-047: one raw missing-ref string replaces the entire Activity workbench. Local work, review state, and repository recovery are all absent despite ample space. |
| `work/User Facing Acceptance 20260801/Screenshots/17 STM Viewer Light.jpg` | pywebview / STM first run | 1386×893 | `cdce33c27cf1` | The first-run card clearly explains that a derived CubeMX index is needed and offers one Build the Index action. It does not preview source discovery or how a missing source will be repaired. |
| `work/User Facing Acceptance 20260801/Screenshots/18 STM Index Missing Source Light.jpg` | pywebview / STM recovery | 1386×893 | `a1394a324bc5` | P1 VA-048: the error exposes PATCH/environment-variable plumbing and only Try Again, giving a normal user no actionable way to choose CubeMX source inside Stockroom. |
| `work/User Facing Acceptance 20260801/Screenshots/19 Settings Light.jpg` | pywebview / Settings General | 1386×893 | `2ff1bbf49c40` | Delivery and machine-readiness summaries remain first-glance readable, category navigation is stable, and update semantics are explicit. The unmanaged disposable host correctly shows Blocked, but that fixture status dominates a screen otherwise showing three of four machine capabilities ready. |
| `work/User Facing Acceptance 20260801/Screenshots/20 Settings Library Light.jpg` | pywebview / Settings Library | 1386×893 | `86c477c19a15` | Separate-library Git ownership, active checkout, pull/push, and GitHub credential boundary are understandable. Long paths truncate safely; fixture branch/ahead state is visible without contaminating the application repository. |
| `work/User Facing Acceptance 20260801/Screenshots/21 Settings EDA Tools Light.jpg` | pywebview / Settings EDA Tools | 1386×893 | `ff06fe16d9be` | KiCad and Altium integrations use matched cards with automatic state first and recovery actions second. The explicit claim that opening Stockroom never launches Altium is contradicted by VA-046 later in this same acceptance run. |
| `work/User Facing Acceptance 20260801/Screenshots/22 Settings Data Sources Light.jpg` | pywebview / Settings Data Sources | 1386×893 | `9e65cef228c9` | Distributor APIs, procurement refresh, and provider sessions have distinct scopes. The first viewport makes DigiKey API/account boundaries visible, but credentials dominate vertical space before direct CAD providers appear. |
| `work/User Facing Acceptance 20260801/Screenshots/23 Settings Provider Sessions Light.jpg` | pywebview / provider credentials | 1386×893 | `520e43620931` | DigiKey, Ultra Librarian, SnapEDA, and SamacSys sign-ins are consistently grouped with saved-state labels. The form is necessarily dense; repeated full-width password rows offer little scan differentiation beyond provider headings. |
| `work/User Facing Acceptance 20260801/Screenshots/24 Settings Maintenance Light.jpg` | pywebview / Maintenance inherited scroll | 1386×893 | `c8a923c31c55` | P2 VA-049: switching from a scrolled Data Sources category opens Maintenance halfway down, clipping the component-completeness and presentation-data tasks even though the remaining cards are legible. |
| `work/User Facing Acceptance 20260801/Screenshots/25 Settings Maintenance Top Light.jpg` | pywebview / Maintenance top | 1386×893 | `f8d7552c73c9` | Once restored to the top, completeness, presentation rebuild, repair, binary storage, and destructive recovery follow a clear hierarchy. `All Complete` beside a zero-component library is technically consistent but reads more confidently than the empty state warrants. |
| `work/User Facing Acceptance 20260801/Screenshots/26 About Dialog Light.jpg` | pywebview / About | 1386×893 | `bf42dca75ca1` | The approved icon, product name, author, version, and external identities fit a compact modal. The isolated host's cached `0.1.0+aa7a649d` version is fixture evidence, not authority for the current source revision. |
| `work/User Facing Acceptance 20260801/Screenshots/27 Collapsed Navigation Rail Light.jpg` | pywebview / compact rail | 1386×893 | `83b525e43ee2` | The rail collapses to a consistent icon column and the Settings workbench expands without overlay or horizontal clipping. Active Settings remains identifiable by border/background, while Update and Theme remain reachable. |
| `work/User Facing Acceptance 20260801/Screenshots/28 Settings Maintenance Dark.jpg` | pywebview / dark-theme parity | 1386×893 | `8405904f52f1` | Dark theme preserves dense-card hierarchy, green/amber states, and bounded scrolling without whole-image inversion. Disabled recovery actions are visually quieter but remain legible. |
| `work/User Facing Acceptance 20260801/Screenshots/29 Projects Dark.jpg` | pywebview / Projects dark | 1386×893 | `52e54f6ce036` | Overview keeps the PCB center and document inspector readable in dark mode. Muted empty-canvas copy passes basic legibility; the broad no-placement region remains the dominant layout weakness. |
| `work/User Facing Acceptance 20260801/Screenshots/30 Altium Project Overview Dark.jpg` | pywebview / Altium project selection | 1386×893 | `5728db4d127a` | The selected Altium project identifies EDA, boards, local-only state, and loading workbench. No visible action was invoked, making the native launch captured next an unambiguous surprise. |
| `work/User Facing Acceptance 20260801/Screenshots/31 Altium Project Loaded Dark.jpg` | pywebview + native Altium splash | 1386×893 | `ce6239851c2d` | P0 VA-046 authority: Altium's splash obscures the Stockroom project after selection alone while Stockroom still says native previews are paused. This is the exact unwanted editor/command behavior the user reported. |
| `work/User Facing Acceptance 20260801/Screenshots/32 Altium Auto Launch Stopped Dark.jpg` | pywebview / interrupted auto-render | 1386×893 | `5728db4d127a` | After stopping only the generated scene-export process, Stockroom remains responsive but the placement map waits indefinitely with no failure or retry. The identical hash to frame 30 confirms no usable state change was communicated. |
| `work/User Facing Acceptance 20260801/Screenshots/33 Embedded Ultra Librarian Dark.jpg` | self-contained WPF host / embedded WebView2 | 1266×833 | `fe4934803515` | The provider stays inside a Stockroom-owned window with a persistent Return To Stockroom control, and login/search remain reachable. VA-045 remains: Ultra Librarian's hero begins beyond the left viewport edge at this width. |
| `work/User Facing Acceptance 20260801/Screenshots/34 Embedded Provider Search Result.jpg` | self-contained WPF host / Ultra Librarian search | 1266×833 | `edd8b9780875` | Exact MPN search returns Texas Instruments rows with availability, price, compliance, and three visible model-availability icons. Horizontal provider overflow is present but all core result actions and exact identity remain reachable. |
| `work/User Facing Acceptance 20260801/Screenshots/35 Embedded Provider Part Detail.jpg` | self-contained WPF host / Ultra Librarian part | 1266×833 | `f81cf6264b59` | Exact part detail visibly presents Symbol, Footprint, and 3D Model together under the Stockroom provider frame, proving the intended one-window discovery path. Provider-owned horizontal overflow and login/download below the fold remain, but identity and all three assets are unmistakable. |

## 2026-08-02 Native P-CAD Output Comparison

These live Altium Designer 26.8.1 captures compare the same ABM13W Ultra Librarian
P-CAD source after Altium's Import Wizard and after Stockroom's native converter.
They were inspected through Windows Computer Use at 05:00-05:04 EDT; the source
files and importer log remain under `work/Real ABM13W P-CAD Qualification`.

| Capture | Host / surface | Visual audit |
| --- | --- | --- |
| Live window `2026-07-27_20-09-29.SchLib` | Altium Designer 26.8.1 / Import Wizard output | Symbol geometry matches Stockroom's output: four numbered pins, grounded pin 2, central crystal, and outer body. Altium truncates the component name to `ABM13W-32.0000MH`; Stockroom retains the exact MPN and linked `ABM13W_ABR` model. |
| Live window `2026-07-27_20-09-29.PcbLib` | Altium Designer 26.8.1 / Import Wizard output | P0 conversion defect in the legacy importer, not a Stockroom visual defect: only generic `PCBCOMPONENT_1` is present with 0 pads and 0 primitives after the log reports skipped pattern tokens. This output cannot be the visual gold standard. |
| Live window `ABM13W-32.0000MHZ-5-DH7G-T5.PcbLib` | Altium Designer 26.8.1 / Stockroom converter output | All three provider variants are visible with four pads each and 52/52/60 primitives. The conspicuous asterisk-like mechanical graphics and diagonal line are also present in Ultra Librarian's same-bundle KiCad files, so they are provider geometry rather than renderer artifacts. |

## 2026-08-02 Live Verified ABM13W Component

The real Windows Stockroom source host was captured after durable publication commit
`fc26296` and a fresh live-index load.

| Capture | Host / surface | Visual audit |
| --- | --- | --- |
| Live window `Stockroom` | pywebview / WebView2, real Stockroom Library | The real ABM13W workspace visibly reports `KiCad Ready · Altium Ready`, renders the provider STEP in the central 3D viewport, and keeps exact identity, sourcing, product media, and specifications visible together. Open polish: the light-theme viewport has weak contrast between a nearly white model and mid-gray canvas; product-data tiles have inconsistent two-line density; and the bottom revision/update/library strip compresses four facts into one visual weight. None blocks CAD use or readiness truth. |
| Live window `Stockroom`, Symbol | pywebview / WebView2, real Stockroom Library | P0 acceptance regression resolved: the production-scoped ABM13W symbol now renders instead of `Preview unavailable`, reports both EDAs Ready, fits the complete body, and displays each pin designator once. The first successful frame exposed duplicated `1 1`/`2 2`/`3 3`/`4 4` labels; inspection proved the provider KiCad file repeats names while the P-CAD source says names hidden, so the preview now suppresses only exact name/number echoes. Open P2: this shared inspection surface is a KiCad projection even when both tools are Ready; the UI should identify the projection explicitly or offer an EDA comparison before it can serve as visual cross-EDA proof. |
| Live window `Stockroom`, Footprint | pywebview / WebView2, real Stockroom Library | P0 acceptance regression resolved: the production-scoped footprint and land-pattern endpoints render all four pads from the exact active candidate rather than failing against the old category library. Open P2: the thick courtyard dominates the tile and the preview omits pad numbers, polarity/origin, dimensions, and a visible EDA-projection label, so it proves presence but is a weak inspection tool for a very small four-pad package. |

## 2026-08-02 Live Verified TPD6E05U06RVZR Component

The second real production component was captured after durable publication commit
`598c4c5` and a fresh source-host restart against the independent Stockroom Library.

| Capture | Host / surface | Visual audit |
| --- | --- | --- |
| Live window `Stockroom`, Symbol | pywebview / WebView2, real Stockroom Library | P1 acceptance defect found and resolved: the published KiCad source contains a complete 15.24 × 25.4 mm rectangular body and eight electrical pins, but the preview fitter measured only SVG paths/circles and cropped the body because KiCad emitted it as `<rect>`. The fitter now covers standard SVG primitives, the cache version is advanced, and the live frame shows the complete body, seven visible terminals, and intentionally stacked hidden GND pin 10 without clipping. Open P2: this remains an unlabeled KiCad projection even while both EDAs report Ready. |
| Live window `Stockroom`, Footprint | pywebview / WebView2, real Stockroom Library | All fourteen provider pads and the complete courtyard are visible and whole-drawing fit is correct. Open P2: the source also contains Silk/Fab body edges, pin-one markers, and pad numbers, but the current copper/courtyard-only projection suppresses them; it proves geometry presence but is weaker than an editor-like inspection surface. |
| Live window `Stockroom`, 3D Model | pywebview / WebView2, real Stockroom Library | The exact shared STEP is rendered whole and aligned to all fourteen lands while both EDA readiness labels stay green. Open P3: for this very small USON package, the dark carrier/land plane occupies more visual area than the white component body; a component-weighted inspection framing option would improve first-glance recognition without changing geometry truth. |
| Live window `Stockroom`, Components overview | pywebview / WebView2, real Stockroom Library, dark, 1386×893 | Current reliability-repair acceptance: 3D, Symbol, and Footprint remain three simultaneous viewers, the restored 3D layer/view/appearance controls open in place, and KiCad/Altium readiness agrees below them. Open P2: long component names truncate in both the picker and title band with no visible secondary identity at this width; the revision/footer row also gives the dirty source build the old `8ebd17c` identity. |
| Live window `Stockroom`, standalone Symbol | pywebview / WebView2, real Stockroom Library, dark, 1386×893 | The owner-reported combined-inspector regression is resolved: opening Symbol exposes only the Symbol canvas, with no Footprint or 3D tabs. The complete twelve-pin projection fits without clipping. Open P2: the bottom-right zoom/Fit/SVG controls remain very small and low-contrast relative to the full-screen stage; enlarge the hit targets and labels without reducing canvas area. |
| Live window `Stockroom`, managed source fixture 0.5.2.0 | .NET WindowHost / WebView2, real Stockroom Library, dark, 1266×793 | Current source is visibly running through the release-owned managed host. Switching from `MAX17608ATC+` to `TPS2121RUXR` shows an honest `Loading part...` transition and then all three separate 3D/Symbol/Footprint viewers with `KiCad Ready · Altium Ready`; the earlier transient false `Unverified` verdict does not appear. Open P2: the fixture-only offline feed makes both the rail and footer say `Retrying...`, which is accurate for this isolated proof but visually louder than component work; long part titles also remain truncated at this width. |
| Live window `Stockroom`, TPS2121 guided collection | .NET WindowHost / WebView2, real Stockroom Library, dark, 1266×793 | The collection modal starts from one `Collect CAD Sources` action, re-verifies the installed projection, and backgrounds into a persistent `Capturing` pill that reopens correctly through its accessible control. Open P1: after provider activity, the modal still reports only `Provider Work Is Active`; it does not expose whether the visible browser download was received, accepted, rejected, or is still being processed, leaving the user unable to distinguish progress from a stalled workflow. |
| Live window `Stockroom`, embedded DigiKey TPS2121 | .NET WindowHost / embedded WebView2, real Stockroom Library, dark, 1266×793 | DigiKey remains inside the Stockroom-owned window and the signed-in account state is preserved. The native `Return To Stockroom` action returns immediately and preserves the background capture. Open P1: the normal provider page does not display the Stockroom/provider tab strip or capture HUD shown on security-gate pages, and WebView2's visible download tray exposes an opaque GUID-like filename, so source identity and download-capture standing are not understandable at the moment the user needs them. |

## 2026-08-02 Packaged Main App Acceptance

The normal `Stockroom.exe` launcher updated its clean continuous-runtime checkout to
GitHub `main` at `873fd8be5ca9`, preserved the live `Stockroom Library` selection, and
opened the real two-component library without launching KiCad or Altium.

| Capture | Host / surface | Visual audit |
| --- | --- | --- |
| Live window `Stockroom`, TPD6E05U06RVZR 3D Model | packaged launcher / continuous-runtime WebView2 | Exact shared STEP, fourteen lands, `KiCad Ready · Altium Ready`, two-component count, canonical library name, and `Current` update standing are simultaneously visible. The component-weighted framing observation remains the already-tracked P3; no release-blocking defect is present. |
| Live window `Stockroom`, ABM13W Symbol | packaged launcher / continuous-runtime WebView2 | The complete four-pin crystal drawing, unique pin designators, grounded pin 2, both EDA readiness badges, and `Current` update standing remain visible after the GitHub update. The existing unlabeled-projection P2 remains; no new finding. |
| Live window `Stockroom`, ABM13W Footprint | packaged launcher / continuous-runtime WebView2 | Four lands and the complete provider outline remain whole-drawing fitted after update. The existing thick-outline/pad-label P2 remains; no new finding. |
| Live window `Stockroom`, TPD6E05U06RVZR Symbol | packaged launcher / continuous-runtime WebView2 | The formerly cropped body is fully visible with all intended terminals and the complete lower GND region. Both EDA readiness badges and `Current` remain stable; no new finding. |
| Live window `Stockroom`, TPD6E05U06RVZR Footprint | packaged launcher / continuous-runtime WebView2 | All fourteen lands and the full rectangular outline remain visible after the continuous-runtime update. The existing copper-only projection P2 remains; no new finding. |

## 2026-08-03 Managed CAD Intake Repair

| Capture | Host / surface | Visual audit |
| --- | --- | --- |
| Live window `Stockroom`, 0.5.3.1 SN74HCS11QDRQ1 overview | .NET WindowHost / WebView2, real Stockroom Library, dark, 1266×793 | The same real component visibly holds separate 3D, Symbol, and Footprint viewers after DigiKey activation. The 3D stage opens in source-color/realistic mode and the PCB, copper, and pads have stable separated silhouettes with no visible z-fighting. Open P2: the icon-only appearance choices remain difficult to distinguish without hover text. |
| Live window `Stockroom`, 0.5.3.1 embedded DigiKey | .NET WindowHost / embedded provider WebView2, real Stockroom Library, 1266×793 | Native Stockroom, Provider, Back, and Forward controls survive provider reloads. Switching Provider → Stockroom → Provider returns to the same active DigiKey task while automatic capture continues. The first pass exposed two host-chrome defects: the selected tab became low-contrast under Windows hover and WebView2's delayed download tray exposed a GUID. Both became source fixes rather than accepted polish debt. |
| Live window `Stockroom`, 0.5.3.1 completion modal | .NET WindowHost / WebView2, real Stockroom Library, dark, 1266×793 | `Processing Downloaded Files` now says the route output is being validated, converted, and attached as KiCad, Altium, and STEP; the user is explicitly told no manual import is required. The modal remains available while the provider tab is open. Open P2: elapsed time is visible but per-provider route progress is still available only after completion, so exhaustive secondary-provider collection can look longer than the already-successful primary mapping actually was. |
| Live window `Stockroom`, 0.5.3.2 embedded DigiKey hover | .NET WindowHost / embedded provider WebView2, real Stockroom Library, 1266×793 | The Provider label stays dark and legible against the native light hover surface. The header remains stable over DigiKey's product, modal, loading, and security-verification documents. The delayed GUID tray remained visible and therefore failed this visual acceptance; 0.5.3.2 is not the final tray authority. |
| Live window `Stockroom`, 0.5.3.4 embedded DigiKey completion | .NET WindowHost / embedded provider WebView2, real Stockroom Library, 1266×793 | Final repair authority: the native header clearly states that KiCad + Altium + STEP capture is automatic, both DigiKey downloads progress and complete without WebView2's opaque GUID flyout appearing, and Provider → Stockroom → Provider preserves the exact DigiKey page while the modal reports background conversion/attachment. Hover text remains legible. Open P2: the header's long guidance line is intentionally quiet but approaches the right edge at this minimum audit width; responsive shortening below 1,100 px would improve polish without changing the workflow. |
| `work/Release 0.6.0 Verification/Source Theme One.png` | pywebview / WebView2, real Stockroom Library, dark, 1386×893 | Release-source authority: the final bundle exposes one **Get CAD Files** action, separate 3D/Symbol/Footprint viewers, realistic source-color 3D, and matching KiCad/Altium readiness. Existing P2s remain the truncated long component names and compact icon-only 3D controls; no release-blocking regression or overflow is visible. SHA-256 `387038c75aef8952a6095b1115323edc721141cefe57eb5f2ae022ff580f61fa`. |
| `work/Release 0.6.0 Verification/Source Theme Two.png` | pywebview / WebView2, real Stockroom Library, light, 1386×893 | Theme-parity authority preserves the same layout, action priority, representation separation, model appearance, and readiness truth. The white model remains distinguishable from the neutral stage; no whole-image inversion, clipped action, or horizontal overflow is visible. SHA-256 `6a9c9b307caf4236409f37dcd15e41d0dcc3c23a036fd703857cbeff6c9580f6`. |

### 2026-08-03 — Stockroom 0.7 Clean-Profile Startup Failure

- Capture layer: Computer Use against the exact reproducible `0.7.0` candidate with empty
  app/config/tools/Python/browser caches and a prerequisite-scrubbed `PATH`.
- Visible result: the native error boundary correctly surfaced `ModuleNotFoundError: No module
  named 'PIL'` from `altium/project_visuals.py` instead of silently exiting.
- Audit: the dialog is legible and actionable for engineering, but too traceback-heavy for an
  end user. The release blocker is the missing production Pillow dependency; a later polish item
  should summarize the primary error and put the traceback behind a details affordance.
- Disposition: release-blocking dependency boundary fixed in source; the candidate remains
  rejected until the same clean profile opens the real Stockroom window.

### 2026-08-03 — Stockroom 0.7 Clean-Profile Success

- Capture layer: Computer Use against the repaired `0.7.0` candidate with empty app, config,
  tools, Python, and Playwright directories plus a prerequisite-scrubbed `PATH`.
- Onboarding: the first-run library choice stayed inside the Stockroom window, named the default
  library destination, exposed the alternative-library action, and replaced its primary action
  with explicit working feedback while initialization completed. The deliberately long isolated
  acceptance path wrapped heavily; a normal `%LOCALAPPDATA%` path is materially shorter.
- Main workspace, dark and light, 1386×893: the application reached the real Components route,
  showed the intentional `No Components Yet` state, kept Add Parts primary, exposed the active
  `.bootstrap-library`, and reported `Current` rather than `Update Unknown`. The compact icon rail
  is internally consistent but remains less self-describing than the expanded rail for a first-time
  user. No clipping, horizontal overflow, modal residue, or theme-parity defect was visible.
- Disposition: clean-profile visible startup and onboarding pass. Runtime proof also confirmed the
  installed native CAD converter, exact Python, bundled Git/Git LFS, Node/npm, signed WebView2
  bootstrapper, Chromium cache, and real Git LFS payloads; the final release asset still requires
  one exact-byte clean-profile rerun after the reproducible rebuild.

### 2026-08-03 — Stockroom 0.7 Exact-Asset Clean-Profile Acceptance

- Capture layer: Computer Use against `dist/Stockroom.exe`, SHA-256
  `d64a79a0003380bc53b7927d6e98331eeed0b781742fb69e8d1a49226f0b19a5`, built reproducibly
  from clean pushed source `3c173369aadd0aa6ee91b5f00c4627d0a97fc039`.
- Onboarding, dark, 1386×893: the exact release bytes opened the real in-window setup surface from
  an empty isolated profile and prerequisite-scrubbed `PATH`. Open Existing, Create New, and Clone
  From Git remain understandable; the long acceptance-only default path wraps to a second line but
  stays inside its card. The action immediately changed to disabled `Working...` feedback.
- Main workspace, dark, 1386×893: default-library creation completed without a second window or
  stale modal. The empty Components state, Add Parts action, active `.bootstrap-library`, and green
  `Current` update standing are all visible with no clipping or horizontal overflow. Open P2: the
  compact navigation rail still depends on recognizable icons until expanded.
- Runtime correlation: the running checkout is the exact build revision; Python 3.12.13/Pillow,
  bundled Git/Git LFS and Node/npm, Chromium, four non-pointer LFS CAD assets, and the installed
  converter were inspected from the isolated tree. A native conversion produced and read back one
  symbol and one footprint without Altium. No release-blocking visual or runtime defect remains.
