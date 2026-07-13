import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves the built SPA from app/frontend-dist/ (see
// stockroom.api.app._FRONTEND_DIST), so emit there. Relative asset base so the
// bundle works whether the host loads it from the API mount or from file://.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../frontend-dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    strictPort: false,
  },
});
