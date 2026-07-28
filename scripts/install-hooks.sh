#!/usr/bin/env bash
# Point git at the repo's tracked hooks. Run once per clone.
#
# `core.hooksPath` rather than copying into `.git/hooks`: a copy drifts the moment the tracked
# version changes, and nothing would say so. This way the hooks a clone runs ARE the committed
# ones, which is the same reason this project keeps its gates in the repo rather than in a wiki.
set -euo pipefail
cd "$(dirname "$0")/.."
git config core.hooksPath scripts/hooks

# git-lfs keeps its own hooks (pre-push, post-checkout, post-merge) and writes them into whatever
# `core.hooksPath` names - so it has to run AFTER the line above, or it writes them into
# `.git/hooks` where nothing will ever call them. Doing it here rather than committing the
# generated files means every clone gets the version its OWN git-lfs emits, and a peer who forgets
# `git lfs install` still ends up with working LFS instead of silently pushing raw binaries.
# Non-fatal: a machine without git-lfs can still develop, it just cannot fetch the binaries.
#
# It reports its OWN outcome rather than being chained onto an `&&` that swallows a failure: with
# `scripts/hooks/post-commit` already present and authored by this repo, `git lfs install` REFUSES
# (it will not clobber a hook it did not write) and exits non-zero. That is the correct refusal,
# but the first version of this block printed nothing at all in that case - a silent failure, which
# is the shape this repo has been burned by most.
if ! command -v git-lfs >/dev/null 2>&1; then
    echo "WARNING: git-lfs is not installed, so the library's binary payloads will not resolve." >&2
elif git lfs install --local >/dev/null 2>&1; then
    echo "git-lfs hooks generated"
else
    # --force is deliberately NOT used: it would overwrite the authored post-commit hook that
    # re-renders the progress page. Naming the two hooks LFS actually needs keeps the check honest.
    missing=""
    for h in pre-push post-checkout; do
        [ -f "scripts/hooks/$h" ] || missing="$missing $h"
    done
    if [ -n "$missing" ]; then
        echo "WARNING: git-lfs could not install these hooks:$missing" >&2
        echo "         Run 'git lfs update --manual' and merge them by hand." >&2
    else
        echo "git-lfs hooks already present (it declined to touch the authored post-commit hook)"
    fi
fi

echo "hooks wired: $(git config core.hooksPath)"
ls -1 scripts/hooks
