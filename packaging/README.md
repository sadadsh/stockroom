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

## What's bundled (runs on a bare Windows box)

The exe bundles **everything it needs to run**, so a target machine needs no git, no uv,
and no Python preinstalled:

- **uv** (provisions Python + the app environment) is bundled beside the launcher
  (`sys._MEIPASS/uv.exe`, resolved by `launcher._uv_bin`).
- **portable git** (MinGit, fetched by the release CI) is bundled
  (`sys._MEIPASS/mingit/cmd/git.exe`, resolved by `launcher._git_bin`); the launcher also
  prepends it to the host's PATH (`launcher._child_env`) so the app's OWN git operations
  (library sync, project commits, self-update) find it too.
- **Python** is provided by uv on demand.

Every git and uv subprocess runs with `CREATE_NO_WINDOW` (also in `vcs/repo.py`), so **no
console windows flash**.

## Target-machine prerequisites

- The **WebView2 runtime** (bundled with current Windows 10/11; the app's window needs it).
- **Internet** on first launch (to clone the app repo) and for updates.
- 64-bit Windows.
- KiCad 10 for the ERC/DRC and preview features (a feature dependency, degraded honestly
  when absent, never a crash).

A local/dev build (`build_exe.ps1`) that does not fetch MinGit falls back to the system git
on PATH; the release CI always bundles MinGit.

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
