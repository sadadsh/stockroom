# Stockroom launcher

The frozen-once bootstrapper for Stockroom on Windows. It is built **once** into
`Stockroom.exe` and then **never rebuilt for application changes** — the app updates
itself over `git pull --ff-only`, so a new build is only ever needed if the launch
*sequence itself* changes (rare).

## What it does (in order)

1. **`ensure_webview2`** — check the evergreen Microsoft WebView2 runtime is present;
   if absent, run `MicrosoftEdgeWebview2Setup.exe`. (Windows-only; a no-op elsewhere.)
2. **`ensure_ff_pull`** — fast-forward-only pull of the app repo so the machine runs
   the latest committed code. Uses `git` on `PATH` when available, else a `dulwich`
   fallback (`launcher/gitshim.py`). A non-fast-forwardable state is surfaced, never
   guessed (matches `AppUpdater.DIVERGED`).
3. **`uv_sync_frozen`** — run the bundled `uv` with `uv sync --frozen`: provisions a
   pinned CPython on first run (no system Python needed) and installs the locked deps.
   `--frozen` means the lockfile is never silently re-resolved; a real failure raises.
4. **`uv_run_app`** — `uv run python -m stockroom.host.run`, the **windowed** host
   entry: it binds the API to loopback on an ephemeral port **and opens the WebView2
   window** onto the FastAPI-served frontend. (Not `stockroom.api.serve`, which is the
   headless API only — launching that would show no UI.)

`run_launch_sequence(steps)` runs those step callables in the fixed order, short-
circuiting with a clear error if any step raises (an honest failed pull / missing uv,
never a silent half-launch). The order is Linux-unit-tested with the steps injected;
the real steps and the freeze are Windows-verified.

## `uv.exe` ships beside the launcher — not in git

`uv.exe` is placed next to `Stockroom.exe` at package time and is **not** committed to
git history (it is a large binary with its own release cadence). Record the `uv.exe`
version used at freeze time in the ledger so the distribution is reproducible.

## Freeze command (fill in on the Windows box)

```
REM run once on Windows, then place uv.exe beside the produced Stockroom.exe
pyinstaller --onefile --name Stockroom launcher/stockroom_launcher.py
```

(Record the exact freezer, version, and any `--add-data` flags used in the ledger when
the first real freeze is done — this placeholder is replaced with the verified command.)

## Windows acceptance bar

Owner runs on a clean Windows box with KiCad 10 + WebView2 and records results in
`Hardware Perfection Log.md`:

- First run provisions CPython via `uv`, `uv sync --frozen` installs deps, the window
  opens on the FastAPI-served page (time first-run vs warm-run).
- With the app closed, advancing the app repo remote by one commit and relaunching
  ff-pulls it before starting.
- On a box **without** git on `PATH`, the dulwich ff-pull fallback still updates.
- A non-fast-forwardable repo state is surfaced (divergence reported, safe resolution
  offered), not guessed.
