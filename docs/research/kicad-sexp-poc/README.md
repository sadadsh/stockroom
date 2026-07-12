# KiCad s-expression layer: validated research seeds

These are research artifacts from the design phase (2026-07-12), not app code. They were
written by a research agent to empirically settle the KiCad file-surgery choice against
real KiCad 10 files, and they proved the span-preserving approach the spec adopts. Keep
them here as the seed for the real implementation of the s-expression layer and its
verification harness.

- `span_poc.py`: the ~90-line span-preserving edit proof of concept. Tokenizes with byte
  offsets, edits by splicing into the original byte string, never re-serializes untouched
  regions. Demonstrated a one-property edit on a real `.kicad_sch` producing a 2-line byte
  diff (CRLF, tabs, token order all preserved), which kicad-cli then parsed clean.
- `semdiff.py`: an independent canonical-tree semantic differ. This becomes the permanent
  CI gate: after every write, assert only the intended nodes changed (zero lost, zero
  added). It is independent of the edit layer on purpose, so it can catch that layer's bugs.
- `roundtrip_test.py`: the head-to-head harness that disqualified kiutils/kicad-skip/
  kicad-tools/kicadfiles/kicad-sch-api by measuring node loss and formatting churn.

Findings that drove the decision are in the spec (`docs/superpowers/specs/`) and the
project ledger. When implementation starts, harden `span_poc.py` into the real layer
(escapes, node insertion/deletion with KiCad-style indentation inference) and wire
`semdiff.py` plus a `kicad-cli` parse check into the test suite as a gate on every
KiCad-writing path.
