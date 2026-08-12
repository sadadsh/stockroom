import { api } from "../api/client";
import type { CaptureState } from "./captureRequirements";
import { pickHostFiles } from "./hostFilePicker";

interface RecoveryDependencies {
  pick: typeof pickHostFiles;
  attach: typeof api.attachSelectedCaptureFiles;
  add: typeof api.addPartFiles;
}

export interface CaptureRecoveryResult {
  selected: number;
  accepted: number;
  outcome: "canceled" | "queued" | "attached";
}

const DEFAULT_DEPENDENCIES: RecoveryDependencies = {
  pick: pickHostFiles,
  attach: (input) => api.attachSelectedCaptureFiles(input),
  add: (input) => api.addPartFiles(input),
};

export async function recoverCaptureFiles(
  componentId: string,
  active: CaptureState,
  dependencies: RecoveryDependencies = DEFAULT_DEPENDENCIES,
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

  const result = await dependencies.add({ partId: componentId, paths });
  return { selected: paths.length, accepted: result.attached.length, outcome: "attached" };
}
