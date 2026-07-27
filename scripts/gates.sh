#!/usr/bin/env bash
# Every verify gate in one command, in the cheapest-fails-first order.
#
# Why this exists: these four commands were retyped on every slice, which wasted time and, worse,
# invited running only some of them. One entry point means "gates green" has the same meaning every
# time, and the backend suite runs PARALLEL by default (pytest-xdist, ~2m45s across 24 cores instead
# of the 8-9 minutes it took serially).
#
#   scripts/gates.sh              # everything
#   scripts/gates.sh lint         # ruff (fast; run it first, it fails in under a second)
#   scripts/gates.sh backend      # backend suite only
#   scripts/gates.sh since [REF]  # ONLY the tests for files changed vs REF (default HEAD).
#                                 # Seconds, not minutes. A LOOP tool, never a gate.
#   scripts/gates.sh frontend     # frontend tests + typecheck + build
#   scripts/gates.sh quick        # typecheck + a serial-safe backend subset, for a tight loop
#   scripts/gates.sh types        # ty (advisory: NOT a gate yet, see the punch list)
#   scripts/gates.sh bg           # start the backend suite detached, print the log path
#   scripts/gates.sh await        # block until the detached run finishes, print its summary line
#
# `bg` + `await` exist because the backend suite takes ~2m and the useful thing to do meanwhile is
# keep working. That was being hand-written every time as a nohup plus a sleep-and-grep loop, three
# times in one session, so it is a subcommand now. `await` polls for the pytest SUMMARY LINE, which
# is a real success/failure signal, and gives up on its own ceiling rather than looping forever: a
# timeout here means the run died without writing a summary, which is a defect worth seeing.
#
# SERIAL_TESTS=1 forces the single-process run. Use it when a failure might itself be a parallelism
# artifact: if a test passes serially but fails under -n auto, the test shares state, and that is a
# real defect in the test rather than a reason to abandon parallelism.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

FAILED=()
run() {  # run <label> <cmd...>
  local label="$1"; shift
  printf '\n\033[1m== %s ==\033[0m\n' "$label"
  if "$@"; then
    printf '\033[32mPASS\033[0m  %s\n' "$label"
  else
    printf '\033[31mFAIL\033[0m  %s\n' "$label"
    FAILED+=("$label")
  fi
}

# MEASURED 2026-07-27 on the owner's box (Ryzen 9 7900X, 12 physical cores / 24 threads, /tmp on
# ext4). Same slice, three runs:
#   -n auto (=24 workers) on disk-backed /tmp .... 51.5 s
#   -n 24   on RAM-backed tmp .................... 51.5 s -> tmpfs alone bought ~15% on a git-heavy slice
#   -n 12   on RAM-backed tmp .................... 46.7 s  <- best
# `-n auto` reads LOGICAL cores and oversubscribes 12 physical ones, and this suite is dominated by
# git subprocess I/O rather than CPU, so more workers meant more contention, not more throughput.
# PYTEST_WORKERS overrides; SERIAL_TESTS=1 still forces one process.
TMPBASE="${GATES_TMPDIR:-/dev/shm/pytest-stockroom}"
backend() {
  local n=(-n "${PYTEST_WORKERS:-12}")
  [[ "${SERIAL_TESTS:-0}" == "1" ]] && n=()
  mkdir -p "$TMPBASE"
  # A RAM-backed temp dir is safe to wipe: pytest owns everything under it. If /dev/shm is too
  # small on some other machine, GATES_TMPDIR points this back at a disk path.
  QT_QPA_PLATFORM=offscreen TMPDIR="$TMPBASE" \
    .venv/bin/python -m pytest tests/backend -q -p no:randomly "${n[@]}" --basetemp="$TMPBASE/bt"
  local rc=$?
  rm -rf "${TMPBASE:?}/bt" 2>/dev/null
  return $rc
}

# The single biggest time sink is not the suite, it is running the WHOLE suite after every small
# edit. `since` runs only the test files touching what git says changed, which is seconds instead
# of minutes. It is a LOOP tool, never a gate: it can miss a caller it does not know about, so the
# full suite still has to pass before a commit.
since() {
  local base="${1:-HEAD}"
  mapfile -t changed < <(git diff --name-only "$base" -- '*.py' | grep -E '^(app/backend|tests)/' || true)
  if [[ ${#changed[@]} -eq 0 ]]; then echo "no python changes vs $base"; return 0; fi
  local targets=()
  for f in "${changed[@]}"; do
    [[ "$f" == tests/* ]] && { targets+=("$f"); continue; }
    # map app/backend/stockroom/<pkg>/<mod>.py -> tests/backend/<pkg>/test_<mod>.py when it exists
    local pkg mod
    pkg="$(basename "$(dirname "$f")")"; mod="$(basename "$f" .py)"
    for cand in "tests/backend/$pkg/test_$mod.py" "tests/backend/$pkg"; do
      [[ -e "$cand" ]] && { targets+=("$cand"); break; }
    done
  done
  mapfile -t targets < <(printf '%s\n' "${targets[@]}" | sort -u)
  printf 'running %d target(s) for %d changed file(s): %s\n' \
    "${#targets[@]}" "${#changed[@]}" "${targets[*]}"
  mkdir -p "$TMPBASE"
  QT_QPA_PLATFORM=offscreen TMPDIR="$TMPBASE" \
    .venv/bin/python -m pytest "${targets[@]}" -q -p no:randomly -n "${PYTEST_WORKERS:-12}" \
    --basetemp="$TMPBASE/bt-since"
}
fe() { npm --prefix app/frontend run "$1"; }
# ruff was CONFIGURED in pyproject.toml and enforced by nothing until 2026-07-26. Its first
# repo-wide run found 48 issues, including a duplicate dict key in the LCSC field map and two
# computed-then-dropped variables. Scoped to hand-authored code: `skills/` alone produces over a
# thousand third-party findings, and an ignored linter is decoration.
lint() { .venv/bin/ruff check app/backend scripts tests; }

ROOT="$PWD"
BG_LOG="${GATES_BG_LOG:-build/gates-backend.log}"

case "${1:-all}" in
  lint)     run "ruff" lint ;;
  backend)  run "backend suite" backend ;;
  since)    since "${2:-HEAD}" ;;
  bg)       mkdir -p "$(dirname "$BG_LOG")"
            : > "$BG_LOG"
            # The child re-invokes THIS script's own `backend` mode from an absolute path, so there
            # is exactly one pytest invocation to maintain and the child's $0 resolves correctly.
            # Sourcing it with a flag instead looked tidier and was broken: in a sourced script $0 is
            # "bash", so `cd $(dirname $0)/..` walked OUT of the repo and .venv/bin/python vanished.
            setsid nohup "$ROOT/scripts/gates.sh" backend >>"$BG_LOG" 2>&1 &
            echo $! > "$BG_LOG.pid"
            echo "backend suite started detached; log: $BG_LOG"
            echo "wait for it with: $0 await"
            exit 0 ;;
  await)    [[ -f "$BG_LOG" ]] || { echo "no detached run: $BG_LOG is absent" >&2; exit 2; }
            pid="$(cat "$BG_LOG.pid" 2>/dev/null || echo 0)"
            deadline=$(( $(date +%s) + ${GATES_AWAIT_TIMEOUT:-900} ))
            while (( $(date +%s) < deadline )); do
              # SUCCESS signal: pytest's own summary line.
              if grep -qE '[0-9]+ (passed|failed|error)' "$BG_LOG"; then
                grep -E '^FAILED|[0-9]+ (passed|failed|error)' "$BG_LOG" | tail -20
                grep -qE '[0-9]+ (failed|error)' "$BG_LOG" && exit 1
                exit 0
              fi
              # FAILURE signal, checked every cycle so a child that died never costs the ceiling.
              # This is the whole point: waiting out a clock tells you only that time passed.
              if [[ "$pid" != 0 ]] && ! kill -0 "$pid" 2>/dev/null; then
                echo "the detached run exited without a pytest summary:" >&2
                tail -20 "$BG_LOG" >&2
                exit 1
              fi
              sleep 5
            done
            echo "TIMEOUT: no pytest summary in $BG_LOG. The run died without reporting, which is" >&2
            echo "a gap in the observation, not a normal outcome. Read the log." >&2
            exit 5 ;;
  frontend) run "frontend tests" fe test:run
            run "typecheck" fe typecheck
            run "build" fe build ;;
  quick)    run "ruff" lint
            run "typecheck" fe typecheck
            run "backend (projects+store+model)" env QT_QPA_PLATFORM=offscreen \
                .venv/bin/python -m pytest tests/backend/projects tests/backend/store \
                tests/backend/model -q -p no:randomly ;;
  types)    run "ty (advisory)" .venv/bin/ty check app/backend/stockroom ;;
  all)      run "ruff" lint
            run "typecheck" fe typecheck
            run "frontend tests" fe test:run
            run "backend suite" backend
            run "build" fe build ;;
  *) echo "usage: $0 [all|lint|backend|frontend|quick|types|bg|await]" >&2; exit 2 ;;
esac

# The build must be the LAST thing that ran before a commit, because app/frontend-dist/ is what the
# backend serves and it has to be committed with the source.
if ((${#FAILED[@]})); then
  printf '\n\033[31m%d GATE(S) FAILED:\033[0m %s\n' "${#FAILED[@]}" "${FAILED[*]}"
  exit 1
fi
printf '\n\033[32mAll gates passed.\033[0m Remember: commit app/frontend-dist/ with the source.\n'
