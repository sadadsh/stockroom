import { render, screen } from "@testing-library/react";

import { ProviderCaptureGuide } from "./ProviderCaptureGuide";

describe("ProviderCaptureGuide", () => {
  it("gives one exact download instruction when the provider is ready", () => {
    render(
      <ProviderCaptureGuide
        providerLabel="DigiKey"
        ready
        requiredFiles={["STEP", "Altium Designer (Native)"]}
      />,
    );

    expect(screen.getByTestId("provider-capture-guide")).toHaveTextContent(
      "Download STEP and Altium Designer (Native)",
    );
    expect(screen.getByText("Stockroom finds files in the background.")).toBeVisible();
  });

  it("shows the active filename and determinate progress while receiving a download", () => {
    render(
      <ProviderCaptureGuide
        providerLabel="DigiKey"
        ready
        requiredFiles={["STEP"]}
        progress={{
          active: 1,
          completed: 0,
          bytes_received: 50,
          total_bytes: 100,
          files: [{
            name: "ADG714BRUZ.zip",
            state: "in_progress",
            bytes_received: 50,
            total_bytes: 100,
          }],
        }}
      />,
    );

    expect(screen.getByText("Receiving ADG714BRUZ.zip")).toBeVisible();
    expect(screen.getByText("50%")).toBeVisible();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "50");
  });

  it("confirms found files and explains the automatic next step", () => {
    render(
      <ProviderCaptureGuide
        providerLabel="DigiKey"
        ready
        requiredFiles={["STEP"]}
        progress={{
          active: 0,
          completed: 2,
          bytes_received: 200,
          total_bytes: 200,
          files: [
            { name: "symbol.zip", state: "completed", bytes_received: 100, total_bytes: 100 },
            { name: "model.step", state: "completed", bytes_received: 100, total_bytes: 100 },
          ],
        }}
      />,
    );

    expect(screen.getByText("2 files found")).toBeVisible();
    expect(screen.getByText("Checking the files and preparing attachments.")).toBeVisible();
  });

  it("uses the visible Apply action terminology for a fallback proposal", () => {
    render(
      <ProviderCaptureGuide
        providerLabel="DigiKey"
        attachmentCount={2}
      />,
    );

    expect(screen.getByText("Review and apply 2 verified attachments.")).toBeVisible();
    expect(screen.queryByText(/commit/i)).toBeNull();
  });

  it("turns an interrupted download into one precise recovery instruction", () => {
    render(
      <ProviderCaptureGuide
        providerLabel="DigiKey"
        ready
        requiredFiles={["STEP"]}
        progress={{
          active: 0,
          completed: 0,
          bytes_received: 20,
          total_bytes: 100,
          files: [{
            name: "model.step",
            state: "interrupted",
            bytes_received: 20,
            total_bytes: 100,
          }],
        }}
      />,
    );

    expect(screen.getByText("Download interrupted")).toBeVisible();
    expect(screen.getByText("Download model.step again from the provider page.")).toBeVisible();
  });
});
