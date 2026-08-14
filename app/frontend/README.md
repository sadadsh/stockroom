# Stockroom Frontend

Vite + React + TypeScript + Tailwind SPA for the Stockroom KiCad component
library manager. This is the first vertical slice: the Components page, wired to
the real library API.

## Build

```
npm install
npm run build
```

`npm run build` emits the static SPA to `../frontend-dist/`, which the FastAPI
backend serves (see `stockroom.api.app._FRONTEND_DIST`). The built dist is
committed so end users need no Node toolchain.

## Local development

From the repository root on Windows, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\Start-Stockroom-Development.ps1
```

That launcher starts the isolated source backend plus Vite, opens the SPA as **Stockroom
Development**, and keeps production state untouched. Frontend edits use HMR. Backend Python edits
restart the development child automatically. Dependency installation is an explicit separate
`scripts\Setup-Stockroom-Development.ps1` step; startup never provisions tools or pulls Git.

Direct `npm run dev` remains available for frontend-only work.

The client resolves the API base and token in this order:

1. `window.__API_BASE__` / `window.__STOCKROOM_TOKEN__` (injected by the WebView2
   host at launch)
2. `VITE_API_BASE` / `VITE_API_TOKEN` (a `.env` for browser dev)
3. a loopback default of `http://127.0.0.1:8765`

The Stockroom Development launcher proxies `/api` through Vite and injects its per-session token
only into the same-origin development renderer. It never writes the token into a committed file or
`VITE_*` build variable. For manual browser-only work, start a backend and set `VITE_API_BASE` plus
`VITE_API_TOKEN` to match.

## Design

Ported from `docs/mockups/library-v2.html`. Tokens live in `tailwind.config.js`.
Fonts fall back to Segoe UI / system-ui if DM Sans is not installed. No em dashes
in UI copy; interactive labels are Title Case.
