import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, useRouter } from "./router";
import { defaultUiSession, resetUiSessionForTests } from "./uiSession";

function Probe() {
  const { route, navigate } = useRouter();
  return (
    <div>
      <span data-testid="route">{route}</span>
      <button type="button" onClick={() => navigate("settings")}>
        go settings
      </button>
      <button type="button" onClick={() => navigate("stm")}>
        go stm
      </button>
      <button type="button" onClick={() => navigate("projects")}>
        go projects
      </button>
    </div>
  );
}

describe("router", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("starts at the initial route and navigates on demand", async () => {
    render(
      <RouterProvider initial="components">
        <Probe />
      </RouterProvider>,
    );
    expect(screen.getByTestId("route")).toHaveTextContent("components");
    expect(window.location.hash).toBe("#route=components");
    await userEvent.click(screen.getByText("go settings"));
    expect(screen.getByTestId("route")).toHaveTextContent("settings");
    expect(window.location.hash).toBe("#route=settings");
    await userEvent.click(screen.getByText("go projects"));
    expect(screen.getByTestId("route")).toHaveTextContent("projects");
    expect(window.location.hash).toBe("#route=projects");
  });

  it("restores a valid route after the renderer remounts", () => {
    window.history.replaceState({}, "", "/stockroom?source=update#route=settings");

    const first = render(
      <RouterProvider initial="components">
        <Probe />
      </RouterProvider>,
    );
    expect(screen.getByTestId("route")).toHaveTextContent("settings");

    first.unmount();
    render(
      <RouterProvider initial="components">
        <Probe />
      </RouterProvider>,
    );
    expect(screen.getByTestId("route")).toHaveTextContent("settings");
    expect(window.location.pathname).toBe("/stockroom");
    expect(window.location.search).toBe("?source=update");
  });

  it("restores the server-owned route when a replacement origin has no hash yet", () => {
    const snapshot = defaultUiSession();
    snapshot.route = "settings";
    resetUiSessionForTests(snapshot);
    window.history.replaceState({}, "", "/");

    render(
      <RouterProvider initial="components">
        <Probe />
      </RouterProvider>,
    );

    expect(screen.getByTestId("route")).toHaveTextContent("settings");
    expect(window.location.hash).toBe("#route=settings");
  });

  it.each([
    "#https://outside.example/settings",
    "#route=%73ettings",
    "#route=settings&next=https://outside.example",
    "#/settings",
  ])("fails an untrusted or malformed hash closed to Components: %s", (hash) => {
    window.history.replaceState({}, "", `/stockroom?keep=yes${hash}`);

    render(
      <RouterProvider initial="stm">
        <Probe />
      </RouterProvider>,
    );

    expect(screen.getByTestId("route")).toHaveTextContent("components");
    expect(window.location.pathname).toBe("/stockroom");
    expect(window.location.search).toBe("?keep=yes");
    expect(window.location.hash).toBe("#route=components");
  });

  it("keeps navigation on the current origin, path, and query", async () => {
    window.history.replaceState({}, "", "/stockroom/library?batch=1000");
    const origin = window.location.origin;

    render(
      <RouterProvider>
        <Probe />
      </RouterProvider>,
    );
    await userEvent.click(screen.getByText("go settings"));

    expect(window.location.origin).toBe(origin);
    expect(window.location.pathname).toBe("/stockroom/library");
    expect(window.location.search).toBe("?batch=1000");
    expect(window.location.hash).toBe("#route=settings");
  });

  it("tracks browser back and forward navigation", async () => {
    render(
      <RouterProvider>
        <Probe />
      </RouterProvider>,
    );
    await userEvent.click(screen.getByText("go settings"));
    await userEvent.click(screen.getByText("go stm"));
    expect(screen.getByTestId("route")).toHaveTextContent("stm");

    act(() => window.history.back());
    await waitFor(() =>
      expect(screen.getByTestId("route")).toHaveTextContent("settings"),
    );

    act(() => window.history.back());
    await waitFor(() =>
      expect(screen.getByTestId("route")).toHaveTextContent("components"),
    );

    act(() => window.history.forward());
    await waitFor(() =>
      expect(screen.getByTestId("route")).toHaveTextContent("settings"),
    );
  });

  it("throws when used outside a provider", () => {
    // React logs the thrown error; that noise is expected here.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/RouterProvider/);
    spy.mockRestore();
  });
});
