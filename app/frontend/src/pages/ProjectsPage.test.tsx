import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import type {
  AuditResult,
  BomDiffResult,
  BomResult,
  ChecksResult,
  DesignResult,
  ProcurementResult,
  ProjectDetail,
  ProjectSummary,
  RevisionsResult,
  BoardSettings,
} from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listProjects: vi.fn(),
      registerProject: vi.fn(),
      getProject: vi.fn(),
      deleteProject: vi.fn(),
      projectAudit: vi.fn(),
      runChecks: vi.fn(),
      getChecks: vi.fn(),
      runBom: vi.fn(),
      getBom: vi.fn(),
      getProcurement: vi.fn(),
      getRevisions: vi.fn(),
      getBomDiff: vi.fn(),
      downloadBomExport: vi.fn(),
      openJobStream: vi.fn(),
      getDesign: vi.fn(),
      setNetClasses: vi.fn(),
      setDesignRules: vi.fn(),
      getBoardSettings: vi.fn(),
      setBoardSettings: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const NETDECK: ProjectSummary = {
  id: "netdeck",
  name: "Netdeck",
  root: "/home/sadad/git/netdeck",
  board_count: 1,
  sheet_count: 3,
  has_git: true,
  registered_at: "2026-07-13T12:00:00-04:00",
};

const BENCH: ProjectSummary = {
  id: "bench",
  name: "Bench",
  root: "/home/sadad/git/bench",
  board_count: 1,
  sheet_count: 1,
  has_git: false,
  registered_at: "2026-07-12T09:00:00-04:00",
};

const NETDECK_DETAIL: ProjectDetail = {
  id: "netdeck",
  name: "Netdeck",
  root: "/home/sadad/git/netdeck",
  pro_path: "/home/sadad/git/netdeck/netdeck.kicad_pro",
  board_paths: ["/home/sadad/git/netdeck/netdeck.kicad_pcb"],
  sheet_paths: ["/home/sadad/git/netdeck/netdeck.kicad_sch"],
  git_root: "/home/sadad/git/netdeck",
  audit_digest: null,
  registered_at: "2026-07-13T12:00:00-04:00",
};

const AUDIT: AuditResult = {
  project: "netdeck",
  components: 42,
  healthy: 40,
  counts: {
    by_severity: { error: 1, warning: 1, info: 0 },
    by_kind: { unannotated: 1, no_footprint: 1 },
  },
  findings: [
    {
      ref: "U1",
      severity: "error",
      kind: "unannotated",
      detail: "reference designator not annotated",
    },
    {
      ref: "R5",
      severity: "warning",
      kind: "no_footprint",
      detail: "no footprint assigned",
    },
  ],
  checked_footprints: 40,
  unresolved_footprints: 0,
  sheets: 3,
  markdown: "# Netdeck Health\n\nAll good.\n",
};

const NOT_RUN: ChecksResult = {
  project: "Netdeck",
  erc: null,
  drc: [],
  summary: null,
  ran_at: null,
};

const RAN: ChecksResult = {
  project: "Netdeck",
  erc: {
    ok: true,
    findings: [
      { severity: "warning", rule: "pin_not_connected", message: "Pin floating", where: "U1" },
    ],
    summary: {
      total: 1, errors: 0, warnings: 1,
      by_severity: { error: 0, warning: 1, exclusion: 0, info: 0 },
      by_rule: { pin_not_connected: 1 },
    },
    error: "",
    sheet: "netdeck.kicad_sch",
  },
  drc: [
    {
      ok: true,
      findings: [
        { severity: "error", rule: "clearance", message: "Tracks too close", where: "(10, 20)" },
      ],
      summary: {
        total: 1, errors: 1, warnings: 0,
        by_severity: { error: 1, warning: 0, exclusion: 0, info: 0 },
        by_rule: { clearance: 1 },
      },
      error: "",
      board: "netdeck.kicad_pcb",
    },
  ],
  summary: { ok: true, errors: 1, warnings: 1, total: 2, checked: 2 },
  ran_at: "2026-07-13T15:00:00Z",
};

const NOT_BUILT: BomResult = {
  project: "Netdeck",
  ran_at: null,
  boards: 1,
  priced: false,
  line_count: 0,
  component_count: 0,
  lines: [],
  summary: null,
  by_source: null,
  cost_at_qty: null,
};

const BUILT: BomResult = {
  project: "Netdeck",
  ran_at: "2026-07-13T16:00:00Z",
  boards: 1,
  priced: true,
  line_count: 2,
  component_count: 3,
  lines: [
    {
      refs: ["R1", "R2"],
      qty: 2,
      value: "10k",
      mpn: "",
      manufacturer: "",
      has_real_mpn: false,
      footprint: "Resistor_SMD:R_0402",
      datasheet: "",
      description: "",
      basic: true,
    },
    {
      refs: ["U1"],
      qty: 1,
      value: "TPS2121",
      mpn: "TPS2121RUXR",
      manufacturer: "TI",
      has_real_mpn: true,
      footprint: "",
      datasheet: "",
      description: "",
      basic: false,
      unit_price: 1.25,
      extended: 1.25,
      stock: 5000,
      source: "Mouser",
    },
  ],
  summary: {
    total_cost: 1.25,
    priced_lines: 1,
    unpriced_lines: 1,
    line_count: 2,
    currency: "USD",
    state: "partial",
    priced: true,
  },
  by_source: { sources: { Mouser: { total_cost: 1.25, lines: 1 } }, currency: "USD" },
  cost_at_qty: null,
};

// Build an SSE body from event frames, matching the fetch-based job stream the client
// consumes (event:/data: lines, blank-line separated).
function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const body = frames.map((f) => f + "\r\n\r\n").join("");
  const bytes = new TextEncoder().encode(body);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <ProjectsPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const PROC_NOT_BUILT: ProcurementResult = {
  project: "Netdeck",
  built: false,
  priced: false,
  boards: 1,
  lines: [],
  risks: { not_active: 0, no_stock: 0, insufficient_stock: 0, risky_mpns: [], any: false },
  lead: { max_weeks: null, critical_mpn: null, with_lead: 0, any: false },
  summary: "",
};

const PROC_BUILT: ProcurementResult = {
  project: "Netdeck",
  built: true,
  priced: true,
  boards: 1,
  lines: [
    {
      refs: ["U1"],
      qty: 1,
      value: "TPS2121",
      mpn: "TPS2121RUXR",
      manufacturer: "TI",
      has_real_mpn: true,
      footprint: "",
      datasheet: "",
      description: "",
      basic: false,
      unit_price: 1.25,
      extended: 1.25,
      stock: 0,
      lifecycle: "NRND",
      lead_time: "18 Weeks",
      source: "Mouser",
      stock_risk: { kind: "err", required: 1, available: 0, short: true },
      orderable: false,
    },
  ],
  risks: {
    not_active: 1,
    no_stock: 1,
    insufficient_stock: 0,
    risky_mpns: ["TPS2121RUXR"],
    any: true,
  },
  lead: { max_weeks: 18, critical_mpn: "TPS2121RUXR", with_lead: 1, any: true },
  summary: "BOM: 1 lines · 1 parts · $1.25/board · critical path 18 wk",
};

const DESIGN: DesignResult = {
  project: "Netdeck",
  under_git: true,
  has_pro: true,
  net_classes: [
    {
      name: "Default", clearance: 0.2, track_width: 0.2, via_diameter: 0.6, via_drill: 0.3,
      microvia_diameter: 0.3, microvia_drill: 0.1, diff_pair_width: 0.2, diff_pair_gap: 0.25,
      priority: 2147483647, wire_width: 6, bus_width: 12,
    },
    {
      name: "HS", clearance: 0.15, track_width: 0.1, via_diameter: 0.45, via_drill: 0.2,
      microvia_diameter: 0.3, microvia_drill: 0.1, diff_pair_width: 0.2, diff_pair_gap: 0.25,
      priority: 3, wire_width: 6, bus_width: 12,
    },
  ],
  netclass_patterns: [{ netclass: "HS", pattern: "*USB*" }],
  design_rules: {
    min_clearance: 0.2, min_track_width: 0.2, min_via_diameter: 0.5,
    use_height_for_length_calcs: true,
  },
  track_widths: [],
  via_dimensions: [],
  diff_pair_dimensions: [],
  fab_floors: {
    none: { label: "No fab floor", min_clearance: 0, min_track: 0, min_via: 0, min_drill: 0, min_annular: 0 },
    oshpark_2: { label: "OSH Park 2-layer", min_clearance: 0.1524, min_track: 0.1524, min_via: 0.508, min_drill: 0.254, min_annular: 0.127 },
  },
  validation: [{ netclass: "HS", issue: "track width 0.1 below fab min 0.1524" }],
};

const SETTINGS: BoardSettings = {
  project: "Netdeck",
  under_git: true,
  has_board: true,
  board_setup: {
    pad_to_mask_clearance: 0.0508,
    allow_soldermask_bridges_in_footprints: false,
    tenting_front: true,
    tenting_back: true,
    covering_front: false,
    covering_back: false,
    plugging_front: false,
    plugging_back: false,
    capping: false,
    filling: false,
    aux_axis_origin: [140, 115.5],
  },
  thickness: 1.6,
  fields: [
    { key: "pad_to_mask_clearance", kind: "length", label: "Solder Mask Clearance" },
    { key: "solder_mask_min_width", kind: "length", label: "Solder Mask Minimum Width" },
    { key: "pad_to_paste_clearance", kind: "length", label: "Solder Paste Clearance" },
    { key: "pad_to_paste_clearance_ratio", kind: "ratio", label: "Solder Paste Clearance Ratio" },
    {
      key: "allow_soldermask_bridges_in_footprints",
      kind: "bool",
      label: "Allow Soldermask Bridges In Footprints",
    },
    { key: "tenting_front", kind: "bool", label: "Tent Vias Front" },
    { key: "tenting_back", kind: "bool", label: "Tent Vias Back" },
    { key: "covering_front", kind: "bool", label: "Cover Vias Front" },
    { key: "covering_back", kind: "bool", label: "Cover Vias Back" },
    { key: "plugging_front", kind: "bool", label: "Plug Vias Front" },
    { key: "plugging_back", kind: "bool", label: "Plug Vias Back" },
    { key: "capping", kind: "bool", label: "Cap Vias" },
    { key: "filling", kind: "bool", label: "Fill Vias" },
    { key: "aux_axis_origin", kind: "coord", label: "Auxiliary Axis Origin" },
    { key: "grid_origin", kind: "coord", label: "Grid Origin" },
  ],
};

const REVS_NONE: RevisionsResult = { project: "Bench", under_git: false, revisions: [] };

const REVS_TWO: RevisionsResult = {
  project: "Netdeck",
  under_git: true,
  revisions: [
    { sha: "aaaaaaaa1111", short: "aaaaaaa", subject: "add power mux", author: "s", date: "d" },
    { sha: "bbbbbbbb2222", short: "bbbbbbb", subject: "initial", author: "s", date: "d" },
  ],
};

const DIFF: BomDiffResult = {
  project: "Netdeck",
  rev_a: "aaaaaaaa1111",
  rev_b: "current",
  added: [{ mpn: "STM32", value: "MCU", footprint: "", qty: 1 }],
  removed: [],
  changed: [{ mpn: "", value: "10k", footprint: "R_0402", from_qty: 2, to_qty: 3, delta: 1 }],
  unchanged: 1,
  cost: { delta: 3.5, added_cost: 3.5, changed_cost: 0, removed_unpriced: 0, priced: true, currency: "USD" },
  lead: {
    added_max_weeks: 20,
    added_critical_mpn: "STM32",
    build_max_weeks: 20,
    build_critical_mpn: "STM32",
    on_critical_path: true,
    removed_unassessed: 0,
    any: true,
  },
  csv: "Change,MPN,Value,From Qty,To Qty,Delta\nAdded,STM32,MCU,0,1,1\n",
  a_sheets_found: 1,
  b_sheets_found: null,
};

beforeEach(() => {
  mockApi.listProjects.mockResolvedValue([NETDECK, BENCH]);
  mockApi.getProject.mockResolvedValue(NETDECK_DETAIL);
  mockApi.projectAudit.mockResolvedValue(AUDIT);
  mockApi.registerProject.mockResolvedValue(NETDECK_DETAIL);
  mockApi.deleteProject.mockResolvedValue(undefined);
  mockApi.getChecks.mockResolvedValue(NOT_RUN);
  mockApi.getBom.mockResolvedValue(NOT_BUILT);
  mockApi.getProcurement.mockResolvedValue(PROC_NOT_BUILT);
  mockApi.getRevisions.mockResolvedValue(REVS_NONE);
  mockApi.getBomDiff.mockResolvedValue(DIFF);
  mockApi.downloadBomExport.mockResolvedValue(undefined);
  mockApi.getDesign.mockResolvedValue(DESIGN);
  mockApi.setNetClasses.mockResolvedValue({
    project: "Netdeck", committed: "cccccccc3333", net_classes: DESIGN.net_classes,
    validation: DESIGN.validation,
  });
  mockApi.setDesignRules.mockResolvedValue({
    project: "Netdeck", committed: "cccccccc3333", design_rules: DESIGN.design_rules,
  });
  mockApi.getBoardSettings.mockResolvedValue(SETTINGS);
  mockApi.setBoardSettings.mockResolvedValue({ ...SETTINGS, committed: "dddddddd4444" });
});

describe("ProjectsPage", () => {
  it("lists each project with its name and full folder path", async () => {
    renderPage();
    expect(await screen.findByTestId("project-row-netdeck")).toHaveTextContent("Netdeck");
    expect(screen.getByTestId("project-row-netdeck")).toHaveTextContent(
      "/home/sadad/git/netdeck",
    );
    expect(screen.getByTestId("project-row-bench")).toHaveTextContent("/home/sadad/git/bench");
  });

  it("shows an honest empty state with a register affordance when no projects are registered", async () => {
    mockApi.listProjects.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No projects are registered/i)).toBeInTheDocument();
    // the register input is still reachable
    expect(screen.getByPlaceholderText(/absolute path/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register Project" })).toBeInTheDocument();
  });

  it("registers a project from the entered path and toasts on success", async () => {
    mockApi.listProjects.mockResolvedValue([]);
    renderPage();
    const user = userEvent.setup();

    const input = await screen.findByPlaceholderText(/absolute path/i);
    await user.type(input, "/home/sadad/git/netdeck");
    await user.click(screen.getByRole("button", { name: "Register Project" }));

    await waitFor(() =>
      expect(mockApi.registerProject).toHaveBeenCalledWith("/home/sadad/git/netdeck"),
    );
    expect(await screen.findByText(/Registered Netdeck/)).toBeInTheDocument();
  });

  it("surfaces a 400 register error honestly as a toast", async () => {
    mockApi.listProjects.mockResolvedValue([]);
    mockApi.registerProject.mockRejectedValue(new ApiError(400, "no KiCad files found"));
    renderPage();
    const user = userEvent.setup();

    const input = await screen.findByPlaceholderText(/absolute path/i);
    await user.type(input, "/tmp/empty");
    await user.click(screen.getByRole("button", { name: "Register Project" }));

    expect(await screen.findByText("no KiCad files found")).toBeInTheDocument();
  });

  it("selecting a project shows its audit headline, findings, and download button", async () => {
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("project-row-netdeck"));

    // headline: healthy / total
    expect(await screen.findByText(/40 of 42/)).toBeInTheDocument();
    // findings table rows
    expect(screen.getByText("U1")).toBeInTheDocument();
    expect(screen.getByText("reference designator not annotated")).toBeInTheDocument();
    expect(screen.getByText("R5")).toBeInTheDocument();
    // the report download affordance
    expect(screen.getByRole("button", { name: "Download Report" })).toBeInTheDocument();
  });

  it("renders the findings-table headers without letterspaced uppercase (design contract)", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const head = await screen.findByTestId("findings-head");
    // no `uppercase` / `tracking-*` classes: Title Case labels, no letterspacing.
    expect(head.className).not.toMatch(/uppercase|tracking/);
    expect(within(head).getByText("Ref")).toBeInTheDocument();
  });

  it("filters the findings table by kind when a breakdown chip is clicked", async () => {
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByText("U1");

    // click the unannotated breakdown chip -> only U1 (unannotated) remains, R5 gone
    await user.click(screen.getByTestId("audit-chip-unannotated"));
    const table = screen.getByTestId("audit-findings");
    expect(within(table).getByText("U1")).toBeInTheDocument();
    expect(within(table).queryByText("R5")).toBeNull();

    // clicking it again clears the filter -> both are back
    await user.click(screen.getByTestId("audit-chip-unannotated"));
    expect(within(table).getByText("R5")).toBeInTheDocument();
  });

  it("downloads the audit markdown as a .md file", async () => {
    const createUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:mock/report");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("project-row-netdeck"));
    await user.click(await screen.findByRole("button", { name: "Download Report" }));

    expect(createUrl).toHaveBeenCalledTimes(1);
    const blob = createUrl.mock.calls[0][0] as Blob;
    expect(blob.type).toContain("markdown");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeUrl).toHaveBeenCalled();

    createUrl.mockRestore();
    revokeUrl.mockRestore();
    clickSpy.mockRestore();
  });

  it("deletes a project behind an in-window confirm and toasts", async () => {
    mockApi.listProjects
      .mockResolvedValueOnce([NETDECK, BENCH])
      .mockResolvedValue([BENCH]);
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("project-row-netdeck"));
    await user.click(await screen.findByRole("button", { name: "Remove Project" }));

    // the confirm dialog, not a native prompt
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(mockApi.deleteProject).toHaveBeenCalledWith("netdeck"));
    expect(await screen.findByText(/Removed Netdeck/)).toBeInTheDocument();
  });

  it("shows a connection error surface when the list fails to load", async () => {
    mockApi.listProjects.mockRejectedValue(new ApiError(0, "connection refused"));
    renderPage();
    expect(
      await screen.findByText(/Cannot reach the Stockroom server/i),
    ).toBeInTheDocument();
  });

  // ---- Rules Check (ERC + DRC, M7b) ----------------------------------------

  it("prompts to run checks and offers a Run Checks action on an unchecked project", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    expect(await screen.findByText(/Checks have not run yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Checks" })).toBeInTheDocument();
  });

  it("runs ERC and DRC and shows the combined verdict plus the findings", async () => {
    mockApi.runChecks.mockResolvedValue({ job_id: "checks-1" });
    mockApi.openJobStream.mockResolvedValue(
      sseStream([
        `event: result\r\ndata: ${JSON.stringify({ result: RAN })}`,
        `event: done\r\ndata: {}`,
      ]),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await user.click(await screen.findByRole("button", { name: "Run Checks" }));

    await waitFor(() => expect(mockApi.runChecks).toHaveBeenCalledWith("netdeck"));
    // combined verdict: one error + one warning
    const result = await screen.findByTestId("checks-result");
    expect(within(result).getByText("1 Error")).toBeInTheDocument();
    expect(within(result).getByText("1 Warning")).toBeInTheDocument();
    // ERC + DRC findings surfaced with their rules and messages
    expect(within(result).getByText("pin_not_connected")).toBeInTheDocument();
    expect(within(result).getByText("Pin floating")).toBeInTheDocument();
    expect(within(result).getByText("clearance")).toBeInTheDocument();
    expect(within(result).getByText("Tracks too close")).toBeInTheDocument();
  });

  it("surfaces an honest cli-absent error when checks cannot start", async () => {
    mockApi.runChecks.mockRejectedValue(new ApiError(502, "kicad-cli not found; install KiCad 10"));
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await user.click(await screen.findByRole("button", { name: "Run Checks" }));

    // inline error (never a fabricated pass) + the run prompt did not become a result
    expect(await screen.findAllByText(/kicad-cli not found/i)).not.toHaveLength(0);
    expect(screen.queryByTestId("checks-result")).toBeNull();
  });

  it("shows Nothing Checked (never a green Clean) when a run verified no files", async () => {
    // A .kicad_pro-only project: ERC/DRC ran on nothing (checked 0). That must read as
    // an honest "Nothing Checked", not a fabricated green pass.
    mockApi.getChecks.mockResolvedValue({
      project: "Netdeck",
      erc: null,
      drc: [],
      summary: { ok: false, errors: 0, warnings: 0, total: 0, checked: 0 },
      ran_at: "2026-07-13T15:00:00Z",
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const result = await screen.findByTestId("checks-result");
    expect(within(result).getByText("Nothing Checked")).toBeInTheDocument();
    expect(within(result).queryByText("Clean")).toBeNull();
  });

  it("renders a previously cached run on select without re-running", async () => {
    mockApi.getChecks.mockResolvedValue(RAN);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    // the cached run renders and the action reads Re-run, without any runChecks call
    expect(await screen.findByTestId("checks-result")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-run Checks" })).toBeInTheDocument();
    expect(mockApi.runChecks).not.toHaveBeenCalled();
  });

  it("prompts to build and offers a Build And Cost action on an unbuilt project", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    expect(await screen.findByText(/BOM has not been built yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build And Cost" })).toBeInTheDocument();
  });

  it("builds a grouped, priced BOM and shows the verdict, lines, and cost", async () => {
    mockApi.runBom.mockResolvedValue({ job_id: "bom-1" });
    mockApi.openJobStream.mockResolvedValue(
      sseStream([
        `event: result\r\ndata: ${JSON.stringify({ result: BUILT })}`,
        `event: done\r\ndata: {}`,
      ]),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await user.click(await screen.findByRole("button", { name: "Build And Cost" }));

    await waitFor(() => expect(mockApi.runBom).toHaveBeenCalledWith("netdeck"));
    const result = await screen.findByTestId("bom-result");
    // partial verdict: costed total plus an honest unpriced-line count (never hidden)
    expect(within(result).getByText("$1.25 Costed")).toBeInTheDocument();
    expect(within(result).getByText("1 Unpriced Line")).toBeInTheDocument();
    // the grouped lines: the merged passive (Basic) and the priced IC
    const lines = within(result).getByTestId("bom-lines");
    expect(within(lines).getByText("TPS2121RUXR")).toBeInTheDocument();
    expect(within(lines).getByText("Basic")).toBeInTheDocument();
    expect(within(lines).getByText("R1, R2")).toBeInTheDocument();
    expect(within(lines).getByText("$1.25")).toBeInTheDocument();
  });

  it("surfaces an honest error when the BOM build cannot start", async () => {
    mockApi.runBom.mockRejectedValue(new ApiError(500, "the build engine failed"));
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await user.click(await screen.findByRole("button", { name: "Build And Cost" }));

    expect(await screen.findAllByText(/the build engine failed/i)).not.toHaveLength(0);
    expect(screen.queryByTestId("bom-result")).toBeNull();
  });

  it("shows an honest Unpriced verdict when a build could source nothing", async () => {
    mockApi.getBom.mockResolvedValue({
      ...BUILT,
      lines: [BUILT.lines[1]].map((l) => ({ ...l, unit_price: undefined, extended: undefined, source: undefined })),
      line_count: 1,
      priced: true,
      summary: {
        total_cost: 0,
        priced_lines: 0,
        unpriced_lines: 1,
        line_count: 1,
        currency: "USD",
        state: "unpriced",
        priced: true,
      },
      by_source: { sources: {}, currency: "USD" },
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const result = await screen.findByTestId("bom-result");
    expect(within(result).getByText("Unpriced")).toBeInTheDocument();
    expect(within(result).queryByText(/Costed/)).toBeNull();
  });

  it("labels an MPN-less non-basic part No MPN, not Basic (honest basic field)", async () => {
    // A connector J1 has no MPN and is NOT a basic passive (basic:false); it must read
    // "No MPN", never a false "Basic" badge keyed off the missing MPN.
    mockApi.getBom.mockResolvedValue({
      ...BUILT,
      lines: [
        {
          refs: ["J1"], qty: 1, value: "Conn_01x04", mpn: "", manufacturer: "",
          has_real_mpn: false, footprint: "Connector:Conn_01x04", datasheet: "",
          description: "", basic: false,
        },
        BUILT.lines[0], // the real basic passive, still "Basic"
      ],
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const lines = within(await screen.findByTestId("bom-result")).getByTestId("bom-lines");
    expect(within(lines).getByText("No MPN")).toBeInTheDocument();
    expect(within(lines).getByText("Basic")).toBeInTheDocument(); // the true passive keeps it
  });

  it("renders a previously cached build on select without rebuilding", async () => {
    mockApi.getBom.mockResolvedValue(BUILT);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    expect(await screen.findByTestId("bom-result")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild BOM" })).toBeInTheDocument();
    expect(mockApi.runBom).not.toHaveBeenCalled();
  });

  // -- Procurement (M7d) --

  it("prompts to build the BOM before showing procurement", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const section = await screen.findByTestId("procurement-section");
    expect(section).toHaveTextContent(/Build the BOM to see sourcing risk/i);
    expect(screen.queryByTestId("procurement-lines")).not.toBeInTheDocument();
  });

  it("shows sourcing risk, lead and per-line orderability from a built BOM", async () => {
    mockApi.getProcurement.mockResolvedValue(PROC_BUILT);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    const rollup = await screen.findByTestId("procurement-rollup");
    expect(rollup).toHaveTextContent(/Not Active/i);
    expect(rollup).toHaveTextContent(/No Stock Line/i);
    expect(rollup).toHaveTextContent(/Critical path 18 wk/i);
    const lines = screen.getByTestId("procurement-lines");
    expect(within(lines).getByText("TPS2121RUXR")).toBeInTheDocument();
    expect(within(lines).getByText("NRND")).toBeInTheDocument();
    // 0 stock + a 1-part run -> not orderable
    expect(within(lines).getByText("No")).toBeInTheDocument();
  });

  it("exports the BOM through the authed download client", async () => {
    mockApi.getProcurement.mockResolvedValue(PROC_BUILT);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    await screen.findByTestId("export-bar");
    await user.click(screen.getByRole("button", { name: "JLCPCB BOM" }));
    // JLCPCB is a plain one-click export: no procurement knobs.
    expect(mockApi.downloadBomExport).toHaveBeenCalledWith("netdeck", "jlcpcb", undefined);
  });

  it("threads the procurement-sheet options into the export (percent to fraction)", async () => {
    mockApi.getProcurement.mockResolvedValue(PROC_BUILT);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    await screen.findByTestId("export-options");
    await user.clear(screen.getByTestId("opt-sparesPct"));
    await user.type(screen.getByTestId("opt-sparesPct"), "5");
    await user.clear(screen.getByTestId("opt-taxPct"));
    await user.type(screen.getByTestId("opt-taxPct"), "7");
    await user.click(screen.getByRole("button", { name: "Procurement Sheet" }));

    expect(mockApi.downloadBomExport).toHaveBeenCalledWith(
      "netdeck",
      "procurement",
      expect.objectContaining({ spares_pct: 5, tax_rate: 0.07, pcb_multiple: 1 }),
    );
  });

  it("toasts when an export fails", async () => {
    mockApi.getProcurement.mockResolvedValue(PROC_BUILT);
    mockApi.downloadBomExport.mockRejectedValue(new ApiError(400, "build the BOM before exporting it"));
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    await screen.findByTestId("export-bar");
    await user.click(screen.getByRole("button", { name: "BOM CSV" }));
    expect(await screen.findByText(/build the BOM before exporting it/i)).toBeInTheDocument();
  });

  // -- Revision diff (M7d) --

  it("shows an honest not-under-git state when the project has no git history", async () => {
    // The default getRevisions returns under_git false: the diff section must say so, not crash.
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const section = await screen.findByTestId("diff-section");
    expect(section).toHaveTextContent(/not under git/i);
  });

  it("diffs a chosen revision against the current build", async () => {
    mockApi.getRevisions.mockResolvedValue(REVS_TWO);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    await screen.findByTestId("diff-pickers");
    await user.selectOptions(screen.getByTestId("diff-rev-a"), "aaaaaaaa1111");
    expect(mockApi.getBomDiff).toHaveBeenCalledWith("netdeck", "aaaaaaaa1111", "");

    const result = await screen.findByTestId("diff-result");
    expect(result).toHaveTextContent(/1 Added/);
    expect(result).toHaveTextContent(/1 Changed/);
    expect(result).toHaveTextContent(/\$3\.50\/board/);
    const lines = screen.getByTestId("diff-lines");
    expect(within(lines).getByText("STM32")).toBeInTheDocument();
  });

  it("does not diff until a revision is chosen", async () => {
    mockApi.getRevisions.mockResolvedValue(REVS_TWO);
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    await screen.findByTestId("diff-pickers");
    expect(screen.getByText(/Choose a commit to compare/i)).toBeInTheDocument();
    expect(mockApi.getBomDiff).not.toHaveBeenCalled();
  });

  it("flags an unreadable revision instead of fabricating an everything-added diff", async () => {
    // a_sheets_found 0 = rev A predates the schematic; the diff would otherwise show every
    // current part as Added with a cost delta. It must show an honest caveat, not that diff.
    mockApi.getRevisions.mockResolvedValue(REVS_TWO);
    mockApi.getBomDiff.mockResolvedValue({ ...DIFF, a_sheets_found: 0 });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));

    await screen.findByTestId("diff-pickers");
    await user.selectOptions(screen.getByTestId("diff-rev-a"), "aaaaaaaa1111");
    expect(await screen.findByTestId("diff-unreadable")).toHaveTextContent(
      /no readable schematics/i,
    );
    // the fabricated diff table + cost badge must NOT render
    expect(screen.queryByTestId("diff-result")).not.toBeInTheDocument();
  });

  // -- Editor: design rules + net classes (M7e) --

  it("renders the project net classes and design rules", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const editor = await screen.findByTestId("editor-section");
    expect(within(editor).getByTestId("nc-row-Default")).toBeInTheDocument();
    expect(within(editor).getByTestId("nc-row-HS")).toBeInTheDocument();
    // a design-rule field renders with its current value
    expect((within(editor).getByTestId("dr-min_track_width") as HTMLInputElement).value).toBe("0.2");
  });

  it("saves an edited net-class track width to the right endpoint", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const input = screen.getByTestId("nc-Default-track_width");
    await user.clear(input);
    await user.type(input, "0.15");
    await user.click(screen.getByRole("button", { name: "Save Net Classes" }));
    expect(mockApi.setNetClasses).toHaveBeenCalledTimes(1);
    const [id, classes] = mockApi.setNetClasses.mock.calls[0];
    expect(id).toBe("netdeck");
    expect(classes).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "Default", track_width: 0.15 })]),
    );
  });

  it("adds a net class and includes it on save", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    await user.click(screen.getByRole("button", { name: "Add Net Class" }));
    await user.type(screen.getByTestId("nc-new-name"), "PWR");
    await user.click(screen.getByRole("button", { name: "Save Net Classes" }));
    const [, classes] = mockApi.setNetClasses.mock.calls[0];
    expect(classes).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "PWR" })]),
    );
  });

  it("deletes a net class on save", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    await user.click(within(screen.getByTestId("nc-row-HS")).getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Save Net Classes" }));
    const call = mockApi.setNetClasses.mock.calls[0];
    // deleted names are passed as the 3rd positional options arg
    expect(call[2]).toEqual(expect.objectContaining({ deleted: ["HS"] }));
    // the deleted class is not in the submitted set
    expect(call[1].some((c: { name: string }) => c.name === "HS")).toBe(false);
  });

  it("saves edited design rules to the right endpoint", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const input = screen.getByTestId("dr-min_track_width");
    await user.clear(input);
    await user.type(input, "0.13");
    await user.click(screen.getByRole("button", { name: "Save Design Rules" }));
    expect(mockApi.setDesignRules).toHaveBeenCalledTimes(1);
    const [id, rules] = mockApi.setDesignRules.mock.calls[0];
    expect(id).toBe("netdeck");
    expect(rules).toEqual(expect.objectContaining({ min_track_width: 0.13 }));
  });

  it("surfaces fab-floor validation as amber on the offending class", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const row = screen.getByTestId("nc-row-HS");
    expect(row).toHaveTextContent(/below fab min/i);
  });

  it("refetches the design against the chosen fab floor", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    await user.selectOptions(screen.getByTestId("fab-floor-select"), "oshpark_2");
    await waitFor(() =>
      expect(mockApi.getDesign).toHaveBeenCalledWith("netdeck", "oshpark_2"),
    );
  });

  it("marks the net-class section dirty on edit and disables Save until then", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const save = screen.getByRole("button", { name: "Save Net Classes" });
    expect(save).toBeDisabled(); // clean on load
    const input = screen.getByTestId("nc-Default-track_width");
    await user.clear(input);
    await user.type(input, "0.15");
    expect(save).toBeEnabled(); // dirty after an edit
  });

  it("shows an honest not-under-git state without editing controls", async () => {
    mockApi.getDesign.mockResolvedValue({ ...DESIGN, under_git: false });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    const editor = await screen.findByTestId("editor-section");
    expect(editor).toHaveTextContent(/not under git/i);
    expect(screen.queryByRole("button", { name: "Save Net Classes" })).not.toBeInTheDocument();
  });

  it("keeps unsaved net-class edits when the fab floor changes", async () => {
    // each design fetch returns a FRESH object (new references, same content), as the real
    // backend does per floor. Picking a floor to validate an edit must NOT reset the edit.
    mockApi.getDesign.mockImplementation(() =>
      Promise.resolve(JSON.parse(JSON.stringify(DESIGN))),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const input = screen.getByTestId("nc-Default-track_width");
    await user.clear(input);
    await user.type(input, "0.15");
    await user.selectOptions(screen.getByTestId("fab-floor-select"), "oshpark_2");
    await waitFor(() =>
      expect(mockApi.getDesign).toHaveBeenCalledWith("netdeck", "oshpark_2"),
    );
    expect(screen.getByTestId("nc-Default-track_width")).toHaveValue("0.15"); // edit survived
    expect(screen.getByRole("button", { name: "Save Net Classes" })).toBeEnabled();
  });

  it("does not send a re-added class in both classes and deleted", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    await user.click(within(screen.getByTestId("nc-row-HS")).getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Add Net Class" }));
    await user.type(screen.getByTestId("nc-new-name"), "HS");
    await user.click(screen.getByRole("button", { name: "Save Net Classes" }));
    const call = mockApi.setNetClasses.mock.calls[0]!;
    expect(call[1].some((c: { name: string }) => c.name === "HS")).toBe(true); // re-added
    expect(call[2]?.deleted).not.toContain("HS"); // and not also deleted (reconcile would drop it)
  });

  it("blocks the save and warns when a net-class dimension is not a number", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const input = screen.getByTestId("nc-Default-track_width");
    await user.clear(input);
    await user.type(input, "abc");
    await user.click(screen.getByRole("button", { name: "Save Net Classes" }));
    expect(mockApi.setNetClasses).not.toHaveBeenCalled(); // no NaN -> null written
    expect(await screen.findByText(/valid number/i)).toBeInTheDocument();
  });

  it("blocks the save and warns when a design-rule field is cleared", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("editor-section");
    const input = screen.getByTestId("dr-min_track_width");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Save Design Rules" }));
    expect(mockApi.setDesignRules).not.toHaveBeenCalled(); // no silent 0 written
    expect(await screen.findByText(/valid number/i)).toBeInTheDocument();
  });

  // --- M7f-A Board Setup editor ---

  it("shows the board setup with its current values", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    expect(screen.getByTestId("bs-pad_to_mask_clearance")).toHaveValue("0.0508");
    expect(screen.getByTestId("bs-thickness")).toHaveValue("1.6");
    expect(screen.getByTestId("bs-tenting_front")).toBeChecked(); // effective default ON
    expect(screen.getByTestId("bs-capping")).not.toBeChecked();
    expect(screen.getByTestId("bs-aux_axis_origin-x")).toHaveValue("140");
  });

  it("saves an edited board-setup clearance to the settings endpoint", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    const input = screen.getByTestId("bs-pad_to_mask_clearance");
    await user.clear(input);
    await user.type(input, "0.1");
    await user.click(screen.getByRole("button", { name: "Save Board Setup" }));
    await waitFor(() => expect(mockApi.setBoardSettings).toHaveBeenCalled());
    expect(mockApi.setBoardSettings).toHaveBeenCalledWith("netdeck", {
      board_setup: { pad_to_mask_clearance: 0.1 },
      thickness: undefined,
    });
  });

  it("saves the board thickness alone without re-writing untouched board setup", async () => {
    // the anti-flip guarantee: editing only thickness must NOT resend the via-protection
    // defaults (which would flip an absent-defaults-ON tenting to a written OFF).
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    const input = screen.getByTestId("bs-thickness");
    await user.clear(input);
    await user.type(input, "0.8");
    await user.click(screen.getByRole("button", { name: "Save Board Setup" }));
    await waitFor(() => expect(mockApi.setBoardSettings).toHaveBeenCalled());
    expect(mockApi.setBoardSettings).toHaveBeenCalledWith("netdeck", {
      board_setup: undefined,
      thickness: 0.8,
    });
  });

  it("toggles a via-protection checkbox and saves just that field", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    await user.click(screen.getByTestId("bs-tenting_front")); // ON -> OFF
    await user.click(screen.getByRole("button", { name: "Save Board Setup" }));
    await waitFor(() => expect(mockApi.setBoardSettings).toHaveBeenCalled());
    expect(mockApi.setBoardSettings).toHaveBeenCalledWith("netdeck", {
      board_setup: { tenting_front: false },
      thickness: undefined,
    });
  });

  it("marks the board setup dirty on edit and disables Save until then", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    const save = screen.getByRole("button", { name: "Save Board Setup" });
    expect(save).toBeDisabled();
    const input = screen.getByTestId("bs-thickness");
    await user.clear(input);
    await user.type(input, "0.8");
    expect(screen.getByRole("button", { name: "Save Board Setup" })).toBeEnabled();
  });

  it("blocks the save and warns on a non-numeric clearance", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    const input = screen.getByTestId("bs-pad_to_mask_clearance");
    await user.clear(input);
    await user.type(input, "wide");
    await user.click(screen.getByRole("button", { name: "Save Board Setup" }));
    expect(mockApi.setBoardSettings).not.toHaveBeenCalled();
    expect(await screen.findByText(/valid number/i)).toBeInTheDocument();
  });

  it("shows an honest no-board state", async () => {
    mockApi.getBoardSettings.mockResolvedValue({
      ...SETTINGS, has_board: false, board_setup: {}, thickness: null,
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    expect(await screen.findByTestId("board-setup-no-board")).toBeInTheDocument();
    expect(screen.queryByTestId("board-setup-form")).not.toBeInTheDocument();
  });

  it("shows an honest not-under-git state for the board setup", async () => {
    mockApi.getBoardSettings.mockResolvedValue({ ...SETTINGS, under_git: false });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    expect(await screen.findByTestId("board-setup-no-git")).toBeInTheDocument();
    expect(screen.queryByTestId("board-setup-form")).not.toBeInTheDocument();
  });

  it("does not mark dirty when a number is re-typed in an equal but different format", async () => {
    // "1.60" is numerically 1.6; a string-only diff would strand the form permanently Unsaved.
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    const input = screen.getByTestId("bs-thickness");
    await user.clear(input);
    await user.type(input, "1.60");
    expect(screen.getByRole("button", { name: "Save Board Setup" })).toBeDisabled();
  });

  it("does not strand the form dirty when a field is cleared", async () => {
    // a blanked length cannot be sent (KiCad has no delete-key), so it must count as no change
    // rather than leaving Save enabled on a body that would be rejected as "nothing to write".
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    await user.clear(screen.getByTestId("bs-pad_to_mask_clearance"));
    expect(screen.getByRole("button", { name: "Save Board Setup" })).toBeDisabled();
  });

  it("returns to a clean state after a successful save", async () => {
    // the post-save refetch reads back the committed value, which re-seeds the form to clean.
    mockApi.getBoardSettings
      .mockReset()
      .mockResolvedValueOnce(SETTINGS) // initial load: thickness 1.6
      .mockResolvedValue({ ...SETTINGS, thickness: 0.8 }); // refetch after save: 0.8
    mockApi.setBoardSettings.mockResolvedValue({
      ...SETTINGS, thickness: 0.8, committed: "dddddddd4444",
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("project-row-netdeck"));
    await screen.findByTestId("board-setup-form");
    const input = screen.getByTestId("bs-thickness");
    await user.clear(input);
    await user.type(input, "0.8");
    await user.click(screen.getByRole("button", { name: "Save Board Setup" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Board Setup" })).toBeDisabled(),
    );
    expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
  });
});
