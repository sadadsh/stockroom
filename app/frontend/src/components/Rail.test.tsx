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

describe("Rail", () => {
  beforeEach(() => {
    state.route = "components";
  });

  it("shows exactly the top-level destinations: Library, Projects, Settings", () => {
    render(<Rail />);
    expect(screen.getByRole("button", { name: /Library/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Projects/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Settings/ })).toBeInTheDocument();
    // the folded Library tabs are not rail destinations anymore
    expect(screen.queryByRole("button", { name: /Ingest|Add Parts/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Duplicates/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Doctor/ })).toBeNull();
  });

  it("marks Library active for the default route and navigates on click", async () => {
    render(<Rail />);
    const library = screen.getByRole("button", { name: /Library/ });
    expect(library).toHaveAttribute("aria-current", "page");
    await userEvent.click(library);
    expect(navigate).toHaveBeenCalledWith("components");
  });

  it("keeps Library marked active while a folded library tab is the route", () => {
    state.route = "doctor";
    render(<Rail />);
    expect(screen.getByRole("button", { name: /Library/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: /Projects/ })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
