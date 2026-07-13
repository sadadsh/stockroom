import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, useRouter } from "./router";

function Probe() {
  const { route, navigate } = useRouter();
  return (
    <div>
      <span data-testid="route">{route}</span>
      <button type="button" onClick={() => navigate("settings")}>
        go settings
      </button>
    </div>
  );
}

describe("router", () => {
  it("starts at the initial route and navigates on demand", async () => {
    render(
      <RouterProvider initial="components">
        <Probe />
      </RouterProvider>,
    );
    expect(screen.getByTestId("route")).toHaveTextContent("components");
    await userEvent.click(screen.getByText("go settings"));
    expect(screen.getByTestId("route")).toHaveTextContent("settings");
  });

  it("throws when used outside a provider", () => {
    // React logs the thrown error; that noise is expected here.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/RouterProvider/);
    spy.mockRestore();
  });
});
