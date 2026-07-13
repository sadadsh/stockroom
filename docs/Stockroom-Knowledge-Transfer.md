# Stockroom: Knowledge Transfer and Progress Record

A single-file capture of everything designed, verified, and built for **Stockroom**, the
ground-up KiCad V10 component-library manager that replaces the old Hardware app. Current as
of 2026-07-12. Written so it can live in the Hardware repo as the record of where that effort
went and the hard-won facts it produced.

Repo: `github.com/sadadsh/stockroom` (public) · local `~/git/stockroom` · SSH remote.
No em dashes anywhere is a standing owner rule for all Stockroom output, honored here.

---

## 1. What Stockroom is, and why a rewrite

Stockroom is a Windows desktop app that manages a KiCad V10 component library with zero manual
bookkeeping. You drag in the zips you download (symbol, footprint, 3D model), paste a product
link, and the app does the rest: converts, names, categorizes, links footprint to symbol and
3D model to footprint, stores the datasheet and purchase link, fills every field, and registers
everything with KiCad so the part is immediately usable in any project. It can also audit an
existing KiCad project, step through its components, add unrecognized ones, and relink the
recognized ones.

It updates itself from git (no release builds), carries its library data inside its own repo
(clone anywhere, get the identical library and an identically wired KiCad), and presents a
minimal, monochrome, search-first UI.

**Why not keep the Hardware app.** The owner chose a clean-room rewrite for three reasons:
codebase quality/trust, the wrong tech and update model, and a UI that never felt right. The
directive was explicit: disregard the old app entirely, zero compromises, full end to end. The
Hardware app's *problem definition* was correct; its *implementation* is what Stockroom leaves
behind. This document is the bridge between the two.

**Non-goals (v1):** no BOM building, PCB setup, bench tooling, or routing (Stockroom is a
components manager only); no multi-user permission system (sync is git, collaborators are
trusted committers); no EDA tool other than KiCad and no KiCad below 9 (target is V10).

---

## 2. Architecture and stack (the decisions and the why)

Three layers in one repository, with strictly different change rates:

```
stockroom/
  launcher/            Frozen to Stockroom.exe ONCE. Never rebuilt for app changes.
  app/
    backend/           Python (FastAPI). All logic lives here.
    frontend/          TypeScript SPA source.
    frontend-dist/     Built UI, committed to git. Users never need Node.
  libraries/
    <Profile>/         A library profile (one folder per profile).
      parts/           One JSON file per part (metadata records).
      symbols/         Per-category .kicad_sym libraries.
      footprints/      Per-category .pretty directories.
      models/          STEP/WRL 3D models.
      datasheets/      PDF per part.
  docs/                Spec, plans, research seeds, ledger of deferrals.
```

**Process model.** `Stockroom.exe` (the launcher) ensures the Python runtime and deps exist
(pinned by `uv` against a committed lockfile), starts the FastAPI/uvicorn backend on
`127.0.0.1` on an ephemeral port, and opens a native WebView2 window (pywebview) onto the
frontend served by the backend. All heavy work (zip inspection, format conversion, STEP-to-GLB,
scraping, enrichment, git, KiCad config surgery, search) runs in the backend; the window is
pure presentation.

**Update flow.** An Update control (and a non-blocking on-launch check) does
`git pull --ff-only` on the app repo, then `uv sync`, then a graceful backend restart and window
reload. One pull updates code, UI, and library data together. If the pull is not fast-forwardable
the app does not guess; it surfaces the state and offers safe resolutions.

**Per-machine state (outside the repo).** `%APPDATA%/Stockroom/config.json`: active profile,
window state, KiCad install path, API keys, sync preferences. Nothing machine-specific or secret
ever enters the repo. A missing Mouser key just means enrichment falls back to the generic parser.

### Stack decisions and rationale

| Area | Choice | Why this over the alternatives |
|---|---|---|
| Backend | Python 3.12+, FastAPI + uvicorn | All logic server-side; the window is a thin client. |
| KiCad file surgery | **Purpose-built span-preserving s-expression layer** | See section 3.1. Every existing library was disqualifying. |
| Window | pywebview on **WebView2** (evergreen) | Native drag/drop delivers full filesystem paths to Python, so big zips skip HTTP upload. Doubles as the scraping fallback engine. |
| Previews | The user's own `kicad-cli` for SVGs; three.js for 3D from backend-converted GLB | No re-implementation of KiCad rendering; always matches the installed KiCad. |
| 3D convert | `cascadio` + `trimesh` (STEP to GLB) | `kicad-cli` has no footprint-level 3D export, so conversion is a backend step. |
| LCSC import | `easyeda2kicad` | LCSC has no KiCad zip; the ecosystem standard is API-fetch-and-convert keyed on the `Cxxxxx` number. |
| Scraping HTTP | `curl_cffi` (Chrome-impersonating TLS) | Plain-Python TLS is fingerprinted and blocked by Akamai even on good IPs. |
| Update model | git pull (ff-only), no release builds | One pull ships code + UI + library data together; the exe is frozen once. |
| Frontend | Vite + TS + React + Tailwind v4, cmdk palette, TanStack Virtual/Query, three.js, lucide | Built dist committed so end users never need Node. |
| VCS access | `git` binary via subprocess (dulwich fallback for machines without git, in the launcher) | Same wrapper shape as the kicad-cli wrapper; dev/CI always have git. |

**Why NOT the official KiCad IPC API (kicad-python / kipy):** verified out of scope for V10. It
operates on live editor sessions, not files; has no `.kicad_sym` library manipulation; and its
schematic access plus headless `api-server` are KiCad 11 features. Revisit at KiCad 11 for the
audit's schematic work; the file layer is the path now.

---

## 3. Empirically-verified technical findings (the load-bearing facts)

Everything here was verified against the owner's real machines and real KiCad 10 files, not from
model memory. These are the facts the whole app rests on.

### 3.1 KiCad file surgery: why a custom byte-preserving layer

Head-to-head testing against the owner's real KiCad 10 files (`NETDECK/.../Power_Supply.kicad_sch`
and `Hardware/libs/MySymbols.kicad_sym`) was decisive:

- **kiutils is dead** and silently drops about 16% of nodes on V10 files.
- **Every other library** (kicad-skip, kicad-tools, kicadfiles, kicad-sch-api, edea) rewrites the
  WHOLE file: CRLF becomes LF, lists refold, so a one-property edit becomes a whole-file diff.
  That is disqualifying here specifically because the library is git-synced and every edit is a
  commit. A whole-file diff destroys the value of per-line history and invites merge conflicts.

**Chosen: a purpose-built span-preserving s-expression layer.** It tokenizes to a tree where each
token records its exact byte offsets, applies edits by splicing replacement text into the original
byte string, and never re-serializes untouched regions. A validated proof of concept edits a real
schematic with a **2-line byte diff**, preserving CRLF, tabs, and token order, with `kicad-cli`
parsing the result clean. The layer is format-version-agnostic by construction, so KiCad 11 tokens
will round-trip untouched. This shipped as M1 (see section 4).

Design rules that fell out of building it:
- Edits are recorded as `(start, end, replacement, seq)` and applied from the highest offset down
  so earlier offsets stay valid. A replacement has `start < end` (deduped by span, last write wins);
  an insertion has `start == end` (never deduped, ordered by `seq`).
- Overlapping edits are a hard error (fail loud, never splice garbage). Inserting inside a replaced
  span is likewise rejected.
- A freshly inserted node is read-only in-session (its spans point into its own fragment text, not
  the main document); re-editing its value needs a reload. Inserts must anchor on ORIGINAL text.
- Reads use `newline=""` so CRLF survives exactly. `Path.read_text` does not accept `newline=` on
  Python 3.12, so use `open()`.

### 3.2 Version stamps: never invent one

- V10 `.kicad_sym` stamps `(version 20251024)`. **V9 refuses V10-stamped files.** Changes since V9
  are additive tokens plus a semantic change where `~` no longer means empty text.
- Policy: surgical edits PRESERVE the file's existing version stamp and all untouched tokens, so a
  V9-compatible library never gets silently upgraded out of compatibility.
- New category libraries are stamped by the user's installed KiCad, never by Stockroom. **Verified
  route:** feed an empty `EESchema-LIBRARY Version 2.4` legacy `.lib` through `kicad-cli sym
  upgrade` and it emits a valid empty `.kicad_sym` stamped `(version 20251024)` with KiCad's own
  CRLF/TAB formatting. This is how empty per-category symbol libs get created.

### 3.3 KiCad config layout and the lib-table writer (verified from the real files)

Config lives at `%APPDATA%\kicad\10.0\` on Windows and `~/.config/kicad/10.0/` on Linux. The real
global `sym-lib-table` on the owner's machine (CRLF line endings, TAB indent):

```
(sym_lib_table
	(version 7)
	(lib (name "KiCad") (type "Table") (uri "/usr/share/kicad/template/sym-lib-table") (options "") (descr "KiCad Default Libraries"))
	(lib (name "MySymbols") (type "KiCad") (uri "/home/sadad/git/Hardware/libs") (options "") (descr ""))
)
```

Load-bearing facts:
- Format is `(version 7)`; rows are `(lib (name ..) (type ..) (uri ..) (options "") (descr ..))`.
- **V10 chains the stock libraries through a `(type "Table")` row.** The writer must append only
  its own `(type "KiCad")` rows and never touch the Table row or any non-Stockroom entry.
- Footprint rows point their `uri` at a `.pretty` DIRECTORY; symbol rows point at a `.kicad_sym`
  file.
- Stockroom writes one path variable `SR_LIB` into `kicad_common.json` under `environment.vars`,
  then registers each category library with a `${SR_LIB}`-based URI and an `SR-` nickname. Profile
  switch is therefore a one-variable flip plus a table refresh, and the same library resolves
  identically on every machine.

**`kicad_common.json` reality:** KiCad ships `"environment": { "vars": null }` (literally null).
The writer must materialize that to an object. Because KiCad rewrites this file every run and it
lives outside the repo, a whole-file JSON re-serialize is safe here (unlike the library files),
but it still gets a timestamped backup and a parse-validate after write.

The writer's four properties (spec-mandated, enforced): **idempotent** (no change when already
correct), **scoped** (never touches non-Stockroom entries), **safe** (timestamped backup before
modifying anything Stockroom does not own, parse-validate after), **aware** (detects a running
KiCad and reports that a restart is needed for table changes to load).

### 3.4 Previews (verified on kicad-cli 10.0.4)

- Symbol SVG: `kicad-cli sym export svg -s <name> [--black-and-white]`. Transparent background by
  default, one SVG per unit named `<Name>_unitN.svg`.
- Footprint SVG: `kicad-cli fp export svg --fp <name> -l <layers>`. Must be invoked on the
  `.pretty` DIRECTORY plus `--fp`, never on a bare `.kicad_mod`. Transparent background.
- No footprint-level 3D command exists, which is why 3D conversion (STEP to GLB) is a backend step.
- SVGs are re-tinted to the app theme client-side.

### 3.5 Vendor zip ingestion: fingerprint by content, never by origin

A zip "from DigiKey" or a manufacturer site can be any of several backend layouts, so identity is
decided by what is INSIDE the archive. Modeled on the actively-maintained reference importer
`Steffen-W/Import-LIB-KiCad-Plugin` (`identify_remote_type()`, verified current 2026):

- **Octopart:** contains `device.lib` + `device.dcm` (fixed legacy filenames).
- **SamacSys / Component Search Engine** (Mouser's and DigiKey's "ECAD Model" download): a folder
  named exactly `KiCad`, with a LOOSE `.kicad_mod` (not a `.pretty`) plus `.kicad_sym` or legacy
  `.lib` + `.dcm`. Ignore sibling `.epw` files and per-EDA folders (`Altium/`, `EAGLE/`).
- **UltraLibrarian:** a folder named exactly `KiCAD` (the capitalization is the load-bearing
  discriminator from SamacSys), containing a real `.pretty` dir, often with several near-duplicate
  footprint variants, and a symbol file frequently named by a generation TIMESTAMP
  (`2025-02-10_09-58-00.lib`), so part identity is NEVER derived from the symbol filename.
- **SnapMagic/SnapEDA:** the fallback (no marker folder), loose `.kicad_sym` + `.kicad_mod` +
  `.step` + a `how-to-import.htm` marker; datasheet sometimes bundled.
- **Partial:** a zip carrying only a 3D model (attach to an existing part or hold for the next add).

Realities the pipeline handles because vendors do not: 3D models sit anywhere in the zip (glob the
whole archive, priority `.step` then `.stp` then `.wrl`); NO vendor wires the 3D model into the
footprint, so Stockroom writes the `(model ...)` link itself as `${SR_LIB}/models/...`; a loose
`.kicad_mod` is synthesized into a proper `.pretty`; a multi-footprint `.pretty` presents its
variants for the user to pick. Legacy `.lib` is a standard input (converted via `kicad-cli sym
upgrade`, which also handles Altium/EAGLE/CADSTAR/EasyEDA), not an edge case, since vendors still
ship it in 2026.

### 3.6 Enrichment (planned for M4, research complete)

Layered, best source first, every field carrying its source and confidence:

1. **Mouser Search API v2** (free key, 1000/day, 30/min). Auth is an `apiKey` query parameter;
   requests are JSON POST. Lookup by MPN or by the MPN extracted from a `mouser.com` URL
   (`/ProductDetail/{Manufacturer}/{MPN}`; the trailing `qs=` token is opaque and ignored).
   Type-handling verified: price is a currency-symbol STRING, stock and discontinued arrive as
   strings, so the parser coerces them.
2. **Generic URL parser** (no key, held to the same bar): fetch with `curl_cffi` Chrome
   impersonation, then a cascade of schema.org JSON-LD Product markup, OpenGraph/meta, per-site
   extractor modules (preferring `data-*` over CSS classes), embedded JS state
   (`__NEXT_DATA__`-style), then heuristics.
3. **In-window WebView2 fallback** (what makes generic parsing match the API bar): bot-protected
   sites (Cloudflare on DigiKey/TME, Akamai on Mouser/Farnell/RS/ST) defeat any HTTP client when a
   JS challenge fires. Since Stockroom hosts a real WebView2 engine, it loads the page in an actual
   browser context and reads the rendered DOM. User-initiated, one page at a time, never a crawler.
4. **Datasheet fetcher:** follow the PDF link with a real User-Agent and a Referer set to the
   source page, retry over HTTP/1.1 when HTTP/2 fails (verified necessary for Mouser's datasheet
   CDN), and validate by `Content-Type` plus `%PDF-` magic bytes (rejecting HTML viewer wrappers).

Enrichment never silently overwrites a filled field; changes to existing values are per-field
opt-in.

### 3.7 Window and launcher (verified 2026-07-12)

- pywebview 6.2.x on WebView2. Native drag/drop delivers full filesystem paths to Python
  (`pywebviewFullPath` via the DOM `drop` event), so large dropped zips open in-process with no
  HTTP upload; the fetch-upload path exists only for browser-picked files.
- Known Windows trap (handled): Python's `mimetypes` reads the registry and can serve Vite JS
  bundles as `text/plain`, giving a blank window. The backend registers JS MIME types explicitly
  before mounting static files. No service workers (stale-bundle risk after self-update).
- Launcher (ComfyUI-Desktop-shaped): a frozen-once stub that ensures WebView2, fast-forward-pulls
  the repo, runs the bundled `uv.exe` (`uv sync --frozen`, auto-provisioning CPython on first run),
  then `uv run` launches the app. Git layer: probe PATH for git, else dulwich for ff-only pulls;
  MinGit fetched lazily only if repair tooling is ever needed. `uv.exe` ships beside the launcher,
  not in git history.

---

## 4. What is built so far

### M1: Foundation (SHIPPED, merged to main, CI green on ubuntu + windows)

The byte-preserving KiCad file core. Delivered and verified:
- `sexp/`: span-preserving tokenizer + document/node tree with read-after-write, safe ordered
  inserts, and an overlap guard. Byte-identical round-trip proven by a gate.
- `verify/`: an independent semantic-diff gate (`semantic_diff`, `assert_only_changed`) using its
  own minimal parser, so it can catch bugs in the edit layer. Asserts only intended nodes changed.
- `kicad/`: file models `SymbolLib`/`Symbol` (property get/set), `Footprint` (3D-model link edit),
  `Schematic`/`SymbolInstance` (instance enumeration + byte-preserving rewrite), and a `kicad-cli`
  wrapper (version, sym upgrade, sym/fp SVG export).
- CRLF fixtures + round-trip + `kicad-cli` parse-back gates. CI on ubuntu + windows.
- **Status:** 60 pure-Python tests green on Windows CI; 5 kicad-cli integration tests skip on CI
  (no KiCad on the runner), green locally on WSL with kicad-cli 10.0.4. The one remaining M1
  verification gap is running those 5 integration tests on the owner's real Windows machine.

The M1 review loop (subagent implementer per task, per-task review, whole-branch review) caught and
fixed several real corruption paths in the edit API: remove-then-insert ordering, removing an
inserted node, overlapping edits, a multi-insert silent-corruption bug, and a read-after-write gap.
All closed and independently re-reviewed.

### M2: Library data model, profiles, git sync, KiCad wiring (IN PROGRESS)

16-task plan, built straight through. As of this writing:
- **Green and committed:** `model/` (fixed 13-category taxonomy + the part record with canonical
  merge-friendly JSON), `store/` (per-machine config resolver, library profiles with
  git-committed create/delete), `vcs/` (git wrapper with scoped commit + rollback, and a
  pull-before-push ff-only sync engine). 42 tests passing.
- **Building:** `kicad/` (config-dir resolver, empty-category-lib creator, byte-preserving
  lib-table writer that spares the V10 Table row, `kicad_common.json` `SR_LIB` writer, wiring
  orchestrator) and `mutation/` (git-backed atomic transaction, add/edit/move/delete part,
  drift detection).

Two real bugs found and fixed during the M2 build that are worth recording:
1. **Sync first-push:** a freshly cloned empty remote has a remote but no upstream ref, so keying
   "has remote" off `@{upstream}` wrongly reported no-remote. Fix: detect the remote via
   `git remote`, and set upstream on the first push (`git push -u origin <branch>`).
2. **Scoped commit of deletions:** `git add` must be `git add -A` so a scoped commit stages the
   DELETION of tracked files removed from the working tree (profile/part deletion), not just
   adds and modifications.

M2 adds **no new Python runtime dependencies**; it is stdlib-only at runtime, using subprocess to
the `git` and `kicad-cli` binaries. The heavier deps (curl_cffi, cascadio, easyeda2kicad, fastapi,
pywebview) arrive in M3 to M5.

---

## 5. Key engineering learnings (the transferable lessons)

1. **Byte preservation is not a nicety, it is the whole game for a git-synced library.** Any tool
   that reformats on write turns every one-field edit into a whole-file diff, which destroys
   history and invites merge conflicts. This single constraint disqualified every off-the-shelf
   KiCad Python library and forced the custom span layer. If the Hardware app or any successor ever
   git-syncs KiCad files, it needs the same property.
2. **Verify against the real files, never from memory.** Every load-bearing format fact here
   (the Table row, `environment.vars: null`, the `20251024` stamp, the CRLF/TAB row layout, the
   empty-lib-via-sym-upgrade trick) came from reading the owner's actual KiCad 10 config and
   running kicad-cli, not from assumptions. Several would have been wrong from memory.
3. **Fingerprint vendor zips by content, not by where they came from.** The same "DigiKey"
   download can be three different backend layouts. Filename-based identity (especially trusting
   UltraLibrarian's timestamp-named symbol files) is a trap.
4. **Git is the transaction log and the undo system.** Every library mutation stages, validates
   (re-parse every written KiCad file, semantic-diff for edits), then commits as one scoped commit;
   a failed mutation restores the touched paths from HEAD and leaves zero trace. This is simpler
   and more robust than a bespoke journaling scheme, and it gives per-part history for free.
5. **An independent verification gate catches edit-layer bugs a self-test cannot.** The
   semantic-diff gate uses its own parser precisely so it does not share bugs with the code it
   checks. It caught real corruption during M1.
6. **The WebView2 engine you already ship is your scraping escape hatch.** Rather than an arms race
   against Cloudflare/Akamai with HTTP clients, load the page in the real browser context you
   already have and read the DOM.
7. **A subagent-driven build with adversarial review pays for itself.** Independent reviewers over
   the plan caught a genuine build-breaker (profile delete) and an encapsulation smell before a
   16-task build; the per-task test gates caught two more real bugs (sync, deletion staging) during
   the build. Per-task commits also made a mid-build process death fully recoverable.
8. **Honest degradation over fake success.** No swallowed errors, partial results labeled partial,
   every failure states what happened and what to do. Offline is a first-class state; divergence is
   surfaced with exact state and safe options, never clobbered.

---

## 6. Milestone roadmap

| M | Scope | Status |
|---|---|---|
| M1 | Foundation: byte-preserving KiCad file core, semantic-diff gate, file models, kicad-cli wrapper | Shipped, merged, CI green |
| M2 | Library data model, profiles, git sync, KiCad wiring, atomic mutation engine | In progress (store/vcs green, kicad/mutation building) |
| M3 | Ingestion: content-fingerprint zip adapters, legacy upgrade, 3D re-linking, staging, LCSC path | Planned |
| M4 | Enrichment: Mouser API v2, generic parser, in-window WebView2 fallback, datasheet fetcher | Planned |
| M5 | Backend API + app shell + frozen-once launcher + git-pull self-update | Planned (needs Windows) |
| M6 | Frontend UI: library, Ctrl+K palette, symbol/footprint/3D viewers, ingest, duplicates, settings, doctor | Planned |
| M7 | Project audit: sheet-hierarchy parse, match cascade, step-through wizard, apply | Planned |

Each milestone produces working, testable software and is built, adversarially reviewed, and
merged before the next. The milestones are a dependency chain (M3 calls M2's mutation engine, M6
calls M5's API, M7 reuses M2 + M1), so they cannot be built truly in parallel. Two things always
need one pass on the real Windows machine with KiCad 10: the launcher (M5) and the final KiCad
wiring/preview verification. WSL/Linux green is necessary, never sufficient.

---

## 7. Repo layout and how to run

- Backend package imports as `stockroom`, living at `app/backend/stockroom/`.
- Toolchain: Python 3.12, `uv` (lockfile-pinned), pytest. Node 20 + npm for the frontend (built
  dist committed, so end users never need Node). kicad-cli 10.0.4 for integration tests and
  previews.
- Run the backend tests: `uv run pytest tests/backend -q`. kicad-cli integration tests auto-skip
  when the binary is absent.
- CI: GitHub Actions matrix on ubuntu-latest and windows-latest (the release gate). kicad-cli
  tests skip on CI because there is no KiCad on the runners.

Testing philosophy: golden-file round-trip tests for KiCad surgery, real vendor zips as fixtures,
scraper tests against saved HTML fixtures, a separate opt-in live smoke suite, property-based tests
for the s-expression layer, and (from M6) Playwright E2E as the merge gate. The acceptance bar is
the owner's real Windows machine with real KiCad V10; claims always name the environment they rest
on.

---

## 8. Open items and deferrals (logged, not hidden)

- **M1 real-Windows kicad-cli run.** The 5 integration tests are green on WSL and skipped on CI;
  they still need one run on the owner's Windows machine with KiCad 10 installed.
- **Interactive drift heal (`doctor` UI).** M2 ships drift DETECTION (compares each part's JSON
  against its mirrored symbol properties and returns a diff). The show-a-diff-then-heal flow is the
  M6 doctor surface.
- **Background sync timer.** `SyncEngine.sync()` is complete and tested; the periodic scheduler and
  post-commit-batch trigger are wired in M5 (backend lifecycle).
- **dulwich / bundled-git fallback.** The backend requires the `git` binary (present in dev/CI and
  guaranteed by the launcher). The dulwich ff-pull fallback for end-user machines without git is M5
  launcher scope.
- **File-level locking for concurrent same-library writes.** M2 assumes single-threaded
  per-profile access (the synchronous mutation engine guarantees this today). When M5 puts the
  engine behind concurrent FastAPI requests, symbol-lib writes take an fcntl/msvcrt lock.
- **`kicad-cli fp upgrade` for foreign footprints.** M2 places already-KiCad `.kicad_mod`
  footprints; legacy/foreign footprint upgrade is part of the M3 ingestion convert stage.
- **Encapsulation cleanup.** A review flagged that the M2 placement code reaches into the M1
  file models' private document; the planned cleanup adds public `SymbolLib.insert_symbol` /
  `remove_symbol` and `Footprint.set_name` mutators. Functional, but tidied before the M2 merge.

---

*This file is a snapshot. The living sources of truth are the spec at
`docs/superpowers/specs/2026-07-12-stockroom-design.md`, the per-milestone plans under
`docs/superpowers/plans/`, and the project ledger in the Brain vault
(`Agent/Stockroom Log.md`).*
