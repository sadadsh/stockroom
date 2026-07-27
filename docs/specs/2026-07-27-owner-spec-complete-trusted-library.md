# Owner Spec: a complete, trusted, self-maintaining library

**Date:** 2026-07-27 · **Status:** AUTHORITATIVE, stated directly by the owner
**Supersedes** the framing in `2026-07-26_2209_register-import.md` and the source choice in
`2026-07-20-bom-ready-library-rebuild-design.md` section 1 (which named UL/SnapEDA already, and
which a session on 2026-07-27 failed to read before researching the same question from scratch).

> **READ THIS BEFORE PROPOSING ANY SOURCE, SCHEMA OR SURFACE CHANGE.** The single most expensive
> failure on 2026-07-27 was re-deriving decisions that were already written down in this directory.
> The specs here are the answer, not background reading.

---

## 1. The owner's words, verbatim

These five are the spec. Check work against THESE SENTENCES, never against a summary of them.

1. *"Import everything from that list, its proper data from mouser, digikey, lcsc if possible using
   api keys. Import everything so we can change the way the data's manipulated later (human naming
   scheme for example)."*
2. *"Every non passive has trusted files downloaded and shown in the UI; non passives just show in
   the UI and only exist for bom creation later down the line."*
3. *"All non passive components linked properly to the edas."*
4. *"Everything done within the app, not some third party manipulation u do. Everything as seamless
   as possible, least amount of work left to the user. Download anything u need within the
   environment to make this possible."*
5. *"App updates should be automatic and never face errors, app shouldnt have to fully relaunch to
   update either."*

### The one reading applied to (2)
Its second clause says "non passives" where the first clause already covers non-passives, and the
two halves contradict each other as written. Read as **PASSIVES**, because the owner established
the same rule twice on the same day:

> *"passive components dont need files, models or symbols not for kicad or for altium, theyre built
> in. we use kicad for those passives only for our app's uis. the only 'linking to the eda' is for
> building boms."*

**FLAGGED TO THE OWNER.** If that reading is wrong, everything downstream of it is wrong.

---

## 2. What each item actually requires, and what blocks it

### (1) Import everything, with real distributor data
- **BLOCKER, and it is a half-wired feature already in the repo:** the backend builds a
  `DigiKeyAdapter` when `digikey_client_id` + `digikey_client_secret` are set
  (`api/routers/enrich.py::_make_pipeline`), the fields exist in the settings DTO, and **no UI
  anywhere sets them**. Measured: 5 of 158 records carry any DigiKey data. Mouser's key IS saved.
- LCSC has no official API; the free keyless `jlcsearch` community endpoint is what the repo uses.
- "so we can change the way the data's manipulated later" means: **store everything the sources
  return, raw and complete.** Naming/derivation is a presentation concern applied later, never a
  reason to drop a field at import.

### (2) Every non-passive has TRUSTED files, shown in the UI
- **Owner's definition of trusted, chosen 2026-07-27:** Ultra Librarian, SnapMagic/SnapEDA, and
  **"Never LCSC/EasyEDA again"** - what LCSC produced is to be treated as untrusted.
- **BLOCKER:** neither UL nor SnapMagic hands out API keys easily or free (owner, 2026-07-27). UL
  has no public REST API at all; SnapMagic's is behind a request form.
- **A PASSIVE NEEDS NOTHING.** Enforced in `capture/requirements.py::capture_needs`, which returns
  `[]` for `record.passive`. Its `SR-*` symbol is a BOM-property vehicle produced by `rebuild_part`
  (see the 2026-07-20 spec), never an asset to acquire.

### (3) Non-passives linked properly to the EDAs
- KiCad: symbol/footprint/3D by reference, already works.
- Altium: `.SchLib` + `.PcbLib` + an embedded 3D body. A DbLib emitter exists; the FILES do not.
- Note the ordering the owner set: *"then we can work on routing that to their respective eda
  cads"* - files first, linking second.

### (4) Everything inside the app
- **Every manual step is a MISSING FEATURE, not a solution.** Anything Claude runs by hand that the
  owner would want to repeat is a gap to be logged and closed.
- Standing authority to install whatever tooling is needed.
- Known outstanding: the app cannot ingest the register/a BOM itself; it could not answer "is my
  library complete" until `GET /api/library/completion` shipped on 2026-07-27.

### (5) Updates automatic, error-free, no full relaunch
- `api/routers/updater.py` exists. Today a device only becomes current because `scripts/deploy.py`
  is pointed at it by hand, which means that route is not doing its job.
- "no full relaunch" implies a hot-reload path for the frontend bundle at minimum.
- Ties to the owner's DEVICE PARITY rule: same update, same files, same info, every machine.

---

## 3. TRUST IS NOT PRESENCE - the gate that must exist before more acquisition

Owner: *"a lot of our symbols, footprints, and 3d models are broken so its not trusted where we've
gotten them"*, and when asked what "broken" means, selected **all four**: 3D renders wrong,
footprint geometry wrong, symbol wrong, and wrong part entirely.

`capture_needs` only asks whether a reference EXISTS. The coverage matrix shipped on 2026-07-27
therefore measures presence and reads like a quality claim. **The next build is a per-part TRUST
verdict**, owner-selected:

    symbol pins    vs datasheet pinout
    footprint pads vs package dimensions
    3D bbox        vs footprint courtyard size
    category       vs description

- Every check must produce **PASS / FAIL / UNKNOWN**. UNKNOWN is mandatory: a check that cannot run
  must never claim either outcome.
- **Every check must be proven against a part the OWNER has confirmed is broken before it is
  trusted.** On 2026-07-27 a package-vs-pad-count check reported 16 mismatches and ALL 16 were
  false positives (it read "SOT-23" as 23 pins). A false-positive machine is worse than no check.
- Then re-source only what fails.

### Measured starting state (owner's real library, 2026-07-27, after the passive fix)
| | |
|---|---|
| records | 158 (68 passive, 90 non-passive) |
| complete (needs nothing) | 71 |
| non-passives needing KiCad symbol+footprint | 30 |
| non-passives needing a KiCad 3D model | 33 |
| non-passives needing Altium symbol+footprint | 87 |
| **3D models whose placement the viewer IGNORES** | **21 of 57 (37%)** |
| records filed from the now-untrusted LCSC lane | 36 |

Data quality of the import itself is SOUND: 0 records missing description, manufacturer or
datasheet; 25-82 specs each; 9 unclassified. The problem is ASSETS and REPORTING, not the import.
One real defect found by eye: `103AT-2` is an NTC thermistor filed under Diodes and described as a
diode - a wrong-part failure the automated checks did not catch.

---

## 4. SEPARATE THE SOURCED LAYER FROM THE PRESENTATION LAYER (owner, 2026-07-27)

Owner, granting the architecture explicitly:

> *"if we have to separate the app ui side layer of each component from the data layer so we dont
> manipulate the authenticly pulled information, thats fine"*

This is the mechanism item (1) needs. *"Import everything so we can change the way the data's
manipulated later (human naming scheme for example)"* is only possible if the authentic pull is
still there to re-derive from.

### The rule
- **SOURCED is immutable.** Exactly what each source returned, per source, per field, byte for
  byte. Never normalized, never overwritten, never merged. It is the evidence.
- **DERIVED is disposable.** `display_name`, `value`, `category`, normalized spec keys/values, the
  human naming scheme - all computed FROM sourced, and safe to recompute at any time because
  recomputing destroys nothing.
- A naming-scheme change then becomes a re-derive, not a re-import, and never a data loss.

### Measured state of the current schema (owner's real record `103at_2.json`, 2026-07-27)
Partly there already, which makes this a migration rather than a rewrite:

| field | holds | verdict |
|---|---|---|
| `specs` (76 entries) | the NORMALIZED winning value | **mutated - raw winner is LOST** |
| `enrichment` (76) | `{source, confidence}` per key | attribution kept, value not |
| `alternates` (14) | the LOSING values, raw, with source | already sourced-layer shaped |
| `display_name`, `value`, `category`, `description` | derived, stored flat | **no separation** |

So per-source attribution and the losing values already survive. What is lost is (a) the winning
value as it was actually returned, because `spec_hygiene.normalize_spec_key/value` rewrites it at
import, and (b) any boundary between derived presentation fields and sourced truth.

### What "done" looks like
1. A `sourced` block: per source, the raw payload as returned, keyed by source name. Additive, so
   nothing existing breaks; `schema_version` already exists to carry the migration.
2. `specs`/`display_name`/`category`/`value` become explicitly DERIVED, recomputed from `sourced`
   by one function, with the existing `rebuild_part` as the re-derive entry point.
3. Normalization moves from IMPORT time to DERIVE time. Nothing is normalized on the way in.
4. A re-derive over the whole library is idempotent and provably lossless: run it twice, get the
   same records; run it after a naming-scheme change, get new names and identical sourced data.

**NOT STARTED.** Recorded here at the end of the 2026-07-27 session; a schema migration should not
be begun at exhausted context.

---

## 5. SCHEMA DISCIPLINE (owner, 2026-07-27) - a rule, and the gate that must enforce it

> *"i think from now on we have to properly think out our schemas before coding fully or be able to
> have modular schemas we always remember to update"*

> *"we need to think of the best schema for everything i want, i feel like we are building on a
> shitty schema"* / *"i meant in general, look at every schema in our app too."*

**"Always remember to update" is the failure mode, not the fix.** Per the self-optimizing rule in
`~/.claude/CLAUDE.md`, an objectively checkable rule belongs in a HOOK, because a hook cannot be
skipped or forgotten. What is mechanically checkable here, and therefore gateable:

- a persisted dataclass gained/lost/renamed a field while its `SCHEMA_VERSION` did not change
- a `to_dict` / `from_dict` pair no longer covers every field of its own dataclass
- a new persisted schema was introduced carrying no version at all
- two schemas that must agree (record <-> index columns <-> DTO <-> TS type) drifted apart

**DECIDES A FACT, so it may block.** Not a judgement. Proposed as `hooks/schema-guard.py`, run at
edit time on the model/store/schema files and again in the gate script.

### Measured schema defects across the app, 2026-07-27
Found by reading, with the owner's scopes (10k parts, multi-EDA, trust, sourced-vs-derived) as the
yardstick. This is the backlog, ordered as the owner chose.

| # | schema | defect | evidence |
|---|---|---|---|
| 1 | `store/index.py` parts table | **single-tool and single-asset.** `footprint_name`, `model_file`, `datasheet_file`, `purchase_url` are all singular and implicitly KiCad; there is NO Altium column, so the index cannot express "has an Altium footprint". Exactly the flat-implicitly-KiCad anti-pattern this repo's CLAUDE.md forbids. | the DDL |
| 2 | same | `DROP TABLE IF EXISTS parts` - full rebuild, no incremental path. ~100 MB of JSON re-read per sync at 10k parts. | the DDL |
| 3 | same | `is_complete INTEGER` + `missing TEXT` bake presence-as-completeness into SQL, the defect the owner hit as "not trusted". | the DDL |
| 4 | `model/part.py` | `passive: bool` is a two-valued part class. The register already contains mechanical parts (M3 holes) and a ring LED integral to its button, both excluded BY HAND because they fit neither value. | record + register |
| 5 | `model/project.py` | `audit_digest: dict \| None` - an untyped blob as a schema field. No shape, no version. | the dataclass |
| 6 | `model/project.py` | `eda: str = "kicad"` plus `pro_path` / `board_paths` / `sheet_paths`: KiCad-shaped names carrying Altium meanings by comment, instead of per-tool file sets read from the EDA registry. | the dataclass |
| 7 | versioning | three independent `SCHEMA_VERSION`s (part=2, enrich=2, library_pin=1) with no coordinated migration, and `PartRecord.from_dict` does `max(SCHEMA_VERSION, ...)` - which **relabels a v1 record as v2 without migrating its data**. A stale record silently claims to be current. | `part.py:468` |

### Build order, owner-chosen
1. **PART RECORD** - sourced/derived split, part CLASS, assets with origin + evidence
2. **INDEX** - per-tool columns, incremental, trust-aware, no DROP TABLE
3. **PROJECTS** - per-tool file sets, typed audit digest
4. **VERSIONING** - one migration story, real upgrades not relabels

---

## 6. PART RECORD - decisions made so far (owner-approved, 2026-07-27)

**D1. Sourced data lives BESIDE the record, one file per source.**
`parts/<id>.json` stays small, readable and mergeable (derived fields + refs). Raw pulls go to
`sourced/<id>/{mouser,digikey,lcsc}.json`, byte-for-byte as returned. A re-pull rewrites one file
and never touches the record; raw payloads can move to LFS later with no schema change, because
they are re-fetchable evidence rather than authored truth. Rejected: everything inline (~300 MB at
10k parts, unreviewable diffs) and a per-machine cache (breaks device parity - a fresh clone could
not re-derive).

**D2. Trust = STORE THE EVIDENCE, DERIVE THE VERDICT.**
An asset records facts: origin (which trusted vendor, when), what checks ran, what each measured,
and against what (datasheet revision, package spec). PASS/FAIL/UNKNOWN is computed from those facts
on read. Same principle as D1: facts stored and immutable, judgements recomputed. Tightening a
check re-judges the whole library with no re-audit, and a verdict can never silently disagree with
its own evidence. Rejected: a stored verdict (goes stale, can contradict reality) and compute-
everything-live (unusable at 10k, no history of what was checked when).

**D3. Four part classes, each with different file needs, plus a per-part override.**

| class | needs | notes |
|---|---|---|
| `passive` | nothing | both EDAs ship them; exists for app UI + BOM only |
| `component` | trusted symbol + footprint + 3D, per EDA tool | the acquisition case |
| `mechanical` | footprint only, no symbol | M3 screw; may or may not be orderable |
| `virtual` | nothing, and no BOM line | test point, fiducial, logo |

Requirements become `f(part class, EDA tool)` read off the registry, which is what
`capture/requirements.py` should compute instead of the current per-tool-only loop. The per-part
override handles the exception so an odd part never forces a new class. Rejected: keeping the
binary passive flag (M3 holes and the button-integral ring LED already have no home, and are
excluded by hand today) and per-part explicit requirements (a decision per part, 10,000 times -
the manual work the owner wants removed).

**STILL TO DECIDE:** the concrete asset record shape; which fields are derived and how a re-derive
is proven lossless; the migration path for the 158 live records.

---

## 7. FILE SOURCES - the full landscape, researched 2026-07-27

Owner: *"look up how we can get these files accurately and without limiters"*, and
*"i will rebuild my whole library once everything is perfect"* (so NO migration constraint - design
for correctness, the owner re-imports).

**CONCLUSION: a free, unlimited, automated, both-format source DOES NOT EXIST.** Every source that
emits both Altium and KiCad gates automation behind a partner API or a desktop app.

| source | Altium | KiCad | automatable | limits | trusted |
|---|---|---|---|---|---|
| **SamacSys / Component Search Engine** | yes | yes | plugin + Library Loader desktop app; **no documented API** | **none stated; downloads FREE** | yes, IPC-verified |
| Ultra Librarian | yes | yes | **no public REST API found** | - | yes |
| SnapMagic / SnapEDA | yes | yes | API exists, **behind a request form** | free + premium tiers | yes |
| Mouser API | **no CAD fields at all** | no | yes, key works today | 30/min, 1000/day | yes (owner trusts most) |
| LCSC / EasyEDA | **never** (KiCad only) | yes | keyless | CloudFront blocks past ~20 calls/min | **NO - owner: "never again"** |
| KiCad official libraries | no | yes | **already installed locally** | **NONE** | yes, community-reviewed |

### Evidence behind each row
- **Mouser has no CAD.** Dumped every key the Search API returns for `595-TPS62130RGTR`:
  `DataSheetUrl, PriceBreaks, ProductAttributes, LifecycleStatus, ProductCompliance, ...` and
  nothing for symbol/footprint/3D/CAD/model. Mouser's own "Download Design Files" button is
  SamacSys, a separate service outside the Search API.
- **SamacSys is what Mouser uses**, so trusting Mouser already means trusting SamacSys indirectly.
  Free, no stated download limits, 24+ CAD systems including Altium and KiCad. Account required.
  No API documented; access is the web UI or the **Library Loader** desktop app.
- **KiCad official libs are ON DISK**: `C:\Program Files\KiCad\10.0\share\kicad\` - 223 symbol,
  155 footprint, 105 3D-model libraries. Zero network, zero limit. Coverage measured against the
  owner's failing parts: Samtec **998** footprints, Harwin **104**, QFN-16 **83**, TSSOP-28 **24**,
  SOIC-8 **23**, SOT-23-5/-6 four each, SOT-363 and SOT-563 one each. KiCad-only, so it cannot
  satisfy Altium on its own.

### The recommendation, and the one test that decides it
**SamacSys is the strongest candidate** and was under-weighted earlier: free, unlimited, both
formats, IPC-verified, and already implicitly trusted via Mouser. "No API" is a weaker blocker than
it looks - this repo ALREADY drives a desktop application headlessly (`altium/driver.py`, proven
for 3D embedding), so Library Loader is drivable by the same pattern.

**NEXT TEST (short, decisive):** does a logged-in SamacSys session expose a predictable per-part
download URL, or is Library Loader the only path? That answer picks between a clean in-app fetcher
and a driven desktop app. Everything else about acquisition waits on it.

**Do NOT propose LCSC/EasyEDA again.** Owner ruled it out explicitly; it is also KiCad-only, so it
could never satisfy the Altium half regardless.

### DECIDED 2026-07-27: SamacSys primary, Ultra Librarian fallback, SnapMagic NOT USED

Owner's own research, which settles it:

> *"Ultra Librarian: Offers the widest raw collection of manufacturer-verified models. They partner
> directly with large semiconductor companies (like Texas Instruments and Analog Devices) to build
> models straight from the source. SnapMagic (formerly SnapEDA): Hosts a massive database of
> millions of parts but heavily blends manufacturer data with community-built and AI-generated
> models. SamacSys: Possesses a smaller independent footprint but is deeply integrated into Mouser
> Electronics and RS Components. If a part is on Mouser, its SamacSys-powered model is usually
> available instantly."*

**SnapMagic is DISQUALIFIED as a primary source** despite being the only one with a usable API.
Its models blend community-built and AI-GENERATED content, which is precisely the defect the owner
reported ("a lot of our symbols, footprints, and 3d models are broken so its not trusted where
we've gotten them"). Automating against it would have bought speed at the cost of the one property
that matters. Recorded so no future session re-proposes it for its API.

**SamacSys is PRIMARY, and its "smaller database" is not a limitation HERE.** The owner buys from
Mouser and trusts Mouser most; SamacSys IS Mouser's model provider. So for this library, SamacSys
coverage and the purchasable set are the same set by construction - the register is a Mouser
register. "Smaller in absolute terms" is irrelevant when the subset it covers is exactly the subset
being bought.

**Ultra Librarian is the FALLBACK**, for anything Mouser does not carry. Highest verification of
the three (built from source with the manufacturer), widest raw coverage, but no public API - so it
is the second call, not the first.

Both chosen sources are manufacturer-verified. That is what "trusted" means for this project.

**Open, and it gates the build:** whether SamacSys downloads can be automated (a predictable
per-part URL on a logged-in session) or whether the Library Loader desktop app is the only path.
This repo already drives a desktop app headlessly (`altium/driver.py`), so either answer is
workable; the answer decides which.

---

## 8. NEXAR / OCTOPART - the angle every earlier pass missed (researched 2026-07-27)

Found only after the owner pushed for deeper research. **Nexar is a business unit of ALTIUM**, and
Octopart's CAD Model Marketplace **aggregates Ultra Librarian AND SnapEDA in one place**. Three
earlier research passes never surfaced it, because each stopped at the first usable answer.

### What is CONFIRMED
- **A documented API with first-class CAD awareness.** The supply search accepts the filters
  `cad_models:["symbol_footprint_3d"]` and `cad_models:["symbol_footprint"]`, and a `cad_agg`
  aggregation returns a `CadBucket` counting parts that have symbol + footprint + 3D.
  Source: support.nexar.com "Supply: Sorting and Filtering your Queries" (fetched, quoted).
- **It answers the exact question that defeated scraping:** does THIS part have a CAD model.
- **Free tier is capped: "the FREE Evaluation plan that allows up to 100 matched parts"**, rising
  to a custom Enterprise plan. Source: nexar.com/api, quoted verbatim.
- Octopart's own API reference (`octopart.com/api/v4/reference`) returns **403 to automated
  fetching** - noted as a fact about access, not a conclusion about the API.

### What this changes
- **The coverage question is now answerable, for free, exactly.** The owner has **90 non-passives**
  and the free tier covers **100 matched parts**. One pass measures precisely how many have a CAD
  model, with no scraping and no fabricated instrument. This is the next concrete step.
- **It does NOT solve bulk acquisition at 10,000 parts.** 100 matched parts is a hard limiter; the
  paid tiers are a cost decision for the owner, not a technical one.

### STILL OPEN - the questions this raised and did not answer
1. **Does Nexar return model DOWNLOAD URLs, or only availability?** Decides whether it is an
   acquisition path or only a coverage oracle. Unknown; the v4 reference 403s.
2. **Which formats does it expose** - Altium `.SchLib`/`.PcbLib`, KiCad, or a neutral form?
3. **What do the paid tiers cost, and what are their per-month part caps?**
4. **Terms of service on automated download** - unread for Nexar, SamacSys, UL and SnapMagic alike.
   No source has been checked on whether bulk automated retrieval is permitted. **This is a real
   gap and must be closed before building any fetcher.**
5. Does the `cad_agg` count distinguish PROVENANCE (manufacturer-verified vs AI-generated), which is
   the owner's actual trust criterion?

### Negative results, recorded so they are not retried
- **Plain HTTP + regex against componentsearchengine.com yields nothing.** It is a Next.js **App
  Router** site: no `__NEXT_DATA__`, and RSC flight-chunk extraction returned 0 bytes. Three
  attempts, three wrong layers. Use a real browser (`scripts/uishot.py` already drives Playwright).
- **A coverage probe built on that scraping could not distinguish a hit from a miss** - a fabricated
  MPN returned a byte-identical response shape to a real part. Any future coverage number must ship
  with its negative control stated.

---

## 9. THE PART RECORD SHAPE (owner-confirmed order, 2026-07-27)

### The governing principle, owner's words
> *"the new schema would allow us to manipulate the data after without losing what we imported"*
> *"all of these need to happen after the data exists in a way where we can edit it without
> reimporting you know?"*

**ACCEPTANCE TEST for this whole schema:** change the naming scheme, re-derive the entire library,
and lose nothing that was imported. If a re-derive can destroy imported data, the schema is wrong.
Concretely: a re-derive must be **idempotent** (run it twice, get identical records) and **lossless**
(the `sourced/` tree is never written by it).

### Build order, owner-set
1. **SCHEMA** — the gate; everything below waits on it
2. **DELETE the current library and re-import onto it** (data is cheap and automated; no migration)
3. **GUIDED CAPTURE** — for single part adds AND for completing existing components
4. **The owner's capture pass** (the one expensive, human, irreversible step)
5. **AUTOMATIC LINKING** to the EDA tools
6. **3D rotation fix** — last; cosmetic, independent, already measured (21 of 57 parts)

### Layout on disk
    parts/<id>.json          small, reviewable, mergeable. Identity + class + DERIVED + asset refs.
    sourced/<id>/mouser.json raw payload exactly as returned. NEVER written by a re-derive.
    sourced/<id>/digikey.json
    sourced/<id>/lcsc.json

### `parts/<id>.json`
    {
      "schema_version": 3,
      "id": "tps62130rgtr",
      "mpn": "TPS62130RGTR",            // identity: never derived, never overwritten
      "manufacturer": "Texas Instruments",
      "part_class": "component",        // passive | component | mechanical | virtual
      "requires_override": null,        // per-part escape hatch; null = use the class default

      "derived": {                      // EVERY field here is recomputable from sourced/
        "display_name": "Buck Converter 3A 17V QFN-16",
        "value": "",
        "category": "ICs",
        "description": "...",
        "specs": { "Package / Case": "16-VQFN", ... },
        "derived_at": "2026-07-27T21:04:00Z",
        "derived_by": "rules@3"         // which derivation ruleset produced this
      },

      "sources": {                      // provenance INDEX, not the payloads themselves
        "mouser":  { "fetched_at": "...", "file": "sourced/tps62130rgtr/mouser.json" },
        "digikey": { "fetched_at": "...", "file": "sourced/tps62130rgtr/digikey.json" }
      },

      "assets": {                       // per EDA tool, per kind
        "kicad": {
          "symbol": {
            "ref":    { "lib": "SR-ICs", "name": "TPS62130RGTR" },
            "origin": { "vendor": "ultralibrarian", "url": "...", "captured_at": "..." },
            "checks": [                 // EVIDENCE. The verdict is DERIVED from these on read.
              { "check": "pins_vs_datasheet", "measured": 16, "expected": 16, "against": "rev C" }
            ]
          },
          "footprint": { ... }, "model": { ... }
        },
        "altium": { "symbol": { ... }, "footprint": { ... } }
      }
    }

### The rules that make it work
1. **`sourced/` is append-only evidence.** A re-derive READS it and never writes it. A re-pull
   rewrites exactly one file and touches no record. This is what "edit without reimporting" means.
2. **`derived` is disposable by construction.** Deleting the whole block and recomputing must
   reproduce it byte-for-byte. Normalization happens at DERIVE time, never at import time — the
   current schema normalizes on the way in and the raw winning value is lost forever.
3. **Identity is not derived.** `id`, `mpn`, `manufacturer`, `part_class` are never rewritten by a
   re-derive; only a human or an explicit re-classify changes them.
4. **`origin` on every asset**, because capture is now human-driven across four vendors and
   "SnapMagic, 2026-07-27" and "Ultra Librarian, 2026-07-27" carry DIFFERENT trust weight. Without
   this, the library cannot answer "where did this file come from", which is the owner's original
   complaint verbatim: *"its not trusted where we've gotten them"*.
5. **`checks` are facts, the verdict is derived** (D2). Tightening a check re-judges the whole
   library with no re-audit, and a verdict can never disagree with its own evidence.
6. **Requirements = f(part_class, tool)** off the EDA registry (D3), with `requires_override` for
   the genuine exception. A passive resolves to `[]` for every tool.

### What the importer emits on day one
Identity + `part_class` + `sources` + the raw `sourced/` files + a first `derived` block. **No
assets** — those arrive from the capture pass (step 4) and are attached without ever rewriting
`sourced` or `derived`.

### Still to decide before implementation
- The `id` scheme (today it is a slugged MPN; a human naming scheme is an explicit owner goal).
- Which derivation ruleset version (`derived_by`) gates a re-derive, and whether records carry it.
- Whether `sourced/` is git-tracked, LFS'd, or ignored — it is re-fetchable, so all three are
  defensible; tracked is the default for device parity.
