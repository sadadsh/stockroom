# Stockroom packaging (M9): the portable Windows launcher exe

Stockroom ships as a **portable, single-file, frozen-once launcher** (`Stockroom.exe`),
built by PyInstaller on Windows. The launcher is a tiny, stable process manager; it is
frozen ONCE and thereafter never needs re-freezing, because all code / UI / data updates
flow through the in-app self-updater over git (spec section 12).

## What the exe actually is

`Stockroom.exe` bundles only `stockroom.launcher.*` + the Python stdlib. On launch it:

1. Ensures a git working copy of the app repo exists at a per-user location
   (`%LOCALAPPDATA%\Stockroom\app`), cloning it on first run.
2. Runs `uv sync --frozen` in that checkout to provision the app environment.
3. Runs `uv run python -m stockroom.host.run` (the WebView2 host + FastAPI backend).
4. Relaunches automatically whenever the app requests a self-update restart (the in-app
   Update control does `git pull --ff-only` + `uv sync`, then the host exits with a
   restart code the launcher recognizes).

So the heavy backend deps (FastAPI, uvicorn, pywebview, trimesh, ...) live in the managed
git checkout, never inside the exe. Self-update is a git pull, never a re-download.

First launch shows the **onboarding** screen (M9a-c): open an existing library, clone a
git URL, or create a fresh one. That choice is remembered in the per-machine config.

## Target-machine prerequisites

- **git** on PATH (Stockroom is a git-native app: library sync, project edits, and the
  self-update all use git).
- **uv** on PATH (https://astral.sh/uv) to provision + run the app environment.
- KiCad 10 for the ERC/DRC and preview features (as before).

These are the app's deliberate dependencies, not hidden gaps; a missing git or uv fails
loudly at the shell boundary, never silently.

## Build it (on Windows)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
# -> dist\Stockroom.exe
```

or directly:

```powershell
uv run --with pyinstaller pyinstaller packaging\stockroom.spec --noconfirm --clean
```

CI (`.github/workflows/release.yml`, `windows-latest`) runs this on a tag and uploads
`Stockroom.exe` as a GitHub Release asset, so a release exe is produced without a local
Windows build.

## Not buildable from Linux

PyInstaller does not cross-compile and pywebview/WebView2 are Windows-only, so the exe is
produced on Windows (the CI job or a local Windows build). Everything else in M9 (the
onboarding engine, the launcher supervisor logic, this spec) is authored + tested on Linux.
