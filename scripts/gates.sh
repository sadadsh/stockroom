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
#   scripts/gates.sh bg all      # detach ANY scope (default: backend), not just the suite
#   scripts/gates.sh await       # block until the detached run finishes, print its summary line
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
# PER-RUN, not shared. `backend()` wipes its basetemp when it finishes, so two runs sharing one
# directory means whichever ends first deletes the other's temp files out from under it. Measured
# 2026-07-27, the moment `bg` made concurrent runs easy: a second suite started while one was
# running produced **1655 errors** that had nothing to do with the code. $$ is this shell's pid.
TMPBASE="${GATES_TMPDIR:-/dev/shm/pytest-stockroom-$$}"

# REAP STALE BASETEMPS BEFORE RUNNING, because a full tmpfs does NOT fail as "disk full".
#
# Measured 2026-07-27, and it cost most of an hour plus one wrong diagnosis: /dev/shm was 4.5 GB
# full of basetemps left by killed runs and by a SECOND external tool session. Playwright's `save_as` then
# cannot write the download, and the capture tests fail as "a submitted capture reported no file at
# all" - which reads exactly like a capture bug. I blamed a code change and reverted it; the revert
# changed nothing, because the cause was the disk.
#
# Only directories whose owning PID is GONE are removed, so a concurrent run is never touched (that
# is the 1655-error footgun noted above, from the other direction).
reap_stale_tmp() {
  local parent; parent="$(dirname "$TMPBASE")"
  [[ -d "$parent" ]] || return 0
  local d pid
  for d in "$parent"/pytest-stockroom-*; do
    [[ -d "$d" ]] || continue
    pid="${d##*-}"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    kill -0 "$pid" 2>/dev/null && continue   # a LIVE run owns it
    rm -rf "$d" 2>/dev/null && echo "reaped stale basetemp $d (pid $pid is gone)"
  done
  # Report what is left if it is still tight. A warning, not a block: the threshold is a guess, but
  # a NUMBER the reader can act on is not.
  local avail_kb; avail_kb="$(df -Pk "$parent" 2>/dev/null | awk 'NR==2{print $4}')"
  if [[ -n "$avail_kb" && "$avail_kb" -lt 2097152 ]]; then
    printf '\033[31mWARNING\033[0m  only %s MiB free on %s - downloads may fail SILENTLY.\n' \
      "$((avail_kb / 1024))" "$parent" >&2
    du -sh "$parent"/* 2>/dev/null | sort -rh | head -5 >&2
  fi
}

backend() {
  local n=(-n "${PYTEST_WORKERS:-12}")
  [[ "${SERIAL_TESTS:-0}" == "1" ]] && n=()
  reap_stale_tmp
  mkdir -p "$TMPBASE"
  # A RAM-backed temp dir is safe to wipe: pytest owns everything under it. If /dev/shm is too
  # small on some other machine, GATES_TMPDIR points this back at a disk path.
  # --dist loadgroup, not the default load. pytest-xdist 3.8's own --help: "Like 'load', but sends
  # tests marked with 'xdist_group' to the same worker" - so UNGROUPED tests distribute exactly as
  # before and nothing else changes. It exists for the real-source STM tests, which share one ~235 MB
  # index; scattered across workers they each saw an empty directory and failed (measured
  # 2026-07-27).
  QT_QPA_PLATFORM=offscreen TMPDIR="$TMPBASE" \
    .venv/bin/python -m pytest tests/backend -q -p no:randomly --dist loadgroup "${n[@]}" \
    --basetemp="$TMPBASE/bt"
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
    .venv/bin/python -m pytest "${targets[@]}" -q -p no:randomly --dist loadgroup \
    -n "${PYTEST_WORKERS:-12}" --basetemp="$TMPBASE/bt-since"
}
fe() { npm --prefix app/frontend run "$1"; }
# ruff was CONFIGURED in pyproject.toml and enforced by nothing until 2026-07-26. Its first
# repo-wide run found 48 issues, including a duplicate dict key in the LCSC field map and two
# computed-then-dropped variables. Scoped to hand-authored code: `skills/` alone produces over a
# thousand third-party findings, and an ignored linter is decoration.
lint() { .venv/bin/ruff check app/backend scripts tests; }

# Run pytest against ONE path, with the same parallelism and RAM temp dir the full suite uses, so
# a targeted run and the gate cannot disagree about the environment they ran in.
pytest_path() {
  local target="$1"
  local n=(-n "${PYTEST_WORKERS:-12}")
  [[ "${SERIAL_TESTS:-0}" == "1" ]] && n=()
  reap_stale_tmp
  mkdir -p "$TMPBASE"
  QT_QPA_PLATFORM=offscreen TMPDIR="$TMPBASE" \
    .venv/bin/python -m pytest "$target" -q -p no:randomly "${n[@]}" --basetemp="$TMPBASE/bt"
  local rc=$?
  rm -rf "$TMPBASE/bt"
  return $rc
}

ROOT="$PWD"
BG_LOG="${GATES_BG_LOG:-build/gates-backend.log}"

case "${1:-all}" in
  lint)     run "ruff" lint ;;
  backend)  run "backend suite" backend ;;
  # A pytest PATH is a first-class scope, so `bg tests/backend/capture` works and `await` reports
  # it exactly like any other. Without this, backgrounding one slow file meant hand-rolled polling.
  tests|tests/*) run "pytest ${1}" pytest_path "$1" ;;
  since)    since "${2:-HEAD}" ;;
  bg)       # `bg [scope]` detaches ANY scope, not just the backend. It used to hardcode `backend`,
            # so a FULL gate run had no detached mode at all -- and the way round that was to
            # redirect it to a file and hand-poll with an `until grep` loop, which is a step
            # nothing verifies and which got retyped three times in one session before the
            # repeat-detector called it. `await` reads the same log either way.
            scope="${2:-backend}"
            case "$scope" in
              all|lint|backend|frontend|quick|types) ;;
              # A PYTEST PATH is a scope too. Without this, backgrounding one slow test file meant
              # hand-rolling `pytest ... > log &` plus a `ps`/`pgrep` poll - which is how a dozen
              # self-matching wait loops got created in one session, none of which could ever exit
              # (their own argv contained the pattern they polled for). `await` already keys on a
              # pid file and a .done marker, so routing a path through here inherits both.
              tests/*|tests) [[ -e "$ROOT/${scope%%::*}" ]] || {
                     echo "no such test path: $scope" >&2; exit 2; } ;;
              *) echo "usage: $0 bg [all|lint|backend|frontend|quick|types|<tests/... path>]" >&2
                 exit 2 ;;
            esac
            mkdir -p "$(dirname "$BG_LOG")"
            : > "$BG_LOG"
            # The child re-invokes THIS script from an absolute path, so there is exactly one
            # pytest invocation to maintain and the child's $0 resolves correctly. Sourcing it with
            # a flag instead looked tidier and was broken: in a sourced script $0 is "bash", so
            # `cd $(dirname $0)/..` walked OUT of the repo and .venv/bin/python vanished.
            # A COMPLETION MARKER, written by the work itself, is the terminal signal.
            # `$!` here is SETSID's pid, and setsid forks and exits the moment it has made the
            # child a session leader -- so `kill -0 $!` goes false within milliseconds and any
            # await built on it returns almost immediately. Measured 2026-07-27: a `bg all`
            # awaited that way came back green in 45s on a run that needs ~3min.
            rm -f "$BG_LOG.done"
            setsid nohup bash -c \
              '"$1" "$2" >>"$3" 2>&1; echo $? > "$3.done"' _ \
              "$ROOT/scripts/gates.sh" "$scope" "$ROOT/$BG_LOG" &
            echo $! > "$BG_LOG.pid"
            echo "$scope started detached; log: $BG_LOG"
            echo "wait for it with: $0 await"
            exit 0 ;;
  await)    [[ -f "$BG_LOG" ]] || { echo "no detached run: $BG_LOG is absent" >&2; exit 2; }
            pid="$(cat "$BG_LOG.pid" 2>/dev/null || echo 0)"
            # REFUSE A STALE LOG. Without this, `await` happily reports the summary of a run that
            # finished HOURS ago as though it were the run you are waiting on -- measured
            # 2026-07-27, when it printed "3037 passed" from a log dated the previous afternoon
            # while a completely different suite was still running. That is a green signal not
            # wired to the fact it claims, which is the exact failure mode this repo bans.
            #
            # The check is a FACT, not a heuristic: a live pid means a real run; no live pid plus
            # an already-complete log means the log describes a PREVIOUS run and there is nothing
            # to await. Say so and exit non-zero rather than answering the wrong question.
            # REFUSE A STALE LOG: a marker that already exists means the log describes a run
            # that FINISHED, so there is nothing to await. Answering from it would report an old
            # result as the current one -- measured 2026-07-27, when this printed "3037 passed"
            # from the previous afternoon's log while a different suite was still running.
            if [[ -f "$BG_LOG.done" ]]; then
              echo "no detached run is in flight; $BG_LOG is a COMPLETED earlier run" >&2
              echo "  (last written: $(date -r "$BG_LOG" '+%Y-%m-%d %H:%M:%S'))" >&2
              echo "  start one with: $0 bg [scope]" >&2
              exit 2
            fi
            deadline=$(( $(date +%s) + ${GATES_AWAIT_TIMEOUT:-900} ))
            waited=0
            while (( $(date +%s) < deadline )); do
              # THE TERMINAL SIGNAL IS THE MARKER THE RUN WRITES WHEN IT EXITS, carrying its
              # exit code. Not a line in the log: a scope that runs several gates prints an
              # INTERMEDIATE summary partway through, and polling for one returned 0 on a `bg all`
              # while the backend suite was still going. Not the pid either: `$!` is setsid's, and
              # setsid exits immediately. The marker is written BY THE WORK, after the work.
              if [[ -f "$BG_LOG.done" ]]; then
                grep -aE '^FAILED|^PASS  |^FAIL  |All gates passed|[0-9]+ (passed|failed|error)' \
                  "$BG_LOG" | tail -20
                exit "$(cat "$BG_LOG.done")"
              fi
              # SAY THAT IT IS ALIVE. This printed nothing at all while waiting, which is
              # indistinguishable from a hang - and on 2026-07-27 that is exactly how it read, so
              # `await` was abandoned mid-session and the same until-grep loop was hand-written
              # THREE times instead. A silent correct tool loses to a noisy wrong one, so the fix
              # belongs in the tool. Reports the newest progress marker the scope actually emits.
              if (( waited % 30 == 0 )); then
                stage="$(grep -aoE '^== .* ==|\[ *[0-9]+%\]' "$BG_LOG" | tail -1)"
                printf '\r  ...still running (%ds) %s' "$waited" "${stage:-starting}" >&2
              fi
              sleep 5
              waited=$(( waited + 5 ))
            done
            echo >&2
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
  *) echo "usage: $0 [all|lint|backend|frontend|quick|types|since <ref>|bg [scope]|await]" >&2
     exit 2 ;;
esac

# The build must be the LAST thing that ran before a commit, because app/frontend-dist/ is what the
# backend serves and it has to be committed with the source.
if ((${#FAILED[@]})); then
  printf '\n\033[31m%d GATE(S) FAILED:\033[0m %s\n' "${#FAILED[@]}" "${FAILED[*]}"
  exit 1
fi
printf '\n\033[32mAll gates passed.\033[0m Remember: commit app/frontend-dist/ with the source.\n'
