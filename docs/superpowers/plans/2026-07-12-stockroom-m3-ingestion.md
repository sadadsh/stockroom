# Stockroom M3: Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn vendor packages (zips, folders, bare files, any mix) and LCSC part numbers into review-ready staged parts and commit each one atomically into the active profile's per-category libraries via the M2 `LibraryOps.add_part` seam.

**Architecture:** A new `stockroom.ingest` package with a clean two-call surface — `IngestPipeline.inspect(inputs, lcsc_ids)` returns `StagingCandidate`s (Inspect → Convert → Stage), and `IngestPipeline.commit(candidate)` runs one atomic, zero-trace transaction (Commit). Source identity is fingerprinted by archive **content**, never origin (ported from the reference importer `Steffen-W/Import-LIB-KiCad-Plugin::identify_remote_type`). Legacy/foreign formats are normalized through `kicad-cli sym upgrade` / `fp upgrade`. The symbol's KiCad name is always read from **inside** the file, never from the filename (UltraLibrarian ships timestamp-named symbol files). The LCSC path shells out to `easyeda2kicad` and feeds the same staging.

**Tech Stack:** Python 3.12, stdlib `zipfile`/`hashlib`/`shutil`/`tempfile`, `subprocess` to `kicad-cli` (10.0.4) and `easyeda2kicad` (new dependency), the M1 byte-preserving s-expression layer, the M2 mutation/model/store spine. `pytest`.

## Global Constraints

- **No em dashes** anywhere (code, comments, docstrings, test names, commit messages). Standing owner rule for all Stockroom output.
- **Byte preservation is mandatory for every TARGET KiCad file written** (the category `.kicad_sym` and `.pretty` files). Use the M2 primitives (`merge_symbol_into_lib`, `place_footprint`, `Footprint.set_model_path`) which go through the M1 span layer. Incoming vendor files ARE allowed to be re-serialized during normalization (they are inputs, not tracked library files).
- **Never invent a KiCad version stamp.** Empty category libs are created only via `create_empty_symbol_lib(cli, dst)` (upgrades an empty legacy `.lib` through kicad-cli, which emits stamp `20251024`).
- **A failed ingest leaves zero trace.** The commit stage runs inside one M2 `Transaction`; on any failure git restores every touched path.
- **Fingerprint by content, never by origin.** Detection order and markers are load-bearing and copied verbatim from the reference importer: Octopart (`device.lib`+`device.dcm`) → Samacsys (folder named exactly `KiCad`) → UltraLibrarian (folder named exactly `KiCAD`, capitalization is the discriminator) → Snapeda (loose files, fallback) → Partial (3D only).
- **3D model glob priority:** `.step` then `.stp` then `.wrl`, searched across the whole archive. No vendor wires the 3D into the footprint; Stockroom writes the `(model ${SR_LIB}/models/...)` link itself (`add_part` already does this).
- **New runtime dependency:** `easyeda2kicad` (LCSC path only). Added to `pyproject.toml` `dependencies` and `uv.lock` in Task 9. All other work is stdlib + existing deps.
- **Source layout:** backend package root is `app/backend/stockroom/`; tests live under `tests/backend/`; `pytest` config sets `pythonpath = ["app/backend"]`. Tests needing the binary use the `requires_kicad_cli` marker from `tests/backend/conftest.py`.

---

## File Structure

New package `app/backend/stockroom/ingest/`:

- `__init__.py` — package marker.
- `errors.py` — `IngestError` (base for pipeline failures).
- `sandbox.py` — `unpack_inputs(inputs, workdir)`: safely extract zips / copy folders and bare files into isolated sandbox roots; `sha256_of(path)`.
- `fingerprint.py` — `detect_source(root) -> DetectedSource`: content fingerprint + file location. Pure (no kicad-cli).
- `naming.py` — `propose_entry_name`, `propose_display_name`, `propose_category`: pure proposal heuristics.
- `convert.py` — `normalize_symbol(cli, src, dcm=None) -> Path`, `read_symbol_names(path) -> list[str]`, `normalize_footprint(cli, src) -> Path`. Uses kicad-cli.
- `staging.py` — `StagingCandidate` dataclass + `to_staged_part()`; `build_candidates(cli, detected, provenance) -> list[StagingCandidate]`.
- `lcsc.py` — `is_lcsc_id(text)`, `fetch_lcsc(lcsc_id, workdir) -> DetectedSource` (via `easyeda2kicad` subprocess).
- `pipeline.py` — `IngestPipeline(profile, repo, cli)`: `inspect(...)`, `commit(...)`, `attach_model(...)`.

Modified existing files:

- `app/backend/stockroom/kicad/cli.py` — add `fp_upgrade(pretty_dir)` (M2 deferral now due).
- `app/backend/stockroom/mutation/library_ops.py` — `LibraryOps.__init__` gains an optional `cli`; `add_part` ensures the category symbol lib exists inside the transaction.
- `pyproject.toml` + `uv.lock` — add `easyeda2kicad` (Task 9).

New test files under `tests/backend/ingest/`:

- `__init__.py`, `test_sandbox.py`, `test_fingerprint.py`, `test_naming.py`, `test_convert.py`, `test_staging.py`, `test_lcsc.py`, `test_pipeline.py`, `test_ensure_category_lib.py`, `vendor_fixtures.py` (shared synthetic-zip builder).

---

### Task 1: Add `fp_upgrade` to the kicad-cli wrapper

**Files:**
- Modify: `app/backend/stockroom/kicad/cli.py`
- Test: `tests/backend/kicad/test_cli.py`

**Interfaces:**
- Consumes: existing `KiCadCli._run(*args) -> str`, `KiCadCli.sym_upgrade(src, dst)`.
- Produces: `KiCadCli.fp_upgrade(pretty_dir: Path) -> None` — runs `kicad-cli fp upgrade <pretty_dir>` in place; raises `KiCadCliError` on failure.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/kicad/test_cli.py`:

```python
def test_fp_upgrade_rewrites_footprint_to_current_format(tmp_path, fixtures_dir):
    from stockroom.kicad.cli import KiCadCli
    import shutil

    cli = KiCadCli()
    pretty = tmp_path / "in.pretty"
    pretty.mkdir()
    # one_footprint.kicad_mod carries an older (version 20240108) stamp.
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", pretty / "fp.kicad_mod")
    cli.fp_upgrade(pretty)
    # still a valid, parseable footprint after upgrade
    from stockroom.kicad.footprint import Footprint
    fp = Footprint.load(pretty / "fp.kicad_mod")
    assert fp.name  # non-empty name survives the upgrade
```

Mark it: put `@requires_kicad_cli` above the function (import already present in `test_cli.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_cli.py::test_fp_upgrade_rewrites_footprint_to_current_format -v`
Expected: FAIL with `AttributeError: 'KiCadCli' object has no attribute 'fp_upgrade'`.

- [ ] **Step 3: Write minimal implementation**

Add to `app/backend/stockroom/kicad/cli.py` after `sym_upgrade`:

```python
    def fp_upgrade(self, pretty_dir: Path) -> None:
        """Upgrade every footprint in a .pretty directory to the current KiCad
        format, in place. A no-op-equivalent rewrite for already-current
        footprints; normalizes older and foreign-origin footprints."""
        self._run("fp", "upgrade", str(Path(pretty_dir)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_cli.py::test_fp_upgrade_rewrites_footprint_to_current_format -v`
Expected: PASS (or SKIP if kicad-cli is absent; must PASS on WSL).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/cli.py tests/backend/kicad/test_cli.py
git commit -m "Add KiCadCli.fp_upgrade for foreign/legacy footprint normalization"
```

---

### Task 2: Sandbox unpack + content hash

**Files:**
- Create: `app/backend/stockroom/ingest/__init__.py` (empty)
- Create: `app/backend/stockroom/ingest/errors.py`
- Create: `app/backend/stockroom/ingest/sandbox.py`
- Create: `tests/backend/ingest/__init__.py` (empty)
- Test: `tests/backend/ingest/test_sandbox.py`

**Interfaces:**
- Produces:
  - `IngestError(Exception)` in `errors.py`.
  - `sha256_of(path: Path) -> str` — hex digest of a file's bytes.
  - `Unpacked` dataclass: `root: Path`, `origin: Path`, `is_zip: bool`, `sha256: str`.
  - `unpack_inputs(inputs: list[Path], workdir: Path) -> list[Unpacked]` — for each input: a zip is extracted into `workdir/<n>/` (zip-slip guarded); a folder is copied into `workdir/<n>/`; a bare file is copied into `workdir/<n>/`. `sha256` is the zip's digest for zips, the file's digest for bare files, and `""` for folders. Raises `IngestError` on a missing input or an unsafe zip entry.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/__init__.py` (empty) and `tests/backend/ingest/test_sandbox.py`:

```python
import zipfile

import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.sandbox import sha256_of, unpack_inputs


def test_unpack_zip_extracts_into_isolated_root(tmp_path):
    z = tmp_path / "part.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("KiCad/foo.kicad_mod", "(footprint)")
    work = tmp_path / "work"
    [u] = unpack_inputs([z], work)
    assert u.is_zip is True
    assert (u.root / "KiCad" / "foo.kicad_mod").read_text() == "(footprint)"
    assert u.sha256 == sha256_of(z)


def test_unpack_bare_file_copies_into_root(tmp_path):
    f = tmp_path / "sym.kicad_sym"
    f.write_text("(kicad_symbol_lib)")
    [u] = unpack_inputs([f], tmp_path / "work")
    assert u.is_zip is False
    assert (u.root / "sym.kicad_sym").read_text() == "(kicad_symbol_lib)"
    assert u.sha256 == sha256_of(f)


def test_unpack_folder_copies_tree(tmp_path):
    src = tmp_path / "src"
    (src / "KiCAD").mkdir(parents=True)
    (src / "KiCAD" / "a.lib").write_text("x")
    [u] = unpack_inputs([src], tmp_path / "work")
    assert (u.root / "KiCAD" / "a.lib").read_text() == "x"
    assert u.sha256 == ""


def test_unpack_multiple_inputs_get_separate_roots(tmp_path):
    a = tmp_path / "a.kicad_sym"; a.write_text("a")
    b = tmp_path / "b.kicad_sym"; b.write_text("b")
    us = unpack_inputs([a, b], tmp_path / "work")
    assert len(us) == 2
    assert us[0].root != us[1].root


def test_zip_slip_is_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "pwn")
    with pytest.raises(IngestError):
        unpack_inputs([z], tmp_path / "work")


def test_missing_input_raises(tmp_path):
    with pytest.raises(IngestError):
        unpack_inputs([tmp_path / "nope.zip"], tmp_path / "work")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/__init__.py` (empty file).

Create `app/backend/stockroom/ingest/errors.py`:

```python
"""Shared exception type for the ingestion pipeline."""

from __future__ import annotations


class IngestError(Exception):
    pass
```

Create `app/backend/stockroom/ingest/sandbox.py`:

```python
"""Unpack ingestion inputs (zips, folders, bare files, any mix) into isolated
sandbox roots so the rest of the pipeline works against a plain directory tree,
never the caller's originals (spec section 5, stage 1). Zip extraction is
zip-slip guarded (spec section 11)."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from stockroom.ingest.errors import IngestError


@dataclass
class Unpacked:
    root: Path
    origin: Path
    is_zip: bool
    sha256: str


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract(zf: zipfile.ZipFile, dst: Path) -> None:
    dst_resolved = dst.resolve()
    for member in zf.namelist():
        target = (dst / member).resolve()
        if dst_resolved != target and dst_resolved not in target.parents:
            raise IngestError(f"unsafe zip entry escapes sandbox: {member!r}")
    zf.extractall(dst)


def unpack_inputs(inputs: list[Path], workdir: Path) -> list[Unpacked]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out: list[Unpacked] = []
    for n, raw in enumerate(inputs):
        origin = Path(raw)
        if not origin.exists():
            raise IngestError(f"input does not exist: {origin}")
        root = workdir / str(n)
        root.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, root, dirs_exist_ok=True)
            out.append(Unpacked(root=root, origin=origin, is_zip=False, sha256=""))
        elif zipfile.is_zipfile(origin):
            with zipfile.ZipFile(origin) as zf:
                _safe_extract(zf, root)
            out.append(Unpacked(root=root, origin=origin, is_zip=True, sha256=sha256_of(origin)))
        else:
            shutil.copyfile(origin, root / origin.name)
            out.append(Unpacked(root=root, origin=origin, is_zip=False, sha256=sha256_of(origin)))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_sandbox.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/__init__.py app/backend/stockroom/ingest/errors.py app/backend/stockroom/ingest/sandbox.py tests/backend/ingest/__init__.py tests/backend/ingest/test_sandbox.py
git commit -m "Add ingest sandbox: safe unpack of zips/folders/files with content hash"
```

---

### Task 3: Content fingerprint (detect vendor + locate files)

**Files:**
- Create: `app/backend/stockroom/ingest/fingerprint.py`
- Test: `tests/backend/ingest/test_fingerprint.py`

**Interfaces:**
- Consumes: nothing from other ingest modules (pure filesystem).
- Produces:
  - `DetectedSource` dataclass: `vendor: str` (one of `"octopart"`, `"samacsys"`, `"ultralibrarian"`, `"snapeda"`, `"partial"`), `symbol_path: Path | None`, `dcm_path: Path | None`, `footprint_paths: list[Path]`, `model_path: Path | None`, `datasheet_path: Path | None`.
  - `detect_source(root: Path) -> DetectedSource` — recursively fingerprints the unpacked tree in the reference importer's exact order. Raises `IngestError` when no usable file is found.

Detection rules (ported verbatim from `Steffen-W/Import-LIB-KiCad-Plugin::identify_remote_type`, adapted from `zipfile.Path` to filesystem `Path`):
- `_find(root, suffix)`: first path (depth-first) whose **name** ends with `suffix`.
- `_find_dir(root, exact_name)`: first **directory** whose basename equals `exact_name` exactly (case sensitive).
- Model: `_find(".step")` else `_find(".stp")` else `_find(".wrl")`.
- Order: Octopart (`device.lib` and `device.dcm` both present) → Samacsys (dir exactly `KiCad`; symbol = `.kicad_sym` or `.lib` inside it; footprints = loose `.kicad_mod` inside it) → UltraLibrarian (dir exactly `KiCAD`; symbol inside it; footprints = every `.kicad_mod` inside the `.pretty` inside it) → Snapeda (loose `.kicad_sym`/`.lib` at root; footprint = loose `.kicad_mod`) → Partial (only a model). Datasheet = first `.pdf` anywhere.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_fingerprint.py`:

```python
import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import detect_source


def _touch(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_octopart_detected_by_device_lib_and_dcm(tmp_path):
    _touch(tmp_path / "device.lib")
    _touch(tmp_path / "device.dcm")
    _touch(tmp_path / "MyPart.pretty" / "fp.kicad_mod")
    _touch(tmp_path / "MyPart.step")
    d = detect_source(tmp_path)
    assert d.vendor == "octopart"
    assert d.symbol_path.name == "device.lib"
    assert d.dcm_path.name == "device.dcm"
    assert [p.name for p in d.footprint_paths] == ["fp.kicad_mod"]
    assert d.model_path.name == "MyPart.step"


def test_samacsys_detected_by_exact_KiCad_folder(tmp_path):
    _touch(tmp_path / "KiCad" / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "KiCad" / "MyPart.kicad_mod", "(footprint)")
    d = detect_source(tmp_path)
    assert d.vendor == "samacsys"
    assert d.symbol_path.suffix == ".kicad_sym"
    assert [p.name for p in d.footprint_paths] == ["MyPart.kicad_mod"]


def test_samacsys_prefers_kicad_sym_over_legacy_lib(tmp_path):
    _touch(tmp_path / "KiCad" / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "KiCad" / "MyPart.lib", "EESchema")
    _touch(tmp_path / "KiCad" / "MyPart.kicad_mod", "(footprint)")
    d = detect_source(tmp_path)
    assert d.symbol_path.suffix == ".kicad_sym"


def test_ultralibrarian_detected_by_exact_KiCAD_folder_and_pretty(tmp_path):
    base = tmp_path / "KiCAD"
    _touch(base / "2025-02-10_09-58-00.lib", "EESchema")  # timestamp-named symbol
    _touch(base / "MyPart.pretty" / "VarA.kicad_mod", "(footprint)")
    _touch(base / "MyPart.pretty" / "VarB.kicad_mod", "(footprint)")
    _touch(tmp_path / "3D" / "MyPart.stp")
    d = detect_source(tmp_path)
    assert d.vendor == "ultralibrarian"
    assert d.symbol_path.name == "2025-02-10_09-58-00.lib"
    assert sorted(p.name for p in d.footprint_paths) == ["VarA.kicad_mod", "VarB.kicad_mod"]
    assert d.model_path.name == "MyPart.stp"


def test_snapeda_fallback_loose_files(tmp_path):
    _touch(tmp_path / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "MyPart.kicad_mod", "(footprint)")
    _touch(tmp_path / "MyPart.step")
    _touch(tmp_path / "datasheet.pdf")
    _touch(tmp_path / "how-to-import.htm")
    d = detect_source(tmp_path)
    assert d.vendor == "snapeda"
    assert d.symbol_path.name == "MyPart.kicad_sym"
    assert [p.name for p in d.footprint_paths] == ["MyPart.kicad_mod"]
    assert d.datasheet_path.name == "datasheet.pdf"


def test_partial_model_only(tmp_path):
    _touch(tmp_path / "MyPart.step")
    d = detect_source(tmp_path)
    assert d.vendor == "partial"
    assert d.model_path.name == "MyPart.step"
    assert d.symbol_path is None
    assert d.footprint_paths == []


def test_model_priority_step_over_stp_over_wrl(tmp_path):
    _touch(tmp_path / "MyPart.kicad_sym", "(kicad_symbol_lib)")
    _touch(tmp_path / "a.wrl")
    _touch(tmp_path / "b.stp")
    _touch(tmp_path / "c.step")
    d = detect_source(tmp_path)
    assert d.model_path.name == "c.step"


def test_nothing_usable_raises(tmp_path):
    _touch(tmp_path / "readme.txt")
    with pytest.raises(IngestError):
        detect_source(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest.fingerprint'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/fingerprint.py`:

```python
"""Fingerprint an unpacked vendor package by its CONTENT, never its origin, and
locate the symbol, footprint(s), 3D model, datasheet, and .dcm. Ported from the
reference importer Steffen-W/Import-LIB-KiCad-Plugin::identify_remote_type,
whose detection order and folder-name capitalization are load-bearing because
they must match real vendor output (spec section 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.ingest.errors import IngestError


@dataclass
class DetectedSource:
    vendor: str
    symbol_path: Path | None = None
    dcm_path: Path | None = None
    footprint_paths: list[Path] = field(default_factory=list)
    model_path: Path | None = None
    datasheet_path: Path | None = None


def _walk(root: Path):
    """Depth-first iterator over every path under root (dirs and files)."""
    for child in sorted(root.iterdir()):
        yield child
        if child.is_dir():
            yield from _walk(child)


def _find(root: Path, suffix: str) -> Path | None:
    """First path whose name ends with `suffix` (matches the reference's
    endswith semantics), searched depth-first for a stable result."""
    for p in _walk(root):
        if p.name.endswith(suffix):
            return p
    return None


def _find_all(root: Path, suffix: str) -> list[Path]:
    return [p for p in _walk(root) if p.is_file() and p.name.endswith(suffix)]


def _find_dir(root: Path, exact_name: str) -> Path | None:
    for p in _walk(root):
        if p.is_dir() and p.name == exact_name:
            return p
    return None


def _first_footprint_lib(root: Path) -> Path | None:
    for p in _walk(root):
        if p.is_dir() and p.name.endswith(".pretty"):
            return p
    return None


def _find_symbol(root: Path) -> Path | None:
    return _find(root, ".kicad_sym") or _find(root, ".lib")


def _find_model(root: Path) -> Path | None:
    return _find(root, ".step") or _find(root, ".stp") or _find(root, ".wrl")


def detect_source(root: Path) -> DetectedSource:
    root = Path(root)
    model = _find_model(root)
    datasheet = _find(root, ".pdf")

    # 1. Octopart: fixed legacy filenames device.lib + device.dcm.
    dev_lib = _find(root, "device.lib")
    dev_dcm = _find(root, "device.dcm")
    if dev_lib is not None and dev_dcm is not None:
        pretty = _first_footprint_lib(root)
        fps = _find_all(pretty, ".kicad_mod") if pretty else _find_all(root, ".kicad_mod")
        return DetectedSource("octopart", dev_lib, dev_dcm, fps, model, datasheet)

    # 2. Samacsys / Component Search Engine: a folder named exactly "KiCad" with a
    #    LOOSE .kicad_mod inside it.
    kicad_dir = _find_dir(root, "KiCad")
    if kicad_dir is not None:
        return DetectedSource(
            "samacsys",
            _find_symbol(kicad_dir),
            _find(kicad_dir, ".dcm"),
            _find_all(kicad_dir, ".kicad_mod"),
            model,
            datasheet,
        )

    # 3. UltraLibrarian: a folder named exactly "KiCAD" (capitalization is the
    #    discriminator from Samacsys) with a real .pretty inside it. The symbol
    #    file is often timestamp-named, so identity is never the filename.
    kicad_dir = _find_dir(root, "KiCAD")
    if kicad_dir is not None:
        pretty = _first_footprint_lib(kicad_dir)
        fps = _find_all(pretty, ".kicad_mod") if pretty else _find_all(kicad_dir, ".kicad_mod")
        return DetectedSource(
            "ultralibrarian",
            _find_symbol(kicad_dir),
            _find(kicad_dir, ".dcm"),
            fps,
            model,
            datasheet,
        )

    # 4. Snapeda / SnapMagic fallback: loose files, no marker folder.
    symbol = _find_symbol(root)
    if symbol is not None:
        fp = _find(root, ".kicad_mod")
        return DetectedSource(
            "snapeda",
            symbol,
            _find(root, ".dcm"),
            [fp] if fp is not None else [],
            model,
            datasheet,
        )

    # 5. Partial: only a 3D model.
    if model is not None:
        return DetectedSource("partial", None, None, [], model, datasheet)

    raise IngestError("unable to identify package: no symbol, footprint, or model found")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_fingerprint.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/fingerprint.py tests/backend/ingest/test_fingerprint.py
git commit -m "Add content fingerprint: detect vendor and locate files by archive content"
```

---

### Task 4: Normalize symbol and footprint through kicad-cli

**Files:**
- Create: `app/backend/stockroom/ingest/convert.py`
- Test: `tests/backend/ingest/test_convert.py`

**Interfaces:**
- Consumes: `KiCadCli.sym_upgrade(src, dst)`, `KiCadCli.fp_upgrade(pretty_dir)` (Task 1), `SymbolLib.load(path).symbol_names`.
- Produces:
  - `normalize_symbol(cli: KiCadCli, src: Path, dcm: Path | None, workdir: Path) -> Path` — copies `src` (and its sibling `.dcm` if given, so kicad-cli merges descriptions) into `workdir`, runs `sym upgrade`, returns the resulting `.kicad_sym` path. Handles legacy `.lib` and already-v10 `.kicad_sym` uniformly (upgrade is idempotent).
  - `read_symbol_names(kicad_sym: Path) -> list[str]` — top-level symbol names from inside the file (never the filename).
  - `normalize_footprint(cli: KiCadCli, src: Path, workdir: Path) -> Path` — copies `src` into a temp `.pretty` under `workdir`, runs `fp upgrade`, returns the upgraded `.kicad_mod` path.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_convert.py`:

```python
import shutil

from tests.backend.conftest import requires_kicad_cli

# requires_kicad_cli is a pytest.mark.skipif; usable as a module-level pytestmark
# so every test here skips cleanly when the binary is absent.
pytestmark = requires_kicad_cli


def _cli():
    from stockroom.kicad.cli import KiCadCli
    return KiCadCli()


def test_normalize_legacy_lib_becomes_kicad_sym(tmp_path, fixtures_dir):
    from stockroom.ingest.convert import normalize_symbol, read_symbol_names
    src = tmp_path / "in.lib"
    shutil.copyfile(fixtures_dir / "legacy.lib", src)
    out = normalize_symbol(_cli(), src, None, tmp_path / "work")
    assert out.suffix == ".kicad_sym"
    names = read_symbol_names(out)
    assert len(names) >= 1


def test_normalize_kicad_sym_passthrough_reads_inner_name(tmp_path, fixtures_dir):
    from stockroom.ingest.convert import normalize_symbol, read_symbol_names
    src = tmp_path / "2025-02-10_09-58-00.kicad_sym"  # timestamp-named on purpose
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", src)
    out = normalize_symbol(_cli(), src, None, tmp_path / "work")
    # name comes from INSIDE the file, not the timestamp filename
    assert "TESTPART" in read_symbol_names(out)


def test_normalize_footprint_upgrades_in_place(tmp_path, fixtures_dir):
    from stockroom.ingest.convert import normalize_footprint
    from stockroom.kicad.footprint import Footprint
    src = tmp_path / "old.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", src)
    out = normalize_footprint(_cli(), src, tmp_path / "work")
    assert out.suffix == ".kicad_mod"
    assert Footprint.load(out).name  # parseable, named
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_convert.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest.convert'` (or SKIP if kicad-cli absent; must run on WSL).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/convert.py`:

```python
"""Normalize incoming vendor symbol/footprint files to current KiCad V10 format
through KiCad's own tooling (spec section 5, stage 2). Legacy .lib and foreign
formats are a standard input, not an edge case. Incoming files are re-serialized
freely here; byte preservation applies only to the TARGET library files, which
are written later by the M2 placement primitives."""

from __future__ import annotations

import shutil
from pathlib import Path

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib


def normalize_symbol(cli: KiCadCli, src: Path, dcm: Path | None, workdir: Path) -> Path:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    if src.suffix == ".kicad_sym":
        # already a native symbol library: copy into the sandbox and use as-is
        # (the reference importer loads .kicad_sym directly, upgrading only .lib).
        dst = workdir / src.name
        shutil.copyfile(src, dst)
        return dst
    # legacy .lib or foreign format: upgrade via kicad-cli. Keep the source and
    # the output on distinct paths (never src == dst). A sibling .dcm named like
    # the library is copied next to the source so kicad-cli merges descriptions.
    in_dir = workdir / "in"
    in_dir.mkdir(parents=True, exist_ok=True)
    staged_src = in_dir / src.name
    shutil.copyfile(src, staged_src)
    if dcm is not None:
        shutil.copyfile(dcm, in_dir / (staged_src.stem + ".dcm"))
    out = workdir / "normalized.kicad_sym"
    cli.sym_upgrade(staged_src, out)
    return out


def read_symbol_names(kicad_sym: Path) -> list[str]:
    return SymbolLib.load(kicad_sym).symbol_names


def normalize_footprint(cli: KiCadCli, src: Path, workdir: Path) -> Path:
    workdir = Path(workdir)
    pretty = workdir / "normalize.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    dst = pretty / src.name
    shutil.copyfile(src, dst)
    cli.fp_upgrade(pretty)
    return dst
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_convert.py -v`
Expected: PASS (3 tests) on WSL.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/convert.py tests/backend/ingest/test_convert.py
git commit -m "Add ingest convert: normalize symbol/footprint via kicad-cli, read inner symbol name"
```

---

### Task 5: Name and category proposals

**Files:**
- Create: `app/backend/stockroom/ingest/naming.py`
- Test: `tests/backend/ingest/test_naming.py`

**Interfaces:**
- Consumes: `stockroom.model.category.CATEGORIES`, `slugify`.
- Produces:
  - `propose_entry_name(symbol_name: str, mpn: str = "") -> str` — a KiCad-safe library entry name; prefers a non-empty `mpn`, else the symbol name; strips characters KiCad forbids in a lib_id (`{}` and whitespace collapse), never empty (falls back to `"Part"`).
  - `propose_display_name(symbol_name: str, mpn: str = "") -> str` — human label; prefers `mpn` else `symbol_name`.
  - `propose_category(text: str) -> str` — keyword heuristic over lowercased `text` (symbol name + keywords); returns a member of `CATEGORIES`, defaulting to `"Other"`.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_naming.py`:

```python
from stockroom.ingest.naming import (
    propose_category,
    propose_display_name,
    propose_entry_name,
)
from stockroom.model.category import CATEGORIES


def test_entry_name_prefers_mpn():
    assert propose_entry_name("SYM_TIMESTAMP", "TPS62130RGTR") == "TPS62130RGTR"


def test_entry_name_falls_back_to_symbol_name():
    assert propose_entry_name("LM358", "") == "LM358"


def test_entry_name_sanitizes_forbidden_chars():
    out = propose_entry_name("weird {name} here", "")
    assert "{" not in out and "}" not in out and " " not in out


def test_entry_name_never_empty():
    assert propose_entry_name("", "") == "Part"


def test_display_name_prefers_mpn():
    assert propose_display_name("SYM", "MPN123") == "MPN123"


def test_category_keyword_heuristic():
    assert propose_category("0.1uF ceramic capacitor X7R") == "Capacitors"
    assert propose_category("USB Type-C connector receptacle") == "Connectors"
    assert propose_category("LDO voltage regulator IC") == "ICs"
    assert propose_category("something with no hint") == "Other"


def test_category_result_is_always_valid():
    assert propose_category("anything") in CATEGORIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_naming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest.naming'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/naming.py`:

```python
"""Propose an entry name, display name, and category for a staged part (spec
section 5, stage 3). Proposals only; the user confirms or overrides in review."""

from __future__ import annotations

import re

# Keyword -> category, checked in order; first hit wins. Ordered so specific
# terms (regulator, oscillator) are not shadowed by generic ones.
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("resistor", "Resistors"),
    ("capacitor", "Capacitors"),
    ("inductor", "Inductors"),
    ("ferrite", "Inductors"),
    ("crystal", "Crystals & Oscillators"),
    ("oscillator", "Crystals & Oscillators"),
    ("resonator", "Crystals & Oscillators"),
    ("diode", "Diodes"),
    ("led", "Diodes"),
    ("transistor", "Transistors"),
    ("mosfet", "Transistors"),
    ("connector", "Connectors"),
    ("receptacle", "Connectors"),
    ("header", "Connectors"),
    ("switch", "Switches"),
    ("button", "Switches"),
    ("relay", "Electromechanical"),
    ("motor", "Electromechanical"),
    ("buzzer", "Electromechanical"),
    ("sensor", "Sensors"),
    ("accelerometer", "Sensors"),
    ("gyroscope", "Sensors"),
    ("module", "Modules"),
    ("regulator", "ICs"),
    ("microcontroller", "ICs"),
    ("amplifier", "ICs"),
    ("ic", "ICs"),
)

_FORBIDDEN = re.compile(r"[{}\s]+")


def _sanitize(name: str) -> str:
    return _FORBIDDEN.sub("_", name).strip("_")


def propose_entry_name(symbol_name: str, mpn: str = "") -> str:
    base = mpn.strip() or symbol_name.strip()
    cleaned = _sanitize(base)
    return cleaned or "Part"


def propose_display_name(symbol_name: str, mpn: str = "") -> str:
    return mpn.strip() or symbol_name.strip() or "Part"


def propose_category(text: str) -> str:
    low = text.lower()
    for keyword, category in _CATEGORY_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", low):
            return category
    return "Other"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_naming.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/naming.py tests/backend/ingest/test_naming.py
git commit -m "Add ingest naming: entry-name/display-name/category proposals"
```

---

### Task 6: StagingCandidate and its StagedPart projection

**Files:**
- Create: `app/backend/stockroom/ingest/staging.py`
- Test: `tests/backend/ingest/test_staging.py`

**Interfaces:**
- Consumes: `stockroom.mutation.library_ops.StagedPart`, `stockroom.model.part.Provenance`, `Datasheet`.
- Produces:
  - `StagingCandidate` dataclass (fields below).
  - `StagingCandidate.chosen_footprint -> Path | None`.
  - `StagingCandidate.to_staged_part() -> StagedPart` — projects a finalized candidate onto the M2 seam; raises `IngestError` if it has no symbol or no footprint.

Fields:
```
vendor: str
symbol_lib_path: Path | None
symbol_name: str
footprint_variants: list[Path]
chosen_footprint_index: int = 0
model_path: Path | None = None
datasheet_path: Path | None = None
display_name: str = ""
entry_name: str = ""
category: str = "Other"
mpn: str = ""
manufacturer: str = ""
description: str = ""
tags: list[str] = field(default_factory=list)
gaps: list[str] = field(default_factory=list)
provenance: Provenance | None = None
```

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_staging.py`:

```python
from pathlib import Path

import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.staging import StagingCandidate


def _candidate(**kw):
    base = dict(
        vendor="snapeda",
        symbol_lib_path=Path("/tmp/sym.kicad_sym"),
        symbol_name="TESTPART",
        footprint_variants=[Path("/tmp/a.kicad_mod"), Path("/tmp/b.kicad_mod")],
        entry_name="TPS62130RGTR",
        display_name="TPS62130 buck",
        category="ICs",
        mpn="TPS62130RGTR",
    )
    base.update(kw)
    return StagingCandidate(**base)


def test_chosen_footprint_defaults_to_first():
    c = _candidate()
    assert c.chosen_footprint == Path("/tmp/a.kicad_mod")


def test_chosen_footprint_honors_index():
    c = _candidate(chosen_footprint_index=1)
    assert c.chosen_footprint == Path("/tmp/b.kicad_mod")


def test_to_staged_part_maps_all_fields():
    c = _candidate(model_path=Path("/tmp/m.step"), datasheet_path=Path("/tmp/d.pdf"))
    sp = c.to_staged_part()
    assert sp.display_name == "TPS62130 buck"
    assert sp.category == "ICs"
    assert sp.symbol_source == Path("/tmp/sym.kicad_sym")
    assert sp.symbol_source_name == "TESTPART"
    assert sp.footprint_source == Path("/tmp/a.kicad_mod")
    assert sp.entry_name == "TPS62130RGTR"
    assert sp.model_source == Path("/tmp/m.step")
    assert sp.datasheet_source == Path("/tmp/d.pdf")


def test_to_staged_part_rejects_missing_symbol():
    c = _candidate(symbol_lib_path=None)
    with pytest.raises(IngestError):
        c.to_staged_part()


def test_to_staged_part_rejects_missing_footprint():
    c = _candidate(footprint_variants=[])
    with pytest.raises(IngestError):
        c.to_staged_part()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_staging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest.staging'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/staging.py`:

```python
"""A review card per candidate part: the converted files, proposed name and
category, honestly-flagged gaps, and provenance. Projects onto the M2
StagedPart seam once the user finalizes it (spec section 5, stages 3 and 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.model.part import Datasheet, Provenance
from stockroom.mutation.library_ops import StagedPart


@dataclass
class StagingCandidate:
    vendor: str
    symbol_lib_path: Path | None
    symbol_name: str
    footprint_variants: list[Path]
    chosen_footprint_index: int = 0
    model_path: Path | None = None
    datasheet_path: Path | None = None
    display_name: str = ""
    entry_name: str = ""
    category: str = "Other"
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    provenance: Provenance | None = None

    @property
    def chosen_footprint(self) -> Path | None:
        if not self.footprint_variants:
            return None
        idx = self.chosen_footprint_index
        if idx < 0 or idx >= len(self.footprint_variants):
            raise IngestError(f"footprint index {idx} out of range")
        return self.footprint_variants[idx]

    def to_staged_part(self) -> StagedPart:
        if self.symbol_lib_path is None:
            raise IngestError("candidate has no symbol; cannot stage")
        fp = self.chosen_footprint
        if fp is None:
            raise IngestError("candidate has no footprint; cannot stage")
        datasheet_meta = None
        if self.provenance is not None and self.provenance.source_url:
            datasheet_meta = Datasheet(source_url=self.provenance.source_url)
        return StagedPart(
            display_name=self.display_name,
            category=self.category,
            mpn=self.mpn,
            manufacturer=self.manufacturer,
            description=self.description,
            tags=list(self.tags),
            symbol_source=self.symbol_lib_path,
            symbol_source_name=self.symbol_name,
            footprint_source=fp,
            entry_name=self.entry_name,
            model_source=self.model_path,
            datasheet_source=self.datasheet_path,
            provenance=self.provenance,
            datasheet_meta=datasheet_meta,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_staging.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/staging.py tests/backend/ingest/test_staging.py
git commit -m "Add StagingCandidate and its projection onto the StagedPart seam"
```

---

### Task 7: Build candidates from a detected source

**Files:**
- Modify: `app/backend/stockroom/ingest/staging.py`
- Test: `tests/backend/ingest/test_staging.py`

**Interfaces:**
- Consumes: `DetectedSource` (Task 3), `normalize_symbol`/`read_symbol_names`/`normalize_footprint` (Task 4), `propose_*` (Task 5), `SymbolLib`, `Provenance`.
- Produces: `build_candidates(cli: KiCadCli, detected: DetectedSource, workdir: Path, provenance: Provenance | None = None) -> list[StagingCandidate]` — normalizes the symbol and each footprint variant, reads the inner symbol name(s), pulls description/keywords from the symbol properties, proposes name and category, records gaps, and returns one candidate per top-level symbol. A `partial` (model-only) source returns a single candidate with `symbol_lib_path=None` and a gap note.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/ingest/test_staging.py`:

```python
import shutil

from tests.backend.conftest import requires_kicad_cli
from stockroom.ingest.fingerprint import DetectedSource
from stockroom.ingest.staging import build_candidates
from stockroom.model.part import Provenance


def _cli():
    from stockroom.kicad.cli import KiCadCli
    return KiCadCli()


@requires_kicad_cli
def test_build_candidates_from_snapeda(tmp_path, fixtures_dir):
    sym = tmp_path / "MyPart.kicad_sym"
    fp = tmp_path / "MyPart.kicad_mod"
    model = tmp_path / "MyPart.step"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp)
    model.write_bytes(b"ISO-10303-21;\n")
    detected = DetectedSource("snapeda", sym, None, [fp], model, None)
    prov = Provenance(source="snapeda")
    cands = build_candidates(_cli(), detected, tmp_path / "work", prov)
    assert len(cands) == 1
    c = cands[0]
    assert c.symbol_name == "TESTPART"
    assert c.entry_name == "TESTPART"
    assert c.model_path == model
    assert c.gaps == []  # symbol, footprint, and model all present


@requires_kicad_cli
def test_build_candidates_flags_missing_model(tmp_path, fixtures_dir):
    sym = tmp_path / "MyPart.kicad_sym"
    fp = tmp_path / "MyPart.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp)
    detected = DetectedSource("snapeda", sym, None, [fp], None, None)
    [c] = build_candidates(_cli(), detected, tmp_path / "work")
    assert any("3D model" in g for g in c.gaps)


def test_build_candidates_partial_is_model_only():
    model = Path("/tmp/only.step")
    detected = DetectedSource("partial", None, None, [], model, None)
    # partial does not need kicad-cli; pass None safely.
    [c] = build_candidates(None, detected, Path("/tmp"))
    assert c.symbol_lib_path is None
    assert c.model_path == model
    assert any("only a 3D model" in g for g in c.gaps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_staging.py -k build_candidates -v`
Expected: FAIL with `ImportError: cannot import name 'build_candidates'`.

- [ ] **Step 3: Write minimal implementation**

Append to `app/backend/stockroom/ingest/staging.py` (add imports at top: `from stockroom.ingest.convert import normalize_footprint, normalize_symbol, read_symbol_names`, `from stockroom.ingest.fingerprint import DetectedSource`, `from stockroom.ingest.naming import propose_category, propose_display_name, propose_entry_name`, `from stockroom.kicad.cli import KiCadCli`, `from stockroom.kicad.symbol_lib import SymbolLib`):

```python
def _symbol_metadata(sym_lib: SymbolLib, name: str) -> tuple[str, list[str]]:
    sym = sym_lib.get_symbol(name)
    description = sym.get_property("Description") or ""
    keywords = sym.get_property("ki_keywords") or ""
    tags = [t for t in keywords.split() if t]
    return description, tags


def build_candidates(
    cli: KiCadCli | None,
    detected: DetectedSource,
    workdir: Path,
    provenance: Provenance | None = None,
) -> list[StagingCandidate]:
    workdir = Path(workdir)

    if detected.vendor == "partial" or detected.symbol_path is None:
        return [
            StagingCandidate(
                vendor=detected.vendor,
                symbol_lib_path=None,
                symbol_name="",
                footprint_variants=[],
                model_path=detected.model_path,
                datasheet_path=detected.datasheet_path,
                gaps=["package contains only a 3D model; attach it to an existing part"],
                provenance=provenance,
            )
        ]

    sym_workdir = workdir / "symbol"
    normalized_sym = normalize_symbol(cli, detected.symbol_path, detected.dcm_path, sym_workdir)
    sym_lib = SymbolLib.load(normalized_sym)
    names = read_symbol_names(normalized_sym)
    if not names:
        raise IngestError(f"no symbol found inside {detected.symbol_path.name}")

    variants: list[Path] = []
    for i, fp in enumerate(detected.footprint_paths):
        variants.append(normalize_footprint(cli, fp, workdir / f"fp{i}"))

    candidates: list[StagingCandidate] = []
    for name in names:
        description, tags = _symbol_metadata(sym_lib, name)
        gaps: list[str] = []
        if not variants:
            gaps.append("no footprint in this package")
        if detected.model_path is None:
            gaps.append("no 3D model in this package")
        if detected.datasheet_path is None:
            gaps.append("no datasheet in this package")
        candidates.append(
            StagingCandidate(
                vendor=detected.vendor,
                symbol_lib_path=normalized_sym,
                symbol_name=name,
                footprint_variants=list(variants),
                model_path=detected.model_path,
                datasheet_path=detected.datasheet_path,
                display_name=propose_display_name(name),
                entry_name=propose_entry_name(name),
                category=propose_category(f"{name} {description} {' '.join(tags)}"),
                description=description,
                tags=tags,
                gaps=gaps,
                provenance=provenance,
            )
        )
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_staging.py -v`
Expected: PASS (all staging tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/staging.py tests/backend/ingest/test_staging.py
git commit -m "Build staging candidates from a detected source (normalize, name, flag gaps)"
```

---

### Task 8: `add_part` ensures the category symbol lib exists

**Files:**
- Modify: `app/backend/stockroom/mutation/library_ops.py`
- Test: `tests/backend/ingest/test_ensure_category_lib.py`

**Interfaces:**
- Consumes: `create_empty_symbol_lib(cli, dst)`, `ensure_footprint_lib(dir)`, `KiCadCli`.
- Produces: `LibraryOps.__init__(self, profile, repo, cli=None)`; `add_part` creates the category symbol lib (via `create_empty_symbol_lib`) inside the transaction when it is missing and a `cli` is available, tracking the new file so it is committed atomically. Backward compatible: existing callers that pre-create the lib pass no `cli` and see no behavior change.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_ensure_category_lib.py`:

```python
import shutil

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.mutation.library_ops import LibraryOps, StagedPart
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo
from tests.backend.conftest import requires_kicad_cli

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
    requires_kicad_cli,
]


def _staged(tmp_path, fixtures_dir):
    sym = tmp_path / "one_symbol.kicad_sym"
    fp = tmp_path / "one_footprint.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp)
    return StagedPart(
        display_name="Part",
        category="Diodes",
        symbol_source=sym,
        symbol_source_name="TESTPART",
        footprint_source=fp,
        entry_name="MYDIODE",
    )


def test_add_part_creates_missing_category_lib(tmp_path, fixtures_dir):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    profile.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    # Deliberately do NOT pre-create the Diodes symbol lib.
    ops = LibraryOps(profile, repo, cli=KiCadCli())
    ops.add_part(_staged(tmp_path, fixtures_dir))
    sym_lib_path = profile.library.symbol_lib_path("Diodes")
    assert sym_lib_path.exists()
    assert "MYDIODE" in SymbolLib.load(sym_lib_path).symbol_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_ensure_category_lib.py -v`
Expected: FAIL — `add_part` currently raises because `SymbolLib.load` cannot open the missing lib (or `TypeError` on the unexpected `cli` kwarg).

- [ ] **Step 3: Write minimal implementation**

In `app/backend/stockroom/mutation/library_ops.py`:

Add imports near the top:

```python
from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
```

Change the constructor:

```python
    def __init__(self, profile: Profile, repo: GitRepo, cli=None):
        self.profile = profile
        self.repo = repo
        self.lib = profile.library
        self.cli = cli
```

In `add_part`, replace exactly this existing opening of the transaction block:

```python
        with Transaction(self.repo) as txn:
            # 1. merge the symbol (renamed to entry_name) into the category lib
            merge_symbol_into_lib(
```

with:

```python
        with Transaction(self.repo) as txn:
            # 0. ensure the category libraries exist (idempotent); a freshly
            # created empty symbol lib is tracked so it commits atomically.
            ensure_footprint_lib(pretty_dir)
            if not sym_lib_path.exists():
                if self.cli is None:
                    raise ValueError(
                        f"category symbol library {sym_lib_path.name} is missing and "
                        "no kicad-cli was provided to create it"
                    )
                create_empty_symbol_lib(self.cli, sym_lib_path)
                txn.track(sym_lib_path)

            # 1. merge the symbol (renamed to entry_name) into the category lib
            merge_symbol_into_lib(
```

Everything below (the `txn.track(sym_lib_path)` after the merge, and steps 2 through 6) stays unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_ensure_category_lib.py -v`
Then the M2 regression: `uv run pytest tests/backend/mutation/test_library_ops.py -v`
Expected: both PASS (the existing library_ops tests pre-create the lib, so the new branch is a no-op for them).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/mutation/library_ops.py tests/backend/ingest/test_ensure_category_lib.py
git commit -m "add_part ensures the category symbol lib exists inside the transaction"
```

---

### Task 9: LCSC path via easyeda2kicad

**Files:**
- Create: `app/backend/stockroom/ingest/lcsc.py`
- Modify: `pyproject.toml` (add `easyeda2kicad` to `dependencies`)
- Modify: `uv.lock` (regenerated by `uv lock`)
- Test: `tests/backend/ingest/test_lcsc.py`

**Interfaces:**
- Consumes: `DetectedSource` (Task 3), `subprocess`.
- Produces:
  - `is_lcsc_id(text: str) -> bool` — matches `^C\d+$` (case-insensitive on the leading C).
  - `fetch_lcsc(lcsc_id: str, workdir: Path, runner=None) -> DetectedSource` — runs `easyeda2kicad --full --lcsc_id=<id> --output <workdir>/lib --overwrite`, then locates `<workdir>/lib.kicad_sym`, the single `.kicad_mod` in `<workdir>/lib.pretty/`, and the preferred model in `<workdir>/lib.3dshapes/` (`.step` over `.wrl`). `runner` defaults to a thin `subprocess.run` wrapper and is injectable for tests. Raises `IngestError` on a bad id, a runner failure, or missing outputs.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_lcsc.py`:

```python
import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.lcsc import fetch_lcsc, is_lcsc_id


def test_is_lcsc_id():
    assert is_lcsc_id("C2040")
    assert is_lcsc_id("c2040")
    assert not is_lcsc_id("TPS62130")
    assert not is_lcsc_id("C")
    assert not is_lcsc_id("")


def test_fetch_lcsc_invalid_id_raises(tmp_path):
    with pytest.raises(IngestError):
        fetch_lcsc("not-an-id", tmp_path)


def test_fetch_lcsc_locates_outputs(tmp_path):
    # A fake runner that writes the files easyeda2kicad would produce.
    def fake_runner(cmd):
        # cmd is the arg list; find the --output base
        base = None
        for a in cmd:
            if a.startswith("--output"):
                base = a.split("=", 1)[1] if "=" in a else None
        if base is None:
            base = cmd[cmd.index("--output") + 1]
        from pathlib import Path
        base = Path(base)
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".kicad_sym").write_text("(kicad_symbol_lib)")
        pretty = Path(str(base) + ".pretty")
        pretty.mkdir(parents=True, exist_ok=True)
        (pretty / "C2040.kicad_mod").write_text("(footprint)")
        shapes = Path(str(base) + ".3dshapes")
        shapes.mkdir(parents=True, exist_ok=True)
        (shapes / "C2040.wrl").write_text("wrl")
        (shapes / "C2040.step").write_text("step")

    d = fetch_lcsc("C2040", tmp_path, runner=fake_runner)
    assert d.vendor == "lcsc"
    assert d.symbol_path.suffix == ".kicad_sym"
    assert d.footprint_paths[0].name == "C2040.kicad_mod"
    assert d.model_path.name == "C2040.step"  # step preferred over wrl


def test_fetch_lcsc_runner_failure_raises(tmp_path):
    def failing_runner(cmd):
        raise RuntimeError("network down")

    with pytest.raises(IngestError):
        fetch_lcsc("C2040", tmp_path, runner=failing_runner)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_lcsc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest.lcsc'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/lcsc.py`:

```python
"""LCSC part-number ingestion. There is no KiCad zip for LCSC/EasyEDA, so the
ecosystem standard is an API fetch and convert keyed on the Cxxxxx id. We shell
out to easyeda2kicad (kept at arm's length as a subprocess so its AGPL license
does not reach Stockroom's code) and feed the produced symbol, footprint, and 3D
model into the same staging path (spec section 5)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import DetectedSource

_LCSC_RE = re.compile(r"^C\d+$", re.IGNORECASE)


def is_lcsc_id(text: str) -> bool:
    return bool(_LCSC_RE.match(text.strip())) if text else False


def _default_runner(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise IngestError(f"easyeda2kicad failed: {proc.stderr.strip() or proc.stdout.strip()}")


def fetch_lcsc(lcsc_id: str, workdir: Path, runner=None) -> DetectedSource:
    if not is_lcsc_id(lcsc_id):
        raise IngestError(f"not an LCSC part number: {lcsc_id!r}")
    runner = runner or _default_runner
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    base = workdir / "lib"
    cmd = [
        "easyeda2kicad",
        "--full",
        f"--lcsc_id={lcsc_id.upper()}",
        "--output",
        str(base),
        "--overwrite",
    ]
    try:
        runner(cmd)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(f"easyeda2kicad invocation failed: {exc}") from exc

    symbol = base.with_suffix(".kicad_sym")
    if not symbol.exists():
        raise IngestError(f"easyeda2kicad produced no symbol for {lcsc_id}")
    pretty = Path(str(base) + ".pretty")
    footprints = sorted(pretty.glob("*.kicad_mod")) if pretty.is_dir() else []
    shapes = Path(str(base) + ".3dshapes")
    model = None
    if shapes.is_dir():
        step = sorted(shapes.glob("*.step"))
        wrl = sorted(shapes.glob("*.wrl"))
        model = (step or wrl or [None])[0]
    return DetectedSource(
        vendor="lcsc",
        symbol_path=symbol,
        dcm_path=None,
        footprint_paths=footprints,
        model_path=model,
        datasheet_path=None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_lcsc.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the dependency and lock**

Add `easyeda2kicad` to `pyproject.toml`:

```toml
dependencies = ["easyeda2kicad>=1.0.1"]
```

Then regenerate the lock:

Run: `uv lock`
Expected: `uv.lock` updated with easyeda2kicad and its transitive deps. Then `uv run pytest tests/backend/ingest/test_lcsc.py -v` still PASS.

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/ingest/lcsc.py tests/backend/ingest/test_lcsc.py pyproject.toml uv.lock
git commit -m "Add LCSC ingestion path via easyeda2kicad subprocess"
```

---

### Task 10: Pipeline inspect (Inspect + Convert + Stage)

**Files:**
- Create: `app/backend/stockroom/ingest/pipeline.py`
- Test: `tests/backend/ingest/test_pipeline.py`

**Interfaces:**
- Consumes: `unpack_inputs` (Task 2), `detect_source` (Task 3), `build_candidates` (Task 7), `fetch_lcsc` (Task 9), `Provenance`, `sha256_of`.
- Produces:
  - `IngestPipeline(profile: Profile, repo: GitRepo, cli: KiCadCli)`.
  - `IngestPipeline.inspect(self, inputs: list[Path] = (), lcsc_ids: list[str] = (), workdir: Path | None = None) -> list[StagingCandidate]` — unpacks and fingerprints each package input, fetches each LCSC id, and returns the flattened candidate list with provenance (source vendor, `original_zip_sha256`, source id) attached. A `workdir` is created under a temp dir when not supplied and kept for the lifetime of the returned candidates (their file paths point into it).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/test_pipeline.py`:

```python
import shutil
import zipfile

import pytest

from stockroom.ingest.pipeline import IngestPipeline
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo
from tests.backend.conftest import requires_kicad_cli

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
    requires_kicad_cli,
]


def _pipeline(tmp_path):
    from stockroom.kicad.cli import KiCadCli
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    return IngestPipeline(profile, repo, KiCadCli())


def _snapeda_zip(tmp_path, fixtures_dir, name="part.zip"):
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(fixtures_dir / "one_symbol.kicad_sym", "MyPart.kicad_sym")
        zf.write(fixtures_dir / "one_footprint.kicad_mod", "MyPart.kicad_mod")
        zf.writestr("MyPart.step", "ISO-10303-21;\n")
    return z


def test_inspect_a_snapeda_zip(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    cands = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    assert len(cands) == 1
    c = cands[0]
    assert c.vendor == "snapeda"
    assert c.symbol_name == "TESTPART"
    assert c.provenance.original_zip_sha256  # recorded


def test_inspect_multiple_zips_at_once(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z1 = _snapeda_zip(tmp_path, fixtures_dir, "a.zip")
    z2 = _snapeda_zip(tmp_path, fixtures_dir, "b.zip")
    cands = pipe.inspect(inputs=[z1, z2], workdir=tmp_path / "work")
    assert len(cands) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k inspect -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.ingest.pipeline'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/ingest/pipeline.py`:

```python
"""The ingestion pipeline: Inspect (unpack + fingerprint) and Convert + Stage
produce review-ready candidates; Commit runs one atomic, zero-trace transaction
through the M2 add_part seam. Partial (3D-only) packages attach to an existing
part (spec section 5)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from stockroom.ingest.fingerprint import detect_source
from stockroom.ingest.lcsc import fetch_lcsc
from stockroom.ingest.sandbox import unpack_inputs
from stockroom.ingest.staging import StagingCandidate, build_candidates
from stockroom.kicad.cli import KiCadCli
from stockroom.model.part import Provenance
from stockroom.mutation.library_ops import LibraryOps
from stockroom.store.profile import Profile
from stockroom.vcs.repo import GitRepo


class IngestPipeline:
    def __init__(self, profile: Profile, repo: GitRepo, cli: KiCadCli):
        self.profile = profile
        self.repo = repo
        self.cli = cli
        self.ops = LibraryOps(profile, repo, cli=cli)

    def inspect(
        self,
        inputs: list[Path] = (),
        lcsc_ids: list[str] = (),
        workdir: Path | None = None,
    ) -> list[StagingCandidate]:
        workdir = Path(workdir) if workdir is not None else Path(tempfile.mkdtemp(prefix="sr-ingest-"))
        workdir.mkdir(parents=True, exist_ok=True)
        candidates: list[StagingCandidate] = []

        unpacked = unpack_inputs(list(inputs), workdir / "unpack")
        for u in unpacked:
            detected = detect_source(u.root)
            prov = Provenance(
                source=detected.vendor,
                original_zip_sha256=u.sha256,
            )
            stage_dir = workdir / "stage" / u.root.name
            candidates.extend(build_candidates(self.cli, detected, stage_dir, prov))

        for i, lcsc_id in enumerate(lcsc_ids):
            fetch_dir = workdir / "lcsc" / str(i)
            detected = fetch_lcsc(lcsc_id, fetch_dir, runner=None)
            prov = Provenance(source="lcsc", source_url="")
            stage_dir = workdir / "stage" / f"lcsc-{i}"
            for c in build_candidates(self.cli, detected, stage_dir, prov):
                c.mpn = c.mpn or lcsc_id.upper()
                candidates.append(c)

        return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k inspect -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/pipeline.py tests/backend/ingest/test_pipeline.py
git commit -m "Add IngestPipeline.inspect: unpack, fingerprint, and stage candidates"
```

---

### Task 11: Pipeline commit (atomic, zero trace)

**Files:**
- Modify: `app/backend/stockroom/ingest/pipeline.py`
- Test: `tests/backend/ingest/test_pipeline.py`

**Interfaces:**
- Consumes: `StagingCandidate.to_staged_part()` (Task 6), `LibraryOps.add_part` (Task 8), `GitRepo.head`.
- Produces: `IngestPipeline.commit(self, candidate: StagingCandidate) -> PartRecord` — projects the finalized candidate onto a `StagedPart` and calls `add_part` (one atomic transaction; category libs ensured; zero trace on failure).

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/ingest/test_pipeline.py`:

```python
from stockroom.kicad.symbol_lib import SymbolLib


def test_commit_lands_the_part_in_the_category_lib(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    record = pipe.commit(c)
    assert record.category == "ICs"
    sym_lib = SymbolLib.load(pipe.profile.library.symbol_lib_path("ICs"))
    assert "TESTPART" in sym_lib.symbol_names
    fp = pipe.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert fp.exists()
    json_path = pipe.profile.library.parts_dir / f"{record.id}.json"
    assert json_path.exists()


def test_failed_commit_leaves_zero_trace(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    head_before = pipe.repo.head()
    # Corrupt the symbol source so add_part's merge fails mid-transaction.
    c.symbol_lib_path.write_text("(kicad_symbol_lib (this is broken")
    with pytest.raises(Exception):
        pipe.commit(c)
    assert pipe.repo.head() == head_before  # no commit
    # the category lib was never created/left behind
    assert not (pipe.profile.library.parts_dir / f"testpart.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k commit -v`
Expected: FAIL with `AttributeError: 'IngestPipeline' object has no attribute 'commit'`.

- [ ] **Step 3: Write minimal implementation**

Append to `IngestPipeline` in `app/backend/stockroom/ingest/pipeline.py` (add import `from stockroom.model.part import PartRecord` at top):

```python
    def commit(self, candidate: StagingCandidate) -> PartRecord:
        staged = candidate.to_staged_part()
        return self.ops.add_part(staged)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k commit -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/pipeline.py tests/backend/ingest/test_pipeline.py
git commit -m "Add IngestPipeline.commit: atomic zero-trace add via the M2 seam"
```

---

### Task 12: Pipeline attach_model (Partial packages)

**Files:**
- Modify: `app/backend/stockroom/ingest/pipeline.py`
- Test: `tests/backend/ingest/test_pipeline.py`

**Interfaces:**
- Consumes: `LibraryOps.load_record`, `Transaction`, `Footprint.set_model_path`, `ModelRef`, `StagingCandidate.model_path`.
- Produces: `IngestPipeline.attach_model(self, part_id: str, candidate: StagingCandidate) -> PartRecord` — copies the candidate's 3D model into the profile `models/`, writes the `(model ${SR_LIB}/models/...)` link on the existing part's footprint, updates the record's `model`, and commits atomically. Raises `IngestError` if the candidate has no model or the part has no footprint on disk.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/ingest/test_pipeline.py`:

```python
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.footprint import Footprint


def test_attach_model_to_existing_part(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    # Commit WITHOUT a model.
    c.model_path = None
    record = pipe.commit(c)

    model = tmp_path / "late.step"
    model.write_bytes(b"ISO-10303-21;\n")
    partial = StagingCandidate(
        vendor="partial", symbol_lib_path=None, symbol_name="",
        footprint_variants=[], model_path=model,
    )
    updated = pipe.attach_model(record.id, partial)
    assert updated.model is not None
    fp_path = pipe.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert "models/" in (Footprint.load(fp_path).model_path or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k attach_model -v`
Expected: FAIL with `AttributeError: 'IngestPipeline' object has no attribute 'attach_model'`.

- [ ] **Step 3: Write minimal implementation**

Append to `IngestPipeline` (add imports at top: `import shutil`, `from stockroom.ingest.errors import IngestError`, `from stockroom.kicad.footprint import Footprint`, `from stockroom.model.part import ModelRef`, `from stockroom.mutation.transaction import Transaction`):

```python
    def attach_model(self, part_id: str, candidate: StagingCandidate) -> PartRecord:
        if candidate.model_path is None:
            raise IngestError("candidate has no 3D model to attach")
        record = self.ops.load_record(part_id)
        if record.footprint is None:
            raise IngestError(f"part {part_id} has no footprint to link a model to")
        lib = self.profile.library
        fp_path = lib.footprint_lib_path(record.category) / f"{record.footprint.name}.kicad_mod"
        if not fp_path.exists():
            raise IngestError(f"footprint file missing for {part_id}: {fp_path.name}")
        lib.models_dir.mkdir(parents=True, exist_ok=True)
        model_name = f"{record.footprint.name}{Path(candidate.model_path).suffix}"
        model_dst = lib.models_dir / model_name
        json_path = lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            shutil.copyfile(candidate.model_path, model_dst)
            txn.track(model_dst)
            fp = Footprint.load(fp_path)
            fp.set_model_path(f"${{SR_LIB}}/models/{model_name}")
            fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
            txn.track(fp_path)
            record.model = ModelRef(file=f"models/{model_name}")
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Attach 3D model to {part_id}")
        return record
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k attach_model -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/ingest/pipeline.py tests/backend/ingest/test_pipeline.py
git commit -m "Add IngestPipeline.attach_model for Partial (3D-only) packages"
```

---

### Task 13: Vendor-layout fixtures and the end-to-end integration test

**Files:**
- Create: `tests/backend/ingest/vendor_fixtures.py`
- Test: `tests/backend/ingest/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `make_vendor_zip(dst_zip: Path, vendor: str, fixtures_dir: Path) -> Path` — builds a synthetic zip in each real vendor layout (`octopart`, `samacsys`, `ultralibrarian`, `snapeda`) using the repo's `one_symbol.kicad_sym`, `legacy.lib`, and `one_footprint.kicad_mod` fixtures, so detection is exercised against true directory shapes. A parametrized test drives `inspect` then `commit` for each layout and asserts the part lands byte-preservingly.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/ingest/vendor_fixtures.py`:

```python
"""Build synthetic vendor-layout zips from the repo's KiCad fixtures so the
ingestion pipeline is tested against real directory shapes, not mocks."""

from __future__ import annotations

import zipfile
from pathlib import Path


def make_vendor_zip(dst_zip: Path, vendor: str, fixtures_dir: Path) -> Path:
    sym = (fixtures_dir / "one_symbol.kicad_sym").read_bytes()
    legacy = (fixtures_dir / "legacy.lib").read_bytes()
    fp = (fixtures_dir / "one_footprint.kicad_mod").read_bytes()
    step = b"ISO-10303-21;\n"
    with zipfile.ZipFile(dst_zip, "w") as zf:
        if vendor == "octopart":
            zf.writestr("device.lib", legacy)
            zf.writestr("device.dcm", "EESchema-DOCLIB  Version 2.0\n#\n#End Doc Library\n")
            zf.writestr("MyPart.pretty/MyPart.kicad_mod", fp)
            zf.writestr("MyPart.step", step)
        elif vendor == "samacsys":
            zf.writestr("KiCad/MyPart.kicad_sym", sym)
            zf.writestr("KiCad/MyPart.kicad_mod", fp)
            zf.writestr("MyPart.step", step)
            zf.writestr("MyPart.epw", "pointer")  # junk, ignored
        elif vendor == "ultralibrarian":
            zf.writestr("KiCAD/2025-02-10_09-58-00.kicad_sym", sym)
            zf.writestr("KiCAD/MyPart.pretty/VarA.kicad_mod", fp)
            zf.writestr("KiCAD/MyPart.pretty/VarB.kicad_mod", fp)
            zf.writestr("3D/MyPart.stp", step)
        elif vendor == "snapeda":
            zf.writestr("MyPart.kicad_sym", sym)
            zf.writestr("MyPart.kicad_mod", fp)
            zf.writestr("MyPart.step", step)
            zf.writestr("how-to-import.htm", "<html></html>")  # junk marker
        else:
            raise ValueError(f"unknown vendor: {vendor}")
    return dst_zip
```

Append to `tests/backend/ingest/test_pipeline.py`:

```python
from tests.backend.ingest.vendor_fixtures import make_vendor_zip


@pytest.mark.parametrize("vendor", ["octopart", "samacsys", "ultralibrarian", "snapeda"])
def test_end_to_end_ingest_each_vendor_layout(tmp_path, fixtures_dir, vendor):
    pipe = _pipeline(tmp_path)
    z = make_vendor_zip(tmp_path / f"{vendor}.zip", vendor, fixtures_dir)
    cands = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    assert len(cands) >= 1
    c = cands[0]
    assert c.vendor == vendor
    # UltraLibrarian ships several footprint variants for the user to pick.
    if vendor == "ultralibrarian":
        assert len(c.footprint_variants) == 2
    c.category = "ICs"
    c.entry_name = f"PART_{vendor}"
    record = pipe.commit(c)
    from stockroom.kicad.symbol_lib import SymbolLib
    sym_lib = SymbolLib.load(pipe.profile.library.symbol_lib_path("ICs"))
    assert f"PART_{vendor}" in sym_lib.symbol_names
    # a real git commit was produced
    assert record.id


def test_second_add_only_adds_to_target_lib(tmp_path, fixtures_dir):
    """Adding a second part must not rewrite the first part's symbol node: the
    target category lib changes only by ADDITION (byte preservation via the M1
    span layer + semantic-diff gate)."""
    from stockroom.verify.semdiff import semantic_diff

    pipe = _pipeline(tmp_path)
    z1 = make_vendor_zip(tmp_path / "a.zip", "snapeda", fixtures_dir)
    [c1] = pipe.inspect(inputs=[z1], workdir=tmp_path / "w1")
    c1.category = "ICs"; c1.entry_name = "FIRST"
    pipe.commit(c1)
    sym_path = pipe.profile.library.symbol_lib_path("ICs")
    after_first = sym_path.read_text(encoding="utf-8")

    z2 = make_vendor_zip(tmp_path / "b.zip", "snapeda", fixtures_dir)
    [c2] = pipe.inspect(inputs=[z2], workdir=tmp_path / "w2")
    c2.category = "ICs"; c2.entry_name = "SECOND"
    pipe.commit(c2)
    after_second = sym_path.read_text(encoding="utf-8")

    assert '(symbol "FIRST"' in after_second
    assert '(symbol "SECOND"' in after_second
    diffs = semantic_diff(after_first, after_second)
    assert diffs and all(d.startswith("ADDED") for d in diffs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/ingest/test_pipeline.py -k "each_vendor or only_adds" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.backend.ingest.vendor_fixtures'`.

- [ ] **Step 3: Write minimal implementation**

The `vendor_fixtures.py` file above IS the implementation; the tests exercise the already-built pipeline.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/ingest/ -v`
Expected: PASS across the whole ingest suite.

- [ ] **Step 5: Full suite + commit**

Run: `uv run pytest tests/backend -q`
Expected: all prior 155 tests plus the new ingest tests PASS (kicad-cli tests run on WSL).

```bash
git add tests/backend/ingest/vendor_fixtures.py tests/backend/ingest/test_pipeline.py
git commit -m "Add vendor-layout fixtures and end-to-end ingestion integration tests"
```

---

## Self-Review

**1. Spec coverage (section 5):**
- Accepts zips, bare files, folders, mixed, multiple at once → Task 2 (`unpack_inputs`), Task 10 (`inspect`). ✓
- LCSC `Cxxxxx` path via easyeda2kicad → Task 9. ✓
- Fingerprint by content, exact order and marker capitalization → Task 3. ✓
- Ignore junk (`.epw`, `how-to-import.htm`, EDA folders) → detection keys only on the marker files, so siblings are ignored; exercised by `samacsys`/`snapeda` fixtures carrying junk (Task 13). ✓
- Inspect (unpack + classify) → Tasks 2, 3, 10. ✓
- Convert (legacy `.lib` and foreign via `sym upgrade`/`fp upgrade`) → Tasks 1, 4. ✓
- Stage (review card, previews-ready fields, proposed name/category, honest gaps, multi-variant pick, fast path) → Tasks 5, 6, 7 (variants in `footprint_variants` + `chosen_footprint_index`; `gaps`). ✓
- Enrich seam (M4) → `StagingCandidate` carries editable mpn/manufacturer/description/tags/provenance fields for M4 to fill; not implemented here by design. ✓
- Commit: one atomic transaction, files into per-category libs, footprint field on symbol, `(model ...)` link, datasheet stored, JSON record, git commit, re-parse validation gate, zero trace on failure → Tasks 8, 11 (delegates to M2 `add_part` + `Transaction.validate`). ✓
- 3D anywhere, priority step>stp>wrl, Stockroom writes the model link → Task 3 (`_find_model`), `add_part` writes link; Partial attach → Task 12. ✓

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N". Every code step shows real code. The one conditional ("if brittle, use semdiff form") gives both concrete forms, not a placeholder.

**3. Type consistency:** `DetectedSource` fields (`vendor`, `symbol_path`, `dcm_path`, `footprint_paths`, `model_path`, `datasheet_path`) are consistent across Tasks 3, 7, 9, 10. `StagingCandidate` fields consistent across Tasks 6, 7, 10, 11, 12. `build_candidates(cli, detected, workdir, provenance)` signature consistent (Tasks 7, 10). `LibraryOps(profile, repo, cli=None)` consistent (Tasks 8, 10). `fetch_lcsc(lcsc_id, workdir, runner=None)` consistent (Tasks 9, 10 passes `runner=None`). `normalize_symbol(cli, src, dcm, workdir)` / `normalize_footprint(cli, src, workdir)` consistent (Tasks 4, 7).

## Execution Handoff

Plan complete. Per the owner's standing directive for this project (build milestones back-to-back autonomously, no per-task review gates, one adversarial review at the END before merge), execution proceeds straight through on a feature branch with per-task commits (crash-recoverable), then one end-of-build review, then ff-merge + push.
