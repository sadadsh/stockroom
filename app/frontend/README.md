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

## Local dev

```
npm run dev
```

The client resolves the API base and token in this order:

1. `window.__API_BASE__` / `window.__STOCKROOM_TOKEN__` (injected by the WebView2
   host at launch)
2. `VITE_API_BASE` / `VITE_API_TOKEN` (a `.env` for browser dev)
3. a loopback default of `http://127.0.0.1:8765`

To point dev at a running backend, start the server, then set `VITE_API_BASE`
(and `VITE_API_TOKEN` if the server was started with a token) to match.

## Design

Ported from `docs/mockups/library-v2.html`. Tokens live in `tailwind.config.js`.
Fonts fall back to Segoe UI / system-ui if DM Sans is not installed. No em dashes
in UI copy; interactive labels are Title Case.
