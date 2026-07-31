import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { api } from "../../api/client";
import type {
  AssemblyRun,
  ProjectCollaboration,
  ProjectPlacementGeometry,
} from "../../api/types";
import { ToastProvider } from "../../lib/toast";
import { ProjectAssemblyWorkbench } from "./ProjectAssemblyWorkbench";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      activeAssembly: vi.fn(),
      startAssembly: vi.fn(),
      recordAssemblyEvent: vi.fn(),
      completeAssembly: vi.fn(),
      projectCollaboration: vi.fn(),
      projectPlacementGeometry: vi.fn(),
      projectVisuals: vi.fn(),
      projectVisualArtifact: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const COLLABORATION: ProjectCollaboration = {
  repository: {
    root: "C:\\Projects\\Power",
    remote: "origin",
    branch: "main",
    commit: "0123456789abcdef",
    clean: true,
    dirty_paths: [],
    has_remote: true,
    has_upstream: true,
    ahead: 0,
    behind: 0,
  },
  session: null,
  recovery: null,
};

const GEOMETRY: ProjectPlacementGeometry = {
  schema_version: 1,
  adapter: "kicad",
  status: "ready",
  runtime: { name: "KiCad", available: true },
  boards: ["Power.kicad_pcb"],
  placements: ["R1", "R2"].map((reference, index) => ({
    reference,
    board: "Power.kicad_pcb",
    x_mm: 10 + index * 10,
    y_mm: 18.5,
    rotation_deg: 0,
    side: "top",
    footprint: "R_0402_1005Metric",
  })),
  summary: { boards: 1, placements: 2, top: 2, bottom: 0 },
  source: { digest: "source", files: [], preserved: true },
  detail: "Placement data ready.",
  digest: "geometry",
};

// The backend emits one placement per (board_index, component) with its own placement_id
// (projects/assembly.py::_snapshot_placements), so a 2-board run of R1/R2 is four rows.
function run(boards: number): AssemblyRun {
  const placements = Array.from({ length: boards }, (_, board) =>
    ["R1", "R2"].map((reference, ordinal) => ({
      placement_id: `placement-${board + 1}-${ordinal + 1}`,
      board_index: board + 1,
      native_id: `native-${reference}`,
      reference,
      sheet: "Main Schematic",
      value: "10k",
      footprint: "R_0402_1005Metric",
      part_id: "resistor-10k",
      mpn: "RC0402FR-0710KL",
      manufacturer: "Yageo",
      state: "pending" as const,
      last_event: null,
    })),
  ).flat();
  return {
    schema_version: 1,
    id: "assembly-1",
    project_id: "kicad-project",
    project_name: "Power Board",
    eda: "kicad",
    operator: "Sadad",
    boards,
    source_commit: "0123456789abcdef",
    project_digest: "project-digest",
    started_at: "2026-07-29T00:00:00Z",
    completed_at: "",
    status: "active",
    placements,
    events: [],
    progress: {
      total: placements.length,
      complete: 0,
      resolved: 0,
      percent: 0,
      counts: {
        pending: placements.length,
        done: 0,
        skipped: 0,
        reworked: 0,
        issue: 0,
      },
    },
  };
}

beforeEach(() => {
  mockApi.projectCollaboration.mockResolvedValue(COLLABORATION);
  mockApi.projectPlacementGeometry.mockResolvedValue(GEOMETRY);
  mockApi.projectVisuals.mockRejectedValue(new Error("no native render in test"));
});

function renderWorkbench() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ProjectAssemblyWorkbench projectId="kicad-project" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ProjectAssemblyWorkbench placement queue", () => {
  it("groups the queue by board and names the board on every row (VA-039)", async () => {
    mockApi.activeAssembly.mockResolvedValue(run(3));
    const { container } = renderWorkbench();

    const selector = await screen.findByRole("combobox", { name: "Placement" });
    // Sorted pending-then-BOARD-then-reference. Without the board term the same three
    // references interleaved and every row read "R1 · Pending · ...", so a three-board
    // run listed nine placements that could not be told apart.
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "Board 1 · R1 · Pending · RC0402FR-0710KL",
      "Board 1 · R2 · Pending · RC0402FR-0710KL",
      "Board 2 · R1 · Pending · RC0402FR-0710KL",
      "Board 2 · R2 · Pending · RC0402FR-0710KL",
      "Board 3 · R1 · Pending · RC0402FR-0710KL",
      "Board 3 · R2 · Pending · RC0402FR-0710KL",
    ]);

    // The wide queue carries one banner per board run plus a board tag on each of its rows.
    const queue = container.querySelector("section")!;
    for (const board of ["Board 1", "Board 2", "Board 3"]) {
      expect(within(queue).getAllByText(board)).toHaveLength(3);
    }
  });

  it("leaves a single-board run unlabelled, since there is nothing to disambiguate", async () => {
    mockApi.activeAssembly.mockResolvedValue(run(1));
    const { container } = renderWorkbench();

    const selector = await screen.findByRole("combobox", { name: "Placement" });
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "R1 · Pending · RC0402FR-0710KL",
      "R2 · Pending · RC0402FR-0710KL",
    ]);
    const queue = container.querySelector("section")!;
    expect(within(queue).queryByText("Board 1")).toBeNull();
  });
});
