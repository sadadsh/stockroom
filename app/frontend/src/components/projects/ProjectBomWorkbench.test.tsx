import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../../api/client";
import type { ProjectBom, ProjectWorkspace } from "../../api/types";
import { ToastProvider } from "../../lib/toast";
import { ProjectBomWorkbench } from "./ProjectBomWorkbench";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      liveProjectBom: vi.fn(),
      liveProjectBomExport: vi.fn(),
      projectAssignments: vi.fn(),
      assignProjectGroup: vi.fn(),
      projectPlacementGeometry: vi.fn(),
      projectVisuals: vi.fn(),
      projectVisualArtifact: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const WORKSPACE = { eda_label: "KiCad" } as unknown as ProjectWorkspace;

function bom(boards: number): ProjectBom {
  return {
    project: "Power Board",
    ran_at: "2026-07-29T00:00:00Z",
    boards,
    priced: false,
    line_count: 1,
    component_count: 2 * boards,
    lines: [
      {
        refs: ["R1", "R2"],
        qty: 2,
        value: "10k",
        mpn: "RC0402FR-0710KL",
        manufacturer: "Yageo",
        footprint: "R_0402_1005Metric",
        description: "Resistor",
        package: "0402",
        basic: false,
        in_library: true,
        library_part_id: "resistor-10k",
        final_qty: 2 * boards,
        final_unit_price: null,
        line_total: null,
      },
    ],
    summary: {
      state: "unpriced",
      total_cost: 0,
      priced_lines: 0,
      unpriced_lines: 1,
      line_count: 1,
      currency: "USD",
    },
    evidence: {
      eda: "kicad",
      variant: "Default",
      source_commit: "0123456789abcdef",
      source_documents: ["Power.kicad_sch"],
      bom_digest: "digest",
      repository_pinned: true,
    },
  };
}

beforeEach(() => {
  mockApi.liveProjectBom.mockImplementation(async (_id, boards = 1) => bom(boards));
  mockApi.projectAssignments.mockResolvedValue({
    project: "Power Board",
    eda: "kicad",
    under_git: true,
    binding: { field: "StockroomPartId", writable: true, reason: "" },
    components: 2,
    unassigned: 0,
    bound: [],
    groups: [],
  });
  mockApi.projectPlacementGeometry.mockRejectedValue(new Error("no geometry in test"));
  mockApi.projectVisuals.mockRejectedValue(new Error("no native render in test"));
});

function renderWorkbench() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ProjectBomWorkbench projectId="kicad-project" workspace={WORKSPACE} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ProjectBomWorkbench build quantity", () => {
  it("can be emptied to type a fresh count, and never queries an invalid one", async () => {
    // `Number(event.target.value) || 1` snapped a cleared field straight back to 1, so the
    // field could not be emptied at all: typing 12 over it produced 112. The field now holds
    // the transient empty value while the COMMITTED count stays in 1..999.
    const user = userEvent.setup();
    renderWorkbench();

    const field = await screen.findByLabelText("Board Quantity");
    await waitFor(() =>
      expect(mockApi.liveProjectBom).toHaveBeenCalledWith("kicad-project", 1),
    );

    await user.clear(field);
    expect(field).toHaveValue(null); // an empty number field, not a snapped-back 1

    await user.type(field, "12");
    expect(field).toHaveValue(12);
    await waitFor(() =>
      expect(mockApi.liveProjectBom).toHaveBeenLastCalledWith("kicad-project", 12),
    );
    // Every board count that reached the API was a usable build quantity.
    for (const [, boards] of mockApi.liveProjectBom.mock.calls) {
      expect(boards).toBeGreaterThanOrEqual(1);
      expect(boards).toBeLessThanOrEqual(999);
    }
  });

  it("settles an abandoned empty field back onto the count in force", async () => {
    const user = userEvent.setup();
    renderWorkbench();

    const field = await screen.findByLabelText("Board Quantity");
    await user.clear(field);
    await user.type(field, "8");
    await user.clear(field);
    await user.tab();

    expect(field).toHaveValue(8);
    await waitFor(() =>
      expect(mockApi.liveProjectBom).toHaveBeenLastCalledWith("kicad-project", 8),
    );
  });
});
