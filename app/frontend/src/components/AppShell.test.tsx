import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { AppShell } from "./AppShell";
import { onQueuedPaths } from "../lib/ingestQueue";
import { RouterProvider, useRouter } from "../lib/router";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { listParts: vi.fn().mockResolvedValue({ parts: [], count: 0 }) },
  };
});

function RouteProbe() {
  const { route } = useRouter();
  return <div data-testid="route">{route}</div>;
}

function renderShell() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <RouterProvider>
            <AppShell>
              <RouteProbe />
            </AppShell>
          </RouterProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("AppShell native drop bridge", () => {
  it("registers the host drop hook, queues the paths, and navigates to ingest", () => {
    renderShell();
    // the WebView2 host forwards native drop paths through this global (a plain
    // browser drop cannot see filesystem paths, so this is the only real channel)
    const hook = window.__STOCKROOM_NATIVE_DROP__;
    expect(typeof hook).toBe("function");

    const received: string[][] = [];
    const unsubscribe = onQueuedPaths((paths) => received.push(paths));
    act(() => {
      hook!(["C:\\Users\\me\\part.zip", "C:\\Users\\me\\model.step"]);
    });
    unsubscribe();

    expect(received).toEqual([["C:\\Users\\me\\part.zip", "C:\\Users\\me\\model.step"]]);
    expect(screen.getByTestId("route").textContent).toBe("ingest");
  });

  it("unregisters the hook on unmount", () => {
    const { unmount } = renderShell();
    expect(typeof window.__STOCKROOM_NATIVE_DROP__).toBe("function");
    unmount();
    expect(window.__STOCKROOM_NATIVE_DROP__).toBeUndefined();
  });

  it("ignores junk from the bridge without navigating", () => {
    renderShell();
    act(() => {
      window.__STOCKROOM_NATIVE_DROP__!([]);
      window.__STOCKROOM_NATIVE_DROP__!([42, null] as unknown as string[]);
    });
    // an empty or non-string-bearing call must not navigate away
    expect(screen.getByTestId("route").textContent).toBe("components");
  });
});
