/// <reference types="vitest/config" />
import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

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

// The backend serves the built SPA from app/frontend-dist/ (see
// stockroom.api.app._FRONTEND_DIST), so emit there. Relative asset base so the
// bundle works whether the host loads it from the API mount or from file://.
export default defineConfig({
  plugins: [react()],
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(buildVersion()),
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
    restoreMocks: true,
  },
});
