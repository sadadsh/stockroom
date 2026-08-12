import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, type ReactNode } from "react";
import App from "../../App";
import { AddPartProvider } from "../../lib/addPart";
import { CaptureProvider } from "../../lib/capture";
import { RouterProvider } from "../../lib/router";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import { DesignStudioProvider, useDesignStudio } from "../DesignStudioProvider";
import { DesignStudioShell } from "../../components/design-mode/DesignStudioShell";
import { bootstrapScenarioRegistry } from ".";

function scenarioTarget(target: string): Element | null {
  return document.querySelector(`[data-dev-id="${target}"], [data-dev-role="${target}"]`);
}

function ScenarioProbe({ expose }: { expose: (activate: (id: string) => Promise<void>) => void }) {
  const studio = useDesignStudio();
  useEffect(() => {
    expose(studio.activateScenario);
  }, [expose, studio.activateScenario]);
  return null;
}

/** Mounts the same production provider/route/component tree after fixture interception is active. */
export async function mountScenario(id: string) {
  window.__STOCKROOM_UI__ = { ...(window.__STOCKROOM_UI__ ?? {}), theme: "dark" };
  const liveRequest = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    throw new Error(`Scenario '${id}' attempted a live product request.`);
  });
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" || input instanceof URL ? input.toString() : input.url);
    if (url.pathname.startsWith("/api/design-studio/")) {
      return new Response(JSON.stringify({ revision: null, document: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return liveRequest(input, init);
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const user = userEvent.setup();
  const scenario = bootstrapScenarioRegistry.scenarioById(id);
  if (!scenario) throw new Error(`Unknown Design Studio scenario '${id}'.`);
  let activateScenario: ((scenarioId: string) => Promise<void>) | undefined;
  const expose = (activate: (scenarioId: string) => Promise<void>) => {
    activateScenario = activate;
  };
  const tree = (children: ReactNode) => (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <DesignStudioProvider>
          <ToastProvider>
            <RouterProvider initial="components">
              <CaptureProvider>
                <AddPartProvider>
                  <ScenarioProbe expose={expose} />
                  {children}
                </AddPartProvider>
              </CaptureProvider>
            </RouterProvider>
          </ToastProvider>
        </DesignStudioProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
  const view = render(tree(null));
  await waitFor(() => expect(activateScenario).toBeDefined());
  await act(async () => activateScenario?.(id));
  view.rerender(tree(<DesignStudioShell><App /></DesignStudioShell>));
  await waitFor(() => expect(scenarioTarget("shell.root")).toBeInTheDocument());
  for (const target of scenario?.expectedTargets ?? []) {
    await waitFor(() => expect(scenarioTarget(target)).toBeInTheDocument());
  }
  if (!scenario.fixtures.some((fixture) => fixture.behavior?.state === "pending")) {
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  }
  await act(async () => Promise.resolve());
  return { user, liveRequest, queryClient };
}
