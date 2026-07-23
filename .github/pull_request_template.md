<!-- Keep it short. The point is a healthy change, not a form. -->

## What and why

<!-- One or two sentences: what this changes and why. -->

## Checklist

- [ ] Backend gate green: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/backend -q`
- [ ] Frontend gate green: `npm run test:run && npm run typecheck && npm run build` (from `app/frontend`)
- [ ] Rebuilt `app/frontend-dist/` committed in the same change (if the frontend changed)
- [ ] New behaviour has a test; a UI change was looked at in both themes
- [ ] Extends a registry/factory over forking a code path; tokens over literals (see [CONTRIBUTING.md](../CONTRIBUTING.md))
