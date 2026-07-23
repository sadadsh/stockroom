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
// The interface face, bundled offline (no CDN) so it renders identically inside
// WebView2 on Windows. Imported before the token sheet, which names it. Work Sans
// carries identity + prose; JetBrains Mono is the machine-data readout face (MPN,
// specs, stock, prices, pins) so every value aligns on tabular figures.
import "@fontsource-variable/work-sans";
import "@fontsource-variable/jetbrains-mono";
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
