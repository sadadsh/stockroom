/**
 * The 3D model preview for a committed part (M6d). Fetches the GLB (converted from the
 * part's STEP/WRL by the backend) and hands it to the shared Glb3DView canvas. All the
 * mounting + honest-degradation logic lives in Glb3DView so a stock-lib_id preview (the
 * Add-A-Part flow) renders through the exact same viewer.
 */
import { usePreviewGlb } from "../api/queries";
import { Glb3DView } from "./Glb3DView";

export function ModelViewer({ partId }: { partId: string }) {
  const query = usePreviewGlb(partId, true);
  return (
    <Glb3DView
      data={query.data as ArrayBuffer | undefined}
      isLoading={query.isLoading}
      isError={query.isError}
      error={query.error}
    />
  );
}
