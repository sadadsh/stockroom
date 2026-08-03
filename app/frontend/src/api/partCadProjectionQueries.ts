import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidate every client projection derived from one part's installed CAD files.
 *
 * Keeping these keys together prevents a successful capture or variant switch from updating the
 * readiness card while the symbol, footprint, or 3D viewer continues showing the previous bytes.
 */
export function invalidatePartCadProjection(queryClient: QueryClient, partId: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["part", partId] }),
    queryClient.invalidateQueries({ queryKey: ["cad-source", partId] }),
    queryClient.invalidateQueries({ queryKey: ["cad-variants", partId] }),
    queryClient.invalidateQueries({ queryKey: ["preview-svg", "symbol", partId] }),
    queryClient.invalidateQueries({ queryKey: ["preview-svg", "footprint", partId] }),
    queryClient.invalidateQueries({ queryKey: ["preview-glb", partId] }),
    queryClient.invalidateQueries({ queryKey: ["land-pattern", partId] }),
  ]);
}
