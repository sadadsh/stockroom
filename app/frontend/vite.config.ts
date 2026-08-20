/// <reference types="vitest/config" />
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { URL } from "node:url";
import { defineConfig, normalizePath } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
import pkg from "./package.json";
import { stockroomDesignIdentityPlugin } from "./scripts/design-identity-transform.mjs";
import {
  assertProductionBuildEnvironment,
  frontendContentRevision,
} from "./scripts/frontend-content-revision.mjs";

// pdf.js ships the 14 standard PDF fonts as separate files and loads them at RUNTIME from a
// directory it is told about. Without them a datasheet whose text relies on a standard font
// renders with fallback metrics - the glyphs are wrong widths, so tables and pin tables in a
// manufacturer PDF stop lining up. Copying the directory into the bundle is what makes
// `standardFontDataUrl` resolvable from the built app as well as from the dev server.
const require = createRequire(import.meta.url);
const standardFontsDir = normalizePath(
  path.join(path.dirname(require.resolve("pdfjs-dist/package.json")), "standard_fonts"),
);

// The version string shown in the About modal: the package version plus a deterministic digest of
// every declared frontend build input. A Git commit cannot identify committed generated output:
// committing that output creates a different commit and would make the next clean build differ.
function buildVersion(): string {
  const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
  return `${pkg.version}+${frontendContentRevision(frontendRoot)}`;
}

const appVersion = buildVersion();

function developmentBootstrapPlugin() {
  if (process.env.STOCKROOM_DEV_BOOTSTRAP !== "1") return null;
  return {
    name: "stockroom-development-bootstrap",
    transformIndexHtml() {
      return [
        {
          tag: "script",
          injectTo: "head-prepend" as const,
          children: `
(function () {
  var prefix = "#__stockroom_development_token=";
  var token = "";
  try {
    if (window.location.hash.indexOf(prefix) === 0) {
      token = decodeURIComponent(window.location.hash.slice(prefix.length));
      sessionStorage.setItem("stockroom-development-token", token);
      history.replaceState(history.state, "", window.location.pathname + window.location.search);
    } else {
      token = sessionStorage.getItem("stockroom-development-token") || "";
    }
  } catch (error) {
    token = "";
  }
  if (token) window.__STOCKROOM_TOKEN__ = token;
})();`,
        },
      ];
    },
  };
}

function developmentApiProxy() {
  const targetText = process.env.STOCKROOM_DEV_BACKEND_URL?.trim() ?? "";
  if (!targetText) return undefined;
  const target = new URL(targetText);
  if (
    target.protocol !== "http:" ||
    target.hostname !== "127.0.0.1" ||
    target.username ||
    target.password ||
    (target.pathname !== "/" && target.pathname !== "") ||
    target.search ||
    target.hash
  ) {
    throw new Error("Stockroom development backend must be a bare 127.0.0.1 HTTP origin");
  }
  return {
    "/api": {
      target: target.origin,
      changeOrigin: false,
    },
  };
}

// The backend serves the built SPA from app/frontend-dist/ (see
// stockroom.api.app._FRONTEND_DIST), so emit there. Relative asset base so the
// bundle works whether the host loads it from the API mount or from file://.
const config = defineConfig({
  plugins: [
    developmentBootstrapPlugin(),
    stockroomDesignIdentityPlugin(),
    react(),
    // `stripBase: true` matters: without it the plugin reproduces each file's path from the
    // project root, so the fonts land under `node_modules/pdfjs-dist/standard_fonts/...` in the
    // bundle - a path `standardFontDataUrl` does not point at, and a `node_modules` tree shipped
    // to the owner's machine for nothing.
    viteStaticCopy({
      targets: [
        {
          src: `${standardFontsDir}/*`,
          dest: "standard_fonts",
          rename: { stripBase: true },
        },
      ],
    }),
    {
      name: "stockroom-build-identity",
      generateBundle() {
        this.emitFile({
          type: "asset",
          fileName: "build-identity.json",
          source: `${JSON.stringify({ version: appVersion })}\n`,
        });
      },
    },
  ],
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  build: {
    outDir: "../frontend-dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: false,
    proxy: developmentApiProxy(),
  },
  // Vitest runs the component + client tests in jsdom. This is the frontend TDD
  // floor: every M6 slice ships with tests that run here (see the M6 plan).
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    clearMocks: true,
    restoreMocks: true,
    // pdf.js needs DOMMatrix, Path2D and a real canvas; importing it under jsdom throws before a
    // test can run. The stub honours the same contract - the two load callbacks, the page's
    // number/scale/rotation, the outline's page click - so the DATASHEET VIEWER'S OWN state
    // machine is what the suite exercises, rather than pdf.js's renderer, which is not ours to
    // test. The real library is what the app imports; only the test environment sees this.
    alias: [{ find: /^react-pdf$/, replacement: "/src/test/reactPdfStub.tsx" }],
  },
});

export default defineConfig(({ command }) => {
  if (command === "build") assertProductionBuildEnvironment();
  return {
    ...config,
    // Vite loads `.env*` after this config module is evaluated. Disabling its environment
    // directory for production is therefore the only reliable way to keep an ignored local file
    // from changing committed bundle bytes without changing the declared content identity.
    envDir:
      command === "build" ? false : process.env.STOCKROOM_DEV_ENV_DIR?.trim() || undefined,
  };
});
