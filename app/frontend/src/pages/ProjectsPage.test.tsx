import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type {
  AssemblyRun,
  ProjectBom,
  ProjectCollaboration,
  ProjectPlacementGeometry,
  ProjectSummary,
  ProjectVisualBundle,
  ProjectWorkspace,
} from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listProjects: vi.fn(),
      discoverProjects: vi.fn(),
      registerProject: vi.fn(),
      projectWorkspace: vi.fn(),
      projectPlacementGeometry: vi.fn(),
      projectVisuals: vi.fn(),
      projectVisualArtifact: vi.fn(),
      projectCollaboration: vi.fn(),
      openProjectDocument: vi.fn(),
      connectProjectRemote: vi.fn(),
      projectReviews: vi.fn(),
      projectReviewEvidence: vi.fn(),
      liveProjectBom: vi.fn(),
      projectAssignments: vi.fn(),
      assignProjectGroup: vi.fn(),
      activeAssembly: vi.fn(),
      startAssembly: vi.fn(),
      recordAssemblyEvent: vi.fn(),
      completeAssembly: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const PROJECTS: ProjectSummary[] = [
  {
    id: "kicad-project",
    name: "Power Board",
    root: "C:\\Projects\\Power",
    eda: "kicad",
    board_count: 1,
    sheet_count: 2,
    has_git: true,
    registered_at: "2026-07-29T00:00:00Z",
  },
  {
    id: "altium-project",
    name: "Control Board",
    root: "C:\\Projects\\Control",
    eda: "altium",
    board_count: 1,
    sheet_count: 2,
    has_git: true,
    registered_at: "2026-07-29T00:00:00Z",
  },
];

const TOOL_CONTRACT: ProjectWorkspace["parity"]["tools"] = [
  "design",
  "bom",
  "assemble",
  "changes",
  "releases",
].map((key) => ({
  key: key as "design" | "bom" | "assemble" | "changes" | "releases",
  label: key,
  status: key === "releases" ? "planned" : "active",
  behavior: "identical",
  actions: [],
  inputs: [],
  states: [],
  results: [],
  recovery: [],
  acceptance: [],
}));

function workspace(eda: "kicad" | "altium"): ProjectWorkspace {
  const project = PROJECTS.find((entry) => entry.eda === eda)!;
  return {
    project: {
      id: project.id,
      name: project.name,
      root: project.root,
      pro_path: eda === "kicad" ? "Power.kicad_pro" : "Control.PrjPcb",
      board_paths: [eda === "kicad" ? "Power.kicad_pcb" : "Control.PcbDoc"],
      sheet_paths: [eda === "kicad" ? "Power.kicad_sch" : "Control.SchDoc"],
      eda,
      git_root: project.root,
    },
    eda_label: eda === "kicad" ? "KiCad" : "Altium Designer",
    tools: ["design", "bom", "assemble", "changes", "releases"],
    parity: {
      schema: "stockroom-project-parity/1",
      edas: ["kicad", "altium"],
      strict: true,
      adapter_boundary: "native_io_only",
      tools: TOOL_CONTRACT,
    },
    runtime: {
      adapter_key: eda,
      available: true,
      status: "ready",
      version: "26",
      detail: "Native runtime ready.",
    },
    documents: [
      {
        document_id: `${eda}-schematic`,
        path: eda === "kicad" ? "Power.kicad_sch" : "Control.SchDoc",
        label: "Main Schematic",
        kind: "schematic",
        exists: true,
        lock_required: true,
      },
      {
        document_id: `${eda}-board`,
        path: eda === "kicad" ? "Power.kicad_pcb" : "Control.PcbDoc",
        label: "Main PCB",
        kind: "pcb",
        exists: true,
        lock_required: true,
      },
    ],
  };
}

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

const BOM: ProjectBom = {
  project: "Power Board",
  ran_at: "2026-07-29T00:00:00Z",
  boards: 1,
  priced: false,
  line_count: 1,
  component_count: 2,
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
      final_qty: 2,
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

function placementGeometry(
  eda: "kicad" | "altium",
): ProjectPlacementGeometry {
  return {
    schema_version: 1,
    adapter: eda,
    status: "ready",
    runtime: { name: eda === "kicad" ? "KiCad" : "Altium Designer", available: true },
    boards: [eda === "kicad" ? "Power.kicad_pcb" : "Control.PcbDoc"],
    placements: [
      {
        reference: "R1",
        board: eda === "kicad" ? "Power.kicad_pcb" : "Control.PcbDoc",
        x_mm: 10.25,
        y_mm: 18.5,
        rotation_deg: 90,
        side: "top",
        footprint: "R_0402_1005Metric",
      },
      {
        reference: "R2",
        board: eda === "kicad" ? "Power.kicad_pcb" : "Control.PcbDoc",
        x_mm: 24.5,
        y_mm: 18.5,
        rotation_deg: 270,
        side: "top",
        footprint: "R_0402_1005Metric",
      },
    ],
    summary: { boards: 1, placements: 2, top: 2, bottom: 0 },
    source: { digest: "source", files: [], preserved: true },
    detail: "Placement data ready.",
    digest: "geometry",
  };
}

function projectVisuals(eda: "kicad" | "altium"): ProjectVisualBundle {
  const path = eda === "kicad" ? "Power.kicad_pcb" : "Control.PcbDoc";
  return {
    schema_version: 1,
    adapter: eda,
    status: "ready",
    runtime: {
      name: eda === "kicad" ? "KiCad CLI" : "Altium Designer",
      version: "test",
    },
    documents: [
      {
        kind: "pcb",
        path,
        status: "ready",
        detail: "Native top and bottom board views",
        scene: {
          schema_version: 1,
          board: path,
          units: "mm",
          bounds: {
            min_x: 0,
            min_y: 0,
            max_x: 40,
            max_y: 30,
            width: 40,
            height: 30,
          },
          components: [
            {
              reference: "R1",
              x_mm: 10.25,
              y_mm: 18.5,
              rotation_deg: 90,
              side: "top",
              package: "R_0402_1005Metric",
              part: "10k",
              bounds: {
                min_x: -0.5,
                min_y: -0.25,
                max_x: 0.5,
                max_y: 0.25,
                width: 1,
                height: 0.5,
              },
              pins: [
                {
                  number: "1",
                  net: "GND",
                  x_mm: 9.9,
                  y_mm: 18.5,
                  rotation_deg: 90,
                  side: "top",
                  layer: eda === "kicad" ? "F.Cu" : "TopLayer",
                  shape: {
                    kind: "rounded-rect",
                    width_mm: 0.5,
                    height_mm: 0.6,
                  },
                },
              ],
            },
            {
              reference: "R2",
              x_mm: 24.5,
              y_mm: 18.5,
              rotation_deg: 270,
              side: "top",
              package: "R_0402_1005Metric",
              part: "10k",
              bounds: {
                min_x: -0.5,
                min_y: -0.25,
                max_x: 0.5,
                max_y: 0.25,
                width: 1,
                height: 0.5,
              },
              pins: [
                {
                  number: "2",
                  net: "GND",
                  x_mm: 24.1,
                  y_mm: 18.5,
                  rotation_deg: 270,
                  side: "top",
                  layer: eda === "kicad" ? "F.Cu" : "TopLayer",
                  shape: {
                    kind: "rounded-rect",
                    width_mm: 0.5,
                    height_mm: 0.6,
                  },
                },
              ],
            },
          ],
          vias: [
            {
              name: "Via_1",
              net: "GND",
              x_mm: 17,
              y_mm: 18.5,
              diameter_mm: 0.3,
              from_layer: eda === "kicad" ? "" : "TopLayer",
              to_layer: eda === "kicad" ? "" : "BottomLayer",
              sides: ["top", "bottom"],
            },
          ],
          tracks: [
            {
              net: "GND",
              layer: eda === "kicad" ? "F.Cu" : "TopLayer",
              side: "top",
              start_x_mm: 9.9,
              start_y_mm: 18.5,
              end_x_mm: 17,
              end_y_mm: 18.5,
              width_mm: 0.254,
            },
          ],
          summary: {
            components: 2,
            pins: 2,
            vias: 1,
            tracks: 1,
            top: 2,
            bottom: 0,
          },
          source: { format: "ipc-2581", sha256: `${eda}-scene-digest` },
        },
        artifacts: [
          {
            id: `${eda}-top`,
            kind: "pcb",
            path,
            view: "top",
            label: "Top copper + mask + silkscreen",
            page: 1,
            media_type: "image/svg+xml",
            width: 1000,
            height: 620,
            bytes: 64,
            sha256: `${eda}-top-digest`,
          },
        ],
      },
    ],
    summary: { documents: 1, artifacts: 1, blocked: 0 },
    detail: "Native PCB views are ready",
    digest: `${eda}-visuals`,
  };
}

const ASSEMBLY: AssemblyRun = {
  schema_version: 1,
  id: "assembly-1",
  project_id: "kicad-project",
  project_name: "Power Board",
  eda: "kicad",
  operator: "Sadad",
  boards: 1,
  source_commit: "0123456789abcdef",
  project_digest: "project-digest",
  started_at: "2026-07-29T00:00:00Z",
  completed_at: "",
  status: "active",
  placements: ["R1", "R2"].map((reference, index) => ({
    placement_id: `placement-${index + 1}`,
    board_index: 1,
    native_id: `native-${reference}`,
    reference,
    sheet: "Main Schematic",
    value: "10k",
    footprint: "R_0402_1005Metric",
    part_id: "resistor-10k",
    mpn: "RC0402FR-0710KL",
    manufacturer: "Yageo",
    state: "pending",
    last_event: null,
  })),
  events: [],
  progress: {
    total: 2,
    complete: 0,
    resolved: 0,
    percent: 0,
    counts: { pending: 2, done: 0, skipped: 0, reworked: 0, issue: 0 },
  },
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ProjectsPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.listProjects.mockResolvedValue(PROJECTS);
  mockApi.discoverProjects.mockResolvedValue({ projects: [] });
  mockApi.registerProject.mockResolvedValue(PROJECTS[0]);
  mockApi.projectWorkspace.mockImplementation(async (id) =>
    workspace(id === "altium-project" ? "altium" : "kicad"),
  );
  mockApi.projectPlacementGeometry.mockImplementation(async (id) =>
    placementGeometry(id === "altium-project" ? "altium" : "kicad"),
  );
  mockApi.projectVisuals.mockImplementation(async (id) =>
    projectVisuals(id === "altium-project" ? "altium" : "kicad"),
  );
  mockApi.projectVisualArtifact.mockResolvedValue(
    new Blob(["<svg viewBox='0 0 1000 620'/>"], { type: "image/svg+xml" }),
  );
  mockApi.projectCollaboration.mockResolvedValue(COLLABORATION);
  mockApi.openProjectDocument.mockResolvedValue({
    opened: true,
    document_id: "pcb:Power.kicad_pcb",
    path: "Power.kicad_pcb",
  });
  mockApi.connectProjectRemote.mockResolvedValue({
    collaboration: COLLABORATION,
    sync: {
      state: "pushed",
      pulled: false,
      pushed: true,
      converged: false,
      detail: "",
    },
  });
  mockApi.projectReviews.mockResolvedValue({ base_branch: "main", candidates: [] });
  mockApi.liveProjectBom.mockResolvedValue(BOM);
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
  mockApi.assignProjectGroup.mockResolvedValue({
    project: "Power Board",
    refs: ["R1", "R2"],
    part_id: "resistor-10k",
    bound: 2,
    committed: null,
  });
  mockApi.activeAssembly.mockResolvedValue(ASSEMBLY);
  mockApi.recordAssemblyEvent.mockResolvedValue({
    ...ASSEMBLY,
    placements: [
      { ...ASSEMBLY.placements[0], state: "done" },
      ASSEMBLY.placements[1],
    ],
    progress: {
      ...ASSEMBLY.progress,
      complete: 1,
      resolved: 1,
      percent: 50,
      counts: { ...ASSEMBLY.progress.counts, pending: 1, done: 1 },
    },
  });
});

describe("ProjectsPage shared workspace", () => {
  it("preselects the only discovered project so linking takes one confirmation", async () => {
    const user = userEvent.setup();
    mockApi.discoverProjects.mockResolvedValueOnce({
      projects: [
        {
          eda: "kicad",
          eda_label: "KiCad",
          name: "Power Board",
          root: "C:\\Projects\\Power",
          descriptor: "C:\\Projects\\Power\\Power.kicad_pro",
          boards: ["C:\\Projects\\Power\\Power.kicad_pcb"],
          schematics: ["C:\\Projects\\Power\\Power.kicad_sch"],
        },
      ],
    });
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("button", { name: "Link Project" }));
    const dialog = screen.getByRole("dialog", { name: "Link Project" });
    await user.type(
      within(dialog).getByPlaceholderText("Project or repository folder"),
      "C:\\Projects\\Power",
    );
    await user.click(within(dialog).getByRole("button", { name: "Find Projects" }));

    expect(
      await within(dialog).findByRole("radio", { name: /Power Board/ }),
    ).toHaveAttribute("aria-checked", "true");
    const link = within(dialog).getByRole("button", { name: "Link Project" });
    expect(link).toBeEnabled();
    await user.click(link);

    expect(mockApi.registerProject).toHaveBeenCalledWith(
      "C:\\Projects\\Power",
      "kicad",
    );
  });

  it("exposes the same selected-project views for KiCad and Altium projects", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole("heading", { name: "Power Board" })).toBeInTheDocument();
    expect(toolNames()).toEqual(["Overview", "BOM", "Build", "Activity"]);
    expect(screen.getAllByText("KiCad").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "PCB view" })).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: /Control Board/ }));
    expect(await screen.findByRole("heading", { name: "Control Board" })).toBeInTheDocument();
    expect(toolNames()).toEqual(["Overview", "BOM", "Build", "Activity"]);
    expect(screen.getAllByText("Altium Designer").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "PCB view" })).toBeInTheDocument();
  });

  it("shows the same native PCB canvas for KiCad and Altium projects", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() =>
      expect(
        document.querySelector('[data-dev-id="projects.native-board-render"]'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Native PCB")).not.toBeInTheDocument();
    expect(mockApi.projectVisualArtifact).toHaveBeenCalledWith(
      "kicad-project",
      "kicad-top",
    );
    const kicadMap = screen.getByRole("region", { name: "PCB view" });
    await user.click(within(kicadMap).getByRole("button", { name: /R1,/ }));
    await user.click(
      within(kicadMap).getByRole("button", { name: "R1, Pin 1, GND" }),
    );
    expect(kicadMap.querySelectorAll("[data-net-peer]")).toHaveLength(2);

    await user.click(screen.getByRole("option", { name: /Control Board/ }));
    await screen.findByRole("heading", { name: "Control Board" });
    await waitFor(() =>
      expect(mockApi.projectVisualArtifact).toHaveBeenCalledWith(
        "altium-project",
        "altium-top",
      ),
    );
    expect(
      document.querySelector('[data-dev-id="projects.native-board-render"]'),
    ).toBeInTheDocument();
    const altiumMap = screen.getByRole("region", { name: "PCB view" });
    await user.click(within(altiumMap).getByRole("button", { name: /R1,/ }));
    await user.click(
      within(altiumMap).getByRole("button", { name: "R1, Pin 1, GND" }),
    );
    expect(altiumMap.querySelectorAll("[data-net-peer]")).toHaveLength(2);
  });

  it("keeps selected-file detail compact without repeating an identical path", async () => {
    const projectWorkspace = workspace("kicad");
    mockApi.projectWorkspace.mockResolvedValue({
      ...projectWorkspace,
      documents: projectWorkspace.documents.map((document) =>
        document.kind === "pcb"
          ? { ...document, label: document.path }
          : document,
      ),
    });
    renderPage();

    await screen.findByRole("heading", { name: "Power Board" });
    const documents = screen.getByRole("region", { name: "Project documents" });
    expect(within(documents).getAllByText("Power.kicad_pcb")).toHaveLength(1);

    const inspector = screen.getByRole("complementary", { name: "Project selection" });
    expect(within(inspector).getByRole("heading", { name: "Power.kicad_pcb" }))
      .toBeInTheDocument();
    expect(within(inspector).getByText("Claim Required")).toBeInTheDocument();
    expect(inspector.querySelector("dl")?.className).toContain("border-y");
  });

  it("opens the selected native document through the same action for both EDAs", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("heading", { name: "Power Board" });
    await user.click(screen.getByRole("button", { name: "Open In KiCad" }));
    expect(mockApi.openProjectDocument).toHaveBeenCalledWith(
      "kicad-project",
      "kicad-board",
    );

    await user.click(screen.getByRole("option", { name: /Control Board/ }));
    await screen.findByRole("heading", { name: "Control Board" });
    await user.click(
      screen.getByRole("button", { name: "Open In Altium Designer" }),
    );
    expect(mockApi.openProjectDocument).toHaveBeenLastCalledWith(
      "altium-project",
      "altium-board",
    );
  });

  it("uses exact shared scene bounds for component hit geometry", async () => {
    renderPage();

    const map = await screen.findByRole("region", { name: "PCB view" });
    const r1 = await within(map).findByRole("button", { name: /R1,/ });
    const r2 = within(map).getByRole("button", { name: /R2,/ });

    expect(Number(r1.getAttribute("data-hit-width"))).toBeGreaterThan(10);
    expect(r1.getAttribute("data-hit-width")).toBe(r2.getAttribute("data-hit-width"));
    expect(r1).toHaveAttribute("data-reference", "R1");
  });

  it("keeps the selected component and inspector scoped to the active board", async () => {
    const user = userEvent.setup();
    const multiBoardWorkspace = workspace("kicad");
    multiBoardWorkspace.project.board_paths.push("Panel.kicad_pcb");
    multiBoardWorkspace.documents.push({
      document_id: "kicad-panel",
      path: "Panel.kicad_pcb",
      label: "Panel PCB",
      kind: "pcb",
      exists: true,
      lock_required: true,
    });

    const multiBoardGeometry = placementGeometry("kicad");
    multiBoardGeometry.boards.push("Panel.kicad_pcb");
    multiBoardGeometry.placements.push({
      reference: "R12",
      board: "Panel.kicad_pcb",
      x_mm: 8,
      y_mm: 6,
      rotation_deg: 0,
      side: "top",
      footprint: "R_0402_1005Metric",
    });
    multiBoardGeometry.summary = {
      boards: 2,
      placements: 3,
      top: 3,
      bottom: 0,
    };

    const multiBoardVisuals = projectVisuals("kicad");
    const mainBoard = multiBoardVisuals.documents[0]!;
    multiBoardVisuals.documents.push({
      ...mainBoard,
      path: "Panel.kicad_pcb",
      scene: {
        ...mainBoard.scene!,
        board: "Panel.kicad_pcb",
        components: [
          {
            ...mainBoard.scene!.components[0],
            reference: "R12",
            x_mm: 8,
            y_mm: 6,
          },
        ],
        summary: { components: 1, top: 1, bottom: 0 },
      },
      artifacts: mainBoard.artifacts.map((artifact) => ({
        ...artifact,
        id: `panel-${artifact.id}`,
        path: "Panel.kicad_pcb",
      })),
    });
    multiBoardVisuals.summary.documents = 2;

    mockApi.projectWorkspace.mockResolvedValue(multiBoardWorkspace);
    mockApi.projectPlacementGeometry.mockResolvedValue(multiBoardGeometry);
    mockApi.projectVisuals.mockResolvedValue(multiBoardVisuals);
    renderPage();

    const map = await screen.findByRole("region", { name: "PCB view" });
    await user.click(await within(map).findByRole("button", { name: /R1,/ }));
    const inspector = screen.getByRole("complementary", { name: "Project selection" });
    expect(within(inspector).getByText("Selected Placement")).toBeInTheDocument();

    await user.selectOptions(within(map).getByRole("combobox", { name: "Board" }), "Panel.kicad_pcb");
    expect(await within(inspector).findByRole("heading", { name: "Panel PCB" }))
      .toBeInTheDocument();
    expect(within(inspector).queryByText("Selected Placement")).not.toBeInTheDocument();

    await user.click(await within(map).findByRole("button", { name: /R12,/ }));
    expect(await within(inspector).findByRole("heading", { name: "R12" })).toBeInTheDocument();
    expect(within(inspector).getByText("Panel.kicad_pcb")).toBeInTheDocument();

    await user.click(within(map).getByRole("radio", { name: "Bottom · 0" }));
    expect(await within(inspector).findByRole("heading", { name: "Panel PCB" }))
      .toBeInTheDocument();
    expect(within(inspector).queryByText("Selected Placement")).not.toBeInTheDocument();
  });

  it("makes project switching and board inspection keyboard-friendly", async () => {
    const user = userEvent.setup();
    renderPage();

    const power = await screen.findByRole("option", { name: /Power Board/ });
    power.focus();
    await user.keyboard("{ArrowDown}");
    expect(await screen.findByRole("heading", { name: "Control Board" })).toBeInTheDocument();

    const map = screen.getByRole("region", { name: "PCB view" });
    expect(
      within(map).getByText("Select a footprint to inspect it"),
    ).toBeInTheDocument();
    expect(within(map).getByRole("button", { name: "Fit Board" })).toHaveTextContent("100%");
    const boardApplication = within(map).getByRole("application", { name: /PCB view/ });
    boardApplication.focus();
    await user.keyboard("+");
    expect(within(map).getByRole("button", { name: "Fit Board" })).toHaveTextContent("125%");
    await user.keyboard("0");
    expect(within(map).getByRole("button", { name: "Fit Board" })).toHaveTextContent("100%");

    const placement = within(map).getByRole("button", { name: /R1,/ });
    placement.focus();
    await user.keyboard("{Enter}");
    const inspector = screen.getByRole("complementary", { name: "Project selection" });
    expect(await within(inspector).findByRole("heading", { name: "R1" })).toBeInTheDocument();
    expect(
      within(map).getByText("R1 · select a pad to trace its net", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    expect(map.querySelector('[data-active-locator="R1"]')).toBeInTheDocument();
    const pin = within(map).getByRole("button", { name: "R1, Pin 1, GND" });
    pin.focus();
    await user.keyboard(" ");
    expect(
      within(map).getByText("Pin 1 · GND · 2 pads · 1 via · 1 track · Top", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    expect(map.querySelectorAll("[data-net-peer]")).toHaveLength(2);
    expect(map.querySelector('[data-net-peer="R2:2"]')).toBeInTheDocument();
    expect(map.querySelectorAll("[data-net-track]")).toHaveLength(1);
    const selectedTrack = map.querySelector("[data-net-track]");
    const selectedFootprint = map.querySelector('[data-reference="R1"]');
    expect(Boolean(
      selectedTrack &&
        selectedFootprint &&
        (selectedTrack.compareDocumentPosition(selectedFootprint) &
          Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
    const via = within(map).getByRole("button", {
      name: "Via Via_1, GND, 0.30 mm drill",
    });
    via.focus();
    await user.keyboard("{Enter}");
    expect(
      within(map).getByText("Via_1 · GND · 0.30 mm drill", { selector: "span" }),
    ).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(
      within(map).getByText("Pin 1 · GND · 2 pads · 1 via · 1 track · Top", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      within(map).getByText("R1 · select a pad to trace its net", {
        selector: "span",
      }),
    ).toBeInTheDocument();

    await user.click(within(map).getByRole("button", { name: "Expand Board" }));
    expect(within(map).getByRole("button", { name: "Close Board View" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(within(map).getByRole("button", { name: "Expand Board" })).toBeInTheDocument();
  });

  it("keeps the PCB dominant at 1024px by collapsing the repeated file rail", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    const picker = document.querySelector('[data-dev-id="projects.picker"]');
    const overview = document.querySelector('[data-dev-id="projects.overview"]');

    expect(picker?.className).toContain("max-[1180px]:w-[224px]");
    expect(overview?.className).toContain(
      "grid-cols-[minmax(0,1fr)_228px]",
    );
    expect(overview?.className).toContain(
      "@[60rem]:grid-cols-[192px_minmax(420px,1fr)_236px]",
    );
    expect(
      screen.getByRole("region", { name: "Project documents" }).className,
    ).toContain("@[60rem]:flex");
    expect(screen.getByRole("combobox", { name: "Project File" })).toBeInTheDocument();
    expect(screen.getAllByText("Claim Needed")).toHaveLength(2);
    expect(screen.getByText("Claim Required")).toBeInTheDocument();
    const stage = document.querySelector('[data-dev-id="projects.placement-stage"]');
    const stageLayers = Array.from(
      stage?.querySelectorAll('[aria-hidden="true"]') ?? [],
    ).map((element) => element.getAttribute("class") ?? "");
    expect(stageLayers).toEqual(
      expect.arrayContaining([
        expect.stringContaining("left-1/2"),
        expect.stringContaining("top-1/2"),
      ]),
    );
    expect(stageLayers.some((classes) => classes.includes("background-size"))).toBe(false);
  });

  it("uses the Library-style selectable line and contextual inspector for BOM", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "BOM" }));
    expect(await screen.findByText("Selected Line")).toBeInTheDocument();
    const summary = screen.getByText("Lines").closest("div");
    expect(summary?.className).toContain("flex");
    expect(summary?.className).not.toContain("grid");
    expect(summary?.className).not.toContain("border");
    const inspector = screen.getByRole("complementary", { name: "BOM line details" });
    expect(within(inspector).getByText("RC0402FR-0710KL")).toBeInTheDocument();
    expect(within(inspector).getByText("Linked")).toBeInTheDocument();
    expect(inspector.parentElement?.className).toContain(
      "grid-cols-[minmax(0,1fr)_228px]",
    );
    expect(inspector.parentElement?.className).toContain(
      "@[60rem]:grid-cols-[220px_minmax(420px,1fr)_250px]",
    );
    expect(
      within(inspector).getByText("References").closest("dl")?.className,
    ).toContain("border-y");
    const compactLineSelector = screen.getByRole("combobox", { name: "BOM line" });
    expect(screen.getByRole("combobox", { name: "BOM status" })).toBeInTheDocument();
    expect(
      within(compactLineSelector).getByRole("option", {
        name: "2 × RC0402FR-0710KL · Linked",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /RC0402FR-0710KL/ })).toBeInTheDocument();
    const map = screen.getByRole("region", { name: "PCB view" });
    const r1 = within(map).getByRole("button", { name: /R1/ });
    expect(r1).toBeInTheDocument();
    expect(within(map).getByRole("button", { name: /R2/ })).toBeInTheDocument();
    expect(
      within(map).getByText("2 placements highlighted · select one to inspect", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    await user.click(r1);
    const pin = within(map).getByRole("button", { name: "R1, Pin 1, GND" });
    pin.focus();
    await user.keyboard("{Enter}");
    expect(
      within(map).getByText("Pin 1 · GND · 2 pads · 1 via · 1 track · Top", {
        selector: "span",
      }),
    ).toBeInTheDocument();
    expect(map.querySelectorAll("[data-net-peer]")).toHaveLength(2);
    expect(map.querySelectorAll("[data-net-via]")).toHaveLength(1);
    expect(map.querySelectorAll("[data-net-track]")).toHaveLength(1);
  });

  it("keeps the visual BOM open while provenance is unavailable", async () => {
    const user = userEvent.setup();
    mockApi.liveProjectBom.mockResolvedValue({
      ...BOM,
      evidence: undefined,
    } as unknown as ProjectBom);
    mockApi.projectAssignments.mockResolvedValue({
      project: "Power Board",
      eda: "kicad",
      under_git: true,
      binding: undefined,
      components: 2,
      unassigned: 0,
      bound: [],
      groups: [],
    } as unknown as Awaited<ReturnType<typeof api.projectAssignments>>);
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "BOM" }));

    expect(await screen.findByText("Default · KiCad · 2 placements")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "PCB view" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "BOM line details" }))
      .toBeInTheDocument();
  });

  it("uses the placement map to select and record physical build progress", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "Build" }));
    const map = await screen.findByRole("region", { name: "PCB view" });
    const placementSelector = screen.getByRole("combobox", { name: "Placement" });
    expect(
      within(placementSelector).getByRole("option", {
        name: "R2 · Pending · RC0402FR-0710KL",
      }),
    ).toBeInTheDocument();
    await user.click(within(map).getByRole("button", { name: /R2/ }));
    const buildInspector = screen.getByRole("complementary", {
      name: "Selected placement",
    });
    expect(screen.getByRole("heading", { name: "R2" })).toBeInTheDocument();
    expect(within(buildInspector).getByText("1")).toBeInTheDocument();
    expect(buildInspector.parentElement?.className).toContain(
      "grid-cols-[minmax(0,1fr)_228px]",
    );
    expect(within(buildInspector).getByText("Board").closest("dl")?.className)
      .toContain("border-y");
    await user.click(screen.getByRole("button", { name: "Mark Placed" }));

    expect(mockApi.recordAssemblyEvent).toHaveBeenCalledWith(
      "kicad-project",
      "assembly-1",
      {
        placement_id: "placement-2",
        state: "done",
        scanned_mpn: "",
        note: "",
      },
    );
  });

  it("reconstructs guided Build progress from saved placements", async () => {
    const user = userEvent.setup();
    mockApi.activeAssembly.mockResolvedValue({
      ...ASSEMBLY,
      progress: undefined,
    } as unknown as AssemblyRun);
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "Build" }));

    expect(await screen.findByText("0/2")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "PCB view" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "R1" })).toBeInTheDocument();
  });

  it("connects a local repository and enters the shared Activity workflow", async () => {
    const user = userEvent.setup();
    mockApi.projectCollaboration.mockResolvedValue({
      ...COLLABORATION,
      repository: {
        ...COLLABORATION.repository!,
        remote: "",
        has_remote: false,
        has_upstream: false,
      },
    });
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "Activity" }));

    expect(await screen.findByText("Connect This Repository")).toBeInTheDocument();
    expect(screen.getByText("Local Only")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Add the Git repository shared by both engineers. Stockroom uses it for protected work sessions and review.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("No Reviews Yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Select a review.")).not.toBeInTheDocument();
    expect(mockApi.projectReviews).not.toHaveBeenCalled();

    await user.type(
      screen.getByLabelText("Repository URL"),
      "git@github.com:team/power-board.git",
    );
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(mockApi.connectProjectRemote).toHaveBeenCalledWith(
      "kicad-project",
      "git@github.com:team/power-board.git",
    );
    expect(
      await screen.findByRole("button", { name: "Start Work" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No shared work yet")).toBeInTheDocument();
    await waitFor(() => expect(mockApi.projectReviews).toHaveBeenCalled());

    await user.click(screen.getByRole("option", { name: /Control Board/ }));
    await screen.findByRole("heading", { name: "Control Board" });
    await user.click(screen.getByRole("tab", { name: "Activity" }));
    const altiumUrl = await screen.findByLabelText("Repository URL");
    await user.type(altiumUrl, "https://github.com/team/control-board.git");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(mockApi.connectProjectRemote).toHaveBeenLastCalledWith(
      "altium-project",
      "https://github.com/team/control-board.git",
    );
  });

  it("presents a shared review as one evidence sheet instead of dashboard cards", async () => {
    const user = userEvent.setup();
    const candidate = {
      branch: "work/alex/power-board",
      commit: "abcdef0123456789",
      base_branch: "main",
      base_commit: "0123456789abcdef",
      fork_commit: "0123456789abcdef",
      changed_paths: ["Power.kicad_sch", "Power.kicad_pcb"],
      commit_count: 2,
      ready: true,
      blocked_reason: "",
      events: [],
    };
    mockApi.projectReviews.mockResolvedValue({
      base_branch: "main",
      candidates: [candidate],
    });
    mockApi.projectReviewEvidence.mockResolvedValue({
      schema_version: 1,
      project_id: "kicad-project",
      project_name: "Power Board",
      eda: "kicad",
      branch: candidate.branch,
      commit: candidate.commit,
      base_branch: candidate.base_branch,
      base_commit: candidate.base_commit,
      source_digest: "source-digest",
      documents: [
        { path: "Power.kicad_sch", kind: "schematic", bytes: 1200, sha256: "a" },
        { path: "Power.kicad_pcb", kind: "pcb", bytes: 2400, sha256: "b" },
      ],
      bom: {
        variant: "Default",
        line_count: 2,
        component_count: 3,
        digest: "bom-digest",
        lines: [
          {
            refs: ["R1", "R2"],
            qty: 2,
            value: "10k",
            mpn: "RC0402FR-0710KL",
            manufacturer: "Yageo",
            footprint: "R_0402_1005Metric",
            package: "0402",
            description: "Resistor",
            datasheet: "",
            basic: false,
            identity_ready: true,
          },
          {
            refs: ["C1"],
            qty: 1,
            value: "100n",
            mpn: "",
            manufacturer: "",
            footprint: "C_0402_1005Metric",
            package: "0402",
            description: "Capacitor",
            datasheet: "",
            basic: false,
            identity_ready: false,
          },
        ],
      },
      semantic_audit: {
        components: 3,
        sheets: 1,
        counts: {
          by_severity: { error: 0, warning: 1, info: 0 },
          by_kind: { missing_identity: 1 },
        },
        findings: [],
        digest: "audit-digest",
      },
      blockers: [],
      warnings: [],
      reviewable: true,
      native_validation: {
        status: "passed",
        detail: "KiCad checks passed.",
      },
      visual_diff: {
        status: "passed",
        detail: "Board render changed.",
      },
      digest: "review-digest",
    });
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "Activity" }));

    const review = await screen.findByRole("complementary", {
      name: "Review evidence",
    });
    expect(within(review).getByRole("heading", { name: candidate.branch }))
      .toBeInTheDocument();
    expect(within(review).getByText("BOM Linked").closest("dl")?.className)
      .toContain("border-y");
    expect(within(review).getByText("1/2")).toHaveClass("text-warn");
    expect(within(review).getByText("Changed Files")).toBeInTheDocument();
    expect(within(review).getByText("Power.kicad_pcb")).toBeInTheDocument();
    expect(within(review).getByText("Review Checks")).toBeInTheDocument();
    expect(within(review).getByLabelText("Reviewer Name")).toBeInTheDocument();
    expect(within(review).getByLabelText("Review Note")).toBeInTheDocument();
    expect(within(review).getByText("Decision")).toBeInTheDocument();
  });

  it("returns an invalid remote to the repository URL field with clear guidance", async () => {
    const user = userEvent.setup();
    mockApi.projectCollaboration.mockResolvedValue({
      ...COLLABORATION,
      repository: {
        ...COLLABORATION.repository!,
        remote: "",
        has_remote: false,
        has_upstream: false,
      },
    });
    mockApi.connectProjectRemote.mockRejectedValueOnce(
      new Error("use a secure HTTPS or SSH repository URL"),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });
    await user.click(screen.getByRole("tab", { name: "Activity" }));

    const input = await screen.findByLabelText("Repository URL");
    await user.type(input, "ftp://example.com/power-board.git");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(
      await screen.findAllByText("use a secure HTTPS or SSH repository URL"),
    ).not.toHaveLength(0);
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("turns native placement blockers into an actionable shared state", async () => {
    mockApi.projectPlacementGeometry.mockResolvedValue({
      ...placementGeometry("kicad"),
      status: "blocked",
      boards: [],
      placements: [],
      summary: { boards: 0, placements: 0, top: 0, bottom: 0 },
      detail: "The editor reported No License.",
    });
    mockApi.projectVisuals.mockResolvedValue({
      ...projectVisuals("altium"),
      status: "blocked",
      documents: [],
      summary: { documents: 0, artifacts: 0, blocked: 1 },
      detail: "The editor reported No License.",
    });
    renderPage();

    expect(
      await screen.findByText("A valid editor license is required to read placement data."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });

  it("keeps a native PCB visible when only the placement overlay is blocked", async () => {
    mockApi.projectPlacementGeometry.mockResolvedValue({
      ...placementGeometry("kicad"),
      status: "blocked",
      boards: [],
      placements: [],
      summary: { boards: 0, placements: 0, top: 0, bottom: 0 },
      detail: "Placement export is unavailable.",
    });
    renderPage();

    await waitFor(() =>
      expect(
        document.querySelector('[data-dev-id="projects.native-board-render"]'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Native PCB")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Placement data is not available for this project."),
    ).not.toBeInTheDocument();
  });

  it("retries a blocked native PCB render without changing the placement workflow", async () => {
    mockApi.projectVisuals
      .mockResolvedValueOnce({
        ...projectVisuals("kicad"),
        status: "blocked",
        documents: [],
        summary: { documents: 0, artifacts: 0, blocked: 1 },
        detail: "Native rendering is temporarily unavailable.",
      })
      .mockResolvedValueOnce(projectVisuals("kicad"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Render PCB" }));

    await waitFor(() =>
      expect(mockApi.projectVisuals).toHaveBeenLastCalledWith(
        "kicad-project",
        true,
      ),
    );
    await waitFor(() =>
      expect(
        document.querySelector('[data-dev-id="projects.native-board-render"]'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Native PCB")).not.toBeInTheDocument();
  });

  it("gates physical builds before the backend has to reject them", async () => {
    const user = userEvent.setup();
    mockApi.activeAssembly.mockResolvedValue(null);
    mockApi.projectCollaboration.mockResolvedValue({
      repository: null,
      session: null,
      recovery: null,
    });
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("tab", { name: "Build" }));

    expect(await screen.findByText("Git Required")).toBeInTheDocument();
    expect(screen.getByText(/before starting a physical build/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start Build" })).not.toBeInTheDocument();
  });

  it("keeps BOM linking available when the native project stores links externally", async () => {
    const user = userEvent.setup();
    mockApi.liveProjectBom.mockResolvedValue({
      ...BOM,
      lines: [{ ...BOM.lines[0], in_library: false, library_part_id: "" }],
    });
    mockApi.projectAssignments.mockResolvedValue({
      project: "Control Board",
      eda: "altium",
      under_git: true,
      binding: {
        field: "StockroomPartId",
        writable: false,
        reason: "A .SchDoc is an OLE2 binary that Stockroom reads but never writes.",
      },
      components: 2,
      unassigned: 2,
      bound: [],
      groups: [
        {
          key: "10k|R_0402_1005Metric",
          lib_id: "",
          value: "10k",
          footprint: "R_0402_1005Metric",
          refs: ["R1", "R2"],
          count: 2,
          sheets: ["Main Schematic"],
          candidates: [
            {
              part_id: "resistor-10k",
              display_name: "10k 1% Resistor",
              mpn: "RC0402FR-0710KL",
              description: "Resistor",
              confidence: "value+footprint",
              distinguish: ["0402"],
            },
          ],
        },
      ],
    });
    renderPage();
    await screen.findByRole("heading", { name: "Power Board" });

    await user.click(screen.getByRole("option", { name: /Control Board/ }));
    await screen.findByRole("heading", { name: "Control Board" });
    await user.click(screen.getByRole("tab", { name: "BOM" }));

    expect(await screen.findByText("Component links are saved with this project."))
      .toBeInTheDocument();
    expect(screen.queryByText(/OLE2 binary/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /10k 1% Resistor/ }));
    expect(mockApi.assignProjectGroup).toHaveBeenCalledWith(
      "altium-project",
      ["R1", "R2"],
      "resistor-10k",
    );
  });
});

function toolNames() {
  return screen.getAllByRole("tab").map((tab) => tab.textContent);
}
