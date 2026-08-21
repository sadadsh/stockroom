# Project Discovery And Unified Renderer Proof

**Status:** Approved for implementation

## Objective

Prove one short project workflow: Stockroom finds existing KiCad and Altium projects, opens either one through the same useful renderer, builds its BOM, and links exact manufacturer part numbers to the current Component Catalog.

This proof replaces the current Altium rendering path that starts Altium Designer. Stockroom must render Altium source without opening Altium, flashing windows, requiring an Altium session, or modifying project files.

## Product Flow

1. Projects queries the Windows Search index for `.kicad_pro` and `.PrjPcb` files across indexed local drives.
2. Stockroom groups each descriptor with its native project folder and documents. **Add Location** remains available when Windows Search does not index a folder.
3. Selecting a project opens one focused workspace with **Overview**, **Schematic**, **PCB**, and **BOM** tabs.
4. A document selector appears only when the selected project contains multiple top-level schematics or PCBs. Schematic pages remain grouped beneath their schematic document.
5. Stockroom renders the selected document, builds the project BOM, and links exact MPN matches to the current Component Catalog.
6. Ambiguous and non-exact matches remain unchanged behind one **Review** action.

The UI calls the shared component source **Catalog**. Git implementation details stay out of the Projects workspace. Existing Catalog Repository and Catalog Sync behavior remain the sharing mechanism for this proof.

## Unified Renderer

Stockroom keeps the existing project adapter seam and visual bundle contract.

- KiCad continues to export read-only SVG through `kicad-cli` from a disposable project copy.
- The bundled Stockroom CAD Converter reads `.SchDoc` and `.PcbDoc` through the vendored AltiumSharp reader and emits SVG directly.
- The Altium path does not start Altium Designer, run an OutJob, publish a PDF, or export IPC-2581 for ordinary viewing.
- Both adapters return the same document and artifact metadata to one frontend viewer.
- The viewer owns one background, fit, pan, zoom, document selector, page selector, side selector, loading state, and error state.
- Both SVG paths use the Stockroom project palette and transparent page background. Exact source geometry remains unchanged.

Stockroom opens KiCad or Altium only when the person selects **Open In KiCad** or **Open In Altium**. Native validation and manufacturing output remain separate actions.

## Speed And Failure Behavior

The project list may show cached results immediately while Windows Search refreshes. A render cache key includes the exact document path, size, and modification time. Selecting a cached project does not rerun a converter until those inputs change.

If a fresh render fails, Stockroom keeps the last valid render and shows **Retry** plus the native open action. Missing EDA installations do not block project discovery, AltiumSharp rendering, BOM reading, or Catalog matching. A missing `kicad-cli` blocks only the KiCad render and native KiCad actions.

## Included

- System-wide indexed project discovery with Add Location fallback.
- KiCad and Altium project grouping.
- Multiple PCB, top-level schematic, and schematic-page selection.
- Headless Altium schematic and PCB SVG rendering.
- One shared Stockroom project viewer.
- Automatic project BOM creation.
- Exact-MPN Catalog linking and one review queue for every uncertain match.
- Existing Catalog sharing and sync behavior.

## Deferred

- Native project editing inside Stockroom.
- 3D project rendering.
- Advanced layer inspection and manufacturing output.
- New collaboration, locking, review, or release systems.
- New background sync infrastructure.

## Agreed Follow-Up Direction

These decisions remain approved but do not expand the first proof:

- Component Catalog repositories and PCB Project repositories remain separate.
- Stockroom calls the shared component source **Catalog** and hides routine Git terms.
- **Share Catalog** handles member access. Accessible shared Catalogs appear after sign-in.
- Catalog exchange runs automatically. The newest field edit becomes active, while Git history retains the displaced value.
- Windows Search results stay current without repeated whole-drive crawling.
- Projects keeps the focused Stockroom layout: one project list, one large workspace, four tabs, and details only when useful.
- Later renderer work may add 3D and advanced layers only after the common 2D proof passes native use.

## Acceptance

The proof is accepted when:

1. A system-wide indexed scan finds representative KiCad and Altium descriptors without typed paths.
2. One project with multiple PCBs and schematic pages presents correct selectors without duplicating the project.
3. Equivalent KiCad and Altium documents render through the same Stockroom canvas and controls.
4. Rendering an Altium project starts no Altium process and leaves every source byte unchanged.
5. A repeated unchanged render returns cached evidence.
6. The BOM appears automatically and exact MPNs link to the current Catalog; uncertain matches remain under Review.
7. A render failure preserves the last valid canvas and leaves the rest of Stockroom usable.
8. Focused frontend, backend, and CAD Converter tests pass, followed by `scripts\Gates.ps1` and real Windows visual inspection in both themes.
