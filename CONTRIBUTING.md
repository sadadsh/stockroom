# Contributing to Stockroom

Whether you are a person or an agent, this is the shortest path to a clean change.

## Start here

- **What is where** → [docs/architecture.md](docs/architecture.md)
- **How to add X** → [docs/adding-a-feature.md](docs/adding-a-feature.md)
- **What it is** → [README.md](README.md)

## Set up

```powershell
# source-pinned native CAD writer (only its required nested abstraction)
git submodule update --init vendor/AltiumSharp
git -C vendor/AltiumSharp submodule update --init shared/OriginalCircuit.Eda.Abstractions

# backend (Python, managed with uv)
uv sync                                   # creates .venv with the pinned deps

# frontend
Push-Location app\frontend
npm ci
Pop-Location

# Windows workflow validator
winget install --id rhysd.actionlint --exact
```

## Run Stockroom Development

Use the isolated source host for the normal edit loop. Vite updates frontend code in place; a
backend Python edit closes and relaunches only the development window. It never pulls Git and
never opens the installed app's configuration, service databases, WebView profile, or library.

```powershell
# Explicit dependency setup, only when the lockfiles change or the checkout is new.
powershell -ExecutionPolicy Bypass -File scripts\Setup-Stockroom-Development.ps1

# Normal development loop.
powershell -ExecutionPolicy Bypass -File scripts\Start-Stockroom-Development.ps1

# Optional Start Menu shortcut. Always name the exact checkout it should run.
powershell -ExecutionPolicy Bypass -File scripts\Install-Stockroom-DevelopmentShortcut.ps1 `
  -RepositoryRoot (Get-Location).Path
```

Development state lives under `%LOCALAPPDATA%\Stockroom Development`. Real data stays in the
signed installed `Stockroom` app. Production behavior must still be verified through the packaged
native host; hot reload is development evidence only.

## The gates

A change is done when these pass. Run them before you commit; do not claim "done" off a subset.

```powershell
# Canonical Windows completion gate: backend, native host, frontend, types, build, and dist.
powershell -ExecutionPolicy Bypass -File scripts\Gates.ps1

# Focused layers during development.
actionlint .github/workflows/ci.yml .github/workflows/release.yml
uv run ty check app/backend/stockroom
uv run pytest tests/backend -q
Push-Location app\frontend
npm run test:run
npm run typecheck
npm run build
Pop-Location
```

Windows CI (`.github/workflows/ci.yml`) runs the same release gate. A focused or non-Windows run is
useful feedback but never sufficient for a visual or Windows-specific change.

> The frontend is built to `app/frontend-dist/`, and that directory **is committed** because the
> backend serves it as static files. Always commit the regenerated `frontend-dist/` in the **same**
> commit as the source change that produced it.

## The rules that keep it healthy

- **Extend a registry or a factory, not a code path.** See the patterns in
  [architecture.md](docs/architecture.md#the-patterns-that-keep-it-modular). If a feature needs a
  new branch of `if`, check whether it belongs in a registry row instead.
- **Tokens, never literals.** Colours, radii, and font sizes go through the design tokens
  (`bg-raise`, `text-t1`, `rounded-card`, the type scale), so the theme flips and the look stays
  consistent by construction.
- **Honest degradation.** A missing field renders an honest empty/"missing" state; nothing is
  fabricated. Errors say what happened and how to fix it.
- **Copy voice.** Interactive labels (buttons, headings, tabs) are Title Case; body prose is
  sentence case; no em dashes.
- **New behaviour gets an outcome test.** A mock proving that a button was clicked or a function
  was called is only a contract test. Acceptance must also observe the user-facing boundary: saved
  bytes, preserved state, a returned host result, or the absence of an unwanted process. UI changes
  get looked at in both light and dark themes.
- **Scoped commits.** `git add <path>`, never `git add -A`. Plain one-line commit messages.

## Local guardrails (optional but recommended)

```bash
pre-commit install     # formats + lightly lints only the files you touch, on commit
```

`.editorconfig` and `.pre-commit-config.yaml` keep new code tidy without reformatting the whole
tree. See [architecture.md](docs/architecture.md#keeping-it-healthy).
