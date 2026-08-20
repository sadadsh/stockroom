import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DesignPreviewBoundary } from "./DesignPreviewBoundary";

function BrokenPreview(): never {
  throw new Error("preview render failed");
}

describe("DesignPreviewBoundary", () => {
  const suppressExpectedError = (event: ErrorEvent) => event.preventDefault();
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    window.addEventListener("error", suppressExpectedError);
  });
  afterEach(() => {
    window.removeEventListener("error", suppressExpectedError);
    vi.restoreAllMocks();
  });

  it("keeps a recovery action visible when the product preview throws", () => {
    const recover = vi.fn();
    render(
      <DesignPreviewBoundary resetKey="draft-1" onRecover={recover}>
        <BrokenPreview />
      </DesignPreviewBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Preview stopped before Stockroom could go blank");
    fireEvent.click(screen.getByRole("button", { name: "Recover Preview" }));
    expect(recover).toHaveBeenCalledTimes(1);
  });

  it("remounts the preview even when recovery has no history entry", () => {
    let broken = true;
    function RecoverablePreview() {
      if (broken) throw new Error("preview render failed once");
      return <p>Recovered Product Preview</p>;
    }
    const recoverWithoutHistory = () => {
      broken = false;
    };
    render(
      <DesignPreviewBoundary resetKey="unchanged-draft" onRecover={recoverWithoutHistory}>
        <RecoverablePreview />
      </DesignPreviewBoundary>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Recover Preview" }));

    expect(screen.getByText("Recovered Product Preview")).toBeInTheDocument();
  });
});
