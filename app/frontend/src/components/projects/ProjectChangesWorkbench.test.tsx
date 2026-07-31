import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../../api/client";
import type { ProjectCollaboration, ProjectWorkspace } from "../../api/types";
import { ToastProvider } from "../../lib/toast";
import { ProjectChangesWorkbench } from "./ProjectChangesWorkbench";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      projectCollaboration: vi.fn(),
      projectReviews: vi.fn(),
      projectReviewEvidence: vi.fn(),
      connectProjectRemote: vi.fn(),
      startWorkSession: vi.fn(),
      shareWorkSession: vi.fn(),
      resumeWorkSession: vi.fn(),
      finishWorkSession: vi.fn(),
      validateProjectReview: vi.fn(),
      approveProjectReview: vi.fn(),
      requestProjectChanges: vi.fn(),
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

const WORKSPACE = {
  project: {
    id: "kicad-project",
    name: "Power Board",
    root: "C:\\Projects\\Power",
    pro_path: "Power.kicad_pro",
    board_paths: ["Power.kicad_pcb"],
    sheet_paths: ["Power.kicad_sch"],
    eda: "kicad",
    git_root: "C:\\Projects\\Power",
  },
  eda_label: "KiCad",
  tools: ["design", "bom", "assemble", "changes", "releases"],
  parity: {
    schema: "stockroom-project-parity/1",
    edas: ["kicad", "altium"],
    strict: true,
    adapter_boundary: "native_io_only",
    tools: [],
  },
  runtime: {
    adapter_key: "kicad",
    available: true,
    status: "ready",
    version: "26",
    detail: "Native runtime ready.",
  },
  documents: [
    {
      document_id: "kicad-schematic",
      path: "Power.kicad_sch",
      label: "Main Schematic",
      kind: "schematic",
      exists: true,
      lock_required: true,
    },
    {
      document_id: "kicad-board",
      path: "Power.kicad_pcb",
      label: "Main PCB",
      kind: "pcb",
      exists: true,
      lock_required: true,
    },
  ],
} as unknown as ProjectWorkspace;

beforeEach(() => {
  mockApi.projectCollaboration.mockResolvedValue(COLLABORATION);
  mockApi.projectReviews.mockResolvedValue({
    base_branch: "main",
    candidates: [],
  });
});

function renderWorkbench() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ProjectChangesWorkbench projectId="kicad-project" workspace={WORKSPACE} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ProjectChangesWorkbench work session", () => {
  it("seeds every lock-required file, then lets the last one be unchecked", async () => {
    // A4: the seeding effect used `documents.length` as both its guard and its dependency,
    // so clearing the last checkbox re-fired it and re-checked everything. Zero selection
    // was unreachable, which also made the disabled Start Work state unreachable.
    const user = userEvent.setup();
    renderWorkbench();

    const schematic = await screen.findByRole("checkbox", { name: "Main Schematic" });
    const board = screen.getByRole("checkbox", { name: "Main PCB" });
    expect(schematic).toBeChecked();
    expect(board).toBeChecked();

    await user.click(schematic);
    expect(schematic).not.toBeChecked();
    expect(board).toBeChecked();

    await user.click(board);
    expect(schematic).not.toBeChecked();
    expect(board).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Start Work" })).toBeDisabled();

    // A re-check is still just a re-check: nothing re-seeds behind the operator.
    await user.click(board);
    expect(schematic).not.toBeChecked();
    expect(board).toBeChecked();
  });

  it("claims only the files still checked when work starts", async () => {
    const user = userEvent.setup();
    mockApi.startWorkSession.mockResolvedValue({
      ...COLLABORATION,
      session: {
        id: "session-1",
        owner: "Sadad",
        branch: "work/sadad/power-board",
        documents: ["Power.kicad_pcb"],
        started_at: "2026-07-29T00:00:00Z",
        shared_commit: "",
      },
    } as unknown as ProjectCollaboration);
    renderWorkbench();

    await user.click(await screen.findByRole("checkbox", { name: "Main Schematic" }));
    await user.type(screen.getByLabelText("Your name"), "Sadad");
    await user.click(screen.getByRole("button", { name: "Start Work" }));

    expect(mockApi.startWorkSession).toHaveBeenCalledWith("kicad-project", {
      owner: "Sadad",
      branch: "work/sadad/power-board",
      documents: ["Power.kicad_pcb"],
    });
  });

  it("counts the claimed files in the Project Files badge", async () => {
    const user = userEvent.setup();
    renderWorkbench();

    const heading = await screen.findByText("Project Files");
    const row = heading.closest("div")!;
    expect(within(row).getByText("2")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Main PCB" }));
    expect(within(row).getByText("1")).toBeInTheDocument();
  });
});
