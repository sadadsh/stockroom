import { api } from "../api/client";
import type { CaptureAttachmentProposal } from "../api/types";
import type { CaptureEda, CaptureState } from "./captureRequirements";
import { pickHostFiles } from "./hostFilePicker";

interface RecoveryDependencies {
  pick: typeof pickHostFiles;
  attach: typeof api.attachSelectedCaptureFiles;
  propose: typeof api.proposePartFiles;
}

export interface CaptureRecoveryResult {
  selected: number;
  accepted: number;
  outcome: "canceled" | "queued" | "proposed";
  proposal?: CaptureAttachmentProposal;
}

const DEFAULT_DEPENDENCIES: RecoveryDependencies = {
  pick: pickHostFiles,
  attach: (input) => api.attachSelectedCaptureFiles(input),
  propose: (input) => api.proposePartFiles(input),
};

export async function recoverCaptureFiles(
  componentId: string,
  active: CaptureState,
  dependencies: RecoveryDependencies = DEFAULT_DEPENDENCIES,
  edas: readonly CaptureEda[] = ["kicad"],
): Promise<CaptureRecoveryResult> {
  const paths = await dependencies.pick("cad-recovery");
  if (paths.length === 0) return { selected: 0, accepted: 0, outcome: "canceled" };

  if (
    active.partId === componentId &&
    active.workflowItemId &&
    active.vendor &&
    active.url &&
    active.routeToken
  ) {
    const result = await dependencies.attach({
      partId: componentId,
      workflowItemId: active.workflowItemId,
      paths,
      vendor: active.vendor,
      detailUrl: active.url,
      routeToken: active.routeToken,
    });
    return { selected: paths.length, accepted: result.queued_files, outcome: "queued" };
  }

  const proposal = await dependencies.propose({ partId: componentId, paths, edas: [...edas] });
  return {
    selected: paths.length,
    accepted: proposal.attachments.length,
    outcome: "proposed",
    proposal,
  };
}
