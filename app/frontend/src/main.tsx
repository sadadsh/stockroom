import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import App from "./App";
import { RouterProvider } from "./lib/router";
import { AddPartProvider } from "./lib/addPart";
import { ToastProvider } from "./lib/toast";
import { ThemeProvider } from "./lib/theme";
// The interface face, bundled offline (no CDN) so it renders identically inside
// WebView2 on Windows. Imported before the token sheet, which names it.
import "@fontsource-variable/work-sans";
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
          <ToastProvider>
            <RouterProvider>
              <AddPartProvider>
                <App />
              </AddPartProvider>
            </RouterProvider>
          </ToastProvider>
        </ThemeProvider>
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
);
