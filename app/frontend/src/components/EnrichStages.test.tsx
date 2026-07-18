import { render, screen } from "@testing-library/react";
import { EnrichStages } from "./EnrichStages";

describe("EnrichStages", () => {
  it("names the in-flight phase and shows the live message", () => {
    render(<EnrichStages progress={{ stage: "rendering", pct: 45, message: "settling the page" }} />);
    const bar = screen.getByRole("progressbar");
    // the rail reports the current phase for assistive tech and names it in the label line
    expect(bar).toHaveAttribute("aria-valuetext", "Rendering");
    expect(screen.getByText("Rendering")).toBeInTheDocument();
    expect(screen.getByText(/settling the page/)).toBeInTheDocument();
  });

  it("falls back to a plain-language hint before a message arrives", () => {
    render(<EnrichStages progress={{ stage: "validating", pct: 92 }} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Checking");
    expect(screen.getByText(/Checking the pulled values/)).toBeInTheDocument();
  });

  it("treats a queued/absent stage as the first phase, nothing completed yet", () => {
    render(<EnrichStages progress={null} />);
    // no stage yet -> Fetching is the phase in flight (honest: the lookup has just started)
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Fetching");
    expect(screen.getByText(/Starting the lookup/)).toBeInTheDocument();
  });

  it("never rewinds when a later source re-emits an earlier stage (monotonic pct wins)", () => {
    // The MPN walk runs multiple sources: LCSC reaches 'extracting', then the scrape source
    // re-emits 'fetching'. The pipeline clamps pct monotonic, so the rail must track pct and
    // hold its reached phase rather than un-filling completed segments (the confirmed bug).
    const { rerender } = render(<EnrichStages progress={{ stage: "extracting", pct: 80 }} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Reading");
    rerender(<EnrichStages progress={{ stage: "fetching", pct: 80 }} />);
    // held at the reached phase; it did NOT jump back to Fetching
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "Reading");
  });
});
