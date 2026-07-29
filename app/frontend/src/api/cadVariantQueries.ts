/**
 * TanStack Query ownership for one selected part's immutable CAD variants.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cadVariantApi,
  type CadVariantActivation,
  type CadVariantDocument,
} from "./cadVariantClient";

export const cadVariantQueryKey = (partId: string) =>
  ["cad-variants", partId] as const;

export function useCadVariantInventory(partId: string, enabled: boolean) {
  return useQuery({
    queryKey: cadVariantQueryKey(partId),
    queryFn: () => cadVariantApi.inventory(partId),
    enabled: enabled && !!partId,
  });
}

export function useActivateCadVariant(partId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (activation: CadVariantActivation) =>
      cadVariantApi.activate(partId, activation),
    onSuccess: async (document: CadVariantDocument) => {
      // The response advances the controlled selector immediately. Refetch both truths anyway:
      // inventory proves the active pointer and part detail proves the newly materialized assets
      // that RepresentationMatrix renders.
      queryClient.setQueryData(cadVariantQueryKey(partId), document);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: cadVariantQueryKey(partId) }),
        queryClient.invalidateQueries({ queryKey: ["part", partId] }),
        queryClient.invalidateQueries({ queryKey: ["parts"] }),
      ]);
    },
    onError: async () => {
      // A 409 means another writer advanced the pointer. Every failure refetches the inventory so
      // the controlled selector cannot keep offering a stale expectedActiveVariantId.
      await queryClient.invalidateQueries({
        queryKey: cadVariantQueryKey(partId),
      });
    },
  });
}
