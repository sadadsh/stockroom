# Projects Workspace Rebuild Plan

**Status:** Approved, Phase 0 implementation in progress
**Owner:** Stockroom
**Scope:** Two-person KiCad 10 and Altium Designer 26 collaboration through a shared Git repository
**Decision:** Rebuild Projects as a visual PCB collaboration editor and BOM maker

## Locked Product Direction

Projects is the shared working surface for two people developing one PCB project.

It should feel like a PCB editor:

- project tree;
- schematic and PCB canvas;
- pan, zoom, search, select, and cross-probe;
- component properties;
- BOM editing;
- live guided PCB population;
- collaborator presence and document ownership;
- visual and semantic change overlays;
- review comments attached to design objects.

It should not become a second geometry engine. Traces, vias, polygons, schematic
wiring, footprints, board outline, layer stack, and native rule configuration remain
authoritative in KiCad or Altium. Stockroom opens the exact document and object in
the native editor for those changes.

Stockroom owns the collaboration layer the native files do not provide consistently:

- safe two-person Git workflow;
- document-level edit ownership;
- normalized visual and semantic comparison;
- review and approval;
- BOM authoring and Stockroom catalog links;
- inventory and procurement context;
- step-by-step manual assembly guidance and traceability;
- native validation orchestration;
- reproducible release packages.

The product promise is:

> Open the shared project, see who is changing what, edit and review the BOM,
> populate the physical boards with live guidance, then synchronize without
> overwriting either person's work.

## Decision Record

### Current Hypothesis

A useful dual-EDA Projects product is a visual collaboration editor, BOM maker, and
safe Git client. It is not a KiCad settings mirror and not merely a build dashboard.

### Evidence

- Altium's external Git workflow explicitly identifies conflicts when two designers
  edit the same document and provides native schematic/PCB comparison.
- Altium's Workspace collaboration uses document edit visibility and soft locks to
  prevent simultaneous conflicting edits.
- KiCad 10 exposes Git status in its project manager and provides CLI seams for
  native exports and checks.
- Hardware collaboration tools center visual/semantic diffs, review comments,
  approval, automation, and releases.
- Stockroom already has Git sync, Git LFS detection and locking probes, atomic
  transactions, project parsing, native KiCad CLI access, and an Altium automation
  bridge. These are stronger foundations than the removed frontend used.

### Rejected Framings

1. **KiCad settings dashboard:** makes Altium a reduced mode and duplicates the EDA.
2. **Build-readiness dashboard only:** useful, but too narrow for two people sharing
   live project files.
3. **Full cross-EDA PCB geometry editor:** would require Stockroom to recreate two
   mature editors and safely round-trip incompatible native formats.

### Next Discriminating Prototype

Before the production UI is rebuilt, prove one vertical two-person workflow in two
clones for each EDA:

1. open and render the project;
2. acquire ownership of one design document;
3. change one BOM identity field;
4. view the semantic and visual diff;
5. push a review branch;
6. review it from the second clone;
7. approve and merge;
8. update the first clone;
9. demonstrate that a competing same-document edit is blocked and recoverable.

If that prototype cannot be made safe for both EDAs, implementation stops before a
large frontend is built.

### Current Phase 0 Evidence

Implemented:

- a production Git LFS lock-service wrapper with strict JSON validation;
- work-session preflight against Git, remote synchronization, branch identity, and
  document claims;
- partial-lock rollback;
- claimed-document-only commits and work-branch push;
- lock-loss refusal;
- isolated-worktree review;
- exact-commit approval and fast-forward integration;
- lock retention until the shared commit is observed as integrated.

Automated evidence:

- two disposable clones and a bare remote;
- paired KiCad `.kicad_pcb` and Altium `.PcbDoc` collaboration paths;
- same-document exclusion and different-document concurrency;
- changed-after-review refusal;
- remote-main-advanced refusal with both histories retained;
- mid-session lock-verification outage with uncommitted work retained;
- explicit forced-unlock command separation;
- no force push, binary merge, or working-copy replacement.
- real GitHub LFS acquire, observe, release, and absence-after-release round trip;
- installed KiCad 10.0.4 BOM, ERC, and DRC execution against the real fixture with
  byte-identical source before and after;
- existing real AD26 `.SchDoc` component and Stockroom identity readback retained
  in the paired native evidence suite.

Still required before Phase 0 is complete:

- real KiCad render/BOM-write/reopen and real Altium `.PcbDoc`
  render/BOM-write/reopen/semantic validation;
- injected lock-expiry and forced-unlock recovery evidence through the full session
  state machine.

## Hard Parity Rule

Every Projects tool ships for KiCad and Altium together.

Parity means the same:

- route and action;
- collaboration state;
- user input;
- normalized result;
- preview and review workflow;
- commit, push, merge, and recovery guarantees;
- receipt and acceptance evidence.

Native implementations may differ. A tool cannot be hidden, weakened, or moved into
an EDA-specific area for one project type.

Runtime availability is not product availability. If the required native runtime or
locking service is unavailable, the same tool remains visible with an actionable
blocked state.

## What The Audit Found

### Current Product

- The current application has no Projects route. Commit
  `821891bc7874499ccb442cb324607decf8d575a1` removed the old page, viewer, and
  navigation entry.
- The backend can register `.kicad_pro` and `.PrjPcb` projects and extract enough
  placement data for basic BOMs.
- Stockroom already has:
  - fast-forward Git sync and remote status;
  - GitHub credential integration;
  - Git LFS status and remote locking probes;
  - atomic Git-backed mutations;
  - KiCad CLI checks and output seams;
  - an Altium automation and native-document bridge.
- Project code is concentrated in large services:
  - `api/routers/projects.py`: 621 lines;
  - `mutation/project_ops.py`: 1,682 lines;
  - `projects/bom.py`: 1,371 lines.

### Removed Projects Page

- `ProjectsPage.tsx` was 5,530 lines with a 3,222-line test file.
- Selection used a permanent 348 px list and absolute folder-path entry.
- The primary tabs were `Overview`, `Health`, `BOM & Procurement`, `PCB Setup`,
  and `Net Classes`.
- Altium support was implemented by hiding KiCad-only actions.
- The page did not provide a coherent two-person work, review, and sync protocol.

The rebuild must replace the product model and backend seams, not restore that page.

## External Research

### Altium

Altium's official external version-control documentation establishes several
important collaboration constraints:

- Git repositories are managed outside Altium while file status, commit, update,
  comparison, and conflict actions can be surfaced inside the editor.
- A conflict occurs when two designers edit the same file and one pushes first.
- Schematic and PCB revisions require native logical/graphical comparison.
- A correct release begins from an up-to-date source snapshot and generates outputs
  from that snapshot.
- Altium's connected collaboration model adds visible collaborators and document
  soft locks because version control alone does not prevent conflicting edits.
- Altium warns that its own Git integration does not fully support LFS repositories.
  Stockroom must therefore qualify its external Git/LFS behavior against real AD26
  open/save cycles and must not assume that Altium's internal VCS client is safe for
  LFS operations.

Sources:

- [Using External Version Control](https://www.altium.com/documentation/altium-designer/using-external-version-control)
- [Git-Based Version Control](https://www.altium.com/documentation/altium-designer/using-external-version-control/git)
- [Collaborators And Conflict Prevention](https://www.altium.com/documentation/altium-designer/collaborators-visualization-conflict-prevention)

### KiCad

KiCad 10 exposes project Git state and official CLI operations for BOM export,
ERC/DRC, and jobsets. KiCad source files are textual, but raw line diffs can contain
tool-generated and ordering noise. Collaboration still needs object-aware
comparison and post-merge native validation.

Sources:

- [KiCad 10 Project Manager](https://docs.kicad.org/10.0/en/kicad/kicad.html)
- [KiCad 10 Command-Line Interface](https://docs.kicad.org/10.0/en/cli/cli.html)

### Hardware Collaboration Pattern

Git-native hardware collaboration products consistently combine:

- visual PCB/schematic inspection;
- semantic revision comparison;
- contextual comments;
- automated checks;
- review and approval;
- a named release tied to a repository revision and manufacturing artifacts.

Sources:

- [AllSpice Quick Review](https://learn.allspice.io/docs/quick-review)
- [AllSpice Design Reviews](https://learn.allspice.io/docs/design-reviews-101)
- [AllSpice Hardware Releases](https://learn.allspice.io/docs/create-a-release)

### BOM And Inventory Pattern

Electronics inventory products treat the project BOM as the bridge to build
quantity, stock, substitutes, shortages, purchasing, and build history.

Sources:

- [PartsBox Projects And BOMs](https://partsbox.com/users-guide.html)
- [PartsBox Production Builds](https://partsbox.com/builds.html)
- [PartsBox Purchase Lists](https://partsbox.com/purchase-lists.html)

## Product Model

### Repository

One linked project belongs to one local Git working copy and one configured remote.
The exact `.kicad_pro` or `.PrjPcb` descriptor identifies the PCB project inside
that repository.

Stockroom records:

- repository root and remote;
- default branch;
- project descriptor;
- EDA and qualified native version;
- Stockroom project schema version;
- collaborator identity;
- library/catalog binding;
- native output recipes;
- ignored/generated file policy.

The repository remains standard Git. Stockroom does not create a proprietary source
store.

### Work Session

A work session is a bounded claim to edit one or more project documents from a known
base commit.

It records:

- person and machine;
- work branch;
- base branch and commit;
- claimed design documents;
- remote lock identifiers;
- start and expiry time;
- current local/remote state;
- source digests;
- recovery branch if needed.

The session is not a cosmetic presence indicator. It is the safety boundary for
opening a native document for editing.

### Review

A review compares one pushed work branch with its recorded base and contains:

- source and target commits;
- files changed;
- rendered before/after or overlay views;
- semantic design changes;
- BOM changes;
- validation delta;
- comments attached to object identifiers and source digests;
- requested changes or approval;
- merge and release-lock receipt.

Review events are append-only, uniquely named files so two reviewers do not edit one
shared JSON blob.

### Release

A release binds an approved commit to:

- variant and intended build quantity;
- normalized BOM;
- catalog and inventory snapshot;
- validation reports;
- native output recipe;
- fabrication and assembly artifacts;
- tool versions and hashes;
- approved exceptions and notes.

### Assembly Run

An assembly run is a durable, local real-time session tied to an immutable project
snapshot, BOM variant, and board quantity.

It records:

- source commit and semantic project digest;
- BOM and placement snapshot;
- board serial or run position;
- operator;
- reserved inventory lots;
- every Done, Skipped, Reworked, and Issue event;
- selected placement, side, orientation, and expected part;
- actual scanned part/lot when used;
- elapsed time;
- inventory consumption and reversal;
- completion receipt.

Git remains the source synchronization system, not the live assembly database.
Assembly events persist immediately in Stockroom's workflow store so a crash does
not lose progress. The completed receipt and immutable summary may be committed to
the project repository.

## Information Architecture

Projects has one persistent Project Lens and five routes:

```text
┌ Projects ──────────────────────────────────────────────────────────────────┐
│ [ NETDECK · Altium ▼ ]  main ← sadad/power-fix  Synced 2m ago             │
│ Main.PcbDoc: You are editing · Power.SchDoc: Alex is editing              │
│                               [Open In Altium] [Review And Share Changes]  │
├────────────────────────────────────────────────────────────────────────────┤
│  Design       BOM       Assemble       Changes 4       Releases            │
└────────────────────────────────────────────────────────────────────────────┘
```

Git and collaborator state are always visible. They are not hidden in a separate
generic Git page while a project is being edited.

## The Smart Toolset

### 1. Project Switcher And Repository Setup

- Open an exact `.kicad_pro` or `.PrjPcb` with a native picker.
- Clone a remote repository or link an existing working copy.
- Detect multiple project descriptors in one repository.
- Search recent and favorite projects.
- Relocate a moved working copy.
- Verify remote, branch, identity, native runtime, library/catalog binding,
  `.gitignore`, generated files, and lock-server readiness.
- Provide **Open In KiCad** or **Open In Altium** everywhere.

Manual path entry remains an advanced fallback.

### 2. Design

Design is a canvas-centered collaboration surface.

Layout:

```text
┌ Project Tree ─────┬ Design Canvas ───────────────────────┬ Properties ─────┐
│ Schematic         │                                      │ U4               │
│  Power            │      rendered sheet or PCB           │ TPS62130RGTR     │
│  MCU              │      with comments, locks,            │ Production: Fit  │
│ PCB               │      selections, and diff overlay     │ Stockroom: SR-42 │
│  Main Board       │                                      │ [Edit BOM Data]  │
└───────────────────┴──────────────────────────────────────┴──────────────────┘
```

Shared controls:

- pan, zoom, fit, layer/sheet selection;
- search by reference, value, MPN, net, comment, or Stockroom part;
- select and cross-probe objects;
- show component, pin/net, footprint, placement, and BOM properties;
- display who is viewing or editing each document;
- add, reply to, resolve, and reopen contextual comments;
- compare working state with base or review target;
- open the selected object in the native EDA.

Editable from Stockroom:

- value and description;
- manufacturer and MPN;
- Stockroom Part ID;
- DNP/fit state and supported native variant membership;
- project-specific approved substitute;
- collaboration notes and review resolution.

These writes use native object identifiers and adapter transactions. Stockroom does
not edit connectivity or geometry.

### 3. BOM

BOM is an authoring surface, not a report generated at the bottom of the page.

- Build automatically from the selected native variant.
- Group placements into editable lines while retaining every object mapping.
- Edit supported BOM properties inline or in bulk.
- Match or replace a Stockroom catalog link.
- Mark DNP/fit state and approved substitutes.
- Show inventory, location, available quantity, order quantity, price breaks, MOQ,
  lifecycle, stock, lead time, and provenance.
- Calculate buildable quantity and shortages for any requested build quantity.
- Generate a combined purchase list.
- Export generic and assembler-specific BOMs.
- Show the BOM diff for the current branch or review.

A BOM edit produces a preview of every affected native component and sidecar fact,
then one commit-ready transaction. Both EDAs use the same edit grid, issue codes,
and receipt.

### 4. Assemble

Assemble guides prototype and short-run manual PCB population from the exact board
and BOM that were reviewed.

Layout:

```text
┌ Assembly BOM ─────────────┬ Live Board ───────────────────┬ Current Part ───┐
│ 18 / 87 lines complete    │                               │ C1-C12           │
│ ▶ 100 nF · 0402 · 12      │    highlighted placements     │ GRM155R71C104... │
│   10 kΩ · 0402 · 8        │    auto-fit and side flip      │ Bin A-14         │
│   TPS62130 · QFN · 1      │    pin-1 / polarity marker     │ Need 12 · Have 84│
│                           │                               │ [Done] [Issue]   │
└───────────────────────────┴───────────────────────────────┴──────────────────┘
```

Workflow:

- start from an approved release or a pinned, validated source snapshot;
- choose variant, number of boards, board identifier, and inventory locations;
- reserve the selected inventory without prematurely consuming it;
- group placements by BOM line, package, side, storage bin, or user-defined order;
- select a BOM line to highlight every placement;
- select one designator to pan, zoom, and flip to its exact board position;
- show orientation, pin 1/polarity, value, footprint, MPN, manufacturer, part image,
  datasheet, storage location, lot, and remaining quantity;
- scan a part, reel, bag, bin, or Stockroom label to verify identity before
  placement;
- reject a scan that does not satisfy the selected BOM line or approved substitute;
- mark an individual placement or grouped line Done, Skipped, Reworked, or Issue;
- advance with large controls and keyboard shortcuts suitable for bench use;
- persist every action immediately and resume at the exact next placement;
- show board, line, placement, and elapsed-time progress live;
- finalize inventory consumption from the reservation when a board or run is
  completed;
- release or reverse unused reservations on cancel/rework;
- produce a build receipt tied to the project commit, BOM, operator, inventory lots,
  and assembly events.

The board view is deliberately usable without a 3D model. A clean 2D top/bottom
view with placement outline, orientation, pin-1 marker, and unambiguous highlight is
the release requirement. 3D bodies, camera alignment, projector guidance, AOI, and
foot-pedal hardware integrations are future enhancements behind the same assembly
event contract.

An active assembly run is invalidated if the project source, variant, BOM identity,
or placement snapshot changes. The user can finish against the pinned snapshot or
start a new run; Stockroom never silently moves a physical build onto newer files.

Primary source:

- [Altium Assembly Assistant](https://www.altium.com/documentation/altium-365/assembly-assistant)

### 5. Work Sessions And Locks

**Start Work**:

1. verify the working tree and preserve any existing local changes;
2. fetch the remote;
3. require an up-to-date base or show the exact incoming change;
4. create or resume the person's work branch;
5. acquire server-backed locks for selected native design documents;
6. record the base commit and source digests;
7. open the project in Stockroom or the native EDA.

Lock policy:

- schematic and PCB documents are one-writer by default for both EDAs;
- different documents may be edited concurrently;
- a user can inspect and comment on a locked document;
- lock owner, age, branch, and machine are visible;
- stale-lock recovery requires evidence that the owner session is expired and
  creates an auditable override receipt;
- no collaborative write session starts when the remote lock service is absent or
  unqualified.

Stockroom reuses its existing Git LFS locking probe and CLI integration. It does not
invent a second locking protocol. Native source files remain ordinary Git blobs
unless real AD26/KiCad qualification proves a particular LFS content policy safe.

### 6. Changes And Review

Changes answers:

> What did this person change in the design, BOM, and build outcome?

It contains:

- branch/base/remote state;
- file changes;
- schematic and PCB visual before/after or overlay;
- components, nets, placements, properties, and rules changed;
- BOM lines added, removed, or changed;
- inventory, shortage, substitute, cost, and sourcing consequences;
- ERC/DRC/compile regression delta;
- comments and review checklist;
- commit history for the work session.

**Review And Share Changes**:

1. ensure native documents are saved and stable;
2. compute source digests;
3. render and normalize the diff;
4. rebuild the BOM;
5. run native checks;
6. present a commit preview and require a meaningful message;
7. create a scoped commit;
8. push the work branch using normal Git compare-and-swap behavior;
9. keep edit locks until approval, merge, withdrawal, or explicit handoff.

The second collaborator can review without replacing their working tree. Stockroom
uses an isolated disposable worktree to render the review branch.

Approval and merge:

- approval is tied to the exact reviewed commit;
- any new push makes approval stale;
- merge rechecks the target branch and all document locks;
- safe, disjoint changes may integrate;
- same-document binary conflicts are never auto-merged;
- KiCad text merges must pass semantic parse, native reopen, and validation before
  acceptance;
- a rejected push or changed target never triggers a force push;
- local work is preserved on a named recovery branch before conflict handling.

### 7. Sync

The Project Lens provides one truthful synchronization state:

- **Synced**
- **Local Changes**
- **Ahead**
- **Behind**
- **Review Pending**
- **Locked By Collaborator**
- **Conflict Risk**
- **Offline**
- **Authentication Required**

**Sync** never means blind pull then push.

- Readonly fetch may happen automatically.
- Working-tree mutation is always previewed when local changes exist.
- Fast-forward updates are automatic only when the tree is clean and no work session
  would be invalidated.
- Divergence opens Changes with both histories and recovery options.
- Generated and ignored native files never silently enter a commit.
- Credentials remain machine-local.

### 8. Releases

An approved commit can become a release:

1. pin the source commit and project digest;
2. rebuild the native BOM and selected variant;
3. verify Stockroom catalog identity;
4. run current native validation;
5. run the selected `.kicad_jobset` or `.OutJob`;
6. collect fabrication, assembly, BOM, drawing, and validation artifacts;
7. create a content-addressed manifest and release receipt;
8. push the release record and tag without rewriting history.

The Releases route shows the latest package, artifact manifest, previous releases,
and design/BOM comparison between releases.

## What Stays In The Native EDA

| Native Editing Task | Stockroom Behavior |
| --- | --- |
| Add/remove schematic symbols | Open the correct sheet and location in KiCad/Altium |
| Draw or reconnect schematic wires | Inspect, diff, comment, and cross-probe only |
| Place/move footprints | Inspect, diff, comment, and cross-probe only |
| Route traces, vias, zones, polygons | Inspect layers and diffs; edit natively |
| Board outline and mechanical geometry | Inspect and diff; edit natively |
| Stackup and layer configuration | Display release-relevant summary; edit natively |
| Net classes and design rules | Display/diff/validate; edit natively |
| Footprint pad or symbol-pin editing | Use the native library editor |
| Output recipe authoring | Run and report existing jobsets/OutJobs |

This is the deliberate meaning of “like a PCB editor”: Stockroom has the visual
workspace and object model needed for collaboration, BOM authoring, and review, but
does not claim geometry-authoring parity it cannot safely deliver.

## Collaboration Safety Contract

### Files

The repository setup policy classifies every path:

- canonical design source;
- portable library/config source;
- collaboration metadata;
- release record;
- generated output;
- cache/temp/backup;
- large binary asset.

Stockroom proposes `.gitignore` and `.gitattributes` changes, explains every rule,
and commits them only after approval. It never guesses that an unknown native file
is disposable.

### Locks

- Locks are server-backed and verified before the editor is opened for writing.
- The lock binds repository, path, owner, and work session.
- Losing network access does not discard local work, but prevents final share/merge
  until ownership is reconciled.
- An unlock cannot discard uncommitted source.
- Forced unlock is explicit, evidence-backed, and retained in review history.

### Git

- No force pushes.
- No destructive reset.
- No automatic binary conflict resolution.
- No pull into a dirty tree without a previewed recovery operation.
- No merge approval after the reviewed commit changes.
- No release from an unpushed or ambiguous source state.
- Every Stockroom mutation commits exact scoped paths.

### Native Validation

Every integrated change must:

- parse through the adapter;
- reopen through the qualified native runtime;
- preserve stable object identity;
- rebuild the normalized BOM;
- run relevant ERC/DRC/compile checks;
- report new, fixed, and unchanged findings separately.

## Architecture

### Project Adapter

Add a registry-backed family under `stockroom.projects.adapters`.

```python
class ProjectAdapter(Protocol):
    key: str

    def detect(self, candidate: Path) -> list[DetectedProject]: ...
    def describe(self, descriptor: Path) -> ProjectDescription: ...
    def runtime(self, project: ProjectRecord) -> RuntimeReport: ...
    def documents(self, project: ProjectRecord) -> list[ProjectDocument]: ...
    def variants(self, project: ProjectRecord) -> list[ProjectVariant]: ...
    def scene(self, project: ProjectRecord, source: SourceRef) -> DesignScene: ...
    def bom(self, project: ProjectRecord, request: BomRequest) -> NativeBom: ...
    def semantic_diff(
        self, project: ProjectRecord, before: SourceRef, after: SourceRef
    ) -> DesignDiff: ...
    def validate(self, project: ProjectRecord, source: SourceRef) -> ValidationRun: ...
    def plan_bom_write(
        self, project: ProjectRecord, request: BomWriteRequest
    ) -> BomChangePlan: ...
    def apply_bom_write(
        self, project: ProjectRecord, plan_id: str
    ) -> ChangeReceipt: ...
    def restore_bom_write(
        self, project: ProjectRecord, receipt_id: str
    ) -> RestoreReceipt: ...
    def output_recipes(self, project: ProjectRecord) -> list[OutputRecipe]: ...
    def run_output(self, project: ProjectRecord, recipe_id: str) -> OutputRun: ...
    def open_native(self, project: ProjectRecord, target: DesignTarget | None) -> None: ...
```

Constraints:

- EDA branching exists only inside adapters and adapter registration.
- Shared API, collaboration engine, normalization, Git workflow, and React
  components never branch on EDA.
- Both adapters implement the complete protocol.
- The same contract suite runs against real paired fixtures with no EDA skips.
- Parser fallback may support readonly recovery, but authoritative rendering,
  editing, validation, diff, and release require qualified native semantics.

### Native Adapter Mapping

KiCad:

- project: `.kicad_pro`;
- scene: parsed/native schematic and PCB data plus CLI exports;
- BOM: `kicad-cli sch export bom`;
- diff: stable object IDs, normalized connectivity/placement/property comparison,
  and rendered overlays;
- validation: `kicad-cli sch erc` and `kicad-cli pcb drc`;
- BOM writes: byte-preserving semantic S-expression transactions;
- outputs: `kicad-cli jobset run`.

Altium:

- project: `.PrjPcb`;
- scene: compiled project and SDK object enumeration;
- BOM: ActiveBOM/Report Manager authority;
- diff: SDK/native comparison evidence normalized to shared objects and renders;
- validation: compile/project validation and PCB DRC through the managed bridge;
- BOM writes: Parameter API, variants, and ECO through the managed extension;
- outputs: `.OutJob` through the bridge.

Stockroom never edits `.SchDoc` or `.PcbDoc` bytes directly.

### Shared Models

- `ProjectRecord`: exact descriptor, repository, remote, branches, EDA, documents,
  variants, runtime, catalog binding, and recents.
- `DesignScene`: sheets/board, layers, objects, geometry, nets, properties, native
  IDs, source locations, and render assets.
- `NormalizedBom`: placements, native object mapping, grouping, variant/DNP,
  identity, Stockroom link, inventory, and provenance.
- `WorkSession`: owner, branch, base, locked documents, source digests, lease, and
  recovery state.
- `DesignDiff`: file, object, net, placement, property, BOM, validation, and visual
  changes.
- `ReviewRecord`: immutable target commits, append-only comments/events, approvals,
  findings, and merge receipt.
- `AssemblyRun`: pinned source/BOM/placement snapshot, operator, boards, reservations,
  placement events, issues, inventory effects, progress, and completion receipt.
- `ReleaseRecord`: source/catalog/BOM digests, native runs, artifact manifest,
  exceptions, and receipt.

### Git Collaboration Service

Extend the existing `stockroom.vcs` registry and `GitRepo` wrapper rather than
creating a second Git implementation.

Responsibilities:

- repository inspection and setup plan;
- fetch-only remote observation;
- branch and upstream state;
- worktree-safe review snapshots;
- Git LFS lock probe, acquire, list, verify, and release;
- scoped commit and normal push;
- merge preflight and integration;
- recovery branch creation;
- `.gitignore`/`.gitattributes` policy;
- redacted receipts and error classification.

All network and Git mutations run as durable jobs. Status reads remain local unless
the user explicitly refreshes or the background fetch policy is enabled.

### Collaboration Metadata

Use a versioned `.stockroom/` directory in the project repository:

```text
.stockroom/
  project.json
  assemblies/
    <assembly-id>/
      receipt.json
  reviews/
    <review-id>/
      review.json
      events/
        <ulid>.json
  releases/
    <release-id>/
      manifest.json
```

Rules:

- metadata references native objects by adapter ID plus source digest;
- review events are immutable and uniquely named;
- live assembly events remain in the workflow store; only completed immutable
  receipts enter the repository;
- credentials, machine paths, lock tokens, caches, and live inventory counts are
  never committed;
- release manifests contain snapshots/digests, not mutable machine configuration.

### Host And Frontend

Host:

- native project picker;
- adapter-mediated open-at-target;
- no remote content access to the host bridge.

Frontend:

- thin `ProjectsPage.tsx` shell;
- focused components under `components/projects/`;
- virtualized project tree, object list, BOM, changes, and comments;
- render canvas isolated from app state;
- one shared query/view-model contract for both EDAs;
- existing tokens, primitives, copy registry, TanStack Query, jobs, and resumable
  events.

## Delivery Plan

The Projects route remains absent from production until the paired collaboration
prototype and core safety gates pass.

### Phase 0: Two-Clone Collaboration Evaluation

- Create equivalent KiCad and Altium fixture repositories with two real clones.
- Configure one supported remote and two collaborator identities.
- Measure native open/save behavior with ordinary Git and qualified LFS policies.
- Prove document locks, same-document contention, expiry, forced unlock, offline
  work, rejected push, and recovery branches.
- Capture expected scenes, BOMs, diffs, validation, and outputs.

Acceptance:

- no same-document edit can be silently overwritten;
- Altium binary conflicts are never presented as mergeable text;
- KiCad merges pass semantic/native validation or are rejected;
- local work survives every simulated remote race;
- both EDAs complete the next discriminating prototype end to end.

### Phase 1: Adapter And Model Foundation

- Implement complete adapters and shared models.
- Move EDA dispatch out of routers and shared services.
- Implement scene, BOM, semantic diff, validation, BOM write, and native open.
- Split concentrated project services.

Acceptance:

- no shared service or component branches on EDA;
- both adapters pass the same contract suite;
- real paired fixtures normalize equivalent facts;
- readonly operations leave source bytes unchanged;
- BOM writes reopen natively and restore.

### Phase 2: Repository Setup And Project Lens

- Add clone/link/open/inspect flows.
- Add recents, favorites, mixed-project selection, and locate.
- Add repository readiness, remote, branch, collaborator, runtime, library, and
  lock-service status.
- Add the persistent Project Lens.

Acceptance:

- either project can be cloned or linked without typing a path;
- both collaborators see the same project identity and shared branch state;
- unsafe repository policies block editing with an exact fix;
- WebView2 passes both themes and supported widths.

### Phase 3: Design Canvas

- Implement the project tree, schematic/PCB scene, canvas controls, selection,
  properties, cross-probe, collaborator overlays, and open-at-target.
- Add contextual comments and immutable review events.
- Add before/after and overlay rendering.

Acceptance:

- equivalent controls exist for KiCad and Altium;
- object selection maps back to stable native objects;
- comments remain anchored across unchanged revisions and become honestly stale
  when their target changes;
- a 1,000-object scene meets the agreed interaction budget.

### Phase 4: BOM Maker

- Implement automatic normalized BOM.
- Add inline/bulk supported-property editing.
- Add Stockroom matching, variants/DNP, substitutes, inventory, build quantity,
  shortages, pricing, purchase list, and exports.
- Bind edits to native object IDs and shared transaction receipts.

Acceptance:

- both EDAs expose the same editable columns and validation;
- equivalent edits produce equivalent native BOM outcomes;
- every affected component appears in preview;
- one transaction commits exact intended paths;
- restore succeeds in both native applications.

### Phase 5: Guided Assembly

- Implement pinned assembly snapshots and inventory reservations.
- Add the live BOM/board cross-probe view, top/bottom navigation, placement
  highlight, orientation/polarity guidance, and bench controls.
- Add barcode/Stockroom-label verification.
- Persist placement events and crash resume.
- Finalize reversible inventory consumption and completed build receipts.

Acceptance:

- KiCad and Altium placement snapshots drive the identical assembly UI;
- selecting a BOM line highlights every correct board location;
- selecting a placement exposes correct side, position, rotation, and pin-1/polarity
  evidence;
- a mismatched scan cannot be accepted as the selected part;
- Done, Skipped, Reworked, and Issue states survive process termination;
- inventory reservations prevent double allocation and reconcile exactly on
  completion, cancel, and rework;
- a changed project cannot silently alter an active run;
- a completed receipt verifies against a fresh clone and the inventory ledger.

### Phase 6: Work Sessions And Locks

- Implement Start Work, document claims, leases, collaborator state, handoff,
  expiry, override, and recovery.
- Integrate native open with lock verification.
- Add background fetch without working-tree mutation.

Acceptance:

- two clones can edit different documents concurrently;
- a second same-document writer is blocked before native editing;
- lock loss never discards local work;
- overrides are explicit and auditable;
- missing locking support blocks collaborative write mode for both EDAs.

### Phase 7: Changes, Review, And Sync

- Implement semantic/visual/BOM/validation diffs.
- Add Review And Share Changes, scoped commit, work-branch push, review, approval,
  requested changes, merge, and sync states.
- Use isolated worktrees for review.

Acceptance:

- the second collaborator reviews without disturbing their working copy;
- approval is invalidated by a changed source commit;
- push and merge races preserve both histories;
- no force push or binary auto-merge occurs;
- integrated projects reopen and validate in both EDAs.

### Phase 8: Releases

- Implement release preflight, native recipe execution, artifact collection,
  content-addressed manifest, tag, history, and release comparison.

Acceptance:

- equivalent KiCad jobset and Altium OutJob roles are generated;
- source, BOM, validation, and outputs bind to one commit;
- artifact hashes verify after a fresh clone;
- two releases compare design, BOM, validation, and artifacts consistently.

### Phase 9: Product Cutover

- Assemble Design, BOM, Assemble, Changes, and Releases.
- Restore Projects navigation only after every paired gate is green.
- Remove superseded project APIs, DTOs, and settings-oriented UI.
- Update architecture, README, current state, and UI north star.
- Rebuild committed frontend distribution and run the Windows gate.

Acceptance:

- both EDAs expose the same routes, actions, states, and receipts;
- two real users complete the full start-work-to-merge flow;
- no unrelated working-tree path is modified or staged;
- backend, frontend tests, typecheck, build, distribution stability, and Windows
  gate pass;
- both themes pass real WebView2 inspection.

## Final Product Acceptance

The rebuild is complete only when two people can:

1. Clone or link the same KiCad or Altium project repository.
2. See the same project, branch, remote, collaborator, and document-lock state.
3. Browse the schematic and PCB visually with shared controls.
4. Select objects, inspect properties, comment, and cross-probe into the native
   EDA.
5. Build and edit the BOM with identical KiCad and Altium workflows.
6. See inventory, substitutes, shortages, pricing, and purchase requirements.
7. Start a guided assembly run from the exact reviewed board and BOM.
8. Scan/select a part, see every placement, orientation, side, polarity, and storage
   location, then record physical progress in real time.
9. Resume an interrupted assembly run and reconcile inventory exactly.
10. Start concurrent work on different documents without interference.
11. Be prevented from silently editing and overwriting the same document.
12. Share a branch with visual, semantic, BOM, and validation diffs.
13. Review and approve the exact commit without replacing the reviewer's working
    tree.
14. Merge and sync without force pushes or silent conflict resolution.
15. Recover both users' work from offline operation, stale bases, rejected pushes,
    lock loss, and interrupted operations.
16. Create a reproducible release tied to exact source and artifact hashes.
17. Encounter no tool, route, or safety guarantee that exists for only one EDA.

## Recommendation

Approve this product direction and build the two-clone prototype before rebuilding
the production page.

The essential Projects product is:

- **Design:** PCB-editor-like visual collaboration;
- **BOM:** native-aware BOM authoring plus Stockroom inventory;
- **Assemble:** real-time guided PCB population and inventory traceability;
- **Changes:** Git work sessions, locks, semantic review, approval, and sync;
- **Releases:** reproducible manufacturing handoff.

This scope makes Projects essential to two collaborators without pretending
Stockroom can safely replace KiCad's or Altium's geometry engine.
