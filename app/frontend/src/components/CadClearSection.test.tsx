/**
 * Tests for the Clear CAD Files section.
 *
 * PRIOR ART: no new test infrastructure -- the same vitest + testing-library + per-test
 * QueryClient + real ToastProvider harness every other component test here uses, and the mock
 * shape is `DerivationSection.test.tsx`'s.
 *
 * What these have to prove, because this is the most destructive control in the app: it never
 * acts without a confirm, it states the real numbers, it says what it will NOT touch, and it
 * reports from the job's own result.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { CadInventory } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { CadClearSection } from "./CadClearSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { cadInventory: vi.fn(), clearCad: vi.fn(), openJobStream: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

function inventory(over: Partial<CadInventory> = {}): CadInventory {
  return {
    cleared: 184,
    kept_stock: 136,
    items: Array.from({ length: 128 }, (_, i) => ({
      part_id: `p${i}`,
      assets: ["kicad_symbol"],
    })),
    failed: [],
    missing_files: [],
    ...over,
  };
}

function jobStream(result: CadInventory): ReadableStream<Uint8Array> {
  const text =
    `event: result\ndata: ${JSON.stringify({ result })}\n\n` + "event: done\ndata: {}\n\n";
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(c) {
      c.enqueue(bytes);
      c.close();
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
        <CadClearSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("states the real count of what it holds and what it would remove", async () => {
  mockApi.cadInventory.mockResolvedValue(inventory());
  renderSection();

  expect(await screen.findByText(/Your library holds/)).toHaveTextContent(
    "Your library holds 184 CAD files across 128 components",
  );
});

it("says what it will NOT touch, by count", async () => {
  // The safety property, surfaced. A KiCad-stock reference names no file here, and clearing one
  // would empty a passive permanently because nothing can refill it.
  mockApi.cadInventory.mockResolvedValue(inventory());
  renderSection();

  expect(await screen.findByText(/built-in libraries/)).toHaveTextContent(
    "136 references point at KiCad's own built-in libraries",
  );
});

it("NEVER clears without a confirm", async () => {
  mockApi.cadInventory.mockResolvedValue(inventory());
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Remove All CAD Files" }));

  // The dialog is up and the API has NOT been called. This is the assertion that matters most in
  // this file: a destructive library-wide action must not fire on one click.
  expect(await screen.findByText("Remove Them")).toBeInTheDocument();
  expect(mockApi.clearCad).not.toHaveBeenCalled();
});

it("cancelling leaves the library alone", async () => {
  mockApi.cadInventory.mockResolvedValue(inventory());
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Remove All CAD Files" }));
  await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));

  expect(mockApi.clearCad).not.toHaveBeenCalled();
});

it("confirming asks for the WRITE explicitly and reports what came back", async () => {
  mockApi.cadInventory.mockResolvedValue(inventory());
  mockApi.clearCad.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(
    jobStream(inventory({ cleared: 184, items: [{ part_id: "p0", assets: ["kicad_symbol"] }] })),
  );
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Remove All CAD Files" }));
  await userEvent.click(await screen.findByRole("button", { name: "Remove Them" }));

  // `dryRun: false` is the explicit ask. Without it the backend defaults to a dry run and the
  // button would report a success that changed nothing.
  await waitFor(() => expect(mockApi.clearCad).toHaveBeenCalledWith({ dryRun: false }));
  // `findAllByText`: the toast and the report both say "Removed ...", which is correct --
  // one is transient feedback, the other is the durable record.
  const said = await screen.findAllByText(/^Removed/);
  expect(said.some((n) => n.textContent?.includes("Removed 184 CAD files from 1"))).toBe(true);
});

it("offers nothing when there is no CAD to remove", async () => {
  mockApi.cadInventory.mockResolvedValue(
    inventory({ cleared: 0, kept_stock: 0, items: [] }),
  );
  renderSection();

  expect(await screen.findByText(/holds no CAD files/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove All CAD Files" })).toBeDisabled();
});

it("names a component it could not clear instead of swallowing it", async () => {
  mockApi.cadInventory.mockResolvedValue(inventory());
  mockApi.clearCad.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(
    jobStream(
      inventory({
        cleared: 1,
        items: [{ part_id: "p0", assets: ["kicad_symbol"] }],
        failed: [{ id: "mmm-2222", error: "symbol library is missing" }],
      }),
    ),
  );
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Remove All CAD Files" }));
  await userEvent.click(await screen.findByRole("button", { name: "Remove Them" }));

  expect(await screen.findByText("mmm-2222")).toBeInTheDocument();
});

it("surfaces a failure to even start the clear", async () => {
  mockApi.cadInventory.mockResolvedValue(inventory());
  mockApi.clearCad.mockRejectedValue(new Error("library is locked"));
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Remove All CAD Files" }));
  await userEvent.click(await screen.findByRole("button", { name: "Remove Them" }));

  expect(await screen.findByText("library is locked")).toBeInTheDocument();
  expect(screen.queryAllByText(/^Removed/)).toEqual([]);
});

it("reports a reference whose FILE was not there, instead of counting it as deleted", async () => {
  // The defect this field exists for, measured on the owner's real library: a clear reported 6
  // Altium libraries removed and touched the directory zero times, because the removal rebuilt
  // the filename from the record id while the file is named for the id it had when attached.
  mockApi.cadInventory.mockResolvedValue(inventory());
  mockApi.clearCad.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(
    jobStream(
      inventory({
        cleared: 2,
        items: [{ part_id: "ina226aidgst-d958", assets: ["altium_symbol"] }],
        missing_files: [
          {
            part_id: "ina226aidgst-d958",
            asset: "altium_symbol",
            expected: "altium/ina226aidgst-d958.SchLib",
          },
        ],
      }),
    ),
  );
  renderSection();

  await userEvent.click(await screen.findByRole("button", { name: "Remove All CAD Files" }));
  await userEvent.click(await screen.findByRole("button", { name: "Remove Them" }));

  expect(await screen.findByText(/pointed at a file/)).toBeInTheDocument();
  expect(screen.getByText("altium/ina226aidgst-d958.SchLib")).toBeInTheDocument();
});
