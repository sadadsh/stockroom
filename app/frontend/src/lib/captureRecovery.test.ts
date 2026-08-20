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
    const propose = vi.fn();
    const result = await recoverCaptureFiles("part-1", state(), {
      pick: vi.fn().mockResolvedValue(["one.zip", "two.step"]),
      attach,
      propose,
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
    expect(propose).not.toHaveBeenCalled();
  });

  it("proposes ordinary component files without attaching when no provider task is active", async () => {
    const proposal = {
      proposal_token: "manual-1",
      part_id: "part-1",
      provider: "manual",
      primary_tool: "altium" as const,
      attachments: [{ role: "3D Model", file_name: "body.step", target: "Shared 3D Model" }],
      inactive_evidence: [],
    };
    const propose = vi.fn().mockResolvedValue(proposal);
    const result = await recoverCaptureFiles("part-1", state({ workflowItemId: null }), {
      pick: vi.fn().mockResolvedValue(["complete.zip"]),
      attach: vi.fn(),
      propose,
    }, ["altium"]);

    expect(result).toEqual({ selected: 1, accepted: 1, outcome: "proposed", proposal });
    expect(propose).toHaveBeenCalledWith({
      partId: "part-1",
      paths: ["complete.zip"],
      edas: ["altium"],
    });
  });
});
