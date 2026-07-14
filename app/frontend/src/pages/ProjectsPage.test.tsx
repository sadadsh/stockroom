import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import type {
  AuditResult,
  ChecksResult,
  ProjectDetail,
  ProjectSummary,
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
      openJobStream: vi.fn(),
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

beforeEach(() => {
  mockApi.listProjects.mockResolvedValue([NETDECK, BENCH]);
  mockApi.getProject.mockResolvedValue(NETDECK_DETAIL);
  mockApi.projectAudit.mockResolvedValue(AUDIT);
  mockApi.registerProject.mockResolvedValue(NETDECK_DETAIL);
  mockApi.deleteProject.mockResolvedValue(undefined);
  mockApi.getChecks.mockResolvedValue(NOT_RUN);
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
});
