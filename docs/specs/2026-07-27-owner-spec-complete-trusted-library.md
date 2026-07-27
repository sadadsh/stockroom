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
