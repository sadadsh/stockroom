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
    fireEvent.click(screen.getByRole("button", { name: "Undo Last Design Change" }));
    expect(recover).toHaveBeenCalledTimes(1);
  });
});
