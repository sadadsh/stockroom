#!/usr/bin/env bash
# Point git at the repo's tracked hooks. Run once per clone.
#
# `core.hooksPath` rather than copying into `.git/hooks`: a copy drifts the moment the tracked
# version changes, and nothing would say so. This way the hooks a clone runs ARE the committed
# ones, which is the same reason this project keeps its gates in the repo rather than in a wiki.
set -euo pipefail
cd "$(dirname "$0")/.."
git config core.hooksPath scripts/hooks
echo "hooks wired: $(git config core.hooksPath)"
ls -1 scripts/hooks
