/**
 * TanStack Query ownership for one selected part's immutable CAD variants.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cadVariantApi,
  type CadVariantDocument,
  type CadVariantPairActivation,
} from "./cadVariantClient";
import { invalidatePartCadProjection } from "./partCadProjectionQueries";

export const cadVariantQueryKey = (partId: string) =>
  ["cad-variants", partId] as const;

export function useCadVariantInventory(partId: string, enabled: boolean) {
  return useQuery({
    queryKey: cadVariantQueryKey(partId),
    queryFn: () => cadVariantApi.inventory(partId),
    enabled: enabled && !!partId,
  });
}

export function useActivateCadPair(partId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (activation: CadVariantPairActivation) =>
      cadVariantApi.activatePair(partId, activation),
    onSuccess: async (document: CadVariantDocument) => {
      queryClient.setQueryData(cadVariantQueryKey(partId), document);
      await Promise.all([
        invalidatePartCadProjection(queryClient, partId),
        queryClient.invalidateQueries({ queryKey: ["parts"] }),
      ]);
    },
    onError: async () => {
      await queryClient.invalidateQueries({
        queryKey: cadVariantQueryKey(partId),
      });
    },
  });
}
