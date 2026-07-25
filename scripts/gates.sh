#!/usr/bin/env bash
# Every verify gate in one command, in the cheapest-fails-first order.
#
# Why this exists: these four commands were retyped on every slice, which wasted time and, worse,
# invited running only some of them. One entry point means "gates green" has the same meaning every
# time, and the backend suite runs PARALLEL by default (pytest-xdist, ~2m45s across 24 cores instead
# of the 8-9 minutes it took serially).
#
#   scripts/gates.sh              # everything
#   scripts/gates.sh backend      # backend suite only
#   scripts/gates.sh frontend     # frontend tests + typecheck + build
#   scripts/gates.sh quick        # typecheck + a serial-safe backend subset, for a tight loop
#   scripts/gates.sh types        # ty (advisory: NOT a gate yet, see the punch list)
#
# SERIAL_TESTS=1 forces the single-process run. Use it when a failure might itself be a parallelism
# artifact: if a test passes serially but fails under -n auto, the test shares state, and that is a
# real defect in the test rather than a reason to abandon parallelism.
set -uo pipefail
cd "$(dirname "$0")/.."

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

backend() {
  local n=(-n auto)
  [[ "${SERIAL_TESTS:-0}" == "1" ]] && n=()
  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend -q -p no:randomly "${n[@]}"
}
fe() { npm --prefix app/frontend run "$1"; }

case "${1:-all}" in
  backend)  run "backend suite" backend ;;
  frontend) run "frontend tests" fe test:run
            run "typecheck" fe typecheck
            run "build" fe build ;;
  quick)    run "typecheck" fe typecheck
            run "backend (projects+store+model)" env QT_QPA_PLATFORM=offscreen \
                .venv/bin/python -m pytest tests/backend/projects tests/backend/store \
                tests/backend/model -q -p no:randomly ;;
  types)    run "ty (advisory)" .venv/bin/ty check app/backend/stockroom ;;
  all)      run "typecheck" fe typecheck
            run "frontend tests" fe test:run
            run "backend suite" backend
            run "build" fe build ;;
  *) echo "usage: $0 [all|backend|frontend|quick|types]" >&2; exit 2 ;;
esac

# The build must be the LAST thing that ran before a commit, because app/frontend-dist/ is what the
# backend serves and it has to be committed with the source.
if ((${#FAILED[@]})); then
  printf '\n\033[31m%d GATE(S) FAILED:\033[0m %s\n' "${#FAILED[@]}" "${FAILED[*]}"
  exit 1
fi
printf '\n\033[32mAll gates passed.\033[0m Remember: commit app/frontend-dist/ with the source.\n'
