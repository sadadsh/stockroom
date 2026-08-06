/**
 * The placement stage's two load-bearing contracts.
 *
 * 1. THE DIAGRAM IS REACHABLE. Every placement, pin and via on the stage is a real control with a
 *    name and a key handler, and the `<svg>` around them must not be the kind of element that makes
 *    its own subtree presentational. It carried `role="img"` for a while, which does exactly that -
 *    the controls rendered, looked right, and were absent from the accessibility tree.
 * 2. A SELECTION BELONGS TO WHAT IT WAS MADE ON. Picking a pad and then changing side, board or
 *    inspected footprint must leave nothing selected: the old selection names a pad that is no
 *    longer on screen.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../../api/client";
import type { ProjectPlacementGeometry, ProjectVisualBundle } from "../../api/types";
import { ProjectPlacementStage } from "./ProjectPlacementStage";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      projectVisuals: vi.fn(),
      projectVisualArtifact: vi.fn(),
      refreshProjectVisuals: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function geometry(boards: string[]): ProjectPlacementGeometry {
  return {
    schema_version: 1,
    adapter: "kicad",
    status: "ready",
    runtime: { name: "kicad", version: "9.0", available: true },
    boards,
    placements: boards.flatMap((board, index) => [
      {
        reference: `R${index + 1}`,
        board,
        x_mm: 10 + index * 4,
        y_mm: 10,
        rotation_deg: 0,
        side: "top" as const,
        footprint: "R_0402",
      },
      {
        reference: `C${index + 1}`,
        board,
        x_mm: 20 + index * 4,
        y_mm: 14,
        rotation_deg: 0,
        side: "bottom" as const,
        footprint: "C_0402",
      },
    ]),
    summary: { boards: boards.length, placements: boards.length * 2, top: 1, bottom: 1 },
    source: { digest: "d", files: [], preserved: true },
    detail: "",
    digest: "d",
  };
}

const SCENE_PIN = {
  net: "VCC",
  rotation_deg: 0,
  side: "top" as const,
  layer: "F.Cu",
  shape: { kind: "rect" as const, width_mm: 0.6, height_mm: 0.6 },
};

function visuals(board: string): ProjectVisualBundle {
  return {
    schema_version: 1,
    adapter: "kicad",
    status: "ready",
    runtime: { name: "kicad", version: "9.0" },
    summary: { documents: 1, artifacts: 0, blocked: 0 },
    digest: "v",
    documents: [
      {
        kind: "pcb",
        path: board,
        status: "ready",
        detail: "",
        artifacts: [],
        scene: {
          schema_version: 1,
          board,
          units: "mm",
          bounds: { min_x: 0, min_y: 0, max_x: 40, max_y: 30, width: 40, height: 30 },
          components: [
            {
              reference: "R1",
              x_mm: 10,
              y_mm: 10,
              rotation_deg: 0,
              side: "top",
              package: "R_0402",
              part: "10k",
              bounds: { min_x: 9, min_y: 9, max_x: 11, max_y: 11, width: 2, height: 2 },
              pins: [
                { ...SCENE_PIN, number: "1", x_mm: 9.5, y_mm: 10 },
                { ...SCENE_PIN, number: "2", x_mm: 10.5, y_mm: 10 },
              ],
            },
          ],
          vias: [],
          tracks: [],
          summary: { components: 1, pins: 2, vias: 0, tracks: 0, top: 1, bottom: 0 },
          source: { format: "ipc-2581", sha256: "s" },
        },
      },
    ],
    detail: "",
  };
}

function renderStage(boards: string[], selectedReferences: string[] = ["R1"]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProjectPlacementStage
        projectId="power"
        geometry={geometry(boards)}
        selectedReferences={selectedReferences}
        activeReference="R1"
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.projectVisuals.mockResolvedValue(visuals("Power.kicad_pcb"));
  mockApi.projectVisualArtifact.mockResolvedValue(new Blob([]));
});

describe("the placement diagram keeps its own controls in the accessibility tree", () => {
  it("names the stage as a GROUP, so the controls inside it are not made presentational", async () => {
    renderStage(["Power.kicad_pcb"]);
    // role="img" would swallow every control below; role="group" keeps them.
    expect(await screen.findByRole("group", { name: "PCB view" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "PCB view" })).toBeNull();
  });

  it("gives each placement a control naming the reference and its footprint", async () => {
    renderStage(["Power.kicad_pcb"]);
    expect(
      await screen.findByRole("button", { name: "R1, R_0402" }),
    ).toBeInTheDocument();
  });
});

describe("the stage says what is selected, and what is on which side", () => {
  it("summarises the whole net a chosen pad sits on, not just the pad", async () => {
    // The counts reach the status line from the same derived scene the diagram draws, so this is
    // the assertion that the picture and its caption are reading one answer. A caption computing
    // its own net could disagree with the peers actually marked on the board.
    const user = userEvent.setup();
    renderStage(["Power.kicad_pcb"]);

    await user.click(await screen.findByRole("button", { name: "R1, Pin 1, VCC" }));

    // Both of R1's pads are on VCC; the fixture board carries no vias and no tracks.
    expect(
      await screen.findByText("Pin 1 · VCC · 2 pads · 0 vias · 0 tracks · Top"),
    ).toBeInTheDocument();
  });

  it("counts each side's placements on its own control, and does not swap them", async () => {
    // Two on top, one on the bottom - deliberately unequal, so a control that read the wrong
    // side's count would show it. An even fixture cannot tell the two filters apart.
    const lopsided: ProjectPlacementGeometry = {
      ...geometry(["Power.kicad_pcb"]),
      placements: [
        {
          reference: "R1",
          board: "Power.kicad_pcb",
          x_mm: 10,
          y_mm: 10,
          rotation_deg: 0,
          side: "top",
          footprint: "R_0402",
        },
        {
          reference: "R2",
          board: "Power.kicad_pcb",
          x_mm: 14,
          y_mm: 10,
          rotation_deg: 0,
          side: "top",
          footprint: "R_0402",
        },
        {
          reference: "C1",
          board: "Power.kicad_pcb",
          x_mm: 20,
          y_mm: 14,
          rotation_deg: 0,
          side: "bottom",
          footprint: "C_0402",
        },
      ],
    };
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={client}>
        <ProjectPlacementStage
          projectId="power"
          geometry={lopsided}
          selectedReferences={["R1"]}
          activeReference="R1"
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("radio", { name: "Top · 2" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Bottom · 1" })).toBeInTheDocument();
  });
});

describe("the bottom side is seen through the board, not from above it", () => {
  // Two parts a side, each pair symmetric about the board's centre line, so the ORDER of their
  // marks states the mirroring on its own - no dependence on the fitted view box.
  const MIRROR_GEOMETRY: ProjectPlacementGeometry = {
    ...geometry(["Power.kicad_pcb"]),
    placements: (
      [
        ["R1", 10, "top"],
        ["R2", 30, "top"],
        ["C1", 10, "bottom"],
        ["C2", 30, "bottom"],
      ] as const
    ).map(([reference, x, side]) => ({
      reference,
      board: "Power.kicad_pcb",
      x_mm: x,
      y_mm: 15,
      rotation_deg: 0,
      side,
      footprint: "R_0402",
    })),
  };

  function markX(container: HTMLElement, reference: string): number {
    const mark = container.querySelector<SVGGElement>(`[data-reference="${reference}"]`)!;
    const transform = mark.parentElement!.getAttribute("transform")!;
    return Number(/translate\(([-\d.]+) /.exec(transform)![1]);
  }

  it("mirrors a bottom-side placement across the board, so the two ends swap", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const view = render(
      <QueryClientProvider client={client}>
        <ProjectPlacementStage
          projectId="power"
          geometry={MIRROR_GEOMETRY}
          selectedReferences={["R1", "R2", "C1", "C2"]}
          activeReference=""
        />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(view.container.querySelector('[data-reference="R2"]')).not.toBeNull(),
    );
    const topLeft = markX(view.container, "R1");
    const topRight = markX(view.container, "R2");
    expect(topLeft).toBeLessThan(topRight);

    // The same millimetres, read from underneath: the part on the left of the top view is on the
    // right of the bottom view. A layer that dropped the reflection would keep the order.
    await user.click(screen.getByRole("radio", { name: /Bottom/ }));
    await waitFor(() =>
      expect(view.container.querySelector('[data-reference="C2"]')).not.toBeNull(),
    );
    const bottomLeft = markX(view.container, "C1");
    const bottomRight = markX(view.container, "C2");
    expect(bottomLeft).toBeGreaterThan(bottomRight);
    // And it is a reflection, not an arbitrary shift: the pair still straddles the same centre.
    expect(topLeft + topRight).toBeCloseTo(bottomLeft + bottomRight, 5);
  });
});

describe("a selection belongs to the board, side and footprint it was made on", () => {
  it("drops a selected pad when the side changes", async () => {
    const user = userEvent.setup();
    renderStage(["Power.kicad_pcb"]);

    const pad = await screen.findByRole("button", { name: "R1, Pin 1, VCC" });
    expect(document.querySelectorAll("[data-net-peer]")).toHaveLength(0);

    // Selecting a pad traces its net: every pad on that net is marked as a peer.
    await user.click(pad);
    expect(document.querySelectorAll("[data-net-peer]").length).toBeGreaterThan(0);

    // Leaving the side and coming back must not bring the selection back with it: the pad the
    // trace was anchored to went off screen in between.
    await user.click(screen.getByRole("radio", { name: /Bottom/ }));
    await user.click(screen.getByRole("radio", { name: /Top/ }));
    await screen.findByRole("button", { name: "R1, Pin 1, VCC" });
    expect(document.querySelectorAll("[data-net-peer]")).toHaveLength(0);
  });

  it("shows a board that exists, whichever boards the project reports", async () => {
    const { rerender } = renderStage(["A.kicad_pcb", "B.kicad_pcb"]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    expect(await screen.findByTitle("A.kicad_pcb")).toBeInTheDocument();

    // The reported boards change under the picker. There must be no render in which the stage still
    // names the board that is gone.
    rerender(
      <QueryClientProvider client={client}>
        <ProjectPlacementStage
          projectId="power"
          geometry={geometry(["B.kicad_pcb"])}
          selectedReferences={["R1"]}
          activeReference="R1"
        />
      </QueryClientProvider>,
    );
    expect(screen.queryByTitle("A.kicad_pcb")).toBeNull();
    expect(screen.getByTitle("B.kicad_pcb")).toBeInTheDocument();
  });
});
