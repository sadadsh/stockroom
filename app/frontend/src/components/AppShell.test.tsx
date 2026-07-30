import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { AppShell } from "./AppShell";
import { RouterProvider } from "../lib/router";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { CaptureProvider } from "../lib/capture";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listParts: vi.fn().mockResolvedValue({ parts: [], count: 0 }),
      facets: vi.fn(),
      listProfiles: vi.fn(),
      activateProfile: vi.fn(),
      checkUpdate: vi.fn(),
      // The rail persists its collapsed state through the settings endpoint now, so the mock has to
      // carry it or the write throws inside the effect that saves the preference.
      updateSettings: vi.fn().mockResolvedValue({}),
    },
  };
});

const mockApi = vi.mocked(api);

beforeEach(() => {
  mockApi.facets.mockResolvedValue({
    by_category: {}, by_manufacturer: {}, complete: 0, incomplete: 0,
  } as never);
  mockApi.listProfiles.mockResolvedValue({ profiles: [], active: "" } as never);
  mockApi.checkUpdate.mockResolvedValue({
    update_available: false,
    state: "up_to_date",
    current_revision: "123456789abc",
    target_revision: "123456789abc",
    behind: 0,
  } as never);
});

function AddPartProbe() {
  const { isOpen } = useAddPart();
  return <div data-testid="addpart-open">{String(isOpen)}</div>;
}

function renderShell(initial: "components" | "stm" | "settings" = "components") {
  window.history.replaceState({}, "", `/#route=${initial}`);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <RouterProvider initial={initial}>
            <CaptureProvider>
        <AddPartProvider>
              <AppShell>
                <AddPartProbe />
              </AppShell>
            </AddPartProvider>
        </CaptureProvider>
          </RouterProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("AppShell network-only Add A Part boundary", () => {
  it("does not register a local-file drop bridge or open Add A Part for files", () => {
    renderShell();

    expect(screen.getByTestId("addpart-open").textContent).toBe("false");
    expect(screen.queryByText(/Drop to Add Parts/i)).not.toBeInTheDocument();
  });
});

// -- punch 13b + the doubled wording. The status bar called useProfiles() and then rendered the
// active profile as DEAD TEXT: zero interactive elements in the whole bar. And its left segment read
// "Components Loaded / Components", saying Components twice, while carrying no information - the
// state it reported is true almost always.
describe("AppShell status bar", () => {
  it("shows the exact running revision and only calls a remotely proven match Current", async () => {
    renderShell();
    expect(
      await screen.findByRole("status", {
        name: "running revision 1234567, Current",
      }),
    ).toBeInTheDocument();
  });

  it("shows the running-to-target revision path when an update is available", async () => {
    mockApi.checkUpdate.mockResolvedValue({
      update_available: true,
      state: "update_available",
      current_revision: "111111111111",
      target_revision: "222222222222",
      behind: 1,
    } as never);
    renderShell();
    expect(
      await screen.findByRole("status", {
        name: "running revision 1111111, Update Available, target revision 2222222",
      }),
    ).toHaveTextContent("1111111→2222222Update Available");
  });

  it("reports Retrying instead of Current when the remote check is interrupted", async () => {
    mockApi.checkUpdate.mockResolvedValue({
      update_available: false,
      state: "offline",
      current_revision: "123456789abc",
      detail: "network unavailable",
    } as never);
    renderShell();
    const status = await screen.findByRole("status", {
      name: "running revision 1234567, Retrying…",
    });
    expect(status).toBeInTheDocument();
    expect(status).not.toHaveTextContent("Current");
  });

  it("shows Checking while the first remote comparison is still pending", () => {
    mockApi.checkUpdate.mockReturnValue(new Promise(() => {}) as never);
    renderShell();
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Checking…");
    expect(status).not.toHaveTextContent("Current");
  });

  it("states the library's scale instead of announcing that loading finished", async () => {
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 5, Resistors: 2 },
      by_manufacturer: {},
      complete: 6,
      incomplete: 1,
    } as never);
    renderShell();
    expect(await screen.findByText(/7 Components/)).toBeTruthy();
    expect(screen.queryByText("Components Loaded")).toBeNull();
  });

  it("renders permanent status facts legibly and separates the profile label from its value", async () => {
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 158 },
      by_manufacturer: {},
      complete: 158,
      incomplete: 0,
    } as never);
    mockApi.listProfiles.mockResolvedValue({
      profiles: ["Stockroom", "Archive"],
      active: "Stockroom",
    } as never);
    renderShell();

    expect(await screen.findByText("158 Components")).toHaveClass("text-t1");
    const profile = await screen.findByRole("button", { name: "Profile: Stockroom" });
    expect(profile).toHaveClass("text-t2");
    expect(profile.textContent).toContain("Profile:");
    expect(profile.querySelector(".text-t1")).toHaveTextContent("Stockroom");
  });

  it("agrees with its number at exactly one component", async () => {
    // Measured on the owner's real window: the bar read "1 Components" on 10 of the 12 captured
    // screens. A one-part library is the DEFAULT state of a new install, so this was the first
    // thing most users would ever read in that bar.
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    } as never);
    renderShell();
    expect(await screen.findByText(/1 Component\b/)).toBeTruthy();
    expect(screen.queryByText(/1 Components/)).toBeNull();
  });

  it("flags the incomplete ones, because that is the number worth acting on", async () => {
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 5 },
      by_manufacturer: {},
      complete: 4,
      incomplete: 3,
    } as never);
    renderShell();
    // "Missing Data", not "Incomplete" (owner's decision, 2026-07-26). The sheet's CAD row says
    // "Incomplete" about ASSETS while this counts the DATA passport, and one part carrying two
    // verdicts twelve pixels apart read as a contradiction. Each now names what it counts.
    expect(await screen.findByText(/3 Missing Data/)).toBeTruthy();
  });

  it("says so honestly while loading and when the load fails", async () => {
    mockApi.facets.mockRejectedValue(new Error("nope"));
    renderShell();
    expect(await screen.findByText(/Could Not Load Components/)).toBeTruthy();
  });

  it("does not report an unrelated component failure inside STM Viewer", () => {
    mockApi.facets.mockRejectedValue(new Error("nope"));
    renderShell("stm");
    expect(document.querySelector('[data-dev-id="shell.statusbar"]')).toHaveTextContent("STM Viewer");
    expect(screen.queryByText(/Could Not Load Components/)).toBeNull();
  });

  it("switches the active profile from the status bar", async () => {
    const user = userEvent.setup();
    mockApi.facets.mockResolvedValue({
      by_category: {}, by_manufacturer: {}, complete: 0, incomplete: 0,
    } as never);
    mockApi.listProfiles.mockResolvedValue({
      profiles: ["Stockroom", "Archive"],
      active: "Stockroom",
    } as never);
    mockApi.activateProfile.mockResolvedValue({ profiles: [], active: "Archive" } as never);
    renderShell();

    const trigger = await screen.findByRole("button", { name: /Profile: Stockroom/i });
    await user.click(trigger);
    await user.click(await screen.findByRole("button", { name: "Archive" }));
    expect(mockApi.activateProfile).toHaveBeenCalledWith("Archive");
  });

  it("closes the profile menu on Escape", async () => {
    const user = userEvent.setup();
    mockApi.facets.mockResolvedValue({
      by_category: {}, by_manufacturer: {}, complete: 0, incomplete: 0,
    } as never);
    mockApi.listProfiles.mockResolvedValue({
      profiles: ["Stockroom", "Archive"],
      active: "Stockroom",
    } as never);
    renderShell();
    await user.click(await screen.findByRole("button", { name: /Profile: Stockroom/i }));
    expect(screen.getByRole("button", { name: "Archive" })).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
  });
});

// -- punch 13a: the rail was a hard-coded w-[190px] with no state and no toggle, so 190px of the
// window was spent on nav labels whether or not they were wanted - and at narrow widths that is
// exactly the space the detail sheet needs.
describe("Rail collapse", () => {
  // These drive the rail's EXPANDED starting state ("Collapse Rail"), which is now conditional:
  // below RAIL_NEEDS_COLLAPSE_BELOW an untouched rail starts collapsed so the detail sheet keeps
  // its three columns, and jsdom's default window is 1024px. Stating the width these tests always
  // implicitly assumed, rather than letting the new default silently change what they assert.
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { value: 1600, configurable: true, writable: true });
  });

  // The preference PERSISTS by design, so each case has to start from a known slate - without this
  // the first case's collapse leaked into the next one, which is a test-isolation bug and not a
  // product one (it did prove the persistence works).
  beforeEach(() => {
    // The preference now lives in the MACHINE CONFIG, handed to the page by the host as
    // window.__STOCKROOM_UI__, because an ephemeral port gave every launch a new origin and wiped
    // origin-scoped localStorage. Clearing the mirror alone therefore no longer resets the slate.
    localStorage.removeItem("stockroom.rail.collapsed");
    window.__STOCKROOM_UI__ = {};
  });

  it("collapses to icons and back, and says which it will do", async () => {
    const user = userEvent.setup();
    renderShell();
    const toggle = await screen.findByRole("button", { name: "Collapse Rail" });
    const rail = document.querySelector('[data-dev-id="rail.root"]') as HTMLElement;
    expect(rail).toHaveClass("w-[190px]");
    // labels are visible while expanded
    expect(screen.getByText("Components")).toBeTruthy();
    await user.click(toggle);
    const expand = screen.getByRole("button", { name: "Expand Rail" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(rail).toHaveClass("w-[52px]");
    // the nav items survive as icons: still reachable by their accessible names
    expect(screen.getByRole("button", { name: "Components" })).toBeTruthy();
    await user.click(expand);
    expect(screen.getByRole("button", { name: "Collapse Rail" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(rail).toHaveClass("w-[190px]");
  });

  it("remembers the choice across a remount, because it is a workspace preference", async () => {
    const user = userEvent.setup();
    const first = renderShell();
    await user.click(await screen.findByRole("button", { name: "Collapse Rail" }));
    first.unmount();
    // a fresh mount reads the stored preference, as a new app launch would
    renderShell();
    expect(await screen.findByRole("button", { name: "Expand Rail" })).toBeTruthy();
  });
});
