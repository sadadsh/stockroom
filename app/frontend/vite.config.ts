/// <reference types="vitest/config" />
import { execSync } from "node:child_process";
import path from "node:path";
import { createRequire } from "node:module";
import { defineConfig, normalizePath } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
import pkg from "./package.json";

// pdf.js ships the 14 standard PDF fonts as separate files and loads them at RUNTIME from a
// directory it is told about. Without them a datasheet whose text relies on a standard font
// renders with fallback metrics - the glyphs are wrong widths, so tables and pin tables in a
// manufacturer PDF stop lining up. Copying the directory into the bundle is what makes
// `standardFontDataUrl` resolvable from the built app as well as from the dev server.
const require = createRequire(import.meta.url);
const standardFontsDir = normalizePath(
  path.join(path.dirname(require.resolve("pdfjs-dist/package.json")), "standard_fonts"),
);

// The version string shown in the About modal: the package version plus the app-repo git
// short SHA, resolved ONCE at build (config-load) time and baked in as a constant. The git
// call is wrapped so any failure (no git, a detached/CI checkout, no repo) falls back to just
// the package version and never throws or blocks the build. No runtime shell, no network.
function buildVersion(): string {
  try {
    const sha = execSync("git rev-parse --short HEAD", {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
    return sha ? `${pkg.version}+${sha}` : pkg.version;
  } catch {
    return pkg.version;
  }
}

const appVersion = buildVersion();

// The backend serves the built SPA from app/frontend-dist/ (see
// stockroom.api.app._FRONTEND_DIST), so emit there. Relative asset base so the
// bundle works whether the host loads it from the API mount or from file://.
export default defineConfig({
  plugins: [
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
    port: 5173,
    strictPort: false,
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
