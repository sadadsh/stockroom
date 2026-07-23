import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Rail } from "./Rail";
import { DEV_ID_BY_ID } from "../lib/devIds";

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
