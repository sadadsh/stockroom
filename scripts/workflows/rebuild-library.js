export const meta = {
  name: 'rebuild-library',
  description: 'Fan out the part-schema critical path: derive engine, requirements, index, then importer and guided capture',
  whenToUse:
    'After reading docs/specs/2026-07-27-owner-spec-complete-trusted-library.md AND after the part record model is committed on main. Pass args "core" or "build" to pick the wave.',
  phases: [
    { title: 'Core', detail: 'derive engine, requirements by part class, index schema - all read the model' },
    { title: 'Build', detail: 'importer and guided capture - both read the derive engine' },
  ],
}

// WHY THIS IS ONE WAVE PER RUN, not one script for the whole job.
// The first version fanned out nine agents across five phases. Measured on the run that died:
// hot-reload produced 0 commits, 3d-rotation produced 0 commits, and the ONE agent on the actual
// critical path - the part record - left 629 insertions uncommitted in the working tree. So the
// parallelism was spent on the least important work (the spec puts the 3D fix LAST, "cosmetic") and
// the gate everything waits on ran serially and nearly got lost.
// Now: only critical-path work is fanned out, one dependency wave per invocation, and the MAIN LOOP
// does the merging between waves. A merge needs judgement about which of two parallel edits to the
// same file is right; that judgement belongs where it can be shown to the owner, not in an agent.

const SPEC = 'docs/specs/2026-07-27-owner-spec-complete-trusted-library.md'

const RULES = `
HARD CONSTRAINTS (from CLAUDE.md and the spec - violating any of these fails the task):
- READ ${SPEC} FIRST, in full. It carries the owner's verbatim requirements and every decision
  already made (D1 sourced-vs-derived, D2 trust-as-evidence, D3 four part classes, the record shape,
  the id scheme, and the two invariants). DO NOT re-derive or re-litigate any of them.
- Also read the repo CLAUDE.md. Zero Qt in the backend. Every KiCad write goes through the
  byte-preserving sexp layer. Every mutation is one atomic git Transaction.
- TDD: write the test, PROVE IT RED, then implement. A test that cannot fail is worse than none.
- Tool-agnostic core: iterate the EDA registry. Never write 'if tool == "altium"' in shared logic.
- Gates before you claim done: QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest tests/backend
  -q -n auto, plus ruff. Frontend work also runs npm run test:run, typecheck and build, and commits
  app/frontend-dist/ in the SAME commit as the source.
- Scoped 'git add <path>' only. Never -A, never 'git add .'. One sentence commit messages, no trailers.
- Report honestly: say what you exercised and name what you did NOT. Never claim "fully verified".
`

// A worktree starts with NO .venv and NO node_modules (both gitignored) and is DISPOSABLE - work is
// only reachable afterwards if it is committed on a named branch. Both facts were learned the hard
// way: the dead run left an agent's entire output uncommitted in a tree that was about to vanish.
const worktreeSetup = (branch) => `
YOU ARE IN AN ISOLATED GIT WORKTREE. Read this before your first command.
1. Confirm where you are: 'git rev-parse --show-toplevel'. Everything happens HERE. Never cd into
   /home/sadad/git/stockroom (the main worktree) and never edit files there.
2. FIRST COMMAND: 'git switch -c ${branch}'.
3. This worktree has NO .venv and NO node_modules. Bootstrap before running any gate:
     backend:  'uv sync' from the worktree root, then use ./.venv/bin/python
     frontend: 'npm ci' in app/frontend
   Do NOT borrow the main worktree's .venv: pytest would then run a mix of two checkouts and a green
   result would mean nothing.
4. COMMIT EVERYTHING YOU FINISH, scoped, on ${branch}, AS YOU GO - not once at the end. This
   worktree is disposable and uncommitted work is DESTROYED. The previous run lost an agent's entire
   output exactly this way. 'git status' must show a clean tree when you are done.
5. Do NOT merge or rebase onto main yourself; the main loop lands your branch.
6. REPORT the branch name and 'git rev-parse HEAD'.
`

const BRANCH_RESULT = {
  type: 'object',
  properties: {
    branch: { type: 'string', description: 'the branch the work was committed on' },
    head: { type: 'string', description: 'output of git rev-parse HEAD on that branch' },
    committed: { type: 'boolean', description: 'true only if the worktree is clean and all work is committed' },
    summary: { type: 'string', description: 'what was built: modules, classes, fields, endpoints' },
    notDone: { type: 'string', description: 'what was NOT achieved or NOT verified, named explicitly' },
    gates: { type: 'string', description: 'the gate commands actually run and their actual results' },
    conflictsExpected: { type: 'string', description: 'files you edited that a sibling agent likely also edited' },
  },
  required: ['branch', 'committed', 'summary', 'notDone', 'gates'],
}

const wave = args === 'build' ? 'build' : 'core'

// ---------------------------------------------------------------------------------------------
// WAVE 1: everything that reads the part record model and nothing else. Genuinely parallel - three
// different modules - and every one of them is on the critical path to the owner's rebuild.
if (wave === 'core') {
  phase('Core')

  const core = await parallel([
    () =>
      agent(
        `${RULES}${worktreeSetup('wf/derive-engine')}
The part record model is COMMITTED ON MAIN and your worktree has it: model/part_id.py,
model/part_class.py, model/sourced.py, model/derived.py, model/asset.py, model/trust.py and the
rewritten model/part.py. READ THEM FIRST - they are the contract you build against.

TASK: THE DERIVE ENGINE. One function that recomputes the entire 'derived' block from sourced/.

THE ACCEPTANCE TEST FOR THE WHOLE SCHEMA, straight from the owner - "we can edit it without
reimporting":
  1. IDEMPOTENT: run the derive twice, get byte-identical records.
  2. LOSSLESS: a derive NEVER writes anything under sourced/.
  3. A naming-scheme change is a RE-DERIVE, not a re-import, and loses nothing.
Write those three as real tests, and prove each RED before it goes green.

- Normalization MOVES here from import time. Today spec_hygiene.normalize_spec_key/value rewrites
  values on the way in and the raw winning value is lost forever - that is the bug this fixes.
- Derives display_name, value, category, description and normalized specs from the raw payloads.
- Identity (id, mpn, manufacturer, part_class) is NEVER touched by a derive.
- Conflicts between sources: keep the existing per-key source+confidence and alternates behaviour,
  but derive it rather than storing a mutated winner.
- The naming scheme must be swappable BY CONFIGURATION, not by editing the function - that is what
  makes test 3 meaningful rather than a code edit dressed up as a test.`,
        { label: 'derive-engine', phase: 'Core', isolation: 'worktree', schema: BRANCH_RESULT },
      ),

    () =>
      agent(
        `${RULES}${worktreeSetup('wf/requirements')}
The part record model is COMMITTED ON MAIN and your worktree has it. READ model/part_class.py and
model/part.py FIRST - part_class and requires_override are the contract you build against.

TASK: REQUIREMENTS BY PART CLASS. Rewrite capture/requirements.py so requirements are
f(part_class, EDA tool), read off the EDA registry (spec D3).

- passive -> [] for EVERY tool. Both KiCad and Altium ship passives built in. MEASURED: the old
  code exempted only 'model' for passives, so it demanded altium_symbol + altium_footprint from all
  68 of the owner's passives - 136 requirements nothing could ever satisfy, which was most of what
  the UI reported as permanently stuck.
- component -> symbol + footprint + 3D per tool.
- mechanical -> footprint only, no symbol.
- virtual -> nothing, and no BOM line.
- requires_override on the record wins over the class default when set.
- The Requirement enum is a WIRE CONTRACT the TypeScript union mirrors; keep
  test_the_enum_covers_exactly_the_registry green.
- Requirements answer PRESENCE. Trust is a separate, derived question (spec D2). Do not let this
  module read like a trust verdict - that conflation is the owner's original complaint.`,
        { label: 'requirements', phase: 'Core', isolation: 'worktree', schema: BRANCH_RESULT },
      ),

    () =>
      agent(
        `${RULES}${worktreeSetup('wf/index-schema')}
The part record model is COMMITTED ON MAIN and your worktree has it. READ model/part.py,
model/asset.py and model/trust.py FIRST.

TASK: THE DERIVED INDEX. Rewrite store/index.py, which is measurably wrong for this project's scope.

Defects to fix, all verified by reading the DDL:
- It is SINGLE-TOOL and SINGLE-ASSET: footprint_name, model_file, datasheet_file, purchase_url are
  all singular and implicitly KiCad. There is NO Altium column, so the index physically cannot
  express "has an Altium footprint". This is the flat-implicitly-KiCad anti-pattern the repo's own
  CLAUDE.md forbids. Make it per-tool by iterating the EDA registry.
- purchase_url is singular for a part with Mouser + DigiKey + LCSC rows.
- 'DROP TABLE IF EXISTS parts' means a FULL rebuild every sync - roughly 100 MB of JSON re-read at
  10,000 parts. Make it incremental, and MEASURE the before/after on a synthetic 10k library rather
  than asserting it is faster.
- is_complete + missing bake presence-as-completeness into SQL. The index must be able to express
  TRUST (derived from the assets' checks), not just presence.
Keep every existing read path (search, facets, parametric filters) green.`,
        { label: 'index-schema', phase: 'Core', isolation: 'worktree', schema: BRANCH_RESULT },
      ),
  ])

  const done = core.filter(Boolean)
  log(`Core wave done. Branches: ${done.map((r) => `${r.branch}${r.committed ? '' : ' (UNCOMMITTED)'}`).join(', ')}`)
  return { wave: 'core', results: done, unlanded: done.filter((r) => !r.committed).map((r) => r.branch) }
}

// ---------------------------------------------------------------------------------------------
// WAVE 2: both of these read the derive engine, so they only run once wave 1 is merged onto main.
phase('Build')

const build = await parallel([
  () =>
    agent(
      `${RULES}${worktreeSetup('wf/importer')}
The part record model AND the derive engine are COMMITTED ON MAIN and your worktree has both. Read
model/ and the derive engine module FIRST - they are the contract.

TASK: THE IMPORTER. The owner is DELETING the library and re-importing, so there is NO migration to
write - build the importer the rebuild will use.

- Input: a list of MPNs (the register). Sources: Mouser and DigiKey, both with live credentials in
  the machine config. LCSC is available but the owner has ruled its CAD out; its DATA is still fine.
- Writes sourced/<id>/<vendor>.json verbatim, then calls the EXISTING derive engine for the first
  derived block. Do not write a second derive. NO ASSETS - those come from the capture pass later
  and must attach without rewriting sourced or derived.
- Classify each part into passive | component | mechanical | virtual on import.
- Mouser is rate-limited at 30/min and 1000/day; DigiKey has its own. Pace, back off, and make a
  rate-limited part DEFERRED (retry later) rather than FAILED (nothing can help it) - conflating
  those two makes the report useless. capture/pacing.py already implements exactly this pattern;
  reuse it rather than writing a second one.
- The run must be stoppable and resumable, and the worklist DERIVED from library state so a re-run
  is free on parts already done. capture/complete.py is the proven shape.
- Report success from the code that OBSERVED the write landing, never from the code that dispatched
  the request.`,
      { label: 'importer', phase: 'Build', isolation: 'worktree', schema: BRANCH_RESULT },
    ),

  () =>
    agent(
      `${RULES}${worktreeSetup('wf/guided-capture')}
The part record model and derive engine are COMMITTED ON MAIN and your worktree has them. Read
model/asset.py (origin + checks) FIRST - recording provenance is the point of this task.

TASK: GUIDED CAPTURE, REBUILT. Owner: "yes rebuild guided capture, digikey UL snapmagic and
samacsys", and it must serve BOTH single part adds AND completing existing components.

This is a FRONTEND task in a fresh worktree: run 'npm ci' in app/frontend before any frontend gate,
and commit app/frontend-dist/ in the same commit as the source it was built from.

WHY IT IS HUMAN-DRIVEN, so you do not try to automate it: every automated route was measured and
closed. Nexar is $1,000/month. Ultra Librarian's terms state verbatim "You may not use any robot or
other automated means to access or gather content from the Website". SnapMagic blends AI-generated
models and fails the owner's trust bar. Mouser's API carries no CAD at all. DO NOT BUILD ANYTHING
THAT SCRAPES OR AUTO-DOWNLOADS FROM A VENDOR SITE. The user clicks Download; the app does everything
either side of that click.

- enrich/cad_sources.py ALREADY resolves the correct per-vendor URL for a part across all four
  vendors, with per-vendor instructions and MPN-safe encoding. Build on it; do not rewrite it.
- app/frontend/src/components/CompletePartModal.tsx already models the right shape (per-tool
  CaptureGroup, a SegmentMeter of needs-vs-received). Extend it to the four vendors rather than
  starting over.
- Catch the downloaded file, classify it (capture/classify.py), attach it, and record origin
  {vendor, url, captured_at} on the asset - the owner's complaint was literally "its not trusted
  where we've gotten them", so provenance is the point.
- Both formats per part where the vendor offers them, and a fast path to the NEXT part: the owner is
  doing ~90 parts in one sitting and every extra click is multiplied by 90.
- This UI is the owner's main surface for a 90-part sitting: invoke the frontend-design skill, design
  it deliberately, take a screenshot with scripts/uishot.py and critique it element by element in
  both themes before calling it done.`,
      { label: 'guided-capture', phase: 'Build', isolation: 'worktree', schema: BRANCH_RESULT },
    ),
])

const doneB = build.filter(Boolean)
log(`Build wave done. Branches: ${doneB.map((r) => `${r.branch}${r.committed ? '' : ' (UNCOMMITTED)'}`).join(', ')}`)
return { wave: 'build', results: doneB, unlanded: doneB.filter((r) => !r.committed).map((r) => r.branch) }
