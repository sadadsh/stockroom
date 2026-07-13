# Stockroom — KiCad Manager (app development instructions)

Stockroom is the clean-room rewrite of the retired PyQt "Hardware" app: a KiCad V10
component-library + PCB-project manager for Windows. A Python backend
(`app/backend/stockroom`, FastAPI) serves a React/TS/Tailwind/TanStack frontend
(`app/frontend`, built to `app/frontend-dist/`) inside a WebView2 window (`host/`).
The library is a git-synced repo of one-JSON-per-part records with a derived,
never-committed SQLite index; every KiCad file is written through a byte-preserving
s-expression layer under a git-atomic transaction.

- **Repo:** `~/git/stockroom` (github.com/sadadsh/stockroom, public).
- **The retired PyQt app lives at `~/git/Hardware`** — bug-fix-only, replaced per-feature
  at parity (spec M8). Do NOT bring PyQt-app concerns here (`drive_audit`, `render_gate`,
  `python -m ui`, the Qt widget-lifecycle footgun); they are moot for this rewrite.
- **Design spec (authoritative):** `docs/superpowers/specs/2026-07-12-perfected-rewrite-direction.md`
  (the reconciled direction; the older `2026-07-12-stockroom-design.md` is superseded).
  Milestone plans: `docs/superpowers/plans/`. Research: `docs/research/2026-07-13-kicad-ecosystem-learnings.md`.
- **Design contract:** `docs/design/design-rules.md` (+ `docs/design/north-star-ui.md`).

## Current status (2026-07-13)

M1–M6 complete + verified on Linux AND real Windows (byte-preserving KiCad layer;
library model/profiles/git-sync/atomic-mutation + complete-to-add gate + derived SQLite
index + archive profile; content-fingerprint ingestion; scrape-first enrichment; FastAPI
API layer + per-launch bearer token + JobRunner/SSE; the M5 WebView2 host + launcher; the
M6 frontend: Components read/edit/enrich/ingest/settings/duplicates/doctor/palette/pinout/git-timeline).
**M7 (full Projects) is IN PROGRESS** — plan authored (`docs/superpowers/plans/2026-07-13-stockroom-m7-projects.md`),
M7a-1 `ProjectRecord` model shipped. The live status is the ledger Current State (below).

## Session Ledger + Idea Tracker — MANDATORY (owner standing directive)

Same durable memory as the whole initiative, in the Obsidian vault (NOT in this repo):

- **Ledger** `~/Documents/Obsidian/Brain/Agent/Hardware Perfection Log.md` — log LITERALLY
  everything, every turn (handoff or not): every `ASK` (owner message + intent), `DECISION`
  (+why), `IDEA`, `ACTION` (change/commit/workflow/test), `COMPROMISE` (why + when + what
  "done" means). Append newest-at-bottom; keep the **Current State** header + **Open
  Compromises** table current. A SessionStart hook reprints Current State each session.
- **Idea tracker** `~/Documents/Obsidian/Brain/Agent/Hardware Ideas.md` — the moment the
  owner gives an idea, add it as a `- [ ]` checkbox; tick `- [x]` (+ commit) when it ships.
- Commit + push **scoped** to the Obsidian repo (only the ledger / tracker / `Log.md` — never
  the repo-root `.obsidian/` churn).

## Hard constraints (non-negotiable)

- **Zero Qt / pywebview in the backend.** Every `stockroom.*` module (and especially
  `stockroom.api`) imports zero PyQt (`PyQt5`, `QtCore`, `QtWidgets`, `QtGui`) and no
  `pywebview` outside `host/`. CI greps and fails on any hit. Reuse from the old app is
  **reuse-by-extraction** into Qt-free modules — never `import LibraryManager` / `fp_render`
  (they drag PyQt5 at import); copy the pure helpers out.
- **Every KiCad write goes through Layer 0.** The byte-preserving `sexp/SexpDocument`
  span-splice editor is the only thing that edits `.kicad_*`; a targeted JSON editor is the
  only thing that edits `.kicad_pro`; `mutation/Transaction` is the only committer. Edits are
  scoped token/key substitution, never a re-serialize, never `pcbnew.Save`. The writer passes
  unmodeled tokens through losslessly and fails loud on overlapping edits.
- **Fail-proof / atomic.** Every mutation is one git-backed `Transaction`: a single scoped
  commit, or restore every touched path and leave zero trace. Complete-to-add gate (no partial
  adds); commit-time asset gate (a record may not reference an asset uncommitted in the same tree).
- **Design contract** (`docs/design/design-rules.md`): no em dashes; Title Case for interactive
  labels (buttons, headings, tags, menu items); sentence case for body prose (real sentences);
  8px card radius / 6px control radius invariant; tokens only (spacing via tokens, never scattered
  literals); category hues ≥3:1 contrast both themes.
- **Honest completion.** Never claim "0 regressions", "fully verified", "flawless", or "done" off
  tests alone. State exactly what was exercised and where. Windows CI (`ci.yml`, windows-latest) is
  the release gate; Linux/offscreen green is necessary, never sufficient. The owner runs Windows on
  a real library. File I/O passes `encoding="utf-8"`; never `str(Path)` for display (use `.as_posix()`).

## Implementation standard

Every implementation is **no-compromise, full end-to-end** — never a stub, happy-path, silent
fallback, hardcoded placeholder, or "good enough" first cut. Time is not a constraint; correctness
and completeness are. Full authority to strip-and-rebuild. If a gap is genuinely unavoidable, it is
LOGGED in the ledger (why + when + what "done" looks like), never hidden.

## Verify gates (per slice)

- **Backend:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend -q` (or `uv run pytest`).
  New seam built TDD, `pytest` RED→GREEN, BEFORE its frontend lands.
- **Frontend:** `cd app/frontend && npm run test:run && npm run typecheck && npm run build` — **commit
  the regenerated `app/frontend-dist/` in the same scoped commit as the source** (that is what the
  backend serves).
- **Adversarial-review Workflow** over each committed diff (multi-lens find → adversarial-verify);
  fix confirmed findings TDD/mutation-locked before "done". (The advisor tool has been down; this +
  TDD are its substitute.)
- **Windows pixel gate** for any visual slice: update the winverify clone
  (`C:\Users\Sadad Haidari\stockroom-winverify`, `git reset --hard origin/main`), write a
  `demo_server_<slice>.py` + `pw_<slice>.py` under `C:\srverify` (seed real data, serve the SPA with
  the token injected, drive headless Chromium), run them, then **Read the PNGs** against
  `docs/design/*.md` in both themes. Windows suite: `cmd /c C:\srverify\wv.bat`.

## Git

- **Scoped `git add <path>` only** — never `-A` / `commit -a`.
- Plain commit messages, **one sentence max, no body**; **NO `Co-Authored-By` / `Claude-Session` trailers.**
- Push without asking once committed + ready; never force-push. **Do NOT tag a release** — the owner
  calls the version tag once a milestone is complete + its Windows pixel gate is closed.

## Model & effort routing

Standing ultracode default: xhigh effort + Workflow-tool orchestration for substantive/parallelizable
work; adversarially verify before "done"; delegate cheap/bulk stages down to Haiku/low; keep the hard
reasoning + verify/judge stages on Opus/xhigh. Say which tier you used when it matters.
