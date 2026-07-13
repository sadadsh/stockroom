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
