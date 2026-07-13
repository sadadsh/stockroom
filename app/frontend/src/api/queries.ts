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

// Committing a staging candidate adds a real part, so it invalidates the list and
// facets (the new part must appear in Components). A gate failure rejects with an
// ApiError carrying `missing`; the caller surfaces that, so no invalidation runs.
export function useIngestCommit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (candidate: import("./types").StagingCandidate) =>
      api.ingestCommit(candidate),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    },
  });
}

// --- Settings page server state (M6g) ---

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { mouser_api_key?: string }) => api.updateSettings(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useProfiles() {
  return useQuery({ queryKey: ["profiles"], queryFn: () => api.listProfiles() });
}

export function useSystemInfo() {
  return useQuery({ queryKey: ["system"], queryFn: () => api.getSystemInfo() });
}

export function useCreateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { name: string; archive?: boolean }) =>
      api.createProfile(vars.name, vars.archive),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });
}

// Activating a profile swaps the whole library, so the parts list, facets, and
// the system readout (active_profile, part_count) all change under it. Refresh
// them alongside the profile list rather than leaving a stale Components view.
export function useActivateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.activateProfile(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      qc.invalidateQueries({ queryKey: ["system"] });
      qc.invalidateQueries({ queryKey: ["parts"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    },
  });
}

export function useDeleteProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteProfile(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profiles"] }),
  });
}

export function useSyncStatus() {
  return useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.getSyncStatus(),
  });
}

// A sync that pulled new commits changed the library on disk, so the parts view
// must refresh; a no-op/up-to-date sync leaves the parts view untouched (only the
// sync status changes). Either way the status readout is refreshed.
export function useDoSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.doSync(),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["sync-status"] });
      if (result.pulled) {
        qc.invalidateQueries({ queryKey: ["parts"] });
        qc.invalidateQueries({ queryKey: ["facets"] });
      }
    },
  });
}

export function useUpdateCheck() {
  return useQuery({
    queryKey: ["update-check"],
    queryFn: () => api.checkUpdate(),
  });
}

export function useApplyUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.applyUpdate(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["update-check"] }),
  });
}
