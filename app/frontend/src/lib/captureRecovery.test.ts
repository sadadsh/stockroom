import type { CaptureState } from "./captureRequirements";
import { recoverCaptureFiles } from "./captureRecovery";

function state(overrides: Partial<CaptureState> = {}): CaptureState {
  return {
    partId: "part-1",
    workflowItemId: "item-1",
    partName: "Part One",
    status: "receiving",
    message: null,
    url: "https://provider.example/part-1",
    routeToken: "route-1",
    vendor: "provider-one",
    needs: [],
    received: {},
    backgrounded: false,
    providerOutcomes: [],
    completionEvidence: null,
    completionEvidenceReported: false,
    ...overrides,
  };
}

describe("capture file recovery", () => {
  it("routes selected files into the active provider task", async () => {
    const attach = vi.fn().mockResolvedValue({ queued_files: 2 });
    const add = vi.fn();
    const result = await recoverCaptureFiles("part-1", state(), {
      pick: vi.fn().mockResolvedValue(["one.zip", "two.step"]),
      attach,
      add,
    });

    expect(result).toEqual({ selected: 2, accepted: 2, outcome: "queued" });
    expect(attach).toHaveBeenCalledWith({
      partId: "part-1",
      workflowItemId: "item-1",
      paths: ["one.zip", "two.step"],
      vendor: "provider-one",
      detailUrl: "https://provider.example/part-1",
      routeToken: "route-1",
    });
    expect(add).not.toHaveBeenCalled();
  });

  it("uses the ordinary component import when no provider task is active", async () => {
    const add = vi.fn().mockResolvedValue({ attached: ["symbol", "footprint", "model"] });
    const result = await recoverCaptureFiles("part-1", state({ workflowItemId: null }), {
      pick: vi.fn().mockResolvedValue(["complete.zip"]),
      attach: vi.fn(),
      add,
    });

    expect(result).toEqual({ selected: 1, accepted: 3, outcome: "attached" });
    expect(add).toHaveBeenCalledWith({ partId: "part-1", paths: ["complete.zip"] });
  });
});
