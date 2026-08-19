# Guided Setup And UI Cohesion Plan

## Outcome

Stockroom should guide a person from first launch to a ready daily workspace, require one primary
CAD tool choice, keep every screen visually and structurally related, respond immediately to safe
edits, and never launch Altium or provider work merely because someone added a component.

The primary CAD tool is a per-machine preference. The shared library may retain KiCad and Altium
assets because collaborators can use different tools. Choosing one tool controls setup, completion,
provider format defaults, readiness, and UI emphasis. Switching tools later must retain every asset
and recalculate the work needed for the newly selected tool.

## Premise Check

- **Uneven and complicated screens: Supported.** The 44-screen gallery shows inconsistent page
  frames, several competing toolbar grammars, repeated status boxes, dense Settings disclosures,
  and workflow steps that live far from the work they affect.
- **Adding a component launches Altium setup every time: Weakened for current commit, supported in
  the completion path.** At `686d813d`, `/api/ingest/commit` writes the identity and does not call
  Altium. The frontend then opens the new component. However, guided capture constructs
  `IngestPipeline(auto_embed_altium_models=True)`, so completion can launch Altium to embed a model.
  Dual-EDA copy and defaults also make each new component appear to require both tools. The plan
  removes every automatic CAD process from Add and moves Altium materialization to an explicit
  queue.
- **Optimistic rendering is incomplete: Supported.** Stockroom retains previous query data and
  writes some authoritative mutation results directly into cache, but most mutations still wait,
  invalidate, and refetch. There is no shared snapshot, optimistic patch, rollback, and reconcile
  interface.
- **Latest development state is not baked into Git: Disproved at the repository layer.**
  `development` and `origin/development` both resolve to `686d813d969c6f1480e9d7bde78dcbca60db3623`,
  and the full Windows gate proved the committed distribution matches source. A stale running
  development window remains possible. This plan ends with a new verified branch head and a fresh
  source-host launch receipt.

## Product Decisions

Owner decisions from the structured interview:

1. Stockroom optimizes first for a PCB engineer maintaining and using their own reusable catalog.
   Team collaboration remains first-class but does not dominate daily interaction.
2. Every machine must choose exactly one primary CAD tool: `kicad` or `altium`.
3. The preference is switchable and non-destructive. Existing files for the other tool remain.
4. New and migrated users confirm the choice. Discovery may recommend a tool but may not choose one
   silently.
5. First-run setup requires only a primary CAD tool, a usable catalog, and a working selected-tool
   connection. Optional source and maintenance integrations remain skippable.
6. Add Component performs identity, evidence, and record creation only.
7. Add Component defaults to **Add And Continue**, leaves the Add Session open, and never opens a
   provider page, launches KiCad or Altium, runs Altium setup, or embeds a model.
8. Adds accumulate pending EDA Catalog Projection changes without rebuilding the tool catalog.
   **Build Now** coalesces all pending changes into one Catalog Build; no automatic catalog build runs
   after Add or on app close.
9. Missing CAD assets belong to the separate, grouped, non-interrupting **Assets** workspace.
   Provider Visits and CAD-tool launches wait for explicit action.
10. Altium setup is one explicit machine-level operation. Adding another component never repeats it.
11. Altium model embedding runs only inside an explicitly confirmed Assets Catalog Build. One
    Stockroom-owned Altium session processes the selected batch; verified embedded output becomes a
    canonical CAD Asset in the Catalog Repository, while DbLib/index output remains derived.
12. Stockroom uses balanced professional density and progressive disclosure. Healthy optional
    integrations do not dominate the UI; problems and next actions receive emphasis.
13. Delete removes an item immediately with Undo. Its provisional Catalog Tombstone synchronizes
    only after Undo expires; backend or connectivity failure restores the exact item. Simple inline
    edits autosave optimistically on Enter or blur; complex forms keep **Save Changes**.
14. Stockroom requires current GitHub connectivity for normal use. During an internet or GitHub
    outage, block the product behind one human-readable Offline state and automatically retry. Resume
    and reconcile without a button or restart when connectivity returns.
15. Navigation and selection render trusted cached state immediately; heavy previews load
    independently and no refetch blanks the screen.
16. Keep the current component-workspace structure. Improve its hierarchy, alignment, controls,
    discoverability, and visual finish rather than replacing it with a new tab architecture.
17. Preserve Stockroom's current owner-authored dark and light themes. Improve IA, hierarchy,
    spacing, alignment, control consistency, and interaction clarity rather than applying a new
    visual style.
18. Offer Mouser and DigiKey official API connection as one optional, skippable setup step with a
    plain explanation of exact specifications, price, stock, lifecycle, and datasheet benefits.
19. Inside Assets, show Catalog Build state as one quiet fact such as **Current**, **18 Pending**, or
    **Building** with details on demand. Do not put a count in the rail. Notify only on failure or
    completion of **Build Now**.
20. At narrow widths, preserve the component list, CAD previews, and readable Specifications; move
    Sourcing into an easy side sheet. Normal widths retain the current simultaneous columns.
21. Keep Datasheet, permanent Manage CAD Assets, and More in the component header. Move Manufacturer
    Page, destructive actions, and diagnostics into More; the visible MPN remains click-to-copy.
22. A ready app opens Components. Broken essential setup opens the exact repair step instead.
23. First-run setup must create or connect a GitHub-backed Catalog Repository, choose its local
    folder with an Explorer picker, detect the selected CAD installation, and configure it.
24. Settings uses grouped, action-first sections with sticky category navigation over one mounted,
    page-owned scroll. Human terms lead; unfamiliar paths, identifiers, and diagnostics stay in
    Details.
25. Rename **STM Viewer** to **Tools** in the main rail. When CubeMX is absent, Tools opens its setup.
    Selecting an MCU replaces the all-MCU comparison with that MCU's focused table and information.
26. Projects deep-link missing BOM records and incomplete parts to the exact Catalog or CAD action.
27. Distinguish **Quick Search** from **Parametric Search**.
28. Show one Readiness Verdict at the component top. Hover, keyboard focus, or activation opens a
    compact explanation; repeated status badges elsewhere are removed.
29. Condense Sourcing into clear disclosures with only **Price Breaks** open initially. Use one Price
    Breaks section containing both Mouser and DigiKey provider rows. Preferred Source leads,
    otherwise the strongest in-stock source is labeled Suggested. Each provider's first real tier is
    inline with its name. Beneath it, show up to four additional tiers; if that additional count is
    odd, omit the last compact tile. **All Price Breaks** exposes every omitted provider, offer, and
    tier without loss.
30. Repository creation asks Public or Private, while setup also supports connecting an existing
    Catalog Repository. GitHub uses browser sign-in; users never paste tokens.
31. Never ask a user to type a filesystem path. Use a managed default folder and Windows Explorer
    pickers, with **Open In Explorer** wherever the location matters.
32. Catalog Sync is automatic and has no Sync button. The latest GitHub-accepted same-field value
    becomes active while displaced values, authorship, source, and time remain in history. For a
    delete-versus-edit collision, the latest accepted operation controls visibility and deletion
    creates a restorable Catalog Tombstone. A quiet footer shows Synced, Syncing, Offline, or Review
    Available. Review Available is informational and never blocks sync, editing, Catalog Build, or
    startup.
33. Settings category tabs are sticky scroll anchors over one mounted page, not hiding tabs.
34. Tools uses a compact family/MCU picker and a focused selected-MCU workspace for Summary, Pinout,
    Peripherals, Memory/Clock, Packages/Ordering, Documents, and Add To Catalog.
35. The widened Add Component modal accepts exactly one MPN or product URL at a time and uses a
    persistent right Add Session tray for Added, Adding, Failed, Review Needed, Existing, and CAD
    Needed records. Closing ends the session, clears successful rows, and preserves unfinished work
    in Assets. An exact existing component is never duplicated; offer **Open
    Component** and **Refresh Evidence**.
36. **Build Now** exists only in the main-rail **Assets** workspace. Assets lists every component with a
    Missing required CAD Asset or whose latest accepted record is absent/outdated in the primary EDA
    Catalog Projection. Symbol and Footprint are always required; only the shared 3D Model may be
    explicitly **Not Available**, with no required note. Projects keeps its current picker/detail
    structure while gaining direct BOM-to-Catalog actions, one readiness summary, and exact issue
    links.
37. Repository creation lets the signed-in user choose a personal account or organization, suggests
    **Stockroom Catalog** as an editable name, and asks Public or Private.
38. Components opens with no component selected and shows only **Select A Component** in the
    workspace. The component header follows the current-theme compact action cluster: identity and
    one Readiness Verdict lead; **Datasheet**, permanent **Manage CAD Assets**, and **More** form the
    right action group. Catalog Build actions never appear here.
39. Stockroom teaches itself through a dismissible, resumable First Workflow using real controls and
    a searchable, context-aware in-app Help panel opened from the rail footer or local **Learn More**
    links. After setup, Components opens with the compact Help side panel and First Workflow active;
    quiet progress remains in the rail footer after dismissal. Completion requires one real
    end-to-end component through Catalog Build plus use of every main useful screen. The HUD allows
    Skip or Stop at any time and Settings always offers **Run First Workflow Again**. Help covers
    tasks, domain language, and recovery without exposing developer internals.
    Normal screens use plain labels and progressive explanation; empty/error states say what
    happened, whether work was preserved, and
    one exact recovery action.
40. Optimize discoverability for mouse use. Preserve normal Tab, focus, activation, and accessibility
    semantics, but do not make hidden shortcuts or command-palette knowledge part of the expected
    workflow.
41. Main rail order is **Components**, **Assets**, **Projects**, **Tools**, **Settings**. Assets shows
    no pending badge and opens with neither **Needs Assets** nor **Build Now** selected; the person
    chooses the task. Help and theme controls remain in the rail footer.
42. Verified updates download silently and show **Update Ready** with a person-started **Restart When
    Convenient**. Never restart automatically or during Add, Assets Build, Provider Visit, project
    mutation, or unsaved interaction.
43. During a requested Primary CAD Tool switch, the old tool remains visibly primary with **Switch
    Pending** until its active work finishes. Then the new tool activates and Assets recomputes.
44. Every Catalog Build, including one headless KiCad component, receives one concise confirmation;
    no per-component confirmations appear inside a batch.
45. If connectivity drops during a mutation, roll the mutation and its optimistic UI back completely,
    enter Offline, and accept no further work until automatic reconnection succeeds.

## Phase 1: Primary CAD Tool Contract

Add a typed `primary_eda` field to `MachineConfig`, the redacted Settings DTO, onboarding status,
and frontend types. Keep it out of library records.

Create a deep `PrimaryEdaPolicy` module. Its small interface answers:

- which tool is primary;
- which capture requirements apply by default;
- which setup checks are essential;
- which Settings integration is promoted;
- which optional other-tool assets remain retained.

Do not scatter `if primary_eda == ...` through pages and workflows. The EDA registry remains the
source of tool capabilities. `PrimaryEdaPolicy` combines the machine choice with registry data.

Migration behavior:

- New install: no default; onboarding requires confirmation.
- Existing install: show a one-time choice with the strongest detected tool preselected as a
  recommendation, not an accepted answer.
- Switching: preserve all data and let an already-running operation finish under its captured old
  tool. Keep the old tool visibly primary with **Switch Pending**. Activate the new Primary CAD Tool
  afterwards, then recompute setup readiness and Assets.

## Phase 2: Guided Setup

Replace the current library-only welcome card with one setup flow:

1. **Choose CAD Tool**: KiCad or Altium, with one sentence explaining what Stockroom configures.
2. **Catalog Repository**: authenticate with GitHub, create or connect the required repository, and
   choose its local folder through Explorer.
3. **Connect The Tool**:
   - KiCad: locate the installation and config, wire the catalog, and state whether KiCad must
     restart.
   - Altium: locate Altium and ODBC, prepare the local DbLib, and complete its one-time setup. If an
     interactive launch is technically unavoidable, say so before continuing.
4. **Improve Source Data**: explain optional Mouser and DigiKey credentials. Skipping them must not
   block readiness.
5. **Ready**: show the exact repository, primary tool, integration state, and first action.

Persist each completed step so a restart resumes at the right point. The setup page owns one clear
primary action. Errors stay beside the failed step with a direct recovery action.

After onboarding, Settings starts with the same compact Setup Summary. A person can change the CAD
tool or repair one failed step without reading every maintenance capability.

## Phase 3: Add Many Components Without Interruption

Refactor Add Component into a repeatable intake workspace:

- Keep the source input focused after a successful add.
- Default action: **Add And Continue**.
- Secondary action: **Add And Open**.
- Show a persistent right-side session tray of added, adding, failed, and CAD-needed components.
- Accept one MPN or product URL at a time; do not add multiline intake or a bulk-import island.
- Remove `capture.requestOpenFor(created.id)` from the default success path.
- Remove stale Complete Part continuation copy and delete the unreferenced `CompletePartModal` after
  proving no production caller remains.

A new component may show **CAD Needed** in Components. It must not interrupt intake. Add **Assets**
to the main rail. It lists all components with Missing required CAD Assets or absent/outdated primary
EDA Catalog Projection records. The Assets landing page starts with one large full-width **Add
Parts** action; the retired **Import A List** island does not appear in Add Parts. Provide **Needs
Assets** and **Build Now** as the only primary views, with built history available secondarily.
Symbol and Footprint remain required; only 3D Model offers
**Not Available**. Provide **Build Selected** and **Build All Ready**, safe machine batches,
person-driven focused Provider Visits, and Catalog Build actions. Completing or skipping a Provider
Visit returns to the same list position.

Add an acceptance test that adds 25 active components and proves:

- zero Altium process launches;
- zero provider routes;
- zero KiCad process launches;
- all 25 records appear without reopening the app;
- each add resolves serially and the intake remains ready for component 26.

## Phase 4: Explicit CAD Preparation

Change guided capture defaults from both tools to `PrimaryEdaPolicy.requirements()`. Guided capture
remains person-started. Missing assets join Assets; it never opens a Provider Visit or CAD tool on
its own. Clicking a supported provider row is the person's start action: show browser chrome
immediately and begin that exact task-bound Provider Visit without a separate **Open Provider**
button. One row means one chosen provider visit: it never advances through that provider's hidden
author or fallback ladder, even when no file lands. A Provider Visit settles automatically after
its required downloads land; switching rows cancels the whole old provider workflow durably before
opening the newly selected provider, with no manual **Done With Provider** or **Skip This Part**
controls. A direct provider choice may use that provider's measured MPN search when no exact DigiKey
media route exists; attachment validation still binds every accepted file to the exact component.
Unsupported sources retain **Open Listing** because they cannot safely own captured bytes.
Copy-on-write preparation and retained-evidence checks run behind navigation rather than
delaying it. The provider surface has one live guide strip: before navigation it asks for a provider;
when ready it names the exact files to download; during intake it shows the filename and progress;
after intake it reports files found, verification, interruption, or attachment readiness. Browser
chrome stays compact and read-only—Back, Forward, Reload, truthful current address, and Hide—with
no duplicate instruction block or persistent recovery action during an active visit. Provider
choices are compact names only; per-provider Complete Set and Symbol/Footprint/3D summaries are not
part of this action strip. Repeated unchanged viewport reports are deduplicated before native HWND
placement so workflow polling cannot flash the embedded browser. A confirmed Altium-only attachment
updates the component's canonical Altium asset references and immutable evidence immediately; it does
not embed or publish those assets into the CAD tool catalog. That remains a separate Assets Catalog
Build.

Track Catalog Build generations without starting work after Add. Each canonical component change
increments the desired projection generation. Assets' **Build Now** updates only the selected
primary tool's ready affected records when possible and records the completed generation. A restart
reconstructs pending work from the generation mismatch instead of trusting an ephemeral task file.
Altium DbLib/SQLite and KiCad catalog projection may run headlessly. Interactive tool launch remains
forbidden except for an explicitly confirmed Stockroom-owned Altium Assets batch. Any accepted
component change returns its record to **Build Now**. A 25-component Add
Session followed by one Assets build produces one coalesced build, not 25 rebuilds. Independent
component successes remain current when another component fails; failed rows stay pending with exact
recovery.

For KiCad-primary machines:

- request KiCad symbol, footprint, and shared STEP only;
- never query or launch Altium as part of completion;
- retain extra Altium files from a provider bundle as inactive evidence if they arrive, without
  making them required.

For Altium-primary machines:

- request native Altium symbol, footprint, and shared STEP;
- attach and verify the native libraries without starting Altium;
- add model embedding to the Altium preparation queue;
- update the machine-local DbLib silently without rerunning setup.

Set `auto_embed_altium_models=False` in person-driven capture. Replace per-part embedding with one
explicit Assets batch. Every **Build Selected** and **Build All Ready** action receives one concise
confirmation. An Altium confirmation also says Altium will open and names the component count. If
Altium is already open, Stockroom waits for the person to close it and never controls their live
design session. The target implementation opens one Stockroom-owned Altium session for the selected
queue, processes every safe item, independently reads back each result, commits each verified
embedded Altium asset to the Catalog Repository, updates the derived local DbLib/index, and closes
normally. If one-session batching is blocked by Altium automation limits, the fallback may use
several launches only after the person starts the batch. It may never return to per-add launches.

## Phase 5: Honest Optimistic Rendering

Create one `OptimisticCommand` interface around TanStack Query:

1. cancel conflicting reads;
2. snapshot affected query documents;
3. apply a typed local patch;
4. mark the exact entity `saving`;
5. submit an idempotent command;
6. replace provisional data with the authoritative response;
7. restore the snapshot and show one actionable error on backend or connectivity failure.

Use it for:

- primary CAD selection;
- safe Settings fields and toggles;
- metadata edits;
- source preferences;
- add-component pending rows;
- project and component selections;
- component deletion through an immediate provisional Catalog Tombstone plus Undo; synchronize only
  after Undo expires.

Use pending rendering without an optimistic success claim for:

- catalog switching and Git sync;
- CAD writes and verification;
- provider navigation and downloads;
- KiCad wiring and Altium setup;
- release installation and rollback;
- destructive external operations that cannot be restored through a Catalog Tombstone.

If connectivity drops during any mutation, cancel/roll back the command atomically before entering
the blocking Offline state. Accept no further mutation until automatic reconnection and reconciliation
succeed.

Keep prior content visible during refetch. Use skeletons only for a true first load. Prefetch a
component dossier when a row receives hover or keyboard focus. Centralize query keys and
invalidation sets so each mutation does not maintain its own list.

## Phase 6: Screen Information Architecture

### Components

Keep the current master/detail engineering workspace: catalog rail, component list, identity header,
three fitted CAD previews, Specifications, and Sourcing visible together. Refine rather than replace:

- establish one strong current-theme component header with identity, one Readiness Verdict,
  Datasheet, Manage CAD Assets, and More;
- align column headers, search fields, tabs, and action baselines;
- show only **Select A Component** when nothing is selected; make the current selection and next
  useful action obvious after selection;
- reduce repeated labels, borders, badges, and healthy-state emphasis;
- keep Model, Footprint, and Schematic visible and fitted; clicking opens an inspector only;
- make permanent **Manage CAD Assets** enter a focused in-app workspace that temporarily replaces
  Specifications and Sourcing while preserving the component list and header;
- open Main Specifications and the category's most important electrical group initially; collapse
  secondary groups with row/issue counts and expand search matches;
- let a specification row reveal value, source, confidence, alternatives, and edit/review actions
  inline;
- preserve every sourcing and specification fact through progressive disclosure;
- let missing-data actions focus the exact control that resolves them;
- collapse contextual detail before shrinking core data below readable density;
- preserve category-grouped component rows and add CAD Needed, Review Needed, and Recently Added
  filters.

### Projects

Keep project selection on the left and preserve the current overall structure. Use Overview, BOM,
Build, and Recent Work as one consistent tab bar. Add one project readiness summary, direct **Add To
Catalog** actions for missing BOM records, and exact links from incomplete records and build issues
to their owning Catalog or CAD control. Show the right inspector only when a placement or record is
selected. Empty canvases must state what selection or action produces content; do not replace the
screen with a generic dashboard-card home page.

### Tools

Rename STM Viewer to **Tools** in the main rail. When CubeMX is not configured, show one focused
setup state that detects the installation, explains what Stockroom configures, and runs setup without
a typed path. If CubeMX is absent, open the official download page only after an explicit action and
then retry detection. After selecting an MCU, replace the comparison table with the focused Summary,
Pinout, Peripherals, Memory/Clock, Packages/Ordering, Documents, and Add To Catalog workspace.

### Assets

Use one main-rail workspace with **Needs Assets** and **Build Now** as the only primary views; built
history remains secondary. Each compact row shows Symbol, Footprint, and 3D Model state plus one next
action. Provider acquisition remains one-component-at-a-time and person-driven. After a download,
propose asset mappings with compact previews and require **Apply Attachments**. Batch only
deterministic local validation, attachment, selected-tool preparation, and build work. Successful
current rows leave the pending views immediately. No Catalog Build action appears elsewhere.

### Settings

Keep one page-owned scroller and mounted content. Add sticky scroll-anchor categories and begin with
a collapsible, issue-first Setup Status summary. Group content as:

1. Setup;
2. Catalog And Sync;
3. Selected CAD Tool;
4. Source Data And Accounts;
5. Maintenance;
6. About.

Promote the selected CAD tool. Render the other tool as one optional collapsed row with **Switch CAD
Tool**, not as a full equal-priority setup burden. Healthy maintenance detail stays collapsed;
problems open automatically.

### Dialogs And States

Use one dialog width system, header grammar, footer grammar, focus contract, and action order. Empty,
loading, offline, and error states each answer: what happened, what the person can do, and whether
existing data is still safe.

## Phase 7: Visual System And Code Quality

Build shared page-frame, pane-header, toolbar, property-grid, setup-step, empty-state, and async-action
modules. Use ASTRYX Card, Banner, TextInput, Link, Kbd, Selector, Stepper, and status primitives where
they preserve Stockroom semantics. Keep the shell, CAD canvases, virtualized data, provider HWND,
and engineering evidence surfaces custom.

Retain the current owner-authored theme tokens and palette. Apply one spacing ladder, one 32px
control height, one 34px pane-header height, 2px geometry, and one page gutter per viewport. Use
cards for setup widgets, not dense rows. Use status color only for a condition that needs attention
or confirms a requested operation.

Remove stale dual-EDA copy, dead completion code, duplicate state derivations, undefined token use,
and broad cache invalidations. Action labels must match completion and toast language exactly.

## Phase 8: Delivery And Acceptance

Deliver in scoped commits. Every frontend commit includes its synchronized `app/frontend-dist`.
Do not rewrite published history.

Acceptance requires:

- first-run KiCad and Altium paths completed separately on Windows;
- switching the primary tool without deleting either tool's retained assets, including visible
  **Switch Pending** until old-tool work finishes;
- 25-component uninterrupted add test with zero CAD/provider launches;
- explicit Altium Assets batch launch, canonical embedded-asset commit, derived local projection,
  independent component readback, and refusal to control an already-open Altium session;
- one confirmation for every KiCad and Altium Catalog Build, with no per-component batch prompts;
- optimistic success, connectivity rollback, duplicate-submit, restart, and stale-response tests;
- optimistic delete remains unsynchronized through Undo, restores on failure, and synchronizes its
  Catalog Tombstone only after expiry;
- first launch offline, runtime disconnect, authentication failure, automatic reconnect, and
  mutation rollback while the app blocks normal use;
- Provider Visit proves all page controls remain person-operated and completion/skip returns to the
  exact Assets list position;
- First Workflow proves real-control progress, every main useful screen, Skip, Stop, resume, Help
  search/context, and **Run First Workflow Again** from Settings;
- Settings proves sticky category anchors over one mounted, page-owned scroller;
- update download, protected-work deferral, and person-started **Restart When Convenient**;
- all screen families captured in dark and light at 1,400 × 900 and the real 1,100 × 650 native
  viewport;
- keyboard, focus, reduced-motion, DPI, and WebView2 inspection;
- measured first interaction and screen-change latency with no refetch blanking;
- ASTRYX Doctor, frontend check triage, npm audit, `git diff --check`, deterministic dist, and
  `scripts/Gates.ps1`;
- a fresh Stockroom Development launch from the final branch head;
- `HEAD == origin/development`, with only approved ignored runtime artifacts left untracked.

The final branch head, generated distribution, acceptance captures, visual audit, Current State, and
checkpoint must all name the same commit.
