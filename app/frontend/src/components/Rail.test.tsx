import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Rail } from "./Rail";
import { DevModeProvider } from "../lib/devMode";
import { DEV_ID_BY_ID } from "../lib/devIds";

// A controllable router stand-in so the rail can be tested in isolation. The update-availability,
// apply mutation, and its pending flag are hoisted too, so a test can drive the Update control
// through both its available/click and busy states.
const { state, navigate, applyMutate, updateState, applyState } = vi.hoisted(() => ({
  state: { route: "components" },
  navigate: vi.fn(),
  applyMutate: vi.fn(),
  updateState: { update_available: false },
  applyState: { isPending: false },
}));
vi.mock("../lib/router", () => ({
  useRouter: () => ({ route: state.route, navigate }),
}));
// The rail now reads theme + live library/sync/update state; stub them so the rail can be
// tested in isolation (its own render, not the providers).
vi.mock("../lib/theme", () => ({
  useTheme: () => ({ theme: "dark", setTheme: vi.fn(), toggle: vi.fn() }),
}));
vi.mock("../api/queries", () => ({
  useFacetsQuery: () => ({ data: { complete: 80, incomplete: 8 } }),
  useSyncStatus: () => ({ data: { current_branch: "main", ahead: 0, behind: 0 } }),
  useUpdateCheck: () => ({ data: { update_available: updateState.update_available } }),
  useApplyUpdate: () => ({ mutate: applyMutate, isPending: applyState.isPending }),
}));
vi.mock("../lib/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// The rail now starts collapsed on a window too narrow for the detail sheet's three-column
// layout (see RAIL_NEEDS_COLLAPSE_BELOW), and jsdom's default window is 1024px - narrow. Every
// test below this line was written against the EXPANDED rail and reads labels that only exist
// there ("Updating", the wordmark), so the width they always implicitly relied on is now stated
// instead of assumed. The auto-collapse block at the bottom sets its own widths.
beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { value: 1600, configurable: true, writable: true });
});

describe("Rail", () => {
  beforeEach(() => {
    state.route = "components";
    updateState.update_available = false;
    applyState.isPending = false;
    applyMutate.mockReset();
  });

  it("shows exactly the top-level destinations: Library, Projects, Settings", () => {
    render(<Rail />);
    expect(screen.getByRole("button", { name: /Components/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Projects/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Settings/ })).toBeInTheDocument();
    // the folded Library tabs are not rail destinations anymore
    expect(screen.queryByRole("button", { name: /Ingest|Add Parts/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Duplicates/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Doctor/ })).toBeNull();
  });

  it("marks Library active for the default route and navigates on click", async () => {
    render(<Rail />);
    const library = screen.getByRole("button", { name: /Components/ });
    expect(library).toHaveAttribute("aria-current", "page");
    await userEvent.click(library);
    expect(navigate).toHaveBeenCalledWith("components");
  });

  it("applies the update when the rail's Update button is clicked", async () => {
    updateState.update_available = true;
    render(<Rail />);
    const button = screen.getByRole("button", { name: /Update/ });
    expect(button).toBeEnabled();
    await userEvent.click(button);
    // Same flow as Settings' Apply Update: the useApplyUpdate mutation with result-shaped
    // toasts (asserted here at the mutation seam; the toast branching lives in onApply).
    expect(applyMutate).toHaveBeenCalledTimes(1);
  });

  it("shows a busy label and disables the Update button while the apply is in flight", () => {
    updateState.update_available = true;
    applyState.isPending = true;
    render(<Rail />);
    const button = screen.getByRole("button", { name: /Updating/ });
    expect(button).toBeDisabled();
    // clicking a disabled busy button must not fire a second apply
    fireEvent.click(button);
    expect(applyMutate).not.toHaveBeenCalled();
  });

  it("carries stable data-dev-id attributes, including the derived rail.nav-* ids, that all resolve via DEV_ID_BY_ID", () => {
    const { container } = render(<Rail />);
    // The rail shell and the About trigger are static ids on their anchor elements.
    // The three primary/footer destinations get their id derived on the reusable RailItem.
    const expected = [
      "rail.root",
      "rail.about",
      "rail.nav-components",
      "rail.nav-projects",
      "rail.nav-settings",
    ];
    for (const id of expected) {
      const el = container.querySelector(`[data-dev-id="${id}"]`);
      expect(el, `expected an element with data-dev-id="${id}"`).not.toBeNull();
      expect(DEV_ID_BY_ID.has(id), `expected ${id} to resolve via DEV_ID_BY_ID`).toBe(true);
    }
  });

});

// The AboutModal is the only Rail region this phase adopts (its nav glyphs + nav.* labels belong to
// Phase 2 and are untouched here). `../lib/theme` is module-mocked above, so DevModeProvider's
// useTheme() resolves the same dark stub and no ThemeProvider is needed.
describe("Rail AboutModal - copy + brand icon adoption", () => {
  beforeEach(() => {
    state.route = "components";
  });

  function toggleDevMode() {
    fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
  }

  it("keeps the non-dev About behaviour: opens, exposes the two links, and closes on the scrim", async () => {
    const { container } = render(
      <DevModeProvider>
        <Rail />
      </DevModeProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /About/ }));

    // The dialog opens with its accessible name and both social links resolve their hrefs.
    expect(screen.getByRole("dialog", { name: "About Stockroom" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "LinkedIn" })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/sadadhaidari",
    );
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/sadadsh",
    );

    // Off dev mode a <Text> is a bare string: no editable copy targets exist in the modal.
    expect(container.querySelector("[data-copy-id]")).toBeNull();

    // A scrim click closes it.
    fireEvent.click(container.querySelector('[data-dev-id="about.scrim"]')!);
    expect(screen.queryByRole("dialog", { name: "About Stockroom" })).toBeNull();
  });

  it("wraps the title and link labels as copy ids and draws each brand glyph through <Icon> in dev mode", async () => {
    const { container } = render(
      <DevModeProvider>
        <Rail />
      </DevModeProvider>,
    );
    // Open the modal first, then toggle dev mode: in dev mode the About button's own <Text> label
    // intercepts the click (click-to-edit), so opening must happen while dev mode is off.
    await userEvent.click(screen.getByRole("button", { name: /About/ }));
    toggleDevMode();

    // The visible AboutModal labels carry their modals.json ids.
    expect(container.querySelector('[data-copy-id="modal.about.title"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.about.credit"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.about.linkedin"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.about.github"]')).not.toBeNull();

    // "Sadad Haidari" stays a literal proper noun inside its emphasized span (not a copy target).
    expect(screen.getByText("Sadad Haidari")).toBeInTheDocument();

    // Each of the three brand glyphs renders through <Icon>, which advertises its id in dev mode.
    const about = container.querySelector('[data-dev-id="about.root"]')!;
    expect(about.querySelector('svg[data-icon-id="brand.wordmark"]')).not.toBeNull();
    expect(about.querySelector('svg[data-icon-id="brand.linkedin"]')).not.toBeNull();
    expect(about.querySelector('svg[data-icon-id="brand.github"]')).not.toBeNull();
  });
  it("shows a real version string in the About modal (FIX-02)", async () => {
    render(<Rail />);
    await userEvent.click(screen.getByRole("button", { name: /About/ }));
    // a Title Case "Version" label with the build-injected value beside it
    const label = screen.getByText("Version");
    expect(label).toBeInTheDocument();
    expect(typeof __APP_VERSION__).toBe("string");
    expect(__APP_VERSION__.length).toBeGreaterThan(0);
    expect(screen.getByText(__APP_VERSION__)).toBeInTheDocument();
    // no em dash anywhere in the About modal copy (design contract)
    expect(screen.getByRole("dialog").textContent).not.toContain("—");
  });

});

describe("the rail fits itself to the window when you have never chosen", () => {
  // MEASURED on the owner's real window: the detail sheet needs a container of >=896px for its
  // three-column layout (DetailPanel's own comment states the breakpoint). At 1384x861 with the
  // rail EXPANDED the container was 815px, so Specifications and Sourcing stacked and each got
  // its own scrollbar in a 500px column. Collapsing the rail gains 137px and clears it.
  //
  // The rule the owner picked: the app does that itself rather than expecting them to know that
  // a nav rail governs whether a spec sheet has three columns. An EXPLICIT choice still wins,
  // forever - this only decides the case where they have never touched it.
  const setWidth = (w: number) => {
    Object.defineProperty(window, "innerWidth", { value: w, configurable: true, writable: true });
  };

  beforeEach(() => {
    window.__STOCKROOM_UI__ = {};
    try { localStorage.clear(); } catch { /* jsdom may deny it */ }
  });

  it("starts collapsed on a window too narrow for the three-column sheet", () => {
    setWidth(1384); // the owner's real window
    render(<DevModeProvider><Rail /></DevModeProvider>);
    expect(screen.getByRole("button", { name: /expand rail/i })).toBeInTheDocument();
  });

  it("starts expanded when the window is wide enough for it", () => {
    setWidth(1920);
    render(<DevModeProvider><Rail /></DevModeProvider>);
    expect(screen.getByRole("button", { name: /collapse rail/i })).toBeInTheDocument();
  });

  it("NEVER overrides a stored preference, however narrow the window", () => {
    // The half that matters: once you have chosen, the window does not get a vote. Otherwise the
    // app would quietly undo your choice every launch, which is worse than the layout it fixes.
    setWidth(1000);
    window.__STOCKROOM_UI__ = { rail_collapsed: false };
    render(<DevModeProvider><Rail /></DevModeProvider>);
    expect(screen.getByRole("button", { name: /collapse rail/i })).toBeInTheDocument();
  });

  it("does not persist the width-derived state, so it stays a default and not a choice", () => {
    // The trap this was written around: the existing effect wrote the state on MOUNT, which would
    // turn the derived value into a stored preference immediately - and then "never chosen" could
    // never happen again on any machine.
    setWidth(1384);
    render(<DevModeProvider><Rail /></DevModeProvider>);
    expect(localStorage.getItem("stockroom.rail.collapsed")).toBeNull();
  });
});
