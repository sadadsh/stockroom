# Stockroom

Stockroom helps PCB engineers build, maintain, and use a trusted component catalog across PCB design work.

## Language

**PCB Engineer**:
The primary Stockroom user, who selects parts, maintains reusable component data, and prepares PCB designs.
_Avoid_: Operator, administrator

**Component Catalog**:
The shared, versioned collection of component records, sourcing evidence, and retained CAD assets.
_Avoid_: Database, workspace, components folder

**PCB Project**:
One KiCad or Altium design grouped by its native project descriptor, source documents, and project repository. A PCB Project uses a Component Catalog but never contains or owns that catalog.
_Avoid_: Catalog project, project catalog

**Project Document**:
One top-level schematic or PCB source file inside a PCB Project. Stockroom uses the exact filename when more than one document of the same kind exists.
_Avoid_: Project tab, canvas

**Schematic Sheet**:
One page within a schematic Project Document. Sheets remain grouped under their document instead of appearing as separate projects.
_Avoid_: Schematic project, document

**Project Render**:
The read-only Stockroom view of a Project Document. KiCad and Altium Project Renders use the same canvas, controls, sizing, and presentation grammar.
_Avoid_: Native editor, project preview image

**Catalog Repository**:
The GitHub repository and its managed local folder that own one Component Catalog. Its visibility is chosen when the repository is created.
_Avoid_: Library path, database location

**Catalog Sync**:
Automatic exchange and semantic reconciliation of Catalog Repository changes across machines. The latest accepted value becomes active while displaced values remain in history; no manual sync action is required.
_Avoid_: Overwrite, push/pull button

**Catalog Tombstone**:
A retained deletion record that removes a component from normal use while preserving its identity and history for restoration and synchronization.
_Avoid_: Soft delete, trash file

**Primary CAD Tool**:
The one CAD tool a person chooses for setup, readiness, and daily component preparation on a machine. The choice may change without deleting retained assets for another tool.
_Avoid_: Active adapter, preferred EDA

**CAD Preparation**:
The work that makes a component ready for the Primary CAD Tool, including obtaining, validating, and publishing required CAD assets.
_Avoid_: Component setup, completion

**CAD Assets**:
The symbol, footprint, and 3D model retained for use by KiCad or Altium.
_Avoid_: Models, CAD files

**EDA Catalog Projection**:
The tool-specific catalog view that makes Stockroom components available to KiCad or Altium. It is derived from the Component Catalog and may be rebuilt without changing component truth.
_Avoid_: CAD database, generated library

**Catalog Build**:
A person-confirmed Assets batch that finalizes ready CAD Assets and updates the EDA Catalog Projection. Verified embedded Altium output is retained in the Catalog Repository; the machine-local DbLib/index remains derived.
_Avoid_: Projection Queue, background CAD queue

**Assets**:
The main-rail workspace containing every component that lacks a required CAD Asset or is not current in the EDA Catalog Projection. It owns provider acquisition, explicit 3D Model availability, and Catalog Build actions.
_Avoid_: CAD Work, Assets Page, completion queue

**Asset Availability**:
The per-component state of a CAD Asset. Symbol and Footprint are Available or Missing and are always required; the shared 3D Model may additionally be explicitly Not Available.
_Avoid_: Completeness, file status

**Provider Visit**:
A person-driven interaction with a provider website to obtain CAD files. Stockroom presents the page and records resulting downloads but never operates the provider controls.
_Avoid_: Browser automation, provider capture

**Preferred Source**:
The Mouser or DigiKey source chosen for the compact sourcing summary. When none is chosen, Stockroom labels its strongest in-stock source as Suggested.
_Avoid_: Default vendor, cheapest distributor

**Add Session**:
A continuous period in which a PCB Engineer adds one or many components without being diverted into CAD Preparation.
_Avoid_: Ingest batch, intake continuation

**Readiness Verdict**:
One compact statement of whether a component is ready for the Primary CAD Tool and, when it is not, how many actions remain.
_Avoid_: Health badge, completeness score

**First Workflow**:
A skippable, stoppable, rerunnable in-app checklist that teaches one real component end to end and briefly exercises every main useful screen through real controls.
_Avoid_: Product tour, onboarding slideshow
