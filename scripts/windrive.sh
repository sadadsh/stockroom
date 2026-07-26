#!/usr/bin/env bash
# Run the Windows-side `windrive.py` against the real install, from WSL, in one command.
#
# PROMOTED 2026-07-26 after typing the raw form three times in one session:
#
#   cmd.exe /c "cd /d %LOCALAPPDATA%\Stockroom\app && py scripts\windrive.py hosts"
#
# which is long, easy to get subtly wrong, and prints three lines of UNC noise every time
# because cmd.exe cannot use a WSL working directory. This wrapper fixes all three:
#
#   scripts/windrive.sh hosts
#   scripts/windrive.sh down --all
#   scripts/windrive.sh up
#   scripts/windrive.sh tour --shots
#
# NOT hardcoded to one machine: the install directory is discovered through `%LOCALAPPDATA%`,
# which cmd.exe expands on whatever Windows user is running, and `STOCKROOM_INSTALL` overrides it
# for a non-default install. Note `%LOCALAPPDATA%` does NOT expand through WSL interop, so it has
# to be passed through cmd.exe as a literal rather than resolved here.
#
# Deliberately NOT a Python script: it is three lines of shell around an existing Python CLI, and
# a second Python process to launch a Python process is cost with no benefit. `deploy.py` is
# Python because it has real logic (assert the resulting HEAD, grep for content markers).
#
# WARNING carried from the repo local instructions, because this script is exactly where it would bite:
# NEVER run `uv` with the shell's cwd inside the install. `uv` treats the directory it starts in
# as its project and once DELETED that install's Windows venv, rebuilding it as a Linux one. This
# script changes directory only INSIDE cmd.exe, never in the calling shell, so it cannot cause it.
set -euo pipefail

if [ "$#" -eq 0 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "Any further arguments are passed straight to windrive.py."
    exit 0
fi

if ! command -v cmd.exe >/dev/null 2>&1; then
    echo "cmd.exe not found: this needs WSL with Windows interop enabled." >&2
    exit 1
fi

INSTALL="${STOCKROOM_INSTALL:-%LOCALAPPDATA%\\Stockroom\\app}"

# Run cmd.exe from a Windows-visible directory. Started from a WSL path it warns
# "UNC paths are not supported. Defaulting to Windows directory." on every single call - three
# lines of noise ahead of every answer, which is how a real message gets skimmed past.
cd /mnt/c

# `py` is the Windows Python launcher, which is what the install's own docs use. Quoting: the
# whole command is ONE argument to `/c`, so the args are joined here rather than passed through.
exec cmd.exe /c "cd /d $INSTALL && py scripts\\windrive.py $*"
