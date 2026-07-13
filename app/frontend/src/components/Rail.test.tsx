import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Rail } from "./Rail";

// A controllable router stand-in so the rail can be tested in isolation.
const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("../lib/router", () => ({
  useRouter: () => ({ route: "components", navigate }),
}));

describe("Rail", () => {
  it("renders the available destinations and marks the active one", () => {
    render(<Rail />);
    const components = screen.getByRole("button", { name: /Components/ });
    expect(components).toBeInTheDocument();
    expect(components).toHaveAttribute("aria-current", "page");
  });

  it("navigates when a destination is clicked", async () => {
    render(<Rail />);
    await userEvent.click(screen.getByRole("button", { name: /Components/ }));
    expect(navigate).toHaveBeenCalledWith("components");
  });
});
