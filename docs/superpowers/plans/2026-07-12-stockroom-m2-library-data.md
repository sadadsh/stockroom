# Stockroom M2: Library Data Model, Profiles, Git Sync, KiCad Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the library persistence and KiCad-registration spine: per-part JSON records, a fixed category taxonomy, per-machine config, switchable library profiles, a git-backed atomic mutation engine, git sync (pull-before-push, ff-only), and the KiCad wiring that registers Stockroom's category libraries so parts are usable in KiCad with zero manual steps.

**Architecture:** A pure data layer (`model/`) defines the part record and category taxonomy with no IO. A store layer (`store/`) owns per-machine config (active profile, keys, KiCad path — never in the repo) and profiles (self-contained `libraries/<Name>/` folders). A version-control layer (`vcs/`) wraps the `git` binary and adds a pull-before-push ff-only sync engine. The existing `kicad/` package gains config-dir resolution, byte-preserving `sym-lib-table`/`fp-lib-table` writers that append `SR-` rows without disturbing the V10 `(type "Table")` row, a `kicad_common.json` `SR_LIB` writer, an empty-category-library creator (stamped by the user's installed KiCad via `kicad-cli`), and a wiring orchestrator. A mutation layer (`mutation/`) provides a git-backed transaction that stages, validates (re-parse + semantic-diff), and atomically commits — or rolls back to zero trace — plus the concrete library operations (add / edit / move-category / delete a part, and drift detection). Everything builds on the M1 byte-preserving s-expression core.

**Tech Stack:** Python 3.12, uv (lockfile-pinned), pytest. **No new Python runtime dependencies** — M2 stays stdlib-only at runtime, using `subprocess` to the `git` and `kicad-cli` binaries (same pattern as the M1 `KiCadCli` wrapper). External tools: `git` (present in dev/CI) and `kicad-cli` 10.0.4 (integration tests auto-skip when absent).

## Global Constraints

- **KiCad target: V10.** `.kicad_sym` current stamp is `(version 20251024)`; V9 refuses V10-stamped files. `sym-lib-table`/`fp-lib-table` are format `(version 7)`. Copied verbatim from spec §8 and the real files on the owner's machine.
- **Never invent a version stamp.** New category `.kicad_sym` libraries are stamped by the user's installed KiCad via `kicad-cli sym upgrade` (verified: upgrading an empty `EESchema-LIBRARY Version 2.4` legacy lib emits `(version 20251024)`). Stockroom never writes a stamp of its own (spec §8).
- **Byte preservation for library and KiCad-table files.** All `.kicad_sym` / `.kicad_mod` / `.kicad_sch` edits and all `sym-lib-table` / `fp-lib-table` edits go through the M1 span-preserving `SexpDocument`; untouched bytes (CRLF, TAB indent, token order, existing rows, the V10 `(type "Table")` row) are never rewritten. Only KiCad's per-machine JSON config (`kicad_common.json`, outside the repo) may be re-serialized wholesale, because KiCad itself rewrites it every run; it still gets a timestamped backup and a parse-validate.
- **Scoped, safe, idempotent, aware writers** (spec §4): every writer that touches a file Stockroom does not own (KiCad tables, `kicad_common.json`, project files) takes a timestamped backup first, re-parses to validate after, never touches non-Stockroom entries, produces no change when already correct, and reports when a running KiCad means a restart is needed.
- **Atomic mutations, git as the undo system** (spec §9): every library mutation stages, validates (re-parse every written KiCad file, semantic-diff for edits), then commits as one scoped git commit with a meaningful message; a failed mutation leaves zero trace. True divergence is never clobbered; sync surfaces it.
- **Nothing machine-specific or secret enters the repo** (spec §2, §11): API keys, active profile, KiCad install path, window state live only in the per-machine config dir (`%APPDATA%/Stockroom/` on Windows, `${XDG_CONFIG_HOME:-~/.config}/stockroom/` elsewhere, `STOCKROOM_CONFIG_DIR` override).
- **No em dashes anywhere** (code, comments, docs, commit messages, strings). Owner directive.
- **Encoding:** all file reads use `encoding="utf-8"`. All KiCad s-expression file reads/writes use `newline=""` so CRLF is preserved (via the M1 `SexpDocument`). Never `str(Path)` for display; use `.as_posix()`.
- **Platform:** developed in WSL (Linux); the owner's Windows machine with real KiCad V10 is the verification gate. Linux-green is necessary, never sufficient; completion claims name the environment they rest on.
- **Package import root:** the backend package is importable as `stockroom` (pytest `pythonpath = ["app/backend"]`), living at `app/backend/stockroom/`.

## Milestone roadmap (context; only M2 is detailed here)

- **M1 (done): Foundation.** Span-preserving s-expression core (`sexp/`), semantic-diff gate (`verify/`), KiCad file models (`kicad/symbol_lib.py`, `footprint.py`, `schematic.py`), `kicad/cli.py`. Merged to `main`, CI green on ubuntu+windows.
- **M2 (this plan): Library data model, profiles, git sync, KiCad wiring.**
- **M3: Ingestion pipeline.** Content-fingerprint zip adapters, legacy upgrade, 3D re-linking, staging, feeding `mutation.add_part`. LCSC `Cxxxxx` path.
- **M4: Enrichment engine.** Mouser API v2, generic parser, in-window WebView2 fallback, datasheet fetcher.
- **M5: Backend API + app shell + launcher.** FastAPI, pywebview window, frozen-once launcher, git-pull self-update (dulwich ff-pull fallback when `git` is absent).
- **M6: Frontend UI.** React + Vite + TS + Tailwind v4; library, palette, viewers, ingest, duplicates, settings; the interactive drift-heal (`doctor`) UI.
- **M7: Project audit.** Sheet-hierarchy parse, match cascade, wizard, apply.

---

## What M1 provides (the exact surface M2 consumes)

From `stockroom.sexp.document`:
- `SexpDocument.load(path) -> SexpDocument`, `.parse(text) -> SexpDocument`, `.serialize() -> str`, `.save(path) -> None`, attribute `.root: SexpNode`.
- `SexpNode`: `.name -> str | None`, `.value -> str`, `.children -> list[SexpNode]`, `.find(name) -> SexpNode | None`, `.find_all(name) -> list[SexpNode]`, `.set_value(new, *, quote: bool) -> None`, `.insert_child_text(sexp_text: str) -> None`, `.insert_after(child, sexp_text) -> None`, `.remove_child(child) -> None`. A freshly inserted node is read-only until the doc is reloaded.
- `quote_kicad(value: str) -> str`.

From `stockroom.verify.semdiff`: `semantic_diff(original, modified, cap=200) -> list[str]` (entries start with `CHANGED`/`LOST`/`ADDED`/`TYPE-CHANGED`); `assert_only_changed(original, modified, *, allowed_changes: int) -> None` (raises `SemDiffError` on any LOST/ADDED/TYPE or too many CHANGED).

From `stockroom.kicad.symbol_lib`: `SymbolLib.load(path)`, `.version -> str`, `.symbol_names -> list[str]`, `.get_symbol(name) -> Symbol`, `.serialize()`, `.save(path)`. `Symbol.name -> str`, `.get_property(name) -> str | None`, `.set_property(name, value) -> None`.

From `stockroom.kicad.footprint`: `Footprint.load(path)`, `.name -> str`, `.model_path -> str | None`, `.set_model_path(path) -> None`, `.serialize()`, `.save(path)`.

From `stockroom.kicad.cli`: `KiCadCli(binary=None)`, `.version() -> str`, `.sym_upgrade(src: Path, dst: Path) -> None`, `.sym_export_svg(...)`, `.fp_export_svg(...)`.

From `stockroom.kicad.errors`: `KiCadError`, `KiCadFileError`, `KiCadCliError`.

From `tests/backend/conftest.py`: fixtures `fixtures_dir` (Path to `tests/backend/fixtures/kicad`), `tmp_fixture` (copy a named fixture into tmp, return its path), and `requires_kicad_cli` (skip marker).

---

## File Structure (M2)

```
app/backend/stockroom/
  model/
    __init__.py            # re-exports PartRecord, CATEGORIES, category helpers
    category.py            # CATEGORIES, slugify, category_nickname/symbol_lib/footprint_lib/is_valid
    part.py                # PartRecord + nested records, dumps/loads, new_part_id, KICAD_MIRROR_FIELDS
  store/
    __init__.py
    machine_config.py      # config_dir, MachineConfig (active_profile, mouser_api_key, kicad_config_override)
    profile.py             # Profile, ProfileLibrary, ProfileStore (list/create/switch/delete, git-committed)
  vcs/
    __init__.py
    repo.py                # GitRepo (subprocess git), GitError, Commit, PullResult, PushResult
    sync.py                # SyncEngine, SyncResult, SyncState
  kicad/                   # extends the existing package
    config.py              # kicad_config_dir, detect_running_kicad
    lib_table.py           # LibTable (byte-preserving sym/fp lib-table reader+writer)
    common_json.py         # write_env_var, read_env_var (kicad_common.json)
    category_lib.py        # create_empty_symbol_lib, ensure_footprint_lib
    wiring.py              # KiCadWiring, WiringReport
  mutation/
    __init__.py
    transaction.py         # Transaction (git-backed atomic), TransactionError
    placement.py           # merge_symbol_into_lib, place_footprint, mirror_fields_to_symbol, assert_only_added
    library_ops.py         # LibraryOps (add_part, edit_field, move_category, delete_part, detect_drift), DriftReport
tests/backend/
  fixtures/kicad/
    SR-ICs.kicad_sym                 # empty category lib (v10 stamp, CRLF) — created in T7 test, committed as fixture
    one_symbol.kicad_sym             # a single-symbol source lib to merge (CRLF)
    one_footprint.kicad_mod          # a single footprint source (CRLF)
    sym-lib-table.sample             # real global sym-lib-table (CRLF, Table row + user row)
    fp-lib-table.sample              # real global fp-lib-table (CRLF)
    kicad_common.sample.json         # real kicad_common.json (environment.vars: null)
  model/test_category.py
  model/test_part.py
  store/test_machine_config.py
  store/test_profile.py
  vcs/test_repo.py
  vcs/test_sync.py
  kicad/test_config.py
  kicad/test_lib_table.py
  kicad/test_common_json.py
  kicad/test_category_lib.py
  kicad/test_wiring.py
  mutation/test_transaction.py
  mutation/test_placement.py
  mutation/test_library_ops.py
```

Responsibilities: `model/` is pure data (no IO). `store/` owns per-machine + profile filesystem layout. `vcs/` owns git. `kicad/` owns KiCad-config-file meaning. `mutation/` composes them into atomic operations. Files that change together live together.

---

## Task 1: Category taxonomy

**Files:**
- Create: `app/backend/stockroom/model/__init__.py`
- Create: `app/backend/stockroom/model/category.py`
- Test: `tests/backend/model/__init__.py`, `tests/backend/model/test_category.py`

**Interfaces:**
- Produces: `CATEGORIES: tuple[str, ...]` (13 fixed names); `slugify(text: str) -> str`; `is_valid_category(name: str) -> bool`; `category_nickname(cat: str) -> str` (e.g. `"SR-ICs"`); `category_symbol_lib(cat: str) -> str` (`"SR-ICs.kicad_sym"`); `category_footprint_lib(cat: str) -> str` (`"SR-ICs.pretty"`). These names are used by every later task that references a category library.

- [ ] **Step 1: Create the test package marker**

`tests/backend/model/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`tests/backend/model/test_category.py`:

```python
import pytest

from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
    is_valid_category,
    slugify,
)


def test_taxonomy_is_the_fixed_thirteen():
    assert CATEGORIES == (
        "Resistors",
        "Capacitors",
        "Inductors",
        "Diodes",
        "Transistors",
        "ICs",
        "Connectors",
        "Switches",
        "Crystals & Oscillators",
        "Sensors",
        "Modules",
        "Electromechanical",
        "Other",
    )


def test_is_valid_category():
    assert is_valid_category("ICs")
    assert not is_valid_category("Widgets")


def test_nickname_and_lib_names():
    assert category_nickname("ICs") == "SR-ICs"
    assert category_symbol_lib("ICs") == "SR-ICs.kicad_sym"
    assert category_footprint_lib("ICs") == "SR-ICs.pretty"


def test_nickname_slugifies_spaces_and_punctuation():
    # "Crystals & Oscillators" must become a filesystem/nickname-safe token.
    assert category_nickname("Crystals & Oscillators") == "SR-Crystals_Oscillators"
    assert category_symbol_lib("Crystals & Oscillators") == "SR-Crystals_Oscillators.kicad_sym"


def test_lib_helpers_reject_unknown_category():
    with pytest.raises(ValueError):
        category_nickname("Widgets")


def test_slugify():
    assert slugify("TPS62130RGTR") == "tps62130rgtr"
    assert slugify("Crystals & Oscillators") == "crystals_oscillators"
    assert slugify("  Multiple   spaces ") == "multiple_spaces"
    assert slugify("weird/\\:*?chars") == "weird_chars"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/model/test_category.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.model'`.

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/model/__init__.py`:

```python
"""Pure data layer: category taxonomy and the part record. No IO."""

from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
    is_valid_category,
    slugify,
)

__all__ = [
    "CATEGORIES",
    "category_footprint_lib",
    "category_nickname",
    "category_symbol_lib",
    "is_valid_category",
    "slugify",
]
```

`app/backend/stockroom/model/category.py`:

```python
"""Fixed component-category taxonomy and the library-naming rules.

Each category maps to exactly one KiCad symbol library and one footprint
library, named SR-<slug>. The slug keeps nicknames filesystem-safe and
self-documenting inside KiCad lib_ids (spec sections 3 and 4).
"""

from __future__ import annotations

import re

CATEGORIES: tuple[str, ...] = (
    "Resistors",
    "Capacitors",
    "Inductors",
    "Diodes",
    "Transistors",
    "ICs",
    "Connectors",
    "Switches",
    "Crystals & Oscillators",
    "Sensors",
    "Modules",
    "Electromechanical",
    "Other",
)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, collapse every non-alphanumeric run to a single underscore,
    strip leading/trailing underscores. Deterministic and reversible enough for
    stable ids and library nicknames."""
    return _SLUG_RE.sub("_", text).strip("_").lower()


def is_valid_category(name: str) -> bool:
    return name in CATEGORIES


def _require(name: str) -> None:
    if not is_valid_category(name):
        raise ValueError(f"unknown category: {name!r}")


def _lib_slug(name: str) -> str:
    """Category token for a library name: slugify but keep original casing of
    the alphanumerics (so ICs stays ICs, not ics)."""
    _require(name)
    token = _SLUG_RE.sub("_", name).strip("_")
    return token


def category_nickname(name: str) -> str:
    return f"SR-{_lib_slug(name)}"


def category_symbol_lib(name: str) -> str:
    return f"{category_nickname(name)}.kicad_sym"


def category_footprint_lib(name: str) -> str:
    return f"{category_nickname(name)}.pretty"
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/model/test_category.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/model/__init__.py app/backend/stockroom/model/category.py tests/backend/model/
git commit -m "Add fixed category taxonomy and SR- library naming rules"
```

---

## Task 2: The part record

**Files:**
- Create: `app/backend/stockroom/model/part.py`
- Modify: `app/backend/stockroom/model/__init__.py` (re-export `PartRecord`, `new_part_id`, `KICAD_MIRROR_FIELDS`)
- Test: `tests/backend/model/test_part.py`

**Interfaces:**
- Consumes: `slugify` from Task 1.
- Produces:
  - Dataclasses `Datasheet(file, source_url, fetched_at)`, `Purchase(vendor, url, price_breaks, stock, currency, fetched_at)`, `LibRef(lib, name)`, `ModelRef(file)`, `Provenance(source, source_url, original_zip_sha256, ingested_at)`, `Hashes(symbol_content, footprint_content, model_file)`, `EnrichmentField(source, confidence)`.
  - `PartRecord` dataclass with fields `id, display_name, category, description, tags, mpn, manufacturer, datasheet, purchase, symbol, footprint, model, provenance, hashes, enrichment`.
  - `PartRecord.to_dict() -> dict`, `PartRecord.from_dict(d) -> PartRecord`, `PartRecord.dumps() -> str` (canonical JSON: `indent=2`, `sort_keys=True`, trailing newline — merge-friendly and diff-stable), `PartRecord.loads(text) -> PartRecord`.
  - `new_part_id(parts_dir: Path, base: str) -> str` (slug of `base`, uniqued against existing `parts/<id>.json`, never reused).
  - `KICAD_MIRROR_FIELDS: tuple[str, ...]` — the property names mirrored into symbols (used by Task 12/16).

- [ ] **Step 1: Write the failing test**

`tests/backend/model/test_part.py`:

```python
import json

from stockroom.model.part import (
    Datasheet,
    LibRef,
    PartRecord,
    Provenance,
    Purchase,
    new_part_id,
)


def _sample() -> PartRecord:
    return PartRecord(
        id="tps62130rgtr",
        display_name="TPS62130 buck regulator",
        category="ICs",
        description="3-17V 3A step-down converter",
        tags=["buck", "regulator", "dcdc"],
        mpn="TPS62130RGTR",
        manufacturer="Texas Instruments",
        datasheet=Datasheet(file="tps62130rgtr.pdf", source_url="https://ti.com/x.pdf", fetched_at="2026-07-12T00:00:00Z"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/x", price_breaks=[[1, "3.21"]], stock=42, currency="USD", fetched_at="2026-07-12T00:00:00Z")],
        symbol=LibRef(lib="SR-ICs", name="TPS62130RGTR"),
        footprint=LibRef(lib="SR-ICs", name="VQFN-16"),
        provenance=Provenance(source="samacsys", source_url="https://componentsearchengine.com/x", original_zip_sha256="abc123", ingested_at="2026-07-12T00:00:00Z"),
    )


def test_round_trip_preserves_every_field():
    p = _sample()
    again = PartRecord.from_dict(p.to_dict())
    assert again == p


def test_dumps_is_canonical_json():
    text = _sample().dumps()
    assert text.endswith("\n")
    parsed = json.loads(text)
    # sort_keys => top-level keys are alphabetical, so diffs stay stable.
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert parsed["mpn"] == "TPS62130RGTR"
    assert parsed["purchase"][0]["stock"] == 42


def test_loads_round_trip():
    p = _sample()
    assert PartRecord.loads(p.dumps()) == p


def test_defaults_are_empty_not_none():
    p = PartRecord(id="x", display_name="X", category="Other")
    d = p.to_dict()
    assert d["tags"] == []
    assert d["purchase"] == []
    assert d["datasheet"] is None
    assert d["model"] is None
    assert d["enrichment"] == {}


def test_new_part_id_slugifies(tmp_path):
    assert new_part_id(tmp_path, "TPS62130RGTR") == "tps62130rgtr"


def test_new_part_id_never_reuses(tmp_path):
    (tmp_path / "tps62130rgtr.json").write_text("{}")
    assert new_part_id(tmp_path, "TPS62130RGTR") == "tps62130rgtr-2"
    (tmp_path / "tps62130rgtr-2.json").write_text("{}")
    assert new_part_id(tmp_path, "TPS62130RGTR") == "tps62130rgtr-3"


def test_new_part_id_handles_empty_base(tmp_path):
    # a base that slugifies to empty still yields a usable id
    got = new_part_id(tmp_path, "///")
    assert got == "part"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/model/test_part.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.model.part'`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/model/part.py`:

```python
"""The Stockroom part record: one JSON file per part.

One file per part is git-merge friendly by construction: concurrent adds on two
machines land in different files and cannot conflict (spec section 3). JSON is
emitted canonically (sorted keys, 2-space indent, trailing newline) so a
one-field edit produces a minimal, stable diff.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stockroom.model.category import slugify

# KiCad-visible fields mirrored INTO symbol properties so KiCad shows a complete
# part even without Stockroom (spec section 3). Maps record-derived value ->
# KiCad property name; the actual value extraction lives in mutation/placement.
KICAD_MIRROR_FIELDS: tuple[str, ...] = (
    "MPN",
    "Manufacturer",
    "Datasheet",
    "Description",
    "ki_keywords",
    "Purchase",
)


@dataclass
class Datasheet:
    file: str = ""
    source_url: str = ""
    fetched_at: str = ""


@dataclass
class Purchase:
    vendor: str = ""
    url: str = ""
    price_breaks: list = field(default_factory=list)
    stock: int | None = None
    currency: str = ""
    fetched_at: str = ""


@dataclass
class LibRef:
    lib: str = ""
    name: str = ""


@dataclass
class ModelRef:
    file: str = ""


@dataclass
class Provenance:
    source: str = ""
    source_url: str = ""
    original_zip_sha256: str = ""
    ingested_at: str = ""


@dataclass
class Hashes:
    symbol_content: str = ""
    footprint_content: str = ""
    model_file: str = ""


@dataclass
class EnrichmentField:
    source: str = ""
    confidence: str = ""


@dataclass
class PartRecord:
    id: str
    display_name: str
    category: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    mpn: str = ""
    manufacturer: str = ""
    datasheet: Datasheet | None = None
    purchase: list[Purchase] = field(default_factory=list)
    symbol: LibRef | None = None
    footprint: LibRef | None = None
    model: ModelRef | None = None
    provenance: Provenance | None = None
    hashes: Hashes | None = None
    enrichment: dict[str, EnrichmentField] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "tags": list(self.tags),
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "datasheet": asdict(self.datasheet) if self.datasheet else None,
            "purchase": [asdict(p) for p in self.purchase],
            "symbol": asdict(self.symbol) if self.symbol else None,
            "footprint": asdict(self.footprint) if self.footprint else None,
            "model": asdict(self.model) if self.model else None,
            "provenance": asdict(self.provenance) if self.provenance else None,
            "hashes": asdict(self.hashes) if self.hashes else None,
            "enrichment": {k: asdict(v) for k, v in self.enrichment.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PartRecord":
        return cls(
            id=d["id"],
            display_name=d["display_name"],
            category=d["category"],
            description=d.get("description", ""),
            tags=list(d.get("tags", [])),
            mpn=d.get("mpn", ""),
            manufacturer=d.get("manufacturer", ""),
            datasheet=Datasheet(**d["datasheet"]) if d.get("datasheet") else None,
            purchase=[Purchase(**p) for p in d.get("purchase", [])],
            symbol=LibRef(**d["symbol"]) if d.get("symbol") else None,
            footprint=LibRef(**d["footprint"]) if d.get("footprint") else None,
            model=ModelRef(**d["model"]) if d.get("model") else None,
            provenance=Provenance(**d["provenance"]) if d.get("provenance") else None,
            hashes=Hashes(**d["hashes"]) if d.get("hashes") else None,
            enrichment={
                k: EnrichmentField(**v) for k, v in d.get("enrichment", {}).items()
            },
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def loads(cls, text: str) -> "PartRecord":
        return cls.from_dict(json.loads(text))


def new_part_id(parts_dir: Path, base: str) -> str:
    """A stable, unique, never-reused id derived from `base` (an MPN or name).

    Slug of `base`; if `parts/<slug>.json` exists, suffix -2, -3, ... A base
    that slugifies to empty falls back to 'part'."""
    parts_dir = Path(parts_dir)
    slug = slugify(base) or "part"
    candidate = slug
    n = 1
    while (parts_dir / f"{candidate}.json").exists():
        n += 1
        candidate = f"{slug}-{n}"
    return candidate
```

- [ ] **Step 4: Update the model package init**

Edit `app/backend/stockroom/model/__init__.py` to add the part re-exports. Replace its contents with:

```python
"""Pure data layer: category taxonomy and the part record. No IO."""

from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
    is_valid_category,
    slugify,
)
from stockroom.model.part import (
    KICAD_MIRROR_FIELDS,
    Datasheet,
    EnrichmentField,
    Hashes,
    LibRef,
    ModelRef,
    PartRecord,
    Provenance,
    Purchase,
    new_part_id,
)

__all__ = [
    "CATEGORIES",
    "category_footprint_lib",
    "category_nickname",
    "category_symbol_lib",
    "is_valid_category",
    "slugify",
    "KICAD_MIRROR_FIELDS",
    "Datasheet",
    "EnrichmentField",
    "Hashes",
    "LibRef",
    "ModelRef",
    "PartRecord",
    "Provenance",
    "Purchase",
    "new_part_id",
]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/model/test_part.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/model/ tests/backend/model/test_part.py
git commit -m "Add the part record with canonical JSON and non-reusing id generator"
```

---

## Task 3: Per-machine config store

**Files:**
- Create: `app/backend/stockroom/store/__init__.py`
- Create: `app/backend/stockroom/store/machine_config.py`
- Test: `tests/backend/store/__init__.py`, `tests/backend/store/test_machine_config.py`

**Interfaces:**
- Produces:
  - `config_dir() -> Path` — resolves the per-machine config directory: `STOCKROOM_CONFIG_DIR` if set, else `%APPDATA%/Stockroom` on Windows, else `${XDG_CONFIG_HOME:-~/.config}/stockroom`.
  - `MachineConfig` dataclass with `active_profile: str = "Main"`, `mouser_api_key: str = ""`, `kicad_config_override: str = ""`, `sync_enabled: bool = True`, `window: dict = {}`.
  - `MachineConfig.load(path: Path | None = None) -> MachineConfig` (path defaults to `config_dir()/config.json`; missing file returns defaults), `.save(path: Path | None = None) -> None` (creates the dir, writes canonical JSON).
- Consumes: nothing from earlier tasks (stdlib only).

- [ ] **Step 1: Create the test package marker**

`tests/backend/store/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`tests/backend/store/test_machine_config.py`:

```python
import json

import pytest

from stockroom.store.machine_config import MachineConfig, config_dir


def test_config_dir_honors_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_CONFIG_DIR", str(tmp_path / "sr"))
    assert config_dir() == tmp_path / "sr"


def test_config_dir_uses_appdata_on_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKROOM_CONFIG_DIR", raising=False)
    monkeypatch.setattr("stockroom.store.machine_config.os.name", "nt")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert config_dir() == tmp_path / "AppData" / "Roaming" / "Stockroom"


def test_config_dir_uses_xdg_on_posix(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKROOM_CONFIG_DIR", raising=False)
    monkeypatch.setattr("stockroom.store.machine_config.os.name", "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_dir() == tmp_path / "xdg" / "stockroom"


def test_missing_file_returns_defaults(tmp_path):
    cfg = MachineConfig.load(tmp_path / "nope.json")
    assert cfg.active_profile == "Main"
    assert cfg.mouser_api_key == ""
    assert cfg.sync_enabled is True


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "deep" / "config.json"
    cfg = MachineConfig(active_profile="Bench", mouser_api_key="KEY123", sync_enabled=False)
    cfg.save(path)
    assert path.exists()
    again = MachineConfig.load(path)
    assert again == cfg


def test_saved_json_is_human_readable(tmp_path):
    path = tmp_path / "config.json"
    MachineConfig(active_profile="Bench").save(path)
    data = json.loads(path.read_text())
    assert data["active_profile"] == "Bench"
    assert path.read_text().endswith("\n")


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_profile": "X", "future_field": 9}))
    cfg = MachineConfig.load(path)
    assert cfg.active_profile == "X"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/store/test_machine_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.store'`.

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/store/__init__.py`: empty file (package marker).

`app/backend/stockroom/store/machine_config.py`:

```python
"""Per-machine configuration, stored OUTSIDE the repo.

Active profile, API keys, KiCad path override, sync preference, window state.
Nothing here is machine-independent or secret-free enough to live in the repo
(spec sections 2 and 11).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    """Resolve the per-machine config directory.

    STOCKROOM_CONFIG_DIR wins (used in tests and for portable installs); then
    %APPDATA%/Stockroom on Windows; then ${XDG_CONFIG_HOME:-~/.config}/stockroom.
    """
    override = os.environ.get("STOCKROOM_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Stockroom"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "stockroom"


@dataclass
class MachineConfig:
    active_profile: str = "Main"
    mouser_api_key: str = ""
    kicad_config_override: str = ""
    sync_enabled: bool = True
    window: dict = field(default_factory=dict)

    @classmethod
    def _path(cls, path: Path | None) -> Path:
        return Path(path) if path is not None else config_dir() / "config.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "MachineConfig":
        p = cls._path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/store/test_machine_config.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/store/__init__.py app/backend/stockroom/store/machine_config.py tests/backend/store/
git commit -m "Add per-machine config store with platform-resolved config dir"
```

---

## Task 4: Git wrapper

**Files:**
- Create: `app/backend/stockroom/vcs/__init__.py`
- Create: `app/backend/stockroom/vcs/repo.py`
- Test: `tests/backend/vcs/__init__.py`, `tests/backend/vcs/test_repo.py`

**Interfaces:**
- Produces:
  - `GitError(Exception)`.
  - `Commit` dataclass (`sha, subject, author, iso_date`).
  - `PullResult` dataclass (`ok: bool, updated: bool, reason: str`), `PushResult` dataclass (`ok: bool, reason: str`).
  - `GitRepo(root: Path, git_binary: str | None = None)`:
    - `.init() -> None` (init if not already a repo; sets a local test-safe identity if none configured).
    - `.is_git_repo() -> bool`, `.head() -> str` (`""` if no commits).
    - `.status_porcelain() -> list[str]`, `.is_clean(paths: list[Path] | None = None) -> bool`.
    - `.commit(message: str, paths: list[Path]) -> str` (stages exactly `paths`, commits, returns sha; raises on empty message; returns current head unchanged if nothing to commit).
    - `.log_paths(paths: list[Path], max_count: int = 50) -> list[Commit]`.
    - `.restore_paths(paths: list[Path]) -> None` (revert tracked mods to HEAD, delete untracked created files/dirs — the rollback primitive).
    - `.add_remote(name: str, url: str) -> None`, `.set_upstream(branch: str, remote: str) -> None`.
    - `.pull_ff() -> PullResult`, `.push() -> PushResult`, `.ahead_behind() -> tuple[int, int] | None`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Create the test package marker**

`tests/backend/vcs/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`tests/backend/vcs/test_repo.py`:

```python
import shutil

import pytest

from stockroom.vcs.repo import GitError, GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path):
    r = GitRepo(tmp_path)
    r.init()
    return r


def test_init_and_empty_head(tmp_path):
    r = _repo(tmp_path)
    assert r.is_git_repo()
    assert r.head() == ""


def test_commit_returns_sha_and_advances_head(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    sha = r.commit("Add a", [tmp_path / "a.txt"])
    assert len(sha) == 40
    assert r.head() == sha
    assert r.is_clean()


def test_commit_only_stages_listed_paths(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    r.commit("Add a only", [tmp_path / "a.txt"])
    # b.txt is still untracked => not clean
    assert not r.is_clean()
    assert any("b.txt" in line for line in r.status_porcelain())


def test_commit_rejects_empty_message(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    with pytest.raises(GitError):
        r.commit("", [tmp_path / "a.txt"])


def test_log_paths(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("1")
    r.commit("first", [tmp_path / "a.txt"])
    (tmp_path / "a.txt").write_text("2")
    r.commit("second", [tmp_path / "a.txt"])
    log = r.log_paths([tmp_path / "a.txt"])
    assert [c.subject for c in log] == ["second", "first"]
    assert all(len(c.sha) == 40 for c in log)


def test_restore_reverts_tracked_modification(tmp_path):
    r = _repo(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("original")
    r.commit("add", [f])
    f.write_text("scribbled")
    r.restore_paths([f])
    assert f.read_text() == "original"
    assert r.is_clean()


def test_restore_deletes_untracked_created_file(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "keep.txt").write_text("keep")
    r.commit("base", [tmp_path / "keep.txt"])
    created = tmp_path / "new.txt"
    created.write_text("scratch")
    r.restore_paths([created])
    assert not created.exists()
    assert r.is_clean()


def test_restore_deletes_untracked_created_dir(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "keep.txt").write_text("keep")
    r.commit("base", [tmp_path / "keep.txt"])
    d = tmp_path / "sub"
    d.mkdir()
    (d / "x.txt").write_text("x")
    r.restore_paths([d])
    assert not d.exists()


def test_pull_ff_and_push_against_local_bare_remote(tmp_path):
    # origin = bare repo; clone A commits+pushes; clone B pulls ff.
    origin = tmp_path / "origin.git"
    GitRepo(origin).init(bare=True)
    a = GitRepo(tmp_path / "a")
    a.clone_from(origin)
    (a.root / "f.txt").write_text("v1")
    a.commit("v1", [a.root / "f.txt"])
    assert a.push().ok

    b = GitRepo(tmp_path / "b")
    b.clone_from(origin)
    assert (b.root / "f.txt").read_text() == "v1"

    (a.root / "f.txt").write_text("v2")
    a.commit("v2", [a.root / "f.txt"])
    a.push()
    res = b.pull_ff()
    assert res.ok and res.updated
    assert (b.root / "f.txt").read_text() == "v2"


def test_pull_ff_reports_non_fast_forward(tmp_path):
    origin = tmp_path / "origin.git"
    GitRepo(origin).init(bare=True)
    a = GitRepo(tmp_path / "a")
    a.clone_from(origin)
    (a.root / "f.txt").write_text("base")
    a.commit("base", [a.root / "f.txt"])
    a.push()

    b = GitRepo(tmp_path / "b")
    b.clone_from(origin)

    # A advances remote; B makes a divergent local commit.
    (a.root / "f.txt").write_text("remote-change")
    a.commit("remote", [a.root / "f.txt"])
    a.push()
    (b.root / "g.txt").write_text("local-change")
    b.commit("local", [b.root / "g.txt"])

    res = b.pull_ff()
    assert not res.ok
    assert "fast-forward" in res.reason.lower() or "diverg" in res.reason.lower()
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/vcs/test_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.vcs'`.

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/vcs/__init__.py`: empty file (package marker).

`app/backend/stockroom/vcs/repo.py`:

```python
"""Thin wrapper over the git binary (subprocess), mirroring the KiCadCli shape.

Only the operations Stockroom needs: init/clone, scoped commit, status,
fast-forward-only pull, push, per-path log, and a rollback primitive that git
gives us for free (git is the undo system, spec section 9). A bundled portable
git or dulwich fallback for machines without git is an M5 launcher concern; the
backend requires git on PATH (present in dev and CI).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    pass


@dataclass
class Commit:
    sha: str
    subject: str
    author: str
    iso_date: str


@dataclass
class PullResult:
    ok: bool
    updated: bool
    reason: str


@dataclass
class PushResult:
    ok: bool
    reason: str


class GitRepo:
    def __init__(self, root: Path, git_binary: str | None = None):
        resolved = shutil.which(git_binary or "git")
        if resolved is None:
            raise GitError(f"git not found: {git_binary or 'git'}")
        self.git = resolved
        self.root = Path(root)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [self.git, "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    def _set_test_identity_if_missing(self) -> None:
        # CI and fresh dev machines may have no global identity. Set a local one
        # so commits never fail; a real machine's global identity still wins.
        if self._run("config", "user.email", check=False).returncode != 0:
            self._run("config", "user.email", "stockroom@localhost")
            self._run("config", "user.name", "Stockroom")

    def init(self, *, bare: bool = False) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        args = ["init", "-b", "main"]
        if bare:
            args.append("--bare")
        subprocess.run([self.git, "-C", str(self.root), *args], capture_output=True, text=True, check=True)
        if not bare:
            self._set_test_identity_if_missing()

    def clone_from(self, origin: Path) -> None:
        self.root.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [self.git, "clone", str(origin), str(self.root)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise GitError(f"git clone failed: {proc.stderr.strip()}")
        self._set_test_identity_if_missing()

    def is_git_repo(self) -> bool:
        return self._run("rev-parse", "--is-inside-work-tree", check=False).returncode == 0

    def head(self) -> str:
        proc = self._run("rev-parse", "HEAD", check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def status_porcelain(self) -> list[str]:
        out = self._run("status", "--porcelain").stdout
        return [line for line in out.splitlines() if line.strip()]

    def is_clean(self, paths: list[Path] | None = None) -> bool:
        args = ["status", "--porcelain"]
        if paths:
            args.append("--")
            args += [str(p) for p in paths]
        return not [line for line in self._run(*args).stdout.splitlines() if line.strip()]

    def commit(self, message: str, paths: list[Path]) -> str:
        if not message.strip():
            raise GitError("commit message must not be empty")
        # -A so a scoped commit also stages DELETIONS of tracked files that were
        # removed from the working tree (profile/part deletion), not just adds/mods.
        self._run("add", "-A", "--", *[str(p) for p in paths])
        # nothing staged among these paths => no-op, return current head.
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return self.head()
        self._run("commit", "-m", message, "--only", "--", *[str(p) for p in paths])
        return self.head()

    def log_paths(self, paths: list[Path], max_count: int = 50) -> list[Commit]:
        fmt = "%H%x1f%s%x1f%an%x1f%aI"
        out = self._run(
            "log", f"--max-count={max_count}", f"--pretty=format:{fmt}",
            "--", *[str(p) for p in paths],
        ).stdout
        commits = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, subject, author, date = line.split("\x1f")
            commits.append(Commit(sha=sha, subject=subject, author=author, iso_date=date))
        return commits

    def restore_paths(self, paths: list[Path]) -> None:
        """Roll back exactly these paths: revert tracked modifications to HEAD,
        and delete anything untracked that was created. This is the transaction
        rollback (spec section 9)."""
        for p in paths:
            rel = str(p)
            tracked = self._run("ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0
            if tracked:
                self._run("checkout", "HEAD", "--", rel, check=False)
            else:
                path = Path(p)
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()

    def add_remote(self, name: str, url: str) -> None:
        self._run("remote", "add", name, url)

    def set_upstream(self, branch: str, remote: str) -> None:
        self._run("branch", f"--set-upstream-to={remote}/{branch}", branch)

    def ahead_behind(self) -> tuple[int, int] | None:
        proc = self._run("rev-list", "--left-right", "--count", "@{upstream}...HEAD", check=False)
        if proc.returncode != 0:
            return None
        behind, ahead = proc.stdout.split()
        return int(ahead), int(behind)

    def pull_ff(self) -> PullResult:
        before = self.head()
        proc = self._run("pull", "--ff-only", check=False)
        if proc.returncode != 0:
            text = (proc.stderr + proc.stdout).lower()
            reason = "not fast-forwardable (diverged)" if (
                "fast-forward" in text or "diverg" in text or "non-fast" in text
            ) else proc.stderr.strip()
            return PullResult(ok=False, updated=False, reason=reason)
        return PullResult(ok=True, updated=self.head() != before, reason="")

    def push(self) -> PushResult:
        proc = self._run("push", check=False)
        if proc.returncode != 0:
            return PushResult(ok=False, reason=proc.stderr.strip())
        return PushResult(ok=True, reason="")
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/vcs/test_repo.py -v`
Expected: PASS (all tests; skipped only if git is absent).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/vcs/__init__.py app/backend/stockroom/vcs/repo.py tests/backend/vcs/
git commit -m "Add git wrapper with scoped commit, ff-only pull, and rollback primitive"
```

---

## Task 5: Profiles and library layout

**Files:**
- Create: `app/backend/stockroom/store/profile.py`
- Modify: `app/backend/stockroom/store/__init__.py` (re-export)
- Test: `tests/backend/store/test_profile.py`

**Interfaces:**
- Consumes: `CATEGORIES`, `category_symbol_lib`, `category_footprint_lib` (Task 1); `GitRepo` (Task 4).
- Produces:
  - `ProfileLibrary(root: Path)` — paths for one profile: `.parts_dir`, `.symbols_dir`, `.footprints_dir`, `.models_dir`, `.datasheets_dir`; `.symbol_lib_path(category) -> Path`, `.footprint_lib_path(category) -> Path`; `.ensure_layout() -> list[Path]` (creates the five subdirs each with a `.gitkeep`, returns the gitkeep paths so a caller can commit them).
  - `Profile(name: str, root: Path)` with `.library -> ProfileLibrary`.
  - `ProfileStore(libraries_root: Path, repo: GitRepo)`:
    - `.list() -> list[str]` (sorted profile names present on disk).
    - `.exists(name) -> bool`.
    - `.get(name) -> Profile`.
    - `.create(name) -> Profile` (make `libraries/<name>/` layout, git-commit the `.gitkeep`s; raises if it already exists or name is unsafe).
    - `.delete(name) -> None` (remove the folder in a scoped commit; raises if it is the last profile).
- Note: switching the active profile is a `MachineConfig` write, not a `ProfileStore` op; the wiring orchestrator (Task 10) performs the KiCad-side switch.

- [ ] **Step 1: Write the failing test**

`tests/backend/store/test_profile.py`:

```python
import shutil

import pytest

from stockroom.store.profile import ProfileLibrary, ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _store(tmp_path):
    repo = GitRepo(tmp_path)
    repo.init()
    (tmp_path / "seed.txt").write_text("seed")
    repo.commit("seed", [tmp_path / "seed.txt"])
    return ProfileStore(tmp_path / "libraries", repo)


def test_library_layout_paths(tmp_path):
    lib = ProfileLibrary(tmp_path / "Main")
    assert lib.parts_dir == tmp_path / "Main" / "parts"
    assert lib.symbols_dir == tmp_path / "Main" / "symbols"
    assert lib.symbol_lib_path("ICs") == tmp_path / "Main" / "symbols" / "SR-ICs.kicad_sym"
    assert lib.footprint_lib_path("ICs") == tmp_path / "Main" / "footprints" / "SR-ICs.pretty"


def test_ensure_layout_creates_five_subdirs_with_gitkeep(tmp_path):
    lib = ProfileLibrary(tmp_path / "Main")
    keeps = lib.ensure_layout()
    for sub in ("parts", "symbols", "footprints", "models", "datasheets"):
        assert (tmp_path / "Main" / sub / ".gitkeep").exists()
    assert len(keeps) == 5


def test_create_profile_commits_and_lists(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    assert store.exists("Main")
    assert store.list() == ["Main"]
    assert store.repo.is_clean()  # create committed everything


def test_create_rejects_duplicate(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    with pytest.raises(ValueError):
        store.create("Main")


def test_create_rejects_unsafe_name(tmp_path):
    store = _store(tmp_path)
    for bad in ("../evil", "a/b", "", "."):
        with pytest.raises(ValueError):
            store.create(bad)


def test_delete_removes_folder_in_a_commit(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    store.create("Bench")
    store.delete("Bench")
    assert not store.exists("Bench")
    assert store.list() == ["Main"]
    assert store.repo.is_clean()


def test_delete_refuses_last_profile(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    with pytest.raises(ValueError):
        store.delete("Main")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/store/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.store.profile'`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/store/profile.py`:

```python
"""Library profiles: each libraries/<Name>/ is a complete, self-contained set.

Create/switch/delete in-app; the active profile is per-machine state. Delete
removes the folder in a scoped commit; git history preserves everything (spec
section 3).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from stockroom.model.category import category_footprint_lib, category_symbol_lib
from stockroom.vcs.repo import GitRepo

_SUBDIRS = ("parts", "symbols", "footprints", "models", "datasheets")


def _validate_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"unsafe profile name: {name!r}")


class ProfileLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def parts_dir(self) -> Path:
        return self.root / "parts"

    @property
    def symbols_dir(self) -> Path:
        return self.root / "symbols"

    @property
    def footprints_dir(self) -> Path:
        return self.root / "footprints"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def datasheets_dir(self) -> Path:
        return self.root / "datasheets"

    def symbol_lib_path(self, category: str) -> Path:
        return self.symbols_dir / category_symbol_lib(category)

    def footprint_lib_path(self, category: str) -> Path:
        return self.footprints_dir / category_footprint_lib(category)

    def ensure_layout(self) -> list[Path]:
        keeps: list[Path] = []
        for sub in _SUBDIRS:
            d = self.root / sub
            d.mkdir(parents=True, exist_ok=True)
            keep = d / ".gitkeep"
            if not keep.exists():
                keep.write_text("")
            keeps.append(keep)
        return keeps


class Profile:
    def __init__(self, name: str, root: Path):
        self.name = name
        self.root = Path(root)
        self.library = ProfileLibrary(self.root)


class ProfileStore:
    def __init__(self, libraries_root: Path, repo: GitRepo):
        self.libraries_root = Path(libraries_root)
        self.repo = repo

    def list(self) -> list[str]:
        if not self.libraries_root.exists():
            return []
        return sorted(p.name for p in self.libraries_root.iterdir() if p.is_dir())

    def exists(self, name: str) -> bool:
        return (self.libraries_root / name).is_dir()

    def get(self, name: str) -> Profile:
        _validate_name(name)
        if not self.exists(name):
            raise ValueError(f"profile does not exist: {name}")
        return Profile(name, self.libraries_root / name)

    def create(self, name: str) -> Profile:
        _validate_name(name)
        if self.exists(name):
            raise ValueError(f"profile already exists: {name}")
        profile = Profile(name, self.libraries_root / name)
        keeps = profile.library.ensure_layout()
        self.repo.commit(f"Create profile {name}", keeps)
        return profile

    def delete(self, name: str) -> None:
        _validate_name(name)
        if not self.exists(name):
            raise ValueError(f"profile does not exist: {name}")
        if self.list() == [name]:
            raise ValueError("refusing to delete the last profile")
        target = self.libraries_root / name
        # remove from the working tree; the scoped commit stages the deletion of the
        # now-missing tracked files (git add -A records removals) as one commit.
        shutil.rmtree(target)
        self.repo.commit(f"Delete profile {name}", [target])
```

- [ ] **Step 4: Update the store package init**

Replace `app/backend/stockroom/store/__init__.py` with:

```python
"""Per-machine config and library profiles."""

from stockroom.store.machine_config import MachineConfig, config_dir
from stockroom.store.profile import Profile, ProfileLibrary, ProfileStore

__all__ = ["MachineConfig", "config_dir", "Profile", "ProfileLibrary", "ProfileStore"]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/store/test_profile.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/store/profile.py app/backend/stockroom/store/__init__.py tests/backend/store/test_profile.py
git commit -m "Add library profiles with git-committed create and delete"
```

---

## Task 6: KiCad config-dir resolver and running-KiCad detection

**Files:**
- Create: `app/backend/stockroom/kicad/config.py`
- Test: `tests/backend/kicad/test_config.py`

**Interfaces:**
- Produces:
  - `kicad_config_dir(version: str = "10.0", override: str = "") -> Path` — `override` wins; else `%APPDATA%/kicad/<version>` on Windows, else `${XDG_CONFIG_HOME:-~/.config}/kicad/<version>`.
  - `detect_running_kicad(lister=None) -> bool` — best-effort; `lister` is an injectable callable returning the process-name listing text (default shells to `tasklist` on Windows / `ps -A` on POSIX). Never raises; returns `False` if it cannot tell.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test**

`tests/backend/kicad/test_config.py`:

```python
from stockroom.kicad.config import detect_running_kicad, kicad_config_dir


def test_override_wins(tmp_path):
    assert kicad_config_dir(override=str(tmp_path / "kc")) == tmp_path / "kc"


def test_windows_path(monkeypatch, tmp_path):
    monkeypatch.setattr("stockroom.kicad.config.os.name", "nt")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert kicad_config_dir("10.0") == tmp_path / "Roaming" / "kicad" / "10.0"


def test_posix_xdg_path(monkeypatch, tmp_path):
    monkeypatch.setattr("stockroom.kicad.config.os.name", "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert kicad_config_dir("10.0") == tmp_path / "xdg" / "kicad" / "10.0"


def test_detect_running_true_when_process_present():
    assert detect_running_kicad(lister=lambda: "1234 kicad\n5678 bash\n") is True


def test_detect_running_matches_editors():
    assert detect_running_kicad(lister=lambda: "pcbnew.exe\n") is True
    assert detect_running_kicad(lister=lambda: "eeschema\n") is True


def test_detect_running_false_when_absent():
    assert detect_running_kicad(lister=lambda: "bash\nvim\n") is False


def test_detect_running_never_raises():
    def boom():
        raise OSError("no process tool")
    assert detect_running_kicad(lister=boom) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_config.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError` for `stockroom.kicad.config`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/kicad/config.py`:

```python
"""Locate the KiCad per-user config directory and detect a running KiCad.

Verified layout: %APPDATA%\\kicad\\10.0\\ on Windows, ~/.config/kicad/10.0/ on
Linux (spec section 4). A Settings override wins over both.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_EDITOR_TOKENS = ("kicad", "pcbnew", "eeschema", "kicad-cli")


def kicad_config_dir(version: str = "10.0", override: str = "") -> Path:
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "kicad" / version
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "kicad" / version


def _default_lister() -> str:
    cmd = ["tasklist"] if os.name == "nt" else ["ps", "-A", "-o", "comm"]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return proc.stdout


def detect_running_kicad(lister=None) -> bool:
    """Best-effort: is a KiCad editor running (so lib-table changes need a
    restart)? Never raises; on any failure returns False."""
    try:
        text = (lister or _default_lister)().lower()
    except Exception:
        return False
    return any(tok in text for tok in _EDITOR_TOKENS)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_config.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/config.py tests/backend/kicad/test_config.py
git commit -m "Add KiCad config-dir resolver and running-KiCad detection"
```

---

## Task 7: Empty category library creation

**Files:**
- Create: `app/backend/stockroom/kicad/category_lib.py`
- Create fixtures: `tests/backend/fixtures/kicad/one_symbol.kicad_sym`, `tests/backend/fixtures/kicad/one_footprint.kicad_mod`
- Test: `tests/backend/kicad/test_category_lib.py`

**Interfaces:**
- Consumes: `KiCadCli` (M1), `SymbolLib` (M1), `category_symbol_lib`/`category_footprint_lib` (Task 1).
- Produces:
  - `create_empty_symbol_lib(cli: KiCadCli, dst: Path) -> None` — write a properly V10-stamped empty `.kicad_sym` at `dst` by upgrading a canonical empty legacy lib through `kicad-cli sym upgrade` (verified: emits `(version 20251024)`). Idempotent: if `dst` already exists and parses as a symbol lib, do nothing.
  - `ensure_footprint_lib(dst_pretty: Path) -> None` — an empty `.pretty` dir is a valid empty footprint library; create it if missing.
  - `EMPTY_LEGACY_LIB: str` — the canonical empty `EESchema-LIBRARY Version 2.4` source (module constant, reused as a test anchor).

- [ ] **Step 1: Create the merge-source fixtures**

`tests/backend/fixtures/kicad/one_symbol.kicad_sym` (author with CRLF line endings; a single minimal symbol Stockroom can merge into a category lib in later tasks):

```
(kicad_symbol_lib
	(version 20251024)
	(generator "kicad_symbol_editor")
	(generator_version "10.0")
	(symbol "TESTPART"
		(property "Reference" "U" (at 0 0 0))
		(property "Value" "TESTPART" (at 0 0 0))
		(property "Footprint" "" (at 0 0 0))
		(property "Datasheet" "" (at 0 0 0))
	)
)
```

`tests/backend/fixtures/kicad/one_footprint.kicad_mod` (CRLF; a minimal footprint with no model block, so later tasks exercise `set_model_path`):

```
(footprint "TEST-FP"
	(version 20240108)
	(generator "pcbnew")
	(layer "F.Cu")
	(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
)
```

Note to implementer: ensure both files are saved with CRLF (`\r\n`) endings. In Python you can create them exactly:

```python
from pathlib import Path
sym = '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kicad_symbol_editor")\n\t(generator_version "10.0")\n\t(symbol "TESTPART"\n\t\t(property "Reference" "U" (at 0 0 0))\n\t\t(property "Value" "TESTPART" (at 0 0 0))\n\t\t(property "Footprint" "" (at 0 0 0))\n\t\t(property "Datasheet" "" (at 0 0 0))\n\t)\n)\n'
Path("tests/backend/fixtures/kicad/one_symbol.kicad_sym").write_text(sym.replace("\n", "\r\n"), newline="")
fp = '(footprint "TEST-FP"\n\t(version 20240108)\n\t(generator "pcbnew")\n\t(layer "F.Cu")\n\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n)\n'
Path("tests/backend/fixtures/kicad/one_footprint.kicad_mod").write_text(fp.replace("\n", "\r\n"), newline="")
```

- [ ] **Step 2: Write the failing test**

`tests/backend/kicad/test_category_lib.py`:

```python
import pytest

from stockroom.kicad.category_lib import (
    create_empty_symbol_lib,
    ensure_footprint_lib,
)
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib
from tests.backend.conftest import requires_kicad_cli


def test_ensure_footprint_lib_creates_pretty_dir(tmp_path):
    pretty = tmp_path / "SR-ICs.pretty"
    ensure_footprint_lib(pretty)
    assert pretty.is_dir()
    # idempotent
    ensure_footprint_lib(pretty)
    assert pretty.is_dir()


@requires_kicad_cli
def test_create_empty_symbol_lib_is_v10_stamped(tmp_path):
    cli = KiCadCli()
    dst = tmp_path / "SR-ICs.kicad_sym"
    create_empty_symbol_lib(cli, dst)
    lib = SymbolLib.load(dst)
    assert lib.version == "20251024"
    assert lib.symbol_names == []


@requires_kicad_cli
def test_create_empty_symbol_lib_is_idempotent(tmp_path):
    cli = KiCadCli()
    dst = tmp_path / "SR-ICs.kicad_sym"
    create_empty_symbol_lib(cli, dst)
    first = dst.read_bytes()
    create_empty_symbol_lib(cli, dst)  # must not overwrite / re-stamp
    assert dst.read_bytes() == first
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_category_lib.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.kicad.category_lib` (kicad-cli tests may also show as errors until the module exists).

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/kicad/category_lib.py`:

```python
"""Create empty per-category KiCad libraries.

An empty symbol library must carry the installed KiCad's version stamp, and
Stockroom never invents a stamp (spec section 8). Verified route: upgrade a
canonical empty legacy library through kicad-cli, which emits the current
(version 20251024) stamp. An empty .pretty directory is already a valid empty
footprint library.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib

EMPTY_LEGACY_LIB = "EESchema-LIBRARY Version 2.4\n#\n#End Library\n"


def create_empty_symbol_lib(cli: KiCadCli, dst: Path) -> None:
    dst = Path(dst)
    if dst.exists():
        # already a valid symbol lib? leave it byte-for-byte untouched.
        try:
            SymbolLib.load(dst)
            return
        except Exception:
            pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "empty.lib"
        src.write_text(EMPTY_LEGACY_LIB, encoding="utf-8")
        cli.sym_upgrade(src, dst)


def ensure_footprint_lib(dst_pretty: Path) -> None:
    Path(dst_pretty).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_category_lib.py -v`
Expected: PASS (the footprint test always; the two symbol tests pass where kicad-cli is present, skip where absent).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/kicad/category_lib.py tests/backend/kicad/test_category_lib.py tests/backend/fixtures/kicad/one_symbol.kicad_sym tests/backend/fixtures/kicad/one_footprint.kicad_mod
git commit -m "Add empty category-library creation stamped by installed KiCad"
```

---

## Task 8: sym-lib-table / fp-lib-table writer (byte-preserving)

**Files:**
- Create: `app/backend/stockroom/kicad/lib_table.py`
- Create fixtures: `tests/backend/fixtures/kicad/sym-lib-table.sample`, `tests/backend/fixtures/kicad/fp-lib-table.sample`
- Test: `tests/backend/kicad/test_lib_table.py`

**Interfaces:**
- Consumes: `SexpDocument`, `SexpNode`, `quote_kicad` (M1); `semantic_diff` (M1).
- Produces:
  - `LibTable(doc: SexpDocument, kind: str)` where `kind in ("sym_lib_table", "fp_lib_table")`.
    - `LibTable.load(path) -> LibTable`, `LibTable.new(kind) -> LibTable` (fresh format-v7 table with only the header).
    - `.entries() -> list[str]` (row `name` values in order).
    - `.has_lib(name) -> bool`.
    - `.append_kicad_lib(name: str, uri: str, descr: str = "") -> bool` — append one `(lib (name ...) (type "KiCad") (uri ...) (options "") (descr ...))` row before the closing paren, matching the file's existing indentation; returns `False` (no-op) if `name` already present. Never touches the `(type "Table")` row or any other existing row.
    - `.serialize() -> str`, `.save(path) -> None`.
  - `TABLE_ROW_NAME` constant handling: a `(type "Table")` row is the V10 stock-library chain and must be preserved untouched (verified from the real file).

- [ ] **Step 1: Create the real-format fixtures**

`tests/backend/fixtures/kicad/sym-lib-table.sample` (author with CRLF; this is the real global table from the owner's KiCad 10 with the V10 `Table` row and a user library):

```
(sym_lib_table
	(version 7)
	(lib (name "KiCad") (type "Table") (uri "/usr/share/kicad/template/sym-lib-table") (options "") (descr "KiCad Default Libraries"))
	(lib (name "MySymbols") (type "KiCad") (uri "/home/sadad/git/Hardware/libs") (options "") (descr ""))
)
```

`tests/backend/fixtures/kicad/fp-lib-table.sample` (CRLF):

```
(fp_lib_table
	(version 7)
	(lib (name "KiCad") (type "Table") (uri "/usr/share/kicad/template/fp-lib-table") (options "") (descr "KiCad Default Libraries"))
	(lib (name "MyFootprints") (type "KiCad") (uri "/home/sadad/git/Hardware/libs/MyFootprints.pretty") (options "") (descr ""))
)
```

Implementer note: save both with CRLF. Exact Python:

```python
from pathlib import Path
sym = '(sym_lib_table\n\t(version 7)\n\t(lib (name "KiCad") (type "Table") (uri "/usr/share/kicad/template/sym-lib-table") (options "") (descr "KiCad Default Libraries"))\n\t(lib (name "MySymbols") (type "KiCad") (uri "/home/sadad/git/Hardware/libs") (options "") (descr ""))\n)\n'
Path("tests/backend/fixtures/kicad/sym-lib-table.sample").write_text(sym.replace("\n", "\r\n"), newline="")
fp = '(fp_lib_table\n\t(version 7)\n\t(lib (name "KiCad") (type "Table") (uri "/usr/share/kicad/template/fp-lib-table") (options "") (descr "KiCad Default Libraries"))\n\t(lib (name "MyFootprints") (type "KiCad") (uri "/home/sadad/git/Hardware/libs/MyFootprints.pretty") (options "") (descr ""))\n)\n'
Path("tests/backend/fixtures/kicad/fp-lib-table.sample").write_text(fp.replace("\n", "\r\n"), newline="")
```

- [ ] **Step 2: Write the failing test**

`tests/backend/kicad/test_lib_table.py`:

```python
import shutil

import pytest

from stockroom.kicad.lib_table import LibTable
from stockroom.verify.semdiff import semantic_diff


def _load(tmp_path, name):
    src = pytest.importorskip  # noqa: keep import structure simple
    dst = tmp_path / name
    shutil.copyfile(
        __import__("pathlib").Path(__file__).parent.parent / "fixtures" / "kicad" / (name + ".sample"),
        dst,
    )
    return dst


def test_reads_existing_entries(tmp_fixture, fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    t = LibTable.load(dst)
    assert t.entries() == ["KiCad", "MySymbols"]
    assert t.has_lib("MySymbols")
    assert not t.has_lib("SR-ICs")


def test_append_adds_one_row_and_preserves_everything(fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    before = dst.read_bytes().decode("utf-8")
    t = LibTable.load(dst)
    added = t.append_kicad_lib(
        "SR-ICs", "${SR_LIB}/symbols/SR-ICs.kicad_sym", "Stockroom ICs"
    )
    assert added is True
    out = t.serialize()
    # the Table row and MySymbols row are byte-identical substrings still present
    assert '(lib (name "KiCad") (type "Table")' in out
    assert '(lib (name "MySymbols") (type "KiCad") (uri "/home/sadad/git/Hardware/libs")' in out
    # exactly one new row, nothing lost
    diffs = semantic_diff(before, out)
    assert all(d.startswith("ADDED") for d in diffs), diffs
    assert t.has_lib("SR-ICs")


def test_append_preserves_crlf_and_tabs(fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    t = LibTable.load(dst)
    t.append_kicad_lib("SR-ICs", "${SR_LIB}/symbols/SR-ICs.kicad_sym", "Stockroom ICs")
    out = t.serialize()
    # the new row sits on its own CRLF+TAB line like the existing rows
    assert '\r\n\t(lib (name "SR-ICs") (type "KiCad")' in out
    assert out.endswith(")\r\n") or out.endswith(")\n")


def test_append_is_idempotent(fixtures_dir, tmp_path):
    dst = tmp_path / "sym-lib-table"
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", dst)
    t = LibTable.load(dst)
    assert t.append_kicad_lib("SR-ICs", "u", "d") is True
    assert t.append_kicad_lib("SR-ICs", "u", "d") is False  # already present
    assert t.entries().count("SR-ICs") == 1


def test_new_empty_table_has_version_7(tmp_path):
    t = LibTable.new("sym_lib_table")
    t.append_kicad_lib("SR-ICs", "${SR_LIB}/symbols/SR-ICs.kicad_sym", "Stockroom ICs")
    out = t.serialize()
    assert "(version 7)" in out
    assert '(lib (name "SR-ICs") (type "KiCad")' in out
    assert t.entries() == ["SR-ICs"]


def test_fp_table_uri_points_at_pretty(fixtures_dir, tmp_path):
    dst = tmp_path / "fp-lib-table"
    shutil.copyfile(fixtures_dir / "fp-lib-table.sample", dst)
    t = LibTable.load(dst)
    t.append_kicad_lib("SR-ICs", "${SR_LIB}/footprints/SR-ICs.pretty", "Stockroom ICs")
    out = t.serialize()
    assert '(uri "${SR_LIB}/footprints/SR-ICs.pretty")' in out
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_lib_table.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.kicad.lib_table`.

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/kicad/lib_table.py`:

```python
"""Byte-preserving reader/writer for KiCad global sym-lib-table / fp-lib-table.

These are s-expression files (format version 7). Stockroom appends its own
(type "KiCad") rows with ${SR_LIB} URIs and never disturbs existing rows, in
particular the V10 (type "Table") stock-library chain row (verified against the
owner's real KiCad 10 tables). All edits go through the M1 span-preserving
layer, so CRLF, tabs, and every untouched row survive exactly.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, quote_kicad

_KINDS = ("sym_lib_table", "fp_lib_table")


class LibTable:
    def __init__(self, doc: SexpDocument, kind: str):
        if kind not in _KINDS:
            raise ValueError(f"unknown lib-table kind: {kind}")
        if doc.root.name != kind:
            raise KiCadFileError(f"not a {kind} (root is {doc.root.name!r})")
        self._doc = doc
        self.kind = kind

    @classmethod
    def load(cls, path) -> "LibTable":
        doc = SexpDocument.load(path)
        return cls(doc, doc.root.name)

    @classmethod
    def new(cls, kind: str) -> "LibTable":
        if kind not in _KINDS:
            raise ValueError(f"unknown lib-table kind: {kind}")
        text = f"({kind}\r\n\t(version 7)\r\n)\r\n"
        return cls(SexpDocument.parse(text), kind)

    def _lib_nodes(self):
        return self._doc.root.find_all("lib")

    def _row_name(self, lib_node) -> str:
        name = lib_node.find("name")
        return name.children[1].value if name else ""

    def entries(self) -> list[str]:
        return [self._row_name(n) for n in self._lib_nodes()]

    def has_lib(self, name: str) -> bool:
        return name in self.entries()

    def append_kicad_lib(self, name: str, uri: str, descr: str = "") -> bool:
        if self.has_lib(name):
            return False
        row = (
            f"(lib (name {quote_kicad(name)}) (type \"KiCad\") "
            f"(uri {quote_kicad(uri)}) (options \"\") (descr {quote_kicad(descr)}))"
        )
        # insert_child_text anchors on the last original child (a lib row, or the
        # (version 7) node in a fresh table) and replicates its CRLF+TAB indent,
        # so the new row lands on its own correctly-indented line.
        self._doc.root.insert_child_text(row)
        return True

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        self._doc.save(path)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_lib_table.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/kicad/lib_table.py tests/backend/kicad/test_lib_table.py tests/backend/fixtures/kicad/sym-lib-table.sample tests/backend/fixtures/kicad/fp-lib-table.sample
git commit -m "Add byte-preserving sym/fp lib-table writer that spares the V10 Table row"
```

---

## Task 9: kicad_common.json SR_LIB writer

**Files:**
- Create: `app/backend/stockroom/kicad/common_json.py`
- Create fixture: `tests/backend/fixtures/kicad/kicad_common.sample.json`
- Test: `tests/backend/kicad/test_common_json.py`

**Interfaces:**
- Produces:
  - `write_env_var(path: Path, name: str, value: str) -> bool` — set `environment.vars.<name> = value` in `kicad_common.json`, preserving every other key and every other env var; creates `environment.vars` (which KiCad ships as `null`) when absent. Takes a timestamped `.bak` before writing; re-parses after writing to validate. Returns `False` (still takes no backup, makes no write) when the value is already correct (idempotent).
  - `read_env_var(path: Path, name: str) -> str | None`.
- Consumes: nothing from earlier tasks (stdlib `json`).

- [ ] **Step 1: Create the real-format fixture**

`tests/backend/fixtures/kicad/kicad_common.sample.json` — copy the real file (it has `"environment": { "vars": null }` and many other keys). Author it as this minimal-but-faithful excerpt preserving the shape that matters:

```json
{
  "api": {
    "enable_server": false
  },
  "environment": {
    "vars": null
  },
  "meta": {
    "version": 6
  },
  "system": {
    "working_dir": "/home/sadad/git/stockroom"
  }
}
```

- [ ] **Step 2: Write the failing test**

`tests/backend/kicad/test_common_json.py`:

```python
import json
import shutil

from stockroom.kicad.common_json import read_env_var, write_env_var


def _load(fixtures_dir, tmp_path):
    dst = tmp_path / "kicad_common.json"
    shutil.copyfile(fixtures_dir / "kicad_common.sample.json", dst)
    return dst


def test_sets_var_when_vars_is_null(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    changed = write_env_var(p, "SR_LIB", "/home/sadad/git/stockroom/libraries/Main")
    assert changed is True
    data = json.loads(p.read_text())
    assert data["environment"]["vars"]["SR_LIB"] == "/home/sadad/git/stockroom/libraries/Main"
    # every other key survives
    assert data["meta"]["version"] == 6
    assert data["system"]["working_dir"] == "/home/sadad/git/stockroom"


def test_read_back(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    write_env_var(p, "SR_LIB", "/x")
    assert read_env_var(p, "SR_LIB") == "/x"
    assert read_env_var(p, "MISSING") is None


def test_preserves_other_env_vars(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    data = json.loads(p.read_text())
    data["environment"]["vars"] = {"KIPRJMOD": "/somewhere"}
    p.write_text(json.dumps(data))
    write_env_var(p, "SR_LIB", "/x")
    out = json.loads(p.read_text())
    assert out["environment"]["vars"]["KIPRJMOD"] == "/somewhere"
    assert out["environment"]["vars"]["SR_LIB"] == "/x"


def test_idempotent_no_backup_when_already_correct(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    assert write_env_var(p, "SR_LIB", "/x") is True
    # a backup exists from the first real write
    backups_after_first = list(tmp_path.glob("kicad_common.json.*.bak"))
    assert len(backups_after_first) == 1
    assert write_env_var(p, "SR_LIB", "/x") is False  # no change
    # no second backup taken
    assert list(tmp_path.glob("kicad_common.json.*.bak")) == backups_after_first


def test_takes_backup_before_writing(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    original = p.read_text()
    write_env_var(p, "SR_LIB", "/x")
    backups = list(tmp_path.glob("kicad_common.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_common_json.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.kicad.common_json`.

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/kicad/common_json.py`:

```python
"""Write the SR_LIB path-substitution variable into kicad_common.json.

This is KiCad's own per-machine config (outside the repo), and KiCad rewrites it
on every run, so a whole-file JSON re-serialize is safe here (unlike the library
files, which are byte-preserved). The writer still takes a timestamped backup
before touching it and re-parses to validate after (spec section 4). Verified:
KiCad ships environment.vars as null; we materialize it to an object.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_env_var(path: Path, name: str) -> str | None:
    data = _load(Path(path))
    vars_ = (data.get("environment") or {}).get("vars") or {}
    return vars_.get(name)


def write_env_var(path: Path, name: str, value: str) -> bool:
    path = Path(path)
    data = _load(path)
    env = data.get("environment")
    if not isinstance(env, dict):
        env = {}
        data["environment"] = env
    vars_ = env.get("vars")
    if not isinstance(vars_, dict):
        vars_ = {}
        env["vars"] = vars_
    if vars_.get(name) == value:
        return False  # already correct: no backup, no write
    # timestamped backup before modifying a file Stockroom does not own
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    vars_[name] = value
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    json.loads(path.read_text(encoding="utf-8"))  # parse-validate the result
    return True
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_common_json.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/kicad/common_json.py tests/backend/kicad/test_common_json.py tests/backend/fixtures/kicad/kicad_common.sample.json
git commit -m "Add kicad_common.json SR_LIB writer with backup and validate"
```

---

## Task 10: KiCad wiring orchestrator

**Files:**
- Create: `app/backend/stockroom/kicad/wiring.py`
- Test: `tests/backend/kicad/test_wiring.py`

**Interfaces:**
- Consumes: `Profile`/`ProfileLibrary` (Task 5); `KiCadCli` (M1); `kicad_config_dir`, `detect_running_kicad` (Task 6); `create_empty_symbol_lib`, `ensure_footprint_lib` (Task 7); `LibTable` (Task 8); `write_env_var` (Task 9); `CATEGORIES`, `category_nickname`, `category_symbol_lib`, `category_footprint_lib` (Task 1).
- Produces:
  - `WiringReport` dataclass (`sr_lib_value: str`, `categories_registered: list[str]`, `symbol_rows_added: int`, `footprint_rows_added: int`, `libs_created: list[str]`, `kicad_running: bool`, `restart_needed: bool`).
  - `KiCadWiring(kicad_dir: Path, cli: KiCadCli | None = None, running_detector=detect_running_kicad)`:
    - `.apply(profile: Profile) -> WiringReport` — the full first-run/profile-switch wiring:
      1. Create any missing category symbol libs (via `create_empty_symbol_lib`; needs `cli`) and `.pretty` dirs.
      2. Set `SR_LIB` in `kicad_common.json` to the profile's `libraries/<Name>` folder (absolute).
      3. Register every category in the global `sym-lib-table` and `fp-lib-table` with `${SR_LIB}`-based URIs and `SR-` nicknames (idempotent append), creating the tables if absent.
      4. Report whether KiCad is running (so a restart is needed for table changes).
    - Idempotent: a second `apply` with the same profile adds zero rows and changes nothing.
    - `cli` may be `None` only when every category symbol lib already exists (used by the pure-Python idempotency test); otherwise creation needs `cli` and raises a clear error if missing.

- [ ] **Step 1: Write the failing test**

`tests/backend/kicad/test_wiring.py`:

```python
import shutil

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.lib_table import LibTable
from stockroom.kicad.wiring import KiCadWiring
from stockroom.model.category import CATEGORIES, category_symbol_lib
from stockroom.kicad.common_json import read_env_var
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo
from tests.backend.conftest import requires_kicad_cli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _profile(tmp_path):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    return store.create("Main")


def _kicad_dir(tmp_path, fixtures_dir):
    kdir = tmp_path / "kicad" / "10.0"
    kdir.mkdir(parents=True)
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", kdir / "sym-lib-table")
    shutil.copyfile(fixtures_dir / "fp-lib-table.sample", kdir / "fp-lib-table")
    shutil.copyfile(fixtures_dir / "kicad_common.sample.json", kdir / "kicad_common.json")
    return kdir


@requires_kicad_cli
def test_apply_registers_all_categories_and_sets_sr_lib(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=KiCadCli(), running_detector=lambda: False)
    report = wiring.apply(profile)

    assert report.symbol_rows_added == len(CATEGORIES)
    assert report.footprint_rows_added == len(CATEGORIES)
    assert report.restart_needed is False

    sym = LibTable.load(kdir / "sym-lib-table")
    # existing rows preserved, all SR- rows added
    assert "MySymbols" in sym.entries()
    assert "SR-ICs" in sym.entries()
    assert sym.entries().count("SR-Resistors") == 1

    # SR_LIB points at the profile folder
    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(profile.root)

    # category libs were created on disk
    assert profile.library.symbol_lib_path("ICs").exists()
    assert profile.library.footprint_lib_path("ICs").is_dir()


@requires_kicad_cli
def test_apply_is_idempotent(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=KiCadCli(), running_detector=lambda: False)
    wiring.apply(profile)
    sym_before = (kdir / "sym-lib-table").read_bytes()
    report2 = wiring.apply(profile)
    assert report2.symbol_rows_added == 0
    assert report2.footprint_rows_added == 0
    assert (kdir / "sym-lib-table").read_bytes() == sym_before


@requires_kicad_cli
def test_apply_flags_restart_when_kicad_running(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=KiCadCli(), running_detector=lambda: True)
    report = wiring.apply(profile)
    assert report.kicad_running is True
    assert report.restart_needed is True


def test_apply_without_cli_and_precreated_libs_is_pure_python(tmp_path, fixtures_dir):
    # exercise the wiring logic without kicad-cli by pre-creating empty category
    # libs by hand (valid empty .kicad_sym) so create_empty_symbol_lib is a no-op.
    profile = _profile(tmp_path)
    empty = '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n'
    for cat in CATEGORIES:
        (profile.library.symbols_dir / category_symbol_lib(cat)).write_text(empty, newline="")
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=None, running_detector=lambda: False)
    report = wiring.apply(profile)
    assert report.symbol_rows_added == len(CATEGORIES)
    assert report.libs_created == []  # nothing needed creating
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_wiring.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.kicad.wiring`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/kicad/wiring.py`:

```python
"""Wire Stockroom's active profile into KiCad: SR_LIB variable + lib-table rows.

Runs on first setup and on every profile switch. Idempotent, scoped, safe,
aware (spec section 4): re-running changes nothing; it never disturbs
non-Stockroom rows; it backs up KiCad's own config before touching it; and it
reports when a running KiCad means a restart is needed for the new rows to load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.common_json import write_env_var
from stockroom.kicad.config import detect_running_kicad
from stockroom.kicad.lib_table import LibTable
from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
)
from stockroom.store.profile import Profile

_SR_LIB = "SR_LIB"


@dataclass
class WiringReport:
    sr_lib_value: str = ""
    categories_registered: list[str] = field(default_factory=list)
    symbol_rows_added: int = 0
    footprint_rows_added: int = 0
    libs_created: list[str] = field(default_factory=list)
    kicad_running: bool = False
    restart_needed: bool = False


class KiCadWiring:
    def __init__(self, kicad_dir: Path, cli=None, running_detector=detect_running_kicad):
        self.kicad_dir = Path(kicad_dir)
        self.cli = cli
        self._running_detector = running_detector

    def _ensure_category_libs(self, profile: Profile, report: WiringReport) -> None:
        lib = profile.library
        lib.symbols_dir.mkdir(parents=True, exist_ok=True)
        lib.footprints_dir.mkdir(parents=True, exist_ok=True)
        for cat in CATEGORIES:
            sym_path = lib.symbol_lib_path(cat)
            if not sym_path.exists():
                if self.cli is None:
                    raise ValueError(
                        f"kicad-cli is required to create category library {sym_path.name}"
                    )
                create_empty_symbol_lib(self.cli, sym_path)
                report.libs_created.append(sym_path.name)
            ensure_footprint_lib(lib.footprint_lib_path(cat))

    def _load_or_new(self, path: Path, kind: str) -> LibTable:
        return LibTable.load(path) if path.exists() else LibTable.new(kind)

    def apply(self, profile: Profile) -> WiringReport:
        report = WiringReport()
        # 1. category libraries on disk
        self._ensure_category_libs(profile, report)

        # 2. SR_LIB points at the active profile folder (absolute)
        sr_value = str(profile.root.resolve())
        report.sr_lib_value = sr_value
        write_env_var(self.kicad_dir / "kicad_common.json", _SR_LIB, sr_value)

        # 3. register every category in both global tables (idempotent append)
        sym_path = self.kicad_dir / "sym-lib-table"
        fp_path = self.kicad_dir / "fp-lib-table"
        sym_table = self._load_or_new(sym_path, "sym_lib_table")
        fp_table = self._load_or_new(fp_path, "fp_lib_table")
        for cat in CATEGORIES:
            nickname = category_nickname(cat)
            if sym_table.append_kicad_lib(
                nickname,
                f"${{{_SR_LIB}}}/symbols/{category_symbol_lib(cat)}",
                f"Stockroom {cat}",
            ):
                report.symbol_rows_added += 1
            if fp_table.append_kicad_lib(
                nickname,
                f"${{{_SR_LIB}}}/footprints/{category_footprint_lib(cat)}",
                f"Stockroom {cat}",
            ):
                report.footprint_rows_added += 1
            report.categories_registered.append(cat)
        sym_table.save(sym_path)
        fp_table.save(fp_path)

        # 4. aware: a running KiCad must restart to load table changes
        report.kicad_running = bool(self._running_detector())
        made_changes = (
            report.symbol_rows_added or report.footprint_rows_added or report.libs_created
        )
        report.restart_needed = report.kicad_running and bool(made_changes)
        return report
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_wiring.py -v`
Expected: PASS (the pure-Python test always; the three kicad-cli tests pass where kicad-cli is present, skip where absent).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/wiring.py tests/backend/kicad/test_wiring.py
git commit -m "Add KiCad wiring orchestrator (SR_LIB var + category lib-table rows)"
```

---

## Task 11: Git-backed atomic transaction

**Files:**
- Create: `app/backend/stockroom/mutation/__init__.py`
- Create: `app/backend/stockroom/mutation/transaction.py`
- Test: `tests/backend/mutation/__init__.py`, `tests/backend/mutation/test_transaction.py`

**Interfaces:**
- Consumes: `GitRepo` (Task 4); `SexpDocument` (M1).
- Produces:
  - `TransactionError(Exception)`.
  - `Transaction(repo: GitRepo)` used as a context manager:
    - `.track(*paths: Path) -> None` — register touched paths (files created/edited/removed) for validation and rollback.
    - `.validate() -> None` — re-parse every tracked existing `.kicad_sym`/`.kicad_mod`/`.kicad_sch`/`.kicad_pcb`/lib-table via `SexpDocument.load`, and every tracked `.json` via `json.loads`; raise `TransactionError` on any parse failure. (Removed paths that no longer exist are skipped.)
    - `.commit(message: str) -> str` — `validate()`, then `repo.commit(message, tracked_paths)`; returns the commit sha; marks the transaction committed.
    - `__exit__`: if not committed (exception or no explicit commit), call `repo.restore_paths(tracked_paths)` so the working tree returns to HEAD with zero trace.

- [ ] **Step 1: Create the test package marker**

`tests/backend/mutation/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`tests/backend/mutation/test_transaction.py`:

```python
import shutil

import pytest

from stockroom.mutation.transaction import Transaction, TransactionError
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path):
    r = GitRepo(tmp_path)
    r.init()
    (tmp_path / "base").write_text("base")
    r.commit("base", [tmp_path / "base"])
    return r


def test_commit_persists_and_advances_head(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with Transaction(repo) as txn:
        f = tmp_path / "a.json"
        f.write_text('{"ok": true}')
        txn.track(f)
        sha = txn.commit("Add a")
    assert sha != before
    assert repo.head() == sha
    assert repo.is_clean()
    assert (tmp_path / "a.json").exists()


def test_uncommitted_block_rolls_back_created_file(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with Transaction(repo) as txn:
        f = tmp_path / "a.json"
        f.write_text('{"ok": true}')
        txn.track(f)
        # no commit
    assert not (tmp_path / "a.json").exists()  # zero trace
    assert repo.head() == before
    assert repo.is_clean()


def test_exception_rolls_back(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with pytest.raises(RuntimeError):
        with Transaction(repo) as txn:
            f = tmp_path / "a.json"
            f.write_text("x")
            txn.track(f)
            raise RuntimeError("boom")
    assert not (tmp_path / "a.json").exists()
    assert repo.head() == before
    assert repo.is_clean()


def test_validate_rejects_broken_kicad_file_and_rolls_back(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with pytest.raises(TransactionError):
        with Transaction(repo) as txn:
            f = tmp_path / "bad.kicad_sym"
            f.write_text("(kicad_symbol_lib (version 20251024)")  # missing close paren
            txn.track(f)
            txn.commit("should fail validation")
    assert not (tmp_path / "bad.kicad_sym").exists()
    assert repo.head() == before


def test_validate_rejects_broken_json(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(TransactionError):
        with Transaction(repo) as txn:
            f = tmp_path / "bad.json"
            f.write_text("{not json")
            txn.track(f)
            txn.commit("should fail")
    assert not (tmp_path / "bad.json").exists()


def test_rollback_restores_edited_tracked_file(tmp_path):
    repo = _repo(tmp_path)
    tracked = tmp_path / "keep.kicad_sym"
    tracked.write_text("(kicad_symbol_lib (version 20251024))")
    repo.commit("add keep", [tracked])
    with Transaction(repo) as txn:
        tracked.write_text("(kicad_symbol_lib (version 20251024) (symbol \"X\"))")
        txn.track(tracked)
        # no commit -> rollback restores original content
    assert tracked.read_text() == "(kicad_symbol_lib (version 20251024))"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/mutation/test_transaction.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.mutation`.

- [ ] **Step 4: Write the implementation**

`app/backend/stockroom/mutation/__init__.py`: empty file (package marker).

`app/backend/stockroom/mutation/transaction.py`:

```python
"""Git-backed atomic mutation transaction.

Every library mutation stages its file operations, validates them (re-parse each
written KiCad file and JSON record), then commits as one scoped git commit. If
anything fails, git restores the touched paths and the mutation leaves zero
trace (spec sections 5 and 9). Git is the commit boundary and the undo system.
"""

from __future__ import annotations

import json
from pathlib import Path

from stockroom.sexp.document import SexpDocument
from stockroom.vcs.repo import GitRepo

_SEXP_SUFFIXES = {".kicad_sym", ".kicad_mod", ".kicad_sch", ".kicad_pcb"}
_SEXP_TABLE_NAMES = {"sym-lib-table", "fp-lib-table"}


class TransactionError(Exception):
    pass


class Transaction:
    def __init__(self, repo: GitRepo):
        self.repo = repo
        self._paths: list[Path] = []
        self._committed = False

    def track(self, *paths: Path) -> None:
        for p in paths:
            path = Path(p)
            if path not in self._paths:
                self._paths.append(path)

    def validate(self) -> None:
        for p in self._paths:
            if not p.exists():
                continue  # a removal is a legitimate tracked change
            if p.suffix in _SEXP_SUFFIXES or p.name in _SEXP_TABLE_NAMES:
                try:
                    SexpDocument.load(p)
                except Exception as exc:
                    raise TransactionError(f"invalid KiCad file {p.name}: {exc}") from exc
            elif p.suffix == ".json":
                try:
                    json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise TransactionError(f"invalid JSON {p.name}: {exc}") from exc

    def commit(self, message: str) -> str:
        self.validate()
        sha = self.repo.commit(message, self._paths)
        self._committed = True
        return sha

    def __enter__(self) -> "Transaction":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._committed:
            self.repo.restore_paths(self._paths)
        return False  # never suppress exceptions
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/mutation/test_transaction.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/mutation/__init__.py app/backend/stockroom/mutation/transaction.py tests/backend/mutation/
git commit -m "Add git-backed atomic transaction with validate and zero-trace rollback"
```

---

## Task 12: Library placement primitives

**Files:**
- Create: `app/backend/stockroom/mutation/placement.py`
- Test: `tests/backend/mutation/test_placement.py`

**Interfaces:**
- Consumes: `SexpDocument` (M1); `SymbolLib`, `Symbol` (M1); `Footprint` (M1); `semantic_diff` (M1); `PartRecord`, `KICAD_MIRROR_FIELDS` (Task 2).
- Produces:
  - `assert_only_added(before: str, after: str) -> None` — raise `PlacementError` unless every semantic diff entry is an `ADDED` (no `LOST`/`CHANGED`/`TYPE`). Used to gate additive merges.
  - `PlacementError(Exception)`.
  - `merge_symbol_into_lib(lib_path: Path, symbol_source: Path, source_name: str, new_name: str) -> None` — copy the `(symbol "...")` node named `source_name` out of `symbol_source` (a `.kicad_sym`), rename it to `new_name`, and append it into the category lib at `lib_path` (byte-preserving), gated by `assert_only_added`. Raises if `new_name` already exists in the target.
  - `place_footprint(pretty_dir: Path, footprint_source: Path, new_name: str) -> Path` — copy a `.kicad_mod` into the category `.pretty` as `<new_name>.kicad_mod`, rewriting the internal footprint name token to `new_name`; returns the written path.
  - `mirror_fields_to_symbol(symbol: Symbol, record: PartRecord) -> None` — write the KiCad-visible subset (MPN, Manufacturer, Datasheet path via `${SR_LIB}`, Description, keywords, purchase URL) into the symbol's properties, using `Symbol.set_property` (never overwrites unrelated properties).

- [ ] **Step 1: Write the failing test**

`tests/backend/mutation/test_placement.py`:

```python
import shutil

import pytest

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import Datasheet, LibRef, PartRecord
from stockroom.mutation.placement import (
    PlacementError,
    assert_only_added,
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)


def test_assert_only_added_passes_for_pure_addition():
    before = '(kicad_symbol_lib (version 20251024))'
    after = '(kicad_symbol_lib (version 20251024) (symbol "X"))'
    assert_only_added(before, after)  # no raise


def test_assert_only_added_rejects_a_change():
    before = '(kicad_symbol_lib (version 20251024))'
    after = '(kicad_symbol_lib (version 20240101))'
    with pytest.raises(PlacementError):
        assert_only_added(before, after)


def _empty_lib(tmp_path):
    p = tmp_path / "SR-ICs.kicad_sym"
    p.write_text('(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline="")
    return p


def test_merge_symbol_appends_renamed_symbol(tmp_path, fixtures_dir):
    lib_path = _empty_lib(tmp_path)
    src = tmp_path / "one_symbol.kicad_sym"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    merge_symbol_into_lib(lib_path, src, source_name="TESTPART", new_name="TPS62130RGTR")
    lib = SymbolLib.load(lib_path)
    assert lib.symbol_names == ["TPS62130RGTR"]
    assert lib.version == "20251024"  # untouched


def test_merge_symbol_rejects_duplicate_name(tmp_path, fixtures_dir):
    lib_path = _empty_lib(tmp_path)
    src = tmp_path / "one_symbol.kicad_sym"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    merge_symbol_into_lib(lib_path, src, "TESTPART", "PART1")
    with pytest.raises(PlacementError):
        merge_symbol_into_lib(lib_path, src, "TESTPART", "PART1")


def test_place_footprint_copies_and_renames(tmp_path, fixtures_dir):
    pretty = tmp_path / "SR-ICs.pretty"
    pretty.mkdir()
    src = tmp_path / "one_footprint.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", src)
    out = place_footprint(pretty, src, "VQFN-16")
    assert out == pretty / "VQFN-16.kicad_mod"
    assert Footprint.load(out).name == "VQFN-16"


def test_mirror_fields_writes_kicad_properties(tmp_path, fixtures_dir):
    lib_path = _empty_lib(tmp_path)
    src = tmp_path / "one_symbol.kicad_sym"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    merge_symbol_into_lib(lib_path, src, "TESTPART", "TPS62130RGTR")
    lib = SymbolLib.load(lib_path)
    sym = lib.get_symbol("TPS62130RGTR")
    record = PartRecord(
        id="tps62130rgtr", display_name="TPS62130", category="ICs",
        description="buck", tags=["dcdc", "buck"], mpn="TPS62130RGTR",
        manufacturer="TI", datasheet=Datasheet(file="tps.pdf"),
    )
    mirror_fields_to_symbol(sym, record)
    lib.save(lib_path)
    reloaded = SymbolLib.load(lib_path).get_symbol("TPS62130RGTR")
    assert reloaded.get_property("MPN") == "TPS62130RGTR"
    assert reloaded.get_property("Manufacturer") == "TI"
    assert reloaded.get_property("Description") == "buck"
    assert reloaded.get_property("ki_keywords") == "dcdc buck"
    assert reloaded.get_property("Datasheet") == "${SR_LIB}/datasheets/tps.pdf"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/mutation/test_placement.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.mutation.placement`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/mutation/placement.py`:

```python
"""Primitives that place a part's files into the per-category libraries.

Merging a symbol into an existing .kicad_sym and copying a footprint into a
.pretty are the building blocks of add_part (Task 13). Both preserve the target
file's bytes via the M1 span layer; the symbol merge is gated so it can only
ADD nodes, never lose or mutate existing ones (spec sections 5 and 8).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import Symbol, SymbolLib
from stockroom.model.part import PartRecord
from stockroom.sexp.document import SexpDocument, quote_kicad
from stockroom.verify.semdiff import semantic_diff


class PlacementError(Exception):
    pass


def assert_only_added(before: str, after: str) -> None:
    diffs = semantic_diff(before, after)
    bad = [d for d in diffs if not d.startswith("ADDED")]
    if bad:
        raise PlacementError("expected only additions, got: " + "; ".join(bad[:5]))


def _symbol_node_text(source: Path, source_name: str) -> str:
    """Return the exact source bytes of the (symbol "<source_name>" ...) node."""
    doc = SexpDocument.load(source)
    for node in doc.root.find_all("symbol"):
        kids = node.children
        if len(kids) >= 2 and kids[1].value == source_name:
            start, end = node.span
            return doc.text[start:end]
    raise PlacementError(f"symbol {source_name!r} not found in {source.name}")


def merge_symbol_into_lib(
    lib_path: Path, symbol_source: Path, source_name: str, new_name: str
) -> None:
    lib = SymbolLib.load(lib_path)
    if new_name in lib.symbol_names:
        raise PlacementError(f"symbol {new_name!r} already in {Path(lib_path).name}")
    node_text = _symbol_node_text(Path(symbol_source), source_name)
    # rename only the symbol's own name token: (symbol "<source_name>" -> new_name.
    # The name is the first string token right after 'symbol'; replace just that.
    renamed = re.sub(
        r'^\(symbol\s+' + re.escape(quote_kicad(source_name)),
        f"(symbol {quote_kicad(new_name)}",
        node_text,
        count=1,
    )
    if renamed == node_text and source_name != new_name:
        raise PlacementError(f"could not rename symbol {source_name!r}")
    before = lib.serialize()
    lib._doc.root.insert_child_text(renamed)  # append the symbol node
    after = lib.serialize()
    assert_only_added(before, after)
    Path(lib_path).write_text(after, encoding="utf-8", newline="")


def place_footprint(pretty_dir: Path, footprint_source: Path, new_name: str) -> Path:
    pretty_dir = Path(pretty_dir)
    pretty_dir.mkdir(parents=True, exist_ok=True)
    dst = pretty_dir / f"{new_name}.kicad_mod"
    shutil.copyfile(footprint_source, dst)
    # rewrite the internal footprint name token to new_name (first string after
    # 'footprint'), byte-preserving everything else.
    fp = Footprint.load(dst)
    fp._doc.root.children[1].set_value(new_name, quote=True)
    dst.write_text(fp.serialize(), encoding="utf-8", newline="")
    return dst


def _datasheet_value(record: PartRecord) -> str:
    if record.datasheet and record.datasheet.file:
        return f"${{SR_LIB}}/datasheets/{record.datasheet.file}"
    if record.datasheet and record.datasheet.source_url:
        return record.datasheet.source_url
    return ""


def mirror_fields_to_symbol(symbol: Symbol, record: PartRecord) -> None:
    """Mirror the KiCad-visible subset into the symbol's properties so KiCad
    shows a complete part even without Stockroom (spec section 3)."""
    values = {
        "MPN": record.mpn,
        "Manufacturer": record.manufacturer,
        "Description": record.description,
        "ki_keywords": " ".join(record.tags),
        "Datasheet": _datasheet_value(record),
    }
    if record.purchase and record.purchase[0].url:
        values["Purchase"] = record.purchase[0].url
    for name, value in values.items():
        if value:
            symbol.set_property(name, value)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/mutation/test_placement.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/mutation/placement.py tests/backend/mutation/test_placement.py
git commit -m "Add library placement primitives (symbol merge, footprint copy, field mirror)"
```

---

## Task 13: add_part (atomic)

**Files:**
- Create: `app/backend/stockroom/mutation/library_ops.py`
- Test: `tests/backend/mutation/test_library_ops.py` (add_part cases)

**Interfaces:**
- Consumes: `Transaction` (Task 11); placement primitives (Task 12); `Profile`/`ProfileLibrary` (Task 5); `GitRepo` (Task 4); `PartRecord`, `LibRef`, `ModelRef`, `new_part_id` (Task 2); `SymbolLib` (M1); `Footprint` (M1); category helpers (Task 1).
- Produces:
  - `StagedPart` dataclass — the ingestion-produced inputs `add_part` consumes: `display_name, category, mpn, manufacturer, description, tags, symbol_source: Path, symbol_source_name: str, footprint_source: Path, entry_name: str, model_source: Path | None, datasheet_source: Path | None, provenance, datasheet_meta`.
  - `LibraryOps(profile: Profile, repo: GitRepo)`:
    - `.add_part(staged: StagedPart) -> PartRecord` — one atomic transaction: allocate id; merge the symbol into `SR-<Category>.kicad_sym` (renamed to `entry_name`); place the footprint into `SR-<Category>.pretty`; set the symbol's `Footprint` property to `SR-<Category>:<entry_name>`; write the `(model ...)` link on the placed footprint as `${SR_LIB}/models/<file>` when a model is present; copy model + datasheet into the profile; build and write the `PartRecord` JSON; mirror KiCad-visible fields into the symbol; commit. On any failure, zero trace.
- Note: ingestion (M3) constructs `StagedPart` from a zip; M2 tests construct it from fixtures.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/mutation/test_library_ops.py`:

```python
import shutil

import pytest

from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.kicad.footprint import Footprint
from stockroom.model.part import PartRecord
from stockroom.mutation.library_ops import LibraryOps, StagedPart
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _setup(tmp_path, fixtures_dir):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    # pre-create the ICs category symbol lib by hand (empty, valid, v10 stamp)
    profile.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    (profile.library.symbol_lib_path("ICs")).write_text(
        '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline=""
    )
    profile.library.footprint_lib_path("ICs").mkdir(parents=True, exist_ok=True)
    sym_src = tmp_path / "one_symbol.kicad_sym"
    fp_src = tmp_path / "one_footprint.kicad_mod"
    model_src = tmp_path / "part.step"
    ds_src = tmp_path / "part.pdf"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym_src)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp_src)
    model_src.write_bytes(b"ISO-10303-21;\n")  # a stand-in STEP payload
    ds_src.write_bytes(b"%PDF-1.4\n")
    staged = StagedPart(
        display_name="TPS62130 buck",
        category="ICs",
        mpn="TPS62130RGTR",
        manufacturer="TI",
        description="3A buck",
        tags=["dcdc", "buck"],
        symbol_source=sym_src,
        symbol_source_name="TESTPART",
        footprint_source=fp_src,
        entry_name="TPS62130RGTR",
        model_source=model_src,
        datasheet_source=ds_src,
    )
    return repo, profile, staged


def test_add_part_places_everything_and_commits(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    before_head = repo.head()
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged)

    assert record.id == "tps62130rgtr"
    assert record.symbol == PartRecord.from_dict(record.to_dict()).symbol  # round-trips

    lib = profile.library
    # JSON written
    json_path = lib.parts_dir / "tps62130rgtr.json"
    assert json_path.exists()

    # symbol merged and named
    sym_lib = SymbolLib.load(lib.symbol_lib_path("ICs"))
    assert "TPS62130RGTR" in sym_lib.symbol_names
    sym = sym_lib.get_symbol("TPS62130RGTR")
    assert sym.get_property("Footprint") == "SR-ICs:TPS62130RGTR"
    assert sym.get_property("MPN") == "TPS62130RGTR"

    # footprint placed with a model link
    fp_path = lib.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod"
    assert fp_path.exists()
    fp = Footprint.load(fp_path)
    assert fp.model_path == "${SR_LIB}/models/TPS62130RGTR.step"

    # model + datasheet copied
    assert (lib.models_dir / "TPS62130RGTR.step").exists()
    assert (lib.datasheets_dir / "tps62130rgtr.pdf").exists()

    # exactly one new commit, clean tree
    assert repo.head() != before_head
    assert repo.is_clean()
    assert repo.log_paths([json_path])[0].subject.startswith("Add TPS62130RGTR")


def test_add_part_without_model_or_datasheet(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.model_source = None
    staged.datasheet_source = None
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged)
    assert record.model is None
    fp = Footprint.load(profile.library.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod")
    assert fp.model_path is None  # no (model ...) block written


def test_add_part_rolls_back_on_duplicate_symbol(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    head_after_first = repo.head()
    # a second add with the SAME entry_name must fail the symbol merge and leave zero trace
    staged2 = StagedPart(**{**staged.__dict__})
    with pytest.raises(Exception):
        ops.add_part(staged2)
    assert repo.head() == head_after_first
    assert repo.is_clean()
    # only one part json exists
    assert len(list(profile.library.parts_dir.glob("*.json"))) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/mutation/test_library_ops.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.mutation.library_ops`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/mutation/library_ops.py`:

```python
"""High-level, atomic library operations: add / edit / move-category / delete a
part, and drift detection. Each mutation runs inside one git-backed Transaction
so it either commits as a single scoped commit or leaves zero trace (spec
sections 3, 5, 9).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.category import category_nickname, slugify
from stockroom.model.part import (
    Datasheet,
    LibRef,
    ModelRef,
    PartRecord,
    Provenance,
    new_part_id,
)
from stockroom.mutation.placement import (
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)
from stockroom.mutation.transaction import Transaction
from stockroom.store.profile import Profile
from stockroom.vcs.repo import GitRepo


@dataclass
class StagedPart:
    display_name: str
    category: str
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    symbol_source: Path | None = None
    symbol_source_name: str = ""
    footprint_source: Path | None = None
    entry_name: str = ""
    model_source: Path | None = None
    datasheet_source: Path | None = None
    provenance: Provenance | None = None
    datasheet_meta: Datasheet | None = None


class LibraryOps:
    def __init__(self, profile: Profile, repo: GitRepo):
        self.profile = profile
        self.repo = repo
        self.lib = profile.library

    def add_part(self, staged: StagedPart) -> PartRecord:
        self.lib.parts_dir.mkdir(parents=True, exist_ok=True)
        self.lib.models_dir.mkdir(parents=True, exist_ok=True)
        self.lib.datasheets_dir.mkdir(parents=True, exist_ok=True)

        part_id = new_part_id(self.lib.parts_dir, staged.mpn or staged.display_name)
        nickname = category_nickname(staged.category)
        sym_lib_path = self.lib.symbol_lib_path(staged.category)
        pretty_dir = self.lib.footprint_lib_path(staged.category)

        with Transaction(self.repo) as txn:
            # 1. merge the symbol (renamed to entry_name) into the category lib
            merge_symbol_into_lib(
                sym_lib_path, staged.symbol_source, staged.symbol_source_name, staged.entry_name
            )
            txn.track(sym_lib_path)

            # 2. place the footprint into the category .pretty
            fp_path = place_footprint(pretty_dir, staged.footprint_source, staged.entry_name)
            txn.track(fp_path)

            # 3. model file + (model ...) link
            model_ref = None
            if staged.model_source is not None:
                model_name = f"{staged.entry_name}{Path(staged.model_source).suffix}"
                model_dst = self.lib.models_dir / model_name
                shutil.copyfile(staged.model_source, model_dst)
                txn.track(model_dst)
                fp = Footprint.load(fp_path)
                fp.set_model_path(f"${{SR_LIB}}/models/{model_name}")
                fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
                model_ref = ModelRef(file=f"models/{model_name}")

            # 4. datasheet file
            datasheet = None
            if staged.datasheet_source is not None:
                ds_name = f"{part_id}.pdf"
                ds_dst = self.lib.datasheets_dir / ds_name
                shutil.copyfile(staged.datasheet_source, ds_dst)
                txn.track(ds_dst)
                datasheet = staged.datasheet_meta or Datasheet()
                datasheet.file = ds_name

            # 5. the symbol's Footprint property, then mirror KiCad-visible fields
            record = PartRecord(
                id=part_id,
                display_name=staged.display_name,
                category=staged.category,
                description=staged.description,
                tags=list(staged.tags),
                mpn=staged.mpn,
                manufacturer=staged.manufacturer,
                datasheet=datasheet,
                symbol=LibRef(lib=nickname, name=staged.entry_name),
                footprint=LibRef(lib=nickname, name=staged.entry_name),
                model=model_ref,
                provenance=staged.provenance,
            )
            sym_lib = SymbolLib.load(sym_lib_path)
            sym = sym_lib.get_symbol(staged.entry_name)
            sym.set_property("Footprint", f"{nickname}:{staged.entry_name}")
            mirror_fields_to_symbol(sym, record)
            sym_lib.save(sym_lib_path)

            # 6. the JSON record
            json_path = self.lib.parts_dir / f"{part_id}.json"
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)

            txn.commit(f"Add {staged.entry_name} ({staged.category}): symbol, footprint, "
                       f"{'3D model, ' if model_ref else ''}"
                       f"{'datasheet, ' if datasheet else ''}record")
        return record
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/mutation/test_library_ops.py -v`
Expected: PASS (3 add_part tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/mutation/library_ops.py tests/backend/mutation/test_library_ops.py
git commit -m "Add atomic add_part operation with model and datasheet placement"
```

---

## Task 14: move_category, delete_part, edit_field (atomic)

**Files:**
- Modify: `app/backend/stockroom/mutation/library_ops.py` (add methods)
- Test: `tests/backend/mutation/test_library_ops.py` (append cases)

**Interfaces:**
- Consumes: everything Task 13 consumes.
- Produces (added to `LibraryOps`):
  - `.edit_field(part_id: str, field: str, value) -> PartRecord` — set a top-level record field (`display_name`, `description`, `tags`, `mpn`, `manufacturer`), re-mirror the affected KiCad-visible property into the symbol when relevant, write JSON, commit atomically.
  - `.move_category(part_id: str, new_category: str) -> PartRecord` — move the symbol node from the old `SR-<Old>.kicad_sym` to `SR-<New>.kicad_sym`, move the footprint `.kicad_mod` between `.pretty` dirs, update the symbol's `Footprint` property and the record's `symbol`/`footprint`/`category`, write JSON, all in one atomic commit.
  - `.delete_part(part_id: str) -> None` — remove the symbol node from its category lib, delete the footprint `.kicad_mod`, delete model + datasheet files, delete the JSON, one atomic commit.
  - `.load_record(part_id: str) -> PartRecord` (helper).

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/mutation/test_library_ops.py`:

```python
def test_edit_field_updates_json_and_mirror(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    rec = ops.edit_field("tps62130rgtr", "manufacturer", "Texas Instruments")
    assert rec.manufacturer == "Texas Instruments"
    sym = SymbolLib.load(profile.library.symbol_lib_path("ICs")).get_symbol("TPS62130RGTR")
    assert sym.get_property("Manufacturer") == "Texas Instruments"
    assert repo.is_clean()


def test_move_category_relocates_symbol_and_footprint(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    # also pre-create the destination category (Modules) libs
    (profile.library.symbol_lib_path("Modules")).write_text(
        '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline=""
    )
    profile.library.footprint_lib_path("Modules").mkdir(parents=True, exist_ok=True)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    rec = ops.move_category("tps62130rgtr", "Modules")

    assert rec.category == "Modules"
    assert rec.symbol.lib == "SR-Modules"
    # gone from ICs, present in Modules
    assert "TPS62130RGTR" not in SymbolLib.load(profile.library.symbol_lib_path("ICs")).symbol_names
    assert "TPS62130RGTR" in SymbolLib.load(profile.library.symbol_lib_path("Modules")).symbol_names
    assert not (profile.library.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod").exists()
    assert (profile.library.footprint_lib_path("Modules") / "TPS62130RGTR.kicad_mod").exists()
    sym = SymbolLib.load(profile.library.symbol_lib_path("Modules")).get_symbol("TPS62130RGTR")
    assert sym.get_property("Footprint") == "SR-Modules:TPS62130RGTR"
    assert repo.is_clean()


def test_delete_part_removes_everything(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    ops.delete_part("tps62130rgtr")
    lib = profile.library
    assert not (lib.parts_dir / "tps62130rgtr.json").exists()
    assert "TPS62130RGTR" not in SymbolLib.load(lib.symbol_lib_path("ICs")).symbol_names
    assert not (lib.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod").exists()
    assert not (lib.models_dir / "TPS62130RGTR.step").exists()
    assert not (lib.datasheets_dir / "tps62130rgtr.pdf").exists()
    assert repo.is_clean()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/mutation/test_library_ops.py -k "edit_field or move_category or delete_part" -v`
Expected: FAIL with `AttributeError: 'LibraryOps' object has no attribute 'edit_field'`.

- [ ] **Step 3: Write the implementation**

Add these to `app/backend/stockroom/mutation/library_ops.py`. First add the imports at the top (extend the existing `from stockroom.kicad.symbol_lib import SymbolLib` region and category import):

```python
from stockroom.model.category import category_footprint_lib, category_symbol_lib
```

Then add a small helper near the top of the module (after imports):

```python
# top-level record field -> KiCad property to re-mirror on edit (None => no mirror)
_MIRROR_ON_EDIT = {
    "mpn": "MPN",
    "manufacturer": "Manufacturer",
    "description": "Description",
}
```

Add these methods to `LibraryOps`:

```python
    def load_record(self, part_id: str) -> PartRecord:
        path = self.lib.parts_dir / f"{part_id}.json"
        return PartRecord.loads(path.read_text(encoding="utf-8"))

    def edit_field(self, part_id: str, field: str, value) -> PartRecord:
        record = self.load_record(part_id)
        if not hasattr(record, field):
            raise ValueError(f"unknown field: {field}")
        setattr(record, field, value)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        sym_lib_path = self.lib.symbol_lib_path(record.category)
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            prop = _MIRROR_ON_EDIT.get(field)
            if prop is not None or field == "tags":
                sym_lib = SymbolLib.load(sym_lib_path)
                sym = sym_lib.get_symbol(record.symbol.name)
                if field == "tags":
                    sym.set_property("ki_keywords", " ".join(record.tags))
                else:
                    sym.set_property(prop, str(value))
                sym_lib.save(sym_lib_path)
                txn.track(sym_lib_path)
            txn.commit(f"Edit {part_id}: {field}")
        return record

    def _remove_symbol_node(self, sym_lib_path: Path, name: str) -> str:
        """Remove the named symbol node from a lib and return the new file text."""
        sym_lib = SymbolLib.load(sym_lib_path)
        target = None
        for node in sym_lib._doc.root.find_all("symbol"):
            if node.children[1].value == name:
                target = node
                break
        if target is None:
            raise ValueError(f"symbol {name!r} not in {sym_lib_path.name}")
        sym_lib._doc.root.remove_child(target)
        return sym_lib.serialize()

    def move_category(self, part_id: str, new_category: str) -> PartRecord:
        record = self.load_record(part_id)
        old_cat = record.category
        if new_category == old_cat:
            return record
        name = record.symbol.name
        old_sym = self.lib.symbol_lib_path(old_cat)
        new_sym = self.lib.symbol_lib_path(new_category)
        old_fp = self.lib.footprint_lib_path(old_cat) / f"{name}.kicad_mod"
        new_pretty = self.lib.footprint_lib_path(new_category)
        new_fp = new_pretty / f"{name}.kicad_mod"
        new_nickname = category_nickname(new_category)
        json_path = self.lib.parts_dir / f"{part_id}.json"

        with Transaction(self.repo) as txn:
            # symbol: append to new lib (byte-preserving), then remove from old
            merge_symbol_into_lib(new_sym, old_sym, name, name)
            txn.track(new_sym)
            old_sym.write_text(self._remove_symbol_node(old_sym, name), encoding="utf-8", newline="")
            txn.track(old_sym)
            # footprint: move file between .pretty dirs
            new_pretty.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_fp), str(new_fp))
            txn.track(old_fp, new_fp)
            # symbol Footprint property + record fields
            sym_lib = SymbolLib.load(new_sym)
            sym_lib.get_symbol(name).set_property("Footprint", f"{new_nickname}:{name}")
            sym_lib.save(new_sym)
            record.category = new_category
            record.symbol = LibRef(lib=new_nickname, name=name)
            record.footprint = LibRef(lib=new_nickname, name=name)
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Move {part_id}: {old_cat} -> {new_category}")
        return record

    def delete_part(self, part_id: str) -> None:
        record = self.load_record(part_id)
        name = record.symbol.name
        sym_lib_path = self.lib.symbol_lib_path(record.category)
        fp_path = self.lib.footprint_lib_path(record.category) / f"{name}.kicad_mod"
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            sym_lib_path.write_text(self._remove_symbol_node(sym_lib_path, name), encoding="utf-8", newline="")
            txn.track(sym_lib_path)
            for p in (fp_path, json_path):
                if p.exists():
                    p.unlink()
                    txn.track(p)
            if record.model and record.model.file:
                mp = self.lib.root / record.model.file
                if mp.exists():
                    mp.unlink()
                    txn.track(mp)
            if record.datasheet and record.datasheet.file:
                dp = self.lib.datasheets_dir / record.datasheet.file
                if dp.exists():
                    dp.unlink()
                    txn.track(dp)
            txn.commit(f"Delete {part_id}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/mutation/test_library_ops.py -v`
Expected: PASS (all add + edit + move + delete tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/mutation/library_ops.py tests/backend/mutation/test_library_ops.py
git commit -m "Add atomic edit_field, move_category, and delete_part operations"
```

---

## Task 15: Sync engine

**Files:**
- Create: `app/backend/stockroom/vcs/sync.py`
- Modify: `app/backend/stockroom/vcs/__init__.py` (re-export)
- Test: `tests/backend/vcs/test_sync.py`

**Interfaces:**
- Consumes: `GitRepo`, `PullResult`, `PushResult` (Task 4).
- Produces:
  - `SyncState` enum-like string constants: `SYNCED`, `PUSHED`, `PULLED`, `OFFLINE`, `DIVERGED`, `NO_REMOTE`.
  - `SyncResult` dataclass (`state: str`, `pulled: bool`, `pushed: bool`, `detail: str`).
  - `SyncEngine(repo: GitRepo)`:
    - `.sync() -> SyncResult` — pull-before-push, fast-forward only. If no upstream, `NO_REMOTE`. Pull first; on non-ff, `DIVERGED` (never clobber, surface state). On network failure, `OFFLINE` (local state intact). Then push if ahead. Idempotent when already in sync.
- Note: background timer scheduling is an M5 concern; `SyncEngine.sync()` is the unit the timer and post-commit hook call.

- [ ] **Step 1: Write the failing test**

`tests/backend/vcs/test_sync.py`:

```python
import shutil

import pytest

from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine, SyncState

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _origin_and_clone(tmp_path, name):
    origin = tmp_path / "origin.git"
    if not origin.exists():
        GitRepo(origin).init(bare=True)
    clone = GitRepo(tmp_path / name)
    clone.clone_from(origin)
    return origin, clone


def test_no_remote_reported(tmp_path):
    r = GitRepo(tmp_path / "local")
    r.init()
    (r.root / "f").write_text("x")
    r.commit("x", [r.root / "f"])
    res = SyncEngine(r).sync()
    assert res.state == SyncState.NO_REMOTE


def test_push_when_ahead(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("v1")
    a.commit("v1", [a.root / "f"])
    res = SyncEngine(a).sync()
    assert res.pushed is True
    assert res.state in (SyncState.PUSHED, SyncState.SYNCED)

    # a second clone sees it after pull
    _, b = _origin_and_clone(tmp_path, "b")
    assert (b.root / "f").read_text() == "v1"


def test_pull_when_behind(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("v1")
    a.commit("v1", [a.root / "f"])
    SyncEngine(a).sync()

    _, b = _origin_and_clone(tmp_path, "b")
    (a.root / "f").write_text("v2")
    a.commit("v2", [a.root / "f"])
    SyncEngine(a).sync()

    res = SyncEngine(b).sync()
    assert res.pulled is True
    assert (b.root / "f").read_text() == "v2"


def test_divergence_is_surfaced_not_clobbered(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("base")
    a.commit("base", [a.root / "f"])
    SyncEngine(a).sync()

    _, b = _origin_and_clone(tmp_path, "b")
    (a.root / "f").write_text("remote")
    a.commit("remote", [a.root / "f"])
    SyncEngine(a).sync()
    (b.root / "g").write_text("local")
    b.commit("local", [b.root / "g"])

    res = SyncEngine(b).sync()
    assert res.state == SyncState.DIVERGED
    # local work intact, remote not merged over it
    assert (b.root / "g").read_text() == "local"


def test_already_in_sync_is_idempotent(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("v1")
    a.commit("v1", [a.root / "f"])
    SyncEngine(a).sync()
    res = SyncEngine(a).sync()
    assert res.state == SyncState.SYNCED
    assert res.pulled is False and res.pushed is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/vcs/test_sync.py -v`
Expected: FAIL with `ModuleNotFoundError` for `stockroom.vcs.sync`.

- [ ] **Step 3: Write the implementation**

`app/backend/stockroom/vcs/sync.py`:

```python
"""Pull-before-push, fast-forward-only library sync.

True divergence is never clobbered: it is surfaced with the exact state and the
caller decides. Offline is a first-class state (local work is untouched, sync
resumes when the network returns). This is the unit the M5 background timer and
the post-commit hook call (spec sections 2 and 9).
"""

from __future__ import annotations

from dataclasses import dataclass

from stockroom.vcs.repo import GitRepo


class SyncState:
    SYNCED = "synced"
    PUSHED = "pushed"
    PULLED = "pulled"
    OFFLINE = "offline"
    DIVERGED = "diverged"
    NO_REMOTE = "no_remote"


@dataclass
class SyncResult:
    state: str
    pulled: bool = False
    pushed: bool = False
    detail: str = ""


def _looks_offline(reason: str) -> bool:
    r = reason.lower()
    return any(
        tok in r
        for tok in ("could not resolve host", "connection", "timed out",
                    "network", "unable to access", "no route")
    )


class SyncEngine:
    def __init__(self, repo: GitRepo):
        self.repo = repo

    def sync(self) -> SyncResult:
        ab = self.repo.ahead_behind()
        if ab is None:
            return SyncResult(state=SyncState.NO_REMOTE, detail="no upstream configured")

        pulled = False
        pull = self.repo.pull_ff()
        if not pull.ok:
            if _looks_offline(pull.reason):
                return SyncResult(state=SyncState.OFFLINE, detail=pull.reason)
            return SyncResult(state=SyncState.DIVERGED, detail=pull.reason)
        pulled = pull.updated

        # re-evaluate ahead count after a possible fast-forward
        ab2 = self.repo.ahead_behind() or (0, 0)
        pushed = False
        if ab2[0] > 0:
            push = self.repo.push()
            if not push.ok:
                if _looks_offline(push.reason):
                    return SyncResult(state=SyncState.OFFLINE, pulled=pulled, detail=push.reason)
                return SyncResult(state=SyncState.DIVERGED, pulled=pulled, detail=push.reason)
            pushed = True

        if pushed:
            return SyncResult(state=SyncState.PUSHED, pulled=pulled, pushed=True)
        if pulled:
            return SyncResult(state=SyncState.PULLED, pulled=True)
        return SyncResult(state=SyncState.SYNCED)
```

- [ ] **Step 4: Update the vcs package init**

Replace `app/backend/stockroom/vcs/__init__.py` with:

```python
"""Version control: git wrapper and sync engine."""

from stockroom.vcs.repo import Commit, GitError, GitRepo, PullResult, PushResult
from stockroom.vcs.sync import SyncEngine, SyncResult, SyncState

__all__ = [
    "Commit",
    "GitError",
    "GitRepo",
    "PullResult",
    "PushResult",
    "SyncEngine",
    "SyncResult",
    "SyncState",
]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/vcs/test_sync.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/vcs/sync.py app/backend/stockroom/vcs/__init__.py tests/backend/vcs/test_sync.py
git commit -m "Add pull-before-push ff-only sync engine with offline and divergence states"
```

---

## Task 16: Drift detection (doctor core)

**Files:**
- Modify: `app/backend/stockroom/mutation/library_ops.py` (add `detect_drift` + `DriftReport`)
- Test: `tests/backend/mutation/test_library_ops.py` (append cases)

**Interfaces:**
- Consumes: `PartRecord` (Task 2); `SymbolLib` (M1); placement `_datasheet_value` logic (Task 12 — reuse `mirror_fields_to_symbol`'s field map by importing a shared helper).
- Produces (added to `LibraryOps`):
  - `DriftItem` dataclass (`part_id`, `property`, `json_value`, `symbol_value`).
  - `DriftReport` dataclass (`items: list[DriftItem]`, `missing_symbol: list[str]`).
  - `.detect_drift() -> DriftReport` — for every part JSON, compare the KiCad-visible fields against the actual symbol properties in the category lib; report any mismatch (a field edited behind Stockroom's back). It DETECTS and returns a diff only; the interactive heal is the M6 `doctor` UI (deferred, logged below).
- Refactor: extract the record->property mapping from `mirror_fields_to_symbol` into a shared `kicad_visible_properties(record) -> dict[str, str]` in `placement.py`, so drift compares against exactly what `add_part` would have written (single source of truth, DRY).

- [ ] **Step 1: Refactor the mirror map into a shared function**

In `app/backend/stockroom/mutation/placement.py`, replace the body of `mirror_fields_to_symbol` to delegate to a new exported helper:

```python
def kicad_visible_properties(record: PartRecord) -> dict[str, str]:
    """The KiCad-visible subset mirrored into a symbol, as {property: value}.
    Single source of truth for both writing (mirror) and drift detection."""
    values = {
        "MPN": record.mpn,
        "Manufacturer": record.manufacturer,
        "Description": record.description,
        "ki_keywords": " ".join(record.tags),
        "Datasheet": _datasheet_value(record),
    }
    if record.purchase and record.purchase[0].url:
        values["Purchase"] = record.purchase[0].url
    return {k: v for k, v in values.items() if v}


def mirror_fields_to_symbol(symbol: Symbol, record: PartRecord) -> None:
    for name, value in kicad_visible_properties(record).items():
        symbol.set_property(name, value)
```

- [ ] **Step 2: Write the failing test**

Append to `tests/backend/mutation/test_library_ops.py`:

```python
def test_detect_drift_clean_after_add(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    report = ops.detect_drift()
    assert report.items == []
    assert report.missing_symbol == []


def test_detect_drift_finds_behind_the_back_edit(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    # scribble the symbol property directly, as if KiCad edited it
    sym_lib_path = profile.library.symbol_lib_path("ICs")
    lib = SymbolLib.load(sym_lib_path)
    lib.get_symbol("TPS62130RGTR").set_property("Manufacturer", "WRONG")
    lib.save(sym_lib_path)

    report = ops.detect_drift()
    assert len(report.items) == 1
    item = report.items[0]
    assert item.part_id == "tps62130rgtr"
    assert item.property == "Manufacturer"
    assert item.json_value == "TI"
    assert item.symbol_value == "WRONG"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/backend/mutation/test_library_ops.py -k drift -v`
Expected: FAIL with `AttributeError: 'LibraryOps' object has no attribute 'detect_drift'`.

- [ ] **Step 4: Write the implementation**

In `app/backend/stockroom/mutation/library_ops.py`, add the import:

```python
from stockroom.mutation.placement import (
    kicad_visible_properties,
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)
```

Add the dataclasses near the top (after `StagedPart`):

```python
@dataclass
class DriftItem:
    part_id: str
    property: str
    json_value: str
    symbol_value: str


@dataclass
class DriftReport:
    items: list[DriftItem] = field(default_factory=list)
    missing_symbol: list[str] = field(default_factory=list)
```

Add the method to `LibraryOps`:

```python
    def detect_drift(self) -> DriftReport:
        """Compare each part's JSON (the source of truth) against its symbol's
        mirrored properties; report mismatches. Detection only: healing is the
        M6 doctor UI (shows a diff before healing, spec section 3)."""
        report = DriftReport()
        parts_dir = self.lib.parts_dir
        if not parts_dir.exists():
            return report
        for json_path in sorted(parts_dir.glob("*.json")):
            record = PartRecord.loads(json_path.read_text(encoding="utf-8"))
            if record.symbol is None:
                continue
            sym_lib_path = self.lib.symbol_lib_path(record.category)
            try:
                sym = SymbolLib.load(sym_lib_path).get_symbol(record.symbol.name)
            except Exception:
                report.missing_symbol.append(record.id)
                continue
            for prop, expected in kicad_visible_properties(record).items():
                actual = sym.get_property(prop)
                if actual is not None and actual != expected:
                    report.items.append(
                        DriftItem(part_id=record.id, property=prop, json_value=expected, symbol_value=actual)
                    )
        return report
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/mutation/test_library_ops.py -v`
Expected: PASS (all library_ops tests including drift).

- [ ] **Step 6: Full-suite gate + commit**

Run the whole backend suite to confirm no regressions across M1 + M2:

Run: `uv run pytest tests/backend -q`
Expected: all pass (kicad-cli integration tests skip where absent).

```bash
git add app/backend/stockroom/mutation/library_ops.py app/backend/stockroom/mutation/placement.py tests/backend/mutation/test_library_ops.py
git commit -m "Add drift detection (doctor core) with a shared KiCad-visible property map"
```

---

## Deferrals carried into M2 from M1 (addressed here where relevant)

- **`quote_kicad` newline escape** (M1 deferral, "relevant NOW when writing values that could contain newlines"): M2 property writes go through `Symbol.set_property` -> `set_value(quote=True)` -> `quote_kicad`, which escapes `\\` and `"` but not literal newlines. Part-record fields mirrored into symbols (MPN, Manufacturer, Description, keywords, datasheet path, purchase URL) are single-line by construction, and `add_part`/`edit_field` accept them as such. If a multi-line value ever reaches a mirror, KiCad's parser accepts a literal newline inside a quoted string, and the byte-preserving round-trip test would catch a break. No code change needed in M2; re-evaluate if free-text multi-line fields are ever mirrored (they are not in this milestone).
- **Exact-filename SVG glob / `fp svgs[0]`** (M1 deferral): not touched in M2 (previews are M5/M6). Left as-is.
- **effects/hide on inserted schematic props** (M1 deferral): schematic writes are M7 (audit); not touched here.
- **overlap-check O(n^2)** (M1 deferral): edit batches in M2 are tiny (a handful per mutation); no change.

## Deferrals introduced by M2 (logged, not hidden)

- **Interactive drift heal (`doctor` UI).** M2 ships `detect_drift` (detection + diff). The "show a diff before healing, then heal" flow is the M6 doctor surface. Done means: a UI lists drift items and, on user confirm, rewrites the symbol property (or the JSON) through an atomic `LibraryOps` mutation. Tracked for M6.
- **Background sync timer.** `SyncEngine.sync()` is complete and tested; the periodic scheduler and the post-commit-batch trigger are wired in M5 (backend app lifecycle). Done means: a timer calls `sync()` on an interval and after each commit batch, surfacing `DIVERGED`/`OFFLINE` states as toasts.
- **dulwich / bundled-git fallback.** `GitRepo` requires the `git` binary (present in dev/CI and guaranteed by the M5 launcher). The dulwich ff-pull fallback for end-user machines without git is M5 launcher scope. Done means: the launcher probes for git, else uses dulwich for ff-only pulls, and the backend is handed a working git path.
- **File-level locking for concurrent same-library writes.** `LibraryOps` mutations write a category `.kicad_sym` via read-modify-write. M2 assumes single-threaded per-profile access (the synchronous mutation engine guarantees this today), so no lock is needed yet. Done means: when M5 puts the mutation engine behind concurrent FastAPI requests, symbol-lib writes take an `fcntl`/`msvcrt` file lock so two mutations on one category cannot clobber each other. Tracked for M5.
- **`kicad-cli fp upgrade` for foreign footprints.** M2 places already-KiCad `.kicad_mod` footprints. Legacy/foreign footprint upgrade is part of the M3 ingestion convert stage. Done means: M3 runs `fp upgrade` on non-KiCad footprint inputs before they reach `place_footprint`.

---

## Self-Review

**1. Spec coverage.**

- §2 Library data sync (scoped commits, pull-before-push ff-only, divergence surfaced, offline first-class): Tasks 4 (GitRepo), 15 (SyncEngine). ✓
- §2 Per-machine state (`config.json`: active profile, KiCad path, keys, sync prefs; nothing secret in repo): Task 3 (MachineConfig). ✓
- §3 Part record (all fields, one JSON per part, canonical/merge-friendly): Task 2. ✓
- §3 KiCad-visible mirror into symbol properties; single writer; doctor detects drift with a diff: Tasks 12 (mirror), 16 (detect_drift). Interactive heal deferred to M6 (logged). ✓
- §3 Categories (fixed 13, SR-<Category> libs, move between categories atomically): Tasks 1, 14 (move_category). ✓
- §3 Profiles (self-contained folders, create/switch/delete, active = per-machine, delete = scoped commit): Tasks 3 (active profile), 5 (create/delete). ✓
- §4 Wiring (locate config dir; SR_LIB in kicad_common.json; register category libs in global sym/fp-lib-table as KiCad rows with ${SR_LIB} URIs and SR- nicknames; never touch the Table row; idempotent/scoped/safe/aware): Tasks 6, 7, 8, 9, 10. ✓
- §4 3D model refs written as ${SR_LIB}/models/... in the (model ...) block: Task 13 (add_part sets `${SR_LIB}/models/<file>`). ✓
- §5 Commit stage (atomic transaction: move files into per-category libs, footprint field on symbol, (model ...) on footprint, datasheet stored, JSON written, git commit; re-parse validation gate; failed ingest leaves zero trace): Tasks 11 (Transaction), 12, 13. ✓ (The zip inspect/convert/stage stages upstream of the commit are M3, which feeds `StagedPart`.)
- §8 Never invent a version stamp; new category libs stamped by installed KiCad via kicad-cli: Task 7 (verified). ✓
- §8 Byte preservation for lib-table edits: Task 8 (via M1 span layer). ✓
- §9 Atomic mutations, timestamped backups before touching non-Stockroom files, git as undo, round-trip validation, honest degradation: Tasks 9 (backup), 11 (validate + rollback), 15 (honest sync states). ✓
- §12 Acceptance #3 (fresh machine: clone, run, first-run setup, KiCad sees the library): the wiring half is Task 10; the launcher/first-run-setup wrapper is M5. ✓ (M2 provides the mechanism, M5 the UX.)

**2. Placeholder scan.** No `TBD`/`TODO`/"add error handling"/"similar to Task N" left; every code step carries full code; every test step carries real assertions. ✓

**3. Type consistency.** `ProfileLibrary.symbol_lib_path`/`footprint_lib_path` names are consistent across Tasks 5, 10, 13, 14, 16. `LibRef` (not `SymbolRef`) is the single ref type used in `PartRecord` and set in `add_part`/`move_category`. `category_nickname`/`category_symbol_lib`/`category_footprint_lib` names are consistent from Task 1 through the wiring and mutation tasks. `Transaction.track`/`.commit`/`.validate` names match across Tasks 11, 13, 14. `kicad_visible_properties` (Task 16 refactor) is the one map used by both `mirror_fields_to_symbol` and `detect_drift`. `GitRepo.commit(message, paths)` argument order is consistent everywhere it is called. ✓

## Execution Handoff

Plan complete. Recommended: **subagent-driven-development** (fresh subagent per task, two-stage review between tasks), the same loop that shipped M1. Branch `m2-library-data` off `main`; ledger each task in `.superpowers/sdd/progress.md`.
