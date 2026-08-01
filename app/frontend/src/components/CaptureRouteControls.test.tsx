/**
 * The person's own end-of-route controls, tested for the promises that make them worth trusting.
 *
 * They exist because de-automation removed the provider HUD: the page is in the person's OWN
 * browser now, so Stockroom cannot draw Finish or Skip on it. Without these, a person-driven route
 * ended only on Stockroom's global Cancel, on ~25 s of quiet after a file had landed, or on the
 * 600 s timeout - and DigiKey fans out to five author routes.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CaptureRouteControls } from "./CaptureRouteControls";
import { CaptureProvider, useCapture } from "../lib/capture";
import { ApiError, api } from "../api/client";
import { resetUiSessionForTests } from "../lib/uiSession";

// A tiny harness that puts one assisted capture in flight, exactly as a real surface would, and
// then renders the controls beside it.
function Harness({ partId }: { partId: string }) {
  const capture = useCapture();
  return (
    <>
      <button
        type="button"
        onClick={() => void capture.start(partId, "LM317 Regulator", [], "ultralibrarian", "assisted")}
      >
        Begin
      </button>
      <CaptureRouteControls partId="lm317" />
    </>
  );
}

function renderControls(partId = "lm317") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CaptureProvider>
        <Harness partId={partId} />
      </CaptureProvider>
    </QueryClientProvider>,
  );
}

async function beginCapture() {
  // Never resolves, so the capture stays in flight for the length of the test.
  vi.spyOn(api, "runCapture").mockReturnValue(new Promise(() => {}));
  await userEvent.click(screen.getByRole("button", { name: "Begin" }));
  await screen.findByRole("button", { name: "Finish Route" });
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetUiSessionForTests();
});

afterEach(() => {
  resetUiSessionForTests();
});

describe("capture route controls", () => {
  it("renders nothing until a capture for this exact component is running", async () => {
    renderControls();

    expect(screen.queryByTestId("capture-route-controls")).toBeNull();
  });

  it("says the person is finished with the open route, keeping what already landed", async () => {
    renderControls();
    await beginCapture();
    const intent = vi.spyOn(api, "captureIntent").mockResolvedValue({
      part_id: "lm317",
      action: "finish-route",
      accepted: true,
    });

    await userEvent.click(screen.getByRole("button", { name: "Finish Route" }));

    await waitFor(() => expect(intent).toHaveBeenCalledWith("lm317", "finish-route"));
    // The copy has to say the un-obvious half: finishing is not discarding.
    expect(
      await screen.findByText(/Anything already downloaded is kept/),
    ).toBeInTheDocument();
  });

  it("stops this component's remaining routes when the person skips it", async () => {
    renderControls();
    await beginCapture();
    const intent = vi.spyOn(api, "captureIntent").mockResolvedValue({
      part_id: "lm317",
      action: "skip-part",
      accepted: true,
    });

    await userEvent.click(screen.getByRole("button", { name: "Skip This Part" }));

    await waitFor(() => expect(intent).toHaveBeenCalledWith("lm317", "skip-part"));
    expect(await screen.findByText(/stopping this component/)).toBeInTheDocument();
  });

  it("reports a refused signal instead of claiming the route ended", async () => {
    // The backend refuses a signal for a component it is not capturing. A control that claimed
    // success anyway would be exactly the control nobody could trust.
    renderControls();
    await beginCapture();
    vi.spyOn(api, "captureIntent").mockRejectedValue(
      new ApiError(409, "No person-driven capture is running for this component."),
    );

    await userEvent.click(screen.getByRole("button", { name: "Finish Route" }));

    expect(
      await screen.findByText("No person-driven capture is running for this component."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish Route" })).toBeEnabled();
  });

  it("refuses a second answer while the first is still being sent", async () => {
    renderControls();
    await beginCapture();
    vi.spyOn(api, "captureIntent").mockReturnValue(new Promise(() => {}));

    await userEvent.click(screen.getByRole("button", { name: "Finish Route" }));

    expect(await screen.findByRole("button", { name: "Finishing Route" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Skip This Part" })).toBeDisabled();
  });
});
