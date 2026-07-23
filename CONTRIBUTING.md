# Contributing to Stockroom

Whether you are a person or an agent, this is the shortest path to a clean change.

## Start here

- **What is where** → [docs/architecture.md](docs/architecture.md)
- **How to add X** → [docs/adding-a-feature.md](docs/adding-a-feature.md)
- **What it is** → [README.md](README.md)

## Set up

```bash
# backend (Python, managed with uv)
uv sync                                   # creates .venv with the pinned deps

# frontend
cd app/frontend && npm ci
```

## The gates

A change is done when these pass. Run them before you commit; do not claim "done" off a subset.

```bash
# backend
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend -q

# frontend (from app/frontend)
npm run test:run && npm run typecheck && npm run build
```

Windows CI (`.github/workflows/ci.yml`) is the release gate; a green Linux run is necessary but
never sufficient for a visual or Windows-specific change.

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
- **New behaviour gets a test.** Backend seams are built test-first. UI changes get looked at in
  both light and dark themes.
- **Scoped commits.** `git add <path>`, never `git add -A`. Plain one-line commit messages.

## Local guardrails (optional but recommended)

```bash
pre-commit install     # formats + lightly lints only the files you touch, on commit
```

`.editorconfig` and `.pre-commit-config.yaml` keep new code tidy without reformatting the whole
tree. See [architecture.md](docs/architecture.md#keeping-it-healthy).
