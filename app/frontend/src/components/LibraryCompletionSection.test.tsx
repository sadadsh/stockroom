/**
 * The completion surface, tested for the things that make a report TRUSTWORTHY rather than
 * merely present. Most of these assert a distinction the UI must not collapse, because every
 * one of them, collapsed, turns into the surface quietly lying about the library.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LibraryCompletionSection } from "./LibraryCompletionSection";
import { ToastProvider } from "../lib/toast";
import { api } from "../api/client";
import { resetCompletion } from "../lib/completionStore";
import type { LibraryCoverage } from "../api/types";

function coverage(over: Partial<LibraryCoverage> = {}): LibraryCoverage {
  return {
    total: 158,
    complete: 92,
    needs_files: 47,
    unsourced: 19,
    by_requirement: {
      kicad_symbol: 66,
      kicad_footprint: 66,
      kicad_model: 68,
      altium_symbol: 155,
      altium_footprint: 155,
    },
    sources: ["lcsc"],
    can_provide: ["kicad_footprint", "kicad_model", "kicad_symbol"],
    ...over,
  };
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LibraryCompletionSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  resetCompletion();
  vi.restoreAllMocks();
});

describe("coverage", () => {
  it("says how many components hold every file they need", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(
      await screen.findByText(/components have every file they need/i),
    ).toBeInTheDocument();
    // 92 appears in the headline AND in the KiCad symbol cell, which is correct: the sentence
    // and the matrix are two readings of the same fact.
    expect(screen.getAllByText("92").length).toBeGreaterThan(0);
  });

  it("shows both EDA tools as rows, so a missing tool cannot be averaged away", async () => {
    // The whole reason this is a matrix and not a percentage: 3 of 158 parts have Altium files,
    // and one number over 158 parts would report that as a healthy-looking library.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(await screen.findByRole("rowheader", { name: "KiCad" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Altium" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "3D Model" })).toBeInTheDocument();
  });

  it("counts each cell as have-of-total, not as an anonymous missing number", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    // kicad_symbol: 66 of 158 missing -> 92 have.
    await screen.findByRole("rowheader", { name: "KiCad" });
    expect(screen.getAllByText("of 158").length).toBeGreaterThan(0);
  });

  it("marks a requirement no source can supply, instead of showing it as pending work", async () => {
    // Altium gaps are real and reported, but a run cannot touch them. Presenting them as work
    // the button will do is a promise the app cannot keep.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect((await screen.findAllByText("No Source")).length).toBe(2);
  });

  it("states the number the action will actually work on, and how long it takes", async () => {
    // 47 parts at ~8/minute is 6 minutes. A run whose cost is discovered rather than stated is
    // one nobody can consent to.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    // "can be filled" would be a promise the run cannot keep: 19 of those have no catalogue
    // entry and will find nothing. The copy says what is TRIED, not what is guaranteed.
    expect(await screen.findByText(/47 components have gaps a source can try/i)).toBeInTheDocument();
    expect(screen.getByText(/Not every one will find files/i)).toBeInTheDocument();
    expect(screen.getByText(/about 6 minutes/i)).toBeInTheDocument();
  });

  it("estimates a 10,000 part library in hours, not in 1250 minutes", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ total: 10000, complete: 0, needs_files: 10000, unsourced: 0 }),
    );
    renderSection();
    expect(await screen.findByText(/about 20.8 hours/i)).toBeInTheDocument();
  });

  it("separately names the components no automatic source can reach", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(
      await screen.findByText(/no automatic source can supply yet/i),
    ).toBeInTheDocument();
  });

  it("disables the action when there is genuinely nothing to do", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ complete: 158, needs_files: 0, unsourced: 0, by_requirement: {} }),
    );
    renderSection();
    expect(
      await screen.findByText(/All 158 components have every file they need/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete My Library" })).toBeDisabled();
  });

  it("says so plainly when the library is empty", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ total: 0, complete: 0, needs_files: 0, unsourced: 0, by_requirement: {} }),
    );
    renderSection();
    expect(await screen.findByText(/no components yet/i)).toBeInTheDocument();
  });

  it("reports a read failure instead of rendering a confident zero", async () => {
    vi.spyOn(api, "libraryCoverage").mockRejectedValue(new Error("nope"));
    renderSection();
    expect(await screen.findByText(/Could not read your library/i)).toBeInTheDocument();
  });
});

describe("running", () => {
  function streamOf(events: { event: string; data: unknown }[]): ReadableStream<Uint8Array> {
    const text = events
      .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
      .join("");
    return new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    });
  }

  it("streams each part as it is filed, and offers a way out", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    let release: () => void = () => {};
    const held = new Promise<void>((r) => (release = r));
    vi.spyOn(api, "openJobStream").mockImplementation(async () => {
      await held;
      return streamOf([
        { event: "result", data: { result: { items: [], counts: {}, stopped: false, stop_reason: "" } } },
      ]);
    });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Complete My Library" }));
    // A run that cannot be stopped is a commitment the user cannot take back.
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
    release();
  });

  it("keeps a rate-limited part apart from one nothing can help", async () => {
    // The distinction the whole report rests on. `deferred` means run it again; `unchanged`
    // means do not bother. Merging them makes the report useless for deciding what to do next.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        {
          event: "result",
          data: {
            result: {
              items: [],
              counts: { completed: 10, deferred: 33, unchanged: 19 },
              stopped: false,
              stop_reason: "",
            },
          },
        },
      ]),
    );
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Complete My Library" }));
    expect(await screen.findByText("10 Filed")).toBeInTheDocument();
    expect(screen.getByText("33 To Retry")).toBeInTheDocument();
    expect(screen.getByText("19 No Source")).toBeInTheDocument();
  });

  it("shows the reason a run stopped itself", async () => {
    // A stop with no reason is indistinguishable from a crash.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        {
          event: "result",
          data: {
            result: {
              items: [],
              counts: { deferred: 5 },
              stopped: true,
              stop_reason: "the catalogue is refusing requests, so the run stopped",
            },
          },
        },
      ]),
    );
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Complete My Library" }));
    expect(
      await screen.findByText(/the catalogue is refusing requests/i),
    ).toBeInTheDocument();
  });

  it("surfaces a failure to start rather than sitting on a spinner", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockRejectedValue(new Error("backend is down"));
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Complete My Library" }));
    // Reported in two places on purpose: the toast is transient, the paragraph persists.
    await waitFor(() =>
      expect(screen.getAllByText(/backend is down/i).length).toBeGreaterThan(0),
    );
  });
});
