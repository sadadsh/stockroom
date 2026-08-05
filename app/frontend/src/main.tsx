import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import App from "./App";
import { RouterProvider } from "./lib/router";
import { AddPartProvider } from "./lib/addPart";
import { ToastProvider } from "./lib/toast";
import { ThemeProvider } from "./lib/theme";
import { DevModeProvider } from "./lib/devMode";
import { DevPanel } from "./components/DevPanel";
import { DevInspector } from "./components/DevInspector";
import { CaptureProvider } from "./lib/capture";
// The interface face is the PLATFORM's: Segoe UI Variable, named in the token sheet, loaded from
// Windows itself. Nothing is bundled for it. A branded webfont in application chrome is the single
// loudest signal that a desktop tool is really a web page, and it rasterises unlike every other
// window on the machine, so the app never quite sits among them.
//
// The mono face IS bundled, because it is not chrome: it marks genuinely machine-oriented text
// (file paths, raw identifiers, hashes, net names, provider keys, diagnostic payloads). Consolas
// leads on Windows to match Altium; Geist Mono covers a machine without it, offline, since the
// host serves from an ephemeral local port where a CDN font would fail outright.
import "@fontsource-variable/geist-mono";
import "./styles/index.css";

// One shared client. Reads are cheap (served from the warm index) so a short
// stale time is fine; a couple of retries covers a server that is still booting.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element not found");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* reducedMotion="user" makes every animation collapse to instant when the OS asks. */}
      <MotionConfig reducedMotion="user">
        <ThemeProvider>
          {/* Dev mode wraps the app so its token overrides apply for everyone on boot; the panel
              itself renders only while dev mode is toggled on (Ctrl/Cmd+Shift+D). */}
          <DevModeProvider>
            <ToastProvider>
              <RouterProvider>
                <CaptureProvider>
                  <AddPartProvider>
                    <App />
                  </AddPartProvider>
                </CaptureProvider>
              </RouterProvider>
            </ToastProvider>
            <DevPanel />
            <DevInspector />
          </DevModeProvider>
        </ThemeProvider>
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
);
