# Stockroom: Design Specification

Date: 2026-07-12
Status: draft (pending owner review)
Owner: Sadad
Author: Claude (brainstorming session, all five design sections approved interactively)

## 1. What Stockroom is

Stockroom is a Windows desktop app that manages a KiCad V10 component library with zero
manual bookkeeping. You drag in the zips you download from the internet (symbol,
footprint, 3D model), paste a product link, and the app does everything else: converts,
names, categorizes, links footprint to symbol and 3D model to footprint, stores the
datasheet and purchase link, fills every field, and registers everything with KiCad so
the part is immediately usable in any project. It can also audit an existing KiCad
project, stepping through its components, offering to add unrecognized ones to the
library and filling in and relinking the recognized ones.

The app updates itself from git (no release builds), carries its library data inside its
own repo (clone the repo on any machine, get the identical library and an identically
wired KiCad), and presents a minimal, monochrome, search-first UI.

### Explicit requirements (from the owner, verbatim intent)

1. Drag/drop downloaded component zips; app ingests symbol + footprint + 3D model.
2. Datasheet and purchase link stored per part.
3. All fields filled, everything linked; zero manual work after the drop.
4. Point at a KiCad project; step through components; add unrecognized ones to the
   library; fill and relink recognized ones.
5. Minimal, clean, monochrome, modular UI that feels good.
6. Updates without a GitHub release (chosen model: self-update via git pull).
7. Smart parsing of a pasted link to auto-pull fields (Mouser API + generic scraping,
   generic held to the same quality bar as the API).
8. Symbol, footprint, and 3D model all display in-app alongside all part data.
9. Search across every field; flexible filtering; categorized by component type.
10. Duplicate detection and management.
11. Runs as a Windows exe.
12. Library data lives inside the app repo; switchable library-set profiles (one folder
    per library); the manager shows only the active library.
13. Zero compromises: no stubs, no happy paths, no silent fallbacks, full end to end.

### Non-goals (v1)

- No BOM building, PCB setup, bench tooling, routing, or any other function of any
  previous tool. Stockroom is a components manager only.
- No multi-user permission system. Sync is git; collaborators are trusted committers.
- No support for EDA tools other than KiCad, and no KiCad version below 9.
  (Target is V10; the file formats and config layout of 9/10 are handled explicitly.)

## 2. Architecture

Three layers in one repository, with strictly different change rates:

```
stockroom/
  launcher/            Frozen to Stockroom.exe ONCE. Never rebuilt for app changes.
  app/
    backend/           Python (FastAPI). All logic lives here.
    frontend/          TypeScript SPA source.
    frontend-dist/     Built UI, committed to git. Users never need Node.
  libraries/
    Main/              A library profile (one folder per profile).
      parts/           One JSON file per part (metadata records).
      symbols/         Per-category .kicad_sym libraries.
      footprints/      Per-category .pretty directories.
      models/          STEP/WRL 3D models, per category.
      datasheets/      PDF per part.
  docs/                Design contract, specs, ledger of deferrals.
  uv.lock, pyproject.toml
```

### Process model

`Stockroom.exe` (the launcher):
1. Ensures the Python runtime and dependencies exist, pinned by `uv` against the
   committed lockfile (first run bootstraps; later runs are a no-op check).
2. Starts the backend (FastAPI/uvicorn) on `127.0.0.1` on an ephemeral port.
3. Opens a native WebView2 window (pywebview) onto the frontend served by the backend.

All heavy work runs in the backend: zip inspection, format conversion, STEP to GLB
conversion, scraping, enrichment, git operations, KiCad config surgery, search indexing.
The window is pure presentation.

### Update flow

An Update control in Settings (and an on-launch check, non-blocking):
`git pull --ff-only` on the app repo, then `uv sync`, then graceful backend restart and
window reload. One pull updates code, UI, and library data together. If the pull is not
fast-forwardable, the app does not guess: it surfaces the state and offers the safe
resolutions (stash local data changes on top, or open the folder).

### Library data sync

Every library mutation is a scoped git commit with a meaningful message, for example:
`Add TPS62130 (buck regulator): symbol, footprint, 3D model, datasheet`.
Background sync: pull before push, fast-forward only, on a timer and after each commit
batch. True divergence never gets clobbered; the app surfaces it with the exact state
and safe options. Offline is a first-class state: everything local works; sync resumes
when the network returns.

### Per-machine state (outside the repo)

`%APPDATA%/Stockroom/config.json`: active profile, window state, KiCad install path,
API keys, sync preferences. Nothing machine-specific or secret ever enters the repo.
Missing Mouser key simply means enrichment uses the generic parser only.

## 3. Data model

### The part record

`libraries/<Profile>/parts/<part-id>.json`, one file per part (git-merge friendly by
construction; concurrent adds on two machines cannot conflict on a shared file).

Fields:
- `id`: stable slug, assigned at ingest, never reused.
- `display_name`, `category`, `description`, `tags[]`.
- `mpn`, `manufacturer`.
- `datasheet`: `{ file, source_url, fetched_at }`.
- `purchase[]`: `{ vendor, url, price_breaks, stock, currency, fetched_at }`.
- `symbol`: `{ lib, name }` (which Stockroom library, which symbol).
- `footprint`: `{ lib, name }`.
- `model`: `{ file }` (repo-relative, referenced from the footprint via `${SR_LIB}`).
- `provenance`: `{ source ("snapeda" | "ultralibrarian" | "samacsys" | "manual" | ...),
  source_url, original_zip_sha256, ingested_at }`.
- `hashes`: `{ symbol_content, footprint_content, model_file }` (duplicate detection).
- `enrichment`: per-field source + confidence (`mouser_api`, `jsonld`, `og`,
  `site:<domain>`, `heuristic`, `manual`), so the UI can always answer "where did this
  value come from".

The KiCad-visible subset (MPN, Manufacturer, Datasheet, Description, keywords, purchase
URL) is mirrored INTO the symbol properties so KiCad shows a complete part even without
Stockroom. The app is the single writer of both representations; a reconcile pass
(`doctor`) detects and heals drift if files were edited behind its back, always showing
a diff before healing.

### Categories

Fixed taxonomy, each mapping to one KiCad symbol library and one footprint library:

Resistors, Capacitors, Inductors, Diodes, Transistors, ICs, Connectors, Switches,
Crystals & Oscillators, Sensors, Modules, Electromechanical, Other.

Files: `SR-<Category>.kicad_sym`, `SR-<Category>.pretty/`. Category is auto-suggested at
ingest (from enrichment category data and heuristics) and confirmed or overridden by the
user. Moving a part between categories moves the symbol/footprint between libraries and
updates the JSON, atomically.

### Profiles

Each `libraries/<Name>/` folder is a complete, self-contained library set. The active
profile is per-machine state. Create/switch/delete in-app. Delete removes the folder in
a scoped commit (git history preserves everything). The manager only ever shows the
active profile.

## 4. KiCad integration

### Wiring (first run and every profile switch)

1. Locate the KiCad V10 per-user config directory on Windows (verified:
   `%APPDATA%\kicad\10.0\`; configurable override in Settings).
2. Write one path substitution variable `SR_LIB` under `environment.vars` in
   `kicad_common.json` pointing at the active profile folder (verified structure).
3. Register each category library in the GLOBAL `sym-lib-table` and `fp-lib-table`
   (format version 7) with `${SR_LIB}`-based URIs and `SR-` nicknames, as
   `(type "KiCad")` rows. Verified V10 caution honored: V10 chains the stock libraries
   through a `(type "Table")` row; the writer appends only its own rows and never
   touches the Table row or any non-Stockroom entry.
4. All 3D model references inside footprints are written as
   `${SR_LIB}/models/...` in the standard `(model ...)` block (syntax verified against
   the V10 parser, including optional hide/opacity tokens).

Properties of the writer:
- Idempotent: re-running produces no changes when already correct.
- Scoped: never touches non-Stockroom entries.
- Safe: timestamped backup of each file before modification; parse-validate after write.
- Aware: detects a running KiCad and tells the user a restart is needed for table
  changes to load.

Profile switch is therefore a one-variable flip plus table refresh, and the same library
resolves identically on every machine that has run Stockroom's setup.

### Project audit

Input: a `.kicad_pro` (or `.kicad_sch`). The backend parses the full sheet hierarchy and
deduplicates components. Matching cascade against the active library:
1. Exact MPN property match.
2. Symbol lib_id / name match.
3. Fuzzy match on value + footprint (offered, never auto-applied).

Wizard (step-through, per the owner's requirement):
- Unrecognized part: add from zip, add from link, map to an existing library part, or
  skip. Adding routes through the normal ingestion pipeline, then returns to the wizard.
- Recognized part: shows exactly which fields will be filled and which links rewritten
  (lib_id to the Stockroom library, footprint field, datasheet, MPN, manufacturer, 3D path).

Apply phase: timestamped backups of every file to be touched, then rewrite schematic
symbol instances (fields + lib_ids), fix 3D model paths in the project's board file
footprints where they reference ingested models, save, and re-parse to validate. The
final footprint refresh on the PCB is done by KiCad's own Update PCB from Schematic;
the app says so explicitly at the end (honest about the one step KiCad owns).

## 5. Ingestion pipeline

Accepts two kinds of input:
- **Packages**: zips (SnapMagic/SnapEDA, UltraLibrarian, SamacSys / Component Search
  Engine which is Mouser's and DigiKey's "ECAD Model" download, manufacturer-direct
  downloads which are white-labeled instances of those three engines), bare files
  (`.kicad_sym`, legacy `.lib` + `.dcm`, `.kicad_mod`, `.step`/`.stp`/`.wrl`, PDF),
  folders, and any mix, multiple at once.
- **LCSC part numbers** (`Cxxxxx`): there is no KiCad zip for LCSC/EasyEDA; the
  ecosystem standard is an API fetch and convert, keyed on the part number. Stockroom
  has a dedicated LCSC path (easyeda2kicad-style: fetch the EasyEDA JSON, convert to a
  KiCad symbol, footprint, and 3D model) that feeds the same staging and commit stages.

### Fingerprint by content, never by origin (verified)

Vendor identity is determined by what is inside the archive, not where it was
downloaded, because a zip "from DigiKey" or a manufacturer site can be any of three
backend layouts. The detection is modeled on the actively-maintained reference
importer `Steffen-W/Import-LIB-KiCad-Plugin` (`identify_remote_type()`, verified current
2026), which stays correct because it must match real vendor output:
- **Octopart**: contains `device.lib` + `device.dcm` (fixed legacy filenames).
- **SamacSys / CSE**: a folder named exactly `KiCad`, with a LOOSE `.kicad_mod`
  (not a `.pretty` dir) and `.kicad_sym` or legacy `.lib` + `.dcm`. Ignore sibling
  `.epw` files (SamacSys Library Loader pointers) and per-EDA folders (`Altium/`,
  `EAGLE/`).
- **UltraLibrarian**: a folder named exactly `KiCAD` (the capitalization is the
  load-bearing discriminator from SamacSys), containing a real `.pretty` dir, often
  with SEVERAL near-duplicate footprint variants, and a symbol file frequently named by
  a generation TIMESTAMP (`2025-02-10_09-58-00.lib`), so part identity is never derived
  from the symbol filename.
- **SnapMagic/SnapEDA**: the fallback (no marker folder), loose `.kicad_sym` +
  `.kicad_mod` + `.step` + a `how-to-import.htm` marker; datasheet sometimes bundled.
- **Partial**: a zip carrying only a 3D model. Common enough to special-case (attach
  the model to an existing part, or hold it for the next matching add).

Realities the pipeline handles because vendors do not: 3D models sit anywhere in the
zip (glob the whole archive, priority `.step` then `.stp` then `.wrl`); NO vendor wires
the 3D model into the footprint, so Stockroom writes the `(model ...)` link itself; a
loose `.kicad_mod` (SnapEDA, SamacSys) is synthesized into a proper `.pretty`; a
multi-footprint `.pretty` (UltraLibrarian) presents its variants for the user to pick.

Stages:
1. **Inspect**: unpack to a sandbox; fingerprint the source per above; classify every
   file by content, not extension; identify symbol libraries, footprints, 3D models,
   datasheets, and junk to ignore (`.epw`, `how-to-import.htm`, sibling EDA folders,
   `.bxl`).
2. **Convert**: legacy and foreign formats upgraded via KiCad's own tooling (verified:
   `kicad-cli sym upgrade` converts legacy KiCad `.lib` AND Altium/EAGLE/CADSTAR/
   EasyEDA symbol formats; `kicad-cli fp upgrade` exists for footprints). Legacy `.lib`
   is treated as a standard input, not an edge case, since UltraLibrarian and SamacSys
   still ship it in 2026. Names normalized to library conventions.
3. **Stage**: a review card per part: rendered previews (symbol, footprint, 3D),
   proposed name and category, and gaps flagged honestly ("no 3D model in this zip").
   Multi-variant zips let the user pick or take all. A one-click fast path exists when
   the contents are unambiguous.
4. **Enrich**: paste a URL or MPN (or skip and enrich later from the part page).
5. **Commit**: one atomic transaction. Files move from staging into the per-category
   libraries; footprint field written on the symbol; `(model ...)` written on the
   footprint with a `${SR_LIB}` path; datasheet stored; JSON record written; git commit.
   Every written KiCad file is re-parsed as a validation gate before the transaction
   completes. A failed ingest leaves zero trace.

## 6. Enrichment engine

Layered, best source first, unified into one preview. Every field carries its source and
confidence; the user edits inline and accepts. Enrichment never silently overwrites a
filled field; changes to existing values are per-field opt-in.

1. **Mouser Search API v2** (if key configured; free key, 1,000 calls/day, 30/min).
   Auth is an `apiKey` query parameter; requests are JSON POST. Lookup by MPN or by the
   MPN extracted from a pasted mouser.com URL (`/ProductDetail/{Manufacturer}/{MPN}`,
   the trailing `qs=` token is opaque and ignored; the Mouser part number is generally
   not in the URL). Endpoints: `search/partnumber` (exact) with a
   `partnumberandmanufacturer` disambiguation and a `search/keyword` fallback on zero
   hits. Yields manufacturer, MPN, description, category, datasheet URL, product URL,
   image, price breaks, stock, lifecycle, and attribute pairs. Type-handling verified:
   price is a currency-symbol string, stock and discontinued arrive as strings, so the
   parser coerces them.
2. **Generic URL parser** (no key required; held to the same quality bar). Fetch with a
   browser-grade client whose TLS fingerprint matches Chrome (`curl_cffi` impersonation,
   since plain-Python TLS is fingerprinted and blocked by Akamai even on good IPs), then
   extract through a cascade:
   a. schema.org JSON-LD Product markup (the most stable target; verified rich on LCSC,
      including a direct datasheet URL),
   b. OpenGraph / standard meta tags,
   c. per-site extractor modules preferring `data-*` attributes over CSS classes (plain
      Python files in the repo; new sites and fixes arrive via the git-pull update path),
   d. embedded JS state blobs (`__NEXT_DATA__`-style) for JS-rendered pages,
   e. pattern heuristics (MPN shapes, title decomposition).
3. **In-window browser fallback** (the strategy that makes generic parsing match the API
   bar). Bot-protected sites (Cloudflare on DigiKey and TME; Akamai on Mouser, Farnell,
   RS, ST) defeat any HTTP client when a JS challenge fires. Because Stockroom already
   hosts a real WebView2 engine, it can load the product page in an actual browser
   context and read the rendered DOM (JSON-LD and all), which passes challenges no HTTP
   client can. This runs only for a user-initiated paste, one page at a time, never as a
   crawler. Open sites (LCSC, TI) skip straight to the fast HTTP path.
4. **Datasheet fetcher**: follows the discovered PDF link, follows redirects with a real
   User-Agent and a Referer set to the source page, retries over HTTP/1.1 when HTTP/2
   fails (verified necessary for Mouser's datasheet CDN), and validates the result by
   `Content-Type` plus `%PDF-` magic bytes (rejecting HTML viewer wrappers), then stores
   the PDF in the profile. The in-window browser is the fallback for challenge-gated
   datasheet hosts.

## 7. UI

### Shell

One window, native WebView2, themed to the app (dark title bar on Windows 11). A slim
left rail with five surfaces: Library, Ingest, Audit, Duplicates, Settings; the profile
switcher pinned at the rail's bottom. The frontend is a thin shell plus self-contained
feature modules behind a routing and command registry: future surfaces slot in without
touching existing ones.

### Library (the heart)

Three panes:
- **Filter sidebar**: categories with live counts; completeness facets (missing 3D,
  missing datasheet, missing footprint, unenriched); saved filters.
- **Parts list**: dense calm rows (name, MPN, manufacturer, completeness dots),
  keyboard-first (j/k, Enter), virtualized for large libraries.
- **Detail panel**: symbol, footprint, and 3D viewers with pan/zoom, all theme-tinted;
  every field inline-editable; purchase links; datasheet preview; provenance; the
  part's git history.

### Search

- **Ctrl+K palette**: instant fuzzy search over every field of every part AND every app
  action ("switch profile", "run audit", "add from link" execute as commands).
- **Filter bar**: free text plus composable field tokens (`mfr:TI cat:ICs missing:3d`)
  rendered as removable chips; token grammar documented in-app; saveable named filters.

### Duplicates

A dedicated surface grouping suspected duplicates (same MPN, same normalized symbol
content hash, same footprint hash, same model hash) side by side with previews, and a
keep/merge/delete flow that routes through the same atomic mutation engine.

### Feel

Monochrome gray ramp in the Notion register (soft warm-neutral grays, dark and light
themes), exactly one quiet accent reserved for focus and selection. 8px spacing grid,
restrained type scale (Inter or Geist), hairline borders, 150ms transitions, no
decorative color. Raycast density with Notion calm. Drag a file anywhere over the
window and the whole window becomes the drop target. Background work reports through
quiet toasts. Everything happens in-window; the only OS dialogs are the file pickers
the OS owns. The design contract lives at `docs/design/contract.md` with tokens and
rules, enforced by lint tests.

## 8. Technology choices

- **Backend**: Python 3.12+, FastAPI + uvicorn, `curl_cffi` (Chrome-impersonating HTTP
  client for scraping) with BeautifulSoup/lxml for JSON-LD and OpenGraph parsing,
  cascadio + trimesh (STEP to GLB), easyeda2kicad (LCSC part-number import),
  pywebview (WebView2 window, also the in-window scraping fallback), git via a bundled
  portable git or dulwich if none is installed.
- **KiCad file surgery (decided, empirically validated against the owner's real KiCad 10
  files)**: a purpose-built **span-preserving** s-expression layer. It tokenizes to a
  tree that records each token's byte offsets, applies targeted edits by splicing
  replacement text into the original byte string, and never re-serializes untouched
  regions. This was chosen over every existing library after head-to-head testing:
  kiutils is unmaintained and silently drops ~16% of nodes on KiCad 10 files;
  kicad-skip, kicad-tools, kicadfiles, kicad-sch-api and edea all rewrite the ENTIRE
  file (CRLF becomes LF, lists refold), turning a one-property edit into a whole-file
  diff. That is disqualifying here specifically because the library is git-synced and
  every edit is a commit: byte-preservation keeps diffs to the lines that actually
  changed, and makes the layer structurally incapable of the corruption modes that
  disqualified the others. A validated ~90-line proof of concept already edits a real
  schematic with a 2-line byte diff, preserving CRLF, tabs, and token order, with
  kicad-cli parsing the result clean. The layer is format-version-agnostic by
  construction, so KiCad 11 tokens will round-trip untouched.
  Format facts (verified): V10 `.kicad_sym` stamps `(version 20251024)`; V9 refuses
  V10-stamped files; changes since V9 are additive tokens plus a semantic change to
  `~` (no longer means empty text). Policy: surgical edits PRESERVE the file's existing
  version stamp and all untouched tokens, so a V9-compatible library never gets silently
  upgraded out of compatibility. New category libraries that Stockroom creates are
  stamped by the user's installed KiCad (the V10 target) via kicad-cli; Stockroom never
  invents a version stamp of its own.
- **Verification harness (permanent CI gate, not a dev aid)**: after every write, an
  independent canonical-tree semantic diff asserts only the intended nodes changed
  (zero lost, zero added), then `kicad-cli` (sym/fp/sch export) confirms KiCad itself
  parses the result. This gate runs in the test suite on every KiCad-writing path.
- **Why not the official KiCad IPC API (kicad-python / kipy)**: verified out of scope
  for V10. It operates on live editor sessions, not files; has no `.kicad_sym` library
  manipulation; and its schematic access plus headless `api-server` are KiCad 11
  features. Revisit at KiCad 11 for schematic work; the file layer above is the path now.
- **Sidecar tools (verified current)**: `easyeda2kicad` 1.0.1 (Apr 2026) for the LCSC
  part-number import path (it is version-aware and emits the `20251024` KiCad 10 symbol
  format when appending to a V10-era library); `cascadio` 0.0.17 + `trimesh` for
  STEP to GLB (maintained, Windows wheels through CPython 3.14). `kicad-tools` 0.14.0
  (MIT) is available as a maintained parser reference to borrow ergonomics from, but its
  high-level instance setters have a silent-no-op write bug, so only its low-level layer
  is trustworthy and our own span layer is preferred.
- **Previews (verified on kicad-cli 10.0.4, present in WSL and Windows)**:
  symbol SVGs via `kicad-cli sym export svg -s <name> [--black-and-white]` (transparent
  background by default, one SVG per unit named `<Name>_unitN.svg`); footprint SVGs via
  `kicad-cli fp export svg --fp <name> -l <layers>` (must be invoked on the `.pretty`
  directory plus `--fp`, never a bare `.kicad_mod`; transparent background). SVGs are
  re-tinted to the app theme client-side. 3D display via three.js from backend-converted
  GLB (cascadio). kicad-cli has no footprint-level 3D command (verified), which is why
  conversion happens in the backend.
- **Frontend**: Vite + TypeScript + a modern component framework, command palette,
  virtualized lists, three.js. Built dist committed. Any library that raises the bar is
  fair game (owner directive: make it phenomenal).
- **Window (verified 2026-07-12)**: pywebview 6.2.x on WebView2. Native drag and drop
  delivers full filesystem paths to the Python side (`pywebviewFullPath` via the DOM
  `drop` event), so large dropped zips are opened in-process with no HTTP upload; the
  fetch-upload path exists only for browser-picked files. Dark title bar follows the OS
  theme automatically. WebView2 is evergreen on Win10/11; the launcher checks the
  registry and silently runs Microsoft's ~2 MB Evergreen bootstrapper if missing.
  Known Windows trap (handled): Python's mimetypes reads the registry and can serve
  Vite JS bundles as text/plain; the backend registers JS MIME types explicitly before
  mounting static files. No service workers (stale-bundle risk after self-update).
- **Launcher (verified 2026-07-12, ComfyUI-Desktop-shaped)**: a frozen-once stub that
  (1) ensures WebView2, (2) fast-forward-pulls the repo, (3) runs the bundled `uv.exe`
  (`uv sync --frozen` against the committed `uv.lock`, auto-provisioning CPython on
  first run), (4) `uv run` launches the app. Git layer: probe PATH for git, else use
  dulwich for ff-only pulls; MinGit BusyBox (34 MB) fetched lazily only if repair
  tooling is ever needed. `uv.exe` (~24 MB) ships beside the launcher, not in git
  history.

## 9. Error handling

- Atomic mutations everywhere (staging, validate, move). No half-writes, ever.
- Timestamped backups before modifying anything not owned by Stockroom (KiCad tables,
  kicad_common.json, project files).
- Git as the undo system: every library change is a scoped commit; in-app history and
  revert per part.
- Round-trip validation after every KiCad file write.
- Honest degradation and honest reporting: no fake success, no swallowed errors,
  partial results labeled partial, every failure states what happened and what to do.

## 10. Testing

- **Backend**: pytest; golden-file round-trip tests for KiCad surgery; real vendor zips
  as fixtures; scraper tests against saved HTML fixtures; separate opt-in live smoke
  suite; property-based tests for the s-expression layer.
- **End-to-end**: Playwright driving the real UI against a real backend and fixture
  library (ingest, search, edit, profile switch, audit). E2E green is the merge gate.
- **Acceptance bar**: the owner's real Windows machine with real KiCad V10. WSL/Linux
  green is necessary, never sufficient, and claims always state which environment they
  rest on.
- **Design contract lint**: automated checks that the UI uses only contract tokens.

## 11. Security and privacy

- API keys live only in `%APPDATA%`, never in the repo.
- The repo may be private or public; nothing in it is machine-specific or secret.
- Scraping runs locally with ordinary single-page fetches (no crawling, no automation
  against login walls).

## 12. Acceptance criteria (v1 done means)

1. Drop a SnapEDA/UltraLibrarian/SamacSys zip: part lands fully linked (symbol,
   footprint, 3D, datasheet, fields) and is immediately placeable in KiCad on the same
   machine with zero manual steps.
2. Paste a Mouser link with a key configured: all fields fill from the API.
   Paste a manufacturer product link with no key: fields fill from the generic parser
   with visible sources and confidence.
3. Fresh machine: clone repo, run exe, complete first-run setup; KiCad immediately sees
   the full library; parts place with working 3D models.
4. Audit a real KiCad project: wizard steps through, adds one new part mid-flow,
   relinks recognized parts; project opens clean in KiCad afterward with all fields;
   the rewritten schematic diff touches only the lines that actually changed (byte
   preservation verified by the semantic-diff gate, not a whole-file rewrite).
5. Search returns correct results across every field; token filters compose; duplicate
   view finds a deliberately planted duplicate pair.
6. Update button pulls a new commit and relaunches on it without touching the exe.
7. Full test suite green (backend + E2E) in WSL AND the flows above verified on the
   owner's Windows machine against real KiCad V10.
