# Project Discovery And Unified Renderer Implementation Plan

**Goal:** Prove that Stockroom can find existing KiCad and Altium projects, open either through one fast read-only viewer, build the BOM, and link exact catalog matches without starting Altium Designer.

**Architecture:** Keep the existing project-adapter and `ProjectVisualBundle` boundaries. Windows Search supplies descriptor paths, the existing adapters group documents, KiCad keeps its disposable-copy `kicad-cli` SVG path, and the packaged CAD Converter adds direct AltiumSharp SVG rendering. The frontend reuses the current Projects shell, query cache, BOM workbench, pan/zoom behavior, and registration API.

**Tech Stack:** Python/FastAPI, React/TypeScript/TanStack Query, .NET 10, vendored AltiumSharp, KiCad CLI, Windows Search, Vitest, pytest, xUnit.

**Spec:** `docs/specs/2026-08-21-project-discovery-and-unified-renderer.md`

## Global Constraints

- [ ] Keep Component Catalog repositories separate from PCB Project repositories.
- [ ] Call the shared component source **Catalog**; do not expose routine Git mechanics in this proof.
- [ ] Read project sources only. Rendering and discovery must not modify them.
- [ ] Never start Altium Designer for ordinary viewing.
- [ ] Reuse the existing visual bundle, artifact endpoint, BOM, exact-MPN matching, Add Location, and project registration paths.
- [ ] Add no crawler, database, file watcher, collaboration service, 3D renderer, or native project editor.
- [ ] Record the implementation decision before each wave and commit each verified wave separately.

---

## Task 1: Render Altium Documents In The Existing CAD Converter

**Files:**

- Modify: `app/desktop/Stockroom.CadConverter/Stockroom.CadConverter.csproj`
- Modify: `app/desktop/Stockroom.CadConverter/Contracts.cs`
- Modify: `app/desktop/Stockroom.CadConverter/Program.cs`
- Create: `app/desktop/Stockroom.CadConverter/ProjectDocumentRenderer.cs`
- Modify: `tests/native/Stockroom.CadConverter.Tests/Stockroom.CadConverter.Tests.csproj`
- Create: `tests/native/Stockroom.CadConverter.Tests/ProjectDocumentRendererTests.cs`
- Modify: `docs/design/Stockroom Reliability And Design Freedom Decisions.md`

- [ ] **Step 1: Add the failing native rendering tests**

Use the vendored `TestData` `.SchDoc` and `.PcbDoc` fixtures. Assert that one request:

- accepts only files inside the declared project root;
- emits schematic SVG and top/bottom PCB SVG;
- reports exact path, media type, dimensions, byte count, and SHA-256;
- leaves source hashes unchanged;
- rejects path traversal, unsupported suffixes, and output escape;
- contains no Altium process-launch contract.

Run:

```powershell
dotnet test tests/native/Stockroom.CadConverter.Tests/Stockroom.CadConverter.Tests.csproj --filter ProjectDocumentRendererTests
```

Expected: FAIL because the project-render request and renderer do not exist.

- [ ] **Step 2: Add one schema-dispatched converter operation**

Add request/result records with schemas:

```text
stockroom.cad-converter/project-render-request/1
stockroom.cad-converter/project-render-result/1
```

`Program.cs` should inspect only the request `schema`, then call the existing library converter or the new document renderer. Do not add another executable or IPC protocol.

- [ ] **Step 3: Render with the vendored reader**

Add the existing rendering project reference and use:

```csharp
await AltiumLibrary.OpenSchDocAsync(path, cancellationToken);
await AltiumLibrary.OpenPcbDocAsync(path, cancellationToken);
await new SvgRenderer().RenderAsync(document, output, options, cancellationToken);
```

Use `PcbRenderSettings.Top` and `.Bottom` for boards. Keep a transparent Stockroom-compatible background and deterministic output names. Hash the source before and after rendering and fail if it changes.

- [ ] **Step 4: Verify and commit**

```powershell
dotnet test tests/native/Stockroom.CadConverter.Tests/Stockroom.CadConverter.Tests.csproj
git diff --check
git add app/desktop/Stockroom.CadConverter tests/native/Stockroom.CadConverter.Tests docs/design/Stockroom Reliability And Design Freedom Decisions.md
git commit -m "feat: render Altium projects without Altium"
```

---

## Task 2: Route Altium Project Visuals Through The Converter

**Files:**

- Modify: `app/backend/stockroom/altium/converter.py`
- Modify: `app/backend/stockroom/altium/project_visuals.py`
- Modify: `app/backend/stockroom/projects/adapters/altium.py`
- Modify: `tests/backend/altium/test_converter.py`
- Modify: `tests/backend/altium/test_project_visuals.py`
- Modify: `tests/backend/projects/test_adapters.py`
- Modify: `docs/design/Stockroom Reliability And Design Freedom Decisions.md`

- [ ] **Step 1: Add failing converter-boundary tests**

Cover exact executable invocation, project-root confinement, result-schema validation, artifact hash validation, timeouts, and source preservation. Add an adapter regression proving rendering does not call `AltiumDriver`, create a Pascal script, run an OutJob, emit PDF, or request IPC-2581.

```powershell
uv run pytest tests/backend/altium/test_converter.py tests/backend/altium/test_project_visuals.py tests/backend/projects/test_adapters.py -q
```

Expected: FAIL because project rendering still uses the Altium automation path.

- [ ] **Step 2: Extend the existing sidecar wrapper**

Generalize the private `_invoke` result-schema check and add one public project-render function. Preserve the exact packaged/development executable resolution already used for library conversion.

- [ ] **Step 3: Normalize converter artifacts into `ProjectVisualBundle`**

Replace the ordinary-view script/OutJob/PDF path in `altium/project_visuals.py` with the converter response. Reuse `artifact_metadata` and the existing artifact endpoint; do not introduce another visual DTO.

- [ ] **Step 4: Keep a useful render cache**

Use the existing root/path/size/mtime key without the five-second expiry. A changed document rerenders. If that fresh render fails, retain the last valid artifacts for the same project and return a truthful stale detail with **Retry**; never substitute another project's cache.

- [ ] **Step 5: Verify and commit**

```powershell
uv run pytest tests/backend/altium/test_converter.py tests/backend/altium/test_project_visuals.py tests/backend/projects/test_adapters.py -q
uv run ruff check app/backend/stockroom/altium app/backend/stockroom/projects/adapters/altium.py tests/backend/altium tests/backend/projects/test_adapters.py
git diff --check
git add app/backend/stockroom/altium app/backend/stockroom/projects/adapters/altium.py tests/backend/altium tests/backend/projects/test_adapters.py docs/design/Stockroom Reliability And Design Freedom Decisions.md
git commit -m "feat: serve unified Altium project visuals"
```

---

## Task 3: Find Projects Through Windows Search

**Files:**

- Create: `app/backend/stockroom/projects/windows_search.py`
- Modify: `app/backend/stockroom/api/routers/projects.py`
- Create: `tests/backend/projects/test_windows_search.py`
- Modify: `tests/backend/api/test_projects.py`
- Modify: `app/frontend/src/api/types.ts`
- Modify: `app/frontend/src/api/client.ts`
- Modify: `app/frontend/src/api/queries.ts`
- Modify: `docs/design/Stockroom Reliability And Design Freedom Decisions.md`

- [ ] **Step 1: Add failing system-discovery tests**

Test static indexed results containing `.kicad_pro` and `.PrjPcb`, duplicate paths, missing results, unavailable Windows Search, non-Windows behavior, and paths that disappear before adapter inspection.

```powershell
uv run pytest tests/backend/projects/test_windows_search.py tests/backend/api/test_projects.py -q
```

Expected: FAIL because no system-discovery endpoint exists.

- [ ] **Step 2: Query the native Windows Search index**

Use the built-in `Search.CollatorDSO` OLE DB provider through one bounded, noninteractive PowerShell invocation. Query only descriptor extensions, return normalized absolute paths as JSON, cap the result count, and inject the command runner in tests. Do not crawl drives or add a dependency.

- [ ] **Step 3: Group results with existing adapters**

For each descriptor, call the current `discover_projects` path, deduplicate by normalized `(root, eda, descriptor)`, sort by project name/root, and return an honest status plus projects. Keep `POST /api/projects/discover` unchanged for **Add Location**.

Add:

```text
GET /api/projects/discover-system
```

- [ ] **Step 4: Add the frontend query**

Add one `useSystemProjectDiscovery()` query. Do not poll; refresh on Projects entry and explicit Retry only. Registered projects remain authoritative and are omitted from the discovered suggestion list by normalized root/EDA equality.

- [ ] **Step 5: Verify and commit**

```powershell
uv run pytest tests/backend/projects/test_windows_search.py tests/backend/api/test_projects.py -q
npm.cmd --prefix app/frontend run typecheck
git diff --check
git add app/backend/stockroom/projects/windows_search.py app/backend/stockroom/api/routers/projects.py tests/backend/projects/test_windows_search.py tests/backend/api/test_projects.py app/frontend/src/api/types.ts app/frontend/src/api/client.ts app/frontend/src/api/queries.ts docs/design/Stockroom Reliability And Design Freedom Decisions.md
git commit -m "feat: discover indexed PCB projects"
```

---

## Task 4: Open Discovered Projects In One Focused Workspace

**Files:**

- Modify: `app/frontend/src/pages/ProjectsPage.tsx`
- Modify: `app/frontend/src/pages/ProjectsPage.test.tsx`
- Modify: `app/frontend/src/components/projects/ProjectPicker.tsx`
- Modify: `app/frontend/src/components/projects/ProjectPicker.test.tsx`
- Modify: `app/frontend/src/components/projects/ProjectDesignWorkbench.tsx`
- Modify: `app/frontend/src/components/projects/ProjectDesignWorkbench.test.tsx`
- Modify: `app/frontend/src/components/projects/ProjectPlacementStage.tsx`
- Modify: `app/frontend/src/components/projects/ProjectPlacementStage.test.tsx`
- Modify: `app/frontend/src/lib/devIds.ts`
- Modify: `app/frontend/src/lib/devIds.test.ts`
- Modify: `docs/design/Stockroom Reliability And Design Freedom Decisions.md`

- [ ] **Step 1: Add failing workflow tests**

Cover:

- indexed projects appearing without a typed path;
- selecting an indexed result registering and opening it in one action;
- **Add Location** remaining available;
- Overview, Schematic, PCB, and BOM views;
- selectors appearing only for multiple schematics, boards, or pages;
- one shared canvas behavior for KiCad and Altium;
- automatic BOM query on project open;
- exact Catalog matches shown immediately and uncertain matches under one **Review** action;
- stale render plus Retry without blanking the workspace.

```powershell
npm.cmd --prefix app/frontend run test:run -- src/pages/ProjectsPage.test.tsx src/components/projects/ProjectPicker.test.tsx src/components/projects/ProjectDesignWorkbench.test.tsx src/components/projects/ProjectPlacementStage.test.tsx
```

Expected: FAIL on system discovery, document tabs, and schematic rendering.

- [ ] **Step 2: Merge linked and found projects in the picker**

Keep one list. Linked rows select immediately. Found rows call the existing registration mutation and select the returned ID. Use a small **Found On This PC** status; keep **Add Location** as the only fallback control. Do not add an import wizard.

- [ ] **Step 3: Make document views direct**

Add Schematic and PCB views beside Overview and BOM. Preserve Build and Recent Work without changing their behavior, placing them after the proof views. A view with one document has no selector. Multiple documents use the existing `AdaptiveChoice`; schematic pages use the same control beneath the schematic choice.

- [ ] **Step 4: Reuse the existing viewer**

Extend `ProjectPlacementStage` instead of creating a second viewer. It should accept the chosen visual document, use the same artifact query, pan/zoom/fit/background/loading/error controls, and keep the existing PCB placement overlay only for PCB documents. A schematic displays the returned SVG inside that same frame.

- [ ] **Step 5: Keep BOM automatic**

Start the existing live BOM query when a project workspace opens, not only after the BOM tab is clicked. Reuse existing exact-MPN and Review UI; add no new matching engine.

- [ ] **Step 6: Verify and commit**

```powershell
npm.cmd --prefix app/frontend run test:run -- src/pages/ProjectsPage.test.tsx src/components/projects/ProjectPicker.test.tsx src/components/projects/ProjectDesignWorkbench.test.tsx src/components/projects/ProjectPlacementStage.test.tsx src/components/projects/ProjectBomWorkbench.test.tsx src/lib/devIds.test.ts src/lib/devIds.parity.test.ts
npm.cmd --prefix app/frontend run typecheck
git diff --check
git add app/frontend/src/pages/ProjectsPage.tsx app/frontend/src/pages/ProjectsPage.test.tsx app/frontend/src/components/projects app/frontend/src/lib/devIds.ts app/frontend/src/lib/devIds.test.ts docs/design/Stockroom Reliability And Design Freedom Decisions.md
git commit -m "feat: open discovered projects in one workspace"
```

---

## Task 5: Native Acceptance, Full Gate, And Publication

**Files:**

- Modify only if durable truth changed: `D:/Workspace/Knowledge/Engineering Brain/Projects/Stockroom/Current State.md`
- Modify only if required by source changes: `README.md`, `app/frontend-dist/**`

- [ ] **Step 1: Run the focused proof end to end**

On Windows, use indexed fixtures or representative local projects to prove:

1. Projects appears without entering a path.
2. A multi-board/multi-sheet project shows only needed selectors.
3. KiCad and Altium render in the same controls.
4. No `X2.EXE`/Altium process starts during Altium rendering.
5. Source hashes are unchanged.
6. BOM and exact Catalog links appear without a separate build action.
7. A failed refresh keeps the last valid canvas and exposes Retry.

- [ ] **Step 2: Inspect both themes**

Capture the Projects list, KiCad schematic/PCB, Altium schematic/PCB, and BOM at 1366x872 and 1600x1000. Critique wasted space, duplicated controls, clipping, unclear selectors, palette mismatch, and unnecessary borders. Fix only proof-blocking defects and rerun the focused tests.

- [ ] **Step 3: Run the repository authority**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1
```

Expected: PASS. Do not replace this with focused suites.

- [ ] **Step 4: Verify deterministic distribution**

Run two production builds and compare every `app/frontend-dist` path byte-for-byte. Confirm the current 190-scenario projection remains exact.

- [ ] **Step 5: Update durable state, commit, and publish**

Update Current State only with verified behavior and remaining physical/external boundaries. Refresh its QMD collection. Then:

```powershell
git status --short
git diff --check
git add app/frontend-dist README.md
git commit -m "release: verify project discovery and rendering"
git push origin HEAD:main
```

Do not push if the worktree contains unexplained changes, the full gate fails, native visual acceptance is incomplete, or `origin/main` is no longer an ancestor of the verified commit.

