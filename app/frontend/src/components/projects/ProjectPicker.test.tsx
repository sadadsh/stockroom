/**
 * The Add Location window is a MODAL, and had been declaring itself one (`role="dialog"`,
 * `aria-modal`) while behaving like a floating panel: no Escape, no focus trap, no focus restore,
 * and a hardcoded z-index that could put it underneath the surface that raised it. It goes through
 * the shared modal stack now, so these are the guarantees that must not silently lapse again.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../../api/client";
import { MODAL_BASE_Z } from "../../lib/useModalDismiss";
import { ToastProvider } from "../../lib/toast";
import { ProjectPicker } from "./ProjectPicker";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: { discoverProjects: vi.fn(), registerProject: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

function renderPicker(foundProjects: React.ComponentProps<typeof ProjectPicker>["foundProjects"] = []) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ProjectPicker
          projects={[]}
          selectedId={null}
          loading={false}
          error={null}
          onSelect={vi.fn()}
          foundProjects={foundProjects}
          onFoundSelect={vi.fn()}
          onRetry={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.discoverProjects.mockResolvedValue({ projects: [] });
});

describe("the Add Location window behaves like the modal it declares itself to be", () => {
  it("closes on Escape and puts focus back on the control that opened it", async () => {
    const user = userEvent.setup();
    renderPicker();

    const trigger = screen.getAllByRole("button", { name: "Add Location" })[0];
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Add Location" });
    // The window it exists to fill keeps the focus, not the dialog frame.
    expect(screen.getByPlaceholderText(/folder/i)).toHaveFocus();
    // It sits on the shared modal stack rather than at a hand-picked z-index.
    expect((dialog.parentElement as HTMLElement).style.zIndex).toBe(String(MODAL_BASE_Z));

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Add Location" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("keeps Tab inside the window instead of walking the page behind the scrim", async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(screen.getAllByRole("button", { name: "Add Location" })[0]);
    const dialog = await screen.findByRole("dialog", { name: "Add Location" });

    for (let press = 0; press < 12; press += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });
});

it("shows location context only when discovered projects share a name", () => {
  renderPicker([
    {
      eda: "kicad",
      eda_label: "KiCad",
      name: "Controller",
      root: "C:\\Work\\Alpha\\Controller",
      descriptor: "C:\\Work\\Alpha\\Controller\\Controller.kicad_pro",
      boards: [],
      schematics: [],
    },
    {
      eda: "kicad",
      eda_label: "KiCad",
      name: "Controller",
      root: "C:\\Work\\Beta\\Controller",
      descriptor: "C:\\Work\\Beta\\Controller\\Controller.kicad_pro",
      boards: [],
      schematics: [],
    },
  ]);

  expect(screen.getByText("Beta\\Controller")).toBeInTheDocument();
  expect(screen.getByText("Alpha\\Controller")).toBeInTheDocument();
});
