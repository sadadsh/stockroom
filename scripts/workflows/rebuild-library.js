export const meta = {
  name: 'rebuild-library',
  description: "Build the owner's five-point spec: new part schema, reimport, guided capture, hot reload, 3D fix",
  whenToUse:
    'After reading docs/specs/2026-07-27-owner-spec-complete-trusted-library.md. Runs the full ' +
    'implementation of the owner-approved schema + capture + hot-reload + 3D work in dependency order.',
  phases: [
    { title: 'Independent', detail: 'hot reload, 3D rotation, device sync - none depend on the schema' },
    { title: 'Model', detail: 'the part record: sourced/derived split, part classes, id scheme' },
    { title: 'OnModel', detail: 'derive engine, requirements by part class, index schema' },
    { title: 'MergeA', detail: 'land the independent + on-model branches on main, gates green' },
    { title: 'OnDerive', detail: 'importer and guided capture UI' },
    { title: 'MergeB', detail: 'land the on-derive branches on main, gates green' },
    { title: 'Verify', detail: 'acceptance test + adversarial review of every diff' },
  ],
}

// The one document every agent must read first. The single most expensive failure of 2026-07-27 was
// re-deriving decisions that were already written down; every brief below points here so no agent
// re-litigates the schema.
const SPEC = 'docs/specs/2026-07-27-owner-spec-complete-trusted-library.md'

// Constraints that are NOT negotiable and that every agent gets, because a subagent cannot see the
// conversation that produced them.
const RULES = `
HARD CONSTRAINTS (from CLAUDE.md and the spec - violating any of these fails the task):
- READ ${SPEC} FIRST, in full. It carries the owner's verbatim requirements and every decision
  already made (D1 sourced-vs-derived, D2 trust-as-evidence, D3 four part classes, the record shape,
  the id scheme, and the two invariants). DO NOT re-derive or re-litigate any of them.
- Also read the repo CLAUDE.md. Zero Qt in the backend. Every KiCad write goes through the
  byte-preserving sexp layer. Every mutation is one atomic git Transaction.
- TDD: write the test, PROVE IT RED, then implement. A test that cannot fail is worse than none.
- Tool-agnostic core: iterate the EDA registry. Never write 'if tool == "altium"' in shared logic.
- Gates before you claim done: QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend
  -q -n auto, plus ruff. Frontend work also runs npm run test:run, typecheck and build, and commits
  app/frontend-dist/ in the SAME commit as the source.
- Scoped 'git add <path>' only. Never -A, never 'git add .'. One sentence commit messages, no trailers.
- Report honestly: say what you exercised and name what you did NOT. Never claim "fully verified".
`

// Every concurrent builder runs in its own git worktree, because they touch overlapping backend
// files and four agents committing into one .git also collide on index.lock. A worktree starts with
// NO .venv and NO node_modules (both gitignored), so bootstrapping is part of the task, and the work
// is only reachable afterwards if it is committed on a NAMED BRANCH - the worktree itself is
// disposable. The merge phases below land those branches on main.
const worktreeSetup = (branch) => `
YOU ARE IN AN ISOLATED GIT WORKTREE. Read this before your first command.
1. Confirm where you are: 'git rev-parse --show-toplevel' and 'git status'. Everything you do happens
   HERE. Never cd into /home/sadad/git/stockroom (the main worktree) and never edit files there.
2. FIRST COMMAND: 'git switch -c ${branch}'. Your work is only reachable later if it is committed on
   that branch. An uncommitted worktree is thrown away.
3. This worktree has NO .venv and NO node_modules - both are gitignored, so a fresh checkout lacks
   them. Bootstrap what you need before running any gate:
     backend:  'uv sync' from the worktree root, then use ./.venv/bin/python
     frontend: 'npm ci' in app/frontend
   Do NOT reach into the main worktree's .venv: pytest would then be running against a mix of two
   checkouts, and a green result would mean nothing.
4. COMMIT everything you finish, scoped, on ${branch}. Leave the tree CLEAN - 'git status' must show
   no modified tracked files when you are done, or that work is lost.
5. Your branch will be merged into main by a later agent. Keep your commits scoped and coherent so a
   conflict is readable. Do NOT merge or rebase onto main yourself.
6. REPORT the branch name and the output of 'git rev-parse HEAD'.
`

// Structured return so the merge phases get the branch names as data rather than as prose that has
// to be re-parsed.
const BRANCH_RESULT = {
  type: 'object',
  properties: {
    branch: { type: 'string', description: 'the branch the work was committed on' },
    head: { type: 'string', description: 'output of git rev-parse HEAD on that branch' },
    committed: { type: 'boolean', description: 'true only if the worktree is clean and all work is committed' },
    summary: { type: 'string', description: 'what was built: modules, dataclasses, fields, endpoints' },
    notDone: { type: 'string', description: 'what was NOT achieved or NOT verified, named explicitly' },
    gates: { type: 'string', description: 'the gate commands actually run and their actual results' },
  },
  required: ['branch', 'committed', 'summary', 'notDone', 'gates'],
}

// ---------------------------------------------------------------------------------------------
// These three depend on NOTHING in the schema work, so they start immediately and run alongside it.
// Deliberately NOT awaited here - they run concurrently with the Model agent and are collected at
// MergeA. (The original script never awaited this at all, which made the final return crash.)
phase('Independent')

const independent = parallel([
  () =>
    agent(
      `${RULES}${worktreeSetup('wf/hot-reload')}
TASK: HOT RELOAD. Owner: "i also want the app to always be updated even if its open so u dont have
to close to see updates." Spec section 10.

Today a device only becomes current because scripts/deploy.py is pointed at it by hand, and seeing
an update requires relaunching. Make the running app pick up an update WITHOUT the user closing it.

- Read host/ (the WebView2 host), app/backend/stockroom/api/routers/update.py and updater.py, and
  scripts/deploy.py to establish what update machinery already exists. Do not rebuild what is there.
- At minimum the frontend bundle must reload in place after an update lands.
- A backend change must either hot-swap or restart without the user ever seeing a closed window.
- An update must NEVER leave the app in a broken state: if it cannot complete, it must roll back and
  say so. The owner's words are "automatic and never face errors".
- State plainly which half you achieved (frontend reload / backend restart) and which you did not.`,
      { label: 'hot-reload', phase: 'Independent', isolation: 'worktree', schema: BRANCH_RESULT },
    ),

  () =>
    agent(
      `${RULES}${worktreeSetup('wf/3d-rotation')}
TASK: 3D MODEL ROTATION. MEASURED on the owner's real library: 21 of 57 parts carrying our own
footprint have a non-identity model placement that the viewer IGNORES, so they render in the wrong
orientation. Eleven are 180 degrees about Z, ten are 270.

ROOT CAUSE: kicad/model_convert.py::model_to_glb(src) takes ONLY the model path and never sees the
footprint's (model ... (rotate (xyz ...)) (offset ...) (scale ...)).

- A previous session deliberately did NOT ship this because the SIGN could not be settled: KiCad
  applies the rotation NEGATED, and the only sample was 180 degrees, which is its own inverse.
  THAT BLOCKER IS GONE - there are now TEN parts at 270 degrees. Render one, compare against KiCad's
  own 3D viewer, settle the sign FROM EVIDENCE, then apply rotate + offset + scale.
- A WRONG SIGN ROTATES CORRECT PARTS AWAY FROM CORRECT, which is strictly worse than shipping
  nothing. Do not guess the sign; prove it, and say what you compared against.
- Footprint.model_placement is a PROPERTY, not a method (this exact mistake was made three times in
  one session). Same for Footprint.pads and SymbolLib.symbol_names.
- Do NOT re-seat or move any part: that regression was already fixed once in cae5a81.`,
      { label: '3d-rotation', phase: 'Independent', isolation: 'worktree', schema: BRANCH_RESULT },
    ),

  () =>
    agent(
      `${RULES}${worktreeSetup('wf/device-sync')}
TASK: DEVICE SYNC. Owner: "library should always also be linked" -> clarified as "i meant libraries
linked between devices". Spec section 10. This is the DEVICE PARITY invariant: same parts, same
files, same info on every machine, with nobody clicking Sync.

- Today auto_push fires on write and NOTHING PULLS, so a part added on device A is invisible on
  device B until a human remembers. One-directional sync is divergence with extra steps. Add
  automatic pull.
- Handle the real merge case: two devices adding DIFFERENT parts is a genuine git merge.
- The empty SR-*.kicad_sym blocker is already FIXED (commit 88dce84) - they were required by KiCad's
  sym-lib-table but untracked. Do not re-open it, and NEVER glob SR-*.kicad_sym: the nine real
  libraries carry 2-29 symbols each and a glob sweeps them up.
- The enrich cache is per-device today (libraries_root.parent/.stockroom-enrich-cache), so two
  machines can show DIFFERENT specs for the same part. Per-machine state that changes what the user
  SEES is a parity break; move it or justify it in writing.`,
      { label: 'device-sync', phase: 'Independent', isolation: 'worktree', schema: BRANCH_RESULT },
    ),
])

// ---------------------------------------------------------------------------------------------
// The schema track is strictly sequential at its root: everything downstream reads the model. It
// runs in the MAIN worktree, which is free because every Independent agent is off in its own.
phase('Model')

const model = await agent(
  `${RULES}
TASK: THE PART RECORD MODEL. Implement section 9 of ${SPEC} exactly - the shape is already decided
and drawn out there. Do not redesign it.

You are in the MAIN worktree (/home/sadad/git/stockroom) on branch main, which already has a .venv.
Commit your work directly to main, scoped, and leave the tree CLEAN.

- parts/<id>.json holds identity + part_class + a DERIVED block + asset refs + a sources index.
- sourced/<id>/<vendor>.json holds the raw payload byte-for-byte as returned. It is APPEND-ONLY
  evidence: a re-derive READS it and never writes it. It MUST be git-tracked (device parity settles
  this - a per-machine cache would let two devices derive different values for the same part).
- id = slug(mpn) + "-" + sha256(mpn)[:4]. Lowercase [a-z0-9-]. Guard Windows reserved stems
  (CON, PRN, AUX, NUL, COM1..LPT9). The hash exists because slugging is LOSSY and collides:
  MAX6817EUT+T (which the owner owns) and MAX6817EUT-T both slug to max6817eut_t.
- part_class is passive | component | mechanical | virtual, with a requires_override escape hatch.
- Every asset carries origin {vendor, url, captured_at} and a checks[] list of measurements. The
  trust VERDICT is derived from checks on read and is NEVER stored (spec D2).
- Bump SCHEMA_VERSION. NOTE THE EXISTING BUG: PartRecord.from_dict does
  max(SCHEMA_VERSION, ...), which RELABELS a v1 record as current without migrating its data. The
  owner is deleting and re-importing so no migration is needed, but do not reproduce that bug.

Return a summary of the dataclasses and fields you created, precise enough that another agent can
write code against them WITHOUT reading your diff: module paths, class names, every field and type.`,
  { label: 'part-record', phase: 'Model' },
)

// ---------------------------------------------------------------------------------------------
// SPEED NOTE. These three touch overlapping backend files (model/, store/, capture/), so they run
// in ISOLATED WORKTREES. Without isolation they serialise on each other's edits, which is what
// makes a nominally parallel phase secretly sequential - the single biggest hidden cost in a
// fan-out over one repo. They branch off main AFTER the model commit, so they all see it.
phase('OnModel')

const onModel = await parallel([
  () =>
    agent(
      `${RULES}${worktreeSetup('wf/derive-engine')}
The part record model has landed on main: ${model}

TASK: THE DERIVE ENGINE. One function that recomputes the entire 'derived' block from sourced/.

THE ACCEPTANCE TEST FOR THE WHOLE SCHEMA, straight from the owner - "we can edit it without
reimporting":
  1. IDEMPOTENT: run the derive twice, get byte-identical records.
  2. LOSSLESS: a derive NEVER writes anything under sourced/.
  3. A naming-scheme change is a RE-DERIVE, not a re-import, and loses nothing.
Write those three as real tests.

- Normalization MOVES here from import time. Today spec_hygiene.normalize_spec_key/value rewrites
  values on the way in and the raw winning value is lost forever - that is the bug this fixes.
- Derives display_name, value, category, description and normalized specs from the raw payloads.
- Identity (id, mpn, manufacturer, part_class) is NEVER touched by a derive.
- Conflicts between sources: keep the existing per-key source+confidence and alternates behaviour,
  but derive it rather than storing a mutated winner.`,
      { label: 'derive-engine', phase: 'OnModel', isolation: 'worktree', schema: BRANCH_RESULT },
    ),

  () =>
    agent(
      `${RULES}${worktreeSetup('wf/requirements')}
The part record model has landed on main: ${model}

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
  test_the_enum_covers_exactly_the_registry green.`,
      { label: 'requirements', phase: 'OnModel', isolation: 'worktree', schema: BRANCH_RESULT },
    ),

  () =>
    agent(
      `${RULES}${worktreeSetup('wf/index-schema')}
The part record model has landed on main: ${model}

TASK: THE DERIVED INDEX. Rewrite store/index.py, which is measurably wrong for this project's scope.

Defects to fix, all verified by reading the DDL:
- It is SINGLE-TOOL and SINGLE-ASSET: footprint_name, model_file, datasheet_file, purchase_url are
  all singular and implicitly KiCad. There is NO Altium column, so the index physically cannot
  express "has an Altium footprint". This is the flat-implicitly-KiCad anti-pattern the repo's own
  CLAUDE.md forbids. Make it per-tool by iterating the EDA registry.
- purchase_url is singular for a part with Mouser + DigiKey + LCSC rows.
- 'DROP TABLE IF EXISTS parts' means a FULL rebuild every sync - roughly 100 MB of JSON re-read at
  10,000 parts. Make it incremental.
- is_complete + missing bake presence-as-completeness into SQL. The index must be able to express
  TRUST (derived from the assets' checks), not just presence.
Keep every existing read path (search, facets, parametric filters) green.`,
      { label: 'index-schema', phase: 'OnModel', isolation: 'worktree', schema: BRANCH_RESULT },
    ),
])

// ---------------------------------------------------------------------------------------------
// Land everything built so far on main. This phase exists because the previous version of this
// script never merged the worktree branches at all: the OnDerive importer was told "the derive
// engine landed" while running against a tree that did not contain it.
phase('MergeA')

const independentResults = (await independent).filter(Boolean)
const onModelResults = onModel.filter(Boolean)
const branchesA = [...independentResults, ...onModelResults]
  .filter((r) => r && r.committed && r.branch)
  .map((r) => r.branch)

log(`MergeA: landing ${branchesA.length} branches on main - ${branchesA.join(', ')}`)

const mergeA = await agent(
  `${RULES}
TASK: MERGE. Land these branches on main IN THIS ORDER, in the MAIN worktree
(/home/sadad/git/stockroom): ${JSON.stringify(branchesA)}

Context for resolving conflicts:
- The part record model: ${model}
- What each branch built: ${JSON.stringify([...independentResults, ...onModelResults].map((r) => ({ branch: r.branch, summary: r.summary, notDone: r.notDone })))}

- 'git merge --no-ff <branch>' one at a time. After EACH merge, run the backend gate
  (QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend -q -n auto) so you know which
  merge broke what. Merging all of them and then testing tells you nothing about which one is at fault.
- RESOLVE conflicts on the merits, using the spec and the summaries above. Never resolve by taking
  one side wholesale without reading both - these branches were written against the same model and a
  blind --ours/--theirs silently deletes real work.
- If a branch cannot be landed without breaking the suite, do NOT force it: leave it unmerged, say
  which one and exactly what broke, and continue with the rest.
- These branches were built in parallel against the same base, so overlapping edits to
  capture/requirements.py, store/index.py and model/ are EXPECTED. Reconcile them into one coherent
  implementation rather than stacking two versions of the same idea.
- Finish with: full backend suite, ruff, and (if any frontend changed) npm run test:run + typecheck +
  build with app/frontend-dist committed. Leave main CLEAN and every gate result stated verbatim.
- Do NOT push. Report which branches landed, which did not, and why.`,
  { label: 'merge-a', phase: 'MergeA', effort: 'high' },
)

// ---------------------------------------------------------------------------------------------
phase('OnDerive')

const onDerive = await parallel([
  () =>
    agent(
      `${RULES}${worktreeSetup('wf/importer')}
Model: ${model}
Landed on main by the merge phase: ${mergeA}

TASK: THE IMPORTER. The owner is DELETING the library and re-importing, so there is NO migration to
write - build the importer the rebuild will use.

- Input: a list of MPNs (the register). Sources: Mouser and DigiKey, both with live credentials in
  the machine config. LCSC is available but the owner has ruled its CAD out; its DATA is still fine.
- Writes sourced/<id>/<vendor>.json verbatim, then a first derived block. NO ASSETS - those come
  from the capture pass later and must attach without rewriting sourced or derived.
- Classify each part into passive | component | mechanical | virtual on import.
- Mouser is rate-limited at 30/min and 1000/day; DigiKey has its own. Pace, back off, and make a
  rate-limited part DEFERRED (retry later) rather than FAILED (nothing can help it) - conflating
  those two makes the report useless. capture/pacing.py already implements exactly this pattern;
  reuse it rather than writing a second one.
- The run must be stoppable and resumable, and the worklist DERIVED from library state so a re-run
  is free on parts already done. capture/complete.py is the proven shape.`,
      { label: 'importer', phase: 'OnDerive', isolation: 'worktree', schema: BRANCH_RESULT },
    ),

  () =>
    agent(
      `${RULES}${worktreeSetup('wf/guided-capture')}
Model: ${model}
Landed on main by the merge phase: ${mergeA}

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
  it deliberately, and critique your own screenshot element by element before calling it done.`,
      { label: 'guided-capture', phase: 'OnDerive', isolation: 'worktree', schema: BRANCH_RESULT },
    ),
])

// ---------------------------------------------------------------------------------------------
phase('MergeB')

const onDeriveResults = onDerive.filter(Boolean)
const branchesB = onDeriveResults.filter((r) => r && r.committed && r.branch).map((r) => r.branch)

log(`MergeB: landing ${branchesB.length} branches on main - ${branchesB.join(', ')}`)

const mergeB = await agent(
  `${RULES}
TASK: MERGE. Land these branches on main, in order, in the MAIN worktree
(/home/sadad/git/stockroom): ${JSON.stringify(branchesB)}

What each built: ${JSON.stringify(onDeriveResults.map((r) => ({ branch: r.branch, summary: r.summary, notDone: r.notDone })))}

Same rules as the earlier merge: '--no-ff' one at a time, run the backend gate after EACH so you
know which merge broke what, resolve conflicts on the merits rather than by taking a side wholesale,
and leave any branch that cannot land unmerged with a plain statement of what broke.

The guided-capture branch carries frontend changes: after merging it, run npm ci if needed, then
npm run test:run, npm run typecheck and npm run build, and make sure app/frontend-dist/ on main
matches the merged source. A stale dist is what the backend would actually serve.

Finish with every gate stated verbatim, main CLEAN, and no push.`,
  { label: 'merge-b', phase: 'MergeB', effort: 'high' },
)

// ---------------------------------------------------------------------------------------------
phase('Verify')

const verdicts = await parallel([
  () =>
    agent(
      `${RULES}
TASK: PROVE THE ACCEPTANCE TEST on the real code, not in principle. Work in the MAIN worktree, which
now carries every landed branch: ${mergeA}\n${mergeB}

The owner's requirement is "we can edit it without reimporting". Demonstrate it end to end:
  1. Import a handful of real parts (Mouser creds are live).
  2. Run the derive. Run it AGAIN. Prove the records are byte-identical (idempotent).
  3. Prove nothing under sourced/ was written by either derive (lossless).
  4. CHANGE the naming scheme, re-derive, and show display_name changed while sourced/ and identity
     did not.
Do NOT touch the owner's real library - work against a scratch library directory.
Report the actual commands and their actual output. If any step fails, say so plainly - a failed
acceptance test reported honestly is worth far more than a green claim.`,
      { label: 'acceptance-test', phase: 'Verify', effort: 'high' },
    ),

  () =>
    agent(
      `${RULES}
TASK: ADVERSARIALLY REVIEW every diff this workflow produced. Try to REFUTE each piece of work.
Review the diff of main against ${'a56b918'} (the commit this workflow started from). You are
READ-ONLY: report findings, do not fix them and do not commit.

Look specifically for the failure patterns this project has actually shipped:
- A check that CANNOT FAIL. Feed every new detector a known-BAD input and confirm it says so. A
  coverage probe here once returned an identical answer for a real part and for a fabricated MPN.
- A LOOSE pattern. A package-vs-pad audit here reported 16 mismatches and all 16 were false
  positives because it read "SOT-23" as 23 pins.
- Requirements or completeness that measure PRESENCE while reading like TRUST.
- Any 'if tool == ...' branch in shared logic instead of iterating the registry.
- A success message emitted by the code that STARTED the work rather than the code that OBSERVED it.
- Anything that writes under sourced/ outside the importer.
- Work LOST in the merges: a field, test or behaviour a branch summary claims that main does not
  actually have. A parallel fan-out plus a conflict resolution is exactly where that happens.
Report confirmed findings with file:line and a concrete failure scenario. Do not report style.`,
      { label: 'adversarial-review', phase: 'Verify', effort: 'high' },
    ),
])

log('rebuild-library complete - read the acceptance test and the adversarial review before shipping')

return {
  independent: independentResults,
  model,
  onModel: onModelResults,
  mergeA,
  onDerive: onDeriveResults,
  mergeB,
  verdicts: verdicts.filter(Boolean),
  unlanded: [...independentResults, ...onModelResults, ...onDeriveResults]
    .filter((r) => r && !r.committed)
    .map((r) => r.branch),
}
