import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ProviderBrowserIdentity } from "../../lib/hostProviderViewport";
import { ProviderBrowserModal } from "./ProviderBrowserModal";

const bridge = vi.hoisted(() => ({
  command: vi.fn(),
  viewport: vi.fn(),
}));

vi.mock("../../lib/hostProviderViewport", () => ({
  onProviderCloseRequest: () => () => undefined,
  providerHostAvailable: () => true,
  sendProviderCommand: bridge.command,
  setProviderViewport: bridge.viewport,
}));

const identity: ProviderBrowserIdentity = {
  componentId: "part-1",
  providerId: "mouser",
  routeId: "mouser-search",
  sessionId: "session-1",
};

function modal(overrides: Partial<React.ComponentProps<typeof ProviderBrowserModal>> = {}) {
  return (
    <ProviderBrowserModal
      identity={identity}
      providerLabel="Mouser"
      url="https://www.mouser.com/c/?q=LM358"
      ready
      navigateOnOpen
      onClose={vi.fn()}
      {...overrides}
    />
  );
}

describe("ProviderBrowserModal recovery", () => {
  beforeEach(() => {
    bridge.command.mockReset();
    bridge.viewport.mockReset();
  });

  it("clears a failed open after a later provider session navigates successfully", async () => {
    bridge.command
      .mockResolvedValueOnce({ accepted: false, error: "The first page did not open." })
      .mockResolvedValue({ accepted: true, error: "" });
    const { rerender } = render(modal());
    expect(await screen.findByRole("alert")).toHaveTextContent("The first page did not open.");

    rerender(modal({
      identity: { ...identity, providerId: "digikey", routeId: "digikey-search", sessionId: "session-2" },
      providerLabel: "DigiKey",
      url: "https://www.digikey.com/en/products/result?keywords=LM358",
    }));

    await waitFor(() => expect(bridge.command).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("The first page did not open.")).toBeNull();
  });

  it("clears the stale open failure before retrying", async () => {
    const retry = vi.fn();
    bridge.command.mockResolvedValueOnce({
      accepted: false,
      error: "The first page did not open.",
    });
    render(modal({ stalled: true, onRetry: retry }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The first page did not open.");

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(retry).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("The first page did not open.")).toBeNull();
  });
});
