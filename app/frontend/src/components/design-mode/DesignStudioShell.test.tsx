import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import App from "../../App";
import { AddPartProvider } from "../../lib/addPart";
import { CaptureProvider } from "../../lib/capture";
import { RouterProvider } from "../../lib/router";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import { DesignStudioProvider } from "../../design-studio/DesignStudioProvider";
import { DesignStudioShell } from "./DesignStudioShell";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listParts: vi.fn().mockResolvedValue({ parts: [], count: 0 }),
      facets: vi.fn().mockResolvedValue({
        by_category: {},
        by_manufacturer: {},
        complete: 0,
        incomplete: 0,
      }),
      getOnboarding: vi.fn().mockResolvedValue({
        onboarded: true,
        first_run: false,
        libraries_root: "C:\\Stockroom",
        profiles: [],
        under_git: true,
        default_dir: "C:\\Stockroom\\Components",
        libraries: [],
      }),
      designStudioGet: vi.fn().mockRejectedValue(new Error("No personal design fixture")),
      devStatus: vi.fn().mockResolvedValue({
        available: false,
        can_publish: false,
        publish_blocker: "Source promotion is unavailable.",
      }),
      updateSettings: vi.fn().mockResolvedValue({}),
    },
  };
});

function Providers({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <DesignStudioProvider>
          <ToastProvider>
            <RouterProvider initial="components">
              <CaptureProvider>
                <AddPartProvider>{children}</AddPartProvider>
              </CaptureProvider>
            </RouterProvider>
          </ToastProvider>
        </DesignStudioProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function renderApp() {
  return render(
    <Providers>
      <DesignStudioShell>
        <App />
      </DesignStudioShell>
    </Providers>,
  );
}

async function renderStudio() {
  const result = renderApp();
  const entry = screen.getByRole("button", { name: "Design Studio" });
  await userEvent.setup().click(entry);
  await screen.findByRole("region", { name: "Stockroom Preview" });
  return { ...result, entry };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/#route=components");
  window.__STOCKROOM_UI__ = { rail_collapsed: false };
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ schema_version: 1, document: null, revision: 0 }),
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DesignStudioShell", () => {
  it("opens from the visible rail entry and starts with the simple screen-first workflow", async () => {
    renderApp();
    await userEvent.setup().click(screen.getByRole("button", { name: "Design Studio" }));

    expect(screen.getByRole("complementary", { name: "Screens And States" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen
        .getByRole("region", { name: "Stockroom Preview" })
        .querySelector('[data-dev-id="shell.root"]'),
    ).toBeVisible();
  });

  it("collapses every editor region without hiding Stockroom chrome", async () => {
    const { container } = await renderStudio();
    await userEvent.setup().click(
      within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Inspect" }),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Presentation Mode" }));

    expect(screen.queryByRole("complementary", { name: "Screens And States" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector('[data-dev-id="rail.root"]')).toBeVisible();
  });

  it("uses Escape to return to Browse before closing and restores focus to the rail entry", async () => {
    const { entry } = await renderStudio();
    await userEvent.setup().click(
      within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Inspect" }),
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("gives panel resizers named keyboard controls", async () => {
    await renderStudio();
    const resizer = screen.getByRole("separator", { name: "Resize Screens And States Panel" });
    const before = screen.getByRole("complementary", { name: "Screens And States" }).getAttribute("style");

    fireEvent.keyDown(resizer, { key: "ArrowRight" });

    expect(screen.getByRole("complementary", { name: "Screens And States" }).getAttribute("style")).not.toBe(before);
  });
});
