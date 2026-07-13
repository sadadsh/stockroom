# Stockroom — KiCad-Ecosystem Research Findings

Synthesis of 5 research clusters (library-managers, ingestion, enrichment-bom, plumbing-projects, previews-diff), covering 18 tools. Load-bearing code claims (KiCost sliding-window limiter, priority-registry fall-through, KiABOM exact-MPN match) were re-verified against the pulled source before ranking.

The single strongest cross-cutting signal: **13 of 18 tools independently converged on Stockroom's core architecture** (text/JSON source of truth, generated-and-disposable KiCad artifacts, per-part/per-MPN keying, no live DB), and **every general-purpose read/write library in the study reformats-on-write** — which is the exact gap Stockroom's byte-preserving layer fills. The one genuine challenge is to the *scraper-first* premise (see §3).

---

## 1. Top opportunities (ranked by value)

1. **Structural (not filename) vendor fingerprinting with an explicit "Partial / 3D-only" branch** — from **Steffen-W/Import-LIB-KiCad-Plugin** (`identify_remote_type`). *M3.* This is the heart of M3 and the plugin already solved the load-bearing edge cases: probe the zip's *structure* recursively (Octopart = `device.lib`+`device.dcm`; Samacsys = `KiCad/` dir; UltraLibrarian = `KiCAD/` dir — the casing difference is real and load-bearing; SnapEDA = fallthrough), and have a dedicated branch for archives that contain **only a 3D model**. **Action:** reimplement the ordered structural-probe (GPL-3.0 → reference, don't vendor), keyed on marker files/dirs, with an explicit partial/degenerate branch, then dedup on **MPN + content-hash in your JSON/SQLite layer** (Import-LIB is stuck on name-only identity — that gap is your value-add).

2. **`kicad-cli`-for-upgrades + targeted string-edit for the model path — never re-serialize** — from **Import-LIB** + **easyeda2kicad**. *M3, validates cross-cutting byte layer.* Import-LIB shells out to `kicad-cli sym upgrade`/`fp upgrade` for legacy `.lib`→`.kicad_sym`, and does the 3D-model-path rewrite as a targeted `re.sub(r'(\(model\s+)"[^"]*"', …)` that "leave[s] everything else untouched." **Action:** adopt this exactly — don't build a v4→v6 converter, and prove your byte-preserving writer by doing model-path edits as scoped token substitution, not a round-trip.

3. **Atomic write + `.backup` + re-parse-verify as the mechanized complete-to-add gate** — from **Import-LIB** (write to `.tmp` → re-parse to confirm non-empty → rename over original; `.backup` first, restore on any failure) + **eeintech-csv** (diff-then-write with explicit per-field change logging: `(F.upd) "Footprint": old -> new`). *M3, cross-cutting.* **Action:** make the byte-preserving writer touch only changed tokens, log each change, verify-then-commit, and fail loudly ("can't add without a template/assets") rather than emit a broken part. This *is* your complete-to-add gate, mechanized.

4. **Priority-registry `remaining`-set fall-through + sliding-window rate limiter** — from **hildogjr/KiCost** (MIT — code-reusable). *M4.* Verified in source: `distributor.py` walks APIs in priority order, each returns the set it solved, `remaining -= solved` so the next tier only handles leftovers; `api_mouser.py` keeps a timestamp list (`LIMIT=30`/`WINDOW=60`), bursts to the cap then sleeps `WINDOW − elapsed + 0.1` and pops the oldest. This is strictly better than KiABOM's blunt "sleep a full 60s" counter. **Action:** this is the concrete backbone of tiered M4 enrichment (LCSC-free → scraper → Mouser-API). MIT → you may lift the limiter and registry code directly.

5. **Key everything on MPN, cache per-part with TTL, and prefer exact-MPN-match on multi-result responses** — from **KiCost** + **Mage/KiABOM** (both converged independently; verified `kiabom.py:389–395`). *M4, validates core design.* KiABOM: normalize MPN (`/`,`\`→`-`) to a filesystem-safe key, cache one `mpn___<epoch>.pickle` per MPN with epoch-in-filename TTL, and **never trust `parts[0]`** — pick the row where `part.mpn == mpn` (a keyword search returns near-matches; blindly taking result #0 is a classic wrong-part bug). KiCost prefixes cache keys `mou_` vs `mpn_` so a part cached under its SKU and its MPN don't collide. **Action:** adopt all four; add KiABOM's `--ignore-mpns` skip list to cut API calls for house parts.

6. **Embed kicanvas (MIT) for interactive symbol/footprint previews instead of per-part `kicad-cli` SVG** — from **theacodes/kicanvas**. *M6.* Vanilla-TS WebGL viewer, ships as a Web Component (`<kicanvas-embed>` / inline `<kicanvas-source>`), pure static esbuild bundle, CSP-friendly, no KiCad binary and no network in the render path — a clean fit for pywebview/WebView2, and strictly richer than one-shot SVG (pan/zoom/select, live re-theme). Its parser already fully models `LibSymbol` (pins/units/`extends` inheritance). **Caveat → budget for it:** kicanvas has **no standalone `.kicad_sym`/`.kicad_mod` loader** (`project.ts` only dispatches `.kicad_sch`/`.kicad_pcb`/`.kicad_pro`). **Action:** either synth a throwaway minimal `.kicad_sch` (the part's `lib_symbols` block + one instance) and `.kicad_pcb` (one footprint) in memory and feed via inline `<kicanvas-source>`, or fork `project.ts`'s loader to accept lib files (parser already does the hard part). Keep `kicad-cli` for 3D/STEP and as a headless SVG fallback.

7. **Read part history straight from git objects — never checkout, never mutate** — from **plotgitsch** (`gitFs.ml`/`git-unix` blob reads) + **kiri** (`git archive <hash> | tar`). *Cross-cutting + M6.* plotgitsch reads blobs directly from the object store (`Store.read`) with no checkout and no temp files — the cleanest precedent for "render this part as it was at commit X." **Action (Python):** `pygit2` `repo.revparse_single(rev).tree[path].data` or `git cat-file -p <rev>:<path>`. This keeps git clean by construction and directly serves the "what changed in this part" view.

8. **Two-tier diff: structured field-diff on the JSON record + visual old-vs-new SVG overlay** — from **plotgitsch** (internal semantic diff vs `Image_Diff`) + **kiri** (`kiri.js` two-SVG filter/opacity toggle + commit stepper). *M6.* plotgitsch proves both are worth having, and the semantic one is far more useful for a component record (added/removed/changed fields, MPN, footprint assoc, datasheet URL). The semantic diff is *trivial on your per-part JSON and awkward on raw s-expr* — a direct payoff of JSON-as-source. **Action:** field-diff the JSON, render an old-vs-new SVG overlay (kicanvas or `kicad-cli`) for the visual side; kiri's two-SVG toggle is a ready-made React/Tailwind UI.

9. **KinJector's per-concern flat-JSON Projects model + partial-merge semantics** — from **devbisme/kinjector** (MIT — schema/merge code reusable). *M7.* Its `dict_key` schema is a direct precedent for the M7 editor: `design rules`; net classes split into **`definitions` + `assignments`** (net-name → class-name, a two-part model — don't inline the class into each net); `track width list`; `via dimensions`; `diff pair dimensions`; `modules` keyed by refdes with `position{x,y,angle,side}`. Its `merge_dicts` means a partial edit only touches the keys it names. **Action:** adopt the schema shape and partial-merge (so editing net-classes never rewrites design-rules), but route the actual write through Stockroom's byte layer — **not** `pcbnew.LoadBoard/Save` (that rewrites the whole file, the exact churn you're avoiding).

10. **KiBoM's BOM grouping-correctness rules, verbatim** — from **SchrodingersGat/KiBoM** (MIT). *M7.* Three cheap-to-reimplement rules that are each a shippable bug if missed: (a) **component-alias equivalence** (`c/c_small/cap/capacitor`, `r/r_small/res/resistor`) so the same cap drawn with different symbols merges into one row; (b) **numeric value-normalization before grouping** so `0.1uF` and `100n` group together (naive string-equality splits them); (c) **DNF/DNP spelling set** (~10 spellings: "dnp"/"no stuff"/"noload"…, case-insensitive) + `REGEX_EXCLUDE` to strip test points/fiducials/mount-holes by ref/footprint pattern. **Action:** adopt all three. **Caveat:** take the grouping logic, *not* KiBoM's ingestion path — it consumes the legacy XML netlist, which is going away in V10.

11. **Category-keyed supplier→canonical field-mapping engine with parent/child inheritance** — from **sparkmicro/Ki-nTree** (`supplier_parameters.yaml`) + **kicadLibCreator** (category-linked fill rules). *M4.* Two independent tools converged on category-driven field rules as the one abstraction that makes multi-source enrichment tractable: normalize heterogeneous scraped/API fields into one canonical schema *per category*, with per-supplier name overrides. **Action:** build M4 enrichment on this shape (re-implement clean — Ki-nTree is GPL-3.0). Don't hand-enter fields; derive them per category.

12. **Fuzzy value-normalization + footprint-gated consolidation for the dedup layer** — from **Boms-Away** + **KiBoM**. *M3 dedup / M4.* `10K`==`10 K`==`10k` collapse to one canonical value, **but only consolidate parts sharing a footprint** — a good guardrail against false merges. **Action:** feed this into the SQLite-index dedup on top of the MPN+content-hash identity from opportunity #1.

---

## 2. Design validations (ecosystem confirms Stockroom's choices)

**Byte-preserving custom s-expression layer — VALIDATED, overwhelmingly (all 5 clusters).** This is the most-corroborated finding in the study:
- **Three independent general-purpose libs all reformat/lose bytes on write:** KinJector (via `pcbnew.LoadBoard/Save`), kicad-rw (via `sexpdata.dumps()` renormalizing whitespace/quoting/floats), and pykicad (via its OO model's `to_file()`). None preserves comments, field ordering, or unmodeled tokens.
- **The two most-used Python ingestion tools *deliberately refuse* to re-serialize** just to change one field: Import-LIB does a targeted regex sub and comments "leave everything else untouched"; easyeda2kicad passes STEP through unchanged.
- **Ki-nTree deliberately chose a "SCM-friendly" parser (KiUtils)** specifically to keep git diffs sane — the entire justification for your layer, arrived at independently.
- **Hard requirement this surfaces:** your layer must **losslessly pass through tokens it does not model** (comments + KiCad V10 additions a V5-era model never knew), which a schema-bound OO model (pykicad) structurally *cannot* do. This is the bar all three generic libs fail.

**Text-source + derived index over KiCad-native DB (`.kicad_dbl`) — VALIDATED by unanimous omission (clusters 1, 2, 3).** **Not one of the 18 tools uses `.kicad_dbl`.** The closest atomic-part manager (kicad-db-lib) independently chose **JSON-per-part → regenerate `.kicad_sym`**, explicitly for sync/VCS friendliness, and treats `output/` as disposable/rebuildable — exactly your "derived index is disposable" stance. KiCost and KiABOM both use a flat per-MPN file cache with mtime/epoch TTL, never a heavyweight DB for the source of truth. Your JSON-as-truth + SQLite-index-as-derived is the mainstream-validated shape, not a novelty.

**Per-part JSON as source of truth — VALIDATED (clusters 1, 3, 4).** kicad-db-lib is JSON-per-part in production, cross-platform. KiCost and KiABOM both key everything on MPN and cache per-part. plotgitsch's semantic (field-level) diff is *natural on JSON, painful on s-expr* — reinforcing JSON as the diff/source layer. Boms-Away's *anti-pattern* (smearing the record across reserved schematic fields `SPN/MPN/SPR/MFR`) validates keeping the authoritative record in JSON by counter-example.

**Scraper-first enrichment — PARTIALLY validated, with a serious caveat (see §3).** The *fragility of single-proprietary-API binding* is validated: kicadLibCreator is effectively dead because it bound to Octopart (now paywalled), and KiCost's one free aggregator (Kitspace PartInfo) is hard-marked dead in-source. Multi-source is clearly right. Ki-nTree treats API cache/rate-limits as first-class. **But scraper-*first* specifically is challenged** — the caveat is real and belongs in §3.

**WebView2 previews — VALIDATED and upgradeable (cluster 5).** kicanvas is a drop-in interactive WebGL viewer that beats one-shot `kicad-cli` SVG for the interactive symbol/board case, is CSP-friendly and network-free once bundled, and fits pywebview/WebView2 exactly. kiri + plotgitsch prove you can drive a full git-history visual diff *without ever mutating tracked files* — validating the git-synced-library + byte-preserving design together.

**Complete-to-add gate (identity + assets + sourcing) — VALIDATED (clusters 2, 3, 4).** eeintech's honest "component X could not be added: missing template file" and Import-LIB's verify-then-commit both match your gate philosophy. plotgitsch's real-world failure — "cache lib wasn't committed → component-not-found on old revs" — is *exactly* what your gate prevents, and argues for a commit-time check that every referenced asset is in the same tree. kicad-db-lib's unsolved TODOs (uniqueness validation, dedup) are precisely what your gate + SQLite dedup own.

---

## 3. Design challenges / risks (be honest)

**RISK 1 — "scraper-first" is challenged by the single most experienced tool in this space.** *(cluster 3, the one real pushback.)* KiCost's `HISTORY.rst` is a graveyard of dead scrapers ("Fixed RS scrape module," "re-factored… to decrease probability of ban," "Fixed scraping of Digi-Key pages…"). After ~a decade of scraper-first, KiCost **ripped scraping out entirely** and moved to `distributors/api_*.py`, because scrapers break on every site redesign and get your IP banned. This does not kill the plan, but it should **reframe** it:
- Treat scraping as a *best-effort enrichment tier that is expected to rot*, not the primary path you minimize the API "toward zero."
- Make the **Mouser API the reliable floor**, not the thing you avoid.
- **The complete-to-add gate must NOT hard-depend on any scraped field** — a dead scraper must never block a part from reaching "complete." Keep per-part JSON authoritative so enrichment failures degrade gracefully.
- Net: keep the multi-source, scraper-*aware* design; drop the framing that the API is a rate-limited nuisance to route around. It's your dependable floor.

**RISK 2 — AGPL-3.0 reach from easyeda2kicad into the FastAPI backend.** *(cluster 2, sharpest license constraint.)* easyeda2kicad is **AGPL-3.0**; its network-use clause means if Stockroom's FastAPI backend *imports it in-process* and is ever served over a network, the AGPL can reach your whole app. **Mitigation:** invoke it strictly as a **subprocess/CLI** (its supported entrypoint), keep it an optional external dependency, never link it into your own-licensed Python. Also note Import-LIB **bundles easyeda2kicad as a submodule** — copying their LCSC integration wholesale imports the trap.

**RISK 3 — no precedent anywhere for standalone `.kicad_sym`/`.kicad_mod` preview.** *(clusters 1 + 5.)* The library-managers cluster has *zero* preview precedent, and kicanvas — your best option — cannot load a bare symbol/footprint file (it only dispatches `.kicad_sch`/`.kicad_pcb`/`.kicad_pro`). M6 must budget for either the synth-a-throwaway-container trick or a kicanvas loader fork. This is real, unavoidable work, not a drop-in.

**RISK 4 — 3D-path portability is a landmine for a git-synced repo.** *(cluster 2, a CHALLENGE.)* All three ingestion tools ship *different* path conventions (absolute / `${EASYEDA2KICAD}` env-var / `${KIPRJMOD}`-relative / `${KICAD_3RD_PARTY}`). **Absolute paths break the moment the repo is cloned elsewhere.** M3 must standardize *up front* on a single library-root env-var-relative convention (`${STOCKROOM}`-relative), copying easyeda2kicad's `--project-relative` `relative_to()` logic. Decide this before the first import writes a path.

**RISK 5 — coupling enrichment to an external schema silently breaks it.** *(cluster 1, cautionary tale.)* Ki-nTree issue #165: a KiCad-parser/enum-template change silently broke its InvenTree parameter-unit mapping. Your canonical-schema mapping (opportunity #11) must be *your* schema, versioned and owned, not a thin passthrough of a supplier's field names — or a supplier changing a field breaks enrichment invisibly.

**RISK 6 — the CRLF/binary-asset churn you already fight, unaddressed in the library repo.** *(cluster 4, actionable.)* You already fight `libs/My3DModels/*.STEP` CRLF churn. The git-synced *library* repo needs a hardened `.gitattributes` up front: force LF and `-text`/binary handling for `.STEP`/`.wrl`/`.kicad_*`. Without it, cross-platform clones re-churn binary/model files and pollute the clean-git guarantee.

**Non-risk to note (a validated *rejection*):** Kandle's per-project layout + manual category-per-import argument is the road you're deliberately *not* taking (global git-synced library, derived facets). Correct call — the manual category argument is the friction your JSON+SQLite index exists to remove.

---

## 4. Specific reuse candidates (depend/embed vs re-implement)

### Embed / depend directly (permissive, right stack)
| Tool | License | Use | Milestone |
|---|---|---|---|
| **kicanvas** | MIT | **Embed** as a static WebView2 asset for interactive symbol/footprint previews. Budget a `project.ts` loader fork or synth-container trick (no standalone lib-file loader). | M6 |
| **KiCost** | MIT | **Lift code** — sliding-window rate limiter (`api_mouser.py:307–351`) + priority-registry `remaining`-set fall-through (`distributor.py:141–169`). | M4 |
| **easyeda2kicad** | **AGPL-3.0** | **Depend as subprocess/CLI ONLY** — the LCSC path (`Cxxxxx` → symbol+footprint+3D). Never import in-process (network-clause reach into FastAPI). Wrap output in your JSON/content-hash layer; force `${STOCKROOM}`-relative 3D paths. | M3 |
| **kinjector** | MIT | **Lift schema + `merge_dicts`** for the Projects data model + partial-merge. Do NOT use its `pcbnew.Save` write path. | M7 |
| **KiBoM** | MIT | **Lift** component-alias table, numeric value-normalization, DNF-spelling set + regex-exclude. Not its XML-netlist ingestion. | M7 |
| **kicad-db-lib** | MIT | **Reuse the field schema** (symbol ref + footprint ref + value + refdes + description + datasheet + keywords + custom mfr/order-code fields) and the "generated libs are disposable" discipline. C#/Avalonia → no code, but MIT means even schema reuse is clean. | M3 |
| **KiABOM** | GPL-3.0 (whole) / MIT sub-modules | **Reference patterns** (MPN-normalize-then-key, epoch-in-filename TTL cache, exact-MPN preference, `--ignore-mpns`). Whole is GPL via `kicad_netlist_reader` — re-implement, don't vendor. | M4/M7 |

### Re-implement clean (GPL/AGPL/unclear license, or wrong stack)
| Tool | License | Why re-implement, not vendor |
|---|---|---|
| **Import-LIB-KiCad-Plugin** | GPL-3.0 | The M3 reference (structural fingerprint, `kicad-cli` upgrades, atomic write, string-based model-path edit). Study + reimplement; do not pull GPL source into your own-licensed exe. Also bundles AGPL easyeda2kicad — don't copy the integration wholesale. |
| **Ki-nTree** | GPL-3.0 | The M4 gold standard (category-keyed YAML supplier→canonical mapping, template-wildcard generation). Depends on kiutils + digikey-api (both GPL). Copy the *architecture*, write your own. |
| **eeintech-csv** | none (SPDX null) | Diff-then-write + honest "can't add without template" pattern. No license = legal AVOID for any copying; also V5 `.lib`-only. Pattern reference only. |
| **Boms-Away** | GPL-3.0 | Value-normalization + footprint-gated consolidation idea. Python 2.7/wxPython, dead. Design reference. |
| **kicadLibCreator** | NOASSERTION | Category-rule enrichment idea + Octopart cautionary tale. No clear license → AVOID code. |
| **uConfig** | GPL-3.0 | Datasheet-PDF pinout extraction (Poppler positioned-blocks + per-vendor "magic rules"). Qt5/C++, viral. Prefer the installed `datasheets`/`pdf` skills; keep uConfig as a pin-pairing-heuristic reference only. |
| **Kandle** | MIT (unverified — `LICENCE` fetch empty) | Filename normalization (strip `ul_`/`LIB_` prefixes) is the only borrow; C++, least aligned. Reject its per-project + manual-category UX. |
| **kicad-rw / pykicad** | GPL-family (verify) / ISC | Do NOT use for I/O (both reformat-on-write). Borrow: kicad-rw's tree/xpath **read** idiom (read path only); pykicad's `NetClass`/`Setup`/`Zone` field enumerations as an M7 schema checklist. |
| **kiri** | MIT | Bash + jQuery + GUI-automation version-matrix — ideas not code. Take `git archive <hash> | tar` history-materialization + two-SVG diff-toggle UI. |
| **plotgitsch** | ISC-family (verify) | OCaml — pattern only. Take: `gitFs` git-object blob reads, the `HEAD / <rev> / <rev1> <rev2>` + `dir:` diff triad, and semantic-vs-visual two-tier diff. |

---

## 5. New idea-tracker items (checkbox-ready, milestone-tagged)

- [ ] **[M3]** Reimplement Import-LIB's `identify_remote_type` as an ordered structural probe (marker files/dirs, not filenames; honor `KiCad/` vs `KiCAD/` casing) with an explicit **3D-only "Partial" branch**.
- [ ] **[M3]** Key ingestion identity/dedup on **MPN + content-hash** in the JSON/SQLite layer (fixes the name-only identity both reference tools are stuck with — a SnapEDA LM358 and an UltraLibrarian LM358 must merge).
- [ ] **[M3]** Use `kicad-cli sym upgrade` / `fp upgrade` for all legacy `.lib`→`.kicad_sym`; never hand-write a v4→v6 converter.
- [ ] **[M3]** Implement the byte-preserving model-path rewrite as a scoped token substitution (Import-LIB's `re.sub(r'(\(model\s+)"[^"]*"', …)` pattern), not a re-serialize.
- [ ] **[M3]** Wrap the write path in atomic `.tmp` → re-parse-verify-non-empty → rename, with `.backup` + restore-on-failure; log each per-field change (`(F.upd) old -> new`).
- [ ] **[M3]** Standardize on a single **`${STOCKROOM}`-relative** 3D/asset path convention before the first import writes a path; port easyeda2kicad's `--project-relative` `relative_to()` logic. Never write absolute paths.
- [ ] **[M3]** Ship a hardened `.gitattributes` in the library repo (force LF, `-text`/binary for `.STEP`/`.wrl`/`.kicad_*`) to stop CRLF/binary churn on cross-platform clones.
- [ ] **[M3]** Firewall AGPL: invoke easyeda2kicad **subprocess-only**, never in-process; wrap its output in the content-fingerprint/JSON layer so LCSC parts dedup against vendor-zip parts by MPN.
- [ ] **[M3/dedup]** Add value-normalization (`10K`==`10 K`==`10k`) + **footprint-gated** consolidation to the SQLite dedup layer.
- [ ] **[M4]** Build enrichment as a **priority-registry with a `remaining`-set fall-through** (LCSC-free → scraper → Mouser-API, each tier solving what it can); lift KiCost's code (MIT).
- [ ] **[M4]** Use KiCost's **sliding-window** rate limiter (burst to N, sleep `WINDOW − elapsed + 0.1`, pop oldest), not a blunt sleep-60s counter.
- [ ] **[M4]** MPN-normalize (`/`,`\`→`-`) → filesystem-safe cache key; one file per MPN with an expiry timestamp; prefix SKU-keyed vs MPN-keyed cache entries so they don't collide.
- [ ] **[M4]** On any multi-result supplier response, **prefer the exact `part.mpn == query` row**, never blindly `parts[0]` (wrong-part bug).
- [ ] **[M4]** Add an **`--ignore-mpns`** / house-parts skip list so known parts never hit the rate-limited API.
- [ ] **[M4]** Build the supplier→canonical field mapping as a **category-keyed, versioned, Stockroom-owned schema** with parent/child inheritance + per-supplier name overrides (not a passthrough of supplier field names — see Ki-nTree #165).
- [ ] **[M4]** **Reframe scraper-first → scraper-*aware*:** Mouser API is the reliable floor; scraped fields are best-effort and expected to rot; the complete-to-add gate must never hard-depend on a scraped field.
- [ ] **[M4/read]** Add an xpath-over-s-expr-tree accessor for the READ path (search/index extraction, preview metadata); never let the parsed tree become the write path.
- [ ] **[M5]** (byte layer) Guarantee the s-expr writer **losslessly passes through tokens it does not model** (comments + KiCad V10 additions) — add a round-trip test that a real V10 `.kicad_sym`/`.kicad_pcb` survives read→write byte-identical.
- [ ] **[M6]** Embed **kicanvas** (MIT) as a static WebView2 asset for interactive symbol/footprint previews; keep `kicad-cli` for 3D/STEP + headless SVG fallback.
- [ ] **[M6]** Resolve kicanvas's missing standalone lib-file loader: either synth a minimal throwaway `.kicad_sch`/`.kicad_pcb` in memory, or fork `project.ts` to accept `.kicad_sym`/`.kicad_mod` directly.
- [ ] **[M6/cross-cutting]** Read part history straight from git objects (`pygit2 tree[path].data` / `git cat-file -p <rev>:<path>`) — never checkout, never mutate — scoped to the part/project subtree, not the repo root.
- [ ] **[M6]** Build the "what changed in this part" view as **two-tier**: structured field-diff on the JSON record + old-vs-new SVG overlay (kiri's two-SVG filter/opacity toggle as the UI).
- [ ] **[M6]** Implement the git rev-spec **triad** (`HEAD` / `<rev>` / `<rev1> <rev2>`) plus a git-free `dir:` diff for ingestion staging.
- [ ] **[M7]** Model the Projects editor on KinJector's **per-concern flat JSON** (`design rules` / net-class `definitions`+`assignments` / `modules`→`position{x,y,angle,side}`) with **partial-merge** semantics (edit one concern without rewriting others); write through the byte layer, not `pcbnew.Save`.
- [ ] **[M7]** Adopt KiBoM's BOM grouping rules verbatim: **component-alias equivalence**, **numeric value-normalization** (`0.1uF`==`100n`), **DNF-spelling set + regex-exclude** for test-points/fiducials/mount-holes.
- [ ] **[M7]** Model a tabular bulk-field editor (KiField's rows×fields extract→edit→reinsert) as a **derived, regenerable** view over the JSON — table never becomes source of truth.
- [ ] **[M7/cross-cutting]** Add a **commit-time gate** that fails if a part record references an asset not committed in the same tree (plotgitsch's uncommitted-cache-lib failure is exactly what this prevents).
