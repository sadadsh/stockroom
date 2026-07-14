import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import type { AuditResult, ProjectDetail, ProjectSummary } from "../api/types";
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
});
