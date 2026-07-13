/**
 * TanStack Query hooks over the API client. Server state lives here so the page
 * stays declarative: change the search/category/completeOnly and the list
 * refetches; select a part and the detail loads. keepPreviousData keeps the list
 * from flickering to empty while a new search is in flight.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, type ListPartsArgs } from "./client";

export function usePartsQuery(args: ListPartsArgs) {
  return useQuery({
    queryKey: ["parts", args.q ?? "", args.category ?? "", !!args.completeOnly],
    queryFn: () => api.listParts(args),
    placeholderData: keepPreviousData,
  });
}

export function useFacetsQuery() {
  return useQuery({
    queryKey: ["facets"],
    queryFn: () => api.facets(),
  });
}

export function usePartDetailQuery(id: string | null) {
  return useQuery({
    queryKey: ["part", id],
    queryFn: () => api.partDetail(id as string),
    enabled: !!id,
  });
}

// A mutation rebuilds the derived index server-side, so after any write we
// invalidate the list, the facets, and the affected detail to read-after-write.
function useInvalidateAfterWrite() {
  const qc = useQueryClient();
  return (id: string) => {
    qc.invalidateQueries({ queryKey: ["parts"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    qc.invalidateQueries({ queryKey: ["part", id] });
  };
}

export function useEditField() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (vars: { id: string; field: string; value: unknown }) =>
      api.editField(vars.id, vars.field, vars.value),
    onSuccess: (_data, vars) => invalidate(vars.id),
  });
}

export function useMoveCategory() {
  const invalidate = useInvalidateAfterWrite();
  return useMutation({
    mutationFn: (vars: { id: string; category: string }) =>
      api.moveCategory(vars.id, vars.category),
    onSuccess: (_data, vars) => invalidate(vars.id),
  });
}

export function useDeletePart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deletePart(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
      qc.removeQueries({ queryKey: ["part", id] });
    },
  });
}

// Enrichment is a lookup, not a write: it returns sourced candidates without
// touching the record, so there is nothing to invalidate here. Applying a
// candidate goes through useEditField, which does the read-after-write invalidation.
export function useEnrichPart() {
  return useMutation({
    mutationFn: (vars: { mpn: string; category?: string; want?: string[] }) =>
      api.enrichPart(vars.mpn, vars.category, vars.want),
  });
}
