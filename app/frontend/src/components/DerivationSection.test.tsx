/**
 * Tests for the Presentation Data section.
 *
 * PRIOR ART: no new test infrastructure. Same harness the repo already standardises on (vitest +
 * @testing-library/react + a per-test QueryClient and the real ToastProvider), and the mock shape
 * uses the same explicit QueryClient defaults as the other isolated section tests. REJECTED: hoisting the
 * three-line `renderSection` into a shared helper -- every component test here keeps its own, and
 * one more instance is not yet a pattern worth reading every test through a helper for.
 *
 * What these have to prove, beyond "it renders": the section's whole reason to exist is telling
 * three different stale states apart, and reporting what a rebuild ACTUALLY wrote rather than the
 * fact that it was started.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { DerivationReport, LibraryDerivation } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { DerivationSection } from "./DerivationSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      libraryDerivation: vi.fn(),
      rebuildDerivation: vi.fn(),
      openJobStream: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function derivation(over: Partial<LibraryDerivation> = {}): LibraryDerivation {
  return { ruleset: "rules@2", counts: { "rules@2": 158 }, current: 158, stale: 0, ...over };
}

function report(over: Partial<DerivationReport> = {}): DerivationReport {
  return {
    ruleset: "rules@2",
    checked: 158,
    rewritten: 158,
    unchanged: 0,
    no_evidence: 0,
    failed: [],
    ...over,
  };
}

/** A job SSE body carrying one terminal `result` event, exactly as the backend streams it. */
function jobStream(result: DerivationReport): ReadableStream<Uint8Array> {
  const text =
    `event: result\ndata: ${JSON.stringify({ result })}\n\n` + "event: done\ndata: {}\n\n";
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <DerivationSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("names the ruleset running, so 'current' has a referent", async () => {
  mockApi.libraryDerivation.mockResolvedValue(derivation());
  renderSection();

  expect(await screen.findByText(/All/)).toHaveTextContent("rules@2");
});

it("offers nothing to do when every component is already current", async () => {
  mockApi.libraryDerivation.mockResolvedValue(derivation());
  renderSection();

  // The action is present but inert: a button that would change nothing must not invite a click.
  expect(await screen.findByRole("button", { name: "Recompute Presentation Data" })).toBeDisabled();
});

it("tells an OLDER ruleset, a NEWER one and never-derived apart", async () => {
  // The reason this section is a per-stamp ledger rather than one "N behind" number. These three
  // are different problems: this build is ahead, this build is BEHIND a peer, and nothing has
  // ever derived those parts. A single count would flatten all three into one.
  mockApi.libraryDerivation.mockResolvedValue(
    derivation({
      counts: { "rules@1": 40, "rules@2": 100, "rules@3": 15, "": 3 },
      current: 100,
      stale: 58,
    }),
  );
  renderSection();

  const rows = await screen.findAllByRole("row");
  const text = (needle: string) =>
    rows.find((r) => r.textContent?.includes(needle))?.textContent ?? "";
  expect(text("rules@1")).toContain("Behind");
  expect(text("rules@2")).toContain("Current");
  expect(text("rules@3")).toContain("From A Newer Build");
  expect(text("None")).toContain("Never Derived");
});

it("reports what the rebuild actually wrote, not that it was started", async () => {
  mockApi.libraryDerivation.mockResolvedValue(
    derivation({ counts: { "rules@1": 158 }, current: 0, stale: 158 }),
  );
  mockApi.rebuildDerivation.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(
    jobStream(report({ checked: 158, rewritten: 120, unchanged: 30, no_evidence: 8 })),
  );
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Recompute Presentation Data" }));

  await waitFor(() => {
    expect(screen.getByText(/Checked/)).toHaveTextContent("Checked 158");
  });
  // The three numbers the report is FOR, each carrying a different meaning.
  expect(screen.getByText(/Checked/)).toHaveTextContent("recomputed 120");
  expect(screen.getByText(/Checked/)).toHaveTextContent("already current 30");
});

it("says a component with no stored data was LEFT ALONE, never that it was done", async () => {
  // The safety property, surfaced. Recomputing a part with no evidence would blank it, so the
  // engine skips it -- and the report has to say so, or a skip reads as a success.
  mockApi.libraryDerivation.mockResolvedValue(
    derivation({ counts: { "rules@1": 10 }, current: 0, stale: 10 }),
  );
  mockApi.rebuildDerivation.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(
    jobStream(report({ checked: 10, rewritten: 2, unchanged: 0, no_evidence: 8 })),
  );
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Recompute Presentation Data" }));

  expect(await screen.findByText(/no stored distributor data/)).toHaveTextContent(
    "8 components have no stored distributor data",
  );
});

it("names a component it could not read instead of swallowing it", async () => {
  mockApi.libraryDerivation.mockResolvedValue(
    derivation({ counts: { "rules@1": 3 }, current: 0, stale: 3 }),
  );
  mockApi.rebuildDerivation.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(
    jobStream(
      report({
        checked: 3,
        rewritten: 2,
        failed: [{ id: "mmm-2222", error: "Expecting property name" }],
      }),
    ),
  );
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Recompute Presentation Data" }));

  expect(await screen.findByText("mmm-2222")).toBeInTheDocument();
  expect(screen.getByText(/1 Component Could Not Be Read/)).toBeInTheDocument();
});

it("surfaces a failure to even start the rebuild", async () => {
  mockApi.libraryDerivation.mockResolvedValue(
    derivation({ counts: { "rules@1": 3 }, current: 0, stale: 3 }),
  );
  mockApi.rebuildDerivation.mockRejectedValue(new Error("library is locked"));
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Recompute Presentation Data" }));

  expect(await screen.findByText("library is locked")).toBeInTheDocument();
  // And no report is shown: nothing ran, so nothing is claimed.
  expect(screen.queryByText(/Checked/)).toBeNull();
});

it("says ALL, not 'N of N', when nothing in the library is current", () => {
  // A count whose numerator equals its denominator reads as broken. This was visible in the very
  // first screenshot of this section: "162 of 162 components were built by different rules".
  mockApi.libraryDerivation.mockResolvedValue(
    derivation({ counts: { "rules@1": 158, "": 4 }, current: 0, stale: 162 }),
  );
  renderSection();

  return waitFor(() => {
    const summary = screen.getByText(/components were built/);
    expect(summary).toHaveTextContent("None of the 162 components");
    expect(summary.textContent).not.toMatch(/162 of 162/);
  });
});
