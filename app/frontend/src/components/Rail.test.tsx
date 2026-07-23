import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Rail } from "./Rail";

// A controllable router stand-in so the rail can be tested in isolation.
const { state, navigate } = vi.hoisted(() => ({
  state: { route: "components" },
  navigate: vi.fn(),
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
  useUpdateCheck: () => ({ data: { update_available: false } }),
}));

describe("Rail", () => {
  beforeEach(() => {
    state.route = "components";
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
