# Stockroom M1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the byte-preserving KiCad file core: an s-expression layer that reads, edits, and writes `.kicad_sym`, `.kicad_mod`, and `.kicad_sch` files while preserving every untouched byte, plus a semantic-diff verification gate and a kicad-cli wrapper.

**Architecture:** A pure-Python span-preserving s-expression layer tokenizes KiCad files into a node tree that records each token's byte offsets; edits splice replacement text into the original byte string and untouched regions are never re-serialized. On top of it sit thin file models (SymbolLib, Footprint, Schematic) that expose intent-level operations (get/set a property, rewrite an instance, link a 3D model). An independent semantic differ verifies after every write that only the intended nodes changed, and a kicad-cli wrapper provides format upgrades and SVG previews. This is the substrate every later milestone builds on.

**Tech Stack:** Python 3.12, uv (lockfile-pinned), pytest. No third-party runtime dependencies in M1 (the s-expression layer is stdlib-only). External tool: kicad-cli 10.0.4 (already installed; integration tests auto-skip when absent).

## Global Constraints

- **KiCad target: V10.** `.kicad_sym` current stamp is `(version 20251024)`; V9 refuses V10-stamped files. Changes since V9 are additive tokens plus a semantic change where `~` no longer means empty text. Copied verbatim from spec §8.
- **Byte preservation is mandatory.** Parse then serialize with no edits MUST return byte-identical output (CRLF, tabs, number formatting, token order all preserved). A one-property edit MUST diff only the changed line(s). This is disqualifying for every existing library and is the reason for a custom layer (spec §8).
- **Version-stamp policy.** Surgical edits PRESERVE the file's existing `(version ...)` stamp and all untouched tokens. Stockroom never invents a version stamp; new libraries are stamped by the user's installed KiCad via kicad-cli (spec §8).
- **No em dashes anywhere** (code, comments, docs, commit messages, strings). Owner directive.
- **Encoding:** all file reads use `encoding="utf-8"`. All KiCad file reads/writes use `newline=""` so CRLF is preserved exactly. Never `str(Path)` for display; use `.as_posix()`.
- **Platform:** developed in WSL (Linux); the owner's Windows machine with real KiCad V10 is the verification gate. Linux-green is necessary, never sufficient; completion claims name the environment they rest on.
- **Package import root:** the backend package is importable as `stockroom` (configured via pytest `pythonpath`), living at `app/backend/stockroom/`.

## Milestone roadmap (context; only M1 is detailed here)

Each milestone produces working, testable software and gets its own plan when reached.

- **M1 (this plan): Foundation.** Span-preserving s-expression core + semantic-diff gate + KiCad file models (SymbolLib, Footprint, Schematic) + kicad-cli wrapper. Deliverable: losslessly read/edit/write KiCad design and library files, proven by a round-trip gate.
- **M2: Library data model, profiles, git sync, KiCad wiring.** Part JSON records, per-category libraries, profile create/switch/delete, atomic mutation engine, git commit/pull/push, `sym-lib-table`/`fp-lib-table` + `kicad_common.json` writers (append `${SR_LIB}` rows without disturbing the V10 `(type "Table")` row).
- **M3: Ingestion pipeline.** Content-fingerprint zip adapters (SnapMagic/UltraLibrarian/SamacSys/Octopart/Partial), legacy `.lib` upgrade, 3D re-linking, staging, atomic commit. LCSC `Cxxxxx` path via easyeda2kicad.
- **M4: Enrichment engine.** Mouser Search API v2, generic parser (curl_cffi + JSON-LD/OG ladder), in-window WebView2 scraping fallback, datasheet fetcher.
- **M5: Backend API + app shell + launcher.** FastAPI routes, pywebview WebView2 window, frozen-once launcher, git-pull self-update.
- **M6: Frontend UI.** React + Vite + TS + Tailwind v4: library view, Ctrl+K palette (cmdk), virtualized list (TanStack Virtual), detail panel (symbol/footprint SVG + three.js 3D), ingest, duplicates, settings.
- **M7: Project audit.** Sheet-hierarchy parse, match cascade, step-through wizard, apply phase with backups.

---

## File Structure (M1)

```
stockroom/
  pyproject.toml                         # uv/hatchling project, pytest config
  .github/workflows/ci.yml               # pure-Python suite on ubuntu + windows
  app/backend/stockroom/
    __init__.py                          # version string
    sexp/
      __init__.py                        # re-exports SexpDocument, SexpNode
      tokens.py                          # Token, tokenize_spans
      document.py                        # SexpDocument, SexpNode, quote_kicad
    verify/
      __init__.py                        # re-exports semantic_diff, assert_only_changed
      semdiff.py                         # semantic_diff, assert_only_changed, SemDiffError
    kicad/
      __init__.py
      errors.py                          # KiCadError, KiCadFileError, KiCadCliError
      cli.py                             # KiCadCli (locate, version, sym_upgrade, export svg)
      symbol_lib.py                      # SymbolLib, Symbol
      footprint.py                       # Footprint, Model3D
      schematic.py                       # Schematic, SymbolInstance
  tests/backend/
    conftest.py                          # fixture loaders, requires_kicad_cli marker
    fixtures/kicad/
      minimal.kicad_sym                  # hand-authored, CRLF, v10 stamp
      minimal.kicad_mod                  # hand-authored, CRLF
      minimal.kicad_sch                  # hand-authored, CRLF, 2 instances
      legacy.lib                         # KiCad 5 EESchema-LIBRARY for upgrade test
    sexp/test_tokens.py
    sexp/test_document.py
    sexp/test_roundtrip.py
    verify/test_semdiff.py
    kicad/test_cli.py
    kicad/test_symbol_lib.py
    kicad/test_footprint.py
    kicad/test_schematic.py
```

Responsibilities: `sexp/` owns byte-preserving parse/edit/serialize and knows nothing about KiCad semantics. `verify/` owns the independent semantic check and depends on nothing else. `kicad/` owns KiCad-specific meaning (what a symbol property is, where a 3D model link lives) and consumes `sexp/`. Files that change together live together; each file has one responsibility.

---

## Task 1: Repo scaffold and toolchain

**Files:**
- Create: `pyproject.toml`
- Create: `app/backend/stockroom/__init__.py`
- Create: `tests/backend/conftest.py`
- Create: `tests/backend/sexp/test_smoke.py`

**Interfaces:**
- Produces: importable package `stockroom` with `stockroom.__version__`; pytest runnable via `uv run pytest`; a `requires_kicad_cli` marker and a `fixtures_dir` fixture consumed by later tasks.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "stockroom"
version = "0.1.0"
description = "KiCad V10 component-library manager"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.2"]

[tool.hatch.build.targets.wheel]
packages = ["app/backend/stockroom"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
pythonpath = ["app/backend"]
testpaths = ["tests/backend"]
markers = [
    "requires_kicad_cli: test needs the kicad-cli binary; skipped when absent",
]
```

- [ ] **Step 2: Write the package init**

`app/backend/stockroom/__init__.py`:

```python
"""Stockroom backend package."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write `conftest.py`**

`tests/backend/conftest.py`:

```python
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "kicad"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def tmp_fixture(tmp_path):
    """Copy a named fixture into a temp dir and return its path (for edit tests)."""

    def _copy(name: str) -> Path:
        dst = tmp_path / name
        shutil.copyfile(FIXTURES / name, dst)
        return dst

    return _copy


def _has_kicad_cli() -> bool:
    return shutil.which("kicad-cli") is not None


requires_kicad_cli = pytest.mark.skipif(
    not _has_kicad_cli(), reason="kicad-cli not installed"
)
```

- [ ] **Step 4: Write the smoke test**

`tests/backend/sexp/test_smoke.py`:

```python
import stockroom


def test_package_imports():
    assert stockroom.__version__ == "0.1.0"
```

- [ ] **Step 5: Run it**

Run: `uv run pytest tests/backend/sexp/test_smoke.py -v`
Expected: PASS (uv provisions Python 3.12 and pytest on first run, then the test passes).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/backend/stockroom/__init__.py tests/backend/conftest.py tests/backend/sexp/test_smoke.py
git commit -m "Scaffold Stockroom backend package and pytest toolchain"
```

---

## Task 2: s-expression tokenizer

**Files:**
- Create: `app/backend/stockroom/sexp/__init__.py`
- Create: `app/backend/stockroom/sexp/tokens.py`
- Test: `tests/backend/sexp/test_tokens.py`

**Interfaces:**
- Produces: `Token(kind: str, start: int, end: int)` where `kind` is one of `"("`, `")"`, `"str"`, `"atom"`; and `tokenize_spans(text: str) -> Iterator[Token]`. `start`/`end` are byte-agnostic string indices into `text`; `text[start:end]` is the exact token slice (quotes included for `"str"`).

- [ ] **Step 1: Write the failing test**

`tests/backend/sexp/test_tokens.py`:

```python
from stockroom.sexp.tokens import Token, tokenize_spans


def toks(text):
    return list(tokenize_spans(text))


def test_parens_and_atoms_have_exact_spans():
    text = '(a bc)'
    result = toks(text)
    assert result == [
        Token("(", 0, 1),
        Token("atom", 1, 2),
        Token("atom", 3, 5),
        Token(")", 5, 6),
    ]


def test_string_span_includes_quotes():
    text = '(x "hi there")'
    result = toks(text)
    str_tok = [t for t in result if t.kind == "str"][0]
    assert text[str_tok.start : str_tok.end] == '"hi there"'


def test_escaped_quote_inside_string():
    text = r'("a\"b")'
    str_tok = [t for t in toks(text) if t.kind == "str"][0]
    assert text[str_tok.start : str_tok.end] == r'"a\"b"'


def test_crlf_and_tabs_are_whitespace():
    text = '(\r\n\t(y 1)\r\n)'
    result = toks(text)
    assert [t.kind for t in result] == ["(", "(", "atom", "atom", ")", ")"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/sexp/test_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.sexp.tokens'`

- [ ] **Step 3: Write the tokenizer**

`app/backend/stockroom/sexp/tokens.py`:

```python
"""Span-recording tokenizer for KiCad s-expressions.

Every token carries its exact [start, end) slice into the source text, so an
editor can splice replacements without re-serializing anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Token:
    kind: str  # "(", ")", "str", or "atom"
    start: int
    end: int


def tokenize_spans(text: str) -> Iterator[Token]:
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield Token(c, i, i + 1)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    j += 1
            yield Token("str", i, j + 1)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield Token("atom", i, j)
            i = j
```

- [ ] **Step 4: Write the package init**

`app/backend/stockroom/sexp/__init__.py`:

```python
from stockroom.sexp.tokens import Token, tokenize_spans

__all__ = ["Token", "tokenize_spans"]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/sexp/test_tokens.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/sexp/tokens.py app/backend/stockroom/sexp/__init__.py tests/backend/sexp/test_tokens.py
git commit -m "Add span-recording s-expression tokenizer"
```

---

## Task 3: s-expression document and node tree

**Files:**
- Create: `app/backend/stockroom/sexp/document.py`
- Modify: `app/backend/stockroom/sexp/__init__.py`
- Test: `tests/backend/sexp/test_document.py`

**Interfaces:**
- Consumes: `Token`, `tokenize_spans` from Task 2.
- Produces:
  - `quote_kicad(value: str) -> str` returns a KiCad-quoted, escaped string literal (wraps in `"`, escapes `\` and `"`).
  - `SexpDocument.parse(text: str) -> SexpDocument`, with `.text: str`, `.root: SexpNode`, `.serialize() -> str`, `.save(path)`, and `.replace_span(start: int, end: int, replacement: str) -> None`.
  - `SexpNode` with: `.is_atom: bool`, `.kind: str` (`"("` for lists, else token kind), `.span: tuple[int, int]`, `.value: str` (unquoted atom/str text; empty for lists), `.name: str | None` (head atom value of a list), `.children: list[SexpNode]`, `.find(name: str) -> SexpNode | None`, `.find_all(name: str) -> list[SexpNode]`, `.set_value(new: str, *, quote: bool) -> None` (leaf only; records an edit).

- [ ] **Step 1: Write the failing test**

`tests/backend/sexp/test_document.py`:

```python
from stockroom.sexp.document import SexpDocument, quote_kicad


def test_quote_kicad_escapes():
    assert quote_kicad('a"b\\c') == '"a\\"b\\\\c"'


def test_parse_exposes_names_and_children():
    doc = SexpDocument.parse('(symbol (property "Value" "10k") (lib_id "L:R"))')
    assert doc.root.name == "symbol"
    prop = doc.root.find("property")
    assert prop is not None
    assert prop.children[1].value == "Value"
    assert prop.children[2].value == "10k"


def test_find_all_returns_every_match():
    doc = SexpDocument.parse('(x (p 1) (p 2) (q 3))')
    ps = doc.root.find_all("p")
    assert [p.children[1].value for p in ps] == ["1", "2"]


def test_serialize_without_edits_is_byte_identical():
    text = '(symbol\r\n\t(property "V" "1")\r\n)'
    doc = SexpDocument.parse(text)
    assert doc.serialize() == text


def test_set_value_records_minimal_edit():
    text = '(symbol (property "Value" "10k"))'
    doc = SexpDocument.parse(text)
    val_leaf = doc.root.find("property").children[2]
    val_leaf.set_value("22k", quote=True)
    assert doc.serialize() == '(symbol (property "Value" "22k"))'


def test_set_value_on_unquoted_atom():
    text = '(at 1.5 2.5 90)'
    doc = SexpDocument.parse(text)
    doc.root.children[3].set_value("180", quote=False)
    assert doc.serialize() == '(at 1.5 2.5 180)'


def test_load_and_save_preserve_crlf(tmp_path):
    text = '(symbol\r\n\t(property "V" "1")\r\n)'
    src = tmp_path / "x.kicad_sym"
    src.write_text(text, encoding="utf-8", newline="")
    doc = SexpDocument.load(src)
    out = tmp_path / "out.kicad_sym"
    doc.save(out)
    assert out.read_bytes() == src.read_bytes()


def test_double_set_value_last_write_wins():
    doc = SexpDocument.parse('(at 90)')
    leaf = doc.root.children[1]
    leaf.set_value("180", quote=False)
    leaf.set_value("270", quote=False)
    assert doc.serialize() == '(at 270)'
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/sexp/test_document.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.sexp.document'`

- [ ] **Step 3: Write the document module**

`app/backend/stockroom/sexp/document.py`:

```python
"""Byte-preserving s-expression document.

Parse builds a node tree whose leaves carry source spans. Edits are recorded
as (start, end, replacement) tuples and applied to the ORIGINAL text in reverse
order at serialize time, so untouched bytes are never rewritten.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.sexp.tokens import Token, tokenize_spans


def quote_kicad(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(text: str, tok: Token) -> str:
    raw = text[tok.start : tok.end]
    if tok.kind == "str":
        inner = raw[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return raw


class SexpNode:
    __slots__ = ("_doc", "_token", "_children", "_text", "_list_span")

    def __init__(self, doc, text, token=None, children=None):
        self._doc = doc
        self._text = text
        self._token = token  # set for leaves
        self._children = children  # set for lists
        self._list_span = None  # (open, close) byte span; set for list nodes

    @property
    def is_atom(self) -> bool:
        return self._token is not None

    @property
    def kind(self) -> str:
        return self._token.kind if self._token else "("

    @property
    def span(self) -> tuple[int, int]:
        if self._token:
            return (self._token.start, self._token.end)
        first, last = self._children_span()
        return (first, last)

    def _children_span(self) -> tuple[int, int]:
        # span of a list = from its own '(' to its ')'; stored on the list node
        return self._list_span

    @property
    def value(self) -> str:
        if not self._token:
            return ""
        return _unquote(self._text, self._token)

    @property
    def name(self) -> str | None:
        if self._token or not self._children:
            return None
        head = self._children[0]
        return head.value if head.is_atom else None

    @property
    def children(self) -> list["SexpNode"]:
        return list(self._children or [])

    def find(self, name: str) -> "SexpNode | None":
        for ch in self._children or []:
            if not ch.is_atom and ch.name == name:
                return ch
        return None

    def find_all(self, name: str) -> list["SexpNode"]:
        return [
            ch
            for ch in (self._children or [])
            if not ch.is_atom and ch.name == name
        ]

    def set_value(self, new: str, *, quote: bool) -> None:
        if not self._token:
            raise ValueError("set_value is only valid on a leaf node")
        replacement = quote_kicad(new) if quote else new
        self._doc.replace_span(self._token.start, self._token.end, replacement)


class SexpDocument:
    def __init__(self, text: str):
        self.text = text
        self._edits: list[tuple[int, int, str]] = []
        self.root = self._build()

    @classmethod
    def parse(cls, text: str) -> "SexpDocument":
        return cls(text)

    @classmethod
    def load(cls, path) -> "SexpDocument":
        # newline="" disables newline translation so CRLF is read back exactly.
        # (Path.read_text does not accept newline on Python 3.12, so use open().)
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        return cls(text)

    def _build(self) -> SexpNode:
        toks = list(tokenize_spans(self.text))
        pos = 0

        def read() -> SexpNode:
            nonlocal pos
            tok = toks[pos]
            if tok.kind == "(":
                open_start = tok.start
                pos += 1
                kids: list[SexpNode] = []
                while toks[pos].kind != ")":
                    kids.append(read())
                close_end = toks[pos].end
                pos += 1
                node = SexpNode(self, self.text, children=kids)
                node._list_span = (open_start, close_end)
                return node
            pos += 1
            return SexpNode(self, self.text, token=tok)

        return read()

    def replace_span(self, start: int, end: int, replacement: str) -> None:
        # Last write wins for an identical span, so re-editing the same token
        # supersedes the prior edit instead of splicing both against the
        # original coordinates (which would corrupt the output).
        self._edits = [e for e in self._edits if not (e[0] == start and e[1] == end)]
        self._edits.append((start, end, replacement))

    def serialize(self) -> str:
        text = self.text
        # Apply edits from the highest start offset down so earlier offsets stay
        # valid. Spans are distinct leaf tokens (deduped in replace_span), so
        # sorting by start alone is unambiguous.
        for start, end, replacement in sorted(self._edits, key=lambda e: e[0], reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
```

- [ ] **Step 4: Update the package init**

`app/backend/stockroom/sexp/__init__.py`:

```python
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad
from stockroom.sexp.tokens import Token, tokenize_spans

__all__ = ["Token", "tokenize_spans", "SexpDocument", "SexpNode", "quote_kicad"]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/sexp/test_document.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/sexp/document.py app/backend/stockroom/sexp/__init__.py tests/backend/sexp/test_document.py
git commit -m "Add byte-preserving s-expression document and node tree"
```

---

## Task 4: node insertion with indentation inference

**Files:**
- Modify: `app/backend/stockroom/sexp/document.py`
- Test: `tests/backend/sexp/test_document.py` (append cases)

**Interfaces:**
- Consumes: `SexpNode`, `SexpDocument` from Task 3.
- Produces: on `SexpNode` (list nodes only):
  - `.insert_child_text(sexp_text: str) -> None` inserts a child just before the list's closing paren, matching sibling indentation.
  - `.insert_after(child: SexpNode, sexp_text: str) -> None` inserts `sexp_text` on its own line after `child`, matching `child`'s indentation.
  - `.remove_child(child: SexpNode) -> None` deletes a child and the whitespace on its line.
  Indentation is inferred from the newline-prefixed whitespace preceding an existing child; when a list is single-line, insertion stays single-line with a leading space.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/sexp/test_document.py`:

```python
def test_insert_child_multiline_matches_indent():
    text = '(symbol\n\t(property "A" "1")\n)'
    doc = SexpDocument.parse(text)
    doc.root.insert_child_text('(property "B" "2")')
    assert doc.serialize() == '(symbol\n\t(property "A" "1")\n\t(property "B" "2")\n)'


def test_insert_after_specific_child():
    text = '(x\n\t(a 1)\n\t(c 3)\n)'
    doc = SexpDocument.parse(text)
    a = doc.root.find("a")
    doc.root.insert_after(a, '(b 2)')
    assert doc.serialize() == '(x\n\t(a 1)\n\t(b 2)\n\t(c 3)\n)'


def test_insert_child_single_line():
    text = '(pts (xy 0 0))'
    doc = SexpDocument.parse(text)
    doc.root.insert_child_text('(xy 1 1)')
    assert doc.serialize() == '(pts (xy 0 0) (xy 1 1))'


def test_remove_child_multiline():
    text = '(x\n\t(a 1)\n\t(b 2)\n)'
    doc = SexpDocument.parse(text)
    doc.root.remove_child(doc.root.find("b"))
    assert doc.serialize() == '(x\n\t(a 1)\n)'


def test_insert_child_preserves_crlf():
    text = '(symbol\r\n\t(property "A" "1")\r\n)'
    doc = SexpDocument.parse(text)
    doc.root.insert_child_text('(property "B" "2")')
    out = doc.serialize()
    assert out == '(symbol\r\n\t(property "A" "1")\r\n\t(property "B" "2")\r\n)'
    assert "\n\t" not in out.replace("\r\n\t", "")  # no bare-LF indent introduced


def test_remove_child_preserves_crlf():
    text = '(x\r\n\t(a 1)\r\n\t(b 2)\r\n)'
    doc = SexpDocument.parse(text)
    doc.root.remove_child(doc.root.find("b"))
    out = doc.serialize()
    assert out == '(x\r\n\t(a 1)\r\n)'
    assert "\r\r" not in out  # no orphaned CR left behind
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/sexp/test_document.py -k "insert or remove" -v`
Expected: FAIL with `AttributeError: 'SexpNode' object has no attribute 'insert_child_text'`

- [ ] **Step 3: Implement insertion helpers**

Add these methods to `SexpNode` in `document.py` (and the helper below):

```python
    def _indent_before(self, index: int) -> str:
        """Whitespace run (including a leading newline) before child `index`,
        or empty string if the child is not newline-prefixed. Captures the full
        CRLF pair so inserting/removing on a Windows/KiCad file keeps CRLF."""
        child = self._children[index]
        start = child.span[0]
        text = self._text
        j = start
        while j > 0 and text[j - 1] in " \t":
            j -= 1
        if j > 0 and text[j - 1] == "\n":
            nl = j - 1
            if nl > 0 and text[nl - 1] == "\r":
                nl -= 1  # include the \r of a \r\n pair
            return text[nl:start]
        if j > 0 and text[j - 1] == "\r":
            return text[j - 1 : start]  # lone CR (old-Mac), defensive
        return ""

    def insert_after(self, child: "SexpNode", sexp_text: str) -> None:
        if self._children is None:
            raise ValueError("insert_after is only valid on a list node")
        idx = self._children.index(child)
        indent = self._indent_before(idx)
        pos = child.span[1]
        if indent:
            self._doc.replace_span(pos, pos, f"{indent}{sexp_text}")
        else:
            self._doc.replace_span(pos, pos, f" {sexp_text}")

    def insert_child_text(self, sexp_text: str) -> None:
        if self._children is None:
            raise ValueError("insert_child_text is only valid on a list node")
        if self._children:
            last = self._children[-1]
            self.insert_after(last, sexp_text)
            return
        # empty list: insert right before ')'
        close = self._list_span[1] - 1
        self._doc.replace_span(close, close, sexp_text)

    def remove_child(self, child: "SexpNode") -> None:
        if self._children is None:
            raise ValueError("remove_child is only valid on a list node")
        idx = self._children.index(child)
        indent = self._indent_before(idx)
        start = child.span[0] - len(indent) if indent else child.span[0]
        self._doc.replace_span(start, child.span[1], "")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/sexp/test_document.py -v`
Expected: PASS (all Task 3 + Task 4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/sexp/document.py tests/backend/sexp/test_document.py
git commit -m "Add s-expression node insertion and removal with indentation inference"
```

---

## Task 5: semantic diff verification gate

**Files:**
- Create: `app/backend/stockroom/verify/__init__.py`
- Create: `app/backend/stockroom/verify/semdiff.py`
- Test: `tests/backend/verify/test_semdiff.py`

**Interfaces:**
- Produces:
  - `semantic_diff(original: str, modified: str) -> list[str]` returns human-readable difference lines; empty list means semantically identical (formatting-only changes ignored, numbers normalized).
  - `SemDiffError(Exception)`.
  - `assert_only_changed(original: str, modified: str, *, allowed_changes: int) -> None` raises `SemDiffError` if any node was LOST or ADDED, or if the number of CHANGED atoms exceeds `allowed_changes`.
- This module is independent of `sexp/` on purpose (its own minimal parser), so it can catch bugs in the edit layer.

- [ ] **Step 1: Write the failing test**

`tests/backend/verify/test_semdiff.py`:

```python
import pytest

from stockroom.verify.semdiff import (
    SemDiffError,
    assert_only_changed,
    semantic_diff,
)


def test_identical_is_empty():
    assert semantic_diff("(a 1)", "(a 1)") == []


def test_formatting_only_is_empty():
    assert semantic_diff("(a\n\t1)", "(a 1)") == []


def test_number_repr_noise_ignored():
    assert semantic_diff("(at 1.0)", "(at 1)") == []


def test_changed_atom_detected():
    diffs = semantic_diff('(p "V" "10k")', '(p "V" "22k")')
    assert any("CHANGED" in d for d in diffs)


def test_lost_node_detected():
    diffs = semantic_diff("(x (a 1) (b 2))", "(x (a 1))")
    assert any("LOST" in d for d in diffs)


def test_assert_only_changed_allows_intended_edit():
    assert_only_changed('(p "V" "10k")', '(p "V" "22k")', allowed_changes=1)


def test_assert_only_changed_rejects_lost_node():
    with pytest.raises(SemDiffError):
        assert_only_changed("(x (a 1) (b 2))", "(x (a 1))", allowed_changes=1)


def test_assert_only_changed_rejects_extra_change():
    with pytest.raises(SemDiffError):
        assert_only_changed('(p "10k" "1")', '(p "22k" "2")', allowed_changes=1)


def test_malformed_input_raises_semdifferror():
    # the gate must surface a catchable SemDiffError, not crash with IndexError,
    # when an edit produces malformed output (the exact case it exists to catch).
    for bad in ("", '(a "unterminated)', "(a (b 1)"):
        with pytest.raises(SemDiffError):
            semantic_diff(bad, "(a 1)")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/verify/test_semdiff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.verify.semdiff'`

- [ ] **Step 3: Write the semantic differ**

`app/backend/stockroom/verify/semdiff.py` (hardened from the validated PoC `docs/research/kicad-sexp-poc/semdiff.py`):

```python
"""Independent semantic s-expression diff used as a write-verification gate.

Distinguishes harmless reformatting from token loss, mutation, or reordering.
Uses its own minimal parser so it can catch bugs in the edit layer.
"""

from __future__ import annotations

import difflib
import re

NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


class SemDiffError(Exception):
    pass


def _tokenize(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield c, c
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j : j + 2])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise SemDiffError(f"unterminated string at index {i}")
            yield "str", "".join(buf)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield "atom", text[i:j]
            i = j


def _norm_atom(kind, val):
    if kind == "atom" and NUM_RE.match(val):
        return ("num", float(val))
    if kind == "str":
        v = val.replace('\\"', '"').replace("\\\\", "\\")
        if NUM_RE.match(v):
            return ("num", float(v))
        return ("s", v)
    return ("s", val)


def _parse(text):
    toks = list(_tokenize(text))
    pos = 0

    def read():
        nonlocal pos
        if pos >= len(toks):
            raise SemDiffError("unexpected end of input")
        kind, val = toks[pos]
        if kind == "(":
            pos += 1
            lst = []
            while pos < len(toks) and toks[pos][0] != ")":
                lst.append(read())
            if pos >= len(toks):
                raise SemDiffError("missing close paren")
            pos += 1
            return tuple(lst)
        pos += 1
        return _norm_atom(kind, val)

    root = read()
    if pos != len(toks):
        raise SemDiffError(f"trailing tokens at {pos}/{len(toks)}")
    return root


def _is_atom(t):
    return (
        isinstance(t, tuple)
        and len(t) == 2
        and t[0] in ("num", "s")
        and not isinstance(t[1], tuple)
    )


def _node_name(t):
    if not _is_atom(t) and isinstance(t, tuple) and t and _is_atom(t[0]):
        return t[0][1]
    return None


def _count(t):
    if isinstance(t, tuple) and t and not _is_atom(t):
        return 1 + sum(_count(c) for c in t)
    return 1


def _diff(a, b, path, out, cap):
    if len(out) >= cap:
        return
    if _is_atom(a) and _is_atom(b):
        if a != b:
            if a[0] == "num" and b[0] == "num" and abs(a[1] - b[1]) < 1e-9:
                return
            out.append(f"CHANGED {path}: {a[1]!r} -> {b[1]!r}")
        return
    if _is_atom(a) != _is_atom(b):
        out.append(f"TYPE-CHANGED {path}")
        return
    name = _node_name(a) or ""

    def sig(t):
        return ("A", t) if _is_atom(t) else ("L", _node_name(t), len(t))

    sm = difflib.SequenceMatcher(None, [sig(c) for c in a], [sig(c) for c in b], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if len(out) >= cap:
            break
        if tag in ("equal", "replace") and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                _diff(a[i1 + k], b[j1 + k], f"{path}/{name}[{i1 + k}]", out, cap)
        else:
            for k in range(i1, i2):
                out.append(f"LOST {path}/{name}: [{_count(a[k])} nodes]")
            for k in range(j1, j2):
                out.append(f"ADDED {path}/{name}: [{_count(b[k])} nodes]")


def semantic_diff(original: str, modified: str, cap: int = 200) -> list[str]:
    out: list[str] = []
    _diff(_parse(original), _parse(modified), "", out, cap)
    return out


def assert_only_changed(original: str, modified: str, *, allowed_changes: int) -> None:
    diffs = semantic_diff(original, modified)
    lost = [d for d in diffs if d.startswith(("LOST", "ADDED", "TYPE"))]
    changed = [d for d in diffs if d.startswith("CHANGED")]
    if lost:
        raise SemDiffError("structural change detected: " + "; ".join(lost[:5]))
    if len(changed) > allowed_changes:
        raise SemDiffError(
            f"expected <= {allowed_changes} changed atoms, got {len(changed)}: "
            + "; ".join(changed[:5])
        )
```

- [ ] **Step 4: Write the package init**

`app/backend/stockroom/verify/__init__.py`:

```python
from stockroom.verify.semdiff import SemDiffError, assert_only_changed, semantic_diff

__all__ = ["SemDiffError", "assert_only_changed", "semantic_diff"]
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/backend/verify/test_semdiff.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add app/backend/stockroom/verify/ tests/backend/verify/test_semdiff.py
git commit -m "Add independent semantic-diff write-verification gate"
```

---

## Task 6: KiCad fixtures and round-trip fidelity gate

**Files:**
- Create: `tests/backend/fixtures/kicad/minimal.kicad_sym`
- Create: `tests/backend/fixtures/kicad/minimal.kicad_mod`
- Create: `tests/backend/fixtures/kicad/minimal.kicad_sch`
- Create: `tests/backend/fixtures/kicad/legacy.lib`
- Create: `tests/backend/sexp/test_roundtrip.py`

**Interfaces:**
- Consumes: `SexpDocument` from Task 3.
- Produces: committed KiCad fixtures (CRLF line endings, V10 stamps) used by all later KiCad tests, and a parametrized round-trip test proving parse then serialize is byte-identical for every fixture.

- [ ] **Step 1: Create `minimal.kicad_sym`** (write with CRLF line endings and a leading tab on nested lines; V10 stamp)

```
(kicad_symbol_lib
	(version 20251024)
	(generator "kicad_symbol_editor")
	(generator_version "10.0")
	(symbol "R_0603"
		(property "Reference" "R" (at 0 0 0))
		(property "Value" "R_0603" (at 0 0 0))
		(property "Footprint" "" (at 0 0 0))
		(property "Datasheet" "" (at 0 0 0))
		(property "MPN" "" (at 0 0 0))
		(property "Manufacturer" "" (at 0 0 0))
	)
)
```

Note to implementer: save this file with CRLF (`\r\n`) line endings and hard tabs, matching KiCad's own output. In Python: `Path("...").write_text(text.replace("\n", "\r\n"), encoding="utf-8", newline="")`.

- [ ] **Step 2: Create `minimal.kicad_mod`** (CRLF, one model link present)

```
(footprint "R_0603"
	(version 20260206)
	(generator "pcbnew")
	(layer "F.Cu")
	(pad "1" smd roundrect (at -0.8 0) (size 0.9 0.95) (layers "F.Cu"))
	(pad "2" smd roundrect (at 0.8 0) (size 0.9 0.95) (layers "F.Cu"))
	(model "${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603.step"
		(offset (xyz 0 0 0))
		(scale (xyz 1 1 1))
		(rotate (xyz 0 0 0))
	)
)
```

- [ ] **Step 3: Create `minimal.kicad_sch`** (CRLF, two symbol instances for the audit tests)

```
(kicad_sch
	(version 20260306)
	(generator "eeschema")
	(symbol
		(lib_id "Device:R")
		(at 100 100 0)
		(property "Reference" "R1" (at 100 95 0))
		(property "Value" "10k" (at 100 105 0))
		(property "Footprint" "Resistor_SMD:R_0603" (at 100 100 0))
	)
	(symbol
		(lib_id "Device:C")
		(at 120 100 0)
		(property "Reference" "C1" (at 120 95 0))
		(property "Value" "100n" (at 120 105 0))
		(property "Footprint" "Capacitor_SMD:C_0603" (at 120 100 0))
	)
)
```

- [ ] **Step 4: Create `legacy.lib`** (KiCad 5 format, LF is fine here; used only for the upgrade test)

```
EESchema-LIBRARY Version 2.4
#encoding utf-8
#
# TEST_R
#
DEF TEST_R R 0 0 N Y 1 F N
F0 "R" 0 0 50 H V C CNN
F1 "TEST_R" 0 0 50 H V C CNN
DRAW
S -50 50 50 -50 0 1 10 N
ENDDRAW
ENDDEF
#
#End Library
```

- [ ] **Step 5: Write the round-trip test**

`tests/backend/sexp/test_roundtrip.py`:

```python
import pytest

from stockroom.sexp.document import SexpDocument

KICAD_FIXTURES = ["minimal.kicad_sym", "minimal.kicad_mod", "minimal.kicad_sch"]


@pytest.mark.parametrize("name", KICAD_FIXTURES)
def test_parse_then_serialize_is_byte_identical(fixtures_dir, name):
    original = (fixtures_dir / name).read_text(encoding="utf-8", newline="")
    doc = SexpDocument.parse(original)
    assert doc.serialize() == original


@pytest.mark.parametrize("name", KICAD_FIXTURES)
def test_fixtures_use_crlf(fixtures_dir, name):
    raw = (fixtures_dir / name).read_bytes()
    assert b"\r\n" in raw, f"{name} must use CRLF to mirror KiCad output"
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/backend/sexp/test_roundtrip.py -v`
Expected: PASS (5 tests). If `test_fixtures_use_crlf` fails, the fixture was saved with LF; re-save with CRLF per Step 1's note.

- [ ] **Step 7: Commit**

```bash
git add tests/backend/fixtures/kicad/ tests/backend/sexp/test_roundtrip.py
git commit -m "Add CRLF KiCad fixtures and byte-identical round-trip fidelity gate"
```

---

## Task 7: KiCad errors and kicad-cli wrapper

**Files:**
- Create: `app/backend/stockroom/kicad/__init__.py`
- Create: `app/backend/stockroom/kicad/errors.py`
- Create: `app/backend/stockroom/kicad/cli.py`
- Test: `tests/backend/kicad/test_cli.py`

**Interfaces:**
- Produces:
  - `errors.py`: `KiCadError(Exception)`, `KiCadFileError(KiCadError)`, `KiCadCliError(KiCadError)`.
  - `cli.py`: `KiCadCli(binary: str | None = None)` with `.version() -> str`, `.sym_upgrade(src: Path, dst: Path) -> None`, `.sym_export_svg(lib: Path, symbol: str, out_dir: Path, *, black_and_white: bool = False) -> list[Path]`, `.fp_export_svg(pretty_dir: Path, footprint: str, out_dir: Path, layers: str = "F.Cu,F.SilkS,F.Fab") -> Path`. Constructor raises `KiCadCliError` if the binary is not found. All exports invoke the real `kicad-cli`; footprint export targets the `.pretty` DIRECTORY plus `--fp` (never a bare `.kicad_mod`).

- [ ] **Step 1: Write the failing test**

`tests/backend/kicad/test_cli.py`:

```python
from pathlib import Path

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.errors import KiCadCliError
from tests.backend.conftest import requires_kicad_cli


def test_missing_binary_raises():
    with pytest.raises(KiCadCliError):
        KiCadCli(binary="definitely-not-kicad-cli-xyz")


@requires_kicad_cli
def test_version_reports_10():
    assert KiCadCli().version().startswith("10.")


@requires_kicad_cli
def test_sym_upgrade_produces_v10_stamp(tmp_path, fixtures_dir):
    dst = tmp_path / "upgraded.kicad_sym"
    KiCadCli().sym_upgrade(fixtures_dir / "legacy.lib", dst)
    text = dst.read_text(encoding="utf-8")
    assert "kicad_symbol_lib" in text
    assert "(version 2025" in text or "(version 2024" in text


@requires_kicad_cli
def test_sym_export_svg_writes_file(tmp_path, fixtures_dir):
    out = KiCadCli().sym_export_svg(fixtures_dir / "minimal.kicad_sym", "R_0603", tmp_path)
    assert out and all(p.suffix == ".svg" and p.exists() for p in out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.kicad.cli'`

- [ ] **Step 3: Write errors and cli**

`app/backend/stockroom/kicad/errors.py`:

```python
class KiCadError(Exception):
    pass


class KiCadFileError(KiCadError):
    pass


class KiCadCliError(KiCadError):
    pass
```

`app/backend/stockroom/kicad/cli.py`:

```python
"""Thin wrapper over the kicad-cli binary (KiCad 10)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from stockroom.kicad.errors import KiCadCliError


class KiCadCli:
    def __init__(self, binary: str | None = None):
        resolved = shutil.which(binary or "kicad-cli")
        if resolved is None:
            raise KiCadCliError(f"kicad-cli not found: {binary or 'kicad-cli'}")
        self.binary = resolved

    def _run(self, *args: str) -> str:
        proc = subprocess.run(
            [self.binary, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise KiCadCliError(f"kicad-cli {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def version(self) -> str:
        return self._run("version").strip()

    def sym_upgrade(self, src: Path, dst: Path) -> None:
        self._run("sym", "upgrade", "-o", str(Path(dst)), str(Path(src)))

    def sym_export_svg(
        self, lib: Path, symbol: str, out_dir: Path, *, black_and_white: bool = False
    ) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        args = ["sym", "export", "svg", "-o", str(out_dir), "-s", symbol]
        if black_and_white:
            args.append("--black-and-white")
        args.append(str(Path(lib)))
        self._run(*args)
        return sorted(out_dir.glob("*.svg"))

    def fp_export_svg(
        self,
        pretty_dir: Path,
        footprint: str,
        out_dir: Path,
        layers: str = "F.Cu,F.SilkS,F.Fab",
    ) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # kicad-cli requires the .pretty DIRECTORY plus --fp, never a bare .kicad_mod.
        self._run(
            "fp", "export", "svg",
            "-o", str(out_dir),
            "--fp", footprint,
            "-l", layers,
            str(Path(pretty_dir)),
        )
        svgs = sorted(out_dir.glob("*.svg"))
        if not svgs:
            raise KiCadCliError(f"no SVG produced for footprint {footprint}")
        return svgs[0]
```

`app/backend/stockroom/kicad/__init__.py`:

```python
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.errors import KiCadCliError, KiCadError, KiCadFileError

__all__ = ["KiCadCli", "KiCadError", "KiCadFileError", "KiCadCliError"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_cli.py -v`
Expected: PASS (the `requires_kicad_cli` tests run since kicad-cli 10.0.4 is installed; the missing-binary test always runs).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/__init__.py app/backend/stockroom/kicad/errors.py app/backend/stockroom/kicad/cli.py tests/backend/kicad/test_cli.py
git commit -m "Add kicad-cli wrapper for version, symbol upgrade, and SVG export"
```

---

## Task 8: SymbolLib file model

**Files:**
- Create: `app/backend/stockroom/kicad/symbol_lib.py`
- Test: `tests/backend/kicad/test_symbol_lib.py`

**Interfaces:**
- Consumes: `SexpDocument`, `SexpNode`, `quote_kicad` (Task 3/4); `assert_only_changed` (Task 5); `KiCadFileError` (Task 7).
- Produces:
  - `Symbol` view with `.name -> str`, `.get_property(name: str) -> str | None`, `.set_property(name: str, value: str) -> None` (updates the value token of an existing `(property "name" "value" ...)`, or inserts a new property node when absent).
  - `SymbolLib` with `SymbolLib.load(path) -> SymbolLib`, `.version -> str` (the `(version ...)` stamp), `.symbol_names -> list[str]`, `.get_symbol(name: str) -> Symbol`, `.serialize() -> str`, `.save(path) -> None`.
  - Property list order in `(property "Name" "Value" ...)`: child[1] is the name string, child[2] is the value string.

- [ ] **Step 1: Write the failing test**

`tests/backend/kicad/test_symbol_lib.py`:

```python
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.verify.semdiff import assert_only_changed


def test_lists_symbols_and_version(fixtures_dir):
    lib = SymbolLib.load(fixtures_dir / "minimal.kicad_sym")
    assert lib.symbol_names == ["R_0603"]
    assert lib.version == "20251024"


def test_get_and_set_existing_property(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    sym = lib.get_symbol("R_0603")
    assert sym.get_property("Value") == "R_0603"
    original = lib.serialize()
    sym.set_property("MPN", "RC0603FR-0710KL")
    assert sym.get_property("MPN") == "RC0603FR-0710KL"
    assert_only_changed(original, lib.serialize(), allowed_changes=1)


def test_set_absent_property_inserts(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    sym = lib.get_symbol("R_0603")
    original = lib.serialize()
    assert sym.get_property("Description") is None
    sym.set_property("Description", "10k 1% 0603 resistor")
    assert sym.get_property("Description") == "10k 1% 0603 resistor"
    # a pure insert adds nodes; assert no existing node was lost or changed
    diffs = [
        d
        for d in __import__(
            "stockroom.verify.semdiff", fromlist=["semantic_diff"]
        ).semantic_diff(original, lib.serialize())
        if d.startswith(("LOST", "CHANGED", "TYPE"))
    ]
    assert diffs == []


def test_version_stamp_is_preserved_on_edit(tmp_fixture):
    lib = SymbolLib.load(tmp_fixture("minimal.kicad_sym"))
    lib.get_symbol("R_0603").set_property("Value", "22k")
    assert "(version 20251024)" in lib.serialize()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_symbol_lib.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.kicad.symbol_lib'`

- [ ] **Step 3: Write SymbolLib**

`app/backend/stockroom/kicad/symbol_lib.py`:

```python
"""Read/edit KiCad .kicad_sym symbol libraries with byte preservation."""

from __future__ import annotations

from pathlib import Path

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad


class Symbol:
    def __init__(self, node: SexpNode):
        self._node = node

    @property
    def name(self) -> str:
        return self._node.children[1].value

    def _property_node(self, name: str) -> SexpNode | None:
        for prop in self._node.find_all("property"):
            kids = prop.children
            if len(kids) >= 3 and kids[1].value == name:
                return prop
        return None

    def get_property(self, name: str) -> str | None:
        prop = self._property_node(name)
        return prop.children[2].value if prop else None

    def set_property(self, name: str, value: str) -> None:
        prop = self._property_node(name)
        if prop is not None:
            prop.children[2].set_value(value, quote=True)
        else:
            self._node.insert_child_text(
                f"(property {quote_kicad(name)} {quote_kicad(value)} (at 0 0 0))"
            )


class SymbolLib:
    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "kicad_symbol_lib":
            raise KiCadFileError("not a .kicad_sym file (missing kicad_symbol_lib)")

    @classmethod
    def load(cls, path) -> "SymbolLib":
        return cls(SexpDocument.load(path))

    @property
    def version(self) -> str:
        node = self._doc.root.find("version")
        return node.children[1].value if node else ""

    @property
    def symbol_names(self) -> list[str]:
        return [s.children[1].value for s in self._doc.root.find_all("symbol")]

    def get_symbol(self, name: str) -> Symbol:
        for s in self._doc.root.find_all("symbol"):
            if s.children[1].value == name:
                return Symbol(s)
        raise KiCadFileError(f"symbol not found: {name}")

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_symbol_lib.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/symbol_lib.py tests/backend/kicad/test_symbol_lib.py
git commit -m "Add SymbolLib model for byte-preserving symbol property edits"
```

---

## Task 9: Footprint model with 3D link editing

**Files:**
- Create: `app/backend/stockroom/kicad/footprint.py`
- Test: `tests/backend/kicad/test_footprint.py`

**Interfaces:**
- Consumes: `SexpDocument`, `SexpNode`, `quote_kicad` (Task 3/4); `assert_only_changed`, `semantic_diff` (Task 5); `KiCadFileError` (Task 7).
- Produces:
  - `Footprint` with `Footprint.load(path) -> Footprint`, `.name -> str`, `.model_path -> str | None` (the path string of the first `(model ...)`), `.set_model_path(path: str) -> None` (rewrites the existing model path token, or inserts a full `(model ...)` block before the footprint's closing paren when none exists), `.serialize()`, `.save(path)`.
  - The inserted model block has the form `(model "<path>" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))`.

- [ ] **Step 1: Write the failing test**

`tests/backend/kicad/test_footprint.py`:

```python
from stockroom.kicad.footprint import Footprint
from stockroom.verify.semdiff import assert_only_changed, semantic_diff


def test_reads_model_path(fixtures_dir):
    fp = Footprint.load(fixtures_dir / "minimal.kicad_mod")
    assert fp.model_path.endswith("R_0603.step")


def test_rewrites_existing_model_path(tmp_fixture):
    fp = Footprint.load(tmp_fixture("minimal.kicad_mod"))
    original = fp.serialize()
    fp.set_model_path("${SR_LIB}/models/Resistors/R_0603.step")
    assert fp.model_path == "${SR_LIB}/models/Resistors/R_0603.step"
    assert_only_changed(original, fp.serialize(), allowed_changes=1)


def test_inserts_model_when_absent(tmp_path):
    text = '(footprint "X"\n\t(version 20260206)\n\t(layer "F.Cu")\n)'.replace("\n", "\r\n")
    p = tmp_path / "nomodel.kicad_mod"
    p.write_text(text, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    assert fp.model_path is None
    original = fp.serialize()
    fp.set_model_path("${SR_LIB}/models/X.step")
    assert fp.model_path == "${SR_LIB}/models/X.step"
    structural = [
        d for d in semantic_diff(original, fp.serialize()) if d.startswith(("LOST", "CHANGED", "TYPE"))
    ]
    assert structural == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_footprint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.kicad.footprint'`

- [ ] **Step 3: Write Footprint**

`app/backend/stockroom/kicad/footprint.py`:

```python
"""Read/edit KiCad .kicad_mod footprints, focused on the 3D model link."""

from __future__ import annotations

from pathlib import Path

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, quote_kicad


class Footprint:
    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "footprint":
            raise KiCadFileError("not a .kicad_mod file (missing footprint)")

    @classmethod
    def load(cls, path) -> "Footprint":
        return cls(SexpDocument.load(path))

    @property
    def name(self) -> str:
        return self._doc.root.children[1].value

    def _model_node(self):
        return self._doc.root.find("model")

    @property
    def model_path(self) -> str | None:
        node = self._model_node()
        return node.children[1].value if node else None

    def set_model_path(self, path: str) -> None:
        node = self._model_node()
        if node is not None:
            node.children[1].set_value(path, quote=True)
        else:
            block = (
                f"(model {quote_kicad(path)} "
                "(offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))"
            )
            self._doc.root.insert_child_text(block)

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_footprint.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/footprint.py tests/backend/kicad/test_footprint.py
git commit -m "Add Footprint model with byte-preserving 3D model link editing"
```

---

## Task 10: Schematic model with instance enumeration and rewrite

**Files:**
- Create: `app/backend/stockroom/kicad/schematic.py`
- Test: `tests/backend/kicad/test_schematic.py`

**Interfaces:**
- Consumes: `SexpDocument`, `SexpNode`, `quote_kicad` (Task 3/4); `assert_only_changed` (Task 5); `KiCadFileError` (Task 7).
- Produces:
  - `SymbolInstance` with `.reference -> str`, `.lib_id -> str`, `.value -> str`, `.get_property(name) -> str | None`, `.set_property(name, value) -> None`, `.set_lib_id(lib_id: str) -> None`.
  - `Schematic` with `Schematic.load(path) -> Schematic`, `.instances -> list[SymbolInstance]` (top-level `(symbol ...)` nodes with a `lib_id`), `.instance_by_reference(ref: str) -> SymbolInstance`, `.serialize()`, `.save(path)`.
  - Reference is read from the `(property "Reference" "..." ...)` child, lib_id from the `(lib_id "...")` child.

- [ ] **Step 1: Write the failing test**

`tests/backend/kicad/test_schematic.py`:

```python
from stockroom.kicad.schematic import Schematic
from stockroom.verify.semdiff import assert_only_changed


def test_enumerates_instances(fixtures_dir):
    sch = Schematic.load(fixtures_dir / "minimal.kicad_sch")
    refs = sorted(i.reference for i in sch.instances)
    assert refs == ["C1", "R1"]
    r1 = sch.instance_by_reference("R1")
    assert r1.lib_id == "Device:R"
    assert r1.value == "10k"
    assert r1.get_property("Footprint") == "Resistor_SMD:R_0603"


def test_rewrites_only_target_instance(tmp_fixture):
    sch = Schematic.load(tmp_fixture("minimal.kicad_sch"))
    original = sch.serialize()
    r1 = sch.instance_by_reference("R1")
    r1.set_lib_id("SR-Resistors:R_0603")
    r1.set_property("MPN", "RC0603FR-0710KL")
    assert r1.lib_id == "SR-Resistors:R_0603"
    assert r1.get_property("MPN") == "RC0603FR-0710KL"
    # C1 must be untouched
    assert sch.instance_by_reference("C1").lib_id == "Device:C"


def test_lib_id_edit_is_minimal(tmp_fixture):
    sch = Schematic.load(tmp_fixture("minimal.kicad_sch"))
    original = sch.serialize()
    sch.instance_by_reference("R1").set_lib_id("SR-Resistors:R_0603")
    assert_only_changed(original, sch.serialize(), allowed_changes=1)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/backend/kicad/test_schematic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.kicad.schematic'`

- [ ] **Step 3: Write Schematic**

`app/backend/stockroom/kicad/schematic.py`:

```python
"""Read KiCad .kicad_sch schematics and rewrite symbol instances (for audit)."""

from __future__ import annotations

from pathlib import Path

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, SexpNode, quote_kicad


class SymbolInstance:
    def __init__(self, node: SexpNode):
        self._node = node

    def _property_node(self, name: str) -> SexpNode | None:
        for prop in self._node.find_all("property"):
            kids = prop.children
            if len(kids) >= 3 and kids[1].value == name:
                return prop
        return None

    @property
    def lib_id(self) -> str:
        node = self._node.find("lib_id")
        return node.children[1].value if node else ""

    @property
    def reference(self) -> str:
        return self.get_property("Reference") or ""

    @property
    def value(self) -> str:
        return self.get_property("Value") or ""

    def get_property(self, name: str) -> str | None:
        prop = self._property_node(name)
        return prop.children[2].value if prop else None

    def set_property(self, name: str, value: str) -> None:
        prop = self._property_node(name)
        if prop is not None:
            prop.children[2].set_value(value, quote=True)
        else:
            self._node.insert_child_text(
                f"(property {quote_kicad(name)} {quote_kicad(value)} (at 0 0 0))"
            )

    def set_lib_id(self, lib_id: str) -> None:
        node = self._node.find("lib_id")
        if node is None:
            raise KiCadFileError("instance has no lib_id")
        node.children[1].set_value(lib_id, quote=True)


class Schematic:
    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "kicad_sch":
            raise KiCadFileError("not a .kicad_sch file (missing kicad_sch)")

    @classmethod
    def load(cls, path) -> "Schematic":
        return cls(SexpDocument.load(path))

    @property
    def instances(self) -> list[SymbolInstance]:
        out = []
        for node in self._doc.root.find_all("symbol"):
            if node.find("lib_id") is not None:
                out.append(SymbolInstance(node))
        return out

    def instance_by_reference(self, ref: str) -> SymbolInstance:
        for inst in self.instances:
            if inst.reference == ref:
                return inst
        raise KiCadFileError(f"no instance with reference {ref}")

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        Path(path).write_text(self.serialize(), encoding="utf-8", newline="")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_schematic.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/kicad/schematic.py tests/backend/kicad/test_schematic.py
git commit -m "Add Schematic model with instance enumeration and byte-preserving rewrite"
```

---

## Task 11: kicad-cli parse-back integration gate

**Files:**
- Create: `tests/backend/kicad/test_parse_back_gate.py`

**Interfaces:**
- Consumes: `SymbolLib` (Task 8), `Footprint` (Task 9), `Schematic` (Task 10), `KiCadCli` (Task 7).
- Produces: the permanent gate proving that after Stockroom edits and saves a file, the real kicad-cli parses it clean. This is the "KiCad itself accepts our output" half of the verification harness (the semantic-diff is the "only intended change" half). Tests are `requires_kicad_cli`.

- [ ] **Step 1: Write the test**

`tests/backend/kicad/test_parse_back_gate.py`:

```python
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from tests.backend.conftest import requires_kicad_cli


@requires_kicad_cli
def test_edited_symbol_lib_still_exports(tmp_fixture, tmp_path):
    src = tmp_fixture("minimal.kicad_sym")
    lib = SymbolLib.load(src)
    lib.get_symbol("R_0603").set_property("MPN", "RC0603FR-0710KL")
    lib.save(src)
    # kicad-cli parsing the edited lib and exporting a symbol proves it is valid.
    out = KiCadCli().sym_export_svg(src, "R_0603", tmp_path)
    assert out and out[0].exists()


@requires_kicad_cli
def test_edited_footprint_still_exports(tmp_fixture, tmp_path):
    # place the fixture inside a .pretty dir, since fp export needs the directory
    pretty = tmp_path / "SR-Resistors.pretty"
    pretty.mkdir()
    src = pretty / "R_0603.kicad_mod"
    src.write_text(
        (tmp_fixture("minimal.kicad_mod")).read_text(encoding="utf-8", newline=""),
        encoding="utf-8",
        newline="",
    )
    fp = Footprint.load(src)
    fp.set_model_path("${SR_LIB}/models/Resistors/R_0603.step")
    fp.save(src)
    svg = KiCadCli().fp_export_svg(pretty, "R_0603", tmp_path / "out")
    assert svg.exists()
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/backend/kicad/test_parse_back_gate.py -v`
Expected: PASS (kicad-cli 10.0.4 present). If a KiCadCliError surfaces, read its stderr; it means the edited file is malformed, which is a real bug in the edit layer to fix before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/kicad/test_parse_back_gate.py
git commit -m "Add kicad-cli parse-back gate proving edited files stay KiCad-valid"
```

---

## Task 12: CI workflow and full-suite green

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `docs/backend-testing.md`

**Interfaces:**
- Consumes: the whole M1 test suite.
- Produces: a CI workflow running the pure-Python suite on ubuntu-latest and windows-latest (kicad-cli tests auto-skip on runners without KiCad), and a short doc stating how to run the full suite including the kicad-cli gate locally, and that the owner's Windows + real KiCad is the final gate.

- [ ] **Step 1: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  backend:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v5
      - name: Sync
        run: uv sync
      - name: Run backend suite
        run: uv run pytest tests/backend -v
```

- [ ] **Step 2: Write the testing doc**

`docs/backend-testing.md`:

```markdown
# Backend testing

Run the full suite (from the repo root):

    uv run pytest tests/backend -v

- Pure-Python tests (sexp, verify) run everywhere and are the CI gate on
  ubuntu-latest and windows-latest.
- Tests marked `requires_kicad_cli` exercise the real kicad-cli binary and
  auto-skip when it is absent (so CI runners skip them). Run them locally on a
  machine with KiCad 10 installed.

The two-part write-verification gate:

1. `stockroom.verify.semdiff.assert_only_changed` proves an edit changed only
   the intended nodes (no token lost, added, or mutated).
2. The `test_parse_back_gate` tests prove kicad-cli itself still parses the
   edited file.

Linux-green is necessary, not sufficient. The final gate is the owner's Windows
machine with real KiCad V10 and the real library.
```

- [ ] **Step 3: Run the full suite locally**

Run: `uv run pytest tests/backend -v`
Expected: PASS, all tasks' tests green (kicad-cli tests execute locally).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml docs/backend-testing.md
git commit -m "Add CI workflow and backend testing guide for the M1 foundation"
```

---

## Self-Review

**Spec coverage (M1 scope):** The spec's KiCad file-surgery requirement (§8: byte-preserving s-expression layer, semantic-diff gate, kicad-cli parse-back, version-stamp preservation) is implemented across Tasks 2-12. The file models needed by later milestones (SymbolLib for symbol properties, Footprint for the `(model ...)` link, Schematic for instance rewrite in audit §4) are Tasks 8-10. `sym-lib-table`/`fp-lib-table` and `kicad_common.json` writers are intentionally deferred to M2 (wiring), noted in the roadmap; ingestion, enrichment, UI, launcher, and audit are M3-M7. No M1 requirement is left without a task.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" present; every code step contains complete, runnable code.

**Type consistency:** `SexpNode`/`SexpDocument` API (`.find`, `.find_all`, `.value`, `.name`, `.children`, `.set_value(quote=)`, `.insert_child_text`, `.insert_after`, `.remove_child`, `.replace_span`) is defined in Tasks 3-4 and consumed with matching signatures in Tasks 8-10. `quote_kicad`, `assert_only_changed(allowed_changes=)`, `semantic_diff`, `KiCadCli.sym_export_svg`/`fp_export_svg`/`sym_upgrade` names match between definition and use. Property-node child indexing (name = child[1], value = child[2]) is consistent across SymbolLib, Schematic. Fixture names (`minimal.kicad_sym/mod/sch`, `legacy.lib`) match between Task 6 and Tasks 7-11.
