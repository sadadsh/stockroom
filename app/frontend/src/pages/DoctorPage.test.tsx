import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { DoctorScan, SystemInfo, WiringReport } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { DoctorPage } from "./DoctorPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      scanDoctor: vi.fn(),
      repairLibrary: vi.fn(),
      wireKicad: vi.fn(),
      openJobStream: vi.fn(),
      getSystemInfo: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const HEALTHY: DoctorScan = { fixable: [], manual: [], uncommitted: [], healthy: true };

const DEFECTIVE: DoctorScan = {
  fixable: [
    {
      kind: "drift",
      part_id: "lm358",
      detail: 'Manufacturer: symbol shows "WRONG", record has "TI"',
      before: "WRONG",
      after: "TI",
    },
    {
      kind: "model_path",
      part_id: "tps62130",
      detail: "footprint 3D-model link is not portable: C:\\x\\y.step",
      before: "C:\\x\\y.step",
      after: "${SR_LIB}/models/y.step",
    },
  ],
  manual: [
    {
      kind: "dangling_model",
      part_id: "cap1",
      detail: "3D model file is missing: models/cap.step",
      how_to_fix: "re-import the 3D model for this part",
    },
  ],
  uncommitted: [" M parts/lm358.json"],
  healthy: false,
};

const SYSTEM: SystemInfo = {
  active_profile: "Main",
  part_count: 3,
  kicad_config_dir: "/kicad",
  kicad_running: true,
  kicad_cli_available: true,
  kicad_cli_path: "/usr/bin/kicad-cli",
};

const WIRING: WiringReport = {
  sr_lib_value: "/lib",
  categories_registered: ["ICs", "Passives"],
  symbol_rows_added: 2,
  footprint_rows_added: 2,
  libs_created: [],
  kicad_running: true,
  restart_needed: true,
};

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
        <DoctorPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.getSystemInfo.mockResolvedValue(SYSTEM);
  mockApi.scanDoctor.mockResolvedValue(HEALTHY);
  mockApi.repairLibrary.mockResolvedValue({
    healed_drift: 1,
    fixed_paths: 1,
    committed_files: 1,
    commit: "abc123",
    manual: [],
  });
});

describe("DoctorPage", () => {
  it("shows an honest healthy state with no repair button when nothing is wrong", async () => {
    renderPage();
    expect(await screen.findByTestId("doctor-healthy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Repair Library" })).toBeNull();
  });

  it("lists fixable defects, uncommitted changes, and manual findings", async () => {
    mockApi.scanDoctor.mockResolvedValue(DEFECTIVE);
    renderPage();

    // fixable: drift + non-portable model path, each with its before/after diff
    expect(await screen.findByTestId("doctor-fixable-lm358")).toBeInTheDocument();
    expect(screen.getByTestId("doctor-fixable-tps62130")).toBeInTheDocument();
    expect(screen.getByText("TI")).toBeInTheDocument(); // the healed value
    // the uncommitted note
    expect(screen.getByTestId("doctor-uncommitted")).toHaveTextContent("1 uncommitted change");
    // manual finding: a missing file, shown with how to fix (never auto-resolved)
    const manual = screen.getByTestId("doctor-manual-cap1");
    expect(manual).toHaveTextContent("Missing 3D Model");
    expect(manual).toHaveTextContent("re-import the 3D model for this part");
    // and the repair action is offered
    expect(screen.getByRole("button", { name: "Repair Library" })).toBeInTheDocument();
  });

  it("runs the repair, reports what it did, and refreshes to the healed state", async () => {
    mockApi.scanDoctor.mockResolvedValueOnce(DEFECTIVE).mockResolvedValue(HEALTHY);
    renderPage();
    const user = userEvent.setup();

    const repairBtn = await screen.findByRole("button", { name: "Repair Library" });
    await user.click(repairBtn);

    await waitFor(() => expect(mockApi.repairLibrary).toHaveBeenCalledTimes(1));
    // the toast summarizes exactly what was done
    expect(await screen.findByText(/Repaired:/)).toBeInTheDocument();
    // the scan re-runs (invalidated) and the surface flips to healthy
    expect(await screen.findByTestId("doctor-healthy")).toBeInTheDocument();
  });

  it("wires KiCad through the job and reports when a restart is needed", async () => {
    mockApi.wireKicad.mockResolvedValue({ job_id: "job-1" });
    mockApi.openJobStream.mockResolvedValue(
      sseStream([
        `event: result\r\ndata: ${JSON.stringify({ result: WIRING })}`,
        `event: done\r\ndata: {}`,
      ]),
    );
    renderPage();
    const user = userEvent.setup();

    const wireBtn = await screen.findByRole("button", { name: "Wire KiCad" });
    await user.click(wireBtn);

    await waitFor(() => expect(mockApi.wireKicad).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Registered 2 categories/)).toBeInTheDocument();
    expect(screen.getByText(/Restart KiCad to load the updated libraries\./)).toBeInTheDocument();
  });
});
