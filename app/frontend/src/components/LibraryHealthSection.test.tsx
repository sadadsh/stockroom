import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { DoctorScan } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { LibraryHealthSection } from "./LibraryHealthSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { scanDoctor: vi.fn(), repairLibrary: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

const HEALTHY: DoctorScan = { fixable: [], manual: [], uncommitted: [], healthy: true };

const DEFECTIVE: DoctorScan = {
  fixable: [
    { kind: "drift", part_id: "lm358", detail: 'Manufacturer drift', before: "WRONG", after: "TI" },
    { kind: "model_path", part_id: "tps62130", detail: "non-portable model link", before: "C:\\x\\y.step", after: "${SR_LIB}/models/y.step" },
  ],
  manual: [
    { kind: "dangling_model", part_id: "cap1", detail: "3D model file is missing", how_to_fix: "re-import the 3D model for this part" },
  ],
  uncommitted: [" M parts/lm358.json"],
  healthy: false,
};

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LibraryHealthSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.scanDoctor.mockResolvedValue(HEALTHY);
  mockApi.repairLibrary.mockResolvedValue({
    healed_drift: 1,
    fixed_paths: 1,
    committed_files: 1,
    commit: "abc123",
    manual: [],
  });
});

describe("LibraryHealthSection", () => {
  it("shows an honest healthy state with no repair button when nothing is wrong", async () => {
    renderSection();
    expect(await screen.findByTestId("doctor-healthy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Repair Components" })).toBeNull();
  });

  it("lists fixable defects, uncommitted changes, and manual findings", async () => {
    mockApi.scanDoctor.mockResolvedValue(DEFECTIVE);
    renderSection();

    expect(await screen.findByTestId("doctor-fixable-lm358")).toBeInTheDocument();
    expect(screen.getByTestId("doctor-fixable-tps62130")).toBeInTheDocument();
    expect(screen.getByText("TI")).toBeInTheDocument();
    expect(screen.getByTestId("doctor-uncommitted")).toHaveTextContent("1 uncommitted change");
    const manual = screen.getByTestId("doctor-manual-cap1");
    expect(manual).toHaveTextContent("Missing 3D Model");
    expect(manual).toHaveTextContent("re-import the 3D model for this part");
    expect(screen.getByRole("button", { name: "Repair Components" })).toBeInTheDocument();
  });

  it("runs the repair, reports what it did, and refreshes to the healed state", async () => {
    mockApi.scanDoctor.mockResolvedValueOnce(DEFECTIVE).mockResolvedValue(HEALTHY);
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Repair Components" }));

    await waitFor(() => expect(mockApi.repairLibrary).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Repaired:/)).toBeInTheDocument();
    expect(await screen.findByTestId("doctor-healthy")).toBeInTheDocument();
  });
});
